"""
Brand Brain Extraction Logic

Validates schema, extracts content, and converts to BrandBrain model.
Called by `/api/brain/extract` endpoint.

Follows spec_cerebro_9_nodos.md (CEO-signed 2026-09-09) as source of truth.
"""

from typing import Dict, List, Optional, Any
import re

from app.tools.brand_brain.models import BrandBrain, Section, CitationInvariantError
from app.tools.brand_brain.questions import (
    get_section_by_id,
    all_required_fields_gathered,
    get_section_order
)
from app.tools.brand_brain.store import save_brand_brain, get_brand_brain


class ExtractionError(Exception):
    """Raised when extraction validation fails"""
    pass


def validate_extraction_input(transcript: str, turn_count: int = None) -> None:
    """
    Validate input parameters for extraction.

    Raises:
        ExtractionError: If validation fails
    """
    if not transcript or len(transcript.strip()) < 100:
        raise ExtractionError("transcript must be at least 100 characters")

    # turn_count validation removed per CEO decision: no turn limit
    # Sections are validated by content and citation, not turn count


def normalize_citation_for_matching(citation: str) -> str:
    """
    Normalize citation for ASR-robust matching.

    Normalization: lowercase, remove punctuation, collapse spaces.

    Uses substring match per spec: agent provides exact citation, we verify
    it appears literally in transcript after normalization.

    Args:
        citation: The citation text from the agent

    Returns:
        Normalized citation string for matching
    """
    # Lowercase
    normalized = citation.lower()

    # Remove punctuation (keep letters, numbers, spaces)
    normalized = re.sub(r'[^\w\s]', ' ', normalized)

    # Collapse multiple spaces to single
    normalized = re.sub(r'\s+', ' ', normalized)

    # Strip leading/trailing spaces
    return normalized.strip()


def normalized_citation_matches_transcript(citation: str, transcript: str) -> bool:
    """
    Check if normalized citation appears in normalized transcript.

    Uses substring match (not exact match) to be lenient with ASR variations.
    If the normalized citation text is a substring of the normalized transcript,
    we consider it a match.

    Args:
        citation: citation text from agent
        transcript: full conversation transcript

    Returns:
        True if citation appears in transcript after normalization
    """
    norm_citation = normalize_citation_for_matching(citation)
    norm_transcript = normalize_citation_for_matching(transcript)

    # ponytail: match normalizado por substring; subir a fuzzy si el ASR lo exige
    return norm_citation in norm_transcript


def extract_citation_from_transcript(section_data: Dict, transcript: str) -> Optional[str]:
    """
    Extract citation from transcript.

    DISCARDED: Previous implementation used 3-char prefix matching of Spanish phrases,
    which produced garbage like ["el ", "la ", "las", "qué"].

    New implementation: use agent-provided citation directly with normalized
    substring matching.

    Args:
        section_data: Section data containing citation_text
        transcript: Full conversation transcript

    Returns:
        citation_text if valid and found in transcript, None otherwise
    """
    citation_text = section_data.get("citation_text")
    if not citation_text:
        return None

    # Verify citation appears in transcript
    if not normalized_citation_matches_transcript(citation_text, transcript):
        return None

    return citation_text


