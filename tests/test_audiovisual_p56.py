"""
Unit and integration tests for PIEZA 56:
El founder graba TODAS las escenas a cámara (también las de B-roll).

Covers:
1. POST /api/audiovisual/{idea}/takes/{scene_n}/upload-url accepts stock and B-roll scenes (200).
2. POST /api/audiovisual/{idea}/takes/{scene_n}/commit accepts stock and B-roll scenes.
3. Job 'a_roll_take' output role:
   - "on_camera" for a_roll scenes.
   - "voiceover" for B-roll scenes (stock, ai_image, ai_video, motion_graphic).
4. Security: storage_path validation rejects foreign paths (403).
5. 0 credits charged for takes and retakes across any scene.
6. Retake replaces previous take and transcript jobs for that scene.
7. Frontend static contracts for Pieza 56 in app.js.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    get_job,
)
from app.audiovisual.worker import (
    RESOLVERS,
)
from app.guard import guard
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


@pytest.fixture(autouse=True)
def reset_jobs_and_resolvers():
    """Ensure clean jobs storage, mock script client, sessions, and resolvers before and after every test."""
    _reset_local_jobs()
    RESOLVERS.clear()
    from app.audiovisual.worker import resolve_transcript

    RESOLVERS["transcript"] = resolve_transcript
    guard._sessions.clear()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Close-up of founder pointing at screen",
        on_screen_text="Stop doing this manually",
        why_it_stops_the_scroll="High emotion and clear dilemma",
    )


def make_scene(
    n: int,
    phase: str,
    asset_type: str = "a_roll",
    spoken_text: str = "Spoken text for scene.",
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken_text,
        shot="close up",
        b_roll=None,
        on_screen_text=f"Scene {n} tip",
        acting_note="Energetic and steady posture",
        sound="light background hum",
        asset_type=asset_type,
        stock_query="team working together" if asset_type == "stock" else None,
        visual_prompt="futuristic dashboard animation" if "ai" in asset_type else None,
    )


def make_multi_asset_scenes() -> list[Scene]:
    """Build a 6-scene script with all asset types: a_roll, stock, ai_image, ai_video, motion_graphic."""
    return [
        make_scene(1, "hook", "a_roll", spoken_text="Hook spoken line on camera."),
        make_scene(2, "lock_in", "stock", spoken_text="Lock in spoken text over stock."),
        make_scene(3, "body_1", "ai_image", spoken_text="Body 1 spoken text over AI image."),
        make_scene(4, "rehook", "ai_video", spoken_text="Rehook spoken text over AI video."),
        make_scene(5, "body_2", "motion_graphic", spoken_text="Body 2 spoken text over motion."),
        make_scene(6, "close_cta", "a_roll", spoken_text="Call to action on camera."),
    ]


def make_locked_script(
    session_id: str,
    idea_id: str,
    scenes: list[Scene],
    frame_zero: FrameZero,
    state: str = "locked",
) -> Script:
    return Script(
        session_id=session_id,
        idea_id=idea_id,
        title="Test Script P56 Record All Scenes",
        angle="From manual chaos to agentic system",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=frame_zero,
        scenes=scenes,
        state=state,
        sources=["Industry benchmark 2026"],
        music_prompt="Subtle energetic lo-fi beat",
        recording_format="selfie_natural",
    )


# =============================================================================
# 1. UPLOAD-URL ACCEPTS ALL SCENE TYPES (A-ROLL & B-ROLL)
# =============================================================================


def test_upload_url_accepts_stock_and_all_broll_scenes(authenticated_client, sample_frame_zero):
    """
    POST /takes/{scene_n}/upload-url returns 200 with signed upload URL for any scene
    in locked script (a_roll, stock, ai_image, ai_video, motion_graphic).
    Returns 404 for nonexistent scene, 409 for unlocked script.
    Charges 0 credits.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p56_upload_url"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_multi_asset_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    # All scenes (1 to 6) must return 200
    for scene in scenes:
        res = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/{scene.n}/upload-url")
        assert res.status_code == 200, f"Scene {scene.n} ({scene.asset_type}) was rejected with {res.status_code}"
        data = res.json()
        assert "storage_path" in data
        assert "signed_upload_url" in data
        assert "token" in data

        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
        expected_prefix = f"{token_hash}/{idea_id}/{scene.n}/"
        assert data["storage_path"].startswith(expected_prefix)

    # Nonexistent scene 99 -> 404
    res_nonexistent = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/99/upload-url")
    assert res_nonexistent.status_code == 404

    # Unlocked script -> 409
    script_draft = make_locked_script(
        session_token, "idea_p56_draft", scenes, sample_frame_zero, state="draft"
    )
    _save_script(script_draft)
    res_draft = authenticated_client.post("/api/audiovisual/idea_p56_draft/takes/1/upload-url")
    assert res_draft.status_code == 409

    # Total balance unchanged (0 credits charged for upload URLs)
    assert guard.get_remaining_credits(session_token) == initial_credits


