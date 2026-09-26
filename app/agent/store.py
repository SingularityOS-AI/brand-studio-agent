"""Database store and local fallback for agent_actions (Block F — Agentic Mode, F-02).

Same pattern as app/editing/store.py: a Supabase client when configured, an
in-memory dict for tests/local dev otherwise. The backend is the only writer
(service key) and every read is scoped to the caller's own session_token --
callers of this module never expose another session's rows.
"""
from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings

_actions_client: Any = None
_local_actions: dict[str, dict[str, Any]] = {}
_actions_lock = threading.Lock()

STATUSES = ("proposed", "queued", "running", "done", "failed", "cancelled")
SOURCES = ("voice", "button")


def _get_actions_supabase_client() -> Any:
    """Creates Supabase client for the agent_actions table."""
    supabase_url = settings.supabase_url
    supabase_key = settings.supabase_key
    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials not configured")
    try:
        from supabase import create_client

        return create_client(supabase_url, supabase_key)
    except (ImportError, RuntimeError):
        raise RuntimeError("Failed to connect to Supabase")


def _get_actions_client() -> Any:
    """Returns a cached Supabase client, or None if not configured/available."""
    global _actions_client
    if _actions_client is None:
        try:
            _actions_client = _get_actions_supabase_client()
        except Exception:  # noqa: BLE001 — audit trail must never break the endpoint
            return None
    return _actions_client


def _reset_local_actions() -> None:
    """Reset local storage and the cached client (used for test isolation)."""
    global _actions_client
    with _actions_lock:
        _local_actions.clear()
        _actions_client = None


def create_action(
    *,
    session_token: str,
    step: str,
    source: str,
    action: str,
    idea_id: str | None = None,
    args: dict[str, Any] | None = None,
    utterance: str | None = None,
    restatement: str | None = None,
    credits: int | None = None,
    status: str = "proposed",
    error: str | None = None,
) -> dict[str, Any]:
    """Insert a new agent_actions row.

    Raises ValueError if `source` or `status` is not one of the allowed values --
    callers are expected to turn that into a 4xx, never a silently-dropped row.
    """
    if source not in SOURCES:
        raise ValueError(f"Invalid source: {source}")
    if status not in STATUSES:
        raise ValueError(f"Invalid status: {status}")

    row: dict[str, Any] = {
        "session_token": session_token,
        "idea_id": idea_id,
        "step": step,
        "source": source,
        "action": action,
        "args": args or {},
        "utterance": utterance,
        "restatement": restatement,
        "confirmation": None,
        "confirmed_at": None,
        "credits": credits,
        "status": status,
        "result_ref": None,
        "error": error,
    }

    client = _get_actions_client()
    if client is not None:
        res = client.table("agent_actions").insert(row).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("Failed to create agent_actions row")

    with _actions_lock:
        now_iso = datetime.now(timezone.utc).isoformat()
        new_row = {
            **row,
            "id": str(uuid.uuid4()),
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _local_actions[new_row["id"]] = new_row
        return copy.deepcopy(new_row)


def get_action(action_id: str) -> dict[str, Any] | None:
    """Fetch a single row by id, regardless of owner (internal use only)."""
    client = _get_actions_client()
    if client is not None:
        res = client.table("agent_actions").select("*").eq("id", action_id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    with _actions_lock:
        item = _local_actions.get(action_id)
        return copy.deepcopy(item) if item is not None else None


def update_action(
    action_id: str,
    session_token: str,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Update fields on a row scoped to its owning session_token.

    Returns None if the row doesn't exist or belongs to a different session --
    callers (the PATCH endpoint, the audit middleware) must treat that as
    "not this caller's row", never update it.
    """
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")

    update_data = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}

    client = _get_actions_client()
    if client is not None:
        res = (
            client.table("agent_actions")
            .update(update_data)
            .eq("id", action_id)
            .eq("session_token", session_token)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    with _actions_lock:
        row = _local_actions.get(action_id)
        if row is None or row.get("session_token") != session_token:
            return None
        row.update(update_data)
        return copy.deepcopy(row)


def list_actions(
    session_token: str,
    idea_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List a session's own actions, newest first."""
    client = _get_actions_client()
    if client is not None:
        query = (
            client.table("agent_actions")
            .select("*")
            .eq("session_token", session_token)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if idea_id is not None:
            query = query.eq("idea_id", idea_id)
        res = query.execute()
        return res.data or []

    with _actions_lock:
        rows = [
            copy.deepcopy(r)
            for r in _local_actions.values()
            if r.get("session_token") == session_token
            and (idea_id is None or r.get("idea_id") == idea_id)
        ]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:limit]