def normalize_section_content(section_id: str,
                               content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize and validate section content per spec_cerebro_9_nodos.md.

    Handles per-node field mappings from agent output to canonical schema.

    Args:
        section_id: Section ID (one of the 9 nodes)
        content: Raw content from extraction agent

    Returns:
        Normalized content dict for storage
    """
    normalized = {}

    # Per-node normalization blocks
    if section_id == "diagnostico":
        normalized["etapa"] = content.get("etapa")
        normalized["nivel_ramiro"] = content.get("nivel_ramiro")
        normalized["sintoma_diagnostico"] = content.get("sintoma_diagnostico")
        normalized["habilidad_a_desbloquear"] = content.get("habilidad_a_desbloquear")
        normalized["prohibicion"] = content.get("prohibicion")
        normalized["postura"] = content.get("postura")
        normalized["justificacion_postura"] = content.get("justificacion_postura")

    elif section_id == "brand_journey":
        normalized["resultado_deseado"] = content.get("resultado_deseado")
        normalized["de_que_ser_conocido"] = content.get("de_que_ser_conocido")
        normalized["que_hacer"] = content.get("que_hacer")
        normalized["que_aprender"] = content.get("que_aprender")

    elif section_id == "charco":
        normalized["problema"] = content.get("problema")
        normalized["nivel"] = content.get("nivel")
        normalized["logro_que_lo_respalda"] = content.get("logro_que_lo_respalda")
        normalized["costo_de_no_resolverlo"] = content.get("costo_de_no_resolverlo")
        normalized["intentos_fallidos"] = content.get("intentos_fallidos")

    elif section_id == "icp":
        normalized["quien_decide"] = content.get("quien_decide")
        normalized["tamano_empresa"] = content.get("tamano_empresa")
        normalized["disparador_de_urgencia"] = content.get("disparador_de_urgencia")
        normalized["poder_adquisitivo"] = content.get("poder_adquisitivo")
        normalized["comite_de_compra"] = content.get("comite_de_compra")
        normalized["a_quien_le_rinde_cuentas"] = content.get("a_quien_le_rinde_cuentas")

    elif section_id == "contrarian":
        normalized["creencia_comun"] = content.get("creencia_comun")
        normalized["postura_opuesta"] = content.get("postura_opuesta")
        normalized["prueba"] = content.get("prueba")
        normalized["por_que_no_es_provocacion"] = content.get("por_que_no_es_provocacion")

    elif section_id == "asociaciones":
        normalized["deseadas"] = content.get("deseadas")
        normalized["prohibidas"] = content.get("prohibidas")

    elif section_id == "identidad":
        normalized["voz"] = content.get("voz")
        normalized["colores"] = content.get("colores")
        normalized["tipografias"] = content.get("tipografias")
        normalized["narrativa_de_origen"] = content.get("narrativa_de_origen")

    elif section_id == "oferta":
        normalized["resultado_sonado"] = content.get("resultado_sonado")
        normalized["probabilidad_percibida"] = content.get("probabilidad_percibida")
        normalized["retraso"] = content.get("retraso")
        normalized["esfuerzo"] = content.get("esfuerzo")
        normalized["componentes"] = content.get("componentes")
        normalized["garantia"] = content.get("garantia")

    elif section_id == "lead_magnet":
        normalized["tipo"] = content.get("tipo")
        normalized["problema_A"] = content.get("problema_A")
        normalized["problema_B_que_revela"] = content.get("problema_B_que_revela")
        normalized["formato"] = content.get("formato")
        normalized["captura"] = content.get("captura")

    else:
        # Unknown section - passthrough
        normalized = content.copy()

    return normalized


def convert_to_sections(transcript: str,
                        tool_result: Dict[str, Any]) -> List[Section]:
    """
    Convert extraction tool result to Section objects.

    Validates citations (must appear in transcript) and checks required fields.

    Args:
        transcript: Full conversation transcript
        tool_result: Dict from extraction agent with section data

    Returns:
        List of Section objects

    Raises:
        ExtractionError: If section structure is invalid
    """
    sections = []

    # Mapping from old IDs to new IDs is NO LONGER NEEDED - direct ID-to-ID
    # Agent now returns correct IDs per spec

    # Extract citations map if present
    citations_map = tool_result.get("citations", {})

    # Extract section data
    sections_data = tool_result.get("sections", [])

    for section_data in sections_data:
        section_id = section_data.get("id")
        if not section_id:
            continue

        section_def = get_section_by_id(section_id)
        if not section_def:
            # Skip unknown sections
            print(f"[WARNING] Unknown section ID: {section_id}")
            continue

        # Extract citation
        citation_text = section_data.get("citation_text")
        citation_source = section_data.get("citation_source", "usuario")

        if not citation_text:
            print(f"[WARNING] Section {section_id} missing citation_text, skipping")
            continue

        # Verify citation appears in transcript
        if not normalized_citation_matches_transcript(citation_text, transcript):
            print(f"[WARNING] Section {section_id} citation not found in transcript, skipping")
            continue

        # Extract content
        raw_content = section_data.get("content", {})
        content = normalize_section_content(section_id, raw_content)

        # Derive status from confirmed flag (FIX #3)
        confirmed = section_data.get("confirmed", False)
        status = "confirmado" if confirmed else "propuesto"

        try:
            section = Section(
                id=section_id,
                label=section_def.title,
                status=status,
                content=content,
                citation_text=citation_text,
                citation_source=citation_source
            )
            sections.append(section)
        except CitationInvariantError as e:
            print(f"[WARNING] Section {section_id} failed citation invariant: {e}, skipping")
            continue

    return sections


def extract_and_persist(session_token: str,
                       transcript: str,
                       turn_count: Optional[int] = None,
                       tool_result: Dict[str, Any] = None) -> BrandBrain:
    """
    Extract brand brain sections from transcript and persist to database.

    Args:
        session_token: User session token
        transcript: Full conversation transcript
        turn_count: Number of conversation turns (optional, unused per CEO)
        tool_result: Extraction agent output dict

    Returns:
        Updated BrandBrain object

    Raises:
        ExtractionError: If extraction or persistence fails
    """
    validate_extraction_input(transcript, turn_count)

    if not tool_result:
        tool_result = {}

    # Get existing brain or create new
    existing_brain = get_brand_brain(session_token)
    if existing_brain:
        brain = existing_brain
    else:
        brain = BrandBrain(sections=[])

    # Extract new sections from tool_result
    new_sections = convert_to_sections(transcript, tool_result)

    # Merge with existing sections (overwrite by ID)
    existing_section_ids = {s.id for s in brain.sections}
    for new_section in new_sections:
        if new_section.id in existing_section_ids:
            # Replace existing section
            brain.sections = [s for s in brain.sections if s.id != new_section.id]
        brain.sections.append(new_section)

    # Determine which sections are still missing (not meeting TERMINADO criteria)
    # TERMINADO = (a) all required fields filled, (b) citation verified, (c) confirmed=true
    all_section_ids = get_section_order()
    missing_sections = []

    for section_id in all_section_ids:
        section = next((s for s in brain.sections if s.id == section_id), None)

        if not section:
            missing_sections.append(section_id)
            continue

        # Check required fields
        if not all_required_fields_gathered(section_id, section.content):
            missing_sections.append(section_id)
            continue

        # Check confirmed status
        if section.status != "confirmado":
            missing_sections.append(section_id)
            continue

    # Save to database
    save_brand_brain(session_token, brain)

    # Store missing_sections as metadata for agent to use in next prompt
    if not hasattr(brain, '_metadata'):
        brain._metadata = {}
    brain._metadata['missing_sections'] = missing_sections

    return brain
