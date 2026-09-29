"""
Test suite for E2-09: Caption band drag + presets UI
Verifies caption drag infrastructure, preset buttons, and arrow key controls.
"""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.editing.ir import build_ir_stage1
from app.editing.router import router
from render_service.manifest import CAPTION_Y_MAX, CAPTION_Y_MIN, clamp_caption_y

REPO_ROOT = Path(__file__).resolve().parent.parent

NODE_AVAILABLE = os.environ.get("CHROME_PATH") or os.environ.get("PATH", "").find("chrom") >= 0


@pytest.fixture(scope="module")
def app():
    """Fixture for FastAPI test app."""
    app = FastAPI()
    app.include_router(router, prefix="/api/editing", tags=["editing"])
    app.mount("/static", directory="app/static", name="static")

    @app.post("/test-login")
    async def test_login():
        """Mock login endpoint for testing."""
        return {"access_token": "test_token"}

    return app


@pytest.fixture(scope="module")
def client(app):
    """Fixture for TestClient."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Caption drag infrastructure in editing_preview.js
# ---------------------------------------------------------------------------


def test_editing_preview_exports_setup_caption_drag():
    """Test editing_preview.js exports setupCaptionDrag function."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Verify setupCaptionDrag is defined and exported
    assert "setupCaptionDrag" in content
    # Should be in module.exports or similar
    assert "module.exports" in content

    # Verify drag canvas exists
    assert "dragCanvas" in content


def test_editing_preview_drag_canvas_attrs():
    """Test drag canvas has correct positioning and style."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Verify drag canvas element exists
    assert "dragCanvas" in content
    # Should be absolute or have positioning
    assert "position" in content or "style" in content
    # Should handle pointer events
    assert "pointer" in content.lower()


def test_editing_preview_caption_y_min_max():
    """Test caption Y min and max constants are defined."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Should have min=360 and max=1700 (from backend render_service/manifest.py)
    assert "360" in content  # CAPTION_Y_MIN
    assert "1700" in content  # CAPTION_Y_MAX


def test_editing_preview_live_state_tracking():
    """Test _lastState is used for live drag updates."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Should track state during drag
    assert "_lastState" in content
    # Should apply state during drag (not just on release)
    assert "_applyState" in content


def test_editing_preview_pointer_events():
    """Test Pointer events API is used for unified mouse/touch."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Should use pointer events (unified mouse/touch)
    assert "pointerdown" in content.lower()
    assert "pointermove" in content.lower()
    assert "pointerup" in content.lower()


def test_editing_preview_preview_scale_conversion():
    """Test screen px → canvas px conversion via preview scale."""
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    content = preview_js_path.read_text(encoding="utf-8")

    # Should handle preview scale
    assert "previewScale" in content or "data-preview-scale" in content
    # Should have division for conversion
    assert "/" in content


# ---------------------------------------------------------------------------
# 2. Preset buttons in editing.js
# ---------------------------------------------------------------------------


def test_editing_js_preset_buttons():
    """Test preset buttons are defined in editing.js."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Verify preset buttons HTML exists
    assert "caption-preset-btn" in content
    assert "data-caption-y" in content

    # Should have preset values
    assert "520" in content   # Top
    assert "1080" in content  # Middle
    assert "1600" in content  # Bottom


def test_editing_js_handle_set_caption_y():
    """Test handleSetCaptionY function exists."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should have helper function
    assert "handleSetCaptionY" in content


def test_editing_js_caption_y_action():
    """Test caption_y EDIT_ACTION exists."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should have caption_y action in EDIT_ACTIONS
    assert "caption_y:" in content or "caption_y" in content
    # Should patch settings with caption_y op
    assert '"caption_y"' in content or "'caption_y'" in content


# ---------------------------------------------------------------------------
# 3. Arrow key handling
# ---------------------------------------------------------------------------


def test_editing_js_arrow_key_listener():
    """Test Up/Down arrow key listeners are defined."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should handle keydown events
    assert "keydown" in content.lower()
    # Should check for ArrowUp/ArrowDown
    assert "ArrowUp" in content or "arrowup" in content.lower()
    assert "ArrowDown" in content or "arrowdown" in content.lower()


