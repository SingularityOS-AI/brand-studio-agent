"""
Request Guard: Rate Limiting + Session Budget + Hard Cutoff.
Supports both in-memory and Supabase backends with Google OAuth authentication.
"""
import os
import time
import secrets
from typing import Optional, Dict
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from app.config import settings


class Guard:
    """
    Singleton guard for rate limiting and session budget enforcement.
    Uses Supabase if configured, otherwise falls back to in-memory storage.
    Now supports Google OAuth JWT authentication.
    """

    def __init__(self):
        # CRITICAL: Respect TEST_MODE to prevent writing to production database during tests
        # conftest.py sets TEST_MODE=true before any app imports
        use_test_mode = os.getenv("TEST_MODE") == "true"

        # Supabase client (lazy-loaded when credentials are available)
        self._supabase = None
        self._use_supabase = False

        # Rate limiting: {ip: [(timestamp, ), ...]}
        # Always in-memory even with Supabase (60-second window, not worth DB trip)
        self._rate_limits: Dict[str, list] = {}

        # IP blocklist: {ip: blocked_until}
        # Always in-memory
        self._blocked_ips: Dict[str, float] = {}

        # Voice session tracking: {session_token: {"start_time": float, "last_deduct": float}}
        # For per-second credit deduction during voice sessions
        self._voice_sessions: Dict[str, dict] = {}

        # In TEST_MODE, force in-memory storage regardless of environment variables
        if use_test_mode:
            print("[guard] TEST_MODE=true: forzando almacenamiento en memoria (no se toca Supabase)")
            self._sessions: Dict[str, dict] = {}
            return

        # Check for Supabase configuration (only in production mode)
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if supabase_url and supabase_key:
            try:
                try:
                    # Try importing from supabase_py package
                    from supabase import create_client as supabase_create_client
                except ImportError:
                    try:
                        # Try importing from supabase package (newer versions)
                        from supabase import create_client as supabase_create_client
                    except ImportError:
                        # Fallback: supabase package not installed
                        raise ImportError("supabase package not installed")

                self._supabase = supabase_create_client(supabase_url, supabase_key)
                self._use_supabase = True
                print("[guard] usando Supabase para persistencia de sesiones")
            except (ImportError, Exception) as e:
                print(f"[guard] ERROR: No se pudo inicializar Supabase ({e}). Usando memoria.")

        if not self._use_supabase:
            print("[guard] sin Supabase: estado en memoria, se pierde al reiniciar")
            # In-memory session storage
            self._sessions: Dict[str, dict] ={}

    def check_rate_limit(self, ip: str, max_requests_per_minute: int = 30) -> None:
        """
        Raises HTTPException(429) if IP exceeds rate limit.
        Uses sliding window of 60 seconds (always in-memory).
        """
        now = time.time()

        # Check if IP is blocked
        if ip in self._blocked_ips:
            if now < self._blocked_ips[ip]:
                retry_after = int(self._blocked_ips[ip] - now)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "retry_after": retry_after,
                    },
                )
            else:
                # Block expired
                del self._blocked_ips[ip]

        # Clean old entries (older than 60 seconds)
        if ip in self._rate_limits:
            self._rate_limits[ip] = [
                ts for ts in self._rate_limits[ip] if now - ts < 60
            ]
        else:
            self._rate_limits[ip] = []

        # Check if limit exceeded
        if len(self._rate_limits[ip]) >= max_requests_per_minute:
            # Block for 1 minute
            self._blocked_ips[ip] = now + 60
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "retry_after": 60,
                },
            )

        # Record this request
        self._rate_limits[ip].append(now)

    def get_or_create_user_session(self, user_id: str) -> str:
        """
        Get existing session or create new one for authenticated user.
        Uses Supabase RPC function get_or_create_user_session if available.

        Args:
            user_id: User UUID from Supabase Auth

        Returns:
            Session token
        """
        if self._use_supabase:
            # Call Supabase RPC function to get or create session
            try:
                response = self._supabase.rpc(
                    "get_or_create_user_session",
                    params={"p_user_id": user_id}
                ).execute()
                
                if response.data:
                    return response.data
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to get or create user session"
                    )
            except HTTPException:
                raise
            except Exception as e:
                print(f"[guard] Error calling get_or_create_user_session: {e}")
                # Fallback to manual creation
                pass

        # Fallback: check for existing session (even if exhausted - let deduct_credits handle 402)
        if self._use_supabase:
            result = self._supabase.table("sessions") \
                .select("*") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            if result.data:
                return result.data[0]["token"]
        else:
            # In-memory fallback - return most recent session for this user
            for token, session in self._sessions.items():
                if session.get("user_id") == user_id:
                    return token

        # No existing session, create new one
        return self.create_user_session(user_id)

    def create_user_session(self, user_id: str, initial_credits: int = None) -> str:
        """
        Create a new session for an authenticated user.

        Args:
            user_id: User UUID from Supabase Auth
            initial_credits: Initial credit balance (defaults to settings.initial_session_credits)

        Returns:
            Session token
        """
        if initial_credits is None:
            initial_credits = settings.initial_session_credits

        token = secrets.token_urlsafe(32)

        if self._use_supabase:
            # Store in Supabase
            self._supabase.table("sessions").insert({
                "token": token,
                "credits": initial_credits,
                "user_id": user_id,
            }).execute()
        else:
            # Store in-memory
            self._sessions[token] = {
                "credits": initial_credits,
                "created_at": time.time(),
                "user_id": user_id,
            }

        return token

    def get_session(self, token: str) -> Optional[Dict]:
        """Returns session data if valid, None otherwise."""
        if self._use_supabase:
            # Fetch from Supabase
            result = self._supabase.table("sessions").select("*").eq("token", token).execute()
            if result.data:
                return {
                    "credits": result.data[0]["credits"],
                    "user_id": result.data[0].get("user_id"),
                }
            return None
        else:
            # Fetch from memory
            return self._sessions.get(token)

    def deduct_credits(self, token: str, amount: int = 1) -> int:
        """
        Deducts credits from session.
        Returns remaining credits.
        Raises HTTPException(402) if budget depleted.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        if self._use_supabase:
            # Atomic deduct using raw SQL
            response = self._supabase.rpc(
                "deduct_credits",
                params={
                    "p_token": token,
                    "p_amount": amount,
                }
            ).execute()

            if response.data is None:
                # No credits left or invalid token
                # Check if session exists to give proper error message
                session = self.get_session(token)
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid session token",
                    )
                else:
                    # Session exists but insufficient credits
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail={
                            "error": "Session budget exhausted",
                            "credits_remaining": session["credits"],
                            "payment_url": "https://example.com/upgrade",
                        },
                    )

            return response.data
        else:
            # In-memory deduct (not atomic across processes, but OK for single-process dev)
            session = self._sessions.get(token)
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid session token",
                )

            if session["credits"] < amount:
                # Budget depleted
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "Session budget exhausted",
                        "credits_remaining": session["credits"],
                        "payment_url": "https://example.com/upgrade",
                    },
                )

            session["credits"] -= amount
            return session["credits"]

    def get_remaining_credits(self, token: str) -> Optional[int]:
        """Returns remaining credits for session, None if invalid."""
        session = self.get_session(token)
        if not session:
            return None
        return session["credits"]

    def invalidate_session(self, token: str) -> None:
        """Invalidates a session token."""
        if self._use_supabase:
            self._supabase.table("sessions").delete().eq("token", token).execute()
        else:
            if token in self._sessions:
                del self._sessions[token]

    # Voice session tracking methods

    def start_voice_session(self, session_token: str) -> None:
        """
        Track the start time of a voice session for per-second credit deduction.

        Args:
            session_token: Session token to track
        """
        self._voice_sessions[session_token] = {
            "start_time": time.time(),
            "last_deduct": time.time(),
        }

    def deduct_voice_credits(self, session_token: str, interval_seconds: int = 10) -> int:
        """
        Deduct credits for voice session based on elapsed time.

        Args:
            session_token: Session token to deduct from
            interval_seconds: Time interval in seconds to calculate deduction for

        Returns:
            Remaining credits

        Raises:
            HTTPException 402: If budget depleted
        """
        if session_token not in self._voice_sessions:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Voice session not tracked"
            )

        # Calculate credits to deduct: (credits/min / 60) * seconds
        credits_per_second = settings.voice_credits_per_minute / 60
        credits_to_deduct = int(credits_per_second * interval_seconds)
        
        # Minimum 1 credit if any time passed
        if credits_to_deduct == 0:
            credits_to_deduct = 1

        # Deduct credits
        remaining = self.deduct_credits(session_token, amount=credits_to_deduct)
        
        # Update last deduction time
        self._voice_sessions[session_token]["last_deduct"] = time.time()
        
        return remaining

    def end_voice_session(self, session_token: str) -> int:
        """
        Final deduction when voice session ends, based on exact elapsed time.

        Args:
            session_token: Session token to finalize

        Returns:
            Total remaining credits
        """
        if session_token not in self._voice_sessions:
            return self.get_remaining_credits(session_token)

        session_data = self._voice_sessions[session_token]
        elapsed_time = time.time() - session_data["last_deduct"]
        
        # Deduct remaining credits for partial interval
        if elapsed_time > 0:
            credits_per_second = settings.voice_credits_per_minute / 60
            credits_to_deduct = int(credits_per_second * elapsed_time)
            
            if credits_to_deduct > 0:
                try:
                    self.deduct_credits(session_token, amount=credits_to_deduct)
                except HTTPException as e:
                    if e.status_code == 402:
                        pass  # Already depleted
                    else:
                        raise

        # Remove from tracking
        del self._voice_sessions[session_token]
        
        return self.get_remaining_credits(session_token)


# Singleton instance
guard = Guard()
