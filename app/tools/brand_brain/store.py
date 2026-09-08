"""
Persistence layer for Brand Brain

Handles CRUD operations with Supabase `brand_brains` table.
Enforces citation invariant before writing to database (defense in depth).
"""

import os
from typing import Optional, Dict, List
from supabase import create_client, Client as SupabaseClient

from app.tools.brand_brain.models import BrandBrain, CitationInvariantError


def _get_supabase_client():
    """
    Lazy initialization of Supabase client.
    Only initialized when actually needed (allows mocking in tests).
    """
    # Allow test mode to skip initialization
    if os.getenv("TEST_MODE") == "true":
        return None
    
    # SUPABASE_KEY es el nombre que ya usan guard.py, render.yaml y .env.example.
    # Se acepta SUPABASE_SERVICE_ROLE_KEY como alias por si alguien lo declaro asi,
    # pero el canonico es SUPABASE_KEY: dos nombres para la misma credencial hacen
    # que el guard use Supabase y el cerebro reviente, que es lo que pasaba.
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL y SUPABASE_KEY deben estar configuradas para persistir "
            "el brand_brain. guard.py cae a memoria sin ellas, pero el cerebro no: "
            "sin base no hay nada que recordar al recargar."
        )

    return create_client(supabase_url, supabase_key)


# Global client (lazy)
_client: Optional[SupabaseClient] = None


def _get_client():
    """
    Get or create the Supabase client.
    In test mode, returns None to allow mocking.
    """
    global _client
    if _client is None and os.getenv("TEST_MODE") != "true":
        _client = _get_supabase_client()
    return _client


def save_brand_brain(session_token: str, brand_brain: BrandBrain) -> bool:
    """
    Save or update a brand brain in Supabase.
    
    ENFORCES INVARIANT: Validates all sections before writing to database.
    If any section has invalid citation, raises CitationInvariantError and
    does NOT write to database.

    Args:
        session_token: The session token (primary key)
        brand_brain: The BrandBrain object to save
    
    Returns:
        bool: True if successful
    
    Raises:
        CitationInvariantError: If any section has empty/invalid citation
    """
    # DEFENSE IN DEPTH: Validate before writing to database
    # Even though Section validates at construction, we check again here
    # in case someone constructs from raw JSON (e.g., from_dict bypasses validation)
    if not brand_brain.all_sections_valid():
        # Find and report the specific invalid sections
        validation = brand_brain.validate_all_sections()
        invalid_sections = [sid for sid, is_valid in validation.items() if not is_valid]
        
        raise CitationInvariantError(
            f"Cannot save BrandBrain: sections with invalid citations: {', '.join(invalid_sections)}. "
            f"Brand Brain cannot contain sections without citations (product invariant)."
        )
    
    # Convert to dict for storage
    brain_dict = brand_brain.to_dict()

    # Get client (may be None in test mode for mocking)
    client = _get_client()
    if client is None:
        # In test mode, let the caller handle this via mocking
        return False

    # Upsert (insert or replace)
    response = client.table("brand_brains").upsert(
        {
            "session_token": session_token,
            "sections": brain_dict["sections"],
            "formato": brain_dict["formato"]
        },
        on_conflict="session_token"
    ).execute()

    return len(response.data) > 0


def get_brand_brain(session_token: str) -> Optional[BrandBrain]:
    """
    Retrieve a brand brain by session token.
    
    NOTE: When loading from database, we recommend calling validate_invariant()
    on the returned BrandBrain to ensure data integrity, since from_dict()
    bypasses construction validation.

    Args:
        session_token: The session token

    Returns:
        BrandBrain if found, None otherwise
    """
    client = _get_client()
    if client is None:
        # In test mode, return None to allow mocking
        return None

    response = client.table("brand_brains").select("*").eq("session_token", session_token).execute()

    if not response.data:
        return None

    brain_data = response.data[0]
    sections = brain_data.get("sections", [])

    # Reconstruct BrandBrain
    brain_dict = {
        "sections": sections,
        "formato": brain_data.get("formato"),
        "created_at": brain_data.get("created_at"),
        "updated_at": brain_data.get("updated_at")
    }

    return BrandBrain.from_dict(brain_dict)


def delete_brand_brain(session_token: str) -> bool:
    """
    Delete a brand brain by session token.

    Args:
        session_token: The session token

    Returns:
        bool: True if deleted
    """
    client = _get_client()
    if client is None:
        # In test mode, return False
        return False

    response = client.table("brand_brains").delete().eq("session_token", session_token).execute()
    return len(response.data) > 0


def list_all_brand_brains() -> List[Dict]:
    """
    List all brand brains (for debugging/monitoring only).

    Returns:
        List of brain records with session_token and metadata
    """
    client = _get_client()
    if client is None:
        return []

    response = client.table("brand_brains").select("session_token, created_at, updated_at, formato").execute()
    return response.data


def validate_table_exists() -> bool:
    """
    Verify the brand_brains table exists in Supabase.

    Returns:
        bool: True if table exists
    """
    client = _get_client()
    if client is None:
        return False

    try:
        response = client.table("brand_brains").select("*").limit(1).execute()
        return True
    except Exception as e:
        return False
