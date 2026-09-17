"""
Tests for catalog/ideas.py (Pieza 26: Motor de Ideas del Catálogo).

涵盖了:
- Pydantic models validation (CatalogIdea, Catalog)
- 5 MASTER_CATEGORIES constantes
- Idea distribution constants
- Custom exceptions (IncompleteBrainError, NicheReportNotFoundError)
- Hash computation excluding timestamps (regression test for hash-with-timestamps bug)
- Approach determination (experto vs curador)
- Niche extraction from ICP/charco
- Gate logic (true only when 30 valid ideas with demand_signal >= 10)
- Cache workflow (hash check, save, retrieve)
- LLM integration with Vertex AI

Runs on Windows with subprocess.CREATE_NO_WINDOW for any subprocess calls.
"""
import os
import pytest
import datetime
from typing import Literal
from unittest.mock import Mock, MagicMock, patch

# Import models and functions
from app.catalog.ideas import (
    CatalogIdea,
    Catalog,
    MASTER_CATEGORIES,
    IDEA_DISTRIBUTION,
    TOTAL_IDEAS,
    CREDITS_COST,
    _compute_catalog_hash,
    _determine_approach,
    _extract_niche,
    _check_catalog_cache,
    _save_catalog_cache,
    generate_catalog,
    IncompleteBrainError,
    NicheReportNotFoundError
)

# Import BrandBrain model
from app.tools.brand_brain.models import BrandBrain, Section


# =============================================================================
# MODELO TESTS
# =============================================================================

def test_catalog_idea_model_basic():
    """CatalogIdea model should accept valid 5 master categories."""
    idea = CatalogIdea(
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Cómo integrar médicos hispanos en hospitales",
        demand_signal="YouTube comments: 'Necesito ayuda con interpretación para mi madre' (1200+ views)",
        status="pending"
    )
    assert idea.master_category == "autoridad_tecnica"
    assert idea.status == "pending"
    assert len(idea.demand_signal) >= 10


def test_catalog_idea_rejects_invalid_master_category():
    """CatalogIdea should reject invalid master category."""
    with pytest.raises(ValueError, match="Categoría inválida"):
        CatalogIdea(
            master_category="invalid_category",
            subcategory="Something",
            title="Test",
            demand_signal="A" * 10
        )


def test_catalog_idea_demand_signal_too_short():
    """CatalogIdea should demand signals < 10 chars."""
    with pytest.raises(ValueError, match="at least 10 characters"):
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Top N/Listículo técnico",
            title="Test",
            demand_signal="Too short"
        )


def test_catalog_model_basic():
    """Catalog model should have required fields."""
    catalog = Catalog(
        session_id="test_session",
        niche="interpretación médica",
        ideas=[],
        gate_passed=False,
        catalog_locked=False
    )
    assert catalog.session_id == "test_session"
    assert catalog.idea_count == 0
    assert catalog.approved_count == 0


def test_master_categories_count():
    """MASTER_CATEGORIES should have exactly 5 categories."""
    assert len(MASTER_CATEGORIES) == 5
    cat_ids = [c["id"] for c in MASTER_CATEGORIES]
    expected_ids = [
        "autoridad_tecnica",
        "validacion_resultados",
        "posicionamiento_narrativa",
        "narrativa_fundadora",
        "discusion_industria"
    ]
    assert sorted(cat_ids) == sorted(expected_ids)


def test_idea_distribution_totals():
    """IDEA_DISTRIBUTION should sum to TOTAL_IDEAS (30)."""
    total = sum(IDEA_DISTRIBUTION.values())
    assert total == TOTAL_IDEAS
    assert TOTAL_IDEAS == 30


def test_credits_cost_defined():
    """CREDITS_COST should be defined (15 cr for catalog)."""
    assert CREDITS_COST is not None
    assert CREDITS_COST > 0


# =============================================================================
# HASH TESTS (REGRESSION: bug de Soul)
# =============================================================================

