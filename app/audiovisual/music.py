"""
Music resolver with AI decision and local library manifest (Pieza 52).
Decision via Vertex AI text model (mood, energy, volume clamping, reason).
Selects track from app/audiovisual/library/music.json.
Fallback to Lyria behind AV_ALLOW_LYRIA flag (default disabled -> use_music: false, 0 charge).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.audiovisual.config import AV_ALLOW_LYRIA
from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MOODS: list[str] = [
    "upbeat",
    "calm",
    "inspiring",
    "dramatic",
    "corporate",
    "tense",
    "warm",
]

ALLOWED_ENERGIES: list[str] = ["low", "mid", "high"]

LIBRARY_FILE: Path = Path(__file__).parent / "library" / "music.json"


def _clamp_music_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Validates and clamps AI music decision to strict bounds."""
    use_music = bool(decision.get("use_music", True))

    raw_mood = str(decision.get("mood", "")).strip().lower()
    mood = raw_mood if raw_mood in ALLOWED_MOODS else "calm"

    raw_energy = str(decision.get("energy", "")).strip().lower()
    energy = raw_energy if raw_energy in ALLOWED_ENERGIES else "mid"

    try:
        vol = float(decision.get("volume", 0.15))
    except (TypeError, ValueError):
        vol = 0.15
    volume = round(max(0.05, min(0.40, vol)), 2)

    reason = str(decision.get("reason") or "Music matches video tone")

    return {
        "use_music": use_music,
        "mood": mood,
        "energy": energy,
        "volume": volume,
        "reason": reason,
    }


async def _decide_music_with_ai(
    angle: str,
    phases: list[str],
    music_prompt: str,
    recording_format: str,
) -> dict[str, Any]:
    """Calls Vertex AI text model to decide whether to use music, mood, energy, and volume."""
    phases_str = ", ".join(phases) if phases else "hook to cta"
    prompt = (
        "You are the Audio Director for short-form vertical videos.\n"
        "Analyze this video script blueprint and decide whether to use background music, "
        "what mood, energy level, volume, and explanation:\n\n"
        f"- Angle: {angle or 'Business advice'}\n"
        f"- Phases: {phases_str}\n"
        f"- Music Search Prompt: {music_prompt or 'ambient'}\n"
        f"- Recording Format: {recording_format or 'selfie_natural'}\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "use_music": true,\n'
        '  "mood": "upbeat" | "calm" | "inspiring" | "dramatic" | "corporate" | "tense" | "warm",\n'
        '  "energy": "low" | "mid" | "high",\n'
        '  "volume": 0.05 - 0.40,\n'
        '  "reason": "short explanation"\n'
        "}"
    )

    try:
        from vertexai.generative_models import GenerativeModel

        model = GenerativeModel(settings.vertex_ai_model)
        resp = await model.generate_content_async(
            prompt,
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 512,
                "response_mime_type": "application/json",
            },
        )
        text = getattr(resp, "text", "") or ""
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return _clamp_music_decision(parsed)
    except Exception as e:
        logger.warning(f"[music] AI music decision call failed: {type(e).__name__} - using default")

    return {
        "use_music": True,
        "mood": "calm",
        "energy": "mid",
        "volume": 0.15,
        "reason": "Default fallback decision",
    }


def load_music_library() -> list[dict[str, Any]]:
    """Loads music track list from library/music.json manifest."""
    if not LIBRARY_FILE.exists():
        return []
    try:
        content = LIBRARY_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return []
        data = json.loads(content)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[music] Failed to read music.json: {e}")
        return []


async def resolve_music(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'music' jobs (Pieza 52).
    Paso 1: Decisión por IA (Vertex AI model) validada y clampeada.
    Paso 2: Selección de pista en biblioteca local (music.json).
    Fallback Lyria detrás de AV_ALLOW_LYRIA (default desactivado -> use_music: false, 0 créditos).
    """
    input_data = job.get("input", {}) or {}
    angle = str(input_data.get("angle", ""))
    phases = input_data.get("phases") or []
    music_prompt = str(input_data.get("music_prompt", ""))
    recording_format = str(input_data.get("recording_format", ""))
    trim_to_s = float(input_data.get("duration_s") or input_data.get("target_seconds") or 30.0)

    # Paso 1: Decisión
    decision = await _decide_music_with_ai(angle, phases, music_prompt, recording_format)

    if not decision["use_music"]:
        return {
            "use_music": False,
            "mood": decision["mood"],
            "energy": decision["energy"],
            "volume": decision["volume"],
            "reason": decision["reason"],
            "track_file": None,
            "storage_path": None,
            "signed_url": None,
            "trim_to_s": trim_to_s,
        }

    # Paso 2: Pista de biblioteca local
    library = load_music_library()
    matching_tracks = [t for t in library if str(t.get("mood", "")).lower() == decision["mood"]]

    if matching_tracks:
        # Prefer matching energy, then duration >= trim_to_s, or longest
        def _track_score(t: dict[str, Any]) -> tuple[int, int, float]:
            energy_match = 1 if str(t.get("energy", "")).lower() == decision["energy"] else 0
            dur = float(t.get("duration_s") or 0.0)
            dur_ok = 1 if (trim_to_s <= 0 or dur >= trim_to_s) else 0
            return (energy_match, dur_ok, dur)

        chosen = max(matching_tracks, key=_track_score)
        track_file = chosen.get("file", "")
        storage_path = f"library/music/{track_file}" if track_file else None

        signed_url_val = None
        if storage_path:
            try:
                from app.audiovisual.storage import signed_url

                signed_url_val = signed_url(storage_path, ttl=3600)
            except Exception:
                signed_url_val = None

        return {
            "use_music": True,
            "mood": decision["mood"],
            "energy": decision["energy"],
            "volume": decision["volume"],
            "reason": decision["reason"],
            "track_file": track_file,
            "storage_path": storage_path,
            "signed_url": signed_url_val,
            "trim_to_s": trim_to_s,
        }

    # Sin pista para ese mood en la biblioteca local
    if AV_ALLOW_LYRIA:
        # TODO (P53): Lyria music generation ($0.04 / 30s, 5 credits)
        raise NotImplementedError("Lyria music generation is not implemented yet (scheduled for P53)")

    # Lyria apagado por defecto -> video sin música, 0 cobro
    return {
        "use_music": False,
        "mood": decision["mood"],
        "energy": decision["energy"],
        "volume": decision["volume"],
        "reason": f"no library track for mood {decision['mood']}",
        "track_file": None,
        "storage_path": None,
        "signed_url": None,
        "trim_to_s": trim_to_s,
    }
