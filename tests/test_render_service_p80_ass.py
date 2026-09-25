"""Tests for render_service/ffmpeg_dress.py (PIEZA 80)."""

import hashlib
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

from render_service.ffmpeg_dress import ass_escape, build_final, write_ass
from render_service.manifest import (
    CaptionEvent,
    CaptionStyle,
    CaptionToken,
    FrameZero,
    RenderIR,
    RenderRequest,
)


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


def extract_frame_png(video_path: Path, time_s: float, out_png: Path) -> None:
    """Extracts a single video frame as PNG at time_s."""
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
        "image2",
        "-c:v",
        "png",
        str(out_png),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def parse_ass_time_cs(time_str: str) -> int:
    """Parses ASS time string H:MM:SS.cc into centiseconds."""
    match = re.match(r"^(\d+):(\d{2}):(\d{2})\.(\d{2})$", time_str.strip())
    if not match:
        raise ValueError(f"Invalid ASS time format: '{time_str}'")
    h, m, s, c = map(int, match.groups())
    return h * 360000 + m * 6000 + s * 100 + c


def test_1_ass_escape():
    """Test 1: ass_escape escapes ASS control characters, line breaks, and collapses spaces."""
    raw = "a{\\b}c\n{\\pos(1,1)}"
    res = ass_escape(raw)
    assert "{" not in res
    assert "}" not in res
    assert "\\" not in res
    assert "\n" not in res
    assert "\r" not in res
    assert "\t" not in res
    assert "  " not in res
    assert res == "a｛＼b｝c ｛＼pos(1,1)｝"


def test_2_write_ass_structure(tmp_path):
    """Test 2: write_ass produces 1 FrameZero, 1 Hero, and 3 Block dialogues with highlighted tokens."""
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=4000,
        frame_zero=FrameZero(text="Hook zero", start_ms=0, end_ms=1000),
        captions=[
            CaptionEvent(
                start_ms=1000,
                end_ms=2000,
                lines=[[CaptionToken(text="HERO", start_ms=1000, end_ms=2000)]],
                size="hero",
                emphasis=[],
            ),
            CaptionEvent(
                start_ms=2000,
                end_ms=4000,
                lines=[
                    [
                        CaptionToken(text="First", start_ms=2000, end_ms=2500),
                        CaptionToken(text="Second", start_ms=2500, end_ms=3000),
                    ],
                    [CaptionToken(text="Third", start_ms=3000, end_ms=4000)],
                ],
                size="block",
                emphasis=[],
            ),
        ],
        style=CaptionStyle(
            font="Inter",
            text="#FFFFFF",
            accent="#00FF00",
            outline="#000000",
        ),
    )

    ass_file = tmp_path / "test.ass"
    write_ass(ir, ass_file)

    content = ass_file.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]

    assert len(dialogue_lines) == 5  # 1 FrameZero + 1 Hero + 3 Block tokens

    fz_dialogues = [line for line in dialogue_lines if ",FrameZero," in line]
    hero_dialogues = [line for line in dialogue_lines if ",Hero," in line]
    block_dialogues = [line for line in dialogue_lines if ",Block," in line]

    assert len(fz_dialogues) == 1
    assert len(hero_dialogues) == 1
    assert len(block_dialogues) == 3

    # Accent color in hex_to_ass format: #00FF00 -> &H0000FF00
    accent_tag = r"{\c&H0000FF00}"
    text_tag = r"{\c&H00FFFFFF}"

    for b_line in block_dialogues:
        assert "\\N" in b_line
        assert b_line.count(accent_tag) == 1
        assert text_tag in b_line


def test_3_dialogue_times_no_gaps(tmp_path):
    """Test 3: No dialogue end <= start, and Block dialogues cover event without gaps."""
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=4000,
        captions=[
            CaptionEvent(
                start_ms=2000,
                end_ms=4000,
                lines=[
                    [
                        CaptionToken(text="First", start_ms=2000, end_ms=2500),
                        CaptionToken(text="Second", start_ms=2500, end_ms=3000),
                    ],
                    [CaptionToken(text="Third", start_ms=3000, end_ms=4000)],
                ],
                size="block",
                emphasis=[],
            ),
        ],
        style=CaptionStyle(
            font="Inter",
            text="#FFFFFF",
            accent="#00FF00",
            outline="#000000",
        ),
    )

    ass_file = tmp_path / "test_times.ass"
    write_ass(ir, ass_file)

    content = ass_file.read_text(encoding="utf-8-sig")
    dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]

    spans = []
    for d_line in dialogue_lines:
        parts = d_line.split(",")
        start_str = parts[1]
        end_str = parts[2]
        start_cs = parse_ass_time_cs(start_str)
        end_cs = parse_ass_time_cs(end_str)

        assert end_cs > start_cs, f"Dialogue end <= start: {start_str} -> {end_str}"
        spans.append((start_cs, end_cs))

    assert len(spans) == 3
    # Check continuous coverage from 200 cs (2000 ms) to 400 cs (4000 ms)
    assert spans[0][0] == 200
    assert spans[0][1] == spans[1][0] == 250
    assert spans[1][1] == spans[2][0] == 300
    assert spans[2][1] == 400


