"""
Supabase Auth Helper Module

Handles JWT token verification and user extraction from Supabase Auth.
Uses Supabase JWKS endpoints for ES256 asymmetric key verification.
"""
import os
import jwt
from typing import Optional, Dict
from fastapi import HTTPException, status
from app.config import settings


class SupabaseAuth:
    """
    Helper class for verifying Supabase JWT tokens and extracting user information.
    Uses PyJWKClient to fetch and verify against Supabase's public JWKS endpoints.
    """

    def __init__(self, jwt_secret: str = None, supabase_url: str = None, jwks_url: str = None):
        """
        Initialize SupabaseAuth with optional config override (for tests).

        Args:
            jwt_secret: Override JWT secret (DEPRECATED - kept for backward compatibility only)
            supabase_url: Override Supabase URL (for tests)
            jwks_url: Override JWKS URL (for tests - must use ES256 keys)
        """
        self.supabase_url = supabase_url or settings.supabase_url
        self.jwks_url = jwks_url or f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

        # For testing only: if jwt_secret is provided, force legacy HMAC mode
        # Otherwise, we'll check TEST_MODE dynamically in verify_token
        self._force_legacy_hmac = jwt_secret is not None
        self._legacy_secret = jwt_secret

        # Lazy initialization of JWKS client - only created when needed
        self._jwks_client = None

    def verify_token(self, token: str) -> Dict:
        """
        Verify a Supabase JWT token and return the decoded payload.

        Args:
            token: The JWT token string (usually from Authorization header)

        Returns:
            Decoded JWT payload containing user information

        Raises:
            HTTPException 401: If token is invalid, expired, or malformed
        """
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization token"
            )

        # Check TEST_MODE dynamically - this allows tests to set TEST_MODE
        # after the singleton is created
        in_test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
        use_legacy_hmac = self._force_legacy_hmac or in_test_mode
        legacy_secret = self._legacy_secret or os.environ.get("SUPABASE_JWT_SECRET", "") or "test_jwt_secret_for_testing_only_32bytes"

        # Remove "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

        try:
            if use_legacy_hmac:
                # Legacy mode for backward compatibility with tests
                # Uses HS256 symmetric signing
                payload = jwt.decode(
                    token,
                    legacy_secret,
                    algorithms=["HS256"],
                    audience=["authenticated"],
                    issuer=f"{self.supabase_url}/auth/v1"
                )
            else:
                # Production mode: use ES256 asymmetric key verification
                # Lazy-initialize JWKS client if needed
                if self._jwks_client is None:
                    from jwt import PyJWKClient
                    self._jwks_client = PyJWKClient(self.jwks_url)
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256"],
                    audience="authenticated",
                    issuer=f"{self.supabase_url}/auth/v1"
                )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )

    def get_user_id(self, token: str) -> str:
        """
        Extract user_id from a valid JWT token.

        Args:
            token: The JWT token string

        Returns:
            User ID (UUID string)

        Raises:
            HTTPException: If token is invalid or doesn't contain user_id
        """
        payload = self.verify_token(token)
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain user_id"
            )

        return user_id

    def get_audience(self, token: str) -> str:
        """
        Extract audience from a valid JWT token.

        Args:
            token: The JWT token string

        Returns:
            Audience string
        """
        payload = self.verify_token(token)
        return payload.get("aud", "")

    def is_authenticated_as_user(self, token: str) -> bool:
        """
        Check if the token belongs to an authenticated user (not anonymous).

        Args:
            token: The JWT token string

        Returns:
            True if authenticated, False otherwise
        """
        audience = self.get_audience(token)
        return audience == "authenticated"


# Singleton instance (production mode: uses ES256 via JWKS)
supabase_auth = SupabaseAuth()


def get_current_user_id(authorization: str) -> str:
    """
    FastAPI dependency to extract and verify user_id from Authorization header.

    Usage:
        @app.get("/api/endpoint")
        async def protected_endpoint(current_user_id: str = Depends(get_current_user_id)):
            ...

    Args:
        authorization: Authorization header value (injected by FastAPI)

    Returns:
        User ID (UUID string)

    Raises:
        HTTPException 401: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    return supabase_auth.get_user_id(authorization)
