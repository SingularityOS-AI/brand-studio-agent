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

import os
from typing import Dict, Optional, List, Tuple
import hashlib
import json

from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.store import get_brand_brain, save_brand_brain
from app.tools.brand_soul.template import (
    build_soul_html,
    get_etapa_context,
    detect_etapa_from_brand_brain
)
from app.config import settings


class SoulGenerationError(Exception):
    """Raised when Brand Soul cannot be generated"""
    pass


class CitationValidationError(SoulGenerationError):
    """Raised when generated HTML contains invented citations"""
    pass


class IncompleteBrainError(SoulGenerationError):
    """Raised when brain doesn't have all 9 confirmed sections"""
    pass


def _check_all_sections_confirmed(brain: BrandBrain) -> Tuple[bool, List[str]]:
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


def _extract_literal_citations(brain: BrandBrain) -> Dict[str, str]:
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
    # In test mode, return None to allow mocking
    if os.getenv("TEST_MODE") == "true":
        return None

    if not settings.vertex_ai_project_id:
        raise RuntimeError(
            "VERTEX_AI_PROJECT_ID is not configured. "
            "Set it in .env file or environment variable before starting the server."
        )

    try:
        from vertexai.generative_models import GenerativeModel
        import vertexai

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
    all_citations: Dict[str, str]
) -> Tuple[Dict[str, str], int]:
    """
    Redact a section's content using Gemini 2.5 Flash-Lite via Vertex AI.

    CRITICAL: The LLM only sees the section content and its own citation.
    It NEVER sees the raw transcript or external context.

    The prompt instructs the LLM to:
    1. Redact with strategic voice (not like a form)
    2. Use ONLY facts in the section content
    3. Keep core assertions accurate
    4. Temperature = 0 for determinism
    5. NEVER invent data that isn't in the content

    Args:
        section: The Section object to redact
        all_citations: Dict mapping section_id to citation text

    Returns:
        Tuple of (dict with redacted text fields, estimated_token_count)

    Raises:
        SoulGenerationError: If LLM call fails

    NOTE: For sections that are pure data transformations (not prose),
    we return the structured data directly without LLM calls.
    """
    content = section.content

    # These sections don't need LLM redaction - they're structured data
    if section.id == "diagnostico":
        # Extract knowledge level (experto vs estudiante) from etapa field
        etapa_name = content.get("etapa", "")
        if "invisible" in etapa_name.lower() or "explorador" in etapa_name.lower():
            knowledge_level = "ESTUDIANTE"
            implication = "Estás al principio. Tu perspectiva única es más valiosa que tu experiencia."
        else:
            knowledge_level = "EXPERTO"
            implication = "Ya has recorrido el camino. Tu experiencia es tu ventaja competitiva."

        return {
            "knowledge_level": knowledge_level,
            "implication": implication,
            "citation": all_citations["diagnostico"]
        }, _estimate_tokens(implication) + 100  # Estimate

    elif section.id == "identidad":
        voz = content.get("voz", "")
        colores = content.get("colores", "")
        tipografias = content.get("tipografias", "")
        voice_text = f"Voz: {voz}. Colores: {colores}. Tipografías: {tipografias}"

        voz = content.get("voz", "")
        voice_text = f"Voz de marca: {voz}"

        return {
            "voice": voice_text,
            "associations_desired": "",  # Not used in this template
            "associations_prohibited": "",  # Not used in this template
            "citation": all_citations["identidad"]
        }, _estimate_tokens(voice_text) + 200

    elif section.id == "oferta":
        resultado = content.get("resultado_sonado", "")
        probabilidad = content.get("probabilidad_percibida", "")
        retraso = content.get("retraso", "")
        esfuerzo = content.get("esfuerzo", "")

        equation_parts = [resultado, probabilidad, retraso, esfuerzo]
        equation_text = " | ".join(filter(None, equation_parts))

        return {
            "equation": equation_text,
            "citation": all_citations["oferta"]
        }, _estimate_tokens(equation_text) + 50

    elif section.id == "lead_magnet":
        tipo = content.get("tipo", "")
        problema_a = content.get("problema_A", "")

        text = f"{tipo}: {problema_a}" if tipo or problema_a else ""

        return {
            "text": text,
            "citation": all_citations["lead_magnet"]
        }, _estimate_tokens(text) + 50

    elif section.id == "brand_journey":
        resultado = content.get("resultado_deseado", "")
        conocido_por = content.get("de_que_ser_conocido", "")
        que_hacer = content.get("que_hacer", "")
        que_aprender = content.get("que_aprender", "")

        stages = [resultado, conocido_por, que_hacer, que_aprender]
        stages_text = " → ".join(filter(None, stages))

        return {
            "stages": stages_text,
            "citation": all_citations["brand_journey"]
        }, _estimate_tokens(stages_text) + 100

    elif section.id == "credibilidad":
        # This section is used for evidence, not as a main section in the document
        return {"citation": all_citations["credibilidad"]}, 50

    elif section.id == "icp":
        # This section is used for persona info, integrated into other sections
        return {"citation": all_citations["icp"]}, 50

    # Sections that NEED LLM redaction (prose sections)
    elif section.id == "charco":
        problema = content.get("problema", "")
        if not problema:
            return {
                "content": "",
                "citation": all_citations["charco"]
            }, 50

        redacted_text = _call_llm_for_redaction(
            section_text=problema,
            citation_text=all_citations["charco"],
            instruction=(
                "Redacta el punto de dolor de forma estratégica, como lo haría un consultor de marca. "
                "Usa un tono directo y contundente. No inventes detalles que no estén en el texto original."
            )
        )

        return {
            "content": redacted_text,
            "citation": all_citations["charco"]
        }, _estimate_tokens(problema) + _estimate_tokens(redacted_text) + 500

    elif section.id == "contrarian":
        common_belief = content.get("creencia_comun", "")
        contrarian_position = content.get("postura_opuesta", "")

        if not common_belief or not contrarian_position:
            return {
                "common_belief": common_belief or "",
                "contrarian_position": contrarian_position or "",
                "citation": all_citations["contrarian"]
            }, 100

        redacted_common = _call_llm_for_redaction(
            section_text=common_belief,
            citation_text=all_citations["contrarian"],
            instruction=(
                "Redacta esta creencia común en una frase clara y breve. "
                "Mantén el significado exacto, solo mejora la redacción."
            )
        )

        redacted_contrarian = _call_llm_for_redaction(
            section_text=contrarian_position,
            citation_text=all_citations["contrarian"],
            instruction=(
                "Redacta esta posición contraria con fuerza estratégica. "
                "Haz que suene como una verdad contraintuitiva impactante. "
                "No añadas argumentos que no estén en el original."
            )
        )

        return {
            "common_belief": redacted_common,
            "contrarian_position": redacted_contrarian,
            "citation": all_citations["contrarian"]
        }, _estimate_tokens(common_belief) + _estimate_tokens(contrarian_position) + _estimate_tokens(redacted_common) + _estimate_tokens(redacted_contrarian) + 1000

    else:
        return {"citation": all_citations.get(section.id, "")}, 50


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


