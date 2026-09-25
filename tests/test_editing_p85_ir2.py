"""Tests for RenderIR stage 2: zooms, transitions, SFX, and emphasis (PIEZA 85)."""

from __future__ import annotations

import json
from typing import Any

from app.editing.ir import build_ir_stage2
from render_service.ffmpeg_dress import zoom_at
from render_service.manifest import RenderIR, ZoomKey


def _base_style() -> dict[str, Any]:
    return {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }


def test_1_punch_in_medium_zoom_at_values() -> None:
    """punch_in medium en una palabra a 5 s -> zoom_at da 1.0 a 4.9 s, 1.15 a 6 s y 1.0 a 7.2 s."""
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
        "hash": "test_hash_1",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Hola", "start_ms": 5000, "end_ms": 5400}
    ]

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash1",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [
                    {"type": "punch_in", "word_idx": 0, "intensity": "medium"}
                ],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing
    )
    ir = res["ir"]
    RenderIR.model_validate(ir)

    zk_models = [ZoomKey.model_validate(k) for k in ir["zoom_keys"]]
    scale_49, _, _ = zoom_at(zk_models, 4900)
    scale_60, _, _ = zoom_at(zk_models, 6000)
    scale_72, _, _ = zoom_at(zk_models, 7200)

    assert scale_49 == 1.0
    assert abs(scale_60 - 1.15) < 0.001
    assert scale_72 == 1.0


def test_2_zoom_distance_filter_and_slow_push_fill() -> None:
    """Dos zooms a 1 s de distancia -> sobrevive el primero; escena de 14 s sin zooms -> slow_push."""
    # Part A: Two zooms 1 s apart
    timeline_a = {
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
                "visual": "face",
                "take_job_id": "job1",
                "take_input": "https://input1",
                "segments": [{"in_ms": 0, "out_ms": 5000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 5000,
            }
        ],
        "duration_ms": 5000,
        "hash": "test_hash_2a",
    }
    words_a = [
        {"id": "s1w0", "scene_n": 1, "text": "Uno", "start_ms": 1000, "end_ms": 1300},
        {"id": "s1w1", "scene_n": 1, "text": "Dos", "start_ms": 2000, "end_ms": 2300},
    ]
    dressing_a = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash2a",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [
                    {"type": "punch_in", "word_idx": 0, "intensity": "soft"},
                    {"type": "punch_in", "word_idx": 1, "intensity": "strong"},
                ],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res_a = build_ir_stage2(
        timeline_a, words_a, None, _base_style(), dressing_a
    )
    zk_models_a = [ZoomKey.model_validate(k) for k in res_a["ir"]["zoom_keys"]]
    # Zoom at 2000 was filtered out, so at 2180 (1000+180) scale is 1.08 (soft) not 1.25 (strong)
    scale_2180, _, _ = zoom_at(zk_models_a, 1180)
    assert abs(scale_2180 - 1.08) < 0.001

    # Part B: 14 s scene without zooms gets filled by slow_push soft
    timeline_b = {
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
                "visual": "face",
                "take_job_id": "job1",
                "take_input": "https://input1",
                "segments": [{"in_ms": 0, "out_ms": 14000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 14000,
            }
        ],
        "duration_ms": 14000,
        "hash": "test_hash_2b",
    }
    words_b = [
        {"id": "s1w0", "scene_n": 1, "text": "Word1", "start_ms": 3200, "end_ms": 3500},
        {"id": "s1w1", "scene_n": 1, "text": "Word2", "start_ms": 6500, "end_ms": 6800},
        {"id": "s1w2", "scene_n": 1, "text": "Word3", "start_ms": 9800, "end_ms": 10100},
    ]
    dressing_b = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash2b",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res_b = build_ir_stage2(
        timeline_b, words_b, None, _base_style(), dressing_b
    )
    zk_models_b = [ZoomKey.model_validate(k) for k in res_b["ir"]["zoom_keys"]]
    assert len(zk_models_b) > 0
    # Evaluate slow_push at 3200+3000 = 6200
    scale_6200, _, _ = zoom_at(zk_models_b, 6200)
    assert scale_6200 > 1.0


