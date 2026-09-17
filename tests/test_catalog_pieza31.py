"""
Tests for Pieza 31 (8 bugs reales encontrados por auditoría QA + verificados
por el Arquitecto):

  B1. Un catálogo ya guardado NO se cobra de nuevo en /generate ni en
      /investigate (y /investigate no repite research_niche()).
  B2. /generate verifica saldo ANTES de llamar al LLM (402 sin trabajo).
  B3. Un fallo real de lectura/escritura de Supabase levanta
      CatalogStorageError -- nunca se confunde con "no hay catálogo", y los
      endpoints la convierten en 503 sin cobrar.
  B4. subcategory se valida contra las subcategorías permitidas de la
      categoría elegida (backend). El escapeHtml del frontend se cubre con
      asserts estáticos sobre app.js (mismo patrón que test_catalog_pieza30).
  B5, B6, B7. Fixes puntuales de app.js (updateCreditsUI con argumentos,
      currentCatalog declarada, guard dataset.wired en el botón de lock) --
      cubiertos con asserts estáticos sobre el archivo, igual que B4.

B8 (idempotencia de webhooks + add_credits atómico) vive en
tests/test_webhooks.py, no aquí.
"""
import os

os.environ.setdefault("TEST_MODE", "true")

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.catalog.ideas import (
    Catalog,
    CatalogIdea,
    CatalogStorageError,
    MASTER_CATEGORIES,
    CREDITS_COST,
    _check_catalog_cache,
    _save_catalog_cache,
)
from app.catalog.demand import NicheResearch
from app.guard import guard
from app.main import app


STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


@pytest.fixture(autouse=True)
def _no_real_supabase_for_catalog():
    """
    Mismo criterio que test_catalog_pieza27.py: este entorno de desarrollo
    tiene credenciales reales de Supabase -- sin este mock, cualquier test
    que no mockee `_get_catalog_client` explícitamente pegaría contra la red
    real. Los tests de B3 que SÍ quieren ejercitar una falla de Supabase
    mockean su propio cliente con un `with patch(...)` anidado, que gana
    sobre este de aquí.
    """
    with patch('app.catalog.ideas._get_catalog_client', return_value=None):
        yield


