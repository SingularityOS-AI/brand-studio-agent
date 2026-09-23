"""
Local SFX resolver and selector (Pieza 52).
Matches scene sound keywords and funnel phase to library/sfx.json entries.
0 credits, resolved immediately.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LIBRARY_FILE: Path = Path(__file__).parent / "library" / "sfx.json"

PHASE_TAG_MAP: dict[str, str] = {
    "rehook": "riser",
    "close_cta": "ding",
}

KEYWORD_TAGS: list[tuple[str, str]] = [
    ("whoosh", "whoosh"),
    ("swoosh", "whoosh"),
    ("transition", "whoosh"),
    ("pop", "pop"),
    ("click", "click"),
    ("riser", "riser"),
    ("ding", "ding"),
    ("chime", "ding"),
    ("bell", "ding"),
]


def load_sfx_library() -> list[dict[str, Any]]:
    """Loads SFX list from library/sfx.json manifest."""
    if not LIBRARY_FILE.exists():
        return []
    try:
        content = LIBRARY_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return []
        data = json.loads(content)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[sfx] Failed to read sfx.json: {e}")
        return []


def pick_sfx(scene: Any) -> dict[str, Any] | None:
    """
    Selects the best SFX for a scene based on its sound description and phase.
    Returns dict with file, tag, and storage_path, or None if no match or library is empty.
    """
    library = load_sfx_library()
    if not library:
        return None

    if isinstance(scene, dict):
        sound = str(scene.get("sound") or "").lower()
        phase = str(scene.get("phase") or "").lower()
    else:
        sound = str(getattr(scene, "sound", None) or "").lower()
        phase = str(getattr(scene, "phase", None) or "").lower()

    target_tag: str | None = None

    # 1. Direct sound keywords
    for kw, tag in KEYWORD_TAGS:
        if kw in sound:
            target_tag = tag
            break

    # 2. Phase-based fallback
    if not target_tag and phase in PHASE_TAG_MAP:
        target_tag = PHASE_TAG_MAP[phase]

    # 3. Check any tag present in the library mentioned in sound
    if not target_tag:
        for item in library:
            tags = [t.lower() for t in item.get("tags", [])]
            for t in tags:
                if t in sound:
                    target_tag = t
                    break
            if target_tag:
                break

    if not target_tag:
        return None

    # Search for an entry in sfx.json with target_tag
    for item in library:
        tags = [str(t).lower() for t in item.get("tags", [])]
        if target_tag in tags or target_tag in str(item.get("file", "")).lower():
            file_name = item.get("file", "")
            return {
                "file": file_name,
                "tag": target_tag,
                "storage_path": f"library/sfx/{file_name}",
            }

    return None


async def resolve_sfx(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'sfx' jobs (Pieza 52).
    Resolves immediately with storage_path and signed_url (0 credits).
    """
    input_data = job.get("input", {}) or {}
    sfx_file = input_data.get("sfx_file")
    storage_path = input_data.get("storage_path") or (f"library/sfx/{sfx_file}" if sfx_file else None)

    signed_url_val = None
    if storage_path:
        try:
            from app.audiovisual.storage import signed_url

            signed_url_val = signed_url(storage_path, ttl=3600)
        except Exception:
            signed_url_val = None

    return {
        "file": sfx_file,
        "storage_path": storage_path,
        "signed_url": signed_url_val,
        "tag": input_data.get("tag"),
        "scene_n": job.get("scene_n"),
    }
