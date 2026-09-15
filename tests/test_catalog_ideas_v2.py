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
    """
    Mock NicheResearch for testing.

    NOTE (bug found while fixing B1/B2/B6): esta fixture nunca se usaba en
    ningún test antes -- traía trends_series/trends_related con tuplas/strings
    en vez de dicts, lo que la hace inválida contra el modelo real
    (`List[dict]`). Se corrige para que quede utilizable por los nuevos tests
    de regresión.
    """
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
            {"date": "2023-01", "value": 100},
            {"date": "2023-02", "value": 95},
            {"date": "2023-03", "value": 110}
        ],
        trends_related=[
            {"query": "medical interpreter certification", "value": 100},
            {"query": "hospital interpretation services", "value": 80}
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
    """
    Catalog should enforce MAX_IDEAS (45), not TOTAL_IDEAS (30).

    Pieza 29 (punto B): TOTAL_IDEAS=30 sigue siendo el objetivo exacto de la
    generación por LLM; MAX_IDEAS=45 es el techo real del catálogo una vez
    que se permiten hasta 15 ideas manuales del fundador encima de las 30.
    """
    from app.catalog.ideas import MAX_IDEAS

    ideas = [
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Any",
            title=f"Idea Number {i}",
            demand_signal=f"Signal Number {i}"
        )
        for i in range(MAX_IDEAS + 1)
    ]

    with pytest.raises(ValueError, match=f"Máximo {MAX_IDEAS} ideas"):
        Catalog(
            session_id="test",
            niche="test",
            ideas=ideas
        )


def test_catalog_allows_more_than_30_up_to_max_ideas():
    """30 generated + manual founder ideas up to MAX_IDEAS must be accepted."""
    from app.catalog.ideas import TOTAL_IDEAS, MAX_IDEAS

    ideas = [
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Any",
            title=f"Idea Number {i}",
            demand_signal=f"Signal Number {i}"
        )
        for i in range(TOTAL_IDEAS + 5)  # 30 generadas + 5 manuales
    ]
    assert TOTAL_IDEAS + 5 <= MAX_IDEAS

    catalog = Catalog(session_id="test", niche="test", ideas=ideas)
    assert catalog.idea_count == TOTAL_IDEAS + 5


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
    icp = {"quien_decide": "interpretación médica"}
    charco = {"problema": "Cualquier cosa"}

    # Bug B12: _extract_niche() exige 3 args (icp, charco, diagnostico).
    niche = _extract_niche(icp, charco, {})
    assert "interpretación" in niche.lower()


def test_extract_niche_from_charco():
    """Should fall back to charco if ICP empty."""
    icp = {"quien_decide": ""}
    charco = {"problema": "Niche: liderazgo ejecutivo estrategico responsable decisiones"}

    niche = _extract_niche(icp, charco, {})
    assert niche.strip() != ""


# =============================================================================
# Cache Tests
# =============================================================================

@patch('app.catalog.ideas._get_catalog_client', return_value=None)
@patch('app.catalog.ideas.get_brand_brain')
def test_save_and_load_cache(mock_get_brain, mock_catalog_client, brand_brain, tmp_path, monkeypatch):
    """
    Should save and load catalog from cache.

    Pieza 29: se mockea _get_catalog_client() a None para forzar el fallback
    a archivo local (Supabase no configurado en tests).
    """
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
# Bug regression tests: B1 (single research call), B2 (bounded fill loop),
# B4 (shared Vertex AI client), B6 (no text-fallback parser).
# =============================================================================


@patch('app.catalog.ideas.get_brand_brain')
@patch('app.catalog.ideas._check_brand_soul_generated', return_value=True)
@pytest.mark.asyncio
async def test_generate_catalog_reuses_passed_niche_research(
    mock_soul, mock_get_brain, brand_brain, niche_research_sample
):
    """
    Bug B1: si el llamador ya calculó un NicheResearch, generate_catalog()
    NO debe volver a llamar research_niche() -- evita la doble llamada que
    duplicaba el costo/latencia de /investigate.
    """
    mock_get_brain.return_value = brand_brain

    with patch('app.catalog.ideas.research_niche') as mock_research:
        with patch(
            'app.catalog.ideas._generate_ideas_for_category',
            new=AsyncMock(return_value=[
                CatalogIdea(
                    master_category="autoridad_tecnica",
                    subcategory="Top N",
                    title=f"Idea {i}",
                    demand_signal="Valid signal from research"
                ) for i in range(12)
            ])
        ):
            catalog = await generate_catalog("test_session", niche_research=niche_research_sample)

    mock_research.assert_not_called()
    assert catalog.niche is not None


@patch('app.catalog.ideas.get_brand_brain')
@patch('app.catalog.ideas._check_brand_soul_generated', return_value=True)
@pytest.mark.asyncio
async def test_generate_catalog_fill_loop_is_bounded(
    mock_soul, mock_get_brain, brand_brain, niche_research_sample
):
    """
    Bug B2 regression: si el LLM nunca devuelve ideas (siempre []), el loop de
    relleno debe TERMINAR (no colgarse hasta el timeout de 120s del endpoint)
    y dejar gate_passed=False en vez de ideas inventadas.
    """
    mock_get_brain.return_value = brand_brain

    with patch(
        'app.catalog.ideas._generate_ideas_for_category',
        new=AsyncMock(return_value=[])
    ) as mock_gen:
        catalog = await generate_catalog("test_session", niche_research=niche_research_sample)

    assert catalog.gate_passed is False
    assert len(catalog.ideas) == 0
    # 4 categorías (llamada inicial) + como máximo 2 rondas de relleno * 4
    # categorías = 12 llamadas totales, nunca "cuelga" llamando sin fin.
    assert mock_gen.call_count <= 12


