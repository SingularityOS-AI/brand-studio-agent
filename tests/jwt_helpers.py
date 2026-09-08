"""
JWT helper functions for testing.
Provides JWT generation for tests in TEST_MODE (uses HS256 for simplicity).
In production, Supabase uses ES256 with asymmetric keys.
"""
import os
import jwt
from datetime import datetime, timedelta

# JWT configuration for tests (uses environment variables from conftest)
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "test_jwt_secret_for_testing_only_32bytes")
JWT_SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://test.supabase.co")


def create_test_jwt(user_id: str, expires_in_hours: int = 24) -> str:
    """
    Helper function to create test JWT tokens using HS256 in TEST_MODE.

    Args:
        user_id: The user ID to embed in the token
        expires_in_hours: How many hours until the token expires

    Returns:
        A signed JWT token string

    Note:
        Tests use HS256 for simplicity. In production, Supabase uses ES256 with
        asymmetric keys via JWKS endpoints. Both are verified correctly by
        SupabaseAuth depending on TEST_MODE setting.
    """
    payload = {
        "sub": user_id,
        "aud": "authenticated",
        "iss": f"{JWT_SUPABASE_URL}/auth/v1",
        "exp": (datetime.utcnow() + timedelta(hours=expires_in_hours)).timestamp(),
    }

    # Sign with HS256 for test simplicity
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
