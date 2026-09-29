"""
H8-02 - Brand Soul: Regenerate really regenerates, and failures refund.

Everything external is mocked: the generator, the cache peek and the brain store.
No network, no LLM.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

START_CREDITS = 250
COST = 20


@pytest.fixture
def soul_client(monkeypatch):
    """TestClient with a logged-in session holding START_CREDITS."""
    monkeypatch.setenv("TEST_MODE", "true")

    from app.guard import guard
    from app.main import app
    from tests.jwt_helpers import create_test_jwt

    user_id = str(uuid.uuid4())  # fresh session per test: the guard reuses sessions by user
    token = guard.create_user_session(user_id, initial_credits=START_CREDITS)
    guard._sessions[token] = {"credits": START_CREDITS, "created_at": None, "user_id": user_id}

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {create_test_jwt(user_id)}"})
    return client, guard, token


def _balance(guard, token) -> int:
    return guard.get_session(token)["credits"]


def test_regenerate_calls_generator_with_force_and_charges_20_once(soul_client):
    client, guard, token = soul_client
    generator = MagicMock(return_value=("<html>fresh</html>", "generated"))

    with patch("app.tools.brand_soul.generator.generate_brand_soul", generator):
        response = client.post("/api/soul/generate", json={"regenerate": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["html"] == "<html>fresh</html>"
    assert body["cache_status"] == "generated"
    assert body["credits_remaining"] == START_CREDITS - COST
    assert _balance(guard, token) == START_CREDITS - COST
    generator.assert_called_once_with(token, force=True)


def test_cache_hit_without_regenerate_charges_nothing(soul_client):
    client, guard, token = soul_client
    generator = MagicMock()

    with (
        patch("app.tools.brand_soul.generator.generate_brand_soul", generator),
        patch("app.tools.brand_brain.store.get_brand_brain", return_value=object()),
        patch("app.tools.brand_soul.generator._check_cache", return_value="<html>cached</html>"),
        patch(
            "app.tools.brand_soul.generator.validate_citations_in_html",
            return_value=(True, []),
        ),
    ):
        response = client.post("/api/soul/generate", json={"regenerate": False})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["html"] == "<html>cached</html>"
    assert body["cache_status"] == "cached"
    assert body["credits_remaining"] == START_CREDITS
    assert _balance(guard, token) == START_CREDITS
    generator.assert_not_called()


def test_cache_miss_without_regenerate_generates_and_charges_20(soul_client):
    client, guard, token = soul_client
    generator = MagicMock(return_value=("<html>new</html>", "generated"))

    with (
        patch("app.tools.brand_soul.generator.generate_brand_soul", generator),
        patch("app.tools.brand_brain.store.get_brand_brain", return_value=object()),
        patch("app.tools.brand_soul.generator._check_cache", return_value=None),
    ):
        response = client.post("/api/soul/generate", json={"regenerate": False})

    assert response.status_code == 200, response.text
    assert response.json()["credits_remaining"] == START_CREDITS - COST
    assert _balance(guard, token) == START_CREDITS - COST
    generator.assert_called_once_with(token, force=False)


@pytest.mark.parametrize("error_name", [
    "IncompleteBrainError",
    "CitationValidationError",
    "SoulGenerationError",
    "RuntimeError",
])
def test_generator_failure_refunds_the_20_credits(soul_client, error_name):
    client, guard, token = soul_client
    from app.tools.brand_soul import generator as soul_generator

    error_cls = getattr(soul_generator, error_name, None) or RuntimeError
    generator = MagicMock(side_effect=error_cls("boom"))

    with patch("app.tools.brand_soul.generator.generate_brand_soul", generator):
        response = client.post("/api/soul/generate", json={"regenerate": True})

    assert response.status_code in (400, 500)
    assert response.json()["credits_remaining"] == START_CREDITS
    assert _balance(guard, token) == START_CREDITS


def test_cached_result_after_charge_is_refunded(soul_client):
    """The cache turned valid between the peek and the charge: nothing generated, nothing owed."""
    client, guard, token = soul_client
    generator = MagicMock(return_value=("<html>cached</html>", "cached"))

    with (
        patch("app.tools.brand_soul.generator.generate_brand_soul", generator),
        patch("app.tools.brand_brain.store.get_brand_brain", return_value=object()),
        patch("app.tools.brand_soul.generator._check_cache", return_value=None),
    ):
        response = client.post("/api/soul/generate", json={"regenerate": False})

    assert response.status_code == 200, response.text
    assert response.json()["cache_status"] == "cached"
    assert response.json()["credits_remaining"] == START_CREDITS
    assert _balance(guard, token) == START_CREDITS


def test_force_skips_check_cache_in_generator():
    from app.tools.brand_soul import generator as soul_generator

    with (
        patch.object(soul_generator, "get_brand_brain", return_value=object()),
        patch.object(soul_generator, "_check_all_sections_confirmed", return_value=(True, [])),
        patch.object(soul_generator, "_check_cache") as check_cache,
        patch.object(soul_generator, "detect_etapa_from_brand_brain", side_effect=RuntimeError("stop")),
    ):
        with pytest.raises(RuntimeError, match="stop"):
            soul_generator.generate_brand_soul("tok", force=True)

    check_cache.assert_not_called()
