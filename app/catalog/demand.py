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
from typing import Literal, Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from collections import Counter
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, HttpUrl, Field

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


class NicheResearch(BaseModel):
    """Research data from multiple sources for a niche.

    Used to inform catalog idea generation with citable demand signals.
    """

    niche: str
    youtube_titles: List[str] = Field(default_factory=list)
    youtube_pain_signals: List[str] = Field(default_factory=list)
    trends_series: List[dict] = Field(default_factory=list)
    trends_related: List[dict] = Field(default_factory=list)
    web_grounding_notes: List[str] = Field(default_factory=list)


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

    async def get_video_comments(
        self, video_id: str, max_results: int = 50, force_fresh: bool = False
    ) -> list[dict]:
        """
        Fetch comments from a video with pagination support.

        If cached (and not force_fresh), returns memoized comments.
        Caches on the server per video_id to avoid re-fetching.

        Args:
            video_id: 11‑character video ID
            max_results: Maximum number of comments to return (default: 50)
            force_fresh: If True, bypass cache and fetch fresh data

        Returns:
            List of dicts with comment details:
            [
                {"author": "user123", "text": "Great video!", "like_count": 10},
                ...
            ]
            Empty list if error occurs or token invalid
        """
        comments: list[dict] = []
        results_fetched = 0

        try:
            # Initial request
            params = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": min(100, max_results),
                "textFormat": "plainText",
                "order": "relevance",
                "key": self.api_key,
            }

            response = await self._client.get(f"{self.base_url}/commentThreads", params=params)
            response.raise_for_status()
            data = response.json()

            while data and results_fetched < max_results:
                for item in data.get("items", []):
                    comment = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                    comments.append({
                        "author": comment.get("authorDisplayName", ""),
                        "text": comment.get("textDisplay", ""),
                        "like_count": comment.get("likeCount", 0),
                        "published_at": comment.get("publishedAt", ""),
                    })
                    results_fetched += 1
                    if results_fetched >= max_results:
                        break

                # Check for next page
                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break

                # Fetch next page
                params["pageToken"] = next_page_token
                response = await self._client.get(f"{self.base_url}/commentThreads", params=params)
                response.raise_for_status()
                data = response.json()

            logger.info(f"[youtube] Fetched {len(comments)} comments for {video_id}")
            return comments

        except Exception as e:
            logger.error(f"[youtube] Error fetching comments for {video_id}: {e}")
            return []


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

    def get_interest_over_time(self, keyword: str, timeframe: str = "today 3-m") -> List[dict]:
        """Get interest over time series for a keyword.

        Args:
            keyword: Search term to analyze
            timeframe: Timeframe string (default "today 3-m" for last 3 months)

        Returns:
            List of dicts with date and value: [{"date": "2026-09-07", "value": 28}, ...]
            Empty list if pytrends not available or error occurs
        """
        if not self._available:
            logger.warning("[trends] pytrends not available - cannot fetch interest over time")
            return []

        try:
            # Build payload
            self.pytrends.build_payload([keyword], cat=0, timeframe=timeframe, gprop='')

            # Fetch interest over time
            interest_over_time = self.pytrends.interest_over_time()

            if interest_over_time is None or interest_over_time.empty:
                logger.warning(f"[trends] No data for keyword '{keyword}'")
                return []

            # Drop isPartial column if present
            if 'isPartial' in interest_over_time.columns:
                interest_over_time = interest_over_time[interest_over_time['isPartial'] == False]
                interest_over_time = interest_over_time.drop(columns=['isPartial'])

            # Extract keyword column
            if keyword not in interest_over_time.columns:
                logger.warning(f"[trends] Keyword '{keyword}' not in response")
                return []

            # Convert to list of dicts
            result = []
            for date_index, value in interest_over_time[keyword].items():
                if pd.notna(value):
                    result.append({
                        "date": date_index.strftime("%Y-%m-%d"),
                        "value": int(value)
                    })

            logger.info(f"[trends] Fetched {len(result)} data points for '{keyword}'")
            return result

        except Exception as e:
            logger.error(f"[trends] Error fetching interest over time for '{keyword}': {e}")
            return []

    def get_related_queries(self, keyword: str) -> List[dict]:
        """Get related queries for a keyword.

        Args:
            keyword: Search term to analyze

        Returns:
            List of dicts with query and value: [{"query": "medical interpreter jobs", "value": 100}, ...]
            Empty list if pytrends not available or error occurs
        """
        if not self._available:
            logger.warning("[trends] pytrends not available - cannot fetch related queries")
            return []

        try:
            # Build payload with default timeframe for related queries
            self.pytrends.build_payload([keyword], cat=0, timeframe="today 3-m", gprop='')

            # Fetch related queries
            related = self.pytrends.related_queries()

            if related is None or keyword not in related:
                logger.warning(f"[trends] No related queries for keyword '{keyword}'")
                return []

            # Extract top queries (DataFrame with columns: query, value)
            top_df = related[keyword].get('top')

            if top_df is None or top_df.empty:
                logger.info(f"[trends] No top queries for '{keyword}'")
                return []

            # Convert to list of dicts
            result = []
            for _, row in top_df.iterrows():
                query = row.get('query', '')
                value = row.get('value', 0)
                if pd.notna(query) and pd.notna(value):
                    result.append({
                        "query": query,
                        "value": int(value)
                    })

            logger.info(f"[trends] Fetched {len(result)} related queries for '{keyword}'")
            return result

        except Exception as e:
            logger.error(f"[trends] Error fetching related queries for '{keyword}': {e}")
            return []


