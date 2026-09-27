"""Tests for piece E2-07: no-collision overlay layout in the IR.

F2 (E2-D2). Overlays sometimes sit on top of captions (CEO video 0:08).
This piece ensures overlays never intersect caption boxes.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from app.editing.ir import (
    _boxes_intersect,
    _calculate_caption_box,
    _get_overlay_zone,
    _resolve_overlay_collisions,
)
from render_service.manifest import CAPTION_Y_DEFAULT

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "specs" / "evidence" / "E2-07"

SAMPLE_STYLE = {
    "font": "Inter",
    "text": "#FFFFFF",
    "accent": "#2B4CD8",
    "outline": "#000000",
}

# Position boxes from ir.py
POSITION_BOXES = {
    "top": (90, 260, 900, 300),
    "center": (90, 760, 900, 400),
    "lower_third": (90, 1300, 900, 200),
    "left": (60, 700, 420, 420),
    "right": (600, 700, 420, 420),
}


def _caption_event(start_ms: int, end_ms: int, text: str, num_lines: int = 1) -> dict[str, Any]:
    """Create a caption event for testing."""
    lines = []
    if num_lines == 1:
        lines = [[{"text": text, "start_ms": start_ms, "end_ms": end_ms}]]
    else:
        words = text.split()
        mid = len(words) // 2
        lines = [
            [{"text": " ".join(words[:mid]), "start_ms": start_ms, "end_ms": (start_ms + end_ms) // 2}],
            [{"text": " ".join(words[mid:]), "start_ms": (start_ms + end_ms) // 2, "end_ms": end_ms}],
        ]
    return {"start_ms": start_ms, "end_ms": end_ms, "lines": lines, "size": "block", "emphasis": []}


def _overlay(ov_id: str, kind: str, start_ms: int, end_ms: int, position: str = "lower_third") -> dict[str, Any]:
    """Create an overlay cue for testing."""
    bx, by, bw, bh = POSITION_BOXES.get(position, (90, 1300, 900, 200))
    if kind == "emoji":
        w, h = 220, 220
        x = bx + (bw - 220) // 2
        y = by + (bh - 220) // 2
    else:
        x, y, w, h = bx, by, bw, bh
    return {"id": ov_id, "kind": kind, "asset": None, "text": "Test" if kind != "emoji" else None,
            "start_ms": start_ms, "end_ms": end_ms, "x": x, "y": y, "w": w, "h": h, "anim": "pop", "hide_captions": False}


# Unit tests for helper functions

def test_boxes_intersect_overlapping():
    """Two boxes that share area should intersect."""
    assert _boxes_intersect((0, 0, 100, 100), (50, 50, 100, 100)) is True
    assert _boxes_intersect((50, 50, 100, 100), (0, 0, 100, 100)) is True


def test_boxes_intersect_separate():
    """Non-overlapping boxes should not intersect."""
    assert _boxes_intersect((0, 0, 100, 100), (200, 200, 100, 100)) is False


def test_calculate_caption_box_no_active_event():
    """Should return None when no caption event is active."""
    events = [_caption_event(1000, 2000, "Hello")]
    assert _calculate_caption_box(CAPTION_Y_DEFAULT, events, 500) is None


def test_calculate_caption_box_single_line():
    """Single line caption has correct height."""
    events = [_caption_event(0, 2000, "Hello", num_lines=1)]
    result = _calculate_caption_box(CAPTION_Y_DEFAULT, events, 1000)
    assert result is not None
    assert result[2] == 900  # width


def test_get_overlay_zone():
    """Zone detection based on overlay center y."""
    assert _get_overlay_zone((90, 260, 900, 300)) == "top"
    assert _get_overlay_zone((90, 760, 900, 400)) == "middle"
    assert _get_overlay_zone((90, 1300, 900, 200)) == "bottom"


def test_overlay_in_free_zone_no_collision():
    """Overlay in a zone away from captions should stay there."""
    caption_y = 1250
    captions = [_caption_event(0, 5000, "Hello")]
    overlays = [_overlay("ov1", "card_stat", 1000, 2000, position="top")]
    resolved, filtered, _ = _resolve_overlay_collisions(overlays, captions, caption_y, POSITION_BOXES)
    assert len(resolved) == 1
    assert resolved[0]["y"] == POSITION_BOXES["top"][1]


# Property test: 200 random configurations


def _generate_random_caption(idx: int, duration_ms: int) -> dict:
    start = random.randint(0, max(1, duration_ms - 1000))
    end = min(start + random.randint(500, 2000), duration_ms)
    return _caption_event(start, end, f"Word{idx}")


def _generate_random_overlay(idx: int, duration_ms: int) -> dict:
    start = random.randint(1000, max(1001, duration_ms - 2000))
    end = min(start + random.randint(600, 2000), duration_ms)
    kind = random.choice(["card_stat", "card_quote"])
    position = random.choice(list(POSITION_BOXES.keys()))
    return _overlay(f"ov_{idx}", kind, start, end, position)


@pytest.mark.parametrize("seed", range(200))
def test_property_no_overlay_intersects_caption(seed: int):
    """Property test: no overlay box should intersect caption box at same time."""
    random.seed(seed)
    duration_ms = random.randint(3000, 15000)
    caption_y = random.choice([520, 900, 1250, 1600])

    num_captions = random.randint(3, 10)
    captions = [_generate_random_caption(i, duration_ms) for i in range(num_captions)]
    captions.sort(key=lambda e: e["start_ms"])

    num_overlays = random.randint(1, 5)
    overlays = [_generate_random_overlay(i, duration_ms) for i in range(num_overlays)]

    resolved, filtered, _ = _resolve_overlay_collisions(overlays, captions, caption_y, POSITION_BOXES)

    for ov in resolved:
        if ov.get("hide_captions"):
            continue
        ov_box = (ov["x"], ov["y"], ov["w"], ov["h"])
        ov_start, ov_end = ov["start_ms"], ov["end_ms"]

        for cap in filtered:
            cap_start, cap_end = cap["start_ms"], cap["end_ms"]
            if ov_end <= cap_start or ov_start >= cap_end:
                continue
            mid_ms = (ov_start + ov_end) // 2
            cap_box = _calculate_caption_box(caption_y, [cap], mid_ms)
            if cap_box is None:
                continue
            assert not _boxes_intersect(ov_box, cap_box)
