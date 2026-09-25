"""Tests for PIEZA 83 - editing_preview.js preview layer contract & node parity."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from render_service.ffmpeg_dress import zoom_at
from render_service.manifest import ZoomKey

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_FILE = REPO_ROOT / "app" / "static" / "editing_preview.js"

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
def test_node_syntax_check() -> None:
    res = subprocess.run(
        ["node", "--check", str(JS_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed: {res.stderr}"


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_ffmpeg_zoom_parity() -> None:
    sets_data = [
        # Set 1: punch_in
        [
            ZoomKey(t_ms=0, scale=1.0, cx=0.5, cy=0.5, ease="linear"),
            ZoomKey(t_ms=500, scale=1.2, cx=0.5, cy=0.5, ease="out"),
            ZoomKey(t_ms=3000, scale=1.2, cx=0.5, cy=0.5, ease="linear"),
        ],
        # Set 2: slow_push
        [
            ZoomKey(t_ms=0, scale=1.0, cx=0.5, cy=0.5, ease="linear"),
            ZoomKey(t_ms=4000, scale=1.1, cx=0.8, cy=0.3, ease="out"),
        ],
        # Set 3: zoom_through
        [
            ZoomKey(t_ms=0, scale=1.0, cx=0.5, cy=0.5, ease="linear"),
            ZoomKey(t_ms=2000, scale=1.5, cx=0.2, cy=0.7, ease="out"),
            ZoomKey(t_ms=4000, scale=1.0, cx=0.5, cy=0.5, ease="out"),
        ],
    ]

    t_steps = [i * 125 for i in range(40)]

    for keys in sets_data:
        keys_json = json.dumps([k.model_dump() for k in keys])
        ts_json = json.dumps(t_steps)

        node_script = (
            f"const {{ zoomAt }} = require('./app/static/editing_preview.js');\n"
            f"const keys = {keys_json};\n"
            f"const ts = {ts_json};\n"
            f"const res = ts.map(t => zoomAt(keys, t));\n"
            f"console.log(JSON.stringify(res));\n"
        )

        out = run_node_code(node_script)
        node_results = json.loads(out)

        for t_ms, node_res in zip(t_steps, node_results):
            py_scale, py_cx, py_cy = zoom_at(keys, t_ms)
            assert abs(py_scale - node_res["scale"]) < 1e-6, (
                f"Mismatch scale at t={t_ms}: py={py_scale}, node={node_res['scale']}"
            )
            assert abs(py_cx - node_res["cx"]) < 1e-6, (
                f"Mismatch cx at t={t_ms}: py={py_cx}, node={node_res['cx']}"
            )
            assert abs(py_cy - node_res["cy"]) < 1e-6, (
                f"Mismatch cy at t={t_ms}: py={py_cy}, node={node_res['cy']}"
            )


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_state_at() -> None:
    ir = {
        "duration_ms": 10000,
        "frame_zero": {"text": "FRAME ZERO HOOK", "start_ms": 0, "end_ms": 1500},
        "captions": [
            {
                "start_ms": 1500,
                "end_ms": 3500,
                "size": "hero",
                "emphasis": [0],
                "lines": [
                    [
                        {"text": "HI", "start_ms": 1500, "end_ms": 2500},
                        {"text": "WORLD", "start_ms": 2500, "end_ms": 3500},
                    ]
                ],
            },
            {
                "start_ms": 3500,
                "end_ms": 6000,
                "size": "block",
                "emphasis": [1],
                "lines": [
                    [
                        {"text": "BUILDING", "start_ms": 3500, "end_ms": 4500},
                        {"text": "SOMETHING", "start_ms": 4500, "end_ms": 6000},
                    ]
                ],
            },
        ],
        "zoom_keys": [],
        "transitions": [
            {"at_ms": 1000, "type": "flash", "dur_ms": 500},
            {"at_ms": 7000, "type": "whip", "dur_ms": 400},
        ],
        "overlays": [],
        "sfx": [],
        "style": {
            "font": "Inter",
            "text": "#FFFFFF",
            "accent": "#FFFF00",
            "outline": "#000000",
        },
    }

    ir_json = json.dumps(ir)
    timestamps = [500, 1000, 1500, 2800, 7000]
    node_script = (
        f"const {{ stateAt }} = require('./app/static/editing_preview.js');\n"
        f"const ir = {ir_json};\n"
        f"const ts = {json.dumps(timestamps)};\n"
        f"const res = ts.map(t => stateAt(ir, t));\n"
        f"console.log(JSON.stringify(res));\n"
    )

    out = run_node_code(node_script)
    res = json.loads(out)
    st_500, st_1000, st_1500, st_2800, st_7000 = res

    # 1. t=500: frameZero active, no caption, flash=0
    assert st_500["frameZero"] == "FRAME ZERO HOOK"
    assert st_500["caption"] is None
    assert st_500["flash"] == 0

    # 2. t=1000: frameZero active, flash=0.8
    assert st_1000["frameZero"] == "FRAME ZERO HOOK"
    assert abs(st_1000["flash"] - 0.8) < 1e-6

    # 3. t=1500: frameZero null, hero caption active, "HI" active
    assert st_1500["frameZero"] is None
    assert st_1500["caption"]["size"] == "hero"
    assert st_1500["caption"]["lines"][0][0]["text"] == "HI"
    assert st_1500["caption"]["lines"][0][0]["active"] is True
    assert st_1500["caption"]["lines"][0][1]["text"] == "WORLD"
    assert st_1500["caption"]["lines"][0][1]["active"] is False

    # 4. t=2800: frameZero null, hero caption active, "WORLD" active
    assert st_2800["frameZero"] is None
    assert st_2800["caption"]["size"] == "hero"
    assert st_2800["caption"]["lines"][0][0]["active"] is False
    assert st_2800["caption"]["lines"][0][1]["active"] is True

    # 5. t=7000: whip transition active
    assert st_7000["blurAxis"] == "x"
    assert st_7000["blurPx"] == 20


def test_static_file_checks() -> None:
    content = JS_FILE.read_text(encoding="utf-8")
    assert "innerHTML" not in content, "editing_preview.js must not contain innerHTML"
    assert "eval(" not in content, "editing_preview.js must not contain eval("
    assert "new Function" not in content, "editing_preview.js must not contain new Function"
    assert "import " not in content, "editing_preview.js must not contain import statements"
    assert "export " not in content, "editing_preview.js must not contain export statements"
    assert "requestVideoFrameCallback" in content, "editing_preview.js must contain requestVideoFrameCallback"
    assert "textContent" in content, "editing_preview.js must contain textContent"
