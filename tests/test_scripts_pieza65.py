"""
Tests for Pieza 65 — Un guion, un idioma (single-language enforcement & audit rule 14).
Zero real calls to Vertex/Gemini, zero network.
"""
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _detect_language,
    audit_script,
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
def english_scenes():
    return [
        Scene(
            n=1,
            start_s=0.0,
            end_s=3.0,
            phase="hook",
            spoken_text="There's a big fear AI in healthcare means replacing doctors and nurses. Is that the real story?",
            shot="Medium shot",
            b_roll=None,
            on_screen_text="AI in healthcare fear",
            acting_note="Empathic delivery and rhythm",
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
            spoken_text="This delay creates friction for care teams every day in our clinic and for your team.",
            shot="Close-up",
            b_roll=None,
            on_screen_text="Care team friction",
            acting_note="Serious tone and clear pauses",
            sound="subtle background",
        ),
        Scene(
            n=3,
            start_s=7.0,
            end_s=11.0,
            phase="body_1",
            spoken_text="Our AI instant voice agent is designed to connect interpreters for you in seconds.",
            shot="Medium shot",
            b_roll=None,
            on_screen_text="Instant connections",
            acting_note="Confident delivery and gaze",
            sound="tech tone",
        ),
        Scene(
            n=4,
            start_s=11.0,
            end_s=14.0,
            phase="rehook",
            spoken_text="There is no complex hardware setup required for you and your team.",
            shot="Wide shot",
            b_roll=None,
            on_screen_text="Zero hardware setup",
            acting_note="Direct gaze and strong finish",
            sound="pause",
        ),
        Scene(
            n=5,
            start_s=14.0,
            end_s=18.0,
            phase="body_2",
            spoken_text="It is about giving healthcare staff instant access for your team when it is needed.",
            shot="Medium close-up",
            b_roll=None,
            on_screen_text="Instant access matters",
            acting_note="Focused explanation with pause",
            sound="upbeat",
        ),
        Scene(
            n=6,
            start_s=18.0,
            end_s=21.0,
            phase="close_cta",
            spoken_text="Try our demo today and see how it works for you and your clinic.",
            shot="Medium shot",
            b_roll=None,
            on_screen_text="Try demo today",
            acting_note="Friendly invitation and gaze",
            sound="upbeat outro",
        ),
    ]


def test_detect_language():
    """Test 1: _detect_language deterministically identifies Spanish, English, or None."""
    spanish_hook = "Hay un gran temor de que la IA en salud signifique reemplazar médicos y enfermeras…"
    english_hook = "There's a big fear AI in healthcare means replacing doctors and nurses. Is that the real story?"
    short_text = "Twenty minutes."

    assert _detect_language(spanish_hook) == "es"
    assert _detect_language(english_hook) == "en"
    assert _detect_language(short_text) is None


