"""
Unit and integration tests for PIEZA 64:
- Audiovisual estimate with live assets check (credits_pending, cost_usd_pending, has_live_asset)
- _scene_has_live_asset consistency between /estimate and /generate
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    list_jobs,
    mark_cancelled,
    mark_done,
    mark_failed,
)
from app.audiovisual.worker import RESOLVERS
from app.guard import guard
from app.main import _scene_has_live_asset
from app.scripting.scripts import FrameZero, Scene, Script, _save_script


@pytest.fixture(autouse=True)
def clean_p64_environment():
    """Ensure clean local state and mock script storage client for tests."""
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
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken_text,
        shot="close up",
        b_roll="hands typing code",
        on_screen_text=f"Scene {n} focus",
        acting_note="Confident tone",
        sound="upbeat music",
        asset_type=asset_type,
        stock_query=stock_query,
        visual_prompt=visual_prompt,
    )


def make_locked_script(
    session_id: str,
    idea_id: str,
    scenes: list[Scene],
    frame_zero: FrameZero,
) -> Script:
    return Script(
        session_id=session_id,
        idea_id=idea_id,
        title="Test Script P64",
        angle="Sovereignty and efficiency",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=frame_zero,
        scenes=scenes,
        state="locked",
        sources=["Internal Spec 2026"],
        music_prompt="Lo-fi beats",
        recording_format="selfie_natural",
    )


def make_5_scenes_3_non_aroll() -> list[Scene]:
    return [
        make_scene(1, "hook", asset_type="a_roll"),
        make_scene(2, "lock_in", asset_type="a_roll"),
        make_scene(3, "body_1", asset_type="ai_image"),
        make_scene(4, "rehook", asset_type="ai_image"),
        make_scene(5, "body_2", asset_type="ai_image"),
    ]


def test_estimate_with_done_job(authenticated_client, sample_frame_zero):
    """
    1. Guion con 3 escenas no-a_roll, una con job done -> GET /estimate marca esa fila
    has_live_asset: true, credits_pending = suma de las otras dos, credits_total sin cambios.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p64_estimate_done"

    scenes = make_5_scenes_3_non_aroll()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    # Job done for scene 3 (kind="ai_image")
    job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_image",
        credits=15,
        cost_usd=0.0336,
        input={"visual_prompt": "test prompt"},
        idempotency_key=f"{session_token}:{idea_id}:3:ai_image",
    )
    mark_done(job["id"], output={"signed_url": "http://example.com/asset.png"})

    res = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res.status_code == 200
    data = res.json()

    # credits_total should remain 45
    assert data.get("credits_total") == 45
    # credits_pending should be 30 (scene 4 and scene 5)
    assert data.get("credits_pending") == 30

    scene_entries = data.get("scenes", [])
    sc3 = next(s for s in scene_entries if s["scene_n"] == 3)
    sc4 = next(s for s in scene_entries if s["scene_n"] == 4)
    sc5 = next(s for s in scene_entries if s["scene_n"] == 5)

    assert sc3.get("has_live_asset") is True
    assert sc4.get("has_live_asset") is False
    assert sc5.get("has_live_asset") is False


def test_estimate_with_failed_or_cancelled_job(authenticated_client, sample_frame_zero):
    """
    2. Job failed o cancelled -> la fila cuenta como pendiente (has_live_asset: False).
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p64_estimate_failed"

    scenes = make_5_scenes_3_non_aroll()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    job_failed = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_image",
        credits=15,
        cost_usd=0.0336,
        input={"visual_prompt": "test prompt 1"},
        idempotency_key=f"{session_token}:{idea_id}:3:ai_image_failed",
    )
    mark_failed(job_failed["id"], error="Timeout error")

    job_cancelled = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=4,
        kind="ai_image",
        credits=15,
        cost_usd=0.0336,
        input={"visual_prompt": "test prompt 2"},
        idempotency_key=f"{session_token}:{idea_id}:4:ai_image_cancelled",
    )
    mark_cancelled(job_cancelled["id"], error="Cancelled by user")

    res = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res.status_code == 200
    data = res.json()

    assert data.get("credits_pending") == 45
    scene_entries = data.get("scenes", [])
    for sc in scene_entries:
        assert sc.get("has_live_asset") is False


def test_scene_has_live_asset_shared_by_estimate_and_generate(authenticated_client, sample_frame_zero):
    """
    3. _scene_has_live_asset es la que usan /generate y /estimate:
    Comprueba que existe y que /generate con la misma situación crea exactamente los jobs
    que credits_pending promete.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p64_shared_helper"

    scenes = make_5_scenes_3_non_aroll()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    # Job done for scene 3
    job3 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=3,
        kind="ai_image",
        credits=15,
        cost_usd=0.0336,
        input={"visual_prompt": "test prompt"},
        idempotency_key=f"{session_token}:{idea_id}:3:ai_image",
    )
    mark_done(job3["id"], output={"signed_url": "http://example.com/3.png"})

    jobs_before = list_jobs(session_token, idea_id)
    assert _scene_has_live_asset(jobs_before, 3, "ai_image") is True
    assert _scene_has_live_asset(jobs_before, 4, "ai_image") is False

    res_est = authenticated_client.get(f"/api/audiovisual/{idea_id}/estimate")
    assert res_est.status_code == 200
    est_pending = res_est.json().get("credits_pending")
    assert est_pending == 30

    guard._sessions[session_token]["credits"] = 500

    res_gen = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    jobs_after = gen_data.get("jobs", [])

    scene_jobs_after = [j for j in jobs_after if j.get("scene_n") in (3, 4, 5)]
    sc3_job = next(j for j in scene_jobs_after if j["scene_n"] == 3)
    sc4_job = next(j for j in scene_jobs_after if j["scene_n"] == 4)
    sc5_job = next(j for j in scene_jobs_after if j["scene_n"] == 5)

    assert sc3_job["id"] == job3["id"]
    assert sc4_job["id"] != job3["id"]
    assert sc5_job["id"] != job3["id"]