def test_3_broll_scene_zooms_ignored() -> None:
    """Zooms en escena broll son ignorados."""
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
                "take_job_id": "job1",
                "take_input": "https://input1",
                "broll": {"kind": "stock", "input_id": "broll1"},
                "segments": [{"in_ms": 0, "out_ms": 8000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 8000,
            }
        ],
        "duration_ms": 8000,
        "hash": "test_hash_3",
    }
    words = [
        {"id": "s1w0", "scene_n": 1, "text": "BrollWord", "start_ms": 4000, "end_ms": 4300}
    ]
    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash3",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [{"type": "punch_in", "word_idx": 0, "intensity": "strong"}],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(timeline, words, None, _base_style(), dressing)
    assert res["ir"]["zoom_keys"] == []


def test_4_transition_rules_and_cycle() -> None:
    """flash tras body_1 -> cut; flash tras hook ok; 2 whips permitidos -> segundo pasa a flash."""
    # Part A: flash after body_1 -> cut
    timeline_a = {
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
                "visual": "face",
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "face",
                "take_job_id": "j2",
                "take_input": "https://i2",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 6000,
            },
            {
                "n": 3,
                "phase": "body_2",
                "visual": "face",
                "take_job_id": "j3",
                "take_input": "https://i3",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 6000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 6000,
                "out_end_ms": 9000,
            },
        ],
        "duration_ms": 9000,
        "hash": "test_hash_4a",
    }

    dressing_a = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash4a",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "flash",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 2,
                "seed": 1002,
                "transition_in": "flash",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 3,
                "seed": 1003,
                "transition_in": "flash",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res_a = build_ir_stage2(timeline_a, [], None, _base_style(), dressing_a)
    transitions_a = res_a["ir"]["transitions"]
    # Scene 1 is cut (not emitted). Scene 2 is after hook -> flash (at 3000 ms).
    # Scene 3 is body_2 after body_1 -> cut (not emitted).
    assert len(transitions_a) == 1
    assert transitions_a[0]["type"] == "flash"
    assert transitions_a[0]["at_ms"] == 3000

    # Part B: two consecutive whip transitions -> second becomes flash
    timeline_b = {
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
                "visual": "face",
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "rehook",
                "visual": "face",
                "take_job_id": "j2",
                "take_input": "https://i2",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 6000,
            },
            {
                "n": 3,
                "phase": "close_cta",
                "visual": "face",
                "take_job_id": "j3",
                "take_input": "https://i3",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 6000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 6000,
                "out_end_ms": 9000,
            },
        ],
        "duration_ms": 9000,
        "hash": "test_hash_4b",
    }

    dressing_b = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash4b",
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
                "transition_in": "whip",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 3,
                "seed": 1003,
                "transition_in": "whip",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res_b = build_ir_stage2(timeline_b, [], None, _base_style(), dressing_b)
    transitions_b = res_b["ir"]["transitions"]
    assert len(transitions_b) == 2
    assert transitions_b[0]["type"] == "whip"
    assert transitions_b[1]["type"] == "flash"  # Cycle after whip is flash


def test_5_zoom_through_keys() -> None:
    """zoom_through -> claves saltan a 1.5 en at y vuelven a 1.0 en at+330."""
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
                "visual": "face",
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "rehook",
                "visual": "face",
                "take_job_id": "j2",
                "take_input": "https://i2",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 6000,
            },
        ],
        "duration_ms": 6000,
        "hash": "test_hash_5",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash5",
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
                "transition_in": "zoom_through",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res = build_ir_stage2(timeline, [], None, _base_style(), dressing)
    zk_models = [ZoomKey.model_validate(k) for k in res["ir"]["zoom_keys"]]

    scale_3000, _, _ = zoom_at(zk_models, 3000)
    scale_3330, _, _ = zoom_at(zk_models, 3330)

    assert scale_3000 == 1.5
    assert scale_3330 == 1.0


