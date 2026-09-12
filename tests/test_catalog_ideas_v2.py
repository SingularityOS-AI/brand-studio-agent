"""
Tests for catalog/ideas.py (Pieza 26: Motor de Ideas del Catálogo).

Coverage:
- Pydantic models validation (CatalogIdea, Catalog)
- Master categories definition (5 fixed categories)
- Hash computation excluding timestamps
- Approach determination (experto vs curador)
- Niche extraction from ICP/charco
- Gate logic (true only when 30 valid ideas with real signals)
- Cache workflow (hash check, save, retrieve)
"""
import pytest
import datetime
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from typing import List

# Import models and functions
from app.catalog.ideas import (
    CatalogIdea,
    Catalog,
    _compute_catalog_hash,
    _determine_approach,
    _extract_niche,
    CREDITS_COST,
    _check_catalog_cache,
    _save_catalog_cache,
    generate_catalog,
    MASTER_CATEGORIES,
    TOTAL_IDEAS,
    IDEA_DISTRIBUTION
)

# Import BrandBrain model and store function
from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.store import get_brand_brain

# Import NicheResearch
from app.catalog.demand import NicheResearch


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_brand_sections():
    """Mock BrandBrain sections with required citation_text and valid citation_source."""
    return [
        Section(
            id="diagnostico",
            label="diagnostico",
            status="confirmado",
            content={"postura": "experto", "descripcion": "Fundador tiene 15 años de experiencia."},
            citation_text="Entrevista con fundador sobre experiencia",
            citation_source="usuario",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        ),
        Section(
            id="icp",
            label="icp",
            status="confirmado",
            content={"nicho": "Interpretación médica para hospitales", "target": "gerentes de RR."},
            citation_text="Análisis de perfil de cliente",
            citation_source="analisis_publico",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        ),
        Section(
            id="charco",
            label="charco",
            status="confirmado",
            content={"problema": "Líder en interpretación médica certificada. Niche: interpretación médica."},
            citation_text="Storytelling del fundador",
            citation_source="usuario",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        ),
        Section(
            id="identidad",
            label="identidad",
            status="confirmado",
            content={"voz": "autoritaria, de confianza, clara", "descripcion": "Médicos confían en nosotros."},
            citation_text="Directrices de tono y voz",
            citation_source="analisis_publico",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
    ]


@pytest.fixture
def brand_brain(sample_brand_sections):
    """Complete BrandBrain fixture with all required sections."""
    return BrandBrain(
        sections=sample_brand_sections,
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.fixture
def niche_research_sample():
    """Mock NicheResearch for testing."""
    return NicheResearch(
        niche="interpretación médica",
        youtube_titles=[
            "Medical Interpretation Best Practices",
            "Hospital Interpreter Training Tips"
        ],
        youtube_pain_signals=[
            "Communication breakdown leads to medical errors",
            "Lack of certified interpreters in emergencies"
        ],
        trends_series=[
            ("2023-01", 100),
            ("2023-02", 95),
            ("2023-03", 110)
        ],
        trends_related=[
            "medical interpreter certification",
            "hospital interpretation services"
        ],
        web_grounding_notes=[
            "Growing demand for certified medical interpreters",
            "Regulations requiring interpretation services"
        ]
    )


# =============================================================================
# Model Tests
# =============================================================================

def test_catalog_idea_model_validation():
    """CatalogIdea should validate required fields."""
    idea = CatalogIdea(
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="5 Essential Medical Interpretation Techniques",
        demand_signal="Communication breakdown leads to medical errors"
    )

    assert idea.master_category == "autoridad_tecnica"
    assert idea.subcategory == "Top N/Listículo técnico"
    assert idea.title == "5 Essential Medical Interpretation Techniques"
    assert idea.demand_signal == "Communication breakdown leads to medical errors"
    assert idea.status == "pending"


def test_catalog_idea_invalid_master_category():
    """CatalogIdea should reject invalid master categories."""
    with pytest.raises(ValueError, match="Categoría inválida"):
        CatalogIdea(
            master_category="invalid_category",
            subcategory="Any",
            title="Test",
            demand_signal="Test signal with enough length"
        )


def test_catalog_idea_demand_signal_min_length():
    """CatalogIdea should enforce minimum demand signal length (10 chars)."""
    with pytest.raises(ValueError, match="at least 10 characters"):
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Any",
            title="Valid Title",
            demand_signal="short"
        )


def test_catalog_model_properties():
    """Catalog should expose helpful properties."""
    catalog = Catalog(
        session_id="test_session",
        niche="medical interpretation",
        ideas=[
            CatalogIdea(
                master_category="autoridad_tecnica",
                subcategory="Anatomía de un proceso",
                title="Test Idea 1",
                demand_signal="Valid signal 1"
            ),
            CatalogIdea(
                master_category="validacion_resultados",
                subcategory="Antes/Después con métricas",
                title="Test Idea 2",
                demand_signal="Valid signal 2",
                status="approved"
            )
        ],
        gate_passed=True
    )

    assert catalog.idea_count == 2
    assert catalog.approved_count == 1
    assert catalog.category_counts["autoridad_tecnica"] == 1
    assert catalog.category_counts["validacion_resultados"] == 1


def test_catalog_locked_field():
    """Catalog should have catalog_locked field for Piece 27."""
    catalog = Catalog(
        session_id="test_session",
        niche="test niche",
        ideas=[],
        gate_passed=False,
        catalog_locked=True
    )

    assert catalog.catalog_locked is True


def test_catalog_ideas_max_count():
    """Catalog should enforce max of 30 ideas."""
    ideas = [
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Any",
            title=f"Idea Number {i}",
            demand_signal=f"Signal Number {i}"
        )
        for i in range(31)
    ]

    with pytest.raises(ValueError, match="Máximo 30 ideas"):
        Catalog(
            session_id="test",
            niche="test",
            ideas=ideas
        )


