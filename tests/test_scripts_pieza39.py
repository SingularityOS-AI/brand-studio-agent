"""
Tests for Pieza 39 — Blueprint fields and duration estimation.

Coverage:
- Backward compatibility: old scripts without blueprint fields load correctly
- Round-trip persistence: blueprint fields survive save/load cycle
- Duration estimation: based on spoken_text word count (2.5 words/sec)
- Blueprint fields in Scene (asset_type, stock_query, visual_prompt)
- Blueprint fields in Script (music_prompt, recording_format)
"""
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.scripting.scripts import (
    CREDITS_COST_GENERATE,
    CREDITS_COST_REGENERATE_SCENE,
    FrameZero,
    Scene,
    Script,
    ScriptStorageError,
    _check_script,
    _row_to_script,
    _save_script,
    _script_to_row,
    audit_script,
    generate_script,
    lock_script,
    regenerate_scene,
    update_scene_text,
)


@pytest.fixture
def valid_frame_zero():
    """Valid FrameZero model."""
    return FrameZero(
        visual="Founder staring at endless spreadsheets, clearly frustrated",
        on_screen_text="Still doing this?",
        why_it_stops_the_scroll="Relatable frustration stops scroll instantly"
    )


@pytest.fixture
def old_format_scenes():
    """Scenes in old format (before Pieza 39) — no asset_type, stock_query, visual_prompt."""
    return [
        Scene(
            n=1,
            start_s=0.0,
            end_s=3.0,
            phase="hook",
            spoken_text="You're still doing this manually? Let me show you a better way.",
            shot="medium shot",
            b_roll=None,
            on_screen_text="Stop the manual work",
            acting_note="Lean in slightly, empathetic tone",
            sound="upbeat synth background",
            # No asset_type, stock_query, visual_prompt (use defaults)
        ),
        Scene(
            n=2,
            start_s=3.0,
            end_s=7.0,
            phase="lock_in",
            spoken_text="This problem affects teams.",
            shot="medium",
            b_roll=None,
            on_screen_text="Problem affects",
            acting_note="Serious tone",
            sound="test",
        ),
        Scene(
            n=3,
            start_s=7.0,
            end_s=11.0,
            phase="body_1",
            spoken_text="Our AI reduces errors.",
            shot="medium",
            b_roll=None,
            on_screen_text="Reduces errors",
            acting_note="Confident tone",
            sound="test",
        ),
        Scene(
            n=4,
            start_s=11.0,
            end_s=14.0,
            phase="rehook",
            spoken_text="But here is different.",
            shot="medium",
            b_roll=None,
            on_screen_text="Different",
            acting_note="Pause for emphasis",
            sound="test",
        ),
        Scene(
            n=5,
            start_s=14.0,
            end_s=18.0,
            phase="body_2",
            spoken_text="Real analytics show ROI.",
            shot="medium",
            b_roll=None,
            on_screen_text="Show ROI",
            acting_note="Excited tone",
            sound="test",
        ),
        Scene(
            n=6,
            start_s=18.0,
            end_s=22.0,
            phase="close_cta",
            spoken_text="Try it today.",
            shot="medium",
            b_roll=None,
            on_screen_text="Try it",
            acting_note="Direct gaze",
            sound="test",
        ),
    ]


@pytest.fixture
def old_format_script(valid_frame_zero, old_format_scenes):
    """Script in old format (before Pieza 39) — no music_prompt, recording_format."""
    return Script(
        session_id="test_session",
        idea_id="idea_123",
        title="Test script",
        angle="Opens with problem, narrows to solution",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=valid_frame_zero,
        scenes=old_format_scenes,
        sources=["Test source"],
    )


