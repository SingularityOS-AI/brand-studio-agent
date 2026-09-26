"""API router for agent_actions (Block F — Agentic Mode, F-02).

Voice-originated actions go through this router explicitly: the frontend's
confirmation engine (F-06) creates a `proposed`/`queued` row before the
founder confirms, then patches it as the action runs. Button-originated rows
are written by app/agent/middleware.py instead -- this router never sees
those.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agent.store import create_action, list_actions, update_action
from app.auth.supabase_auth import supabase_auth
from app.guard import guard

router = APIRouter(prefix="/api/agent")


def _session(request: Request) -> str:
    """Extract and verify the user session token from the Authorization header."""
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    user_id = supabase_auth.get_user_id(authorization)
    return guard.get_or_create_user_session(user_id)


class CreateActionRequest(BaseModel):
    step: str
    action: str
    idea_id: str | None = None
    args: dict[str, Any] = {}
    utterance: str | None = None
    restatement: str | None = None
    credits: int | None = None
    status: str = "proposed"


@router.post("/actions")
async def create_action_endpoint(request: Request, body: CreateActionRequest) -> JSONResponse:
    """Creates a proposed/queued voice action row. Returns {id}."""
    session_token = _session(request)

    if body.status not in ("proposed", "queued"):
        return JSONResponse(
            status_code=422,
            content={"error": f"Invalid status for creation: {body.status}"},
        )

    row = create_action(
        session_token=session_token,
        step=body.step,
        source="voice",
        action=body.action,
        idea_id=body.idea_id,
        args=body.args,
        utterance=body.utterance,
        restatement=body.restatement,
        credits=body.credits,
        status=body.status,
    )

    return JSONResponse(status_code=201, content={"id": row["id"]})


class PatchActionRequest(BaseModel):
    confirmation: str | None = None
    confirmed_at: str | None = None
    status: str | None = None


@router.patch("/actions/{action_id}")
async def patch_action_endpoint(
    request: Request, action_id: str, body: PatchActionRequest
) -> JSONResponse:
    """Updates confirmation/confirmed_at/status on the caller's own row."""
    session_token = _session(request)

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return JSONResponse(status_code=422, content={"error": "No fields to update"})

    try:
        row = update_action(action_id, session_token, fields)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})

    if row is None:
        return JSONResponse(status_code=404, content={"error": "Action not found"})

    return JSONResponse(status_code=200, content={"id": row["id"], "status": row["status"]})


@router.get("/actions")
async def list_actions_endpoint(request: Request) -> JSONResponse:
    """Lists the caller's own actions, newest first. Optional idea_id filter."""
    session_token = _session(request)

    idea_id = request.query_params.get("idea_id")
    limit_raw = request.query_params.get("limit", "50")
    try:
        limit = int(limit_raw)
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "Invalid 'limit' parameter"})
    limit = max(1, min(limit, 200))

    rows = list_actions(session_token, idea_id=idea_id, limit=limit)
    return JSONResponse(status_code=200, content={"actions": rows})
