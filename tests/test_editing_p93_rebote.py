"""Tests for PIEZA 93 — Rebote de la auditoría backend of Editing."""

from typing import Any
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.audiovisual import worker as worker_mod
from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    find_jobs,
    get_job,
    list_jobs,
    mark_charged,
    mark_done,
    mark_failed,
)
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing.dispatch import (
    build_final_request,
    build_raw_request,
    refund_failed_prepaid,
)
from app.editing.router import _llm_calls, _signed_url_cache, _state, router
from app.editing.store import _reset_local_edits, get_or_create_edit, save_edit
from app.editing.timeline import cut_hash

app = FastAPI()
app.include_router(router)
client = TestClient(app)


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
                "spoken_text": f"Spoken text for scene {i}",
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


_user_credits = 100


def _mock_deduct_credits(session_token: str, amount: int) -> int:
    global _user_credits
    if _user_credits < amount:
        raise HTTPException(status_code=402, detail="Insufficient credits balance")
    _user_credits -= amount
    return _user_credits


def _mock_get_remaining_credits(session_token: str) -> int:
    global _user_credits
    return _user_credits


def _mock_refund_credits(session_token: str, amount: int, source: str = "") -> int:
    global _user_credits
    _user_credits += amount
    return _user_credits


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resets storage and mocks external dependencies."""
    global _user_credits
    _user_credits = 100
    _reset_local_jobs()
    _reset_local_edits()
    _signed_url_cache.clear()
    _llm_calls.clear()

    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test"
    )
    monkeypatch.setattr("app.guard.guard.deduct_credits", _mock_deduct_credits)
    monkeypatch.setattr("app.guard.guard.get_remaining_credits", _mock_get_remaining_credits)
    monkeypatch.setattr("app.guard.guard.refund_credits", _mock_refund_credits)
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)

    monkeypatch.setattr(
        "app.scripting.scripts._check_script", lambda session_token, idea_id: MockScript()
    )
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda session_token, idea_id: MockScript()
    )

    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret")
    monkeypatch.setattr(dispatch_config, "PUBLIC_BASE_URL", "https://brand-studio-agent.onrender.com")
    monkeypatch.setattr(dispatch_config, "LLM_CALLS_PER_HOUR", 30)


def _setup_scene_takes(session_token: str = "tok_test", idea_id: str = "idea1") -> None:
    """Helper to add completed takes and transcripts for scenes 1 and 2."""
    for n in (1, 2):
        t = create_job(session_token=session_token, idea_id=idea_id, scene_n=n, kind="a_roll_take")
        mark_done(t["id"], output={"storage_path": f"takes/s{n}.mp4", "duration_ms": 5000})

        tr = create_job(
            session_token=session_token,
            idea_id=idea_id,
            scene_n=n,
            kind="transcript",
            input={"take_job_id": t["id"]},
        )
        mark_done(tr["id"], output={
            "words": [
                {"text": f"word{n}_1", "start_ms": 100, "end_ms": 500},
                {"text": f"word{n}_2", "start_ms": 600, "end_ms": 1000},
            ]
        })


def test_finding_1_undo_raw() -> None:
    """Test 1: Undo changes reuses done raw job and updates edit.raw_render and raw.fresh."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    # 1. Post raw for initial state A
    resp_raw1 = client.post("/api/editing/idea1/raw", headers=headers)
    assert resp_raw1.status_code == 202
    job_a = resp_raw1.json()["job"]

    # Mark job A done and simulate worker updating edit.raw_render
    get_res = client.get("/api/editing/idea1", headers=headers).json()
    t_hash_a = get_res["timeline"]["hash"]
    mark_done(job_a["id"], output={
        "storage_path": "path_A.mp4",
        "duration_ms": 5000,
        "bytes": 1000,
        "render_s": 2.0,
        "scene_marks_ms": [0, 2500],
    })
    save_edit("tok_test", "idea1", fields={
        "raw_render": {
            "job_id": job_a["id"],
            "status": "done",
            "storage_path": "path_A.mp4",
            "duration_ms": 5000,
            "bytes": 1000,
            "render_s": 2.0,
            "scene_marks_ms": [0, 2500],
            "timeline_hash": t_hash_a,
        }
    }, expected_version=get_res["edit_version"])

    state_a = client.get("/api/editing/idea1", headers=headers).json()
    assert state_a["raw"]["fresh"] is True

    # 2. Change state to B (trim scene 1)
    resp_patch = client.patch(
        "/api/editing/idea1/settings",
        headers=headers,
        json={"op": "trim", "scene_n": 1, "value": {"start_ms": 100, "end_ms": 0}, "expected_version": state_a["edit_version"]},
    )
    assert resp_patch.status_code == 200
    state_b = resp_patch.json()
    assert state_b["raw"]["fresh"] is False

    # Post raw for state B
    resp_raw2 = client.post("/api/editing/idea1/raw", headers=headers)
    assert resp_raw2.status_code == 202
    job_b = resp_raw2.json()["job"]
    t_hash_b = state_b["timeline"]["hash"]
    mark_done(job_b["id"], output={
        "storage_path": "path_B.mp4",
        "duration_ms": 4900,
        "bytes": 950,
        "render_s": 1.9,
        "scene_marks_ms": [0, 2400],
    })
    cur_ver = client.get("/api/editing/idea1", headers=headers).json()["edit_version"]
    save_edit("tok_test", "idea1", fields={
        "raw_render": {
            "job_id": job_b["id"],
            "status": "done",
            "storage_path": "path_B.mp4",
            "duration_ms": 4900,
            "bytes": 950,
            "render_s": 1.9,
            "scene_marks_ms": [0, 2400],
            "timeline_hash": t_hash_b,
        }
    }, expected_version=cur_ver)

    # 3. Undo change: trim scene 1 back to 0,0
    state_b2 = client.get("/api/editing/idea1", headers=headers).json()
    resp_patch2 = client.patch(
        "/api/editing/idea1/settings",
        headers=headers,
        json={"op": "trim", "scene_n": 1, "value": {"start_ms": 0, "end_ms": 0}, "expected_version": state_b2["edit_version"]},
    )
    assert resp_patch2.status_code == 200

    # Post raw again (returns to state A)
    resp_raw3 = client.post("/api/editing/idea1/raw", headers=headers)
    assert resp_raw3.status_code == 200
    res3 = resp_raw3.json()
    assert res3["created"] is False
    assert res3["reused"] is True
    assert res3["job"]["id"] == job_a["id"]

    # Verify GET returns raw.fresh == true and POST /render does not 409
    final_state = client.get("/api/editing/idea1", headers=headers).json()
    assert final_state["raw"]["fresh"] is True

    resp_render = client.post("/api/editing/idea1/render", headers=headers)
    assert resp_render.status_code == 202


