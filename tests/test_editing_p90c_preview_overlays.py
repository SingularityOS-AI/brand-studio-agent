"""Tests for PIEZA 90C - editing_preview.js preview layer overlays & node parity."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

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
def test_state_at_overlays_fading_and_active_filtering() -> None:
    ir = {
        "duration_ms": 10000,
        "frame_zero": None,
        "captions": [],
        "zoom_keys": [],
        "transitions": [],
        "overlays": [
            {
                "id": "ov1",
                "kind": "onscreen_text",
                "asset": None,
                "text": "Texto prueba",
                "start_ms": 2000,
                "end_ms": 4000,
                "x": 90,
                "y": 1300,
                "w": 900,
                "h": 200,
                "anim": "pop",
                "accent": True,
            },
            {
                "id": "ov2",
                "kind": "card_lower_third",
                "asset": None,
                "text": "Texto dos",
                "start_ms": 5000,
                "end_ms": 7000,
                "x": 90,
                "y": 1300,
                "w": 900,
                "h": 200,
                "anim": "pop",
                "accent": False,
            },
        ],
        "sfx": [],
        "style": {
            "font": "Inter",
            "text": "#FFFFFF",
            "accent": "#FFFF00",
            "outline": "#000000",
        },
    }

    ir_json = json.dumps(ir)
    timestamps = [2100, 3000, 3925, 4000, 6000]

    node_script = (
        f"const {{ stateAt }} = require('./app/static/editing_preview.js');\n"
        f"const ir = {ir_json};\n"
        f"const ts = {json.dumps(timestamps)};\n"
        f"const res = ts.map(t => stateAt(ir, t));\n"
        f"console.log(JSON.stringify(res));\n"
    )

    out = run_node_code(node_script)
    res = json.loads(out)
    st_2100, st_3000, st_3925, st_4000, st_6000 = res

    # 1. t=2100: ov1 active, opacity approx 0.5
    ovs_2100 = st_2100["overlays"]
    assert len(ovs_2100) == 1
    assert ovs_2100[0]["id"] == "ov1"
    assert abs(ovs_2100[0]["opacity"] - 0.5) < 1e-4

    # 2. t=3000: ov1 active, opacity == 1.0
    ovs_3000 = st_3000["overlays"]
    assert len(ovs_3000) == 1
    assert ovs_3000[0]["id"] == "ov1"
    assert abs(ovs_3000[0]["opacity"] - 1.0) < 1e-4

    # 3. t=3925: ov1 active, opacity approx 0.5
    ovs_3925 = st_3925["overlays"]
    assert len(ovs_3925) == 1
    assert ovs_3925[0]["id"] == "ov1"
    assert abs(ovs_3925[0]["opacity"] - 0.5) < 1e-4

    # 4. t=4000: ov1 not active (start_ms <= t < end_ms) -> overlays empty
    ovs_4000 = st_4000["overlays"]
    assert len(ovs_4000) == 0

    # 5. t=6000: ov2 active only
    ovs_6000 = st_6000["overlays"]
    assert len(ovs_6000) == 1
    assert ovs_6000[0]["id"] == "ov2"
    assert abs(ovs_6000[0]["opacity"] - 1.0) < 1e-4


def test_static_file_checks() -> None:
    content = JS_FILE.read_text(encoding="utf-8")
    assert "innerHTML" not in content, "editing_preview.js must not contain innerHTML"
    assert "eval(" not in content, "editing_preview.js must not contain eval("
    assert "new Function" not in content, "editing_preview.js must not contain new Function"
    assert "textContent" in content, "editing_preview.js must contain textContent"
    assert "protocol" in content, "editing_preview.js must contain protocol"
