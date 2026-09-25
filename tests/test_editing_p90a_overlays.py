"""Tests for RenderIR stage 2: overlays and sfx_inputs image resolution (PIEZA 90A)."""

from __future__ import annotations

from typing import Any

from app.editing.ir import build_ir_stage2
from render_service.manifest import OverlayCue, RenderIR


def _base_style() -> dict[str, Any]:
    return {
        "font": "Inter",
        "text": "#FFFFFF",
        "accent": "#2B4CD8",
        "outline": "#000000",
    }


def test_1_onscreen_text_word_index_and_lower_third_box() -> None:
    """onscreen_text en lower_third sobre la palabra 3 (index 2) -> caja (90,1300,900,200), start_ms = inicio de esa palabra."""
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
        "hash": "test_hash_p90a_1",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Palabra1", "start_ms": 2000, "end_ms": 2300},
        {"id": "s1w1", "scene_n": 1, "text": "Palabra2", "start_ms": 2400, "end_ms": 2700},
        {"id": "s1w2", "scene_n": 1, "text": "Palabra3", "start_ms": 3000, "end_ms": 3300},
    ]

    script = {
        "scenes": [
            {
                "n": 1,
                "on_screen_text": "Texto en Pantalla",
                "spoken_text": "Palabra1 Palabra2 Palabra3",
            }
        ]
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
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    {
                        "kind": "onscreen_text",
                        "word_idx": 2,
                        "duration_ms": 2000,
                        "position": "lower_third",
                        "accent": False,
                        "broll_scene": None,
                        "emoji": None,
                    }
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, script=script
    )
    ir = res["ir"]
    RenderIR.model_validate(ir)

    overlays = ir["overlays"]
    assert len(overlays) == 1
    ov = OverlayCue.model_validate(overlays[0])

    assert ov.kind == "onscreen_text"
    assert ov.text == "Texto en Pantalla"
    assert ov.start_ms == 3000
    assert ov.end_ms == 5000
    assert (ov.x, ov.y, ov.w, ov.h) == (90, 1300, 900, 200)


def test_2_frame_zero_clipping_and_duration_filtering() -> None:
    """Overlay en [0,1500) descartado; overlay recortado al fin de su escena; descartado si queda < 600 ms."""
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
                "segments": [{"in_ms": 0, "out_ms": 5000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 5000,
            }
        ],
        "duration_ms": 5000,
        "hash": "test_hash_p90a_2",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Early", "start_ms": 1000, "end_ms": 1300},
        {"id": "s1w1", "scene_n": 1, "text": "Valid", "start_ms": 3000, "end_ms": 3300},
        {"id": "s1w2", "scene_n": 1, "text": "Short", "start_ms": 4600, "end_ms": 4800},
    ]

    script = {
        "scenes": [
            {
                "n": 1,
                "on_screen_text": "Capa de prueba",
                "spoken_text": "Early Valid Short",
            }
        ]
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
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    # 1. Overlay starting in frame zero [0, 1500) (word 0, 1000 ms) -> discarded
                    {
                        "kind": "onscreen_text",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "top",
                    },
                    # 2. Overlay starting at 3000 ms (word 1), duration 3000 ms, scene end 5000 ms -> clipped to 5000 ms (duration 2000 ms >= 600 ms) -> kept
                    {
                        "kind": "onscreen_text",
                        "word_idx": 1,
                        "duration_ms": 3000,
                        "position": "lower_third",
                    },
                    # 3. Overlay starting at 4600 ms (word 2), duration 1000 ms, scene end 5000 ms -> clipped to 5000 ms (duration 400 ms < 600 ms) -> discarded
                    {
                        "kind": "onscreen_text",
                        "word_idx": 2,
                        "duration_ms": 1000,
                        "position": "center",
                    },
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, script=script
    )
    overlays = res["ir"]["overlays"]
    assert len(overlays) == 1
    assert overlays[0]["start_ms"] == 3000
    assert overlays[0]["end_ms"] == 5000


def test_3_overlays_overlap_filtering() -> None:
    """Dos overlays solapados -> queda solo el primero."""
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
                "segments": [{"in_ms": 0, "out_ms": 10000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 10000,
            }
        ],
        "duration_ms": 10000,
        "hash": "test_hash_p90a_3",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "First", "start_ms": 2000, "end_ms": 2300},
        {"id": "s1w1", "scene_n": 1, "text": "Second", "start_ms": 3000, "end_ms": 3300},
    ]

    script = {
        "scenes": [
            {
                "n": 1,
                "on_screen_text": "Texto prueba",
                "spoken_text": "First Second",
            }
        ]
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
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    # Overlaps from 2000 to 4000
                    {
                        "kind": "onscreen_text",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "lower_third",
                    },
                    # Starts at 3000 < 4000 -> discarded
                    {
                        "kind": "card_lower_third",
                        "word_idx": 1,
                        "duration_ms": 2000,
                        "position": "top",
                    },
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, script=script
    )
    overlays = res["ir"]["overlays"]
    assert len(overlays) == 1
    assert overlays[0]["start_ms"] == 2000
    assert overlays[0]["end_ms"] == 4000


