"""Tests for piece H8-01: no-collision (E2-07) uses the caption_y stage 1 puts in layout.

Before H8-01, stage 2 read caption_y from ``timeline["settings"]`` (never present), so the
collision math always used the default 1250 while the renderers drew captions at the real value.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from app.editing.ir import (
    _boxes_intersect,
    _calculate_caption_box,
    _resolve_overlay_collisions,
    build_ir_stage2,
)
from render_service.manifest import CAPTION_Y_DEFAULT, RenderIR

STYLE = {"font": "Inter", "text": "#FFFFFF", "accent": "#2B4CD8", "outline": "#000000"}

POSITION_BOXES = {
    "top": (90, 260, 900, 300),
    "center": (90, 760, 900, 400),
    "lower_third": (90, 1300, 900, 200),
    "left": (60, 700, 420, 420),
    "right": (600, 700, 420, 420),
}


def _timeline() -> dict[str, Any]:
    # Deliberately no caption_y anywhere in the timeline dict (as in production).
    return {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {"gap_ms": 400, "pad_ms": 100, "music_volume": 0.2, "music_muted": False, "sfx_enabled": False},
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "take_job_id": "job1",
                "take_input": "https://input1",
                "segments": [{"in_ms": 0, "out_ms": 10000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 10000,
            }
        ],
        "duration_ms": 10000,
        "hash": "test_hash_h8_01",
    }


def _words() -> list[dict[str, Any]]:
    # Continuous speech through the overlay window (3000..5000) so a caption is active at its midpoint.
    return [
        {"id": f"s1w{i}", "scene_n": 1, "text": f"Word{i}", "start_ms": 2000 + i * 400, "end_ms": 2300 + i * 400}
        for i in range(12)
    ]


def _dressing(position: str, kind: str) -> dict[str, Any]:
    return {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash_h8_01",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    {"kind": kind, "word_idx": 3, "duration_ms": 2000, "position": position},
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }


def _script() -> dict[str, Any]:
    return {"scenes": [{"n": 1, "on_screen_text": "On Screen", "spoken_text": "Word0 Word1 Word2"}]}


def _stage2(caption_y: int | None, position: str, kind: str) -> dict[str, Any]:
    settings: dict[str, Any] = {} if caption_y is None else {"caption_y": caption_y}
    res = build_ir_stage2(
        _timeline(), _words(), None, STYLE, _dressing(position, kind), settings=settings, script=_script()
    )
    RenderIR.model_validate(res["ir"])
    return res["ir"]


def _assert_clear_of_captions(ir: dict[str, Any]) -> None:
    caption_y = ir["layout"]["caption_y"]
    for ov in ir["overlays"]:
        if ov.get("hide_captions"):
            for cap in ir["captions"]:
                assert cap["end_ms"] <= ov["start_ms"] or cap["start_ms"] >= ov["end_ms"]
            continue
        ov_box = (ov["x"], ov["y"], ov["w"], ov["h"])
        for cap in ir["captions"]:
            if ov["end_ms"] <= cap["start_ms"] or ov["start_ms"] >= cap["end_ms"]:
                continue
            cap_box = _calculate_caption_box(caption_y, [cap], (ov["start_ms"] + ov["end_ms"]) // 2)
            if cap_box is not None:
                assert not _boxes_intersect(ov_box, cap_box)


def test_stage2_caption_y_1600_moves_lower_third_overlay():
    ir = _stage2(1600, "lower_third", "card_lower_third")
    assert ir["layout"]["caption_y"] == 1600
    assert len(ir["overlays"]) == 1
    ov = ir["overlays"][0]
    # Overlay was at y 1300 (h 200): it must have been moved or the captions hidden.
    assert ov["y"] != 1300 or ov["hide_captions"] is True
    _assert_clear_of_captions(ir)


def test_stage2_caption_y_520_moves_top_overlay():
    ir = _stage2(520, "top", "card_lower_third")
    assert ir["layout"]["caption_y"] == 520
    assert len(ir["overlays"]) == 1
    ov = ir["overlays"][0]
    # Overlay was at y 260 (h 300): it must have been moved or the captions hidden.
    assert ov["y"] != 260 or ov["hide_captions"] is True
    _assert_clear_of_captions(ir)


def test_stage2_default_caption_y_unchanged_when_setting_absent():
    ir = _stage2(None, "top", "card_lower_third")
    assert ir["layout"]["caption_y"] == CAPTION_Y_DEFAULT
    _assert_clear_of_captions(ir)


def test_stage2_layout_and_collision_share_one_caption_y():
    # An out-of-range value is clamped once in stage 1; stage 2 must use that same number.
    ir = _stage2(99999, "lower_third", "card_lower_third")
    assert ir["layout"]["caption_y"] != 99999
    _assert_clear_of_captions(ir)


def _caption_event(start_ms: int, end_ms: int, text: str) -> dict[str, Any]:
    lines = [[{"text": text, "start_ms": start_ms, "end_ms": end_ms}]]
    return {"start_ms": start_ms, "end_ms": end_ms, "lines": lines, "size": "block", "emphasis": []}


def _overlay(ov_id: str, kind: str, start_ms: int, end_ms: int, position: str) -> dict[str, Any]:
    x, y, w, h = POSITION_BOXES[position]
    return {
        "id": ov_id, "kind": kind, "asset": None, "text": "Test", "start_ms": start_ms, "end_ms": end_ms,
        "x": x, "y": y, "w": w, "h": h, "anim": "pop", "hide_captions": False,
    }


@pytest.mark.parametrize("seed", range(100))
@pytest.mark.parametrize("caption_y", [520, 1080, 1250, 1600])
def test_property_no_intersections_for_each_caption_y(seed: int, caption_y: int):
    rng = random.Random(seed * 10007 + caption_y)
    duration_ms = rng.randint(3000, 15000)
    captions = []
    for i in range(rng.randint(3, 10)):
        start = rng.randint(0, max(1, duration_ms - 1000))
        captions.append(_caption_event(start, min(start + rng.randint(500, 2000), duration_ms), f"Word{i}"))
    captions.sort(key=lambda e: e["start_ms"])
    overlays = []
    for i in range(rng.randint(1, 5)):
        start = rng.randint(1000, max(1001, duration_ms - 2000))
        overlays.append(
            _overlay(f"ov_{i}", rng.choice(["card_stat", "card_quote"]), start,
                     min(start + rng.randint(600, 2000), duration_ms), rng.choice(list(POSITION_BOXES)))
        )

    resolved, filtered, _ = _resolve_overlay_collisions(overlays, captions, caption_y, POSITION_BOXES)

    for ov in resolved:
        if ov.get("hide_captions"):
            continue
        ov_box = (ov["x"], ov["y"], ov["w"], ov["h"])
        for cap in filtered:
            if ov["end_ms"] <= cap["start_ms"] or ov["start_ms"] >= cap["end_ms"]:
                continue
            cap_box = _calculate_caption_box(caption_y, [cap], (ov["start_ms"] + ov["end_ms"]) // 2)
            if cap_box is not None:
                assert not _boxes_intersect(ov_box, cap_box)
