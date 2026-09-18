"""
Tests for Piece 27 endpoints (investigate, accept, discard, regenerate, lock).
"""
import os

os.environ.setdefault("TEST_MODE", "true")

import pytest
import datetime
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from app.catalog.ideas import CatalogIdea, Catalog, _save_catalog_cache
from app.catalog.demand import NicheResearch
from app.tools.brand_brain.models import BrandBrain, Section
from app.guard import guard
from app.main import app


@pytest.fixture(autouse=True)
def _no_real_supabase_for_catalog():
    """
    Pieza 29: _check_catalog_cache()/_save_catalog_cache() ahora intentan
    Supabase (tabla `catalogs`) antes del archivo local. Este repo tiene
    credenciales reales de Supabase en el entorno de desarrollo, así que sin
    este mock todos los tests de este archivo pegarían contra la red de
    verdad. Se fuerza el fallback a archivo local para todos los tests de
    este módulo (mismo criterio que brand_brain/store.py en TEST_MODE).
    """
    with patch('app.catalog.ideas._get_catalog_client', return_value=None):
        yield


@pytest.fixture
def sample_brand_sections():
    return [
        Section(
            id="diagnostico",
            label="diagnostico",
            status="confirmado",
            content={"postura": "experto", "descripcion": "Fundador con experiencia."},
            citation_text="Texto",
            citation_source="usuario",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        ),
        Section(
            id="icp",
            label="icp",
            status="confirmado",
            content={"nicho": "salud digital"},
            citation_text="Texto",
            citation_source="usuario",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        ),
        Section(
            id="charco",
            label="charco",
            status="confirmado",
            content={"problema": "problema en salud"},
            citation_text="Texto",
            citation_source="usuario",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
    ]


@pytest.fixture
def brand_brain(sample_brand_sections):
    return BrandBrain(
        sections=sample_brand_sections,
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.fixture
def sample_catalog():
    return Catalog(
        session_id="test_session_27",
        niche="salud digital",
        ideas=[
            CatalogIdea(
                id=f"idea_{i}",
                master_category="autoridad_tecnica",
                subcategory="Top N",
                title=f"Título de prueba {i}",
                demand_signal="Demanda detectada en salud",
                status="pending"
            )
            for i in range(30)
        ],
        gate_passed=True
    )


@pytest.mark.asyncio
async def test_update_idea_status_accept_and_discard(sample_catalog, brand_brain):
    with patch('app.catalog.ideas.get_brand_brain', return_value=brand_brain):
        _save_catalog_cache(sample_catalog)

        from app.catalog.ideas import update_idea_status

        # Accept
        updated = await update_idea_status("test_session_27", "idea_0", "approved")
        assert updated.ideas[0].status == "approved"

        # Discard
        updated = await update_idea_status("test_session_27", "idea_1", "rejected")
        assert updated.ideas[1].status == "rejected"


def test_lock_catalog_fails_if_pending(sample_catalog, brand_brain):
    with patch('app.catalog.ideas.get_brand_brain', return_value=brand_brain):
        _save_catalog_cache(sample_catalog)

        from app.catalog.ideas import lock_catalog_session

        with pytest.raises(ValueError, match="aún en estado 'pending'"):
            lock_catalog_session("test_session_27")


def test_lock_catalog_succeeds_when_all_reviewed(sample_catalog, brand_brain):
    with patch('app.catalog.ideas.get_brand_brain', return_value=brand_brain):
        for idea in sample_catalog.ideas:
            idea.status = "approved"

        _save_catalog_cache(sample_catalog)

        from app.catalog.ideas import lock_catalog_session

        locked = lock_catalog_session("test_session_27")
        assert locked.catalog_locked is True


# =============================================================================
# Bug B10 regression: update_idea_status / regenerate_single_idea deben usar
# SOLO el cache, nunca disparar una generación completa gratis.
# =============================================================================


@pytest.mark.asyncio
async def test_update_idea_status_without_catalog_raises_value_error():
    """Bug B10: sin catálogo cacheado, debe fallar con ValueError, no generar uno gratis."""
    from app.catalog.ideas import update_idea_status

    with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
        with patch('app.catalog.ideas.generate_catalog') as mock_generate:
            with pytest.raises(ValueError, match="No catalog generated"):
                await update_idea_status("session_sin_catalogo", "idea_x", "approved")
            mock_generate.assert_not_called()


@pytest.mark.asyncio
async def test_regenerate_single_idea_without_catalog_raises_value_error():
    """Bug B10: mismo fix para regenerate_single_idea."""
    from app.catalog.ideas import regenerate_single_idea

    with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
        with patch('app.catalog.ideas.generate_catalog') as mock_generate:
            with pytest.raises(ValueError, match="No catalog generated"):
                await regenerate_single_idea("session_sin_catalogo", "idea_x")
            mock_generate.assert_not_called()


# =============================================================================
# Endpoint-level regression tests (TestClient) -- B1, B9, B11.
# Guard se mockea directamente (no se pega contra Supabase real) para que
# estos tests sean deterministas y no dependan de la red.
# =============================================================================


@pytest.fixture
def api_client():
    """
    TestClient con auth mockeada. NOTA: no se usa el flujo real de
    verify_token/JWKS aquí -- ese flujo ya está roto de forma independiente a
    esta pieza (ver test_guard_jwt.py, fuera de alcance de este fix) porque
    SupabaseAuth solo usa HS256 de test cuando se le pasa jwt_secret al
    constructor, y el singleton de producción nunca lo recibe. Mockear
    get_user_id evita depender de esa deuda para probar los bugs de catálogo.
    """
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch('app.auth.supabase_auth.supabase_auth.get_user_id', return_value='550e8400-e29b-41d4-a716-446655440000'):
        yield client


def test_investigate_insufficient_credits_returns_402_without_doing_work(api_client):
    """
    Bug B1: si el saldo no alcanza, /investigate debe responder 402 SIN
    llamar a research_niche()/generate_catalog() -- nunca se cobra por un
    trabajo que no se hizo.
    """
    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 5}):
            with patch.object(guard, 'get_remaining_credits', return_value=5):
                with patch('app.catalog.demand.research_niche') as mock_research:
                    response = api_client.post('/api/catalog/investigate')

    assert response.status_code == 402
    assert response.json()['credits_remaining'] == 5
    mock_research.assert_not_called()


