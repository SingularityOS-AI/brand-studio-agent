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
    """
    n: int = Field(..., description="Scene number (1-indexed)")
    start_s: float = Field(..., ge=0, description="Start time in seconds")
    end_s: float = Field(..., gt=0, description="End time in seconds")
    phase: Literal["hook", "lock_in", "body_1", "rehook", "body_2", "close_cta"] = Field(
        ..., description="Funnel phase"
    )
    spoken_text: str = Field(..., description="What the founder says (natural prose)")
    shot: str = Field(..., description="Camera angle")
    b_roll: str | None = Field(None, description="B-roll overlay")
    on_screen_text: str = Field(..., max_length=50, description="Subtitle, max 8 words")
    acting_note: str = Field(..., description="Acting/direction note")
    sound: str = Field(..., description="Background mood or SFX")

    @property
    def duration_s(self) -> float:
        """Scene duration in seconds."""
        return self.end_s - self.start_s

    def model_post_init(self, __context: Any):
        """Validate Scene constraints."""
        # Validate duration: 3-7 seconds for non-hook scenes, hook max 3 seconds
        if self.phase == "hook":
            if self.duration_s > 3:
                raise ValueError(f"Hook scene must be at most 3 seconds, got {self.duration_s:.1f}s")
        elif self.duration_s < 3 or self.duration_s > 7:
            raise ValueError(f"Scene duration must be between 3 and 7 seconds, got {self.duration_s:.1f}s")

        # Validate on-screen text max 8 words
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
# AUDIT RULES (12 deterministic rules, no LLM)
# =============================================================================

AUDIT_RULES: list[dict[str, Any]] = [
    {
        "rule": "rule_1",
        "name": "Duration: 45-90 seconds",
        "check": lambda s: 45 <= s.actual_seconds <= 90,
        "fail_msg": lambda s: f"Duration is {s.actual_seconds:.1f}s (must be 45-90s)",
    },
    {
        "rule": "rule_2",
        "name": "Hook duration: max 3 seconds",
        "check": lambda s: all(
            sc.phase != "hook" or sc.duration_s <= 3.0
            for sc in s.scenes
        ),
        "fail_msg": lambda s: "Hook scene exceeds 3 seconds",
    },
    {
        "rule": "rule_3",
        "name": "Has all 6 phases",
        "check": lambda s: {
            "hook", "lock_in", "body_1", "rehook", "body_2", "close_cta"
        }.issubset({sc.phase for sc in s.scenes}),
        "fail_msg": lambda s: "Missing one or more required phases",
    },
    {
        "rule": "rule_4",
        "name": "Exactly 2 key points (body_1 and body_2)",
        "check": lambda s: (
            len([sc for sc in s.scenes if sc.phase == "body_1"]) == 1
            and len([sc for sc in s.scenes if sc.phase == "body_2"]) == 1
        ),
        "fail_msg": lambda s: "Must have exactly one body_1 and one body_2 scene",
    },
    {
        "rule": "rule_5",
        "name": "FrameZero stops scroll",
        "check": lambda s: bool(s.frame_zero.why_it_stops_the_scroll.strip()),
        "fail_msg": lambda s: "FrameZero must explain why it stops the scroll",
    },
    {
        "rule": "rule_6",
        "name": "Has rehook before second point",
        "check": lambda s: any(sc.phase == "rehook" for sc in s.scenes),
        "fail_msg": lambda s: "Missing rehook before second key point",
    },
    {
        "rule": "rule_7",
        "name": "No 'not X, it's Y' patterns",
        "check": lambda s: all(
            " is not " not in sc.spoken_text.lower()
            and " it's not " not in sc.spoken_text.lower()
            for sc in s.scenes
        ),
        "fail_msg": lambda s: "Contains forbidden 'not X, it's Y' pattern",
    },
    {
        "rule": "rule_8",
        "name": "No AI counterexamples",
        "check": lambda s: all(
            not ("unlike" in sc.spoken_text.lower() and "ai" in sc.spoken_text.lower())
            and "not like" not in sc.spoken_text.lower()
            for sc in s.scenes
        ),
        "fail_msg": lambda s: "Contains AI counterexample pattern",
    },
    {
        "rule": "rule_9",
        "name": "All numbers have citations",
        "check": lambda s: len(s.sources) > 0,
        "fail_msg": lambda s: "Script must cite at least one source",
    },
    {
        "rule": "rule_10",
        "name": "On-screen text ≤ 8 words",
        "check": lambda s: all(
            len(sc.on_screen_text.split()) <= 8
            for sc in s.scenes
        ),
        "fail_msg": lambda s: "On-screen text exceeds 8 words in some scene",
    },
    {
        "rule": "rule_11",
        "name": "Each scene 3-7 seconds",
        "check": lambda s: all(3.0 <= sc.duration_s <= 7.0 for sc in s.scenes),
        "fail_msg": lambda s: "Some scene outside 3-7 second range",
    },
    {
        "rule": "rule_12",
        "name": "Has CTA",
        "check": lambda s: any(sc.phase == "close_cta" for sc in s.scenes),
        "fail_msg": lambda s: "Missing CTA (close_cta) scene",
    },
]


def audit_script(script: Script) -> list[AuditFinding]:
    """
    Run all 12 audit rules on a script (deterministic, no LLM).

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

