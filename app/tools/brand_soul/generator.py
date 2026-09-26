"""
Brand Soul Generator

Generates the Brand Soul document from a BrandBrain with:

1. LLM ON A LEASH:
   - Only sees the 9 sections and their literal citations
   - Strictly forbidden from introducing new facts
   - Temperature = 0 for deterministic output
   - Fixed seed if provider supports it

2. CITATION VALIDATION:
   - Every citation in the generated HTML must exist literally in the brain
   - If any citation is invented, validation fails and document is NOT shown
   - Citations are taken from the brain verbatim, not reworded by LLM

3. CACHE LAYER:
   - Generated HTML is cached in Supabase (soul_html column)
   - Same brain produces same HTML every time (determinism)
   - Instant reopening of previously generated documents

Core design principle:
"The brand_brain is the ONLY source of truth. The LLM only redacts."
"""

import hashlib
import json

from app.config import settings
from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.store import get_brand_brain
from app.tools.brand_soul.template import build_soul_html


class SoulGenerationError(Exception):
    """Raised when Brand Soul cannot be generated"""


class CitationValidationError(SoulGenerationError):
    """Raised when generated HTML contains invented citations"""


class IncompleteBrainError(SoulGenerationError):
    """Raised when brain doesn't have all 9 confirmed sections"""


def _check_all_sections_confirmed(brain: BrandBrain) -> tuple[bool, list[str]]:
    """
    Check if all 9 sections exist and are confirmed.

    Returns:
        Tuple of (is_complete, list_of_missing_sections)
    """
    required_section_ids = [
        "diagnostico",
        "brand_journey",
        "charco",
        "icp",
        "contrarian",
        "asociaciones",
        "identidad",
        "oferta",
        "lead_magnet"
    ]

    missing_sections = []

    for section_id in required_section_ids:
        section = brain.get_section(section_id)
        if not section:
            missing_sections.append(f"{section_id} (no existe)")
        elif section.status != "confirmado":
            missing_sections.append(f"{section_id} (estado: {section.status})")

    is_complete = len(missing_sections) == 0
    return is_complete, missing_sections


def _extract_literal_citations(brain: BrandBrain) -> dict[str, str]:
    """
    Extract all literal citation texts from the brand_brain.

    Returns:
        Dict mapping section_id -> literal citation text
    """
    citations = {}
    for section in brain.sections:
        citations[section.id] = section.citation_text
    return citations


def _get_vertex_ai_client():
    """
    Get the Vertex AI client for Gemini models.

    Returns:
        Vertex AI client or None if not configured/test mode

    Raises:
        RuntimeError: If Vertex AI is not configured in production mode
    """
    if not settings.vertex_ai_project_id:
        raise RuntimeError(
            "VERTEX_AI_PROJECT_ID is not configured. "
            "Set it in .env file or environment variable before starting the server."
        )

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        # Initialize Vertex AI
        vertexai.init(
            project=settings.vertex_ai_project_id,
            location=settings.vertex_ai_location
        )

        return GenerativeModel(settings.vertex_ai_model)

    except ImportError:
        raise RuntimeError(
            "google-cloud-aiplatform is not installed. "
            "Install it with: pip install google-cloud-aiplatform"
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize Vertex AI client: {e}. "
            "Ensure VERTEX_AI_PROJECT_ID and VERTEX_AI_LOCATION are correct."
        )