@pytest.fixture
def mock_brand_brain():
    """Mock BrandBrain with all sections confirmed."""
    from app.tools.brand_brain.models import BrandBrain, Section

    sections = [
        Section(
            id="diagnostico",
            label="Diagnóstico",
            status="confirmado",
            content={"niche": "SaaS for SMBs"},
            citation_text="CEO said: manual data entry",
            citation_source="usuario"
        ),
        Section(
            id="icp",
            label="ICP",
            status="confirmado",
            content={"segment": "Small business owners"},
            citation_text="Market research",
            citation_source="analisis_publico"
        ),
    ]

    return BrandBrain(sections=sections)


@pytest.fixture
def mock_catalog():
    """Mock catalog with locked flag and approved idea."""
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
            niche="SaaS",
            trend_direction="alta",
            youtube_channels=10,
            avg_views=50000,
            search_volume=5000,
        ),
    )


@pytest.fixture
def valid_script(valid_frame_zero):
    """Valid Script model with blueprint fields."""
    scenes = [
        Scene(
            n=1,
            start_s=0.0,
            end_s=3.0,
            phase="hook",
            spoken_text="Hook text here.",
            shot="close-up",
            b_roll=None,
            on_screen_text="Hook",
            acting_note="Energetic start",
            sound="upbeat",
            asset_type="a_roll",
        ),
        Scene(
            n=2,
            start_s=3.0,
            end_s=7.0,
            phase="lock_in",
            spoken_text="Lock in content here.",
            shot="medium",
            b_roll=None,
            on_screen_text="Lock",
            acting_note="Serious",
            sound="test",
            asset_type="a_roll",
        ),
        Scene(
            n=3,
            start_s=7.0,
            end_s=11.0,
            phase="body_1",
            spoken_text="This is some B roll footage needed",
            shot="b-roll",
            b_roll="charts showing growth",
            on_screen_text="Growth chart",
            acting_note="Narration over visuals",
            sound="ambient",
            asset_type="stock",
            stock_query="business growth chart upward trending",
        ),
        Scene(
            n=4,
            start_s=11.0,
            end_s=14.0,
            phase="rehook",
            spoken_text="Rehook content.",
            shot="medium",
            b_roll=None,
            on_screen_text="Rehook",
            acting_note="Pause",
            sound="test",
            asset_type="a_roll",
        ),
        Scene(
            n=5,
            start_s=14.0,
            end_s=18.0,
            phase="body_2",
            spoken_text="Body two content.",
            shot="medium",
            b_roll="dashboard.png",
            on_screen_text="Body 2",
            acting_note="Excited",
            sound="test",
            asset_type="ai_image",
            visual_prompt="Blue dashboard UI on dark background",
        ),
        Scene(
            n=6,
            start_s=18.0,
            end_s=22.0,
            phase="close_cta",
            spoken_text="Call to action.",
            shot="medium",
            b_roll=None,
            on_screen_text="CTA",
            acting_note="Direct",
            sound="test",
            asset_type="a_roll",
        ),
    ]

    return Script(
        session_id="test_session",
        idea_id="idea_123",
        title="Test script",
        angle="Test angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=valid_frame_zero,
        scenes=scenes,
        sources=["Test source"],
        music_prompt="upbeat corporate electronic",
        recording_format="dynamic",
    )


# =============================================================================
# TRAP 1: Old scripts load correctly (with 5+ scenes for validation)
# =============================================================================

