"""H8-03: a new render engine rebuilds the raw cut (never discarding the paid dressing)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audiovisual.jobs import _reset_local_jobs, create_job, mark_done
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing import router as router_mod
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_or_create_edit, save_edit
from app.editing.timeline import cut_hash

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"authorization": "Bearer tok_test"}
IDEA = "idea_h8_03"


class MockScript:
    def __init__(self) -> None:
        self.state = "locked"
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 10
        self.frame_zero = {"visual": "v", "on_screen_text": "Hook", "why_it_stops_the_scroll": "x"}
        self.scenes = [
            {
                "n": 1,
                "start_s": 0.0,
                "end_s": 5.0,
                "phase": "hook",
                "spoken_text": "Spoken text for scene 1",
                "shot": "medium shot",
                "on_screen_text": "Text scene 1",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            }
        ]

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }


def _engine(version: str):
    async def _fn() -> str:
        return version

    return _fn


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_local_jobs()
    _reset_local_edits()
    router_mod._signed_url_cache.clear()
    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr("app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test")
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, idea: MockScript())
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret")
    monkeypatch.setattr(router_mod, "get_engine_version", _engine("engine-A"))

    t = create_job("tok_test", IDEA, scene_n=1, kind="a_roll_take")
    mark_done(t["id"], output={"storage_path": "takes/s1.mp4", "duration_ms": 5000})
    tr = create_job(
        "tok_test", IDEA, scene_n=1, kind="transcript", input={"take_job_id": t["id"]}
    )
    mark_done(tr["id"], output={"words": [{"text": "hi", "start_ms": 0, "end_ms": 300}]})


def _set_engine(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(router_mod, "get_engine_version", _engine(version))


def _build_raw() -> dict[str, Any]:
    """POST /raw, then mark the job done the way the worker does."""
    resp = client.post(f"/api/editing/{IDEA}/raw", headers=HEADERS)
    assert resp.status_code in (200, 202), resp.text
    body = resp.json()
    job = body["job"]
    if not body.get("reused"):
        out = {
            "job_id": job["id"],
            "status": "done",
            "storage_path": f"renders/{job['id']}.mp4",
            "duration_ms": 5000,
            "bytes": 10,
            "render_s": 1.0,
            "timeline_hash": job["input"]["timeline"]["hash"],
        }
        mark_done(job["id"], output=out)
        edit = get_or_create_edit("tok_test", IDEA)
        save_edit("tok_test", IDEA, {"raw_render": out}, expected_version=edit["version"])
    return body


def _raw_state() -> dict[str, Any]:
    return client.get(f"/api/editing/{IDEA}", headers=HEADERS).json()["raw"]


def test_same_content_same_engine_is_reused() -> None:
    first = _build_raw()
    second = client.post(f"/api/editing/{IDEA}/raw", headers=HEADERS)
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["job"]["id"] == first["job"]["id"]


def test_same_content_new_engine_creates_new_job(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _build_raw()
    assert _raw_state()["fresh"] is True

    _set_engine(monkeypatch, "engine-B")
    assert _raw_state()["fresh"] is False

    second = client.post(f"/api/editing/{IDEA}/raw", headers=HEADERS)
    assert second.status_code == 202
    assert second.json()["created"] is True
    assert second.json()["job"]["id"] != first["job"]["id"]
    assert second.json()["job"]["input"]["engine_version"] == "engine-B"
    assert second.json()["job"]["credits"] == 0


def test_rebuilt_raw_is_fresh_and_reused_on_its_own_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_raw()
    _set_engine(monkeypatch, "engine-B")
    rebuilt = _build_raw()
    assert _raw_state()["fresh"] is True
    again = client.post(f"/api/editing/{IDEA}/raw", headers=HEADERS)
    assert again.json()["reused"] is True
    assert again.json()["job"]["id"] == rebuilt["job"]["id"]


def test_unknown_engine_reuses_and_never_stales(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _build_raw()
    _set_engine(monkeypatch, "unknown")
    assert _raw_state()["fresh"] is True
    again = client.post(f"/api/editing/{IDEA}/raw", headers=HEADERS)
    assert again.status_code == 200
    assert again.json()["reused"] is True
    assert again.json()["job"]["id"] == first["job"]["id"]


def test_raw_without_recorded_engine_is_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw built before the engine was recorded has no engine: treated as unknown."""
    _build_raw()
    edit = get_or_create_edit("tok_test", IDEA)
    raw = dict(edit["raw_render"])
    raw.pop("engine_version", None)
    raw["job_id"] = "legacy-job-not-in-list"
    save_edit("tok_test", IDEA, {"raw_render": raw}, expected_version=edit["version"])
    _set_engine(monkeypatch, "engine-B")
    assert _raw_state()["fresh"] is True


def test_dressing_stays_fresh_across_raw_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_raw()
    state = client.get(f"/api/editing/{IDEA}", headers=HEADERS).json()
    c_hash = cut_hash(state["timeline"])
    edit = get_or_create_edit("tok_test", IDEA)
    save_edit(
        "tok_test",
        IDEA,
        {"dressing": {"scenes": {"1": {"overlays": []}}, "raw_hash": c_hash}},
        expected_version=edit["version"],
    )
    before = get_or_create_edit("tok_test", IDEA)["dressing"]

    _set_engine(monkeypatch, "engine-B")
    _build_raw()

    after = get_or_create_edit("tok_test", IDEA)["dressing"]
    assert after == before
    state2 = client.get(f"/api/editing/{IDEA}", headers=HEADERS).json()
    assert cut_hash(state2["timeline"]) == c_hash
    assert after["raw_hash"] == c_hash
