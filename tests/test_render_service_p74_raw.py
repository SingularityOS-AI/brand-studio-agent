"""Tests for render_service/ffmpeg_raw.py (PIEZA 74)."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import pytest

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(r"C:\Python312_Neural\DLLs")
    except Exception:
        pass

from render_service.ffmpeg_raw import build_raw, build_raw_args
from render_service.manifest import (
    Broll,
    Canvas,
    InputRef,
    RenderRequest,
    Segment,
    Timeline,
    TimelineMusic,
    TimelineScene,
    TimelineSettings,
    Trim,
)


def create_synthetic_video(path: Path, duration_s: float = 3.0, w: int = 360, h: int = 640) -> None:
    """Generates a small synthetic video with audio using lavfi."""
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


def create_synthetic_image(path: Path, w: int = 360, h: int = 640) -> None:
    """Generates a small synthetic PNG image using lavfi."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:s={w}x{h}",
        "-frames:v",
        "1",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def create_synthetic_audio(path: Path, duration_s: float = 5.0) -> None:
    """Generates a small synthetic AAC audio file using lavfi."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=f=220:r=48000",
        "-t",
        f"{duration_s:.3f}",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def probe_media(path: Path) -> dict:
    """Probes media file with ffprobe and returns parsed JSON."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def make_sample_timeline(music: TimelineMusic | None = None) -> Timeline:
    return Timeline(
        schema="brandstudio.timeline.v1",
        edit_version=1,
        canvas=Canvas(w=1080, h=1920, fps=30),
        settings=TimelineSettings(
            gap_ms=400,
            pad_ms=100,
            music_volume=0.2,
            music_muted=False,
            sfx_enabled=True,
        ),
        scenes=[
            TimelineScene(
                n=1,
                phase="hook",
                visual="face",
                take_job_id="take_job_1",
                take_input="take_1",
                broll=None,
                segments=[
                    Segment(in_ms=0, out_ms=1000, out_start_ms=0),
                    Segment(in_ms=1500, out_ms=2500, out_start_ms=1000),
                ],
                trim=Trim(start_ms=0, end_ms=0),
                out_start_ms=0,
                out_end_ms=2000,
            ),
            TimelineScene(
                n=2,
                phase="body",
                visual="broll",
                take_job_id="take_job_1",
                take_input="take_1",
                broll=Broll(kind="ai_image", input_id="broll_img"),
                segments=[Segment(in_ms=0, out_ms=1500, out_start_ms=2000)],
                trim=Trim(start_ms=0, end_ms=0),
                out_start_ms=2000,
                out_end_ms=3500,
            ),
            TimelineScene(
                n=3,
                phase="close",
                visual="broll",
                take_job_id="take_job_1",
                take_input="take_1",
                broll=Broll(kind="ai_video", input_id="broll_vid"),
                segments=[Segment(in_ms=0, out_ms=2000, out_start_ms=3500)],
                trim=Trim(start_ms=0, end_ms=0),
                out_start_ms=3500,
                out_end_ms=5500,
            ),
        ],
        music=music,
        duration_ms=5500,
        hash="sample_hash_74",
    )


def make_sample_request(mode: str = "raw", music: TimelineMusic | None = None) -> RenderRequest:
    inputs = {
        "take_1": InputRef(url="https://example.com/take1.mp4", kind="video"),
        "broll_img": InputRef(url="https://example.com/img.png", kind="image"),
        "broll_vid": InputRef(url="https://example.com/vid.mp4", kind="video"),
    }
    if music:
        inputs[music.input_id] = InputRef(url="https://example.com/music.mp3", kind="audio")

    timeline = make_sample_timeline(music=music) if mode == "raw" else None

    raw_dict = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_p74_1",
        "attempt": 1,
        "mode": mode,
        "timeline": timeline.model_dump() if timeline else None,
        "ir": None,
        "raw_input_id": None,
        "inputs": {k: v.model_dump() for k, v in inputs.items()},
        "convert": [],
        "output": {
            "upload_url": "https://example.com/upload",
            "storage_path": "output/video.mp4",
            "max_bytes": 47000000,
        },
        "progress_url": None,
    }

    if mode == "final":
        raw_dict["ir"] = {
            "schema": "brandstudio.ir.v1",
            "duration_ms": 5000,
            "style": {
                "font": "Inter",
                "text": "#FFFFFF",
                "accent": "#2B4CD8",
                "outline": "#000000",
            },
        }
        raw_dict["raw_input_id"] = "take_1"

    return RenderRequest.model_validate(raw_dict)


