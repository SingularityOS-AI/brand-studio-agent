"""
Unit and integration tests for PIEZA 57:
Backend: founder asset type selector, updated pricing, AI spend guard, music/sfx display, stripe env price IDs.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
    list_jobs,
    mark_done,
)
from app.audiovisual.pricing import CREDITS_TABLE, estimate
from app.audiovisual.spend_guard import can_spend, monthly_ai_spend_usd
from app.audiovisual.worker import RESOLVERS, process_one_job
from app.billing import get_package_price_id
from app.config import settings
from app.guard import guard
from app.scripting.scripts import FrameZero, Scene, Script, _save_script

TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def clean_p57_environment():
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
        sound="upbeat music",
        asset_type=asset_type,
        stock_query=stock_query,
        visual_prompt=visual_prompt,
    )


def make_5_scenes() -> list[Scene]:
    return [
        make_scene(1, "hook", "a_roll"),
        make_scene(2, "lock_in", "a_roll"),
        make_scene(3, "body_1", "stock"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "motion_graphic"),
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
        title="Test Script P57",
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


# =============================================================================
# 1. PRECIOS NUEVOS Y ESTIMATE
# =============================================================================

def test_p57_pricing_table_and_estimate(sample_frame_zero):
    """
    estimate de guion con 1 ai_image + 1 ai_video + 4 a_roll = 165 créditos, base 0.
    credits_by_type presente sin la clave base ni music_lyria.
    """
    assert CREDITS_TABLE["base"] == 0
    assert CREDITS_TABLE["ai_image"] == 15
    assert CREDITS_TABLE["ai_video"] == 150

    scenes = [
        make_scene(1, "hook", "ai_image"),
        make_scene(2, "lock_in", "ai_video"),
        make_scene(3, "body_1", "a_roll"),
        make_scene(4, "rehook", "a_roll"),
        make_scene(5, "body_2", "a_roll"),
        make_scene(6, "close_cta", "a_roll"),
    ]
    script = make_locked_script("sess_p57", "idea_p57_prices", scenes, sample_frame_zero)
    est = estimate(script)

    assert est["credits_base"] == 0
    assert est["credits_total"] == 165  # 15 + 150
    assert "credits_by_type" in est
    assert "base" not in est["credits_by_type"]
    assert "music_lyria" not in est["credits_by_type"]
    assert est["credits_by_type"]["ai_image"] == 15
    assert est["credits_by_type"]["ai_video"] == 150
    assert est["ai_paused"] is False


def test_p57_generate_base_0_no_deduct_credits(authenticated_client, sample_frame_zero):
    """
    generate con base 0 no llama a deduct_credits al lanzar.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_base0"
    scenes = make_5_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    initial_credits = guard.get_remaining_credits(session_token)

    with patch("app.guard.guard.deduct_credits") as mock_deduct:
        res = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
        assert res.status_code == 200
        mock_deduct.assert_not_called()
        assert res.json()["credits_remaining"] == initial_credits


# =============================================================================
# 2. FRENO DE GASTO REAL DE IA (SPEND_GUARD)
# =============================================================================

def test_p57_spend_guard_calculation_and_can_spend():
    """
    Suma solo AI_KINDS del mes actual con status pending/running/done.
    can_spend respeta el tope.
    """
    _reset_local_jobs()
    # Create AI jobs (cost_usd: ai_video 0.30, ai_image 0.0336)
    create_job("sess_1", "idea_1", 1, "ai_video", cost_usd=0.30)
    create_job("sess_1", "idea_1", 2, "ai_image", cost_usd=0.0336)
    create_job("sess_1", "idea_1", 3, "stock", cost_usd=0.0)  # non-AI, should be ignored

    spend = monthly_ai_spend_usd()
    assert abs(spend - 0.3336) < 1e-4

    with patch("app.audiovisual.config.AV_MONTHLY_AI_SPEND_CAP_USD", 0.50):
        assert can_spend(0.10) is True  # 0.3336 + 0.10 <= 0.50
        assert can_spend(0.20) is False  # 0.3336 + 0.20 > 0.50


def test_p57_spend_guard_fail_closed():
    """can_spend devuelve False (fail-closed) cuando la consulta/calculo lanza."""
    with patch("app.audiovisual.spend_guard.monthly_ai_spend_usd", side_effect=RuntimeError("DB disconnect")):
        assert can_spend(0.01) is False


