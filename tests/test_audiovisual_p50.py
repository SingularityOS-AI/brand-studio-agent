"""
Unit and integration tests for Pieza 50 (Bloque D Cimientos):
- Pricing & cost estimation (sweet spot 15 credits, ai_video limit, ceiling limit)
- Storage (path hash, signed URLs, no clear session token)
- Jobs (idempotency, atomic claiming, resume stale)
- Worker (resolver dispatch, cobro al done una sola vez, 0 cobro en failed, jobs sin resolver pending)
- Endpoints (GET /api/audiovisual/{idea_id}/estimate, POST .../generate, GET .../jobs)
- Deuda (POST /api/script/generate con raw_footage -> 400 sin cobro)
"""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from app.audiovisual.config import AV_COST_CEILING_USD
from app.audiovisual.jobs import (
    _reset_local_jobs,
    claim_next_pending,
    create_job,
    get_job,
    list_jobs,
    mark_done,
    resume_stale,
)
from app.audiovisual.pricing import estimate
from app.audiovisual.storage import signed_url, upload_bytes
from app.audiovisual.worker import RESOLVERS, process_one_job
from app.guard import guard
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)


@pytest.fixture(autouse=True)
def reset_jobs_and_resolvers():
    """Ensure clean jobs storage and resolvers before and after every test."""
    _reset_local_jobs()
    RESOLVERS.clear()
    yield
    _reset_local_jobs()
    RESOLVERS.clear()


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Founder frustrated at screen",
        on_screen_text="Stop this now",
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
        title="Test Script Bloque D",
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
# 1. ESTIMATOR & PRICING TESTS
# =============================================================================

