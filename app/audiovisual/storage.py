"""
Supabase Storage and local cache fallback for audiovisual assets (Bloque D).
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from typing import Any
import uuid

from app.audiovisual.config import AV_STORAGE_BUCKET
from app.config import settings

_VALID_PATH_REGEX = re.compile(r"^[A-Za-z0-9_./-]+$")

MIME_TO_EXT: dict[str, str] = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "text/plain": "txt",
    "application/json": "json",
}

_storage_client: Any = None


def _resolve_extension(mime: str) -> str:
    """Normalize mime type to file extension without leading dot."""
    cleaned = mime.strip().lower()
    if cleaned in MIME_TO_EXT:
        return MIME_TO_EXT[cleaned]
    guessed = mimetypes.guess_extension(cleaned)
    if guessed:
        return guessed.lstrip(".")
    return "bin"


def _get_storage_supabase_client() -> Any:
    """Creates Supabase client for storage operations (same pattern as scripts.py)."""
    supabase_url = settings.supabase_url
    supabase_key = settings.supabase_key
    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials not configured")
    try:
        from supabase import create_client
        return create_client(supabase_url, supabase_key)
    except (ImportError, RuntimeError):
        raise RuntimeError("Failed to connect to Supabase")


def _get_storage_client() -> Any:
    """Returns Supabase client or None if not configured/available."""
    global _storage_client
    if _storage_client is None:
        try:
            _storage_client = _get_storage_supabase_client()
        except RuntimeError:
            return None
    return _storage_client


def upload_bytes(
    session_token: str,
    idea_id: str,
    scene_n: int | None,
    job_id: str,
    data: bytes,
    mime: str = "video/mp4",
) -> str:
    """
    Upload binary asset bytes to storage.

    Storage path format: {token_hash}/{idea_id}/{scene_n or 'video'}/{job_id}.{ext}
    Uses sha256[:16] of session_token so clear-text tokens never leak into storage paths.
    """
    ext = _resolve_extension(mime)
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    scene_str = str(scene_n) if scene_n is not None else "video"
    storage_path = f"{token_hash}/{idea_id}/{scene_str}/{job_id}.{ext}"

    client = _get_storage_client()
    if client is not None:
        try:
            client.storage.from_(AV_STORAGE_BUCKET).upload(
                storage_path,
                data,
                {"content-type": mime, "upsert": "true"},
            )
            return storage_path
        except Exception as e:
            raise RuntimeError(f"Failed to upload to Supabase storage: {e}") from e
    else:
        # Fallback local file cache for tests
        local_dir = os.path.join(
            "cache", "storage", AV_STORAGE_BUCKET, token_hash, idea_id, scene_str
        )
        os.makedirs(local_dir, exist_ok=True)
        local_file = os.path.join(local_dir, f"{job_id}.{ext}")
        with open(local_file, "wb") as f:
            f.write(data)
        return storage_path


def signed_url(storage_path: str, ttl: int = 3600) -> str:
    """
    Generate a signed URL for a stored asset path.

    Falls back to a deterministic mock signed URL when Supabase is not available.
    """
    client = _get_storage_client()
    if client is not None:
        try:
            res = client.storage.from_(AV_STORAGE_BUCKET).create_signed_url(storage_path, ttl)
            if isinstance(res, dict):
                return res.get("signedURL") or res.get("signedUrl") or str(res)
            return str(res)
        except Exception as e:
            raise RuntimeError(f"Failed to create signed URL from Supabase: {e}") from e
    else:
        return f"https://local-storage.test/{AV_STORAGE_BUCKET}/{storage_path}?ttl={ttl}&token=mock_signed"


def create_signed_upload_url(
    session_token: str,
    idea_id: str,
    scene_n: int,
    ext: str = "webm",
) -> dict[str, str]:
    """
    Creates a signed upload URL for an A-roll take.

    Storage path format: {token_hash}/{idea_id}/{scene_n}/{take_id}.{ext}
    Returns a dict with:
      - storage_path: full path inside brand-assets bucket
      - signed_upload_url: direct upload URL
      - token: signature token for uploadToSignedUrl
    """
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    clean_ext = _resolve_extension(ext) if "/" in ext else ext.lstrip(".")
    if not clean_ext:
        clean_ext = "webm"
    take_id = f"take_{uuid.uuid4().hex[:12]}"
    storage_path = f"{token_hash}/{idea_id}/{scene_n}/{take_id}.{clean_ext}"

    client = _get_storage_client()
    if client is not None:
        try:
            res = client.storage.from_(AV_STORAGE_BUCKET).create_signed_upload_url(storage_path)
            signed_url_val = res.get("signed_url") or res.get("signedUrl") or ""
            token_val = res.get("token") or ""
            return {
                "storage_path": storage_path,
                "signed_upload_url": signed_url_val,
                "token": token_val,
            }
        except Exception as e:
            raise RuntimeError(f"Failed to create signed upload URL from Supabase: {e}") from e
    else:
        return {
            "storage_path": storage_path,
            "signed_upload_url": f"https://local-storage.test/{AV_STORAGE_BUCKET}/{storage_path}?token=mock_upload_token",
            "token": "mock_upload_token",
        }


def create_signed_upload_url_at(storage_path: str) -> dict[str, str]:
    """
    Creates a signed upload URL for a specific storage path.
    Validates storage_path format before creation.
    """
    if (
        ".." in storage_path
        or storage_path.startswith("/")
        or "\\" in storage_path
        or not _VALID_PATH_REGEX.match(storage_path)
        or not storage_path.endswith((".mp4", ".png", ".webm"))
    ):
        raise ValueError(f"Invalid storage path: {storage_path}")

    client = _get_storage_client()
    if client is not None:
        try:
            res = client.storage.from_(AV_STORAGE_BUCKET).create_signed_upload_url(storage_path)
            signed_url_val = res.get("signed_url") or res.get("signedUrl") or ""
            token_val = res.get("token") or ""
            return {
                "storage_path": storage_path,
                "signed_upload_url": signed_url_val,
                "token": token_val,
            }
        except Exception as e:
            raise RuntimeError(f"Failed to create signed upload URL from Supabase: {e}") from e
    else:
        return {
            "storage_path": storage_path,
            "signed_upload_url": f"https://local-storage.test/{AV_STORAGE_BUCKET}/{storage_path}?token=mock_upload_token",
            "token": "mock_upload_token",
        }


def editing_output_path(
    session_token: str,
    idea_id: str,
    job_id: str,
    attempt: int,
    ext: str = "mp4",
) -> str:
    """
    Generates deterministic output storage path for editing job attempts.
    Format: {token_hash}/{idea_id}/video/{job_id}_a{attempt}.{ext}
    """
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    clean_ext = ext.lstrip(".")
    return f"{token_hash}/{idea_id}/video/{job_id}_a{attempt}.{clean_ext}"


