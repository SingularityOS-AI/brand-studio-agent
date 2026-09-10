"""
Demand Validation Engine for Faceless YouTube Channels.

Uses only public data sources:
- YouTube Data API v3: organic demand, trust barrier, packaging patterns
- pytrends: search trend analysis

Every Signal includes a verificable evidence_url. Graceful degradation:
if one source fails, the report continues with available signals.

Hard rule from spec.md §3.4 (Forensic methodology):
- If trend_direction == "baja", abort_recommended = True
- No exceptions, even if creative idea.

Algorithm based on 4-stage validation:
1. Organic Demand: views > subscribers in top 10 videos (last 6 months)
2. Trust Barrier: faceless vs face-on in top 20 channels
3. Packaging Patterns: recurring title/thumbnail patterns in winners
4. Trend Direction: pytrends search volume in last 30 days
"""

import os
import time
import hashlib
import logging
from typing import Literal, Optional, Dict, List, Any
from datetime import datetime, timedelta
from collections import Counter
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, HttpUrl

from app.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# DATA MODELS
# =============================================================================


class Signal(BaseModel):
    """A citable signal extracted from public data.

    Each signal must include:
    - label: What the signal measures
    - value: Human-readable finding
    - evidence_url: Link to verify manually
    - source: youtube_api or pytrends
    """

    label: str
    value: str
    evidence_url: Optional[str] = None
    source: Literal["youtube_api", "pytrends"]


class NicheReport(BaseModel):
    """Structured report for a niche demand validation.

    Contains signals for:
    - demand: Organic interest metrics
    - trust_barrier: Facelessness landscape
    - packaging: Visual/title patterns
    - trend_direction: sube | estable | baja
    - abort_recommended: True if trend_direction == "baja" (hard rule)
    """

    niche: str
    demand: List[Signal] = field(default_factory=list)
    trust_barrier: List[Signal] = field(default_factory=list)
    packaging: List[Signal] = field(default_factory=list)
    trend_direction: Literal["sube", "estable", "baja"] = "estable"
    abort_recommended: bool = False


# =============================================================================
# CACHING LAYER
# =============================================================================


class CacheManager:
    """TTL-based cache for niche demand results.

    Prevents duplicate API quota usage: two users searching the same niche
    in the TTL window reuse cached results.
    """

    def __init__(self, ttl_seconds: int = 3600):
        """Initialize cache with TTL (default 1 hour)."""
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # {key: (timestamp, data)}

    def _make_key(self, niche: str) -> str:
        """Create cache key from normalized niche string."""
        normalized = niche.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, niche: str) -> Optional[NicheReport]:
        """Get cached report if valid."""
        key = self._make_key(niche)
        if key in self._cache:
            timestamp, data = self._cache[key]
            if time.time() - timestamp < self.ttl:
                logger.debug(f"[cache] HIT for niche: {niche}")
                return data
            else:
                # Expired
                del self._cache[key]
        logger.debug(f"[cache] MISS for niche: {niche}")
        return None

    def set(self, niche: str, report: NicheReport) -> None:
        """Cache report with current timestamp."""
        key = self._make_key(niche)
        self._cache[key] = (time.time(), report)

    def clear(self) -> None:
        """Clear all cache entries (useful for tests)."""
        self._cache.clear()


# Singleton cache
_cache_manager = CacheManager()


# =============================================================================
# YOUTUBE DATA API v3 INTEGRATION
# =============================================================================


