"""
Brand Brain Tests

Tests for Pieza 2: Bloque A — el Cerebro de Marca.

Invariants tested:
1. No Section can be created without non-empty citation_text (enforced at construction)
2. Nine sections in canonical order
3. Voice correction changes content and status (propuesto → confirmado)
4. Recovery by session token works correctly

Testing pattern:
- Mock Supabase client and AssemblyAI SDK
- Do NOT mock internal classes (test the real logic)
- Tests 1-3 skip internal mocking, test 4 mocks Supabase client, tests 5-8 mock LLM
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.tools.brand_brain.models import Section, BrandBrain, CitationInvariantError
from app.tools.brand_brain.questions import (
    get_section_definitions,
    get_section_by_id,
    can_deduce_content,
    triage_knowledge_level,
    all_required_fields_gathered,
    get_section_order,
    LEVEL_EXPERTO,
    LEVEL_ESTUDIANTE
)
from app.tools.brand_brain.store import save_brand_brain, get_brand_brain
from app.tools.brand_brain.extractor import extract_and_persist, convert_to_sections, ExtractionError


# =============================================================================
# SECTION DEFINITIONS
# =============================================================================

def test_nine_sections_exist():
    """Nine specific sections with exact IDs"""
    sections = get_section_definitions()
    assert len(sections) == 9

    section_ids = [s.id for s in sections]
    expected_ids = [
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
    assert section_ids == expected_ids


def test_section_order():
    """Sections must be in canonical order"""
    order = get_section_order()
    assert len(order) == 9
    assert order[0] == "brand_journey"
    assert order[-1] == "lead_magnet"


def test_each_section_has_deducible_requirements():
    """Every section must have deducible requirements for agent triage"""
    sections = get_section_definitions()
    for section in sections:
        assert len(section.deducible_requirements) > 0, f"{section.id} has no deducible requirements"


# =============================================================================
# SECTION MODEL INVARIANT: citation_text required (NEW - enforced at construction)
# =============================================================================

def test_section_empty_citation_raises_error():
    """Section with empty citation_text raises CitationInvariantError"""
    with pytest.raises(CitationInvariantError) as exc_info:
        Section(
            id="test_section",
            label="Test Section",
            status="propuesto",
            content={"test": "data"},
            citation_text="",  # Empty!
            citation_source="usuario"
        )
    assert "citation_text cannot be empty" in str(exc_info.value)
    assert "test_section" in str(exc_info.value)


def test_section_whitespace_only_citation_raises_error():
    """Section with whitespace-only citation_text raises CitationInvariantError"""
    with pytest.raises(CitationInvariantError) as exc_info:
        Section(
            id="test_section",
            label="Test Section",
            status="propuesto",
            content={"test": "data"},
            citation_text="   ",  # Only spaces
            citation_source="usuario"
        )
    assert "citation_text cannot be empty or whitespace" in str(exc_info.value)


def test_section_valid_with_citation_text():
    """Section is valid with non-empty citation_text"""
    section = Section(
        id="test_section",
        label="Test Section",
        status="propuesto",
        content={"test": "data"},
        citation_text="Esta es mi cita del usuario",
        citation_source="usuario"
    )
    assert section.validate_invariant()


def test_citation_source_invalid_raises_error():
    """citation_source other than 'usuario' or 'analisis_publico' raises CitationInvariantError"""
    with pytest.raises(CitationInvariantError) as exc_info:
        Section(
            id="test_section",
            label="Test Section",
            status="propuesto",
            content={"test": "data"},
            citation_text="Cita válida",
            citation_source="invalid_source"
        )
    assert "citation_source must be" in str(exc_info.value)


def test_citation_source_valid() -> None:
    """citation_source accepts both 'usuario' and 'analisis_publico'"""
    section_valid = Section(
        id="test_section",
        label="Test Section",
        status="propuesto",
        content={"test": "data"},
        citation_text="Cita válida",
        citation_source="analisis_publico"
    )
    assert section_valid.validate_invariant()


# =============================================================================
# BRAND BRAIN MODEL
# =============================================================================

def test_brand_brain_empty_starts_with_no_sections():
    """New BrandBrain has no sections"""
    brain = BrandBrain()
    assert len(brain.sections) == 0
    assert brain.all_sections_valid()  # Vacuously true (no sections to validate)


def test_brand_brain_upsert_section():
    """Upsert updates existing section or creates new one"""
    brain = BrandBrain()

    # Insert first section
    section1 = brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "No sé marketing"},
        citation_text="El usuario dijo: No sé marketing",
        citation_source="usuario",
        status="propuesto"
    )
    assert len(brain.sections) == 1
    assert section1.id == "charco"
    assert section1.status == "propuesto"

    # Update same section
    section2 = brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "No entienden marketing moderno"},
        citation_text="El usuario corrigió: No entienden marketing moderno",
        citation_source="usuario",
        status="confirmado"  # User confirmed
    )
    assert len(brain.sections) == 1  # Still one section
    assert section2.content["pain_point"] == "No entienden marketing moderno"
    assert section2.status == "confirmado"


def test_upsert_with_empty_citation_raises_error():
    """Upserting with empty citation_text raises CitationInvariantError"""
    brain = BrandBrain()

    # Insert valid section
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "No sé marketing"},
        citation_text="El usuario dijo: No sé marketing",
        citation_source="usuario",
        status="propuesto"
    )

    # Try to update with empty citation - should fail
    with pytest.raises(CitationInvariantError):
        brain.upsert_section(
            section_id="charco",
            label="El Charco del Dolor",
            content={"pain_point": "Nuevo dolor"},
            citation_text="",  # Empty!
            citation_source="usuario",
            status="confirmado"
        )


def test_voice_correction_changes_status():
    """Voice correction moves section from propuesto to confirmado"""
    brain = BrandBrain()

    # Agent proposes
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "Deduced: No sabe nada"},
        citation_text="Usuario: 'No entiendo...'",
        citation_source="usuario",
        status="propuesto"
    )
    section = brain.get_section("charco")
    assert section.status == "propuesto"

    # User corrects via voice
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "No entienden marketing B2B"},
        citation_text="Usuario corrigió: 'En realidad es B2B'",
        citation_source="usuario",
        status="confirmado"
    )
    section = brain.get_section("charco")
    assert section.status == "confirmado"
    assert "B2B" in section.content["pain_point"]


def test_brand_brain_validate_all_sections():
    """validate_all_sections checks every section for citation invariant"""
    brain = BrandBrain()

    # Add valid section
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "Test"},
        citation_text="Valid citation",
        citation_source="usuario"
    )

    validation = brain.validate_all_sections()
    assert validation["charco"] == True
    assert brain.all_sections_valid()


# =============================================================================
# DEDUCTION LOGIC
# =============================================================================

def test_can_deduce_content_with_sufficient_evidence():
    """Agent can deduce when enough evidence present in transcript"""
    user_utterances = [
        "Mi problema principal es que no entiendo el marketing digital",
        "Ya probé Facebook ads y no funcionó",
        "Tengo una agencia de consultoría con 5 clientes",
    ]

    result = can_deduce_content("charco", user_utterances)
    assert result["can_deduce"] is True
    assert result["confidence_score"] > 0.5


def test_cannot_deduce_without_evidence():
    """Agent cannot deduce when evidence missing"""
    user_utterances = [
        "Hola, soy nuevo acá",
        "¿Qué tienes disponible?",
    ]

    result = can_deduce_content("charco", user_utterances)
    assert result["can_deduce"] is False
    assert len(result["missing_evidence"]) > 0


def test_knowledge_triage_experto():
    """User with concrete metrics is triaged as experto"""
    user_utterances = [
        "Mis ingresos son de 50k USD mensuales",
        "Tengo un CAC de 200 USD",
        "Mi LTV es de 2000 USD",
        "El churn es del 5% mensual"
    ]

    level = triage_knowledge_level(user_utterances)
    assert level == LEVEL_EXPERTO


def test_knowledge_triage_estudiante():
    """User with vague statements is triaged as estudiante"""
    user_utterances = [
        "Estoy pensando en comenzar un negocio",
        "A lo mejor el año que viene",
        "No sé realmente qué ofrece",
        "Todavía estoy explorando"
    ]

    level = triage_knowledge_level(user_utterances)
    assert level == LEVEL_ESTUDIANTE


# =============================================================================
# SUPABASE STORE (MOCKED CLIENT - NOT INTERNAL LAYER)
# =============================================================================

def test_save_and_retrieve_brand_brain():
    """Persistence to Supabase works correctly with mocked client"""
    # Create a brand brain with valid sections
    brain = BrandBrain()
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "No sé marketing"},
        citation_text="Usuario: No sé marketing",
        citation_source="usuario"
    )
    brain.upsert_section(
        section_id="etapa",
        label="Etapa Actual",
        content={"stage": "Problem Aware", "revenue": "10k"},
        citation_text="Usuario: Estoy ganando 10k",
        citation_source="usuario"
    )

    # Mock the Supabase client
    with patch('app.tools.brand_brain.store._client') as mock_client:
        # Mock upsert response
        mock_upsert = MagicMock()
        mock_upsert.data = [{"session_token": "test123"}]
        mock_client.table.return_value.upsert.return_value.execute.return_value = mock_upsert

        # Save
        result = save_brand_brain("test123", brain)
        assert result is True
        mock_client.table.assert_called_once_with("brand_brains")

        # Verify the actual payload sent to Supabase
        call_args = mock_client.table.return_value.upsert.call_args
        payload = call_args[0][0]
        assert payload["session_token"] == "test123"
        assert len(payload["sections"]) == 2
        assert payload["sections"][0]["citation_text"] == "Usuario: No sé marketing"

        # Mock select response for get
        mock_select = MagicMock()
        mock_select.data = [{
            "session_token": "test123",
            "sections": brain.to_dict()["sections"],
            "formato": None,
            "created_at": brain.created_at,
            "updated_at": brain.updated_at
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select

        # Get
        retrieved = get_brand_brain("test123")
        assert retrieved is not None
        assert len(retrieved.sections) == 2
        assert retrieved.get_section("charco").content["pain_point"] == "No sé marketing"
        # Validate invariants on loaded data
        assert retrieved.all_sections_valid()


def test_save_with_invalid_section_raises_error():
    """save_brand_brain rejects BrandBrain with invalid sections"""
    # Create a brain with an invalid section (simulating from_dict bypass)
    brain = BrandBrain()
    brain.upsert_section(
        section_id="charco",
        label="El Charco del Dolor",
        content={"pain_point": "Test"},
        citation_text="Valid citation",
        citation_source="usuario"
    )
    
    # Manually corrupt to simulate loading invalid data
    brain.sections[-1].citation_text = ""
    brain.sections[-1].citation_source = "usuario"

    # Mock Supabase client
    with patch('app.tools.brand_brain.store._client') as mock_client:
        # Trying to save should fail
        with pytest.raises(CitationInvariantError) as exc_info:
            save_brand_brain("test123", brain)
        
        assert "invalid citations" in str(exc_info.value).lower()
        assert "charco" in str(exc_info.value)
        
        # Verify nothing was sent to Supabase
        mock_client.table.assert_not_called()


# =============================================================================
# EXTRACTION LOGIC (MOCKED LLM)
# =============================================================================

def test_extractor_skips_sections_without_citation():
    """ extractor does not create sections when LLM response lacks citation"""
    # Transcript WITHOUT keyword matches for deducible requirements
    transcript = (
        "Usuario: Hola, quiero trabajar mi marca.\n"
        "Usuario: ¿Qué tal?\n"
        "Usuario: Adiós\n"
    )
    
    # Mock LLM response with some sections
    tool_result = {
        "brand_brain": {
            "pain_puddle": {
                "pain_point": "No entiende marketing",
                "urgency": "alta",
                "consequences": "Pérdida de clientes",
                "failed_attempts": "Facebook ads"
            },
            "irresistible_offer": {
                "offer_components": ["Ebook", "Consultoría"],
                "result_guaranteed": "Mejora en ventas",
                "delivery_format": "Online",
                "guarantee": "30 días devolución"
            }
        },
        "validation_status": "valid"
    }

    sections = convert_to_sections("test_token", tool_result, transcript)
    
    # With no keyword matches, both sections should be skipped
    assert len(sections) == 0

def test_extractor_handles_transcript_with_no_matches():
    """ extractor returns empty list when transcript has no keyword matches"""
    transcript = "Usuario: Hola\nUsuario: ¿Qué tal?\nUsuario: Adiós"
    
    # Mock LLM response
    tool_result = {
        "brand_brain": {
            "pain_puddle": {
                "pain_point": "No entiende marketing",
                "urgency": "alta",
                "consequences": "Pérdida de clientes",
                "failed_attempts": "Facebook ads"
            }
        },
        "validation_status": "valid"
    }

    sections = convert_to_sections("test_token", tool_result, transcript)
    
    # No sections should be created because no citations could be extracted
    assert len(sections) == 0


def test_full_extraction_workflow_with_mocks():
    """Complete workflow with mocked Supabase client"""
    transcript = (
        "Usuario: Mi problema principal es marketing.\n"
        "Usuario: Tengo una agencia de 5 clientes.\n"
        "Usuario: Mis ingresos son de 50k USD.\n"
        "Usuario: No entiendo cómo crecer.\n"
        "Usuario: Ya probé Facebook ads.\n"
        "Usuario: Ayúdame con esto."
    )
    
    tool_result = {
        "brand_brain": {
            "pain_puddle": {
                "pain_point": "No entiende marketing moderno",
                "urgency": "alta",
                "consequences": "Estancamiento",
                "failed_attempts": "Facebook ads sin estrategia"
            },
            "segues_stage": {
                "stage": "Problem Aware",
                "revenue": "50k USD",
                "team_size": "No especificado",
                "primary_focus": "Marketing",
                "pain_points": ["Falta de estrategia"]
            }
        },
        "validation_status": "valid"
    }

    # Mock Supabase client for get (no existing brain)
    with patch('app.tools.brand_brain.extractor.get_brand_brain') as mock_get:
        mock_get.return_value = None
        
        # Mock Supabase client for save
        with patch('app.tools.brand_brain.extractor.save_brand_brain') as mock_save:
            mock_save.return_value = True
            
            # Run extraction
            brain = extract_and_persist("test123", transcript, 6, tool_result)
            
            # Verify brain was created
            assert brain is not None
            assert isinstance(brain, BrandBrain)
            
            # Verify save was called
            mock_save.assert_called_once()
            
            # Verify all sections have valid citations
            assert brain.all_sections_valid()
            
            # Verify the saved data
            save_call_args = mock_save.call_args
            saved_brain = save_call_args[0][1]
            assert saved_brain.all_sections_valid()


# =============================================================================
# INTEGRATION: ENDPOINT BEHAVIOR WITH TestClient
# =============================================================================

def test_get_brand_brain_endpoint_returns_404_when_not_found():
    """GET /api/brain returns 404 if no brand brain exists for session"""
    from fastapi.testclient import TestClient
    from app.main import app
    import os
    
    # Set test mode
    os.environ["TEST_MODE"] = "true"
    
    client = TestClient(app)
    
    # First, get a session token
    token_response = client.get("/api/token")
    assert token_response.status_code == 200
    session_token = token_response.json()["token"]
    
    # Try to get brand brain (should not exist yet)
    response = client.get("/api/brain", cookies={"session_token": session_token})
    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
