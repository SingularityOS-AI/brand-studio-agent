"""
Scripting engine (Piece 32 — Block C).

Generates, audits, and persists scripts from catalog ideas using Gemini.
Follows the same persistence pattern as app/catalog/ideas.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.catalog.ideas import CatalogIdea
from app.config import settings
from app.tools.brand_brain.models import BrandBrain
from app.tools.brand_brain.store import get_brand_brain

# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class ScriptStorageError(Exception):
    """
    Exception for Supabase read/write failures (same pattern as CatalogStorageError).

    Distinguishes "no script" (None, normal case) from "read/write failed".
    Endpoints convert this to 503 and NEVER charge credits on failure.
    """


class SceneRegenerationInProgressError(Exception):
    """
    Raised when a regeneration for the same (session_id, idea_id, scene_n)
    is already in flight.

    Audit finding (Block C concurrency, Pieza 43): firing the SAME scene's
    regeneration twice concurrently used to just queue behind the lock and
    charge credits twice for what the founder experienced as one click.
    This is checked and raised BEFORE the lock, before any Gemini call, and
    before any credit is charged -- the endpoint converts it to 409.
    """


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FrameZero(BaseModel):
    """
    FrameZero: what shows in the first frame before speaking.

    Required for stopping the scroll in less than 1 second.
    """
    visual: str = Field(..., description="What we see in the first frame")
    # PIEZA 43: removed an invented max_length=50 -- the SIGNED rule is <= 8
    # words (enforced below in model_post_init), not a character count. An
    # honest 8-word subtitle can easily run past 50 chars and this was
    # killing whole generations with a raw Pydantic error for text that was
    # actually within spec.
    on_screen_text: str = Field(..., description="Text overlay, max 8 words")
    why_it_stops_the_scroll: str = Field(..., description="Why this catches attention")

    def model_post_init(self, __context: Any):
        """Validate on-screen text max 8 words."""
        word_count = len(self.on_screen_text.split())
        if word_count > 8:
            raise ValueError(f"FrameZero on-screen text must be at most 8 words, got {word_count}")


class Scene(BaseModel):
    """
    Single scene in the script (3-7 seconds).

    Follows ScriptOS structure:
    - phase: which part of the funnel (hook, lock_in, body_1, rehook, body_2, close_cta)
    - spoken_text: what the founder says (natural prose, not reading)
    - shot: camera angle (e.g., "medium shot", "close-up", "POV")
    - b_roll: what overlays the speaker (optional, +rep scene-specific footage in shot)
    - on_screen_text: subtitle, max 8 words
    - acting_note: how to say it (e.g., "lean forward", "pause before this")
    - sound: background mood or SFX (e.g., "upbeat", "suspenseful", "silence")
    - start_s, end_s: timing (seconds)

    BLUEPRINT FIELDS (Pieza 39) - for Block D (audiovisual generation):
    - asset_type: what kind of visual the scene needs (a_roll, stock, ai_image, ai_video, motion_graphic)
    - stock_query: search query for Pexels/Pixabay (IN ENGLISH)
    - visual_prompt: generation prompt for AI image/video (IN ENGLISH)
    """
    n: int = Field(..., description="Scene number (1-indexed)")
    start_s: float = Field(..., ge=0, description="Start time in seconds (ESTIMATED)")
    end_s: float = Field(..., gt=0, description="End time in seconds (ESTIMATED)")
    phase: Literal["hook", "lock_in", "body_1", "rehook", "body_2", "close_cta"] = Field(
        ..., description="Funnel phase"
    )
    spoken_text: str = Field(..., description="What the founder says (natural prose)")
    shot: str = Field(..., description="Camera angle")
    b_roll: str | None = Field(None, description="B-roll overlay")
    # PIEZA 43: same invented max_length=50 removed -- see FrameZero above.
    # The signed rule is <= 8 words, already enforced in model_post_init.
    on_screen_text: str = Field(..., description="Subtitle, max 8 words")
    acting_note: str = Field(..., description="Acting/direction note")
    sound: str = Field(..., description="Background mood or SFX")

    # BLUEPRINT fields (Pieza 39) - Block D consumption
    asset_type: Literal["a_roll", "stock", "ai_image", "ai_video", "motion_graphic"] = Field(
        default="a_roll",
        description="Visual asset type. a_roll = founder on camera; stock/ai_* = B-roll"
    )
    stock_query: str | None = Field(
        default=None,
        description="Search query for stock footage (Pexels/Pixabay). ALWAYS IN ENGLISH. None if a_roll."
    )
    visual_prompt: str | None = Field(
        default=None,
        description="Generation prompt for AI image/video. ALWAYS IN ENGLISH. None if a_roll."
    )
    suggested_asset_type: str | None = Field(
        default=None,
        description="Original asset type suggested by LLM when script was created"
    )

    @property
    def duration_s(self) -> float:
        """Scene duration in seconds."""
        return self.end_s - self.start_s

    def model_post_init(self, __context: Any):
        """
        Validate Scene constraints.

        Pieza 39: Duration validation removed. Timings are ESTIMATES for planning,
        not real measurements - actual duration only exists after recording.
        Only validate on-screen text (it's text, we can measure words).
        """
        # Validate on-screen text max 8 words - this is the only hard check,
        # because it's text and we can validate it before recording
        word_count = len(self.on_screen_text.split())
        if word_count > 8:
            raise ValueError(f"On-screen text must be at most 8 words, got {word_count}")


class AuditFinding(BaseModel):
    """
    Finding from automatic audit against the 12 hard rules.

    Each rule is a check WITHOUT LLM — deterministic validation.
    """
    rule: str = Field(..., description="Rule name/number (e.g., 'rule_1', 'rule_7')")
    status: Literal["pass", "fail"] = Field(..., description="Pass or fail")
    detail: str = Field(..., description="Human-readable explanation")
    critical: bool = Field(default=False, description="Whether this is a critical rule that blocks locking")


class Script(BaseModel):
    """
    Complete script with all metadata.

    Linked to a catalog idea via idea_id and session_token.
    One live script per idea — regenerate replaces the current one.

    BLUEPRINT FIELDS (Pieza 39) - for Block D (audiovisual generation):
    - music_prompt: search query for background music (mood + genre, IN ENGLISH)
    - recording_format: proposed recording format from CEO decision E3
    """
    # Persistence keys
    id: str | None = Field(None, description="UUID from database")
    session_id: str = Field(..., description="Session token")
    idea_id: str = Field(..., description="Catalog idea ID")

    # Content
    title: str = Field(..., description="Script title")
    angle: str = Field(..., description="Progressive angle narrows from general to specific")
    funnel_stage: Literal["tofu", "mofu", "bofu"] = Field(
        default="tofu", description="Funnel stage"
    )
    target_seconds: int = Field(..., ge=45, le=90, description="Target duration (45-90s)")

    frame_zero: FrameZero = Field(..., description="First frame visual")
    scenes: list[Scene] = Field(..., description="Scenes")

    audit: list[AuditFinding] = Field(default_factory=list, description="Audit findings")
    sources: list[str] = Field(default_factory=list, description="Citations from Brand Brain/demand")

    state: Literal["draft", "reviewed", "locked"] = Field(default="draft", description="Script state")

    # BLUEPRINT fields (Pieza 39) - Block D consumption
    music_prompt: str = Field(
        default="",
        description="Music search query for background (mood + genre). ALWAYS IN ENGLISH."
    )
    recording_format: Literal[
        "selfie_natural", "pov", "dramatization", "teleprompter_clean", "dynamic"
    ] = Field(
        default="selfie_natural",
        description="Proposed recording format per CEO decision E3"
    )

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any):
        """Validate script after initialization."""
        if len(self.scenes) < 5:
            raise ValueError("Script must have at least 5 scenes")

    @property
    def actual_seconds(self) -> float:
        """Actual duration based on last scene's end_s."""
        if not self.scenes:
            return 0.0
        return self.scenes[-1].end_s


# =============================================================================
# SUPABASE CLIENT (same pattern as ideas.py)
# =============================================================================

def _get_script_supabase_client():
    """Creates Supabase client for scripts table."""
    supabase_url = settings.supabase_url
    supabase_key = settings.supabase_key  # Service key for RLS bypass

    if not supabase_url or not supabase_key:
        raise RuntimeError("Supabase credentials not configured")

    try:
        from supabase import create_client
        return create_client(supabase_url, supabase_key)
    except (ImportError, RuntimeError):
        # Network/certificate errors in tests -> fall back to local cache
        raise RuntimeError("Failed to connect to Supabase")


# Global client (lazy)
_script_client = None


def _get_script_client():
    """
    Returns Supabase client for scripts, or None if not configured.

    Tests mock this to force local file cache.
    Same pattern as _get_catalog_client() in ideas.py.
    """
    global _script_client
    if _script_client is None:
        try:
            _script_client = _get_script_supabase_client()
        except RuntimeError:
            return None
    return _script_client


def _script_to_row(script: Script) -> dict[str, Any]:
    """Serialize Script to Supabase row format."""
    return {
        "session_token": script.session_id,
        "idea_id": script.idea_id,
        "status": script.state,
        "data": {
            "id": script.id,
            "title": script.title,
            "angle": script.angle,
            "funnel_stage": script.funnel_stage,
            "target_seconds": script.target_seconds,
            "frame_zero": script.frame_zero.model_dump(mode="json"),
            "scenes": [scene.model_dump(mode="json") for scene in script.scenes],
            "audit": [finding.model_dump(mode="json") for finding in script.audit],
            "sources": script.sources,
            "timestamp": script.timestamp.isoformat(),
            # BLUEPRINT fields (Pieza 39)
            "music_prompt": script.music_prompt,
            "recording_format": script.recording_format,
        },
    }


def _row_to_script(row: dict[str, Any]) -> Script | None:
    """Reconstruct Script from Supabase row or local cache."""
    data = row.get("data") or {}
    try:
        frame_zero = FrameZero(**data.get("frame_zero", {}))
        raw_scenes = data.get("scenes", [])
        cleaned_scenes = []
        for s_data in raw_scenes:
            s_dict = dict(s_data) if isinstance(s_data, dict) else s_data
            if isinstance(s_dict, dict):
                cleaned_vp = _clean_optional_text(s_dict.get("visual_prompt"))
                s_dict["visual_prompt"] = cleaned_vp

                cleaned_sq = _clean_optional_text(s_dict.get("stock_query"))
                s_dict["stock_query"] = (
                    _sanitize_stock_query(cleaned_sq) if cleaned_sq is not None else None
                )

                if s_dict.get("shot") in _RECORDING_FORMATS:
                    s_dict["shot"] = "Medium shot"
            cleaned_scenes.append(Scene(**s_dict))
        scenes = cleaned_scenes
        audit = [AuditFinding(**finding_data) for finding_data in data.get("audit", [])]

        timestamp_str = data.get("timestamp")
        timestamp = (
            datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if timestamp_str
            else datetime.now(timezone.utc)
        )

        return Script(
            id=data.get("id") or row.get("id"),
            session_id=row.get("session_token"),
            idea_id=row.get("idea_id"),
            title=data.get("title", ""),
            angle=data.get("angle", ""),
            funnel_stage=data.get("funnel_stage", "tofu"),
            target_seconds=data.get("target_seconds", 60),
            frame_zero=frame_zero,
            scenes=scenes,
            audit=audit,
            sources=data.get("sources", []),
            state=row.get("status", "draft"),
            # BLUEPRINT fields (Pieza 39) - TRAP: defaults for backward compatibility
            music_prompt=data.get("music_prompt", "") if "music_prompt" in data else "",
            recording_format=data.get("recording_format", "selfie_natural") if "recording_format" in data else "selfie_natural",
            timestamp=timestamp,
        )
    except (ValueError, KeyError, TypeError) as e:
        print(f"Error reconstructing script: {e}")
        return None


def _check_script(session_id: str, idea_id: str) -> Script | None:
    """
    Fetch script from Supabase or local cache.

    Auditing and audit findings are recomputed on load to ensure freshness.

    Args:
        session_id: Session token
        idea_id: Catalog idea ID

    Returns:
        Script if exists, None otherwise
    """
    client = _get_script_client()
    if client is not None:
        try:
            response = (
                client.table("scripts")
                .select("*")
                .eq("session_token", session_id)
                .eq("idea_id", idea_id)
                .execute()
            )
            if not response.data:
                return None
            script = _row_to_script(response.data[0])
        except Exception as e:
            print(f"Error reading script from Supabase: {e}")
            raise ScriptStorageError(f"Failed to read script from Supabase: {e}") from e
    else:
        # Fallback: local file cache
        cache_dir = os.path.join("cache", "script", session_id)
        cache_file = os.path.join(cache_dir, f"{idea_id}.json")

        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                row = json.load(f)
            script = _row_to_script(row)
        except (json.JSONDecodeError, OSError, KeyError, ValueError) as e:
            print(f"Error reading script local cache: {e}")
            return None

    # Recompute audit to ensure freshness after load
    if script is not None:
        script.audit = audit_script(script)

    return script


def get_script_states_by_session(session_id: str) -> dict[str, str]:
    """
    Fetch a mapping of idea_id -> script state (draft|reviewed|locked)
    for all scripts in the given session with a SINGLE query/read.

    PIEZA 45: Avoids N queries per catalog idea.
    """
    states: dict[str, str] = {}
    client = _get_script_client()
    if client is not None:
        try:
            response = (
                client.table("scripts")
                .select("idea_id, status")
                .eq("session_token", session_id)
                .execute()
            )
            if response.data:
                for row in response.data:
                    idea_id = row.get("idea_id")
                    status = row.get("status")
                    if idea_id and status:
                        states[idea_id] = status
            return states
        except Exception as e:
            print(f"Error reading script states from Supabase: {e}")
            raise ScriptStorageError(f"Failed to read script states from Supabase: {e}") from e

    # Fallback: local file cache
    cache_dir = os.path.join("cache", "script", session_id)
    if os.path.exists(cache_dir):
        try:
            for fname in os.listdir(cache_dir):
                if fname.endswith(".json"):
                    cache_file = os.path.join(cache_dir, fname)
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            row = json.load(f)
                            idea_id = row.get("idea_id") or fname[:-5]
                            status = row.get("status")
                            if not status and isinstance(row.get("data"), dict):
                                status = row["data"].get("state")
                            if idea_id and status:
                                states[idea_id] = status
                    except Exception:
                        pass
        except OSError as e:
            print(f"Error reading script cache directory: {e}")
            raise ScriptStorageError(f"Failed to read script cache directory: {e}") from e

    return states


def _save_script(script: Script) -> None:
    """
    Persist script to Supabase or local cache (upsert).

    Args:
        script: Script to persist
    """
    client = _get_script_client()
    if client is not None:
        try:
            client.table("scripts").upsert(_script_to_row(script), on_conflict="session_token,idea_id").execute()
            return
        except Exception as e:
            print(f"Error saving script to Supabase: {e}")
            raise ScriptStorageError(f"Failed to save script to Supabase: {e}") from e

    # Fallback: local file cache
    cache_dir = os.path.join("cache", "script", script.session_id)
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{script.idea_id}.json")

    try:
        row = _script_to_row(script)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving script local cache: {e}")
        raise ScriptStorageError(f"Failed to save script local cache: {e}") from e


# =============================================================================
# HELPER: _build_brand_context (reused from ideas.py)
# =============================================================================

def _build_brand_context(brand_brain: BrandBrain) -> str:
    """
    Build brand context string from Brand Brain sections.

    Reused from app/catalog/ideas.py to avoid duplication.
    """
    sections_text = []
    for section in brand_brain.sections:
        if section.status == "confirmado":
            sections_text.append(f"{section.label}: {section.content}")

    return "\n\n".join(sections_text) if sections_text else "No confirmed brand data available."


def _derive_script_kind(idea: CatalogIdea) -> str:
    """
    Derive script kind from idea's subcategory and master category.

    Pieza 35: Brandy chooses the script kind based on Brand Soul, not user selection.
    The idea's classification (master_category + subcategory) is the signal.

    Mapping from existing MASTER_CATEGORIES and their subcategories.
    QA Pieza 35: este docstring decia que producia "testimony" y que
    autoridad_tecnica daba "comparison" -- ninguno de los dos sale del mapeo real.
    Es el patron que ya mordio tres veces en este repo (el nombre dice una cosa,
    el codigo hace otra), asi que aqui va lo que el codigo DE VERDAD devuelve:
    - autoridad_tecnica      -> tutorial
    - validacion_resultados  -> case_study
    - posicionamiento        -> promo (Mito vs Realidad) | story (el resto)
    - narrativa_fundadora    -> story
    - discusion_industria    -> comparison (Pregunta de debate) | story

    Defaults to "tutorial" for unrecognized subcategories.
    """
    # Subcategory to script kind mapping
    SUBCATEGORY_TO_KIND = {
        "Autoridad Técnica e Instrucción": {
            "Top N/Listículo técnico": "tutorial",
            "Anatomía de un proceso": "tutorial",
            "Dato contraintuitivo con fuente": "tutorial",
        },
        "Validación de Resultados e Impacto": {
            "Antes/Después con métricas": "case_study",
            "Desglose de caso de éxito": "case_study",
            "Costo de la inacción": "case_study",
        },
        "Posicionamiento y Tesis de Mercado": {
            "Mito vs Realidad": "promo",
            "Tesis Contrarian": "story",
            "Structured Yapping": "story",
        },
        "Narrativa Fundadora y Origen": {
            "Historia personal con lección": "story",
            "Vulnerabilidad operativa": "story",
            "Detrás de cámaras": "story",
        },
        "Discusión y Co-creación de Industria": {
            "Pregunta de debate": "comparison",
            "Reacción a regulación/tendencia": "story",
        },
    }

    # Try to find by subcategory first
    for category_name, subcats in SUBCATEGORY_TO_KIND.items():
        if idea.subcategory in subcats:
            return subcats[idea.subcategory]

    # Fallback to master category-based defaults
    MASTER_CATEGORY_DEFAULTS = {
        "autoridad_tecnica": "tutorial",
        "validacion_resultados": "case_study",
        "posicionamiento_narrativa": "story",
        "narrativa_fundadora": "story",
        "discusion_industria": "comparison",
    }

    return MASTER_CATEGORY_DEFAULTS.get(idea.master_category, "tutorial")


# =============================================================================
# AUDIT RULES (14 deterministic rules, no LLM)
# =============================================================================
# CRITICAL RULES (must pass for locking):
# - rule_1:  Duration 45-90 seconds (estimated)
# - rule_3:  Has all 6 phases
# - rule_4:  Exactly 2 key points (body_1 and body_2)
# - rule_5:  FrameZero stops scroll (why_it_stops_the_scroll not empty)
# - rule_7:  No "not X, it's Y" patterns
# - rule_8:  No AI counterexamples
# - rule_9:  All numbers have citations (has sources)
# - rule_12: Has CTA (close_cta phase exists)
# - rule_14: Single language (all detectable scenes use same language)
#
# NON-CRITICAL RULES (informational, don't block locking):
# - rule_2:  Hook acting note is concrete
# - rule_6:  Has rehook before second point
# - rule_10: On-screen text ≤ 8 words
# - rule_11: Max one rhetorical question and one list of three
# - rule_13: No AI blacklist words

AUDIT_RULES: list[dict[str, Any]] = [
    {
        "rule": "rule_1",
        "name": "Duration: 45-90 seconds (estimated)",
        "check": lambda s: 45 <= s.actual_seconds <= 90,
        "fail_msg": lambda s: f"Duration is {s.actual_seconds:.1f}s estimated (must be 45-90s)",
        "critical": True,
    },
    {
        "rule": "rule_2",
        "name": "Hook acting note is concrete (not generic)",
        "check": lambda s: _check_hook_acting_note_concrete(s),
        "fail_msg": lambda s: "Hook acting note is too generic (min ~6 words, specific direction)",
        "critical": False,
    },
    {
        "rule": "rule_3",
        "name": "Has all 6 phases",
        "check": lambda s: {
            "hook", "lock_in", "body_1", "rehook", "body_2", "close_cta"
        }.issubset({sc.phase for sc in s.scenes}),
        "fail_msg": lambda s: "Missing one or more required phases",
        "critical": True,
    },
    {
        "rule": "rule_4",
        "name": "Exactly 2 key points (body_1 and body_2)",
        "check": lambda s: (
            len([sc for sc in s.scenes if sc.phase == "body_1"]) == 1
            and len([sc for sc in s.scenes if sc.phase == "body_2"]) == 1
        ),
        "fail_msg": lambda s: "Must have exactly one body_1 and one body_2 scene",
        "critical": True,
    },
    {
        "rule": "rule_5",
        "name": "FrameZero stops scroll",
        "check": lambda s: bool(s.frame_zero.why_it_stops_the_scroll.strip()),
        "fail_msg": lambda s: "FrameZero must explain why it stops the scroll",
        "critical": True,
    },
    {
        "rule": "rule_6",
        "name": "Has rehook before second point",
        "check": lambda s: any(sc.phase == "rehook" for sc in s.scenes),
        "fail_msg": lambda s: "Missing rehook before second key point",
        "critical": False,
    },
    {
        "rule": "rule_7",
        "name": "No 'not X, it's Y' patterns",
        "check": lambda s: _check_no_not_x_its_y(s),
        "fail_msg": lambda s: "Contains forbidden 'not X, it's Y' pattern",
        "critical": True,
    },
    {
        "rule": "rule_8",
        "name": "No AI counterexamples",
        "check": lambda s: _check_no_ai_counterexamples(s),
        "fail_msg": lambda s: "Contains AI counterexample pattern",
        "critical": True,
    },
    {
        "rule": "rule_9",
        "name": "All numbers have citations",
        "check": lambda s: len(s.sources) > 0,
        "fail_msg": lambda s: "Script must cite at least one source",
        "critical": True,
    },
    {
        "rule": "rule_10",
        "name": "On-screen text ≤ 8 words",
        "check": lambda s: all(
            len(sc.on_screen_text.split()) <= 8
            for sc in s.scenes
        ),
        "fail_msg": lambda s: "On-screen text exceeds 8 words in some scene",
        "critical": False,
    },
    {
        "rule": "rule_11",
        "name": "Max one rhetorical question and one list of three",
        "check": lambda s: _check_rhetorical_devices(s),
        "fail_msg": lambda s: _get_rhetorical_fail_message(s),
        "critical": False,
    },
    {
        "rule": "rule_12",
        "name": "Has CTA",
        "check": lambda s: any(sc.phase == "close_cta" for sc in s.scenes),
        "fail_msg": lambda s: "Missing CTA (close_cta) scene",
        "critical": True,
    },
    {
        "rule": "rule_13",
        "name": "No AI blacklist words",
        "check": lambda s: _check_no_ai_blacklist(s),
        "fail_msg": lambda s: _get_blacklist_fail_message(s),
        "critical": False,
    },
    {
        "rule": "rule_14",
        "name": "Single language",
        "check": lambda s: _check_single_language(s),
        "fail_msg": lambda s: _get_single_language_fail_msg(s),
        "critical": True,
    },
]


# =============================================================================
# AUDIT RULE HELPER FUNCTIONS
# =============================================================================

def _check_no_not_x_its_y(script: Script) -> bool:
    """Check for forbidden 'not X, it's Y' patterns."""
    forbidden_patterns = [
        " is not ",
        " it's not ",
        "it's not ",
        "not just a ",
        "not just an ",
        "not just ",
        "not only a ",
        "not only an ",
        "not only ",
        "no se trata de ",
        "no es solo ",
        "no es sólo ",
        "no solo ",
        "no sólo ",
    ]
    for scene in script.scenes:
        text_lower = scene.spoken_text.lower()
        for pattern in forbidden_patterns:
            if pattern in text_lower:
                return False
    return True



def _check_no_ai_counterexamples(script: Script) -> bool:
    """Check for AI counterexample patterns."""
    for scene in script.scenes:
        text_lower = scene.spoken_text.lower()
        # Check for "unlike" + "ai" pattern
        if "unlike" in text_lower and "ai" in text_lower:
            return False
        # Check for "not like" pattern
        if "not like" in text_lower:
            return False
        # Check for other comparison patterns
        if any(phrase in text_lower for phrase in ["other ai", "most ai", "typical ai"]):
            return False
    return True


# AI word blacklist from humanization guide
# Sources: 01_INVESTIGACION/Humanización de Guiones IA B2B.md, línea 184
AI_BLACKLIST = frozenset([
    "delve", "delves",
    "crucial",
    "tapestry",
    "landscape",
    "ever-evolving", "ever evolving",
    "unlock the potential", "unlocking the potential",
    "revolutionary",
    "vital",
    "in conclusion",
    "in summary",
    "discover how",
    "optimize", "optimise",
])


def _check_no_ai_blacklist(script: Script) -> bool:
    """Check for AI blacklist words in spoken_text (case-insensitive)."""
    for scene in script.scenes:
        text_lower = scene.spoken_text.lower()
        for word in AI_BLACKLIST:
            if word in text_lower:
                return False
    return True


def _get_blacklist_fail_message(script: Script) -> str:
    """Get specific fail message for blacklist violations."""
    violations = []
    for scene in script.scenes:
        text_lower = scene.spoken_text.lower()
        for word in AI_BLACKLIST:
            if word in text_lower:
                # Find the actual case in the text
                start_idx = text_lower.find(word)
                actual_word = scene.spoken_text[start_idx:start_idx + len(word)]
                violations.append(f"Scene {scene.n}: '{actual_word}'")
                break
    if violations:
        return f"AI blacklist words found: {'; '.join(violations[:3])}"
    return "AI blacklist words found"


def _detect_language(text: str) -> str | None:
    """
    Deterministically detect whether text is Spanish ('es') or English ('en').
    Returns None if text is too short (< 3 total functional word/accent matches)
    or if neither language has at least double the matches of the other.
    """
    if not text or not text.strip():
        return None

    text_lower = text.lower()
    accent_count = sum(1 for c in text_lower if c in "áéíóúñ¿¡")

    import re
    words = re.findall(r'[a-záéíóúñ]+', text_lower)

    es_words = {
        "el", "la", "los", "las", "de", "del", "que", "y", "en",
        "un", "una", "es", "por", "para", "con", "su", "se", "lo",
        "al", "más", "pero", "como", "esta", "este", "tu"
    }
    en_words = {
        "the", "and", "to", "of", "is", "that", "for", "with",
        "your", "you", "in", "it", "this", "are", "on", "but",
        "what", "how", "our"
    }

    es_count = sum(1 for w in words if w in es_words) + accent_count
    en_count = sum(1 for w in words if w in en_words)

    total_matches = es_count + en_count
    if total_matches < 3:
        return None

    if es_count >= 2 * en_count and es_count > 0:
        return "es"
    if en_count >= 2 * es_count and en_count > 0:
        return "en"

    return None


def _script_language(scenes: list[Scene], exclude_n: int | None = None) -> str:
    """
    Determine the dominant language ("es" or "en") of the script scenes.
    Optionally excludes scene `exclude_n` (e.g. the scene being regenerated).
    Returns "en" if there is no clear majority or no detectable scenes.
    """
    detected = [
        _detect_language(sc.spoken_text)
        for sc in scenes
        if exclude_n is None or sc.n != exclude_n
    ]
    valid = [lang for lang in detected if lang is not None]
    if not valid:
        return "en"

    es_count = valid.count("es")
    en_count = valid.count("en")

    if es_count > en_count:
        return "es"
    if en_count > es_count:
        return "en"

    return "en"


def _check_single_language(script: Script) -> bool:
    """Rule 14: Check that all scenes with detectable language use the same language."""
    detected_langs = {
        _detect_language(sc.spoken_text)
        for sc in script.scenes
    } - {None}
    return len(detected_langs) <= 1


def _get_single_language_fail_msg(script: Script) -> str:
    """Get fail message for rule_14 detailing which scenes use which language."""
    lang_scenes: dict[str, list[int]] = {}
    for sc in script.scenes:
        lang = _detect_language(sc.spoken_text)
        if lang is not None:
            lang_scenes.setdefault(lang, []).append(sc.n)

    if len(lang_scenes) <= 1:
        return "Script uses multiple languages across scenes"

    # Sort by number of scenes ascending so minority language comes first
    sorted_langs = sorted(
        lang_scenes.keys(),
        key=lambda lang_code: (len(lang_scenes[lang_code]), lang_code)
    )
    minority_lang = sorted_langs[0]
    majority_lang = sorted_langs[1]

    minority_nums = lang_scenes[minority_lang]
    minority_name = "Spanish" if minority_lang == "es" else "English"
    majority_name = "Spanish" if majority_lang == "es" else "English"

    nums_str = ", ".join(str(n) for n in minority_nums)
    scene_word = "Scene" if len(minority_nums) == 1 else "Scenes"
    verb = "is" if len(minority_nums) == 1 else "are"

    return f"{scene_word} {nums_str} {verb} in {minority_name}; the rest in {majority_name}. Iterate or edit them so the whole script uses one language."


def _check_hook_acting_note_concrete(script: Script) -> bool:
    """
    Check if hook's acting_note is concrete (not generic).
    
    Heuristic: Must be at least ~6 words (concrete direction has rhythm,
    emphasis, pauses, gaze - generic is "say it confidently").
    """
    for scene in script.scenes:
        if scene.phase == "hook":
            word_count = len(scene.acting_note.split())
            # Concrete notes have specific direction (min ~6 words)
            # Generic is "say it confidently" (~3 words)
            return word_count >= 6
    return True  # No hook scene found, pass (other rules catch this)


def _check_rhetorical_devices(script: Script) -> bool:
    """
    Check rhetorical devices: max one rhetorical question and one list of three.
    
    HEURISTIC (documented limitations):
    - Rhetorical questions: sentences ending with "?"
    - Lists of three: patterns like "A, B and C" or "A, B, or C"
    
    Cases this heuristic misses:
    - Indirect questions: "People wonder why they fail" (no "?")
    - Lists with different conjunctions: "A, B, plus C"
    - Lists in separate sentences: "We have speed. We have power. We have reliability."
    """
    import re
    
    rhetorical_count = 0
    list_of_three_count = 0
    
    for scene in script.scenes:
        text = scene.spoken_text
        
        # Count questions (sentences ending with ?)
        # Split by sentence boundaries and count ?
        sentences = re.split(r'[.!?]+', text)
        for sentence in sentences:
            if sentence.strip().endswith('?'):
                rhetorical_count += 1
        # Also count ? directly in case splitting missed something
        rhetorical_count = max(rhetorical_count, text.count('?'))
        
        # Count lists of three: patterns like "word, word and word" or "word, word, and word"
        # Oxford comma: "A, B, and C" or regular: "A, B and C"
        list_three_pattern = r'\w+[^,]{0,20},\s*\w+[^,]{0,20},?(\s+and|\s+or)\s+\w+'
        matches = re.findall(list_three_pattern, text, re.IGNORECASE)
        list_of_three_count += len(matches)
    
    # Max one rhetorical question AND max one list of three
    return rhetorical_count <= 1 and list_of_three_count <= 1


def _get_rhetorical_fail_message(script: Script) -> str:
    """Get specific fail message for rhetorical device violations."""
    import re
    
    rhetorical_count = 0
    list_of_three_count = 0
    
    for scene in script.scenes:
        text = scene.spoken_text
        rhetorical_count += text.count('?')
        list_three_pattern = r'\w+[^,]{0,20},\s*\w+[^,]{0,20},?(\s+and|\s+or)\s+\w+'
        list_of_three_count += len(re.findall(list_three_pattern, text, re.IGNORECASE))
    
    issues = []
    if rhetorical_count > 1:
        issues.append(f"{rhetorical_count} rhetorical questions (max 1)")
    if list_of_three_count > 1:
        issues.append(f"{list_of_three_count} lists of three (max 1)")
    
    if issues:
        return f"Rhetorical devices exceeded: {', '.join(issues)}"
    return "Rhetorical devices exceeded"


def audit_script(script: Script) -> list[AuditFinding]:
    """
    Run all 13 audit rules on a script (deterministic, no LLM).

    Args:
        script: Script to audit

    Returns:
        List of AuditFinding objects
    """
    findings = []

    for rule_def in AUDIT_RULES:
        rule = rule_def["rule"]
        check_fn = rule_def["check"]
        fail_msg_fn = rule_def["fail_msg"]
        critical = rule_def.get("critical", False)

        try:
            if check_fn(script):
                findings.append(AuditFinding(rule=rule, status="pass", detail="OK", critical=critical))
            else:
                findings.append(AuditFinding(rule=rule, status="fail", detail=fail_msg_fn(script), critical=critical))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            findings.append(AuditFinding(rule=rule, status="fail", detail=f"Error checking: {e}", critical=critical))

    return findings


# =============================================================================
# SCRIPT GENERATION
# =============================================================================

CREDITS_COST_GENERATE = 10
CREDITS_COST_REGENERATE_SCENE = 2

# Duration ESTIMATE formula (150 words/minute = 2.5 words/sec), shared by
# generation, regeneration, AND manual edits (Pieza 43) so timing is
# computed the exact same way everywhere a scene's spoken_text changes.
WORDS_PER_SECOND = 2.5
MIN_SCENE_DURATION = 1.0  # Minimum 1 second per scene, so nothing shows as 0s


def _estimate_scene_duration(spoken_text: str) -> float:
    """
    Estimate a scene's duration from its spoken_text word count.

    This is a planning ESTIMATE, not a measurement -- actual duration only
    exists after recording. Used by generate_script, regenerate_scene, AND
    update_scene_text (Pieza 43: manual edits used to leave stale timing
    that only a paid regeneration could fix).
    """
    words = len((spoken_text or "").split())
    return max(MIN_SCENE_DURATION, words / WORDS_PER_SECOND)


def _reflow_following_scenes(scenes: list[Scene], changed_idx: int) -> None:
    """
    Shift start_s/end_s of every scene AFTER changed_idx (0-indexed) so they
    stay back-to-back with the scene at changed_idx -- no gaps, no overlaps.
    Each later scene KEEPS its own duration, only its position shifts.
    """
    for i in range(changed_idx + 1, len(scenes)):
        prev_scene = scenes[i - 1]
        curr_scene = scenes[i]
        duration = curr_scene.end_s - curr_scene.start_s
        curr_scene.start_s = prev_scene.end_s
        curr_scene.end_s = curr_scene.start_s + duration


def _recompute_scene_timing_and_reflow(scenes: list[Scene], changed_idx: int) -> None:
    """
    Recompute scenes[changed_idx]'s end_s from its (already-updated)
    spoken_text using the SAME estimate formula as generation, then reflow
    every later scene to keep the whole timeline consistent.

    Pieza 43 (audit finding): update_scene_text used to change spoken_text
    without touching start_s/end_s at all, so a manual edit could silently
    desync the timeline from the words actually being said -- rule_1
    (duration) could then only be "fixed" by paying for a regeneration.
    """
    changed = scenes[changed_idx]
    changed.end_s = changed.start_s + _estimate_scene_duration(changed.spoken_text)
    _reflow_following_scenes(scenes, changed_idx)


# Gemini sometimes confuses the SCENE-level `b_roll` overlay field with the
# BLUEPRINT `asset_type` enum and returns "b_roll" (or a close variant)
# where a valid asset_type is expected. Since a b_roll-style scene is by
# definition NOT the founder on camera, "stock" is the closest safe valid
# value -- it still routes the scene to Block D as non-a_roll footage
# instead of failing validation outright. Anything not in this map is left
# untouched so validation still catches genuinely unknown values loudly.
_ASSET_TYPE_NORMALIZATION: dict[str, str] = {
    "b_roll": "stock",
    "b-roll": "stock",
    "broll": "stock",
}


_RECORDING_FORMATS = {
    "selfie_natural",
    "pov",
    "dramatization",
    "teleprompter_clean",
    "dynamic",
}


def _clean_optional_text(value: Any) -> str | None:
    """
    Clean optional text fields (stock_query, visual_prompt, b_roll).

    Returns None if value is None, not a str, empty after strip(),
    or if strip().lower() is in {"null", "none", "n/a", "na", "undefined"}.
    Otherwise returns stripped string.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"null", "none", "n/a", "na", "undefined"}:
        return None
    return cleaned


def _sanitize_stock_query(text: Any) -> str | None:
    """
    Sanitize stock search query to 2-5 clean English words for Pexels.

    - Splits in lines, discards empty lines and lines ending with ':'
    - Takes first remaining line
    - Removes initial list numbering (1., 1), -, *), asterisks, #, quotes
    - Keeps only letters, digits, spaces, and hyphens
    - Collapses spaces and cuts to max 5 words
    - Returns None if nothing remains
    """
    if not isinstance(text, str):
        return None

    lines = text.splitlines()
    valid_line = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.endswith(":"):
            continue
        valid_line = stripped
        break

    if not valid_line:
        return None

    cleaned = re.sub(r"^(?:[\d]+[\.\)]|[-*])\s*", "", valid_line)
    cleaned = re.sub(r"[^\w\s-]", "", cleaned).replace("_", "")

    words = cleaned.split()
    if not words:
        return None

    words = words[:5]
    result = " ".join(words)
    return result if result else None


def _get_scene_attr(scene: Any, attr: str) -> str | None:
    if isinstance(scene, dict):
        val = scene.get(attr)
    else:
        val = getattr(scene, attr, None)
    return val if isinstance(val, str) else None


def _fallback_stock_query(scene: Any) -> str:
    """
    Deterministically derive a stock search query fallback from scene fields (Pieza 66).
    Tries b_roll, then on_screen_text, then spoken_text (words with len > 2, max 4 words).
    Passes through _sanitize_stock_query. Returns 'business office' if empty.
    """
    for field in ("b_roll", "on_screen_text", "spoken_text"):
        raw_val = _get_scene_attr(scene, field)
        if raw_val:
            words = [w for w in raw_val.split() if len(w) > 2][:4]
            if words:
                candidate = " ".join(words)
                sanitized = _sanitize_stock_query(candidate)
                if sanitized:
                    return sanitized
    return "business office"


def _fallback_visual_prompt(scene: Any) -> str:
    """
    Deterministically derive a visual prompt fallback from scene fields (Pieza 66).
    base = cleaned stock_query, or b_roll, or on_screen_text, or first 12 words of spoken_text.
    Returns f"{base}, cinematic, vertical 9:16, clean composition, no text".
    """
    sq = _clean_optional_text(_get_scene_attr(scene, "stock_query"))
    br = _clean_optional_text(_get_scene_attr(scene, "b_roll"))
    ost = _clean_optional_text(_get_scene_attr(scene, "on_screen_text"))
    st_raw = _get_scene_attr(scene, "spoken_text")

    base = sq or br or ost
    if not base and st_raw:
        words = st_raw.split()[:12]
        if words:
            base = _clean_optional_text(" ".join(words))

    if not base:
        base = "cinematic scene"

    return f"{base}, cinematic, vertical 9:16, clean composition, no text"


def _clean_visual_prompt_text(raw_val: Any) -> str | None:
    """Clean visual_prompt string, discarding a first line preamble ending in ':' if present."""
    cleaned = _clean_optional_text(raw_val)
    if not cleaned:
        return None
    lines = cleaned.splitlines()
    if lines and lines[0].strip().endswith(":"):
        lines = lines[1:]
    clean_str = "\n".join(lines).strip()
    paragraphs = [p.strip() for p in clean_str.split("\n\n") if p.strip()]
    first_para = paragraphs[0] if paragraphs else clean_str
    result = first_para.strip('"').strip("'").strip()
    if not result:
        return None
    return result[:400]


async def _fill_missing_asset_prompts(
    script: Any,
    only_n: set[int] | None = None,
) -> bool:
    """
    Ensure every target scene in script has non-None, non-null stock_query and visual_prompt (Pieza 66).
    If any field is missing, calls Gemini once grouped across missing scenes.
    Fills ONLY missing fields; never overwrites existing clean values.
    Falls back to deterministic fallback helpers if Gemini call fails or omits values.
    Never raises an exception. Returns True if any scene was modified.
    """
    if not script or not getattr(script, "scenes", None):
        return False

    scenes_needing_fill: list[Any] = []
    for scene in script.scenes:
        if only_n is not None and scene.n not in only_n:
            continue
        sq_clean = _clean_optional_text(getattr(scene, "stock_query", None))
        vp_clean = _clean_optional_text(getattr(scene, "visual_prompt", None))
        if sq_clean is None or vp_clean is None:
            scenes_needing_fill.append(scene)

    if not scenes_needing_fill:
        return False

    llm_results_by_n: dict[int, dict[str, Any]] = {}

    try:
        import asyncio
        from vertexai.generative_models import GenerativeModel
        from app.config import settings

        angle = getattr(script, "angle", "") or ""
        scenes_payload = []
        for s in scenes_needing_fill:
            scenes_payload.append({
                "n": s.n,
                "phase": getattr(s, "phase", "") or "",
                "asset_type": getattr(s, "asset_type", "") or "",
                "spoken_text": getattr(s, "spoken_text", "") or "",
                "on_screen_text": getattr(s, "on_screen_text", "") or "",
                "b_roll": getattr(s, "b_roll", "") or "",
            })

        prompt = f"""Generate missing asset stock search queries and visual prompts for short-form video scenes.

