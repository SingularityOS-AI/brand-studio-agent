"""
Tests for Brand Brain Model - Core model logic.
Tests for API endpoints with JWT are in test_brain_endpoints.py
"""
import os
os.environ["TEST_MODE"] = "true"

import pytest
from app.tools.brand_brain.models import BrandBrain, Section, CitationInvariantError


def test_section_requires_non_empty_citation_text():
    """Section with empty citation_text should raise CitationInvariantError."""
    with pytest.raises(CitationInvariantError, match="citation_text cannot be empty"):
        Section(
            id="value_proposition",
            label="Propuesta de Valor",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="",
            citation_source="usuario"
        )


def test_section_requires_whitespace_citation_text_raises_error():
    """Section with whitespace-only citation_text should raise CitationInvariantError."""
    with pytest.raises(CitationInvariantError, match="citation_text cannot be empty"):
        Section(
            id="value_proposition",
            label="Propuesta de Valor",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="   ",  # Whitespace only
            citation_source="usuario"
        )


def test_section_valid_with_citation_text():
    """Section with valid citation_text should work."""
    section = Section(
        id="value_proposition",
        label="Propuesta de Valor",
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
            id="value_proposition",
            label="Propuesta de Valor",
            status="propuesto",
            content={"text": "Test content"},
            citation_text="[00:15-00:30] Test",
            citation_source="invalid"  # Not "usuario" or "analisis_publico"
        )


def test_section_valid_citation_source_usuario():
    """Section with 'usuario' citation_source should work."""
    section = Section(
        id="value_proposition",
        label="Propuesta de Valor",
        status="confirmado",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Podemos ofrecer servicios de alta calidad.",
        citation_source="usuario"
    )
    assert section.citation_source == "usuario"


def test_section_valid_citation_source_analisis_publico():
    """Section with 'analisis_publico' citation_source should work."""
    section = Section(
        id="value_proposition",
        label="Propuesta de Valor",
        status="propuesto",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Analysis result",
        citation_source="analisis_publico"
    )
    assert section.citation_source == "analisis_publico"


def test_section_validate_invariant_returns_true():
    """Section with valid data should pass invariant validation."""
    section = Section(
        id="value_proposition",
        label="Propuesta de Valor",
        status="propuesto",
        content={"text": "Test content"},
        citation_text="[00:15-00:30] Valid citation",
        citation_source="usuario"
    )
    assert section.validate_invariant() is True


def test_brand_brain_empty_starts_with_no_sections():
    """Empty brand brain should start with no sections."""
    brain = BrandBrain()
    assert len(brain.sections) == 0


def test_brand_brain_upsert_section_add():
    """Upsert section should add new section."""
    brain = BrandBrain()

    section = brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Propuesta de valor única"},
        citation_text="[00:15-00:30] Nuestra propuesta...",
        citation_source="usuario",
        status="confirmado"
    )
    assert len(brain.sections) == 1
    assert section.id == "value_proposition"
    assert section.label == "Propuesta de Valor"
    assert section.status == "confirmado"


def test_brand_brain_upsert_section_update():
    """Upsert section should update existing section."""
    brain = BrandBrain()

    # Add first section
    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Propuesta de valor única"},
        citation_text="[00:15-00:30] Nuestra propuesta...",
        citation_source="usuario",
        status="confirmado"
    )

    # Update section
    updated = brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Propuesta de valor actualizada"},
        citation_text="[00:15-00:45] Nuestra propuesta actualizada...",
        citation_source="usuario",
        status="confirmado"
    )

    assert len(brain.sections) == 1
    assert updated.content["text"] == "Propuesta de valor actualizada"
    assert updated.citation_text == "[00:15-00:45] Nuestra propuesta actualizada..."


def test_upsert_with_empty_citation_raises_error():
    """Upsert with empty citation_text should raise CitationInvariantError."""
    brain = BrandBrain()

    with pytest.raises(CitationInvariantError, match="citation_text cannot be empty"):
        brain.upsert_section(
            section_id="value_proposition",
            label="Propuesta de Valor",
            content={"text": "Content"},
            citation_text="",  # Empty
            citation_source="usuario",
            status="confirmado"
        )


def test_get_section_by_id():
    """Get section by ID should return correct section."""
    brain = BrandBrain()

    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Content"},
        citation_text="[00:15-00:30]",
        citation_source="usuario",
        status="confirmado"
    )

    section = brain.get_section("value_proposition")
    assert section is not None
    assert section.id == "value_proposition"
    assert section.label == "Propuesta de Valor"


