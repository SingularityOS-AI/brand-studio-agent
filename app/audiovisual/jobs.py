"""
Job tracking and lifecycle management for Audiovisual Generation (Bloque D).
"""
from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings

_jobs_client: Any = None
_local_jobs: dict[str, dict[str, Any]] = {}
_idempotency_index: dict[str, str] = {}
_jobs_lock = threading.Lock()


def _get_jobs_supabase_client() -> Any:
    """Creates Supabase client for asset_jobs table."""
    supabase_url = settings.supabase_url
    supabase_key = settings.supabase_key
    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials not configured")
    try:
        from supabase import create_client

        return create_client(supabase_url, supabase_key)
    except (ImportError, RuntimeError):
        raise RuntimeError("Failed to connect to Supabase")


def _get_jobs_client() -> Any:
    """Returns Supabase client or None if not configured/available."""
    global _jobs_client
    if _jobs_client is None:
        try:
            _jobs_client = _get_jobs_supabase_client()
        except RuntimeError:
            return None
    return _jobs_client


def _reset_local_jobs() -> None:
    """Reset local jobs storage (used for test isolation)."""
    with _jobs_lock:
        _local_jobs.clear()
        _idempotency_index.clear()


def create_job(
    session_token: str,
    idea_id: str,
    scene_n: int | None,
    kind: str,
    credits: int = 0,
    cost_usd: float = 0.0,
    provider: str | None = None,
    model_id: str | None = None,
    input: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    return_created: bool = False,
) -> Any:
    """
    Create a new asset job idempotently.

    If an idempotency_key is provided and a job with that key already exists,
    returns the existing job with created=False without creating a duplicate.
    If the existing job was previously cancelled, reactivates it to pending and sets created=True.
    """
    client = _get_jobs_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    if client is not None:
        if idempotency_key:
            res = (
                client.table("asset_jobs")
                .select("*")
                .eq("idempotency_key", idempotency_key)
                .execute()
            )
            if res.data:
                existing = dict(res.data[0])
                if existing.get("status") == "cancelled":
                    update_res = (
                        client.table("asset_jobs")
                        .update({"status": "pending", "error": None, "updated_at": now_iso})
                        .eq("id", existing["id"])
                        .execute()
                    )
                    reactivated = dict(update_res.data[0]) if update_res.data else existing
                    reactivated["created"] = True
                    return (reactivated, True) if return_created else reactivated
                existing["created"] = False
                return (existing, False) if return_created else existing

        job_data = {
            "session_token": session_token,
            "idea_id": idea_id,
            "scene_n": scene_n,
            "kind": kind,
            "status": "pending",
            "attempts": 0,
            "credits": credits,
            "charged": False,
            "cost_usd": cost_usd,
            "provider": provider,
            "model_id": model_id,
            "input": input or {},
            "output": {},
            "error": None,
            "idempotency_key": idempotency_key,
        }
        try:
            insert_res = client.table("asset_jobs").insert(job_data).execute()
            if insert_res.data:
                new_job = dict(insert_res.data[0])
                new_job["created"] = True
                return (new_job, True) if return_created else new_job
        except Exception:
            # Race condition on idempotency key: re-query
            if idempotency_key:
                res = (
                    client.table("asset_jobs")
                    .select("*")
                    .eq("idempotency_key", idempotency_key)
                    .execute()
                )
                if res.data:
                    existing = dict(res.data[0])
                    existing["created"] = False
                    return (existing, False) if return_created else existing
            raise

    # Fallback to local memory / cache with thread-safety
    with _jobs_lock:
        if idempotency_key and idempotency_key in _idempotency_index:
            existing_id = _idempotency_index[idempotency_key]
            if existing_id in _local_jobs:
                existing = _local_jobs[existing_id]
                if existing.get("status") == "cancelled":
                    existing["status"] = "pending"
                    existing["error"] = None
                    existing["updated_at"] = now_iso
                    reactivated = copy.deepcopy(existing)
                    reactivated["created"] = True
                    return (reactivated, True) if return_created else reactivated
                existing_copy = copy.deepcopy(existing)
                existing_copy["created"] = False
                return (existing_copy, False) if return_created else existing_copy

        if idempotency_key:
            for j in _local_jobs.values():
                if j.get("idempotency_key") == idempotency_key:
                    _idempotency_index[idempotency_key] = j["id"]
                    if j.get("status") == "cancelled":
                        j["status"] = "pending"
                        j["error"] = None
                        j["updated_at"] = now_iso
                        reactivated = copy.deepcopy(j)
                        reactivated["created"] = True
                        return (reactivated, True) if return_created else reactivated
                    existing_copy = copy.deepcopy(j)
                    existing_copy["created"] = False
                    return (existing_copy, False) if return_created else existing_copy

        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "session_token": session_token,
            "idea_id": idea_id,
            "scene_n": scene_n,
            "kind": kind,
            "status": "pending",
            "attempts": 0,
            "credits": credits,
            "charged": False,
            "cost_usd": cost_usd,
            "provider": provider,
            "model_id": model_id,
            "input": input or {},
            "output": {},
            "error": None,
            "idempotency_key": idempotency_key,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _local_jobs[job_id] = job
        if idempotency_key:
            _idempotency_index[idempotency_key] = job_id
        new_job = copy.deepcopy(job)
        new_job["created"] = True
        return (new_job, True) if return_created else new_job