Script angle: {angle}

Scenes needing prompts:
{json.dumps(scenes_payload, indent=2)}

INSTRUCTIONS:
For EACH scene listed, provide:
1. "stock_query": 2 to 5 concrete filmable search words IN ENGLISH for Pexels stock video search.
2. "visual_prompt": A single visual prompt description IN ENGLISH, max 40 words, vertical 9:16 composition, no text/letters/logos, no identifiable real faces of people.

Output MUST ALWAYS BE IN ENGLISH, regardless of the language of spoken_text or on_screen_text.

Return ONLY a JSON object with this exact structure:
{{
  "scenes": [
    {{
      "n": 1,
      "stock_query": "concrete english search words",
      "visual_prompt": "english visual prompt description..."
    }}
  ]
}}
"""

        model = GenerativeModel(settings.vertex_ai_model)
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config={
                    "temperature": 0.4,
                    "response_mime_type": "application/json",
                },
            ),
            timeout=20.0,
        )

        raw_text = (getattr(response, "text", "") or "").strip()
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict) and "scenes" in parsed and isinstance(parsed["scenes"], list):
            for item in parsed["scenes"]:
                if isinstance(item, dict) and "n" in item:
                    try:
                        n_int = int(item["n"])
                    except (ValueError, TypeError):
                        continue
                    llm_results_by_n[n_int] = {
                        "stock_query": item.get("stock_query"),
                        "visual_prompt": item.get("visual_prompt"),
                    }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[_fill_missing_asset_prompts] LLM call failed or timed out: {e}")

    changed = False

    for scene in scenes_needing_fill:
        sq_clean = _clean_optional_text(getattr(scene, "stock_query", None))
        vp_clean = _clean_optional_text(getattr(scene, "visual_prompt", None))

        llm_item = llm_results_by_n.get(scene.n, {})

        if sq_clean is None:
            new_sq = None
            if llm_item.get("stock_query"):
                new_sq = _sanitize_stock_query(llm_item["stock_query"])
            if not new_sq:
                new_sq = _fallback_stock_query(scene)
            scene.stock_query = new_sq
            changed = True

        if vp_clean is None:
            new_vp = None
            if llm_item.get("visual_prompt"):
                new_vp = _clean_visual_prompt_text(llm_item["visual_prompt"])
            if not new_vp:
                new_vp = _fallback_visual_prompt(scene)
            scene.visual_prompt = new_vp
            changed = True

    return changed


def _normalize_asset_type(value: Any) -> Any:
    """Normalize obvious, documented model slips in asset_type before validation."""
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_")
        if key in _ASSET_TYPE_NORMALIZATION:
            return _ASSET_TYPE_NORMALIZATION[key]
    return value


def _normalize_b_roll(value: Any) -> str | None:
    """
    Normalize b_roll field from LLM response before Scene validation (Pieza 48).

    - None / "" -> None
    - str -> _clean_optional_text(value)
    - dict -> primer valor de texto útil entre description, text, visual, query;
              si no hay, los valores de texto unidos con " — "
    - list -> elementos de texto unidos con "; "
    - cualquier otro tipo -> str(value)
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_optional_text(value)
    if isinstance(value, dict):
        for key in ("description", "text", "visual", "query"):
            val = value.get(key)
            if isinstance(val, str):
                cleaned = _clean_optional_text(val)
                if cleaned:
                    return cleaned
        text_vals = [
            cleaned
            for v in value.values()
            if isinstance(v, str) and (cleaned := _clean_optional_text(v))
        ]
        if text_vals:
            return " — ".join(text_vals)
        return None
    if isinstance(value, list):
        items = [
            cleaned
            for x in value
            if isinstance(x, str) and (cleaned := _clean_optional_text(x))
        ]
        if items:
            return "; ".join(items)
        return None
    return _clean_optional_text(str(value))


