"""Unit tests for PIEZA 75 container & motion graphics converter."""

from __future__ import annotations

import ast
import hashlib
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()


def test_dockerfile_contents():
    dockerfile_path = REPO_ROOT / "render_service" / "Dockerfile"
    assert dockerfile_path.is_file(), "render_service/Dockerfile missing"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "node:22-bookworm-slim" in content
    assert "ffmpeg" in content
    assert "chromium" in content
    assert "fonts-noto-color-emoji" in content
    assert "hyperframes@0.8.75" in content
    assert "USER" in content
    assert "uvicorn" in content
    assert "render_service.app:app" in content
    assert "--workers" in content
    assert "1" in content

    assert "--reload" not in content
    assert "ADD http" not in content


def test_requirements_pinned():
    reqs_path = REPO_ROOT / "render_service" / "requirements.txt"
    assert reqs_path.is_file(), "render_service/requirements.txt missing"
    content = reqs_path.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]

    required_pkgs = {"fastapi", "uvicorn", "httpx", "pydantic"}
    found_pkgs = set()

    for line in lines:
        assert "==" in line, f"Requirement line '{line}' must be pinned with =="
        pkg = line.split("==")[0].strip().lower()
        found_pkgs.add(pkg)

    assert required_pkgs.issubset(
        found_pkgs
    ), f"Missing required pkgs in requirements.txt: {required_pkgs - found_pkgs}"


def test_fonts_and_sources_hashes():
    fonts_dir = REPO_ROOT / "render_service" / "fonts"
    sources_md = fonts_dir / "SOURCES.md"
    assert fonts_dir.is_dir(), "render_service/fonts directory missing"
    assert sources_md.is_file(), "render_service/fonts/SOURCES.md missing"

    sources_content = sources_md.read_text(encoding="utf-8")

    from render_service.manifest import FONT_ALLOWLIST

    ttf_files = list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.otf"))
    for family in FONT_ALLOWLIST:
        clean_family = family.replace(" ", "")
        matching = [
            f
            for f in ttf_files
            if family.lower() in f.name.lower()
            or clean_family.lower() in f.name.lower()
        ]
        assert (
            len(matching) > 0
        ), f"No TTF font file found for allowlist family '{family}'"

    file_blocks = sources_content.split("- **File:**")
    for block in file_blocks[1:]:
        filename_match = re.search(r"`([^`]+)`", block)
        sha_match = re.search(r"SHA256:\*\* `([0-9a-fA-F]{64})`", block)
        if filename_match and sha_match:
            filename = filename_match.group(1)
            expected_sha = sha_match.group(1).lower()
            file_path = fonts_dir / filename
            assert (
                file_path.is_file()
            ), f"File `{filename}` listed in SOURCES.md does not exist"
            actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest().lower()
            assert (
                actual_sha == expected_sha
            ), f"SHA256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}"


def test_convert_html_failure_raises_runtime_error(tmp_path, monkeypatch):
    import render_service.motion as motion

    monkeypatch.setattr(motion, "hyperframes_cmd", lambda: None)
    monkeypatch.setattr(motion, "chromium_path", lambda: None)

    dummy_html = tmp_path / "dummy.html"
    dummy_html.write_text("<html></html>", encoding="utf-8")
    out_mp4 = tmp_path / "out.mp4"

    with pytest.raises(RuntimeError) as exc_info:
        motion.convert_html(dummy_html, out_mp4, 5.0, tmp_path)

    assert "Motion graphic HTML conversion failed" in str(exc_info.value)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not available")
def test_convert_html_chromium_fallback(tmp_path, monkeypatch):
    import render_service.motion as motion

    monkeypatch.setattr(motion, "hyperframes_cmd", lambda: None)
    monkeypatch.setattr(motion, "chromium_path", lambda: "/usr/bin/chromium")

    real_run = subprocess.run

    def fake_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and any("screenshot" in str(arg) for arg in cmd):
            for arg in cmd:
                if str(arg).startswith("--screenshot="):
                    png_dest = pathlib.Path(str(arg).split("=", 1)[1])
                    ffmpeg_exe = shutil.which("ffmpeg")
                    real_run(
                        [
                            ffmpeg_exe,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-f",
                            "lavfi",
                            "-i",
                            "color=c=blue:s=1080x1920:d=1",
                            "-frames:v",
                            "1",
                            "-y",
                            str(png_dest),
                        ],
                        check=True,
                    )
                    return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    dummy_html = tmp_path / "test.html"
    dummy_html.write_text("<h1>Test</h1>", encoding="utf-8")
    out_mp4 = tmp_path / "output.mp4"

    res = motion.convert_html(dummy_html, out_mp4, duration_s=2.0, workdir=tmp_path)
    assert res == out_mp4
    assert out_mp4.is_file()
    assert out_mp4.stat().st_size > 0

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        p = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(out_mp4),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        dur = float(p.stdout.strip())
        assert abs(dur - 2.0) <= 0.1


