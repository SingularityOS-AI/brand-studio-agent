"""
Tests for Piece 88A — Publication metadata per platform.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.audiovisual.genai_client import set_genai_client
from app.editing.metadata import (
    LIMITS,
    PLATFORMS,
    fallback_metadata,
    generate_metadata,
)


@pytest.fixture(autouse=True)
def cleanup_genai_client():
    set_genai_client(None)
    yield
    set_genai_client(None)


@pytest.fixture
def sample_script():
    return {
        "title": "Cómo escalar tu startup con IA",
        "angle": "Estrategias prácticas de automatización para founders",
        "frame_zero": {
            "visual": "Founder mirando a cámara intensamente",
            "on_screen_text": "3 secretos para escalar tu startup",
        },
        "scenes": [
            {
                "phase": "hook",
                "spoken_text": "¿Estás perdiendo tiempo en tareas repetitivas?",
                "on_screen_text": "Perdiendo tiempo",
            },
            {
                "phase": "body_1",
                "spoken_text": "Implementar agentes de IA permite automatizar procesos clave sin aumentar plantilla.",
                "on_screen_text": "Agentes de IA automatizan",
            },
            {
                "phase": "close_cta",
                "spoken_text": "Comenta AGENTE y te envío la guía completa.",
                "on_screen_text": "Comenta AGENTE",
            },
        ],
    }


@pytest.mark.asyncio
async def test_llm_valid_response(sample_script):
    """Test 1: LLM válido -> source='llm', 3 plataformas en orden, 5 hashtags cada una empezando por '#'."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "platforms": {
            "linkedin": {
                "title": "Escalar tu startup con IA en 2026",
                "description": "Descubre cómo los agentes de IA optimizan tu negocio.",
                "hashtags": ["#startup", "#ia", "#founders", "#automatizacion", "#b2b"],
                "first_comment": "Link a la guía en el primer comentario.",
            },
            "instagram": {
                "title": "3 secretos de IA para founders",
                "description": "Automatiza tu startup hoy mismo con estos pasos.",
                "hashtags": ["#reels", "#startups", "#ia", "#emprendimiento", "#business"],
                "first_comment": "Comenta AGENTE abajo",
            },
            "tiktok": {
                "title": "Cómo usar IA en tu negocio",
                "description": "Directo al grano: automatiza tareas repetitivas.",
                "hashtags": ["#tiktoktech", "#ia", "#founders", "#business", "#growth"],
                "first_comment": "Guía gratis en mi bio.",
            },
        }
    })
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    set_genai_client(mock_client)

    result = await generate_metadata(sample_script, None)

    assert result["source"] == "llm"
    assert tuple(result["platforms"].keys()) == PLATFORMS

    for p in PLATFORMS:
        p_data = result["platforms"][p]
        assert "title" in p_data
        assert "description" in p_data
        assert "hashtags" in p_data
        assert "first_comment" in p_data
        assert len(p_data["hashtags"]) == 5
        assert all(tag.startswith("#") for tag in p_data["hashtags"])