def validate_citations_in_html(html: str, brain: BrandBrain) -> Tuple[bool, List[str]]:
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
    import re
    import html as _html

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


def _check_cache(brain: BrandBrain, session_token: str) -> Optional[str]:
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
    # In test mode, return None to force regeneration
    if os.getenv("TEST_MODE") == "true":
        return None

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
    # In test mode, return True (cache not used in tests)
    if os.getenv("TEST_MODE") == "true":
        return True

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


def generate_brand_soul(session_token: str) -> Tuple[str, str]:
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
    # 4a. Extract etapa context
    etapa_id = detect_etapa_from_brand_brain(brain)
    if not etapa_id:
        etapa_id = "invisible"  # Default fallback
    etapa_context = get_etapa_context(etapa_id)

    # 4b. Redact each section with LLM and track tokens
    all_citations = _extract_literal_citations(brain)

    redacted = {}
    total_tokens = 0
    for section in brain.sections:
        redacted[section.id], token_count = _redact_section_content_with_llm(section, all_citations)
        total_tokens += token_count

    # 4c. Build HTML from template
    try:
        html = build_soul_html(
            etapa_context=etapa_context,
            charco_content=redacted["charco"]["content"],
            charco_citation=redacted["charco"]["citation"],
            knowledge_level=redacted["diagnostico"]["knowledge_level"],
            knowledge_implication=redacted["diagnostico"]["implication"],
            knowledge_citation=redacted["diagnostico"]["citation"],
            common_belief=redacted["contrarian"]["common_belief"],
            contrarian_position=redacted["contrarian"]["contrarian_position"],
            contrarian_citation=redacted["contrarian"]["citation"],
            identity_voice=redacted["identidad"]["voice"],
            identity_associations_desired=redacted["identidad"]["associations_desired"],
            identity_associations_prohibited=redacted["identidad"]["associations_prohibited"],
            identity_citation=redacted["identidad"]["citation"],
            offer_equation=redacted["oferta"]["equation"],
            offer_citation=redacted["oferta"]["citation"],
            lead_magnet_text=redacted["lead_magnet"]["text"],
            lead_magnet_citation=redacted["lead_magnet"]["citation"],
            brand_journey_stages=redacted["brand_journey"]["stages"],
            brand_journey_citation=redacted["brand_journey"]["citation"]
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