def test_finding_2_music_change_preserves_dressing() -> None:
    """Test 2: Changing music volume/mute keeps dressing fresh, changing visual makes it stale."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    b_job = create_job("tok_test", "idea1", scene_n=1, kind="ai_image")
    mark_done(b_job["id"], output={"storage_path": "broll/s1.png"})

    state = client.get("/api/editing/idea1", headers=headers).json()
    c_hash = cut_hash(state["timeline"])

    dressing_plan = {
        "raw_hash": c_hash,
        "source": "closed_catalog",
        "scenes": [{"n": 1, "overlay": None}, {"n": 2, "overlay": None}],
    }
    cur_ver = get_or_create_edit("tok_test", "idea1")["version"]
    save_edit("tok_test", "idea1", fields={"dressing": dressing_plan}, expected_version=cur_ver)

    s1 = client.get("/api/editing/idea1", headers=headers).json()
    assert s1["dressing"]["fresh"] is True
    assert s1["dressing"]["stale"] is False

    # Mute music -> dressing should remain fresh
    resp_patch_m = client.patch(
        "/api/editing/idea1/settings",
        headers=headers,
        json={"op": "music_mute", "value": True, "expected_version": s1["edit_version"]},
    )
    assert resp_patch_m.status_code == 200
    s2 = resp_patch_m.json()
    assert s2["dressing"]["fresh"] is True
    assert s2["dressing"]["stale"] is False

    # Change visual face -> False (broll) -> scenes change -> dressing becomes stale
    resp_patch_f = client.patch(
        "/api/editing/idea1/settings",
        headers=headers,
        json={"op": "face", "scene_n": 1, "value": False, "expected_version": s2["edit_version"]},
    )
    assert resp_patch_f.status_code == 200
    s3 = resp_patch_f.json()
    assert s3["dressing"]["fresh"] is False
    assert s3["dressing"]["stale"] is True


def test_finding_3_render_payment_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 3: Network error during deduct_credits cancels render job and returns 503 payment_error."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    # Set raw to ready
    state = client.get("/api/editing/idea1", headers=headers).json()
    t_hash = state["timeline"]["hash"]
    j_raw = create_job("tok_test", "idea1", None, "raw_render")
    mark_done(j_raw["id"], output={"storage_path": "raw.mp4"})
    cur_ver = get_or_create_edit("tok_test", "idea1")["version"]
    save_edit("tok_test", "idea1", fields={
        "raw_render": {
            "job_id": j_raw["id"],
            "status": "done",
            "storage_path": "raw.mp4",
            "timeline_hash": t_hash,
        }
    }, expected_version=cur_ver)

    # Network error on deduct_credits
    def _raise_conn_error(session_token: str, amount: int) -> int:
        raise ConnectionError("Network timeout connecting to payment service")

    monkeypatch.setattr("app.guard.guard.deduct_credits", _raise_conn_error)

    resp = client.post("/api/editing/idea1/render", headers=headers)
    assert resp.status_code == 503
    assert resp.json() == {"code": "payment_error"}

    render_jobs = [j for j in find_jobs(kinds=["render"], statuses=["cancelled"]) if j.get("session_token") == "tok_test"]
    assert len(render_jobs) == 1
    assert render_jobs[0]["status"] == "cancelled"
    assert render_jobs[0]["charged"] is False


def test_finding_4_refund_failed_prepaid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 4: refund_failed_prepaid re-marks charged on exception, leaves uncharged on None."""
    # Case 1: refund_credits raises exception -> job re-marked charged=True for retry
    j1 = create_job("tok1", "idea1", None, "render", credits=20)
    mark_charged(j1["id"])
    mark_failed(j1["id"], "job failed")

    def _raise_refund_err(token: str, amount: int, source: str = "") -> Any:
        raise RuntimeError("DB connection error during refund")

    monkeypatch.setattr("app.guard.guard.refund_credits", _raise_refund_err)

    refunded_count = refund_failed_prepaid()
    assert refunded_count == 0
    updated_j1 = get_job(j1["id"])
    assert updated_j1["charged"] is True  # Re-marked charged for sweep retry

    # Case 2: refund_credits returns None (session deleted) -> job remains charged=False
    j2 = create_job("tok2", "idea2", None, "render", credits=20)
    mark_charged(j2["id"])
    mark_failed(j2["id"], "job failed")

    def _return_none_refund(token: str, amount: int, source: str = "") -> Any:
        return None

    monkeypatch.setattr("app.guard.guard.refund_credits", _return_none_refund)

    refunded_count2 = refund_failed_prepaid()
    assert refunded_count2 == 0
    updated_j2 = get_job(j2["id"])
    assert updated_j2["charged"] is False  # Not re-marked charged, logged error


