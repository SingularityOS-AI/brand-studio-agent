"""
pytest configuration for Brand Studio Agent

Sets TEST_MODE before any app imports to prevent database writes during tests.
"""
import os
import pytest

# CRITICAL: Set TEST_MODE BEFORE any app.* imports
# This ensures guard.py and store.py use in-memory storage instead of Supabase
os.environ["TEST_MODE"] = "true"

# JWT configuration for tests
os.environ["SUPABASE_URL"] = "https://test.supabase.co"

# Import JWT helpers (use absolute import since conftest is at test root)
from tests.jwt_helpers import create_test_jwt


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


def get_session_token_for_user(user_id: str) -> str:
    """Helper to find an existing session token for a user (for tests)."""
    from app.guard import guard

    for token, session in guard._sessions.items():
        if session.get("user_id") == user_id:
            return token
    return None


# Import app modules after TEST_MODE is set
# This is after the os.environ setting above so all modules respect TEST_MODE
os.environ["TEST_MODE"] = "true"
