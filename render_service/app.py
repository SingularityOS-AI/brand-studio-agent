"""FastAPI application for render service (HTTP endpoint, auth, download/upload, dispatch)."""

from __future__ import annotations

import hmac
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from render_service.io_utils import (
    FetchError,
    TooLargeError,
    download_all,
    post_progress,
    redact,
    upload,
)
from render_service.manifest import (
    ConvertItem,
    RenderError,
    RenderOk,
    RenderRequest,
)

logger = logging.getLogger("brand-studio-render")

app = FastAPI(title="brand-studio-render")


@app.exception_handler(RequestValidationError)
def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    secret = os.getenv("RENDER_SERVICE_SECRET")
    if not secret:
        err = RenderError(
            ok=False,
            code="bad_manifest",
            retryable=False,
            detail="service not configured",
        )
        return JSONResponse(status_code=503, content=err.model_dump())

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        err = RenderError(
            ok=False, code="bad_manifest", retryable=False, detail="unauthorized"
        )
        return JSONResponse(status_code=401, content=err.model_dump())

    token = auth_header[7:].strip()
    if not hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
        err = RenderError(
            ok=False, code="bad_manifest", retryable=False, detail="unauthorized"
        )
        return JSONResponse(status_code=401, content=err.model_dump())

    err = RenderError(
        ok=False,
        code="bad_manifest",
        retryable=False,
        detail=redact(str(exc)),
    )
    return JSONResponse(status_code=400, content=err.model_dump())


def _default_raw_builder(
    request: RenderRequest, local_inputs: dict[str, Path], workdir: Path
) -> dict[str, Any]:
    from render_service.ffmpeg_raw import build_raw

    return build_raw(request, local_inputs, workdir)


def _default_final_builder(
    request: RenderRequest, local_inputs: dict[str, Path], workdir: Path
) -> dict[str, Any]:
    try:
        from render_service.ffmpeg_dress import build_final

        return build_final(request, local_inputs, workdir)
    except ImportError as e:
        raise RuntimeError("final mode not available") from e


def _default_converter(
    item: ConvertItem,
    local_inputs: dict[str, Path],
    workdir: Path,
    duration_s: float = 5.0,
) -> Path | None:
    try:
        from render_service.motion import convert_html

        html_path = local_inputs.get(item.input_id)
        if not html_path or not html_path.is_file():
            return None
        out_path = workdir / f"{item.input_id}_converted.mp4"
        return convert_html(html_path, out_path, duration_s, workdir)
    except ImportError:
        logger.warning(
            "Motion graphics converter render_service.motion not available for %s",
            item.input_id,
        )
        return None
    except Exception as e:
        logger.warning(
            "Motion graphics conversion failed for %s: %s",
            item.input_id,
            redact(str(e)),
        )
        return None


RAW_BUILDER: Callable[[RenderRequest, dict[str, Path], Path], dict[str, Any]] = (
    _default_raw_builder
)
FINAL_BUILDER: Callable[[RenderRequest, dict[str, Path], Path], dict[str, Any]] = (
    _default_final_builder
)
CONVERTER: Callable[..., Path | None] = _default_converter


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "ffmpeg": bool(shutil.which("ffmpeg"))}