def _estimate_tokens(text: str) -> int:
    """
    Estimate token count for a text string.
    Rough approximation: 1 token ≈ 4 characters for English/Spanish.

    Args:
        text: The text to estimate tokens for

    Returns:
        Estimated token count (conservative estimate)
    """
    # Conservative estimate: ~4 characters per token for mixed English/Spanish
    return max(1, len(text) // 4)


def _redact_section_content_with_llm(
    section: Section,
    all_citations: dict[str, str]
) -> tuple[str, int]:
    """
    Redact a section's content using Gemini 2.5 Flash-Lite via Vertex AI.

    CRITICAL: The LLM only sees the section content and its own citation.
    It NEVER sees the raw transcript or external context.
    """
    content = section.content
    citation = all_citations.get(section.id, "")

    # Format the dictionary content into a plain string to avoid JSON inputs
    content_str = " ".join([f"{str(k).replace('_', ' ').capitalize()}: {v}" for k, v in content.items() if v])

    instruction = (
        f"Consolidate this information about the '{section.id}' section into a compelling narrative. "
        "Write 2-4 paragraphs of prose (150-350 words). "
        "OUTPUT IN ENGLISH. "
        "DO NOT output JSON, key-value pairs, bullet dumps, or use snake_case keys or curly braces. "
        "Use a strategic, professional voice."
    )

    redacted_text = _call_llm_for_redaction(
        section_text=content_str,
        citation_text=citation,
        instruction=instruction
    )

    return redacted_text, _estimate_tokens(content_str) + _estimate_tokens(redacted_text) + 500

def _call_llm_for_redaction(
    section_text: str,
    citation_text: str,
    instruction: str
) -> str:
    """
    Call Gemini 2.5 Flash-Lite to redact section content with strategic voice.

    Args:
        section_text: The original section content to redact
        citation_text: The literal citation (for context, NOT to paraphrase)
        instruction: Specific instruction for this section type

    Returns:
        Redacted text string

    Raises:
        SoulGenerationError: If LLM call fails
    """
    model = _get_vertex_ai_client()

    # In test mode, return the original text
    if model is None:
        return section_text

    # Build the strict prompt
    prompt = f"""Eres un estratega de marcas senior. Tu tarea es REDACTAR (no reescribir, no inventar) el siguiente texto con voz profesional y estratégica.

IMPORTANTE - REGLAS INVIOLABLES:
1. NO inventes datos, hechos, ni detalles que NO estén en el texto original
2. NO añadas ejemplos, estadísticas ni testimonios que no estén en el original
3. NO cambies el significado fundamental de ninguna afirmación
4. Usa un tono profesional y estratégico, como lo haría un consultor de marca
5. REDACTA CON EXTENSIÓN Y PROFUNDIDAD: escribe 2-3 párrafos bien desarrollados, elaborando sobre los puntos clave del contenido original
6. La cita vuelve del contexto, pero NO la parafrasees ni la menciones en la redacción

Texto a redactar:
{section_text}

Instrucción específica:
{instruction}

Devuelve SOLO el texto redactado (2-3 párrafos extensos). Sin explicaciones, sin intro, sin formato markdown."""

    try:
        # Generate with temperature=0 for determinism
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 500,
                "candidate_count": 1
            }
        )

        if not response.text:
            raise SoulGenerationError("LLM returned empty response")

        # Clean up the response - remove any markdown or extra whitespace
        redacted = response.text.strip()

        # Remove markdown code blocks if present
        if redacted.startswith("```"):
            lines = redacted.split("\n")
            # Skip first line (```...) and last line (```)
            if len(lines) > 2:
                redacted = "\n".join(lines[1:-1])
            else:
                # Malformed, just take everything after the first line
                redacted = "\n".join(lines[1:])

        return redacted.strip() or section_text

    except Exception as e:
        # If LLM fails, return original text (graceful degradation)
        print(f"[WARN] LLM redaction failed for section: {e}. Using original text.")
        return section_text