def test_6_sfx_resolution_and_disabled_flag() -> None:
    """SFX: whoosh 150 ms antes de transición, riser antes de rehook, ding en close_cta; sfx_enabled=False -> vacíos."""
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
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "rehook",
                "visual": "face",
                "take_job_id": "j2",
                "take_input": "https://i2",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 6000,
            },
            {
                "n": 3,
                "phase": "close_cta",
                "visual": "face",
                "take_job_id": "j3",
                "take_input": "https://i3",
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 6000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 6000,
                "out_end_ms": 9000,
            },
        ],
        "duration_ms": 9000,
        "hash": "test_hash_6",
    }

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash6",
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
                "transition_in": "flash",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 3,
                "seed": 1003,
                "transition_in": "whip",
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    res = build_ir_stage2(timeline, [], None, _base_style(), dressing)
    sfx = res["ir"]["sfx"]
    sfx_inputs = res["sfx_inputs"]

    assert len(sfx) > 0
    assert len(sfx_inputs) > 0

    for input_id, input_info in sfx_inputs.items():
        assert input_info["storage_path"].startswith("library/sfx/")
        assert input_info["kind"] == "audio"

    # Verify no file is repeated twice in a row
    cues_files = [sfx_inputs[cue["input_id"]]["storage_path"] for cue in sfx]
    for i in range(1, len(cues_files)):
        assert cues_files[i] != cues_files[i - 1]

    # Part B: sfx_enabled = False
    timeline_disabled = dict(timeline)
    timeline_disabled["settings"] = dict(timeline["settings"])
    timeline_disabled["settings"]["sfx_enabled"] = False

    res_disabled = build_ir_stage2(
        timeline_disabled, [], None, _base_style(), dressing
    )
    assert res_disabled["ir"]["sfx"] == []
    assert res_disabled["sfx_inputs"] == {}


def test_7_zoom_block_clipped_at_scene_end() -> None:
    """Bloque de claves que cruza el fin de su escena se recorta y termina en 1.0."""
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
                "visual": "face",
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 4000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 4000,
            }
        ],
        "duration_ms": 4000,
        "hash": "test_hash_7",
    }
    words = [
        {"id": "s1w0", "scene_n": 1, "text": "Late", "start_ms": 3000, "end_ms": 3400}
    ]
    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash7",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [
                    {"type": "punch_in", "word_idx": 0, "intensity": "medium"}
                ],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(timeline, words, None, _base_style(), dressing)
    zk_list = res["ir"]["zoom_keys"]

    assert len(zk_list) > 0
    # All keys must be strictly < 4000
    for zk in zk_list:
        assert zk["t_ms"] < 4000

    # The last key should be at 3999 with scale 1.0
    last_key = zk_list[-1]
    assert last_key["t_ms"] == 3999
    assert last_key["scale"] == 1.0


def test_8_determinism() -> None:
    """Misma entrada -> mismo IR (byte a byte con json.dumps(sort_keys=True))."""
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
                "take_job_id": "j1",
                "take_input": "https://i1",
                "segments": [{"in_ms": 0, "out_ms": 4000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 4000,
            },
            {
                "n": 2,
                "phase": "rehook",
                "visual": "face",
                "take_job_id": "j2",
                "take_input": "https://i2",
                "segments": [{"in_ms": 0, "out_ms": 4000, "out_start_ms": 4000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 4000,
                "out_end_ms": 8000,
            },
        ],
        "duration_ms": 8000,
        "hash": "test_hash_8",
    }
    words = [
        {"id": "s1w0", "scene_n": 1, "text": "Start", "start_ms": 1000, "end_ms": 1300},
        {"id": "s2w0", "scene_n": 2, "text": "RehookWord", "start_ms": 5000, "end_ms": 5300},
    ]
    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash8",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [0],
                "zooms": [{"type": "punch_in", "word_idx": 0, "intensity": "soft"}],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            },
            {
                "n": 2,
                "seed": 1002,
                "transition_in": "flash",
                "emphasis_word_idx": [0],
                "zooms": [{"type": "slow_push", "word_idx": 0, "intensity": "medium"}],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            },
        ],
    }

    res1 = build_ir_stage2(timeline, words, "Hero Title", _base_style(), dressing)
    res2 = build_ir_stage2(timeline, words, "Hero Title", _base_style(), dressing)

    s1_ir = json.dumps(res1["ir"], sort_keys=True)
    s2_ir = json.dumps(res2["ir"], sort_keys=True)

    s1_inputs = json.dumps(res1["sfx_inputs"], sort_keys=True)
    s2_inputs = json.dumps(res2["sfx_inputs"], sort_keys=True)

    assert s1_ir == s2_ir
    assert s1_inputs == s2_inputs