def _summarize_validation_error(e: Exception) -> str:
    """
    Turn a pydantic ValidationError into one short, readable line instead of
    its default multi-line dump -- a founder should see "on_screen_text:
    must be at most 8 words, got 10", not a raw Pydantic trace.
    """
    if isinstance(e, ValidationError):
        try:
            parts = []
            for err in e.errors():
                loc = ".".join(str(p) for p in err.get("loc", ())) or "value"
                parts.append(f"{loc}: {err.get('msg', 'invalid value')}")
            if parts:
                return "; ".join(parts)
        except Exception:
            pass
    return str(e)


def _build_validated_scene(
    scene_data: dict[str, Any],
    *,
    n: int,
    phase: str | None,
    start_s: float,
    end_s: float,
    fallback: Scene | None = None,
) -> Scene:
    """
    Build a Scene from raw (LLM) data with FULL validation, BEFORE anything
    is mutated or saved.

    Audit finding (Pieza 43, critical): Pydantic v2 does NOT validate on
    attribute assignment by default. The old regenerate_scene() path did
    `target_scene.spoken_text = new_scene_data["spoken_text"]` directly on
    the already-loaded, already-valid Scene -- so an invalid Gemini response
    (e.g. on_screen_text over 8 words, or an unrecognized asset_type) sat on
    disk looking fine until the NEXT load, when `_row_to_script` hit the
    same validation error and returned None. The founder saw "no script
    found", paid again to regenerate, and the upsert wiped the script and
    every prior iteration. Going through `Scene.model_validate` here forces
    validation to happen NOW, on a value nothing has touched yet -- a bad
    response fails loud immediately, with nothing saved and nothing charged.

    `fallback` (existing scene, used for regeneration) supplies blueprint
    field values (asset_type/stock_query/visual_prompt) the model chose not
    to return, matching the original "preserve if not returned" behavior.

    Raises:
        ValueError: with a clean, one-line summary if the data is invalid.
    """
    asset_type_raw = scene_data.get(
        "asset_type", fallback.asset_type if fallback else "a_roll"
    )
    asset_type = _normalize_asset_type(asset_type_raw)
    b_roll = _normalize_b_roll(scene_data.get("b_roll"))

    raw_stock = scene_data.get("stock_query")
    stock_query = _clean_optional_text(raw_stock)
    if stock_query is not None:
        stock_query = _sanitize_stock_query(stock_query)
    if stock_query is None and fallback and fallback.stock_query is not None:
        stock_query = _clean_optional_text(fallback.stock_query)
        if stock_query is not None:
            stock_query = _sanitize_stock_query(stock_query)

    raw_visual = scene_data.get("visual_prompt")
    visual_prompt = _clean_optional_text(raw_visual)
    if visual_prompt is None and fallback and fallback.visual_prompt is not None:
        visual_prompt = _clean_optional_text(fallback.visual_prompt)

    raw_shot = scene_data.get("shot")
    shot = raw_shot
    if isinstance(raw_shot, str):
        normalized_shot = raw_shot.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized_shot in _RECORDING_FORMATS:
            if fallback and fallback.shot:
                shot = fallback.shot
            else:
                shot = "Medium shot"

    payload = {
        "n": n,
        "start_s": start_s,
        "end_s": end_s,
        "phase": phase,
        "spoken_text": scene_data.get("spoken_text"),
        "shot": shot,
        "b_roll": b_roll,
        "on_screen_text": scene_data.get("on_screen_text"),
        "acting_note": scene_data.get("acting_note"),
        "sound": scene_data.get("sound"),
        "asset_type": asset_type,
        "stock_query": stock_query,
        "visual_prompt": visual_prompt,
    }
    try:
        return Scene.model_validate(payload)
    except ValidationError as e:
        raise ValueError(
            f"Model returned invalid data for scene {n}: {_summarize_validation_error(e)}"
        ) from e


