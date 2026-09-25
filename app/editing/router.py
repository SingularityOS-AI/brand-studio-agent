"""API router for Bloque E Editing module (Pieza 81)."""
from __future__ import annotations

import copy
import hmac
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.supabase_auth import supabase_auth
from app.audiovisual.jobs import (
    create_job,
    list_jobs,
    mark_cancelled,
    mark_charged,
    revert_charged,
    set_job_progress,
)
from app.audiovisual.spend_guard import can_spend
from app.audiovisual.storage import signed_url
from app.editing import config as dispatch_config
from app.editing.brand_style import derive_caption_style
from app.editing.dressing import dress_all, scene_contexts
from app.editing.ir import build_ir_stage1, build_ir_stage2
from app.editing.store import EditVersionConflict, get_or_create_edit, save_edit
from app.editing.timeline import build_timeline
from app.guard import guard
from app.scripting.scripts import _check_script
from app.tools.brand_brain.store import get_brand_brain

router = APIRouter(prefix="/api/editing")


class EditingError(Exception):
    """Custom exception raised by router endpoints to return specific status_code & content."""

    def __init__(self, status_code: int, content: dict[str, Any]) -> None:
        super().__init__(f"EditingError {status_code}: {content}")
        self.status_code = status_code
        self.content = content


def _session(request: Request) -> str:
    """Extract and verify user session token from Authorization header."""
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    return session_token