def test_p57_spend_guard_paused_503_in_generate_and_regenerate(authenticated_client, sample_frame_zero):
    """
    generate y regenerate con IA -> 503 ai_paused sin crear jobs cuando el tope se supera.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_paused"
    scenes = make_5_scenes()
    scenes[0] = make_scene(1, "hook", "ai_video")
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero)
    _save_script(script)

    with patch("app.audiovisual.spend_guard.can_spend", return_value=False):
        res_gen = authenticated_client.post(f"/api/audiovisual/{idea_id}/generate")
        assert res_gen.status_code == 503
        data_gen = res_gen.json()
        assert data_gen["code"] == "ai_paused"
        assert "AI generation is paused right now" in data_gen["error"]
        assert len(list_jobs(session_token, idea_id)) == 0

        res_regen = authenticated_client.post(f"/api/audiovisual/{idea_id}/scenes/1/regenerate")
        assert res_regen.status_code == 503
        data_regen = res_regen.json()
        assert data_regen["code"] == "ai_paused"


@pytest.mark.asyncio
async def test_p57_worker_marks_failed_when_spend_cap_exceeded():
    """
    worker process_one_job: si monthly_ai_spend_usd() > cap -> marca failed sin llamar al resolver ni cobrar.
    """
    session_token = guard.create_user_session("user_p57_worker", initial_credits=100)
    job = create_job(
        session_token=session_token,
        idea_id="idea_worker_cap",
        scene_n=1,
        kind="ai_video",
        credits=150,
        cost_usd=0.30,
    )

    mock_resolver = AsyncMock()
    RESOLVERS["ai_video"] = mock_resolver

    with patch("app.audiovisual.spend_guard.monthly_ai_spend_usd", return_value=25.0):
        with patch("app.audiovisual.config.AV_MONTHLY_AI_SPEND_CAP_USD", 20.0):
            claimed = await process_one_job()
            assert claimed is True
            mock_resolver.assert_not_called()
            updated_job = get_job(job["id"])
            assert updated_job["status"] == "failed"
            assert "AI generation paused (platform spend limit)" in updated_job["error"]
            assert updated_job["charged"] is False


# =============================================================================
# 3. PATCH ASSET_TYPE (DECISIÓN D1)
# =============================================================================

def test_p57_patch_asset_type_validations(authenticated_client, sample_frame_zero):
    """
    PATCH asset_type validation tests:
    - 409 if not locked
    - 422 if invalid asset_type
    - 422 if adding second ai_video
    - 409 if job in flight
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_patch_val"

    # 1. Draft script -> 409
    scenes = make_5_scenes()
    script_draft = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="draft")
    _save_script(script_draft)

    res_draft = authenticated_client.patch(
        f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
        json={"asset_type": "stock"},
    )
    assert res_draft.status_code == 409

    # 2. Locked script -> invalid type 422
    script_locked = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script_locked)

    res_invalid = authenticated_client.patch(
        f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
        json={"asset_type": "invalid_kind"},
    )
    assert res_invalid.status_code == 422

    # 3. Second ai_video -> 422
    scenes_with_aivid = make_5_scenes()
    scenes_with_aivid[0] = make_scene(1, "hook", "ai_video")
    scenes_with_aivid[1] = make_scene(2, "lock_in", "stock")
    script_aivid = make_locked_script(session_token, idea_id, scenes_with_aivid, sample_frame_zero, state="locked")
    _save_script(script_aivid)

    res_sec_vid = authenticated_client.patch(
        f"/api/audiovisual/{idea_id}/scenes/2/asset_type",
        json={"asset_type": "ai_video"},
    )
    assert res_sec_vid.status_code == 422
    assert "Only 1 AI video per script" in res_sec_vid.json()["error"]

    # 4. Job in flight -> 409
    create_job(session_token, idea_id, scene_n=2, kind="stock")
    res_flight = authenticated_client.patch(
        f"/api/audiovisual/{idea_id}/scenes/2/asset_type",
        json={"asset_type": "ai_image"},
    )
    assert res_flight.status_code == 409
    assert "Wait for it to finish" in res_flight.json()["error"]


def test_p57_patch_asset_type_llm_prompt_and_suggested_asset_type(authenticated_client, sample_frame_zero):
    """
    PATCH asset_type stock -> ai_image:
    - calls LLM (mocked) when visual_prompt is missing
    - stores suggested_asset_type with original asset type only on first change
    - script remains locked
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_patch_llm"
    scenes = make_5_scenes()
    scenes[0] = make_scene(1, "hook", "stock", stock_query="digital transformation office")
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    mock_resp = MagicMock()
    mock_resp.text = '"Cinematic vertical shot of AI hologram in modern studio"'

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("app.audiovisual.genai_client.get_genai_client", return_value=mock_client):
        res = authenticated_client.patch(
            f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
            json={"asset_type": "ai_image"},
        )
        assert res.status_code == 200
        data = res.json()
        sc_data = data["scene"]
        assert sc_data["asset_type"] == "ai_image"
        assert sc_data["suggested_asset_type"] == "stock"
        assert sc_data["visual_prompt"] == "Cinematic vertical shot of AI hologram in modern studio"

    # Second change to motion_graphic: suggested_asset_type remains original 'stock'
    res2 = authenticated_client.patch(
        f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
        json={"asset_type": "motion_graphic"},
    )
    assert res2.status_code == 200
    assert res2.json()["scene"]["suggested_asset_type"] == "stock"


def test_p57_patch_asset_type_llm_failure_uses_deterministic_fallback(authenticated_client, sample_frame_zero):
    """
    LLM generation raising exception -> uses deterministic fallback without failing request.
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_patch_fallback"
    scenes = make_5_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    with patch("app.audiovisual.genai_client.get_genai_client", side_effect=RuntimeError("GenAI client error")):
        res = authenticated_client.patch(
            f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
            json={"asset_type": "ai_image"},
        )
        assert res.status_code == 200
        sc = res.json()["scene"]
        assert sc["asset_type"] == "ai_image"
        assert "cinematic, vertical 9:16" in sc["visual_prompt"]


