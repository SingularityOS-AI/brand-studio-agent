"""
Tests for Pieza 59 — Iterar una escena sin contaminarla (backend del guión).
Zero real calls to Vertex/Gemini, zero network.
"""
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _check_no_not_x_its_y,
    _clean_optional_text,
    _save_script,
    regenerate_scene,
)


@pytest.fixture
def valid_frame_zero():
    return FrameZero(
        visual="Founder staring at endless spreadsheets",
        on_screen_text="Still doing this?",
        why_it_stops_the_scroll="Relatable frustration stops scroll",
    )


@pytest.fixture
def valid_scenes():
    return [
        Scene(
            n=1,
            start_s=0.0,
            end_s=3.0,
            phase="hook",
            spoken_text="Twenty minutes. That's how long your patient waits for an interpreter.",
            shot="Medium shot",
            b_roll=None,
            on_screen_text="Twenty minutes waiting",
            acting_note="Empathic tone",
            sound="upbeat",
            asset_type="a_roll",
            stock_query="hospital waiting room",
            visual_prompt="A patient waiting in a medical clinic",
        ),
        Scene(
            n=2,
            start_s=3.0,
            end_s=7.0,
            phase="lock_in",
            spoken_text="This delay creates friction for care teams every day.",
            shot="Close-up",
            b_roll=None,
            on_screen_text="Care team friction",
            acting_note="Serious tone",
            sound="subtle background",
        ),
        Scene(
            n=3,
            start_s=7.0,
            end_s=11.0,
            phase="body_1",
            spoken_text="Our AI instant voice agent connects interpreters in seconds.",
            shot="Medium shot",
            b_roll=None,
            on_screen_text="Instant connections",
            acting_note="Confident delivery",
            sound="tech tone",
        ),
        Scene(
            n=4,
            start_s=11.0,
            end_s=14.0,
            phase="rehook",
            spoken_text="No complex hardware setup required.",
            shot="Wide shot",
            b_roll=None,
            on_screen_text="Zero hardware setup",
            acting_note="Direct gaze",
            sound="pause",
        ),
        Scene(
            n=5,
            start_s=14.0,
            end_s=18.0,
            phase="body_2",
            spoken_text="It is not about replacing human interpreters, it is about speed.",
            shot="Medium close-up",
            b_roll=None,
            on_screen_text="Speed matters",
            acting_note="Focused explanation",
            sound="upbeat",
            asset_type="ai_image",
            stock_query="doctor with tablet",
            visual_prompt="Medical interpreter working alongside doctor",
        ),
    ]


@pytest.fixture
def valid_script(valid_frame_zero, valid_scenes):
    return Script(
        session_id="test_session_p59",
        idea_id="idea_p59",
        title="Instant Medical Interpreting",
        angle="Reduces wait times from 20 minutes to seconds",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=valid_frame_zero,
        scenes=valid_scenes,
        recording_format="teleprompter_clean",
    )