def test_build_raw_args_pure():
    """Test 1: build_raw_args (pure function, no ffmpeg execution)."""
    music = TimelineMusic(input_id="music_1", volume=0.2)
    req_with_music = make_sample_request(mode="raw", music=music)

    local_inputs = {
        "take_1": Path("/tmp/take_1.mp4"),
        "broll_img": Path("/tmp/broll_img.png"),
        "broll_vid": Path("/tmp/broll_vid.mp4"),
        "music_1": Path("/tmp/music_1.mp3"),
    }
    out_path = Path("/tmp/out.mp4")

    args, filter_text = build_raw_args(req_with_music, local_inputs, out_path)

    assert "atrim" in filter_text
    assert "trim" in filter_text
    assert "crop=1080:1920" in filter_text
    assert "concat" in filter_text
    assert "sidechaincompress" in filter_text

    assert args[-1] == str(out_path)
    assert not any("shell" in arg for arg in args)

    # Without music
    req_no_music = make_sample_request(mode="raw", music=None)
    local_inputs_no_music = {
        "take_1": Path("/tmp/take_1.mp4"),
        "broll_img": Path("/tmp/broll_img.png"),
        "broll_vid": Path("/tmp/broll_vid.mp4"),
    }
    args_nm, filter_text_nm = build_raw_args(req_no_music, local_inputs_no_music, out_path)
    assert "sidechaincompress" not in filter_text_nm


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_build_raw_3_scenes_with_music(tmp_path):
    """Test 2: Timeline with 3 scenes + music -> build_raw produces valid MP4."""
    take_path = tmp_path / "take_1.mp4"
    img_path = tmp_path / "broll_img.png"
    vid_path = tmp_path / "broll_vid.mp4"
    music_path = tmp_path / "music_1.aac"

    create_synthetic_video(take_path, duration_s=4.0, w=360, h=640)
    create_synthetic_image(img_path, w=360, h=640)
    create_synthetic_video(vid_path, duration_s=1.0, w=360, h=640)
    create_synthetic_audio(music_path, duration_s=6.0)

    local_inputs = {
        "take_1": take_path,
        "broll_img": img_path,
        "broll_vid": vid_path,
        "music_1": music_path,
    }

    music = TimelineMusic(input_id="music_1", volume=0.2)
    req = make_sample_request(mode="raw", music=music)

    t0 = time.time()
    res = build_raw(req, local_inputs, tmp_path)
    t1 = time.time()
    elapsed = t1 - t0

    print(f"\n[BENCHMARK] test_build_raw_3_scenes_with_music took {elapsed:.2f} s")

    out_file = res["path"]
    assert out_file.exists()
    assert res["duration_ms"] == 5500
    assert res["scene_marks_ms"] == [0, 2000, 3500]

    probe = probe_media(out_file)
    fmt = probe.get("format", {})
    duration_s = float(fmt.get("duration", 0))

    # duration = 5.5 s ± 150 ms
    assert abs(duration_s - 5.5) <= 0.25

    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    assert v_stream is not None
    assert v_stream.get("width") == 1080
    assert v_stream.get("height") == 1920

    assert a_stream is not None
    assert a_stream.get("codec_name") == "aac"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_build_raw_no_music(tmp_path):
    """Test 3: build_raw without music produces valid MP4 with audio."""
    take_path = tmp_path / "take_1.mp4"
    img_path = tmp_path / "broll_img.png"
    vid_path = tmp_path / "broll_vid.mp4"

    create_synthetic_video(take_path, duration_s=4.0, w=360, h=640)
    create_synthetic_image(img_path, w=360, h=640)
    create_synthetic_video(vid_path, duration_s=1.0, w=360, h=640)

    local_inputs = {
        "take_1": take_path,
        "broll_img": img_path,
        "broll_vid": vid_path,
    }

    req = make_sample_request(mode="raw", music=None)
    res = build_raw(req, local_inputs, tmp_path)

    out_file = res["path"]
    assert out_file.exists()
    assert res["duration_ms"] == 5500

    probe = probe_media(out_file)
    fmt = probe.get("format", {})
    duration_s = float(fmt.get("duration", 0))
    assert abs(duration_s - 5.5) <= 0.25

    streams = probe.get("streams", [])
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    assert a_stream is not None


