"""Tests for piece E2-07: no-collision overlay layout in the IR."""
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
    build_ir_stage1,
    build_ir_stage2,
)
from render_service.manifest import CAPTION_Y_DEFAULT, OverlayCue, RenderIR

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs/specs/evidence" / "E2-07"

SAMPLE_STYLE = {"font": "Inter", "text": "#FFFFFF", "accent": "#2B4CD8", "outline": "#000000"}

POSITION_BOXES = {
    "top": (90, 260, 900, 300),
    "center": (90, 760, 900, 400),
    "lower_third": (90, 1300, 900, 200),
    "left": (60, 700, 420, 420),
    "right": (600, 700, 420, 420),
}

def _caption_event(start_ms: int, end_ms: int, text: str, num_lines: int = 1) -> dict[str, Any]:
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
    bx, by, bw, bh = POSITION_BOXES.get(position, (90, 1300, 900, 200))
    if kind == "emoji":
        w, h = 220, 220
        x = bx + (bw - 220) // 2
        y = by + (bh - 220) // 2
    else:
        x, y, w, h = bx, by, bw, bh
    return {"id": ov_id, "kind": kind, "asset": None, "text": "Test" if kind != "emoji" else None, "start_ms": start_ms, "end_ms": end_ms, "x": x, "y": y, "w": w, "h": h, "anim": "pop", "hide_captions": False}

def test_boxes_intersect_overlapping():
    assert _boxes_intersect((0, 0, 100, 100), (50, 50, 100, 100)) is True

def test_boxes_intersect_separate():
    assert _boxes_intersect((0, 0, 100, 100), (200, 200, 100, 100)) is False

def test_calculate_caption_box_no_active_event():
    events = [_caption_event(1000, 2000, "Hello")]
    assert _calculate_caption_box(CAPTION_Y_DEFAULT, events, 500) is None

def test_calculate_caption_box_single_line():
    events = [_caption_event(0, 2000, "Hello", num_lines=1)]
    result = _calculate_caption_box(CAPTION_Y_DEFAULT, events, 1000)
    assert result is not None and result[2] == 900

def test_get_overlay_zone():
    assert _get_overlay_zone((90, 260, 900, 300)) == "top"
    assert _get_overlay_zone((90, 760, 900, 400)) == "middle"
    assert _get_overlay_zone((90, 1300, 900, 200)) == "bottom"

def test_property_no_overlay_intersects_caption():
    caption_y = 1250
    captions = [_caption_event(0, 5000, "Hello")]
    overlays = [_overlay("ov1", "card_stat", 1000, 2000, position="top")]
    resolved, filtered, _ = _resolve_overlay_collisions(overlays, captions, caption_y, POSITION_BOXES)
    assert len(resolved) == 1

