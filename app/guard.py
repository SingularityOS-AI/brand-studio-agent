"""
Request Guard: Rate Limiting + Session Budget + Hard Cutoff.
Supports both in-memory and Supabase backends.
"""
import os
import time
import secrets
from typing import Optional, Dict
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


class Guard:
    """
    Singleton guard for rate limiting and session budget enforcement.
    Uses Supabase if configured, otherwise falls back to in-memory storage.
    """

    def __init__(self):
        # Supabase client (lazy-loaded when credentials are available)
        self._supabase = None
        self._use_supabase = False

        # Rate limiting: {ip: [(timestamp, ), ...]}
        # Always in-memory even with Supabase (60-second window, not worth DB trip)
        self._rate_limits: Dict[str, list] = {}

        # IP blocklist: {ip: blocked_until}
        # Always in-memory
        self._blocked_ips: Dict[str, float] = {}

        # Check for Supabase configuration
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
            self._sessions: Dict[str, dict] = {}

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

    def create_session(self, initial_credits: int = 500) -> str:
        """
        Creates a new session token and returns it.
        Token is stored in httpOnly cookie.
        """
        token = secrets.token_urlsafe(32)

        if self._use_supabase:
            # Store in Supabase
            self._supabase.table("sessions").insert({
                "token": token,
                "credits": initial_credits,
            }).execute()
        else:
            # Store in-memory
            self._sessions[token] = {
                "credits": initial_credits,
                "created_at": time.time(),
            }

        return token

    def get_session(self, token: str) -> Optional[Dict]:
        """Returns session data if valid, None otherwise."""
        if self._use_supabase:
            # Fetch from Supabase
            result = self._supabase.table("sessions").select("*").eq("token", token).execute()
            if result.data:
                return {"credits": result.data[0]["credits"]}
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


# Singleton instance
guard = Guard()
