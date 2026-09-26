"""Tests for render_service/ffmpeg_dress.py zoom, transitions, SFX (PIEZA 86)."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(r"C:\Python312_Neural\DLLs")
    except Exception:
        pass

from render_service.ffmpeg_dress import (
    build_final,
    build_final_args,
    zoom_at,
    zoom_expr,
)
from render_service.manifest import (
    RenderRequest,
    ZoomKey,
)


def eval_ffmpeg_expr(expr: str, t_val: float) -> float:
    """Evaluates nested FFmpeg expression string in python at time t_val (in seconds)."""
    def lt(a: float, b: float) -> bool:
        return a < b

    def iff(cond: bool, val_true: float, val_false: float) -> float:
        return val_true if cond else val_false

    sub_expr = re.sub(r"\bt\b", f"({t_val:.6f})", expr)
    sub_expr = re.sub(r"\bif\(", "iff(", sub_expr)
    return float(eval(sub_expr, {"iff": iff, "lt": lt}))


def create_synthetic_raw_video(path: Path, duration_s: float = 4.0, w: int = 1080, h: int = 1920) -> None:
    """Generates a synthetic raw video with audio using lavfi."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={w}x{h}:r=30",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:r=48000",
        "-t",
        f"{duration_s:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def create_synthetic_sfx_audio(path: Path, duration_s: float = 1.0) -> None:
    """Generates a synthetic sfx audio file using lavfi sine."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=f=880:r=48000",
        "-t",
        f"{duration_s:.3f}",
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def extract_luma_mean(video_path: Path, time_s: float) -> float:
    """Extracts gray rawvideo frame at time_s and computes mean luma byte value."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{time_s:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    res = subprocess.run(cmd, check=True, capture_output=True)
    bytes_data = res.stdout
    assert len(bytes_data) > 0
    return sum(bytes_data) / len(bytes_data)


def test_1_zoom_at():
    """Test 1: zoom_at interpolates zoom keys with out/linear ease and fallback."""
    keys = [
        ZoomKey(t_ms=0, scale=1.0, cx=0.5, cy=0.5, ease="out"),
        ZoomKey(t_ms=200, scale=1.15, cx=0.5, cy=0.5, ease="out"),
        ZoomKey(t_ms=1600, scale=1.15, cx=0.5, cy=0.5, ease="linear"),
        ZoomKey(t_ms=2000, scale=1.0, cx=0.5, cy=0.5, ease="linear"),
    ]

    s_100, _, _ = zoom_at(keys, 100)
    assert abs(s_100 - 1.1125) < 1e-4

    s_1000, _, _ = zoom_at(keys, 1000)
    assert abs(s_1000 - 1.15) < 1e-4

    s_1800, _, _ = zoom_at(keys, 1800)
    assert abs(s_1800 - 1.075) < 1e-4

    s_5000, _, _ = zoom_at(keys, 5000)
    assert abs(s_5000 - 1.0) < 1e-4

    s_no_keys, cx, cy = zoom_at([], 500)
    assert (s_no_keys, cx, cy) == (1.0, 0.5, 0.5)


def test_2_zoom_expr_matches_zoom_at():
    """Test 2: zoom_expr expression evaluated numerically matches zoom_at across 20 points."""
    keys = [
        ZoomKey(t_ms=0, scale=1.0, cx=0.5, cy=0.5, ease="out"),
        ZoomKey(t_ms=200, scale=1.15, cx=0.5, cy=0.5, ease="out"),
        ZoomKey(t_ms=1600, scale=1.15, cx=0.5, cy=0.5, ease="linear"),
        ZoomKey(t_ms=2000, scale=1.0, cx=0.5, cy=0.5, ease="linear"),
    ]

    expr_s, expr_cx, expr_cy = zoom_expr(keys, var="t")

    for i in range(20):
        t_ms = i * 125  # 0 to 2375 ms
        t_sec = t_ms / 1000.0

        expected_s, expected_cx, expected_cy = zoom_at(keys, t_ms)
        actual_s = eval_ffmpeg_expr(expr_s, t_sec)
        actual_cx = eval_ffmpeg_expr(expr_cx, t_sec)
        actual_cy = eval_ffmpeg_expr(expr_cy, t_sec)

        assert abs(actual_s - expected_s) < 1e-3, f"Mismatch at t_ms={t_ms}: {actual_s} vs {expected_s}"
        assert abs(actual_cx - expected_cx) < 1e-3
        assert abs(actual_cy - expected_cy) < 1e-3


