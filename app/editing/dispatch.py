"""Dispatcher and render service integration module for Editing (Pieza 78 — Bloque E)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.audiovisual.storage import (
    create_signed_upload_url_at,
    editing_output_path,
    signed_url,
)
from app.editing import config as dispatch_config
from app.editing.store import EditVersionConflict, get_or_create_edit, save_edit
from render_service.manifest import RenderError, RenderOk, RenderRequest

logger = logging.getLogger(__name__)


class RenderServiceError(Exception):
    """Exception raised when render service call fails or is misconfigured."""

    def __init__(self, code: str, retryable: bool, detail: str) -> None:
        super().__init__(f"{code} (retryable={retryable}): {detail}")
        self.code = code
        self.retryable = retryable
        self.detail = detail


def sign_inputs(inputs_spec: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Signs input paths/URLs into InputRef dicts.
    storage_path -> {"url": signed_url(path, ttl=INPUT_URL_TTL), "kind", "w"?, "h"?}
    external_url/url -> {"url": url, ...}
    """
    ttl = getattr(dispatch_config, "INPUT_URL_TTL", 1800)
    signed: dict[str, dict[str, Any]] = {}
    for input_id, item in inputs_spec.items():
        if "storage_path" in item:
            url = signed_url(item["storage_path"], ttl=ttl)
        elif "external_url" in item:
            url = item["external_url"]
        elif "url" in item:
            url = item["url"]
        else:
            raise ValueError(f"Input '{input_id}' has no storage_path, external_url, or url")

        ref: dict[str, Any] = {
            "url": url,
            "kind": item.get("kind", "video"),
        }
        if "w" in item and item["w"] is not None:
            ref["w"] = item["w"]
        if "h" in item and item["h"] is not None:
            ref["h"] = item["h"]
        signed[input_id] = ref
    return signed


