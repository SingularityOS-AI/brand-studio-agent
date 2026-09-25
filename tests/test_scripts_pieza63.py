"""
Unit tests for Pieza 63:
- Scene prompts generated for all scenes regardless of asset_type
- Sanitization of stock queries
- Cleaning of old script scenes on load (_row_to_script)
- _generate_asset_prompt with charlatan LLM output
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.scripting.scripts import (
    _build_generation_prompt,
    _row_to_script,
    _sanitize_stock_query,
)


def test_row_to_script_cleans_null_and_format_shot():
    """Test 1: _row_to_script cleans 'null'/'None' strings and replaces format shot with 'Medium shot'."""
    row = {
        "id": "script_123",
        "session_token": "sess_abc",
        "idea_id": "idea_xyz",
        "status": "draft",
        "data": {
            "id": "script_123",
            "title": "Test Script",
            "angle": "Tech angle",
            "target_seconds": 60,
            "frame_zero": {
                "visual": "Founder on camera",
                "on_screen_text": "Tech future",
                "why_it_stops_the_scroll": "High energy",
            },
            "scenes": [
                {
                    "n": 1,
                    "start_s": 0.0,
                    "end_s": 5.0,
                    "phase": "hook",
                    "spoken_text": "Welcome to our AI demo.",
                    "shot": "teleprompter_clean",
                    "on_screen_text": "AI Demo",
                    "acting_note": "Direct gaze",
                    "sound": "energetic beat",
                    "asset_type": "ai_image",
                    "visual_prompt": "null",
                    "stock_query": "None",
                },
                {
                    "n": 2,
                    "start_s": 5.0,
                    "end_s": 10.0,
                    "phase": "lock_in",
                    "spoken_text": "Here is how it works.",
                    "shot": "Medium shot",
                    "on_screen_text": "How it works",
                    "acting_note": "Direct gaze",
                    "sound": "energetic beat",
                    "asset_type": "stock",
                    "visual_prompt": None,
                    "stock_query": "doctor clinic",
                },
                {
                    "n": 3,
                    "start_s": 10.0,
                    "end_s": 15.0,
                    "phase": "body_1",
                    "spoken_text": "First, we initialize the model.",
                    "shot": "Medium shot",
                    "on_screen_text": "Initialize model",
                    "acting_note": "Direct gaze",
                    "sound": "energetic beat",
                    "asset_type": "a_roll",
                    "visual_prompt": None,
                    "stock_query": None,
                },
                {
                    "n": 4,
                    "start_s": 15.0,
                    "end_s": 20.0,
                    "phase": "rehook",
                    "spoken_text": "Stay with me now.",
                    "shot": "Medium shot",
                    "on_screen_text": "Stay with me",
                    "acting_note": "Direct gaze",
                    "sound": "energetic beat",
                    "asset_type": "a_roll",
                    "visual_prompt": None,
                    "stock_query": None,
                },
                {
                    "n": 5,
                    "start_s": 20.0,
                    "end_s": 25.0,
                    "phase": "close_cta",
                    "spoken_text": "Try it today.",
                    "shot": "Medium shot",
                    "on_screen_text": "Try it today",
                    "acting_note": "Direct gaze",
                    "sound": "energetic beat",
                    "asset_type": "a_roll",
                    "visual_prompt": None,
                    "stock_query": None,
                },
            ],
            "audit": [],
        },
    }
    script = _row_to_script(row)
    assert script is not None
    assert len(script.scenes) == 5
    scene = script.scenes[0]
    assert scene.visual_prompt is None
    assert scene.stock_query is None
    assert scene.shot == "Medium shot"


def test_sanitize_stock_query_cases():
    """Test 2: _sanitize_stock_query correctly cleans multi-line/bulleted/overlength stock queries."""
    charlatan_text = (
        "Here are 5 search words for Pexels, aiming for footage that complements your on-screen and spoken text:\n\n"
        "1. **Healthcare technology**\n"
        "2. **Medical AI**\n"
    )
    assert _sanitize_stock_query(charlatan_text) == "Healthcare technology"
    assert _sanitize_stock_query("doctor video call tablet clinic") == "doctor video call tablet clinic"
    assert _sanitize_stock_query("**Medical AI**") == "Medical AI"
    assert _sanitize_stock_query("Here are some words:") is None
    assert _sanitize_stock_query("one two three four five six seven eight") == "one two three four five"


@pytest.mark.asyncio
async def test_generate_asset_prompt_stock_charlatan():
    """Test 3: _generate_asset_prompt("stock", ...) cleans charlatan LLM text to 2-5 clean words."""
    mock_resp = Mock()
    mock_resp.text = (
        "Here are 5 search words for Pexels, aiming for footage that complements your on-screen and spoken text:\n\n"
        "1. **Healthcare technology**\n"
        "2. **Medical AI**\n"
    )
    mock_client = Mock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    mock_scene = Mock()
    mock_scene.spoken_text = "Doctor using modern medical tech"
    mock_scene.on_screen_text = "Healthcare AI"
    mock_scene.stock_query = None
    mock_scene.b_roll = None

    with patch("app.audiovisual.genai_client.get_genai_client", return_value=mock_client):
        from app.main import _generate_asset_prompt

        prompt = await _generate_asset_prompt("stock", mock_scene, "healthcare innovation")
        assert prompt == "Healthcare technology"


def test_generation_and_iteration_prompts_require_prompts_for_all_scenes():
    """Test 4: Prompts ask for stock_query and visual_prompt for all scenes, regardless of asset_type."""
    idea = Mock()
    idea.title = "AI in Healthcare"
    idea.master_category = "autoridad_tecnica"
    idea.subcategory = "AI Solutions"
    idea.demand_signal = "High demand"

    gen_prompt = _build_generation_prompt(
        "Brand context here",
        idea,
        "Interview transcript",
        "brand_brain",
        "informative",
    )

    # Key phrase checked: "regardless of asset_type (including a_roll)"
    assert "regardless of asset_type (including a_roll)" in gen_prompt
    assert 'null if asset_type is "a_roll"' not in gen_prompt
    assert "stock_query" in gen_prompt
    assert "visual_prompt" in gen_prompt