def test_investigate_extracts_niche_with_three_args_and_charges_after_success(api_client):
    """
    Bug B1 regression: antes, `ideas._extract_niche(icp, charco)` (2 args)
    garantizaba un TypeError -> 500 en cada request, y los 25 créditos se
    cobraban ANTES de intentar generar. Ahora debe: (a) llamar
    _extract_niche con 3 argumentos, (b) disparar research_niche() una sola
    vez, (c) cobrar solo tras éxito.
    """
    from app.tools.brand_brain.models import BrandBrain, Section

    brain = BrandBrain(
        sections=[
            Section(id="diagnostico", label="diagnostico", status="confirmado",
                    content={"postura": "experto", "descripcion": "test"},
                    citation_text="c", citation_source="usuario",
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                    updated_at=datetime.datetime.now(datetime.timezone.utc)),
            Section(id="icp", label="icp", status="confirmado",
                    content={"quien_decide": "gerentes de salud digital"},
                    citation_text="c", citation_source="usuario",
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                    updated_at=datetime.datetime.now(datetime.timezone.utc)),
            Section(id="charco", label="charco", status="confirmado",
                    content={"problema": "problema en salud digital"},
                    citation_text="c", citation_source="usuario",
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                    updated_at=datetime.datetime.now(datetime.timezone.utc)),
        ],
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

    fake_research = NicheResearch(niche="gerentes de salud digital")
    fake_catalog = Catalog(session_id="sess_1", niche="gerentes de salud digital", ideas=[], gate_passed=False)

    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 100}):
            with patch.object(guard, 'get_remaining_credits', return_value=100):
                with patch.object(guard, 'deduct_credits', return_value=75) as mock_deduct:
                    with patch('app.tools.brand_brain.store.get_brand_brain', return_value=brain):
                        with patch('app.catalog.demand.research_niche', new=AsyncMock(return_value=fake_research)) as mock_research:
                            with patch('app.catalog.ideas.get_or_generate_catalog', new=AsyncMock(return_value=fake_catalog)) as mock_get_catalog:
                                response = api_client.post('/api/catalog/investigate')

    assert response.status_code == 200, response.text
    # _extract_niche ya no explota con TypeError -- se llegó hasta el final.
    mock_research.assert_called_once()
    # research_niche() se llamó UNA sola vez (no otra vez dentro de generate_catalog).
    assert mock_get_catalog.call_count == 1
    _, kwargs = mock_get_catalog.call_args
    assert kwargs.get('niche_research') is fake_research
    # Se cobra DESPUÉS del éxito, no antes.
    mock_deduct.assert_called_once_with('sess_1', amount=25)
    assert response.json()['credits_remaining'] == 75