def _load(
    request: Request, idea_id: str
) -> tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Loads session_token, script dict, jobs list, and edit dict."""
    session_token = _session(request)
    script_obj = _check_script(session_token, idea_id)
    if script_obj is None:
        raise EditingError(status.HTTP_409_CONFLICT, {"code": "script_not_locked"})

    if hasattr(script_obj, "model_dump"):
        script_dict = script_obj.model_dump(mode="json")
    elif isinstance(script_obj, dict):
        script_dict = script_obj
    else:
        script_dict = None

    if not script_dict:
        raise EditingError(status.HTTP_409_CONFLICT, {"code": "script_not_locked"})

    st = script_dict.get("state") or script_dict.get("status")
    if st != "locked":
        raise EditingError(status.HTTP_409_CONFLICT, {"code": "script_not_locked"})

    jobs = list_jobs(session_token, idea_id)
    edit = get_or_create_edit(session_token, idea_id)
    return session_token, script_dict, jobs, edit


def _state(
    session_token: str,
    idea_id: str,
    script: dict[str, Any],
    jobs: list[dict[str, Any]],
    edit: dict[str, Any],
) -> dict[str, Any]:
    """Builds current editing state dictionary."""
    build_res = build_timeline(script, jobs, edit.get("settings"), edit["version"])
    timeline = build_res["timeline"]
    captions_words = build_res["captions_words"]
    missing_takes = build_res["missing_takes"]
    warnings = build_res["warnings"]
    inputs = build_res["inputs"]

    # Apply saved caption word edits
    captions_saved = edit.get("captions") or {}
    edits_map = captions_saved.get("edits") or {}
    for cw in captions_words:
        w_id = cw.get("id")
        if w_id and w_id in edits_map:
            cw["edited_text"] = edits_map[w_id]

    try:
        brand_brain = get_brand_brain(session_token)
    except Exception:
        brand_brain = None
    style = derive_caption_style(brand_brain)

    dressing_data = edit.get("dressing") or {}
    dressing_scenes = dressing_data.get("scenes") if isinstance(dressing_data, dict) else None
    sfx_inputs: dict[str, dict[str, Any]] = {}
    # A dressing was written against one raw cut (its word indices and times).
    # If the cut changed since, it no longer fits: show captions only and let the
    # founder dress again for free.
    dressing_fresh = bool(
        dressing_scenes
        and timeline is not None
        and dressing_data.get("raw_hash") == timeline.get("hash")
    )

    if timeline is not None:
        frame_zero = script.get("frame_zero") or {}
        fz_text = frame_zero.get("on_screen_text")
        if dressing_fresh:
            stage2_res = build_ir_stage2(
                timeline, captions_words, fz_text, style, dressing_data
            )
            ir = stage2_res["ir"]
            sfx_inputs = stage2_res.get("sfx_inputs", {}) or {}
        else:
            ir = build_ir_stage1(timeline, captions_words, fz_text, style)
    else:
        ir = None

    # Construct raw dict
    raw_jobs = [j for j in jobs if j.get("kind") == "raw_render"]
    raw_jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    latest_raw_job = raw_jobs[0] if raw_jobs else None

    edit_raw = edit.get("raw_render") or {}
    if edit_raw:
        raw_dict = dict(edit_raw)
        if latest_raw_job:
            raw_dict["status"] = latest_raw_job.get("status")
            raw_dict["progress"] = (latest_raw_job.get("output") or {}).get("pct")
            raw_dict["error"] = latest_raw_job.get("error")
        t_hash = timeline.get("hash") if timeline else None
        raw_hash = edit_raw.get("timeline_hash")
        # The hash only covers what the raw cut is made of (see raw_content_hash),
        # so saving captions or a dressing never makes a finished raw stale.
        raw_dict["fresh"] = bool(t_hash and raw_hash and raw_hash == t_hash)
        if edit_raw.get("status") == "done" and edit_raw.get("storage_path"):
            raw_dict["signed_url"] = signed_url(edit_raw["storage_path"], ttl=3600)
    elif latest_raw_job:
        raw_dict = {
            "status": latest_raw_job.get("status"),
            "progress": (latest_raw_job.get("output") or {}).get("pct"),
            "error": latest_raw_job.get("error"),
            "fresh": False,
        }
    else:
        raw_dict = {}

    # Construct render dict
    render_jobs = [j for j in jobs if j.get("kind") == "render"]
    render_jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    latest_render_job = render_jobs[0] if render_jobs else None

    edit_render = edit.get("render") or {}
    if edit_render:
        render_dict = dict(edit_render)
        if latest_render_job:
            render_dict["status"] = latest_render_job.get("status")
            render_dict["progress"] = (latest_render_job.get("output") or {}).get("pct")
            render_dict["error"] = latest_render_job.get("error")
        if edit_render.get("status") == "done" and edit_render.get("storage_path"):
            render_dict["signed_url"] = signed_url(edit_render["storage_path"], ttl=3600)
    elif latest_render_job:
        render_dict = {
            "status": latest_render_job.get("status"),
            "progress": (latest_render_job.get("output") or {}).get("pct"),
            "error": latest_render_job.get("error"),
        }
    else:
        render_dict = {}

    return {
        "edit_version": edit["version"],
        "timeline": timeline,
        "captions_words": captions_words,
        "missing_takes": missing_takes,
        "warnings": warnings,
        "style": style,
        "ir": ir,
        "settings": edit.get("settings", {}),
        "raw": raw_dict,
        "render": render_dict,
        "dressing": {
            "source": dressing_data.get("source") if dressing_scenes else None,
            "fresh": dressing_fresh,
            "stale": bool(dressing_scenes) and not dressing_fresh,
        },
        "_inputs": inputs,
        "_sfx_inputs": sfx_inputs,
    }


@router.get("/{idea_id}")
async def get_editing_state(request: Request, idea_id: str) -> JSONResponse:
    """GET editing state endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    state = _state(session_token, idea_id, script, jobs, edit)
    state.pop("_inputs", None)
    state.pop("_sfx_inputs", None)
    return JSONResponse(status_code=200, content=state)