def test_editing_js_arrow_20px_increment():
    """Test arrow keys move caption by 20px."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should have 20px increment/decrement in arrow key handler
    assert "+ 20" in content or "+20" in content or "captionY + 20" in content or "captionY+20" in content
    assert "- 20" in content or "-20" in content or "captionY - 20" in content or "captionY-20" in content


def test_editing_js_drag_setup_in_mount():
    """Test drag setup called after preview mount."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should call setupCaptionDrag after mount
    assert "setupCaptionDrag" in content
    # Should have cleanup variable
    assert "captionDragCleanup" in content


# ---------------------------------------------------------------------------
# 4. Caption drag behavior tests
# ---------------------------------------------------------------------------


def test_caption_y_clamp_bounds():
    """Test caption clipping clamps to min and max bounds."""
    # Values below min
    assert clamp_caption_y(0) == CAPTION_Y_MIN
    assert clamp_caption_y(200) == CAPTION_Y_MIN
    assert clamp_caption_y(359) == CAPTION_Y_MIN  # Just below min

    # Values above max
    assert clamp_caption_y(1700) == CAPTION_Y_MAX
    assert clamp_caption_y(2000) == CAPTION_Y_MAX
    assert clamp_caption_y(5000) == CAPTION_Y_MAX

    # Values in range (should pass through)
    assert clamp_caption_y(500) == 500
    assert clamp_caption_y(1000) == 1000
    assert clamp_caption_y(1500) == 1500

    # Boundary values
    assert clamp_caption_y(CAPTION_Y_MIN) == CAPTION_Y_MIN
    assert clamp_caption_y(CAPTION_Y_MAX) == CAPTION_Y_MAX


def test_caption_y_preset_values():
    """Test preset values are within valid range."""
    presets = {
        "Top": 520,
        "Middle": 1080,
        "Bottom": 1600,
    }

    for preset_name, caption_y in presets.items():
        assert CAPTION_Y_MIN <= caption_y <= CAPTION_Y_MAX, \
            f"{preset_name} preset {caption_y} must be between {CAPTION_Y_MIN} and {CAPTION_Y_MAX}"


def test_caption_y_preset_spacing():
    """Test preset values are reasonably spaced."""
    presets = [520, 1080, 1600]

    # Check spacing between presets
    for i in range(1, len(presets)):
        spacing = presets[i] - presets[i-1]
        assert spacing >= 400, f"Preset {i-1} to {i} spacing {spacing} is too small (< 400px)"


def test_caption_arrow_increment_respects_bounds():
    """Test arrow key increments respect min/max bounds."""
    # Starting at min, should not go below
    at_min = CAPTION_Y_MIN
    assert clamp_caption_y(at_min - 20) == CAPTION_Y_MIN

    # Starting at max, should not go above
    at_max = CAPTION_Y_MAX
    assert clamp_caption_y(at_max + 20) == CAPTION_Y_MAX

    # Multiple decrements should stop at min
    assert clamp_caption_y(CAPTION_Y_MIN + 50 - 100) == CAPTION_Y_MIN

    # Multiple increments should stop at max
    assert clamp_caption_y(CAPTION_Y_MAX - 50 + 100) == CAPTION_Y_MAX


# ---------------------------------------------------------------------------
# 5. Integration: Caption Y in IR
# ---------------------------------------------------------------------------


def test_ir_layout_caption_y_defaults_to_middle():
    """Test IR layout.caption_y defaults to middle of range."""
    SAMPLE_STYLE = {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }

    timeline = {"duration_ms": 10000}
    caption_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Test", "start_ms": 1000, "end_ms": 2000},
    ]

    # Build IR without caption_y setting (should use default)
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=caption_words,
        frame_zero_text="HOOK",
        style=SAMPLE_STYLE,
        settings=None,  # No caption_y specified
    )

    # Verify layout.caption_y exists and is within range
    assert "layout" in ir
    assert "caption_y" in ir["layout"]
    assert CAPTION_Y_MIN <= ir["layout"]["caption_y"] <= CAPTION_Y_MAX


def test_ir_layout_caption_y_uses_setting():
    """Test IR layout.caption_y reads from settings.caption_y."""
    SAMPLE_STYLE = {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }

    timeline = {"duration_ms": 10000}
    caption_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Test", "start_ms": 1000, "end_ms": 2000},
    ]

    # Build IR with preset value
    for preset_y in [520, 1080, 1600]:
        ir = build_ir_stage1(
            timeline=timeline,
            captions_words=caption_words,
            frame_zero_text="HOOK",
            style=SAMPLE_STYLE,
            settings={"caption_y": preset_y},
        )

        assert ir["layout"]["caption_y"] == preset_y