def test_get_vertex_ai_client_reuses_shared_helper():
    """
    Bug B4: ideas._get_vertex_ai_client() debe delegar en
    brand_soul.generator._get_vertex_ai_client() (mismo modelo/proyecto que
    el resto de la app), no reimplementar su propia inicialización con
    GOOGLE_CLOUD_PROJECT (que nunca está poblado en este proyecto) ni un
    modelo hardcodeado retirado (gemini-2.0-flash-exp).
    """
    from app.catalog import ideas
    sentinel = object()
    with patch('app.tools.brand_soul.generator._get_vertex_ai_client', return_value=sentinel) as mock_shared:
        result = ideas._get_vertex_ai_client()
    mock_shared.assert_called_once()
    assert result is sentinel


@pytest.mark.asyncio
async def test_generate_ideas_for_category_returns_empty_on_invalid_json(niche_research_sample):
    """
    Bug B6 regression: si el LLM no devuelve JSON válido (aunque se pida
    response_mime_type="application/json"), no se inventan ideas con un
    fallback de texto -- se devuelve [] y el gate honesto lo reporta.
    """
    from app.catalog.ideas import _generate_ideas_for_category

    with patch(
        'app.catalog.ideas._call_llm_with_prompt',
        new=AsyncMock(return_value="```json\nesto no es json valido")
    ):
        result = await _generate_ideas_for_category(
            niche="interpretación médica",
            master_category="autoridad_tecnica",
            subcategories=["Top N/Listículo técnico"],
            niche_research=niche_research_sample,
            approach="experto",
            count=3
        )

    assert result == []


# =============================================================================
# Bug regression tests: R4 (lying gate), R5 (no invented figures in prompt).
# =============================================================================


@patch('app.catalog.ideas.get_brand_brain')
@patch('app.catalog.ideas._check_brand_soul_generated', return_value=True)
@pytest.mark.asyncio
async def test_generate_catalog_raises_when_all_research_sources_empty(
    mock_soul, mock_get_brain, brand_brain
):
    """
    Bug R4 regression: si NicheResearch viene con las 4 fuentes vacías,
    generate_catalog() debe fallar con ValueError ANTES de llamar al LLM --
    en producción esto generaba 30 ideas con demand_signal literal
    "No hay señales específicas." (el LLM copiaba el placeholder del prompt).
    """
    from app.catalog.demand import NicheResearch

    mock_get_brain.return_value = brand_brain
    empty_research = NicheResearch(niche="nicho sin señales")

    with patch('app.catalog.ideas._generate_ideas_for_category') as mock_gen:
        with pytest.raises(ValueError, match="No se pudo obtener señales de demanda reales"):
            await generate_catalog("test_session", niche_research=empty_research)

    # Nunca se debe haber llamado al LLM -- se corta ANTES.
    mock_gen.assert_not_called()


@pytest.mark.parametrize("placeholder", [
    "No hay señales específicas.",
    "Demanda detectada en investigación de nicho",
])
def test_catalog_idea_placeholder_signal_is_recognized(placeholder):
    """
    Bug R4 regression: el gate debe reconocer los placeholders/fallbacks
    conocidos (sin importar mayúsculas/minúsculas ni el punto final) para
    poder rechazarlos -- antes una idea con este demand_signal pasaba el gate
    como si fuera una señal real.
    """
    from app.catalog.ideas import PLACEHOLDER_DEMAND_SIGNALS

    assert placeholder.strip().lower() in PLACEHOLDER_DEMAND_SIGNALS


@patch('app.catalog.ideas.get_brand_brain')
@patch('app.catalog.ideas._check_brand_soul_generated', return_value=True)
@pytest.mark.asyncio
async def test_generate_catalog_gate_fails_if_llm_copies_placeholder(
    mock_soul, mock_get_brain, brand_brain, niche_research_sample
):
    """
    Bug R4 regression end-to-end: aunque haya 30 ideas "completas", si el LLM
    copió el placeholder como demand_signal el gate_passed debe quedar en
    False (nunca True con una demanda que en realidad es un texto de relleno).
    """
    mock_get_brain.return_value = brand_brain

    fake_ideas = [
        CatalogIdea(
            master_category="autoridad_tecnica",
            subcategory="Top N",
            title=f"Idea {i}",
            demand_signal="No hay señales específicas."
        )
        for i in range(30)
    ]

    async def fake_generate(*args, **kwargs):
        count = kwargs.get("count", 1)
        return fake_ideas[:count]

    with patch('app.catalog.ideas._generate_ideas_for_category', side_effect=fake_generate):
        catalog = await generate_catalog("test_session", niche_research=niche_research_sample)

    assert catalog.gate_passed is False


def test_prompt_forbids_invented_figures_and_clients():
    """
    Bug R5 regression: el prompt de generación de ideas debe prohibir
    explícitamente inventar cifras/porcentajes/clientes -- el LLM había
    inventado "$500K anuales", "Reducción del 25%" y "cliente X" sin que
    ninguna de esas cifras viniera de NicheResearch.
    """
    from app.catalog.ideas import _build_idea_generation_prompt

    prompt = _build_idea_generation_prompt(
        niche="interpretación médica",
        master_category="validacion_resultados",
        subcategories=["Antes/Después con métricas"],
        niche_research=NicheResearch(niche="interpretación médica"),
        approach="experto",
        count=9
    )

    lower = prompt.lower()
    assert "no inventes cifras" in lower
    assert "porcentajes" in lower
    assert "clientes" in lower


# =============================================================================
# Run Tests Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