@router.post("/{idea_id}/raw")
async def post_raw_render(request: Request, idea_id: str) -> JSONResponse:
    """POST raw render endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    url = (getattr(dispatch_config, "RENDER_SERVICE_URL", "") or "").strip()
    secret = (getattr(dispatch_config, "RENDER_SERVICE_SECRET", "") or "").strip()
    if not url or not secret:
        return JSONResponse(
            status_code=503, content={"code": "render_service_not_configured"}
        )

    # First build state with current edit
    state = _state(session_token, idea_id, script, jobs, edit)
    missing_takes = state["missing_takes"]
    if missing_takes:
        return JSONResponse(
            status_code=409,
            content={"code": "missing_takes", "scenes": missing_takes},
        )

    # Save captions if modified/not present
    edits_map = (edit.get("captions") or {}).get("edits") or {}
    captions_payload = {
        "words": state["captions_words"],
        "style": state["style"],
        "edits": edits_map,
    }

    if edit.get("captions") != captions_payload:
        fields_to_save = {"captions": captions_payload, "timeline": state["timeline"]}
        expected_ver = edit["version"]
        try:
            edit = save_edit(
                session_token, idea_id, fields_to_save, expected_version=expected_ver
            )
        except EditVersionConflict:
            fresh_edit = get_or_create_edit(session_token, idea_id)
            edit = save_edit(
                session_token,
                idea_id,
                fields_to_save,
                expected_version=fresh_edit["version"],
            )
        # Re-build state with updated edit version if saved
        state = _state(session_token, idea_id, script, jobs, edit)

    # Check 1 hour rate limit
    raw_per_hour = getattr(dispatch_config, "RAW_PER_HOUR", 12)
    now_utc = datetime.now(timezone.utc)
    one_hour_ago_ts = now_utc.timestamp() - 3600

    raw_jobs = [j for j in jobs if j.get("kind") == "raw_render"]
    count_last_hour = 0
    for rj in raw_jobs:
        c_str = rj.get("created_at")
        if c_str:
            try:
                c_dt = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
                if c_dt.timestamp() >= one_hour_ago_ts:
                    count_last_hour += 1
            except Exception:
                pass

    if count_last_hour >= raw_per_hour:
        return JSONResponse(
            status_code=429, content={"code": "rate_limit_exceeded"}
        )

    timeline = state["timeline"]
    inputs = state.pop("_inputs", {})
    state.pop("_sfx_inputs", None)
    t_hash = timeline["hash"]

    base_key = f"{session_token}:{idea_id}:raw:{t_hash}"
    failed_count = sum(
        1
        for rj in raw_jobs
        if (rj.get("idempotency_key") or "").startswith(base_key)
        and rj.get("status") == "failed"
    )

    if failed_count > 0:
        idempotency_key = f"{base_key}:retry{failed_count}"
    else:
        idempotency_key = base_key

    job, created = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=None,
        kind="raw_render",
        credits=0,
        cost_usd=0.005,
        input={"timeline": timeline, "inputs": inputs},
        idempotency_key=idempotency_key,
        return_created=True,
    )

    return JSONResponse(status_code=202, content={"job": job, "created": created})


class SettingsPatchBody(BaseModel):
    op: str
    scene_n: int | None = None
    value: Any = None
    expected_version: int


@router.patch("/{idea_id}/settings")
async def patch_settings(request: Request, idea_id: str) -> JSONResponse:
    """PATCH settings endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    try:
        raw_body = await request.json()
        body = SettingsPatchBody.model_validate(raw_body)
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Invalid request body"})

    op = body.op
    allowed_ops = {"face", "trim", "music_mute", "sfx_enabled", "music_volume"}
    if op not in allowed_ops:
        return JSONResponse(status_code=422, content={"detail": f"Invalid op: {op}"})

    settings_dict = copy.deepcopy(edit.get("settings") or {})

    if op == "face":
        if body.scene_n is None:
            return JSONResponse(status_code=422, content={"detail": "scene_n required for face"})
        if body.value is not None and not isinstance(body.value, bool):
            return JSONResponse(status_code=422, content={"detail": "face value must be bool or null"})
        face_dict = settings_dict.setdefault("face", {})
        sc_key = str(body.scene_n)
        if body.value is None:
            face_dict.pop(sc_key, None)
        else:
            face_dict[sc_key] = body.value

    elif op == "trim":
        if body.scene_n is None:
            return JSONResponse(status_code=422, content={"detail": "scene_n required for trim"})
        if (
            not isinstance(body.value, dict)
            or "start_ms" not in body.value
            or "end_ms" not in body.value
        ):
            return JSONResponse(
                status_code=422,
                content={"detail": "trim value must be dict with start_ms and end_ms"},
            )
        try:
            start_ms = int(body.value["start_ms"])
            end_ms = int(body.value["end_ms"])
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=422, content={"detail": "start_ms and end_ms must be integers"}
            )
        bounded_start = max(-500, min(500, start_ms))
        bounded_end = max(-500, min(500, end_ms))
        trim_dict = settings_dict.setdefault("trim", {})
        trim_dict[str(body.scene_n)] = {"start_ms": bounded_start, "end_ms": bounded_end}

    elif op == "music_mute":
        if not isinstance(body.value, bool):
            return JSONResponse(
                status_code=422, content={"detail": "music_mute value must be bool"}
            )
        settings_dict["music_muted"] = body.value

    elif op == "sfx_enabled":
        if not isinstance(body.value, bool):
            return JSONResponse(
                status_code=422, content={"detail": "sfx_enabled value must be bool"}
            )
        settings_dict["sfx_enabled"] = body.value

    elif op == "music_volume":
        if isinstance(body.value, bool) or not isinstance(body.value, (int, float)):
            return JSONResponse(
                status_code=422, content={"detail": "music_volume must be a float"}
            )
        val_float = float(body.value)
        if not (0.0 <= val_float <= 1.0):
            return JSONResponse(
                status_code=422, content={"detail": "music_volume must be between 0 and 1"}
            )
        settings_dict["music_volume"] = val_float

    try:
        updated_edit = save_edit(
            session_token,
            idea_id,
            fields={"settings": settings_dict},
            expected_version=body.expected_version,
        )
    except EditVersionConflict as err:
        return JSONResponse(
            status_code=409,
            content={"code": "version_conflict", "current": err.current},
        )

    state = _state(session_token, idea_id, script, jobs, updated_edit)
    state.pop("_inputs", None)
    state.pop("_sfx_inputs", None)
    return JSONResponse(status_code=200, content=state)


