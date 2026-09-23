"""
Unit and integration tests for PIEZA 52B:
Rebote del QA de la P52 (reglas de los términos de Pexels y Pixabay).

Verifica:
1. La URL de Pexels es https://api.pexels.com/v1/videos/search.
2. Caché en memoria de 24h: dos búsquedas iguales -> 1 sola llamada HTTP.
3. Caché normaliza en minúsculas y espacios.
4. Caché respeta límite de 500 entradas (FIFO / descarta la más vieja).
5. Caché expira tras 24h de TTL.
6. Rate limit: 429 en Pexels -> cae a Pixabay sin bucles.
7. Ambos proveedores 429 -> job failed con 'Stock providers rate-limited, try again in a minute', 0 créditos, charged=false.
8. Atribución completa por proveedor: attribution_text, author_url, page_url.
9. Contrato estático frontend: app.js usa attribution_text en inspector y timeline cards si existe.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
)
from app.audiovisual.stock import (
    _STOCK_CACHE,
    _STOCK_CACHE_MAX_ENTRIES,
    _cache_get,
    _cache_set,
    _clear_stock_cache,
    _search_pexels,
    _search_pixabay,
)
from app.audiovisual.worker import (
    RESOLVERS,
    process_one_job,
    register_default_resolvers,
)
from app.config import settings
from app.guard import guard

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


@pytest.fixture(autouse=True)
def reset_p52b_state():
    """Ensure clean jobs storage, resolvers, sessions, and stock cache for each test."""
    _reset_local_jobs()
    RESOLVERS.clear()
    register_default_resolvers()
    guard._sessions.clear()
    _clear_stock_cache()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()
    _clear_stock_cache()


PEXELS_SAMPLE_RESPONSE = {
    "page": 1,
    "per_page": 10,
    "videos": [
        {
            "id": 855234,
            "width": 1080,
            "height": 1920,
            "duration": 12,
            "url": "https://www.pexels.com/video/855234/",
            "image": "https://images.pexels.com/videos/855234/preview.jpg",
            "user": {"name": "Alex Tech", "url": "https://www.pexels.com/@alex"},
            "video_files": [
                {
                    "id": 1,
                    "quality": "hd",
                    "width": 1080,
                    "height": 1920,
                    "link": "https://videos.pexels.com/video-files/855234/1080p.mp4",
                }
            ],
        }
    ],
}

PIXABAY_SAMPLE_RESPONSE = {
    "total": 1,
    "hits": [
        {
            "id": 998877,
            "user_id": 445566,
            "pageURL": "https://pixabay.com/videos/tech-office-998877/",
            "duration": 8,
            "user": "PixelMaster",
            "picture_id": "123456",
            "videos": {
                "medium": {
                    "url": "https://cdn.pixabay.com/video/medium.mp4",
                    "width": 1080,
                    "height": 1920,
                    "thumbnail": "https://cdn.pixabay.com/video/thumb.jpg",
                }
            },
        }
    ],
}


# ---------------------------------------------------------------------------
# 1. PEXELS URL V1 TEST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pexels_url_is_v1():
    """Pexels search endpoint must be https://api.pexels.com/v1/videos/search (Item 1)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = PEXELS_SAMPLE_RESPONSE

    with patch.object(settings, "pexels_api_key", "pexels_key_123"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            result = await _search_pexels("futuristic tech office", 5.0)
            assert result is not None
            assert result["provider"] == "pexels"

            # Check exact URL called
            mock_client.get.assert_called_once()
            called_url = mock_client.get.call_args[0][0]
            assert called_url == "https://api.pexels.com/v1/videos/search", (
                f"Pexels URL must be v1, got: {called_url}"
            )


# ---------------------------------------------------------------------------
# 2. IN-MEMORY CACHE (24H TTL & MAX 500 CAPACITY)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_cache_two_identical_queries_one_http_call():
    """Two identical searches must result in exactly 1 HTTP call (Item 2)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = PEXELS_SAMPLE_RESPONSE

    with patch.object(settings, "pexels_api_key", "pexels_key_123"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            # Job 1
            job1 = create_job(
                session_token="sess_1",
                idea_id="idea_1",
                scene_n=1,
                kind="stock",
                credits=0,
                input={"stock_query": "futuristic tech office", "duration_s": 5.0},
            )
            success1 = await process_one_job()
            assert success1 is True
            j1_data = get_job(job1["id"])
            assert j1_data["status"] == "done"

            # Job 2 with identical stock_query
            job2 = create_job(
                session_token="sess_1",
                idea_id="idea_1",
                scene_n=2,
                kind="stock",
                credits=0,
                input={"stock_query": "futuristic tech office", "duration_s": 5.0},
            )
            success2 = await process_one_job()
            assert success2 is True
            j2_data = get_job(job2["id"])
            assert j2_data["status"] == "done"

            # HTTP get must have been called exactly ONCE
            assert mock_client.get.call_count == 1
            assert j1_data["output"]["video_url"] == j2_data["output"]["video_url"]


@pytest.mark.asyncio
async def test_stock_cache_normalization_lowercase_and_whitespace():
    """Cache key normalizes query in lowercase and strips leading/trailing whitespace."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = PEXELS_SAMPLE_RESPONSE

    with patch.object(settings, "pexels_api_key", "pexels_key_123"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            # Query 1: lowercase
            r1 = await _search_pexels("cyberpunk city", 5.0)
            assert r1 is not None

            # Query 2: uppercase with extra spaces
            r2 = await _search_pexels("  CYBERPUNK CITY  ", 5.0)
            assert r2 is not None

            # Query 3: MixedCase
            r3 = await _search_pexels("Cyberpunk City", 5.0)
            assert r3 is not None

            # Only 1 network request should have been made
            assert mock_client.get.call_count == 1


def test_stock_cache_fifo_eviction_at_max_capacity():
    """Cache top is 500 entries; inserting 501st discards the oldest entry."""
    _clear_stock_cache()
    assert len(_STOCK_CACHE) == 0

    # Fill up to 500
    for i in range(_STOCK_CACHE_MAX_ENTRIES):
        _cache_set("pexels", f"query_{i}", {"test_idx": i})

    assert len(_STOCK_CACHE) == _STOCK_CACHE_MAX_ENTRIES
    # Verify the first entry exists
    assert _cache_get("pexels", "query_0") is not None

    # Insert 501st entry
    _cache_set("pexels", "query_500", {"test_idx": 500})
    assert len(_STOCK_CACHE) == _STOCK_CACHE_MAX_ENTRIES

    # Oldest entry (query_0) must have been evicted
    assert _cache_get("pexels", "query_0") is None
    # Latest entry must be present
    assert _cache_get("pexels", "query_500") is not None
    # Entry 1 should still be present
    assert _cache_get("pexels", "query_1") is not None


def test_stock_cache_ttl_expiration():
    """Entries older than 24 hours expire and return None."""
    _clear_stock_cache()
    _cache_set("pixabay", "vintage cars", {"hits": []})

    # Fresh entry should be found
    assert _cache_get("pixabay", "vintage cars") is not None

    # Manipulate timestamp to 25 hours ago
    key = ("pixabay", "vintage cars", "portrait")
    ts, data = _STOCK_CACHE[key]
    _STOCK_CACHE[key] = (ts - (25 * 3600), data)

    # Now it should be expired
    assert _cache_get("pixabay", "vintage cars") is None
    assert key not in _STOCK_CACHE


# ---------------------------------------------------------------------------
# 3. RATE LIMIT TESTS (HTTP 429)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_pexels_429_falls_back_to_pixabay():
    """If Pexels returns 429, it must not retry in a loop: immediately falls back to Pixabay."""
    mock_pexels_resp = MagicMock()
    mock_pexels_resp.status_code = 429

    mock_pixabay_resp = MagicMock()
    mock_pixabay_resp.status_code = 200
    mock_pixabay_resp.json.return_value = PIXABAY_SAMPLE_RESPONSE

    with patch.object(settings, "pexels_api_key", "key_pexels"):
        with patch.object(settings, "pixabay_api_key", "key_pixabay"):
            with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()

                def _get_side_effect(url, *args, **kwargs):
                    if "pexels.com" in url:
                        return mock_pexels_resp
                    return mock_pixabay_resp

                mock_client.get.side_effect = _get_side_effect
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=1,
                    kind="stock",
                    credits=0,
                    input={"stock_query": "deep sea coral", "duration_s": 5.0},
                )

                success = await process_one_job()
                assert success is True

                updated = get_job(job["id"])
                assert updated["status"] == "done"
                assert updated["output"]["provider"] == "pixabay"
                assert updated["output"]["attribution_text"] == "Video by PixelMaster on Pixabay"

                # Pexels called once (no infinite retry loop), Pixabay called once
                assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_stock_both_429_fails_without_charge():
    """If both providers return 429 -> job failed with exact message and 0 charge (Item 4)."""
    mock_429_resp = MagicMock()
    mock_429_resp.status_code = 429

    with patch.object(settings, "pexels_api_key", "key_pexels"):
        with patch.object(settings, "pixabay_api_key", "key_pixabay"):
            with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_429_resp
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=1,
                    kind="stock",
                    credits=0,
                    input={"stock_query": "aurora borealis", "duration_s": 5.0},
                )

                success = await process_one_job()
                assert success is True

                updated = get_job(job["id"])
                assert updated["status"] == "failed"
                assert "Stock providers rate-limited, try again in a minute" in updated["error"]
                assert updated["credits"] == 0
                assert updated["charged"] is False


