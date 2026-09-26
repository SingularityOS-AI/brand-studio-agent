"""Tests for PIEZA 94: Rebote de auditoría frontend - Editing Studio & Preview fixes."""

import json
import shutil
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITING_JS = REPO_ROOT / "app" / "static" / "editing.js"
PREVIEW_JS = REPO_ROOT / "app" / "static" / "editing_preview.js"

NODE_AVAILABLE = shutil.which("node") is not None


def run_node_code(code: str) -> str:
    proc = subprocess.run(
        ["node", "-e", code],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_node_check_both_files():
    """1. node --check of editing.js and editing_preview.js."""
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"

    res1 = subprocess.run([node_bin, "--check", str(EDITING_JS)], capture_output=True, text=True)
    assert res1.returncode == 0, f"node --check editing.js failed: {res1.stderr}"

    res2 = subprocess.run([node_bin, "--check", str(PREVIEW_JS)], capture_output=True, text=True)
    assert res2.returncode == 0, f"node --check editing_preview.js failed: {res2.stderr}"


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_node_layout_text_cases():
    """2. Node require editing_preview.js and test layoutText behavior."""
    node_script = """
    const { layoutText } = require('./app/static/editing_preview.js');

    const resFz = layoutText("frame_zero", "Stop wasting money on ads that never convert");
    const resHero = layoutText("hero", "entrepreneurship");
    const resBlock = layoutText("block", ["First line of text", "Second shorter line"]);

    console.log(JSON.stringify({ resFz, resHero, resBlock }));
    """

    out = run_node_code(node_script)
    data = json.loads(out)
    res_fz = data["resFz"]
    res_hero = data["resHero"]

    # FrameZero: 3 lines
    assert len(res_fz["lines"]) == 3, f"Expected 3 lines, got {len(res_fz['lines'])}"
    max_len_fz = max(len(line) for line in res_fz["lines"])
    expected_fz_font = min(110, int(900 / (0.58 * max_len_fz)))
    assert res_fz["fontPx"] == expected_fz_font, f"Expected fontPx {expected_fz_font}, got {res_fz['fontPx']}"

    # Hero: 1 word of len 16
    expected_hero_font = min(170, int(900 / (0.58 * 16)))
    assert res_hero["fontPx"] == expected_hero_font, f"Expected hero fontPx {expected_hero_font}, got {res_hero['fontPx']}"


def test_ffmpeg_dress_parity():
    """2b. Parity test with render_service.ffmpeg_dress.layout_text (xfail if P92 not implemented)."""
    try:
        from render_service import ffmpeg_dress
        if not hasattr(ffmpeg_dress, "layout_text"):
            pytest.xfail("P92 render_service.ffmpeg_dress.layout_text does not exist yet")
    except (ImportError, ModuleNotFoundError):
        pytest.xfail("P92 render_service.ffmpeg_dress does not exist yet")

    test_cases = [
        ("frame_zero", "Stop wasting money on ads that never convert"),
        ("hero", "entrepreneurship"),
        ("block", ["Short line", "Longer block of subtitle text"]),
        ("frame_zero", "Simple test"),
        ("hero", "test"),
    ]

    node_bin = shutil.which("node")
    assert node_bin is not None

    for kind, text_in in test_cases:
        text_json = json.dumps(text_in)
        node_script = f"""
        const {{ layoutText }} = require('./app/static/editing_preview.js');
        console.log(JSON.stringify(layoutText('{kind}', {text_json})));
        """
        out = run_node_code(node_script)
        node_res = json.loads(out)

        py_lines, py_font_px = ffmpeg_dress.layout_text(kind, text_in)
        assert node_res["fontPx"] == py_font_px
        assert node_res["lines"] == py_lines


def test_static_assertions_p94_rebote():
    """3. Static assertions for editing_preview.js and editing.js."""
    preview_content = PREVIEW_JS.read_text(encoding="utf-8")
    editing_content = EDITING_JS.read_text(encoding="utf-8")

    # 3a. editing_preview.js does NOT contain 'blur(20px) scaleX'
    assert "blur(20px) scaleX" not in preview_content, "editing_preview.js must NOT contain blur(20px) scaleX"

    # 3b. editing.js uses !settings.music_muted (or equivalent) for checkbox and compares storage_path
    assert "!settings.music_muted" in editing_content or "settings.music_muted ?" in editing_content, (
        "editing.js must handle music checkbox properly"
    )
    assert "storage_path" in editing_content, "editing.js must compare storage_path"

    # 3c. editing.js contains required error strings & notices
    assert "Updating your raw cut" in editing_content, "editing.js must contain 'Updating your raw cut'"
    assert "payment_error" in editing_content, "editing.js must contain 'payment_error'"
    assert "too_many_ai_calls" in editing_content, "editing.js must contain 'too_many_ai_calls'"

    # 3d. editing.js has no alert( or eval(
    assert "alert(" not in editing_content, "editing.js must NOT contain alert("
    assert "eval(" not in editing_content, "editing.js must NOT contain eval("
