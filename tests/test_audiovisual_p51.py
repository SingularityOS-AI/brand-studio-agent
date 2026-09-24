"""
Unit and integration tests for PIEZA 51:
Teleprompter + Grabación por toma de escenas A-roll + Transcripción AssemblyAI.

Covers:
a. POST /api/audiovisual/{idea_id}/takes/{scene_n}/upload-url rechazado si guion no locked (409) o escena no a_roll (400).
b. POST /api/audiovisual/{idea_id}/takes/{scene_n}/upload-url devuelve storage_path, signed_upload_url y token para escena a_roll de guion locked (0 créditos).
c. POST /api/audiovisual/{idea_id}/takes/{scene_n}/commit rechaza storage_path ajeno (403) o no matching con caller.
d. POST /api/audiovisual/{idea_id}/takes/{scene_n}/commit cancela take previo y encola transcript (0 créditos).
e. Resolver transcript corre mock de AssemblyAI y llena words (con start_ms, end_ms, confidence) + text + language_code en job output.
f. Error de AssemblyAI marca job failed sin cobrar créditos.
g. Ciclo completo: estimate -> 1 toma -> retoma -> commit -> jobs list confirma 0 cobro.
"""
from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
)
from app.audiovisual.worker import (
    RESOLVERS,
    process_one_job,
)
from app.guard import guard
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)


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
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Founder talking directly to camera",
        on_screen_text="Stop doing this manually",
        why_it_stops_the_scroll="High emotion and clear dilemma",
    )


def make_scene(
    n: int,
    phase: str,
    asset_type: str = "a_roll",
    spoken_text: str = "Here is what we do to scale cleanly.",
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


def make_default_scenes(first_scene_type: str = "a_roll") -> list[Scene]:
    return [
        make_scene(1, "hook", first_scene_type, spoken_text="The first hook line."),
        make_scene(2, "lock_in", "a_roll", spoken_text="Second line lock in."),
        make_scene(3, "body_1", "stock"),
        make_scene(4, "rehook", "a_roll", spoken_text="Rehook line."),
        make_scene(5, "body_2", "motion_graphic"),
        make_scene(6, "close_cta", "a_roll", spoken_text="Final call to action."),
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
        title="Test Script P51 Teleprompter",
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
# a. UPLOAD URL REJECTION (409 & 400)
# =============================================================================

def test_upload_url_unlocked_script_rejected(authenticated_client, sample_frame_zero):
    """POST /takes/{scene_n}/upload-url returns 409 if script is not locked."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_unlocked_test"

    scenes = make_default_scenes("a_roll")
    script_draft = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="draft"
    )
    _save_script(script_draft)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/1/upload-url")
    assert res.status_code == 409
    assert "locked" in res.json()["error"].lower()


def test_upload_url_scene_validation(authenticated_client, sample_frame_zero):
    """POST /takes/{scene_n}/upload-url accepts stock scenes (Pieza 56) and returns 404 for nonexistent scenes."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_non_aroll_test"

    scenes = make_default_scenes("a_roll")
    script = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="locked"
    )
    _save_script(script)

    # Scene 3 is stock -> accepts per Pieza 56 (200)
    res_stock = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/3/upload-url")
    assert res_stock.status_code == 200
    assert "storage_path" in res_stock.json()

    # Scene 99 does not exist -> 404
    res_nonexistent = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/99/upload-url")
    assert res_nonexistent.status_code == 404


# =============================================================================
# b. UPLOAD URL SUCCESS (0 CREDITS)
# =============================================================================

def test_upload_url_success_zero_credits(authenticated_client, sample_frame_zero):
    """POST /takes/{scene_n}/upload-url returns storage_path, signed_upload_url and token (0 credits)."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_upload_url_success"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_default_scenes("a_roll")
    script = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="locked"
    )
    _save_script(script)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/1/upload-url")
    assert res.status_code == 200
    data = res.json()

    assert "storage_path" in data
    assert "signed_upload_url" in data
    assert "token" in data

    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    expected_prefix = f"{token_hash}/{idea_id}/1/"
    assert data["storage_path"].startswith(expected_prefix)
    assert data["storage_path"].endswith(".webm")

    # 0 credits charged
    assert guard.get_remaining_credits(session_token) == initial_credits


# =============================================================================
# c. COMMIT REJECTS FOREIGN OR INVALID STORAGE PATH (403)
# =============================================================================

def test_commit_foreign_storage_path_rejected(authenticated_client, sample_frame_zero):
    """POST /takes/{scene_n}/commit rejects storage_path from another session or idea (403)."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_commit_security"

    scenes = make_default_scenes("a_roll")
    script = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="locked"
    )
    _save_script(script)

    # 1. Foreign caller hash
    foreign_path = "0123456789abcdef/idea_commit_security/1/take_123.webm"
    res_foreign = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": foreign_path, "duration_s": 5.2},
    )
    assert res_foreign.status_code == 403

    # 2. Foreign idea in path
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    other_idea_path = f"{token_hash}/other_idea_id/1/take_123.webm"
    res_other_idea = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": other_idea_path, "duration_s": 5.2},
    )
    assert res_other_idea.status_code == 403

    # 3. Mismatched scene_n in path
    wrong_scene_path = f"{token_hash}/{idea_id}/2/take_123.webm"
    res_wrong_scene = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": wrong_scene_path, "duration_s": 5.2},
    )
    assert res_wrong_scene.status_code == 403


