"""H8-06: /api/agent-token and /api/demand refund their charge when the upstream call fails.

Network is mocked: AssemblyAI (httpx.AsyncClient in app.main) and validate_niche_demand.
"""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.guard import guard
from app.main import app
from tests.jwt_helpers import create_test_jwt

START = 250


@pytest.fixture
def founder():
    user_id = str(uuid.uuid4())
    session_token = guard.create_user_session(user_id, initial_credits=START)
    guard._sessions[session_token] = {
        "credits": START,
        "created_at": datetime.utcnow().timestamp(),
        "user_id": user_id,
    }
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {create_test_jwt(user_id)}"})
    return client, session_token


def _balance(session_token):
    return guard._sessions[session_token]["credits"]


def _assemblyai_client(*, status_code=200, body=None, get_side_effect=None):
    response = MagicMock()
    response.status_code = status_code
    response.text = "upstream error"
    response.json.return_value = body if body is not None else {"token": "tok_abc"}
    http = MagicMock()
    http.get = AsyncMock(return_value=response, side_effect=get_side_effect)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=http)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def test_agent_token_success_charges_exactly_once(founder):
    client, token = founder
    with patch("app.main.httpx.AsyncClient", _assemblyai_client()):
        r = client.get("/api/agent-token")
    assert r.status_code == 200
    assert r.json() == {"token": "tok_abc", "credits_remaining": START - 1}
    assert _balance(token) == START - 1


def test_agent_token_upstream_500_refunds(founder):
    client, token = founder
    with patch("app.main.httpx.AsyncClient", _assemblyai_client(status_code=500)):
        r = client.get("/api/agent-token")
    assert r.status_code >= 500
    assert _balance(token) == START


def test_agent_token_request_error_refunds(founder):
    client, token = founder
    failing = _assemblyai_client(get_side_effect=httpx.ConnectError("boom"))
    with patch("app.main.httpx.AsyncClient", failing):
        r = client.get("/api/agent-token")
    assert r.status_code == 502
    assert _balance(token) == START


def test_agent_token_refund_failure_does_not_mask_original_error(founder):
    client, token = founder
    failing = _assemblyai_client(get_side_effect=httpx.ConnectError("boom"))
    with patch("app.main.httpx.AsyncClient", failing), patch.object(
        guard, "refund_credits", side_effect=RuntimeError("db down")
    ):
        r = client.get("/api/agent-token")
    assert r.status_code == 502
    assert "Failed to connect to AssemblyAI" in r.json()["detail"]


def test_demand_failure_refunds(founder):
    client, token = founder
    with patch("app.main.validate_niche_demand", AsyncMock(side_effect=RuntimeError("yt down"))):
        r = client.get("/api/demand", params={"niche": "fitness"})
    assert r.status_code == 500
    assert "Demand validation failed" in r.json()["error"]
    assert _balance(token) == START


def test_demand_success_charges_exactly_once(founder):
    client, token = founder
    report = MagicMock()
    report.model_dump.return_value = {"niche": "fitness"}
    with patch("app.main.validate_niche_demand", AsyncMock(return_value=report)):
        r = client.get("/api/demand", params={"niche": "fitness"})
    assert r.status_code == 200
    assert r.json()["credits_remaining"] == START - 10
    assert _balance(token) == START - 10