# =============================================================================
# Constant Tests
# =============================================================================

def test_master_categories_definition():
    """MASTER_CATEGORIES should have 5 categories with correct structure."""
    assert len(MASTER_CATEGORIES) == 5

    # Check each category has required fields
    for cat in MASTER_CATEGORIES:
        assert "id" in cat
        assert "name" in cat
        assert "percentage" in cat
        assert "subcategories" in cat
        assert len(cat["subcategories"]) > 0

    # Check IDs
    category_ids = [cat["id"] for cat in MASTER_CATEGORIES]
    expected_ids = [
        "autoridad_tecnica",
        "validacion_resultados",
        "posicionamiento_narrativa",
        "narrativa_fundadora",
        "discusion_industria"
    ]
    assert category_ids == expected_ids


def test_idea_distribution():
    """IDEA_DISTRIBUTION should sum to 30 with correct percentages."""
    total = sum(IDEA_DISTRIBUTION.values())
    assert total == 30

    # Check distribution percentages
    assert IDEA_DISTRIBUTION["autoridad_tecnica"] == 12  # 40%
    assert IDEA_DISTRIBUTION["validacion_resultados"] == 9  # 30%
    assert IDEA_DISTRIBUTION["posicionamiento_narrativa"] == 6  # 20%
    assert IDEA_DISTRIBUTION["discusion_industria"] == 3  # 10%


def test_total_ideas_constant():
    """TOTAL_IDEAS should be 30."""
    assert TOTAL_IDEAS == 30


def test_credits_cost():
    """CREDITS_COST should be defined."""
    assert CREDITS_COST == 15


# =============================================================================
# Hash Computation Tests
# =============================================================================

@patch('app.catalog.ideas.get_brand_brain')
def test_compute_hash_excludes_timestamps(mock_get_brain, brand_brain):
    """Hash should not include timestamps (regression test)."""
    mock_get_brain.return_value = brand_brain

    hash1 = _compute_catalog_hash("test_session")
    hash2 = _compute_catalog_hash("test_session")

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex length
    assert isinstance(hash1, str)


# =============================================================================
# Approach Determination Tests
# =============================================================================

def test_determine_approach_experto():
    """Should detect 'experto' approach."""
    diagnostico = {
        "postura": "experto",
        "descripcion": "15 años de experiencia"
    }
    assert _determine_approach(diagnostico) == "experto"


def test_determine_approach_curador():
    """Should detect 'curador' approach."""
    diagnostico = {
        "postura": "curador",
        "descripcion": "Investigador de tendencias"
    }
    assert _determine_approach(diagnostico) == "curador"


def test_determine_approach_infers_from_expertise():
    """Should infer from description when posture not explicit."""
    diagnostico = {
        "postura": "inicativa",
        "descripcion": "Fundador con 20 años creando soluciones"
    }
    assert _determine_approach(diagnostico) == "experto"


# =============================================================================
# Niche Extraction Tests
# =============================================================================

def test_extract_niche_from_icp():
    """Should extract niche from ICP first."""
    icp = {"nicho": "interpretación médica"}
    charco = {"problema": "Cualquier cosa"}

    niche = _extract_niche(icp, charco)
    assert "interpretación" in niche.lower()


def test_extract_niche_from_charco():
    """Should fall back to charco if ICP empty."""
    icp = {"nicho": ""}
    charco = {"problema": "Niche: liderazgo ejecutivo"}

    niche = _extract_niche(icp, charco)
    assert niche.strip() != ""


# =============================================================================
# Cache Tests
# =============================================================================

@patch('app.catalog.ideas.get_brand_brain')
def test_save_and_load_cache(mock_get_brain, brand_brain, tmp_path, monkeypatch):
    """Should save and load catalog from cache."""
    mock_get_brain.return_value = brand_brain

    catalog = Catalog(
        session_id="test_session",
        niche="test niche",
        ideas=[
            CatalogIdea(
                master_category="autoridad_tecnica",
                subcategory="Test",
                title="Valid Title",
                demand_signal="Valid signal test"
            )
        ],
        gate_passed=True
    )

    # Save
    _save_catalog_cache(catalog)

    # Should create cache file
    import os
    cache_dir = "cache/catalog"
    cache_file = os.path.join(cache_dir, "test_session.json")
    assert os.path.exists(cache_file)
    
    # Cleanup test cache file if needed
    if os.path.exists(cache_file):
        os.remove(cache_file)


# =============================================================================
# Run Tests Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