def test_audit_script_rule_14(valid_frame_zero, english_scenes):
    """Test 2: audit_script rule_14 passes for single language and fails for mixed languages."""
    # All English -> PASS
    english_script = Script(
        session_id="test_session",
        idea_id="idea_mix1",
        title="Test English Script",
        angle="test_angle",
        target_seconds=60,
        recording_format="teleprompter_clean",
        frame_zero=valid_frame_zero,
        scenes=english_scenes,
        sources=["Source 1"],
    )
    findings_en = audit_script(english_script)
    rule_14_en = next(f for f in findings_en if f.rule == "rule_14")
    assert rule_14_en.status == "pass"
    assert rule_14_en.critical is True

    # All Spanish -> PASS
    spanish_scenes = [
        Scene(
            n=sc.n,
            start_s=sc.start_s,
            end_s=sc.end_s,
            phase=sc.phase,
            spoken_text="Hay un gran temor de que la IA en salud signifique reemplazar médicos y enfermeras.",
            shot=sc.shot,
            on_screen_text="IA en salud",
            acting_note=sc.acting_note,
            sound="upbeat",
        )
        for sc in english_scenes
    ]
    spanish_script = Script(
        session_id="test_session",
        idea_id="idea_mix2",
        title="Test Spanish Script",
        angle="test_angle",
        target_seconds=60,
        recording_format="teleprompter_clean",
        frame_zero=valid_frame_zero,
        scenes=spanish_scenes,
        sources=["Fuente 1"],
    )
    findings_es = audit_script(spanish_script)
    rule_14_es = next(f for f in findings_es if f.rule == "rule_14")
    assert rule_14_es.status == "pass"

    # Mixed: scenes 1 and 4 in Spanish, rest (2, 3, 5, 6) in English -> FAIL
    mixed_scenes = list(english_scenes)
    mixed_scenes[0] = Scene(
        n=1,
        start_s=0.0,
        end_s=3.0,
        phase="hook",
        spoken_text="Hay un gran temor de que la IA en salud signifique reemplazar médicos y enfermeras.",
        shot="Medium shot",
        on_screen_text="Temor en salud",
        acting_note="Empathic delivery and rhythm",
        sound="upbeat",
    )
    mixed_scenes[3] = Scene(
        n=4,
        start_s=11.0,
        end_s=14.0,
        phase="rehook",
        spoken_text="Trabajar con la tecnología correcta marca la diferencia en cada consulta para el equipo.",
        shot="Wide shot",
        on_screen_text="La tecnología correcta",
        acting_note="Direct gaze and strong finish",
        sound="pause",
    )
    mixed_script = Script(
        session_id="test_session",
        idea_id="idea_mix3",
        title="Test Mixed Script",
        angle="test_angle",
        target_seconds=60,
        recording_format="teleprompter_clean",
        frame_zero=valid_frame_zero,
        scenes=mixed_scenes,
        sources=["Source 1"],
    )
    findings_mixed = audit_script(mixed_script)
    rule_14_mixed = next(f for f in findings_mixed if f.rule == "rule_14")
    assert rule_14_mixed.status == "fail"
    assert rule_14_mixed.critical is True
    assert "1, 4" in rule_14_mixed.detail
    assert "Spanish" in rule_14_mixed.detail


@pytest.mark.asyncio
async def test_regenerate_scene_language_enforcement(valid_frame_zero, english_scenes):
    """
    Test 3: regenerate_scene raises ValueError when rewritten scene remains in wrong language
    after retry (and script is untouched), but succeeds if retry brings it back in English.
    """
    script = Script(
        session_id="test_session",
        idea_id="idea_regen",
        title="Regen Script Test",
        angle="test_angle",
        target_seconds=60,
        recording_format="teleprompter_clean",
        frame_zero=valid_frame_zero,
        scenes=english_scenes,
        sources=["Source 1"],
    )

    spanish_llm_json = json.dumps({
        "spoken_text": "Hay un gran temor de que la IA en salud signifique reemplazar médicos y enfermeras.",
        "shot": "Medium shot",
        "on_screen_text": "IA en salud",
        "acting_note": "Empathic delivery with clear rhythm",
        "sound": "upbeat",
        "asset_type": "a_roll",
        "stock_query": "hospital waiting room",
        "visual_prompt": "A patient waiting in a medical clinic",
    })

    english_llm_json = json.dumps({
        "spoken_text": "There's a big fear that AI in healthcare means replacing doctors and nurses.",
        "shot": "Medium shot",
        "on_screen_text": "AI healthcare fear",
        "acting_note": "Empathic delivery with clear rhythm",
        "sound": "upbeat",
        "asset_type": "a_roll",
        "stock_query": "hospital waiting room",
        "visual_prompt": "A patient waiting in a medical clinic",
    })

    # Case A: LLM returns Spanish both times -> raises ValueError and script scene 1 is unchanged
    with patch("app.scripting.scripts._check_script", return_value=script), \
         patch("app.scripting.scripts.get_brand_brain", return_value=Mock(sections=[])), \
         patch("app.scripting.scripts._save_script") as mock_save, \
         patch("vertexai.generative_models.GenerativeModel") as MockModelClass:

        mock_model = Mock()
        mock_resp_es = Mock()
        mock_resp_es.text = spanish_llm_json
        mock_model.generate_content_async = AsyncMock(return_value=mock_resp_es)
        MockModelClass.return_value = mock_model

        with pytest.raises(ValueError) as excinfo:
            await regenerate_scene(
                session_id="test_session",
                idea_id="idea_regen",
                scene_n=1,
                instruction="make it punchier",
            )

        assert "The rewritten scene came back in Spanish" in str(excinfo.value)
        assert "this script is in English" in str(excinfo.value)
        # Ensure script was NOT saved and scene 1 was NOT modified
        mock_save.assert_not_called()
        assert script.scenes[0].spoken_text == english_scenes[0].spoken_text

    # Case B: LLM returns Spanish on 1st call, English on retry -> succeeds and saves
    with patch("app.scripting.scripts._check_script", return_value=script), \
         patch("app.scripting.scripts.get_brand_brain", return_value=Mock(sections=[])), \
         patch("app.scripting.scripts._save_script") as mock_save, \
         patch("vertexai.generative_models.GenerativeModel") as MockModelClass:

        mock_model = Mock()
        mock_resp_es = Mock()
        mock_resp_es.text = spanish_llm_json
        mock_resp_en = Mock()
        mock_resp_en.text = english_llm_json

        mock_model.generate_content_async = AsyncMock(side_effect=[mock_resp_es, mock_resp_en])
        MockModelClass.return_value = mock_model

        updated_script = await regenerate_scene(
            session_id="test_session",
            idea_id="idea_regen",
            scene_n=1,
            instruction="make it punchier",
        )

        assert mock_save.called
        assert "There's a big fear" in updated_script.scenes[0].spoken_text