def test_old_script_loads_with_defaults(valid_frame_zero):
    """
    TRAP 1: Scripts saved before Pieza 39 load with default blueprint fields.
    This test verifies _row_to_script applies defaults for missing fields.
    NOTE: Script requires at least 5 scenes, so old script must have 5+ scenes.
    """
    # Simulate an old-format database row (no blueprint fields in data)
    # Must have at least 5 scenes to pass validation
    old_row = {
        "session_token": "test_session",
        "idea_id": "idea_123",
        "status": "draft",
        "data": {
            "id": "script_abc_123",
            "title": "Old script",
            "angle": "Old angle",
            "funnel_stage": "tofu",
            "target_seconds": 60,
            "frame_zero": {
                "visual": "Test visual",
                "on_screen_text": "Test text",
                "why_it_stops_the_scroll": "Test reason"
            },
            "scenes": [
                {
                    "n": 1,
                    "start_s": 0.0,
                    "end_s": 3.0,
                    "phase": "hook",
                    "spoken_text": "Test hook",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "Test",
                    "acting_note": "Test note",
                    "sound": "test"
                    # NO asset_type, stock_query, visual_prompt
                },
                {
                    "n": 2,
                    "start_s": 3.0,
                    "end_s": 7.0,
                    "phase": "lock_in",
                    "spoken_text": "Test lock",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "Lock",
                    "acting_note": "Test",
                    "sound": "test"
                },
                {
                    "n": 3,
                    "start_s": 7.0,
                    "end_s": 11.0,
                    "phase": "body_1",
                    "spoken_text": "Test body 1",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "Body 1",
                    "acting_note": "Test",
                    "sound": "test"
                },
                {
                    "n": 4,
                    "start_s": 11.0,
                    "end_s": 14.0,
                    "phase": "rehook",
                    "spoken_text": "Test rehook",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "Rehook",
                    "acting_note": "Test",
                    "sound": "test"
                },
                {
                    "n": 5,
                    "start_s": 14.0,
                    "end_s": 18.0,
                    "phase": "body_2",
                    "spoken_text": "Test body 2",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "Body 2",
                    "acting_note": "Test",
                    "sound": "test"
                },
                {
                    "n": 6,
                    "start_s": 18.0,
                    "end_s": 22.0,
                    "phase": "close_cta",
                    "spoken_text": "Test CTA",
                    "shot": "medium",
                    "b_roll": None,
                    "on_screen_text": "CTA",
                    "acting_note": "Test",
                    "sound": "test"
                },
            ],
            "audit": [],
            "sources": ["Test source"],
            "timestamp": "2024-01-15T10:00:00+00:00",
            # NO music_prompt, recording_format
        }
    }

    # This should NOT return None (trap: missing fields cause silent failure)
    script = _row_to_script(old_row)

    assert script is not None, "Old script should load without error"
    assert script.id == "script_abc_123"
    assert script.title == "Old script"

    # Verify blueprint fields have sensible defaults - check first scene
    assert len(script.scenes) == 6
    scene = script.scenes[0]

    # Scene blueprint defaults
    assert scene.asset_type == "a_roll", "asset_type defaults to a_roll"
    assert scene.stock_query is None, "stock_query defaults to None"
    assert scene.visual_prompt is None, "visual_prompt defaults to None"

    # Script blueprint defaults
    assert script.music_prompt == "", "music_prompt defaults to empty string"
    assert script.recording_format == "selfie_natural", "recording_format defaults to selfie_natural"


# =============================================================================
# TRAP 2: Blueprint fields survive round-trip (save -> load)
# =============================================================================

