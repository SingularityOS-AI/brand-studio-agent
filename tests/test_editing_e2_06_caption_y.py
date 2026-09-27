"""Tests for piece E2-06: one caption style + caption_y in the IR and both renderers.

F6 + data half of F1. Before this piece, `app/editing/ir.py` produced `size:"hero"`
giant-word caption events for the first 1.5s after frame zero; every script now
renders with a single uniform 'block' Brand Soul caption style, and the caption
band position (`caption_y`) is a setting the IR carries and both renderers
(FFmpeg's ASS `\\pos` and the browser preview's `top`) read from the same place.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.supabase_auth import supabase_auth
from app.editing.ir import build_ir_stage1, build_ir_stage2
from app.editing.router import router
from app.editing.store import _reset_local_edits
from render_service.ffmpeg_dress import build_final, write_ass
from render_service.manifest import (
    CAPTION_Y_MAX,
    CAPTION_Y_MIN,
    CaptionEvent,
    CaptionStyle,
    CaptionToken,
    Layout,
    RenderIR,
    RenderRequest,
    clamp_caption_y,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "specs" / "evidence" / "E2-06"

NODE_AVAILABLE = shutil.which("node") is not None
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

SAMPLE_STYLE = {
    "font": "Inter",
    "text": "#FFFFFF",
    "accent": "#2B4CD8",
    "outline": "#000000",
}


# ---------------------------------------------------------------------------
# 1. IR for any script has 0 hero events (build_ir_stage1 + build_ir_stage2)
# ---------------------------------------------------------------------------


def test_build_ir_stage1_never_produces_hero_right_after_frame_zero():
    """The old hero window [fz_end, fz_end+1500) now produces uniform block events."""
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Uno", "start_ms": 1600, "end_ms": 1900},
        {"id": "s1w1", "scene_n": 1, "text": "Dos", "start_ms": 2200, "end_ms": 2500},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text="HOOK",
        style=SAMPLE_STYLE,
    )
    assert ir["captions"], "expected at least one caption event"
    assert all(ev["size"] == "block" for ev in ir["captions"])
    RenderIR.model_validate(ir)


def test_build_ir_stage1_never_produces_hero_with_no_frame_zero():
    """No frame zero -> hook starts at 0; the first words used to render as hero."""
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Primera", "start_ms": 200, "end_ms": 500},
        {"id": "s1w1", "scene_n": 1, "text": "Segunda", "start_ms": 600, "end_ms": 900},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )
    assert ir["captions"]
    assert all(ev["size"] == "block" for ev in ir["captions"])
    RenderIR.model_validate(ir)


def test_build_ir_stage2_never_produces_hero():
    """build_ir_stage2 (the dressing-fresh path the router actually uses) also
    never emits a hero event, with an empty dressing plan (no scenes)."""
    timeline = {"duration_ms": 6000, "scenes": [], "settings": {}}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Stop", "start_ms": 0, "end_ms": 300},
        {"id": "s1w1", "scene_n": 1, "text": "now", "start_ms": 400, "end_ms": 700},
    ]
    res = build_ir_stage2(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
        dressing={"scenes": []},
    )
    ir = res["ir"]
    assert ir["captions"]
    assert all(ev["size"] == "block" for ev in ir["captions"])
    RenderIR.model_validate(ir)


# ---------------------------------------------------------------------------
# 2. caption_y: default, clamping, and propagation into the IR's layout
# ---------------------------------------------------------------------------


def test_clamp_caption_y_bounds():
    assert clamp_caption_y(200) == CAPTION_Y_MIN
    assert clamp_caption_y(5000) == CAPTION_Y_MAX
    assert clamp_caption_y(900) == 900
    assert clamp_caption_y(CAPTION_Y_MIN) == CAPTION_Y_MIN
    assert clamp_caption_y(CAPTION_Y_MAX) == CAPTION_Y_MAX


def test_build_ir_stage1_default_caption_y_matches_today_band():
    timeline = {"duration_ms": 3000}
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=[{"id": "s1w0", "scene_n": 1, "text": "Hi", "start_ms": 0, "end_ms": 300}],
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )
    assert ir["layout"]["caption_y"] == 1250
    RenderIR.model_validate(ir)


@pytest.mark.parametrize(
    "requested,expected",
    [(200, CAPTION_Y_MIN), (5000, CAPTION_Y_MAX), (520, 520), (1600, 1600)],
)
def test_build_ir_stage1_reads_and_clamps_settings_caption_y(requested, expected):
    timeline = {"duration_ms": 3000}
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=[{"id": "s1w0", "scene_n": 1, "text": "Hi", "start_ms": 0, "end_ms": 300}],
        frame_zero_text=None,
        style=SAMPLE_STYLE,
        settings={"caption_y": requested},
    )
    assert ir["layout"]["caption_y"] == expected
    RenderIR.model_validate(ir)


def test_build_ir_stage2_propagates_caption_y_into_layout():
    timeline = {"duration_ms": 3000, "scenes": [], "settings": {}}
    res = build_ir_stage2(
        timeline=timeline,
        captions_words=[{"id": "s1w0", "scene_n": 1, "text": "Hi", "start_ms": 0, "end_ms": 300}],
        frame_zero_text=None,
        style=SAMPLE_STYLE,
        dressing={"scenes": []},
        settings={"caption_y": 900},
    )
    assert res["ir"]["layout"]["caption_y"] == 900
    RenderIR.model_validate(res["ir"])


# ---------------------------------------------------------------------------
# 3. write_ass: caption events carry \an2\pos(540,caption_y)
# ---------------------------------------------------------------------------


def test_write_ass_caption_events_use_an2_pos_with_caption_y(tmp_path):
    tok = CaptionToken(text="HELLO", start_ms=0, end_ms=1000)
    event = CaptionEvent(start_ms=0, end_ms=1000, lines=[[tok]], size="block", emphasis=[])
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=1000,
        captions=[event],
        style=CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000"),
        layout=Layout(caption_y=777),
    )
    ass_path = tmp_path / "test.ass"
    write_ass(ir, ass_path)
    content = ass_path.read_text(encoding="utf-8-sig")
    assert r"\an2\pos(540,777)" in content


# ---------------------------------------------------------------------------
# 4. PATCH settings caption_y (router): clamped, never touches dressing
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)
client = TestClient(app)
HEADERS = {"authorization": "Bearer tok_test"}


class MockScript:
    """Minimal locked-script mock; PATCH settings needs no takes/transcripts."""

    def __init__(self) -> None:
        self.state = "locked"
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 10
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
        self.scenes = [
            {
                "n": 1,
                "start_s": 0.0,
                "end_s": 5.0,
                "phase": "hook",
                "spoken_text": "Spoken text for scene 1",
                "shot": "medium shot",
                "on_screen_text": "Text scene 1",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            }
        ]

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_local_edits()
    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test"
    )
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript()
    )


@pytest.mark.parametrize(
    "requested,expected",
    [(200, CAPTION_Y_MIN), (5000, CAPTION_Y_MAX), (900, 900)],
)
def test_patch_settings_caption_y_clamped(requested, expected):
    resp = client.patch(
        "/api/editing/idea_e206/settings",
        json={"op": "caption_y", "value": requested, "expected_version": 1},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["caption_y"] == expected


def test_patch_settings_caption_y_invalid_value_422():
    resp = client.patch(
        "/api/editing/idea_e206b/settings",
        json={"op": "caption_y", "value": "not-a-number", "expected_version": 1},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_patch_settings_caption_y_never_touches_dressing():
    """A caption_y patch never re-runs auto-edit: dressing state is unaffected."""
    before = client.get("/api/editing/idea_e206c", headers=HEADERS).json()
    assert before["dressing"]["fresh"] is False

    resp = client.patch(
        "/api/editing/idea_e206c/settings",
        json={"op": "caption_y", "value": 1600, "expected_version": 1},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["caption_y"] == 1600
    assert resp.json()["dressing"]["fresh"] is False
    assert resp.json()["dressing"] == before["dressing"]


# ---------------------------------------------------------------------------
# 5. Offline E2E: caption_y=520 and 1600 -> MP4 bottom edge within +-20px
# ---------------------------------------------------------------------------

CLIP_TOLERANCE_PX = 20


def _render_caption_band_mp4(tmp_path: Path, caption_y: int) -> Path:
    raw_mp4 = tmp_path / "raw.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(raw_mp4),
        ],
        check=True,
        capture_output=True,
    )

    tok = CaptionToken(text="HELLO", start_ms=0, end_ms=2000)
    event = CaptionEvent(start_ms=0, end_ms=2000, lines=[[tok]], size="block", emphasis=[])
    style = CaptionStyle(font="Inter", text="#00FF00", accent="#00FF00", outline="#000000")
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=2000,
        captions=[event],
        style=style,
        layout=Layout(caption_y=caption_y),
    )
    req = RenderRequest(
        schema="brandstudio.render.v1",
        job_id=f"job_e2_06_caption_y_{caption_y}",
        attempt=1,
        mode="final",
        raw_input_id="raw_video",
        ir=ir,
        inputs={"raw_video": {"url": "https://example.com/raw.mp4", "kind": "video"}},
        output={"upload_url": "https://example.com/out.mp4", "storage_path": "test/out.mp4"},
    )
    res = build_final(req, {"raw_video": raw_mp4}, tmp_path)
    return res["path"]


def _green_pixel_bottom_edge(mp4_path: Path, at_s: float) -> tuple[int, Path]:
    """Extracts one raw rgb24 frame and returns the max y with a green caption pixel."""
    raw_frame = mp4_path.parent / "frame.rgb24"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(at_s), "-i", str(mp4_path),
            "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-y", str(raw_frame),
        ],
        check=True,
        capture_output=True,
    )
    data = raw_frame.read_bytes()
    width = 1080
    max_y = 0
    for y in range(1920):
        row_off = y * width * 3
        row = data[row_off : row_off + width * 3]
        for x in range(0, len(row), 3):
            r, g, b = row[x], row[x + 1], row[x + 2]
            if g > 180 and r < 100 and b < 100:
                if y > max_y:
                    max_y = y
                break
    return max_y, raw_frame


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg is not installed")
@pytest.mark.parametrize("caption_y", [520, 1600])
def test_offline_e2e_caption_bottom_edge_matches_caption_y(tmp_path, caption_y):
    out_mp4 = _render_caption_band_mp4(tmp_path, caption_y)
    assert out_mp4.is_file()

    max_y, raw_frame = _green_pixel_bottom_edge(out_mp4, at_s=1.0)
    assert max_y > 0, "caption text was not rendered"

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    png_out = EVIDENCE_DIR / f"caption_y_{caption_y}.png"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", "1.0", "-i", str(out_mp4), "-vframes", "1", "-y", str(png_out),
        ],
        check=True,
        capture_output=True,
    )
    (EVIDENCE_DIR / f"caption_y_{caption_y}_measurement.txt").write_text(
        f"requested caption_y: {caption_y}\n"
        f"measured bottom edge (max y with green caption pixel): {max_y}\n"
        f"tolerance: +-{CLIP_TOLERANCE_PX}px\n"
    )

    assert abs(max_y - caption_y) <= CLIP_TOLERANCE_PX, (
        f"caption bottom edge {max_y} not within {CLIP_TOLERANCE_PX}px of caption_y={caption_y}"
    )


# ---------------------------------------------------------------------------
# 6. Preview parity: stateAt's `top` equals caption_y (Node test)
# ---------------------------------------------------------------------------


def _run_node_state_at(ir: dict, t_ms: int) -> dict:
    payload_ir = json.dumps(ir)
    node_script = f"""
    const {{ stateAt }} = require('./app/static/editing_preview.js');
    const ir = {payload_ir};
    console.log(JSON.stringify(stateAt(ir, {t_ms})));
    """
    proc = subprocess.run(
        ["node", "-e", node_script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout.strip())


BASE_STYLE = {"font": "Inter", "text": "#FFFFFF", "accent": "#2B4CD8", "outline": "#000000"}


def _ir_with_one_block_event(caption_y: int | None) -> dict:
    ir: dict[str, Any] = {
        "schema": "brandstudio.ir.v1",
        "duration_ms": 2000,
        "captions": [
            {
                "start_ms": 0,
                "end_ms": 2000,
                "lines": [[{"text": "HELLO", "start_ms": 0, "end_ms": 2000}]],
                "size": "block",
                "emphasis": [],
            }
        ],
        "style": BASE_STYLE,
    }
    if caption_y is not None:
        ir["layout"] = {"caption_y": caption_y}
    return ir


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
@pytest.mark.parametrize("caption_y", [520, 1600])
def test_state_at_top_equals_caption_y(caption_y):
    ir = _ir_with_one_block_event(caption_y)
    st = _run_node_state_at(ir, 500)
    assert st["caption"]["top"] == caption_y


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_state_at_top_defaults_to_1250_without_layout():
    """Legacy IR with no 'layout' key still renders at today's default band."""
    ir = _ir_with_one_block_event(None)
    st = _run_node_state_at(ir, 500)
    assert st["caption"]["top"] == 1250