# Singleton trends client
_trends_client = TrendsClient()


# =============================================================================
# LLM-BASED FUNCTIONS
# =============================================================================


async def classify_pain_from_comments(video_title: str, comments: List[dict]) -> List[str]:
    """
    Classify pain signals from video comments using a single LLM call.

    This is expensive: 1 LLM call per video. Use sparingly.
    Reuses the Vertex AI client from brand_soul.generator.

    Args:
        video_title: Title of the video for context
        comments: List of comment dicts with "text" field

    Returns:
        List of pain signal strings (e.g., ["cost", "complexity", "trust"])
        Empty list on error or if no pain signals identified

    # PLACEHOLDER: afinar en ronda posterior
    """
    if not comments:
        logger.warning(f"[llm] No comments provided for pain classification")
        return []

    try:
        # Reuse Vertex AI client from brand_soul.generator
        # _get_vertex_ai_client() returns a GenerativeModel directly, not a client
        from app.tools.brand_soul.generator import _get_vertex_ai_client
        model = _get_vertex_ai_client()

    except Exception as e:
        logger.error(f"[llm] Error obtaining Vertex AI client: {e}")
        return []

    try:
        # Prepare comment texts (limit to 20 comments for cost)
        comment_texts = "\n".join([c["text"] for c in comments[:20]])

        # Construct prompt
        prompt = f"""# PLACEHOLDER: afinar en ronda posterior

Video title: {video_title}

Comments:
{comment_texts}

Task: Analyze these comments and identify the main pain points or problems people express.
Return a JSON array of pain signals. Keep it concise (2-5 signals).

Example format: ["cost", "complexity", "lack of trust", "time required"]
"""

        # Generate response
        response = model.generate_content(prompt)

        # Parse response
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]

        import json
        pain_signals = json.loads(result_text)

        if isinstance(pain_signals, list):
            logger.info(f"[llm] Classified {len(pain_signals)} pain signals for '{video_title}'")
            return pain_signals
        else:
            logger.warning(f"[llm] Expected list, got {type(pain_signals)}")
            return []

    except Exception as e:
        logger.error(f"[llm] Error classifying pain signals for '{video_title}': {e}")
        return []


