"""
Unit tests for PIEZA 66 script generation & asset prompt fill:
- Guarantees every scene has stock_query and visual_prompt filled in code.
- Zero network / real Vertex calls.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    _fallback_stock_query,
    _fallback_visual_prompt,
    _fill_missing_asset_prompts,
    generate_script,
    regenerate_scene,
)


@pytest.fixture
def sample_frame_zero():
    return FrameZero(
        visual="Founder talking about local AI solution",
        on_screen_text="Local AI Infrastructure",
        why_it_stops_the_scroll="Strong hook about data privacy",
    )


def make_test_scene(
    n: int,
    phase: str = "hook",
    asset_type: str = "a_roll",
    spoken: str = "We build custom AI voice agents for healthcare teams.",
    stock_q: str | None = None,
    visual_p: str | None = None,
) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase=phase,
        spoken_text=spoken,
        shot="Medium shot",
        b_roll="close up of typing on mechanical keyboard" if asset_type != "a_roll" else None,
        on_screen_text=f"Scene {n} focus",
        acting_note="Confident delivery",
        sound="upbeat music",
        asset_type=asset_type,
        stock_query=stock_q,
        visual_prompt=visual_p,
    )


@pytest.mark.asyncio
async def test_fallback_helpers():
    scene = make_test_scene(
        1,
        spoken="Our company revolutionizes customer service with instant AI agents.",
        stock_q=None,
        visual_p=None,
    )
    sq = _fallback_stock_query(scene)
    vp = _fallback_visual_prompt(scene)

    assert isinstance(sq, str) and len(sq) > 0
    assert isinstance(vp, str) and "cinematic, vertical 9:16" in vp
    assert sq != "null" and vp != "null"


@pytest.mark.asyncio
async def test_fill_missing_asset_prompts_when_already_full():
    scenes = [
        make_test_scene(i, stock_q="hospital room", visual_p="A modern hospital room, cinematic, 9:16")
        for i in range(1, 6)
    ]
    script = MagicMock()
    script.scenes = scenes
    script.angle = "AI in healthcare"

    with patch("vertexai.generative_models.GenerativeModel") as mock_model_cls:
        changed = await _fill_missing_asset_prompts(script)
        assert changed is False
        mock_model_cls.assert_not_called()


@pytest.mark.asyncio
async def test_generate_script_fills_missing_prompts_for_aroll():
    # Model response for initial script generation with missing stock_query/visual_prompt in a_roll
    script_gemini_response = {
        "title": "Local AI Healthcare",
        "angle": "Sovereign AI agents for healthcare privacy",
        "funnel_stage": "tofu",
        "target_seconds": 60,
        "frame_zero": {
            "visual": "Founder in clinic office",
            "on_screen_text": "Healthcare AI fear",
            "why_it_stops_the_scroll": "Immediate dilemma",
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "spoken_text": "There is a big fear that AI in healthcare will replace doctors.",
                "shot": "Medium shot",
                "b_roll": None,
                "on_screen_text": "AI in healthcare fear",
                "acting_note": "Empathic rhythm",
                "sound": "upbeat",
                "asset_type": "a_roll",
                "stock_query": None,
                "visual_prompt": None,
            },
            {
                "n": 2,
                "phase": "lock_in",
                "spoken_text": "This delay creates friction for care teams every day in clinics.",
                "shot": "Close-up",
                "b_roll": None,
                "on_screen_text": "Care team friction",
                "acting_note": "Serious tone",
                "sound": "subtle background",
                "asset_type": "a_roll",
                "stock_query": None,
                "visual_prompt": None,
            },
            {
                "n": 3,
                "phase": "body_1",
                "spoken_text": "Our AI instant voice agent connects interpreters for you in seconds.",
                "shot": "Medium shot",
                "b_roll": "Doctor talking to patient in hospital hallway",
                "on_screen_text": "Instant connections",
                "acting_note": "Confident delivery",
                "sound": "tech tone",
                "asset_type": "stock",
                "stock_query": "doctor patient conversation",
                "visual_prompt": "Doctor talking to patient in bright hospital, cinematic, vertical 9:16",
            },
            {
                "n": 4,
                "phase": "rehook",
                "spoken_text": "There is no complex hardware setup required for your team.",
                "shot": "Wide shot",
                "b_roll": None,
                "on_screen_text": "Zero hardware setup",
                "acting_note": "Direct gaze",
                "sound": "pause",
                "asset_type": "a_roll",
                "stock_query": None,
                "visual_prompt": None,
            },
            {
                "n": 5,
                "phase": "body_2",
                "spoken_text": "Giving healthcare staff instant access when needed most.",
                "shot": "Medium close-up",
                "b_roll": None,
                "on_screen_text": "Instant access matters",
                "acting_note": "Focused explanation",
                "sound": "upbeat",
                "asset_type": "a_roll",
                "stock_query": None,
                "visual_prompt": None,
            },
            {
                "n": 6,
                "phase": "close_cta",
                "spoken_text": "Try our demo today and see how it works for your clinic.",
                "shot": "Medium shot",
                "b_roll": "Medical tablet interface",
                "on_screen_text": "Try demo today",
                "acting_note": "Strong closing",
                "sound": "upbeat",
                "asset_type": "ai_image",
                "stock_query": "medical tablet app",
                "visual_prompt": "Futuristic medical app on tablet screen, cinematic, vertical 9:16",
            },
        ],
        "sources": ["Brand Brain"],
        "music_prompt": "upbeat ambient medical synth",
        "recording_format": "selfie_natural",
    }

    fill_gemini_response = {
        "scenes": [
            {"n": 1, "stock_query": "medical clinic doctor", "visual_prompt": "Doctor speaking in modern clinic, cinematic, 9:16"},
            {"n": 2, "stock_query": "hospital corridor busy", "visual_prompt": "Busy hospital corridor, cinematic, 9:16"},
            {"n": 4, "stock_query": "server rack clean", "visual_prompt": "Clean server rack setup, cinematic, 9:16"},
            {"n": 5, "stock_query": "doctor typing computer", "visual_prompt": "Healthcare worker using workstation, cinematic, 9:16"},
        ]
    }

    mock_model_gen = MagicMock()
    mock_model_gen.generate_content_async = AsyncMock(
        side_effect=[
            MagicMock(text=json.dumps(script_gemini_response)),  # generate_script call
            MagicMock(text=json.dumps(fill_gemini_response)),    # _fill_missing_asset_prompts call
        ]
    )

    mock_brain = MagicMock()
    mock_idea = MagicMock()
    mock_idea.id = "idea_p66_test"
    mock_idea.status = "approved"
    mock_idea.subcategory = "Anatomía de un proceso"
    mock_idea.master_category = "autoridad_tecnica"
    mock_idea.hook = "Big fear in AI"
    mock_catalog = MagicMock()
    mock_catalog.catalog_locked = True
    mock_catalog.ideas = [mock_idea]

    with patch("app.scripting.scripts.get_brand_brain", return_value=mock_brain), \
         patch("app.catalog.ideas._check_catalog_cache", return_value=mock_catalog), \
         patch("app.scripting.scripts._save_script"), \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel", return_value=mock_model_gen):

        script = await generate_script(
            session_id="test_session",
            idea_id="idea_p66_test",
            interview_transcript="Interview text",
        )

        assert len(script.scenes) == 6
        for scene in script.scenes:
            assert scene.stock_query is not None and scene.stock_query != "null"
            assert scene.visual_prompt is not None and scene.visual_prompt != "null"

        # B-roll scene 3 and 6 original queries preserved
        assert script.scenes[2].stock_query == "doctor patient conversation"
        assert script.scenes[5].stock_query == "medical tablet app"


@pytest.mark.asyncio
async def test_fill_missing_asset_prompts_fallback_on_llm_exception():
    scenes = [
        make_test_scene(1, spoken="First scene about software engineering", stock_q=None, visual_p=None),
        make_test_scene(2, spoken="Second scene about server deployment", stock_q=None, visual_p=None),
        make_test_scene(3, spoken="Third scene about database queries", stock_q="database server", visual_p="Database server rack, 9:16"),
        make_test_scene(4, spoken="Fourth scene about cloud monitoring", stock_q=None, visual_p=None),
        make_test_scene(5, spoken="Fifth scene about system uptime", stock_q=None, visual_p=None),
    ]
    script = MagicMock()
    script.scenes = scenes
    script.angle = "Software engineering best practices"

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(side_effect=asyncio.TimeoutError("Gemini timeout"))

    with patch("vertexai.generative_models.GenerativeModel", return_value=mock_model):
        changed = await _fill_missing_asset_prompts(script)
        assert changed is True
        for s in script.scenes:
            assert s.stock_query is not None and len(s.stock_query) > 0 and s.stock_query != "null"
            assert s.visual_prompt is not None and len(s.visual_prompt) > 0 and s.visual_prompt != "null"


@pytest.mark.asyncio
async def test_regenerate_scene_only_fills_target_scene():
    scenes = [
        make_test_scene(1, stock_q="office team", visual_p="Office team working, 9:16"),
        make_test_scene(2, stock_q="code editor", visual_p="Code editor screen, 9:16"),
        make_test_scene(3, stock_q="cloud server", visual_p="Cloud server rack, 9:16"),
        make_test_scene(4, stock_q="laptop desk", visual_p="Laptop on desk, 9:16"),
        make_test_scene(5, stock_q="meeting room", visual_p="Meeting room discussion, 9:16"),
    ]
    existing_script = Script(
        session_id="session_regen_p66",
        idea_id="idea_regen_p66",
        title="Regen Test",
        angle="Regen angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="o", why_it_stops_the_scroll="w"),
        scenes=scenes,
        state="draft",
    )

    regen_gemini_resp = {
        "spoken_text": "Updated spoken text for scene 2 with better rhythm.",
        "shot": "Close-up",
        "b_roll": "programmer typing fast",
        "on_screen_text": "Faster coding",
        "acting_note": "Energetic tone",
        "sound": "keyboard click",
        "asset_type": "a_roll",
        "stock_query": None,
        "visual_prompt": None,
    }

    fill_gemini_resp = {
        "scenes": [
            {"n": 2, "stock_query": "programmer typing keyboard", "visual_prompt": "Programmer typing fast on keyboard, cinematic, 9:16"}
        ]
    }

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        side_effect=[
            MagicMock(text=json.dumps(regen_gemini_resp)),
            MagicMock(text=json.dumps(fill_gemini_resp)),
        ]
    )

    with patch("app.scripting.scripts._check_script", return_value=existing_script), \
         patch("app.scripting.scripts._save_script"), \
         patch("app.scripting.scripts.get_brand_brain", return_value=MagicMock()), \
         patch("vertexai.generative_models.GenerativeModel", return_value=mock_model):

        updated_script = await regenerate_scene(
            session_id="session_regen_p66",
            idea_id="idea_regen_p66",
            scene_n=2,
            instruction="Make it more energetic",
        )

        assert updated_script.scenes[1].stock_query is not None
        assert updated_script.scenes[1].visual_prompt is not None


@pytest.mark.asyncio
async def test_spanish_script_asks_fill_prompt_in_english():
    scenes = [
        make_test_scene(1, spoken="Hola a todos, este es un guión en español sobre IA.", stock_q=None, visual_p=None),
        make_test_scene(2, spoken="Aquí mostramos los resultados del sistema.", stock_q=None, visual_p=None),
        make_test_scene(3, spoken="El proceso es rápido y seguro.", stock_q="proceso seguro", visual_p="Proceso seguro, 9:16"),
        make_test_scene(4, spoken="Cero complicaciones para tu equipo.", stock_q=None, visual_p=None),
        make_test_scene(5, spoken="Pruébalo hoy mismo en tu empresa.", stock_q=None, visual_p=None),
    ]
    script = MagicMock()
    script.scenes = scenes
    script.angle = "Automatización con IA"

    captured_prompts = []

    async def mock_generate_content(prompt, generation_config=None):
        captured_prompts.append(prompt)
        return MagicMock(text=json.dumps({
            "scenes": [
                {"n": 1, "stock_query": "artificial intelligence office", "visual_prompt": "AI concept in modern office, cinematic, 9:16"},
                {"n": 2, "stock_query": "data dashboard metrics", "visual_prompt": "Metrics dashboard display, cinematic, 9:16"},
                {"n": 4, "stock_query": "team meeting clean", "visual_prompt": "Team meeting discussion, cinematic, 9:16"},
                {"n": 5, "stock_query": "business hand shake", "visual_prompt": "Business handshake, cinematic, 9:16"},
            ]
        }))

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(side_effect=mock_generate_content)

    with patch("vertexai.generative_models.GenerativeModel", return_value=mock_model):
        await _fill_missing_asset_prompts(script)
        assert len(captured_prompts) == 1
        prompt_text = captured_prompts[0]
        assert "IN ENGLISH" in prompt_text
        assert "Pexels" in prompt_text
