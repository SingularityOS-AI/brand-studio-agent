"""
Tests for Guard Rate Limiting and Session Budget Enforcement with JWT authentication.
Uses TestClient with 3 paths:
  1. Normal pass/deduct
  2. Rate limit excess → 429
  3. Budget depleted → 402 with payment URL
"""
import os

# IMPORTANT: Set TEST_MODE BEFORE any imports that create the supabase_auth singleton
# This ensures the singleton is initialized in test mode (HS256) instead of production mode (ES256)
os.environ["TEST_MODE"] = "true"

import time
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from app.main import app
from app.guard import guard


# Mock AssemblyAI to avoid real API calls
@pytest.fixture(autouse=True)
def mock_assemblyai():
    # Mock the new SDK classes used by wrapper.py
    with patch("app.voice.wrapper.StreamingClient") as mock_client:
        with patch("app.voice.wrapper.StreamingClientOptions"):
            with patch("app.voice.wrapper.StreamingParameters"):
                with patch("app.voice.wrapper.StreamingEvents"):
                    mock_instance = Mock()
                    mock_instance.on = Mock()
                    mock_client.return_value = mock_instance
                    yield mock_client


@pytest.fixture
def test_user_id():
    """Fixture providing a test user ID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def test_jwt_token(test_user_id):
    """Fixture providing a test JWT token for the test user."""
    from tests.jwt_helpers import create_test_jwt
    return create_test_jwt(test_user_id)


@pytest.fixture
def client_with_auth(test_jwt_token):
    """TestClient with JWT authentication."""
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {test_jwt_token}"})
    return client


def test_normal_request_pass_and_deduct(client_with_auth):
    """
    Path 1: Normal request passes rate limit and deducts budget.
    Should receive token and remaining credits.
    """
    response = client_with_auth.get("/api/token")
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "credits_remaining" in data
    # Credits should be less than initial 250 after deduct
    assert 0 <= data["credits_remaining"] <= 249


def test_request_without_jwt_returns_401():
    """Request without JWT should return 401."""
    client = TestClient(app)
    response = client.get("/api/token")
    assert response.status_code == 401
    assert "Missing authorization header" in response.json()["detail"]


def test_request_with_invalid_jwt_returns_401():
    """Request with invalid JWT should return 401."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer invalid_token"})
    response = client.get("/api/token")
    assert response.status_code == 401


def test_rate_limit_excess_returns_429(client_with_auth):
    """
    Path 2: IP exceeding rate limit gets 429.
    Make 31 requests (exceeds default 30/min) and verify 429 response.
    """
    # Clear any existing rate limits for fresh session
    guard._rate_limits.clear()
    guard._blocked_ips.clear()

    # First 30 requests should pass
    for i in range(30):
        response = client_with_auth.get("/api/token")
        # May get 200, 402 (budget depleted), or 429 (early rate limit)
        assert response.status_code in [200, 402, 429]
        # Stop if we already hit rate limit
        if response.status_code == 429:
            data = response.json()
            # FastAPI wraps in 'detail' key
            error_data = data.get("detail", data)
            assert "error" in error_data
            assert "retry_after" in error_data
            return

    # 31st request should hit rate limit (unless budget depleted first)
    response = client_with_auth.get("/api/token")
    if response.status_code == 429:
        data = response.json()
        error_data = data.get("detail", data)
        assert "error" in error_data
        assert "retry_after" in error_data
    else:
        # Budget depleted before rate limit hit - still valid
        assert response.status_code == 402


def test_budget_exhausted_returns_402(client_with_auth, monkeypatch):
    """
    Path 3: Session exhausting budget gets 402 with configurable payment URL.
    Exhaust all credits and verify payment required response.

    Rate limit (default 30/min) is neutralized here so this test actually
    reaches 402 instead of hitting 429 first and silently skipping the
    assertion it's named for — a session's budget can legitimately outlast
    a minute of requests in real use.
    """
    monkeypatch.setattr(guard, "check_rate_limit", lambda *a, **k: None)

    # Clear any existing sessions to start fresh
    guard._sessions.clear()

    # Make requests until budget is exhausted (250 credits)
    for i in range(250):
        response = client_with_auth.get("/api/token")
        if response.status_code == 402:
            break
        assert response.status_code == 200, f"Request {i} failed: {response.json()}"

    # The session now has 0 credits: the very next call must 402.
    response = client_with_auth.get("/api/token")
    assert response.status_code == 402
    data = response.json()
    assert data["error"] == "Session budget exhausted"
    assert data["credits_remaining"] == 0
    assert "example.com" in data["payment_url"]

    # And it stays 402 — no leak of one extra free call.
    assert client_with_auth.get("/api/token").status_code == 402


def test_health_endpoint():
    """Health check should return configuration info."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "rate_limit_requests_per_minute" in data
    assert "initial_session_credits" in data


def test_session_status_with_jwt(client_with_auth):
    """Session status should work with valid JWT."""
    response = client_with_auth.get("/api/session")
    assert response.status_code == 200
    data = response.json()
    assert "credits_remaining" in data


def test_session_status_without_jwt():
    """Session status should fail without valid JWT."""
    client = TestClient(app)
    response = client.get("/api/session")
    assert response.status_code == 401
    data = response.json()
    assert "Missing authorization header" in data["detail"]


def test_config_endpoint():
    """Config endpoint should return Supabase configuration."""
    client = TestClient(app)
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "supabase_url" in data
    assert "supabase_publishable_key" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
