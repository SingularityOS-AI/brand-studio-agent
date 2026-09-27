"""FFmpeg dress video rendering module for ASS subtitle overlay, zooms, transitions, SFX, and final builder (PIEZA 86)."""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
import subprocess
from typing import Any

from render_service.cards import render_card_png
from render_service.manifest import OverlayCue, RenderIR, RenderRequest, ZoomKey, hex_to_ass

logger = logging.getLogger(__name__)

FONTS_DIR: Path = Path(__file__).parent / "fonts"


def layout_text(
    kind: str,
    lines_or_text: Any,
) -> tuple[list[str], int]:
    """Pure function calculating text line breaks and font size for FrameZero, Hero, and Block.

    Shared text layout rules (usable width 900px, K=0.58):
    - FrameZero: words packed greedily into max 16 chars per line, max 3 lines (3rd line absorbs rest).
      font_px = min(110, floor(900 / (0.58 * len(longest_line))))
    - Hero: single word.
      font_px = min(170, floor(900 / (0.58 * len(word))))
    - Block: lines as provided.
      font_px = min(84, floor(900 / (0.58 * len(longest_line))))
    """
    k_factor = 0.58
    usable_width = 900.0
    norm_kind = kind.lower().replace("_", "")

    if norm_kind in ("framezero", "fz"):
        if isinstance(lines_or_text, str):
            words = lines_or_text.strip().split()
        elif isinstance(lines_or_text, list):
            words = []
            for item in lines_or_text:
                if isinstance(item, str):
                    words.extend(item.strip().split())
                elif isinstance(item, list):
                    for tok in item:
                        t_str = tok.text if hasattr(tok, "text") else str(tok)
                        words.extend(t_str.strip().split())
        else:
            words = []

        if not words:
            return ([], 110)

        lines: list[str] = []
        curr: list[str] = []
        for w in words:
            if len(lines) == 2:
                curr.append(w)
            else:
                candidate = " ".join(curr + [w]) if curr else w
                if len(candidate) <= 16 or not curr:
                    curr.append(w)
                else:
                    lines.append(" ".join(curr))
                    curr = [w]
        if curr:
            lines.append(" ".join(curr))

        max_len = max((len(line) for line in lines), default=1)
        font_px = min(110, math.floor(usable_width / (k_factor * max_len)))
        return (lines, font_px)

    elif norm_kind == "hero":
        if isinstance(lines_or_text, str):
            word = lines_or_text.strip()
        elif isinstance(lines_or_text, list):
            if lines_or_text and isinstance(lines_or_text[0], list):
                flat = []
                for sub in lines_or_text:
                    flat.extend(t.text if hasattr(t, "text") else str(t) for t in sub)
                word = " ".join(flat).strip()
            else:
                word = " ".join(str(x) for x in lines_or_text).strip()
        else:
            word = str(lines_or_text).strip()

        word_len = len(word)
        if word_len == 0:
            return ([""], 170)
        font_px = min(170, math.floor(usable_width / (k_factor * word_len)))
        return ([word], font_px)

    elif norm_kind == "block":
        if isinstance(lines_or_text, str):
            raw_lines = [line for line in lines_or_text.splitlines() if line]
        elif isinstance(lines_or_text, list):
            raw_lines = []
            for item in lines_or_text:
                if isinstance(item, str):
                    raw_lines.append(item)
                elif isinstance(item, list):
                    line_str = " ".join(t.text if hasattr(t, "text") else str(t) for t in item)
                    raw_lines.append(line_str)
                else:
                    raw_lines.append(str(item))
        else:
            raw_lines = []

        if not raw_lines:
            return ([], 84)

        max_len = max((len(line) for line in raw_lines), default=1)
        font_px = min(84, math.floor(usable_width / (k_factor * max_len)))
        return (raw_lines, font_px)

    else:
        return ([], 84)



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