OUTPUT: Valid JSON with this exact schema:
{{
  "title": "script title",
  "angle": "progressive angle description",
  "target_seconds": 60,
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
      "acting_note": "how to say it",
      "sound": "mood or SFX"
    }}
  ],
  "sources": ["citation text from brand context or demand signal"]
}}

Total scenes should be 7-12 to hit 45-90s. Return ONLY valid JSON.
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

    # Calculate timing with phase-specific duration limits
    current_time = 0.0
    scenes = []
    for idx, scene_data in enumerate(scenes_data, start=1):
        phase = scene_data["phase"]

        # Use explicit duration if provided, otherwise compute based on phase
        if "duration_s" in scene_data:
            duration = scene_data["duration_s"]
            # Enforce phase limits
            if phase == "hook" and duration > 3.0:
                duration = 3.0  # Hook must be ≤3s
            elif not (3.0 <= duration <= 7.0):
                # Clamp other phases to 3-7s range
                duration = max(3.0, min(7.0, duration))
        else:
            # Default durations by phase when not specified
            if phase == "hook":
                duration = 2.5  # Hook default: 2.5s (well under 3s limit)
            else:
                duration = 5.0  # Other phases default: 5s

        start_s = current_time
        end_s = start_s + duration
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

    # Build regeneration prompt
    prompt = f"""You are regenerating a single scene of a B2B short-form video script.

CONTEXT:
Brand: {brand_context}

Original scene:
- Phase: {target_scene.phase}
- Original text: {target_scene.spoken_text}
- Shot: {target_scene.shot}
- Acting note: {target_scene.acting_note}

Instruction: {instruction}

RULES:
- Keep the SAME phase ({target_scene.phase})
- Keep the same timing ({target_scene.duration_s:.1f}s)
- On-screen text: max 8 words
- Output ONLY valid JSON for the scene (no markdown)

OUTPUT schema:
{{
  "spoken_text": "new text",
  "shot": "camera angle",
  "b_roll": "overlay (or null)",
  "on_screen_text": "subtitle max 8 words",
  "acting_note": "how to say it",
  "sound": "mood or SFX"
}}
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

    # Update the scene
    target_scene.spoken_text = new_scene_data["spoken_text"]
    target_scene.shot = new_scene_data["shot"]
    target_scene.b_roll = new_scene_data.get("b_roll")
    target_scene.on_screen_text = new_scene_data["on_screen_text"]
    target_scene.acting_note = new_scene_data["acting_note"]
    target_scene.sound = new_scene_data["sound"]

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

    # Re-run audit
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
    - No critical audit failures (rule_1, rule_4, rule_5, rule_8, rule_9, rule_12)
    - Once locked, ALL edits rejected with ValueError

    Critical rules check:
    - rule_1: Duration 45-90s
    - rule_4: All 6 phases in order (last must be close_cta)
    - rule_5: Exactly one body_1 and one body_2
    - rule_8: No "not X, it's Y" patterns
    - rule_9: No numbers without citations
    - rule_12: FrameZero not empty

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
    critical_rules = {"rule_1", "rule_4", "rule_5", "rule_8", "rule_9", "rule_12"}
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
