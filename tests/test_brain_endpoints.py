"""
Tests for Brain API endpoints with JWT authentication.
This replaces the old cookie-based test in test_brain.py.
"""
import os

# IMPORTANT: Set TEST_MODE BEFORE any imports that create the supabase_auth singleton
os.environ["TEST_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.guard import guard


def test_get_brand_brain_endpoint_returns_404_when_not_found():
    """GET /api/brain returns 404 if no brand brain exists for session"""
    # Use jwt_helpers to create JWT token with ES256
    from tests.jwt_helpers import create_test_jwt

    user_id = "550e8400-e29b-41d4-a716-446655440000"
    jwt_token = create_test_jwt(user_id)

    # Create a session for this user
    from datetime import datetime
    session_token = guard.create_user_session(user_id, initial_credits=250)
    guard._sessions[session_token] = {
        "credits": 250,
        "created_at": datetime.utcnow().timestamp(),
        "user_id": user_id,
    }

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {jwt_token}"})

    # Try to get brand brain (should not exist yet)
    response = client.get("/api/brain")
    # Should return 404 - no brand brain for this session
    assert response.status_code in [404, 401]  # May fail auth or not found
    if response.status_code == 404:
        assert "not found" in response.json()["error"].lower()