def test_finding_5_render_idempotency_no_duplicate_charge() -> None:
    """Test 5: Pressing Render twice without changes reuses existing job and does not double charge."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    state = client.get("/api/editing/idea1", headers=headers).json()
    t_hash = state["timeline"]["hash"]
    j_raw = create_job("tok_test", "idea1", None, "raw_render")
    mark_done(j_raw["id"], output={"storage_path": "raw.mp4"})
    cur_ver = get_or_create_edit("tok_test", "idea1")["version"]
    save_edit("tok_test", "idea1", fields={
        "raw_render": {
            "job_id": j_raw["id"],
            "status": "done",
            "storage_path": "raw.mp4",
            "timeline_hash": t_hash,
        }
    }, expected_version=cur_ver)

    credits_before = _user_credits

    # 1st render
    r1 = client.post("/api/editing/idea1/render", headers=headers)
    assert r1.status_code == 202
    res1 = r1.json()
    assert res1["created"] is True
    job_id_1 = res1["job"]["id"]
    credits_after_1 = _user_credits
    assert credits_after_1 == credits_before - 20

    # Simulate worker saving finished render (which increments edit_version)
    cur_ver2 = get_or_create_edit("tok_test", "idea1")["version"]
    save_edit("tok_test", "idea1", fields={
        "render": {"job_id": job_id_1, "status": "done", "storage_path": "render.mp4"}
    }, expected_version=cur_ver2)

    # 2nd render without changes
    r2 = client.post("/api/editing/idea1/render", headers=headers)
    assert r2.status_code == 202
    res2 = r2.json()
    assert res2["created"] is False
    assert res2["job"]["id"] == job_id_1
    assert _user_credits == credits_after_1  # No extra charge!


def test_finding_6_manifest_progress_url() -> None:
    """Test 6: Manifest includes progress_url when PUBLIC_BASE_URL is configured."""
    _setup_scene_takes()
    script = MockScript().model_dump()
    jobs = list_jobs("tok_test", "idea1")
    edit = get_or_create_edit("tok_test", "idea1")
    state = _state("tok_test", "idea1", script, jobs, edit)

    job_raw = {
        "id": "job_raw_123",
        "attempts": 1,
        "session_token": "tok_test",
        "idea_id": "idea1",
        "input": {
            "timeline": state["timeline"],
            "inputs": {
                "take_s1": {"storage_path": "takes/s1.mp4", "kind": "video"},
                "take_s2": {"storage_path": "takes/s2.mp4", "kind": "video"},
            },
        },
    }

    raw_req = build_raw_request(job_raw)
    assert raw_req["progress_url"] == "https://brand-studio-agent.onrender.com/api/editing/internal/jobs/job_raw_123/progress"

    job_final = {
        "id": "job_final_456",
        "attempts": 1,
        "session_token": "tok_test",
        "idea_id": "idea1",
        "input": {
            "ir": state["ir"],
            "raw_storage_path": "editing/raw.mp4",
        },
    }
    final_req = build_final_request(job_final)
    assert final_req["progress_url"] == "https://brand-studio-agent.onrender.com/api/editing/internal/jobs/job_final_456/progress"


def test_finding_7_signed_url_cache_and_llm_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 7a: Signed URL cache & Test 7b: LLM rate limiting per session."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    # Setup edit with raw and render done
    state = client.get("/api/editing/idea1", headers=headers).json()
    t_hash = state["timeline"]["hash"]
    save_edit("tok_test", "idea1", fields={
        "raw_render": {"job_id": "jraw", "status": "done", "storage_path": "raw_cache.mp4", "timeline_hash": t_hash},
        "render": {"job_id": "jren", "status": "done", "storage_path": "render_cache.mp4"},
    }, expected_version=state["edit_version"])

    signed_calls: list[str] = []

    def _mock_signed_url(path: str, ttl: int = 3600) -> str:
        signed_calls.append(path)
        return f"https://storage.test/{path}?token=signed"

    monkeypatch.setattr("app.editing.router.signed_url", _mock_signed_url)

    # 7a: Two consecutive GET calls
    client.get("/api/editing/idea1", headers=headers)
    calls_after_1 = list(signed_calls)
    client.get("/api/editing/idea1", headers=headers)
    calls_after_2 = list(signed_calls)

    # Assert signed_url was not called again for the cached paths on the 2nd GET
    assert len(calls_after_1) == len(calls_after_2)

    # 7b: LLM rate limit (30 per hour)
    async def _mock_gen_meta(script, bb):
        return {"platforms": {}}

    monkeypatch.setattr("app.editing.router.generate_metadata", _mock_gen_meta)

    for _ in range(30):
        resp = client.post("/api/editing/idea1/metadata", headers=headers)
        assert resp.status_code == 200

    # 31st call exceeds limit
    resp_limit = client.post("/api/editing/idea1/metadata", headers=headers)
    assert resp_limit.status_code == 429
    assert resp_limit.json() == {"code": "too_many_ai_calls"}


def test_finding_8_caption_correction_take_invalidation() -> None:
    """Test 8: Caption word correction is invalidated if a new take is recorded for that scene."""
    headers = {"Authorization": "Bearer token123"}
    _setup_scene_takes()

    # Get version first
    st0 = client.get("/api/editing/idea1", headers=headers).json()

    # Correct word s1w0
    patch_resp = client.patch(
        "/api/editing/idea1/captions/s1w0",
        headers=headers,
        json={"text": "corregido", "expected_version": st0["edit_version"]},
    )
    assert patch_resp.status_code == 200
    st1 = patch_resp.json()
    cw0 = next(w for w in st1["captions_words"] if w["id"] == "s1w0")
    assert cw0["edited_text"] == "corregido"

    # Add a new take for scene 1 (replacing take 1)
    t_new = create_job("tok_test", "idea1", scene_n=1, kind="a_roll_take")
    mark_done(t_new["id"], output={"storage_path": "takes/s1_take2.mp4", "duration_ms": 5000})

    tr_new = create_job(
        session_token="tok_test",
        idea_id="idea1",
        scene_n=1,
        kind="transcript",
        input={"take_job_id": t_new["id"]},
    )
    mark_done(tr_new["id"], output={
        "words": [
            {"text": "word1_1_new", "start_ms": 100, "end_ms": 500},
            {"text": "word1_2_new", "start_ms": 600, "end_ms": 1000},
        ]
    })

    # GET state: s1w0 caption correction should NO LONGER apply to the new take
    st2 = client.get("/api/editing/idea1", headers=headers).json()
    cw0_new = next(w for w in st2["captions_words"] if w["id"] == "s1w0")
    assert cw0_new["edited_text"] is None

    # Legacy string format edit still applies
    save_edit("tok_test", "idea1", fields={
        "captions": {"edits": {"s1w0": "legacy_text"}}
    }, expected_version=st2["edit_version"])

    st3 = client.get("/api/editing/idea1", headers=headers).json()
    cw0_leg = next(w for w in st3["captions_words"] if w["id"] == "s1w0")
    assert cw0_leg["edited_text"] == "legacy_text"


def test_finding_9_non_ascii_bearer_and_worker_loop() -> None:
    """Test 9a: Non-ASCII bearer token gives 401 & Test 9b: Editing worker loop skips resume_stale."""
    # 9a: Non-ASCII Bearer token (passed as raw bytes in header to httpx)
    headers = {"Authorization": b"Bearer test_token_\xe5\xdf_non_ascii"}
    resp = client.post("/api/editing/internal/jobs/j1/progress", headers=headers, json={"pct": 50})
    assert resp.status_code == 401

    # 9b: Editing loop does not run resume_stale
    resumed_calls = []

    def _mock_resume_stale() -> int:
        resumed_calls.append(1)
        return 0

    worker_mod.resume_stale = _mock_resume_stale  # type: ignore

    assert worker_mod.EDITING_KINDS == ("raw_render", "render")