def test_estimate_sweet_spot(sample_frame_zero):
    """
    Punto dulce: 4 a_roll + 1 stock + 1 motion = 15 créditos total.
    Music: línea aparte con credits 0 (biblioteca).
    No sobrepasa límites ni techo.
    """
    scenes = [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "stock"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "motion_graphic"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script("sess_1", "idea_1", scenes, sample_frame_zero)
    est = estimate(script)

    assert est["credits_total"] == 15
    assert est["credits_base"] == 15
    assert est["cost_usd_base"] == 0.01
    assert est["ai_video_count"] == 0
    assert est["over_ceiling"] is False
    assert est["over_ai_video_limit"] is False
    assert len(est["scenes"]) == 6
    assert est["music"]["credits"] == 0
    assert est["music"]["cost_usd"] == 0.0
    assert est["music"]["resolution"] == "library_music"

    # Verify scene resolutions
    assert est["scenes"][0]["resolution"] == "founder_take"
    assert est["scenes"][2]["resolution"] == "pexels_pixabay"
    assert est["scenes"][4]["resolution"] == "hyperframes_template"


def test_estimate_two_ai_video_triggers_limit(sample_frame_zero):
    """2 ai_video -> over_ai_video_limit is True."""
    scenes = [
        make_scene(1, "hook", "ai_video"),
        make_scene(2, "lock_in", "ai_video"),
        make_scene(3, "body_1", "a_roll"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script("sess_1", "idea_1", scenes, sample_frame_zero)
    est = estimate(script)

    assert est["ai_video_count"] == 2
    assert est["over_ai_video_limit"] is True
    # 15 base + 90 + 90 = 195 credits
    assert est["credits_total"] == 195


def test_estimate_over_ceiling(sample_frame_zero):
    """Cost > 1.50 -> over_ceiling is True."""
    # 5 ai_video: 5 * 0.30 + 0.01 = 1.51 > 1.50
    scenes = [
        make_scene(1, "hook", "ai_video"),
        make_scene(2, "lock_in", "ai_video"),
        make_scene(3, "body_1", "ai_video"),
        make_scene(4, "rehook", "ai_video"),
        make_scene(5, "body_2", "ai_video"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script("sess_1", "idea_1", scenes, sample_frame_zero)
    est = estimate(script)

    assert est["cost_usd_total"] > AV_COST_CEILING_USD
    assert est["over_ceiling"] is True


def test_estimate_unlocked_script_rejected(sample_frame_zero):
    """estimate() rejects draft or reviewed scripts."""
    scenes = [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "a_roll"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script_draft = make_locked_script("sess_1", "idea_1", scenes, sample_frame_zero, state="draft")
    with pytest.raises(ValueError, match="Script must be locked"):
        estimate(script_draft)

    script_reviewed = make_locked_script("sess_1", "idea_1", scenes, sample_frame_zero, state="reviewed")
    with pytest.raises(ValueError, match="Script must be locked"):
        estimate(script_reviewed)


# =============================================================================
# 2. STORAGE TESTS
# =============================================================================

def test_storage_path_no_clear_token():
    """
    Ruta de storage sin token en claro.
    Usa sha256[:16] del session_token.
    """
    raw_token = "sess_secret_token_unhashed_abc_123"
    idea_id = "idea_viral_99"
    job_id = "job_456"

    path = upload_bytes(
        session_token=raw_token,
        idea_id=idea_id,
        scene_n=2,
        job_id=job_id,
        data=b"fake_video_bytes_here",
        mime="video/mp4",
    )

    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:16]
    assert raw_token not in path
    assert path.startswith(f"{expected_hash}/{idea_id}/2/{job_id}.mp4")

    # Video-level asset (scene_n is None) uses 'video'
    path_video = upload_bytes(
        session_token=raw_token,
        idea_id=idea_id,
        scene_n=None,
        job_id="job_music_1",
        data=b"fake_audio_bytes",
        mime="audio/mp3",
    )
    assert path_video.startswith(f"{expected_hash}/{idea_id}/video/job_music_1.mp3")

    # Signed URL generation
    url = signed_url(path, ttl=1800)
    assert isinstance(url, str)
    assert path in url


# =============================================================================
# 3. JOBS TESTS
# =============================================================================

def test_create_job_idempotency():
    """create_job(...) con la misma idempotency_key devuelve el existente."""
    key = "unique_idem_key_123"
    job1 = create_job(
        session_token="sess_1",
        idea_id="idea_1",
        scene_n=3,
        kind="stock",
        credits=0,
        cost_usd=0.0,
        idempotency_key=key,
    )
    job2 = create_job(
        session_token="sess_1",
        idea_id="idea_1",
        scene_n=3,
        kind="stock",
        credits=0,
        cost_usd=0.0,
        idempotency_key=key,
    )

    assert job1["id"] == job2["id"]
    all_jobs = list_jobs("sess_1", "idea_1")
    assert len(all_jobs) == 1


def test_claim_next_pending_no_duplicate():
    """claim_next_pending no entrega el mismo job dos veces."""
    create_job("sess_1", "idea_1", 1, "stock", idempotency_key="j1")
    create_job("sess_1", "idea_1", 2, "stock", idempotency_key="j2")

    claimed1 = claim_next_pending()
    claimed2 = claim_next_pending()
    claimed3 = claim_next_pending()

    assert claimed1 is not None
    assert claimed2 is not None
    assert claimed3 is None
    assert claimed1["id"] != claimed2["id"]
    assert claimed1["status"] == "running"
    assert claimed2["status"] == "running"
    assert claimed1["attempts"] == 1
    assert claimed2["attempts"] == 1


def test_resume_stale():
    """
    resume_stale() al arrancar: running -> pending con attempts+1;
    si attempts >= 3 -> failed.
    """
    # Job A: running with attempts=0 -> becomes pending with attempts=1
    j_a = create_job("sess_1", "idea_1", 1, "stock", idempotency_key="stale_a")
    claimed_a = claim_next_pending()
    assert claimed_a["id"] == j_a["id"]
    assert claimed_a["attempts"] == 1

    # Job B: running with attempts=1 -> becomes pending with attempts=2
    j_b = create_job("sess_1", "idea_1", 2, "stock", idempotency_key="stale_b")
    claimed_b = claim_next_pending()
    assert claimed_b["id"] == j_b["id"]

    # Job C: running with attempts=2 -> becomes failed with attempts=3
    j_c = create_job("sess_1", "idea_1", 3, "stock", idempotency_key="stale_c")
    claim_next_pending()
    # Artificially set attempts=2 while running
    from app.audiovisual.jobs import _jobs_lock, _local_jobs
    with _jobs_lock:
        _local_jobs[j_c["id"]]["attempts"] = 2

    resumed_count = resume_stale()
    assert resumed_count == 3

    check_a = get_job(j_a["id"])
    check_b = get_job(j_b["id"])
    check_c = get_job(j_c["id"])

    assert check_a["status"] == "pending"
    assert check_a["attempts"] == 2

    assert check_b["status"] == "pending"
    assert check_b["attempts"] == 2

    assert check_c["status"] == "failed"
    assert check_c["attempts"] == 3
    assert "Max attempts" in check_c["error"]


# =============================================================================
# 4. WORKER & RESOLVER TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_worker_cobro_al_done_una_sola_vez():
    """
    Cobro: al pasar a done, si credits > 0 y not charged -> guard.deduct_credits
    y charged=true en la misma transacción lógica.
    Nunca cobra dos veces.
    """
    session_token = guard.create_user_session("user_test_worker", initial_credits=100)
    job = create_job(
        session_token=session_token,
        idea_id="idea_1",
        scene_n=1,
        kind="ai_image",
        credits=5,
        cost_usd=0.0336,
        idempotency_key="job_worker_img",
    )

    async def mock_ai_image_resolver(j):
        return {"storage_path": "hash/idea_1/1/job_worker_img.png", "mime": "image/png"}

    RESOLVERS["ai_image"] = mock_ai_image_resolver

    # Process job
    claimed = await process_one_job()
    assert claimed is True

    updated_job = get_job(job["id"])
    assert updated_job["status"] == "done"
    assert updated_job["charged"] is True
    assert guard.get_remaining_credits(session_token) == 95

    # If processed or called again, cannot be claimed again and credits remain 95
    claimed_again = await process_one_job()
    assert claimed_again is False
    assert guard.get_remaining_credits(session_token) == 95


@pytest.mark.asyncio
async def test_worker_zero_cobro_en_failed():
    """0 cobro en failed."""
    session_token = guard.create_user_session("user_fail_worker", initial_credits=100)
    job = create_job(
        session_token=session_token,
        idea_id="idea_1",
        scene_n=1,
        kind="ai_video",
        credits=90,
        cost_usd=0.30,
        idempotency_key="job_worker_fail",
    )

    async def mock_failing_resolver(j):
        raise RuntimeError("Vertex quota exceeded")

    RESOLVERS["ai_video"] = mock_failing_resolver

    claimed = await process_one_job()
    assert claimed is True

    updated_job = get_job(job["id"])
    assert updated_job["status"] == "failed"
    assert updated_job["charged"] is False
    assert "Vertex quota exceeded" in updated_job["error"]
    # 0 credits charged
    assert guard.get_remaining_credits(session_token) == 100


@pytest.mark.asyncio
async def test_worker_unresolved_kind_stays_pending():
    """Un job sin resolver queda pending (no falla)."""
    create_job(
        session_token="sess_unresolved",
        idea_id="idea_1",
        scene_n=1,
        kind="motion_graphic",
        credits=0,
        idempotency_key="job_unresolved",
    )

    RESOLVERS.clear()  # No resolver for motion_graphic
    claimed = await process_one_job()
    assert claimed is False

    jobs = list_jobs("sess_unresolved", "idea_1")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"


# =============================================================================
# 5. ENDPOINTS TESTS (409, 422, 200)
# =============================================================================

def test_endpoints_409_422_200(authenticated_client, sample_frame_zero):
    """
    Test API endpoints:
    - GET /api/audiovisual/{idea_id}/estimate -> 409 si no locked; 200 si locked
    - POST /api/audiovisual/{idea_id}/generate -> 409 si no locked; 422 si over limit; 200 si OK
    - Base charge (15) cobra una sola vez
    - GET /api/audiovisual/{idea_id}/jobs -> lista con signed_url si done
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_endpoint_test"

    # 1. Script in draft state
    scenes_sweet = [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "stock"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "motion_graphic"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script_draft = make_locked_script(
        session_token, idea_id, scenes_sweet, sample_frame_zero, state="draft"
    )
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script_draft)

    # Estimate returns 409
    res_est_409 = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res_est_409.status_code == 409

    # Generate returns 409
    res_gen_409 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen_409.status_code == 409

    # 2. Script locked with over_ai_video_limit (2 ai_video)
    scenes_violating = [
        make_scene(1, "hook", "ai_video"),
        make_scene(2, "lock_in", "ai_video"),
        make_scene(3, "body_1", "a_roll"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script_violating = make_locked_script(
        session_token, idea_id, scenes_violating, sample_frame_zero, state="locked"
    )
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script_violating)

    res_gen_422 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen_422.status_code == 422
    assert "AI video limit exceeded" in res_gen_422.json()["error"]

    # 3. Valid locked script (sweet spot)
    script_ok = make_locked_script(
        session_token, idea_id, scenes_sweet, sample_frame_zero, state="locked"
    )
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script_ok)

    # Estimate 200
    res_est_200 = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res_est_200.status_code == 200
    assert res_est_200.json()["credits_total"] == 15

    initial_credits = guard.get_remaining_credits(session_token)

    # Generate 200
    res_gen_200 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen_200.status_code == 200
    data = res_gen_200.json()
    assert "jobs" in data
    # Scenes non-a_roll: scene 3 (stock) and scene 5 (motion_graphic) + 1 music job = 3 jobs
    assert len(data["jobs"]) == 3
    # 15 base credits deducted
    assert data["credits_remaining"] == initial_credits - 15

    # Calling generate again for the same locked script version is idempotent: no extra deduction
    res_gen_repeat = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen_repeat.status_code == 200
    assert res_gen_repeat.json()["credits_remaining"] == initial_credits - 15

    # 4. Jobs list endpoint
    # Mark one job as done with storage_path
    first_job_id = data["jobs"][0]["id"]
    mark_done(first_job_id, output={"storage_path": "hash/idea_endpoint_test/3/j.mp4"})

    res_jobs = authenticated_client.get(f"/api/audiovisual/{idea_id}/jobs")
    assert res_jobs.status_code == 200
    jobs_list = res_jobs.json()["jobs"]
    assert len(jobs_list) == 3
    done_job = next(j for j in jobs_list if j["id"] == first_job_id)
    assert done_job["status"] == "done"
    assert "signed_url" in done_job
    assert "hash/idea_endpoint_test/3/j.mp4" in done_job["signed_url"]


# =============================================================================
# 6. DEBT: RAW FOOTAGE 400 SIN COBRO
# =============================================================================

def test_raw_footage_400_sin_cobro(authenticated_client):
    """
    POST /api/script/generate con source_mode="raw_footage"
    debe devolver 400 antes de cobrar ("Raw footage upload is coming soon").
    """
    session_token = authenticated_client._test_session_token
    initial_credits = guard.get_remaining_credits(session_token)

    body = {
        "idea_id": "test_idea_raw_footage",
        "source_mode": "raw_footage",
        "interview_transcript": "Some transcript",
    }
    response = authenticated_client.post(
        "/api/script/generate?idea_id=test_idea_raw_footage",
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Raw footage upload is coming soon"
    # Sin cobro
    assert guard.get_remaining_credits(session_token) == initial_credits
