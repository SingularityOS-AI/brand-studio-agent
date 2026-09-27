"""FFmpeg raw video rendering module (PIEZA 74)."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any

from render_service.manifest import RenderRequest

logger = logging.getLogger(__name__)

# E2-03 empty-scene guard (bug B2 safety net): a motion-graphic scene is judged
# empty when > 90% of its luma samples, taken every 250ms, are near-uniform.
_EMPTY_SCENE_SAMPLE_HZ = 4.0  # 1 sample / 250ms
_EMPTY_SCENE_LUMA_STDDEV_THRESHOLD = 4.0
_EMPTY_SCENE_RATIO = 0.9
_EMPTY_SCENE_SAMPLE_W = 160
_EMPTY_SCENE_SAMPLE_H = 90


def _fallback_image_input_id(scene_n: int) -> str:
    """Naming convention for an optional still fallback for a motion-graphic scene.

    Nothing upstream populates this input yet; a scene's AI image is used as the
    empty-scene fallback only when the manifest happens to declare an image InputRef
    under this key. Otherwise the guard falls back to the founder's face take.
    """
    return f"broll_s{scene_n}_image"


def _sample_luma_stddevs(
    video_path: Path,
    sample_hz: float = _EMPTY_SCENE_SAMPLE_HZ,
    timeout_s: int = 30,
) -> list[float]:
    """Samples video_path at sample_hz and returns each sampled frame's luma std-dev.

    Frames are downscaled to a small fixed size before sampling: this is only used to
    tell a near-uniform (blank) scene from a normal one, never to inspect the image.
    Returns an empty list (never raises) when ffmpeg is unavailable or sampling fails,
    so a sampling problem never blocks the raw render.
    """
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        return []

    w, h = _EMPTY_SCENE_SAMPLE_W, _EMPTY_SCENE_SAMPLE_H
    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={sample_hz},scale={w}:{h}:flags=fast_bilinear,format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, check=True, timeout=timeout_s, capture_output=True)
    except Exception as e:  # noqa: BLE001 — a sampling failure must never break the render
        logger.warning("Empty-scene luma sampling failed for %s: %s", video_path, e)
        return []

    raw = proc.stdout
    frame_size = w * h
    stddevs: list[float] = []
    for i in range(0, len(raw) - frame_size + 1, frame_size):
        frame = raw[i : i + frame_size]
        n = len(frame)
        if n == 0:
            continue
        mean = sum(frame) / n
        variance = sum((b - mean) ** 2 for b in frame) / n
        stddevs.append(variance ** 0.5)
    return stddevs


def _is_empty_motion_graphic(
    stddevs: list[float],
    threshold: float = _EMPTY_SCENE_LUMA_STDDEV_THRESHOLD,
    empty_ratio: float = _EMPTY_SCENE_RATIO,
) -> bool:
    """True when more than empty_ratio of stddevs are near-uniform (< threshold)."""
    if not stddevs:
        return False
    empty_count = sum(1 for s in stddevs if s < threshold)
    return (empty_count / len(stddevs)) > empty_ratio


def _guard_empty_motion_graphics(
    request: RenderRequest, local_inputs: dict[str, Path]
) -> tuple[RenderRequest, list[dict[str, Any]]]:
    """Safety net for bug B2 (piece E2-03): no MP4 ever ships a blank MG scene.

    Samples every already-converted motion-graphic scene. A scene sampled as empty
    is swapped for the scene's AI image (see _fallback_image_input_id), if the
    manifest declares one, else the founder's face take. Returns the possibly
    patched request and the scene_fallbacks list for the raw response.
    """
    timeline = request.timeline
    assert timeline is not None

    scene_fallbacks: list[dict[str, Any]] = []
    patched_scenes = []

    for scene in timeline.scenes:
        broll = scene.broll
        if not (scene.visual == "broll" and broll and broll.kind == "motion_graphic"):
            patched_scenes.append(scene)
            continue

        video_path = local_inputs.get(broll.input_id)
        if not video_path or str(video_path).lower().endswith(".html"):
            # Not yet converted (or missing): build_raw_args' own .html fallback
            # already sends this scene to face.
            patched_scenes.append(scene)
            continue

        stddevs = _sample_luma_stddevs(Path(video_path))
        if not _is_empty_motion_graphic(stddevs):
            patched_scenes.append(scene)
            continue

        fallback_id = _fallback_image_input_id(scene.n)
        fallback_path = local_inputs.get(fallback_id)
        fallback_ref = request.inputs.get(fallback_id)
        if fallback_path and fallback_ref and fallback_ref.kind == "image":
            new_broll = broll.model_copy(
                update={"kind": "ai_image", "input_id": fallback_id}
            )
            patched_scenes.append(scene.model_copy(update={"broll": new_broll}))
            scene_fallbacks.append(
                {"scene_n": scene.n, "used": "image", "reason": "empty_motion_graphic"}
            )
        else:
            patched_scenes.append(scene.model_copy(update={"visual": "face"}))
            scene_fallbacks.append(
                {"scene_n": scene.n, "used": "face", "reason": "empty_motion_graphic"}
            )

    patched_timeline = timeline.model_copy(update={"scenes": patched_scenes})
    patched_request = request.model_copy(update={"timeline": patched_timeline})
    return patched_request, scene_fallbacks


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

    request, scene_fallbacks = _guard_empty_motion_graphics(request, local_inputs)

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
        "scene_fallbacks": scene_fallbacks,
    }