# =============================================================================
# CONCURRENCY: per-(session_id, idea_id) locking (Pieza 43)
# =============================================================================
# ASSUMPTION (documented per spec, must be revisited if this ever changes):
# this app runs as a SINGLE Render instance/process. An in-process dict of
# asyncio.Lock objects only serializes mutations WITHIN one process -- it
# does NOT protect against multiple instances or worker processes. If this
# app is ever scaled horizontally, this must move to a shared mechanism
# (DB-level lock/row version, Redis, etc.) or lost updates return.
#
# Locks are created lazily and never evicted -- one Lock object per idea
# that has ever had a mutation attempted stays in memory for the life of
# the process. That is a bounded, tiny amount of memory for this app's
# scale and is not worth the complexity of eviction here.

_script_locks: dict[tuple[str, str], asyncio.Lock] = {}

# In-flight regenerations, keyed by (session_id, idea_id, scene_n). Checked
# and updated with no `await` in between, so it is race-free under asyncio's
# cooperative scheduling without needing its own lock.
_in_flight_regenerations: set[tuple[str, str, int]] = set()


def _get_script_lock(session_id: str, idea_id: str) -> asyncio.Lock:
    """Return the (lazily created) lock that serializes mutations for this script."""
    key = (session_id, idea_id)
    lock = _script_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _script_locks[key] = lock
    return lock


