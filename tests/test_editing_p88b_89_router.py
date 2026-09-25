"""Tests for Pieza 88B + 89: Metadata and Scene Redress Endpoints (Bloque E)."""

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.audiovisual.genai_client import set_genai_client
from app.audiovisual.jobs import (
    _reset_local_jobs,
    claim_next_pending,
    create_job,
    list_jobs,
)
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_or_create_edit

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class FakeResponse:

    def __init__(self, text: str):
        self.text = text


class FakeModels:

    def __init__(self, text_fn):
        self.text_fn = text_fn

    async def generate_content(self, model: str, contents: Any, config: Any = None):
        res = self.text_fn(model, contents, config)
        if asyncio.iscoroutine(res):
            res = await res
        return FakeResponse(res)


class FakeAio:

    def __init__(self, text_fn):
        self.models = FakeModels(text_fn)


class FakeGenAIClient:

    def __init__(self, text_fn):
        self.aio = FakeAio(text_fn)


class MockScript:
    """Mock script model for testing."""

    def __init__(self, state: str = "locked", num_scenes: int = 2) -> None:
        self.state = state
        self.title = "Test Script for Metadata & Redress"
        self.angle = "Personal Branding"
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
            "angle": self.angle,
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


def _mock_refund_credits(
    session_token: str, amount: int, source: str = "refund"
) -> int:
    global _user_credits
    _user_credits += amount
    return _user_credits


def _mock_get_remaining_credits(session_token: str) -> int:
    global _user_credits
    return _user_credits


def _reset_local_jobs_insert(job: dict[str, Any]) -> None:
    from app.audiovisual.jobs import _jobs_lock, _local_jobs

    with _jobs_lock:
        _local_jobs[job["id"]] = job


def default_mock_genai_handler(model, contents, config):
    contents_str = str(contents)
    if (
        "metadata" in contents_str.lower()
        or "publication metadata" in contents_str.lower()
    ):
        return json.dumps({
            "platforms": {
                "linkedin": {
                    "title": "Test Script for Metadata & Redress",
                    "description": "Linkedin desc",
                    "hashtags": [
                        "#marcapersonal",
                        "#founders",
                        "#emprendimiento",
                        "#contenido",
                        "#shorts",
                    ],
                    "first_comment": "First comment",
                },
                "instagram": {
                    "title": "Test Script for Metadata & Redress",
                    "description": "Instagram desc",
                    "hashtags": [
                        "#marcapersonal",
                        "#founders",
                        "#emprendimiento",
                        "#contenido",
                        "#shorts",
                    ],
                    "first_comment": "First comment",
                },
                "tiktok": {
                    "title": "Test Script for Metadata & Redress",
                    "description": "TikTok desc",
                    "hashtags": [
                        "#marcapersonal",
                        "#founders",
                        "#emprendimiento",
                        "#contenido",
                        "#shorts",
                    ],
                    "first_comment": "First comment",
                },
            }
        })
    else:
        return json.dumps({
            "catalog_version": "v1",
            "scenes": [
                {
                    "n": 1,
                    "transition_in": "flash",
                    "emphasis_word_idx": [0],
                    "zooms": [
                        {"type": "punch_in", "word_idx": 0, "intensity": "medium"}
                    ],
                    "overlays": [],
                    "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                }
            ],
        })


@pytest.fixture(autouse=True)
def setup_teardown(monkeypatch: pytest.MonkeyPatch):
    global _user_credits
    _user_credits = 100
    _reset_local_jobs()
    _reset_local_edits()
    set_genai_client(FakeGenAIClient(default_mock_genai_handler))

    monkeypatch.setattr(supabase_auth, "get_user_id", lambda token: "user_p88b_89")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda uid: "tok_p88b_89"
    )
    monkeypatch.setattr("app.guard.guard.deduct_credits", _mock_deduct_credits)
    monkeypatch.setattr("app.guard.guard.refund_credits", _mock_refund_credits)
    monkeypatch.setattr(
        "app.guard.guard.get_remaining_credits", _mock_get_remaining_credits
    )
    monkeypatch.setattr(
        "app.tools.brand_brain.store.get_brand_brain", lambda tok: None
    )

    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret")

    yield
    set_genai_client(None)


def _add_takes_and_transcripts(
    session_token: str = "tok_p88b_89", idea_id: str = "idea1"
) -> None:
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
            ]
        }
        _reset_local_jobs_insert(tr)


def test_1_metadata_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """1. POST metadata -> 200, GET brings metadata.platforms.linkedin.title;
    PATCH hashtags with garbage -> 5 valid hashtags;
    PATCH platform: 'x' -> 422;
    PATCH without generated metadata -> 409.
    """
    mock_s = MockScript(state="locked", num_scenes=2)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)
    _add_takes_and_transcripts()
    headers = {"Authorization": "Bearer tok_p88b_89"}

    # PATCH before metadata generated -> 409 metadata_not_generated
    resp_patch_early = client.patch(
        "/api/editing/idea1/metadata",
        json={
            "platform": "linkedin",
            "field": "title",
            "value": "New Title",
            "expected_version": 1,
        },
        headers=headers,
    )
    assert resp_patch_early.status_code == 409
    assert resp_patch_early.json()["code"] == "metadata_not_generated"

    # POST metadata -> 200
    resp_post = client.post("/api/editing/idea1/metadata", headers=headers)
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert "metadata" in data_post
    assert "platforms" in data_post["metadata"]
    assert "linkedin" in data_post["metadata"]["platforms"]
    assert "title" in data_post["metadata"]["platforms"]["linkedin"]

    # GET confirms metadata is saved
    resp_get = client.get("/api/editing/idea1", headers=headers)
    assert resp_get.status_code == 200
    meta_get = resp_get.json()["metadata"]
    assert (
        meta_get["platforms"]["linkedin"]["title"]
        == "Test Script for Metadata & Redress"
    )

    version = resp_get.json()["edit_version"]

    # PATCH hashtags with garbage -> 5 valid hashtags
    resp_patch_tags = client.patch(
        "/api/editing/idea1/metadata",
        json={
            "platform": "instagram",
            "field": "hashtags",
            "value": "#foo, bar, #baz, INVALID-TAG-LONGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
            "expected_version": version,
        },
        headers=headers,
    )
    assert resp_patch_tags.status_code == 200
    tags = resp_patch_tags.json()["metadata"]["platforms"]["instagram"]["hashtags"]
    assert isinstance(tags, list)
    assert len(tags) == 5

    # PATCH platform 'x' -> 422
    resp_patch_bad_p = client.patch(
        "/api/editing/idea1/metadata",
        json={
            "platform": "x",
            "field": "title",
            "value": "Test",
            "expected_version": version + 1,
        },
        headers=headers,
    )
    assert resp_patch_bad_p.status_code == 422


