"""
Brand Brain Extraction Logic

Validates schema, extracts content, and converts to BrandBrain model.
Called by `/api/brain/extract` endpoint.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.questions import (
    get_section_by_id,
    all_required_fields_gathered,
    get_section_order
)
from app.tools.brand_brain.store import save_brand_brain, get_brand_brain


# Load JSON schema
_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "tools" / "brand_extraction_schema.json"

if _SCHEMA_PATH.exists():
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        _EXTRACTION_SCHEMA = json.load(f)
else:
    _EXTRACTION_SCHEMA = None
    print(f"[WARNING] brand_extraction_schema.json not found at {_SCHEMA_PATH}")


class ExtractionError(Exception):
    """Raised when extraction validation fails"""
    pass


def validate_extraction_input(transcript: str, turn_count: int) -> None:
    """
    Validate input parameters for extraction.

    Raises:
        ExtractionError: If validation fails
    """
    if not transcript or len(transcript.strip()) < 100:
        raise ExtractionError("transcript must be at least 100 characters")

    if turn_count < 6:
        raise ExtractionError(f"turn_count must be 6, got {turn_count}")


def parse_extraction_result(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse and validate the LLM extraction result.

    Args:
        raw_result: The raw output from the LLM/tool

    Returns:
        Parsed and validated extraction result

    Raises:
        ExtractionError: If schema validation fails
    """
    if not raw_result or not isinstance(raw_result, dict):
        raise ExtractionError("Extraction result must be a dict")

    # Check for validation status
    validation_status = raw_result.get("validation_status")
    if validation_status not in ["valid", "partial", "invalid"]:
        raise ExtractionError(f"Invalid validation_status: {validation_status}")

    # Check for brand_brain
    brand_brain = raw_result.get("brand_brain")
    if not brand_brain:
        raise ExtractionError("Missing brand_brain in extraction result")

    return raw_result


def convert_to_sections(session_token: str, extraction_result: Dict[str, Any], transcript: str) -> List[Section]:
    """
    Convert extraction result into Section objects.

    This is where we enforce citations and proper section structure.
    
    CORE INVARIANT: If a section has no valid citation from the transcript,
    it is NOT created. The agent will ask the user instead.

    Args:
        session_token: Session token for persistence
        extraction_result: Validated extraction result
        transcript: Full transcript for citation extraction

    Returns:
        List of Section objects

    Raises:
        ExtractionError: If section conversion fails
    """
    brand_brain_data = extraction_result.get("brand_brain", {})
    sections = []

    # Map extraction framework to our section IDs
    # The JSON schema uses different keys than our section IDs
    section_mapping = {
        "ralston_journey": "brand_journey",
        "segues_stage": "etapa",
        "pain_puddle": "charco",
        "credibility": "credibilidad",
        "contrarian_position": "contrarian",
        "mental_associations": "asociaciones",
        "brand_identity": "identidad",
        "irresistible_offer": "oferta",
        "lead_magnet": "lead_magnet"
    }

    # Process each section
    for framework_key, section_id in section_mapping.items():
        section_def = get_section_by_id(section_id)
        if not section_def:
            print(f"[WARNING] Unknown section_id: {section_id}")
            continue

        section_data = brand_brain_data.get(framework_key)
        if not section_data:
            # Skip missing sections for now (agent will ask)
            continue

        # Extract citation from transcript
        # THIS MAY RETURN None if no valid citation exists
        citation_text = extract_citation_from_transcript(section_id, transcript, section_data)
        
        # CORE INVARIANT: Skip section if no valid citation
        # We do NOT create sections with empty citations
        if not citation_text:
            print(f"[INFO] Skipping section '{section_id}' - no valid citation found in transcript")
            continue
        
        citation_source = "usuario"  # Default until we implement public analysis

        # Convert framework-specific format to our Section content format
        content = normalize_section_content(section_id, section_data)

        # Validate section content
        if not all_required_fields_gathered(section_id, content):
            # If validation fails, skip this section
            print(f"[INFO] Skipping section '{section_id}' - missing required fields")
            continue

        # Create section (will enforce citation invariant at construction)
        section = Section(
            id=section_id,
            label=section_def.label,
            status="propuesto",  # Initially proposed by agent
            content=content,
            citation_text=citation_text,
            citation_source=citation_source
        )

        sections.append(section)

    return sections


def extract_citation_from_transcript(section_id: str, transcript: str, section_data: Dict) -> Optional[str]:
    """
    Extract relevant citation text from transcript for a section.

    CORE INVARIANT: Returns None if no valid citation exists, NOT a placeholder.
    The caller must handle None by NOT creating the section.

    For now, this is a simplified implementation.
    In production, this would use NLP/agentic approach to find the most relevant quote.

    Args:
        section_id: The section ID
        transcript: Full conversation transcript
        section_data: Extracted section data

    Returns:
        Citation text (quote from user or analysis), or None if no valid citation exists
    """
    # Simple approach: find longest user utterance that mentions section-specific keywords
    from app.tools.brand_brain.questions import get_section_by_id

    section_def = get_section_by_id(section_id)
    if not section_def:
        return None

    # Get deducible requirements as search terms
    search_terms = [req.lower()[:3] for req in section_def.deducible_requirements]

    # Split transcript into utterances
    utterances = transcript.split("\n")

    best_citation = None
    best_match_count = 0

    for utterance in utterances:
        if not utterance.strip():
            continue

        match_count = sum(1 for term in search_terms if term in utterance.lower())

        if match_count > best_match_count and match_count >= 2:  # Require at least 2 keyword matches
            best_match_count = match_count
            best_citation = utterance.strip()

    # Return None if no valid citation found (NOT a placeholder)
    return best_citation if best_citation else None


