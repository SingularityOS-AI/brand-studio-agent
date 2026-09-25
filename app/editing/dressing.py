"""Brandy dressing module (Bloque E).

Dresses scene contexts with visual transitions, zooms, overlays, SFX tags, and emphasis
using closed catalog catalog_v1.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.audiovisual.genai_client import get_genai_client
from app.config import settings

logger = logging.getLogger(__name__)


class Zoom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    word_idx: int
    intensity: str


class Overlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    word_idx: int
    duration_ms: int
    position: str
    accent: bool = False
    broll_scene: int | None = None
    emoji: str | None = None


class SfxTags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition: str
    overlay: str


class DressScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    seed: int
    transition_in: str
    emphasis_word_idx: list[int] = Field(default_factory=list)
    zooms: list[Zoom] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list)
    sfx_tags: SfxTags
    stale: bool = False


class Dressing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    source: Literal["llm", "fallback"]
    raw_hash: str
    scenes: list[DressScene]


def load_catalog() -> dict:
    """Load catalog_v1.json from relative catalog folder."""
    catalog_path = Path(__file__).parent / "catalog" / "catalog_v1.json"
    with open(catalog_path, "r", encoding="utf-8") as f:
        return json.load(f)


def scene_contexts(
    timeline: dict, captions_words: list[dict], script: dict
) -> list[dict]:
    """Build context dictionaries for each scene in timeline."""
    script_scenes_map = {
        int(s["n"]): s for s in script.get("scenes", []) if "n" in s
    }

    contexts = []
    for ts in timeline.get("scenes", []):
        n = int(ts["n"])
        phase = str(ts.get("phase", ""))
        visual = str(ts.get("visual", "face"))
        out_start = int(ts.get("out_start_ms", 0))
        out_end = int(ts.get("out_end_ms", 0))
        duration_ms = int(ts.get("duration_ms", out_end - out_start))
        has_broll = ts.get("broll") is not None

        script_s = script_scenes_map.get(n, {})
        on_screen_text = str(script_s.get("on_screen_text", ""))

        cw_in_scene = [
            cw for cw in captions_words if int(cw.get("scene_n", -1)) == n
        ]
        cw_in_scene.sort(key=lambda cw: cw.get("start_ms", 0))

        words = []
        for idx, cw in enumerate(cw_in_scene):
            edited = cw.get("edited_text")
            if edited is not None and str(edited).strip():
                text = str(edited).strip()
            else:
                text = str(cw.get("text", "")).strip()

            w_start = int(cw.get("start_ms", 0))
            rel_start = max(0, w_start - out_start)
            words.append({
                "i": idx,
                "text": text,
                "start_ms": rel_start,
            })

        contexts.append({
            "n": n,
            "phase": phase,
            "visual": visual,
            "duration_ms": duration_ms,
            "has_broll": has_broll,
            "on_screen_text": on_screen_text,
            "words": words,
        })

    return contexts


def build_prompt(contexts: list[dict], catalog: dict) -> str:
    """Build prompt for Brandy LLM dressing director."""
    return (
        "You are Brandy, a vertical video edit director for personal brand content (LinkedIn-first).\n"
        "Your focus is on what the founder says. Visual edits should create emphasis every 3-5 seconds.\n"
        "Choose ONLY values from the closed catalog provided.\n"
        "Within the catalog you have full creative freedom: vary where, when and how strong each move lands, "
        "pick the words that deserve emphasis, combine zooms, overlays and sound so the edit feels alive and "
        "surprising, and never repeat the same pattern scene after scene.\n\n"
        f"Catalog:\n{json.dumps(catalog, indent=2, ensure_ascii=False)}\n\n"
        f"Scene Contexts:\n{json.dumps(contexts, indent=2, ensure_ascii=False)}\n\n"
        "Rules:\n"
        "1. Return ONLY valid JSON matching this structure (do NOT include source, raw_hash, seed):\n"
        "{\n"
        '  "catalog_version": "v1",\n'
        '  "scenes": [\n'
        "    {\n"
        '      "n": <int>,\n'
        '      "transition_in": "<cut|flash|zoom_through|whip>",\n'
        '      "emphasis_word_idx": [<int>, ...],\n'
        '      "zooms": [{"type": "<punch_in|punch_out|slow_push>", "word_idx": <int>, "intensity": "<soft|medium|strong>"}],\n'
        '      "overlays": [{"kind": "<kind>", "word_idx": <int>, "duration_ms": <int 1200-3500>, "position": "<pos>", "accent": <bool>, "broll_scene": <int|null>, "emoji": "<emoji|null>"}],\n'
        '      "sfx_tags": {"transition": "<whoosh|pop|click|riser|ding|none>", "overlay": "<whoosh|pop|click|riser|ding|none>"}\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "2. Transition rules: Default transition is 'cut'. Use motion on phase changes (hook -> next phase, before 'rehook', entry to 'close_cta'). Never use the exact same transition twice in a row.\n"
        "3. Word indices (word_idx) must be valid 0-based indices from each scene's words array.\n"
        "4. In scenes with visual='broll', do not add zooms.\n"
        "5. Respond ONLY with raw JSON."
    )


def fallback_dressing(
    contexts: list[dict], catalog: dict, raw_hash: str, seeds: dict[int, int]
) -> dict:
    """Generate deterministic fallback dressing."""
    catalog_version = catalog.get("version", "v1")
    limits = catalog.get("limits", {})
    max_zooms = limits.get("zooms_per_scene", 3)
    max_overlays = limits.get("overlays_per_scene", 2)
    max_emphasis = limits.get("emphasis_per_scene", 3)

    raw_transitions = []
    for idx, ctx in enumerate(contexts):
        phase = ctx.get("phase", "")
        if idx == 0:
            raw_transitions.append("cut")
        elif (idx > 0 and contexts[idx - 1].get("phase") == "hook") or idx == 1:
            raw_transitions.append("flash")
        elif phase == "rehook":
            raw_transitions.append("zoom_through")
        elif phase in ("close_cta", "cta"):
            raw_transitions.append("whip")
        else:
            raw_transitions.append("cut")

    chosen_transitions: list[str] = []
    allowed_transitions = list(catalog.get("transitions", {}).keys()) or [
        "cut",
        "flash",
        "zoom_through",
        "whip",
    ]
    for idx, tr in enumerate(raw_transitions):
        if idx > 0 and tr == chosen_transitions[idx - 1]:
            alt = [
                t for t in allowed_transitions if t != chosen_transitions[idx - 1]
            ]
            tr = alt[0] if alt else "cut"
        chosen_transitions.append(tr)

    scenes: list[DressScene] = []
    for idx, ctx in enumerate(contexts):
        n = int(ctx["n"])
        seed = seeds.get(n, n)
        tr = chosen_transitions[idx]
        words = ctx.get("words", [])
        duration_ms = int(ctx.get("duration_ms", 3000))

        emphasis = [0] if words else []
        emphasis = emphasis[:max_emphasis]

        zooms: list[Zoom] = []
        if ctx.get("visual") == "face" and words:
            window_ms = 4000
            n_windows = max(1, (duration_ms + window_ms - 1) // window_ms)
            for w_win_idx in range(n_windows):
                w_start = w_win_idx * window_ms
                w_end = w_start + window_ms
                window_words = [
                    w for w in words if w_start <= w.get("start_ms", 0) < w_end
                ]
                if window_words:
                    longest_w = max(
                        window_words, key=lambda w: len(w.get("text", ""))
                    )
                    zooms.append(
                        Zoom(
                            type="punch_in",
                            word_idx=int(longest_w["i"]),
                            intensity="medium",
                        )
                    )
        zooms = zooms[:max_zooms]

        overlays: list[Overlay] = []
        if ctx.get("on_screen_text") and words:
            dur = min(3500, max(1200, duration_ms))
            overlays.append(
                Overlay(
                    kind="onscreen_text",
                    word_idx=0,
                    duration_ms=dur,
                    position="lower_third",
                    accent=False,
                    broll_scene=None,
                    emoji=None,
                )
            )
        overlays = overlays[:max_overlays]

        sfx_tags = SfxTags(transition="whoosh", overlay="pop")

        scene_model = DressScene(
            n=n,
            seed=seed,
            transition_in=tr,
            emphasis_word_idx=emphasis,
            zooms=zooms,
            overlays=overlays,
            sfx_tags=sfx_tags,
            stale=False,
        )
        scenes.append(scene_model)

    dressing_model = Dressing(
        catalog_version=catalog_version,
        source="fallback",
        raw_hash=raw_hash,
        scenes=scenes,
    )
    return dressing_model.model_dump()


def validate_dressing(
    raw: Any,
    contexts: list[dict],
    catalog: dict,
    raw_hash: str,
    seeds: dict[int, int],
    source: str,
) -> dict:
    """Validate raw dressing output against catalog and contexts."""
    valid_transitions = set(catalog.get("transitions", {}).keys())
    valid_sfx_tags = set(catalog.get("sfx_tags", []))
    valid_zoom_types = set(catalog.get("zoom", {}).get("types", []))
    valid_zoom_intensities = set(
        catalog.get("zoom", {}).get("intensity", {}).keys()
    )
    valid_overlay_kinds = set(catalog.get("overlays", {}).get("kinds", []))
    valid_overlay_positions = set(
        catalog.get("overlays", {}).get("positions", [])
    )
    dur_limits = catalog.get("overlays", {}).get("duration_ms", [1200, 3500])
    min_dur, max_dur = int(dur_limits[0]), int(dur_limits[1])
    valid_emojis = set(catalog.get("emoji", []))
    broll_scene_n_set = {int(c["n"]) for c in contexts if c.get("has_broll")}

    limits = catalog.get("limits", {})
    max_zooms = int(limits.get("zooms_per_scene", 3))
    max_overlays = int(limits.get("overlays_per_scene", 2))
    max_emphasis = int(limits.get("emphasis_per_scene", 3))

    raw_scenes_list = (
        raw.get("scenes")
        if (isinstance(raw, dict) and isinstance(raw.get("scenes"), list))
        else []
    )
    raw_scenes_by_n = {
        int(rs["n"]): rs
        for rs in raw_scenes_list
        if isinstance(rs, dict) and "n" in rs and isinstance(rs.get("n"), int)
    }

    fallback_dict = fallback_dressing(contexts, catalog, raw_hash, seeds)
    fallback_scenes_by_n = {
        fs["n"]: fs for fs in fallback_dict.get("scenes", [])
    }

    scenes: list[DressScene] = []
    for ctx in contexts:
        n = int(ctx["n"])
        seed = seeds.get(n, n)
        words = ctx.get("words", [])
        num_words = len(words)
        raw_s = raw_scenes_by_n.get(n)

        if raw_s is None:
            fb_s = fallback_scenes_by_n.get(n)
            if fb_s:
                scenes.append(DressScene.model_validate(fb_s))
            continue

        raw_tr = raw_s.get("transition_in")
        if not isinstance(raw_tr, str) or raw_tr not in valid_transitions:
            logger.info(
                f"Scene {n}: transition_in '{raw_tr}' not in catalog, resetting to cut"
            )
            transition_in = "cut"
        else:
            transition_in = raw_tr

        raw_sfx = raw_s.get("sfx_tags") if isinstance(raw_s.get("sfx_tags"), dict) else {}
        tr_sfx = raw_sfx.get("transition")
        if not isinstance(tr_sfx, str) or tr_sfx not in valid_sfx_tags:
            logger.info(
                f"Scene {n}: sfx transition '{tr_sfx}' not in catalog, resetting to whoosh"
            )
            tr_sfx = "whoosh"

        ov_sfx = raw_sfx.get("overlay")
        if not isinstance(ov_sfx, str) or ov_sfx not in valid_sfx_tags:
            logger.info(
                f"Scene {n}: sfx overlay '{ov_sfx}' not in catalog, resetting to pop"
            )
            ov_sfx = "pop"
        sfx_tags = SfxTags(transition=tr_sfx, overlay=ov_sfx)

        raw_emp = raw_s.get("emphasis_word_idx")
        valid_emp: list[int] = []
        if isinstance(raw_emp, list):
            for idx in raw_emp:
                if isinstance(idx, int) and 0 <= idx < num_words:
                    valid_emp.append(idx)
                else:
                    logger.info(
                        f"Scene {n}: emphasis word_idx {idx} out of range [0, {num_words})"
                    )
        emphasis_word_idx = valid_emp[:max_emphasis]

        zooms: list[Zoom] = []
        if ctx.get("visual") == "broll":
            if raw_s.get("zooms"):
                logger.info(f"Scene {n}: visual is broll, discarding zooms")
        else:
            raw_zooms = (
                raw_s.get("zooms") if isinstance(raw_s.get("zooms"), list) else []
            )
            for z in raw_zooms:
                if not isinstance(z, dict):
                    logger.info(f"Scene {n}: zoom item is not dict")
                    continue
                z_type = z.get("type")
                z_w_idx = z.get("word_idx")
                z_intensity = z.get("intensity")

                if (
                    not isinstance(z_type, str)
                    or z_type not in valid_zoom_types
                ):
                    logger.info(f"Scene {n}: zoom type '{z_type}' not in catalog")
                    continue
                if (
                    not isinstance(z_intensity, str)
                    or z_intensity not in valid_zoom_intensities
                ):
                    logger.info(
                        f"Scene {n}: zoom intensity '{z_intensity}' not in catalog"
                    )
                    continue
                if not isinstance(z_w_idx, int) or not (0 <= z_w_idx < num_words):
                    logger.info(
                        f"Scene {n}: zoom word_idx {z_w_idx} out of range [0, {num_words})"
                    )
                    continue
                zooms.append(
                    Zoom(type=z_type, word_idx=z_w_idx, intensity=z_intensity)
                )
            zooms = zooms[:max_zooms]

        raw_overlays = (
            raw_s.get("overlays")
            if isinstance(raw_s.get("overlays"), list)
            else []
        )
        overlays: list[Overlay] = []
        for ov in raw_overlays:
            if not isinstance(ov, dict):
                logger.info(f"Scene {n}: overlay item is not dict")
                continue
            ov_kind = ov.get("kind")
            ov_w_idx = ov.get("word_idx")
            ov_pos = ov.get("position")
            ov_dur = ov.get("duration_ms")
            ov_accent = bool(ov.get("accent", False))
            ov_broll_scene = ov.get("broll_scene")
            ov_emoji = ov.get("emoji")

            if not isinstance(ov_kind, str) or ov_kind not in valid_overlay_kinds:
                logger.info(f"Scene {n}: overlay kind '{ov_kind}' not in catalog")
                continue
            if (
                not isinstance(ov_pos, str)
                or ov_pos not in valid_overlay_positions
            ):
                logger.info(
                    f"Scene {n}: overlay position '{ov_pos}' not in catalog"
                )
                continue
            if not isinstance(ov_w_idx, int) or not (0 <= ov_w_idx < num_words):
                logger.info(
                    f"Scene {n}: overlay word_idx {ov_w_idx} out of range [0, {num_words})"
                )
                continue
            if ov_emoji is not None:
                if not isinstance(ov_emoji, str) or ov_emoji not in valid_emojis:
                    logger.info(
                        f"Scene {n}: overlay emoji '{ov_emoji}' not in catalog"
                    )
                    continue
            if ov_broll_scene is not None:
                if (
                    not isinstance(ov_broll_scene, int)
                    or ov_broll_scene not in broll_scene_n_set
                ):
                    logger.info(
                        f"Scene {n}: overlay broll_scene {ov_broll_scene} invalid or lacks broll"
                    )
                    continue

            if not isinstance(ov_dur, (int, float)):
                clamped_dur = min_dur
            else:
                clamped_dur = int(min(max_dur, max(min_dur, int(ov_dur))))
                if clamped_dur != ov_dur:
                    logger.info(
                        f"Scene {n}: overlay duration_ms {ov_dur} clamped to {clamped_dur}"
                    )

            overlays.append(
                Overlay(
                    kind=ov_kind,
                    word_idx=ov_w_idx,
                    duration_ms=clamped_dur,
                    position=ov_pos,
                    accent=ov_accent,
                    broll_scene=ov_broll_scene,
                    emoji=ov_emoji,
                )
            )
        overlays = overlays[:max_overlays]

        # Staleness is decided by the backend (a take changed), never by the model.
        stale = False

        scene_model = DressScene(
            n=n,
            seed=seed,
            transition_in=transition_in,
            emphasis_word_idx=emphasis_word_idx,
            zooms=zooms,
            overlays=overlays,
            sfx_tags=sfx_tags,
            stale=stale,
        )
        scenes.append(scene_model)

    dressing_model = Dressing(
        catalog_version=catalog.get("version", "v1"),
        source=source if source in ("llm", "fallback") else "fallback",
        raw_hash=raw_hash,
        scenes=scenes,
    )
    return dressing_model.model_dump()


async def dress_all(
    contexts: list[dict],
    raw_hash: str,
    seed_base: int,
    *,
    timeout_s: float | None = None,
) -> dict:
    """Dress all scenes using LLM or fallback if LLM fails/times out."""
    seeds = {int(c["n"]): seed_base * 1000 + int(c["n"]) for c in contexts}
    catalog = load_catalog()
    prompt = build_prompt(contexts, catalog)

    from app.editing.config import LLM_TIMEOUT_DRESS

    timeout = timeout_s if timeout_s is not None else float(LLM_TIMEOUT_DRESS)

    try:
        client = get_genai_client()
        model_name = getattr(settings, "vertex_ai_model", "gemini-2.5-flash")

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
            )
        except Exception:
            config = {
                "response_mime_type": "application/json",
                "temperature": 0.9,
            }

        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=timeout,
        )
        raw_text = getattr(resp, "text", "") or ""
        raw_json = json.loads(raw_text)
        result = validate_dressing(
            raw_json, contexts, catalog, raw_hash, seeds, source="llm"
        )
    except Exception as exc:
        logger.info(f"Dressing LLM failed or timed out: {exc}, falling back")
        result = fallback_dressing(contexts, catalog, raw_hash, seeds)

    Dressing.model_validate(result)
    return result