def _build_generation_prompt(
    brand_context: str,
    idea: CatalogIdea,
    interview_transcript: str,
    source_mode: Literal["brand_brain", "raw_footage"],
    script_kind: str,
) -> str:
    """
    Build prompt for script generation with Gemini.

    Prompt is in English as per spec.

    Pieza 35: script_kind parameter now included in the prompt and actually used.
    """
    footage_instruction = ""
    if source_mode == "raw_footage":
        footage_instruction = """
IMPORTANT: Describe EXISTING footage in 'shot' and 'acting_note' — do NOT invent new takes.
The founder already has recorded footage; your job is to reconstruct the script from what they actually said.
"""

    prompt = f"""You are an expert short-form video scriptwriter for B2B content.

Your task: Generate a 45-90 second script from an idea and interview transcript.

PARAMETERS:
- Target duration: 45-90 seconds (estimated at 2.5 words per second)
- Tone: Professional, authoritative yet conversational
- Structure: 6 phases (hook, lock_in, body_1, rehook, body_2, close_cta)
- Word budget (CRITICAL): Total spoken_text across all scenes MUST be strictly between 130 and 200 words (approx 52-80 seconds at 2.5 words/sec). Budget by phase:
  * hook: 10-15 words
  * lock_in: 15-20 words
  * body_1: 35-50 words
  * rehook: 12-18 words
  * body_2: 35-50 words
  * close_cta: 20-30 words
  Count words carefully: scripts below 113 words will fail the 45-second duration rule.
- Script kind: {script_kind} (use this as a guide for style and approach)
- Progressive angle: Open very general, then narrow progressively toward CTA

BRAND CONTEXT:
{brand_context}

CATALOG IDEA:
- Title: {idea.title}
- Master category: {idea.master_category}
- Subcategory: {idea.subcategory}
- Demand signal: {idea.demand_signal}

INTERVIEW TRANSCRIPT:
{interview_transcript}

{footage_instruction}

STYLE REQUIREMENTS:
- FrameZero: Must have a visual that stops the scroll in <1 second
- On-screen text: Maximum 8 words per scene
- Spoken text: Natural prose — founder interprets, doesn't read word-for-word
- Rehooks: Use phrases like "stay with me", "and here's why", "but that's not all"
- FORBIDDEN: "not X, it's Y" patterns (e.g., "it's not just a tool, it's a partner"). Prohibited variations include: "It's not about the number of hands. It's about the speed...", "This isn't X. This is Y.", "Not X — Y." (even if split across two sentences or separated by dashes/periods).
- FORBIDDEN: AI counterexamples (e.g., "unlike other AI tools")
- CTA: Must match funnel stage (tofu: awareness, mofu: consideration, bofu: decision)

LANGUAGE CONSISTENCY (CRITICAL):
- All spoken_text, on_screen_text, and acting_note MUST be in English unless the Brand Context explicitly specifies another target publishing language. If Brand Context indicates Spanish, write entirely in Spanish. NEVER mix languages within a script (e.g., an English body with a Spanish closing CTA is strictly forbidden).

HUMANIZATION REQUIREMENTS (CRITICAL):
1. WORDS BLACKLIST — NEVER use these in spoken_text: delve, crucial, tapestry, landscape, ever-evolving, unlock the potential, revolutionary, vital, in conclusion, in summary, discover how, optimize.
2. BURSTINESS — Alternate long sentences with micro-phrases of 2-4 words. Uniform rhythm signals AI generation.
3. RHETORICAL DEVICES — Forbidden by default. Maximum ONE rhetorical question or "list of three" per script if absolutely necessary.
4. NO INVENTED DATA — If a claim needs a number not in Brand Context or interview transcript, DO NOT MAKE IT UP. Reformulate without the number (as question or general frame).

RECORDING FORMAT:
Based on the idea's master_category and subcategory, PROPOSE one of these 5 formats:
- "selfie_natural": Authentic founder selfie style, casual lighting
- "pov": Point-of-view shots showing the user's perspective
- "dramatization": Acted out scenarios with clear staging
- "teleprompter_clean": Clean background, founder looking at teleprompter
- "dynamic": Fast cuts, multiple angles, energetic movement

The shot and acting_note MUST match the chosen format.

AUDIOVISUAL BLUEPRINT (for automated Block D):
For EACH scene, regardless of asset_type (including a_roll):
- asset_type: Choose from "a_roll" (founder on camera), "stock" (stock footage), "ai_image" (AI generated image), "ai_video" (AI generated video), "motion_graphic" (motion graphic overlay)
- stock_query: 2 to 5 concrete filmable search words IN ENGLISH for Pexels (e.g. "doctor video call tablet clinic"), no lists or explanation
- visual_prompt: Generation prompt IN ENGLISH (max 40 words, vertical 9:16, no text/letters/logos, no identifiable real faces of people)

For SCRIPT-LEVEL:
- music_prompt: Search query IN ENGLISH for background music (mood + genre, e.g., "upbeat corporate electronic" or "cinematic suspense piano")
- recording_format: One of the 5 formats above

NOTE ON A-ROLL AND B-ROLL MIX (CRITICAL):
This is a personal brand product. A successful video is a dynamic mix of the founder speaking to camera (A-roll) and supporting visuals (B-roll):
- hook and close_cta: Almost always "a_roll" (the founder must look directly into camera to hook and close).
- B-roll requirement (≥2 escenas no a_roll): At least 2 scenes MUST be B-roll (non-a_roll scenes: "stock" preferred, with concrete filmable stock_query in English, e.g., "doctor video call tablet clinic", not abstract).
- AI assets budget (≤1 ai_video): Maximum 1 scene "ai_video" (it is the most expensive asset). Use "ai_image" or "motion_graphic" only when stock cannot show it (a metric, a chart, a diagram).
- Spoken text: Scenes with B-roll STILL have spoken_text (the founder's voiceover continues speaking over the B-roll visuals).
DO NOT mark all scenes as "a_roll". Mix founder takes with B-roll to create a broadcast-quality video.

HOOK REQUIREMENTS:
The hook's acting_note MUST be SPECIFIC: include rhythm, energy level, which word to emphasize, where to breathe/pause/cut, and where to look. NO generic "say it confidently" — give actionable direction the founder can execute.

OUTPUT: Valid JSON with this exact schema:
{{
  "title": "script title",
  "angle": "progressive angle description",
  "target_seconds": 60,
  "recording_format": "one of the 5 formats above",
  "music_prompt": "search query in ENGLISH for background music",
  "frame_zero": {{
    "visual": "what we see",
    "on_screen_text": "max 8 words",
    "why_it_stops_the_scroll": "why it catches attention"
  }},
  "scenes": [
    {{
      "phase": "hook|lock_in|body_1|rehook|body_2|close_cta",
      "spoken_text": "what the founder says",
      "shot": "camera angle",
      "b_roll": "plain text string describing the overlay, or null — never an object",
      "on_screen_text": "subtitle max 8 words",
      "acting_note": "specific direction: rhythm, emphasis, pauses, gaze",
      "sound": "mood or SFX",
      "asset_type": "a_roll|stock|ai_image|ai_video|motion_graphic",
      "stock_query": "2 to 5 concrete filmable search words in ENGLISH for Pexels, no lists or explanation",
      "visual_prompt": "generation prompt in ENGLISH (max 40 words, 9:16 vertical, no text/logos/real faces)"
    }}
  ],
  "sources": ["citation text from brand context or demand signal"]
}}

Total scenes should be 7-12. ALL queries and prompts must be IN ENGLISH. Return ONLY valid JSON.
"""
    return prompt


