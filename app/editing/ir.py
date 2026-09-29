"""RenderIR v1 stage 1: block captions and frame zero construction (Bloque E)."""

import random
import re
from pathlib import Path
from typing import Any

from app.audiovisual.sfx import load_sfx_library
from app.editing.metadata import sanitize_text
from render_service.manifest import (
    CAPTION_Y_DEFAULT,
    CaptionEvent,
    CaptionToken,
    FrameZero,
    OverlayCue,
    RenderIR,
    SfxCue,
    TransitionCue,
    ZoomKey,
    clamp_caption_y,
)

_PUNCT_END = re.compile(r"(\.|\?|\!|…|\.\.\.)$")
TRANSITION_DURATIONS = {"flash": 200, "zoom_through": 330, "whip": 270}
ZOOM_INTENSITIES = {"soft": 1.08, "medium": 1.15, "strong": 1.25}

# Zone definitions for overlay placement (y ranges)
ZONE_TOP = (160, 700)
ZONE_MIDDLE = (700, 1220)
ZONE_BOTTOM = (1220, 1760)

# Alternative positions for each zone (for collision resolution)
ZONE_ALTERNATIVES = {
    "top": ["top", "center", "lower_third"],
    "middle": ["center", "left", "right", "top", "lower_third"],
    "bottom": ["lower_third", "center", "top"],
}

# Block font size for caption height calculation
BLOCK_FONT_PX = 56
CAPTION_OUTLINE_PX = 3


def _calculate_caption_box(
    caption_y: int, events: list[dict[str, Any]], t_ms: int
) -> tuple[int, int, int, int] | None:
    """Calculate caption box at given time.

    Returns (x, y, w, h) where y is the top of the caption box.
    Returns None if no caption is active at t_ms.
    """
    # Find active caption event at t_ms
    active_event = None
    for ev in events:
        if ev["start_ms"] <= t_ms < ev["end_ms"]:
            active_event = ev
            break

    if active_event is None:
        return None

    # Calculate caption height based on lines
    num_lines = len(active_event["lines"])
    # Height = lines × font_px × 1.15 + 2×outline
    height = int(num_lines * BLOCK_FONT_PX * 1.15 + 2 * CAPTION_OUTLINE_PX)
    # Width is 900px centered
    width = 900
    # Caption y is the bottom edge, so top = caption_y - height
    top = caption_y - height
    # Centered horizontally: x = (1080 - 900) / 2 = 90
    left = 90

    return (left, top, width, height)


