"""Tests for render_service manifest models and helpers (PIEZA 71)."""

import ast
import os
from pathlib import Path
import pytest
from pydantic import ValidationError

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(r"C:\Python312_Neural\DLLs")
    except Exception:
        pass

from render_service.manifest import (
    CaptionEvent,
    CaptionStyle,
    InputRef,
    RenderError,
    RenderRequest,
    Segment,
    Timeline,
    hex_to_ass,
    timeline_hash,
)


def make_valid_timeline_dict():
    return {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "take_job_id": "job_123",
                "take_input": "take_1",
                "segments": [{"in_ms": 0, "out_ms": 1000, "out_start_ms": 0}],
                # trim = founder's ±500 ms adjustment (not an absolute range)
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 1000,
            }
        ],
        "music": None,
        "duration_ms": 1000,
        "hash": "dummy_hash",
    }


def make_valid_ir_dict():
    return {
        "schema": "brandstudio.ir.v1",
        "duration_ms": 5000,
        "frame_zero": {"text": "Hook text", "start_ms": 0, "end_ms": 1500},
        "captions": [],
        "zoom_keys": [],
        "transitions": [],
        "overlays": [],
        "sfx": [],
        "style": {
            "font": "Inter",
            "text": "#FFFFFF",
            "accent": "#2B4CD8",
            "outline": "#000000",
        },
    }


def make_valid_raw_request_dict():
    return {
        "schema": "brandstudio.render.v1",
        "job_id": "job_raw_1",
        "attempt": 1,
        "mode": "raw",
        "timeline": make_valid_timeline_dict(),
        "ir": None,
        "raw_input_id": None,
        "inputs": {"take_1": {"url": "https://example.com/take1.mp4", "kind": "video"}},
        "convert": [],
        "output": {
            "upload_url": "https://example.com/upload",
            "storage_path": "output/video.mp4",
            "max_bytes": 47000000,
        },
        "progress_url": None,
    }


def make_valid_final_request_dict():
    return {
        "schema": "brandstudio.render.v1",
        "job_id": "job_final_1",
        "attempt": 1,
        "mode": "final",
        "timeline": None,
        "ir": make_valid_ir_dict(),
        "raw_input_id": "raw_input",
        "inputs": {"raw_input": {"url": "https://example.com/raw.mp4", "kind": "video"}},
        "convert": [],
        "output": {
            "upload_url": "https://example.com/upload",
            "storage_path": "output/video.mp4",
            "max_bytes": 47000000,
        },
        "progress_url": None,
    }


# 1. Un RenderRequest raw mínimo válido y uno final mínimo válido parsean (model_validate)
def test_minimal_raw_and_final_request_parse():
    raw_req = RenderRequest.model_validate(make_valid_raw_request_dict())
    assert raw_req.mode == "raw"
    assert raw_req.timeline is not None
    assert raw_req.ir is None

    final_req = RenderRequest.model_validate(make_valid_final_request_dict())
    assert final_req.mode == "final"
    assert final_req.timeline is None
    assert final_req.ir is not None


# 2. Campo extra en cualquier nivel -> ValidationError
def test_extra_field_forbidden():
    raw_dict = make_valid_raw_request_dict()
    raw_dict["unexpected_field"] = "bad"
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(raw_dict)

    tl_dict = make_valid_timeline_dict()
    tl_dict["extra_key"] = 123
    with pytest.raises(ValidationError):
        Timeline.model_validate(tl_dict)


# 3. Color #12345 o red -> error; hex_to_ass("#2B4CD8") == "&H00D84C2B"
def test_hex_color_validation_and_ass_conversion():
    with pytest.raises(ValidationError):
        CaptionStyle.model_validate({
            "font": "Inter",
            "text": "#12345",
            "accent": "#2B4CD8",
            "outline": "#000000",
        })

    with pytest.raises(ValidationError):
        CaptionStyle.model_validate({
            "font": "Inter",
            "text": "red",
            "accent": "#2B4CD8",
            "outline": "#000000",
        })

    assert hex_to_ass("#2B4CD8") == "&H00D84C2B"

    with pytest.raises(ValueError):
        hex_to_ass("#12345")


# 4. Fuente fuera de FONT_ALLOWLIST -> error
def test_font_not_in_allowlist():
    with pytest.raises(ValidationError):
        CaptionStyle.model_validate({
            "font": "Comic Sans MS",
            "text": "#FFFFFF",
            "accent": "#2B4CD8",
            "outline": "#000000",
        })


