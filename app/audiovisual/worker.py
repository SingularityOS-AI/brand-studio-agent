"""
Background worker and resolver dispatch loop for audiovisual jobs (Bloque D).
"""
from __future__ import annotations

import asyncio
import logging
import time
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
from app.audiovisual.ai_generation import resolve_ai_image, resolve_ai_video
from app.audiovisual.motion_graphics import resolve_motion_graphic
from app.audiovisual.music import resolve_music
from app.audiovisual.sfx import resolve_sfx
from app.audiovisual.stock import resolve_stock
from app.audiovisual.spend_guard import AI_KINDS, can_spend
from app.guard import guard

logger = logging.getLogger(__name__)

async def resolve_transcript(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'transcript' job (Pieza 51):
    1. Obtains the signed URL for the A-roll take from storage_path.
    2. Sends the signed URL to AssemblyAI for pre-recorded transcription.
    3. Returns text, words (with start_ms, end_ms, confidence), and language_code.
    """
    input_data = job.get("input", {}) or {}
    storage_path = input_data.get("storage_path")
    if not storage_path:
        raise ValueError("Missing storage_path in transcript job input")

    from app.audiovisual.storage import signed_url
    media_signed_url = signed_url(storage_path, ttl=3600)

    from app.config import settings
    import assemblyai as aai

    api_key = getattr(settings, "assemblyai_api_key", None)
    if not api_key:
        raise RuntimeError("AssemblyAI API key not configured")

    aai.settings.api_key = api_key

    config = aai.TranscriptionConfig(language_detection=True)
    transcriber = aai.Transcriber()

    try:
        transcript = await asyncio.wait_for(
            asyncio.to_thread(transcriber.transcribe, media_signed_url, config),
            timeout=120.0,
        )
    except asyncio.TimeoutError as e:
        raise RuntimeError("AssemblyAI transcription timed out") from e
    except Exception as e:
        raise RuntimeError(f"AssemblyAI transcription failed: {e}") from e

    status_val = getattr(transcript, "status", None)
    err = getattr(transcript, "error", None)
    if status_val == aai.TranscriptStatus.error or err:
        raise RuntimeError(f"AssemblyAI transcription error: {err}")

    raw_words = getattr(transcript, "words", None) or []
    words_data: list[dict[str, Any]] = []
    for w in raw_words:
        start_ms = getattr(w, "start", 0)
        end_ms = getattr(w, "end", 0)
        confidence = getattr(w, "confidence", 0.0)
        words_data.append({
            "text": getattr(w, "text", "") or "",
            "start_ms": int(start_ms) if start_ms is not None else 0,
            "end_ms": int(end_ms) if end_ms is not None else 0,
            "confidence": float(confidence) if confidence is not None else 0.0,
        })

    return {
        "text": getattr(transcript, "text", "") or "",
        "words": words_data,
        "language_code": getattr(transcript, "language_code", None) or "en",
        "storage_path": storage_path,
    }


EDITING_KINDS: tuple[str, ...] = ("raw_render", "render")
REFUND_SWEEP_SECONDS: float = 60.0

# Registry of resolvers: kind -> async callable(job: dict) -> dict (output)
# P51: transcript. P52: stock, music, sfx. P53: ai_image, ai_video. P54: motion_graphic.
RESOLVERS: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]] = {
    "transcript": resolve_transcript,
    "stock": resolve_stock,
    "music": resolve_music,
    "sfx": resolve_sfx,
    "ai_image": resolve_ai_image,
    "ai_video": resolve_ai_video,
    "motion_graphic": resolve_motion_graphic,
}


def register_default_resolvers() -> None:
    """Registers built-in resolvers if not present."""
    if "transcript" not in RESOLVERS:
        RESOLVERS["transcript"] = resolve_transcript
    if "stock" not in RESOLVERS:
        RESOLVERS["stock"] = resolve_stock
    if "music" not in RESOLVERS:
        RESOLVERS["music"] = resolve_music
    if "sfx" not in RESOLVERS:
        RESOLVERS["sfx"] = resolve_sfx
    if "ai_image" not in RESOLVERS:
        RESOLVERS["ai_image"] = resolve_ai_image
    if "ai_video" not in RESOLVERS:
        RESOLVERS["ai_video"] = resolve_ai_video
    if "motion_graphic" not in RESOLVERS:
        RESOLVERS["motion_graphic"] = resolve_motion_graphic
    if "raw_render" not in RESOLVERS:
        from app.editing.dispatch import resolve_raw_render

        RESOLVERS["raw_render"] = resolve_raw_render
    if "render" not in RESOLVERS:
        from app.editing.dispatch import resolve_render

        RESOLVERS["render"] = resolve_render


_worker_task: asyncio.Task[None] | None = None
_editing_task: asyncio.Task[None] | None = None
_running: bool = False


async def process_one_job(kinds: list[str] | None = None) -> bool:
    """
    Attempts to claim and execute one pending job.

    Returns True if a job was claimed, False if none available.
    """
    # If no resolvers are registered, jobs without resolver must stay pending (no falla)
    if not RESOLVERS:
        return False

    if kinds is None:
        supported = [k for k in RESOLVERS.keys() if k not in EDITING_KINDS]
    else:
        supported = [k for k in kinds if k in RESOLVERS]

    if not supported:
        return False

    job = claim_next_pending(supported_kinds=supported)
    if not job:
        return False

    kind = job.get("kind", "")
    resolver = RESOLVERS.get(kind)
    if not resolver:
        revert_to_pending(job["id"])
        return False

    if kind in AI_KINDS:
        if not can_spend(0.0):
            logger.warning(
                f"[worker] Job {job['id']} ({kind}) failed: monthly AI spend cap exceeded."
            )
            mark_failed(job_id_or_job=job["id"], error="AI generation paused (platform spend limit)")
            return True

    if kind in EDITING_KINDS:
        if not can_spend(0.01):
            logger.warning(
                f"[worker] Job {job['id']} ({kind}) failed: platform spend limit reached."
            )
            mark_failed(job_id_or_job=job["id"], error="Render paused (platform spend limit)")
            return True

    if kind in ("ai_image", "ai_video"):
        from app.scripting.scripts import _clean_optional_text
        job_input = job.get("input") or {}
        if "visual_prompt" in job_input and _clean_optional_text(job_input.get("visual_prompt")) is None:
            logger.warning(
                f"[worker] Job {job['id']} ({kind}) failed: Missing visual prompt."
            )
            mark_failed(job_id_or_job=job["id"], error="Missing visual prompt")
            return True

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


async def worker_loop(poll_interval: float = 3.0, kinds: list[str] | None = None) -> None:
    """
    Background worker loop executing every poll_interval seconds.

    Calls resume_stale() on start.
    """
    global _running
    _running = True
    logger.info(f"[worker] Audiovisual worker loop started (kinds={kinds}).")
    try:
        resumed = resume_stale()
        if resumed > 0:
            logger.info(f"[worker] Resumed {resumed} stale jobs on worker startup.")

        is_editing_loop = kinds is not None and set(kinds) == set(EDITING_KINDS)
        # The refund sweep is a synchronous Supabase query on the only process
        # (it also serves Brandy's voice): once a minute is plenty, not every tick.
        last_refund_sweep = 0.0

        while _running:
            try:
                if is_editing_loop and time.monotonic() - last_refund_sweep >= REFUND_SWEEP_SECONDS:
                    last_refund_sweep = time.monotonic()
                    try:
                        from app.editing.dispatch import refund_failed_prepaid

                        refund_failed_prepaid()
                    except Exception as e:
                        logger.error(f"[worker] Error in refund_failed_prepaid tick: {e}")

                claimed = await process_one_job(kinds=kinds)
                if not claimed:
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[worker] Error in worker tick: {e}")
                await asyncio.sleep(poll_interval)
    finally:
        _running = False
        logger.info(f"[worker] Audiovisual worker loop stopped (kinds={kinds}).")


def start_worker(poll_interval: float = 3.0) -> asyncio.Task[None] | None:
    """Starts the background worker task if not already running."""
    global _worker_task, _editing_task, _running
    register_default_resolvers()
    if _running or (_worker_task and not _worker_task.done()):
        return _worker_task

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    _worker_task = loop.create_task(worker_loop(poll_interval=poll_interval, kinds=None))
    _editing_task = loop.create_task(
        worker_loop(poll_interval=poll_interval, kinds=list(EDITING_KINDS))
    )
    return _worker_task


async def stop_worker() -> None:
    """Stops the background worker task gracefully."""
    global _worker_task, _editing_task, _running
    _running = False
    tasks = [t for t in (_worker_task, _editing_task) if t and not t.done()]
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    _worker_task = None
    _editing_task = None

