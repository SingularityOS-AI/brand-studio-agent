"""
Unit, integration, and static contract tests for PIEZA 55:
- POST /api/audiovisual/{idea_id}/scenes/{scene_n}/regenerate (401, 404, 409, 400, 402, 422, 200)
- Cancel prior done/failed jobs, retain idempotency
- Stock exclude_ids filtering and rotation
- Motion graphic template_offset rotation
- Audiovisual strip is purely visual (no music/sfx in view)
- Camera permission unblock guide in studio
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
    list_jobs,
    mark_done,
)
from app.audiovisual.motion_graphics import (
    TEMPLATES_ORDER,
    resolve_motion_graphic,
    select_template,
)
from app.audiovisual.stock import (
    _clear_stock_cache,
    _search_pexels,
    resolve_stock,
)
from app.config import settings
from app.guard import guard
from app.main import app
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML_PATH = REPO_ROOT / "app" / "static" / "index.html"


@pytest.fixture(autouse=True)
def reset_audiovisual_state():
    """Reset jobs, sessions, stock cache, and script storage before and after every test."""
    _reset_local_jobs()
    guard._sessions.clear()
    _clear_stock_cache()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    _reset_local_jobs()


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Speaker addressing the camera",
        on_screen_text="Watch this now",
        why_it_stops_the_scroll="Instant curiosity hook",
    )


def make_scene(
    n: int,
    phase: str,
    asset_type: str = "a_roll",
    spoken_text: str = "Here is how to build authority.",
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken_text,
        shot="close up",
        b_roll=None,
        on_screen_text=f"Scene {n} key takeaway",
        acting_note="Confident delivery",
        sound="room tone",
        asset_type=asset_type,
        stock_query="minimal tech workspace" if asset_type == "stock" else None,
        visual_prompt="futuristic neon network nodes" if "ai" in asset_type else None,
    )


def make_standard_scenes() -> list[Scene]:
    return [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "stock"),
        make_scene(3, "body_1", "motion_graphic"),
        make_scene(4, "rehook", "ai_video"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]


def make_script(
    session_id: str,
    idea_id: str,
    scenes: list[Scene] | None = None,
    frame_zero: FrameZero | None = None,
    state: str = "locked",
) -> Script:
    sc = scenes if scenes is not None else make_standard_scenes()
    fz = frame_zero or FrameZero(
        visual="Speaker addressing the camera",
        on_screen_text="Watch this now",
        why_it_stops_the_scroll="Instant curiosity hook",
    )
    return Script(
        session_id=session_id,
        idea_id=idea_id,
        title="Scaling Without Spaghetti",
        angle="Engineering excellence and modular design",
        funnel_stage="tofu",
        target_seconds=60,
        version=1,
        state=state,
        frame_zero=fz,
        scenes=sc,
        raw_footage=None,
    )


# =============================================================================
# 1. ENDPOINT TESTS: POST /api/audiovisual/{idea_id}/scenes/{scene_n}/regenerate
# =============================================================================


def test_regenerate_endpoint_requires_auth():
    """401 if missing Authorization header."""
    client = TestClient(app)
    res = client.post("/api/audiovisual/idea_test/scenes/2/regenerate")
    assert res.status_code == 401


def test_regenerate_endpoint_404_script_not_found(authenticated_client):
    """404 if script does not exist."""
    res = authenticated_client.post("/api/audiovisual/nonexistent_idea/scenes/2/regenerate")
    assert res.status_code == 404
    assert "not found" in res.json()["error"].lower()


def test_regenerate_endpoint_409_if_script_not_locked(authenticated_client, sample_frame_zero):
    """409 if script is in draft state."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_draft"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="draft")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res.status_code == 409
    assert "locked" in res.json()["error"].lower()


def test_regenerate_endpoint_404_scene_not_found(authenticated_client, sample_frame_zero):
    """404 if scene number does not exist in script."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_no_scene"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/99/regenerate")
    assert res.status_code == 404
    assert "scene 99 not found" in res.json()["error"].lower()


def test_regenerate_endpoint_400_if_a_roll(authenticated_client, sample_frame_zero):
    """400 if attempting to regenerate an a_roll scene."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_aroll"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/1/regenerate")
    assert res.status_code == 400
    assert "a_roll" in res.json()["error"].lower()