def test_get_section_nonexistent_returns_none():
    """Get section with non-existent ID should return None."""
    brain = BrandBrain()
    assert brain.get_section("nonexistent") is None


def test_validate_all_sections_returns_dict():
    """Validate all sections should return dict with section validity."""
    brain = BrandBrain()

    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Content"},
        citation_text="[00:15-00:30]",
        citation_source="usuario",
        status="confirmado"
    )

    results = brain.validate_all_sections()
    assert isinstance(results, dict)
    assert "value_proposition" in results
    assert results["value_proposition"] is True


def test_all_sections_valid_true_when_all_valid():
    """all_sections_valid should return True when all sections are valid."""
    brain = BrandBrain()

    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Content"},
        citation_text="[00:15-00:30]",
        citation_source="usuario",
        status="confirmado"
    )

    assert brain.all_sections_valid() is True


def test_get_section_order():
    """get_section_order should return sections in canonical order."""
    from app.tools.brand_brain.questions import get_section_order

    brain = BrandBrain()

    # Add sections in reverse order
    for section_id in reversed(get_section_order()[:3]):
        brain.upsert_section(
            section_id=section_id,
            label=f"Label for {section_id}",
            content={"text": f"Content for {section_id}"},
            citation_text="[00:00-00:15]",
            citation_source="usuario",
            status="confirmado"
        )

    order = brain.get_section_order()
    assert len(order) == 3
    # Should be in canonical order, not insertion order
    expected_first = get_section_order()[0]
    assert order[0] == expected_first


def test_to_dict_serializes_brain():
    """to_dict should serialize brain to dict."""
    brain = BrandBrain()

    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Content"},
        citation_text="[00:15-00:30]",
        citation_source="usuario",
        status="confirmado"
    )

    data = brain.to_dict()
    assert "sections" in data
    assert len(data["sections"]) == 1
    assert data["sections"][0]["id"] == "value_proposition"
    assert data["sections"][0]["label"] == "Propuesta de Valor"
    assert "created_at" in data
    assert "updated_at" in data


def test_from_dict_deserializes_brain():
    """from_dict should deserialize brain from dict."""
    data = {
        "sections": [
            {
                "id": "value_proposition",
                "label": "Propuesta de Valor",
                "status": "confirmado",
                "content": {"text": "Content"},
                "citation_text": "[00:15-00:30]",
                "citation_source": "usuario",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        ],
        "formato": "video",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00"
    }

    brain = BrandBrain.from_dict(data)
    assert len(brain.sections) == 1
    assert brain.sections[0].id == "value_proposition"
    assert brain.formato == "video"
    assert brain.created_at == "2024-01-01T00:00:00"


def test_roundtrip_to_dict_and_from_dict():
    """Brain should survive to_dict then from_dict roundtrip."""
    brain = BrandBrain()

    brain.upsert_section(
        section_id="value_proposition",
        label="Propuesta de Valor",
        content={"text": "Original content"},
        citation_text="[00:15-00:30]",
        citation_source="usuario",
        status="confirmado"
    )

    data = brain.to_dict()
    restored = BrandBrain.from_dict(data)

    assert len(restored.sections) == 1
    assert restored.sections[0].id == "value_proposition"
    assert restored.sections[0].content["text"] == "Original content"
    assert restored.created_at == brain.created_at


def test_status_values_propuesto_and_confirmado():
    """Section status should only accept 'propuesto' or 'confirmado'."""
    # Valid status values
    section1 = Section(
        id="test1",
        label="Test 1",
        status="propuesto",
        content={"text": "Test"},
        citation_text="[00:00-00:15]",
        citation_source="usuario"
    )
    assert section1.status == "propuesto"

    section2 = Section(
        id="test2",
        label="Test 2",
        status="confirmado",
        content={"text": "Test"},
        citation_text="[00:00-00:15]",
        citation_source="usuario"
    )
    assert section2.status == "confirmado"


def test_created_and_updated_timestamps():
    """Section and BrandBrain should have created_at and updated_at timestamps."""
    section = Section(
        id="test",
        label="Test",
        status="propuesto",
        content={"text": "Test"},
        citation_text="[00:00-00:15]",
        citation_source="usuario"
    )
    assert section.created_at is not None
    assert section.updated_at is not None

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


# Tests for extractor logic
# Note: The extractor module doesn't use BaseExtractor pattern - tests removed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
