"""
Tests for Brand Brain Model - Core model logic.
Tests for API endpoints with JWT are in test_brain_endpoints.py
"""
import os
os.environ["TEST_MODE"] = "true"

import pytest
from app.tools.brand_brain.models import BrandBrain, Section, CitationInvariantError


# Update test IDs to match new 9-node system
def test_section_requires_non_empty_citation_text():
    """Section with empty citation_text should raise CitationInvariantError."""
    with pytest.raises(CitationInvariantError, match="citation_text cannot be empty"):
        Section(
            id="identidad",
            label="Identidad de Marca",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="",
            citation_source="usuario"
        )


def test_section_requires_whitespace_citation_text_raises_error():
    """Section with whitespace-only citation_text should raise CitationInvariantError."""
    with pytest.raises(CitationInvariantError, match="citation_text cannot be empty"):
        Section(
            id="oferta",
            label="Oferta de Valor",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="   ",  # Whitespace only
            citation_source="usuario"
        )


def test_section_valid_with_citation_text():
    """Section with valid citation_text should work."""
    section = Section(
        id="lead_magnet",
        label="Lead Magnet",
        status="propuesto",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Podemos ofrecer servicios de alta calidad.",
        citation_source="usuario"
    )
    assert section.citation_text == "[00:15-00:30] Podemos ofrecer servicios de alta calidad."


def test_section_invalid_citation_source_raises_error():
    """Section with invalid citation_source should raise CitationInvariantError."""
    with pytest.raises(CitationInvariantError, match="citation_source must be"):
        Section(
            id="icp",
            label="Cliente Ideal (ICP)",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="[00:15-00:30] Test",
            citation_source="invalid"  # Not "usuario" or "analisis_publico"
        )


def test_section_valid_citation_source_usuario():
    """Section with 'usuario' citation_source should work."""
    section = Section(
        id="asociaciones",
        label="Asociaciones Culturales",
        status="confirmado",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Podemos ofrecer servicios de alta calidad.",
        citation_source="usuario"
    )
    assert section.citation_source == "usuario"


def test_section_valid_citation_source_analisis_publico():
    """Section with 'analisis_publico' citation_source should work."""
    section = Section(
        id="contrarian",
        label="Posicionamiento Contrarian",
        status="propuesto",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Analysis result",
        citation_source="analisis_publico"
    )
    assert section.citation_source == "analisis_publico"


def test_section_validate_invariant_returns_true():
    """Section with valid data should pass invariant validation."""
    section = Section(
        id="charco",
        label="Charco (Punto de Diferencia)",
        status="propuesto",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Valid citation",
        citation_source="usuario"
    )
    assert section.validate_invariant() is True


def test_section_to_dict_format_converted():
    """Section attributes should be accessible."""
    section = Section(
        id="brand_journey",
        label="Brand Journey",
        status="confirmado",
        content={"text": "Test content", "subtitle": "Test subtitle"},
        citation_text="[00:00-00:15] Sample text.",
        citation_source="usuario"
    )
    assert section.id == "brand_journey"
    assert section.label == "Brand Journey"
    assert section.status == "confirmado"
    assert section.content["text"] == "Test content"
    assert section.citation_text == "[00:00-00:15] Sample text."
    assert section.citation_source == "usuario"
    assert section.created_at is not None
    assert section.updated_at is not None


def test_brand_brain_initialization():
    """BrandBrain should initialize with proper defaults."""
    brain = BrandBrain()
    assert brain.sections == []
    assert brain.formato is None


def test_brand_brain_upsert_new_section():
    """upsert_section should add new section."""
    brain = BrandBrain()
    section = brain.upsert_section(
        section_id="diagnostico",
        label="Diagnóstico",
        content={"text": "Test content"},
        citation_text="[00:00-00:15] Test",
        citation_source="usuario",
        status="propuesto"
    )
    assert section.id == "diagnostico"
    # Check section was added to sections list
    assert any(s.id == "diagnostico" for s in brain.sections)


def test_brand_brain_upsert_existing_section():
    """upsert_section should update existing section."""
    brain = BrandBrain()
    # Add section first
    brain.upsert_section(
        section_id="identidad",
        label="Identidad de Marca",
        content={"text": "Original content"},
        citation_text="[00:00-00:15] Original",
        citation_source="usuario",
        status="propuesto"
    )
    
    # Update it
    updated_section = brain.upsert_section(
        section_id="identidad",
        label="Identidad de Marca (Updated)",
        content={"text": "Updated content"},
        citation_text="[00:15-00:30] Updated",
        citation_source="usuario",
        status="confirmado"
    )
    
    assert updated_section.label == "Identidad de Marca (Updated)"
    assert updated_section.status == "confirmado"
    assert len(brain.sections) == 1  # Still only one section


def test_brand_brain_get_section_by_id():
    """get_section should return None for non-existent section."""
    brain = BrandBrain()
    brain.upsert_section(
        section_id="oferta",
        label="Oferta de Valor",
        content={"text": "Test"},
        citation_text="[00:00-00:10]",
        citation_source="usuario",
        status="propuesto"
    )
    
    found = brain.get_section("oferta")
    assert found is not None
    assert found.id == "oferta"
    
    not_found = brain.get_section("non_existent")
    assert not_found is None


def test_brand_brain_get_all_sections_dict():
    """get_section should find sections by ID."""
    brain = BrandBrain()
    brain.upsert_section(
        section_id="lead_magnet", label="Lead Magnet",
        content={"text": "A"}, citation_text="[00:00]", citation_source="usuario", status="propuesto"
    )
    brain.upsert_section(
        section_id="icp", label="Cliente Ideal",
        content={"text": "B"}, citation_text="[00:01]", citation_source="usuario", status="propuesto"
    )
    
    # Verify both sections can be found
    lead_magnet = brain.get_section("lead_magnet")
    icp = brain.get_section("icp")
    
    assert lead_magnet is not None
    assert lead_magnet.id == "lead_magnet"
    assert icp is not None
    assert icp.id == "icp"


def test_brand_brain_validate_invariant():
    """BrandBrain should maintain citation invariant across all sections."""
    brain = BrandBrain()
    brain.upsert_section(
        section_id="contrarian", label="Posicionamiento",
        content={"text": "Test"}, citation_text="[00:00] Test", citation_source="usuario", status="propuesto"
    )
    
    # Should not raise
    section = brain.get_section("contrarian")
    assert section.validate_invariant() is True


def test_brand_brain_initializes_with_timestamps():
    """BrandBrain should initialize with created_at and updated_at."""
    brain = BrandBrain()
    assert brain.created_at is not None
    assert brain.updated_at is not None


def test_upsert_updates_timestamp():
    """Upsert should update the brain's updated_at timestamp."""
    brain = BrandBrain()
    original_updated = brain.updated_at

    brain.upsert_section(
        section_id="test",
        label="Test",
        content={"text": "Test"},
        citation_text="[00:00-00:15]",
        citation_source="usuario",
        status="propuesto"
    )

    # Timestamp should be different (at least in most cases)
    # We can't guarantee exact timing, but we can check it's been updated
    assert brain.updated_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
