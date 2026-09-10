"""
Test that _compute_brain_hash ignores updated_at timestamps.

This test verifies the fix for the bug where credits were charged every time
the Brand Soul was opened because the hash included the brain.updated_at field.

The bug:
- brain.updated_at comes from the DB and changes on every UPDATE (including cache saves)
- _compute_brain_hash was using brain.to_dict() which included updated_at
- Every cache save updated the timestamp -> hash changed -> cache invalid -> regenerated -> charged

The fix:
- _compute_brain_hash now only hashes the actual content (sections and formato)
- Different updated_at values should produce the SAME hash
"""

import pytest
from app.tools.brand_soul.generator import _compute_brain_hash
from app.tools.brand_brain.models import BrandBrain, Section


def test_brain_hash_ignores_updated_at():
    """Test that hash is identical when only updated_at differs."""
    # Create a brain with some sections
    sections1 = [
        Section(
            id="diagnostico",
            label="Diagnóstico",
            content={"etapa": "Invisible", "focus": "first 6 months"},
            citation_text="Estoy recién arrancando",
            citation_source="usuario",
            status="confirmado",
            created_at="2024-01-01T10:00:00",
            updated_at="2024-01-01T10:00:00"
        ),
        Section(
            id="charco",
            label="Charco",
            content={"problema": "Alguien quiere cobrar lo que no necesita"},
            citation_text="Gente quiere pagar por cosas que no usan",
            citation_source="usuario",
            status="confirmado",
            created_at="2024-01-01T10:00:00",
            updated_at="2024-01-01T10:00:00"
        ),
        Section(
            id="identidad",
            label="Identidad",
            content={"voz": "Directa y sin rodeos", "colores": "Negro y neón"},
            citation_text="Soy directo, no tengo pelos en la lengua",
            citation_source="usuario",
            status="confirmado",
            created_at="2024-01-01T10:00:00",
            updated_at="2024-01-01T10:00:00"
        ),
    ]

    # Create two BrandBrain instances with the SAME sections content
    # but DIFFERENT updated_at timestamps
    brain1 = BrandBrain(
        sections=sections1,
        formato="standard",
        created_at="2024-01-01T10:00:00",
        updated_at="2024-01-01T10:00:00"
    )

    # Same sections, different brain-level updated_at
    brain2 = BrandBrain(
        sections=sections1,
        formato="standard",
        created_at="2024-01-01T10:00:00",
        updated_at="2024-01-02T14:30:00"  # Different timestamp!
    )

    # Different section-level updated_at
    sections2_with_future_timestamp = [
        Section(
            id=s.id,
            label=s.label,
            content=s.content,
            citation_text=s.citation_text,
            citation_source=s.citation_source,
            status=s.status,
            created_at=s.created_at,
            updated_at="2025-12-31T23:59:59"  # Far future timestamp!
        )
        for s in sections1
    ]

    brain3 = BrandBrain(
        sections=sections2_with_future_timestamp,
        formato="standard",
        created_at="2024-01-01T10:00:00",
        updated_at="2024-03-15T20:00:00"
    )

    hash1 = _compute_brain_hash(brain1)
    hash2 = _compute_brain_hash(brain2)
    hash3 = _compute_brain_hash(brain3)

    # All three hashes should be IDENTICAL because content is the same
    assert hash1 == hash2, "Hash should be identical when only brain.updated_at differs"
    assert hash1 == hash3, "Hash should be identical when only section.updated_at differs"
    assert hash2 == hash3, "Hash should be identical when only timestamps differ"

    # Verify the hash is not empty and is SHA256 (64 hex chars)
    assert hash1, "Hash should not be empty"
    assert len(hash1) == 64, "SHA256 hash should be 64 characters"
    assert all(c in "0123456789abcdef" for c in hash1), "Hash should be hexadecimal"


def test_brain_hash_changes_with_content():
    """Test that hash DOES change when actual content changes."""
    sections1 = [
        Section(
            id="diagnostico",
            label="Diagnóstico",
            content={"etapa": "Invisible"},
            citation_text="Test quote",
            citation_source="usuario",
            status="confirmado",
            created_at="2024-01-01T10:00:00",
            updated_at="2024-01-01T10:00:00"
        ),
    ]

    sections2 = [
        Section(
            id="diagnostico",
            label="Diagnóstico",
            content={"etapa": "Explorador"},  # Different content
            citation_text="Test quote",
            citation_source="usuario",
            status="confirmado",
            created_at="2024-01-01T10:00:00",
            updated_at="2024-01-01T10:00:00"
        ),
    ]

    brain1 = BrandBrain(
        sections=sections1,
        formato="standard",
        created_at="2024-01-01T10:00:00",
        updated_at="2024-01-01T10:00:00"
    )

    brain2 = BrandBrain(
        sections=sections2,
        formato="standard",
        created_at="2024-01-01T10:00:00",
        updated_at="2024-01-01T10:00:00"
    )

    hash1 = _compute_brain_hash(brain1)
    hash2 = _compute_brain_hash(brain2)

    assert hash1 != hash2, "Hash should differ when section content changes"


if __name__ == "__main__":
    test_brain_hash_ignores_updated_at()
    test_brain_hash_changes_with_content()
    print("✓ All brain hash tests passed!")
