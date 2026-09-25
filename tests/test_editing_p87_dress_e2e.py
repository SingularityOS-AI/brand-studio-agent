"""Tests for Pieza 87: Dress All end-to-end integration (Bloque E)."""
from typing import Any
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audiovisual.jobs import _reset_local_jobs, create_job
from app.auth.supabase_auth import supabase_auth
from app.editing.router import router
from app.editing.store import _reset_local_edits

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _reset_local_jobs_insert(job: dict[str, Any]) -> None:
    from app.audiovisual.jobs import _jobs_lock, _local_jobs
    with _jobs_lock:
        _local_jobs[job["id"]] = job


class MockScript:
    """Mock script model for testing."""

    def __init__(self, state: str = "locked", num_scenes: int = 2) -> None:
        self.state = state
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 60
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Texto Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
        scenes_list = []
        for i in range(1, num_scenes + 1):
            scenes_list.append({
                "n": i,
                "start_s": (i - 1) * 5.0,
                "end_s": i * 5.0,
                "phase": "hook" if i == 1 else "body_1",
                "spoken_text": f"Spoken words for scene {i} are clear and impactful",
                "shot": "medium shot",
                "on_screen_text": f"Text scene {i}",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            })
        self.scenes = scenes_list

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }


@pytest.fixture(autouse=True)
def setup_teardown(monkeypatch):
    _reset_local_jobs()
    _reset_local_edits()
    monkeypatch.setattr(supabase_auth, "get_user_id", lambda token: "test_user_p87")
    monkeypatch.setattr("app.guard.guard.get_or_create_user_session", lambda uid: "sess_p87")


def test_dress_endpoint_returns_valid_dressing_and_ir(monkeypatch):
    """POST /dress generates dressing from catalog and enriches IR to stage 2."""
    session_token = "sess_p87"
    idea_id = "idea_p87_dress"
    mock_s = MockScript(state="locked", num_scenes=2)

    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)

    # Populate takes and transcripts for both scenes
    for sc in (1, 2):
        t = create_job(
            session_token=session_token,
            idea_id=idea_id,
            scene_n=sc,
            kind="a_roll_take",
            credits=0,
            cost_usd=0.0,
        )
        t["status"] = "done"
        t["output"] = {
            "storage_path": f"library/takes/{sc}.webm",
            "mime": "video/webm",
            "duration_s": 5.0,
            "role": "on_camera",
        }
        _reset_local_jobs_insert(t)

        tr = create_job(
            session_token=session_token,
            idea_id=idea_id,
            scene_n=sc,
            kind="transcript",
            credits=0,
            cost_usd=0.0,
        )
        tr["status"] = "done"
        tr["output"] = {
            "words": [
                {"text": "Hello", "start_ms": 100, "end_ms": 500, "confidence": 0.99},
                {"text": "world", "start_ms": 600, "end_ms": 1200, "confidence": 0.99},
                {"text": "scene", "start_ms": 1300, "end_ms": 2000, "confidence": 0.99},
            ]
        }
        _reset_local_jobs_insert(tr)

    headers = {"Authorization": "Bearer fake_token"}

    resp = client.post(f"/api/editing/{idea_id}/dress", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Verify dressing structure
    assert "dressing" in data or "timeline" in data
    ir = data.get("ir")
    assert ir is not None
    assert ir["schema"] == "brandstudio.ir.v1"
    # Stage 2 IR must include zoom_keys, transitions, and sfx lists
    assert "zoom_keys" in ir
    assert isinstance(ir["zoom_keys"], list)
    assert "transitions" in ir
    assert isinstance(ir["transitions"], list)
    assert "sfx" in ir
    assert isinstance(ir["sfx"], list)


def test_state_uses_ir_stage2_when_dressed(monkeypatch):
    """Subsequent GET /api/editing/{idea_id} uses build_ir_stage2."""
    session_token = "sess_p87"
    idea_id = "idea_p87_get"
    mock_s = MockScript(state="locked", num_scenes=1)

    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)

    t = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="a_roll_take",
        credits=0,
        cost_usd=0.0,
    )
    t["status"] = "done"
    t["output"] = {"storage_path": "library/takes/1.webm", "duration_s": 4.0}
    _reset_local_jobs_insert(t)

    tr = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="transcript",
        credits=0,
        cost_usd=0.0,
    )
    tr["status"] = "done"
    tr["output"] = {"words": [{"text": "Testing", "start_ms": 100, "end_ms": 600, "confidence": 0.99}]}
    _reset_local_jobs_insert(tr)

    headers = {"Authorization": "Bearer fake_token"}

    # Dress first
    dress_resp = client.post(f"/api/editing/{idea_id}/dress", headers=headers)
    assert dress_resp.status_code == 200, dress_resp.text

    # Query GET
    get_resp = client.get(f"/api/editing/{idea_id}", headers=headers)
    assert get_resp.status_code == 200
    state = get_resp.json()
    assert state["ir"] is not None
    assert "zoom_keys" in state["ir"]
    assert "transitions" in state["ir"]
    assert "sfx" in state["ir"]


def test_dress_endpoint_handles_missing_takes(monkeypatch):
    """POST /dress returns 409 if takes are missing."""
    session_token = "sess_p87"
    idea_id = "idea_p87_missing"
    mock_s = MockScript(state="locked", num_scenes=2)

    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)

    # Only scene 1 has a take; scene 2 is missing
    t = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="a_roll_take",
        credits=0,
        cost_usd=0.0,
    )
    t["status"] = "done"
    t["output"] = {"storage_path": "library/takes/1.webm", "duration_s": 4.0}
    _reset_local_jobs_insert(t)

    headers = {"Authorization": "Bearer fake_token"}
    resp = client.post(f"/api/editing/{idea_id}/dress", headers=headers)
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("code") == "missing_takes"
    assert 2 in body.get("scenes", [])


def test_capitan_app_mounts_editing_router():
    """QA del Capitán: la app real sirve /api/editing (el router responde su propio 401, no un 404)."""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    client = TestClient(main_mod.app)
    for method, path in (("get", "/api/editing/idea_x"), ("post", "/api/editing/idea_x/dress"), ("post", "/api/editing/idea_x/render")):
        resp = getattr(client, method)(path)
        assert resp.status_code == 401, (path, resp.status_code)
    assert client.get("/api/no_such_route_xyz").status_code == 404
