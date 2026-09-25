"""FFmpeg dress video rendering module for ASS subtitle overlay, zooms, transitions, SFX, and final builder (PIEZA 86)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
import subprocess
from typing import Any

from render_service.manifest import RenderIR, RenderRequest, ZoomKey, hex_to_ass

logger = logging.getLogger(__name__)

FONTS_DIR: Path = Path(__file__).parent / "fonts"


def fmt_num(v: float) -> str:
    """Formats a float to string with up to 4 decimal places, trimming trailing zeros."""
    r = round(v, 4)
    if r == int(r):
        return str(int(r))
    s = f"{r:.4f}".rstrip("0").rstrip(".")
    return s


def zoom_at(keys: list[ZoomKey], t_ms: int | float) -> tuple[float, float, float]:
    """Pure python evaluation of zoom interpolation at time t_ms.

    Returns tuple (scale, cx, cy). Sin claves -> (1.0, 0.5, 0.5).
    """
    if not keys:
        return (1.0, 0.5, 0.5)

    sorted_keys = sorted(keys, key=lambda k: k.t_ms)
    if t_ms <= sorted_keys[0].t_ms:
        k0 = sorted_keys[0]
        return (float(k0.scale), float(k0.cx), float(k0.cy))
    if t_ms >= sorted_keys[-1].t_ms:
        kn = sorted_keys[-1]
        return (float(kn.scale), float(kn.cx), float(kn.cy))

    for i in range(len(sorted_keys) - 1):
        k1 = sorted_keys[i]
        k2 = sorted_keys[i + 1]
        if k1.t_ms <= t_ms <= k2.t_ms:
            dt = k2.t_ms - k1.t_ms
            if dt <= 0:
                return (float(k2.scale), float(k2.cx), float(k2.cy))
            p = (t_ms - k1.t_ms) / dt
            ease = getattr(k2, "ease", "linear")
            if ease == "out":
                e = 1.0 - (1.0 - p) ** 2
            else:
                e = float(p)

            scale = k1.scale + (k2.scale - k1.scale) * e
            cx = k1.cx + (k2.cx - k1.cx) * e
            cy = k1.cy + (k2.cy - k1.cy) * e
            return (float(scale), float(cx), float(cy))

    kn = sorted_keys[-1]
    return (float(kn.scale), float(kn.cx), float(kn.cy))


def zoom_expr(keys: list[ZoomKey], var: str = "t") -> tuple[str, str, str]:
    """Generates FFmpeg expression strings (scale, cx, cy) as functions of time in seconds (var).

    Returns 3 strings. Sin claves -> ("1", "0.5", "0.5"). Redondea a 4 decimales.
    """
    if not keys:
        return ("1", "0.5", "0.5")

    sorted_keys = sorted(keys, key=lambda k: k.t_ms)
    if len(sorted_keys) == 1:
        k = sorted_keys[0]
        return (fmt_num(k.scale), fmt_num(k.cx), fmt_num(k.cy))

    def build_param_expr(attr_name: str) -> str:
        expr = fmt_num(getattr(sorted_keys[-1], attr_name))
        for i in range(len(sorted_keys) - 2, -1, -1):
            k1 = sorted_keys[i]
            k2 = sorted_keys[i + 1]
            t1_sec = k1.t_ms / 1000.0
            t2_sec = k2.t_ms / 1000.0
            dt = t2_sec - t1_sec

            v1 = getattr(k1, attr_name)
            v2 = getattr(k2, attr_name)

            if dt <= 0 or round(v1, 4) == round(v2, 4):
                seg_expr = fmt_num(v1)
            else:
                v1_str = fmt_num(v1)
                dv = v2 - v1
                dv_str = fmt_num(dv)
                t1_str = fmt_num(t1_sec)
                dt_str = fmt_num(dt)

                p_str = f"(({var}-{t1_str})/{dt_str})"
                ease = getattr(k2, "ease", "linear")
                if ease == "out":
                    e_str = f"(1-(1-{p_str})*(1-{p_str}))"
                else:
                    e_str = p_str

                seg_expr = f"({v1_str}+{dv_str}*{e_str})"

            t2_str = fmt_num(t2_sec)
            expr = f"if(lt({var},{t2_str}),{seg_expr},{expr})"

        t0_sec = sorted_keys[0].t_ms / 1000.0
        if t0_sec > 0:
            t0_str = fmt_num(t0_sec)
            v0_str = fmt_num(getattr(sorted_keys[0], attr_name))
            expr = f"if(lt({var},{t0_str}),{v0_str},{expr})"

        return expr

    return (
        build_param_expr("scale"),
        build_param_expr("cx"),
        build_param_expr("cy"),
    )


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

    Sequence: zoom (scale, crop) -> transitions -> ass.
    """
    filters: list[str] = []

    # 1. Zoom filters
    if ir.zoom_keys:
        s_expr, cx_expr, cy_expr = zoom_expr(ir.zoom_keys, var="t")
        scale_filter = (
            f"scale=w='trunc(1080*({s_expr})/2)*2':h='trunc(1920*({s_expr})/2)*2':eval=frame"
        )
        crop_filter = (
            f"crop=1080:1920:x='(in_w-1080)*({cx_expr})':y='(in_h-1920)*({cy_expr})'"
        )
        filters.append(scale_filter)
        filters.append(crop_filter)

    # 2. Transition filters
    for tr in ir.transitions:
        if tr.type == "flash":
            a_sec = fmt_num(tr.at_ms / 1000.0)
            d_sec = fmt_num(tr.dur_ms / 1000.0)
            ad_sec = fmt_num((tr.at_ms + tr.dur_ms) / 1000.0)
            filters.append(
                f"eq=brightness='if(between(t,{a_sec},{ad_sec}),0.8*(1-(t-{a_sec})/{d_sec}),0)':eval=frame"
            )
        elif tr.type == "zoom_through":
            a_sec = fmt_num(tr.at_ms / 1000.0)
            ad2_sec = fmt_num((tr.at_ms + tr.dur_ms / 2.0) / 1000.0)
            filters.append(f"gblur=sigma=12:enable='between(t,{a_sec},{ad2_sec})'")
        elif tr.type == "whip":
            start_sec = fmt_num(max(0.0, (tr.at_ms - tr.dur_ms / 2.0) / 1000.0))
            end_sec = fmt_num((tr.at_ms + tr.dur_ms / 2.0) / 1000.0)
            filters.append(f"avgblur=sizeX=40:sizeY=1:enable='between(t,{start_sec},{end_sec})'")

    # 3. ASS filter
    esc_ass = ass_rel_str.replace("\\", "/").replace(":", "\\:")
    if fonts_rel_str:
        esc_fonts = fonts_rel_str.replace("\\", "/").replace(":", "\\:")
        ass_filter = f"ass={esc_ass}:fontsdir={esc_fonts}"
    else:
        ass_filter = f"ass={esc_ass}"

    filters.append(ass_filter)
    return filters


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

    sfx_cues = request.ir.sfx
    if not sfx_cues:
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

    unique_sfx_ids: list[str] = []
    for cue in sfx_cues:
        if cue.input_id not in local_inputs:
            raise KeyError(f"sfx input_id '{cue.input_id}' not found in local_inputs")
        if cue.input_id not in unique_sfx_ids:
            unique_sfx_ids.append(cue.input_id)

    input_idx_map = {input_id: i + 1 for i, input_id in enumerate(unique_sfx_ids)}
    n_sfx = len(sfx_cues)

    filter_complex_parts: list[str] = []
    filter_complex_parts.append(f"[0:v]{vf_text}[vout]")

    for input_id in unique_sfx_ids:
        idx = input_idx_map[input_id]
        cues_using = [i for i, c in enumerate(sfx_cues) if c.input_id == input_id]
        if len(cues_using) > 1:
            out_labels = "".join(f"[sfx_src_{i}]" for i in cues_using)
            filter_complex_parts.append(f"[{idx}:a]asplit={len(cues_using)}{out_labels}")

    for i, cue in enumerate(sfx_cues):
        cues_using = [idx for idx, c in enumerate(sfx_cues) if c.input_id == cue.input_id]
        if len(cues_using) > 1:
            src_label = f"[sfx_src_{i}]"
        else:
            src_label = f"[{input_idx_map[cue.input_id]}:a]"
        gain_str = fmt_num(cue.gain_db)
        filter_complex_parts.append(f"{src_label}adelay={cue.at_ms}|{cue.at_ms},volume={gain_str}dB[sfx{i}]")

    mix_inputs = 1 + n_sfx
    sfx_labels = "".join(f"[sfx{i}]" for i in range(n_sfx))
    filter_complex_parts.append(f"[0:a]{sfx_labels}amix=inputs={mix_inputs}:duration=first:normalize=0[aout]")

    filter_complex_str = ";".join(filter_complex_parts)

    args = [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(raw_path),
    ]
    for input_id in unique_sfx_ids:
        args.extend(["-i", str(local_inputs[input_id])])

    args.extend([
        "-filter_complex",
        filter_complex_str,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
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
    ])

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
