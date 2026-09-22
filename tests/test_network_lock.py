"""
Test to verify NETWORK_LOCK is active.

This test verifies that the socket-level network isolation is working.
Any attempt to connect to external hosts should fail with a clear error.
"""
import socket
import pytest
import httpx


def test_network_lock_blocks_external_connection():
    """
    Verify NETWORK_LOCK blocks external connections.
    
    This test documents that the network isolation is active.
    Connecting to external hosts (like example.com:80) must fail
    with a RuntimeError containing 'NETWORK_LOCK'.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    with pytest.raises(RuntimeError) as exc_info:
        # Attempt to connect to an external host
        # This MUST fail due to the network lock
        sock.connect(("example.com", 80))
    
    error_msg = str(exc_info.value)
    assert "NETWORK_LOCK" in error_msg, f"Expected NETWORK_LOCK in error, got: {error_msg}"
    assert "example.com" in error_msg, f"Expected host name in error, got: {error_msg}"
    assert "external host" in error_msg, f"Expected 'external host' in error, got: {error_msg}"


def test_network_lock_allows_localhost():
    """
    Verify localhost connections are allowed by NETWORK_LOCK.
    
    TestClient and other local services need localhost connections.
    The lock should not affect these.
    
    Note: This test checks the logic of _is_localhost by attempting
    a connection that we expect to either succeed (if there's a listener)
    or fail with ConnectionRefused (no listener), but NOT fail with
    NETWORK_LOCK.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)  # Short timeout for the test
    
    # Try to connect to localhost on an unlikely port
    # Either ConnectionRefusedError or timeout is acceptable
    # NETWORK_LOCK RuntimeError would NOT be acceptable
    try:
        sock.connect(("127.0.0.1", 65432))
        # If it connects, close the socket
        sock.close()
    except (ConnectionRefusedError, TimeoutError, OSError):
        # These are expected - no listener on that port
        pass
    except RuntimeError as e:
        # This should NOT happen for localhost
        assert "NETWORK_LOCK" not in str(e), f"NETWORK_LOCK should not block localhost: {e}"
        raise


def test_network_lock_allows_localhost_hostname():
    """
    Verify 'localhost' hostname connections are allowed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)

    try:
        sock.connect(("localhost", 65433))
        sock.close()
    except (ConnectionRefusedError, TimeoutError, OSError):
        pass
    except RuntimeError as e:
        assert "NETWORK_LOCK" not in str(e), f"NETWORK_LOCK should not block localhost: {e}"
        raise


# ============================================================================
# Round 3: the async hole (asyncio on Windows never calls socket.connect)
# ============================================================================
# The tests above only proved the lock works for a raw *sync* socket. The
# Captain found empirically that `httpx.AsyncClient` to a real external host
# sailed straight through with no exception at all: on Windows, asyncio's
# default (Proactor) event loop connects via overlapped I/O (`ConnectEx`)
# and never calls `socket.socket.connect`. The fix in conftest.py additionally
# wraps `socket.getaddrinfo` (which every hostname resolution, sync or async,
# goes through -- see the long comment there). These tests prove that hole is
# closed, and reconfirm the sync/raw-socket cases keep working.


def test_network_lock_blocks_getaddrinfo_for_external_host():
    """
    Verify NETWORK_LOCK blocks DNS resolution of an external hostname.

    This is the core of the round-3 fix: asyncio's default event loop
    resolves hostnames via `socket.getaddrinfo` (in a thread executor) before
    ever connecting, sync or async. If this is blocked, every async client
    that isn't handed a raw IP literal is blocked too.
    """
    with pytest.raises(RuntimeError) as exc_info:
        socket.getaddrinfo("example.com", 443)

    error_msg = str(exc_info.value)
    assert "NETWORK_LOCK" in error_msg, f"Expected NETWORK_LOCK in error, got: {error_msg}"
    assert "example.com" in error_msg, f"Expected host name in error, got: {error_msg}"


def test_network_lock_allows_getaddrinfo_for_localhost():
    """
    Verify NETWORK_LOCK does not block resolving 'localhost' or '127.0.0.1'.

    TestClient/uvicorn-style local usage must keep working.
    """
    # Must not raise RuntimeError/NETWORK_LOCK for either of these.
    socket.getaddrinfo("127.0.0.1", 8000)
    socket.getaddrinfo("localhost", 8000)


def test_network_lock_blocks_sync_httpx_to_external_host():
    """
    Verify NETWORK_LOCK blocks a synchronous httpx.get() to an external host.

    Confirms the sync case (via the getaddrinfo wrapper -- httpx resolves the
    hostname before opening the connection) still works after the round-3
    change, alongside the new async coverage below.
    """
    with pytest.raises(RuntimeError) as exc_info:
        httpx.get("https://agents.assemblyai.com/v1/token", timeout=5)

    error_msg = str(exc_info.value)
    assert "NETWORK_LOCK" in error_msg, f"Expected NETWORK_LOCK in error, got: {error_msg}"
    assert "agents.assemblyai.com" in error_msg, f"Expected host name in error, got: {error_msg}"


@pytest.mark.asyncio
async def test_network_lock_blocks_async_httpx_client_to_external_host():
    """
    Verify NETWORK_LOCK blocks httpx.AsyncClient talking to an external host.

    This is the exact case the Captain found escaping the old (sync-only)
    lock: `httpx.AsyncClient().get("https://agents.assemblyai.com/v1/token")`
    -- the same call `app/main.py`'s `mint_temporary_token` makes -- used to
    reach the real internet with no exception at all on Windows. It must now
    fail fast with the NETWORK_LOCK RuntimeError, before any real connection
    is attempted.
    """
    with pytest.raises(RuntimeError) as exc_info:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get("https://agents.assemblyai.com/v1/token")

    error_msg = str(exc_info.value)
    assert "NETWORK_LOCK" in error_msg, f"Expected NETWORK_LOCK in error, got: {error_msg}"
    assert "agents.assemblyai.com" in error_msg, f"Expected host name in error, got: {error_msg}"


@pytest.mark.asyncio
async def test_network_lock_allows_async_httpx_client_to_localhost():
    """
    Verify NETWORK_LOCK does not block an async httpx client reaching for
    localhost. It's expected to fail to actually connect (nothing is
    listening on this port), but it must fail with a connection error, not
    a NETWORK_LOCK RuntimeError.
    """
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            await client.get("http://127.0.0.1:65434/")
    except RuntimeError as e:
        assert "NETWORK_LOCK" not in str(e), f"NETWORK_LOCK should not block localhost: {e}"
    except httpx.HTTPError:
        # Expected: nothing listens on that port, so the connection itself fails.
        pass
