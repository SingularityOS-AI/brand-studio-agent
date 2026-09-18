"""
Unit tests for PIEZA 35 BUG 1 fixes (Founder ideas in locked catalog).

Tests:
- BUG 1a: Founder ideas can change status even when catalog locked
- BUG 1b: Non-founder ideas STILL protected when catalog locked
- BUG 1c: Nonexistent idea still returns "not found" error
- BUG 1d: Founder idea can be moved back toapproved status
"""
import pytest
from app.catalog.ideas import Catalog, CatalogIdea, update_idea_status


@pytest.fixture
def sample_catalog_locked_with_founder():
    """Catálogo bloqueado con ideas del motor y una del founder."""
    return Catalog(
        id="catalog_test_35",
        session_id="test_session_35",
        catalog_locked=True,
        niche="test_niche",  # Required field
        ideas=[
            CatalogIdea(
                id="idea_motor_1",
                title="Idea del motor 1",
                master_category="autoridad_tecnica",
                subcategory="Top N/Listículo técnico",
                demand_signal="Demanda del motor",
                status="approved",
                origin="research",  # Esta NO se debe poder modificar
            ),
            CatalogIdea(
                id="idea_founder_1",
                title="Idea del founder",
                master_category="validacion_resultados",
                subcategory="Desglose de caso de éxito",
                demand_signal="Fuente del founder: experiencia propia",
                status="approved",
                origin="founder",  # Esta SÍ se debe poder modificar
            ),
        ],
    )


@pytest.mark.asyncio
async def test_update_founder_idea_in_locked_catalog_allowed(sample_catalog_locked_with_founder):
    """
    BUG 1 test (a): idea con origin="founder" en catálogo bloqueado
    PUEDE cambiar de status (rejected).
    """
    from unittest.mock import patch

    # Mock de cache
    with patch("app.catalog.ideas._check_catalog_cache", return_value=sample_catalog_locked_with_founder), \
         patch("app.catalog.ideas._save_catalog_cache", return_value=None):

        result = await update_idea_status(
            session_id="test_session_35",
            idea_id="idea_founder_1",
            new_status="rejected",
        )

        # update_idea_status returns a Catalog, not an idea
        assert result is not None
        assert isinstance(result, Catalog)

        # Find the updated idea in the catalog
        updated_idea = None
        for idea in result.ideas:
            if idea.id == "idea_founder_1":
                updated_idea = idea
                break

        assert updated_idea is not None
        assert updated_idea.status == "rejected"


@pytest.mark.asyncio
async def test_update_non_founder_idea_in_locked_catalog_forbidden():
    """
    BUG 1 test (b): idea con origin != "founder" en catálogo bloqueado
    SIGUE dando el error de bloqueado.
    """
    from unittest.mock import patch

    catalog_locked = Catalog(
        id="catalog_test_35_b",
        session_id="test_session_35_b",
        catalog_locked=True,
        niche="test_niche",  # Required field
        ideas=[
            CatalogIdea(
                id="idea_motor_2",
                title="Idea del motor 2",
                master_category="posicionamiento_narrativa",
                subcategory="Mito vs Realidad",
                demand_signal="Demanda del motor",
                status="approved",
                origin="research",
            ),
        ],
    )

    with patch("app.catalog.ideas._check_catalog_cache", return_value=catalog_locked), \
         patch("app.catalog.ideas._save_catalog_cache", return_value=None):

        # Debería lanzar ValueError con el mensaje traducido a inglés
        with pytest.raises(ValueError) as exc_info:
            await update_idea_status(
                session_id="test_session_35_b",
                idea_id="idea_motor_2",
                new_status="rejected",
            )

        # Error en inglés según BUG 5a
        error_msg = str(exc_info.value).lower()
        assert "locked" in error_msg or "cannot modify" in error_msg


@pytest.mark.asyncio
async def test_update_nonexistent_idea_not_found():
    """
    BUG 1 test (c): idea inexistente sigue dando "no encontrada".
    """
    from unittest.mock import patch

    catalog = Catalog(
        id="catalog_test_35_c",
        session_id="test_session_35_c",
        catalog_locked=True,
        niche="test_niche",  # Required field
        ideas=[],
    )

    with patch("app.catalog.ideas._check_catalog_cache", return_value=catalog), \
         patch("app.catalog.ideas._save_catalog_cache", return_value=None):

        # Debería lanzar ValueError con el mensaje traducido a inglés
        with pytest.raises(ValueError) as exc_info:
            await update_idea_status(
                session_id="test_session_35_c",
                idea_id="idea_inexistente",
                new_status="rejected",
            )

        # Error en inglés según BUG 5a
        error_msg = str(exc_info.value).lower()
        assert "not found" in error_msg


@pytest.mark.asyncio
async def test_update_founder_idea_can_change_back_to_approved():
    """
    BUG 1 extra: idea del founder se puede volver a aprobar después de descartarla.
    """
    from unittest.mock import patch

    catalog_locked = Catalog(
        id="catalog_test_35_extra",
        session_id="test_session_35_extra",
        catalog_locked=True,
        niche="test_niche",  # Required field
        ideas=[
            CatalogIdea(
                id="idea_founder_2",
                title="Otra idea del founder",
                master_category="discusion_industria",
                subcategory="Pregunta de debate",
                demand_signal="Fuente del founder: discusión con cliente",
                status="rejected",
                origin="founder",
            ),
        ],
    )

    with patch("app.catalog.ideas._check_catalog_cache", return_value=catalog_locked), \
         patch("app.catalog.ideas._save_catalog_cache", return_value=None):

        result = await update_idea_status(
            session_id="test_session_35_extra",
            idea_id="idea_founder_2",
            new_status="approved",
        )

        # update_idea_status returns a Catalog, not an idea
        assert result is not None
        assert isinstance(result, Catalog)

        # Find the updated idea in the catalog
        updated_idea = None
        for idea in result.ideas:
            if idea.id == "idea_founder_2":
                updated_idea = idea
                break

        assert updated_idea is not None
        assert updated_idea.status == "approved"