class CaptionsPatchBody(BaseModel):
    text: str
    expected_version: int


@router.patch("/{idea_id}/captions/{word_id}")
async def patch_captions(request: Request, idea_id: str, word_id: str) -> JSONResponse:
    """PATCH caption word endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    if not re.match(r"^s\d+w\d+$", word_id):
        return JSONResponse(
            status_code=422, content={"detail": f"Invalid word_id format: {word_id}"}
        )

    try:
        raw_body = await request.json()
        body = CaptionsPatchBody.model_validate(raw_body)
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Invalid request body"})

    clean_text = body.text.strip()
    if not (1 <= len(clean_text) <= 40):
        return JSONResponse(
            status_code=422,
            content={"detail": "Text length must be between 1 and 40 characters"},
        )

    captions_dict = copy.deepcopy(edit.get("captions") or {})
    edits_map = captions_dict.setdefault("edits", {})
    edits_map[word_id] = clean_text

    try:
        updated_edit = save_edit(
            session_token,
            idea_id,
            fields={"captions": captions_dict},
            expected_version=body.expected_version,
        )
    except EditVersionConflict as err:
        return JSONResponse(
            status_code=409,
            content={"code": "version_conflict", "current": err.current},
        )

    state = _state(session_token, idea_id, script, jobs, updated_edit)
    state.pop("_inputs", None)
    state.pop("_sfx_inputs", None)
    return JSONResponse(status_code=200, content=state)


@router.post("/{idea_id}/dress")
async def post_dress(request: Request, idea_id: str) -> JSONResponse:
    """POST dress endpoint — dresses all scenes using closed catalog."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    state = _state(session_token, idea_id, script, jobs, edit)
    missing_takes = state["missing_takes"]
    if missing_takes:
        return JSONResponse(
            status_code=409,
            content={"code": "missing_takes", "scenes": missing_takes},
        )

    timeline = state["timeline"]
    captions_words = state["captions_words"]
    raw_hash = timeline.get("hash", "")

    # "Vestir todo" is included once per raw cut (E-D13): pressing it again on the
    # same cut returns the dressing already made instead of paying Gemini again.
    if state.get("dressing", {}).get("fresh"):
        state.pop("_inputs", None)
        state.pop("_sfx_inputs", None)
        return JSONResponse(status_code=200, content=state)

    contexts = scene_contexts(timeline, captions_words, script)
    dressing_plan = await dress_all(contexts, raw_hash, seed_base=edit.get("version", 1))

    try:
        updated_edit = save_edit(
            session_token,
            idea_id,
            fields={"dressing": dressing_plan},
            expected_version=edit["version"],
        )
    except EditVersionConflict as err:
        return JSONResponse(
            status_code=409,
            content={"code": "version_conflict", "current": err.current},
        )

    new_state = _state(session_token, idea_id, script, jobs, updated_edit)
    new_state.pop("_inputs", None)
    new_state.pop("_sfx_inputs", None)
    return JSONResponse(status_code=200, content=new_state)