# =============================================================================
# 2. COMMIT SETS ROLE: ON_CAMERA FOR A-ROLL, VOICEOVER FOR B-ROLL
# =============================================================================


def test_commit_sets_correct_role_by_asset_type(authenticated_client, sample_frame_zero):
    """
    POST /takes/{scene_n}/commit:
    - Sets role="on_camera" in output for a_roll scenes.
    - Sets role="voiceover" in output for B-roll scenes (stock, ai_image, ai_video, motion_graphic).
    - Status is 'done' (0 credits).
    - Enqueues 'transcript' job (status 'pending', 0 credits).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p56_commit_roles"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_multi_asset_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]

    for scene in scenes:
        storage_path = f"{token_hash}/{idea_id}/{scene.n}/take_scene_{scene.n}.webm"
        res = authenticated_client.post(
            f"/api/audiovisual/{idea_id}/takes/{scene.n}/commit",
            json={"storage_path": storage_path, "duration_s": 4.2, "mime": "video/webm"},
        )
        assert res.status_code == 200, f"Commit failed for scene {scene.n} ({scene.asset_type}): {res.text}"
        data = res.json()

        take_job = get_job(data["take_job_id"])
        transcript_job = get_job(data["transcript_job_id"])

        assert take_job["status"] == "done"
        assert take_job["kind"] == "a_roll_take"
        assert take_job["credits"] == 0

        # Verify role assignment per Pieza 56
        expected_role = "on_camera" if scene.asset_type == "a_roll" else "voiceover"
        assert take_job["output"]["role"] == expected_role, (
            f"Scene {scene.n} ({scene.asset_type}) expected role {expected_role}, "
            f"got {take_job['output'].get('role')}"
        )
        assert take_job["output"]["storage_path"] == storage_path
        assert take_job["output"]["duration_s"] == 4.2

        assert transcript_job["status"] == "pending"
        assert transcript_job["kind"] == "transcript"
        assert transcript_job["credits"] == 0

    # 0 credits charged for all takes
    assert guard.get_remaining_credits(session_token) == initial_credits


# =============================================================================
# 3. COMMIT SECURITY: REJECTS FOREIGN STORAGE PATHS (403)
# =============================================================================


def test_commit_foreign_storage_path_rejected_for_broll_scene(authenticated_client, sample_frame_zero):
    """
    POST /takes/{scene_n}/commit security check:
    Rejects storage_path from another session, idea, or scene with 403 on B-roll scenes too.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p56_security"

    scenes = make_multi_asset_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]

    # Scene 2 is stock (B-roll)
    # 1. Foreign user hash
    foreign_path = f"badhash123456789/{idea_id}/2/take.webm"
    res1 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/2/commit",
        json={"storage_path": foreign_path, "duration_s": 3.0},
    )
    assert res1.status_code == 403

    # 2. Foreign idea
    other_idea_path = f"{token_hash}/other_idea/2/take.webm"
    res2 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/2/commit",
        json={"storage_path": other_idea_path, "duration_s": 3.0},
    )
    assert res2.status_code == 403

    # 3. Wrong scene number
    wrong_scene_path = f"{token_hash}/{idea_id}/1/take.webm"
    res3 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/2/commit",
        json={"storage_path": wrong_scene_path, "duration_s": 3.0},
    )
    assert res3.status_code == 403


