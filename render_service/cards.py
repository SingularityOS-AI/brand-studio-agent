"""HTML overlay card generation and Chromium headless PNG rendering module (PIEZA 90B)."""

from __future__ import annotations

import html
import logging
from pathlib import Path
import subprocess

from render_service.manifest import CaptionStyle, OverlayCue
from render_service.motion import chromium_path

logger = logging.getLogger(__name__)

FONT_SIZES = {
    "card_stat": "110px",
    "card_quote": "60px",
    "card_list": "50px",
    "card_lower_third": "44px",
    "onscreen_text": "64px",
    "emoji": "180px",
}


def card_html(ov: OverlayCue, style: CaptionStyle) -> str:
    """Generates self-contained HTML string for an overlay cue.

    Html and body have transparent background, zero margins, and exact ov.w x ov.h size.
    Text is escaped using html.escape to prevent injection.
    """
    raw_text = ov.text or ov.asset or ""
    escaped_text = html.escape(raw_text)
    font_size = FONT_SIZES.get(ov.kind, "64px")
    font_family = f'"{style.font}", sans-serif'
    accent_color = style.accent

    if ov.kind == "emoji":
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
    font-size: {font_size};
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

    if (
        ov.kind == "card_quote"
        and escaped_text
        and not escaped_text.startswith("“")
        and not escaped_text.startswith('"')
    ):
        display_text = f"“{escaped_text}”"
    else:
        display_text = escaped_text

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
    padding: 20px 30px;
    color: #ffffff;
    font-size: {font_size};
    font-weight: bold;
    font-style: {font_style};
    text-align: {text_align};
    word-wrap: break-word;
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
    """Renders an OverlayCue to a transparent PNG file using Chromium headless."""
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

    cmd = [
        exe,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        "--default-background-color=00000000",
        f"--window-size={ov.w},{ov.h}",
        f"--screenshot={out_png}",
        file_url,
    ]

    subprocess.run(
        cmd,
        check=True,
        timeout=timeout_s,
        capture_output=True,
    )

    if not out_png.is_file() or out_png.stat().st_size == 0:
        raise RuntimeError(f"Chromium failed to produce PNG at {out_png}")

    return out_png
