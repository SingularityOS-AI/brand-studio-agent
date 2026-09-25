"""Tests for render_service HTTP app, auth, downloads, uploads, and error handling (PIEZA 73)."""

import ast
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(r"C:\Python312_Neural\DLLs")
    except Exception:
        pass

import render_service.app as app_module
from render_service.app import app
from render_service.io_utils import FetchError, TooLargeError, check_url, download
from tests.test_render_service_p71_manifest import make_valid_raw_request_dict


# 1. Sin secreto configurado → 503; sin header o header malo → 401
def test_auth_and_secret_configuration(monkeypatch):
    client = TestClient(app)

    # 1a. Sin secreto configurado → 503
    monkeypatch.delenv("RENDER_SERVICE_SECRET", raising=False)
    resp = client.post("/v1/render", json={})
    assert resp.status_code == 503
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "bad_manifest"
    assert data["detail"] == "service not configured"

    # 1b. Secreto configurado, pero sin header → 401
    secret = "s3cret-test-0123456789abcdef0123"
    monkeypatch.setenv("RENDER_SERVICE_SECRET", secret)
    resp = client.post("/v1/render", json={})
    assert resp.status_code == 401
    assert resp.json()["code"] == "bad_manifest"

    # 1c. Header malo → 401
    resp = client.post(
        "/v1/render",
        json={},
        headers={"Authorization": "Bearer wrong-token-1234567890000000"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "bad_manifest"


# 2. Manifest inválido → 400 bad_manifest, y el detail no contiene token=
def test_invalid_manifest_redacts_detail(monkeypatch):
    secret = "s3cret-test-0123456789abcdef0123"
    monkeypatch.setenv("RENDER_SERVICE_SECRET", secret)
    client = TestClient(app)

    invalid_body = {
        "invalid_field": "test",
        "url_with_token": "https://supabase.co/storage/v1/object/sign/b.mp4?token=secret123token",
    }
    headers = {"Authorization": f"Bearer {secret}"}
    resp = client.post("/v1/render", json=invalid_body, headers=headers)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "bad_manifest"
    assert "token=secret123token" not in data["detail"]
    assert "?token=" not in data["detail"]


# 3. check_url: http://, host no permitido, https://user:pw@supabase.co/x, https://127.0.0.1/x → FetchError;
# https://abc.supabase.co/storage/v1/... y https://videos.pexels.com/... → OK
def test_check_url_validation():
    with pytest.raises(FetchError):
        check_url("http://supabase.co/video.mp4")

    with pytest.raises(FetchError):
        check_url("https://forbidden-domain.com/video.mp4")

    with pytest.raises(FetchError):
        check_url("https://user:pw@supabase.co/video.mp4")

    with pytest.raises(FetchError):
        check_url("https://127.0.0.1/video.mp4")

    # Valid URLs pass without raising
    check_url("https://abc.supabase.co/storage/v1/object/public/file.mp4")
    check_url("https://videos.pexels.com/video-files/123/456.mp4")


# 4. download con MockTransport que sirve 2 MB y max_bytes=1 MB → TooLargeError y el archivo parcial no existe
def test_download_too_large_cleanup(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"X" * (2 * 1024 * 1024))

    mock_transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=mock_transport)

    dest_file = tmp_path / "test_too_large.mp4"
    with pytest.raises(TooLargeError):
        download(
            url="https://videos.pexels.com/v.mp4",
            dest=dest_file,
            max_bytes=1024 * 1024,
            client=client,
        )

    assert not dest_file.exists()


# 5. Redirección hacia un host no permitido → FetchError
def test_download_redirect_to_disallowed_host_fails(tmp_path):
    def handler(request):
        if str(request.url) == "https://videos.pexels.com/redirect":
            return httpx.Response(
                302, headers={"location": "https://unauthorized-evil-site.com/v.mp4"}
            )
        return httpx.Response(200, content=b"data")

    mock_transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=mock_transport)

    dest_file = tmp_path / "redirect_test.mp4"
    with pytest.raises(FetchError):
        download(
            url="https://videos.pexels.com/redirect",
            dest=dest_file,
            max_bytes=10 * 1024 * 1024,
            client=client,
        )

    assert not dest_file.exists()