def _parse_and_build_script(
    session_id: str,
    idea_id: str,
    response_text: str,
) -> tuple[Script, dict[str, Any]]:
    """Parse JSON response from Gemini, validate scenes/FrameZero, and build audited Script."""
    try:
        script_data = json.loads(response_text)
    except json.JSONDecodeError:
        import re
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            script_data = json.loads(json_match.group(1))
        else:
            raise ValueError("Failed to parse JSON response from Gemini")

    try:
        frame_zero = FrameZero.model_validate(script_data.get("frame_zero", {}))
    except ValidationError as e:
        raise ValueError(
            f"Model returned invalid frame_zero: {_summarize_validation_error(e)}"
        ) from e

    scenes_data = script_data.get("scenes", [])
    current_time = 0.0
    scenes = []
    for idx, scene_data in enumerate(scenes_data, start=1):
        phase = scene_data.get("phase")
        estimated_duration = _estimate_scene_duration(scene_data.get("spoken_text", ""))

        start_s = current_time
        end_s = start_s + estimated_duration
        current_time = end_s

        scene = _build_validated_scene(
            scene_data,
            n=idx,
            phase=phase,
            start_s=start_s,
            end_s=end_s,
        )
        scenes.append(scene)

    script = Script(
        session_id=session_id,
        idea_id=idea_id,
        title=script_data.get("title", ""),
        angle=script_data.get("angle", ""),
        funnel_stage=script_data.get("funnel_stage", "tofu"),
        target_seconds=script_data.get("target_seconds", 60),
        frame_zero=frame_zero,
        scenes=scenes,
        sources=script_data.get("sources", []),
        music_prompt=script_data.get("music_prompt", ""),
        recording_format=script_data.get("recording_format", "selfie_natural"),
    )
    script.audit = audit_script(script)
    return script, script_data


def _format_critical_audit_failures(script: Script, failed_critical: list[AuditFinding]) -> list[str]:
    """Format exact failure descriptions for single LLM revision attempt."""
    messages = []
    total_words = sum(len((sc.spoken_text or "").split()) for sc in script.scenes)
    forbidden_patterns = [
        " is not ", " it's not ", "it's not ", "not just a ", "not just an ",
        "not just ", "not only a ", "not only an ", "not only ",
    ]
    for f in failed_critical:
        if f.rule == "rule_1":
            messages.append(
                f"- {f.rule} ({f.detail}): Your draft has {total_words} spoken words "
                f"(~{script.actual_seconds:.1f}s estimated duration). "
                "It MUST have strictly between 130 and 200 spoken words across all scenes (target 45-90 seconds)."
            )
        elif f.rule == "rule_7":
            bad_scenes = []
            for sc in script.scenes:
                tl = (sc.spoken_text or "").lower()
                for pat in forbidden_patterns:
                    if pat in tl:
                        bad_scenes.append(f"scene {sc.n} ({sc.phase}) contains '{pat.strip()}'")
                        break
            detail_str = f" Violations: {'; '.join(bad_scenes)}." if bad_scenes else ""
            messages.append(
                f"- {f.rule} ({f.detail}): Forbidden 'not X, it's Y' contrast pattern found.{detail_str} "
                "Prohibited examples include: 'it's not just a tool, it's a partner', "
                "'It's not about the number of hands. It's about the speed...', "
                "'This isn't X. This is Y.', 'Not X — Y.'"
            )
        else:
            messages.append(f"- {f.rule}: {f.detail}")
    return messages


