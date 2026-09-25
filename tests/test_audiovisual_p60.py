"""
Unit and integration tests for PIEZA 60:
- Guarantee AI prompt is never 'null' and soundtrack + SFX exist by any path.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
    list_jobs,
    mark_done,
    mark_failed,
)
from app.audiovisual.worker import RESOLVERS, process_one_job
from app.guard import guard
from app.scripting.scripts import FrameZero, Scene, Script, _check_script, _save_script

TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def clean_p60_environment():
    """Ensure clean local state and mock script client for tests."""
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()


@pytest.fixture
def sample_frame_zero() -> FrameZero:
    return FrameZero(
        visual="Founder talking about tech stack",
        on_screen_text="Sovereign AI Stack",
        why_it_stops_the_scroll="High emotion and clear dilemma",
    )


def make_scene(
    n: int,
    phase: str,
    asset_type: str = "a_roll",
    spoken_text: str = "We build custom agents locally.",
    stock_query: str | None = None,
    visual_prompt: str | None = None,
    sound: str = "upbeat music",
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken_text,
        shot="close up",
        b_roll="hands typing code on mechanical keyboard",
        on_screen_text=f"Scene {n} focus",
        acting_note="Confident tone",
        sound=sound,
        asset_type=asset_type,
        stock_query=stock_query,
        visual_prompt=visual_prompt,
    )


def make_5_scenes() -> list[Scene]:
    return [
        make_scene(1, "hook", "a_roll", sound="whoosh impact"),
        make_scene(2, "lock_in", "a_roll", sound="subtle click"),
        make_scene(3, "body_1", "stock", sound="ambient swell"),
        make_scene(4, "rehook", "a_roll", sound="cash register pop"),
        make_scene(5, "body_2", "motion_graphic", sound="upbeat music"),
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
        title="Test Script P60",
        angle="Sovereignty and efficiency",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=frame_zero,
        scenes=scenes,
        state=state,
        sources=["Internal Spec 2026"],
        music_prompt="Lo-fi beats",
        recording_format="selfie_natural",
    )


def test_soundtrack_endpoint(authenticated_client, sample_frame_zero):
    """
    POST /soundtrack en guion locked sin jobs -> crea 1 music + un sfx por cada escena
    donde pick_sfx devuelve algo; una segunda llamada no crea nada nuevo.
    Sin auth -> 401; guion draft -> 409.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_soundtrack"

    # Test 401 without auth header
    res_unauth = authenticated_client.post(
        f"/api/audiovisual/{idea_id}/soundtrack",
        headers={"authorization": ""},
    )
    assert res_unauth.status_code == 401

    # Test 409 with draft script
    scenes = make_5_scenes()
    draft_script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="draft")
    _save_script(draft_script)

    res_draft = authenticated_client.post(f"/api/audiovisual/{idea_id}/soundtrack")
    assert res_draft.status_code == 409

    # Test 200 with locked script
    locked_script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(locked_script)

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/soundtrack")
    assert res.status_code == 200
    data = res.json()
    jobs = data.get("jobs", [])
    assert len(jobs) >= 1
    music_jobs = [j for j in jobs if j.get("kind") == "music"]
    assert len(music_jobs) == 1

    initial_job_count = len(jobs)

    # Second call creates no duplicate jobs
    res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/soundtrack")
    assert res2.status_code == 200
    data2 = res2.json()
    jobs2 = data2.get("jobs", [])
    assert len(jobs2) == initial_job_count


def test_regenerate_scene_null_visual_prompt(authenticated_client, sample_frame_zero):
    """
    /scenes/{n}/regenerate sobre una escena ai_image con visual_prompt="null" ->
    _generate_asset_prompt (mock) se llama, el input del job lleva el prompt generado y la escena guardada también.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_regen_null"
    scenes = make_5_scenes()
    scenes[2] = make_scene(3, "body_1", asset_type="ai_image", visual_prompt="null")
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    guard._sessions[session_token]["credits"] = 500

    with patch("app.main._generate_asset_prompt", new_callable=AsyncMock) as mock_gen_prompt:
        mock_gen_prompt.return_value = "A realistic futuristic AI agent studio"
        res = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/3/regenerate")
        assert res.status_code == 200
        mock_gen_prompt.assert_called_once()
        job = res.json().get("job", {})
        assert job.get("input", {}).get("visual_prompt") == "A realistic futuristic AI agent studio"

        updated_script = _check_script(session_token, idea_id)
        assert updated_script.scenes[2].visual_prompt == "A realistic futuristic AI agent studio"


def test_patch_asset_type_null_visual_prompt(authenticated_client, sample_frame_zero):
    """
    PATCH a ai_image sobre una escena con visual_prompt="null" -> se genera prompt.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_patch_null"
    scenes = make_5_scenes()
    scenes[2] = make_scene(3, "body_1", asset_type="stock", visual_prompt="null")
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    with patch("app.main._generate_asset_prompt", new_callable=AsyncMock) as mock_gen_prompt:
        mock_gen_prompt.return_value = "High tech servers in glowing blue room"
        res = authenticated_client.patch(
            f"/api/audiovisual/{idea_id}/scenes/3/asset_type",
            json={"asset_type": "ai_image"},
        )
        assert res.status_code == 200
        mock_gen_prompt.assert_called_once()
        updated_script = _check_script(session_token, idea_id)
        assert updated_script.scenes[2].visual_prompt == "High tech servers in glowing blue room"