# =============================================================================
# 4. COMMIT RETAKE: REPLACES PREVIOUS TAKE ON B-ROLL SCENE (0 CREDITS)
# =============================================================================


def test_commit_retake_on_broll_scene_cancels_previous_jobs(authenticated_client, sample_frame_zero):
    """
    Retaking a B-roll scene cancels the old take and transcript jobs, creates a new done take
    with role="voiceover", and enqueues a new pending transcript (0 credits).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p56_retake"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_multi_asset_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]

    # First take on scene 2 (stock)
    path_1 = f"{token_hash}/{idea_id}/2/take_1.webm"
    res1 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/2/commit",
        json={"storage_path": path_1, "duration_s": 4.0},
    )
    assert res1.status_code == 200
    take1_id = res1.json()["take_job_id"]
    transcript1_id = res1.json()["transcript_job_id"]

    assert get_job(take1_id)["status"] == "done"
    assert get_job(take1_id)["output"]["role"] == "voiceover"
    assert get_job(transcript1_id)["status"] == "pending"

    # Retake on same scene 2
    path_2 = f"{token_hash}/{idea_id}/2/take_2.webm"
    res2 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/2/commit",
        json={"storage_path": path_2, "duration_s": 5.0},
    )
    assert res2.status_code == 200
    take2_id = res2.json()["take_job_id"]
    transcript2_id = res2.json()["transcript_job_id"]

    # Old jobs cancelled
    assert get_job(take1_id)["status"] == "cancelled"
    assert get_job(transcript1_id)["status"] == "cancelled"

    # New jobs active
    assert get_job(take2_id)["status"] == "done"
    assert get_job(take2_id)["output"]["role"] == "voiceover"
    assert get_job(transcript2_id)["status"] == "pending"

    # Balance remains unchanged (0 credits)
    assert guard.get_remaining_credits(session_token) == initial_credits


# =============================================================================
# 5. FRONTEND STATIC CONTRACT TESTS FOR PIEZA 56
# =============================================================================


def test_frontend_static_contracts_pieza_56():
    """
    Contract tests for Pieza 56 in app.js:
    - Step 1 header is "Record your takes"
    - "Takes recorded: " summary counter present
    - Labels "On camera" and "Voice over B-roll — you may or may not appear (decided in Editing)" present
    - Small mark "🎙 Your take ✓" present for B-roll card strip
    - Inspector supports AssemblyAI real subtitles for all scenes
    - Studio navigation iterates over allScenes
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    js_content = APP_JS_PATH.read_text(encoding="utf-8")
    stripped_js = re.sub(r"/\*.*?\*/", "", js_content, flags=re.DOTALL)

    # 1. Step 1 title: "Record your takes"
    assert "Record your takes" in stripped_js

    # 2. Step 1 summary: "Takes recorded: "
    assert "Takes recorded:" in stripped_js
    assert "AV-TakesCounter" in stripped_js

    # 3. Role labels for scenes in Step 1
    assert "On camera" in stripped_js
    assert "Voice over B-roll — you may or may not appear (decided in Editing)" in stripped_js

    # 4. Mark "🎙 Your take ✓" for B-roll take in strip and inspector
    assert "🎙 Your take ✓" in stripped_js

    # 5. Inspector shows Real Spoken Subtitles (AssemblyAI)
    assert "Real Spoken Subtitles (AssemblyAI)" in stripped_js

    # 6. Studio takes count and allScenes navigation
    assert "Take ${takeNum} of ${totalTakes}" in stripped_js