def zoom_expr(keys: list[ZoomKey], var: str = "on/30") -> tuple[str, str, str]:
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
        # ASS BackColour &H66000000: AA=0x66 (102 dec = 40% transparency = 60% opacity), BB=00, GG=00, RR=00 (black). On white bg, RGB = 255 * 0.4 = 102 +- 10.
        f"Style: FrameZero,{font_name},110,{c_text},&H000000FF,{c_outline},&H66000000,-1,0,0,0,100,100,0,0,3,7,0,5,90,90,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # 1. Frame zero if present
    if ir.frame_zero:
        fz_start, fz_end = _format_time_span(ir.frame_zero.start_ms, ir.frame_zero.end_ms)
        fz_lines, fz_font_px = layout_text("FrameZero", ir.frame_zero.text)
        fz_text = "\\N".join(ass_escape(line) for line in fz_lines)
        lines.append(f"Dialogue: 0,{fz_start},{fz_end},FrameZero,,0,0,0,,{{\\fs{fz_font_px}}}{fz_text}")

    # 2. Captions events
    for event in ir.captions:
        style_name = "Hero" if event.size == "hero" else "Block"
        all_tokens = [tok for line in event.lines for tok in line]
        if not all_tokens:
            continue

        _cap_lines, font_px = layout_text(style_name, event.lines)

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
            lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{{\\fs{font_px}}}{dialogue_text}")

    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8-sig")


def _base_video_filters(ir: RenderIR) -> list[str]:
    """Builds base video filters (zooms + transitions) without ASS subtitle overlay."""
    filters: list[str] = []

    # 1. Zoom filters
    if ir.zoom_keys:
        s_expr, cx_expr, cy_expr = zoom_expr(ir.zoom_keys, var="on/30")
        zoompan_filter = (
            f"zoompan=z='{s_expr}':x='(iw-iw/zoom)*({cx_expr})':y='(ih-ih/zoom)*({cy_expr})':d=1:s=1080x1920:fps=30"
        )
        filters.append(zoompan_filter)

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

    return filters