def normalize_section_content(section_id: str, framework_data: Dict) -> Dict:
    """
    Convert framework-specific JSON schema format to our normalized Section.content format.

    Args:
        section_id: Our section ID
        framework_data: Data from JSON schema format

    Returns:
        Normalized content dict
    """
    if section_id == "brand_journey":
        # Map ralston_journey stages to our format
        return {
            "stage_1_unaware": framework_data.get("stage_1_unaware", ""),
            "stage_2_problem_aware": framework_data.get("stage_2_problem_aware", ""),
            "stage_3_solution_aware": framework_data.get("stage_3_solution_aware", ""),
            "stage_4_product_aware": framework_data.get("stage_4_product_aware", ""),
            "stage_5_most_aware": framework_data.get("stage_5_most_aware", ""),
            "current_stage": framework_data.get("current_stage", ""),
            "journey_narrative": framework_data.get("journey_narrative", "")
        }
    elif section_id == "etapa":
        return {
            "stage": framework_data.get("stage", ""),
            "revenue": framework_data.get("revenue", ""),
            "team_size": framework_data.get("team_size", ""),
            "primary_focus": framework_data.get("primary_focus", ""),
            "pain_points": framework_data.get("pain_points", [])
        }
    elif section_id == "charco":
        return {
            "pain_point": framework_data.get("pain_point", ""),
            "urgency": framework_data.get("urgency", ""),
            "consequences": framework_data.get("consequences", ""),
            "failed_attempts": framework_data.get("failed_attempts", "")
        }
    elif section_id == "credibilidad":
        return {
            "evidence": framework_data.get("evidence", ""),
            "sources": framework_data.get("sources", [])
        }
    elif section_id == "contrarian":
        return {
            "common_belief": framework_data.get("common_belief", ""),
            "contrarian_position": framework_data.get("contrarian_position", ""),
            "proof": framework_data.get("proof", ""),
            "differentiation": framework_data.get("differentiation", "")
        }
    elif section_id == "asociaciones":
        return {
            "associations": framework_data.get("associations", []),
            "market_position": framework_data.get("market_position", "")
        }
    elif section_id == "identidad":
        return {
            "values": framework_data.get("values", []),
            "principles": framework_data.get("principles", []),
            "voice": framework_data.get("voice", ""),
            "relationship_goal": framework_data.get("relationship_goal", "")
        }
    elif section_id == "oferta":
        return {
            "offer_components": framework_data.get("offer_components", []),
            "result_guaranteed": framework_data.get("result_guaranteed", ""),
            "delivery_format": framework_data.get("delivery_format", ""),
            "guarantee": framework_data.get("guarantee", "")
        }
    elif section_id == "lead_magnet":
        return {
            "format": framework_data.get("format", ""),
            "what_they_get": framework_data.get("what_they_get", ""),
            "value_delivered": framework_data.get("value_delivered", ""),
            "how_to_get_it": framework_data.get("how_to_get_it", "")
        }
    else:
        return framework_data


def extract_and_persist(
    session_token: str,
    transcript: str,
    turn_count: int,
    tool_result: Dict[str, Any]
) -> BrandBrain:
    """
    Main extraction workflow: validate → parse → convert → persist.

    Args:
        session_token: Session token
        transcript: Full conversation transcript
        turn_count: Number of turns
        tool_result: Raw result from extract_brand_brain tool

    Returns:
        Persisted BrandBrain object

    Raises:
        ExtractionError: If any validation fails
    """
    # 1. Validate inputs
    validate_extraction_input(transcript, turn_count)

    # 2. Parse tool result
    extraction_result = parse_extraction_result(tool_result)

    # 3. Convert to sections with citations
    sections = convert_to_sections(session_token, extraction_result, transcript)

    # 4. Get existing brand brain (if any) and merge
    existing_brain = get_brand_brain(session_token)
    if existing_brain:
        # Merge sections, keeping confirmed ones, replacing proposed ones
        for new_section in sections:
            existing_section = existing_brain.get_section(new_section.id)
            if existing_section and existing_section.status == "confirmado":
                # Keep confirmed section, don't overwrite
                continue
            existing_brain.upsert_section(
                section_id=new_section.id,
                label=new_section.label,
                content=new_section.content,
                citation_text=new_section.citation_text,
                citation_source=new_section.citation_source,
                status=new_section.status
            )
        brand_brain = existing_brain
    else:
        # Create new brand brain
        brand_brain = BrandBrain(sections=sections)

    # 5. Validate all sections (enforce citation invariant)
    # This is defense in depth - sections should already be valid due to construction
    validation = brand_brain.validate_all_sections()
    invalid_sections = [sid for sid, is_valid in validation.items() if not is_valid]

    if invalid_sections:
        raise ExtractionError(
            f"Sections violate invariant (missing citation_text): {', '.join(invalid_sections)}"
        )

    # 6. Persist to Supabase
    save_brand_brain(session_token, brand_brain)

    return brand_brain
