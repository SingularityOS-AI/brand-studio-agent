"""
pytest configuration for Brand Studio Agent

Configures test environment for isolated testing without external services.

IMPORTANT: This file sets FAKE values for ALL sensitive environment variables
before ANY import from app/. This prevents the real .env from being loaded
during tests and ensures tests never see production secrets.

See test_no_real_secrets_in_tests.py for the safety lock that verifies this.
"""
import os
import socket
import sys

# ============================================================================
# CRITICAL: Set FAKE values for ALL sensitive variables BEFORE any app imports
# ============================================================================
# Using os.environ.pop() opens a hole: dotenv.load_env(..., override=False)
# then fills missing variables from the real .env file. We must SET them
# to fake values so dotenv sees they're "already present" and leaves them alone.

# AssemblyAI (required, guard checks for this)
os.environ["ASSEMBLYAI_API_KEY"] = "test_assemblyai_key_for_testing_only_32bytes"

# Supabase (these control guard mode - empty/falsy means in-memory mode)
# Note: SUPABASE_KEY must be EMPTY STRING (falsy) for guard to use in-memory mode.
# The fake URL is for JWT validation; the empty key prevents Supabase connection.
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = ""  # Empty = in-memory mode (don't connect to Supabase)
os.environ["SUPABASE_SERVICE_KEY"] = ""
os.environ["SUPABASE_JWT_SECRET"] = "test_jwt_secret_for_testing_only_32bytes"
os.environ["SUPABASE_PUBLISHABLE_KEY"] = "test_supabase_publishable_key_fake"

# YouTube API (empty means validation disabled, which is fine for tests)
os.environ["YOUTUBE_API_KEY"] = "test_youtube_api_key_fake"

# Stripe (these MUST be fake - tests should never touch production)
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake_stripe_key_for_testing_only"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_fake_stripe_key_for_testing_only"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_fake_stripe_webhook_secret"

# Payment URL (used in 402 responses)
os.environ["PAYMENT_URL"] = "https://test.example.com/upgrade"

# Vertex AI (used for brand soul generation)
os.environ["VERTEX_AI_PROJECT_ID"] = "test-vertex-project"
os.environ["VERTEX_AI_LOCATION"] = "us-central1"

# Environment flag (for identifying test mode)
os.environ["ENVIRONMENT"] = "test"

# ============================================================================
# NETWORK LOCK: Block all external network connections except localhost
# ============================================================================
# This prevents tests from making real HTTP calls to external services.
# The lock is applied BEFORE importing app modules to catch any imports
# that might trigger network calls.


def _is_localhost(addr):
    """Check if an address is localhost (127.0.0.1 or ::1)."""
    if isinstance(addr, tuple):
        addr = addr[0]
    if isinstance(addr, str):
        return addr in ("127.0.0.1", "::1", "localhost", "0.0.0.0")
    return False


def _create_blocked_socket_connect(real_connect):
    """Create a wrapper that blocks non-localhost connections."""
    def blocked_connect(self, addr):
        # Allow localhost connections for TestClient and other local services
        if _is_localhost(addr):
            return real_connect(self, addr)
        
        # Get the host for error message
        if isinstance(addr, tuple):
            host = addr[0]
        elif isinstance(addr, str):
            host = addr
        else:
            host = str(addr)
        
        raise RuntimeError(
            f"NETWORK_LOCK: Test attempted to connect to external host '{host}'. "
            "All external network connections are disabled during tests. "
            "Please mock the appropriate HTTP library (httpx, requests, etc.) "
            "in your test fixtures or use responses/aioresponses/httpx_mock."
        )
    return blocked_connect


# Apply the socket lock immediately
_original_socket_connect = socket.socket.connect
socket.socket.connect = _create_blocked_socket_connect(_original_socket_connect)

# ============================================================================
# NOW we can import from app (after all secrets are neutralized)
# ============================================================================
import pytest
from tests.jwt_helpers import create_test_jwt
from app.auth.supabase_auth import supabase_auth