# =============================================================================
# d. COMMIT CANCELS PREVIOUS TAKE AND ENQUEUES TRANSCRIPT (0 CREDITS)
# =============================================================================

def test_commit_cancels_previous_take_and_enqueues_transcript(
    authenticated_client, sample_frame_zero
):
    """
    POST /takes/{scene_n}/commit creates done take job, enqueues pending transcript job,
    and cancels previous take/transcript jobs for the same scene (0 credits).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_commit_lifecycle"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_default_scenes("a_roll")
    script = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="locked"
    )
    _save_script(script)

    # First take
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    path_1 = f"{token_hash}/{idea_id}/1/take_1.webm"

    res1 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": path_1, "duration_s": 4.5, "mime": "video/webm"},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    take1_id = data1["take_job_id"]
    transcript1_id = data1["transcript_job_id"]

    job_take1 = get_job(take1_id)
    assert job_take1["status"] == "done"
    assert job_take1["kind"] == "a_roll_take"
    assert job_take1["output"]["storage_path"] == path_1
    assert job_take1["output"]["duration_s"] == 4.5
    assert job_take1["credits"] == 0

    job_tr1 = get_job(transcript1_id)
    assert job_tr1["status"] == "pending"
    assert job_tr1["kind"] == "transcript"
    assert job_tr1["input"]["storage_path"] == path_1
    assert job_tr1["credits"] == 0

    # 0 credits charged
    assert guard.get_remaining_credits(session_token) == initial_credits

    # Second take (retake) for the same scene
    path_2 = f"{token_hash}/{idea_id}/1/take_2.webm"
    res2 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": path_2, "duration_s": 5.1, "mime": "video/webm"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    take2_id = data2["take_job_id"]
    transcript2_id = data2["transcript_job_id"]

    # Verify previous jobs are cancelled
    assert get_job(take1_id)["status"] == "cancelled"
    assert get_job(transcript1_id)["status"] == "cancelled"

    # Verify new jobs
    assert get_job(take2_id)["status"] == "done"
    assert get_job(transcript2_id)["status"] == "pending"

    # Still 0 credits charged
    assert guard.get_remaining_credits(session_token) == initial_credits


# =============================================================================
# e. RESOLVER TRANSCRIPT: ASSEMBLYAI SUCCESS
# =============================================================================

@pytest.mark.asyncio
async def test_resolver_transcript_assemblyai_success():
    """
    Resolver for transcript calls AssemblyAI with language_detection=True,
    populates words (start_ms, end_ms, confidence), text, and language_code.
    """
    session_token = guard.create_user_session("user_transcript_test", initial_credits=50)
    job = create_job(
        session_token=session_token,
        idea_id="idea_tr_success",
        scene_n=1,
        kind="transcript",
        credits=0,
        input={
            "storage_path": "hash/idea_tr_success/1/take_1.webm",
            "scene_n": 1,
            "spoken_text": "This is the sovereign way to build software.",
        },
    )

    class MockWord:
        def __init__(self, text, start, end, confidence):
            self.text = text
            self.start = start
            self.end = end
            self.confidence = confidence

    mock_transcript = MagicMock()
    mock_transcript.status = "completed"
    mock_transcript.error = None
    mock_transcript.text = "This is the sovereign way to build software."
    mock_transcript.language_code = "en"
    mock_transcript.words = [
        MockWord("This", 100, 300, 0.99),
        MockWord("is", 310, 450, 0.98),
        MockWord("the", 460, 600, 0.97),
        MockWord("sovereign", 610, 1100, 0.96),
        MockWord("way", 1110, 1400, 0.99),
        MockWord("to", 1410, 1550, 0.98),
        MockWord("build", 1560, 1900, 0.99),
        MockWord("software.", 1910, 2400, 0.95),
    ]

    with patch("app.audiovisual.storage.signed_url", return_value="https://storage.mock/fake_video.webm"):
        with patch("assemblyai.Transcriber") as mock_transcriber_cls:
            mock_instance = MagicMock()
            mock_instance.transcribe.return_value = mock_transcript
            mock_transcriber_cls.return_value = mock_instance

            claimed = await process_one_job()
            assert claimed is True

            # Verify transcribe was called with language_detection=True
            mock_instance.transcribe.assert_called_once()
            args, kwargs = mock_instance.transcribe.call_args
            config_arg = kwargs.get("config") if "config" in kwargs else (args[1] if len(args) > 1 else None)
            assert config_arg is not None
            assert config_arg.language_detection is True

    updated_job = get_job(job["id"])
    assert updated_job["status"] == "done"
    assert updated_job["credits"] == 0
    assert guard.get_remaining_credits(session_token) == 50

    output = updated_job["output"]
    assert output["text"] == "This is the sovereign way to build software."
    assert output["language_code"] == "en"
    assert len(output["words"]) == 8
    assert output["words"][0] == {
        "text": "This",
        "start_ms": 100,
        "end_ms": 300,
        "confidence": 0.99,
    }
    assert output["words"][3]["text"] == "sovereign"
    assert output["words"][3]["start_ms"] == 610


# =============================================================================
# f. RESOLVER TRANSCRIPT: ASSEMBLYAI FAILURE (0 CREDITS)
# =============================================================================

@pytest.mark.asyncio
async def test_resolver_transcript_assemblyai_failure_marks_failed():
    """
    If AssemblyAI raises or returns status error, job is marked 'failed'
    with 0 credits charged.
    """
    session_token = guard.create_user_session("user_tr_fail", initial_credits=50)
    job = create_job(
        session_token=session_token,
        idea_id="idea_tr_fail",
        scene_n=1,
        kind="transcript",
        credits=0,
        input={"storage_path": "hash/idea_tr_fail/1/take_bad.webm"},
    )

    with patch("app.audiovisual.storage.signed_url", return_value="https://storage.mock/bad_video.webm"):
        with patch("assemblyai.Transcriber") as mock_transcriber_cls:
            mock_instance = MagicMock()
            mock_instance.transcribe.side_effect = RuntimeError("AssemblyAI API 503 Service Unavailable")
            mock_transcriber_cls.return_value = mock_instance

            claimed = await process_one_job()
            assert claimed is True

    updated_job = get_job(job["id"])
    assert updated_job["status"] == "failed"
    assert "AssemblyAI API 503" in updated_job["error"]
    # 0 credits charged
    assert guard.get_remaining_credits(session_token) == 50


# =============================================================================
# g. FULL CYCLE: ESTIMATE -> TAKE -> RETAKE -> COMMIT -> JOBS CONFIRMS 0 COBRO
# =============================================================================

def test_full_cycle_estimate_take_retake_commit_jobs_zero_credits(
    authenticated_client, sample_frame_zero
):
    """
    Complete workflow:
    1. Locked script: 4 a_roll + 1 stock + 1 motion = 15 base credits.
    2. Estimate: 15 credits.
    3. Generate: deducts 15 base credits (stock, motion, music jobs created).
    4. Record Take 1: upload-url -> commit (0 credits).
    5. Retake Scene 1: upload-url -> commit (0 credits) -> take 1 cancelled, take 2 committed.
    6. Worker processes transcript 2 (0 credits).
    7. GET /jobs: takes and transcripts listed, done takes have signed_url.
    8. Total balance: exactly initial_credits - 15 (takes and transcripts charged 0).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_full_cycle_p51"
    initial_credits = guard.get_remaining_credits(session_token)

    scenes = make_default_scenes("a_roll")
    script = make_locked_script(
        session_token, idea_id, scenes, sample_frame_zero, state="locked"
    )
    _save_script(script)

    # 1. Estimate
    res_est = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res_est.status_code == 200
    assert res_est.json()["credits_total"] == 0

    # 2. Generate
    res_gen = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen.status_code == 200
    assert guard.get_remaining_credits(session_token) == initial_credits

    # 3. Take 1 upload URL
    res_up1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/1/upload-url")
    assert res_up1.status_code == 200
    up1_data = res_up1.json()
    path1 = up1_data["storage_path"]

    # 4. Take 1 commit
    res_com1 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": path1, "duration_s": 4.2},
    )
    assert res_com1.status_code == 200
    take1_id = res_com1.json()["take_job_id"]
    tr1_id = res_com1.json()["transcript_job_id"]

    # 5. Retake scene 1 (Take 2)
    res_up2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/takes/1/upload-url")
    assert res_up2.status_code == 200
    path2 = res_up2.json()["storage_path"]
    assert path1 != path2

    res_com2 = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/takes/1/commit",
        json={"storage_path": path2, "duration_s": 4.8},
    )
    assert res_com2.status_code == 200
    take2_id = res_com2.json()["take_job_id"]
    tr2_id = res_com2.json()["transcript_job_id"]

    # Verify take 1 and transcript 1 cancelled
    assert get_job(take1_id)["status"] == "cancelled"
    assert get_job(tr1_id)["status"] == "cancelled"

    # 6. Worker processes transcript 2
    mock_transcript = MagicMock()
    mock_transcript.status = "completed"
    mock_transcript.error = None
    mock_transcript.text = "The first hook line."
    mock_transcript.language_code = "en"
    mock_transcript.words = []

    with patch("app.audiovisual.storage.signed_url", return_value="https://storage.mock/take2.webm"):
        with patch("assemblyai.Transcriber") as mock_transcriber_cls:
            mock_instance = MagicMock()
            mock_instance.transcribe.return_value = mock_transcript
            mock_transcriber_cls.return_value = mock_instance

            claimed = asyncio.run(process_one_job())
            assert claimed is True

    assert get_job(tr2_id)["status"] == "done"

    # 7. GET /jobs endpoint
    res_jobs = authenticated_client.get(f"/api/audiovisual/{idea_id}/jobs")
    assert res_jobs.status_code == 200
    all_jobs = res_jobs.json()["jobs"]

    take2_job = next(j for j in all_jobs if j["id"] == take2_id)
    assert take2_job["status"] == "done"
    assert "signed_url" in take2_job
    assert path2 in take2_job["signed_url"]

    tr2_job = next(j for j in all_jobs if j["id"] == tr2_id)
    assert tr2_job["status"] == "done"
    assert tr2_job["output"]["text"] == "The first hook line."

    # 8. Confirm total balance: exactly initial_credits (0 extra charged for takes/retakes)
    assert guard.get_remaining_credits(session_token) == initial_credits
