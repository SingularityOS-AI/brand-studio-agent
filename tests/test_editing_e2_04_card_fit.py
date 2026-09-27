"""Tests for piece E2-04: card text always fits its box (Python + JS parity).

Bug B1: `render_service/cards.py::card_html` used a fixed font size per kind with a
fixed box height, so long text overflowed and top/bottom lines were clipped.
`render_service/text_fit.py::fit_card_text` (Python) and
`app/static/editing_preview.js::fitCardText` (JS) now shrink-to-fit + line-wrap the
same way; this file proves parity and that a real render never clips card text.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from render_service.cards import render_card_png
from render_service.ffmpeg_dress import build_final
from render_service.manifest import CaptionStyle, OverlayCue, RenderIR, RenderRequest
from render_service.motion import chromium_path
from render_service.text_fit import fit_card_text

REPO_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_JS = REPO_ROOT / "app" / "static" / "editing_preview.js"
EVIDENCE_DIR = REPO_ROOT / "docs" / "specs" / "evidence" / "E2-04"

NODE_AVAILABLE = shutil.which("node") is not None
CHROMIUM_AVAILABLE = chromium_path() is not None
FFMPEG_EXE = shutil.which("ffmpeg")

# (text, kind, box_w, box_h) — covers: short, ~80 chars, a single 30-char
# (unsplittable) word, emoji, small box forcing the 28px floor, 3-line absorption,
# and an unknown kind (fallback default size).
PARITY_CASES: list[tuple[str, str, int, int]] = [
    ("Reduce wait", "card_stat", 900, 400),
    ("", "card_stat", 900, 400),
    ("Cut your response time by forty percent within just two weeks of onboarding work", "card_stat", 900, 400),
    ("start " + ("x" * 30) + " end", "card_list", 900, 400),
    ("Great news \U0001F389 keep going team", "card_quote", 900, 400),
    ("Dr. Alexandra Martinez, Chief Medical Interpretation Officer", "card_lower_third", 900, 200),
    ("Every founder who ships this week gets a free onboarding call with the team", "onscreen_text", 300, 150),
    (
        (
            "This is a long paragraph meant to force the wrap into three lines before the "
            "shrink loop even has to touch the font size at all for this card"
        ),
        "card_stat",
        900,
        500,
    ),
    ("Some default kind text used to test the fallback font size", "mystery_kind", 900, 400),
    ("\U0001F525\U0001F525\U0001F525 incredible growth this quarter \U0001F525\U0001F525\U0001F525", "card_stat", 900, 400),
    # Bold ASCII capitals and digits render wider than K=0.58 assumes; these two
    # regressed the browser wrapping an extra (uncomputed) line before the
    # per-character width factors were added.
    ("$2,400,000 · SAVED IN YEAR ONE", "card_stat", 900, 300),
    ("URGENT: ONLY 3 SPOTS LEFT THIS WEEK FOR FOUNDERS", "card_stat", 900, 400),
]


def run_node_fit_card_text(cases: list[tuple[str, str, int, int]]) -> list[dict]:
    payload = json.dumps(cases)
    node_script = f"""
    const {{ fitCardText }} = require('./app/static/editing_preview.js');
    const cases = {payload};
    const out = cases.map(function (c) {{
      return fitCardText(c[0], c[1], c[2], c[3]);
    }});
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run(
        ["node", "-e", node_script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout.strip())


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available in PATH")
def test_fit_card_text_parity_python_js():
    """Python fit_card_text and JS fitCardText return identical (lines, font_px)."""
    node_results = run_node_fit_card_text(PARITY_CASES)
    assert len(node_results) == len(PARITY_CASES)

    for (text, kind, box_w, box_h), node_res in zip(PARITY_CASES, node_results):
        py_lines, py_font_px = fit_card_text(text, kind, box_w, box_h)
        assert node_res["fontPx"] == py_font_px, (
            f"fontPx mismatch for {kind!r} {text[:20]!r}...: "
            f"py={py_font_px} js={node_res['fontPx']}"
        )
        assert node_res["lines"] == py_lines, (
            f"lines mismatch for {kind!r} {text[:20]!r}...: "
            f"py={py_lines} js={node_res['lines']}"
        )


def test_fit_card_text_never_splits_a_word_and_respects_bounds():
    """Direct Python-side checks of the contract: max 3 lines, min 28px, no split word."""
    lines, font_px = fit_card_text(
        "start " + ("x" * 30) + " end", "card_list", 900, 400
    )
    assert font_px >= 28
    assert len(lines) <= 3
    for line in lines:
        for word in line.split(" "):
            assert word in ("start", "x" * 30, "end")

    # A box far too small forces the 28px floor rather than a smaller value.
    _, tiny_font_px = fit_card_text(
        "This text is far too long for this tiny little card box", "card_stat", 120, 80
    )
    assert tiny_font_px == 28


def test_editing_preview_js_uses_fit_card_text_for_cards():
    """Card drawing (preview) must call fitCardText, not a fixed per-kind font size."""
    content = PREVIEW_JS.read_text(encoding="utf-8")
    assert "function fitCardText" in content
    assert content.count("setCardLines(el, stOv);") == 2


# ---------------------------------------------------------------------------
# Pixel-level evidence: a minimal, dependency-free PNG decoder (no Pillow in
# requirements.txt) to inspect the actual Chromium/FFmpeg output pixels.
# ---------------------------------------------------------------------------


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decodes an 8-bit, non-interlaced RGB(A) PNG into (width, height, rgba_bytes)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("missing IHDR chunk")
    if bit_depth != 8:
        raise ValueError(f"unsupported bit depth {bit_depth}")
    if color_type == 6:
        channels = 4
    elif color_type == 2:
        channels = 3
    else:
        raise ValueError(f"unsupported color type {color_type}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    rpos = 0
    for y in range(height):
        ftype = raw[rpos]
        rpos += 1
        line = bytearray(raw[rpos : rpos + stride])
        rpos += stride
        if ftype == 1:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + a) & 0xFF
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                line[x] = (line[x] + (a + b) // 2) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"unsupported filter type {ftype}")
        row_off = y * width * 4
        if channels == 4:
            out[row_off : row_off + stride] = line
        else:
            for x in range(width):
                out[row_off + x * 4 : row_off + x * 4 + 3] = line[x * 3 : x * 3 + 3]
                out[row_off + x * 4 + 3] = 255
        prev = line
    return width, height, bytes(out)


def max_rgb_in_band(width: int, rgba: bytes, y_start: int, y_end: int) -> int:
    """Max R/G/B channel value among visible (alpha > 0) pixels in rows [y_start, y_end)."""
    max_val = 0
    for y in range(y_start, y_end):
        row_off = y * width * 4
        for x in range(width):
            off = row_off + x * 4
            if rgba[off + 3] == 0:
                continue
            m = max(rgba[off], rgba[off + 1], rgba[off + 2])
            max_val = max(max_val, m)
    return max_val


def assert_card_box_fully_captured(width: int, height: int, rgba: bytes) -> None:
    """Guards against a silently truncated screenshot.

    A truncated Chromium capture (see `render_service.cards._VIEWPORT_HEIGHT_SLACK_PX`)
    reads back as fully *transparent* for the missing rows, which `max_rgb_in_band`
    alone would not catch when the card's text happens not to reach that band — an
    empty top/bottom band is not proof of a correct fit if the box itself was cut.
    The card's translucent background/border must still be opaque at the box's very
    last row, away from the rounded corners.
    """
    x = width // 2
    off = ((height - 1) * width + x) * 4
    alpha = rgba[off + 3]
    assert alpha > 0, (
        f"card box looks truncated: bottom row (y={height - 1}) is fully "
        f"transparent at x={x} (alpha={alpha}) instead of the card background/border"
    )


CLIP_BAND_PX = 20
# White bold text is ~255; the translucent card border blends to ~70. 160 leaves margin.
NO_TEXT_MAX_RGB = 160
CARD_STAT_70_CHAR_TEXT = (
    "Reduce your customer wait time by forty percent this quarter for good."
)


@pytest.mark.skipif(not CHROMIUM_AVAILABLE, reason="Chromium not available")
def test_card_stat_70_chars_no_clip_top_bottom_20px(tmp_path):
    """Renders the real card PNG (Chromium) for a 70-char card_stat and measures it.

    No text pixel may appear in the box's top/bottom 20px (the old fixed-size bug B1:
    top and bottom lines clipped). Evidence PNG saved under docs/specs/evidence/E2-04/.
    """
    assert len(CARD_STAT_70_CHAR_TEXT) == 70

    style = CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ov = OverlayCue(
        id="ov_card_stat_70",
        kind="card_stat",
        text=CARD_STAT_70_CHAR_TEXT,
        start_ms=0,
        end_ms=2000,
        x=90,
        y=760,
        w=900,
        h=400,
        anim="pop",
    )

    out_png = tmp_path / "card_stat_70.png"
    render_card_png(ov, style, out_png, tmp_path)

    data = out_png.read_bytes()
    width, height, rgba = decode_png_rgba(data)
    assert (width, height) == (ov.w, ov.h)
    assert_card_box_fully_captured(width, height, rgba)

    top_max = max_rgb_in_band(width, rgba, 0, CLIP_BAND_PX)
    bottom_max = max_rgb_in_band(width, rgba, height - CLIP_BAND_PX, height)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "card_stat_70_chars.png").write_bytes(data)
    (EVIDENCE_DIR / "card_stat_70_chars_measurement.txt").write_text(
        f"box: {ov.w}x{ov.h}\n"
        f"text ({len(CARD_STAT_70_CHAR_TEXT)} chars): {CARD_STAT_70_CHAR_TEXT!r}\n"
        f"top {CLIP_BAND_PX}px max R/G/B: {top_max}\n"
        f"bottom {CLIP_BAND_PX}px max R/G/B: {bottom_max}\n"
        f"threshold (no-text-pixel) max R/G/B: {NO_TEXT_MAX_RGB}\n"
    )

    assert top_max < NO_TEXT_MAX_RGB, f"top {CLIP_BAND_PX}px has text-like pixels (max={top_max})"
    assert bottom_max < NO_TEXT_MAX_RGB, f"bottom {CLIP_BAND_PX}px has text-like pixels (max={bottom_max})"


# (kind, text, box_w, box_h) across the sizes real overlays use in the IR.
BOX_SIZE_CASES: list[tuple[str, str, int, int]] = [
    ("card_stat", "47% · faster check-in for every patient", 900, 400),
    ("card_stat", "Cut your response time by forty percent this quarter", 900, 300),
    ("card_lower_third", "Dr. Alexandra Martinez, Chief Medical Interpretation Officer", 900, 200),
    ("card_quote", "This tool paid for itself in the first week", 420, 420),
]


@pytest.mark.skipif(not CHROMIUM_AVAILABLE, reason="Chromium not available")
@pytest.mark.parametrize("kind,text,box_w,box_h", BOX_SIZE_CASES)
def test_card_box_sizes_fully_captured_and_no_clip(tmp_path, kind, text, box_w, box_h):
    """Every IR overlay box size is captured in full (not just the 900x400 case).

    Regression guard for the Chromium headless viewport/window-size bug: the PNG's
    own dimensions always reported the requested box even when the capture itself
    was silently cut ~87px short, so a plain (width, height) == (ov.w, ov.h) check
    was not enough — assert_card_box_fully_captured checks the box was really drawn
    all the way to its last row.
    """
    style = CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ov = OverlayCue(
        id=f"ov-box-{kind}",
        kind=kind,
        text=text,
        start_ms=0,
        end_ms=1000,
        x=90,
        y=760,
        w=box_w,
        h=box_h,
        anim="pop",
    )
    out_png = tmp_path / f"box_{kind}.png"
    render_card_png(ov, style, out_png, tmp_path)

    width, height, rgba = decode_png_rgba(out_png.read_bytes())
    assert (width, height) == (box_w, box_h)
    assert_card_box_fully_captured(width, height, rgba)

    top_max = max_rgb_in_band(width, rgba, 0, CLIP_BAND_PX)
    bottom_max = max_rgb_in_band(width, rgba, height - CLIP_BAND_PX, height)
    assert top_max < NO_TEXT_MAX_RGB, f"top {CLIP_BAND_PX}px has text-like pixels (max={top_max})"
    assert bottom_max < NO_TEXT_MAX_RGB, f"bottom {CLIP_BAND_PX}px has text-like pixels (max={bottom_max})"


CAP_DIGIT_CASES: list[tuple[str, int, int]] = [
    ("$2,400,000 · SAVED IN YEAR ONE", 900, 300),
    ("URGENT: ONLY 3 SPOTS LEFT THIS WEEK FOR FOUNDERS", 900, 400),
]


@pytest.mark.skipif(not CHROMIUM_AVAILABLE, reason="Chromium not available")
@pytest.mark.parametrize("font", ["Inter", "Montserrat"])
@pytest.mark.parametrize("text,box_w,box_h", CAP_DIGIT_CASES)
def test_caps_and_digits_no_clip_in_brand_fonts(tmp_path, font, text, box_w, box_h):
    """Bold capitals/digits are wider than lowercase; both brand fonts must still fit.

    Regression guard for the flat K=0.58 width bug: with capitals/digits at their
    real bold width, Chromium wrapped an extra line fit_card_text never planned for,
    pushing a word out of the visible box (silently, since overflow:hidden on .card
    doesn't error, it just drops content).
    """
    style = CaptionStyle(font=font, text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ov = OverlayCue(
        id=f"ov-caps-{font.lower()}",
        kind="card_stat",
        text=text,
        start_ms=0,
        end_ms=1000,
        x=90,
        y=760,
        w=box_w,
        h=box_h,
        anim="pop",
    )
    out_png = tmp_path / f"caps_{font}.png"
    render_card_png(ov, style, out_png, tmp_path)

    width, height, rgba = decode_png_rgba(out_png.read_bytes())
    assert_card_box_fully_captured(width, height, rgba)

    top_max = max_rgb_in_band(width, rgba, 0, CLIP_BAND_PX)
    bottom_max = max_rgb_in_band(width, rgba, height - CLIP_BAND_PX, height)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    safe_text = "".join(c if c.isalnum() else "_" for c in text)[:40]
    (EVIDENCE_DIR / f"caps_digits_{font}_{safe_text}.png").write_bytes(out_png.read_bytes())

    assert top_max < NO_TEXT_MAX_RGB, f"top {CLIP_BAND_PX}px has text-like pixels (max={top_max})"
    assert bottom_max < NO_TEXT_MAX_RGB, f"bottom {CLIP_BAND_PX}px has text-like pixels (max={bottom_max})"


@pytest.mark.skipif(FFMPEG_EXE is None, reason="ffmpeg is not installed")
@pytest.mark.skipif(not CHROMIUM_AVAILABLE, reason="Chromium not available")
def test_offline_e2e_mp4_card_stat_70_chars_no_clip(tmp_path):
    """Full offline render (real ffmpeg + real Chromium card) with a 70-char card_stat.

    Extracts the overlay's midpoint frame from the final MP4 and measures the card
    box's top/bottom 20px the same way as the direct-PNG test above. Evidence frame
    saved under docs/specs/evidence/E2-04/.
    """
    raw_mp4 = tmp_path / "raw.mp4"
    subprocess.run(
        [
            FFMPEG_EXE,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=1080x1920:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(raw_mp4),
        ],
        check=True,
        capture_output=True,
    )

    style = CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ov = OverlayCue(
        id="ov_card_stat_70",
        kind="card_stat",
        text=CARD_STAT_70_CHAR_TEXT,
        start_ms=200,
        end_ms=1800,
        x=90,
        y=760,
        w=900,
        h=400,
        anim="pop",
    )
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=2000,
        overlays=[ov],
        style=style,
    )
    req = RenderRequest(
        schema="brandstudio.render.v1",
        job_id="job_e2_04_card_fit",
        attempt=1,
        mode="final",
        raw_input_id="raw_video",
        ir=ir,
        inputs={"raw_video": {"url": "https://example.com/raw.mp4", "kind": "video"}},
        output={"upload_url": "https://example.com/out.mp4", "storage_path": "test/out.mp4"},
    )

    res = build_final(req, {"raw_video": raw_mp4}, tmp_path)
    out_mp4 = res["path"]
    assert out_mp4.is_file()

    midpoint_s = (ov.start_ms + ov.end_ms) / 2000.0
    crop_png = tmp_path / "card_crop.png"
    subprocess.run(
        [
            FFMPEG_EXE,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(midpoint_s),
            "-i",
            str(out_mp4),
            "-vf",
            f"crop={ov.w}:{ov.h}:{ov.x}:{ov.y}",
            "-frames:v",
            "1",
            "-y",
            str(crop_png),
        ],
        check=True,
        capture_output=True,
    )

    data = crop_png.read_bytes()
    width, height, rgba = decode_png_rgba(data)

    top_max = max_rgb_in_band(width, rgba, 0, CLIP_BAND_PX)
    bottom_max = max_rgb_in_band(width, rgba, height - CLIP_BAND_PX, height)

    # The MP4 frame has no alpha channel (opaque video), so a truncated card
    # composite doesn't read back transparent like the direct-PNG case — it reads
    # back as the raw clip's own background showing through where the card border
    # should be. An empty-looking bottom band is not proof of "no clipping" unless
    # the card's border/background is actually the last thing drawn there.
    raw_bg_rgb = (128, 128, 128)  # ffmpeg color=c=gray
    x = width // 2
    bottom_off = ((height - 1) * width + x) * 4
    bottom_rgb = rgba[bottom_off : bottom_off + 3]
    bottom_matches_raw_bg = all(abs(c - raw_bg_rgb[i]) < 20 for i, c in enumerate(bottom_rgb))
    assert not bottom_matches_raw_bg, (
        f"card box looks truncated in the MP4 frame: bottom row (y={height - 1}) is "
        f"the raw clip's own background {raw_bg_rgb} instead of the card border/background, "
        f"got {tuple(bottom_rgb)}"
    )

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "mp4_frame_card_crop.png").write_bytes(data)
    (EVIDENCE_DIR / "mp4_frame_measurement.txt").write_text(
        f"crop box: {width}x{height} at ({ov.x},{ov.y}), midpoint {midpoint_s}s\n"
        f"top {CLIP_BAND_PX}px max R/G/B: {top_max}\n"
        f"bottom {CLIP_BAND_PX}px max R/G/B: {bottom_max}\n"
        f"threshold (no-text-pixel) max R/G/B: {NO_TEXT_MAX_RGB}\n"
        f"bottom row center pixel RGB: {tuple(bottom_rgb)} (raw bg would be {raw_bg_rgb})\n"
    )

    assert top_max < NO_TEXT_MAX_RGB, f"top {CLIP_BAND_PX}px has text-like pixels (max={top_max})"
    assert bottom_max < NO_TEXT_MAX_RGB, f"bottom {CLIP_BAND_PX}px has text-like pixels (max={bottom_max})"