def test_blueprint_fields_round_trip(tmp_path):
    """
    TRAP 2: New blueprint fields survive save/load cycle.
    If _script_to_row forgets to include them, they disappear after reload.
    """
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        # Mock working directory to temp path
        import os
        original_dir = os.getcwd()
        os.chdir(tmp_path)

        try:
            # Create script with explicit blueprint values (6 scenes to pass validation)
            frame_zero = FrameZero(
                visual="Test visual",
                on_screen_text="Test",
                why_it_stops_the_scroll="Stops scroll"
            )
            scenes = [
                Scene(
                    n=1,
                    start_s=0.0,
                    end_s=3.0,
                    phase="hook",
                    spoken_text="Test hook text",
                    shot="close-up",
                    b_roll=None,
                    on_screen_text="Hook",
                    acting_note="Energetic start",
                    sound="upbeat",
                    asset_type="a_roll",
                    stock_query=None,
                    visual_prompt=None,
                ),
                Scene(
                    n=2,
                    start_s=3.0,
                    end_s=6.0,
                    phase="lock_in",
                    spoken_text="Lock text here",
                    shot="medium",
                    b_roll=None,
                    on_screen_text="Lock",
                    acting_note="Test",
                    sound="test",
                    asset_type="a_roll",
                ),
                Scene(
                    n=3,
                    start_s=6.0,
                    end_s=9.0,
                    phase="body_1",
                    spoken_text="Body one here",
                    shot="medium",
                    b_roll=None,
                    on_screen_text="Body one",
                    acting_note="Test",
                    sound="test",
                    asset_type="stock",
                    stock_query="business chart growth",
                ),
                Scene(
                    n=4,
                    start_s=9.0,
                    end_s=12.0,
                    phase="rehook",
                    spoken_text="Rehook text",
                    shot="medium",
                    b_roll=None,
                    on_screen_text="Rehook",
                    acting_note="Test",
                    sound="test",
                    asset_type="a_roll",
                ),
                Scene(
                    n=5,
                    start_s=12.0,
                    end_s=15.0,
                    phase="body_2",
                    spoken_text="Body two here",
                    shot="medium",
                    b_roll="dashboard.png",
                    on_screen_text="Body two",
                    acting_note="Excited",
                    sound="test",
                    asset_type="ai_image",
                    visual_prompt="Blue dashboard UI on dark background",
                ),
                Scene(
                    n=6,
                    start_s=15.0,
                    end_s=18.0,
                    phase="close_cta",
                    spoken_text="CTA text here",
                    shot="medium",
                    b_roll=None,
                    on_screen_text="CTA",
                    acting_note="Direct",
                    sound="test",
                    asset_type="a_roll",
                ),
            ]
            script = Script(
                session_id="roundtrip_test",
                idea_id="rt_123",
                title="Round-trip test",
                angle="Test angle",
                funnel_stage="mofu",
                target_seconds=60,
                frame_zero=frame_zero,
                scenes=scenes,
                sources=["Test"],
                music_prompt="upbeat corporate electronic",
                recording_format="dynamic",
            )

            # Save
            _save_script(script)

            # Load
            loaded = _check_script("roundtrip_test", "rt_123")

            # Verify script-level blueprint fields
            assert loaded.music_prompt == "upbeat corporate electronic"
            assert loaded.recording_format == "dynamic"

            # Verify scene-level blueprint fields
            assert loaded.scenes[0].asset_type == "a_roll"
            assert loaded.scenes[0].stock_query is None

            assert loaded.scenes[2].asset_type == "stock"
            assert loaded.scenes[2].stock_query == "business chart growth"

            assert loaded.scenes[4].asset_type == "ai_image"
            assert loaded.scenes[4].visual_prompt == "Blue dashboard UI on dark background"

        finally:
            os.chdir(original_dir)


# =============================================================================
# Duration Estimation Tests
# =============================================================================