def validate_citations_in_html(html: str, brain: BrandBrain) -> tuple[bool, list[str]]:
    """
    Validate that every citation in the HTML exists literally in the brain.

    This is the CRITICAL validation step that prevents the LLM from
    inventing citations. If ANY citation in the HTML doesn't match
    a literal citation from the brain, validation FAILS.

    Args:
        html: The generated HTML document
        brain: The BrandBrain object

    Returns:
        Tuple of (is_valid, list_of_invented_citations)

    Note:
        This function searches for citations within <div class="citation"> tags
        and checks if the literal text (excluding quotes) exists in the brain's
        citation_text fields.
    """
    import html as _html
    import re

    # Se revisa TODO texto entrecomillado del documento, no solo el que esta
    # dentro de <div class="citation">.
    #
    # Por que: mirar solo ese contenedor deja pasar exactamente el caso mas
    # probable. Un LLM al que se le pide que "escriba como estratega" teje las
    # citas dentro de la prosa antes que ponerlas en el div designado:
    #
    #   <p>Como tu mismo dijiste, "llevo quince anos en banca", y eso...</p>
    #
    # Medido: esa frase inventada pasaba la validacion anterior sin tocarla.
    # Y este documento circula sin nosotros: una cita inventada aqui no es un
    # bug, es la credibilidad del fundador y la nuestra.

    # 1. Quitar etiquetas para trabajar sobre el texto visible, y deshacer
    #    entidades (&quot; volveria invisible una cita para el regex).
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = _html.unescape(texto)

    # 2. Todo lo entrecomillado: comillas rectas, tipograficas y angulares.
    entrecomillado = re.findall(r'"([^"]{4,})"|“([^”]{4,})”|«([^»]{4,})»', texto)
    encontradas = [next(g for g in grupo if g) for grupo in entrecomillado]

    def _norm(s: str) -> str:
        """Compara por contenido, no por espaciado ni puntuacion de borde."""
        return re.sub(r"\s+", " ", s).strip().strip(".,;:!?").lower()

    permitidas = {_norm(s.citation_text) for s in brain.sections if s.citation_text}

    invented_citations = []
    for cita in encontradas:
        if _norm(cita) not in permitidas:
            invented_citations.append(cita)

    is_valid = len(invented_citations) == 0
    return is_valid, invented_citations


def _compute_brain_hash(brain: BrandBrain) -> str:
    """
    Compute a hash of the brain to check if it has changed.

    Used for cache invalidation.

    Args:
        brain: BrandBrain object

    Returns:
        SHA256 hash of the brain's serialized state

    NOTE: Only hashes the actual content (sections and formato), NOT
    created_at/updated_at which change automatically on every DB update.
    """
    hashable = {
        "sections": [
            {"id": s.id, "content": s.content, "citation_text": s.citation_text,
             "citation_source": s.citation_source, "status": s.status}
            for s in brain.sections
        ],
        "formato": brain.formato,
    }
    brain_json = json.dumps(hashable, sort_keys=True)
    return hashlib.sha256(brain_json.encode()).hexdigest()


def _check_cache(brain: BrandBrain, session_token: str) -> str | None:
    """
    Check if a cached HTML exists for this brain.

    The cache is stored in the brand_brains table as soul_html.
    We also store a brain_hash to invalidate the cache.

    Args:
        brain: BrandBrain object
        session_token: Session token to query cache

    Returns:
        Cached HTML string if valid cache hit, None otherwise
    """
    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return None

        # Query the brand_brains table
        result = client.table("brand_brains").select(
            "soul_html",
            "brain_hash"
        ).eq("session_token", session_token).execute()

        if not result.data:
            return None

        row = result.data[0]

        # Check if brain_hash matches (cache invalidation)
        current_hash = _compute_brain_hash(brain)
        cached_hash = row.get("brain_hash")

        if not cached_hash or cached_hash != current_hash:
            # Brain changed, cache is invalid
            return None

        # Return cached HTML
        return row.get("soul_html")

    except Exception as e:
        print(f"[WARN] Failed to check cache: {e}")
        return None


