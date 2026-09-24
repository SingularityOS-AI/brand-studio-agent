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
from unittest.mock import patch

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
#
# WHY TWO WRAPPERS (round 3 fix, 2026-09-22):
# `socket.socket.connect` alone is NOT enough. On Windows, asyncio's default
# event loop (ProactorEventLoop) connects through overlapped I/O -- Proactor.
# sock_connect() calls `self._proactor.connect(sock, address)`, which goes
# straight to the IOCP `ConnectEx` syscall (asyncio/windows_events.py +
# asyncio/proactor_events.py) and NEVER calls `socket.socket.connect`. So an
# async client (e.g. `httpx.AsyncClient().get(...)`, which every async path in
# this app -- app/main.py's `mint_temporary_token`, etc. -- goes through) sailed
# right past the connect() wrapper with no exception at all.
#
# What every async (and sync) network call DOES do first, hostname or not, is
# resolve the address: asyncio's default `loop.getaddrinfo()` is implemented as
# `run_in_executor(None, socket.getaddrinfo, host, port, family, type, proto,
# flags)` (see `asyncio.base_events.BaseEventLoop.getaddrinfo`), and anyio's
# `connect_tcp` (which httpcore's async backend uses, which httpx.AsyncClient
# uses) calls that same `getaddrinfo` for any target that isn't already a raw
# IP literal. So wrapping the plain `socket.getaddrinfo` function closes the
# hole for async *and* sync hostname resolution, on top of the existing
# `connect()` wrapper (which still covers direct IP-literal connections made
# synchronously, and localhost bypass for TestClient/uvicorn).
#
# WHAT THIS LOCK STILL CANNOT CATCH:
# - An async connection straight to a raw IP literal (e.g.
#   `httpx.AsyncClient().get("https://93.184.216.34/")`) on Windows: anyio's
#   connect_tcp() skips getaddrinfo entirely when the host is already parseable
#   as an IP address (see anyio/_core/_sockets.py, `ip_address(remote_host)`
#   check), and ProactorEventLoop's sock_connect() never calls
#   `socket.socket.connect` either (see above) -- so neither wrapper fires.
#   This app never calls external services by raw IP (always by hostname), so
#   it's a theoretical gap, not one seen in this codebase, but it is real.
# - Any library that resolves/connects via a compiled extension that bypasses
#   Python's `socket` module entirely (e.g. a C-extension DB driver with its
#   own networking stack) -- none of this app's dependencies do that today.
# - A custom asyncio event loop / third-party async backend that doesn't route
#   through `BaseEventLoop.getaddrinfo` (this project doesn't install one).


def _is_localhost(addr):
    """Check if an address or hostname is localhost (127.0.0.1 or ::1)."""
    if isinstance(addr, tuple):
        addr = addr[0]
    if isinstance(addr, bytes):
        try:
            addr = addr.decode("idna")
        except UnicodeError:
            addr = addr.decode("utf-8", errors="replace")
    if isinstance(addr, str):
        return addr in ("127.0.0.1", "::1", "localhost", "0.0.0.0")
    return False


def _create_blocked_socket_connect(real_connect):
    """Create a wrapper that blocks non-localhost connections.

    Covers synchronous connects (raw sockets, sync httpx/requests) to a
    non-localhost address. See the module docstring above for what this
    does NOT cover on its own (async connections on Windows).
    """
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


def _create_blocked_getaddrinfo(real_getaddrinfo):
    """Create a wrapper that blocks DNS resolution of non-localhost hosts.

    This is what actually closes the async hole: asyncio's default event
    loop resolves every hostname through `socket.getaddrinfo` in a thread
    executor -- synchronously AND from an async caller -- before connecting,
    so blocking it here catches `httpx.AsyncClient` (and anything else async)
    talking to an external hostname, not just sync socket connects.
    `host` is allowed through untouched when it's `None` (used internally for
    server-side binding, e.g. "listen on all interfaces") since that is not
    an outbound connection attempt.
    """
    def blocked_getaddrinfo(host, *args, **kwargs):
        if host is not None and not _is_localhost(host):
            raise RuntimeError(
                f"NETWORK_LOCK: Test attempted to resolve external host '{host}'. "
                "All external network connections are disabled during tests. "
                "Please mock the appropriate HTTP library (httpx, requests, etc.) "
                "in your test fixtures or use responses/aioresponses/httpx_mock."
            )
        return real_getaddrinfo(host, *args, **kwargs)
    return blocked_getaddrinfo


# Apply the socket lock immediately: block sync connects AND async/sync DNS
# resolution, so async httpx.AsyncClient calls to external hosts are caught
# too (see the long comment above for exactly why both wrappers are needed).
_original_socket_connect = socket.socket.connect
socket.socket.connect = _create_blocked_socket_connect(_original_socket_connect)

_original_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = _create_blocked_getaddrinfo(_original_getaddrinfo)

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
def _empty_audiovisual_libraries_by_default():
    """
    Default the SFX/music library loaders to an empty list for every test.

    `app/audiovisual/library/{sfx,music}.json` now ship with real production
    data (14/15 CC0 entries). Tests must not depend on that real content --
    it can grow/shrink/change independently of test expectations (job counts,
    picked tracks, etc.). Tests that need a specific library patch
    `app.audiovisual.sfx.load_sfx_library` / `app.audiovisual.music.load_music_library`
    themselves inside a `with patch(...)` block (see test_audiovisual_p52.py);
    that inner patch wins while active because it's applied on top of this
    fixture's patch and unwound first, restoring this fixture's `[]` mock
    for the rest of the test.
    """
    with patch("app.audiovisual.sfx.load_sfx_library", return_value=[]), \
            patch("app.audiovisual.music.load_music_library", return_value=[]):
        yield


@pytest.fixture(autouse=True)
def network_lock_active():
    """
    Fixture documenting that network lock is active for all tests.

    This fixture serves as documentation that the NETWORK_LOCK applied
    in the module-level code above is active. Any test attempting
    to connect to external hosts will fail with RuntimeError -- both
    synchronously (socket.socket.connect) and via DNS resolution
    (socket.getaddrinfo, which is what actually catches async clients
    like httpx.AsyncClient on Windows -- see the long comment where the
    lock is installed above for why both wrappers exist).

    Localhost connections (127.0.0.1, ::1, localhost) are allowed
    for TestClient and other local services.

    To mock external HTTP calls, use:
    - @respx.mock for httpx (recommended)
    - responses for requests library
    - unittest.mock.patch for direct socket calls
    """
    yield
