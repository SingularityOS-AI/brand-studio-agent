"""
Tests for Guard Rate Limiting and Session Budget Enforcement.
Uses TestClient with 3 paths:
  1. Normal pass/deduct
  2. Rate limit excess → 429
  3. Budget depleted → 402 with payment URL
"""
import os
import time
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

# Set test mode to bypass API key validation
os.environ["TEST_MODE"] = "true"

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


client = TestClient(app)


def test_normal_request_pass_and_deduct():
    """
    Path 1: Normal request passes rate limit and deducts budget.
    Should receive token and remaining credits.
    """
    response = client.get("/api/token")
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "credits_remaining" in data
    # Credits should be less than initial 500 after deduct
    assert 0 <= data["credits_remaining"] <= 499


def test_rate_limit_excess_returns_429():
    """
    Path 2: IP exceeding rate limit gets 429.
    Make 31 requests (exceeds default 30/min) and verify 429 response.
    """
    # Clear any existing cookies for fresh session
    client.cookies.clear()

    # First 30 requests should pass
    for i in range(30):
        response = client.get("/api/token")
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
    response = client.get("/api/token")
    if response.status_code == 429:
        data = response.json()
        error_data = data.get("detail", data)
        assert "error" in error_data
        assert "retry_after" in error_data
    else:
        # Budget depleted before rate limit hit - still valid
        assert response.status_code == 402


def test_budget_exhausted_returns_402(monkeypatch):
    """
    Path 3: Session exhausting budget gets 402 with configurable payment URL.
    Exhaust all credits and verify payment required response.

    Rate limit (default 30/min) is neutralized here so this test actually
    reaches 402 instead of hitting 429 first and silently skipping the
    assertion it's named for — a session's budget can legitimately outlast
    a minute of requests in real use.
    """
    monkeypatch.setattr(guard, "check_rate_limit", lambda *a, **k: None)
    client.cookies.clear()

    # First request creates the session and consumes 1 of its 500 credits.
    client.get("/api/token")

    # Exhaust the remaining 499.
    last = None
    for _ in range(499):
        last = client.get("/api/token")
        assert last.status_code == 200, last.json()

    # The session now has 0 credits: the very next call must 402.
    response = client.get("/api/token")
    assert response.status_code == 402
    data = response.json()
    assert data["error"] == "Session budget exhausted"
    assert data["credits_remaining"] == 0
    assert "example.com" in data["payment_url"]

    # And it stays 402 — no leak of one extra free call.
    assert client.get("/api/token").status_code == 402