def _boxes_intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Check if two boxes (x, y, w, h) intersect."""
    ax1, ay1, aw, ah = a
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx1, by1, bw, bh = b
    bx2, by2 = bx1 + bw, by1 + bh

    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


def _get_overlay_zone(ov_box: tuple[int, int, int, int]) -> str:
    """Determine which zone an overlay box primarily occupies."""
    _, y, _, h = ov_box
    center_y = y + h // 2

    if ZONE_TOP[0] <= center_y < ZONE_TOP[1]:
        return "top"
    elif ZONE_MIDDLE[0] <= center_y < ZONE_MIDDLE[1]:
        return "middle"
    elif ZONE_BOTTOM[0] <= center_y <= ZONE_BOTTOM[1]:
        return "bottom"
    # Default to bottom if outside defined zones
    return "bottom"


def _get_position_box(
    position: str, kind: str, boxes: dict[str, tuple[int, int, int, int]]
) -> tuple[int, int, int, int]:
    """Get the box for a given position, handling emoji sizing."""
    bx, by, bw, bh = boxes.get(position, (90, 1300, 900, 200))

    if kind == "emoji":
        w = 220
        h = 220
        x = bx + (bw - 220) // 2
        y = by + (bh - 220) // 2
        return (x, y, w, h)
    else:
        return (bx, by, bw, bh)


def _move_overlay_to_zone(
    ov: dict[str, Any], target_zone: str, boxes: dict[str, tuple[int, int, int, int]]
) -> dict[str, Any]:
    """Move an overlay to a new zone, keeping x/w/h the same where possible."""
    ov = dict(ov)  # Copy to avoid modifying original
    kind = ov["kind"]

    # Get the appropriate position for this zone
    zone_to_position = {
        "top": "top",
        "middle": "center",
        "bottom": "lower_third",
    }
    target_pos = zone_to_position.get(target_zone, "lower_third")

    # Calculate new box
    new_box = _get_position_box(target_pos, kind, boxes)
    ov["x"] = new_box[0]
    ov["y"] = new_box[1]
    ov["w"] = new_box[2]
    ov["h"] = new_box[3]

    return ov


def _resolve_overlay_collisions(
    overlays: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    caption_y: int,
    boxes: dict[str, tuple[int, int, int, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve overlay-caption collisions by repositioning or hiding captions.

    Returns: (resolved_overlays, filtered_captions, overlays_with_hide_captions)
    """
    resolved = []
    hide_captions_windows: list[tuple[int, int]] = []

    for ov in overlays:
        ov_box = (ov["x"], ov["y"], ov["w"], ov["h"])
        ov_start = ov["start_ms"]
        ov_end = ov["end_ms"]

        # Calculate midpoint for caption check
        mid_ms = (ov_start + ov_end) // 2

        # Get caption box at overlay midpoint
        caption_box = _calculate_caption_box(caption_y, captions, mid_ms)

        if caption_box is None:
            # No caption at this time, overlay can stay
            resolved.append(ov)
            continue

        # Check intersection
        if not _boxes_intersect(ov_box, caption_box):
            # No collision
            resolved.append(ov)
            continue

        # Determine current zone
        current_zone = _get_overlay_zone(ov_box)

        # Try to find a free zone
        # Check which zones are occupied by the caption
        caption_top_y = caption_box[1]
        caption_bottom_y = caption_top_y + caption_box[3]

        # Determine which zones the caption occupies
        caption_zones = set()
        for zone_name, (z_min, z_max) in [
            ("top", ZONE_TOP),
            ("middle", ZONE_MIDDLE),
            ("bottom", ZONE_BOTTOM),
        ]:
            if caption_top_y < z_max and caption_bottom_y > z_min:
                caption_zones.add(zone_name)

        # Try alternatives in order of preference
        moved = False
        position_alternatives = ZONE_ALTERNATIVES.get(current_zone, ["top"])

        for alt_position in position_alternatives:
            # Get the zone this position would occupy
            alt_pos_box = _get_position_box(alt_position, ov["kind"], boxes)
            alt_zone = _get_overlay_zone(alt_pos_box)

            # Skip if this zone is occupied by caption
            if alt_zone in caption_zones:
                continue

            # Check if there's already an overlay in this zone at this time
            zone_occupied = False
            for existing in resolved:
                # Check temporal overlap
                if not (ov_end <= existing["start_ms"] or ov_start >= existing["end_ms"]):
                    # Temporal overlap, check spatial
                    existing_box = (existing["x"], existing["y"], existing["w"], existing["h"])
                    if _get_overlay_zone(existing_box) == alt_zone:
                        # Same zone, might overlap if both active
                        zone_occupied = True
                        break

            if not zone_occupied:
                # Move to this position
                ov = _move_overlay_to_zone(ov, alt_zone, boxes)
                resolved.append(ov)
                moved = True
                break

        if not moved:
            # No free zone available, hide captions for this overlay's duration
            ov["hide_captions"] = True
            resolved.append(ov)
            hide_captions_windows.append((ov_start, ov_end))

    # Now filter captions that overlap with hide_captions windows
    filtered_captions = []
    for ev in captions:
        ev_start = ev["start_ms"]
        ev_end = ev["end_ms"]

        # Check if this caption overlaps any hide window
        should_hide = False
        for win_start, win_end in hide_captions_windows:
            if ev_start < win_end and ev_end > win_start:
                should_hide = True
                break

        if not should_hide:
            filtered_captions.append(ev)

    return resolved, filtered_captions, [ov for ov in resolved if ov.get("hide_captions")]


def _format_token(word: dict[str, Any]) -> dict[str, Any]:
    edited = word.get("edited_text")
    if edited is not None and str(edited).strip():
        text = str(edited).strip()[:40]
    else:
        text = str(word.get("text", "")).strip()[:40]

    start_ms = max(0, int(word.get("start_ms", 0)))
    end_ms = max(start_ms, int(word.get("end_ms", start_ms)))
    token_dict = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
    CaptionToken.model_validate(token_dict)
    return token_dict


