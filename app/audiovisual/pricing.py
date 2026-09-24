"""
Pricing and cost estimation for Audiovisual Generation (Bloque D).
"""
from __future__ import annotations

from typing import Any

from app.audiovisual.config import AV_COST_CEILING_USD, AV_MAX_AI_VIDEO

# Table of credits per asset kind (Plano Bloque D - A2)
CREDITS_TABLE: dict[str, int] = {
    "base": 0,
    "ai_image": 15,
    "ai_video": 150,
    "music_lyria": 5,
    "a_roll": 0,
    "stock": 0,
    "motion_graphic": 0,
    "music": 0,
    "sfx": 0,
}

# Table of real production costs in USD per asset kind
COST_USD_TABLE: dict[str, float] = {
    "base": 0.01,
    "ai_image": 0.0336,
    "ai_video": 0.30,  # $0.05 / s * 6 s
    "music_lyria": 0.04,  # $0.04 / 30 s clip
    "a_roll": 0.0,
    "stock": 0.0,
    "motion_graphic": 0.0,
    "music": 0.0,
    "sfx": 0.0,
}

# Cascade resolution description per asset type (Plano Bloque D - D2)
CASCADE_RESOLUTION: dict[str, str] = {
    "a_roll": "founder_take",
    "stock": "pexels_pixabay",
    "ai_image": "gemini_image",
    "ai_video": "veo_video",
    "motion_graphic": "hyperframes_template",
    "music": "library_music",
    "sfx": "local_sfx",
}


def estimate(script: Any, allow_unlocked: bool = False) -> dict[str, Any]:
    """
    Compute credit and USD cost estimate for a script.

    Requires the script to be in 'locked' state (unless allow_unlocked=True).
    Devuelve por escena:
    - scene_n, phase, asset_type, resolution, credits, cost_usd
    Música:
    - línea aparte con credits 0 (biblioteca) -- Lyria no se estima aquí.
    Totales:
    - credits_base, cost_usd_base
    - credits_total, cost_usd_total
    - ai_video_count
    - over_ceiling (cost_usd_total > AV_COST_CEILING_USD)
    - over_ai_video_limit (ai_video_count > AV_MAX_AI_VIDEO)
    """
    if isinstance(script, dict):
        state = script.get("state") or script.get("status")
        raw_scenes = script.get("scenes") or script.get("data", {}).get("scenes", [])
    else:
        state = getattr(script, "state", None) or getattr(script, "status", None)
        raw_scenes = getattr(script, "scenes", [])

    if not allow_unlocked and state != "locked":
        raise ValueError(
            f"Script must be locked to estimate audiovisual generation (current state: {state})"
        )

    scene_entries: list[dict[str, Any]] = []
    ai_video_count = 0

    for sc in raw_scenes:
        if isinstance(sc, dict):
            scene_n = sc.get("n")
            phase = sc.get("phase")
            asset_type = sc.get("asset_type", "a_roll")
        else:
            scene_n = getattr(sc, "n", None)
            phase = getattr(sc, "phase", None)
            asset_type = getattr(sc, "asset_type", "a_roll")

        credits = CREDITS_TABLE.get(asset_type, 0)
        cost_usd = COST_USD_TABLE.get(asset_type, 0.0)
        resolution = CASCADE_RESOLUTION.get(asset_type, "founder_take")

        if asset_type == "ai_video":
            ai_video_count += 1

        scene_entries.append({
            "scene_n": scene_n,
            "phase": phase,
            "asset_type": asset_type,
            "resolution": resolution,
            "credits": credits,
            "cost_usd": round(cost_usd, 4),
        })

    music_entry = {
        "kind": "music",
        "source": "library",
        "resolution": CASCADE_RESOLUTION["music"],
        "credits": 0,
        "cost_usd": 0.0,
    }

    base_credits = CREDITS_TABLE["base"]
    base_cost_usd = COST_USD_TABLE["base"]

    credits_total = base_credits + sum(s["credits"] for s in scene_entries) + music_entry["credits"]
    cost_usd_total = round(
        base_cost_usd + sum(s["cost_usd"] for s in scene_entries) + music_entry["cost_usd"],
        4,
    )

    over_ceiling = cost_usd_total > AV_COST_CEILING_USD
    over_ai_video_limit = ai_video_count > AV_MAX_AI_VIDEO

    credits_by_type = {k: v for k, v in CREDITS_TABLE.items() if k not in ("base", "music_lyria")}

    from app.audiovisual.spend_guard import AI_KINDS, can_spend

    script_ai_cost = sum(s["cost_usd"] for s in scene_entries if s["asset_type"] in AI_KINDS) + (
        music_entry["cost_usd"] if music_entry.get("kind") in AI_KINDS else 0.0
    )
    ai_paused = not can_spend(script_ai_cost)

    return {
        "scenes": scene_entries,
        "music": music_entry,
        "credits_base": base_credits,
        "cost_usd_base": base_cost_usd,
        "credits_total": credits_total,
        "cost_usd_total": cost_usd_total,
        "ai_video_count": ai_video_count,
        "over_ceiling": over_ceiling,
        "over_ai_video_limit": over_ai_video_limit,
        "credits_by_type": credits_by_type,
        "ai_paused": ai_paused,
    }