def test_4_malicious_text_escaped(tmp_path):
    """Test 4: Malicious ASS tags in token text are escaped."""
    malicious_text = r"{\fs200}HACK"
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=2000,
        captions=[
            CaptionEvent(
                start_ms=0,
                end_ms=2000,
                lines=[[CaptionToken(text=malicious_text, start_ms=0, end_ms=2000)]],
                size="hero",
                emphasis=[],
            ),
        ],
        style=CaptionStyle(
            font="Inter",
            text="#FFFFFF",
            accent="#00FF00",
            outline="#000000",
        ),
    )

    ass_file = tmp_path / "malicious.ass"
    write_ass(ir, ass_file)

    content = ass_file.read_text(encoding="utf-8-sig")
    assert r"{\fs200}" not in content
    assert r"｛＼fs200｝HACK" in content


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_5_build_final_ffmpeg_execution(tmp_path):
    """Test 5: build_final renders MP4 with subtitles burned into frame."""
    raw_path = tmp_path / "raw.mp4"
    create_synthetic_raw_video(raw_path, duration_s=4.0, w=1080, h=1920)

    request_dict = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_p80_final",
        "attempt": 1,
        "mode": "final",
        "timeline": None,
        "ir": {
            "schema": "brandstudio.ir.v1",
            "duration_ms": 4000,
            "frame_zero": None,
            "captions": [
                {
                    "start_ms": 500,
                    "end_ms": 3500,
                    "lines": [
                        [
                            {"text": "BRAND", "start_ms": 500, "end_ms": 2000},
                            {"text": "STUDIO", "start_ms": 2000, "end_ms": 3500},
                        ]
                    ],
                    "size": "hero",
                    "emphasis": [],
                }
            ],
            "zoom_keys": [],
            "transitions": [],
            "overlays": [],
            "sfx": [],
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
    local_inputs = {"raw_1": raw_path}

    res = build_final(req, local_inputs, tmp_path)

    out_file = res["path"]
    assert out_file.exists()
    assert res["duration_ms"] == 4000
    assert res["scene_marks_ms"] == []

    probe = probe_media(out_file)
    fmt = probe.get("format", {})
    duration_s = float(fmt.get("duration", 0))
    assert abs(duration_s - 4.0) <= 0.150

    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    assert v_stream is not None
    assert v_stream.get("width") == 1080
    assert v_stream.get("height") == 1920
    assert a_stream is not None

    # Verify burn-in by comparing frame at t=1.5s
    raw_frame_path = tmp_path / "raw_frame.png"
    final_frame_path = tmp_path / "final_frame.png"

    extract_frame_png(raw_path, 1.5, raw_frame_path)
    extract_frame_png(out_file, 1.5, final_frame_path)

    raw_hash = hashlib.sha256(raw_frame_path.read_bytes()).hexdigest()
    final_hash = hashlib.sha256(final_frame_path.read_bytes()).hexdigest()

    assert raw_hash != final_hash


def test_6_build_final_invalid_mode(tmp_path):
    """Test 6: build_final raises ValueError if mode != 'final'."""
    req_dict = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_p80_raw",
        "attempt": 1,
        "mode": "raw",
        "timeline": {
            "schema": "brandstudio.timeline.v1",
            "edit_version": 1,
            "canvas": {"w": 1080, "h": 1920, "fps": 30},
            "settings": {
                "gap_ms": 0,
                "pad_ms": 0,
                "music_volume": 0.2,
                "music_muted": False,
                "sfx_enabled": True,
            },
            "scenes": [
                {
                    "n": 1,
                    "phase": "hook",
                    "visual": "face",
                    "take_job_id": "t1",
                    "take_input": "raw_1",
                    "broll": None,
                    "segments": [{"in_ms": 0, "out_ms": 1000, "out_start_ms": 0}],
                    "trim": {"start_ms": 0, "end_ms": 0},
                    "out_start_ms": 0,
                    "out_end_ms": 1000,
                }
            ],
            "music": None,
            "duration_ms": 1000,
            "hash": "hash_raw",
        },
        "ir": None,
        "raw_input_id": None,
        "inputs": {
            "raw_1": {"url": "https://example.com/raw.mp4", "kind": "video"},
        },
        "convert": [],
        "output": {
            "upload_url": "https://example.com/upload",
            "storage_path": "output/raw.mp4",
            "max_bytes": 47000000,
        },
        "progress_url": None,
    }

    req = RenderRequest.model_validate(req_dict)
    local_inputs = {"raw_1": tmp_path / "raw.mp4"}

    with pytest.raises(ValueError, match="mode"):
        build_final(req, local_inputs, tmp_path)