def test_regenerate_endpoint_402_if_insufficient_credits(authenticated_client, sample_frame_zero):
    """402 if user balance < required credits for kind; verifies no job is created."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_low_credits"
    # scene 4 is ai_video which requires 10 credits
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Set user balance to 5 credits (< 10)
    guard._sessions[session_token]["credits"] = 5

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/4/regenerate")
    assert res.status_code == 402
    data = res.json()
    assert "Insufficient credits" in data["error"]
    assert data["credits_needed"] == 150
    assert data["credits_remaining"] == 5

    # Verify no jobs created
    jobs = list_jobs(session_token, idea_id)
    assert len(jobs) == 0


def test_regenerate_endpoint_422_if_ai_video_limit_exceeded(authenticated_client, sample_frame_zero):
    """422 if scene is ai_video and another active ai_video job already exists for the script."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_ai_limit"
    scenes = [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "ai_video"),
        make_scene(3, "body_1", "ai_video"),
        make_scene(4, "rehook", "stock"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_script(session_token, idea_id, scenes=scenes, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Active ai_video job exists for scene 3
    create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_video",
        credits=10,
        idempotency_key="active_scene_3_ai",
    )

    # Attempting to regenerate scene 2 as ai_video triggers 422
    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res.status_code == 422
    assert "AI video limit reached" in res.json()["error"]


def test_regenerate_endpoint_cancels_previous_job_and_creates_new(authenticated_client, sample_frame_zero):
    """
    Successfully regenerates a scene:
    - Marks prior done/failed job as cancelled with 'Regenerated by user'
    - Creates a new job with status 'pending'
    - Returns job and status
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_success"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Prior job for scene 2 that finished done
    old_job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=2,
        kind="stock",
        credits=0,
        idempotency_key="prior_scene_2_stock",
    )
    mark_done(old_job["id"], output={"source_id": "pexels_888", "storage_path": "hash/path.mp4"})

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res.status_code == 200
    data = res.json()
    new_job = data["job"]
    assert new_job["status"] == "pending"
    assert new_job["scene_n"] == 2
    assert new_job["kind"] == "stock"
    assert new_job["id"] != old_job["id"]

    # Verify old job is now cancelled
    updated_old_job = get_job(old_job["id"])
    assert updated_old_job["status"] == "cancelled"
    assert "Regenerated by user" in updated_old_job["error"]


def test_regenerate_stock_passes_exclude_ids(authenticated_client, sample_frame_zero):
    """
    Regenerating stock collects source_ids from prior jobs into exclude_ids.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_exclude"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Job 1 with source_id 11111
    j1 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=2,
        kind="stock",
        credits=0,
        idempotency_key="j1",
    )
    mark_done(j1["id"], output={"source_id": "11111"})

    # First regenerate
    res1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res1.status_code == 200
    j2 = res1.json()["job"]
    assert "11111" in j2["input"].get("exclude_ids", [])

    # Mark j2 done with source_id 22222
    mark_done(j2["id"], output={"source_id": "22222"})

    # Second regenerate
    res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res2.status_code == 200
    j3 = res2.json()["job"]
    ex = j3["input"].get("exclude_ids", [])
    assert "11111" in ex
    assert "22222" in ex


