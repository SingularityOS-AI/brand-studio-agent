"""Tests for Piece E2-02: Seek-capture module and non-blank motion graphics."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from app.audiovisual.motion_graphics import build_html
from render_service.motion import chromium_path, convert_html

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(
        chromium_path() is None or shutil.which("ffmpeg") is None,
        reason="Chromium and FFmpeg are required for render tests",
    ),
]

TEMPLATES_TO_TEST = [
    (
        "stat",
        {"value": "40%", "headline": "Growth in 2026"},
    ),
    (
        "quote",
        {
            "headline": "The future belongs to those who build it",
            "subline": "Gabriel Bustos",
        },
    ),
    (
        "list",
        {
            "headline": "Key Milestones",
            "items": ["1. Discover", "2. Automate", "3. Scale"],
        },
    ),
    (
        "lower_third",
        {"headline": "Gabriel Bustos", "subline": "Chief Technology Officer"},
    ),
]


def extract_frame(mp4_path: Path, t_s: float, out_png: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{t_s:.3f}",
            "-i",
            str(mp4_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out_png),
        ],
        check=True,
        capture_output=True,
    )
    return out_png


@pytest.mark.parametrize("template_name,fields", TEMPLATES_TO_TEST)
def test_template_seek_render_non_blank(
    template_name: str, fields: dict, tmp_path: Path
):
    """
    Each template rendered for 6s:
    - Frame at 3.0s is NOT near-uniform (luma std-dev > 8).
    - Frame at 3.0s differs from frame at 0.0s.
    """
    html_content = build_html(template_name, fields, duration_s=6.0)
    html_file = tmp_path / f"{template_name}.html"
    html_file.write_text(html_content, encoding="utf-8")

    out_mp4 = tmp_path / f"{template_name}.mp4"
    workdir = tmp_path / f"work_{template_name}"

    t0 = time.perf_counter()
    res = convert_html(html_file, out_mp4, duration_s=6.0, workdir=workdir)
    wall_s = time.perf_counter() - t0

    assert res.exists() and res.stat().st_size > 0
    assert wall_s < 60.0

    frame_0s = tmp_path / f"{template_name}_0s.png"
    frame_3s = tmp_path / f"{template_name}_3s.png"

    extract_frame(out_mp4, 0.0, frame_0s)
    extract_frame(out_mp4, 3.0, frame_3s)

    img_0s = Image.open(frame_0s).convert("L")
    img_3s = Image.open(frame_3s).convert("L")

    # 1. Luma std-dev > 8 (not near-uniform / blank)
    stat_3s = ImageStat.Stat(img_3s)
    luma_stddev = stat_3s.stddev[0]
    assert luma_stddev > 8.0, (
        f"Template {template_name} at 3s had luma std-dev {luma_stddev:.2f} <= 8"
    )

    # 2. Differs from frame at 0.0s
    diff = ImageChops.difference(img_3s, img_0s)
    diff_stat = ImageStat.Stat(diff)
    diff_mean = diff_stat.mean[0]
    assert diff_mean > 1.0, (
        f"Template {template_name} at 3s did not differ from 0s (mean diff: {diff_mean:.2f})"
    )


def test_convert_html_fallback_when_seek_fails(monkeypatch, tmp_path: Path):
    """With seek-capture forced to fail, convert_html still produces a non-blank video."""

    def mock_capture(*args, **kwargs):
        raise RuntimeError("Simulated seek_capture failure")

    monkeypatch.setattr("render_service.seek_capture.capture", mock_capture)
    # Force the HyperFrames fallback branch off too: without this, on a machine
    # with `npx` on PATH but no local `hyperframes` package cached, motion.py's
    # hyperframes_cmd() would shell out to `npx hyperframes@0.8.75`, which makes
    # a real network call to the npm registry (forbidden in tests by AGENTS.md).
    monkeypatch.setattr("render_service.motion.hyperframes_cmd", lambda: None)

    html_content = build_html(
        "stat", {"value": "99%", "headline": "Fallback Test"}, duration_s=4.0
    )
    html_file = tmp_path / "fallback.html"
    html_file.write_text(html_content, encoding="utf-8")

    out_mp4 = tmp_path / "fallback.mp4"
    workdir = tmp_path / "work_fallback"

    res = convert_html(html_file, out_mp4, duration_s=4.0, workdir=workdir)
    assert res.exists() and res.stat().st_size > 0

    frame_path = tmp_path / "fallback_frame.png"
    extract_frame(out_mp4, 2.0, frame_path)

    img = Image.open(frame_path).convert("L")
    stat = ImageStat.Stat(img)
    assert stat.stddev[0] > 8.0, (
        f"Fallback produced near-uniform frame: stddev={stat.stddev[0]:.2f}"
    )