def _video_filters(
    ir: RenderIR,
    ass_rel_str: str = "subs.ass",
    fonts_rel_str: str | None = None,
) -> list[str]:
    """Builds video filter list for FFmpeg.

    Sequence: zoom (scale, crop) -> transitions -> ass.
    """
    filters = _base_video_filters(ir)

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
    overlay_files: dict[str, Path] | None = None,
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

    # Resolve overlays
    valid_overlays: list[tuple[OverlayCue, Path]] = []
    if request.ir.overlays:
        for ov in request.ir.overlays:
            img_path: Path | None = None
            if overlay_files and ov.id in overlay_files:
                img_path = overlay_files[ov.id]
            elif ov.kind == "broll_card" and ov.asset and ov.asset in local_inputs:
                img_path = local_inputs[ov.asset]
            elif (workdir / f"overlay_{ov.id}.png").is_file():
                img_path = workdir / f"overlay_{ov.id}.png"

            if img_path and img_path.is_file():
                valid_overlays.append((ov, img_path))
            else:
                logger.warning("Overlay %s image file missing, skipping", ov.id)

    sfx_cues = request.ir.sfx

    # 1. Path without overlays and without SFX: uses -vf (backward compatible)
    if not valid_overlays and not sfx_cues:
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

    # 2. Path with overlays or SFX: uses -filter_complex
    args = [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(raw_path),
    ]

    dur_s = fmt_num(request.ir.duration_ms / 1000.0)

    # Add overlay inputs
    for _ov, img_path in valid_overlays:
        args.extend(["-loop", "1", "-t", dur_s, "-i", str(img_path)])

    # Add SFX inputs
    unique_sfx_ids: list[str] = []
    for cue in sfx_cues:
        if cue.input_id not in local_inputs:
            raise KeyError(f"sfx input_id '{cue.input_id}' not found in local_inputs")
        if cue.input_id not in unique_sfx_ids:
            unique_sfx_ids.append(cue.input_id)

    for input_id in unique_sfx_ids:
        args.extend(["-i", str(local_inputs[input_id])])

    filter_complex_parts: list[str] = []

    # Video stream graph construction
    base_vfilters = _base_video_filters(request.ir)
    if base_vfilters:
        filter_complex_parts.append(f"[0:v]{','.join(base_vfilters)}[vbase]")
        v_curr = "[vbase]"
    else:
        v_curr = "[0:v]"

    if valid_overlays:
        for idx, (ov, _img_path) in enumerate(valid_overlays):
            input_k = 1 + idx
            S = fmt_num(ov.start_ms / 1000.0)
            E = fmt_num(ov.end_ms / 1000.0)
            st_out = fmt_num(max(ov.start_ms, ov.end_ms - 150) / 1000.0)

            if ov.kind == "broll_card":
                w_crop = max(1, ov.w - 12)
                h_crop = max(1, ov.h - 12)
                prep_filter = (
                    f"scale={ov.w}:{ov.h}:force_original_aspect_ratio=increase,"
                    f"crop={w_crop}:{h_crop},pad={ov.w}:{ov.h}:6:6:white,"
                    f"format=rgba,fade=t=in:st={S}:d=0.2:alpha=1,fade=t=out:st={st_out}:d=0.15:alpha=1"
                )
            else:
                prep_filter = (
                    f"format=rgba,fade=t=in:st={S}:d=0.2:alpha=1,fade=t=out:st={st_out}:d=0.15:alpha=1"
                )

            ov_label = f"[ov{idx}]"
            filter_complex_parts.append(f"[{input_k}:v]{prep_filter}{ov_label}")

            v_next = f"[v_ov{idx}]"
            filter_complex_parts.append(
                f"{v_curr}{ov_label}overlay=x={ov.x}:y={ov.y}:enable='between(t,{S},{E})'{v_next}"
            )
            v_curr = v_next

    # ASS subtitle filter after last overlay (or after base video)
    esc_ass = ass_name.replace("\\", "/").replace(":", "\\:")
    if fonts_rel:
        esc_fonts = fonts_rel.replace("\\", "/").replace(":", "\\:")
        ass_filter_str = f"ass={esc_ass}:fontsdir={esc_fonts}"
    else:
        ass_filter_str = f"ass={esc_ass}"

    filter_complex_parts.append(f"{v_curr}{ass_filter_str}[vout]")

    # Audio stream graph construction (if SFX present)
    if sfx_cues:
        sfx_base_idx = 1 + len(valid_overlays)
        input_idx_map = {
            input_id: sfx_base_idx + i for i, input_id in enumerate(unique_sfx_ids)
        }
        n_sfx = len(sfx_cues)

        for input_id in unique_sfx_ids:
            idx = input_idx_map[input_id]
            cues_using = [i for i, c in enumerate(sfx_cues) if c.input_id == input_id]
            if len(cues_using) > 1:
                out_labels = "".join(f"[sfx_src_{i}]" for i in cues_using)
                filter_complex_parts.append(
                    f"[{idx}:a]asplit={len(cues_using)}{out_labels}"
                )

        for i, cue in enumerate(sfx_cues):
            cues_using = [
                idx for idx, c in enumerate(sfx_cues) if c.input_id == cue.input_id
            ]
            if len(cues_using) > 1:
                src_label = f"[sfx_src_{i}]"
            else:
                src_label = f"[{input_idx_map[cue.input_id]}:a]"
            gain_str = fmt_num(cue.gain_db)
            filter_complex_parts.append(
                f"{src_label}adelay={cue.at_ms}|{cue.at_ms},volume={gain_str}dB[sfx{i}]"
            )

        mix_inputs = 1 + n_sfx
        sfx_labels = "".join(f"[sfx{i}]" for i in range(n_sfx))
        filter_complex_parts.append(
            f"[0:a]{sfx_labels}amix=inputs={mix_inputs}:duration=first:normalize=0[aout]"
        )

    filter_complex_str = ";".join(filter_complex_parts)

    args.extend([
        "-filter_complex",
        filter_complex_str,
        "-map",
        "[vout]",
    ])

    if sfx_cues:
        args.extend(["-map", "[aout]"])
    else:
        args.extend(["-map", "0:a?"])

    args.extend([
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

    overlay_files: dict[str, Path] = {}
    if request.ir.overlays:
        for ov in request.ir.overlays:
            if ov.kind == "broll_card":
                if ov.asset and ov.asset in local_inputs:
                    overlay_files[ov.id] = local_inputs[ov.asset]
                else:
                    logger.warning("broll_card asset '%s' not found in local_inputs", ov.asset)
            else:
                out_png = workdir / f"overlay_{ov.id}.png"
                try:
                    render_card_png(ov, request.ir.style, out_png, workdir)
                    overlay_files[ov.id] = out_png
                except Exception as e:
                    logger.warning("Failed to render overlay card %s: %s", ov.id, e)

    ass_name = "subs.ass"
    ass_path = workdir / ass_name
    write_ass(request.ir, ass_path)

    out_path = workdir / "final_out.mp4"
    args = build_final_args(
        request,
        local_inputs,
        out_path,
        ass_name,
        FONTS_DIR,
        workdir,
        overlay_files=overlay_files,
    )

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