def claim_next_pending(supported_kinds: list[str] | None = None) -> dict[str, Any] | None:
    """
    Atomically claims the next pending job.

    Updates status to 'running' and increments attempts.
    Guarantees no two concurrent callers claim the same job.
    """
    client = _get_jobs_client()
    if client is not None:
        query = client.table("asset_jobs").select("*").eq("status", "pending")
        if supported_kinds is not None:
            query = query.in_("kind", supported_kinds)
        res = query.order("created_at").limit(1).execute()
        if not res.data:
            return None
        candidate = res.data[0]
        candidate_id = candidate["id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        update_res = (
            client.table("asset_jobs")
            .update({
                "status": "running",
                "attempts": candidate.get("attempts", 0) + 1,
                "updated_at": now_iso,
            })
            .eq("id", candidate_id)
            .eq("status", "pending")
            .execute()
        )
        if update_res.data:
            return update_res.data[0]
        return None

    # Local fallback
    with _jobs_lock:
        candidates = [
            j
            for j in _local_jobs.values()
            if j.get("status") == "pending"
            and (supported_kinds is None or j.get("kind") in supported_kinds)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.get("created_at", ""))
        claimed = candidates[0]
        claimed["status"] = "running"
        claimed["attempts"] = claimed.get("attempts", 0) + 1
        claimed["updated_at"] = datetime.now(timezone.utc).isoformat()
        return copy.deepcopy(claimed)


def revert_to_pending(job_id_or_job: str | dict[str, Any]) -> dict[str, Any]:
    """Reverts a claimed running job back to pending without penalty."""
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    client = _get_jobs_client()
    if client is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (
            client.table("asset_jobs")
            .update({
                "status": "pending",
                "updated_at": now_iso,
            })
            .eq("id", job_id)
            .execute()
        )
        return res.data[0] if res.data else {}

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job["status"] = "pending"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        return copy.deepcopy(job)


