"""Tests for render_service PIEZA 90B: HTML cards rendering to PNG and FFmpeg overlay composition."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from render_service.cards import card_html, render_card_png
from render_service.ffmpeg_dress import build_final, build_final_args
from render_service.manifest import CaptionStyle, OverlayCue, RenderIR, RenderRequest


def test_1_card_html_escapes_text_and_includes_font_size():
    style = CaptionStyle(
        font="Inter",
        text="#FFFFFF",
        accent="#2B4CD8",
        outline="#000000",
    )
    ov = OverlayCue(
        id="ov1",
        kind="card_stat",
        text="<script>alert(1)</script>",
        start_ms=1000,
        end_ms=3000,
        x=90,
        y=760,
        w=900,
        h=400,
        anim="pop",
    )

    html_out = card_html(ov, style)

    assert "<script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "110px" in html_out
    assert "Inter" in html_out


def test_2_render_card_png_raises_runtime_error_without_chromium(tmp_path: Path):
    style = CaptionStyle(
        font="Inter",
        text="#FFFFFF",
        accent="#2B4CD8",
        outline="#000000",
    )
    ov = OverlayCue(
        id="ov1",
        kind="onscreen_text",
        text="Test Overlay",
        start_ms=1000,
        end_ms=3000,
        x=90,
        y=1300,
        w=900,
        h=200,
        anim="pop",
    )
    out_png = tmp_path / "card.png"

    with patch("render_service.cards.chromium_path", return_value=None):
        with pytest.raises(RuntimeError, match="Chromium executable not found"):
            render_card_png(ov, style, out_png, tmp_path)


def test_3_build_final_args_with_overlays_uses_filter_complex(tmp_path: Path):
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        pytest.skip("FFmpeg not installed")

    card_png = tmp_path / "card_ov1.png"
    cmd_card = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=900x200,format=rgba",
        "-vframes",
        "1",
        "-y",
        str(card_png),
    ]
    subprocess.run(cmd_card, check=True)

    broll_img = tmp_path / "broll_img.jpg"
    cmd_broll = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=420x420",
        "-vframes",
        "1",
        "-y",
        str(broll_img),
    ]
    subprocess.run(cmd_broll, check=True)

    ov1 = OverlayCue(
        id="ov1",
        kind="onscreen_text",
        text="Hello World",
        start_ms=1000,
        end_ms=3000,
        x=90,
        y=1300,
        w=900,
        h=200,
        anim="pop",
    )
    ov2 = OverlayCue(
        id="ov2",
        kind="broll_card",
        asset="broll_input",
        start_ms=2000,
        end_ms=4000,
        x=60,
        y=700,
        w=420,
        h=420,
        anim="pop",
    )

    style = CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=5000,
        overlays=[ov1, ov2],
        style=style,
    )
    req = RenderRequest(
        schema="brandstudio.render.v1",
        job_id="job_overlay_test",
        attempt=1,
        mode="final",
        raw_input_id="raw_video",
        ir=ir,
        inputs={
            "raw_video": {"url": "https://example.com/raw.mp4", "kind": "video"},
            "broll_input": {"url": "https://example.com/broll.jpg", "kind": "image"},
        },
        output={"upload_url": "https://example.com/out.mp4", "storage_path": "test/out.mp4"},
    )

    raw_mp4 = tmp_path / "raw.mp4"
    out_mp4 = tmp_path / "out.mp4"
    local_inputs = {"raw_video": raw_mp4, "broll_input": broll_img}
    overlay_files = {"ov1": card_png, "ov2": broll_img}

    args = build_final_args(
        req,
        local_inputs,
        out_mp4,
        "subs.ass",
        tmp_path / "fonts",
        tmp_path,
        overlay_files=overlay_files,
    )

    assert "-filter_complex" in args
    fc_str = args[args.index("-filter_complex") + 1]

    assert "fade=t=in:st=" in fc_str
    assert "alpha=1" in fc_str
    assert "overlay=x=90:y=1300" in fc_str
    assert "enable='between(t," in fc_str

    pos_last_overlay = fc_str.rfind("overlay=")
    pos_ass = fc_str.rfind("ass=")
    assert pos_ass > pos_last_overlay > -1


def test_4_real_ffmpeg_render_with_text_overlay(tmp_path: Path):
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        pytest.skip("FFmpeg not installed")

    raw_mp4 = tmp_path / "raw_4s.mp4"
    cmd_raw = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=1080x1920:r=30:d=4",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(raw_mp4),
    ]
    subprocess.run(cmd_raw, check=True)

    def fake_render_card_png(ov, style, out_png, workdir, timeout_s=30):
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        cmd_red = [
            ffmpeg_exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s={ov.w}x{ov.h},format=rgba",
            "-vframes",
            "1",
            "-y",
            str(out_png),
        ]
        subprocess.run(cmd_red, check=True)
        return out_png

    ov_text = OverlayCue(
        id="ov_red",
        kind="onscreen_text",
        text="Red Box",
        start_ms=1000,
        end_ms=3000,
        x=90,
        y=1300,
        w=900,
        h=200,
        anim="pop",
    )

    style = CaptionStyle(font="Inter", text="#FFFFFF", accent="#2B4CD8", outline="#000000")
    ir = RenderIR(
        schema="brandstudio.ir.v1",
        duration_ms=4000,
        overlays=[ov_text],
        style=style,
    )
    req = RenderRequest(
        schema="brandstudio.render.v1",
        job_id="job_real_render_test",
        attempt=1,
        mode="final",
        raw_input_id="raw_video",
        ir=ir,
        inputs={
            "raw_video": {"url": "https://example.com/raw.mp4", "kind": "video"},
        },
        output={"upload_url": "https://example.com/out.mp4", "storage_path": "test/out.mp4"},
    )

    local_inputs = {"raw_video": raw_mp4}

    with patch("render_service.ffmpeg_dress.render_card_png", side_effect=fake_render_card_png):
        res = build_final(req, local_inputs, tmp_path)

    rendered_path = res["path"]
    assert rendered_path.is_file()
    assert rendered_path.stat().st_size > 0

    def get_center_pixel_rgb(timestamp_s: float) -> tuple[int, int, int]:
        cmd_extract = [
            ffmpeg_exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_s:.2f}",
            "-i",
            str(rendered_path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        proc = subprocess.run(cmd_extract, check=True, capture_output=True)
        raw_bytes = proc.stdout
        assert len(raw_bytes) == 1080 * 1920 * 3

        cx, cy = 540, 1400
        offset = (cy * 1080 + cx) * 3
        r = raw_bytes[offset]
        g = raw_bytes[offset + 1]
        b = raw_bytes[offset + 2]
        return r, g, b

    r_mid, g_mid, b_mid = get_center_pixel_rgb(2.0)
    assert r_mid > 150
    assert b_mid < 100

    r_out, g_out, b_out = get_center_pixel_rgb(0.5)
    assert r_out < 50
    assert b_out > 150