def _build_retry_generation_prompt(
    base_prompt: str,
    previous_script_data: dict[str, Any],
    failure_messages: list[str],
) -> str:
    """Build the single-retry prompt providing the previous script and exact failures to fix."""
    failures_block = "\n".join(failure_messages)
    return f"""{base_prompt}

CRITICAL REVISION REQUIRED:
Your previous draft failed the following critical audit rules:
{failures_block}

PREVIOUS DRAFT:
{json.dumps(previous_script_data, indent=2)}

INSTRUCTIONS FOR REVISION:
Fix all the critical audit failures listed above while preserving the structure and brand tone.
- Total spoken_text across all scenes MUST be strictly between 130 and 200 words (45-90 seconds).
- Distribute word budget across phases: hook 10-15, lock_in 15-20, body_1 35-50, rehook 12-18, body_2 35-50, close_cta 20-30 words.
- Eliminate all forbidden contrast patterns ("not X, it's Y").
- Maintain strict language consistency (all English unless Brand Context specifies Spanish).
Return ONLY the complete corrected script as valid JSON adhering to the exact schema.
"""


def _build_validation_retry_prompt(
    base_prompt: str,
    previous_output: str,
    error_message: str,
) -> str:
    """Build retry prompt when the model's first attempt fails validation / JSON parsing (Pieza 48)."""
    return f"""{base_prompt}

CRITICAL REVISION REQUIRED:
your previous output was invalid: {error_message}. Return valid JSON matching the schema; b_roll must be a string or null.

PREVIOUS OUTPUT:
{previous_output}

INSTRUCTIONS FOR REVISION:
Fix the validation error above. Ensure the response is valid JSON matching the schema exactly; b_roll must be a plain text string or null, never an object.
Return ONLY valid JSON.
"""


async def generate_script(
    session_id: str,
    idea_id: str,
    interview_transcript: str,
    source_mode: Literal["brand_brain", "raw_footage"] = "brand_brain",
    idea_kind: str | None = None,
) -> Script:
    """
    Generate a new script using Gemini.

    Args:
        session_id: Session token
        idea_id: Catalog idea ID
        interview_transcript: Transcript of interview with Brandy
        source_mode: "brand_brain" (default) or "raw_footage"
        idea_kind: Optional kind override (e.g., "narrative", "tutorial")

    Returns:
        Generated Script object

    Raises:
        ValueError: If catalog idea not found or not approved
        ScriptStorageError: If persistence fails
    """
    # 1. Load Brand Brain
    brand_brain = get_brand_brain(session_id)
    if not brand_brain:
        raise ValueError("Brand Brain not found. Complete Brand Soul first.")

    # 2. Load catalog and find idea
    from app.catalog.ideas import _check_catalog_cache as load_catalog
    catalog = load_catalog(session_id)
    if not catalog:
        raise ValueError("No catalog found. Generate catalog first.")

    idea = next(
        (i for i in catalog.ideas if i.id == idea_id),
        None
    )
    if not idea:
        raise ValueError(f"Idea {idea_id} not found in catalog.")
    if idea.status != "approved":
        raise ValueError(f"Idea {idea_id} is not approved. Only approved ideas can be scripted.")

    # 3. Check if catalog is locked (spec requires this)
    if not catalog.catalog_locked:
        raise ValueError("Catalog must be locked (catalog_locked=True) before scripting.")

    # 4. Build context and prompt
    brand_context = _build_brand_context(brand_brain)

    # Pieza 35: derive script kind from idea if not provided as override
    final_idea_kind = idea_kind
    if final_idea_kind is None:
        final_idea_kind = _derive_script_kind(idea)

    prompt = _build_generation_prompt(brand_context, idea, interview_transcript, source_mode, final_idea_kind)

    # 5. Call Gemini
    from vertexai.generative_models import GenerativeModel

    model = GenerativeModel(settings.vertex_ai_model)
    response = await model.generate_content_async(
        prompt,
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        },
    )

    # 6. Parse and build Script object (Pieza 48: single retry covers validation errors too)
    validation_retried = False
    try:
        script, script_data = _parse_and_build_script(session_id, idea_id, response.text)
    except ValueError as e:
        validation_error_msg = str(e)
        retry_prompt = _build_validation_retry_prompt(
            prompt, getattr(response, "text", "") or "", validation_error_msg
        )
        retry_response = await model.generate_content_async(
            retry_prompt,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json",
            },
        )
        # If the retry also fails validation / json parsing, let ValueError propagate
        # to caller (0 credits charged, no third attempt).
        script, script_data = _parse_and_build_script(
            session_id, idea_id, retry_response.text
        )
        validation_retried = True

    # 7. Check critical audit rules
    critical_rules = {
        r["rule"] for r in AUDIT_RULES
        if r.get("critical", False)
    }
    failed_critical = [
        f for f in script.audit
        if f.status == "fail" and f.rule in critical_rules
    ]

    # 8. Single automatic retry if any critical rule fails (Pieza 45)
    # Only if we haven't already used our single retry on a validation error (Pieza 48)
    if failed_critical and not validation_retried:
        failure_messages = _format_critical_audit_failures(script, failed_critical)
        retry_prompt = _build_retry_generation_prompt(prompt, script_data, failure_messages)
        try:
            retry_response = await model.generate_content_async(
                retry_prompt,
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 8192,
                    "response_mime_type": "application/json",
                },
            )
            retry_script, _ = _parse_and_build_script(
                session_id, idea_id, retry_response.text
            )
            retry_failed_critical = [
                f for f in retry_script.audit
                if f.status == "fail" and f.rule in critical_rules
            ]
            if len(retry_failed_critical) < len(failed_critical):
                script = retry_script
        except Exception as e:
            print(f"[WARN] Script automatic retry failed: {e}. Retaining original draft.")

    # 9. Save and return
    await _fill_missing_asset_prompts(script)
    _save_script(script)
    return script


# =============================================================================
# SCENE REGENERATION
# =============================================================================

async def regenerate_scene(
    session_id: str,
    idea_id: str,
    scene_n: int,
    instruction: str,
) -> Script:
    """
    Regenerate a single scene based on instruction.

    Only changes the target scene; preserves all other scenes and timing.

    Args:
        session_id: Session token
        idea_id: Catalog idea ID
        scene_n: Scene number to regenerate (1-indexed)
        instruction: Brief instruction (e.g., "shorter", "more aggressive")

    Returns:
        Updated Script object

    Raises:
        ValueError: If script not found, locked, scene_n invalid, or the
            regenerated scene fails validation. In every ValueError case
            NOTHING is saved and NO credit should be charged (the caller in
            main.py only deducts credits after this returns successfully).
        SceneRegenerationInProgressError: If this exact scene is already
            being regenerated concurrently -- caller should surface this as
            409, not charge, and NOT retry automatically.
        ScriptStorageError: If persistence fails
    """
    lock_key = (session_id, idea_id)
    in_flight_key = (session_id, idea_id, scene_n)

    # Pieza 43 (concurrency fix): reject a duplicate in-flight regeneration
    # of the SAME scene immediately, before the lock, before any Gemini
    # call, before any credit is charged. Without this, a double-click or
    # retry would just queue behind the lock below and run twice, charging
    # CREDITS_COST_REGENERATE_SCENE twice for what the founder experienced
    # as one action.
    if in_flight_key in _in_flight_regenerations:
        raise SceneRegenerationInProgressError(
            f"Scene {scene_n} of idea {idea_id} is already being regenerated. "
            "Wait for it to finish before trying again."
        )
    _in_flight_regenerations.add(in_flight_key)

    try:
        lock = _get_script_lock(*lock_key)
        async with lock:
            # Pieza 43 (concurrency fix): re-read the LATEST script INSIDE
            # the lock. Anything read before acquiring the lock (or before
            # the Gemini await below, which is itself inside the lock) can
            # be stale by the time we are ready to write -- this is what
            # makes "two concurrent regenerations of different scenes" and
            # "a manual PATCH during a regeneration" both safe: whichever
            # operation gets the lock first sees and writes the freshest
            # state, and the next one re-reads that fresh state before it
            # does anything.
            script = _check_script(session_id, idea_id)
            if not script:
                raise ValueError("No script found. Generate script first.")

            if script.state == "locked":
                raise ValueError("Cannot regenerate locked script.")

            if scene_n < 1 or scene_n > len(script.scenes):
                raise ValueError(f"Scene {scene_n} out of range (1-{len(script.scenes)}).")

            target_scene = script.scenes[scene_n - 1]

            # Load context for regeneration
            brand_brain = get_brand_brain(session_id)
            brand_context = _build_brand_context(brand_brain)

            # Pieza 39: Use neutral instruction if None/empty to avoid "None" literal in prompt
            effective_instruction = instruction if instruction else "improve this scene"

            # Pieza 65: target language for this script based on other scenes
            target_lang = _script_language(script.scenes, exclude_n=scene_n)
            target_lang_name = "Spanish" if target_lang == "es" else "English"

            # Build regeneration prompt with BLUEPRINT fields (Pieza 39, Pieza 59)
            other_scenes_text = "\n".join(
                f"{s.n}. {s.phase}: {s.spoken_text}"
                for s in script.scenes
                if s.n != scene_n
            )

            prompt = f"""You are regenerating a single scene of a B2B short-form video script.

CONTEXT:
Brand: {brand_context}
Script recording format: {script.recording_format}

Original scene:
- Phase: {target_scene.phase}
- Original text: {target_scene.spoken_text}
- Shot: {target_scene.shot}
- Acting note: {target_scene.acting_note}
- Asset type: {target_scene.asset_type}

OTHER SCENES (read-only — do NOT repeat their content, do NOT move their lines into this scene):
{other_scenes_text}

Instruction: {effective_instruction}

RULES:
- Keep the SAME phase ({target_scene.phase})
- Write spoken_text, on_screen_text and acting_note in {target_lang_name} — the language of the rest of this script. The instruction may be written in another language; that NEVER changes the output language.
- The recording format is {script.recording_format}: acting_note must fit it. shot is a camera framing, not the format name.
- On-screen text: max 8 words
- HUMANIZATION: NEVER use these words: delve, crucial, tapestry, landscape, ever-evolving, unlock the potential, revolutionary, vital, in conclusion, in summary, discover how, optimize
- BURSTINESS: alternate long sentences with micro-phrases of 2-4 words
- NO INVENTED DATA: if you need a number not in context, reformulate without it

OUTPUT schema (INCLUDE BLUEPRINT FIELDS for Block D):
{{
  "spoken_text": "what the founder says",
  "shot": "camera framing such as 'Medium shot', 'Close-up' or 'Wide shot' — never the recording format name",
  "b_roll": "overlay (or null)",
  "on_screen_text": "subtitle max 8 words",
  "acting_note": "specific direction: rhythm, emphasis, pauses, gaze",
  "sound": "mood or SFX",
  "asset_type": "a_roll|stock|ai_image|ai_video|motion_graphic",
  "stock_query": "2 to 5 concrete filmable search words IN ENGLISH for Pexels, no lists or explanation",
  "visual_prompt": "generation prompt IN ENGLISH (max 40 words, 9:16 vertical, no text/logos/real faces)"
}}

Return ONLY valid JSON.
"""

            from vertexai.generative_models import GenerativeModel
            model = GenerativeModel(settings.vertex_ai_model)
            response = await model.generate_content_async(
                prompt,
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                },
            )

            try:
                new_scene_data = json.loads(response.text)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r"```json\s*(\{.*?\})\s*```", response.text, re.DOTALL)
                if json_match:
                    new_scene_data = json.loads(json_match.group(1))
                else:
                    raise ValueError("Failed to parse JSON from Gemini")

            # Pieza 43 (critical fix): build + FULLY VALIDATE the regenerated
            # scene BEFORE mutating or saving anything. This is what fixes
            # "regeneration persists unvalidated output and the script
            # vanishes on next load" -- if this raises, target_scene and
            # script.scenes are untouched, _save_script is never called, and
            # main.py's caller never reaches the credit deduction line.
            new_duration = _estimate_scene_duration(new_scene_data.get("spoken_text", ""))
            new_scene = _build_validated_scene(
                new_scene_data,
                n=target_scene.n,
                phase=target_scene.phase,  # RULE: phase never changes on regeneration
                start_s=target_scene.start_s,
                end_s=target_scene.start_s + new_duration,
                fallback=target_scene,
            )

            # Pieza 65: Language enforcement (retry once if wrong language, then fail without mutating script)
            det_lang = _detect_language(new_scene.spoken_text)
            if det_lang is not None and det_lang != target_lang:
                retry_prompt = (
                    prompt
                    + f"\n\nYour previous answer was in the wrong language. Rewrite it entirely in {target_lang_name}."
                )
                retry_response = await model.generate_content_async(
                    retry_prompt,
                    generation_config={
                        "temperature": 0.7,
                        "max_output_tokens": 1024,
                        "response_mime_type": "application/json",
                    },
                )
                try:
                    retry_scene_data = json.loads(retry_response.text)
                except json.JSONDecodeError:
                    import re
                    json_match = re.search(r"```json\s*(\{.*?\})\s*```", retry_response.text, re.DOTALL)
                    if json_match:
                        retry_scene_data = json.loads(json_match.group(1))
                    else:
                        raise ValueError("Failed to parse JSON from Gemini")

                retry_duration = _estimate_scene_duration(retry_scene_data.get("spoken_text", ""))
                new_scene = _build_validated_scene(
                    retry_scene_data,
                    n=target_scene.n,
                    phase=target_scene.phase,
                    start_s=target_scene.start_s,
                    end_s=target_scene.start_s + retry_duration,
                    fallback=target_scene,
                )
                det_lang_retry = _detect_language(new_scene.spoken_text)
                if det_lang_retry is not None and det_lang_retry != target_lang:
                    det_lang_str = "Spanish" if det_lang_retry == "es" else ("English" if det_lang_retry == "en" else det_lang_retry)
                    target_lang_str = "Spanish" if target_lang == "es" else "English"
                    raise ValueError(
                        f"The rewritten scene came back in {det_lang_str}, but this script is in {target_lang_str}. Nothing was changed or charged."
                    )

            # Only now, with a fully validated scene in hand, do we touch
            # the script.
            script.scenes[scene_n - 1] = new_scene
            _recompute_scene_timing_and_reflow(script.scenes, scene_n - 1)

            # PIEZA 40: If script was "reviewed", content change invalidates review
            # Return to "draft" so founder must confirm again
            if script.state == "reviewed":
                script.state = "draft"

            # Re-run audit
            script.audit = audit_script(script)

            # Save and return
            await _fill_missing_asset_prompts(script, only_n={scene_n})
            _save_script(script)
            return script
    finally:
        _in_flight_regenerations.discard(in_flight_key)