def test_4_card_stat_number_formatting() -> None:
    """card_stat con on_screen_text 'Reduce 40% la espera' -> el texto empieza con '40%'."""
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
                "segments": [{"in_ms": 0, "out_ms": 10000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 10000,
            }
        ],
        "duration_ms": 10000,
        "hash": "test_hash_p90a_4",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Reduce", "start_ms": 2000, "end_ms": 2300}
    ]

    script = {
        "scenes": [
            {
                "n": 1,
                "on_screen_text": "Reduce 40% la espera",
                "spoken_text": "Reduce la espera",
            }
        ]
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
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    {
                        "kind": "card_stat",
                        "word_idx": 0,
                        "duration_ms": 2500,
                        "position": "center",
                    }
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, script=script
    )
    overlays = res["ir"]["overlays"]
    assert len(overlays) == 1
    assert overlays[0]["text"].startswith("40%")
    assert overlays[0]["text"] == "40% · Reduce la espera"


def test_5_broll_card_with_ai_image_and_stock_fallback() -> None:
    """broll_card apuntando a ai_image -> asset='card_img_s2' y sfx_inputs registrado; apuntando a stock/missing -> descartado."""
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
                "segments": [{"in_ms": 0, "out_ms": 10000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 10000,
            }
        ],
        "duration_ms": 10000,
        "hash": "test_hash_p90a_5",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "ImageWord", "start_ms": 2000, "end_ms": 2300},
        {"id": "s1w1", "scene_n": 1, "text": "StockWord", "start_ms": 5000, "end_ms": 5300},
    ]

    jobs = [
        {
            "id": "job_img_1",
            "kind": "ai_image",
            "status": "done",
            "scene_n": 2,
            "output": {"storage_path": "ideas/123/scene2_ai_img.png"},
        },
        {
            "id": "job_stock_1",
            "kind": "stock",
            "status": "done",
            "scene_n": 3,
            "output": {"video_url": "https://pexels.com/v.mp4"},
        },
    ]

    dressing = {
        "catalog_version": "v1",
        "source": "fallback",
        "raw_hash": "hash5",
        "scenes": [
            {
                "n": 1,
                "seed": 1001,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    # broll_scene = 2 has done ai_image -> kept
                    {
                        "kind": "broll_card",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "center",
                        "broll_scene": 2,
                    },
                    # broll_scene = 3 has stock (no ai_image) -> discarded
                    {
                        "kind": "broll_card",
                        "word_idx": 1,
                        "duration_ms": 2000,
                        "position": "lower_third",
                        "broll_scene": 3,
                    },
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, jobs=jobs
    )
    overlays = res["ir"]["overlays"]
    sfx_inputs = res["sfx_inputs"]

    assert len(overlays) == 1
    assert overlays[0]["asset"] == "card_img_s2"
    assert overlays[0]["text"] is None
    assert "card_img_s2" in sfx_inputs
    assert sfx_inputs["card_img_s2"] == {
        "storage_path": "ideas/123/scene2_ai_img.png",
        "kind": "image",
    }


def test_6_overlay_sfx_pop_integration() -> None:
    """Cada overlay emite su SFX (pop) al start_ms si sfx_enabled=True y no repite archivo seguido."""
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
                "segments": [{"in_ms": 0, "out_ms": 10000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 10000,
            }
        ],
        "duration_ms": 10000,
        "hash": "test_hash_p90a_6",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Word1", "start_ms": 2000, "end_ms": 2300},
        {"id": "s1w1", "scene_n": 1, "text": "Word2", "start_ms": 6000, "end_ms": 6300},
    ]

    script = {
        "scenes": [
            {
                "n": 1,
                "on_screen_text": "Overlay Text",
                "spoken_text": "Word1 Word2",
            }
        ]
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
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [
                    {
                        "kind": "onscreen_text",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "top",
                    },
                    {
                        "kind": "card_lower_third",
                        "word_idx": 1,
                        "duration_ms": 2000,
                        "position": "lower_third",
                    },
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(
        timeline, captions_words, None, _base_style(), dressing, script=script
    )
    sfx = res["ir"]["sfx"]
    sfx_inputs = res["sfx_inputs"]

    overlay_sfx_cues = [c for c in sfx if c["at_ms"] in (2000, 6000)]
    assert len(overlay_sfx_cues) == 2

    files = [sfx_inputs[c["input_id"]]["storage_path"] for c in sfx]
    for i in range(1, len(files)):
        assert files[i] != files[i - 1]


def test_7_defaults_script_none_and_jobs_none_fallback() -> None:
    """Con script=None y jobs=None la función funciona; overlays de texto con respaldo a spoken_text -> si no hay texto, se descarta."""
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
                "segments": [{"in_ms": 0, "out_ms": 5000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 5000,
            }
        ],
        "duration_ms": 5000,
        "hash": "test_hash_p90a_7",
    }

    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "NoScriptWord", "start_ms": 2000, "end_ms": 2300}
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
                "zooms": [],
                "overlays": [
                    {
                        "kind": "onscreen_text",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "lower_third",
                    }
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                "stale": False,
            }
        ],
    }

    res = build_ir_stage2(timeline, captions_words, None, _base_style(), dressing)
    ir = res["ir"]
    RenderIR.model_validate(ir)

    assert ir["overlays"] == []
