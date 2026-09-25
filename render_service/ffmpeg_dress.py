"""FFmpeg dress video rendering module for ASS subtitle overlay and final builder (PIEZA 80)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
import subprocess
from typing import Any

from render_service.manifest import RenderIR, RenderRequest, hex_to_ass

logger = logging.getLogger(__name__)

FONTS_DIR: Path = Path(__file__).parent / "fonts"


def ass_escape(text: str) -> str:
    """Escapes string for ASS subtitle format.

    Rules:
    - Replace '\\' with '＼' (U+FF3C)
    - Replace '{' with '｛' (U+FF5B)
    - Replace '}' with '｝' (U+FF5D)
    - Convert newlines ('\\n', '\\r') and tabs ('\\t') to space
    - Remove control characters (< 0x20 and 0x7F)
    - Collapse whitespace
    """
    cleaned = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 0x20 and ord(ch) != 0x7F)
    cleaned = (
        cleaned.replace("\\", "\uff3c")
        .replace("{", "\uff5b")
        .replace("}", "\uff5d")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _format_time_span(start_ms: int, end_ms: int) -> tuple[str, str]:
    """Formats start_ms and end_ms into ASS H:MM:SS.cc strings.

    Rounds start down to centiseconds (floor), end up (ceil).
    Ensures end_cs > start_cs (never end <= start).
    """
    start_cs = max(0, start_ms // 10)
    end_cs = (max(0, end_ms) + 9) // 10
    if end_cs <= start_cs:
        end_cs = start_cs + 1

    def cs_to_str(cs: int) -> str:
        h = cs // 360000
        cs %= 360000
        m = cs // 6000
        cs %= 6000
        s = cs // 100
        c = cs % 100
        return f"{h}:{m:02d}:{s:02d}.{c:02d}"

    return cs_to_str(start_cs), cs_to_str(end_cs)


def write_ass(ir: RenderIR, path: Path) -> None:
    """Writes ASS subtitle file from RenderIR.

    Generates header, V4+ styles, and events with word-level highlight.
    Uses UTF-8 with BOM (utf-8-sig) encoding.
    """
    font_name = ir.style.font
    c_text = hex_to_ass(ir.style.text)
    c_accent = hex_to_ass(ir.style.accent)
    c_outline = hex_to_ass(ir.style.outline)

    lines: list[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Block,{font_name},84,{c_text},&H000000FF,{c_outline},&H00000000,-1,0,0,0,100,100,0,0,1,6,2,2,90,90,670,1",
        f"Style: Hero,{font_name},170,{c_text},&H000000FF,{c_outline},&H00000000,-1,0,0,0,100,100,0,0,1,8,0,5,90,90,0,1",
        f"Style: FrameZero,{font_name},110,{c_text},&H000000FF,{c_outline},&H66000000,-1,0,0,0,100,100,0,0,3,7,0,5,90,90,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # 1. Frame zero if present
    if ir.frame_zero:
        fz_start, fz_end = _format_time_span(ir.frame_zero.start_ms, ir.frame_zero.end_ms)
        fz_text = ass_escape(ir.frame_zero.text)
        lines.append(f"Dialogue: 0,{fz_start},{fz_end},FrameZero,,0,0,0,,{fz_text}")

    # 2. Captions events
    for event in ir.captions:
        style_name = "Hero" if event.size == "hero" else "Block"
        all_tokens = [tok for line in event.lines for tok in line]
        if not all_tokens:
            continue

        n_tokens = len(all_tokens)
        for idx, active_tok in enumerate(all_tokens):
            # Start time of token dialogue
            t_start = event.start_ms if idx == 0 else active_tok.start_ms
            # End time of token dialogue
            t_end = event.end_ms if idx == n_tokens - 1 else all_tokens[idx + 1].start_ms

            start_str, end_str = _format_time_span(t_start, t_end)

            # Build line texts with active token highlighted
            rendered_lines: list[str] = []
            for line_tokens in event.lines:
                line_parts: list[str] = []
                for tok in line_tokens:
                    tok_text_esc = ass_escape(tok.text)
                    if tok is active_tok:
                        line_parts.append(f"{{\\c{c_accent}}}{tok_text_esc}")
                    else:
                        line_parts.append(f"{{\\c{c_text}}}{tok_text_esc}")
                rendered_lines.append(" ".join(line_parts))

            dialogue_text = "\\N".join(rendered_lines)
            lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{dialogue_text}")

    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8-sig")


def _video_filters(
    ir: RenderIR,
    ass_rel_str: str = "subs.ass",
    fonts_rel_str: str | None = None,
) -> list[str]:
    """Builds video filter list for FFmpeg.

    Extensible for future stages (zoom, transitions, overlays).
    Today returns single ass filter.
    """
    esc_ass = ass_rel_str.replace("\\", "/").replace(":", "\\:")
    if fonts_rel_str:
        esc_fonts = fonts_rel_str.replace("\\", "/").replace(":", "\\:")
        filter_expr = f"ass={esc_ass}:fontsdir={esc_fonts}"
    else:
        filter_expr = f"ass={esc_ass}"

    return [filter_expr]


def build_final_args(
    request: RenderRequest,
    local_inputs: dict[str, Path],
    out_path: Path,
    ass_name: str,
    fonts_dir: Path,
    workdir: Path,
) -> list[str]:
    """Builds FFmpeg argument list for final render (pure function, does not execute)."""
    if request.mode != "final":
        raise ValueError(f"Expected mode 'final', got '{request.mode}'")
    if request.ir is None:
        raise ValueError("RenderRequest in mode 'final' requires ir")
    if request.raw_input_id is None:
        raise ValueError("RenderRequest in mode 'final' requires raw_input_id")
    if request.raw_input_id not in local_inputs:
        raise KeyError(f"raw_input_id '{request.raw_input_id}' not found in local_inputs")

    raw_path = local_inputs[request.raw_input_id]

    fonts_rel: str | None = None
    if fonts_dir.is_dir():
        try:
            fonts_rel = os.path.relpath(fonts_dir, workdir)
        except ValueError:
            dest_fonts = workdir / "fonts"
            dest_fonts.mkdir(parents=True, exist_ok=True)
            for f in fonts_dir.iterdir():
                if f.is_file():
                    (dest_fonts / f.name).write_bytes(f.read_bytes())
            fonts_rel = "fonts"

    filters = _video_filters(request.ir, ass_name, fonts_rel)
    vf_text = ",".join(filters)

    args = [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(raw_path),
        "-vf",
        vf_text,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-maxrate",
        "3.5M",
        "-bufsize",
        "7M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-y",
        str(out_path),
    ]

    return args


def build_final(
    request: RenderRequest,
    local_inputs: dict[str, Path],
    workdir: Path,
    timeout_s: int = 240,
) -> dict[str, Any]:
    """Generates ASS subtitles and renders final video with FFmpeg.

    Returns {"path": out_path, "duration_ms": request.ir.duration_ms, "scene_marks_ms": []}.
    """
    if request.mode != "final":
        raise ValueError(f"Expected mode 'final', got '{request.mode}'")
    if request.ir is None:
        raise ValueError("RenderRequest in mode 'final' requires ir")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    ass_name = "subs.ass"
    ass_path = workdir / ass_name
    write_ass(request.ir, ass_path)

    out_path = workdir / "final_out.mp4"
    args = build_final_args(request, local_inputs, out_path, ass_name, FONTS_DIR, workdir)

    cmd = ["ffmpeg"] + args
    subprocess.run(
        cmd,
        cwd=workdir,
        check=True,
        timeout=timeout_s,
        capture_output=True,
    )

    return {
        "path": out_path,
        "duration_ms": request.ir.duration_ms,
        "scene_marks_ms": [],
    }
