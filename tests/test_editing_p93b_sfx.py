"""Tests for SFX enhancements (whoosh on b-roll entry and pop on frame zero) - PIEZA 93B."""

from __future__ import annotations

import json
from typing import Any

from app.editing.ir import build_ir_stage2


def _base_style() -> dict[str, Any]:
    return {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }


def test_1_broll_entry_whoosh_and_dedup() -> None:
    """Timeline face -> broll -> face: whoosh 150ms before broll start; no duplicate within 300ms."""
    timeline = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "broll",
                "out_start_ms": 3000,
                "out_end_ms": 6000,
            },
            {
                "n": 3,
                "phase": "body_2",
                "visual": "face",
                "out_start_ms": 6000,
                "out_end_ms": 9000,
            },
        ],
        "duration_ms": 9000,
        "hash": "test_hash_p93b_1",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash1",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 2,
                "seed": 1002,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 3,
                "seed": 1003,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res = build_ir_stage2(timeline, [], None, _base_style(), dressing)
    sfx = res["ir"]["sfx"]
    sfx_inputs = res["sfx_inputs"]

    broll_whoosh_cues = [cue for cue in sfx if cue["at_ms"] == 2850]
    assert len(broll_whoosh_cues) == 1
    input_id = broll_whoosh_cues[0]["input_id"]
    assert "whoosh" in sfx_inputs[input_id]["storage_path"].lower()

    dressing_with_trans = json.loads(json.dumps(dressing))
    dressing_with_trans["scenes"][1]["transition_in"] = "flash"

    res2 = build_ir_stage2(timeline, [], None, _base_style(), dressing_with_trans)
    sfx2 = res2["ir"]["sfx"]
    near_2850_cues = [cue for cue in sfx2 if abs(cue["at_ms"] - 2850) < 300]
    assert len(near_2850_cues) == 1


def test_2_frame_zero_pop() -> None:
    """With frame zero: SFX pop at at_ms = 0; without frame zero: no SFX at 0ms."""
    timeline = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "out_start_ms": 0,
                "out_end_ms": 4000,
            }
        ],
        "duration_ms": 4000,
        "hash": "test_hash_p93b_2",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash2",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            }
        ],
    }

    # With frame zero
    res_fz = build_ir_stage2(timeline, [], "HERO TITLE", _base_style(), dressing)
    sfx_fz = res_fz["ir"]["sfx"]
    cues_at_0 = [cue for cue in sfx_fz if cue["at_ms"] == 0]
    assert len(cues_at_0) == 1
    input_id = cues_at_0[0]["input_id"]
    assert "pop" in res_fz["sfx_inputs"][input_id]["storage_path"].lower()

    # Without frame zero
    res_no_fz = build_ir_stage2(timeline, [], None, _base_style(), dressing)
    sfx_no_fz = res_no_fz["ir"]["sfx"]
    assert sfx_no_fz == []


def test_3_sfx_disabled_returns_empty() -> None:
    """sfx_enabled = False -> sfx == []."""
    timeline = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": False,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "broll",
                "out_start_ms": 0,
                "out_end_ms": 4000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "broll",
                "out_start_ms": 4000,
                "out_end_ms": 8000,
            },
        ],
        "duration_ms": 8000,
        "hash": "test_hash_p93b_3",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash3",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 2,
                "seed": 1002,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res = build_ir_stage2(timeline, [], "Title", _base_style(), dressing)
    assert res["ir"]["sfx"] == []
    assert res["sfx_inputs"] == {}


def test_4_determinism() -> None:
    """Same input -> same IR byte for byte."""
    timeline = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "out_start_ms": 0,
                "out_end_ms": 4000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "broll",
                "out_start_ms": 4000,
                "out_end_ms": 8000,
            },
        ],
        "duration_ms": 8000,
        "hash": "test_hash_p93b_4",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash4",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 2,
                "seed": 1002,
                "transition_in": "cut",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res1 = build_ir_stage2(timeline, [], "Frame Zero Title", _base_style(), dressing)
    res2 = build_ir_stage2(timeline, [], "Frame Zero Title", _base_style(), dressing)

    s1_ir = json.dumps(res1["ir"], sort_keys=True)
    s2_ir = json.dumps(res2["ir"], sort_keys=True)

    assert s1_ir == s2_ir
    assert res1["sfx_inputs"] == res2["sfx_inputs"]
