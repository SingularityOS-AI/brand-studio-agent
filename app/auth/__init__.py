"""
Auth package for Brand Studio Agent.

Provides Supabase JWT verification and authentication utilities.
"""
from .supabase_auth import SupabaseAuth, supabase_auth, get_current_user_id

__all__ = ["SupabaseAuth", "supabase_auth", "get_current_user_id"]
