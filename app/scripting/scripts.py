"""
Scripting engine (Piece 32 — Block C).

Generates, audits, and persists scripts from catalog ideas using Gemini.
Follows the same persistence pattern as app/catalog/ideas.py.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

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


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FrameZero(BaseModel):
    """
    FrameZero: what shows in the first frame before speaking.

    Required for stopping the scroll in less than 1 second.
    """
    visual: str = Field(..., description="What we see in the first frame")
    on_screen_text: str = Field(..., max_length=50, description="Text overlay, max 8 words")
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
    on_screen_text: str = Field(..., max_length=50, description="Subtitle, max 8 words")
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
        scenes = [Scene(**scene_data) for scene_data in data.get("scenes", [])]
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
# AUDIT RULES (13 deterministic rules, no LLM)
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

        try:
            if check_fn(script):
                findings.append(AuditFinding(rule=rule, status="pass", detail="OK"))
            else:
                findings.append(AuditFinding(rule=rule, status="fail", detail=fail_msg_fn(script)))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            findings.append(AuditFinding(rule=rule, status="fail", detail=f"Error checking: {e}"))

    return findings


# =============================================================================
# SCRIPT GENERATION
# =============================================================================

CREDITS_COST_GENERATE = 10
CREDITS_COST_REGENERATE_SCENE = 2


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
- Target duration: 45-90 seconds
- Tone: Professional, authoritative yet conversational
- Structure: 6 phases (hook, lock_in, body_1, rehook, body_2, close_cta)
- Each scene: 3-7 seconds
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
- FORBIDDEN: "not X, it's Y" patterns (e.g., "it's not just a tool, it's a partner")
- FORBIDDEN: AI counterexamples (e.g., "unlike other AI tools")
- CTA: Must match funnel stage (tofu: awareness, mofu: consideration, bofu: decision)

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
For EACH scene, include:
- asset_type: Choose from "a_roll" (founder on camera), "stock" (stock footage), "ai_image" (AI generated image), "ai_video" (AI generated video), "motion_graphic" (motion graphic overlay)
- stock_query: Search query IN ENGLISH for Pexels/Pixabay (null if asset_type is "a_roll")
- visual_prompt: Generation prompt IN ENGLISH for AI image/video (null if asset_type is "a_roll")

For SCRIPT-LEVEL:
- music_prompt: Search query IN ENGLISH for background music (mood + genre, e.g., "upbeat corporate electronic" or "cinematic suspense piano")
- recording_format: One of the 5 formats above

NOTE ON A-ROLL: This is a personal brand product. Scenes where the founder speaks to camera are a_roll and cost $0. Stock/AI are used only for B-roll (visuals while founder speaks off-screen or supplementary visuals).

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
      "b_roll": "what overlays (or null)",
      "on_screen_text": "subtitle max 8 words",
      "acting_note": "specific direction: rhythm, emphasis, pauses, gaze",
      "sound": "mood or SFX",
      "asset_type": "a_roll|stock|ai_image|ai_video|motion_graphic",
      "stock_query": "search query in ENGLISH for stock (or null)",
      "visual_prompt": "generation prompt in ENGLISH for AI (or null)"
    }}
  ],
  "sources": ["citation text from brand context or demand signal"]
}}

Total scenes should be 7-12. ALL queries and prompts must be IN ENGLISH. Return ONLY valid JSON.
"""
    return prompt


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

    # 6. Parse response
    try:
        script_data = json.loads(response.text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        import re
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", response.text, re.DOTALL)
        if json_match:
            script_data = json.loads(json_match.group(1))
        else:
            raise ValueError("Failed to parse JSON response from Gemini")

    # 7. Build Script object
    frame_zero = FrameZero(**script_data["frame_zero"])
    scenes_data = script_data["scenes"]

    # Pieza 39: Calculate timing as ESTIMATE based on spoken text.
    # Formula: words / 2.5 words per second (150 words/minute = 2.5 words/sec)
    # min_duration ensures no scene shows as 0 seconds.
    # IMPORTANT: This is an ESTIMATE for planning — actual duration only exists after recording.
    WORDS_PER_SECOND = 2.5
    MIN_SCENE_DURATION = 1.0  # Minimum 1 second per scene

    current_time = 0.0
    scenes = []
    for idx, scene_data in enumerate(scenes_data, start=1):
        phase = scene_data["phase"]

        # Duration is ESTIMATED from spoken_text length, not clamped.
        # We use the word count to give a proportional timeline for planning.
        spoken_words = len(scene_data.get("spoken_text", "").split())
        estimated_duration = max(MIN_SCENE_DURATION, spoken_words / WORDS_PER_SECOND)

        start_s = current_time
        end_s = start_s + estimated_duration
        current_time = end_s

        scene = Scene(
            n=idx,
            start_s=start_s,
            end_s=end_s,
            phase=phase,
            spoken_text=scene_data["spoken_text"],
            shot=scene_data["shot"],
            b_roll=scene_data.get("b_roll"),
            on_screen_text=scene_data["on_screen_text"],
            acting_note=scene_data["acting_note"],
            sound=scene_data["sound"],
            # BLUEPRINT fields (Pieza 39) - Block D consumption
            asset_type=scene_data.get("asset_type", "a_roll"),
            stock_query=scene_data.get("stock_query"),
            visual_prompt=scene_data.get("visual_prompt"),
        )
        scenes.append(scene)

    script = Script(
        session_id=session_id,
        idea_id=idea_id,
        title=script_data["title"],
        angle=script_data["angle"],
        funnel_stage=script_data.get("funnel_stage", "tofu"),
        target_seconds=script_data.get("target_seconds", 60),
        frame_zero=frame_zero,
        scenes=scenes,
        sources=script_data.get("sources", []),
        # BLUEPRINT fields (Pieza 39)
        music_prompt=script_data.get("music_prompt", ""),
        recording_format=script_data.get("recording_format", "selfie_natural"),
    )

    # 8. Run audit
    script.audit = audit_script(script)

    # 9. Save and return
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
        ValueError: If script not found, locked, or scene_n invalid
        ScriptStorageError: If persistence fails
    """
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

    # Build regeneration prompt with BLUEPRINT fields (Pieza 39)
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

Instruction: {effective_instruction}

RULES:
- Keep the SAME phase ({target_scene.phase})
- Use the SAME recording format ({script.recording_format}) for shot and acting_note
- On-screen text: max 8 words
- HUMANIZATION: NEVER use these words: delve, crucial, tapestry, landscape, ever-evolving, unlock the potential, revolutionary, vital, in conclusion, in summary, discover how, optimize
- BURSTINESS: alternate long sentences with micro-phrases of 2-4 words
- NO INVENTED DATA: if you need a number not in context, reformulate without it

OUTPUT schema (INCLUDE BLUEPRINT FIELDS for Block D):
{{
  "spoken_text": "what the founder says",
  "shot": "camera angle matching {script.recording_format} format",
  "b_roll": "overlay (or null)",
  "on_screen_text": "subtitle max 8 words",
  "acting_note": "specific direction: rhythm, emphasis, pauses, gaze",
  "sound": "mood or SFX",
  "asset_type": "a_roll|stock|ai_image|ai_video|motion_graphic",
  "stock_query": "search query IN ENGLISH for stock (or null)",
  "visual_prompt": "generation prompt IN ENGLISH for AI (or null)"
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

    # Update the scene (Pieza 39: include BLUEPRINT fields)
    target_scene.spoken_text = new_scene_data["spoken_text"]
    target_scene.shot = new_scene_data["shot"]
    target_scene.b_roll = new_scene_data.get("b_roll")
    target_scene.on_screen_text = new_scene_data["on_screen_text"]
    target_scene.acting_note = new_scene_data["acting_note"]
    target_scene.sound = new_scene_data["sound"]
    # BLUEPRINT fields (Pieza 39) - preserve if not returned by model
    target_scene.asset_type = new_scene_data.get("asset_type", target_scene.asset_type)
    target_scene.stock_query = new_scene_data.get("stock_query", target_scene.stock_query)
    target_scene.visual_prompt = new_scene_data.get("visual_prompt", target_scene.visual_prompt)

    # Recalculate duration estimate based on new spoken_text (Pieza 39)
    # Words / 2.5 words per second, min 1 second
    spoken_words = len(target_scene.spoken_text.split())
    new_duration = max(1.0, spoken_words / 2.5)
    target_scene.end_s = target_scene.start_s + new_duration

    # Update subsequent scene timings (shift start/end)
    for i in range(scene_n, len(script.scenes)):
        prev_scene = script.scenes[i - 1]
        curr_scene = script.scenes[i]
        duration = curr_scene.end_s - curr_scene.start_s
        curr_scene.start_s = prev_scene.end_s
        curr_scene.end_s = curr_scene.start_s + duration

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
# UPDATE SCENE TEXT (manual edit)
# =============================================================================

def update_scene_text(
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
    script = _check_script(session_id, idea_id)
    if not script:
        raise ValueError("No script found. Generate script first.")

    if script.state == "locked":
        raise ValueError("Cannot edit locked script.")

    if scene_n < 1 or scene_n > len(script.scenes):
        raise ValueError(f"Scene {scene_n} out of range (1-{len(script.scenes)}).")

    # Update text
    script.scenes[scene_n - 1].spoken_text = spoken_text

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
        raise ValueError("Cannot confirm locked script. Unlock first.")

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