def test_regenerate_motion_graphic_increments_template_offset(authenticated_client, sample_frame_zero):
    """
    Regenerating motion_graphic increments template_offset each time.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_motion_rot"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Initial job without template_offset
    j1 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="motion_graphic",
        credits=0,
        input={"template_offset": 0},
        idempotency_key="m1",
    )
    mark_done(j1["id"], output={"storage_path": "m1.mp4"})

    # Regenerate 1: offset becomes 1
    res1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/3/regenerate")
    assert res1.status_code == 200
    j2 = res1.json()["job"]
    assert j2["input"]["template_offset"] == 1
    mark_done(j2["id"], output={"storage_path": "m2.mp4"})

    # Regenerate 2: offset becomes 2
    res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/3/regenerate")
    assert res2.status_code == 200
    j3 = res2.json()["job"]
    assert j3["input"]["template_offset"] == 2


# =============================================================================
# 2. RESOLVER UNIT TESTS: stock exclude_ids & motion_graphic template_offset
# =============================================================================


@pytest.mark.asyncio
async def test_stock_resolver_filters_exclude_ids():
    """
    resolve_stock skips candidates whose ID is in exclude_ids and picks next best candidate.
    """
    fake_pexels_data = {
        "videos": [
            {
                "id": 101,
                "width": 1080,
                "height": 1920,
                "duration": 6,
                "video_files": [
                    {"id": 1011, "quality": "hd", "width": 1080, "height": 1920, "link": "https://fake/101.mp4"}
                ],
            },
            {
                "id": 102,
                "width": 1080,
                "height": 1920,
                "duration": 5,
                "video_files": [
                    {"id": 1021, "quality": "hd", "width": 1080, "height": 1920, "link": "https://fake/102.mp4"}
                ],
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_pexels_data

    with patch.object(settings, "pexels_api_key", "test_key_123"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            # With 101 excluded, _search_pexels returns 102
            res = await _search_pexels("office", 5.0, exclude_ids=["101"])
            assert res is not None
            assert res["source_id"] == "102"

            # With both 101 and 102 excluded, _search_pexels returns None
            res_none = await _search_pexels("office", 5.0, exclude_ids=["101", "102"])
            assert res_none is None

            # Test through resolve_stock directly
            job_with_ex = {
                "id": "j_test_ex",
                "session_token": "s1",
                "idea_id": "i1",
                "scene_n": 2,
                "input": {
                    "stock_query": "office",
                    "duration_s": 5.0,
                    "exclude_ids": ["101"],
                },
            }
            out = await resolve_stock(job_with_ex)
            assert out["source_id"] == "102"


def test_motion_graphic_select_template_rotation():
    """
    select_template respects template_offset and rotates across all 4 templates.
    """
    assert TEMPLATES_ORDER == ["stat", "quote", "list", "lower_third"]

    # Offset 0..3 corresponds to the 4 templates
    t0, _ = select_template("body_1", "90% of founders fail", template_offset=0)
    t1, _ = select_template("body_1", "90% of founders fail", template_offset=1)
    t2, _ = select_template("body_1", "90% of founders fail", template_offset=2)
    t3, _ = select_template("body_1", "90% of founders fail", template_offset=3)

    assert t0 == "stat"
    assert t1 == "quote"
    assert t2 == "list"
    assert t3 == "lower_third"

    # Offset 4 wraps back to stat (modulo 4)
    t4, _ = select_template("body_1", "90% of founders fail", template_offset=4)
    assert t4 == "stat"


@pytest.mark.asyncio
async def test_motion_graphic_resolver_passes_template_offset():
    """
    resolve_motion_graphic parses template_offset and selects corresponding template.
    """
    job = {
        "id": "job_mg_1",
        "session_token": "sess_mg",
        "idea_id": "idea_mg",
        "scene_n": 3,
        "input": {
            "spoken_text": "90% of startups fail before year two.",
            "on_screen_text": "90% failure rate",
            "phase": "body_1",
            "template_offset": 1,  # Forces "quote"
        },
    }

    with patch("app.audiovisual.motion_graphics.upload_bytes", return_value="hash/mg.html"):
        out = await resolve_motion_graphic(job)
        assert out["template"] == "quote"
        assert out["storage_path"] == "hash/mg.html"


# =============================================================================
# 3. STATIC CONTRACT TESTS: frontend, coming next, and camera permissions
# =============================================================================


def test_static_contracts_no_coming_next_text():
    """
    Ensure 'Generate assets — coming next' has been removed from both app.js and index.html.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"

    app_js_text = APP_JS_PATH.read_text(encoding="utf-8")
    index_html_text = INDEX_HTML_PATH.read_text(encoding="utf-8")

    assert "Generate assets — coming next" not in app_js_text, (
        "'Generate assets — coming next' must not exist in app.js"
    )
    assert "Generate assets — coming next" not in index_html_text, (
        "'Generate assets — coming next' must not exist in index.html"
    )


def test_static_contracts_app_js_regenerate_and_scenes_route():
    """
    Ensure app.js calls /scenes/ and regenerate.
    """
    app_js_text = APP_JS_PATH.read_text(encoding="utf-8")

    assert "/scenes/" in app_js_text, "app.js must call endpoint containing /scenes/"
    assert "regenerate" in app_js_text, "app.js must contain regenerate logic"


def test_static_contracts_no_music_in_audiovisual_view():
    """
    Ensure Audiovisual view in app.js does not render 'Background music' status block.
    """
    app_js_text = APP_JS_PATH.read_text(encoding="utf-8")

    # In app.js, the Audiovisual view shouldn't render music status
    assert "AV-MusicStatusLine" not in app_js_text, (
        "AV-MusicStatusLine should be removed from app.js as Audiovisual is purely visual"
    )


def test_static_contracts_camera_unblock_guide_in_app_js():
    """
    Ensure startStudioCamera handles NotAllowedError with address bar unblock instruction
    and NotFoundError with missing hardware message.
    """
    app_js_text = APP_JS_PATH.read_text(encoding="utf-8")

    assert "NotAllowedError" in app_js_text, "app.js must handle NotAllowedError"
    assert "NotFoundError" in app_js_text, "app.js must handle NotFoundError"
    assert "Click the 🔒/camera icon in the address bar" in app_js_text, (
        "app.js must instruct user to click lock/camera icon in address bar to unblock"
    )
    assert "No camera/microphone found" in app_js_text, (
        "app.js must inform when no camera or microphone is found"
    )


def test_regenerate_409_when_scene_job_in_flight(authenticated_client, sample_frame_zero):
    """A second regenerate while the scene's job is still pending (double click,
    retry) must not create a second job: for ai_video that is a second paid Veo."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p55_inflight"
    script = make_script(session_token, idea_id, frame_zero=sample_frame_zero, state="locked")
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    j1 = create_job(
        session_token=session_token, idea_id=idea_id, scene_n=2, kind="stock",
        credits=0, idempotency_key="inflight1",
    )
    mark_done(j1["id"], output={"source_id": "1"})

    res1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res1.status_code == 200
    res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/2/regenerate")
    assert res2.status_code == 409
