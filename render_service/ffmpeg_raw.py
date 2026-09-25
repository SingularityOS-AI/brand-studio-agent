"""FFmpeg raw video rendering module (PIEZA 74)."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import Any

from render_service.manifest import RenderRequest

logger = logging.getLogger(__name__)


def build_raw_args(
    request: RenderRequest,
    local_inputs: dict[str, Path],
    out_path: Path,
) -> tuple[list[str], str]:
    """Devuelve (args de ffmpeg SIN el ejecutable, texto del filter_complex).

    Función pura: no ejecuta nada.
    """
    if request.mode != "raw":
        raise ValueError(f"Expected mode 'raw', got '{request.mode}'")
    if request.timeline is None:
        raise ValueError("RenderRequest in mode 'raw' requires a timeline")

    timeline = request.timeline
    if not timeline.scenes:
        raise ValueError("Timeline must contain at least one scene")
    # A motion graphic whose HTML could not be converted to MP4 is still an
    # .html file here: show the founder's face for that scene instead of
    # failing the whole raw cut.
    scenes = [
        sc.model_copy(update={"visual": "face"})
        if sc.visual == "broll"
        and sc.broll
        and str(local_inputs.get(sc.broll.input_id, "")).lower().endswith(".html")
        else sc
        for sc in timeline.scenes
    ]

    # 1. Collect unique input IDs in order of discovery
    unique_input_ids: list[str] = []

    def register_input(inp_id: str) -> None:
        if inp_id not in unique_input_ids:
            unique_input_ids.append(inp_id)

    for scene in scenes:
        register_input(scene.take_input)
        if scene.broll and scene.visual == "broll":
            register_input(scene.broll.input_id)

    has_music = (
        timeline.music is not None
        and timeline.music.input_id in local_inputs
        and not timeline.settings.music_muted
    )
    if has_music and timeline.music:
        register_input(timeline.music.input_id)

    # Check all required input IDs exist in local_inputs
    for inp_id in unique_input_ids:
        if inp_id not in local_inputs:
            raise KeyError(f"Input '{inp_id}' not found in local_inputs")

    input_id_to_idx = {inp_id: idx for idx, inp_id in enumerate(unique_input_ids)}

    # Map input usage counts for stream splitting
    audio_usage: dict[int, int] = {idx: 0 for idx in range(len(unique_input_ids))}
    video_usage: dict[int, int] = {idx: 0 for idx in range(len(unique_input_ids))}

    for scene in scenes:
        take_idx = input_id_to_idx[scene.take_input]
        audio_usage[take_idx] += len(scene.segments)

        if scene.visual == "face":
            video_usage[take_idx] += len(scene.segments)
        elif scene.visual == "broll" and scene.broll:
            b_idx = input_id_to_idx[scene.broll.input_id]
            video_usage[b_idx] += 1

    if has_music and timeline.music:
        m_idx = input_id_to_idx[timeline.music.input_id]
        audio_usage[m_idx] += 1

    # Prepare stream labels for audio and video splitters
    audio_stream_labels: dict[int, list[str]] = {}
    video_stream_labels: dict[int, list[str]] = {}

    filter_lines: list[str] = []

    for idx in range(len(unique_input_ids)):
        c_a = audio_usage[idx]
        if c_a == 1:
            audio_stream_labels[idx] = [f"[{idx}:a]"]
        elif c_a > 1:
            labels = [f"[a_{idx}_{j}]" for j in range(c_a)]
            audio_stream_labels[idx] = list(labels)
            split_out = "".join(labels)
            filter_lines.append(f"[{idx}:a]asplit={c_a}{split_out}")

        c_v = video_usage[idx]
        if c_v == 1:
            video_stream_labels[idx] = [f"[{idx}:v]"]
        elif c_v > 1:
            labels = [f"[v_{idx}_{j}]" for j in range(c_v)]
            video_stream_labels[idx] = list(labels)
            split_out = "".join(labels)
            filter_lines.append(f"[{idx}:v]split={c_v}{split_out}")

    # Build per-scene filters
    scene_a_outputs: list[str] = []
    scene_v_outputs: list[str] = []

    for s_idx, scene in enumerate(scenes):
        take_idx = input_id_to_idx[scene.take_input]

        # Audio segments for scene
        seg_a_labels: list[str] = []
        for seg_idx, seg in enumerate(scene.segments):
            in_s = seg.in_ms / 1000.0
            out_s = seg.out_ms / 1000.0
            a_in = audio_stream_labels[take_idx].pop(0)
            a_out = f"[a_sc_{s_idx}_seg_{seg_idx}]"
            filter_lines.append(
                f"{a_in}atrim=start={in_s:.3f}:end={out_s:.3f},asetpts=PTS-STARTPTS,aresample=48000:async=1{a_out}"
            )
            seg_a_labels.append(a_out)

        sc_a_out = f"[a_sc_{s_idx}]"
        concat_in_a = "".join(seg_a_labels)
        filter_lines.append(
            f"{concat_in_a}concat=n={len(seg_a_labels)}:v=0:a=1{sc_a_out}"
        )
        scene_a_outputs.append(sc_a_out)

        # Video for scene
        sc_v_out = f"[v_sc_{s_idx}]"
        if scene.visual == "face":
            seg_v_labels: list[str] = []
            for seg_idx, seg in enumerate(scene.segments):
                in_s = seg.in_ms / 1000.0
                out_s = seg.out_ms / 1000.0
                v_in = video_stream_labels[take_idx].pop(0)
                v_out = f"[v_sc_{s_idx}_seg_{seg_idx}]"
                filter_lines.append(
                    f"{v_in}trim=start={in_s:.3f}:end={out_s:.3f},setpts=PTS-STARTPTS,fps=30,"
                    f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,format=yuv420p{v_out}"
                )
                seg_v_labels.append(v_out)

            concat_in_v = "".join(seg_v_labels)
            filter_lines.append(
                f"{concat_in_v}concat=n={len(seg_v_labels)}:v=1:a=0{sc_v_out}"
            )
            scene_v_outputs.append(sc_v_out)

        elif scene.visual == "broll" and scene.broll:
            broll = scene.broll
            b_idx = input_id_to_idx[broll.input_id]
            v_in = video_stream_labels[b_idx].pop(0)
            d_ms = scene.out_end_ms - scene.out_start_ms
            d_sec = d_ms / 1000.0

            input_ref = request.inputs.get(broll.input_id)
            is_image = (input_ref and input_ref.kind == "image") or broll.kind == "ai_image"

            if is_image:
                d_frames = max(1, int(round(d_sec * 30)))
                zoom_expr = f"min(1+0.08*on/{d_frames},1.08)"
                filter_lines.append(
                    f"{v_in}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"zoompan=z='{zoom_expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
                    f"trim=duration={d_sec:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p{sc_v_out}"
                )
            else:
                filter_lines.append(
                    f"{v_in}trim=duration={d_sec:.3f},setpts=PTS-STARTPTS,fps=30,"
                    f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,format=yuv420p{sc_v_out}"
                )
            scene_v_outputs.append(sc_v_out)

    # Concat all scene video outputs -> [vout]
    v_all_in = "".join(scene_v_outputs)
    filter_lines.append(f"{v_all_in}concat=n={len(scenes)}:v=1:a=0[vout]")

    # Concat all scene audio outputs -> [voice]
    a_all_in = "".join(scene_a_outputs)
    filter_lines.append(f"{a_all_in}concat=n={len(scenes)}:v=0:a=1[voice]")

    # Audio music ducking or voice pass-through
    if has_music and timeline.music:
        m_idx = input_id_to_idx[timeline.music.input_id]
        m_in = audio_stream_labels[m_idx].pop(0)
        total_sec = timeline.duration_ms / 1000.0
        vol = timeline.music.volume

        filter_lines.append("[voice]asplit=2[voice_main][voice_sc]")
        filter_lines.append(
            f"{m_in}atrim=duration={total_sec:.3f},asetpts=PTS-STARTPTS,aresample=48000,volume={vol:.4f}[music_proc]"
        )
        filter_lines.append(
            "[music_proc][voice_sc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[music_ducked]"
        )
        filter_lines.append(
            "[voice_main][music_ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_lines.append("[voice]anull[aout]")

    filter_complex_text = ";\n".join(filter_lines)

    # Prepare FFmpeg CLI input args
    cli_args: list[str] = [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]

    for inp_id in unique_input_ids:
        local_path = local_inputs[inp_id]
        is_loop_video = False
        is_loop_image = False

        input_ref = request.inputs.get(inp_id)
        if input_ref and input_ref.kind == "image":
            is_loop_image = True

        for scene in scenes:
            if scene.broll and scene.broll.input_id == inp_id:
                if scene.broll.kind == "ai_image":
                    is_loop_image = True
                elif scene.broll.kind in ("ai_video", "motion_graphic", "stock") and not is_loop_image:
                    is_loop_video = True

        if has_music and timeline.music and timeline.music.input_id == inp_id:
            is_loop_video = True

        if is_loop_image:
            cli_args.extend(["-loop", "1", "-framerate", "30", "-i", str(local_path)])
        elif is_loop_video:
            cli_args.extend(["-stream_loop", "-1", "-i", str(local_path)])
        else:
            cli_args.extend(["-i", str(local_path)])

    cli_args.extend([
        "-filter_complex",
        filter_complex_text,
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

    return cli_args, filter_complex_text


def build_raw(
    request: RenderRequest,
    local_inputs: dict[str, Path],
    workdir: Path,
    timeout_s: int = 240,
) -> dict[str, Any]:
    """Escribe el filtro en workdir/filter.txt, corre ffmpeg con subprocess.run([...], check=True, timeout=timeout_s,

    capture_output=True) — NUNCA shell=True — y devuelve {"path", "duration_ms", "scene_marks_ms"}.
    """
    if request.mode != "raw":
        raise ValueError(f"Expected mode 'raw', got '{request.mode}'")
    if request.timeline is None:
        raise ValueError("RenderRequest in mode 'raw' requires a timeline")

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    out_path = workdir / "raw_out.mp4"
    filter_file = workdir / "filter.txt"

    args, filter_text = build_raw_args(request, local_inputs, out_path)

    filter_file.write_text(filter_text, encoding="utf-8")

    cmd = ["ffmpeg"] + args
    subprocess.run(
        cmd,
        check=True,
        timeout=timeout_s,
        capture_output=True,
    )

    scene_marks_ms = [sc.out_start_ms for sc in request.timeline.scenes]

    return {
        "path": out_path,
        "duration_ms": request.timeline.duration_ms,
        "scene_marks_ms": scene_marks_ms,
    }