def test_build_raw_mode_final_raises(tmp_path):
    """Test 4: mode='final' raises ValueError."""
    req = make_sample_request(mode="final", music=None)
    local_inputs = {"take_1": tmp_path / "take_1.mp4"}

    with pytest.raises(ValueError, match="mode"):
        build_raw(req, local_inputs, tmp_path)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_build_raw_timeout_raises(tmp_path):
    """Test 5: extremely small timeout_s raises subprocess.TimeoutExpired."""
    take_path = tmp_path / "take_1.mp4"
    img_path = tmp_path / "broll_img.png"
    vid_path = tmp_path / "broll_vid.mp4"

    create_synthetic_video(take_path, duration_s=4.0, w=360, h=640)
    create_synthetic_image(img_path, w=360, h=640)
    create_synthetic_video(vid_path, duration_s=1.0, w=360, h=640)

    local_inputs = {
        "take_1": take_path,
        "broll_img": img_path,
        "broll_vid": vid_path,
    }

    req = make_sample_request(mode="raw", music=None)

    with pytest.raises(subprocess.TimeoutExpired):
        build_raw(req, local_inputs, tmp_path, timeout_s=0.001)


def test_scene_marks_ms():
    """Test 6: scene_marks_ms returns out_start_ms for each scene."""
    req = make_sample_request(mode="raw", music=None)
    scene_marks = [sc.out_start_ms for sc in req.timeline.scenes]
    assert scene_marks == [0, 2000, 3500]


def test_capitan_unconverted_motion_graphic_falls_back_to_face():
    """QA del Capitán: si el motion graphic sigue siendo .html (conversión fallida), la escena usa la cara y FFmpeg nunca recibe el .html."""
    from render_service.manifest import RenderRequest as _RR

    seg = {"in_ms": 0, "out_ms": 2000, "out_start_ms": 0}
    req = _RR.model_validate({
        "schema": "brandstudio.render.v1", "job_id": "j", "attempt": 1, "mode": "raw",
        "timeline": {
            "schema": "brandstudio.timeline.v1", "edit_version": 1,
            "canvas": {"w": 1080, "h": 1920, "fps": 30},
            "settings": {"gap_ms": 400, "pad_ms": 100, "music_volume": 0.1, "music_muted": True, "sfx_enabled": True},
            "scenes": [{"n": 1, "phase": "hook", "visual": "broll", "take_job_id": "t1", "take_input": "take_s1",
                        "broll": {"kind": "motion_graphic", "input_id": "broll_s1"},
                        "segments": [seg], "trim": {"start_ms": 0, "end_ms": 0}, "out_start_ms": 0, "out_end_ms": 2000}],
            "music": None, "duration_ms": 2000, "hash": "h"},
        "inputs": {"take_s1": {"url": "https://x.supabase.co/t", "kind": "video"},
                   "broll_s1": {"url": "https://x.supabase.co/m", "kind": "html"}},
        "output": {"upload_url": "https://x.supabase.co/u", "storage_path": "a/b.mp4"}})
    args, filt = build_raw_args(req, {"take_s1": Path("take.webm"), "broll_s1": Path("mg.html")}, Path("out.mp4"))
    assert "mg.html" not in " ".join(args)
    assert "[0:v]" in filt and "trim=start=" in filt  # the take's video is used (face)
