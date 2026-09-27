"""HTML overlay card generation and Chromium headless PNG rendering module (PIEZA 90B)."""

from __future__ import annotations

import html
import logging
import struct
import subprocess
import zlib
from pathlib import Path

from render_service.manifest import CaptionStyle, OverlayCue
from render_service.motion import chromium_path
from render_service.text_fit import fit_card_text

logger = logging.getLogger(__name__)

EMOJI_FONT_SIZE = "180px"

# Chromium's `--headless=new --window-size=W,H --screenshot` only actually captures
# roughly the top `H - 87px` of the page (a known headless viewport vs window-size
# mismatch: https://crbug.com/1508406) and pads the rest with transparent pixels, so a
# card whose content reached near the bottom of its box got silently clipped. Request
# this much extra height and crop the PNG back to the real box (see render_card_png).
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_VIEWPORT_HEIGHT_SLACK_PX = 200


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decodes an 8-bit, non-interlaced RGB(A) PNG into (width, height, rgba_bytes)."""
    if data[:8] != _PNG_SIGNATURE:
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
        raise ValueError(f"unsupported PNG bit depth {bit_depth}")
    if color_type == 6:
        channels = 4
    elif color_type == 2:
        channels = 3
    else:
        raise ValueError(f"unsupported PNG color type {color_type}")

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
            raise ValueError(f"unsupported PNG filter type {ftype}")
        row_off = y * width * 4
        if channels == 4:
            out[row_off : row_off + stride] = line
        else:
            for x in range(width):
                out[row_off + x * 4 : row_off + x * 4 + 3] = line[x * 3 : x * 3 + 3]
                out[row_off + x * 4 + 3] = 255
        prev = line
    return width, height, bytes(out)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encodes raw RGBA bytes (no filtering) as an 8-bit truecolor-with-alpha PNG."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    idat = zlib.compress(bytes(raw), 6)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _crop_png_top_left(data: bytes, width: int, height: int) -> bytes:
    """Crops a screenshot PNG down to its top-left `width x height` region."""
    src_w, src_h, rgba = _decode_png_rgba(data)
    if src_w == width and src_h == height:
        return data
    stride = width * 4
    src_stride = src_w * 4
    cropped = bytearray(width * height * 4)
    for y in range(min(height, src_h)):
        cropped[y * stride : (y + 1) * stride] = rgba[y * src_stride : y * src_stride + stride]
    return _encode_png_rgba(width, height, bytes(cropped))


def card_html(ov: OverlayCue, style: CaptionStyle) -> str:
    """Generates self-contained HTML string for an overlay cue.

    Html and body have transparent background, zero margins, and exact ov.w x ov.h size.
    Text is escaped using html.escape to prevent injection.
    """
    raw_text = ov.text or ov.asset or ""
    font_family = f'"{style.font}", sans-serif'
    accent_color = style.accent

    if ov.kind == "emoji":
        escaped_text = html.escape(raw_text)
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    background: transparent;
    margin: 0;
    padding: 0;
    width: {ov.w}px;
    height: {ov.h}px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: {font_family};
}}
.emoji-box {{
    font-size: {EMOJI_FONT_SIZE};
    line-height: 1;
    text-align: center;
}}
</style>
</head>
<body>
<div class="emoji-box">{escaped_text}</div>
</body>
</html>"""

    is_accent = getattr(ov, "accent", False)
    border_style = (
        f"3px solid {accent_color}"
        if is_accent
        else "3px solid rgba(255, 255, 255, 0.2)"
    )
    text_align = "left" if ov.kind == "card_lower_third" else "center"
    font_style = "italic" if ov.kind == "card_quote" else "normal"

    fit_source = raw_text
    if (
        ov.kind == "card_quote"
        and fit_source
        and not fit_source.startswith("“")
        and not fit_source.startswith('"')
    ):
        fit_source = f"“{fit_source}”"

    lines, font_px = fit_card_text(fit_source, ov.kind, ov.w, ov.h)
    display_text = "<br>".join(html.escape(line) for line in lines)
    font_size = f"{font_px}px"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    background: transparent;
    margin: 0;
    padding: 0;
    width: {ov.w}px;
    height: {ov.h}px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: {font_family};
    box-sizing: border-box;
}}
.card {{
    background: rgba(10, 12, 20, 0.82);
    border-radius: 28px;
    border: {border_style};
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: {"flex-start" if text_align == "left" else "center"};
    padding: 30px 40px;
    color: #ffffff;
    font-size: {font_size};
    line-height: 1.15;
    font-weight: bold;
    font-style: {font_style};
    text-align: {text_align};
    overflow: hidden;
}}
</style>
</head>
<body>
<div class="card">{display_text}</div>
</body>
</html>"""


def render_card_png(
    ov: OverlayCue,
    style: CaptionStyle,
    out_png: Path,
    workdir: Path,
    timeout_s: int = 30,
) -> Path:
    """Renders an OverlayCue to a transparent PNG file using Chromium headless.

    Requests a taller window than the card (see `_VIEWPORT_HEIGHT_SLACK_PX`) to work
    around Chromium's headless viewport/window-size mismatch, then crops the result
    back down to the overlay's real `ov.w x ov.h` box.
    """
    exe = chromium_path()
    if not exe:
        raise RuntimeError("Chromium executable not found")

    out_png = Path(out_png)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    html_path = workdir / f"temp_card_{ov.id}.html"
    content = card_html(ov, style)
    html_path.write_text(content, encoding="utf-8")

    file_url = html_path.resolve().as_uri()

    raw_png = workdir / f"temp_card_{ov.id}_raw.png"
    capture_h = ov.h + _VIEWPORT_HEIGHT_SLACK_PX
    cmd = [
        exe,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        "--default-background-color=00000000",
        f"--window-size={ov.w},{capture_h}",
        f"--screenshot={raw_png}",
        file_url,
    ]

    subprocess.run(
        cmd,
        check=True,
        timeout=timeout_s,
        capture_output=True,
    )

    if not raw_png.is_file() or raw_png.stat().st_size == 0:
        raise RuntimeError(f"Chromium failed to produce PNG at {raw_png}")

    out_png.write_bytes(_crop_png_top_left(raw_png.read_bytes(), ov.w, ov.h))
    raw_png.unlink(missing_ok=True)

    if not out_png.is_file() or out_png.stat().st_size == 0:
        raise RuntimeError(f"Chromium failed to produce PNG at {out_png}")

    return out_png