@app.post("/v1/render")
def render_v1(request: Request, body: Any = Body(default=None)) -> JSONResponse:
    secret = os.getenv("RENDER_SERVICE_SECRET")
    if not secret:
        err = RenderError(
            ok=False,
            code="bad_manifest",
            retryable=False,
            detail="service not configured",
        )
        return JSONResponse(status_code=503, content=err.model_dump())

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        err = RenderError(
            ok=False, code="bad_manifest", retryable=False, detail="unauthorized"
        )
        return JSONResponse(status_code=401, content=err.model_dump())

    token = auth_header[7:].strip()
    if not hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
        err = RenderError(
            ok=False, code="bad_manifest", retryable=False, detail="unauthorized"
        )
        return JSONResponse(status_code=401, content=err.model_dump())

    if body is None or not isinstance(body, dict):
        err = RenderError(
            ok=False,
            code="bad_manifest",
            retryable=False,
            detail="Request body must be a JSON object",
        )
        return JSONResponse(status_code=400, content=err.model_dump())

    try:
        render_req = RenderRequest.model_validate(body)
    except ValidationError as e:
        err = RenderError(
            ok=False,
            code="bad_manifest",
            retryable=False,
            detail=redact(str(e)),
        )
        return JSONResponse(status_code=400, content=err.model_dump())

    t0 = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="bsr_") as tmpdir:
        workdir = Path(tmpdir)

        # Download input assets
        try:
            local_inputs = download_all(render_req.inputs, workdir)
        except FetchError as e:
            err = RenderError(
                ok=False, code="fetch_failed", retryable=True, detail=redact(str(e))
            )
            return JSONResponse(status_code=502, content=err.model_dump())
        except TooLargeError as e:
            err = RenderError(
                ok=False, code="too_large", retryable=False, detail=redact(str(e))
            )
            return JSONResponse(status_code=413, content=err.model_dump())

        post_progress(render_req.progress_url, secret, 10)

        # Convert motion graphics items if present
        converted_list: list[str] = []
        if render_req.convert:
            for item in render_req.convert:
                try:
                    duration_s = 5.0
                    if render_req.timeline:
                        for scene in render_req.timeline.scenes:
                            if scene.broll and scene.broll.input_id == item.input_id:
                                duration_s = (
                                    scene.out_end_ms - scene.out_start_ms
                                ) / 1000.0
                                break
                    c_path = CONVERTER(item, local_inputs, workdir, duration_s)
                    if c_path and c_path.is_file():
                        upload(item.upload_url, c_path)
                        converted_list.append(item.storage_path)
                        local_inputs[item.input_id] = c_path
                except Exception as e:
                    logger.warning(
                        "Convert item %s failed: %s", item.input_id, redact(str(e))
                    )

        # Select render builder function
        if render_req.mode == "raw":
            builder = RAW_BUILDER
        else:
            builder = FINAL_BUILDER

        # Execute render builder
        try:
            res = builder(render_req, local_inputs, workdir)
        except subprocess.TimeoutExpired as e:
            err = RenderError(
                ok=False, code="timeout", retryable=True, detail=redact(str(e))
            )
            return JSONResponse(status_code=504, content=err.model_dump())
        except Exception as e:
            err = RenderError(
                ok=False, code="ffmpeg_failed", retryable=False, detail=redact(str(e))
            )
            return JSONResponse(status_code=500, content=err.model_dump())

        post_progress(render_req.progress_url, secret, 80)

        out_path: Path = res.get("path") if isinstance(res, dict) else None
        if not out_path or not out_path.is_file():
            err = RenderError(
                ok=False,
                code="ffmpeg_failed",
                retryable=False,
                detail="Output video file was not generated",
            )
            return JSONResponse(status_code=500, content=err.model_dump())

        # Check output file size against limit
        file_bytes = out_path.stat().st_size
        if file_bytes > render_req.output.max_bytes:
            err = RenderError(
                ok=False,
                code="too_large",
                retryable=False,
                detail=f"Output file size ({file_bytes} bytes) exceeds max_bytes ({render_req.output.max_bytes})",
            )
            return JSONResponse(status_code=413, content=err.model_dump())

        # Upload final MP4 asset
        try:
            upload(render_req.output.upload_url, out_path)
        except FetchError as e:
            err = RenderError(
                ok=False, code="fetch_failed", retryable=True, detail=redact(str(e))
            )
            return JSONResponse(status_code=502, content=err.model_dump())

        render_s = round(time.monotonic() - t0, 1)
        post_progress(render_req.progress_url, secret, 100)

        ok_res = RenderOk(
            ok=True,
            storage_path=render_req.output.storage_path,
            duration_ms=res.get("duration_ms", 0),
            bytes=file_bytes,
            render_s=render_s,
            scene_marks_ms=res.get("scene_marks_ms", []),
            converted=converted_list,
        )
        return JSONResponse(status_code=200, content=ok_res.model_dump())