def test_no_shell_true_in_motion():
    motion_py = REPO_ROOT / "render_service" / "motion.py"
    tree = ast.parse(motion_py.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell":
                    if isinstance(kw.value, ast.Constant):
                        assert (
                            kw.value.value is not True
                        ), "Found shell=True in motion.py!"


def test_app_converter_replaces_local_inputs_path(tmp_path, monkeypatch):
    import render_service.app as service_app

    converted_mp4 = tmp_path / "broll_converted.mp4"
    converted_mp4.write_bytes(b"FAKE_MP4_CONTENT")

    received_inputs = {}

    def fake_raw_builder(req, local_inputs, workdir):
        received_inputs.update(local_inputs)
        out_mp4 = workdir / "raw_out.mp4"
        out_mp4.write_bytes(b"RAW_OUT")
        return {"path": out_mp4, "duration_ms": 3000, "scene_marks_ms": [0]}

    def fake_converter(item, local_inputs, workdir, duration_s=5.0):
        return converted_mp4

    monkeypatch.setattr(service_app, "RAW_BUILDER", fake_raw_builder)
    monkeypatch.setattr(service_app, "CONVERTER", fake_converter)
    monkeypatch.setattr(service_app, "upload", lambda url, path: None)

    orig_html = tmp_path / "broll.html"
    orig_html.write_text("<html></html>", encoding="utf-8")
    take_file = tmp_path / "take.mp4"
    take_file.write_bytes(b"TAKE")

    local_inputs_map = {"mg_broll": orig_html, "take_inp": take_file}

    req_data = {
        "schema": "brandstudio.render.v1",
        "job_id": "job_p75_test",
        "attempt": 1,
        "mode": "raw",
        "timeline": {
            "schema": "brandstudio.timeline.v1",
            "edit_version": 1,
            "canvas": {"w": 1080, "h": 1920, "fps": 30},
            "settings": {
                "gap_ms": 400,
                "pad_ms": 100,
                "music_volume": 0.2,
                "music_muted": True,
                "sfx_enabled": False,
            },
            "scenes": [
                {
                    "n": 1,
                    "phase": "hook",
                    "visual": "broll",
                    "take_job_id": "take1",
                    "take_input": "take_inp",
                    "broll": {
                        "kind": "motion_graphic",
                        "input_id": "mg_broll",
                    },
                    "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                    "trim": {"start_ms": 0, "end_ms": 0},
                    "out_start_ms": 0,
                    "out_end_ms": 3000,
                }
            ],
            "duration_ms": 3000,
            "hash": "abc",
        },
        "inputs": {
            "take_inp": {"url": "https://supabase.co/take.mp4", "kind": "video"},
            "mg_broll": {"url": "https://supabase.co/mg.html", "kind": "html"},
        },
        "convert": [
            {
                "input_id": "mg_broll",
                "upload_url": "https://supabase.co/upload_mg.mp4",
                "storage_path": "converted/mg.mp4",
            }
        ],
        "output": {
            "upload_url": "https://supabase.co/out.mp4",
            "storage_path": "render/out.mp4",
        },
    }

    monkeypatch.setattr(
        service_app, "download_all", lambda inputs, workdir: local_inputs_map.copy()
    )
    monkeypatch.setenv("RENDER_SERVICE_SECRET", "test_secret")

    client = TestClient(service_app.app)
    headers = {"Authorization": "Bearer test_secret"}
    response = client.post("/v1/render", json=req_data, headers=headers)
    assert response.status_code == 200, response.text

    assert (
        received_inputs["mg_broll"] == converted_mp4
    ), "RAW_BUILDER did not receive the converted .mp4 path"