def test_investigate_timeout_returns_504_without_charging(api_client):
    """Bug B1: un timeout de research_niche()/generate_catalog() no debe cobrar créditos."""
    import asyncio

    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 100}):
            with patch.object(guard, 'get_remaining_credits', return_value=100):
                with patch.object(guard, 'deduct_credits') as mock_deduct:
                    with patch('app.tools.brand_brain.store.get_brand_brain') as mock_brain:
                        mock_brain.return_value.get_section.return_value.content = {"quien_decide": "algo valido aqui"}
                        with patch('app.catalog.demand.research_niche', new=AsyncMock(side_effect=asyncio.TimeoutError)):
                            response = api_client.post('/api/catalog/investigate')

    assert response.status_code == 504
    mock_deduct.assert_not_called()


def test_regenerate_idea_insufficient_credits_returns_402_without_work(api_client):
    """Bug B9: sin saldo, /regenerate responde 402 sin llamar a regenerate_single_idea()."""
    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 1}):
            with patch.object(guard, 'get_remaining_credits', return_value=1):
                with patch('app.catalog.ideas.regenerate_single_idea') as mock_regen:
                    response = api_client.post('/api/catalog/idea/idea_0/regenerate')

    assert response.status_code == 402
    mock_regen.assert_not_called()


def test_regenerate_idea_generic_exception_returns_500_without_charging(api_client):
    """
    Bug B9: antes, una Exception genérica (no ValueError) no tenía handler y
    los 3 créditos ya se habían cobrado antes de llamar a la función. Ahora:
    500 con JSON de error y SIN cobrar.
    """
    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 50}):
            with patch.object(guard, 'get_remaining_credits', return_value=50):
                with patch.object(guard, 'deduct_credits') as mock_deduct:
                    with patch('app.catalog.ideas.regenerate_single_idea', new=AsyncMock(side_effect=Exception("boom"))):
                        response = api_client.post('/api/catalog/idea/idea_0/regenerate')

    assert response.status_code == 500
    assert "boom" in response.json()["error"]
    mock_deduct.assert_not_called()


def test_generate_cache_status_reflects_pre_generation_state(api_client):
    """
    Bug B11: cache_status debe reflejar el estado ANTES de generar, no
    después -- de lo contrario siempre reporta "hit" porque para cuando se
    consulta, get_or_generate_catalog() ya guardó el catálogo recién creado.
    """
    fake_catalog = Catalog(session_id="sess_1", niche="n", ideas=[], gate_passed=False)

    call_log = []

    def fake_check_cache(session_id):
        call_log.append("check")
        # Primera llamada (antes de generar): no hay cache. Segunda llamada
        # (si el código volviera a mirar el cache después de generar):
        # simula que ya existe, para probar que el endpoint NO usa ese valor.
        return None if len(call_log) == 1 else fake_catalog

    async def fake_get_or_generate(session_id, niche_research=None):
        # Al momento de generar, el cache seguía vacío -> "generated" es
        # la respuesta correcta, no "hit".
        return fake_catalog

    with patch.object(guard, 'get_or_create_user_session', return_value='sess_1'):
        with patch.object(guard, 'get_session', return_value={'credits': 100}):
            with patch.object(guard, 'deduct_credits', return_value=85):
                with patch('app.catalog.ideas._check_catalog_cache', side_effect=fake_check_cache):
                    with patch('app.catalog.ideas.get_or_generate_catalog', new=fake_get_or_generate):
                        response = api_client.post('/api/catalog/generate')

    assert response.status_code == 200, response.text
    assert response.json()["cache_status"] == "generated"
