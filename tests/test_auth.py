"""
Tests for Google OAuth authentication and JWT verification with ES256.
"""
import os

# Set TEST_MODE before imports to ensure singleton is initialized in test mode
os.environ["TEST_MODE"] = "true"

import pytest
import jwt
from fastapi import HTTPException
from app.auth.supabase_auth import SupabaseAuth, supabase_auth
from app.config import settings


class TestSupabaseAuth:
    """Tests for Supabase JWT verification and user authentication."""

    def setup_method(self):
        """Set up test configuration."""
        self.mock_jwt_secret = "test_jwt_secret_for_testing_only_32bytes"
        self.mock_supabase_url = "https://test.supabase.co"
        self.test_user_id = "550e8400-e29b-41d4-a716-446655440000"

    def test_create_valid_jwt_token_hs256(self):
        """
        Create a valid HS256 JWT token for backward compatibility testing.
        This tests the legacy mode that allows existing tests to continue working.
        """
        payload = {
            "sub": self.test_user_id,
            "aud": "authenticated",
            "iss": f"{self.mock_supabase_url}/auth/v1",
            "exp": 9999999999,  # Far in the future
        }
        token = jwt.encode(payload, self.mock_jwt_secret, algorithm="HS256")
        payload["exp"] = int(payload["exp"])  # Convert to keep format consistent
        return token

    def test_verify_valid_token_legacy_mode(self):
        """
        Test verification of a valid JWT token in legacy HS256 mode.
        Ensures backward compatibility while we migrate to ES256.
        """
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        token = self.test_create_valid_jwt_token_hs256()
        payload = test_auth.verify_token(token)

        assert payload["sub"] == self.test_user_id
        assert payload["aud"] == "authenticated"

    def test_verify_token_from_jwt_helpers(self):
        """
        Test verification of a JWT token created by jwt_helpers.
        This exercises the test code path with HS256 symmetric keys.
        """
        # Import the jwt_helpers module
        from tests.jwt_helpers import create_test_jwt

        # Create a token using HS256 (how tests create tokens)
        token = create_test_jwt(self.test_user_id)

        # For testing, create auth instance with the test secret
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        payload = test_auth.verify_token(token)

        assert payload["sub"] == self.test_user_id
        assert payload["aud"] == "authenticated"

    def test_verify_expired_token(self):
        """Test that expired tokens are rejected."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        # Create token that's already expired
        payload = {
            "sub": self.test_user_id,
            "aud": "authenticated",
            "iss": f"{self.mock_supabase_url}/auth/v1",
            "exp": 0,  # Expired
        }
        token = jwt.encode(payload, self.mock_jwt_secret, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            test_auth.verify_token(token)

        assert exc_info.value.status_code == 401
        # JWT may raise "expired" or "invalid token" depending on how it handles exp=0
        detail = str(exc_info.value.detail).lower()
        assert "expired" in detail or "invalid" in detail

    def test_verify_invalid_signature(self):
        """Test that tokens with invalid signature are rejected."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        # Create token with wrong secret
        payload = {
            "sub": self.test_user_id,
            "aud": "authenticated",
            "iss": f"{self.mock_supabase_url}/auth/v1",
            "exp": 9999999999,
        }
        token = jwt.encode(payload, "wrong_secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            test_auth.verify_token(token)

        assert exc_info.value.status_code == 401
        assert "invalid" in str(exc_info.value.detail).lower()

    def test_missing_token(self):
        """Test that missing tokens are rejected."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        with pytest.raises(HTTPException) as exc_info:
            test_auth.verify_token("")

        assert exc_info.value.status_code == 401
        assert "missing" in str(exc_info.value.detail).lower()

    def test_get_user_id(self):
        """Test extracting user_id from valid token."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        token = self.test_create_valid_jwt_token_hs256()
        user_id = test_auth.get_user_id(token)

        assert user_id == self.test_user_id

    def test_bearer_prefix_handling(self):
        """Test that 'Bearer ' prefix is properly handled."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        token = self.test_create_valid_jwt_token_hs256()
        token_with_bearer = f"Bearer {token}"

        # Should work both with and without Bearer prefix
        payload1 = test_auth.verify_token(token)
        payload2 = test_auth.verify_token(token_with_bearer)

        assert payload1["sub"] == payload2["sub"]

    def test_is_authenticated_as_user(self):
        """Test checking if token belongs to authenticated user."""
        # Create auth instance in legacy mode
        test_auth = SupabaseAuth(
            jwt_secret=self.mock_jwt_secret,
            supabase_url=self.mock_supabase_url
        )

        token = self.test_create_valid_jwt_token_hs256()
        is_authenticated = test_auth.is_authenticated_as_user(token)

        assert is_authenticated is True

    def test_production_mode_no_jwt_secret(self):
        """
        Test that production mode (ES256) doesn't require jwt_secret.
        Verifies SUPABASE_JWT_SECRET can be removed from config.
        """
        # Create auth instance without jwt_secret (production mode)
        # Temporarily clear TEST_MODE to ensure we're in production mode
        import os
        old_test_mode = os.environ.get("TEST_MODE")
        try:
            os.environ["TEST_MODE"] = "false"
            test_auth = SupabaseAuth(
                supabase_url=self.mock_supabase_url
                # No jwt_secret provided
            )

            # Should not have legacy mode forced
            assert not test_auth._force_legacy_hmac
            # JWKS client should be lazy (None until first use)
            assert test_auth._jwks_client is None
        finally:
            # Restore TEST_MODE
            if old_test_mode is not None:
                os.environ["TEST_MODE"] = old_test_mode
            elif "TEST_MODE" in os.environ:
                del os.environ["TEST_MODE"]
