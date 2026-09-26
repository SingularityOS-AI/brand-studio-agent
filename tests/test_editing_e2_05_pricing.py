"""Tests for PIECE E2-05 — Engine version in the render key + render pricing (P1).

Covers: the 3 render prices (RENDER_CREDITS / RERENDER_CREDITS / free-after-engine-
update), double-click idempotency (no duplicate charge), and refund on failure.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    find_jobs,
    get_job,
    mark_done,
    mark_failed,
)
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing import dispatch as dispatch_mod
from app.editing import router as router_mod
from app.editing.dispatch import refund_failed_prepaid
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_or_create_edit, save_edit

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"authorization": "Bearer tok_test"}


class MockScript:
    """Mock script model for testing (1 scene, locked)."""

    def __init__(self) -> None:
        self.state = "locked"
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 10
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
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


_user_credits = 100


def _mock_deduct_credits(session_token: str, amount: int) -> int:
    global _user_credits
    if _user_credits < amount:
        raise HTTPException(status_code=402, detail="Insufficient credits balance")
    _user_credits -= amount
    return _user_credits


def _mock_get_remaining_credits(session_token: str) -> int:
    return _user_credits


def _mock_refund_credits(session_token: str, amount: int, source: str = "") -> int:
    global _user_credits
    _user_credits += amount
    return _user_credits


def _engine_version_fn(version: str):
    """Builds a fake async get_engine_version() returning a fixed value."""

    async def _fn() -> str:
        return version

    return _fn


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resets storage and mocks external dependencies (no real network/APIs)."""
    global _user_credits
    _user_credits = 100
    _reset_local_jobs()
    _reset_local_edits()
    router_mod._signed_url_cache.clear()
    dispatch_mod._reset_engine_version_cache()

    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test"
    )
    monkeypatch.setattr("app.guard.guard.deduct_credits", _mock_deduct_credits)
    monkeypatch.setattr("app.guard.guard.get_remaining_credits", _mock_get_remaining_credits)
    monkeypatch.setattr("app.guard.guard.refund_credits", _mock_refund_credits)
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, idea: MockScript())

    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret")
    monkeypatch.setattr(dispatch_config, "RENDER_CREDITS", 20)
    monkeypatch.setattr(dispatch_config, "RERENDER_CREDITS", 5)

    # Default: render service /health reachable-but-unmocked calls resolve to a
    # fixed engine version so pricing decisions in a test are deterministic.
    monkeypatch.setattr(router_mod, "get_engine_version", _engine_version_fn("2026.01.01-1"))


def _prepare_raw_ready(idea_id: str = "idea1", raw_storage_path: str = "renders/raw.mp4") -> str:
    """Adds a done take/transcript for scene 1 and a done+fresh raw render.

    Returns the edit_version after saving raw_render.
    """
    t = create_job("tok_test", idea_id, scene_n=1, kind="a_roll_take")
    mark_done(t["id"], output={"storage_path": "takes/s1.mp4", "duration_ms": 5000})
    tr = create_job(
        "tok_test", idea_id, scene_n=1, kind="transcript", input={"take_job_id": t["id"]}
    )
    mark_done(tr["id"], output={
        "words": [{"text": "hi", "start_ms": 0, "end_ms": 300}],
    })

    state = client.get(f"/api/editing/{idea_id}", headers=HEADERS).json()
    t_hash = state["timeline"]["hash"]
    edit_ver = state["edit_version"]
    updated = save_edit(
        "tok_test",
        idea_id,
        {
            "raw_render": {
                "status": "done",
                "storage_path": raw_storage_path,
                "timeline_hash": t_hash,
            }
        },
        expected_version=edit_ver,
    )
    return updated["version"]


