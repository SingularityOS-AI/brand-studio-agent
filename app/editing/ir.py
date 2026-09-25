"""RenderIR v1 stage 1: block captions and frame zero construction (Bloque E)."""

from __future__ import annotations

import re
from typing import Any

from render_service.manifest import CaptionEvent, CaptionToken, FrameZero, RenderIR

_PUNCT_END = re.compile(r"(\.|\?|\!|…|\.\.\.)$")


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

    Words starting before fz_end are ignored.
    Words starting in [fz_end, fz_end + 1500) -> single word 'hero' events.
    Words starting >= fz_end + 1500 -> 'block' events (up to 3 words).
    """
    valid_words = [w for w in words if max(0, int(w.get("start_ms", 0))) >= fz_end]
    valid_words.sort(key=lambda w: int(w.get("start_ms", 0)))

    hero_cutoff = fz_end + 1500
    hero_words = [w for w in valid_words if int(w.get("start_ms", 0)) < hero_cutoff]
    block_words = [w for w in valid_words if int(w.get("start_ms", 0)) >= hero_cutoff]

    raw_events: list[dict[str, Any]] = []

    # Process hero words: 1 word per event
    for w in hero_words:
        token = _format_token(w)
        raw_events.append({
            "size": "hero",
            "lines": [[token]],
            "emphasis": [],
            "words": [w],
        })

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
) -> dict[str, Any]:
    """RenderIR v1 (dict) con frame_zero + captions; zoom_keys/transitions/overlays/sfx vacíos.

    Siempre pasa RenderIR.model_validate antes de devolver.
    """
    duration_ms = int(timeline.get("duration_ms", 0))

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
    }

    RenderIR.model_validate(ir_dict)
    return ir_dict