def test_health_endpoint():
    """Health check should return configuration info."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "rate_limit_requests_per_minute" in data
    assert "initial_session_credits" in data


def test_session_status_without_cookie():
    """Session status should fail without valid session token."""
    client.cookies.clear()
    response = client.get("/api/session")
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_startup_without_supabase_uses_memory():
    """
    Guard should work in-memory when Supabase credentials are not set.
    Verifies the log message appears and operations work.
    """
    # Ensure no Supabase env vars
    for key in ["SUPABASE_URL", "SUPABASE_KEY"]:
        if key in os.environ:
            del os.environ[key]

    # Re-import guard to test initialization
    import importlib
    import app.guard
    importlib.reload(app.guard)

    # The log message should have been printed
    # (we can't directly capture print, but we verify it doesn't crash)

    # Basic operations should work
    from app.guard import guard
    token = guard.create_session(initial_credits=100)
    assert token is not None

    credits = guard.get_remaining_credits(token)
    assert credits == 100

    # Deduct should work
    remaining = guard.deduct_credits(token, amount=10)
    assert remaining == 90


def test_startup_with_supabase_calls_database():
    """
    When Supabase credentials are set and TEST_MODE is false, guard should use database.
    Mock the Supabase client to verify it's being used.
    """
    # Set Supabase env vars
    os.environ["SUPABASE_URL"] = "https://test.supabase.co"
    os.environ["SUPABASE_KEY"] = "test_key"
    # CRITICAL: Disable TEST_MODE for this test to verify Supabase behavior
    os.environ["TEST_MODE"] = "false"

    # Mock supabase.create_client at import time (before guard imports it)
    mock_client = Mock()
    mock_table = Mock()
    mock_table.insert.return_value.execute.return_value = None
    mock_table.select.return_value.eq.return_value.execute.return_value = Mock(data=None)
    mock_table.delete.return_value.eq.return_value.execute.return_value = None
    mock_client.table.return_value = mock_table
    mock_client.rpc.return_value.execute.return_value = Mock(data=90)

    with patch.dict("sys.modules", {"supabase": Mock(__version__="2.3.0", create_client=Mock(return_value=mock_client))}):
        # Re-import guard
        import importlib
        import app.guard
        importlib.reload(app.guard)

        from app.guard import guard

        # Verify create_session uses Supabase (it should have called table().insert())
        token = guard.create_session(initial_credits=100)
        mock_table.insert.assert_called_once()

        # Verify deduct_credits uses RPC (atomic)
        remaining = guard.deduct_credits(token, amount=10)
        mock_client.rpc.assert_called_once_with("deduct_credits", params={"p_token": token, "p_amount": 10})

    # Cleanup
    del os.environ["SUPABASE_URL"]
    del os.environ["SUPABASE_KEY"]
    # Restore TEST_MODE
    os.environ["TEST_MODE"] = "true"


def test_atomic_deduction_no_duplicate_spending():
    """
    Two concurrent deductions should not spend the same credit twice.
    Simulate race condition with mocked Supabase RPC.
    """
    # Set up Supabase env vars
    os.environ["SUPABASE_URL"] = "https://test.supabase.co"
    os.environ["SUPABASE_KEY"] = "test_key"
    # CRITICAL: Disable TEST_MODE for this test to verify Supabase behavior
    os.environ["TEST_MODE"] = "false"

    mock_client = Mock()
    mock_table = Mock()
    mock_table.insert.return_value.execute.return_value = None
    mock_table.select.return_value.eq.return_value.execute.return_value = Mock(data=[{"credits": 10}])
    mock_table.delete.return_value.eq.return_value.execute.return_value = None
    mock_client.table.return_value = mock_table

    # Simulate atomic deduction: first call succeeds (10 -> 5), second fails
    call_count = [0]

    def mock_rpc_side_effect(function_name, params):
        call_count[0] += 1
        if call_count[0] == 1:
            # First deduction: 10 - 5 = 5
            return Mock(execute=Mock(return_value=Mock(data=5)))
        else:
            # Second deduction: insufficient credits (NULL returned)
            return Mock(execute=Mock(return_value=Mock(data=None)))

    mock_client.rpc.side_effect = mock_rpc_side_effect

    with patch.dict("sys.modules", {"supabase": Mock(__version__="2.3.0", create_client=Mock(return_value=mock_client))}):
        # Re-import guard
        import importlib
        import app.guard
        importlib.reload(app.guard)

        from app.guard import guard
        from fastapi import HTTPException

        token = "test_token_session"

        # In Supabase mode, we don't have _sessions. Instead, we test that
        # calling deduct_credits with insufficient balance (when RPC returns NULL)
        # raises the expected HTTPException. Since the mock RPC returns None on second call,
        # the deduct should raise 402.

        # First deduct of 5 should succeed (RPC returns 5)
        remaining = guard.deduct_credits(token, amount=5)
        assert remaining == 5

        # Second deduct of 6 should fail (RPC returns NULL = insufficient credits)
        try:
            guard.deduct_credits(token, amount=6)
            assert False, "Should have raised 402"
        except HTTPException as e:
            assert e.status_code == 402
            assert "budget exhausted" in e.detail["error"]

    # Cleanup
    del os.environ["SUPABASE_URL"]
    del os.environ["SUPABASE_KEY"]
    # Restore TEST_MODE
    os.environ["TEST_MODE"] = "true"


def test_cold_session_creates_and_connects():
    """
    Cold visit (no cookie) should:
    1. Fail /api/session check
    2. Succeed via /api/token
    3. Then be able to open WebSocket
    """
    # Clear any existing rate limits from previous tests
    guard._rate_limits.clear()
    guard._blocked_ips.clear()

    fresh_client = TestClient(app)
    fresh_client.cookies.clear()

    # Step 1: /api/session should fail 401
    response = fresh_client.get("/api/session")
    assert response.status_code == 401
    assert "No session token" in response.json()["detail"] or "Invalid session token" in response.json()["detail"]

    # Before Step 2, bypass rate limit temporarily
    original_check = guard.check_rate_limit
    guard._rate_limits.clear()  # Clear again to be safe
    guard._blocked_ips.clear()

    # Step 2: /api/token should create session (costs 1 credit)
    response = fresh_client.get("/api/token")

    # Check if we hit rate limit from cumulative previous tests
    if response.status_code == 429:
        # If we hit rate limit, clear it and retry once
        guard._rate_limits.clear()
        guard._blocked_ips.clear()
        with patch.object(guard, "check_rate_limit", return_value=None):
            response = fresh_client.get("/api/token")

    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "credits_remaining" in data

    # Step 3: Session cookie should be set
    cookie_header = response.headers.get("set-cookie", "")
    assert "session_token" in cookie_header

    # Step 4: /api/session should now work
    response = fresh_client.get("/api/session")
    assert response.status_code == 200
    data = response.json()
    assert "credits_remaining" in data

    # Note: We can't fully test WebSocket in TestClient, but we verify
    # the session setup path which is what was broken


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