@pytest.mark.asyncio
async def test_stock_single_configured_provider_429_fails_rate_limited():
    """If only Pexels is configured and returns 429, fails with rate-limited error."""
    mock_429_resp = MagicMock()
    mock_429_resp.status_code = 429

    with patch.object(settings, "pexels_api_key", "key_pexels"):
        with patch.object(settings, "pixabay_api_key", ""):
            with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_429_resp
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client_cls.return_value = mock_client

                job = create_job(
                    session_token="sess_1",
                    idea_id="idea_1",
                    scene_n=1,
                    kind="stock",
                    credits=0,
                    input={"stock_query": "northern lights", "duration_s": 5.0},
                )

                success = await process_one_job()
                assert success is True

                updated = get_job(job["id"])
                assert updated["status"] == "failed"
                assert "Stock providers rate-limited, try again in a minute" in updated["error"]
                assert updated["credits"] == 0
                assert updated["charged"] is False


# ---------------------------------------------------------------------------
# 4. ATTRIBUTION COMPLETE (ITEM 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_attribution_complete_pexels_and_pixabay():
    """Both Pexels and Pixabay provide ready attribution_text, author_url, and page_url."""
    # Test Pexels attribution
    mock_pexels_resp = MagicMock()
    mock_pexels_resp.status_code = 200
    mock_pexels_resp.json.return_value = PEXELS_SAMPLE_RESPONSE

    with patch.object(settings, "pexels_api_key", "key_pexels"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_pexels_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            out_pex = await _search_pexels("test query", 5.0)
            assert out_pex is not None
            assert out_pex["author"] == "Alex Tech"
            assert out_pex["author_url"] == "https://www.pexels.com/@alex"
            assert out_pex["page_url"] == "https://www.pexels.com/video/855234/"
            assert out_pex["attribution_text"] == "Video by Alex Tech on Pexels"

    # Test Pixabay attribution
    mock_pixabay_resp = MagicMock()
    mock_pixabay_resp.status_code = 200
    mock_pixabay_resp.json.return_value = PIXABAY_SAMPLE_RESPONSE

    with patch.object(settings, "pixabay_api_key", "key_pixabay"):
        with patch("app.audiovisual.stock.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_pixabay_resp
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client

            out_pix = await _search_pixabay("test query 2", 5.0)
            assert out_pix is not None
            assert out_pix["author"] == "PixelMaster"
            assert out_pix["author_url"] == "https://pixabay.com/users/PixelMaster-445566/"
            assert out_pix["page_url"] == "https://pixabay.com/videos/tech-office-998877/"
            assert out_pix["attribution_text"] == "Video by PixelMaster on Pixabay"


# ---------------------------------------------------------------------------
# 5. FRONTEND STATIC CONTRACT TEST
# ---------------------------------------------------------------------------


def test_frontend_stock_attribution_contract():
    """Verifies that app.js uses attribution_text in inspector and cards if present."""
    assert APP_JS_PATH.exists()
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # Inspector attribution checks attribution_text
    assert "stockJob.output.attribution_text" in content, (
        "Inspector in app.js must check stockJob.output.attribution_text"
    )

    # Timeline card attribution tag includes data-attribution
    assert 'data-attribution="${escapeHtml(attrText)}"' in content, (
        "Timeline card tag in app.js must pass data-attribution attribute"
    )

    # Populator checks dataset.attribution
    assert "el.dataset.attribution" in content, (
        "Card populator in app.js must prefer el.dataset.attribution"
    )
