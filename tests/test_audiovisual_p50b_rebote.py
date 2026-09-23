"""
Unit and integration tests for PIEZA 50B (Rebote del QA de la P50: el dinero no puede tener agujeros):
1. Saldo 20 con guion de 1 ai_video (105 créditos total) -> 402 con credits_needed=105, 0 cobro, 0 jobs.
2. deduct_credits lanza al terminar un job -> job failed, GET /jobs sin URL firmada, 0 cobro.
3. Simula crash: job con charged=true y status=running -> resume_stale + reproceso -> deduct_credits llamado 0 veces más.
4. Dos llamadas a generate con el mismo guion -> base cobrada 1 vez.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import HTTPException
import pytest

from app.audiovisual.jobs import (
    _jobs_lock,
    _local_jobs,
    _reset_local_jobs,
    claim_next_pending,
    create_job,
    get_job,
    list_jobs,
    resume_stale,
)
from app.audiovisual.worker import RESOLVERS, process_one_job
from app.guard import guard
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)

TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def clean_jobs_and_resolvers():
    """Ensure clean jobs storage and resolvers before and after every test."""
    _reset_local_jobs()
    RESOLVERS.clear()
    yield
    _reset_local_jobs()
    RESOLVERS.clear()


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Founder looking at camera",
        on_screen_text="Stop wasting budget",
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
        visual_prompt="futuristic robot worker animation" if "ai" in asset_type else None,
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
        title="Test Script Bloque D - Rebote Cobros",
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
# 1. SALDO 20 CON GUION DE 1 AI_VIDEO -> 402, 0 COBRO, 0 JOBS
# =============================================================================

def test_generate_saldo_insuficiente_para_total_assets_402_0_cobro_0_jobs(
    authenticated_client, sample_frame_zero
):
    """
    Test 1 (Spec P50B #1):
    Saldo 20 con guion de 1 ai_video (base 15 + ai_video 90 = 105 créditos).
    Debe devolver 402 con credits_needed=105, credits_remaining=20, payment_url,
    0 cobro y 0 jobs creados.
    """
    session_token = guard.get_or_create_user_session(TEST_USER_ID)
    # Configurar saldo exacto de 20 créditos
    guard._sessions[session_token]["credits"] = 20
    assert guard.get_remaining_credits(session_token) == 20

    idea_id = "idea_p50b_saldo_20"
    # 1 escena con ai_video (90 créditos) + resto a_roll
    scenes = [
        make_scene(1, "hook", "ai_video"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "a_roll"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")

    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Intentar generar
    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")

    # Debe ser 402 Payment Required
    assert res.status_code == 402
    data = res.json()
    assert data["credits_needed"] == 105
    assert data["credits_remaining"] == 20
    assert "payment_url" in data
    assert data["error"] == "Session budget exhausted"

    # 0 cobro: el saldo sigue siendo 20
    assert guard.get_remaining_credits(session_token) == 20

    # 0 jobs: ningún job fue creado
    jobs_in_db = list_jobs(session_token, idea_id)
    assert len(jobs_in_db) == 0


# =============================================================================
# 2. DEDUCT_CREDITS LANZA AL TERMINAR UN JOB -> JOB FAILED, GET /JOBS SIN URL, 0 COBRO
# =============================================================================

@pytest.mark.asyncio
async def test_worker_deduct_credits_fails_marks_job_failed_sin_url_0_cobro(
    authenticated_client,
):
    """
    Test 2 (Spec P50B #2):
    Si deduct_credits lanza al terminar un job:
    - Job pasa a status='failed' con error descriptivo.
    - charged=False.
    - No se expone el output ni storage_path al founder.
    - GET /api/audiovisual/{idea_id}/jobs no incluye signed_url para este job.
    - 0 cobro en la sesión.
    """
    session_token = guard.get_or_create_user_session(TEST_USER_ID)
    guard._sessions[session_token]["credits"] = 100
    idea_id = "idea_p50b_job_fail_charge"

    # Crear job de ai_image (5 créditos)
    job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="ai_image",
        credits=5,
        cost_usd=0.0336,
        idempotency_key="idem_fail_charge_img",
    )

    async def mock_ai_image_resolver(j):
        return {
            "storage_path": f"hash/{idea_id}/1/mock_img.png",
            "mime": "image/png",
            "cost_usd": 0.0336,
        }

    RESOLVERS["ai_image"] = mock_ai_image_resolver

    # Simular que deduct_credits lanza un error (e.g. 402 o excepción)
    with patch(
        "app.audiovisual.worker.guard.deduct_credits",
        side_effect=HTTPException(status_code=402, detail="Session budget exhausted"),
    ):
        claimed = await process_one_job()
        assert claimed is True

    # Verificar que el job quedó 'failed' y charged=False
    updated_job = get_job(job["id"])
    assert updated_job is not None
    assert updated_job["status"] == "failed"
    assert updated_job["charged"] is False
    assert "Payment failed" in updated_job["error"]
    # No se expone storage_path en output (se guarda como internal_storage_path para cleanup)
    assert updated_job["output"].get("storage_path") is None
    assert updated_job["output"].get("internal_storage_path") == f"hash/{idea_id}/1/mock_img.png"

    # 0 cobro: el saldo sigue en 100
    assert guard.get_remaining_credits(session_token) == 100

    # GET /api/audiovisual/{idea_id}/jobs endpoint no debe dar signed_url para el job failed
    res_jobs = authenticated_client.get(f"/api/audiovisual/{idea_id}/jobs")
    assert res_jobs.status_code == 200
    jobs_list = res_jobs.json()["jobs"]
    assert len(jobs_list) == 1
    failed_job_dto = jobs_list[0]
    assert failed_job_dto["id"] == job["id"]
    assert failed_job_dto["status"] == "failed"
    assert "signed_url" not in failed_job_dto


# =============================================================================
# 3. CRASH DESPUÉS DE CHARGED=TRUE -> RESUME_STALE + REPROCESO -> DEDUCT_CREDITS LLAMADO 0 VECES
# =============================================================================

@pytest.mark.asyncio
async def test_worker_crash_charged_true_resumed_no_double_charge():
    """
    Test 3 (Spec P50B #3):
    Simula crash: un job tenía charged=true y status=running cuando el proceso murió.
    resume_stale() lo pasa a pending respetando charged=true.
    Al reprocesarse, deduct_credits es llamado 0 veces más y el job termina en done.
    """
    session_token = guard.create_user_session("user_p50b_crash_sim", initial_credits=100)
    idea_id = "idea_p50b_crash"

    job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="ai_video",
        credits=90,
        cost_usd=0.30,
        idempotency_key="idem_crash_job",
    )

    # Claim atómico inicial: pasa a running con attempts=1
    claimed = claim_next_pending()
    assert claimed is not None
    assert claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1

    # Simular que el write-ahead ya persistió charged=True y cobró los 90 créditos
    with _jobs_lock:
        _local_jobs[job["id"]]["charged"] = True
    guard.deduct_credits(session_token, amount=90)
    assert guard.get_remaining_credits(session_token) == 10

    # Simular muerte del proceso -> reinicio y llamada a resume_stale()
    resumed_count = resume_stale()
    assert resumed_count == 1

    stale_job = get_job(job["id"])
    assert stale_job["status"] == "pending"
    assert stale_job["attempts"] == 2
    # Invariante crítico: charged=True se preserva a través de resume_stale
    assert stale_job["charged"] is True

    # Resolver disponible para reprocesar
    async def mock_ai_video_resolver(j):
        return {
            "storage_path": f"hash/{idea_id}/1/video_recovered.mp4",
            "mime": "video/mp4",
            "cost_usd": 0.30,
        }

    RESOLVERS["ai_video"] = mock_ai_video_resolver

    # Reprocesar el job reclamado
    with patch("app.audiovisual.worker.guard.deduct_credits") as mock_deduct:
        claimed_again = await process_one_job()
        assert claimed_again is True
        # deduct_credits debe ser llamado EXACTAMENTE 0 veces más
        mock_deduct.assert_not_called()

    # Verificar que el job quedó 'done' con charged=True y los créditos se mantuvieron en 10
    final_job = get_job(job["id"])
    assert final_job["status"] == "done"
    assert final_job["charged"] is True
    assert final_job["output"]["storage_path"] == f"hash/{idea_id}/1/video_recovered.mp4"
    assert guard.get_remaining_credits(session_token) == 10


# =============================================================================
# 4. DOS LLAMADAS A GENERATE CON EL MISMO GUION -> BASE COBRADA 1 VEZ
# =============================================================================

def test_generate_doble_llamada_cobra_base_una_sola_vez(
    authenticated_client, sample_frame_zero
):
    """
    Test 4 (Spec P50B #4):
    Dos llamadas a POST /api/audiovisual/{idea_id}/generate con el mismo guion locked:
    - La primera llamada crea los jobs y cobra la base (15 créditos).
    - La segunda llamada detecta el ancla music por idempotencia y NO vuelve a cobrar la base.
    - Base cobrada EXACTAMENTE 1 vez en total.
    """
    session_token = guard.get_or_create_user_session(TEST_USER_ID)
    guard._sessions[session_token]["credits"] = 100
    idea_id = "idea_p50b_double_click"

    scenes = [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "stock"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "motion_graphic"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")

    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

    # Primera llamada a generate
    res1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["credits_remaining"] == 85  # 100 - 15 base
    assert len(data1["jobs"]) == 3  # stock + motion + music
    assert guard.get_remaining_credits(session_token) == 85

    # Segunda llamada a generate (simulando doble clic o reintento)
    res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res2.status_code == 200
    data2 = res2.json()
    # Saldo debe permanecer exactamente en 85 (NO se descuentan 15 otra vez)
    assert data2["credits_remaining"] == 85
    assert guard.get_remaining_credits(session_token) == 85

    # Los IDs de los jobs son idénticos
    jobs1_ids = [j["id"] for j in data1["jobs"]]
    jobs2_ids = [j["id"] for j in data2["jobs"]]
    assert jobs1_ids == jobs2_ids
