"""
AI Spend Guard anti-bankruptcy module (Bloque D - Pieza 57).
Enforces monthly platform spend limit for AI generation calls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.audiovisual import config as av_config
from app.audiovisual.jobs import sum_cost_usd_since

logger = logging.getLogger(__name__)

AI_KINDS: set[str] = {"ai_image", "ai_video", "music_lyria"}
AI_STATUSES: set[str] = {"pending", "running", "done"}


def monthly_ai_spend_usd() -> float:
    """
    Computes total USD committed/spent on AI assets for the current UTC month.
    Includes pending, running, and done jobs to prevent burst limit bypasses.
    """
    now_utc = datetime.now(timezone.utc)
    first_of_month_iso = now_utc.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    return sum_cost_usd_since(AI_KINDS, AI_STATUSES, first_of_month_iso)


def can_spend(extra_usd: float) -> bool:
    """
    Checks if adding extra_usd to monthly spend keeps total <= AV_MONTHLY_AI_SPEND_CAP_USD.
    Fail-closed: returns False if query or computation fails.
    """
    try:
        cap = float(av_config.AV_MONTHLY_AI_SPEND_CAP_USD)
        current_spend = monthly_ai_spend_usd()
        return (current_spend + float(extra_usd)) <= cap
    except Exception as e:
        logger.error(f"[spend_guard] can_spend check failed: {e}", exc_info=True)
        return False