def build_raw_request(job: dict[str, Any]) -> dict[str, Any]:
    """Builds raw RenderRequest dictionary validated with RenderRequest schema."""
    job_id = job["id"]
    attempt = max(1, job.get("attempts") or 1)
    session_token = job["session_token"]
    idea_id = job["idea_id"]

    input_payload = job.get("input", {}) or {}
    timeline = input_payload.get("timeline")
    inputs_spec = input_payload.get("inputs", {}) or {}

    max_bytes = getattr(dispatch_config, "MAX_OUTPUT_BYTES", 47000000)

    out_sp = editing_output_path(session_token, idea_id, job_id, attempt=attempt, ext="mp4")
    out_upload = create_signed_upload_url_at(out_sp)["signed_upload_url"]
    output = {
        "upload_url": out_upload,
        "storage_path": out_sp,
        "max_bytes": max_bytes,
    }

    signed_inputs = sign_inputs(inputs_spec)

    convert_items: list[dict[str, Any]] = []
    mg_counter = 1
    for input_id, item in inputs_spec.items():
        if item.get("convert") is True:
            mg_sp = editing_output_path(
                session_token,
                idea_id,
                f"{job_id}_mg{mg_counter}",
                attempt=attempt,
                ext="mp4",
            )
            mg_upload = create_signed_upload_url_at(mg_sp)["signed_upload_url"]
            convert_items.append(
                {
                    "input_id": input_id,
                    "upload_url": mg_upload,
                    "storage_path": mg_sp,
                }
            )
            mg_counter += 1

    public_base = (getattr(dispatch_config, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    progress_url = f"{public_base}/api/editing/internal/jobs/{job_id}/progress" if public_base else None

    req_data = {
        "schema": "brandstudio.render.v1",
        "job_id": job_id,
        "attempt": attempt,
        "mode": "raw",
        "timeline": timeline,
        "inputs": signed_inputs,
        "convert": convert_items,
        "output": output,
        "progress_url": progress_url,
    }
    validated = RenderRequest.model_validate(req_data)
    return validated.model_dump(exclude_unset=True)


def build_final_request(job: dict[str, Any]) -> dict[str, Any]:
    """Builds final RenderRequest dictionary validated with RenderRequest schema."""
    job_id = job["id"]
    attempt = max(1, job.get("attempts") or 1)
    session_token = job["session_token"]
    idea_id = job["idea_id"]

    input_payload = job.get("input", {}) or {}
    ir = input_payload.get("ir")
    raw_storage_path = input_payload.get("raw_storage_path")
    if not raw_storage_path:
        raise ValueError("Missing raw_storage_path in final render job input")

    sfx_inputs = input_payload.get("sfx_inputs", {}) or {}

    max_bytes = getattr(dispatch_config, "MAX_OUTPUT_BYTES", 47000000)
    ttl = getattr(dispatch_config, "INPUT_URL_TTL", 1800)

    out_sp = editing_output_path(session_token, idea_id, job_id, attempt=attempt, ext="mp4")
    out_upload = create_signed_upload_url_at(out_sp)["signed_upload_url"]
    output = {
        "upload_url": out_upload,
        "storage_path": out_sp,
        "max_bytes": max_bytes,
    }

    raw_url = signed_url(raw_storage_path, ttl=ttl)
    inputs_dict: dict[str, dict[str, Any]] = {
        "raw": {"url": raw_url, "kind": "video"}
    }
    if sfx_inputs:
        signed_sfx = sign_inputs(sfx_inputs)
        inputs_dict.update(signed_sfx)

    public_base = (getattr(dispatch_config, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    progress_url = f"{public_base}/api/editing/internal/jobs/{job_id}/progress" if public_base else None

    req_data = {
        "schema": "brandstudio.render.v1",
        "job_id": job_id,
        "attempt": attempt,
        "mode": "final",
        "ir": ir,
        "raw_input_id": "raw",
        "inputs": inputs_dict,
        "convert": [],
        "output": output,
        "progress_url": progress_url,
    }
    validated = RenderRequest.model_validate(req_data)
    return validated.model_dump(exclude_unset=True)


async def call_render_service(
    request: dict[str, Any], *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Calls render service via HTTPS POST /v1/render with Authorization header."""
    service_url = getattr(dispatch_config, "RENDER_SERVICE_URL", "")
    service_secret = getattr(dispatch_config, "RENDER_SERVICE_SECRET", "")
    timeout = getattr(dispatch_config, "HTTP_TIMEOUT", 290)

    url = (service_url or "").strip()
    secret = (service_secret or "").strip()
    if not url or not secret:
        raise RenderServiceError("bad_manifest", False, "render service not configured")

    target_url = f"{url.rstrip('/')}/v1/render"
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}

    try:
        if client is not None:
            resp = await client.post(target_url, json=request, headers=headers, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as http_client:
                resp = await http_client.post(
                    target_url, json=request, headers=headers
                )
    except httpx.TimeoutException as e:
        raise RenderServiceError("timeout", True, f"HTTP request timed out: {e}") from e
    except httpx.RequestError as e:
        raise RenderServiceError("fetch_failed", True, f"HTTP request failed: {e}") from e
    except Exception as e:
        raise RenderServiceError("fetch_failed", True, f"HTTP error: {e}") from e

    if resp.status_code == 200:
        try:
            data = resp.json()
            ok_model = RenderOk.model_validate(data)
            return ok_model.model_dump()
        except Exception as e:
            raise RenderServiceError("bad_manifest", False, f"Invalid 200 response: {e}") from e
    else:
        try:
            data = resp.json()
            err_model = RenderError.model_validate(data)
            raise RenderServiceError(err_model.code, err_model.retryable, err_model.detail)
        except RenderServiceError:
            raise
        except Exception:
            code = "ffmpeg_failed" if resp.status_code == 500 else "fetch_failed"
            detail = f"HTTP {resp.status_code}: {resp.text[:500]}"
            raise RenderServiceError(code, True, detail)


async def resolve_raw_render(job: dict[str, Any]) -> dict[str, Any]:
    """Resolver for raw_render job."""
    session_token = job["session_token"]
    idea_id = job["idea_id"]
    cost_per_s = getattr(dispatch_config, "RENDER_COST_PER_S", 0.000088)

    req = build_raw_request(job)
    ok = await call_render_service(req)

    timeline = job["input"]["timeline"]
    raw_render_payload = {
        "job_id": job["id"],
        "status": "done",
        "storage_path": ok["storage_path"],
        "duration_ms": ok["duration_ms"],
        "bytes": ok["bytes"],
        "render_s": ok["render_s"],
        "scene_marks_ms": ok.get("scene_marks_ms", []),
        "timeline_hash": timeline["hash"],
    }

    for attempt in range(3):
        edit_row = get_or_create_edit(session_token, idea_id)
        expected_ver = edit_row["version"]
        try:
            save_edit(
                session_token,
                idea_id,
                fields={"raw_render": raw_render_payload},
                expected_version=expected_ver,
            )
            break
        except EditVersionConflict:
            if attempt == 2:
                raise

    output = dict(raw_render_payload)
    output["cost_usd"] = round(ok["render_s"] * cost_per_s, 4)
    return output


async def resolve_render(job: dict[str, Any]) -> dict[str, Any]:
    """Resolver for final render job."""
    session_token = job["session_token"]
    idea_id = job["idea_id"]
    cost_per_s = getattr(dispatch_config, "RENDER_COST_PER_S", 0.000088)

    req = build_final_request(job)
    ok = await call_render_service(req)

    render_payload = {
        "job_id": job["id"],
        "status": "done",
        "storage_path": ok["storage_path"],
        "duration_ms": ok["duration_ms"],
        "bytes": ok["bytes"],
        "render_s": ok["render_s"],
    }

    for attempt in range(3):
        edit_row = get_or_create_edit(session_token, idea_id)
        expected_ver = edit_row["version"]
        try:
            save_edit(
                session_token,
                idea_id,
                fields={"render": render_payload},
                expected_version=expected_ver,
            )
            break
        except EditVersionConflict:
            if attempt == 2:
                raise

    output = dict(render_payload)
    output["cost_usd"] = round(ok["render_s"] * cost_per_s, 4)
    return output


def refund_failed_prepaid() -> int:
    """Finds failed charged render and redress jobs and refunds prepaid credits."""
    try:
        from app.audiovisual.jobs import find_jobs, mark_charged, release_charge
        from app.guard import guard

        default_credits = getattr(dispatch_config, "RENDER_CREDITS", 20)
        failed_jobs = find_jobs(kinds=["render", "redress"], statuses=["failed"], charged=True, limit=20)
        refunded_count = 0
        for job in failed_jobs:
            if release_charge(job):
                credits_to_refund = job.get("credits") or default_credits
                session_token = job.get("session_token", "")
                try:
                    res = guard.refund_credits(
                        session_token, credits_to_refund, source=f"refund:{job['id']}"
                    )
                    if res is None:
                        token_mask = (
                            session_token[-6:] if len(session_token) >= 6 else "***"
                        )
                        logger.error(
                            f"[dispatch] refund_credits returned None for job {job['id']} (token ...{token_mask})"
                        )
                    else:
                        refunded_count += 1
                except Exception as e:
                    mark_charged(job)
                    token_mask = (
                        session_token[-6:] if len(session_token) >= 6 else "***"
                    )
                    logger.error(
                        f"[dispatch] Failed to refund credits for job {job['id']} (token ...{token_mask}): {e}"
                    )
        return refunded_count
    except Exception as e:
        logger.error(f"[dispatch] refund_failed_prepaid error: {e}")
        return 0