# 6. Camino feliz raw: RAW_BUILDER falso que escribe un archivo de 1 KB, download_all y upload parchados
# (o MockTransport) → 200 con RenderOk válido, render_s >= 0, y upload llamado con el upload_url del manifest
def test_happy_path_raw_render(monkeypatch):
    secret = "s3cret-test-0123456789abcdef0123"
    monkeypatch.setenv("RENDER_SERVICE_SECRET", secret)

    def mock_download_all(inputs, workdir, **kwargs):
        res = {}
        for k in inputs:
            p = workdir / f"{k}.mp4"
            p.write_bytes(b"mock video input")
            res[k] = p
        return res

    uploaded_calls = []

    def mock_upload(upload_url, path, **kwargs):
        uploaded_calls.append((upload_url, path.read_bytes()))

    monkeypatch.setattr(app_module, "download_all", mock_download_all)
    monkeypatch.setattr(app_module, "upload", mock_upload)

    def fake_raw_builder(request, local_inputs, workdir):
        out_file = workdir / "rendered.mp4"
        out_file.write_bytes(b"X" * 1024)
        return {
            "path": out_file,
            "duration_ms": 1000,
            "scene_marks_ms": [0, 1000],
        }

    monkeypatch.setattr(app_module, "RAW_BUILDER", fake_raw_builder)

    req_dict = make_valid_raw_request_dict()
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {secret}"}
    resp = client.post("/v1/render", json=req_dict, headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["storage_path"] == req_dict["output"]["storage_path"]
    assert data["duration_ms"] == 1000
    assert data["bytes"] == 1024
    assert data["render_s"] >= 0.0
    assert len(uploaded_calls) == 1
    assert uploaded_calls[0][0] == req_dict["output"]["upload_url"]


# 7. Builder que lanza subprocess.TimeoutExpired → 504 timeout retryable: true; que lanza RuntimeError → 500 ffmpeg_failed
def test_builder_exceptions_mapped_to_status_codes(monkeypatch):
    secret = "s3cret-test-0123456789abcdef0123"
    monkeypatch.setenv("RENDER_SERVICE_SECRET", secret)

    monkeypatch.setattr(app_module, "download_all", lambda inputs, workdir, **kw: {})

    # 7a. TimeoutExpired -> 504 timeout, retryable: True
    def timeout_builder(request, local_inputs, workdir):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=240)

    monkeypatch.setattr(app_module, "RAW_BUILDER", timeout_builder)

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {secret}"}
    req_dict = make_valid_raw_request_dict()

    resp = client.post("/v1/render", json=req_dict, headers=headers)
    assert resp.status_code == 504
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "timeout"
    assert data["retryable"] is True

    # 7b. RuntimeError -> 500 ffmpeg_failed
    def error_builder(request, local_inputs, workdir):
        raise RuntimeError("FFmpeg crashed")

    monkeypatch.setattr(app_module, "RAW_BUILDER", error_builder)
    resp = client.post("/v1/render", json=req_dict, headers=headers)
    assert resp.status_code == 500
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "ffmpeg_failed"
    assert data["retryable"] is False


# 8. MP4 más grande que max_bytes → 413 too_large y no se sube
def test_output_exceeds_max_bytes_fails(monkeypatch):
    secret = "s3cret-test-0123456789abcdef0123"
    monkeypatch.setenv("RENDER_SERVICE_SECRET", secret)

    monkeypatch.setattr(app_module, "download_all", lambda inputs, workdir, **kw: {})
    uploaded = []
    monkeypatch.setattr(app_module, "upload", lambda url, path, **kw: uploaded.append(url))

    def large_builder(request, local_inputs, workdir):
        out_file = workdir / "output.mp4"
        out_file.write_bytes(b"Y" * 2048)
        return {"path": out_file, "duration_ms": 1000}

    monkeypatch.setattr(app_module, "RAW_BUILDER", large_builder)

    req_dict = make_valid_raw_request_dict()
    req_dict["output"]["max_bytes"] = 1024

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {secret}"}
    resp = client.post("/v1/render", json=req_dict, headers=headers)

    assert resp.status_code == 413
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "too_large"
    assert len(uploaded) == 0


# 9. render_service no importa app (análisis ast de app.py e io_utils.py)
def test_render_service_does_not_import_app():
    root = Path(__file__).parent.parent / "render_service"
    for py_file in root.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app"), (
                        f"Forbidden import of app in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("app"), (
                    f"Forbidden import from app in {py_file}"
                )


def test_healthz_endpoint():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["ffmpeg"], bool)