@pytest.mark.asyncio
async def test_regenerate_scene_prompt_language_instruction(valid_frame_zero, english_scenes):
    """
    Test 4: Prompt sent to model contains 'in English' for an English script,
    even if the target scene being regenerated was edited into Spanish.
    """
    scenes = list(english_scenes)
    # Target scene 1 is edited to Spanish
    scenes[0] = Scene(
        n=1,
        start_s=0.0,
        end_s=3.0,
        phase="hook",
        spoken_text="Hay un gran temor de que la IA en salud signifique reemplazar médicos y enfermeras.",
        shot="Medium shot",
        on_screen_text="Temor en salud",
        acting_note="Empathic delivery and rhythm",
        sound="upbeat",
    )
    script = Script(
        session_id="test_session",
        idea_id="idea_target_es",
        title="English Majority Script",
        angle="test_angle",
        target_seconds=60,
        recording_format="teleprompter_clean",
        frame_zero=valid_frame_zero,
        scenes=scenes,
        sources=["Source 1"],
    )

    english_llm_json = json.dumps({
        "spoken_text": "There's a major fear that AI in healthcare will replace doctors and nurses.",
        "shot": "Medium shot",
        "on_screen_text": "AI healthcare fear",
        "acting_note": "Empathic delivery and rhythm",
        "sound": "upbeat",
        "asset_type": "a_roll",
        "stock_query": "hospital waiting room",
        "visual_prompt": "A patient waiting in a medical clinic",
    })

    with patch("app.scripting.scripts._check_script", return_value=script), \
         patch("app.scripting.scripts.get_brand_brain", return_value=Mock(sections=[])), \
         patch("app.scripting.scripts._save_script"), \
         patch("vertexai.generative_models.GenerativeModel") as MockModelClass:

        mock_model = Mock()
        mock_resp = Mock()
        mock_resp.text = english_llm_json
        mock_model.generate_content_async = AsyncMock(return_value=mock_resp)
        MockModelClass.return_value = mock_model

        await regenerate_scene(
            session_id="test_session",
            idea_id="idea_target_es",
            scene_n=1,
            instruction="reescribir en español",  # Instruction in Spanish
        )

        assert mock_model.generate_content_async.called
        sent_prompt = mock_model.generate_content_async.call_args[0][0]
        assert "Write spoken_text, on_screen_text and acting_note in English" in sent_prompt
