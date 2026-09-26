import pytest
from fastapi.testclient import TestClient

from app.agent import store
import app.main
from app.guard import guard

# Add a dummy route to main app for middleware testing to avoid hitting actual routes that require DB
from fastapi import APIRouter
from pydantic import BaseModel

dummy_router = APIRouter()
class DummyReq(BaseModel):
    topic: str

@dummy_router.post("/api/catalog/dummy_audit_test")
def dummy_catalog(req: DummyReq):
    return {"ok": True}

app.main.app.include_router(dummy_router)

# Ensure we use in-memory store for tests
store._get_supabase_client = lambda: None

client = TestClient(app.main.app)

@pytest.fixture(autouse=True)
def setup_teardown():
    store._reset_local_actions()
    yield
    store._reset_local_actions()

def test_create_voice_action_route(test_jwt_token):
    resp = client.post(
        "/api/agent/actions",
        json={"action": "iterate_scene", "restatement": "Say confirm", "step": "script", "idea_id": "idea1"},
        headers={"Authorization": f"Bearer {test_jwt_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data

    actions = store._local_agent_actions
    assert len(actions) == 1
    assert actions[0]["id"] == data["id"]
    assert actions[0]["source"] == "voice"
    assert actions[0]["status"] == "proposed" # Because restatement is provided

def test_update_voice_action_route(test_jwt_token):
    # Create
    resp = client.post(
        "/api/agent/actions",
        json={"action": "iterate_scene", "step": "script"}, # No restatement -> queued
        headers={"Authorization": f"Bearer {test_jwt_token}"}
    )
    action_id = resp.json()["id"]

    # Update
    resp = client.patch(
        f"/api/agent/actions/{action_id}",
        json={"status": "done", "confirmation": "yes"},
        headers={"Authorization": f"Bearer {test_jwt_token}"}
    )
    assert resp.status_code == 200

    actions = store._local_agent_actions
    assert actions[0]["status"] == "done"
    assert actions[0]["confirmation"] == "yes"

def test_list_actions_route(test_jwt_token):
    client.post("/api/agent/actions", json={"action": "act1", "idea_id": "idea1"}, headers={"Authorization": f"Bearer {test_jwt_token}"})
    client.post("/api/agent/actions", json={"action": "act2", "idea_id": "idea2"}, headers={"Authorization": f"Bearer {test_jwt_token}"})

    # List all
    resp = client.get("/api/agent/actions", headers={"Authorization": f"Bearer {test_jwt_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # List by idea_id
    resp = client.get("/api/agent/actions?idea_id=idea1", headers={"Authorization": f"Bearer {test_jwt_token}"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["action"] == "act1"

def test_middleware_voice_header_updates_row(test_jwt_token, test_user_id):
    # create a voice action manually in the store
    session_token = guard.get_or_create_user_session(test_user_id)
    action = store.create_action({
        "session_token": session_token,
        "source": "voice",
        "action": "test_action",
        "status": "queued"
    })
    action_id = action["id"]

    # hit an endpoint that middleware intercepts
    resp = client.post(
        "/api/catalog/dummy_audit_test",
        json={"topic": "test"},
        headers={"Authorization": f"Bearer {test_jwt_token}", "X-Agent-Action-Id": action_id}
    )
    # Wait for the background tasks to finish
    # Since test client might not run the event loop after returning, we can just yield control briefly
    # But wait, asyncio.sleep doesn't work well outside async tests. So let's sleep briefly.
    import time
    time.sleep(0.1)

    # The endpoint should run normally, and middleware should update status based on resp
    assert resp.status_code == 200

    actions = store._local_agent_actions
    # The middleware should have updated the voice action
    assert actions[0]["status"] == "done"

def test_middleware_button_creates_row(test_jwt_token):
    resp = client.post(
        "/api/catalog/dummy_audit_test",
        json={"topic": "test"},
        headers={"Authorization": f"Bearer {test_jwt_token}"} # NO header
    )
    assert resp.status_code == 200

    import time
    time.sleep(0.1)

    actions = store._local_agent_actions
    assert len(actions) == 1
    assert actions[0]["source"] == "button"
    assert actions[0]["status"] == "done"
    # Action should be roughly POST /api/catalog/dummy_audit_test (or with template)
    assert "POST" in actions[0]["action"]

def test_middleware_failure_updates_row(test_jwt_token, test_user_id):
    session_token = guard.get_or_create_user_session(test_user_id)
    action = store.create_action({
        "session_token": session_token,
        "source": "voice",
        "action": "test_action",
        "status": "queued"
    })
    action_id = action["id"]

    # hit an endpoint that fails
    resp = client.post(
        "/api/catalog/missing_route", # Non-existent route returns 404
        headers={"Authorization": f"Bearer {test_jwt_token}", "X-Agent-Action-Id": action_id}
    )
    assert resp.status_code == 404

    import time
    time.sleep(0.1)

    actions = store._local_agent_actions
    assert actions[0]["status"] == "failed"

def test_middleware_exception_swallowed(test_jwt_token):
    # If the store throws an exception, the request should still succeed.
    original_update = store.update_action

    def buggy_update(*args, **kwargs):
        raise ValueError("Store failed")

    store.update_action = buggy_update
    try:
        resp = client.post(
            "/api/catalog/dummy_audit_test",
            json={"topic": "test"},
            headers={"Authorization": f"Bearer {test_jwt_token}", "X-Agent-Action-Id": "fake-id"}
        )
        assert resp.status_code == 200
    finally:
        store.update_action = original_update