@router.post("/{idea_id}/render")
async def post_final_render(request: Request, idea_id: str) -> JSONResponse:
    """POST final render endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    url = (getattr(dispatch_config, "RENDER_SERVICE_URL", "") or "").strip()
    secret = (getattr(dispatch_config, "RENDER_SERVICE_SECRET", "") or "").strip()
    if not url or not secret:
        return JSONResponse(
            status_code=503, content={"code": "render_service_not_configured"}
        )

    state = _state(session_token, idea_id, script, jobs, edit)
    missing_takes = state["missing_takes"]
    if missing_takes:
        return JSONResponse(
            status_code=409,
            content={"code": "missing_takes", "scenes": missing_takes},
        )

    raw_info = state["raw"]
    if not raw_info or raw_info.get("status") != "done" or not raw_info.get("fresh"):
        return JSONResponse(status_code=409, content={"code": "raw_not_ready"})

    if not can_spend(0.01):
        return JSONResponse(status_code=503, content={"code": "spend_paused"})

    edit_ver = edit["version"]
    base_prefix = f"{session_token}:{idea_id}:render:{edit_ver}:"
    render_jobs = [j for j in jobs if j.get("kind") == "render"]
    failed_count = sum(
        1
        for rj in render_jobs
        if (rj.get("idempotency_key") or "").startswith(base_prefix)
        and rj.get("status") == "failed"
    )

    idempotency_key = f"{base_prefix}{failed_count}"
    render_credits = getattr(dispatch_config, "RENDER_CREDITS", 20)

    edit_raw = edit.get("raw_render") or {}
    raw_storage_path = edit_raw.get("storage_path") or ""

    job, created = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=None,
        kind="render",
        credits=render_credits,
        cost_usd=0.01,
        input={
            "ir": state["ir"],
            "raw_storage_path": raw_storage_path,
            # Only the sound effects: the takes and b-roll are already inside the raw MP4.
            "sfx_inputs": state.get("_sfx_inputs", {}),
        },
        idempotency_key=idempotency_key,
        return_created=True,
    )

    if created:
        mark_charged(job)
        job["charged"] = True
        try:
            guard.deduct_credits(session_token, render_credits)
        except HTTPException as e:
            if e.status_code == status.HTTP_402_PAYMENT_REQUIRED:
                revert_charged(job)
                job["charged"] = False
                mark_cancelled(job, "Payment failed")
                job["status"] = "cancelled"
                raise HTTPException(status_code=402, detail=e.detail)
            else:
                revert_charged(job)
                job["charged"] = False
                mark_cancelled(job, str(e.detail))
                job["status"] = "cancelled"
                raise

    remaining = guard.get_remaining_credits(session_token)
    return JSONResponse(
        status_code=202,
        content={"job": job, "created": created, "credits_remaining": remaining},
    )


@router.get("/{idea_id}/share-link")
async def get_share_link(request: Request, idea_id: str) -> JSONResponse:
    """GET share link endpoint."""
    try:
        session_token, script, jobs, edit = _load(request, idea_id)
    except EditingError as e:
        return JSONResponse(status_code=e.status_code, content=e.content)

    render_info = edit.get("render") or {}
    if render_info.get("status") == "done" and render_info.get("storage_path"):
        ttl = getattr(dispatch_config, "SHARE_TTL", 604800)
        url = signed_url(render_info["storage_path"], ttl=ttl)
        return JSONResponse(status_code=200, content={"url": url, "expires_in": ttl})

    return JSONResponse(status_code=404, content={"detail": "Render not ready"})


class ProgressBody(BaseModel):
    pct: int = Field(..., ge=0, le=100)


@router.post("/internal/jobs/{job_id}/progress")
async def update_job_progress_endpoint(
    request: Request, job_id: str
) -> Response:
    """Internal job progress update endpoint."""
    secret = (getattr(dispatch_config, "RENDER_SERVICE_SECRET", "") or "").strip()
    if not secret:
        return JSONResponse(
            status_code=503, content={"code": "render_service_not_configured"}
        )

    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    token = auth_header[7:].strip()
    if not hmac.compare_digest(token, secret):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    try:
        raw_body = await request.json()
        body = ProgressBody.model_validate(raw_body)
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Invalid pct value"})

    set_job_progress(job_id, {"pct": body.pct})
    return Response(status_code=204)
