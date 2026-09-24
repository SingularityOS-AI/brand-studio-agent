"""
Lazy google-genai clients for Vertex AI (Pieza 53), one per location.
Image and video models live in different Vertex locations (see config.py).
"""
from __future__ import annotations

from typing import Any

from app.audiovisual.config import AV_GENAI_LOCATION
from app.config import settings

_genai_clients: dict[str, Any] = {}


def get_genai_client(location: str | None = None) -> Any:
    """Returns the google-genai Client for the given Vertex location, created lazily."""
    loc = location or AV_GENAI_LOCATION
    client = _genai_clients.get(loc)
    if client is None:
        from google import genai

        project_id = getattr(settings, "vertex_ai_project_id", "") or None
        client = genai.Client(vertexai=True, project=project_id, location=loc)
        _genai_clients[loc] = client
    return client


def set_genai_client(client: Any, location: str | None = None) -> None:
    """Sets (or with None, clears) the client for a location; used by tests."""
    loc = location or AV_GENAI_LOCATION
    if client is None:
        _genai_clients.pop(loc, None)
    else:
        _genai_clients[loc] = client