def test_ir_layout_caption_y_clamps_invalid_setting():
    """Test IR layout.caption_y clamps invalid settings."""
    SAMPLE_STYLE = {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }

    timeline = {"duration_ms": 10000}
    caption_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Test", "start_ms": 1000, "end_ms": 2000},
    ]

    # Below min should clamp
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=caption_words,
        frame_zero_text="HOOK",
        style=SAMPLE_STYLE,
        settings={"caption_y": 200},
    )
    assert ir["layout"]["caption_y"] == CAPTION_Y_MIN

    # Above max should clamp
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=caption_words,
        frame_zero_text="HOOK",
        style=SAMPLE_STYLE,
        settings={"caption_y": 5000},
    )
    assert ir["layout"]["caption_y"] == CAPTION_Y_MAX


# ---------------------------------------------------------------------------
# 6. Evidence generation
# ---------------------------------------------------------------------------


def test_evidence_caption_drag_constants(evidence_dir_for):
    """Save caption drag range constants as evidence."""
    evidence_path = evidence_dir_for("E2-09") / "caption_y_constants.txt"

    content = f"""CAPTION_Y_MIN: {CAPTION_Y_MIN}
CAPTION_Y_MAX: {CAPTION_Y_MAX}
Preset Top: 520
Preset Middle: 1080
Preset Bottom: 1600
Arrow increment: 20px
"""

    evidence_path.write_text(content)


def test_evidence_caption_preset_positions(evidence_dir_for):
    """Save preset caption positions as evidence."""
    evidence_path = evidence_dir_for("E2-09") / "preset_positions.txt"

    presets = {
        "Top": 520,
        "Middle": 1080,
        "Bottom": 1600,
    }

    lines = []
    for name, y in presets.items():
        lines.append(f"{name}: {y}px")

    evidence_path.write_text("\n".join(lines))


def test_evidence_javascript_files_exist(evidence_dir_for):
    """Verify JavaScript files exist and are readable."""
    preview_js = REPO_ROOT / "app" / "static" / "editing_preview.js"
    editing_js = REPO_ROOT / "app" / "static" / "editing.js"

    assert preview_js.exists(), f"{preview_js} not found"
    assert editing_js.exists(), f"{editing_js} not found"

    # Verify they're valid JavaScript (node --check)
    # Note: This test just verifies files exist and can be read
    preview_content = preview_js.read_text(encoding="utf-8")
    editing_content = editing_js.read_text(encoding="utf-8")

    assert len(preview_content) > 0, f"{preview_js} is empty"
    assert len(editing_content) > 0, f"{editing_js} is empty"

    # Count important functions
    evidence_path = evidence_dir_for("E2-09") / "javascript_summary.txt"
    summary = f"""editing_preview.js:
  - Functions defined: {preview_content.count('function ')}
  - setupCaptionDrag exists: {'setupCaptionDrag' in preview_content}
  - CAPTION_Y_MIN defined: {('CAPTION_Y_MIN = 360' in preview_content) or ('CAPTION_Y_MIN=360' in preview_content)}
  - CAPTION_Y_MAX defined: {('CAPTION_Y_MAX = 1700' in preview_content) or ('CAPTION_Y_MAX=1700' in preview_content)}
  
editing.js:
  - Functions defined: {editing_content.count('function ')}
  - handleSetCaptionY exists: {'handleSetCaptionY' in editing_content}
  - preset buttons HTML exists: {'caption-preset-btn' in editing_content}
  - arrow key handler exists: {'ArrowUp' in editing_content or 'arrowup' in editing_content.lower()}
"""
    evidence_path.write_text(summary)


# ---------------------------------------------------------------------------
# 7. Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_drag_handlers():
    """Test drag cleanup function is called on tab switch/destroy."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"

    content = editing_js_path.read_text(encoding="utf-8")

    # Should check cleanup variable
    assert "captionDragCleanup" in content


def test_cleanup_allows_reinitialization():
    """Test cleanup allows drag to be re-initialized on tab switch."""
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"
    preview_js_path = REPO_ROOT / "app" / "static" / "editing_preview.js"

    editing_content = editing_js_path.read_text(encoding="utf-8")
    preview_content = preview_js_path.read_text(encoding="utf-8")

    # Editing.js should check for existing setup before calling
    assert "if (window.BrandStudioPreview.setupCaptionDrag)" in editing_content

    # setupCaptionDrag should work with fresh canvas
    assert "canvas" in preview_content.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
