"""
Tests for Pieza 29 (Catalog closure):
  A. Persistencia en Supabase (tabla `catalogs`), con fallback a archivo local.
  B. Ideas manuales del fundador (gratis).
  C. Ideas ancladas al Brand Brain en el prompt.
"""
import os

os.environ.setdefault("TEST_MODE", "true")

import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.catalog.ideas import (
    Catalog,
    CatalogIdea,
    MASTER_CATEGORIES,
    MAX_IDEAS,
    TOTAL_IDEAS,
    add_founder_idea,
    _build_brand_context,
    _build_idea_generation_prompt,
    _catalog_to_row,
    _row_to_catalog,
    _save_catalog_cache,
    _check_catalog_cache,
)
from app.catalog.demand import NicheResearch
from app.tools.brand_brain.models import BrandBrain, Section
from app.guard import guard
from app.main import app


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
            # Sección NO confirmada -- no debe aparecer en el contexto.
            Section(
                id="oferta", label="oferta", status="pendiente",
                content={"servicio_principal": "sin confirmar todavia"},
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
def sample_catalog():
    return Catalog(
        session_id="test_session_29",
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


@pytest.fixture
def api_client():
    """
    Mismo patrón que test_catalog_pieza27.py: auth mockeada, sin JWKS real, y
    guard.get_or_create_user_session mockeado para no pegarle a Supabase real
    (mismas credenciales reales presentes en este entorno de desarrollo).
    """
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch('app.auth.supabase_auth.supabase_auth.get_user_id', return_value='550e8400-e29b-41d4-a716-446655440000'):
        with patch.object(guard, 'get_or_create_user_session', return_value='test_session_29'):
            yield client


# =============================================================================
# A. Persistencia en Supabase
# =============================================================================

def test_catalog_to_row_shape_matches_migration_columns(sample_catalog):
    """
    _catalog_to_row() debe producir exactamente las columnas de
    supabase/migrations/007_add_catalogs.sql: session_token, niche, data
    (jsonb), catalog_locked.
    """
    row = _catalog_to_row(sample_catalog)
    assert set(row.keys()) == {"session_token", "niche", "data", "catalog_locked"}
    assert row["session_token"] == "test_session_29"
    assert row["niche"] == "salud digital"
    assert row["catalog_locked"] is False
    assert isinstance(row["data"], dict)
    assert len(row["data"]["ideas"]) == 30
    assert "gate_passed" in row["data"]


def test_save_catalog_cache_upserts_to_real_supabase_shape(sample_catalog):
    """
    Bug de forma real: se mockea el cliente Supabase con la MISMA forma que
    usa brand_brain/store.py (client.table(...).upsert(...).execute()), no un
    método inventado. Verifica que se llama upsert sobre la tabla `catalogs`
    con on_conflict="session_token" (mismo patrón que brand_brains).
    """
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_upsert = MagicMock()
    mock_table.upsert.return_value = mock_upsert
    mock_upsert.execute.return_value = MagicMock(data=[{"session_token": "test_session_29"}])

    with patch('app.catalog.ideas._get_catalog_client', return_value=mock_client):
        _save_catalog_cache(sample_catalog)

    mock_client.table.assert_called_with("catalogs")
    mock_table.upsert.assert_called_once()
    args, kwargs = mock_table.upsert.call_args
    assert args[0]["session_token"] == "test_session_29"
    assert kwargs.get("on_conflict") == "session_token"
    mock_upsert.execute.assert_called_once()


def test_check_catalog_cache_reads_from_real_supabase_shape(sample_catalog):
    """
    Misma forma real que store.py::get_brand_brain():
    client.table(...).select("*").eq(...).execute() -> response.data[0].
    """
    row = _catalog_to_row(sample_catalog)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [row]
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_response

    with patch('app.catalog.ideas._get_catalog_client', return_value=mock_client):
        loaded = _check_catalog_cache("test_session_29")

    assert loaded is not None
    assert loaded.session_id == "test_session_29"
    assert loaded.niche == "salud digital"
    assert loaded.idea_count == 30
    mock_client.table.assert_called_with("catalogs")
    mock_client.table.return_value.select.assert_called_with("*")
    mock_client.table.return_value.select.return_value.eq.assert_called_with("session_token", "test_session_29")


def test_check_catalog_cache_returns_none_when_supabase_has_no_row():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = []
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_response

    with patch('app.catalog.ideas._get_catalog_client', return_value=mock_client):
        assert _check_catalog_cache("no_existe") is None


def test_catalog_cache_falls_back_to_local_file_when_supabase_not_configured(sample_catalog, tmp_path, monkeypatch):
    """
    Si Supabase no está configurado (_get_catalog_client() -> None, mismo
    criterio que brand_brain/store.py en TEST_MODE), debe seguir funcionando
    contra el archivo local -- no debe reventar ni perder el catálogo.
    """
    monkeypatch.chdir(tmp_path)
    with patch('app.catalog.ideas._get_catalog_client', return_value=None):
        _save_catalog_cache(sample_catalog)
        loaded = _check_catalog_cache("test_session_29")

    assert loaded is not None
    assert loaded.idea_count == 30


def test_no_ttl_or_hash_invalidation_in_local_fallback(sample_catalog, tmp_path, monkeypatch):
    """
    Bug real corregido en Pieza 29: antes, un catálogo con created_at de hace
    25 horas (o un brand_brain distinto al que se usó para generarlo) se
    invalidaba solo. Ahora un catálogo persistido no desaparece ni se
    regenera solo -- sin importar su antigüedad ni el estado del brain.
    """
    monkeypatch.chdir(tmp_path)
    old_catalog = sample_catalog.model_copy(
        update={"created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)}
    )

    with patch('app.catalog.ideas._get_catalog_client', return_value=None):
        # get_brand_brain NO se mockea a propósito -- si el código todavía
        # dependiera de _compute_catalog_hash() para invalidar, esto
        # explotaría (ValueError "No se encontró BrandBrain") o invalidaría
        # el cache. Debe seguir sirviendo el catálogo igual.
        _save_catalog_cache(old_catalog)
        loaded = _check_catalog_cache("test_session_29")

    assert loaded is not None
    assert loaded.idea_count == 30


# =============================================================================
# Bug real encontrado en Pieza 29: get_or_generate_catalog() no aceptaba
# niche_research= aunque main.py::/investigate ya la llamaba con ese kwarg
# desde la ronda anterior -- TypeError garantizado en cada request real. El
# test que debía cubrir esto mockeaba get_or_generate_catalog() entero (un
# AsyncMock acepta cualquier kwarg sin validar la firma real), por eso nunca
# se detectó.
# =============================================================================

@pytest.mark.asyncio
async def test_get_or_generate_catalog_accepts_niche_research_kwarg(sample_catalog):
    """
    Llama a la función REAL (no un mock) con niche_research= tal como lo hace
    main.py::investigate_catalog_endpoint -- debe reusar el cache existente
    sin explotar con TypeError.
    """
    from app.catalog.ideas import get_or_generate_catalog

    fake_research = NicheResearch(niche="salud digital", youtube_titles=["v1"])

    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        catalog = await get_or_generate_catalog("test_session_29", niche_research=fake_research)

    assert catalog.session_id == "test_session_29"


@pytest.mark.asyncio
async def test_get_or_generate_catalog_forwards_niche_research_to_generate(brand_brain):
    """
    Cuando no hay cache, get_or_generate_catalog() debe reenviar el
    niche_research recibido a generate_catalog() -- no descartarlo ni
    disparar una segunda llamada a research_niche().
    """
    from app.catalog.ideas import get_or_generate_catalog

    import copy
    confirmed_brain = copy.deepcopy(brand_brain)
    for section in confirmed_brain.sections:
        section.status = "confirmado"

    fake_research = NicheResearch(niche="salud digital", youtube_titles=["v1"])

    with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
        with patch('app.catalog.ideas._save_catalog_cache'):
            with patch('app.catalog.ideas.get_brand_brain', return_value=confirmed_brain):
                with patch('app.catalog.ideas._check_brand_soul_generated', return_value=True):
                    with patch('app.catalog.ideas.research_niche') as mock_research:
                        with patch(
                            'app.catalog.ideas._generate_ideas_for_category',
                            new=AsyncMock(return_value=[
                                CatalogIdea(
                                    master_category="autoridad_tecnica", subcategory="Top N",
                                    title=f"Idea {i}", demand_signal="Señal real de más de diez"
                                ) for i in range(12)
                            ])
                        ):
                            catalog = await get_or_generate_catalog(
                                "test_session", niche_research=fake_research
                            )

    mock_research.assert_not_called()
    assert catalog.niche is not None


# =============================================================================
# B. Ideas manuales del fundador
# =============================================================================

def test_add_founder_idea_is_born_approved_with_founder_origin(sample_catalog):
    with patch('app.catalog.ideas._get_catalog_client', return_value=None):
        with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
            with patch('app.catalog.ideas._save_catalog_cache'):
                catalog = add_founder_idea(
                    session_id="test_session_29",
                    title="Mi propia idea de founder sobre operaciones",
                    master_category="autoridad_tecnica",
                    source="Lo viví yo mismo dirigiendo el hospital 8 años"
                )

    new_idea = catalog.ideas[-1]
    assert new_idea.status == "approved"
    assert new_idea.origin == "founder"
    assert new_idea.demand_signal == "Fuente del founder: Lo viví yo mismo dirigiendo el hospital 8 años"
    assert catalog.idea_count == 31


def test_add_founder_idea_defaults_subcategory_to_first_of_category(sample_catalog):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        with patch('app.catalog.ideas._save_catalog_cache'):
            catalog = add_founder_idea(
                session_id="test_session_29",
                title="Idea sin subcategoria especificada por el founder",
                master_category="validacion_resultados",
                source="Dato interno de mi propia operación clínica"
            )

    expected_default = next(
        c for c in MASTER_CATEGORIES if c["id"] == "validacion_resultados"
    )["subcategories"][0]
    assert catalog.ideas[-1].subcategory == expected_default


def test_add_founder_idea_400_when_no_catalog():
    with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
        with pytest.raises(ValueError, match="No hay catálogo generado"):
            add_founder_idea(
                session_id="sin_catalogo",
                title="Idea válida con suficiente longitud",
                master_category="autoridad_tecnica",
                source="Fuente valida de mas de diez caracteres"
            )


def test_add_founder_idea_400_when_locked(sample_catalog):
    locked = sample_catalog.model_copy(update={"catalog_locked": True})
    with patch('app.catalog.ideas._check_catalog_cache', return_value=locked):
        with pytest.raises(ValueError, match="bloqueado"):
            add_founder_idea(
                session_id="test_session_29",
                title="Idea válida con suficiente longitud",
                master_category="autoridad_tecnica",
                source="Fuente valida de mas de diez caracteres"
            )


def test_add_founder_idea_400_when_invalid_category(sample_catalog):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        with pytest.raises(ValueError, match="Categoría inválida"):
            add_founder_idea(
                session_id="test_session_29",
                title="Idea válida con suficiente longitud",
                master_category="categoria_que_no_existe",
                source="Fuente valida de mas de diez caracteres"
            )


def test_add_founder_idea_400_when_source_too_short(sample_catalog):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        with pytest.raises(ValueError, match="source debe tener al menos 10"):
            add_founder_idea(
                session_id="test_session_29",
                title="Idea válida con suficiente longitud",
                master_category="autoridad_tecnica",
                source="corta"
            )


def test_add_founder_idea_400_when_catalog_already_at_max(sample_catalog):
    full_catalog = sample_catalog.model_copy(update={
        "ideas": sample_catalog.ideas + [
            CatalogIdea(
                id=f"extra_{i}", master_category="autoridad_tecnica", subcategory="Top N",
                title=f"Idea extra {i}", demand_signal="Señal suficientemente larga"
            )
            for i in range(MAX_IDEAS - TOTAL_IDEAS)
        ]
    })
    assert full_catalog.idea_count == MAX_IDEAS

    with patch('app.catalog.ideas._check_catalog_cache', return_value=full_catalog):
        with pytest.raises(ValueError, match=f"máximo de {MAX_IDEAS}"):
            add_founder_idea(
                session_id="test_session_29",
                title="Una idea mas que ya no deberia caber",
                master_category="autoridad_tecnica",
                source="Fuente valida de mas de diez caracteres"
            )


def test_add_founder_idea_title_too_short_raises(sample_catalog):
    """Trust boundary: CatalogIdea valida title (min 5) en construcción."""
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        with pytest.raises(Exception):
            add_founder_idea(
                session_id="test_session_29",
                title="Hi",
                master_category="autoridad_tecnica",
                source="Fuente valida de mas de diez caracteres"
            )


# --- Endpoint POST /api/catalog/idea ---

def test_add_founder_idea_endpoint_201(api_client, sample_catalog):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        with patch('app.catalog.ideas._save_catalog_cache'):
            response = api_client.post('/api/catalog/idea', json={
                "title": "Idea propia del fundador sobre procesos",
                "master_category": "autoridad_tecnica",
                "source": "Mi experiencia personal de 10 años en el rubro"
            })

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "success"
    new_idea = data["catalog"]["ideas"][-1]
    assert new_idea["origin"] == "founder"
    assert new_idea["status"] == "approved"


def test_add_founder_idea_endpoint_400_without_catalog(api_client):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=None):
        response = api_client.post('/api/catalog/idea', json={
            "title": "Idea propia del fundador sobre procesos",
            "master_category": "autoridad_tecnica",
            "source": "Mi experiencia personal de 10 años en el rubro"
        })

    assert response.status_code == 400
    assert "error" in response.json()


def test_add_founder_idea_endpoint_400_when_locked(api_client, sample_catalog):
    locked = sample_catalog.model_copy(update={"catalog_locked": True})
    with patch('app.catalog.ideas._check_catalog_cache', return_value=locked):
        response = api_client.post('/api/catalog/idea', json={
            "title": "Idea propia del fundador sobre procesos",
            "master_category": "autoridad_tecnica",
            "source": "Mi experiencia personal de 10 años en el rubro"
        })

    assert response.status_code == 400


@pytest.mark.parametrize("body,missing", [
    ({"master_category": "autoridad_tecnica", "source": "Fuente de mas de diez caracteres"}, "title"),
    ({"title": "Idea con longitud valida de titulo", "source": "Fuente de mas de diez caracteres"}, "master_category"),
    ({"title": "Idea con longitud valida de titulo", "master_category": "autoridad_tecnica"}, "source"),
])
def test_add_founder_idea_endpoint_400_missing_fields(api_client, body, missing):
    response = api_client.post('/api/catalog/idea', json=body)
    assert response.status_code == 400


def test_add_founder_idea_endpoint_400_title_too_short(api_client):
    response = api_client.post('/api/catalog/idea', json={
        "title": "Hi",
        "master_category": "autoridad_tecnica",
        "source": "Fuente de mas de diez caracteres"
    })
    assert response.status_code == 400


def test_add_founder_idea_endpoint_400_source_too_short(api_client):
    response = api_client.post('/api/catalog/idea', json={
        "title": "Titulo con longitud suficiente para pasar",
        "master_category": "autoridad_tecnica",
        "source": "corta"
    })
    assert response.status_code == 400


def test_add_founder_idea_endpoint_400_invalid_category(api_client, sample_catalog):
    with patch('app.catalog.ideas._check_catalog_cache', return_value=sample_catalog):
        response = api_client.post('/api/catalog/idea', json={
            "title": "Titulo con longitud suficiente para pasar",
            "master_category": "no_existe",
            "source": "Fuente de mas de diez caracteres"
        })
    assert response.status_code == 400


# =============================================================================
# C. Ideas ancladas al Brand Brain
# =============================================================================

def test_build_brand_context_includes_confirmed_sections_only(brand_brain):
    context = _build_brand_context(brand_brain)

    assert "directores de operaciones clínicas" in context
    assert "hospitales pierden dinero" in context
    assert "15 años operando hospitales" in context
    # La sección "oferta" está en estado "pendiente" -- no debe aparecer.
    assert "sin confirmar todavia" not in context


def test_build_brand_context_excludes_timestamps(brand_brain):
    context = _build_brand_context(brand_brain)
    assert "created_at" not in context
    assert "updated_at" not in context
    assert str(brand_brain.created_at.year) not in context


def test_build_brand_context_truncates_to_max_chars():
    long_content = "palabra " * 1000  # muy por encima de BRAND_CONTEXT_MAX_CHARS
    brain = BrandBrain(
        sections=[
            Section(
                id="icp", label="icp", status="confirmado",
                content={"detalle": long_content},
                citation_text="c", citation_source="usuario",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            )
        ],
        formato={"language": "es"},
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

    from app.catalog.ideas import BRAND_CONTEXT_MAX_CHARS
    context = _build_brand_context(brain)
    assert len(context) <= BRAND_CONTEXT_MAX_CHARS + len("...")


def test_prompt_includes_brand_context_block_when_provided():
    """
    Bug regression: el prompt debe incluir el bloque "PERFIL DEL FUNDADOR"
    con el texto real del brand_context cuando se pasa -- antes el prompt
    solo recibía nicho + experto/curador, sin nada del perfil del fundador.
    """
    prompt = _build_idea_generation_prompt(
        niche="salud digital",
        master_category="autoridad_tecnica",
        subcategories=["Top N/Listículo técnico"],
        niche_research=NicheResearch(niche="salud digital"),
        approach="experto",
        count=3,
        brand_context="- icp: directores de operaciones clínicas de hospitales medianos"
    )

    assert "PERFIL DEL FUNDADOR" in prompt
    assert "directores de operaciones clínicas de hospitales medianos" in prompt


def test_prompt_omits_brand_context_block_when_empty():
    """Compatibilidad: brand_context="" (default) no debe romper ni dejar un bloque vacío raro."""
    prompt = _build_idea_generation_prompt(
        niche="salud digital",
        master_category="autoridad_tecnica",
        subcategories=["Top N/Listículo técnico"],
        niche_research=NicheResearch(niche="salud digital"),
        approach="experto",
        count=3
    )

    assert "PERFIL DEL FUNDADOR" not in prompt


@pytest.mark.asyncio
async def test_generate_catalog_passes_brand_context_to_prompt(brand_brain):
    """
    Test end-to-end (con el LLM mockeado): generate_catalog() debe construir
    el brand_context desde el BrandBrain real de la sesión y pasarlo hasta
    _build_idea_generation_prompt(), de forma que el texto del perfil del
    fundador termine literalmente en el prompt que se le manda al LLM.
    """
    from app.catalog.ideas import generate_catalog

    captured_prompts = []

    real_build_prompt = _build_idea_generation_prompt

    def spy_build_prompt(*args, **kwargs):
        prompt = real_build_prompt(*args, **kwargs)
        captured_prompts.append(prompt)
        return prompt

    fake_research = NicheResearch(niche="salud digital", youtube_titles=["Video real 1"])

    # generate_catalog() exige TODAS las secciones confirmado/completado --
    # se confirma la sección "oferta" (pendiente en la fixture) solo para
    # este test de integración; la exclusión de secciones no confirmadas ya
    # está cubierta por test_build_brand_context_includes_confirmed_sections_only.
    import copy
    confirmed_brain = copy.deepcopy(brand_brain)
    for section in confirmed_brain.sections:
        section.status = "confirmado"

    with patch('app.catalog.ideas.get_brand_brain', return_value=confirmed_brain):
        with patch('app.catalog.ideas._check_brand_soul_generated', return_value=True):
            with patch('app.catalog.ideas._build_idea_generation_prompt', side_effect=spy_build_prompt):
                with patch(
                    'app.catalog.ideas._call_llm_with_prompt',
                    new=AsyncMock(return_value='{"ideas": [{"subcategory": "Top N/Listículo técnico", "title": "Titulo de prueba valido", "demand_signal": "Video real 1"}]}')
                ):
                    await generate_catalog("test_session", niche_research=fake_research)

    assert len(captured_prompts) > 0
    assert all("directores de operaciones clínicas" in p for p in captured_prompts)