def test_p57_patch_asset_type_llm_async_timeout_uses_fallback(authenticated_client, sample_frame_zero):
    """
    LLM client.aio.models.generate_content raising asyncio.TimeoutError -> PATCH responds 200 with fallback prompt.
    """
    import asyncio
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_patch_timeout"
    scenes = make_5_scenes()
    script = make_locked_script(session_token, idea_id, scenes, sample_frame_zero, state="locked")
    _save_script(script)

    async def mock_never_finish(*args, **kwargs):
        raise asyncio.TimeoutError()

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_never_finish

    with patch("app.audiovisual.genai_client.get_genai_client", return_value=mock_client):
        res = authenticated_client.patch(
            f"/api/audiovisual/{idea_id}/scenes/1/asset_type",
            json={"asset_type": "ai_image"},
        )
        assert res.status_code == 200
        sc = res.json()["scene"]
        assert sc["asset_type"] == "ai_image"
        assert "cinematic, vertical 9:16" in sc["visual_prompt"]


# =============================================================================
# 4. JOBS ENDPOINT OUTPUT_DISPLAY
# =============================================================================

def test_p57_jobs_endpoint_output_display(authenticated_client):
    """
    GET /api/audiovisual/{idea_id}/jobs:
    - music done job with track_file adds output_display {title, author, mood, energy, reason}
    - sfx job adds output_display {tag, title}
    """
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p57_display"

    music_job = create_job(session_token, idea_id, scene_n=None, kind="music")
    mark_done(
        music_job["id"],
        output={
            "track_file": "ambient_drive.mp3",
            "mood": "calm",
            "energy": "low",
            "reason": "Calm atmosphere",
        },
    )

    sfx_job = create_job(
        session_token,
        idea_id,
        scene_n=1,
        kind="sfx",
        input={"sfx_file": "whoosh_01.mp3", "tag": "whoosh"},
    )
    mark_done(sfx_job["id"], output={"file": "whoosh_01.mp3", "tag": "whoosh"})

    mock_music_manifest = [{"file": "ambient_drive.mp3", "title": "Ambient Drive", "author": "Studio Pro"}]
    mock_sfx_manifest = [{"file": "whoosh_01.mp3", "title": "Fast Whoosh", "tags": ["whoosh"]}]

    with patch("app.audiovisual.music.load_music_library", return_value=mock_music_manifest):
        with patch("app.audiovisual.sfx.load_sfx_library", return_value=mock_sfx_manifest):
            res = authenticated_client.get(f"/api/audiovisual/{idea_id}/jobs")
            assert res.status_code == 200
            jobs = res.json()["jobs"]
            m_job = next(j for j in jobs if j["kind"] == "music")
            s_job = next(j for j in jobs if j["kind"] == "sfx")

            assert m_job["output_display"] == {
                "title": "Ambient Drive",
                "author": "Studio Pro",
                "mood": "calm",
                "energy": "low",
                "reason": "Calm atmosphere",
            }
            assert s_job["output_display"] == {
                "tag": "whoosh",
                "title": "Fast Whoosh",
            }


# =============================================================================
# 5. STRIPE BILLING PRICE IDS BY ENV VAR
# =============================================================================

def test_p57_stripe_billing_env_price_ids(monkeypatch):
    """
    - sin env + sk_test_ -> price de test
    - env set -> usa la env var
    - sin env + sk_live_ -> error 400 Package not configured
    """
    # 1. Test key, no env var -> returns test default
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock_key_123")
    monkeypatch.delenv("STRIPE_PRICE_STARTER", raising=False)
    price_starter_test = get_package_price_id("starter")
    assert price_starter_test == "price_1UEbb70StQbwtwVc8mTCMm4Q"

    # 2. Test key with env var -> returns env value
    monkeypatch.setenv("STRIPE_PRICE_STARTER", "price_env_custom_starter")
    price_starter_env = get_package_price_id("starter")
    assert price_starter_env == "price_env_custom_starter"

    # 3. Live key without env var -> raises 400 "Package not configured"
    monkeypatch.delenv("STRIPE_PRICE_PRO", raising=False)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_production_key_456")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        get_package_price_id("pro")
    assert exc_info.value.status_code == 400
    assert "Package not configured" in exc_info.value.detail