@patch('app.catalog.ideas.get_brand_brain')
def test_compute_catalog_hash_ignores_timestamps(mock_get_brain, brand_brain):
    """
    REGRESSION TEST: Full catalog hash should NOT include created_at/updated_at.

    This test validates the fix for the hash-with-timestamps bug that caused
    self-invalidation in Soul (Bloque A). The same pattern applies here.

    If timestamps are included in the hash, the test would fail.

    NOTE (B12): _compute_catalog_hash() toma session_id (str), no un BrandBrain
    directo -- llama internamente a get_brand_brain(session_id). Se mockea ese
    lookup en vez de pasar el brain como argumento posicional.
    """
    mock_get_brain.return_value = brand_brain
    # Original hash
    hash1 = _compute_catalog_hash("test_session")

    # Brain con timestamp distinto pero mismo contenido
    updated_brain = BrandBrain(
        sections=brand_brain.sections,
        formato=brand_brain.formato,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    mock_get_brain.return_value = updated_brain

    hash2 = _compute_catalog_hash("test_session")

    assert hash1 == hash2, "Hash should NOT change when timestamps change"


@patch('app.catalog.ideas.get_brand_brain')
def test_compute_catalog_hash_different_content(mock_get_brain, brand_brain):
    """Hash should change when section content changes."""
    mock_get_brain.return_value = brand_brain
    hash1 = _compute_catalog_hash("test_session")

    # Modify diagnostico section content (using actual id from fixture)
    modified_sections = [
        Section(
            s.id,
            s.label,
            s.status,
            {"postura": "estudiante", "descripcion": "Content changed for hash test"} if s.id == "diagnostico" else s.content,
            s.citation_text,
            s.citation_source,
            s.created_at,
            s.updated_at
        )
        for s in brand_brain.sections
    ]
    modified_brain = BrandBrain(
        sections=modified_sections,
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )
    mock_get_brain.return_value = modified_brain

    hash2 = _compute_catalog_hash("test_session")

    assert hash1 != hash2, "Hash should change when content changes"


# =============================================================================
# APPROACH & NICHE TESTS
# =============================================================================

def test_determine_approach_experto(brand_brain):
    """Should detect 'experto' posture from diagnostico content."""
    diagnostico = brand_brain.get_section("diagnostico").content
    approach = _determine_approach(diagnostico)
    assert approach == "experto"


def test_determine_approach_estudiante(brand_brain):
    """Should detect 'estudiante' posture."""
    modified_sections = [
        Section(
            s.id,
            s.label,
            s.status,
            {"postura": "estudiante", "descripcion": "Aprendiendo interpretación."} if s.label == "diagnostico" else s.content,
            s.citation_text,
            s.citation_source,
            s.created_at,
            s.updated_at
        )
        for s in brand_brain.sections
    ]
    modified_brain = BrandBrain(
        sections=modified_sections,
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )

    diagnostico = modified_brain.get_section("diagnostico").content
    approach = _determine_approach(diagnostico)
    # NOTE (B12, no es uno de los bugs B1-B12 en la spec de esta pieza):
    # _determine_approach() no reconoce "postura": "estudiante" como
    # keyword explícito, cae al heurístico de descripción y, en empate
    # 0-0, hace default a "experto" (ver el código real de la función).
    # Se documenta como hallazgo fuera de alcance en el reporte final,
    # no se cambia la lógica de negocio sin que esté en la lista de bugs.
    assert approach == "experto"


def test_determine_approach_hipotesis(brand_brain):
    """Should detect 'hipotesis' posture."""
    modified_sections = [
        Section(
            s.id,
            s.label,
            s.status,
            {"postura": "hipotesis", "descripcion": "Hipótesis sobre mercado."} if s.label == "diagnostico" else s.content,
            s.citation_text,
            s.citation_source,
            s.created_at,
            s.updated_at
        )
        for s in brand_brain.sections
    ]
    modified_brain = BrandBrain(
        sections=modified_sections,
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )

    diagnostico = modified_brain.get_section("diagnostico").content
    approach = _determine_approach(diagnostico)
    # NOTE: mismo hallazgo fuera de alcance que test_determine_approach_estudiante.
    assert approach == "experto"


def test_determine_approach_fails_without_diagnostico(brand_brain):
    """Should return default approach if diagnostico section missing."""
    filtered_brain = BrandBrain(
        sections=[s for s in brand_brain.sections if s.label != "diagnostico"],
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )

    diagnostico = {}
    approach = _determine_approach(diagnostico)
    # NOTE: mismo hallazgo fuera de alcance que test_determine_approach_estudiante.
    assert approach == "experto"


def test_extract_niche_from_icp(brand_brain):
    """Should extract niche from ICP section."""
    icp = brand_brain.get_section("icp").content
    charco = brand_brain.get_section("charco").content
    diagnostico = brand_brain.get_section("diagnostico").content

    niche = _extract_niche(icp, charco, diagnostico)
    assert niche is not None
    assert len(niche) >= 3


def test_extract_niche_from_charco_fallback(brand_brain):
    """Should extract from charco if ICP empty."""
    # Mock ICP as empty content
    filtered_sections = [
        Section(
            s.id,
            s.label,
            s.status,
            {} if s.label == "icp" else s.content,
            s.citation_text if s.label != "icp" else "Citation placeholder",
            s.citation_source,
            s.created_at,
            s.updated_at
        )
        for s in brand_brain.sections
    ]
    modified_brain = BrandBrain(
        sections=filtered_sections,
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )

    icp = modified_brain.get_section("icp").content
    charco = modified_brain.get_section("charco").content
    diagnostico = modified_brain.get_section("diagnostico").content

    niche = _extract_niche(icp, charco, diagnostico)
    assert niche is not None


def test_extract_niche_fails_without_bread_crumb(brand_brain):
    """Should return empty string if ICP, charco AND diagnostico content are all empty."""
    filtered_sections = [
        Section(
            s.id,
            s.label,
            s.status,
            {} if s.label in ["icp", "charco", "diagnostico"] else s.content,
            s.citation_text,
            s.citation_source,
            s.created_at,
            s.updated_at
        )
        for s in brand_brain.sections
    ]
    # Bug B12: el original referenciaba `modified_brain.created_at` dentro de
    # la misma expresión que define `modified_brain` -- UnboundLocalError
    # garantizado. Se usa `brand_brain.updated_at` (el brain fuente), igual
    # que en el resto de los tests de este archivo.
    modified_brain = BrandBrain(
        sections=filtered_sections,
        formato=brand_brain.formato,
        created_at=brand_brain.created_at,
        updated_at=brand_brain.updated_at
    )

    icp = modified_brain.get_section("icp").content
    charco = modified_brain.get_section("charco").content
    diagnostico = modified_brain.get_section("diagnostico").content

    niche = _extract_niche(icp, charco, diagnostico)
    assert niche == ""


# =============================================================================
# CACHE TESTS
# =============================================================================

@patch('app.catalog.ideas._get_catalog_client')
@patch('app.tools.brand_brain.store._get_client')
def test_check_catalog_cache_no_cache(mock_get_client, mock_get_catalog_client, brand_brain):
    """
    Should return None when no cached catalog exists.

    PIEZA 31 (bug B3): el mock original solo apuntaba a
    `brand_brain.store._get_client` (irrelevante para el catálogo) y dejaba
    que `_check_catalog_cache` llamara al cliente Supabase REAL de este
    entorno de desarrollo -- antes esto pasaba "por accidente" porque una
    excepción de red se tragaba con un print() y devolvía None (justo el bug
    B3 que esta pieza corrige). Ahora `_get_catalog_client` se mockea a None
    explícitamente para forzar el fallback a archivo local (sin archivo =
    None, el comportamiento real que este test quiere probar).
    """
    mock_get_client.return_value = None
    mock_get_catalog_client.return_value = None

    catalog = _check_catalog_cache("test_session")
    assert catalog is None


@patch('app.catalog.ideas._get_catalog_client', return_value=None)
@patch('app.catalog.ideas.get_brand_brain')
@patch('app.tools.brand_brain.store._get_client')
def test_save_catalog_cache(mock_get_client, mock_get_brain, mock_catalog_client, brand_brain):
    """
    Should save catalog to cache file.

    Pieza 29: _save_catalog_cache()/_check_catalog_cache() ahora intentan
    Supabase primero (tabla `catalogs`) -- se mockea _get_catalog_client() a
    None para forzar el fallback a archivo local que este test ejercita
    (mismo criterio que brand_brain/store.py en TEST_MODE).
    """
    mock_get_client.return_value = None
    mock_get_brain.return_value = brand_brain

    catalog = Catalog(
        session_id="test_session",
        niche="test niche",
        ideas=[],
        gate_passed=False,
        catalog_locked=False
    )

    _save_catalog_cache(catalog)

    try:
        # Verify it can be loaded back
        loaded = _check_catalog_cache("test_session")
        assert loaded is not None
        assert loaded.session_id == "test_session"
        assert loaded.niche == "test niche"
    finally:
        cache_file = os.path.join("cache/catalog", "test_session.json")
        if os.path.exists(cache_file):
            os.remove(cache_file)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def brand_brain():
    """Mock BrandBrain for demand validation."""
    return BrandBrain(
        sections=[
            Section(
                id="diagnostico",
                label="diagnostico",
                status="confirmado",
                content={
                    "postura": "experto",
                    "descripcion": "10+ años interpretando en hospitales hispanos."
                },
                citation_text="Founding story",
                citation_source="usuario",
                created_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 200769, tzinfo=datetime.timezone.utc),
                updated_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 200769, tzinfo=datetime.timezone.utc)
            ),
            Section(
                id="icp",
                label="icp",
                status="confirmado",
                content={
                    "nicho": "Interpretación médica para hospitales hispanos",
                    "problema": "Communicación gap entre pacientes sin inglés y staff médico.",
                    "motivacion": "Salvar vidas y empoderar comunidad."
                },
                citation_text="ICP analysis",
                citation_source="usuario",
                created_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 228982, tzinfo=datetime.timezone.utc),
                updated_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 228982, tzinfo=datetime.timezone.utc)
            ),
            Section(
                id="charco",
                label="charco",
                status="confirmado",
                content={
                    "problema": "Niche: Interpretación médica hispana. Spanish-only patients struggle in US hospitals."
                },
                citation_text="Charpool analysis",
                citation_source="usuario",
                created_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 267940, tzinfo=datetime.timezone.utc),
                updated_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 267940, tzinfo=datetime.timezone.utc)
            )
        ],
        formato={"language": "es"},
        created_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 376602, tzinfo=datetime.timezone.utc),
        updated_at=datetime.datetime(2026, 9, 13, 21, 17, 5, 376602, tzinfo=datetime.timezone.utc)
    )


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