@pytest.mark.asyncio
async def test_1_regenerate_scene_prompt_contains_language_rule_and_other_scenes(
    valid_script, tmp_path
):
    """
    Test 1: Prompt passed to GenerativeModel contains the language rule
    and the spoken_text of at least one other scene in the script.
    """
    os.chdir(tmp_path)

    captured_prompt = None

    async def fake_generate(prompt, generation_config=None, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        resp = Mock()
        resp.text = json.dumps({
            "spoken_text": "Twenty minutes is too long for any patient to wait.",
            "shot": "Medium shot",
            "b_roll": None,
            "on_screen_text": "No more waiting",
            "acting_note": "Empathic tone",
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

        await regenerate_scene(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            instruction="Hazlo más directo en español",
        )

    assert captured_prompt is not None
    # Check language rule present in prompt
    assert (
        "Write spoken_text, on_screen_text and acting_note in the SAME language as the original scene text."
        in captured_prompt
    )
    assert (
        "The instruction may be written in a different language — that NEVER changes the output language."
        in captured_prompt
    )
    # Check spoken_text of another scene (e.g., scene 2 or scene 5) is in prompt
    assert "This delay creates friction for care teams every day." in captured_prompt


@pytest.mark.asyncio
async def test_2_regenerate_scene_cleans_string_null_and_uses_fallback(
    valid_script, tmp_path
):
    """
    Test 2: Model returns "visual_prompt": "null" and "stock_query": "None" ->
    saved scene gets fallback's visual_prompt and stock_query.
    """
    os.chdir(tmp_path)

    mock_response = Mock()
    mock_response.text = json.dumps({
        "spoken_text": "Veinte minutos de espera es inaceptable.",
        "shot": "Medium shot",
        "b_roll": None,
        "on_screen_text": "Espera inaceptable",
        "acting_note": "Direct tone",
        "sound": "upbeat",
        "stock_query": "None",
        "visual_prompt": "null",
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

        # Regenerate scene 1 (which has fallback stock_query="hospital waiting room", visual_prompt="A patient waiting...")
        result = await regenerate_scene(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            instruction="Mejora esta escena",
        )

    sc1 = result.scenes[0]
    assert sc1.stock_query == "hospital waiting room"
    assert sc1.visual_prompt == "A patient waiting in a medical clinic"


@pytest.mark.asyncio
async def test_3_regenerate_scene_preserves_shot_when_recording_format_returned(
    valid_script, tmp_path
):
    """
    Test 3: Model returns "shot": "teleprompter_clean" (a recording format) ->
    saved scene preserves original fallback shot.
    """
    os.chdir(tmp_path)

    mock_response = Mock()
    mock_response.text = json.dumps({
        "spoken_text": "Veinte minutos de espera para un intérprete.",
        "shot": "teleprompter_clean",
        "b_roll": None,
        "on_screen_text": "Veinte minutos",
        "acting_note": "Enfático",
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
            instruction="Cambiar texto",
        )

    # Scene 1 original shot was "Medium shot"
    assert result.scenes[0].shot == "Medium shot"


def test_4_check_no_not_x_its_y_spanish_patterns(valid_script):
    """
    Test 4: _check_no_not_x_its_y returns False for forbidden Spanish pattern
    "No se trata de...", and True for valid script text.
    """
    # Create script with Spanish forbidden pattern
    bad_scenes = list(valid_script.scenes)
    bad_scenes[0] = bad_scenes[0].model_copy(
        update={"spoken_text": "No se trata de reemplazar a nadie. Se trata de entender."}
    )
    bad_script = valid_script.model_copy(update={"scenes": bad_scenes})

    assert _check_no_not_x_its_y(bad_script) is False

    # Create script without forbidden patterns
    good_scenes = list(valid_script.scenes)
    good_scenes[0] = good_scenes[0].model_copy(
        update={"spoken_text": "Veinte minutos. Ese es el tiempo que espera tu paciente."}
    )
    good_scenes[4] = good_scenes[4].model_copy(
        update={"spoken_text": "La velocidad en la atención médica salva vidas."}
    )
    good_script = valid_script.model_copy(update={"scenes": good_scenes})

    assert _check_no_not_x_its_y(good_script) is True


def test_5_clean_optional_text_behavior():
    """
    Test 5: _clean_optional_text returns None for "null", " NULL ", "", None, "n/a",
    and returns stripped text for valid strings like "doctor in waiting room".
    """
    assert _clean_optional_text("null") is None
    assert _clean_optional_text(" NULL ") is None
    assert _clean_optional_text("") is None
    assert _clean_optional_text(None) is None
    assert _clean_optional_text("n/a") is None
    assert _clean_optional_text("NA") is None
    assert _clean_optional_text("undefined") is None
    assert _clean_optional_text("doctor in waiting room") == "doctor in waiting room"
    assert _clean_optional_text("  doctor in waiting room  ") == "doctor in waiting room"
