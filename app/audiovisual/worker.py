"""
Background worker and resolver dispatch loop for audiovisual jobs (Bloque D).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from app.audiovisual.jobs import (
    claim_next_pending,
    mark_charged,
    mark_done,
    mark_failed,
    resume_stale,
    revert_charged,
    revert_to_pending,
)
from app.guard import guard

logger = logging.getLogger(__name__)

# Registry of resolvers: kind -> async callable(job: dict) -> dict (output)
# In Pieza 50, this registry is empty in production and only populated in tests.
RESOLVERS: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]] = {}

_worker_task: asyncio.Task[None] | None = None
_running: bool = False


async def process_one_job() -> bool:
    """
    Attempts to claim and execute one pending job.

    Returns True if a job was claimed, False if none available.
    """
    # If no resolvers are registered, jobs without resolver must stay pending (no falla)
    if not RESOLVERS:
        return False

    job = claim_next_pending(supported_kinds=list(RESOLVERS.keys()))
    if not job:
        return False

    kind = job.get("kind", "")
    resolver = RESOLVERS.get(kind)
    if not resolver:
        revert_to_pending(job["id"])
        return False

    try:
        output = await resolver(job)
    except Exception as e:
        logger.error(f"[worker] Job {job['id']} resolver error: {e}")
        # Job fallido: 0 cobro
        mark_failed(job_id_or_job=job["id"], error=str(e))
        return True

    cost_usd = None
    if isinstance(output, dict) and "cost_usd" in output:
        cost_usd = output["cost_usd"]

    # Cobro write-ahead: antes de llamar a deduct_credits, persistir charged=true
    # en la fila (update … where id=… and charged=false y verificar que afectó 1 fila;
    # si afectó 0, otro proceso ya cobró → no cobrar). Luego deduct_credits.
    # Si deduct_credits lanza → revertir charged=false y fallar el job (punto 2).
    # resume_stale y el reproceso deben respetar charged=true (no volver a cobrar).
    credits_to_charge = job.get("credits", 0)
    charged = job.get("charged", False)

    if credits_to_charge > 0 and not charged:
        acquired = mark_charged(job["id"])
        if acquired:
            try:
                guard.deduct_credits(job["session_token"], amount=credits_to_charge)
                charged = True
            except Exception as e:
                logger.error(f"[worker] Failed to deduct credits for job {job['id']}: {e}")
                revert_charged(job["id"])
                internal_path = None
                if isinstance(output, dict):
                    internal_path = output.get("storage_path") or output.get("internal_storage_path")
                mark_failed(
                    job_id_or_job=job["id"],
                    error=f"Payment failed: {e}",
                    internal_storage_path=internal_path,
                )
                return True
        else:
            # Otra llamada o proceso ya cobró
            charged = True

    mark_done(
        job_id_or_job=job["id"],
        output=output if isinstance(output, dict) else {"result": output},
        cost_usd=cost_usd,
        charged=charged,
    )
    return True


async def worker_loop(poll_interval: float = 3.0) -> None:
    """
    Background worker loop executing every poll_interval seconds.

    Calls resume_stale() on start.
    """
    global _running
    _running = True
    logger.info("[worker] Audiovisual worker loop started.")
    try:
        resumed = resume_stale()
        if resumed > 0:
            logger.info(f"[worker] Resumed {resumed} stale jobs on worker startup.")

        while _running:
            try:
                claimed = await process_one_job()
                if not claimed:
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[worker] Error in worker tick: {e}")
                await asyncio.sleep(poll_interval)
    finally:
        _running = False
        logger.info("[worker] Audiovisual worker loop stopped.")


def start_worker(poll_interval: float = 3.0) -> asyncio.Task[None] | None:
    """Starts the background worker task if not already running."""
    global _worker_task, _running
    if _running or (_worker_task and not _worker_task.done()):
        return _worker_task

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    _worker_task = loop.create_task(worker_loop(poll_interval=poll_interval))
    return _worker_task


async def stop_worker() -> None:
    """Stops the background worker task gracefully."""
    global _worker_task, _running
    _running = False
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