def test_duration_estimated_from_spoken_text(mock_brand_brain, mock_catalog, tmp_path):
    """
    Pieza 39: Duration is estimated from spoken_text word count.
    Formula: words / 2.5 words per second, with 1 second minimum.
    """
    import asyncio
    os.chdir(tmp_path)

    # Mock Gemini response with scenes of known word counts
    mock_response = Mock()
    mock_response.text = json.dumps({
        "title": "Duration test",
        "angle": "Test",
        "target_seconds": 60,
        "music_prompt": "upbeat electronic",
        "recording_format": "selfie_natural",
        "frame_zero": {
            "visual": "Test",
            "on_screen_text": "Test",
            "why_it_stops_the_scroll": "Test"
        },
        "scenes": [
            {
                "phase": "hook",
                # 5 words -> 5/2.5 = 2 seconds
                "spoken_text": "This is a test hook",
                "shot": "close-up",
                "b_roll": None,
                "on_screen_text": "Test",
                "acting_note": "Test",
                "sound": "upbeat",
                "asset_type": "a_roll",
                "stock_query": None,
                "visual_prompt": None,
            },
            {
                "phase": "lock_in",
                # 10 words -> 10/2.5 = 4 seconds
                "spoken_text": "This is a longer scene with ten words total here",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Lock in",
                "acting_note": "Test",
                "sound": "test",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_1",
                # 11 words -> 11/2.5 = 4.4 seconds
                "spoken_text": "This scene has fifteen words in total count here and now",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Body one",
                "acting_note": "Test",
                "sound": "test",
                "asset_type": "stock",
                "stock_query": "professional office setting",
            },
            {
                "phase": "rehook",
                # 1 word -> max(1, 1/2.5) = 1 sec (minimum)
                "spoken_text": "Pause.",
                "shot": "close-up",
                "b_roll": None,
                "on_screen_text": "Rehook",
                "acting_note": "Test",
                "sound": "test",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_2",
                # 5 words -> 5/2.5 = 2 seconds
                "spoken_text": "This is body two",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Body two",
                "acting_note": "Test",
                "sound": "test",
                "asset_type": "ai_image",
                "visual_prompt": "Blue tech background abstract",
            },
            {
                "phase": "close_cta",
                # 3 words -> 3/2.5 = 1.2 seconds
                "spoken_text": "Sign up now",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "CTA",
                "acting_note": "Test",
                "sound": "test",
                "asset_type": "a_roll",
            },
        ],
        "sources": ["Test source"]
    })

    async def run_test():
        from app.catalog.ideas import _check_catalog_cache as load_catalog

        with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
             patch("app.catalog.ideas._check_catalog_cache") as mock_catalog_fn, \
             patch("vertexai.generative_models.GenerativeModel") as mock_model_class, \
             patch("app.scripting.scripts._get_script_client", return_value=None):
            mock_get_brain.return_value = mock_brand_brain
            mock_catalog_fn.return_value = mock_catalog

            mock_model = AsyncMock()
            mock_model_class.return_value = mock_model
            mock_model.generate_content_async.return_value = mock_response

            result = await generate_script(
                session_id="duration_test",
                idea_id="idea_123",
                interview_transcript="Test transcript",
                source_mode="brand_brain"
            )

            # Verify hook: 5 words / 2.5 = 2 seconds
            hook = result.scenes[0]
            assert hook.phase == "hook"
            expected_hook_duration = max(1.0, 5 / 2.5)
            assert hook.duration_s == pytest.approx(expected_hook_duration, 0.1)

            # Verify lock_in: 10 words / 2.5 = 4 seconds
            lock_in = result.scenes[1]
            expected_lock_duration = 10 / 2.5
            assert lock_in.duration_s == pytest.approx(expected_lock_duration, 0.1)

            # Verify body_1: 11 words / 2.5 = 4.4 seconds ("This scene has fifteen words in total count here and now" has 11 words)
            body_1 = result.scenes[2]
            expected_body1_duration = 11 / 2.5
            assert body_1.duration_s == pytest.approx(expected_body1_duration, 0.1)

            # Verify rehook: 1 word -> minimum 1 second (not 0.4)
            rehook = result.scenes[3]
            assert rehook.duration_s == pytest.approx(1.0, 0.1)

            # Verify total timeline is correct
            # Hook: 2 + Lock: 4 + Body1: 4.4 + Rehook: 1 + Body2: 2 + CTA: ~1.2 = 14.6
            total_expected = 2 + 4 + (11/2.5) + 1 + (5/2.5) + max(1.0, 3/2.5)
            assert result.actual_seconds == pytest.approx(total_expected, 0.1)

    asyncio.run(run_test())


# =============================================================================
# Blueprint Field Validation
# =============================================================================

def test_scene_asset_type_validation(valid_frame_zero):
    """Scene asset_type accepts only valid values."""
    # Valid values
    for asset_type in ["a_roll", "stock", "ai_image", "ai_video", "motion_graphic"]:
        scene = Scene(
            n=1,
            start_s=0.0,
            end_s=3.0,
            phase="hook",
            spoken_text="Test",
            shot="medium",
            on_screen_text="Test",
            acting_note="Test",
            sound="Test",
            asset_type=asset_type,
        )
        assert scene.asset_type == asset_type