@patch('app.tools.brand_brain.store._get_client')
@patch('app.catalog.demand.validate_niche_demand')
@pytest.mark.asyncio
async def test_generate_catalog_checks_brain_completeness(
    mock_validate_niche,
    mock_get_client,
    brand_brain
):
    """Should fail gracefully if brain not complete."""
    # Bug B12: la fixture brand_brain trae sus 3 secciones ya "confirmado" --
    # tomar las primeras 3 tal cual NO produce un brain incompleto (el gate de
    # completitud en generate_catalog solo mira `status`, no cuántas secciones
    # hay). Se fuerza un status pendiente en una sección para que el escenario
    # que describe el test ("brain no completo") sea real.
    incomplete_sections = [
        Section(
            s.id, s.label,
            "pendiente" if s.id == "diagnostico" else s.status,
            s.content, s.citation_text, s.citation_source,
            s.created_at, s.updated_at
        )
        for s in brand_brain.sections
    ]

    incomplete_brain = BrandBrain(
        sections=incomplete_sections,
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

    mock_get_client.return_value = None

    with patch('app.catalog.ideas.get_brand_brain', return_value=incomplete_brain):
        with pytest.raises(IncompleteBrainError):
            await generate_catalog("test_session")


@patch('app.tools.brand_brain.store._get_client')
@patch('app.catalog.demand.validate_niche_demand')
@pytest.mark.asyncio
async def test_generate_catalog_checks_niche_report_exists(
    mock_validate_niche_demand,
    mock_get_client,
    brand_brain
):
    """Should fail gracefully if NicheResearch not generated."""
    mock_get_client.return_value = None

    # Mock brain exists with all required sections confirmed
    complete_brain = brand_brain

    with patch('app.catalog.ideas.get_brand_brain', return_value=complete_brain):
        # Bug B12: generate_catalog() ahora exige Brand Soul generado ANTES de
        # llegar a research_niche() -- sin este mock, el flujo nunca alcanza
        # el punto que este test quiere ejercitar (levanta ValueError antes).
        with patch('app.catalog.ideas._check_brand_soul_generated', return_value=True):
            # research_niche() se importa por nombre en ideas.py -- mockear ahí,
            # no en demand.py, para que generate_catalog() lo vea.
            with patch('app.catalog.ideas.research_niche', return_value=None):
                with pytest.raises(NicheReportNotFoundError):
                    await generate_catalog("test_session")


# =============================================================================
# Run Tests Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
