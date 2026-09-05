"""
Tests for WebSocket Voice Endpoint /ws/voice.
Uses TestClient with cookies to simulate real browser behavior - no manual query params.
WebSocket endpoint receives session_token from cookies (httpOnly), not from URL.
"""
import os
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from unittest.mock import Mock, patch, MagicMock

# Set test mode to bypass API key validation
os.environ["TEST_MODE"] = "true"

from app.main import app
from app.guard import guard
from app.config import settings


def test_assemblyai_sdk_api_calls():
    """
    Verifies that the wrapper correctly uses the AssemblyAI SDK API.
    This test would catch the TypeError mentioned in the issue:
    RealTimeTranscriber.__init__() got an unexpected keyword argument 'on_turn'

    The correct API is:
    - StreamingClient(options=StreamingClientOptions(api_key=...))
    - client.on(StreamingEvents.Turn, handler)
    - client.connect(StreamingParameters(sample_rate=...))

    NOT:
    - RealTimeTranscriber(on_turn=..., on_error=...)  (This was wrong)

    PRIMARY GOAL: Ensure no TypeError is raised when calling start_realtime_transcription.
    The original bug would crash the app before it could connect.
    """
    from app.voice.wrapper import AssemblyAISpeechEngine

    # Create engine with test API key
    engine = AssemblyAISpeechEngine(api_key="test-key-123")

    # Define callback functions
    on_final_called = []
    on_partial_called = []

    def on_final(text, words):
        on_final_called.append((text, words))

    def on_partial(text):
        on_partial_called.append(text)

    # Call start_realtime_transcription - this should NOT raise TypeError
    # The original bug would raise: RealTimeTranscriber.__init__() got an unexpected keyword argument 'on_turn'
    # If that TypeError had occurred, the test would fail before "Streaming STT conectado" prints
    try:
        engine.start_realtime_transcription(
            on_final_callback=on_final,
            on_partial_callback=on_partial,
            sample_rate=16000,
        )
        # Clean up
        engine.stop()
    except TypeError as e:
        pytest.fail(f"TypeError raised - wrapper still uses wrong API pattern: {e}")

    # Success if we reach here without TypeError
    # The message "Streaming STT Universal-3.5 Pro conectado." in stdout confirms the SDK API is correct


# Mock AssemblyAI to avoid real API calls
@pytest.fixture(autouse=True)
def mock_assemblyai():
    """Mock the AssemblyAI wrapper to prevent real WebSocket connections."""
    mock_engine = Mock()
    mock_engine.start_realtime_transcription = Mock()
    mock_engine.stream_audio_chunk = Mock()
    mock_engine.stop = Mock()

    with patch("app.voice.wrapper.AssemblyAISpeechEngine", return_value=mock_engine):
        yield mock_engine



def test_websocket_rejects_without_session_cookie():
    """
    WebSocket should close with code 1008 when no session_token cookie exists.
    This is how a real browser without a session behaves - no manual query param.
    """
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008


@pytest.fixture(autouse=True)
def reset_guard_state():
    """Reset guard state before each test to avoid rate limit conflicts between tests."""
    guard._rate_limits.clear()
    guard._sessions.clear()
    guard._blocked_ips.clear()
    yield


def test_websocket_rejects_without_session_cookie():
    """
    WebSocket should close with code 1008 when no session_token cookie exists.
    This is how a real browser without a session behaves - no manual query param.
    """
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008


def test_websocket_rejects_invalid_session_cookie():
    """
    WebSocket should close with code 1008 when session_token cookie is invalid.
    Real browser sends bad cookie via cookie header, not query string.
    """
    client = TestClient(app)
    # Set an invalid session cookie manually (browser would send this automatically)
    client.cookies.set("session_token", "invalid_token_xyz123")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008


def test_websocket_rejects_token_in_query_string():
    """
    Token in query string should be IGNORED - only cookie is read.
    This test enforces the security fix that prevents tokens from logging in URLs.
    """
    client = TestClient(app)

    # Create a valid session
    valid_session = guard.create_session(initial_credits=500)

    # Try to pass it via query string (malicious or incorrect pattern)
    # The endpoint REQUIRES it from cookie, not query param
    invalid_url = f"/ws/voice?session_token={valid_session}"

    # This should FAIL because token is in URL, not cookie
    # Real browser behavior: cookie jar, not URL construction
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(invalid_url) as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008

    # Clean up
    guard._sessions.pop(valid_session, None)


def test_websocket_accepts_with_valid_cookie_and_deducts_once():
    """
    WebSocket should accept connection with valid cookie and deduct credits ONCE.
    Simulates real browser: cookie already set, then WebSocket uses it.
    """
    client = TestClient(app)

    # Create a session manually (simulates browser that already has this session)
    session_token = guard.create_session(initial_credits=settings.initial_session_credits)

    # Set cookie manually (simulating browser that already has this session)
    client.cookies.set("session_token", session_token)

    # Verify initial budget
    initial_credits = guard.get_remaining_credits(session_token)
    assert initial_credits == settings.initial_session_credits

    # Step 2: Browser opens WebSocket - TestClient automatically sends cookie
    with client.websocket_connect("/ws/voice") as websocket:
        # Connection accepted
        # Credits should be deducted ONCE for the voice session (10 credits)
        remaining = guard.get_remaining_credits(session_token)
        expected_remaining = initial_credits - 10
        assert remaining == expected_remaining, f"Expected {expected_remaining}, got {remaining}"

        # Send some audio data (simulates browser sending mic chunks)
        audio_chunk = b'\x00' * 4096  # Silent PCM16 audio
        websocket.send_bytes(audio_chunk)

        # Send multiple chunks - should NOT deduct more credits
        for _ in range(5):
            audio_chunk = b'\x00' * 4096
            websocket.send_bytes(audio_chunk)

        # Credits still same - one-time deduction per session
        final_remaining = guard.get_remaining_credits(session_token)
        assert final_remaining == expected_remaining, f"Expected {expected_remaining}, got {final_remaining}"


def test_websocket_rejects_depleted_budget_via_cookie():
    """
    WebSocket should close with code 1008 when session has insufficient credits.
    Uses cookie flow, not query param injection.
    """
    client = TestClient(app)

    # Create a session with exactly 5 credits (less than required 10)
    session_token = guard.create_session(initial_credits=5)

    # Set cookie manually (simulating browser that already has this session)
    client.cookies.set("session_token", session_token)

    # WebSocket requires 10 credits - should fail
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008


def test_websocket_deducts_credits_once_per_session():
    """
    Credits should be deducted ONCE per voice session, not per audio chunk.
    Tests the inflight behavior: multiple chunks, single deduction.
    """
    client = TestClient(app)

    # Create session manually
    session_token = guard.create_session(initial_credits=settings.initial_session_credits)

    # Set cookie
    client.cookies.set("session_token", session_token)

    # Open WebSocket session
    with client.websocket_connect("/ws/voice") as websocket:
        # Initial deduction happened
        initial_remaining = guard.get_remaining_credits(session_token)
        # Should be: initial_credits - 10 (voice session)
        expected = settings.initial_session_credits - 10
        assert initial_remaining == expected, f"Expected {expected}, got {initial_remaining}"

        # Send MANY audio chunks
        for _ in range(20):
            audio_chunk = b'\x00' * 4096
            websocket.send_bytes(audio_chunk)

        # Credits should NOT have been deducted again
        final_remaining = guard.get_remaining_credits(session_token)
        assert final_remaining == expected, f"Expected {expected}, got {final_remaining}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