@pytest.fixture
def api_client():
    """Mismo patrón que test_catalog_pieza27.py / pieza29.py."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch('app.auth.supabase_auth.supabase_auth.get_user_id', return_value='550e8400-e29b-41d4-a716-446655440000'):
        with patch.object(guard, 'get_or_create_user_session', return_value='test_session_31'):
            yield client


def _make_catalog(n=5, niche_research=None):
    return Catalog(
        session_id="test_session_31",
        niche="salud digital",
        ideas=[
            CatalogIdea(
                id=f"idea_{i}",
                master_category="autoridad_tecnica",
                subcategory="Top N/Listículo técnico",
                title=f"Título de prueba {i}",
                demand_signal="Demanda detectada en salud",
                status="pending",
            )
            for i in range(n)
        ],
        gate_passed=(n >= 30),
        niche_research=niche_research,
    )


# =============================================================================
# B1 -- catálogo ya guardado no se cobra de nuevo
# =============================================================================

def test_generate_endpoint_returns_cached_catalog_without_charging(api_client):
    """
    Bug B1: si ya existe un catálogo guardado (cualquier tamaño), /generate
    lo devuelve tal cual, con cache_status="hit", SIN llamar a
    get_or_generate_catalog() (que dispara al LLM) y SIN deducir créditos.
    """
    cached_catalog = _make_catalog(n=5)  # menos de 30 -- el caso del bug real

    with patch.object(guard, 'get_session', return_value={'credits': 42}):
        with patch.object(guard, 'get_remaining_credits', return_value=42):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch('app.catalog.ideas._check_catalog_cache', return_value=cached_catalog):
                    with patch('app.catalog.ideas.get_or_generate_catalog') as mock_generate:
                        response = api_client.post('/api/catalog/generate')

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cache_status"] == "hit"
    assert body["credits_remaining"] == 42
    assert len(body["catalog"]["ideas"]) == 5
    mock_deduct.assert_not_called()
    mock_generate.assert_not_called()


def test_investigate_endpoint_returns_cached_catalog_without_charging_or_research(api_client):
    """
    Bug B1: si ya existe un catálogo (con o sin niche_research persistido),
    /investigate lo devuelve tal cual -- SIN llamar a research_niche() (~40-90s)
    ni cobrar los 25 créditos.
    """
    niche_research = NicheResearch(niche="salud digital", youtube_pain_signals=["billing"])
    cached_catalog = _make_catalog(n=10, niche_research=niche_research)

    with patch.object(guard, 'get_session', return_value={'credits': 77}):
        with patch.object(guard, 'get_remaining_credits', return_value=77):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch('app.catalog.ideas._check_catalog_cache', return_value=cached_catalog):
                    with patch('app.catalog.demand.research_niche') as mock_research:
                        response = api_client.post('/api/catalog/investigate')

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cache_status"] == "hit"
    assert body["credits_remaining"] == 77
    assert body["niche_research"]["niche"] == "salud digital"
    mock_deduct.assert_not_called()
    mock_research.assert_not_called()


# =============================================================================
# B2 -- /generate verifica saldo ANTES de generar
# =============================================================================

def test_generate_endpoint_checks_balance_before_calling_llm(api_client):
    """
    Bug B2: sin catálogo cacheado y con saldo insuficiente, /generate debe
    responder 402 SIN llamar a get_or_generate_catalog() (que dispara al
    LLM) -- antes se generaba primero y deduct_credits() fallaba DESPUÉS,
    dejando un catálogo persistido sin cobrar (gratis en el siguiente GET).
    """
    with patch.object(guard, 'get_session', return_value={'credits': CREDITS_COST - 1}):
        with patch.object(guard, 'get_remaining_credits', return_value=CREDITS_COST - 1):
            with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
                with patch('app.catalog.ideas.get_or_generate_catalog') as mock_generate:
                    with patch.object(guard, 'deduct_credits') as mock_deduct:
                        response = api_client.post('/api/catalog/generate')

    assert response.status_code == 402, response.text
    assert response.json()["credits_remaining"] == CREDITS_COST - 1
    mock_generate.assert_not_called()
    mock_deduct.assert_not_called()


def test_generate_endpoint_proceeds_when_balance_sufficient(api_client):
    """Control: con saldo suficiente y sin cache, sí genera y cobra."""
    fake_catalog = _make_catalog(n=30)

    with patch.object(guard, 'get_session', return_value={'credits': CREDITS_COST}):
        with patch.object(guard, 'get_remaining_credits', return_value=CREDITS_COST):
            with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
                with patch('app.catalog.ideas.get_or_generate_catalog', new=AsyncMock(return_value=fake_catalog)) as mock_generate:
                    with patch.object(guard, 'deduct_credits', return_value=0) as mock_deduct:
                        response = api_client.post('/api/catalog/generate')

    assert response.status_code == 200, response.text
    assert response.json()["cache_status"] == "generated"
    mock_generate.assert_called_once()
    mock_deduct.assert_called_once_with('test_session_31', amount=CREDITS_COST)


# =============================================================================
# B3 -- CatalogStorageError: fallo real de Supabase, nunca "no hay catálogo"
# =============================================================================

def test_check_catalog_cache_raises_storage_error_on_supabase_read_failure():
    """
    Bug B3: una excepción real al leer Supabase (timeout, red, credenciales)
    debe levantar CatalogStorageError, NUNCA devolver None silenciosamente
    -- None es indistinguible de "no hay catálogo todavía" y dispara una
    regeneración que pisa el catálogo real.
    """
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("network down")

    with patch('app.catalog.ideas._get_catalog_client', return_value=mock_client):
        with pytest.raises(CatalogStorageError):
            _check_catalog_cache("any_session")


def test_save_catalog_cache_raises_storage_error_on_supabase_write_failure():
    """
    Bug B3: una escritura fallida debe levantar CatalogStorageError -- antes
    devolvía silenciosamente como si hubiera guardado, y accept/discard/lock
    respondían 200 sin persistir nada.
    """
    mock_client = MagicMock()
    mock_client.table.return_value.upsert.return_value.execute.side_effect = Exception("network down")

    catalog = _make_catalog(n=3)

    with patch('app.catalog.ideas._get_catalog_client', return_value=mock_client):
        with pytest.raises(CatalogStorageError):
            _save_catalog_cache(catalog)


def test_generate_endpoint_returns_503_on_storage_error_without_charging(api_client):
    """Bug B3: el endpoint /generate convierte CatalogStorageError en 503 y nunca cobra."""
    with patch.object(guard, 'get_session', return_value={'credits': 100}):
        with patch.object(guard, 'deduct_credits') as mock_deduct:
            with patch('app.catalog.ideas._check_catalog_cache', side_effect=CatalogStorageError("boom")):
                response = api_client.post('/api/catalog/generate')

    assert response.status_code == 503, response.text
    assert "boom" in response.json()["error"]
    mock_deduct.assert_not_called()


def test_investigate_endpoint_returns_503_on_storage_error_without_charging(api_client):
    """Bug B3: mismo criterio para /investigate."""
    with patch.object(guard, 'get_session', return_value={'credits': 100}):
        with patch.object(guard, 'deduct_credits') as mock_deduct:
            with patch('app.catalog.ideas._check_catalog_cache', side_effect=CatalogStorageError("boom")):
                response = api_client.post('/api/catalog/investigate')

    assert response.status_code == 503, response.text
    assert "boom" in response.json()["error"]
    mock_deduct.assert_not_called()


def test_get_catalog_endpoint_returns_503_on_storage_error_not_404(api_client):
    """
    Bug B3: GET /api/catalog debe distinguir "falló la lectura" (503) de "no
    existe todavía" (404) -- un 404 falso dispararía una regeneración
    cobrada en el frontend para un catálogo que en realidad SÍ existe.
    """
    from app.tools.brand_brain.models import BrandBrain, Section
    import datetime

    brain = BrandBrain(
        sections=[
            Section(id="diagnostico", label="diagnostico", status="confirmado", content={"x": "y"},
                    citation_text="c", citation_source="usuario",
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                    updated_at=datetime.datetime.now(datetime.timezone.utc)),
        ],
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )

    with patch('app.tools.brand_brain.store.get_brand_brain', return_value=brain):
        with patch('app.catalog.ideas._check_catalog_cache', side_effect=CatalogStorageError("boom")):
            response = api_client.get('/api/catalog')

    assert response.status_code == 503, response.text
    assert "boom" in response.json()["error"]


def test_accept_idea_endpoint_returns_503_on_storage_error(api_client):
    """Bug B3: accept también convierte CatalogStorageError en 503, no 200 fantasma."""
    with patch('app.catalog.ideas.update_idea_status', new=AsyncMock(side_effect=CatalogStorageError("boom"))):
        response = api_client.post('/api/catalog/idea/idea_0/accept')

    assert response.status_code == 503, response.text
    assert "boom" in response.json()["error"]


def test_lock_catalog_endpoint_returns_503_on_storage_error(api_client):
    """Bug B3: lock también convierte CatalogStorageError en 503."""
    with patch('app.catalog.ideas.lock_catalog_session', side_effect=CatalogStorageError("boom")):
        response = api_client.post('/api/catalog/lock')

    assert response.status_code == 503, response.text
    assert "boom" in response.json()["error"]


def test_regenerate_idea_endpoint_returns_503_on_storage_error_without_charging(api_client):
    """Bug B3: regenerate no cobra si la idea nueva no se pudo persistir."""
    with patch.object(guard, 'get_session', return_value={'credits': 100}):
        with patch.object(guard, 'get_remaining_credits', return_value=100):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch('app.catalog.ideas.regenerate_single_idea', new=AsyncMock(side_effect=CatalogStorageError("boom"))):
                    response = api_client.post('/api/catalog/idea/idea_0/regenerate')

    assert response.status_code == 503, response.text
    mock_deduct.assert_not_called()


# =============================================================================
# B4 -- subcategory validada contra la categoría elegida (backend)
# =============================================================================

def test_add_founder_idea_rejects_subcategory_not_in_category(api_client):
    """
    Bug B4: `subcategory` es texto libre que termina en innerHTML del
    frontend -- además del escapeHtml del lado del cliente, el backend debe
    rechazar valores que no pertenezcan a la categoría elegida.
    """
    valid_category = MASTER_CATEGORIES[0]["id"]
    bogus_subcategory = "<img src=x onerror=alert(1)>"

    response = api_client.post('/api/catalog/idea', json={
        "title": "Una idea de prueba valida",
        "master_category": valid_category,
        "source": "Experiencia propia de mas de diez caracteres",
        "subcategory": bogus_subcategory,
    })

    assert response.status_code == 400, response.text
    assert "subcategory" in response.json()["error"]


def test_add_founder_idea_accepts_valid_subcategory_for_category(api_client):
    """Control: una subcategory que SÍ pertenece a la categoría elegida pasa la validación."""
    category = MASTER_CATEGORIES[0]
    valid_subcategory = category["subcategories"][0]
    fake_catalog = _make_catalog(n=1)

    with patch('app.catalog.ideas.add_founder_idea', return_value=fake_catalog) as mock_add:
        response = api_client.post('/api/catalog/idea', json={
            "title": "Una idea de prueba valida",
            "master_category": category["id"],
            "source": "Experiencia propia de mas de diez caracteres",
            "subcategory": valid_subcategory,
        })

    assert response.status_code == 201, response.text
    mock_add.assert_called_once()


# =============================================================================
# B4 (frontend) / B5 / B6 / B7 -- asserts estáticos sobre app.js
# (mismo patrón que test_catalog_pieza30.py::test_app_js_no_longer_renders_research_buttons)
# =============================================================================

def _read_app_js() -> str:
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def test_app_js_defines_escape_html_helper():
    """Bug B4: existe una función escapeHtml reutilizable."""
    js = _read_app_js()
    assert "function escapeHtml(" in js


def test_app_js_escapes_idea_fields_in_card_html():
    """
    Bug B4: title/subcategory/demand_signal (texto de terceros -- comentarios
    de YouTube / grounding web) se escapan antes de interpolarse en
    innerHTML dentro de buildIdeaCardHTML().
    """
    js = _read_app_js()
    start = js.index("function buildIdeaCardHTML(")
    end = js.index("\n  }", js.index("return `", start))
    block = js[start:end]

    assert "escapeHtml(idea.title)" in block
    assert "escapeHtml(idea.subcategory" in block
    assert "escapeHtml(idea.demand_signal)" in block


def test_app_js_regenerate_updates_credits_ui_with_arguments():
    """
    Bug B5: updateCreditsUI() se llama con (remaining, initial) tras
    regenerar una idea -- sin argumentos, el saldo mostrado quedaba
    "undefined".
    """
    js = _read_app_js()
    assert "updateCreditsUI(data.credits_remaining, initialSessionCredits);" in js
    # La llamada rota original (sin argumentos) ya no debe existir.
    assert "updateCreditsUI();" not in js


def test_app_js_declares_current_catalog_variable():
    """
    Bug B6: `currentCatalog` estaba en uso (openCreditGateModal) pero nunca
    declarada -- ReferenceError garantizado al hacer clic en el gate con un
    catálogo ya generado.
    """
    js = _read_app_js()
    assert "let currentCatalog = null;" in js
    # Debe asignarse en renderCatalogInPanel para que el gate la use.
    render_start = js.index("function renderCatalogInPanel(catalog) {")
    render_head = js[render_start:render_start + 400]
    assert "currentCatalog = catalog;" in render_head


def test_app_js_lock_button_guarded_against_duplicate_listeners():
    """
    Bug B7: el botón de Lock se re-wireaba en cada render (N renders = N
    listeners = N POST /lock por un solo clic). Debe usar el mismo guard
    dataset.wired que AddIdea-SubmitBtn.
    """
    js = _read_app_js()
    idx = js.index("const lockCatalogBtn = document.getElementById('Catalog-LockBtn');")
    snippet = js[idx:idx + 300]
    assert "dataset.wired" in snippet