def _split_into_lines(tokens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split 1 to 3 tokens into 1 or 2 lines according to length rules.

    Rule 5:
    If total character count of tokens (with single spaces between tokens) <= 14 or 1 token -> 1 line.
    Otherwise -> 2 lines, splitting tokens such that line 1 is as short as possible
    while keeping line 2 <= line 1 + 6 chars.
    """
    n = len(tokens)
    if n <= 1:
        return [tokens]

    total_chars = sum(len(str(t["text"])) for t in tokens) + (n - 1)
    if total_chars <= 14:
        return [tokens]

    if n == 2:
        return [[tokens[0]], [tokens[1]]]

    # n == 3
    len1_a = len(str(tokens[0]["text"]))
    len2_a = len(str(tokens[1]["text"])) + 1 + len(str(tokens[2]["text"]))

    len1_b = len(str(tokens[0]["text"])) + 1 + len(str(tokens[1]["text"]))
    len2_b = len(str(tokens[2]["text"]))

    cond_a = len2_a <= len1_a + 6
    cond_b = len2_b <= len1_b + 6

    if cond_a and not cond_b:
        return [[tokens[0]], [tokens[1], tokens[2]]]
    if cond_b and not cond_a:
        return [[tokens[0], tokens[1]], [tokens[2]]]
    if cond_a and cond_b:
        if len1_a <= len1_b:
            return [[tokens[0]], [tokens[1], tokens[2]]]
        return [[tokens[0], tokens[1]], [tokens[2]]]

    # Fallback if neither satisfies <= line 1 + 6: choose most balanced
    diff_a = abs(len1_a - len2_a)
    diff_b = abs(len1_b - len2_b)
    if diff_a <= diff_b:
        return [[tokens[0]], [tokens[1], tokens[2]]]
    return [[tokens[0], tokens[1]], [tokens[2]]]


def caption_events(
    words: list[dict[str, Any]], duration_ms: int, fz_end: int = 0
) -> list[dict[str, Any]]:
    """Build caption events from words list for given duration_ms.

    Words starting before fz_end are ignored. F6: one Brand Soul caption style for
    the whole video — every remaining word renders as a uniform 'block' event (up
    to 3 words); no early 'hero' giant-word events.
    """
    valid_words = [w for w in words if max(0, int(w.get("start_ms", 0))) >= fz_end]
    valid_words.sort(key=lambda w: int(w.get("start_ms", 0)))

    block_words = valid_words

    raw_events: list[dict[str, Any]] = []

    # Process block words: up to 3 words per block
    if block_words:
        i = 0
        n_block = len(block_words)
        while i < n_block:
            current_group: list[dict[str, Any]] = [block_words[i]]
            i += 1
            while len(current_group) < 3 and i < n_block:
                last_w = current_group[-1]
                edited_val = last_w.get("edited_text")
                last_text = str(
                    edited_val if edited_val is not None else last_w.get("text", "")
                ).strip()

                if _PUNCT_END.search(last_text):
                    break

                next_w = block_words[i]
                if int(next_w.get("scene_n", 1)) != int(last_w.get("scene_n", 1)):
                    break

                gap = int(next_w.get("start_ms", 0)) - int(last_w.get("end_ms", 0))
                if gap > 700:
                    break

                current_group.append(next_w)
                i += 1

            tokens = [_format_token(bw) for bw in current_group]
            lines = _split_into_lines(tokens)
            raw_events.append({
                "size": "block",
                "lines": lines,
                "emphasis": [],
                "words": current_group,
            })

    # Calculate start_ms and end_ms for events
    events: list[dict[str, Any]] = []
    num_events = len(raw_events)
    for idx, ev in enumerate(raw_events):
        first_token = ev["lines"][0][0]
        last_token = ev["lines"][-1][-1]

        start_ms = first_token["start_ms"]
        fin_ultimo_token = last_token["end_ms"]

        if idx + 1 < num_events:
            siguiente_start_ms = raw_events[idx + 1]["lines"][0][0]["start_ms"]
            raw_end = min(siguiente_start_ms, fin_ultimo_token + 400)
        else:
            raw_end = fin_ultimo_token + 400

        end_ms = min(raw_end, duration_ms)
        if end_ms < start_ms:
            end_ms = start_ms

        event_dict = {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "lines": ev["lines"],
            "size": ev["size"],
            "emphasis": ev["emphasis"],
        }
        CaptionEvent.model_validate(event_dict)
        events.append(event_dict)

    return events


def build_ir_stage1(
    timeline: dict[str, Any],
    captions_words: list[dict[str, Any]],
    frame_zero_text: str | None,
    style: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """RenderIR v1 (dict) con frame_zero + captions; zoom_keys/transitions/overlays/sfx vacíos.

    Siempre pasa RenderIR.model_validate antes de devolver.
    """
    duration_ms = int(timeline.get("duration_ms", 0))
    caption_y = clamp_caption_y((settings or {}).get("caption_y", CAPTION_Y_DEFAULT))

    if frame_zero_text and frame_zero_text.strip():
        fz_end = min(1500, duration_ms)
        fz_dict = {
            "text": frame_zero_text.strip()[:80],
            "start_ms": 0,
            "end_ms": fz_end,
        }
        FrameZero.model_validate(fz_dict)
        frame_zero: dict[str, Any] | None = fz_dict
    else:
        fz_end = 0
        frame_zero = None

    events = caption_events(captions_words, duration_ms, fz_end=fz_end)

    ir_dict: dict[str, Any] = {
        "schema": "brandstudio.ir.v1",
        "duration_ms": duration_ms,
        "frame_zero": frame_zero,
        "captions": events,
        "zoom_keys": [],
        "transitions": [],
        "overlays": [],
        "sfx": [],
        "style": style,
        "layout": {"caption_y": caption_y},
    }

    RenderIR.model_validate(ir_dict)
    return ir_dict


def _next_transition_in_cycle(tr: str) -> str:
    if tr == "flash":
        return "zoom_through"
    if tr == "zoom_through":
        return "whip"
    if tr == "whip":
        return "flash"
    return "flash"


def _clip_zoom_block(
    keys: list[dict[str, Any]], fin_escena: int
) -> list[dict[str, Any]]:
    if not keys:
        return []
    kept = [dict(k) for k in keys if k["t_ms"] < fin_escena]
    if len(kept) < len(keys):
        if kept:
            target_t = fin_escena - 1
            if target_t > kept[-1]["t_ms"]:
                kept.append({
                    "t_ms": target_t,
                    "scale": 1.0,
                    "cx": 0.5,
                    "cy": 0.4,
                    "ease": "linear",
                })
            else:
                kept[-1]["scale"] = 1.0
                kept[-1]["ease"] = "linear"
    return kept


def _format_card_stat_text(base_text: str) -> str:
    m = re.search(r"\d+(?:[.,]\d+)?\s*%?", base_text)
    if not m:
        return base_text
    num_str = m.group(0).strip()
    rest_before = base_text[: m.start()]
    rest_after = base_text[m.end() :]
    rest = f"{rest_before} {rest_after}".strip()
    rest = re.sub(r"^\s*[-·.,:]+\s*", "", rest).strip()
    rest = re.sub(r"\s+", " ", rest)
    if rest:
        return f"{num_str} · {rest}"
    return num_str


def build_ir_stage2(
    timeline: dict[str, Any],
    captions_words: list[dict[str, Any]],
    frame_zero_text: str | None,
    style: dict[str, Any],
    dressing: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    sfx_library: list[dict[str, Any]] | None = None,
    script: dict[str, Any] | None = None,
    jobs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build stage 2 RenderIR dictionary with zoom_keys, transitions, overlays, sfx, and emphasis.

    Returns:
        {"ir": RenderIR dict validado, "sfx_inputs": {input_id: {"storage_path": "...", "kind": "audio" | "image"}}}
    """
    ir_stage1 = build_ir_stage1(timeline, captions_words, frame_zero_text, style, settings=settings)
    duration_ms = ir_stage1["duration_ms"]

    if sfx_library is None:
        sfx_library = load_sfx_library()

    timeline_scenes = timeline.get("scenes", [])
    dressing_scenes = dressing.get("scenes", [])
    dressing_by_n = {
        int(s["n"]): s
        for s in dressing_scenes
        if isinstance(s, dict) and "n" in s and isinstance(s.get("n"), int)
    }

    script_scenes_map: dict[int, dict[str, Any]] = {}
    if isinstance(script, dict) and isinstance(script.get("scenes"), list):
        for ss in script["scenes"]:
            if isinstance(ss, dict) and "n" in ss:
                try:
                    script_scenes_map[int(ss["n"])] = ss
                except (ValueError, TypeError):
                    pass

    def _get_ai_image_storage_path(scene_m: int) -> str | None:
        if not isinstance(jobs, list):
            return None
        matching = []
        for j in jobs:
            if not isinstance(j, dict):
                continue
            if j.get("kind") == "ai_image" and j.get("status") == "done":
                j_scene = j.get("scene_n")
                if j_scene is not None:
                    try:
                        if int(j_scene) == scene_m:
                            matching.append(j)
                    except (ValueError, TypeError):
                        pass
        if not matching:
            return None
        latest = matching[-1]
        out = latest.get("output", {})
        if isinstance(out, dict):
            sp = out.get("storage_path")
            if sp and str(sp).strip():
                return str(sp).strip()
        return None

    # 1. Transitions
    resolved_transitions: list[str] = []
    transition_cues: list[dict[str, Any]] = []

    for idx, scene in enumerate(timeline_scenes):
        n = int(scene.get("n", idx + 1))
        phase = str(scene.get("phase", ""))
        out_start_ms = int(scene.get("out_start_ms", 0))
        ds = dressing_by_n.get(n, {})
        raw_tr = str(ds.get("transition_in", "cut"))

        if idx == 0:
            tr = "cut"
        else:
            prev_phase = str(timeline_scenes[idx - 1].get("phase", ""))
            allowed_phase_change = (prev_phase == "hook") or (
                phase in ("rehook", "close_cta")
            )
            if allowed_phase_change:
                tr = raw_tr
            else:
                tr = "cut"

        if tr != "cut":
            if (
                resolved_transitions
                and resolved_transitions[-1] != "cut"
                and tr == resolved_transitions[-1]
            ):
                tr = _next_transition_in_cycle(tr)

        resolved_transitions.append(tr)

        if tr != "cut":
            dur_ms = TRANSITION_DURATIONS.get(tr, 200)
            cue_dict = {
                "at_ms": out_start_ms,
                "type": tr,
                "dur_ms": dur_ms,
            }
            TransitionCue.model_validate(cue_dict)
            transition_cues.append(cue_dict)

    # 2. Overlays
    POSITION_BOXES = {
        "top": (90, 260, 900, 300),
        "center": (90, 760, 900, 400),
        "lower_third": (90, 1300, 900, 200),
        "left": (60, 700, 420, 420),
        "right": (600, 700, 420, 420),
    }

    raw_overlay_candidates: list[dict[str, Any]] = []

    for idx, scene in enumerate(timeline_scenes):
        n = int(scene.get("n", idx + 1))
        out_end_ms = int(scene.get("out_end_ms", 0))
        ds = dressing_by_n.get(n, {})
        dressing_overlays = (
            ds.get("overlays", []) if isinstance(ds.get("overlays"), list) else []
        )
        sfx_tags = ds.get("sfx_tags", {})
        sfx_ov_tag = (
            str(sfx_tags.get("overlay", "pop"))
            if isinstance(sfx_tags, dict)
            else "pop"
        )
        seed = int(ds.get("seed", n))

        scene_cw = [cw for cw in captions_words if int(cw.get("scene_n", -1)) == n]
        scene_cw.sort(key=lambda cw: int(cw.get("start_ms", 0)))

        script_s = script_scenes_map.get(n, {})
        ost = str(script_s.get("on_screen_text", "") or "").strip()
        spk = str(script_s.get("spoken_text", "") or "").strip()

        for k, ov in enumerate(dressing_overlays):
            if not isinstance(ov, dict):
                continue
            kind = str(ov.get("kind", ""))
            w_idx = ov.get("word_idx")
            ov_dur_ms = int(ov.get("duration_ms", 1200))
            position = str(ov.get("position", "lower_third"))

            if not isinstance(w_idx, int) or not (0 <= w_idx < len(scene_cw)):
                continue

            start_ms = int(scene_cw[w_idx].get("start_ms", 0))

            if start_ms < 1500:
                continue

            raw_end_ms = start_ms + ov_dur_ms
            end_ms = min(raw_end_ms, out_end_ms)

            if end_ms - start_ms < 600:
                continue

            bx, by, bw, bh = POSITION_BOXES.get(position, (90, 1300, 900, 200))
            if kind == "emoji":
                w = 220
                h = 220
                x = bx + (bw - 220) // 2
                y = by + (bh - 220) // 2
            else:
                x, y, w, h = bx, by, bw, bh

            text: str | None = None
            asset: str | None = None
            extra_image: tuple[str, str] | None = None

            if kind == "broll_card":
                broll_scene = ov.get("broll_scene")
                if not isinstance(broll_scene, int):
                    continue
                sp = _get_ai_image_storage_path(broll_scene)
                if not sp:
                    continue
                asset_id = f"card_img_s{broll_scene}"
                asset = asset_id
                text = None
                extra_image = (asset_id, sp)
            elif kind == "emoji":
                emoji_val = ov.get("emoji")
                if not emoji_val or not isinstance(emoji_val, str):
                    continue
                asset = emoji_val
                text = None
            else:
                asset = None
                base_text = ost
                if not base_text and spk:
                    words_spk = spk.split()[:8]
                    base_text = " ".join(words_spk)

                if not base_text:
                    continue

                if kind == "card_stat":
                    text_formatted = _format_card_stat_text(base_text)
                else:
                    text_formatted = base_text

                text = text_formatted[:80]

            ov_id = f"ov_s{n}_{k}"

            # E2-13: Conditional anim - set only for animated overlay kinds
            animated_kinds = {
                "stat_counter",
                "checklist",
                "arrow_callout",
                "lower_third_anim",
                "quote_reveal",
                "icon_pop",
                "progress_bar",
                "keyword_highlight",
            }
            anim = kind if kind in animated_kinds else None

            cue_dict = {
                "id": ov_id,
                "kind": kind,
                "asset": asset,
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "anim": anim,
            }

            raw_overlay_candidates.append({
                "cue": cue_dict,
                "extra_image": extra_image,
                "scene_n": n,
                "seed": seed,
                "sfx_ov_tag": sfx_ov_tag,
            })

    raw_overlay_candidates.sort(key=lambda c: (c["cue"]["start_ms"], c["scene_n"]))

    raw_overlay_candidates.sort(key=lambda c: (c["cue"]["start_ms"], c["scene_n"]))

    overlay_cues: list[dict[str, Any]] = []
    sfx_inputs: dict[str, dict[str, str]] = {}
    last_accepted_end = -1
    overlay_sfx_candidates: list[dict[str, Any]] = []

    # Parse overlay settings (E2-10)
    overlay_settings: dict[str, dict[str, Any]] = {}
    overlays_enabled = True
    if isinstance(settings, dict):
        overlays_enabled = bool(settings.get("overlays_enabled", True))
        raw_overlays_settings = settings.get("overlays", {})
        if isinstance(raw_overlays_settings, dict):
            overlay_settings = raw_overlays_settings

    for item in raw_overlay_candidates:
        cue = item["cue"]
        ov_id = cue["id"]

        # Apply overlay settings (E2-10)
        if ov_id in overlay_settings:
            ov_override = overlay_settings[ov_id]
            if isinstance(ov_override, dict):
                # Check if overlay is deleted
                if ov_override.get("deleted"):
                    continue
                # Apply text override if provided
                if "text" in ov_override:
                    new_text = ov_override["text"]
                    if isinstance(new_text, str):
                        # Apply caption sanitizer and E2-04 fit
                        sanitized = sanitize_text(new_text, 80)
                        if sanitized and cue["text"] is not None:
                            # Import text_fit locally to avoid circular import
                            from render_service.text_fit import fit_card_text

                            lines, font_px = fit_card_text(
                                sanitized,
                                cue["kind"],
                                cue["w"],
                                cue["h"],
                            )
                            # Reconstruct multi-line text with explicit <br>
                            cue["text"] = "<br>".join(lines)
                # E2-13: Apply params override if provided
                if "params" in ov_override:
                    params_override = ov_override["params"]
                    if isinstance(params_override, dict):
                        cue["params"] = params_override

        if cue["start_ms"] < last_accepted_end:
            continue

        OverlayCue.model_validate(cue)
        overlay_cues.append(cue)
        last_accepted_end = cue["end_ms"]

        if item["extra_image"]:
            asset_id, sp = item["extra_image"]
            sfx_inputs[asset_id] = {
                "storage_path": sp,
                "kind": "image",
            }

        sfx_ov_tag = item["sfx_ov_tag"]
        # Only add overlay SFX if overlays are enabled (E2-10)
        if sfx_ov_tag != "none" and overlays_enabled:
            overlay_sfx_candidates.append({
                "raw_at": cue["start_ms"],
                "tag": sfx_ov_tag,
                "seed": item["seed"],
                "gain_db": -8.0,
                "scene_n": item["scene_n"],
                "type": "overlay",
            })

    # 3. SFX
    sfx_enabled = bool(timeline.get("settings", {}).get("sfx_enabled", False))
    sfx_cues: list[dict[str, Any]] = []

    if sfx_enabled:
        sfx_candidate_events = []

        if ir_stage1.get("frame_zero") is not None:
            ds1 = dressing_by_n.get(1, {})
            seed1 = int(ds1.get("seed", 1))
            sfx_candidate_events.append({
                "raw_at": 0,
                "tag": "pop",
                "seed": seed1,
                "gain_db": -8.0,
                "scene_n": 1,
                "type": "frame_zero_pop",
            })

        for idx, scene in enumerate(timeline_scenes):
            n = int(scene.get("n", idx + 1))
            phase = str(scene.get("phase", ""))
            visual = str(scene.get("visual", "face"))
            out_start_ms = int(scene.get("out_start_ms", 0))
            ds = dressing_by_n.get(n, {})
            seed = int(ds.get("seed", n))
            sfx_tags = ds.get("sfx_tags", {})
            tr_tag = (
                str(sfx_tags.get("transition", "whoosh"))
                if isinstance(sfx_tags, dict)
                else "whoosh"
            )

            tr = resolved_transitions[idx]

            # Transition SFX
            if tr != "cut" and tr_tag != "none":
                sfx_candidate_events.append({
                    "raw_at": out_start_ms - 150,
                    "tag": tr_tag,
                    "seed": seed,
                    "gain_db": -8.0,
                    "scene_n": n,
                    "type": "transition",
                })

            # Whoosh on entering broll scene (if not scene 1)
            if idx > 0 and visual == "broll" and tr_tag != "none":
                target_raw_at = out_start_ms - 150
                has_trans_sfx = any(
                    ev.get("type") == "transition"
                    and abs(ev.get("raw_at", 0) - target_raw_at) < 300
                    for ev in sfx_candidate_events
                )
                if not has_trans_sfx:
                    sfx_candidate_events.append({
                        "raw_at": target_raw_at,
                        "tag": tr_tag,
                        "seed": seed,
                        "gain_db": -8.0,
                        "scene_n": n,
                        "type": "transition",
                    })

            # Riser SFX
            if phase == "rehook":
                sfx_candidate_events.append({
                    "raw_at": out_start_ms - 800,
                    "tag": "riser",
                    "seed": seed,
                    "gain_db": -10.0,
                    "scene_n": n,
                    "type": "riser",
                })

            # Ding SFX
            if phase == "close_cta":
                sfx_candidate_events.append({
                    "raw_at": out_start_ms,
                    "tag": "ding",
                    "seed": seed,
                    "gain_db": -8.0,
                    "scene_n": n,
                    "type": "ding",
                })

        if overlay_sfx_candidates:
            sfx_candidate_events.extend(overlay_sfx_candidates)

        sfx_candidate_events.sort(
            key=lambda ev: (ev["raw_at"], ev["scene_n"], ev["type"])
        )

        last_file: str | None = None
        for ev in sfx_candidate_events:
            at_ms = min(max(0, ev["raw_at"]), duration_ms)
            tag = ev["tag"].lower()
            seed = ev["seed"]
            gain_db = ev["gain_db"]

            c_files = []
            for item in sfx_library:
                file_name = str(item.get("file", ""))
                tags = [str(t).lower() for t in item.get("tags", [])]
                if tag in tags or tag in file_name.lower():
                    c_files.append(file_name)

            c_files = sorted(list(set(c_files)))
            if not c_files:
                continue

            if last_file in c_files and len(c_files) > 1:
                available = [f for f in c_files if f != last_file]
            else:
                available = c_files

            available.sort()
            rng = random.Random(seed)
            chosen_file = rng.choice(available)
            last_file = chosen_file

            stem = Path(chosen_file).stem.lower()
            clean_stem = re.sub(r"[^a-z0-9_]", "_", stem)
            input_id = f"sfx_{clean_stem}"

            cue_dict = {
                "at_ms": at_ms,
                "input_id": input_id,
                "gain_db": gain_db,
            }
            SfxCue.model_validate(cue_dict)
            sfx_cues.append(cue_dict)

            sfx_inputs[input_id] = {
                "storage_path": f"library/sfx/{chosen_file}",
                "kind": "audio",
            }

    # 4. Zoom Keys
    all_zoom_keys: list[dict[str, Any]] = []

    for idx, scene in enumerate(timeline_scenes):
        n = int(scene.get("n", idx + 1))
        visual = str(scene.get("visual", "face"))
        out_start_ms = int(scene.get("out_start_ms", 0))
        out_end_ms = int(scene.get("out_end_ms", 0))
        tr = resolved_transitions[idx]

        if tr == "zoom_through":
            dur = 330
            zt_keys = [
                {
                    "t_ms": max(0, out_start_ms - 1),
                    "scale": 1.0,
                    "cx": 0.5,
                    "cy": 0.4,
                    "ease": "linear",
                },
                {
                    "t_ms": out_start_ms,
                    "scale": 1.5,
                    "cx": 0.5,
                    "cy": 0.4,
                    "ease": "linear",
                },
                {
                    "t_ms": out_start_ms + dur,
                    "scale": 1.0,
                    "cx": 0.5,
                    "cy": 0.4,
                    "ease": "out",
                },
            ]
            all_zoom_keys.extend(_clip_zoom_block(zt_keys, out_end_ms))

        if visual == "broll":
            continue

        scene_cw = [cw for cw in captions_words if int(cw.get("scene_n", -1)) == n]
        scene_cw.sort(key=lambda cw: int(cw.get("start_ms", 0)))

        ds = dressing_by_n.get(n, {})
        dressing_zooms = (
            ds.get("zooms", []) if isinstance(ds.get("zooms"), list) else []
        )

        candidate_zooms: list[tuple[int, str, str]] = []
        for z in dressing_zooms:
            if isinstance(z, dict):
                z_type = str(z.get("type", "punch_in"))
                z_intensity = str(z.get("intensity", "medium"))
                w_idx = z.get("word_idx")
                if isinstance(w_idx, int) and 0 <= w_idx < len(scene_cw):
                    w_start = int(scene_cw[w_idx].get("start_ms", 0))
                    candidate_zooms.append((w_start, z_type, z_intensity))

        candidate_zooms.sort(key=lambda x: x[0])

        accepted_zooms: list[tuple[int, str, str]] = []
        for t_zoom, z_type, z_intensity in candidate_zooms:
            if tr == "zoom_through" and t_zoom < out_start_ms + 400:
                continue
            if accepted_zooms and (t_zoom - accepted_zooms[-1][0] < 2500):
                continue
            accepted_zooms.append((t_zoom, z_type, z_intensity))

        # Gap filling > 6000 ms
        final_scene_zooms: list[tuple[int, str, str]] = []
        current_ref = out_start_ms
        zoom_idx = 0
        n_zooms = len(accepted_zooms)

        while True:
            if zoom_idx < n_zooms:
                next_t = accepted_zooms[zoom_idx][0]
                gap = next_t - current_ref
                if gap > 6000:
                    target_t = current_ref + 3000
                    found_w = None
                    for cw in scene_cw:
                        cw_start = int(cw.get("start_ms", 0))
                        if target_t <= cw_start < next_t:
                            found_w = cw_start
                            break
                    if found_w is not None and (
                        not final_scene_zooms
                        or found_w - final_scene_zooms[-1][0] >= 2500
                    ):
                        filler = (found_w, "slow_push", "soft")
                        final_scene_zooms.append(filler)
                        current_ref = found_w
                        continue
                final_scene_zooms.append(accepted_zooms[zoom_idx])
                current_ref = next_t
                zoom_idx += 1
            else:
                gap = out_end_ms - current_ref
                if gap > 6000:
                    target_t = current_ref + 3000
                    found_w = None
                    for cw in scene_cw:
                        cw_start = int(cw.get("start_ms", 0))
                        if target_t <= cw_start < out_end_ms:
                            found_w = cw_start
                            break
                    if found_w is not None and (
                        not final_scene_zooms
                        or found_w - final_scene_zooms[-1][0] >= 2500
                    ):
                        filler = (found_w, "slow_push", "soft")
                        final_scene_zooms.append(filler)
                        current_ref = found_w
                        continue
                break

        for t_zoom, z_type, z_intensity in final_scene_zooms:
            S = ZOOM_INTENSITIES.get(z_intensity, 1.15)
            if z_type == "punch_in":
                raw_keys = [
                    {
                        "t_ms": max(0, t_zoom),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "out",
                    },
                    {
                        "t_ms": max(0, t_zoom + 180),
                        "scale": S,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "out",
                    },
                    {
                        "t_ms": max(0, t_zoom + 1600),
                        "scale": S,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                    {
                        "t_ms": max(0, t_zoom + 2000),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                ]
            elif z_type == "punch_out":
                raw_keys = [
                    {
                        "t_ms": max(0, t_zoom - 1),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                    {
                        "t_ms": max(0, t_zoom),
                        "scale": S,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                    {
                        "t_ms": max(0, t_zoom + 300),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "out",
                    },
                ]
            elif z_type == "slow_push":
                raw_keys = [
                    {
                        "t_ms": max(0, t_zoom),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                    {
                        "t_ms": max(0, t_zoom + 3000),
                        "scale": S,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "linear",
                    },
                    {
                        "t_ms": max(0, t_zoom + 3300),
                        "scale": 1.0,
                        "cx": 0.5,
                        "cy": 0.4,
                        "ease": "out",
                    },
                ]
            else:
                raw_keys = []

            all_zoom_keys.extend(_clip_zoom_block(raw_keys, out_end_ms))

    # Sort and deduplicate zoom keys
    all_zoom_keys.sort(key=lambda k: (k["t_ms"], k["scale"], k["ease"]))
    for idx in range(1, len(all_zoom_keys)):
        if all_zoom_keys[idx]["t_ms"] <= all_zoom_keys[idx - 1]["t_ms"]:
            all_zoom_keys[idx]["t_ms"] = all_zoom_keys[idx - 1]["t_ms"] + 1

    all_zoom_keys = [k for k in all_zoom_keys if k["t_ms"] <= duration_ms]
    for k in all_zoom_keys:
        ZoomKey.model_validate(k)

    # 5. Emphasis
    emp_words_set: set[tuple[int, int, str]] = set()
    for scene in timeline_scenes:
        n = int(scene.get("n", 1))
        ds = dressing_by_n.get(n, {})
        emp_indices = (
            ds.get("emphasis_word_idx", [])
            if isinstance(ds.get("emphasis_word_idx"), list)
            else []
        )

        scene_cw = [cw for cw in captions_words if int(cw.get("scene_n", -1)) == n]
        scene_cw.sort(key=lambda cw: int(cw.get("start_ms", 0)))

        for idx in emp_indices:
            if isinstance(idx, int) and 0 <= idx < len(scene_cw):
                cw = scene_cw[idx]
                edited = cw.get("edited_text")
                txt = str(
                    edited
                    if edited is not None and str(edited).strip()
                    else cw.get("text", "")
                ).strip()[:40]
                start_m = max(0, int(cw.get("start_ms", 0)))
                emp_words_set.add((n, start_m, txt))

    # Process captions
    events = ir_stage1["captions"]
    for ev in events:
        tokens = [tok for line in ev["lines"] for tok in line]
        emp_list: list[int] = []
        for tok_idx, tok in enumerate(tokens):
            tok_start = tok["start_ms"]
            tok_txt = tok["text"]
            for cw in captions_words:
                start_m = max(0, int(cw.get("start_ms", 0)))
                if start_m == tok_start:
                    scene_n = int(cw.get("scene_n", 1))
                    if (scene_n, tok_start, tok_txt) in emp_words_set:
                        emp_list.append(tok_idx)
                    break
        ev["emphasis"] = emp_list
        CaptionEvent.model_validate(ev)

    # Use exactly the caption_y stage 1 put in layout (from `settings`, clamped)
    caption_y = clamp_caption_y(
        (ir_stage1.get("layout") or {}).get("caption_y", (settings or {}).get("caption_y", CAPTION_Y_DEFAULT))
    )

    # Define position boxes for collision resolution
    position_boxes = {
        "top": (90, 260, 900, 300),
        "center": (90, 760, 900, 400),
        "lower_third": (90, 1300, 900, 200),
        "left": (60, 700, 420, 420),
        "right": (600, 700, 420, 420),
    }

    # Resolve overlay-caption collisions
    resolved_overlays, filtered_captions, _ = _resolve_overlay_collisions(
        overlay_cues, events, caption_y, position_boxes
    )

    # Validate all overlays
    for ov in resolved_overlays:
        OverlayCue.model_validate(ov)

    # Update layout with caption_y
    layout_dict = ir_stage1["layout"] if "layout" in ir_stage1 else {"caption_y": caption_y}
    if "caption_y" not in layout_dict:
        layout_dict["caption_y"] = caption_y

    ir_dict: dict[str, Any] = {
        "schema": "brandstudio.ir.v1",
        "duration_ms": duration_ms,
        "frame_zero": ir_stage1["frame_zero"],
        "captions": filtered_captions,
        "zoom_keys": all_zoom_keys,
        "transitions": transition_cues,
        "overlays": resolved_overlays,
        "sfx": sfx_cues,
        "style": style,
        "layout": layout_dict,
    }

    RenderIR.model_validate(ir_dict)
    return {
        "ir": ir_dict,
        "sfx_inputs": sfx_inputs,
    }


