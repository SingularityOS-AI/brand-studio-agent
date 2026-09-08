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
        "brand_journey",
        "etapa",
        "charco",
        "credibilidad",
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


def _redact_section_content_with_llm(
    section: Section,
    all_citations: Dict[str, str]
) -> Dict[str, str]:
    """
    Redact a section's content using an LLM.

    CRITICAL: The LLM only sees the section content and its own citation.
    It NEVER sees the raw transcript or external context.

    The prompt instructs the LLM to:
    1. Redact with strategic voice (not like a form)
    2. Use ONLY facts in the section content
    3. Keep core assertions accurate
    4. Temperature = 0 for determinism

    Returns:
        Dict with redacted text fields for that section

    NOTE: This is a stub implementation. In production, you would:
    - Use OpenAI API (gpt-4o-mini, temperature=0, seed if supported)
    - Implement proper prompt engineering for strategic redaction
    - Handle API errors gracefully
    """
    # For now, return raw content as-is
    # In a real implementation, this would call an LLM

    content = section.content

    if section.id == "charco":
        return {
            "content": content.get("pain_point", ""),
            "citation": all_citations["charco"]
        }

    elif section.id == "etapa":
        # Extract knowledge level (experto vs estudiante)
        stage_name = content.get("stage", "")
        if "seed" in stage_name.lower():
            knowledge_level = "ESTUDIANTE"
            implication = "Estás al principio. Tu perspectiva única es más valiosa que tu experiencia."
        else:
            knowledge_level = "EXPERTO"
            implication = "Ya has recorrido el camino. Tu experiencia es tu ventaja competitiva."

        return {
            "knowledge_level": knowledge_level,
            "implication": implication,
            "citation": all_citations["etapa"]
        }

    elif section.id == "contrarian":
        return {
            "common_belief": content.get("common_belief", ""),
            "contrarian_position": content.get("contrarian_position", ""),
            "citation": all_citations["contrarian"]
        }

    elif section.id == "identidad":
        values = content.get("values", [])
        desired = content.get("associations", {}).get("desired", [])
        prohibited = content.get("associations", {}).get("prohibited", [])

        voice_text = f"Valores: {', '.join(values) if values else 'N/A'}"

        desired_html = "\\n".join(
            f'<li class="associations-desired">{item}</li>'
            for item in (desired if isinstance(desired, list) else [desired])
        )

        prohibited_html = "\\n".join(
            f'<li class="associations-prohibited">{item}</li>'
            for item in (prohibited if isinstance(prohibited, list) else [prohibited])
        )

        return {
            "voice": voice_text,
            "associations_desired": desired_html,
            "associations_prohibited": prohibited_html,
            "citation": all_citations["identidad"]
        }

    elif section.id == "oferta":
        components = content.get("offer_components", [])
        guarantee = content.get("guarantee", "")

        equation_text = f"{', '.join(components) if components else 'Tu oferta'}"
        if guarantee:
            equation_text += f" + {guarantee}"

        return {
            "equation": equation_text,
            "citation": all_citations["oferta"]
        }

    elif section.id == "lead_magnet":
        return {
            "text": content.get("what_they_get", ""),
            "citation": all_citations["lead_magnet"]
        }

    elif section.id == "brand_journey":
        stages = [
            content.get(k, "")
            for k in [
                "stage_1_unaware",
                "stage_2_problem_aware",
                "stage_3_solution_aware",
                "stage_4_product_aware",
                "stage_5_most_aware"
            ]
        ]

        stages_text = " → ".join(filter(None, stages))

        return {
            "stages": stages_text,
            "citation": all_citations["brand_journey"]
        }

    elif section.id == "credibilidad":
        # This section is used for evidence, not as a main section in the document
        return {"citation": all_citations["credibilidad"]}

    elif section.id == "asociaciones":
        # This section is integrated into the identity section
        return {"citation": all_citations["asociaciones"]}

    else:
        return {"citation": all_citations.get(section.id, "")}


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
    """
    brain_dict = brain.to_dict()
    brain_json = json.dumps(brain_dict, sort_keys=True)
    return hashlib.sha256(brain_json.encode()).hexdigest()


def _check_cache(brain: BrandBrain) -> Optional[str]:
    """
    Check if a cached HTML exists for this brain.

    The cache is stored in the brand_brains table as soul_html.
    We also store a brain_hash to invalidate the cache.

    Args:
        brain: BrandBrain object

    Returns:
        Cached HTML string if valid cache hit, None otherwise
    """
    # In a real implementation, this would query Supabase
    # For now, return None to always regenerate
    return None


def _save_cache(brain: BrandBrain, html: str) -> bool:
    """
    Save the generated HTML to cache.

    Stores in brand_brains table:
    - soul_html: the generated HTML
    - brain_hash: hash of brain state for invalidation
    - soul_generated_at: timestamp

    Args:
        brain: BrandBrain object
        html: Generated HTML document

    Returns:
        True if saved successfully, False otherwise
    """
    # In a real implementation, this would update Supabase
    # brand_brains table with soul_html column
    return True


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
    cached_html = _check_cache(brain)
    if cached_html:
        # Validate cached HTML citations (defense in depth)
        is_valid, invented = validate_citations_in_html(cached_html, brain)
        if not is_valid:
            # Cache corrupted! Fall through to regeneration
            print(f"[WARN] Cache corrupted - invented citations: {invented}")
        else:
            return cached_html, "cached"

    # 4. Generate new HTML
    # 4a. Extract etapa context
    etapa_id = detect_etapa_from_brand_brain(brain)
    if not etapa_id:
        etapa_id = "invisible"  # Default fallback
    etapa_context = get_etapa_context(etapa_id)

    # 4b. Redact each section with LLM
    all_citations = _extract_literal_citations(brain)

    redacted = {}
    for section in brain.sections:
        redacted[section.id] = _redact_section_content_with_llm(section, all_citations)

    # 4c. Build HTML from template
    try:
        html = build_soul_html(
            etapa_context=etapa_context,
            charco_content=redacted["charco"]["content"],
            charco_citation=redacted["charco"]["citation"],
            knowledge_level=redacted["etapa"]["knowledge_level"],
            knowledge_implication=redacted["etapa"]["implication"],
            knowledge_citation=redacted["etapa"]["citation"],
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
    _save_cache(brain, html)

    return html, "generated"