# Configure the singleton auth instance for testing.
# SupabaseAuth has _force_legacy_hmac and _legacy_secret attributes for testing.
# We MUTATE the object (not reassign the module attribute) because other modules
# may have already imported the singleton.
supabase_auth._force_legacy_hmac = True
supabase_auth._legacy_secret = "test_jwt_secret_for_testing_only_32bytes"


@pytest.fixture
def test_user_id():
    """Fixture providing a test user ID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def test_jwt_token(test_user_id):
    """Fixture providing a test JWT token for the test user."""
    return create_test_jwt(test_user_id)


@pytest.fixture
def test_auth_headers(test_jwt_token):
    """Fixture providing Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {test_jwt_token}"}


@pytest.fixture
def clean_rate_limit():
    """
    Fixture to clean up rate limit state before a test.
    Clears rate limiting for test client IP.
    """
    from app.guard import guard
    # TestClient uses "testclient" as the client identifier
    client_ips = ["127.0.0.1", "testclient"]
    for client_ip in client_ips:
        if client_ip in guard._rate_limits:
            del guard._rate_limits[client_ip]
        if client_ip in guard._blocked_ips:
            del guard._blocked_ips[client_ip]
    yield


@pytest.fixture
def authenticated_client(test_user_id, test_jwt_token):
    """
    Fixture providing a TestClient with pre configured authenticated user session.
    Creates a user session before returning the client.
    """
    from app.main import app
    from fastapi.testclient import TestClient
    from app.guard import guard

    # Create a user session in test mode
    session_token = guard.create_user_session(test_user_id, initial_credits=250)

    # Store session token in in-memory sessions for test retrieval
    guard._sessions[session_token] = {
        "credits": 250,
        "created_at": None,
        "user_id": test_user_id,
    }

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {test_jwt_token}"})

    # Store session token in app state for client access
    client._test_session_token = session_token

    return client


@pytest.fixture
def clean_rate_limits():
    """
    Fixture to clean up ALL rate limit state.
    Clears all rate limiting state for test client IP.
    """
    from app.guard import guard
    # TestClient uses "testclient" as the client identifier
    client_ips = ["127.0.0.1", "testclient"]
    for client_ip in client_ips:
        if client_ip in guard._rate_limits:
            del guard._rate_limits[client_ip]
        if client_ip in guard._blocked_ips:
            del guard._blocked_ips[client_ip]
    yield


@pytest.fixture
def client_with_session(authenticated_client):
    """
    Alias for authenticated_client for backward compatibility with older tests.
    """
    # Get the session token from the client
    from app.guard import guard
    session_token = get_session_token_for_user("550e8400-e29b-41d4-a716-446655440000")

    # Ensure session exists
    if not session_token:
        token = guard.create_user_session("550e8400-e29b-41d4-a716-446655440000", initial_credits=250)
        authenticated_client._test_session_token = token

    return authenticated_client


# Run each test with clean rate limits
@pytest.fixture(autouse=True)
def auto_clean_rate_limits(clean_rate_limits):
    yield


def get_session_token_for_user(user_id: str) -> str:
    """Helper to find an existing session token for a user (for tests)."""
    from app.guard import guard

    for token, session in guard._sessions.items():
        if session.get("user_id") == user_id:
            return token
    return None


@pytest.fixture(autouse=True)
def network_lock_active():
    """
    Fixture documenting that network lock is active for all tests.
    
    This fixture serves as documentation that the NETWORK_LOCK applied
    in the module-level code above is active. Any test attempting
    to connect to external hosts will fail with RuntimeError.
    
    Localhost connections (127.0.0.1, ::1, localhost) are allowed
    for TestClient and other local services.
    
    To mock external HTTP calls, use:
    - @respx.mock for httpx (recommended)
    - responses for requests library
    - unittest.mock.patch for direct socket calls
    """
    yield