def test_script_recording_format_validation(valid_frame_zero):
    """Script recording_format accepts only valid values."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
        Scene(n=2, start_s=3.0, end_s=6.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
        Scene(n=3, start_s=6.0, end_s=9.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
        Scene(n=4, start_s=9.0, end_s=12.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
        Scene(n=5, start_s=12.0, end_s=15.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
        Scene(n=6, start_s=15.0, end_s=18.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="T", acting_note="test", sound="test"),
    ]

    # Valid values
    for fmt in ["selfie_natural", "pov", "dramatization", "teleprompter_clean", "dynamic"]:
        script = Script(
            session_id="test",
            idea_id="idea_123",
            title="Test",
            angle="test",
            funnel_stage="tofu",
            target_seconds=60,
            frame_zero=valid_frame_zero,
            scenes=scenes,
            recording_format=fmt,
        )
        assert script.recording_format == fmt


# =============================================================================
# Regenerate Scene with Blueprint Fields
# =============================================================================

@pytest.mark.asyncio
async def test_regenerate_scene_preserves_blueprint_fields(valid_script, tmp_path):
    """
    Regenerating a scene should preserve existing blueprint fields
    if the model doesn't return new values.
    """
    import os
    os.chdir(tmp_path)

    # Set up blueprint fields on the first scene
    valid_script.scenes[0].asset_type = "stock"
    valid_script.scenes[0].stock_query = "original stock query"
    valid_script.scenes[0].visual_prompt = "original visual prompt"
    valid_script.recording_format = "dramatization"

    mock_response = Mock()
    # Model returns scene WITHOUT blueprint fields
    mock_response.text = json.dumps({
        "spoken_text": "Regenerated text",
        "shot": "close-up",
        "b_roll": None,
        "on_screen_text": "Regenerated",
        "acting_note": "New note",
        "sound": "upbeat"
        # NO asset_type, stock_query, visual_prompt
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
        mock_cat_cache.return_value.id = "idea_123"

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        _save_script(valid_script)

        result = await regenerate_scene(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            instruction="Make it punchier"
        )

        # Text should be updated
        assert result.scenes[0].spoken_text == "Regenerated text"

        # Blueprint fields should be preserved from original
        assert result.scenes[0].asset_type == "stock"
        assert result.scenes[0].stock_query == "original stock query"
        assert result.scenes[0].visual_prompt == "original visual prompt"


@pytest.mark.asyncio
async def test_regenerate_scene_updates_blueprint_fields(valid_script, tmp_path):
    """
    Regenerating a scene should use new blueprint fields if model returns them.
    """
    import os
    os.chdir(tmp_path)

    # Set up original blueprint fields
    valid_script.scenes[0].asset_type = "a_roll"
    valid_script.scenes[0].stock_query = None
    valid_script.scenes[0].visual_prompt = None

    mock_response = Mock()
    # Model returns scene WITH new blueprint fields
    mock_response.text = json.dumps({
        "spoken_text": "Now showing B-roll footage",
        "shot": "b-roll cutaway",
        "b_roll": "Charts showing data",
        "on_screen_text": "Data viz",
        "acting_note": "Voice over",
        "sound": "ambient",
        "asset_type": "ai_video",
        "stock_query": "business data visualization charts",
        "visual_prompt": "Generate animated bar chart with blue gradient"
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
        mock_cat_cache.return_value.id = "idea_123"

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        _save_script(valid_script)

        result = await regenerate_scene(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            instruction="Add B-roll visuals"
        )

        # New blueprint fields should be applied
        assert result.scenes[0].asset_type == "ai_video"
        assert result.scenes[0].stock_query == "business data visualization charts"
        assert result.scenes[0].visual_prompt == "Generate animated bar chart with blue gradient"
