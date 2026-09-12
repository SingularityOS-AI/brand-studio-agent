"""
Tests for Piece 27 endpoints (investigate, accept, discard, regenerate, lock).
"""
import pytest
import datetime
from unittest.mock import patch, MagicMock

from app.catalog.ideas import CatalogIdea, Catalog, _save_catalog_cache
from app.tools.brand_brain.models import BrandBrain, Section


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