async def ground_web_search(niche: str) -> List[str]:
    """
    Perform grounded web search for niche using Gemini's google_search tool.

    Reuses the Vertex AI client from brand_soul.generator.
    Uses the native google_search tool for web grounding.

    Args:
        niche: Niche to search for

    Returns:
        List of key insights/facts about the niche
        Empty list on error

    # PLACEHOLDER: afinar en ronda posterior
    """
    try:
        # Reuse Vertex AI client from brand_soul.generator
        # _get_vertex_ai_client() returns a GenerativeModel directly, not a client
        from app.tools.brand_soul.generator import _get_vertex_ai_client
        from vertexai.generative_models import Tool, grounding
        model = _get_vertex_ai_client()

    except Exception as e:
        logger.error(f"[llm] Error obtaining Vertex AI client: {e}")
        return []

    try:
        # Configure Google Search grounding tool
        google_search_retrieval = grounding.GoogleSearchRetrieval()
        tool = Tool.from_google_search_retrieval(google_search_retrieval)

        # Construct prompt with google_search tool
        prompt = f"""# PLACEHOLDER: afinar en ronda posterior

Research the niche: {niche}

Use google_search to find:
1. What are the main problems/challenges in this niche?
2. Who are the main players or competitors?
3. What are people searching for related to this niche?

Return a JSON array of 3-5 key insights about this niche.

Example format: ["high demand for X", "low supply of Y", "main competitors are Z"]
"""

        # Generate response with Google Search grounding
        response = model.generate_content(prompt, tools=[tool])

        # Parse response
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]

        import json
        insights = json.loads(result_text)

        if isinstance(insights, list):
            logger.info(f"[llm] Generated {len(insights)} web-grounded insights for '{niche}'")
            return insights
        else:
            logger.warning(f"[llm] Expected list, got {type(insights)}")
            return []

    except Exception as e:
        logger.error(f"[llm] Error performing web search for '{niche}': {e}")
        return []


# =============================================================================
# NICHE RESEARCH ORCHESTRATOR
# =============================================================================


async def research_niche(niche: str) -> NicheResearch:
    """
    Research demand for a niche using 4 data sources.

    Data sources:
    1. YouTube: Get video titles + classify pain signals (1 LLM call per video)
    2. Google Trends: Get interest over time series + related queries
    3. Web Grounding: Use Gemini google_search for research insights

    All sources degrade gracefully: return empty lists on error.

    Args:
        niche: Niche to research

    Returns:
        NicheResearch with all 4 research components
    """
    result = NicheResearch(niche=niche)

    # Initialize YouTube client once
    try:
        yt_client = YouTubeAPIClient()
    except ValueError as e:
        logger.warning(f"[research] YouTube API client not available: {e}")
        result.youtube_titles = []
        result.youtube_pain_signals = []
        result.trends_series = []
        result.trends_related = []
        result.web_grounding_notes = []
        return result

    # Source 1: Search YouTube videos and fetch comments for pain classification
    try:
        top_videos = await yt_client.get_top_videos(niche, limit=10)

        # Extract video titles
        result.youtube_titles = [
            v.get("title", "") for v in top_videos if v.get("title")
        ]

        # Fetch comments and classify pain signals (1 LLM call per video)
        pain_signals = []
        for video in top_videos[:5]:  # Limit to 5 videos for cost control
            video_id = video.get("video_id")
            video_title = video.get("title", "")

            if not video_id:
                continue

            try:
                # Fetch comments
                comments = await yt_client.get_video_comments(video_id, max_results=20)

                if comments:
                    # Classify pain signals (1 LLM call)
                    signals = await classify_pain_from_comments(video_title, comments)
                    pain_signals.extend(signals)

            except Exception as e:
                logger.error(f"[research] Error processing video {video_id}: {e}")
                continue

        # Deduplicate pain signals
        result.youtube_pain_signals = list(set(pain_signals))

    except Exception as e:
        logger.error(f"[research] Error fetching YouTube data: {e}")
        result.youtube_titles = []
        result.youtube_pain_signals = []

    # Source 2: Google Trends - interest over time
    try:
        trends_series = _trends_client.get_interest_over_time(niche, timeframe="today 3-m")
        result.trends_series = trends_series
    except Exception as e:
        logger.error(f"[research] Error fetching trends series: {e}")
        result.trends_series = []

    # Source 3: Google Trends - related queries
    try:
        related_queries = _trends_client.get_related_queries(niche)
        result.trends_related = related_queries
    except Exception as e:
        logger.error(f"[research] Error fetching related queries: {e}")
        result.trends_related = []

    # Source 4: Web grounding with Gemini
    try:
        web_insights = await ground_web_search(niche)
        result.web_grounding_notes = web_insights
    except Exception as e:
        logger.error(f"[research] Error performing web search: {e}")
        result.web_grounding_notes = []

    logger.info(f"[research] Completed niche research for '{niche}'")
    return result


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