def test_state_render_price_with_no_ir_and_no_previous_render() -> None:
    """render_price/render_price_kind are always emitted, even before an IR exists.

    With no takes yet, timeline (and so ir) is None; render_price must not depend
    on a content_hash to know there is no previous done render.
    """
    resp = client.get("/api/editing/idea_fresh", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ir"] is None
    assert data["render_price"] == 20
    assert data["render_price_kind"] == "first"


def test_first_render_charges_render_credits() -> None:
    """No previous done render for the idea -> RENDER_CREDITS (20)."""
    _prepare_raw_ready()

    resp = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp.status_code == 202
    data = resp.json()
    assert data["created"] is True
    assert data["job"]["credits"] == 20
    assert data["job"]["charged"] is True
    assert data["credits_remaining"] == 80


def test_later_render_of_same_idea_charges_rerender_credits() -> None:
    """A later render, even when the engine is unchanged, prices at RERENDER_CREDITS (5)."""
    _prepare_raw_ready()

    resp1 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp1.status_code == 202
    job1 = resp1.json()["job"]
    content_hash_1 = job1["input"]["content_hash"]

    edit = get_or_create_edit("tok_test", "idea1")
    save_edit(
        "tok_test",
        "idea1",
        {
            "render": {
                "job_id": job1["id"],
                "status": "done",
                "storage_path": "renders/v1.mp4",
                "content_hash": content_hash_1,
                "engine_version": "2026.01.01-1",
            }
        },
        expected_version=edit["version"],
    )

    # Simulate a new raw cut for the same idea (new content -> new content_hash),
    # engine unchanged.
    _prepare_raw_ready(raw_storage_path="renders/raw_v2.mp4")

    resp2 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["created"] is True
    assert data2["job"]["credits"] == 5
    assert data2["job"]["charged"] is True
    assert data2["credits_remaining"] == 100 - 20 - 5


def test_rerender_after_engine_update_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same content (IR+raw unchanged), only the engine version changed -> free."""
    _prepare_raw_ready()

    resp1 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp1.status_code == 202
    job1 = resp1.json()["job"]
    content_hash_1 = job1["input"]["content_hash"]
    assert job1["input"]["engine_version"] == "2026.01.01-1"

    edit = get_or_create_edit("tok_test", "idea1")
    save_edit(
        "tok_test",
        "idea1",
        {
            "render": {
                "job_id": job1["id"],
                "status": "done",
                "storage_path": "renders/v1.mp4",
                "content_hash": content_hash_1,
                "engine_version": "2026.01.01-1",
            }
        },
        expected_version=edit["version"],
    )

    credits_before_2 = _user_credits

    # The render engine was redeployed: /health now reports a new engine_version.
    monkeypatch.setattr(router_mod, "get_engine_version", _engine_version_fn("2026.09.26-1"))

    resp2 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["created"] is True
    assert data2["job"]["credits"] == 0
    assert data2["job"]["charged"] is False
    assert data2["credits_remaining"] == credits_before_2
    assert _user_credits == credits_before_2


def test_double_click_render_is_idempotent_no_double_charge() -> None:
    """Clicking Render twice with nothing changed reuses the job; no extra charge."""
    _prepare_raw_ready()

    r1 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert r1.status_code == 202
    res1 = r1.json()
    assert res1["created"] is True
    credits_after_1 = _user_credits

    r2 = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert r2.status_code == 202
    res2 = r2.json()
    assert res2["created"] is False
    assert res2["job"]["id"] == res1["job"]["id"]
    assert _user_credits == credits_after_1


def test_refund_on_render_failure() -> None:
    """A failed, charged render job is refunded by refund_failed_prepaid()."""
    _prepare_raw_ready()

    resp = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp.status_code == 202
    job = resp.json()["job"]
    assert job["credits"] == 20
    credits_after_charge = _user_credits
    assert credits_after_charge == 80

    mark_failed(job["id"], "render engine crashed")
    assert get_job(job["id"])["charged"] is True

    refunded_count = refund_failed_prepaid()
    assert refunded_count == 1
    assert _user_credits == 100

    remaining_charged_failed = [
        j
        for j in find_jobs(kinds=["render"], statuses=["failed"], charged=True)
        if j["id"] == job["id"]
    ]
    assert remaining_charged_failed == []
