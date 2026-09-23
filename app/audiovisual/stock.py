"""
Stock footage resolver for Audiovisual Generation (Pieza 52).
Searches Pexels Videos with fallback to Pixabay Videos.
0 credits, never downloads video to Render.
"""
from __future__ import annotations

from collections import OrderedDict
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class StockRateLimitError(RuntimeError):
    """Raised when a stock API responds with HTTP 429."""

    pass


# In-memory stock response cache (Pieza 52B)
# Key: (provider, query_normalized_lowercase, orientation)
# Value: (timestamp, raw_parsed_data)
# Excludes API keys from key and value. TTL: 24h. Cap: ~500 entries (FIFO eviction).
_STOCK_CACHE: OrderedDict[tuple[str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
_STOCK_CACHE_MAX_ENTRIES: int = 500
_STOCK_CACHE_TTL_S: float = 24.0 * 3600.0  # 24 hours


def _cache_key(provider: str, query: str, orientation: str = "portrait") -> tuple[str, str, str]:
    return (provider.strip().lower(), query.strip().lower(), orientation.strip().lower())


def _cache_get(provider: str, query: str, orientation: str = "portrait") -> dict[str, Any] | None:
    key = _cache_key(provider, query, orientation)
    entry = _STOCK_CACHE.get(key)
    if entry is None:
        return None
    created_at, data = entry
    if time.time() - created_at > _STOCK_CACHE_TTL_S:
        _STOCK_CACHE.pop(key, None)
        return None
    return data


def _cache_set(provider: str, query: str, data: dict[str, Any], orientation: str = "portrait") -> None:
    key = _cache_key(provider, query, orientation)
    if key not in _STOCK_CACHE and len(_STOCK_CACHE) >= _STOCK_CACHE_MAX_ENTRIES:
        _STOCK_CACHE.popitem(last=False)
    _STOCK_CACHE[key] = (time.time(), data)


def _clear_stock_cache() -> None:
    """Clears the stock in-memory cache (for testing and isolation)."""
    _STOCK_CACHE.clear()


def _score_pexels_video(v: dict[str, Any], est_dur: float) -> tuple[int, int, float, float]:
    """
    Ranks Pexels videos:
    1. Vertical (height > width) first.
    2. Duration >= estimated scene duration.
    3. Aspect ratio closeness to vertical (height / width).
    4. Duration closeness.
    """
    w = int(v.get("width") or 1)
    h = int(v.get("height") or 1)
    dur = float(v.get("duration") or 0.0)

    is_vertical = 1 if h > w else 0
    dur_ok = 1 if (est_dur <= 0 or dur >= est_dur) else 0
    aspect_ratio = float(h) / float(max(w, 1))
    dur_closeness = -abs(dur - est_dur) if est_dur > 0 else dur

    return (is_vertical, dur_ok, aspect_ratio, dur_closeness)


async def _search_pexels(query: str, est_dur: float, orientation: str = "portrait") -> dict[str, Any] | None:
    """Searches Pexels videos API and returns output payload or None."""
    cached_data = _cache_get("pexels", query, orientation)
    if cached_data is not None:
        data = cached_data
    else:
        api_key = getattr(settings, "pexels_api_key", None)
        if not api_key:
            return None

        url = "https://api.pexels.com/v1/videos/search"
        headers = {"Authorization": api_key}
        params = {
            "query": query,
            "orientation": orientation,
            "per_page": "10",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    logger.warning("[stock] Pexels returned HTTP 429 (rate-limited)")
                    raise StockRateLimitError("Pexels 429")
                if resp.status_code != 200:
                    logger.warning(f"[stock] Pexels returned HTTP {resp.status_code}")
                    return None
                data = resp.json()
                _cache_set("pexels", query, data, orientation)
        except StockRateLimitError:
            raise
        except Exception as e:
            logger.warning(f"[stock] Pexels request failed: {type(e).__name__}")
            return None

    videos = data.get("videos")
    if not isinstance(videos, list) or not videos:
        return None

    # Pick the best video
    best_v = max(videos, key=lambda v: _score_pexels_video(v, est_dur))
    video_files = best_v.get("video_files") or []

    # Choose best quality video file (highest resolution)
    def _file_res(f: dict[str, Any]) -> int:
        return int(f.get("width") or 0) * int(f.get("height") or 0)

    best_file = max(video_files, key=_file_res) if video_files else {}
    video_link = best_file.get("link") or best_v.get("url") or ""

    user_info = best_v.get("user")
    author_name = user_info.get("name") if isinstance(user_info, dict) else "Unknown"
    author_url = user_info.get("url") if isinstance(user_info, dict) else ""
    author = author_name or "Unknown"

    width = int(best_file.get("width") or best_v.get("width") or 0)
    height = int(best_file.get("height") or best_v.get("height") or 0)

    return {
        "provider": "pexels",
        "source_id": str(best_v.get("id", "")),
        "preview_url": best_v.get("image") or "",
        "video_url": video_link,
        "width": width,
        "height": height,
        "duration_s": float(best_v.get("duration") or 0.0),
        "author": author,
        "author_url": author_url or "",
        "page_url": best_v.get("url") or "",
        "license": "Pexels License",
        "attribution_text": f"Video by {author} on Pexels",
    }


def _score_pixabay_hit(hit: dict[str, Any], variant: dict[str, Any], est_dur: float) -> tuple[int, int, float, float]:
    """Ranks Pixabay hits & variants."""
    w = int(variant.get("width") or 1)
    h = int(variant.get("height") or 1)
    dur = float(hit.get("duration") or 0.0)

    is_vertical = 1 if h > w else 0
    dur_ok = 1 if (est_dur <= 0 or dur >= est_dur) else 0
    aspect_ratio = float(h) / float(max(w, 1))
    dur_closeness = -abs(dur - est_dur) if est_dur > 0 else dur

    return (is_vertical, dur_ok, aspect_ratio, dur_closeness)


async def _search_pixabay(query: str, est_dur: float, orientation: str = "portrait") -> dict[str, Any] | None:
    """Searches Pixabay videos API and returns output payload or None."""
    cached_data = _cache_get("pixabay", query, orientation)
    if cached_data is not None:
        data = cached_data
    else:
        api_key = getattr(settings, "pixabay_api_key", None)
        if not api_key:
            return None

        url = "https://pixabay.com/api/videos/"
        params = {
            "key": api_key,
            "q": query,
            "per_page": "10",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    logger.warning("[stock] Pixabay returned HTTP 429 (rate-limited)")
                    raise StockRateLimitError("Pixabay 429")
                if resp.status_code != 200:
                    logger.warning(f"[stock] Pixabay returned HTTP {resp.status_code}")
                    return None
                data = resp.json()
                _cache_set("pixabay", query, data, orientation)
        except StockRateLimitError:
            raise
        except Exception as e:
            logger.warning(f"[stock] Pixabay request failed: {type(e).__name__}")
            return None

    hits = data.get("hits")
    if not isinstance(hits, list) or not hits:
        return None

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for hit in hits:
        videos = hit.get("videos") or {}
        # Pick medium or small (or fallback to any available) closest to vertical
        medium = videos.get("medium")
        small = videos.get("small")
        var = medium or small or videos.get("large") or videos.get("tiny")
        if var and var.get("url"):
            candidates.append((hit, var))

    if not candidates:
        return None

    best_hit, best_var = max(
        candidates,
        key=lambda pair: _score_pixabay_hit(pair[0], pair[1], est_dur),
    )

    picture_id = best_hit.get("picture_id")
    preview_url = best_var.get("thumbnail") or (
        f"https://i.vimeocdn.com/video/{picture_id}_640x360.jpg"
        if picture_id
        else best_hit.get("userImageURL") or ""
    )

    author = str(best_hit.get("user") or "Unknown")
    user_id = best_hit.get("user_id")
    if author != "Unknown" and user_id:
        author_url = f"https://pixabay.com/users/{author}-{user_id}/"
    elif author != "Unknown":
        author_url = f"https://pixabay.com/users/{author}/"
    else:
        author_url = ""

    page_url = best_hit.get("pageURL") or ""

    return {
        "provider": "pixabay",
        "source_id": str(best_hit.get("id", "")),
        "preview_url": preview_url,
        "video_url": best_var.get("url") or "",
        "width": int(best_var.get("width") or 0),
        "height": int(best_var.get("height") or 0),
        "duration_s": float(best_hit.get("duration") or 0.0),
        "author": author,
        "author_url": author_url,
        "page_url": page_url,
        "license": "Pixabay Content License",
        "attribution_text": f"Video by {author} on Pixabay",
    }


async def resolve_stock(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'stock' jobs (Pieza 52 + Pieza 52B).
    1. Tries Pexels videos.
    2. Fallback to Pixabay videos.
    3. If a provider responds with HTTP 429, falls back to the next provider immediately.
    4. If both 429 (or available providers 429) -> fails with:
       'Stock providers rate-limited, try again in a minute', 0 credits.
    5. If neither returns results or both keys missing, fails with:
       'No stock found for ...'.
    6. 0 credits, never downloads file to Render.
    """
    input_data = job.get("input", {}) or {}
    query = (input_data.get("stock_query") or input_data.get("spoken_text") or "").strip()
    est_dur = float(input_data.get("duration_s") or 0.0)

    if not query:
        raise RuntimeError("No stock found for ''")

    # Step 1: Pexels
    pexels_429 = False
    pexels_res = None
    try:
        pexels_res = await _search_pexels(query, est_dur)
    except StockRateLimitError:
        pexels_429 = True
        logger.warning(f"[stock] Pexels rate-limited (429) for '{query}', falling back to Pixabay")

    if pexels_res:
        return pexels_res

    # Step 2: Pixabay fallback
    pixabay_429 = False
    pixabay_res = None
    try:
        pixabay_res = await _search_pixabay(query, est_dur)
    except StockRateLimitError:
        pixabay_429 = True
        logger.warning(f"[stock] Pixabay rate-limited (429) for '{query}'")

    if pixabay_res:
        return pixabay_res

    # Step 3: Check if failure was caused by rate limiting
    if pexels_429 and pixabay_429:
        raise RuntimeError("Stock providers rate-limited, try again in a minute")

    pexels_key = getattr(settings, "pexels_api_key", None)
    pixabay_key = getattr(settings, "pixabay_api_key", None)
    if (pexels_429 and not pixabay_key) or (pixabay_429 and not pexels_key):
        raise RuntimeError("Stock providers rate-limited, try again in a minute")

    # Step 4: Neither provider yielded results
    raise RuntimeError(f"No stock found for '{query}'")