def _save_cache(brain: BrandBrain, html: str, session_token: str) -> bool:
    """
    Save the generated HTML to cache.

    Stores in brand_brains table:
    - soul_html: the generated HTML
    - brain_hash: hash of brain state for invalidation
    - soul_generated_at: timestamp

    Args:
        brain: BrandBrain object
        html: Generated HTML document
        session_token: Session token to update cache

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return False

        # Compute brain hash for cache invalidation
        brain_hash = _compute_brain_hash(brain)

        # Update the brand_brains table
        response = client.table("brand_brains").update({
            "soul_html": html,
            "brain_hash": brain_hash,
            "soul_generated_at": "now()"
        }).eq("session_token", session_token).execute()

        return len(response.data) > 0

    except Exception as e:
        print(f"[WARN] Failed to save cache: {e}")
        return False


def generate_brand_soul(session_token: str) -> tuple[str, str]:
    """
    Generate the Brand Soul document for the given session.

    This is the MAIN function that orchestrates the entire process:

    1. Validate brain has all 9 confirmed sections
    2. Check cache for existing HTML
    3. If cache miss, generate new HTML:
       a. Redact each section with LLM (on a leash)
       b. Build HTML from template
       c. Validate all citations exist literally in brain
    4. Save to cache
    5. Return HTML

    Args:
        session_token: The session token

    Returns:
        Tuple of (html_document, cache_status)
        cache_status is "cached" or "generated"

    Raises:
        IncompleteBrainError: If brain is missing sections
        CitationValidationError: If LLM invented citations
        SoulGenerationError: For other generation errors
    """
    # 1. Load brand brain
    brain = get_brand_brain(session_token)
    if not brain:
        raise SoulGenerationError("No brand brain found for this session")

    # 2. Validate all sections confirmed
    is_complete, missing_sections = _check_all_sections_confirmed(brain)
    if not is_complete:
        missing_text = ", ".join(missing_sections)
        raise IncompleteBrainError(f"Faltan secciones: {missing_text}")

    # 3. Check cache
    cached_html = _check_cache(brain, session_token)
    if cached_html:
        # Validate cached HTML citations (defense in depth)
        is_valid, invented = validate_citations_in_html(cached_html, brain)
        if not is_valid:
            # Cache corrupted! Fall through to regeneration
            print(f"[WARN] Cache corrupted - invented citations: {invented}")
        else:
            return cached_html, "cached"

    # Credit deduction for this generation happens once, in app/main.py's
    # /soul/generate endpoint (20 credits), before this function is called.
    # Do not deduct here too.

    # 4. Generate new HTML
    # 4b. Redact each section with LLM and track tokens
    all_citations = _extract_literal_citations(brain)

    redacted_sections = {}
    total_tokens = 0
    full_context = ""
    for section in brain.sections:
        redacted_text, token_count = _redact_section_content_with_llm(section, all_citations)
        redacted_sections[section.id] = redacted_text
        total_tokens += token_count
        full_context += f"\n\n--- {section.id} ---\n{redacted_text}"

    summary = _call_llm_for_redaction(
        section_text=full_context,
        citation_text="",
        instruction=(
            "Write an Executive Summary of this entire brand strategy. "
            "Write 1-2 paragraphs of prose (120-200 words). "
            "OUTPUT IN ENGLISH. DO NOT output JSON, key-value pairs, bullet dumps, or use snake_case keys or curly braces."
        )
    )
    total_tokens += _estimate_tokens(full_context) + _estimate_tokens(summary) + 200

    closing = _call_llm_for_redaction(
        section_text=full_context,
        citation_text="",
        instruction=(
            "Write a concluding section titled 'How Brandy will use this'. "
            "Explain how the AI agent Brandy will use this strategy to write scripts and create content. "
            "Write 1-2 paragraphs of prose. "
            "OUTPUT IN ENGLISH. DO NOT output JSON, key-value pairs, bullet dumps, or use snake_case keys or curly braces."
        )
    )
    total_tokens += _estimate_tokens(full_context) + _estimate_tokens(closing) + 200

    # 4c. Build HTML from template
    try:
        html = build_soul_html(
            summary=summary,
            closing=closing,
            redacted_sections=redacted_sections,
            citations=all_citations
        )
    except KeyError as e:
        raise SoulGenerationError(f"Missing section in redacted content: {e}")

    # 4d. Validate citations (CRITICAL!)
    is_valid, invented_citations = validate_citations_in_html(html, brain)
    if not is_valid:
        raise CitationValidationError(
            f"El documento contiene citas inventadas: {', '.join(invented_citations)}. "
            "El documento NO se mostrará."
        )

    # 5. Save to cache
    _save_cache(brain, html, session_token)

    return html, "generated"
