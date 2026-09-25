"""Database store and local fallback for edits (Pieza 70 — Bloque E)."""
from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.editing.config import EDIT_FIELDS

_edits_client: Any = None
_local_edits: dict[tuple[str, str], dict[str, Any]] = {}
_edits_lock = threading.Lock()


class EditVersionConflict(Exception):
    """Raised when save_edit optimistic version check fails."""

    def __init__(self, expected: int, current: int) -> None:
        super().__init__(f"Version conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current


def _get_edits_supabase_client() -> Any:
    """Creates Supabase client for edits table."""
    supabase_url = settings.supabase_url
    supabase_key = settings.supabase_key
    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials not configured")
    try:
        from supabase import create_client

        return create_client(supabase_url, supabase_key)
    except (ImportError, RuntimeError):
        raise RuntimeError("Failed to connect to Supabase")


def _get_edits_client() -> Any:
    """Returns Supabase client or None if not configured/available."""
    global _edits_client
    if _edits_client is None:
        try:
            _edits_client = _get_edits_supabase_client()
        except Exception:
            return None
    return _edits_client


def _reset_local_edits() -> None:
    """Reset local edits storage and reset client cache (used for test isolation)."""
    global _edits_client
    with _edits_lock:
        _local_edits.clear()
        _edits_client = None


def get_edit(session_token: str, idea_id: str) -> dict[str, Any] | None:
    """Fetch an edit record by session_token and idea_id, or None if it does not exist."""
    client = _get_edits_client()
    if client is not None:
        res = (
            client.table("edits")
            .select("*")
            .eq("session_token", session_token)
            .eq("idea_id", idea_id)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    with _edits_lock:
        item = _local_edits.get((session_token, idea_id))
        if item is None:
            return None
        return copy.deepcopy(item)


def get_or_create_edit(session_token: str, idea_id: str) -> dict[str, Any]:
    """Get existing edit record or create a new one with default empty dict fields and version 1."""
    client = _get_edits_client()
    if client is not None:
        client.table("edits").upsert(
            {
                "session_token": session_token,
                "idea_id": idea_id,
                "version": 1,
                "timeline": {},
                "raw_render": {},
                "dressing": {},
                "captions": {},
                "settings": {},
                "render": {},
                "metadata": {},
            },
            on_conflict="session_token,idea_id",
            ignore_duplicates=True,
        ).execute()
        result = get_edit(session_token, idea_id)
        if result is None:
            raise RuntimeError("Failed to retrieve edit record after upsert")
        return result

    with _edits_lock:
        key = (session_token, idea_id)
        if key not in _local_edits:
            now_iso = datetime.now(timezone.utc).isoformat()
            new_row: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "session_token": session_token,
                "idea_id": idea_id,
                "version": 1,
                "timeline": {},
                "raw_render": {},
                "dressing": {},
                "captions": {},
                "settings": {},
                "render": {},
                "metadata": {},
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            _local_edits[key] = new_row
        return copy.deepcopy(_local_edits[key])


def save_edit(
    session_token: str,
    idea_id: str,
    fields: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    """Update fields of an edit record with optimistic concurrency control on expected_version."""
    for k, v in fields.items():
        if k not in EDIT_FIELDS:
            raise ValueError(f"Invalid edit field: '{k}'. Allowed fields: {EDIT_FIELDS}")
        if not isinstance(v, dict):
            raise ValueError(f"Field '{k}' value must be a dict, got {type(v).__name__}")

    client = _get_edits_client()
    if client is not None:
        update_data = {
            **fields,
            "version": expected_version + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = (
            client.table("edits")
            .update(update_data)
            .eq("session_token", session_token)
            .eq("idea_id", idea_id)
            .eq("version", expected_version)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]

        current_row = get_edit(session_token, idea_id)
        current_ver = current_row["version"] if current_row else 0
        raise EditVersionConflict(expected=expected_version, current=current_ver)

    with _edits_lock:
        key = (session_token, idea_id)
        current_row = _local_edits.get(key)
        if current_row is None:
            raise EditVersionConflict(expected=expected_version, current=0)

        current_ver = current_row["version"]
        if current_ver != expected_version:
            raise EditVersionConflict(expected=expected_version, current=current_ver)

        current_row["version"] = expected_version + 1
        for k, v in fields.items():
            current_row[k] = copy.deepcopy(v)
        current_row["updated_at"] = datetime.now(timezone.utc).isoformat()
        return copy.deepcopy(current_row)