@pytest.mark.asyncio
async def test_hostile_input_sanitization(sample_script):
    """
    Test 2: Hostil: title con '<script>', hashtags con espacios y HTML, first_comment largo, extra key 'html'
    -> sanitizado, sin '<'/'>', títulos <= 100, exactamente 5 hashtags válidos, first_comment <= 300.
    """
    mock_client = MagicMock()
    mock_response = MagicMock()
    hostile_title = "<script>alert('xss')</script>" * 20
    hostile_comment = "A" * 900
    mock_response.text = json.dumps({
        "html": "<div>extra key</div>",
        "platforms": {
            "linkedin": {
                "title": hostile_title,
                "description": "LinkedIn description <script>",
                "hashtags": [
                    "#a b",
                    "#<img>",
                    "#tag1",
                    "#tag2",
                    "#tag3",
                    "#tag4",
                    "#tag5",
                    "#tag6",
                    "#tag7",
                    "#tag8",
                    "#tag9",
                    "#tag10",
                ],
                "first_comment": hostile_comment,
                "extra_field": "should be ignored",
            },
            "instagram": {
                "title": "<style>body{color:red}</style> Instagram Title",
                "description": "Instagram desc",
                "hashtags": ["#instatag1", "#instatag2", "#instatag3", "#instatag4", "#instatag5"],
                "first_comment": "Normal comment",
            },
            "tiktok": {
                "title": "TikTok Title",
                "description": "TikTok desc",
                "hashtags": ["#tiktok1", "#tiktok2", "#tiktok3", "#tiktok4", "#tiktok5"],
                "first_comment": "Comment",
            },
        },
    })
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    set_genai_client(mock_client)

    result = await generate_metadata(sample_script, None)

    assert result["source"] == "llm"

    linkedin_data = result["platforms"]["linkedin"]
    assert "<" not in linkedin_data["title"]
    assert ">" not in linkedin_data["title"]
    assert len(linkedin_data["title"]) <= LIMITS["linkedin"]["title"]

    assert "<" not in linkedin_data["description"]
    assert ">" not in linkedin_data["description"]

    assert len(linkedin_data["first_comment"]) <= 300

    assert len(linkedin_data["hashtags"]) == 5
    for tag in linkedin_data["hashtags"]:
        assert tag.startswith("#")
        assert "<" not in tag
        assert ">" not in tag


@pytest.mark.asyncio
async def test_missing_platform_filled_from_fallback(sample_script):
    """Test 3: Falta 'tiktok' en la respuesta -> se rellena con el respaldo."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "platforms": {
            "linkedin": {
                "title": "LinkedIn Title",
                "description": "LinkedIn Description",
                "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
                "first_comment": "LinkedIn comment",
            },
            "instagram": {
                "title": "Instagram Title",
                "description": "Instagram Description",
                "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
                "first_comment": "Instagram comment",
            },
        }
    })
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    set_genai_client(mock_client)

    result = await generate_metadata(sample_script, None)

    assert result["source"] == "llm"
    assert tuple(result["platforms"].keys()) == PLATFORMS

    tiktok_data = result["platforms"]["tiktok"]
    assert tiktok_data["title"] == sample_script["title"][: LIMITS["tiktok"]["title"]]
    assert len(tiktok_data["hashtags"]) == 5


@pytest.mark.asyncio
async def test_timeout_and_invalid_json_trigger_fallback(sample_script):
    """Test 4: Timeout / JSON inválido / excepción -> source='fallback' con las 3 plataformas completas."""
    # Subtest 4a: Timeout
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=asyncio.TimeoutError())
    set_genai_client(mock_client)

    res_timeout = await generate_metadata(sample_script, None, timeout_s=0.1)
    assert res_timeout["source"] == "fallback"
    assert tuple(res_timeout["platforms"].keys()) == PLATFORMS
    for p in PLATFORMS:
        assert len(res_timeout["platforms"][p]["hashtags"]) == 5

    # Subtest 4b: Invalid JSON
    mock_response = MagicMock()
    mock_response.text = "NOT JSON {{{ ... "
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    set_genai_client(mock_client)

    res_invalid_json = await generate_metadata(sample_script, None)
    assert res_invalid_json["source"] == "fallback"
    assert tuple(res_invalid_json["platforms"].keys()) == PLATFORMS

    # Subtest 4c: Generic Exception
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("Vertex error"))
    set_genai_client(mock_client)

    res_exception = await generate_metadata(sample_script, None)
    assert res_exception["source"] == "fallback"
    assert tuple(res_exception["platforms"].keys()) == PLATFORMS


def test_fallback_metadata_without_brand_brain(sample_script):
    """Test 5: fallback_metadata con brand_brain=None funciona y respeta límites."""
    res = fallback_metadata(sample_script, brand_brain=None)

    assert res["source"] == "fallback"
    assert tuple(res["platforms"].keys()) == PLATFORMS

    for p in PLATFORMS:
        p_data = res["platforms"][p]
        assert len(p_data["title"]) <= LIMITS[p]["title"]
        assert len(p_data["description"]) <= LIMITS[p]["description"]
        assert len(p_data["first_comment"]) <= 300
        assert len(p_data["hashtags"]) == 5
        assert all(tag.startswith("#") for tag in p_data["hashtags"])