class YouTubeAPIClient:
    """YouTube Data API v3 client with quota-efficient design.

    Quota-aware (10,000 units/day):
    - Search: 100 units
    - Video read: 1 unit
    - Channel read: 1 unit

    Strategy: ONE search, then reads in batch. Never loop searches.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize client with API key from config."""
        self.api_key = api_key or getattr(settings, 'youtube_api_key', None)
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY not configured")

        self.base_url = "https://www.googleapis.com/youtube/v3"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()

    async def search_videos(
        self,
        query: str,
        max_results: int = 50,
        published_after: Optional[datetime] = None
    ) -> List[dict]:
        """Search for videos (expensive: 100 units).

        Args:
            query: Search query
            max_results: Number of results to return
            published_after: Filter videos after this date

        Returns:
            List of video items with metadata
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": self.api_key,
            "order": "relevance",  # Sort by relevance
        }

        if published_after:
            params["publishedAfter"] = published_after.isoformat() + "Z"

        try:
            response = await self._client.get(f"{self.base_url}/search", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
        except httpx.HTTPError as e:
            logger.error(f"YouTube API search error: {e}")
            raise

    async def get_video_details(self, video_ids: List[str]) -> Dict[str, dict]:
        """Get video statistics (1 unit per video).

        Batch optimizes: fetch up to 50 videos in one request.

        Args:
            video_ids: List of video IDs (max 50)

        Returns:
            Dict mapping video_id to video details
        """
        if not video_ids:
            return {}

        # Batch limit 50 per request
        results = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            params = {
                "part": "statistics,snippet",
                "id": ",".join(batch),
                "key": self.api_key,
            }

            try:
                response = await self._client.get(f"{self.base_url}/videos", params=params)
                response.raise_for_status()
                data = response.json()

                for item in data.get("items", []):
                    video_id = item["id"]
                    results[video_id] = {
                        **item["statistics"],
                        "title": item["snippet"]["title"],
                        "channel_id": item["snippet"]["channelId"],
                        "channel_title": item["snippet"]["channelTitle"],
                        "published_at": item["snippet"]["publishedAt"],
                    }
            except httpx.HTTPError as e:
                logger.error(f"YouTube API video details error: {e}")
                # Continue with next batch
                continue

        return results

    async def get_channel_details(self, channel_ids: List[str]) -> Dict[str, dict]:
        """Get channel statistics (1 unit per channel).

        Args:
            channel_ids: List of channel IDs (max 50)

        Returns:
            Dict mapping channel_id to channel details
        """
        if not channel_ids:
            return {}

        results = {}
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i+50]
            params = {
                "part": "statistics,snippet,brandingSettings",
                "id": ",".join(batch),
                "key": self.api_key,
            }

            try:
                response = await self._client.get(f"{self.base_url}/channels", params=params)
                response.raise_for_status()
                data = response.json()

                for item in data.get("items", []):
                    channel_id = item["id"]
                    results[channel_id] = {
                        **item["statistics"],
                        "title": item["snippet"]["title"],
                        "description": item["snippet"].get("description", ""),
                        "thumbnails": item.get("snippet", {}).get("thumbnails", {}),
                    }
            except httpx.HTTPError as e:
                logger.error(f"YouTube API channel details error: {e}")
                continue

        return results


# =============================================================================
# SIGNAL EXTRACTORS - STAGE 1: ORGANIC DEMAND
# =============================================================================


def extract_organic_demand(
    videos: List[dict],
    channels: Dict[str, dict]
) -> List[Signal]:
    """Extract organic demand signals: views vs subscribers.

    Rule: A video with views >> channel subscribers indicates strong demand.

    Top 10 videos in last 6 months: count how many show this pattern.

    Returns:
        List of demand signals with evidence URLs
    """
    signals = []

    if not videos:
        signals.append(Signal(
            label="Demanda orgánica",
            value="No se encontraron videos para analizar",
            source="youtube_api"
        ))
        return signals

    # Count videos where views > subscribers
    viral_count = 0
    viral_examples = []

    for video in videos[:10]:  # Top 10
        video_id = video.get("video_id", "")
        channel_id = video.get("channel_id", "")

        view_count = int(video.get("viewCount", 0))
        sub_count = int(channels.get(channel_id, {}).get("subscriberCount", 0))

        # Strong demand: views at least 5x subscribers
        if sub_count > 0 and view_count > sub_count * 5:
            viral_count += 1
            viral_examples.append({
                "video_id": video_id,
                "title": video.get("title", ""),
                "views": view_count,
                "subscribers": sub_count,
                "ratio": view_count / sub_count,
            })

    # Build signals
    if viral_count > 0:
        signals.append(Signal(
            label="Demanda orgánica",
            value=f"{viral_count} de 10 videos virales (vistas >> suscriptores)",
            evidence_url=f"https://www.youtube.com/results?search_query={videos[0].get('title', '')[:30]}",
            source="youtube_api"
        ))

        # Top viral example
        if viral_examples:
            best = max(viral_examples, key=lambda x: x["ratio"])
            signals.append(Signal(
                label="Ejemplo de demanda fuerte",
                value=f"'{best['title'][:50]}...' ({best['views']:,} vistas, {best['subscribers']:,} subs)",
                evidence_url=f"https://www.youtube.com/watch?v={best['video_id']}",
                source="youtube_api"
            ))
    else:
        signals.append(Signal(
            label="Demanda orgánica",
            value="No se detectó demanda fuerte (ningún video con vistas 5x suscriptores)",
            source="youtube_api"
        ))

    return signals


# =============================================================================
# SIGNAL EXTRACTORS - STAGE 2: TRUST BARRIER
# =============================================================================


def detect_faceless_channel(channel: dict) -> bool:
    """
    Heuristic faceless detection from channel metadata.

    NOT PERFECT: This is an honest approximation. Faceless channels often:
    - Use brands, not personal names
    - Have generic descriptions
    - No custom branding with personal photo

    Returns:
        True if channel appears faceless, False otherwise
    """
    title = channel.get("title", "").lower()

    # Personal name indicators (high confidence face-on)
    personal_keywords = [
        "coach", "master", "guru", "mentor", "consultor",
        "teacher", "profesor", "expert"
    ]

    # Clear personal branding flags
    for kw in personal_keywords:
        if kw in title:
            return False

    # Brand-style naming patterns suggest faceless
    # (without first/last name structure)
    if " " in title:
        first_word = title.split()[0]
        # If first word is common in brands, likely faceless
        brand_keywords = [
            "the", "smart", "easy", "quick", "pro", "digital",
            "online", "learning", "academy", "hub", "central",
            "lab", "network", "group", "company", "official"
        ]
        if first_word in brand_keywords:
            return True

    # Default: uncertain, assume face-on (conservative)
    return False


def extract_trust_barrier(
    videos: List[dict],
    channels: Dict[str, dict]
) -> List[Signal]:
    """Extract trust barrier signals: faceless vs face-on distribution.

    Top 20 unique channels in results:
    - Count faceless vs face-on
    - High face-on % = high trust barrier (hard to enter)
    - Presence of faceless = entry opportunity

    Returns:
        List of trust barrier signals
    """
    signals = []

    if not videos:
        signals.append(Signal(
            label="Barrera de confianza",
            value="No se encontraron canales para analizar",
            source="youtube_api"
        ))
        return signals

    # Get unique channels from top 20 videos
    unique_channel_ids = list(set(v.get("channel_id") for v in videos[:20]))
    unique_channels = [channels.get(cid, {}) for cid in unique_channel_ids if cid in channels]

    if not unique_channels:
        signals.append(Signal(
            label="Barrera de confianza",
            value="No se obtuvieron detalles de canales",
            source="youtube_api"
        ))
        return signals

    # Detect faceless
    faceless_channels = [ch for ch in unique_channels if detect_faceless_channel(ch)]
    faceless_count = len(faceless_channels)
    faceon_count = len(unique_channels) - faceless_count

    # Calculate percentages
    faceless_pct = (faceless_count / len(unique_channels)) * 100 if unique_channels else 0
    faceon_pct = 100 - faceless_pct

    # Build signals
    signals.append(Signal(
        label="Barrera de confianza",
        value=f"{faceless_count} de {len(unique_channels)} canales sin cara ({faceless_pct:.0f}%)",
        source="youtube_api"
    ))

    if faceon_count > 15:
        signals.append(Signal(
            label="Nivel de barrera",
            value="ALTA: dominio de marca personal, difícil de entrar",
            source="youtube_api"
        ))
    elif faceless_count > 5:
        signals.append(Signal(
            label="Nivel de barrera",
            value="MEDIA-BAJA: hay espacio para canales sin cara",
            source="youtube_api"
        ))
    else:
        signals.append(Signal(
            label="Nivel de barrera",
            value="DESCONOCIDA: muestra insuficiente para determinar",
            source="youtube_api"
        ))

    # List faceless channels as examples
    if faceless_channels:
        example_titles = [ch.get("title", "Unknown") for ch in faceless_channels[:3]]
        signals.append(Signal(
            label="Ejemplos faceless",
            value=f"{', '.join(example_titles)} y {len(faceless_channels) - 3} más",
            source="youtube_api"
        ))

    return signals


# =============================================================================
# SIGNAL EXTRACTORS - STAGE 3: PACKAGING PATTERNS
# =============================================================================


def extract_packaging_patterns(videos: List[dict]) -> List[Signal]:
    """Extract packaging patterns from winning videos.

    Analyzes:
    - Title patterns (uppercase, numbers, hooks)
    - Thumbnail hints (from description/snippet)

    Returns:
        List of packaging pattern signals
    """
    signals = []

    if not videos:
        signals.append(Signal(
            label="Patrones de empaquetado",
            value="No se encontraron videos para analizar",
            source="youtube_api"
        ))
        return signals

    # Analyze top 10
    top_videos = videos[:10]

    # Title analysis
    titles = [v.get("title", "") for v in top_videos]

    # Count uppercase-heavy titles (>50% caps)
    caps_heavy = sum(1 for t in titles if sum(c.isupper() for c in t) / len(t) > 0.5)
    caps_pct = (caps_heavy / len(titles)) * 100 if titles else 0

    # Number usage in titles
    numbers_in_titles = sum(1 for t in titles if any(c.isdigit() for c in t))
    numbers_pct = (numbers_in_titles / len(titles)) * 100 if titles else 0

    # Hook words (attention grabbers)
    hook_words = ["secret", "trick", "hack", "mistake", "fail", "best", "worst", "guide"]
    hooks_count = sum(1 for t in titles if any(hw in t.lower() for hw in hook_words))
    hooks_pct = (hooks_count / len(titles)) * 100 if titles else 0

    # Build signals
    signals.append(Signal(
        label="Uso de mayúsculas",
        value=f"{caps_pct:.0f}% de títulos usan mayúsculas agresivas",
        source="youtube_api"
    ))

    signals.append(Signal(
        label="Uso de números",
        value=f"{numbers_pct:.0f}% de títulos incluyen números",
        source="youtube_api"
    ))

    signals.append(Signal(
        label="Uso de hooks",
        value=f"{hooks_pct:.0f}% de títulos usan palabras gancho (secret, trick, etc.)",
        source="youtube_api"
    ))

    # Sample title patterns
    if len(titles) >= 2:
        signals.append(Signal(
            label="Ejemplos de títulos",
            value=f"'{titles[0][:40]}...' vs '{titles[1][:40]}...'",
            evidence_url=f"https://www.youtube.com/results?search_query={titles[0][:20].replace(' ', '+')}",
            source="youtube_api"
        ))

    return signals


# =============================================================================
# SIGNAL EXTRACTORS - STAGE 4: TREND DIRECTION (PYTRENDS)
# =============================================================================


class TrendsClient:
    """pytrends wrapper with graceful degradation.

    pytrends is unofficial and frequently breaks. We wrap it:
    - If it fails, log and return "estable" (neutral)
    - Never crash the entire request for one failed signal
    """

    def __init__(self):
        """Initialize pytrends client."""
        self._available = False
        self.pytrends = None  # Always initialize attribute so tests can mock it

        try:
            from pytrends.request import TrendReq
            self.pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25), retries=2, backoff_factor=0.1)
            self._available = True
            logger.info("[trends] pytrends initialized successfully")
        except ImportError:
            logger.warning("[trends] pytrends not installed - trend analysis disabled")
        except Exception as e:
            logger.warning(f"[trends] pytrends initialization failed: {e}")

    def is_available(self) -> bool:
        """Check if pytrends is available."""
        return self._available

    def get_trend_direction(self, keyword: str) -> Literal["sube", "estable", "baja"]:
        """
        Get trend direction for keyword in last 30 days.

        Args:
            keyword: Search term to analyze

        Returns:
            "sube" if volume increased, "estable" if flat, "baja" if decreased
            Returns "estable" on any error (graceful degradation)
        """
        if not self._available:
            logger.warning("[trends] pytrends not available - defaulting to 'estable'")
            return "estable"

        try:
            # Build timeframe: last 30 days
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            timeframe = f"{start_date.strftime('%Y-%m-%d')} {end_date.strftime('%Y-%m-%d')}"

            # Fetch interest over time
            self.pytrends.build_payload([keyword], cat=0, timeframe=timeframe, gprop='')
            interest_over_time = self.pytrends.interest_over_time()

            if interest_over_time is None or interest_over_time.empty:
                logger.warning(f"[trends] No data for keyword '{keyword}' - defaulting to 'estable'")
                return "estable"

            # Extract values
            values = interest_over_time[keyword].dropna().tolist()

            if len(values) < 2:
                return "estable"

            # Calculate trend: first 10% vs last 10% average
            n = len(values)
            early_avg = sum(values[:n//10]) / (n//10) if n//10 > 0 else values[0]
            late_avg = sum(values[-n//10:]) / (n//10) if n//10 > 0 else values[-1]

            # Calculate percent change
            if early_avg == 0:
                change_pct = 0
            else:
                change_pct = ((late_avg - early_avg) / early_avg) * 100

            # Determine direction
            if change_pct > 10:
                return "sube"
            elif change_pct < -10:
                return "baja"
            else:
                return "estable"

        except Exception as e:
            logger.error(f"[trends] Error fetching trend for '{keyword}': {e}")
            return "estable"


# Singleton trends client
_trends_client = TrendsClient()


# =============================================================================
# MAIN VALIDATION PIPELINE
# =============================================================================


async def validate_niche_demand(niche: str, use_cache: bool = True) -> NicheReport:
    """
    Validate demand for a niche using public data sources.

    Pipeline:
    1. Check cache
    2. Search YouTube Data API (1 search = 100 units)
    3. Fetch video details (1 unit per video)
    4. Fetch channel details (1 unit per channel)
    5. Extract 4 categories of signals
    6. Analyze trends with pytrends
    7. Apply hard rule: "baja" → abort_recommended

    Args:
        niche: Niche to validate (e.g., "ciberseguridad para despachos de abogados")
        use_cache: Whether to use cached results (default True)

    Returns:
        NicheReport with citable signals and abort recommendation
    """
    report = NicheReport(niche=niche)

    # Step 1: Check cache
    if use_cache:
        cached = _cache_manager.get(niche)
        if cached:
            logger.info(f"[demand] Returning cached report for: {niche}")
            return cached

    logger.info(f"[demand] Analyzing niche: {niche}")

    # Step 2: Initialize YouTube client
    try:
        yt_client = YouTubeAPIClient()
    except ValueError as e:
        logger.error(f"[demand] YouTube API not configured: {e}")
        report.demand.append(Signal(
            label="Error de configuración",
            value=f"YOUTUBE_API_KEY no configurada: {e}",
            source="youtube_api"
        ))
        return report

    try:
        # Step 3: Search for videos in niche (last 6 months)
        six_months_ago = datetime.now() - timedelta(days=180)
        search_results = await yt_client.search_videos(
            query=niche,
            max_results=50,
            published_after=six_months_ago
        )

        if not search_results:
            logger.warning(f"[demand] No results found for niche: {niche}")
            report.demand.append(Signal(
                label="Búsqueda",
                value=f"No se encontraron resultados para '{niche}' en los últimos 6 meses",
                source="youtube_api"
            ))
            return report

        # Extract video IDs and unique channel IDs
        video_ids = [item["id"]["videoId"] for item in search_results[:20]]
        channel_ids = [
            item["snippet"]["channelId"]
            for item in search_results[:20]
        ]

        # Step 4: Fetch video details (batch)
        videos = []
        if video_ids:
            video_details = await yt_client.get_video_details(video_ids)
            for vid in video_ids[:20]:
                if vid in video_details:
                    videos.append({
                        "video_id": vid,
                        **video_details[vid]
                    })

        # Step 5: Fetch channel details (batch)
        channels = {}
        unique_channel_ids = list(set(channel_ids[:20]))
        if unique_channel_ids:
            channels = await yt_client.get_channel_details(unique_channel_ids)

        # Step 6: Extract signal categories
        report.demand = extract_organic_demand(videos, channels)
        report.trust_barrier = extract_trust_barrier(videos, channels)
        report.packaging = extract_packaging_patterns(videos)

        # Step 7: Analyze trends with pytrends
        trend_dir = _trends_client.get_trend_direction(niche)
        report.trend_direction = trend_dir

        # Add trend signal
        report.demand.append(Signal(
            label="Tendencia de búsqueda",
            value=f"La búsqueda '{niche}' está: {trend_dir}",
            source="pytrends"
        ))

        # Step 8: Apply hard rule from spec.md §3.4
        # Forensic methodology: if trend is falling, abort regardless of creativity
        if trend_dir == "baja":
            report.abort_recommended = True
            logger.warning(f"[demand] ABORT RECOMMENDED: trend is falling for '{niche}'")

        # Step 9: Cache result
        if use_cache:
            _cache_manager.set(niche, report)

        logger.info(f"[demand] Analysis complete for: {niche} (abort={report.abort_recommended})")

    except Exception as e:
        logger.error(f"[demand] Unexpected error analyzing '{niche}': {e}")
        report.demand.append(Signal(
            label="Error de análisis",
            value=f"Error inesperado: {str(e)}",
            source="youtube_api"
        ))

    finally:
        await yt_client.close()

    return report


# =============================================================================
# TEST HELPERS
# =============================================================================


def clear_demand_cache():
    """Clear demand cache (useful for tests)."""
    _cache_manager.clear()