# 5. mode="raw" sin timeline -> error; mode="final" sin ir o con raw_input_id que no está en inputs -> error
def test_mode_requirements():
    bad_raw = make_valid_raw_request_dict()
    bad_raw["timeline"] = None
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(bad_raw)

    bad_final_1 = make_valid_final_request_dict()
    bad_final_1["ir"] = None
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(bad_final_1)

    bad_final_2 = make_valid_final_request_dict()
    bad_final_2["raw_input_id"] = "nonexistent_input"
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(bad_final_2)


# 6. take_input que no está en inputs -> error
def test_take_input_missing_from_inputs():
    raw_dict = make_valid_raw_request_dict()
    raw_dict["inputs"] = {"other_input": {"url": "https://example.com/other.mp4", "kind": "video"}}
    with pytest.raises(ValidationError):
        RenderRequest.model_validate(raw_dict)


# 7. Segmento con out_ms <= in_ms -> error; canvas 720x1280 -> error
def test_segment_times_and_canvas_dimensions():
    with pytest.raises(ValidationError):
        Segment.model_validate({"in_ms": 1000, "out_ms": 500, "out_start_ms": 0})

    with pytest.raises(ValidationError):
        Segment.model_validate({"in_ms": 1000, "out_ms": 1000, "out_start_ms": 0})

    tl_dict = make_valid_timeline_dict()
    tl_dict["canvas"] = {"w": 720, "h": 1280, "fps": 30}
    with pytest.raises(ValidationError):
        Timeline.model_validate(tl_dict)


# 8. InputRef con http:// -> error
def test_input_ref_http_forbidden():
    with pytest.raises(ValidationError):
        InputRef.model_validate({"url": "http://example.com/video.mp4", "kind": "video"})


# 9. timeline_hash es determinista, ignora la clave hash y cambia si cambia un segmento
def test_timeline_hash_behavior():
    tl1 = make_valid_timeline_dict()
    tl2 = make_valid_timeline_dict()
    tl2["hash"] = "different_hash"

    h1 = timeline_hash(tl1)
    h2 = timeline_hash(tl2)
    assert h1 == h2

    tl3 = make_valid_timeline_dict()
    tl3["scenes"][0]["segments"][0]["out_ms"] = 2000
    h3 = timeline_hash(tl3)
    assert h1 != h3


# 10. RenderError.detail con 900 caracteres y una URL con ?token=abc -> <=500 caracteres y sin token=abc
def test_render_error_detail_sanitization():
    long_detail = (
        "Error fetching https://storage.supabase.co/v1/object/sign/brand-assets/file.mp4?token=abc123secret&other=val "
        + "x" * 900
    )
    err = RenderError(
        code="fetch_failed",
        retryable=True,
        detail=long_detail,
    )
    assert len(err.detail) <= 500
    assert "token=abc123secret" not in err.detail
    assert "?token=" not in err.detail


# 11. CaptionEvent con 3 líneas o una línea de 4 tokens -> error
def test_caption_event_line_and_token_limits():
    token = {"text": "hello", "start_ms": 0, "end_ms": 500}

    # 3 lines -> error
    with pytest.raises(ValidationError):
        CaptionEvent.model_validate({
            "start_ms": 0,
            "end_ms": 500,
            "lines": [[token], [token], [token]],
            "size": "hero",
            "emphasis": [],
        })

    # 1 line of 4 tokens -> error
    with pytest.raises(ValidationError):
        CaptionEvent.model_validate({
            "start_ms": 0,
            "end_ms": 500,
            "lines": [[token, token, token, token]],
            "size": "hero",
            "emphasis": [],
        })


# 12. render_service no importa app (usa ast sobre manifest.py y __init__.py: ningún import app/from app)
def test_render_service_does_not_import_app():
    root = Path(__file__).parent.parent / "render_service"
    for py_file in root.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app"), f"Forbidden import of app in {py_file}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("app"), (
                    f"Forbidden import from app in {py_file}"
                )


def test_trim_is_a_bounded_adjustment():
    """Trim holds the founder's ±0.5 s nudge: negative keeps more air, beyond ±500 is rejected."""
    from render_service.manifest import Trim

    assert Trim(start_ms=-500, end_ms=500).start_ms == -500
    with pytest.raises(ValidationError):
        Trim(start_ms=-501, end_ms=0)
    with pytest.raises(ValidationError):
        Trim(start_ms=0, end_ms=501)
