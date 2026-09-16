"""
Tests for Pieza 30 (4 bugs del Catalogo, encontrados en QA real en produccion):

  B1. Regenerar una idea no debe repetir research_niche() si el catalogo ya
      trae un NicheResearch persistido; catalogos viejos sin el campo siguen
      funcionando (investigan una sola vez y lo guardan).
  B2. Senales de demanda: (a) classify_pain_from_comments() recibe el niche y
      excluye quejas sobre el video/canal/audio/produccion; (b) el prompt de
      ideas exige que el demand_signal respalde DIRECTAMENTE el titulo y
      prohibe placeholders; (c) el gate descarta titulos con "X%" o
      corchetes de placeholder antes de contarlos.
  B4. El copy del paywall refleja pago unico (mode="payment"), no suscripcion.
"""
import os

os.environ.setdefault("TEST_MODE", "true")

import datetime
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from app.catalog.ideas import (
    Catalog,
    CatalogIdea,
    _title_has_placeholder,
    _build_idea_generation_prompt,
)
from app.catalog.demand import NicheResearch
from app.tools.brand_brain.models import BrandBrain, Section


STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def brand_brain():
    return BrandBrain(
        sections=[
            Section(
                id="diagnostico", label="diagnostico", status="confirmado",
                content={"postura": "experto", "descripcion": "15 años operando hospitales"},
                citation_text="c", citation_source="usuario",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ),
            Section(
                id="icp", label="icp", status="confirmado",
                content={"quien_decide": "directores de operaciones clínicas"},
                citation_text="c", citation_source="usuario",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ),
            Section(
                id="charco", label="charco", status="confirmado",
                content={"problema": "hospitales pierden dinero por ineficiencia operativa"},
                citation_text="c", citation_source="usuario",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            ),
        ],
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.fixture
def sample_niche_research():
    return NicheResearch(
        niche="salud digital",
        youtube_pain_signals=["billing complexity", "compliance overhead"],
    )


def _make_catalog(niche_research=None):
    return Catalog(
        session_id="test_session_30",
        niche="salud digital",
        ideas=[
            CatalogIdea(
                id="idea_target",
                master_category="autoridad_tecnica",
                subcategory="Top N",
                title="Idea objetivo a regenerar",
                demand_signal="Señal real de más de diez caracteres",
                status="pending"
            )
        ],
        gate_passed=True,
        niche_research=niche_research,
    )


# =============================================================================
# B1 -- regenerar reutiliza el NicheResearch persistido
# =============================================================================

@pytest.mark.asyncio
async def test_regenerate_single_idea_reuses_persisted_niche_research(brand_brain, sample_niche_research):
    """
    Bug B1: si el catálogo ya trae niche_research, regenerate_single_idea()
    NO debe volver a llamar research_niche() (evita ~40s de investigación
    repetida que producía 520 en el proxy de producción).
    """
    from app.catalog.ideas import regenerate_single_idea

    catalog = _make_catalog(niche_research=sample_niche_research)

    with patch('app.catalog.ideas._check_catalog_cache', return_value=catalog):
        with patch('app.catalog.ideas._save_catalog_cache'):
            with patch('app.catalog.ideas.get_brand_brain', return_value=brand_brain):
                with patch('app.catalog.ideas.research_niche') as mock_research:
                    with patch(
                        'app.catalog.ideas._generate_ideas_for_category',
                        new=AsyncMock(return_value=[
                            CatalogIdea(
                                master_category="autoridad_tecnica",
                                subcategory="Top N",
                                title="Idea reemplazo",
                                demand_signal="Señal real de más de diez caracteres",
                            )
                        ])
                    ):
                        new_idea = await regenerate_single_idea("test_session_30", "idea_target")

    mock_research.assert_not_called()
    assert new_idea.title == "Idea reemplazo"


@pytest.mark.asyncio
async def test_regenerate_single_idea_investigates_once_for_old_catalog_without_research(brand_brain):
    """
    Bug B1: un catálogo viejo (niche_research=None, guardado antes de este
    campo) sigue funcionando -- investiga UNA vez y no explota.
    """
    from app.catalog.ideas import regenerate_single_idea

    old_catalog = _make_catalog(niche_research=None)
    fake_research = NicheResearch(niche="salud digital", youtube_titles=["v1"])

    with patch('app.catalog.ideas._check_catalog_cache', return_value=old_catalog):
        with patch('app.catalog.ideas._save_catalog_cache'):
            with patch('app.catalog.ideas.get_brand_brain', return_value=brand_brain):
                with patch(
                    'app.catalog.ideas.research_niche', new=AsyncMock(return_value=fake_research)
                ) as mock_research:
                    with patch(
                        'app.catalog.ideas._generate_ideas_for_category',
                        new=AsyncMock(return_value=[
                            CatalogIdea(
                                master_category="autoridad_tecnica",
                                subcategory="Top N",
                                title="Idea reemplazo vieja",
                                demand_signal="Señal real de más de diez caracteres",
                            )
                        ])
                    ):
                        new_idea = await regenerate_single_idea("test_session_30", "idea_target")

    mock_research.assert_called_once()
    assert new_idea.title == "Idea reemplazo vieja"


def test_generate_catalog_persists_niche_research_field(sample_niche_research):
    """
    Bug B1: generate_catalog() debe guardar el niche_research usado en el
    Catalog resultante -- se verifica vía roundtrip de serialización
    (_catalog_to_row / _row_to_catalog), mismo contrato que Supabase.
    """
    from app.catalog.ideas import _catalog_to_row, _row_to_catalog

    catalog = _make_catalog(niche_research=sample_niche_research)
    row = _catalog_to_row(catalog)

    assert row["data"]["niche_research"] is not None
    assert row["data"]["niche_research"]["niche"] == "salud digital"

    restored = _row_to_catalog(row, "test_session_30")
    assert restored is not None
    assert restored.niche_research is not None
    assert restored.niche_research.youtube_pain_signals == ["billing complexity", "compliance overhead"]


def test_row_to_catalog_handles_missing_niche_research_key():
    """Bug B1: catálogos viejos sin la clave "niche_research" en absoluto siguen cargando."""
    from app.catalog.ideas import _catalog_to_row, _row_to_catalog

    catalog = _make_catalog(niche_research=None)
    row = _catalog_to_row(catalog)
    del row["data"]["niche_research"]  # simula una fila persistida antes de esta pieza

    restored = _row_to_catalog(row, "test_session_30")
    assert restored is not None
    assert restored.niche_research is None


# =============================================================================
# B2 (a) -- classify_pain_from_comments recibe niche y excluye ruido de video
# =============================================================================

@pytest.mark.asyncio
async def test_classify_pain_from_comments_prompt_includes_niche_and_excludes_video_noise():
    """
    Bug B2 (a): el prompt debe mencionar el niche explícitamente y contener
    las reglas de exclusión de quejas sobre video/canal/audio/producción.
    """
    from unittest.mock import Mock
    from app.catalog.demand import classify_pain_from_comments

    mock_response = Mock(text='["billing complexity"]')
    mock_model = Mock()
    mock_model.generate_content_async = AsyncMock(return_value=mock_response)

    comments = [
        {"text": "difficulty finding content"},
        {"text": "low video quality"},
        {"text": "billing is way too complex for my clinic"},
    ]

    with patch('app.tools.brand_soul.generator._get_vertex_ai_client', return_value=mock_model):
        result = await classify_pain_from_comments("Test Video", comments, "HIPAA compliance for clinics")

    assert mock_model.generate_content_async.call_count == 1
    prompt_arg = mock_model.generate_content_async.call_args[0][0]
    assert "HIPAA compliance for clinics" in prompt_arg
    assert "video" in prompt_arg.lower()
    assert "audio" in prompt_arg.lower()
    assert "English" in prompt_arg
    assert result == ["billing complexity"]


@pytest.mark.asyncio
async def test_classify_pain_from_comments_requires_niche_argument():
    """Bug B2 (a): la firma ahora exige `niche` -- llamarla sin él debe fallar."""
    from app.catalog.demand import classify_pain_from_comments

    with pytest.raises(TypeError):
        await classify_pain_from_comments("Test Video", [{"text": "x"}])


# =============================================================================
# B2 (b) -- el prompt de ideas exige señal directa y prohíbe placeholders
# =============================================================================

def test_idea_generation_prompt_requires_direct_signal_and_forbids_placeholders():
    prompt = _build_idea_generation_prompt(
        niche="salud digital",
        master_category="autoridad_tecnica",
        subcategories=["Top N/Listículo técnico"],
        niche_research=NicheResearch(niche="salud digital"),
        approach="experto",
        count=3,
    )

    assert "respalda DIRECTAMENTE ese título" in prompt
    assert "NO generes esa idea" in prompt
    assert "X%" in prompt
    assert "corchetes" in prompt


# =============================================================================
# B2 (c) -- gate descarta títulos con "X%" o corchetes de placeholder
# =============================================================================

@pytest.mark.parametrize("title,expected", [
    ("Cómo reducir el tiempo de espera en X% en tu hospital", True),
    ("Cómo [Nombre del Hospital] mejoró su operación", True),
    ("Reduce N clientes perdidos con [dato aquí]", True),
    ("Cómo reducir el tiempo de espera en tu hospital", False),
    ("5 señales de que tu clínica pierde dinero", False),
])
def test_title_has_placeholder(title, expected):
    assert _title_has_placeholder(title) is expected


@pytest.mark.asyncio
async def test_generate_ideas_for_category_filters_placeholder_titles(sample_niche_research):
    """
    Bug B2 (c): una idea con "X%" en el título y otra con corchetes se
    descartan antes de contarlas; solo la idea limpia sobrevive.
    """
    from app.catalog.ideas import _generate_ideas_for_category

    fake_response = (
        '{"ideas": ['
        '{"subcategory": "Top N/Listículo técnico", "title": "Reduce tus costos en X%", '
        '"demand_signal": "Señal real de más de diez caracteres"},'
        '{"subcategory": "Top N/Listículo técnico", "title": "Cómo [Cliente] logró resultados", '
        '"demand_signal": "Señal real de más de diez caracteres"},'
        '{"subcategory": "Top N/Listículo técnico", "title": "Cómo reducir el tiempo de espera clínico", '
        '"demand_signal": "Señal real de más de diez caracteres"}'
        ']}'
    )

    with patch('app.catalog.ideas._call_llm_with_prompt', new=AsyncMock(return_value=fake_response)):
        ideas = await _generate_ideas_for_category(
            niche="salud digital",
            master_category="autoridad_tecnica",
            subcategories=["Top N/Listículo técnico"],
            niche_research=sample_niche_research,
            approach="experto",
            count=3,
        )

    assert len(ideas) == 1
    assert ideas[0].title == "Cómo reducir el tiempo de espera clínico"


# =============================================================================
# B4 -- copy del paywall refleja pago único, no suscripción
# =============================================================================

def test_paywall_copy_reflects_one_time_purchase_not_subscription():
    """
    Bug B4: billing.py usa mode="payment" (pago único) -- el copy del modal
    no debe decir "/mo", "monthly" ni "credits/mo" en ningún plan.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    paywall_start = html.index('id="Paywall-Overlay"')
    paywall_end = html.index("</div>\n\n<!-- Brand Soul Document Overlay", paywall_start)
    paywall_block = html[paywall_start:paywall_end]

    assert "/mo" not in paywall_block
    assert "monthly" not in paywall_block.lower()
    assert "credits/mo" not in paywall_block
    assert "one-time" in paywall_block.lower()
    assert "no subscription" in paywall_block.lower()
    assert "$9" in paywall_block
    assert "550 credits" in paywall_block


# =============================================================================
# B3 -- botones WebSearch/YouTube/Trends eliminados de app.js
# =============================================================================

def test_app_js_no_longer_renders_research_buttons():
    """
    Bug B3: el render de `.research-actions` y sus botones WebSearch/YouTube/
    Trends se eliminaron de buildIdeaCardHTML() -- cobraban 25 créditos y
    solo mostraban un alert. El endpoint /api/catalog/investigate se queda
    intacto en el backend (no se toca desde app.js).
    """
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "research-actions" not in js
    assert "research-btn" not in js
    assert 'data-research="websearch"' not in js
    assert 'data-research="youtube"' not in js
    assert 'data-research="trends"' not in js
