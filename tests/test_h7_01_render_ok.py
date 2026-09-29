"""H7-01: RenderOk carries scene_fallbacks so a raw render never 500s after upload."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import render_service.app as app_module
from render_service.app import app
from render_service.manifest import RenderOk, SceneFallback
from render_service.version import ENGINE_VERSION
from tests.test_render_service_p71_manifest import make_valid_raw_request_dict

SECRET = "s3cret-test-0123456789abcdef0123"
BASE = {
    "storage_path": "raw/x.mp4",
    "duration_ms": 1000,
    "bytes": 10,
    "render_s": 0.5,
    "scene_marks_ms": [0, 1000],
}


def test_render_ok_scene_fallbacks_defaults_to_empty_list():
    assert RenderOk(**BASE).scene_fallbacks == []


def test_render_ok_accepts_scene_fallbacks():
    fb = {"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}
    ok = RenderOk(**BASE, scene_fallbacks=[fb])
    assert ok.scene_fallbacks == [SceneFallback(**fb)]
    assert ok.model_dump()["scene_fallbacks"] == [fb]


def test_render_ok_still_forbids_unknown_fields_and_bad_used():
    with pytest.raises(ValidationError):
        RenderOk(**BASE, surprise=1)
    with pytest.raises(ValidationError):
        RenderOk(
            **BASE, scene_fallbacks=[{"scene_n": 1, "used": "video", "reason": "r"}]
        )


def test_engine_version_bumped():
    assert ENGINE_VERSION == "2026.09.29"


def test_raw_request_with_blank_mg_returns_200_and_scene_fallbacks(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_SECRET", SECRET)

    def mock_download_all(inputs, workdir, **kwargs):
        res = {}
        for k in inputs:
            p = workdir / f"{k}.mp4"
            p.write_bytes(b"mock video input")
            res[k] = p
        return res

    def fake_raw_builder(request, local_inputs, workdir):
        out_file = workdir / "rendered.mp4"
        out_file.write_bytes(b"X" * 1024)
        return {
            "path": out_file,
            "duration_ms": 1000,
            "scene_marks_ms": [0, 1000],
            "scene_fallbacks": [
                {"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}
            ],
        }

    monkeypatch.setattr(app_module, "download_all", mock_download_all)
    monkeypatch.setattr(app_module, "upload", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "RAW_BUILDER", fake_raw_builder)

    resp = TestClient(app).post(
        "/v1/render",
        json=make_valid_raw_request_dict(),
        headers={"Authorization": f"Bearer {SECRET}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["scene_fallbacks"] == [
        {"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}
    ]