def mark_done(
    job_id_or_job: str | dict[str, Any],
    output: dict[str, Any],
    cost_usd: float | None = None,
    charged: bool | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Marks a job as done with output payload and optional cost/charge metadata."""
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    now_iso = datetime.now(timezone.utc).isoformat()

    updates: dict[str, Any] = {
        "status": "done",
        "output": output,
        "updated_at": now_iso,
    }
    if cost_usd is not None:
        updates["cost_usd"] = cost_usd
    if charged is not None:
        updates["charged"] = charged
    if error is not None:
        updates["error"] = error

    client = _get_jobs_client()
    if client is not None:
        res = client.table("asset_jobs").update(updates).eq("id", job_id).execute()
        return res.data[0] if res.data else updates

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job.update(updates)
        return copy.deepcopy(job)


def mark_failed(
    job_id_or_job: str | dict[str, Any],
    error: str,
    internal_storage_path: str | None = None,
) -> dict[str, Any]:
    """Marks a job as failed with error description and optional internal storage path."""
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    now_iso = datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {
        "status": "failed",
        "error": str(error),
        "updated_at": now_iso,
    }
    if internal_storage_path:
        updates["output"] = {"internal_storage_path": internal_storage_path}
    else:
        updates["output"] = {}

    client = _get_jobs_client()
    if client is not None:
        res = client.table("asset_jobs").update(updates).eq("id", job_id).execute()
        return res.data[0] if res.data else updates

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job.update(updates)
        return copy.deepcopy(job)


def mark_cancelled(job_id_or_job: str | dict[str, Any], error: str = "Launch payment failed") -> dict[str, Any]:
    """Marks a job as cancelled."""
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    now_iso = datetime.now(timezone.utc).isoformat()
    updates = {
        "status": "cancelled",
        "error": str(error),
        "updated_at": now_iso,
    }

    client = _get_jobs_client()
    if client is not None:
        res = client.table("asset_jobs").update(updates).eq("id", job_id).execute()
        return res.data[0] if res.data else updates

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job.update(updates)
        return copy.deepcopy(job)


def mark_charged(job_id_or_job: str | dict[str, Any]) -> bool:
    """
    Write-ahead charge lock: atomically sets charged=True where id=job_id and charged=False.
    Returns True if 1 row was updated (charge lock acquired).
    Returns False if 0 rows were updated (already charged or locked).
    """
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    client = _get_jobs_client()
    if client is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (
            client.table("asset_jobs")
            .update({"charged": True, "updated_at": now_iso})
            .eq("id", job_id)
            .eq("charged", False)
            .execute()
        )
        return bool(res.data and len(res.data) > 0)

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if not job:
            return False
        if job.get("charged", False):
            return False
        job["charged"] = True
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        return True


def revert_charged(job_id_or_job: str | dict[str, Any]) -> None:
    """Reverts charged=False if credit deduction failed."""
    job_id = job_id_or_job["id"] if isinstance(job_id_or_job, dict) else str(job_id_or_job)
    client = _get_jobs_client()
    if client is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("asset_jobs").update({
            "charged": False,
            "updated_at": now_iso,
        }).eq("id", job_id).execute()
        return

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        if job:
            job["charged"] = False
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def list_jobs(session_token: str, idea_id: str) -> list[dict[str, Any]]:
    """List all jobs for a given session and idea."""
    client = _get_jobs_client()
    if client is not None:
        res = (
            client.table("asset_jobs")
            .select("*")
            .eq("session_token", session_token)
            .eq("idea_id", idea_id)
            .order("created_at")
            .execute()
        )
        return res.data or []

    with _jobs_lock:
        matching = [
            copy.deepcopy(j)
            for j in _local_jobs.values()
            if j.get("session_token") == session_token and j.get("idea_id") == idea_id
        ]
        matching.sort(
            key=lambda x: (
                x.get("scene_n") is not None,
                x.get("scene_n") or 0,
                x.get("created_at", ""),
            )
        )
        return matching


def get_job(job_id: str) -> dict[str, Any] | None:
    """Retrieve single job by id."""
    client = _get_jobs_client()
    if client is not None:
        res = client.table("asset_jobs").select("*").eq("id", job_id).execute()
        return res.data[0] if res.data else None

    with _jobs_lock:
        job = _local_jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def resume_stale() -> int:
    """
    On startup, resumes stale running jobs.

    running -> pending con attempts+1; si attempts >= 3 -> failed.
    Returns number of resumed/stale jobs processed.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    client = _get_jobs_client()
    if client is not None:
        res = client.table("asset_jobs").select("*").eq("status", "running").execute()
        running_jobs = res.data or []
        count = 0
        for job in running_jobs:
            new_attempts = job.get("attempts", 0) + 1
            if new_attempts >= 3:
                client.table("asset_jobs").update({
                    "status": "failed",
                    "attempts": new_attempts,
                    "error": "Max attempts reached (stale job)",
                    "updated_at": now_iso,
                }).eq("id", job["id"]).execute()
            else:
                client.table("asset_jobs").update({
                    "status": "pending",
                    "attempts": new_attempts,
                    "updated_at": now_iso,
                }).eq("id", job["id"]).execute()
            count += 1
        return count

    with _jobs_lock:
        count = 0
        for job in _local_jobs.values():
            if job.get("status") == "running":
                new_attempts = job.get("attempts", 0) + 1
                if new_attempts >= 3:
                    job["status"] = "failed"
                    job["attempts"] = new_attempts
                    job["error"] = "Max attempts reached (stale job)"
                else:
                    job["status"] = "pending"
                    job["attempts"] = new_attempts
                job["updated_at"] = now_iso
                count += 1
        return count
