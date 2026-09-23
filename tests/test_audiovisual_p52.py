"""
Unit and integration tests for PIEZA 52:
Stock (Pexels -> Pixabay) + Música decidida por IA + SFX locales.

Verifica:
1. Pexels con resultado vertical -> done con output completo (0 creditos).
2. Pexels vacio o error -> cae a Pixabay con exito.
3. Sin claves configuradas -> failed claro ('No stock found for ...'), 0 creditos.
4. Decision de musica por IA validada y clampeada (volumen 0.05 - 0.40, mood permitido).
5. Biblioteca vacia + Lyria apagado (default) -> use_music: false, reason claro, 0 cobro.
6. Biblioteca vacia + Lyria encendido (AV_ALLOW_LYRIA=true) -> NotImplementedError (TODO P53).
7. Biblioteca con pistas -> selecciona por mood, energy y duracion.
8. pick_sfx por fase (rehook -> riser, close_cta -> ding) y palabras clave (whoosh, pop).
9. Resolver sfx resuelve de inmediato (done, 0 creditos).
10. Las claves de API nunca aparecen en logs ni en job output.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
)
from app.audiovisual.music import (
    _clamp_music_decision,
    resolve_music,
)
from app.audiovisual.sfx import pick_sfx
from app.audiovisual.stock import _clear_stock_cache
from app.audiovisual.worker import (
    RESOLVERS,
    process_one_job,
    register_default_resolvers,
)
from app.config import settings
from app.guard import guard
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _save_script,
)


@pytest.fixture(autouse=True)
def reset_audiovisual_state():
    """Reset jobs, resolvers, sessions, stock cache, and script mocks for clean test isolation."""
    _reset_local_jobs()
    RESOLVERS.clear()
    register_default_resolvers()
    guard._sessions.clear()
    _clear_stock_cache()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()
    _clear_stock_cache()


@pytest.fixture
def mock_session():
    token = "sess_p52_test_token"
    guard._sessions[token] = {
        "created_at": 1000.0,
        "last_activity": 1000.0,
        "initial_credits": 200,
        "remaining_credits": 200,
        "ip": "127.0.0.1",
        "email": "test@singularityos.com",
    }
    return token


def make_scene(
    n: int,
    phase: str,
    asset_type: str = "stock",
    sound: str = "light background hum",
    spoken_text: str = "Founder explaining the market gap.",
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken_text,
        shot="medium shot",
        b_roll=None,
        on_screen_text=f"Scene {n} key point",
        acting_note="Confident delivery",
        sound=sound,
        asset_type=asset_type,
        stock_query="futuristic tech office" if asset_type == "stock" else None,
        visual_prompt=None,
    )


def make_locked_script(session_id: str, idea_id: str, scenes: list[Scene] | None = None) -> Script:
    sc_list = scenes or [
        make_scene(1, "hook", "a_roll", sound="silence"),
        make_scene(2, "lock_in", "stock", sound="ambient office"),
        make_scene(3, "body_1", "stock", sound="pop sound effect"),
        make_scene(4, "rehook", "stock", sound="rising tension"),
        make_scene(5, "body_2", "motion_graphic", sound="whoosh transition"),
        make_scene(6, "close_cta", "a_roll", sound="notification chime"),
    ]
    script = Script(
        session_id=session_id,
        idea_id=idea_id,
        title="Scaling Without Spaghetti",
        angle="How modular architecture eliminates technical debt",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=FrameZero(
            visual="Founder at desk looking at screen",
            on_screen_text="Stop coding spaghetti",
            why_it_stops_the_scroll="Relatable developer dilemma",
        ),
        scenes=sc_list,
        state="locked",
        music_prompt="modern corporate ambient beats",
        recording_format="selfie_natural",
    )
    _save_script(script)
    return script


# ---------------------------------------------------------------------------
# 1. STOCK RESOLVER TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stock_pexels_vertical_success():
    """Pexels with vertical result -> done with complete output payload, 0 credits."""
    pexels_response_payload = {
        "page": 1,
        "per_page": 10,
        "videos": [
            {
                "id": 855234,
                "width": 1080,
                "height": 1920,
                "duration": 12,
                "url": "https://www.pexels.com/video/855234/",
                "image": "https://images.pexels.com/videos/855234/preview.jpg",
                "user": {"name": "Alex Tech", "url": "https://www.pexels.com/@alex"},
                "video_files": [
                    {
                        "id": 1,
                        "quality": "hd",
                        "width": 1080,
                        "height": 1920,
                        "link": "https://videos.pexels.com/video-files/855234/1080p.mp4",
                    },
                    {
                        "id": 2,
                        "quality": "sd",
                        "width": 720,
                        "height": 1280,
                        "link": "https://videos.pexels.com/video-files/855234/720p.mp4",
                    },
                ],
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = pexels_response_payload

    with patch.object(settings, "pexels_api_key", "valid_pexels_key_123"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            job = create_job(
                session_token="sess_1",
                idea_id="idea_1",
                scene_n=1,
                kind="stock",
                credits=0,
                input={"stock_query": "futuristic tech office", "duration_s": 5.0},
            )

            success = await process_one_job()
            assert success is True

            updated = get_job(job["id"])
            assert updated["status"] == "done"
            assert updated["credits"] == 0
            out = updated["output"]
            assert out["provider"] == "pexels"
            assert out["source_id"] == "855234"
            assert out["preview_url"] == "https://images.pexels.com/videos/855234/preview.jpg"
            assert out["video_url"] == "https://videos.pexels.com/video-files/855234/1080p.mp4"
            assert out["width"] == 1080
            assert out["height"] == 1920
            assert out["duration_s"] == 12.0
            assert out["author"] == "Alex Tech"
            assert out["author_url"] == "https://www.pexels.com/@alex"
            assert out["license"] == "Pexels License"
            assert out["page_url"] == "https://www.pexels.com/video/855234/"
            assert out["attribution_text"] == "Video by Alex Tech on Pexels"


@pytest.mark.asyncio
async def test_stock_pexels_empty_falls_back_to_pixabay():
    """When Pexels returns 0 videos, resolver falls back to Pixabay."""
    pixabay_response_payload = {
        "total": 1,
        "hits": [
            {
                "id": 998877,
                "pageURL": "https://pixabay.com/videos/tech-office-998877/",
                "duration": 8,
                "user": "PixelMaster",
                "picture_id": "123456",
                "videos": {
                    "medium": {
                        "url": "https://cdn.pixabay.com/video/medium.mp4",
                        "width": 1080,
                        "height": 1920,
                        "thumbnail": "https://cdn.pixabay.com/video/thumb.jpg",
                    }
                },
            }
        ],
    }

    mock_pexels_resp = MagicMock()
    mock_pexels_resp.status_code = 200
    mock_pexels_resp.json.return_value = {"videos": []}

    mock_pixabay_resp = MagicMock()
    mock_pixabay_resp.status_code = 200
    mock_pixabay_resp.json.return_value = pixabay_response_payload

    with patch.object(settings, "pexels_api_key", "key_pexels"):
        with patch.object(settings, "pixabay_api_key", "key_pixabay"):
            with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()

                def _get_side_effect(url, *args, **kwargs):
                    if "pexels.com" in url:
                        return mock_pexels_resp
                    return mock_pixabay_resp

                mock_client.get.side_effect = _get_side_effect
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=2,
                    kind="stock",
                    credits=0,
                    input={"stock_query": "tech office coding", "duration_s": 6.0},
                )

                success = await process_one_job()
                assert success is True

                updated = get_job(job["id"])
                assert updated["status"] == "done"
                out = updated["output"]
                assert out["provider"] == "pixabay"
                assert out["source_id"] == "998877"
                assert out["license"] == "Pixabay Content License"
                assert out["video_url"] == "https://cdn.pixabay.com/video/medium.mp4"
                assert out["author"] == "PixelMaster"
                assert out["attribution_text"] == "Video by PixelMaster on Pixabay"
                assert out["page_url"] == "https://pixabay.com/videos/tech-office-998877/"


@pytest.mark.asyncio
async def test_stock_no_keys_fails_clearly():
    """If neither key is configured, stock job fails clearly with 0 credits."""
    with patch.object(settings, "pexels_api_key", ""):
        with patch.object(settings, "pixabay_api_key", ""):
            job = create_job(
                session_token="sess_1",
                idea_id="idea_1",
                scene_n=3,
                kind="stock",
                credits=0,
                input={"stock_query": "cyberpunk city"},
            )

            success = await process_one_job()
            assert success is True

            updated = get_job(job["id"])
            assert updated["status"] == "failed"
            assert "No stock found for 'cyberpunk city'" in updated["error"]
            assert updated["charged"] is False
            assert updated["credits"] == 0


@pytest.mark.asyncio
async def test_stock_keys_never_logged_or_in_output(caplog):
    """API keys must NEVER appear in output payload or in logs."""
    secret_pexels = "PEXELS_SUPER_SECRET_TOKEN_999"
    secret_pixabay = "PIXABAY_SUPER_SECRET_TOKEN_888"

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"error": "unauthorized"}

    with patch.object(settings, "pexels_api_key", secret_pexels):
        with patch.object(settings, "pixabay_api_key", secret_pixabay):
            with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_resp
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=1,
                    kind="stock",
                    credits=0,
                    input={"stock_query": "private security bunker"},
                )

                await process_one_job()
                updated = get_job(job["id"])

                out_str = json.dumps(updated)
                assert secret_pexels not in out_str
                assert secret_pixabay not in out_str
                assert secret_pexels not in caplog.text
                assert secret_pixabay not in caplog.text


# ---------------------------------------------------------------------------
# 2. MUSIC RESOLVER & AI DECISION TESTS
# ---------------------------------------------------------------------------

def test_music_decision_clamping():
    """Music decision validator clamps volume between 0.05 and 0.40 and restricts mood."""
    # 1. Volume too high (> 0.40) clamped to 0.40
    clamped_high = _clamp_music_decision({"volume": 0.85, "mood": "upbeat", "energy": "high"})
    assert clamped_high["volume"] == 0.40
    assert clamped_high["mood"] == "upbeat"
    assert clamped_high["energy"] == "high"

    # 2. Volume too low (< 0.05) clamped to 0.05
    clamped_low = _clamp_music_decision({"volume": 0.01, "mood": "calm", "energy": "low"})
    assert clamped_low["volume"] == 0.05

    # 3. Invalid mood and energy fallback to calm and mid
    clamped_invalid = _clamp_music_decision({"mood": "heavy_metal", "energy": "extreme"})
    assert clamped_invalid["mood"] == "calm"
    assert clamped_invalid["energy"] == "mid"


@pytest.mark.asyncio
async def test_music_empty_library_lyria_disabled_no_music_zero_charge():
    """Empty library + Lyria disabled (default) -> use_music: false, reason, 0 charge."""
    mock_ai_resp = MagicMock()
    mock_ai_resp.text = json.dumps({
        "use_music": True,
        "mood": "inspiring",
        "energy": "mid",
        "volume": 0.20,
        "reason": "Inspiring mood enhances the business journey narrative",
    })

    with patch("vertexai.generative_models.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_ai_resp)
        mock_model_cls.return_value = mock_model

        with patch("app.audiovisual.music.load_music_library", return_value=[]):
            with patch("app.audiovisual.music.AV_ALLOW_LYRIA", False):
                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=None,
                    kind="music",
                    credits=0,
                    input={"music_prompt": "inspiring synth", "duration_s": 50.0},
                )

                success = await process_one_job()
                assert success is True

                updated = get_job(job["id"])
                assert updated["status"] == "done"
                assert updated["credits"] == 0
                out = updated["output"]
                assert out["use_music"] is False
                assert out["mood"] == "inspiring"
                assert "no library track for mood inspiring" in out["reason"]
                assert out["storage_path"] is None


@pytest.mark.asyncio
async def test_music_empty_library_lyria_enabled_raises_not_implemented():
    """Empty library + Lyria enabled -> raises NotImplementedError behind flag (TODO P53)."""
    mock_ai_resp = MagicMock()
    mock_ai_resp.text = json.dumps({
        "use_music": True,
        "mood": "calm",
        "energy": "low",
        "volume": 0.15,
        "reason": "Calm atmosphere",
    })

    with patch("vertexai.generative_models.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_ai_resp)
        mock_model_cls.return_value = mock_model

        with patch("app.audiovisual.music.load_music_library", return_value=[]):
            with patch("app.audiovisual.music.AV_ALLOW_LYRIA", True):
                with pytest.raises(NotImplementedError, match="Lyria music generation is not implemented yet"):
                    await resolve_music({
                        "input": {"music_prompt": "ambient", "duration_s": 30.0}
                    })


@pytest.mark.asyncio
async def test_music_track_selected_from_library():
    """When library has matching track, resolver selects by mood, energy, and duration."""
    mock_tracks = [
        {
            "file": "calm_ambient_30s.mp3",
            "mood": "calm",
            "energy": "low",
            "duration_s": 30.0,
            "source": "ceo_vault",
            "license": "Custom",
        },
        {
            "file": "upbeat_energetic_60s.mp3",
            "mood": "upbeat",
            "energy": "high",
            "duration_s": 60.0,
            "source": "ceo_vault",
            "license": "Custom",
        },
    ]

    mock_ai_resp = MagicMock()
    mock_ai_resp.text = json.dumps({
        "use_music": True,
        "mood": "upbeat",
        "energy": "high",
        "volume": 0.25,
        "reason": "High energy hook matches fast pace",
    })

    with patch("vertexai.generative_models.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_ai_resp)
        mock_model_cls.return_value = mock_model

        with patch("app.audiovisual.music.load_music_library", return_value=mock_tracks):
            with patch("app.audiovisual.storage.signed_url", return_value="https://supabase.co/storage/music/upbeat.mp3"):
                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=None,
                    kind="music",
                    credits=0,
                    input={"music_prompt": "upbeat tech electronic", "duration_s": 45.0},
                )

                await process_one_job()
                updated = get_job(job["id"])
                assert updated["status"] == "done"
                out = updated["output"]
                assert out["use_music"] is True
                assert out["mood"] == "upbeat"
                assert out["energy"] == "high"
                assert out["volume"] == 0.25
                assert out["track_file"] == "upbeat_energetic_60s.mp3"
                assert out["storage_path"] == "library/music/upbeat_energetic_60s.mp3"


# ---------------------------------------------------------------------------
# 3. SFX RESOLVER & SELECTOR TESTS
# ---------------------------------------------------------------------------

def test_pick_sfx_by_phase_and_keywords():
    """pick_sfx selects local sound effects by keywords and phase heuristics."""
    mock_sfx_library = [
        {"file": "whoosh_fast.mp3", "tags": ["whoosh", "swoosh", "transition"]},
        {"file": "riser_tension.mp3", "tags": ["riser", "tension"]},
        {"file": "bell_ding.mp3", "tags": ["ding", "chime", "notification"]},
        {"file": "bubble_pop.mp3", "tags": ["pop", "click"]},
    ]

    with patch("app.audiovisual.sfx.load_sfx_library", return_value=mock_sfx_library):
        # 1. Rehook phase -> riser
        sfx_rehook = pick_sfx({"phase": "rehook", "sound": "light drone"})
        assert sfx_rehook is not None
        assert sfx_rehook["tag"] == "riser"
        assert sfx_rehook["file"] == "riser_tension.mp3"

        # 2. Close CTA phase -> ding
        sfx_cta = pick_sfx({"phase": "close_cta", "sound": "outro"})
        assert sfx_cta is not None
        assert sfx_cta["tag"] == "ding"
        assert sfx_cta["file"] == "bell_ding.mp3"

        # 3. Sound mentions whoosh transition
        sfx_whoosh = pick_sfx({"phase": "body_1", "sound": "quick whoosh into graph"})
        assert sfx_whoosh is not None
        assert sfx_whoosh["tag"] == "whoosh"
        assert sfx_whoosh["file"] == "whoosh_fast.mp3"

        # 4. Sound mentions pop
        sfx_pop = pick_sfx({"phase": "body_2", "sound": "pop text bubble"})
        assert sfx_pop is not None
        assert sfx_pop["tag"] == "pop"
        assert sfx_pop["file"] == "bubble_pop.mp3"

        # 5. Empty library -> None
        with patch("app.audiovisual.sfx.load_sfx_library", return_value=[]):
            assert pick_sfx({"phase": "rehook", "sound": "riser"}) is None


@pytest.mark.asyncio
async def test_sfx_resolver_immediate_resolution():
    """SFX resolver resolves immediately with storage_path and 0 credits."""
    with patch("app.audiovisual.storage.signed_url", return_value="https://supabase.co/storage/sfx/whoosh.mp3"):
        job = create_job(
            session_token="sess_1",
            idea_id="idea_1",
            scene_n=2,
            kind="sfx",
            credits=0,
            input={
                "sfx_file": "whoosh_fast.mp3",
                "tag": "whoosh",
                "storage_path": "library/sfx/whoosh_fast.mp3",
            },
        )

        success = await process_one_job()
        assert success is True

        updated = get_job(job["id"])
        assert updated["status"] == "done"
        assert updated["credits"] == 0
        out = updated["output"]
        assert out["file"] == "whoosh_fast.mp3"
        assert out["storage_path"] == "library/sfx/whoosh_fast.mp3"
        assert out["signed_url"] == "https://supabase.co/storage/sfx/whoosh.mp3"
        assert out["tag"] == "whoosh"


# ---------------------------------------------------------------------------
# 4. GENERATE ENDPOINT INTEGRATION (PIEZA 52)
# ---------------------------------------------------------------------------

def test_generate_endpoint_enqueues_music_and_sfx(authenticated_client):
    """POST /api/audiovisual/{idea_id}/generate creates music job with rich blueprint input and SFX jobs."""
    session_token = authenticated_client._test_session_token
    idea_id = "idea_p52_test"
    make_locked_script(session_token, idea_id)

    mock_sfx_lib = [
        {"file": "riser.mp3", "tags": ["riser"]},
        {"file": "ding.mp3", "tags": ["ding"]},
    ]

    with patch("app.audiovisual.sfx.load_sfx_library", return_value=mock_sfx_lib):
        resp = authenticated_client.post(
            f"/api/audiovisual/{idea_id}/generate",
        )
        assert resp.status_code == 200
        data = resp.json()
        jobs = data.get("jobs", [])

        # Verify music job has angle, phases, recording_format, and music_prompt
        music_jobs = [j for j in jobs if j.get("kind") == "music"]
        assert len(music_jobs) == 1
        m_job = music_jobs[0]
        assert m_job["input"]["music_prompt"] == "modern corporate ambient beats"
        assert m_job["input"]["angle"] == "How modular architecture eliminates technical debt"
        assert "hook" in m_job["input"]["phases"]
        assert m_job["input"]["recording_format"] == "selfie_natural"

        # Verify SFX jobs created for scenes matching tags (rehook -> riser, close_cta -> ding)
        sfx_jobs = [j for j in jobs if j.get("kind") == "sfx"]
        assert len(sfx_jobs) >= 2
        rehook_sfx = [j for j in sfx_jobs if j.get("scene_n") == 4]
        assert len(rehook_sfx) == 1
        assert rehook_sfx[0]["input"]["tag"] == "riser"