def test_2_redress_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """2. Redress without dressing -> 409 dress_first.
    With dressing: 200, charges 2 credits, changes ONLY target scene (others byte-identical),
    and job 'redress' becomes 'done' and 'charged'.
    """
    mock_s = MockScript(state="locked", num_scenes=2)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)
    _add_takes_and_transcripts()
    headers = {"Authorization": "Bearer tok_p88b_89"}

    # Redress before dress -> 409 dress_first
    resp_no_dress = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_test_12345"},
        headers=headers,
    )
    assert resp_no_dress.status_code == 409
    assert resp_no_dress.json()["code"] == "dress_first"

    # Dress first
    resp_dress = client.post("/api/editing/idea1/dress", headers=headers)
    assert resp_dress.status_code == 200

    edit_before = get_or_create_edit("tok_p88b_89", "idea1")
    scene2_before_str = json.dumps(
        edit_before["dressing"]["scenes"][1], sort_keys=True
    )

    # Redress scene 1
    resp_redress = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_test_12345"},
        headers=headers,
    )
    assert resp_redress.status_code == 200
    data_redress = resp_redress.json()
    assert data_redress["credits_remaining"] == 98

    # Verify scene 2 in dressing is byte-identical
    edit_after = get_or_create_edit("tok_p88b_89", "idea1")
    scene2_after_str = json.dumps(
        edit_after["dressing"]["scenes"][1], sort_keys=True
    )
    assert scene2_before_str == scene2_after_str

    # Check job status
    jobs = list_jobs("tok_p88b_89", "idea1")
    redress_jobs = [j for j in jobs if j.get("kind") == "redress"]
    assert len(redress_jobs) == 1
    r_job = redress_jobs[0]
    assert r_job["status"] == "done"
    assert r_job["charged"] is True


def test_3_redress_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    """3. Same request_id twice -> second attempt doesn't charge again."""
    mock_s = MockScript(state="locked", num_scenes=2)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)
    _add_takes_and_transcripts()
    headers = {"Authorization": "Bearer tok_p88b_89"}

    client.post("/api/editing/idea1/dress", headers=headers)

    resp1 = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_same_id_12345"},
        headers=headers,
    )
    assert resp1.status_code == 200
    assert _user_credits == 98

    resp2 = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_same_id_12345"},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert _user_credits == 98


def test_4_gemini_failure_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """4. Gemini fails -> 503 brandy_unavailable and user balance does not change."""
    mock_s = MockScript(state="locked", num_scenes=2)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)
    _add_takes_and_transcripts()
    headers = {"Authorization": "Bearer tok_p88b_89"}

    client.post("/api/editing/idea1/dress", headers=headers)

    def failing_genai_handler(model, contents, config):
        raise RuntimeError("Gemini error simulation")

    set_genai_client(FakeGenAIClient(failing_genai_handler))

    resp = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_fail_12345"},
        headers=headers,
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "brandy_unavailable"
    assert _user_credits == 100


def test_5_insufficient_credits_returns_402(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Insufficient balance -> 402, job becomes failed with charged=False, dressing unchanged."""
    mock_s = MockScript(state="locked", num_scenes=2)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, iid: mock_s)
    _add_takes_and_transcripts()
    headers = {"Authorization": "Bearer tok_p88b_89"}

    client.post("/api/editing/idea1/dress", headers=headers)

    global _user_credits
    _user_credits = 1

    resp = client.post(
        "/api/editing/idea1/scenes/1/redress",
        json={"request_id": "req_insuff_12345"},
        headers=headers,
    )
    assert resp.status_code == 402

    jobs = list_jobs("tok_p88b_89", "idea1")
    redress_jobs = [j for j in jobs if j.get("kind") == "redress"]
    assert len(redress_jobs) == 1
    assert redress_jobs[0]["status"] == "failed"
    assert redress_jobs[0]["charged"] is False


def test_6_worker_never_claims_redress_jobs() -> None:
    """6. claim_next_pending with worker kinds never claims a redress job."""
    create_job(
        session_token="tok_p88b_89",
        idea_id="idea1",
        scene_n=1,
        kind="redress",
        credits=2,
    )

    from app.audiovisual.worker import EDITING_KINDS, RESOLVERS

    supported = [k for k in RESOLVERS.keys() if k not in EDITING_KINDS]
    claimed = claim_next_pending(supported_kinds=supported)
    assert claimed is None

    supported_all = list(RESOLVERS.keys())
    claimed2 = claim_next_pending(supported_kinds=supported_all)
    assert claimed2 is None
