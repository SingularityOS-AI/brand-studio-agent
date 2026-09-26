import uuid
import asyncio
from typing import Any

from app.config import settings

# Global list for local/testing without Supabase
_local_agent_actions: list[dict[str, Any]] = []

_supabase_client = None

def _get_supabase_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    from supabase import create_client
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client

async def create_action_async(data: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(create_action, data)

def create_action(data: dict[str, Any]) -> dict[str, Any]:
    """Creates a new agent action."""
    client = _get_supabase_client()
    if client:
        res = client.table("agent_actions").insert(data).execute()
        if res.data:
            return res.data[0]
        return {}
    else:
        # Local mock
        new_action = dict(data)
        if "id" not in new_action:
            new_action["id"] = str(uuid.uuid4())
        _local_agent_actions.append(new_action)
        return new_action

async def update_action_async(action_id: str, data: dict[str, Any], session_token: str | None = None) -> dict[str, Any] | None:
    return await asyncio.to_thread(update_action, action_id, data, session_token)

def update_action(action_id: str, data: dict[str, Any], session_token: str | None = None) -> dict[str, Any] | None:
    """Updates an existing agent action."""
    client = _get_supabase_client()
    if client:
        query = client.table("agent_actions").update(data).eq("id", action_id)
        if session_token:
            query = query.eq("session_token", session_token)
        res = query.execute()
        if res.data:
            return res.data[0]
        return None
    else:
        for a in _local_agent_actions:
            if a.get("id") == action_id:
                if session_token and a.get("session_token") != session_token:
                    return None
                a.update(data)
                return a
        return None

def list_actions(session_token: str, idea_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Lists actions for a session/idea_id descending by created_at."""
    client = _get_supabase_client()
    if client:
        query = client.table("agent_actions").select("*").eq("session_token", session_token)
        if idea_id:
            query = query.eq("idea_id", idea_id)
        query = query.order("created_at", desc=True).limit(limit)
        res = query.execute()
        return res.data
    else:
        results = []
        for a in reversed(_local_agent_actions):
            if a.get("session_token") == session_token:
                if not idea_id or a.get("idea_id") == idea_id:
                    results.append(a)
        return results[:limit]

def _reset_local_actions():
    """For tests"""
    _local_agent_actions.clear()