def test_3_build_final_args_structure(tmp_path):
    """Test 3: build_final_args with zoom, flash, whip, and 2 SFX uses -filter_complex with required filters."""
    raw_path = tmp_path / "raw.mp4"
    sfx1_path = tmp_path / "sfx1.wav"
    sfx2_path = tmp_path / "sfx2.wav"
    out_path = tmp_path / "out.mp4"

    raw_path.write_bytes(b"dummy_raw")
    sfx1_path.write_bytes(b"dummy_sfx1")
    sfx2_path.write_bytes(b"dummy_sfx2")

    request_dict = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_p86_test3",
        "attempt": 1,
        "mode": "final",
        "timeline": None,
        "ir": {
            "schema": "brandstudio.ir.v1",
            "duration_ms": 4000,
            "frame_zero": None,
            "captions": [],
            "zoom_keys": [
                {"t_ms": 0, "scale": 1.0, "cx": 0.5, "cy": 0.5, "ease": "out"},
                {"t_ms": 1000, "scale": 1.15, "cx": 0.5, "cy": 0.5, "ease": "out"},
            ],
            "transitions": [
                {"at_ms": 1000, "type": "flash", "dur_ms": 200},
                {"at_ms": 2000, "type": "whip", "dur_ms": 270},
            ],
            "overlays": [],
            "sfx": [
                {"at_ms": 500, "input_id": "sfx1", "gain_db": 0.0},
                {"at_ms": 1500, "input_id": "sfx2", "gain_db": -3.0},
            ],
            "style": {
                "font": "Inter",
                "text": "#FFFFFF",
                "accent": "#00FF00",
                "outline": "#000000",
            },
        },
        "raw_input_id": "raw_1",
        "inputs": {
            "raw_1": {"url": "https://example.com/raw.mp4", "kind": "video"},
            "sfx1": {"url": "https://example.com/sfx1.wav", "kind": "audio"},
            "sfx2": {"url": "https://example.com/sfx2.wav", "kind": "audio"},
        },
        "convert": [],
        "output": {
            "upload_url": "https://example.com/upload",
            "storage_path": "output/final.mp4",
            "max_bytes": 47000000,
        },
        "progress_url": None,
    }

    req = RenderRequest.model_validate(request_dict)
    local_inputs = {
        "raw_1": raw_path,
        "sfx1": sfx1_path,
        "sfx2": sfx2_path,
    }

    args = build_final_args(
        req,
        local_inputs,
        out_path,
        "subs.ass",
        tmp_path / "fonts",
        tmp_path,
    )

    assert "-filter_complex" in args
    fc_idx = args.index("-filter_complex")
    fc_expr = args[fc_idx + 1]

    assert "zoompan=" in fc_expr
    assert "fps=30" in fc_expr
    assert "eq=brightness" in fc_expr
    assert "avgblur" in fc_expr
    assert "adelay" in fc_expr
    assert "amix=inputs=3" in fc_expr

    # Verify ass filter is at the end of video chain before [vout]
    v_chain = fc_expr.split("[vout]")[0]
    assert v_chain.endswith("ass=subs.ass") or "ass=subs.ass" in v_chain.split(",")[-1]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_4_build_final_real_ffmpeg_render(tmp_path):
    """Test 4: Real FFmpeg render with zoom, flash, and SFX; frame at 2.05s is brighter with flash."""
    raw_path = tmp_path / "raw.mp4"
    sfx_path = tmp_path / "sfx.wav"

    create_synthetic_raw_video(raw_path, duration_s=4.0, w=1080, h=1920)
    create_synthetic_sfx_audio(sfx_path, duration_s=1.0)

    base_ir_dict = {
        "schema": "brandstudio.ir.v1",
        "duration_ms": 4000,
        "frame_zero": None,
        "captions": [],
        "zoom_keys": [
            {"t_ms": 0, "scale": 1.0, "cx": 0.5, "cy": 0.5, "ease": "out"},
            {"t_ms": 1000, "scale": 1.15, "cx": 0.5, "cy": 0.5, "ease": "out"},
        ],
        "overlays": [],
        "sfx": [
            {"at_ms": 0, "input_id": "sfx1", "gain_db": 0.0},
        ],
        "style": {
            "font": "Inter",
            "text": "#FFFFFF",
            "accent": "#00FF00",
            "outline": "#000000",
        },
    }

    # Render 1: with flash at 2s (2000 ms, duration 200 ms)
    ir_flash_dict = {
        **base_ir_dict,
        "transitions": [{"at_ms": 2000, "type": "flash", "dur_ms": 200}],
    }
    # Render 2: without flash
    ir_noflash_dict = {
        **base_ir_dict,
        "transitions": [],
    }

    def make_req(ir_dict: dict, job_id: str) -> RenderRequest:
        return RenderRequest.model_validate({
            "schema": "brandstudio.render.v1",
            "job_id": job_id,
            "attempt": 1,
            "mode": "final",
            "timeline": None,
            "ir": ir_dict,
            "raw_input_id": "raw_1",
            "inputs": {
                "raw_1": {"url": "https://example.com/raw.mp4", "kind": "video"},
                "sfx1": {"url": "https://example.com/sfx.wav", "kind": "audio"},
            },
            "convert": [],
            "output": {
                "upload_url": "https://example.com/upload",
                "storage_path": f"output/{job_id}.mp4",
                "max_bytes": 47000000,
            },
            "progress_url": None,
        })

    local_inputs = {"raw_1": raw_path, "sfx1": sfx_path}

    dir_flash = tmp_path / "run_flash"
    dir_noflash = tmp_path / "run_noflash"

    res_flash = build_final(make_req(ir_flash_dict, "flash_job"), local_inputs, dir_flash)
    res_noflash = build_final(make_req(ir_noflash_dict, "noflash_job"), local_inputs, dir_noflash)

    out_flash = res_flash["path"]
    out_noflash = res_noflash["path"]

    assert out_flash.exists()
    assert out_noflash.exists()

    # Measure luma mean at t=2.05 s
    luma_flash = extract_luma_mean(out_flash, 2.05)
    luma_noflash = extract_luma_mean(out_noflash, 2.05)

    assert luma_flash > luma_noflash, f"Expected flash luma ({luma_flash}) > noflash luma ({luma_noflash})"

    # Verify duration & streams of output
    ffprobe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(out_flash),
    ]
    probe = json.loads(subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True).stdout)
    fmt = probe.get("format", {})
    dur_s = float(fmt.get("duration", 0))
    assert abs(dur_s - 4.0) <= 0.150

    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    assert v_stream is not None
    assert v_stream.get("width") == 1080
    assert v_stream.get("height") == 1920
    assert a_stream is not None
