"""
Tests for Pieza 43 — Backend audit fixes (Block C scripting).

Independent audit findings fixed here (see spec handed to the implementer):
1. Regeneration persisted unvalidated Gemini output -> script vanished on
   next load. Fixed by building + fully validating the regenerated scene
   BEFORE mutating or saving anything (_build_validated_scene).
2. Invented 50-char limit on on_screen_text (FrameZero + Scene) removed --
   the signed rule is <= 8 words.
3. Credits charged only after a successful, validated, saved result; a
   clean error message on invalid output, not a raw Pydantic trace.
4. Concurrency: per-(session_id, idea_id) asyncio.Lock serializes mutations
   and re-reads the latest script inside the lock; a duplicate in-flight
   regeneration of the SAME scene is rejected (409), not double-charged.
5. Manual edit (update_scene_text) recomputes the edited scene's estimated
   duration and reflows every later scene.
"""
import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.guard import guard
from app.main import app
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    SceneRegenerationInProgressError,
    _check_script,
    _save_script,
    generate_script,
    regenerate_scene,
    update_scene_text,
)


# =============================================================================
# FIXTURES (module-local, same pattern as the other test_scripts_piezaNN.py files)
# =============================================================================

@pytest.fixture
def test_user_id():
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def api_client(test_user_id):
    """TestClient contra la app real, con auth mockeada (mismo patrón que los demás)."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch('app.auth.supabase_auth.supabase_auth.get_user_id', return_value=test_user_id):
        with patch.object(guard, 'get_or_create_user_session', return_value='test_session'):
            yield client


@pytest.fixture
def valid_frame_zero():
    return FrameZero(
        visual="Founder staring at endless spreadsheets, clearly frustrated",
        on_screen_text="Still doing this?",
        why_it_stops_the_scroll="Relatable frustration stops scroll instantly",
    )


@pytest.fixture
def valid_scenes():
    """6 valid scenes covering all required phases."""
    return [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="You're still doing this manually? Let me show you a better way.",
              shot="medium shot", b_roll=None, on_screen_text="Stop the manual work",
              acting_note="Lean in slightly, empathetic tone", sound="upbeat synth"),
        Scene(n=2, start_s=3.0, end_s=7.0, phase="lock_in",
              spoken_text="This problem affects most teams every single week.",
              shot="medium", b_roll=None, on_screen_text="Affects most teams",
              acting_note="Serious tone", sound="test"),
        Scene(n=3, start_s=7.0, end_s=11.0, phase="body_1",
              spoken_text="Our AI reduces errors with a citation right here.",
              shot="medium", b_roll=None, on_screen_text="Reduces errors",
              acting_note="Confident tone", sound="test"),
        Scene(n=4, start_s=11.0, end_s=14.0, phase="rehook",
              spoken_text="But here's what makes us different.",
              shot="medium", b_roll=None, on_screen_text="Different approach",
              acting_note="Pause for emphasis", sound="test"),
        Scene(n=5, start_s=14.0, end_s=18.0, phase="body_2",
              spoken_text="Real-time analytics show clear ROI with a citation.",
              shot="medium", b_roll=None, on_screen_text="Clear ROI",
              acting_note="Excited tone", sound="test"),
        Scene(n=6, start_s=18.0, end_s=22.0, phase="close_cta",
              spoken_text="Try it free today.",
              shot="medium", b_roll=None, on_screen_text="Start now",
              acting_note="Direct gaze", sound="test"),
    ]


@pytest.fixture
def valid_script(valid_frame_zero, valid_scenes):
    return Script(
        session_id="test_session",
        idea_id="idea_123",
        title="Stop Wasting 10 Hours/Week on Spreadsheets",
        angle="Opens with manual work frustration, narrows to AI solution",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=valid_frame_zero,
        scenes=valid_scenes,
        sources=["Test source"],
    )


@pytest.fixture
def mock_brand_brain():
    from app.tools.brand_brain.models import BrandBrain, Section

    sections = [
        Section(
            id="diagnostico", label="Diagnostico", status="confirmado",
            content={"niche": "SaaS for SMBs"},
            citation_text="CEO said: manual data entry", citation_source="usuario",
        ),
    ]
    return BrandBrain(sections=sections)


@pytest.fixture
def mock_catalog():
    from app.catalog.demand import NicheResearch
    from app.catalog.ideas import Catalog, CatalogIdea

    return Catalog(
        session_id="test_session",
        niche="SaaS for SMBs",
        ideas=[
            CatalogIdea(
                id="idea_123",
                master_category="autoridad_tecnica",
                subcategory="Top N/Listículo técnico",
                title="Stop Wasting Time",
                demand_signal="High demand",
                status="approved",
            )
        ],
        catalog_locked=True,
        niche_research=NicheResearch(
            niche="SaaS", trend_direction="alta", youtube_channels=10,
            avg_views=50000, search_volume=5000,
        ),
    )


# =============================================================================
# ITEM 1 + 2: regeneration validates BEFORE saving; no invented char limit
# =============================================================================

@pytest.mark.asyncio
async def test_regenerate_scene_52_char_8_word_subtitle_succeeds_and_script_still_loads(
    valid_script, tmp_path
):
    """
    Audit repro: on_screen_text "Automation saves your front desk twenty
    hours weekly" is 8 words / 52 chars. The signed rule is words, not
    chars -- this must succeed, and the script must still load afterward
    (the exact symptom of the bug: it used to vanish on next load).
    """
    os.chdir(tmp_path)
    subtitle = "Automation saves your front desk twenty hours weekly"
    assert len(subtitle) == 54 or len(subtitle) > 50  # definitely over the old invented limit
    assert len(subtitle.split()) == 8  # but within the real, signed rule

    mock_response = Mock()
    mock_response.text = json.dumps({
        "spoken_text": "Automation now saves your front desk real hours every single week",
        "shot": "close-up",
        "b_roll": None,
        "on_screen_text": subtitle,
        "acting_note": "Confident, direct address, slow down on 'automation'",
        "sound": "upbeat",
    })

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:
        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        _save_script(valid_script)

        result = await regenerate_scene(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            instruction="make it punchier",
        )

    assert result.scenes[0].on_screen_text == subtitle

    # The exact symptom being fixed: the script must still load.
    reloaded = _check_script(valid_script.session_id, valid_script.idea_id)
    assert reloaded is not None, "Script vanished after regeneration -- Pieza 43 bug reintroduced"
    assert reloaded.scenes[0].on_screen_text == subtitle


@pytest.mark.asyncio
async def test_regenerate_scene_invalid_output_saves_nothing_and_script_still_loads(
    valid_script, tmp_path
):
    """
    Audit repro (truly invalid output): on_screen_text with 11 words is
    invalid under the REAL rule. This must raise, save nothing, and leave
    the previously-saved script exactly as it was (still loadable).
    """
    os.chdir(tmp_path)
    original_spoken_text = valid_script.scenes[0].spoken_text
    original_on_screen_text = valid_script.scenes[0].on_screen_text

    mock_response = Mock()
    mock_response.text = json.dumps({
        "spoken_text": "This part is fine.",
        "shot": "close-up",
        "b_roll": None,
        "on_screen_text": "This on screen text has way more than eight words total here",  # 12 words
        "acting_note": "Confident tone",
        "sound": "upbeat",
    })

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:
        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        _save_script(valid_script)

        with pytest.raises(ValueError) as exc:
            await regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=1,
                instruction="whatever",
            )

    # Clean, single-line message -- not a raw multi-line Pydantic dump.
    message = str(exc.value)
    assert "\n" not in message
    assert "scene 1" in message.lower()

    # Nothing saved: reload shows the ORIGINAL, unmodified scene.
    reloaded = _check_script(valid_script.session_id, valid_script.idea_id)
    assert reloaded is not None
    assert reloaded.scenes[0].spoken_text == original_spoken_text
    assert reloaded.scenes[0].on_screen_text == original_on_screen_text


def test_regenerate_endpoint_invalid_output_returns_400_and_charges_nothing(api_client):
    """
    Item 3 (endpoint wiring): when regenerate_scene raises ValueError
    (invalid/unvalidatable model output), the endpoint must return 400 with
    a clean message and must NOT deduct credits.
    """
    with patch.object(guard, 'get_session', return_value={'credits': 42}):
        with patch.object(guard, 'get_remaining_credits', return_value=42):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch(
                    'app.main.regenerate_scene',
                    new_callable=AsyncMock,
                    side_effect=ValueError(
                        "Model returned invalid data for scene 1: "
                        "on_screen_text: Value error, On-screen text must be at most 8 words, got 12"
                    ),
                ):
                    response = api_client.post(
                        '/api/script/idea_123/scene/1/regenerate',
                        json={"instruction": "shorter"},
                    )

    assert response.status_code == 400, response.text
    assert "scene 1" in response.json()["error"].lower()
    mock_deduct.assert_not_called()


# =============================================================================
# ITEM 5 (generate side): invalid model output charges nothing
# =============================================================================

@pytest.mark.asyncio
async def test_generate_script_invalid_model_output_raises_clean_error_and_saves_nothing(
    mock_brand_brain, mock_catalog, tmp_path
):
    os.chdir(tmp_path)

    mock_response = Mock()
    mock_response.text = json.dumps({
        "title": "Bad output test",
        "angle": "test angle",
        "target_seconds": 60,
        "frame_zero": {
            "visual": "Test visual",
            "on_screen_text": "Test",
            "why_it_stops_the_scroll": "Test reason",
        },
        "scenes": [
            {
                "phase": "hook",
                "spoken_text": "Hook text here",
                "shot": "medium",
                "b_roll": None,
                # 12 words -- invalid under the real rule.
                "on_screen_text": "This on screen text has way more than eight words total here",
                "acting_note": "Test note",
                "sound": "test",
            },
        ],
        "sources": ["Test source"],
    })

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_catalog_fn, \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class, \
         patch("app.scripting.scripts._get_script_client", return_value=None):
        mock_get_brain.return_value = mock_brand_brain
        mock_catalog_fn.return_value = mock_catalog

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        with pytest.raises(ValueError) as exc:
            await generate_script(
                session_id="gen_invalid_test",
                idea_id="idea_123",
                interview_transcript="Test transcript",
                source_mode="brand_brain",
            )

    message = str(exc.value)
    assert "\n" not in message, f"Expected a clean one-line error, got: {message!r}"
    assert "scene 1" in message.lower()

    # Nothing was ever saved for this session/idea.
    reloaded = _check_script("gen_invalid_test", "idea_123")
    assert reloaded is None


def test_generate_endpoint_invalid_model_output_charges_nothing(api_client):
    """
    Item 3 (endpoint wiring, generate side): an invalid Gemini response
    surfaces as 400 with a clean message and deducts NO credits.
    """
    with patch.object(guard, 'get_session', return_value={'credits': 100}):
        with patch.object(guard, 'get_remaining_credits', return_value=100):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch('app.scripting.scripts._check_script', return_value=None):
                    with patch(
                        'app.main.generate_script',
                        new_callable=AsyncMock,
                        side_effect=ValueError(
                            "Model returned invalid data for scene 1: "
                            "on_screen_text: Value error, On-screen text must be at most 8 words, got 12"
                        ),
                    ):
                        response = api_client.post(
                            '/api/script/generate?idea_id=idea_123',
                            json={
                                "interview_transcript": "CEO: We have manual data entry problems.",
                                "source_mode": "brand_brain",
                            },
                        )

    assert response.status_code == 400, response.text
    assert "scene 1" in response.json()["error"].lower()
    mock_deduct.assert_not_called()


# =============================================================================
# ITEM 4: concurrency
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_regeneration_different_scenes_no_lost_update(valid_script, tmp_path):
    """
    Audit repro: two simultaneous regenerations of DIFFERENT scenes (2 and
    5, matching the audit's own repro) must BOTH persist -- neither's
    change should be lost to the other's read-modify-write.
    """
    os.chdir(tmp_path)

    async def fake_generate(prompt, generation_config=None, **kwargs):
        resp = Mock()
        if "Phase: lock_in" in prompt:
            resp.text = json.dumps({
                "spoken_text": "Regenerated lock_in scene text here right now",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Lock in regenerated",
                "acting_note": "Serious, direct tone",
                "sound": "test",
            })
        elif "Phase: body_2" in prompt:
            resp.text = json.dumps({
                "spoken_text": "Regenerated body two scene text here right now",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Body two regenerated",
                "acting_note": "Excited, confident tone",
                "sound": "test",
            })
        else:
            raise AssertionError(f"Unexpected prompt in test: {prompt[:200]}")
        return resp

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:
        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.side_effect = fake_generate

        _save_script(valid_script)

        results = await asyncio.gather(
            regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=2,
                instruction="tighten it",
            ),
            regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=5,
                instruction="add energy",
            ),
        )

    assert all(isinstance(r, Script) for r in results)

    final = _check_script(valid_script.session_id, valid_script.idea_id)
    assert final is not None
    assert final.scenes[1].spoken_text == "Regenerated lock_in scene text here right now"
    assert final.scenes[4].spoken_text == "Regenerated body two scene text here right now"


@pytest.mark.asyncio
async def test_concurrent_regeneration_same_scene_rejects_duplicate(valid_script, tmp_path):
    """
    Audit repro: firing the SAME scene's regeneration twice concurrently
    used to both succeed and charge twice. The duplicate must be rejected
    with SceneRegenerationInProgressError WHILE the first is genuinely
    still in flight, and the first must still succeed normally (charged
    once, by the caller in main.py).
    """
    os.chdir(tmp_path)
    gate = asyncio.Event()

    async def fake_generate(prompt, generation_config=None, **kwargs):
        # Block here so the duplicate attempt below is provably rejected
        # WHILE this first call is still in flight, not just faster.
        await gate.wait()
        resp = Mock()
        resp.text = json.dumps({
            "spoken_text": "Regenerated hook text here right now please",
            "shot": "close-up",
            "b_roll": None,
            "on_screen_text": "Regenerated hook",
            "acting_note": "Confident, direct energy",
            "sound": "upbeat",
        })
        return resp

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:
        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.side_effect = fake_generate

        _save_script(valid_script)

        first_task = asyncio.create_task(
            regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=1,
                instruction="first",
            )
        )
        # Give the first call a chance to run and register itself as
        # in-flight (it does so synchronously before its first real await).
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        with pytest.raises(SceneRegenerationInProgressError):
            await regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=1,
                instruction="duplicate",
            )

        gate.set()
        result = await first_task

    assert result.scenes[0].spoken_text == "Regenerated hook text here right now please"

    # First call's change persisted; nothing double-applied.
    final = _check_script(valid_script.session_id, valid_script.idea_id)
    assert final.scenes[0].spoken_text == "Regenerated hook text here right now please"


def test_regenerate_endpoint_duplicate_in_flight_rejected_409_no_charge(api_client):
    """
    Item 4 (endpoint wiring): SceneRegenerationInProgressError maps to 409
    and deducts NO credits.
    """
    with patch.object(guard, 'get_session', return_value={'credits': 42}):
        with patch.object(guard, 'get_remaining_credits', return_value=42):
            with patch.object(guard, 'deduct_credits') as mock_deduct:
                with patch(
                    'app.main.regenerate_scene',
                    new_callable=AsyncMock,
                    side_effect=SceneRegenerationInProgressError(
                        "Scene 1 of idea idea_123 is already being regenerated."
                    ),
                ):
                    response = api_client.post(
                        '/api/script/idea_123/scene/1/regenerate',
                        json={"instruction": "again"},
                    )

    assert response.status_code == 409, response.text
    mock_deduct.assert_not_called()


@pytest.mark.asyncio
async def test_manual_patch_during_in_flight_regeneration_not_lost(valid_script, tmp_path):
    """
    Audit repro: a manual PATCH landing while a regeneration is awaiting
    Gemini must NOT be lost when the regeneration finally saves back. The
    shared lock means the PATCH simply waits its turn and applies cleanly
    on top of the freshest state.
    """
    os.chdir(tmp_path)
    gate = asyncio.Event()

    async def fake_generate(prompt, generation_config=None, **kwargs):
        await gate.wait()
        resp = Mock()
        resp.text = json.dumps({
            "spoken_text": "Regenerated scene 3 text here right now please",
            "shot": "medium",
            "b_roll": None,
            "on_screen_text": "Regenerated body 1",
            "acting_note": "Confident tone",
            "sound": "test",
        })
        return resp

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:
        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.side_effect = fake_generate

        _save_script(valid_script)

        regen_task = asyncio.create_task(
            regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=3,
                instruction="rewrite",
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        patch_task = asyncio.create_task(
            update_scene_text(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=6,
                spoken_text="Manually edited CTA text while regen is in flight",
            )
        )
        # Let the PATCH queue behind the lock, then let the regen finish.
        await asyncio.sleep(0)
        gate.set()

        regen_result, patch_result = await asyncio.gather(regen_task, patch_task)

    final = _check_script(valid_script.session_id, valid_script.idea_id)
    assert final is not None
    assert final.scenes[2].spoken_text == "Regenerated scene 3 text here right now please"
    assert final.scenes[5].spoken_text == "Manually edited CTA text while regen is in flight"


# =============================================================================
# ITEM 5: manual edit recomputes timing and reflows
# =============================================================================

@pytest.mark.asyncio
async def test_update_scene_text_recomputes_timing_and_reflows(valid_script, tmp_path):
    os.chdir(tmp_path)
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(valid_script)

        original_scene2_duration = (
            valid_script.scenes[1].end_s - valid_script.scenes[1].start_s
        )  # 4.0s

        long_text = (
            "This is a much longer replacement sentence with many more words "
            "than before so the estimated duration clearly grows"
        )
        expected_duration = max(1.0, len(long_text.split()) / 2.5)

        result = await update_scene_text(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            spoken_text=long_text,
        )

    scene1 = result.scenes[0]
    assert scene1.spoken_text == long_text
    assert scene1.end_s == pytest.approx(scene1.start_s + expected_duration, abs=0.01)

    # Scene 2 (and everything after) reflowed: keeps ITS OWN duration but
    # starts exactly where scene 1 now ends -- no gap, no overlap.
    scene2 = result.scenes[1]
    assert scene2.start_s == pytest.approx(scene1.end_s, abs=0.01)
    assert (scene2.end_s - scene2.start_s) == pytest.approx(original_scene2_duration, abs=0.01)

    # And this was actually persisted, not just returned in-memory.
    reloaded = _check_script(valid_script.session_id, valid_script.idea_id)
    assert reloaded.scenes[0].end_s == pytest.approx(scene1.end_s, abs=0.01)
    assert reloaded.scenes[1].start_s == pytest.approx(scene2.start_s, abs=0.01)
    assert reloaded.scenes[-1].end_s == pytest.approx(result.scenes[-1].end_s, abs=0.01)
