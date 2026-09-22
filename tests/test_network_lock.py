"""
Test to verify NETWORK_LOCK is active.

This test verifies that the socket-level network isolation is working.
Any attempt to connect to external hosts should fail with a clear error.
"""
import socket
import pytest


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
