"""Tests for Pieza 78 — Render Dispatcher and Editing Worker Loop."""
from __future__ import annotations

import httpx
import pytest

import app.editing.config as dispatch_config
from app.audiovisual.jobs import _reset_local_jobs, create_job, get_job, mark_charged, mark_failed
from app.audiovisual.worker import RESOLVERS, process_one_job, register_default_resolvers
from app.editing.dispatch import (
    RenderServiceError,
    build_raw_request,
    call_render_service,
    refund_failed_prepaid,
    resolve_raw_render,
    sign_inputs,
)
from app.editing.store import _reset_local_edits, get_edit, save_edit, EditVersionConflict
from app.guard import guard
from render_service.manifest import RenderRequest, timeline_hash


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Resets local jobs, edits, and sets test render config."""
    _reset_local_jobs()
    _reset_local_edits()
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret_123")
    register_default_resolvers()


def make_valid_timeline() -> dict:
    """Helper creating valid Timeline dictionary."""
    tl = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "take_job_id": "take_job_1",
                "take_input": "input_take_1",
                "broll": None,
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "broll",
                "take_job_id": "take_job_2",
                "take_input": "input_take_2",
                "broll": {
                    "kind": "motion_graphic",
                    "input_id": "input_mg_2",
                    "w": 1080,
                    "h": 1920,
                    "duration_ms": 2000,
                },
                "segments": [{"in_ms": 0, "out_ms": 2000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 5000,
            },
        ],
        "music": None,
        "duration_ms": 5000,
        "hash": "",
    }
    tl["hash"] = timeline_hash(tl)
    return tl


def test_1_sign_inputs():
    """1. sign_inputs: storage_path -> signed URL local; external_url passes as is; w, h preserved."""
    inputs_spec = {
        "in_storage": {
            "storage_path": "abc12345/idea1/1/take_1.webm",
            "kind": "video",
            "w": 1080,
            "h": 1920,
        },
        "in_ext": {
            "external_url": "https://external.test/video.mp4",
            "kind": "video",
        },
    }
    signed = sign_inputs(inputs_spec)
    assert signed["in_storage"]["url"].startswith("https://local-storage.test/")
    assert signed["in_storage"]["kind"] == "video"
    assert signed["in_storage"]["w"] == 1080
    assert signed["in_storage"]["h"] == 1920
    assert signed["in_ext"]["url"] == "https://external.test/video.mp4"
    assert signed["in_ext"]["kind"] == "video"


def test_2_build_raw_request():
    """2. build_raw_request with 2 scenes (1 motion graphic convert=True) -> valid RenderRequest, mode='raw', 1 ConvertItem, output ends with _a1.mp4."""
    tl = make_valid_timeline()
    inputs_spec = {
        "input_take_1": {
            "storage_path": "abc12345/idea1/1/take_1.webm",
            "kind": "video",
            "w": 1080,
            "h": 1920,
        },
        "input_take_2": {
            "storage_path": "abc12345/idea1/2/take_2.webm",
            "kind": "video",
        },
        "input_mg_2": {
            "storage_path": "abc12345/idea1/2/mg.html",
            "kind": "html",
            "convert": True,
        },
    }
    job = {
        "id": "job_test_raw_123",
        "session_token": "token_session_abc",
        "idea_id": "idea_123",
        "attempts": 1,
        "input": {
            "timeline": tl,
            "inputs": inputs_spec,
        },
    }

    req = build_raw_request(job)
    # Validates against RenderRequest schema
    validated = RenderRequest.model_validate(req)
    assert validated.mode == "raw"
    assert len(validated.convert) == 1
    assert validated.convert[0].input_id == "input_mg_2"
    assert validated.output.storage_path.endswith("_a1.mp4")


@pytest.mark.asyncio
async def test_3_call_render_service(monkeypatch):
    """3. call_render_service handling 200, 502, timeout, missing config, and Authorization header."""
    req = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_1",
        "attempt": 1,
        "mode": "raw",
        "timeline": make_valid_timeline(),
        "inputs": {
            "input_take_1": {"url": "https://local-storage.test/v1.webm", "kind": "video"},
            "input_take_2": {"url": "https://local-storage.test/v2.webm", "kind": "video"},
            "input_mg_2": {"url": "https://local-storage.test/mg.html", "kind": "html"},
        },
        "convert": [],
        "output": {
            "upload_url": "https://local-storage.test/upload.mp4",
            "storage_path": "abc12345/idea1/video/job_1_a1.mp4",
            "max_bytes": 47000000,
        },
    }

    auth_headers_received = []

    def handle_200(request: httpx.Request) -> httpx.Response:
        auth_headers_received.append(request.headers.get("Authorization"))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "storage_path": "abc12345/idea1/video/job_1_a1.mp4",
                "duration_ms": 5000,
                "bytes": 500000,
                "render_s": 2.5,
                "scene_marks_ms": [0, 3000],
                "converted": [],
            },
        )

    # a) 200 OK
    client_200 = httpx.AsyncClient(transport=httpx.MockTransport(handle_200))
    res = await call_render_service(req, client=client_200)
    assert res["ok"] is True
    assert auth_headers_received == ["Bearer test_secret_123"]

    # b) 502 RenderError
    def handle_502(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "ok": False,
                "code": "fetch_failed",
                "retryable": True,
                "detail": "Failed to download asset",
            },
        )

    client_502 = httpx.AsyncClient(transport=httpx.MockTransport(handle_502))
    with pytest.raises(RenderServiceError) as exc_info_502:
        await call_render_service(req, client=client_502)
    assert exc_info_502.value.code == "fetch_failed"
    assert exc_info_502.value.retryable is True

    # c) Timeout
    def handle_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Timed out")

    client_timeout = httpx.AsyncClient(transport=httpx.MockTransport(handle_timeout))
    with pytest.raises(RenderServiceError) as exc_info_timeout:
        await call_render_service(req, client=client_timeout)
    assert exc_info_timeout.value.code == "timeout"
    assert exc_info_timeout.value.retryable is True

    # d) URL empty
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "")
    with pytest.raises(RenderServiceError) as exc_info_bad:
        await call_render_service(req)
    assert exc_info_bad.value.code == "bad_manifest"
    assert exc_info_bad.value.retryable is False


@pytest.mark.asyncio
async def test_4_resolve_raw_render_happy(monkeypatch):
    """4. resolve_raw_render saves edits.raw_render with timeline_hash and returns cost_usd."""
    tl = make_valid_timeline()
    inputs_spec = {
        "input_take_1": {
            "storage_path": "abc12345/idea1/1/take_1.webm",
            "kind": "video",
        },
        "input_take_2": {
            "storage_path": "abc12345/idea1/2/take_2.webm",
            "kind": "video",
        },
        "input_mg_2": {
            "storage_path": "abc12345/idea1/2/mg.html",
            "kind": "html",
        },
    }
    job = create_job(
        session_token="token_session_4",
        idea_id="idea_4",
        scene_n=None,
        kind="raw_render",
        input={"timeline": tl, "inputs": inputs_spec},
    )

    def handle_render(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "storage_path": "abc12345/idea_4/video/job4_a1.mp4",
                "duration_ms": 5000,
                "bytes": 400000,
                "render_s": 10.0,
                "scene_marks_ms": [0, 3000],
                "converted": [],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle_render))

    # Monkeypatch call_render_service to pass custom client
    async def mock_call(request):
        return await call_render_service(request, client=client)

    monkeypatch.setattr("app.editing.dispatch.call_render_service", mock_call)

    out = await resolve_raw_render(job)
    expected_cost = round(10.0 * 0.000088, 4)
    assert out["cost_usd"] == expected_cost
    assert out["status"] == "done"
    assert out["timeline_hash"] == tl["hash"]

    # Verify edit in store
    edit_row = get_edit("token_session_4", "idea_4")
    assert edit_row is not None
    assert edit_row["raw_render"]["job_id"] == job["id"]
    assert edit_row["raw_render"]["timeline_hash"] == tl["hash"]


@pytest.mark.asyncio
async def test_5_resolve_raw_render_version_conflict(monkeypatch):
    """5. EditVersionConflict once when saving -> retries and succeeds."""
    tl = make_valid_timeline()
    inputs_spec = {
        "input_take_1": {
            "storage_path": "abc12345/idea5/1/take_1.webm",
            "kind": "video",
        },
        "input_take_2": {
            "storage_path": "abc12345/idea5/2/take_2.webm",
            "kind": "video",
        },
        "input_mg_2": {
            "storage_path": "abc12345/idea5/2/mg.html",
            "kind": "html",
        },
    }
    job = create_job(
        session_token="token_session_5",
        idea_id="idea_5",
        scene_n=None,
        kind="raw_render",
        input={"timeline": tl, "inputs": inputs_spec},
    )

    async def mock_call(request):
        return {
            "ok": True,
            "storage_path": "abc12345/idea_5/video/job5_a1.mp4",
            "duration_ms": 5000,
            "bytes": 400000,
            "render_s": 5.0,
            "scene_marks_ms": [0, 3000],
            "converted": [],
        }

    monkeypatch.setattr("app.editing.dispatch.call_render_service", mock_call)

    original_save = save_edit
    calls = [0]

    def flaky_save_edit(session_token, idea_id, fields, expected_version):
        calls[0] += 1
        if calls[0] == 1:
            raise EditVersionConflict(expected=expected_version, current=expected_version + 1)
        return original_save(session_token, idea_id, fields, expected_version)

    monkeypatch.setattr("app.editing.dispatch.save_edit", flaky_save_edit)

    out = await resolve_raw_render(job)
    assert out["status"] == "done"
    assert calls[0] == 2


def test_6_refund_failed_prepaid():
    """6. refund_failed_prepaid: job render failed charged=True credits=20 -> refunds 20 to session once."""
    guard.create_user_session(user_id="user_6", initial_credits=50)
    session_token = guard.get_or_create_user_session("user_6")

    job = create_job(
        session_token=session_token,
        idea_id="idea_6",
        scene_n=None,
        kind="render",
        credits=20,
    )
    mark_charged(job["id"])
    mark_failed(job["id"], "render engine failed")

    # First call: refunds 20 credits (balance 50 -> 70)
    refunded_count = refund_failed_prepaid()
    assert refunded_count == 1
    assert guard.get_remaining_credits(session_token) == 70

    # Second call: job charged is now False -> refunds 0
    refunded_count_2 = refund_failed_prepaid()
    assert refunded_count_2 == 0
    assert guard.get_remaining_credits(session_token) == 70


@pytest.mark.asyncio
async def test_7_process_one_job_filtering(monkeypatch):
    """7. process_one_job() without args does NOT claim a pending render job; process_one_job(['raw_render', 'render']) does."""
    guard.create_user_session(user_id="user_7", initial_credits=50)
    session_token = guard.get_or_create_user_session("user_7")

    job = create_job(
        session_token=session_token,
        idea_id="idea_7",
        scene_n=None,
        kind="render",
        credits=20,
    )
    mark_charged(job["id"])

    # 1) process_one_job() without args -> returns False, job remains pending
    claimed_default = await process_one_job()
    assert claimed_default is False
    job_after_1 = get_job(job["id"])
    assert job_after_1["status"] == "pending"

    # Patch resolve_render in worker.RESOLVERS
    async def mock_resolve_render(j):
        return {
            "status": "done",
            "storage_path": "output/render.mp4",
            "duration_ms": 1000,
            "bytes": 100,
            "render_s": 1.0,
        }

    monkeypatch.setitem(RESOLVERS, "render", mock_resolve_render)

    # 2) process_one_job(['raw_render', 'render']) -> claims and resolves the job
    claimed_editing = await process_one_job(["raw_render", "render"])
    assert claimed_editing is True
    job_after_2 = get_job(job["id"])
    assert job_after_2["status"] == "done"



@pytest.mark.asyncio
async def test_8_spend_cap_exhausted(monkeypatch):
    """8. Spend cap exhausted (can_spend patched to False) -> render job fails with limit message and refund sweep refunds it."""
    monkeypatch.setattr("app.audiovisual.worker.can_spend", lambda extra: False)

    session_token = guard.create_user_session(user_id="user_8", initial_credits=100)

    job = create_job(
        session_token=session_token,
        idea_id="idea_8",
        scene_n=None,
        kind="render",
        credits=20,
    )
    mark_charged(job["id"])

    # Attempt to process job when spend cap is exhausted
    claimed = await process_one_job(["raw_render", "render"])
    assert claimed is True

    # Check job failed with message
    job_after = get_job(job["id"])
    assert job_after["status"] == "failed"
    assert "Render paused (platform spend limit)" in job_after["error"]

    # Sweep refunds the prepaid credits
    refunded = refund_failed_prepaid()
    assert refunded == 1
    assert guard.get_remaining_credits(session_token) == 120
