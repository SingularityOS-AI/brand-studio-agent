"""Tests for F-02: agent_actions table + store + audit middleware + list API.

CRITICAL (a previous agent broke this piece twice by getting this wrong):
this file NEVER imports app.main.app. It builds its own isolated FastAPI()
instance per test via a fixture and mounts only the agent router + the audit
middleware on it, plus a couple of throwaway dummy endpoints standing in for
the real catalog/script/editing routes so the middleware has something to
wrap. Calling app.include_router()/app.add_middleware() again on the shared
app.main.app singleton (imported at module scope so it's created exactly
once per test session) would register the router/middleware a second time
and corrupt that singleton for every other test file that reuses it via the
`authenticated_client` fixture -- see tests/test_audiovisual_p50.py's
test_endpoints_409_422_200, which must keep passing unmodified.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.responses import Response

from app.agent import middleware as agent_middleware
from app.agent import store as agent_store
from app.agent.middleware import AgentActionsAuditMiddleware
from app.agent.router import router as agent_router
from app.guard import guard
from tests.jwt_helpers import create_test_jwt

USER_A = "550e8400-e29b-41d4-a716-446655440099"
USER_B = "650e8400-e29b-41d4-a716-446655440088"


@pytest.fixture(autouse=True)
def _reset_agent_actions_store():
    agent_store._reset_local_actions()
    yield
    agent_store._reset_local_actions()


@pytest.fixture
def isolated_app() -> FastAPI:
    """A fresh app: just the agent router + audit middleware, plus dummy
    endpoints under audited/excluded prefixes to exercise the middleware."""
    app = FastAPI()
    app.include_router(agent_router)
    app.add_middleware(AgentActionsAuditMiddleware)

    @app.post("/api/catalog/{idea_id}/lock")
    async def _dummy_catalog_lock(idea_id: str) -> JSONResponse:
        return JSONResponse(status_code=200, content={"locked": True})

    @app.post("/api/catalog/{idea_id}/fail")
    async def _dummy_catalog_fail(idea_id: str) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "bad"})

    @app.post("/api/script/generate")
    async def _dummy_script_generate(idea_id: str) -> JSONResponse:
        # Mirrors the real endpoint: idea_id arrives as a query param, not a
        # path param.
        return JSONResponse(status_code=202, content={"queued": True})

    @app.post("/api/editing/internal/jobs/{job_id}/progress")
    async def _dummy_internal(job_id: str) -> Response:
        return Response(status_code=204)

    return app


@pytest.fixture
def client(isolated_app: FastAPI) -> TestClient:
    return TestClient(isolated_app)


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_test_jwt(user_id)}"}


@pytest.fixture
def headers_a() -> dict[str, str]:
    return _auth_headers(USER_A)


@pytest.fixture
def headers_b() -> dict[str, str]:
    return _auth_headers(USER_B)


@pytest.fixture
def session_a() -> str:
    return guard.get_or_create_user_session(USER_A)


@pytest.fixture
def session_b() -> str:
    return guard.get_or_create_user_session(USER_B)


# =============================================================================
# Middleware: button rows
# =============================================================================


def test_button_request_creates_row(client, headers_a, session_a):
    res = client.post("/api/catalog/idea-1/lock", headers=headers_a)
    assert res.status_code == 200
    assert res.json() == {"locked": True}

    listed = client.get("/api/agent/actions?idea_id=idea-1", headers=headers_a)
    assert listed.status_code == 200
    actions = listed.json()["actions"]
    assert len(actions) == 1
    row = actions[0]
    assert row["source"] == "button"
    assert row["status"] == "done"
    assert row["idea_id"] == "idea-1"
    assert row["action"] == "POST /api/catalog/{idea_id}/lock"
    assert row["session_token"] == session_a


def test_button_request_failure_marks_failed(client, headers_a):
    res = client.post("/api/catalog/idea-2/fail", headers=headers_a)
    assert res.status_code == 400  # response is untouched by the middleware

    listed = client.get("/api/agent/actions?idea_id=idea-2", headers=headers_a)
    row = listed.json()["actions"][0]
    assert row["status"] == "failed"
    assert row["error"] == "HTTP 400"


def test_button_request_202_marks_queued(client, headers_a):
    res = client.post("/api/script/generate?idea_id=idea-3", headers=headers_a)
    assert res.status_code == 202

    listed = client.get("/api/agent/actions?idea_id=idea-3", headers=headers_a)
    row = listed.json()["actions"][0]
    assert row["status"] == "queued"
    assert row["idea_id"] == "idea-3"


def test_excluded_internal_path_is_not_audited(client, headers_a):
    res = client.post("/api/editing/internal/jobs/job-1/progress", headers=headers_a)
    assert res.status_code == 204

    listed = client.get("/api/agent/actions", headers=headers_a)
    assert listed.json()["actions"] == []


# =============================================================================
# Middleware: voice rows via X-Agent-Action-Id
# =============================================================================


def test_header_request_updates_voice_row_instead_of_creating_a_button_row(
    client, headers_a, session_a
):
    created = client.post(
        "/api/agent/actions",
        headers=headers_a,
        json={
            "step": "catalog",
            "action": "lock_catalog",
            "idea_id": "idea-4",
            "utterance": "lock it in",
            "restatement": "Lock the catalog -- 0 credits. Say confirm to go ahead.",
            "credits": 0,
            "status": "proposed",
        },
    )
    assert created.status_code == 201
    action_id = created.json()["id"]

    res = client.post(
        "/api/catalog/idea-4/lock",
        headers={**headers_a, "X-Agent-Action-Id": action_id},
    )
    assert res.status_code == 200

    listed = client.get("/api/agent/actions?idea_id=idea-4", headers=headers_a)
    actions = listed.json()["actions"]
    assert len(actions) == 1  # updated in place, no extra button row
    row = actions[0]
    assert row["id"] == action_id
    assert row["source"] == "voice"
    assert row["status"] == "done"
    assert row["utterance"] == "lock it in"


def test_header_not_owned_by_caller_falls_back_to_button_row(client, headers_a, headers_b):
    created = client.post(
        "/api/agent/actions",
        headers=headers_b,
        json={"step": "catalog", "action": "lock_catalog", "idea_id": "idea-5"},
    )
    action_id = created.json()["id"]

    # User A calls the endpoint with user B's action id in the header.
    res = client.post(
        "/api/catalog/idea-5/lock",
        headers={**headers_a, "X-Agent-Action-Id": action_id},
    )
    assert res.status_code == 200

    # B's original proposed row is untouched.
    b_actions = client.get("/api/agent/actions?idea_id=idea-5", headers=headers_b).json()["actions"]
    assert len(b_actions) == 1
    assert b_actions[0]["id"] == action_id
    assert b_actions[0]["status"] == "proposed"

    # A got a separate button row instead of silently losing the audit entry.
    a_actions = client.get("/api/agent/actions?idea_id=idea-5", headers=headers_a).json()["actions"]
    assert len(a_actions) == 1
    assert a_actions[0]["source"] == "button"
    assert a_actions[0]["id"] != action_id


# =============================================================================
# Middleware resilience: must never break or slow the wrapped endpoint
# =============================================================================


def test_middleware_never_breaks_the_endpoint_when_audit_write_fails(
    client, headers_a, monkeypatch
):
    """Simulates migration 014 not being applied yet (table doesn't exist) --
    or any other audit-write failure -- and asserts the wrapped endpoint's
    response is completely unaffected."""

    def _boom(*args, **kwargs):
        raise RuntimeError('relation "agent_actions" does not exist')

    monkeypatch.setattr(agent_middleware, "create_action", _boom)

    res = client.post("/api/catalog/idea-6/lock", headers=headers_a)
    assert res.status_code == 200
    assert res.json() == {"locked": True}


def test_middleware_never_breaks_the_endpoint_on_update_failure(
    client, headers_a, monkeypatch
):
    def _boom(*args, **kwargs):
        raise RuntimeError("Supabase unreachable")

    monkeypatch.setattr(agent_middleware, "update_action", _boom)

    res = client.post(
        "/api/catalog/idea-7/lock",
        headers={**headers_a, "X-Agent-Action-Id": "some-id"},
    )
    assert res.status_code == 200
    assert res.json() == {"locked": True}


# =============================================================================
# /api/agent/actions endpoints
# =============================================================================


def test_create_patch_list_action_roundtrip(client, headers_a, session_a):
    created = client.post(
        "/api/agent/actions",
        headers=headers_a,
        json={
            "step": "script",
            "action": "iterate_scene",
            "idea_id": "idea-8",
            "args": {"scene_n": 3},
            "utterance": "make the hook punchier",
            "restatement": "Iterate scene 3 -- 2 credits. Say confirm to go ahead.",
            "credits": 2,
        },
    )
    assert created.status_code == 201
    action_id = created.json()["id"]

    patched = client.patch(
        f"/api/agent/actions/{action_id}",
        headers=headers_a,
        json={"confirmation": "confirm", "confirmed_at": "2026-09-26T00:00:00Z", "status": "running"},
    )
    assert patched.status_code == 200
    assert patched.json() == {"id": action_id, "status": "running"}

    listed = client.get("/api/agent/actions?idea_id=idea-8", headers=headers_a)
    row = listed.json()["actions"][0]
    assert row["confirmation"] == "confirm"
    assert row["status"] == "running"
    assert row["args"] == {"scene_n": 3}


def test_patch_action_not_owned_returns_404(client, headers_a, headers_b):
    created = client.post(
        "/api/agent/actions",
        headers=headers_a,
        json={"step": "script", "action": "iterate_scene", "idea_id": "idea-9"},
    )
    action_id = created.json()["id"]

    res = client.patch(
        f"/api/agent/actions/{action_id}",
        headers=headers_b,
        json={"status": "done"},
    )
    assert res.status_code == 404


def test_patch_action_missing_returns_404(client, headers_a):
    res = client.patch(
        "/api/agent/actions/does-not-exist",
        headers=headers_a,
        json={"status": "done"},
    )
    assert res.status_code == 404


def test_list_returns_only_callers_own_rows(client, headers_a, headers_b):
    client.post(
        "/api/agent/actions",
        headers=headers_a,
        json={"step": "catalog", "action": "lock_catalog", "idea_id": "idea-10"},
    )
    client.post(
        "/api/agent/actions",
        headers=headers_b,
        json={"step": "catalog", "action": "lock_catalog", "idea_id": "idea-10"},
    )

    a_actions = client.get("/api/agent/actions?idea_id=idea-10", headers=headers_a).json()["actions"]
    b_actions = client.get("/api/agent/actions?idea_id=idea-10", headers=headers_b).json()["actions"]

    assert len(a_actions) == 1
    assert len(b_actions) == 1
    assert a_actions[0]["id"] != b_actions[0]["id"]


def test_create_action_requires_auth(client):
    res = client.post(
        "/api/agent/actions",
        json={"step": "catalog", "action": "lock_catalog"},
    )
    assert res.status_code == 401


def test_create_action_rejects_invalid_status(client, headers_a):
    res = client.post(
        "/api/agent/actions",
        headers=headers_a,
        json={"step": "catalog", "action": "lock_catalog", "status": "done"},
    )
    assert res.status_code == 422