def test_generate_insufficient_credits_after_soundtrack(authenticated_client, sample_frame_zero):
    """
    Con el job music ya creado por /soundtrack y saldo insuficiente ->
    /generate responde 402 y no crea ningún job de escena.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_low_credits"
    scenes = make_5_scenes()
    scenes[2] = make_scene(3, "body_1", asset_type="ai_video")  # costs 150 credits
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    res_st = authenticated_client.post(f"/api/audiovisual/{idea_id}/soundtrack")
    assert res_st.status_code == 200

    guard._sessions[session_token]["credits"] = 10

    res_gen = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen.status_code == 402
    data = res_gen.json()
    assert data["credits_needed"] == 150

    jobs = list_jobs(session_token, idea_id)
    scene_jobs = [j for j in jobs if j.get("scene_n") is not None and j.get("kind") not in ("sfx",)]
    assert len(scene_jobs) == 0


@pytest.mark.asyncio
async def test_worker_null_visual_prompt_fails_without_charge(sample_frame_zero):
    """
    Worker: job ai_image con visual_prompt "null" -> termina fallido con Missing visual prompt,
    sin llamar a deduct_credits ni al generador.
    """
    session_id = "sess_p60_worker"
    idea_id = "idea_p60_worker"
    guard._sessions[session_id] = {"credits": 100}

    job = create_job(
        session_token=session_id,
        idea_id=idea_id,
        scene_n=1,
        kind="ai_image",
        credits=15,
        cost_usd=0.0336,
        input={"visual_prompt": "null"},
    )

    mock_resolver = AsyncMock()
    RESOLVERS["ai_image"] = mock_resolver

    with patch("app.guard.guard.deduct_credits") as mock_deduct:
        processed = await process_one_job()
        assert processed is True
        mock_resolver.assert_not_called()
        mock_deduct.assert_not_called()

        updated_job = get_job(job["id"])
        assert updated_job["status"] == "failed"
        assert updated_job["error"] == "Missing visual prompt"
        assert updated_job["charged"] is False


def test_generate_skips_scenes_with_live_regen_jobs(authenticated_client, sample_frame_zero):
    """
    escena 3 ai_image con un job done de key regen -> /generate no crea job para la escena 3
    y no la suma a needed (con saldo justo para las otras escenas -> 150, no 402).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_regen_skip"
    scenes = make_5_scenes()
    scenes[2] = make_scene(3, "body_1", asset_type="ai_image")  # costs 15
    scenes[4] = make_scene(5, "body_2", asset_type="ai_video")  # costs 150
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    job_sc3 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_image",
        credits=15,
        idempotency_key=f"{session_token}:{idea_id}:scene_3:ai_image:regen:12345_abcd",
    )
    mark_done(job_sc3["id"], output={"storage_path": "fake.jpg"})

    # Set credits to 150 (enough for scene 5 ai_video, but not scene 3 + 5 = 165)
    guard._sessions[session_token]["credits"] = 150

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res.status_code == 200

    jobs = list_jobs(session_token, idea_id)
    sc3_jobs = [j for j in jobs if j.get("scene_n") == 3]
    # Should only have the 1 regen job created manually, no duplicate job created by /generate
    assert len(sc3_jobs) == 1
    assert sc3_jobs[0]["id"] == job_sc3["id"]

    sc5_jobs = [j for j in jobs if j.get("scene_n") == 5]
    assert len(sc5_jobs) == 1


def test_generate_includes_scenes_with_failed_or_cancelled_regen_jobs(authenticated_client, sample_frame_zero):
    """
    escena con job failed o cancelled de key regen -> sí cuenta y sí se crea.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_regen_failed"
    scenes = make_5_scenes()
    scenes[2] = make_scene(3, "body_1", asset_type="ai_image")  # costs 15
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    job_sc3 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_image",
        credits=15,
        idempotency_key=f"{session_token}:{idea_id}:scene_3:ai_image:regen:12345_abcd",
    )
    mark_failed(job_sc3["id"], error="Failed generation")

    guard._sessions[session_token]["credits"] = 200

    res = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res.status_code == 200

    jobs = list_jobs(session_token, idea_id)
    sc3_jobs = [j for j in jobs if j.get("scene_n") == 3]
    # Should have 2 jobs: the failed regen job + the new pending job created by /generate
    assert len(sc3_jobs) == 2
    assert any(j["status"] == "pending" for j in sc3_jobs)


def test_generate_base_cost_deducted_once(authenticated_client, sample_frame_zero):
    """
    Con CREDITS_TABLE["base"] parcheado a 5, dos llamadas seguidas a /generate ->
    deduct_credits de la base se llama una sola vez.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p60_base_once"
    scenes = make_5_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    guard._sessions[session_token]["credits"] = 200

    with patch("app.audiovisual.pricing.CREDITS_TABLE", {"base": 5, "a_roll": 0, "stock": 0, "motion_graphic": 0}), \
            patch.object(guard, "deduct_credits", wraps=guard.deduct_credits) as mock_deduct:
        res1 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
        assert res1.status_code == 200

        res2 = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
        assert res2.status_code == 200

        # Count calls with amount=5
        base_deduct_calls = [
            c for c in mock_deduct.call_args_list
            if c.kwargs.get("amount") == 5 or (c.args and len(c.args) >= 2 and c.args[1] == 5)
        ]
        assert len(base_deduct_calls) == 1