# =============================================================================
# UPDATE SCENE TEXT (manual edit)
# =============================================================================

async def update_scene_text(
    session_id: str,
    idea_id: str,
    scene_n: int,
    spoken_text: str,
) -> Script:
    """
    Manually update spoken text for a scene.

    PIEZA 40: If script was "reviewed", editing content invalidates the review
    and returns to "draft" state. The founder confirmed THAT version of the
    script; if content changes, they must review again.

    PIEZA 43 (concurrency + timing fixes):
    - Now async and shares the per-(session, idea) lock with
      regenerate_scene. Without this, a manual edit landing while a
      regeneration is awaiting Gemini (holding stale in-memory scenes) could
      be silently overwritten when the regeneration finally saves its own
      copy back. See `_get_script_lock` docstring for the single-instance
      assumption this relies on.
    - Recomputes this scene's estimated duration (same words/2.5 formula as
      generation/regeneration) and reflows every later scene's start/end, so
      a manual edit can no longer leave the timeline (and rule_1) stale.

    Args:
        session_id: Session token
        idea_id: Catalog idea ID
        scene_n: Scene number (1-indexed)
        spoken_text: New spoken text

    Returns:
        Updated Script object

    Raises:
        ValueError: If script not found, locked, or scene_n invalid
        ScriptStorageError: If persistence fails
    """
    lock = _get_script_lock(session_id, idea_id)
    async with lock:
        # Re-read the latest script INSIDE the lock -- see regenerate_scene
        # for why this matters.
        script = _check_script(session_id, idea_id)
        if not script:
            raise ValueError("No script found. Generate script first.")

        if script.state == "locked":
            raise ValueError("Cannot edit locked script.")

        if scene_n < 1 or scene_n > len(script.scenes):
            raise ValueError(f"Scene {scene_n} out of range (1-{len(script.scenes)}).")

        # Update text
        script.scenes[scene_n - 1].spoken_text = spoken_text

        # PIEZA 43: recompute this scene's duration estimate and reflow every
        # later scene's start/end, same formula used in generation/regen.
        _recompute_scene_timing_and_reflow(script.scenes, scene_n - 1)

        # PIEZA 40: If script was "reviewed", content change invalidates review
        # Return to "draft" so founder must confirm again
        if script.state == "reviewed":
            script.state = "draft"

        # Re-run audit
        script.audit = audit_script(script)

        # Save and return
        _save_script(script)
        return script


# =============================================================================
# CONFIRM SCRIPT (Pieza 40)
# =============================================================================

def confirm_script(
    session_id: str,
    idea_id: str,
    funnel_stage: Literal["tofu", "mofu", "bofu"],
    recording_format: Literal["selfie_natural", "pov", "dramatization", "teleprompter_clean", "dynamic"],
) -> Script:
    """
    Confirm a script: set funnel_stage and recording_format, move to "reviewed" state.

    PIEZA 40: This implements the "revisado" state that was defined but never assigned.
    The founder confirms what the system proposed for funnel_stage (decision D5)
    and recording_format (decision E3). No credits charged.

    If the script is "locked", confirmation is not allowed (returns error).
    If the script is already "reviewed", values are updated and stays reviewed.
    If the script is "draft", it moves to "reviewed".

    Args:
        session_id: Session token
        idea_id: Catalog idea ID
        funnel_stage: Confirmed funnel stage (tofu, mofu, bofu)
        recording_format: Confirmed recording format (one of 5 options)

    Returns:
        Updated Script object in "reviewed" state

    Raises:
        ValueError: If script not found, locked, or invalid values
        ScriptStorageError: If persistence fails
    """
    script = _check_script(session_id, idea_id)
    if not script:
        raise ValueError("No script found. Generate script first.")

    if script.state == "locked":
        raise ValueError("Locked scripts cannot be changed.")

    # Update values
    script.funnel_stage = funnel_stage
    script.recording_format = recording_format

    # Move to reviewed state (or stay reviewed if already there)
    if script.state == "draft":
        script.state = "reviewed"
    # If already "reviewed", stays "reviewed"

    # Re-run audit (in case rules check these values)
    script.audit = audit_script(script)

    # Save and return
    _save_script(script)
    return script


# =============================================================================
# LOCK SCRIPT
# =============================================================================

def lock_script(session_id: str, idea_id: str) -> Script:
    """
    Lock a script (final state, no further edits allowed).

    Rules:
    - No critical audit failures (8 rules must pass)
    - Once locked, ALL edits rejected with ValueError

    Critical rules (read from AUDIT_RULES["critical"] field):
    - rule_1:  Duration 45-90s (estimated)
    - rule_3:  Has all 6 phases
    - rule_4:  Exactly 2 key points (body_1 and body_2)
    - rule_5:  FrameZero stops scroll
    - rule_7:  No "not X, it's Y" patterns
    - rule_8:  No AI counterexamples
    - rule_9:  All numbers have citations (has sources)
    - rule_12: Has CTA (close_cta phase)

    Args:
        session_id: Session token
        idea_id: Catalog idea ID

    Returns:
        Locked Script object

    Raises:
        ValueError: If script not found, already locked, or fails lock rules
        ScriptStorageError: If persistence fails
    """
    script = _check_script(session_id, idea_id)
    if not script:
        raise ValueError("No script found. Generate script first.")

    if script.state == "locked":
        return script  # Already locked, no-op

    # PIEZA 42: Lock only from "reviewed" state
    if script.state != "reviewed":
        raise ValueError("Confirm funnel stage and recording format before locking")

    # Check lock rules - critical rules that must pass
    # Build the set dynamically from AUDIT_RULES to ensure sync
    critical_rules = {
        r["rule"] for r in AUDIT_RULES
        if r.get("critical", False)
    }
    failed_critical = [
        f for f in script.audit
        if f.status == "fail" and f.rule in critical_rules
    ]

    if failed_critical:
        raise ValueError(
            f"Cannot lock: critical failures: {', '.join(f.rule for f in failed_critical)}"
        )

    # Lock it
    script.state = "locked"

    # Save and return
    _save_script(script)
    return script
