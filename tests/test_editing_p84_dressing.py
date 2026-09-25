"""Tests for PIEZA 84 — Catalog and Brandy Dressing (test_editing_p84_dressing.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.audiovisual.genai_client import set_genai_client
from app.editing.dressing import (
    Dressing,
    dress_all,
    fallback_dressing,
    load_catalog,
    scene_contexts,
)


class FakeResponse:

    def __init__(self, text: str):
        self.text = text


class FakeModels:

    def __init__(self, text_fn):
        self.text_fn = text_fn

    async def generate_content(self, model: str, contents: Any, config: Any = None):
        res = self.text_fn(model, contents, config)
        if asyncio.iscoroutine(res):
            res = await res
        return FakeResponse(res)


class FakeAio:

    def __init__(self, text_fn):
        self.models = FakeModels(text_fn)


class FakeGenAIClient:

    def __init__(self, text_fn):
        self.aio = FakeAio(text_fn)


@pytest.fixture(autouse=True)
def cleanup_genai_client():
    yield
    set_genai_client(None)


def test_1_load_catalog_sfx_tags():
    """Test 1: load_catalog() has the 5 sfx tags from sfx.json + none."""
    catalog = load_catalog()
    assert catalog["version"] == "v1"

    sfx_json_path = (
        Path(__file__).parent.parent
        / "app"
        / "audiovisual"
        / "library"
        / "sfx.json"
    )
    with open(sfx_json_path, "r", encoding="utf-8") as f:
        sfx_data = json.load(f)

    real_sfx_tags = set()
    for item in sfx_data:
        for tag in item.get("tags", []):
            if tag in ("whoosh", "pop", "click", "riser", "ding"):
                real_sfx_tags.add(tag)

    catalog_sfx_tags = set(catalog.get("sfx_tags", []))
    for expected in ("whoosh", "pop", "click", "riser", "ding", "none"):
        assert expected in catalog_sfx_tags, f"Missing {expected} in catalog"

    assert real_sfx_tags.issubset(catalog_sfx_tags)


def test_2_scene_contexts_indexing():
    """Test 2: scene_contexts indexes words starting at 0 and prefers edited_text."""
    timeline = {
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "out_start_ms": 0,
                "out_end_ms": 3000,
                "duration_ms": 3000,
                "broll": None,
            },
            {
                "n": 2,
                "phase": "body",
                "visual": "broll",
                "out_start_ms": 3000,
                "out_end_ms": 7000,
                "duration_ms": 4000,
                "broll": {"input_id": "broll_s2"},
            },
        ]
    }
    captions_words = [
        {
            "scene_n": 1,
            "text": "original_one",
            "edited_text": "edited_one",
            "start_ms": 200,
            "end_ms": 600,
        },
        {
            "scene_n": 1,
            "text": "original_two",
            "edited_text": None,
            "start_ms": 700,
            "end_ms": 1200,
        },
        {
            "scene_n": 2,
            "text": "original_three",
            "edited_text": "edited_three",
            "start_ms": 3200,
            "end_ms": 4000,
        },
    ]
    script = {
        "scenes": [
            {"n": 1, "on_screen_text": "Hook Title"},
            {"n": 2, "on_screen_text": "Body Title"},
        ]
    }

    ctxs = scene_contexts(timeline, captions_words, script)
    assert len(ctxs) == 2

    c1 = ctxs[0]
    assert c1["n"] == 1
    assert c1["on_screen_text"] == "Hook Title"
    assert len(c1["words"]) == 2
    assert c1["words"][0]["i"] == 0
    assert c1["words"][0]["text"] == "edited_one"
    assert c1["words"][0]["start_ms"] == 200
    assert c1["words"][1]["i"] == 1
    assert c1["words"][1]["text"] == "original_two"

    c2 = ctxs[1]
    assert c2["n"] == 2
    assert c2["has_broll"] is True
    assert c2["words"][0]["i"] == 0
    assert c2["words"][0]["text"] == "edited_three"
    assert c2["words"][0]["start_ms"] == 200  # 3200 - out_start(3000)


@pytest.mark.asyncio
async def test_3_dress_all_valid_llm():
    """Test 3: Valid LLM response -> source='llm', correct seeds and schema."""
    contexts = [
        {
            "n": 1,
            "phase": "hook",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "Hook",
            "words": [
                {"i": 0, "text": "hello", "start_ms": 0},
                {"i": 1, "text": "world", "start_ms": 500},
            ],
        }
    ]

    llm_payload = {
        "catalog_version": "v1",
        "scenes": [
            {
                "n": 1,
                "transition_in": "flash",
                "emphasis_word_idx": [0],
                "zooms": [
                    {"type": "punch_in", "word_idx": 1, "intensity": "strong"}
                ],
                "overlays": [
                    {
                        "kind": "onscreen_text",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "lower_third",
                        "accent": True,
                        "broll_scene": None,
                        "emoji": None,
                    }
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            }
        ],
    }

    def mock_genai(model, contents, config):
        return json.dumps(llm_payload)

    set_genai_client(FakeGenAIClient(mock_genai))

    res = await dress_all(contexts, raw_hash="hash123", seed_base=77)
    assert res["source"] == "llm"
    assert res["catalog_version"] == "v1"
    assert res["raw_hash"] == "hash123"

    scene1 = res["scenes"][0]
    assert scene1["n"] == 1
    assert scene1["seed"] == 77001
    assert scene1["transition_in"] == "flash"
    assert scene1["zooms"][0]["type"] == "punch_in"
    assert scene1["zooms"][0]["intensity"] == "strong"
    Dressing.model_validate(res)


@pytest.mark.asyncio
async def test_4_hostile_llm_output():
    """Test 4: Hostile LLM output is sanitized completely, no injection survives."""
    contexts = [
        {
            "n": 1,
            "phase": "hook",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "Hook",
            "words": [
                {"i": 0, "text": "test", "start_ms": 0},
                {"i": 1, "text": "code", "start_ms": 500},
            ],
        }
    ]

    hostile_payload = {
        "catalog_version": "v1",
        "scenes": [
            {
                "n": 1,
                "transition_in": "<script>alert(1)</script>",
                "emphasis_word_idx": [999],
                "zooms": [
                    {"type": "; rm -rf /", "word_idx": 999, "intensity": "super"},
                    {"type": "punch_in", "word_idx": 0, "intensity": "medium"},
                ],
                "overlays": [
                    {
                        "kind": "emoji",
                        "word_idx": 0,
                        "duration_ms": 2000,
                        "position": "javascript:",
                        "accent": False,
                        "emoji": "<img src=x>",
                    }
                ],
                "sfx_tags": {
                    "transition": "DROP TABLE",
                    "overlay": "cat /etc/passwd",
                },
                "html": "<b>x</b>",
                "seed": 666,
            }
        ],
    }

    def mock_genai(model, contents, config):
        return json.dumps(hostile_payload)

    set_genai_client(FakeGenAIClient(mock_genai))

    res = await dress_all(contexts, raw_hash="h456", seed_base=50)

    dumped = json.dumps(res)
    assert "<" not in dumped
    assert "rm -rf" not in dumped
    assert "javascript:" not in dumped
    assert "DROP TABLE" not in dumped

    scene1 = res["scenes"][0]
    assert scene1["seed"] == 50001
    assert scene1["transition_in"] == "cut"
    assert scene1["sfx_tags"]["transition"] == "whoosh"
    assert scene1["sfx_tags"]["overlay"] == "pop"
    assert len(scene1["zooms"]) == 1
    assert scene1["zooms"][0]["type"] == "punch_in"
    assert len(scene1["overlays"]) == 0
    Dressing.model_validate(res)


@pytest.mark.asyncio
async def test_5_limits_clamping_and_broll_zooms():
    """Test 5: duration_ms clamped to 3500, max 3 zooms, 0 zooms in broll scene."""
    contexts = [
        {
            "n": 1,
            "phase": "body",
            "visual": "face",
            "duration_ms": 5000,
            "has_broll": False,
            "on_screen_text": "Face Scene",
            "words": [{"i": idx, "text": f"w{idx}", "start_ms": idx * 300} for idx in range(10)],
        },
        {
            "n": 2,
            "phase": "body",
            "visual": "broll",
            "duration_ms": 4000,
            "has_broll": True,
            "on_screen_text": "Broll Scene",
            "words": [{"i": idx, "text": f"bw{idx}", "start_ms": idx * 300} for idx in range(5)],
        },
    ]

    llm_payload = {
        "catalog_version": "v1",
        "scenes": [
            {
                "n": 1,
                "transition_in": "cut",
                "emphasis_word_idx": [],
                "zooms": [
                    {"type": "punch_in", "word_idx": i, "intensity": "soft"}
                    for i in range(5)
                ],
                "overlays": [
                    {
                        "kind": "card_stat",
                        "word_idx": 0,
                        "duration_ms": 99999,
                        "position": "center",
                    }
                ],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
            {
                "n": 2,
                "transition_in": "flash",
                "emphasis_word_idx": [],
                "zooms": [
                    {"type": "slow_push", "word_idx": 0, "intensity": "medium"}
                ],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            },
        ],
    }

    def mock_genai(model, contents, config):
        return json.dumps(llm_payload)

    set_genai_client(FakeGenAIClient(mock_genai))

    res = await dress_all(contexts, raw_hash="lim", seed_base=1)

    s1 = res["scenes"][0]
    assert len(s1["zooms"]) == 3
    assert s1["overlays"][0]["duration_ms"] == 3500

    s2 = res["scenes"][1]
    assert len(s2["zooms"]) == 0  # broll scene discards zooms
    Dressing.model_validate(res)


@pytest.mark.asyncio
async def test_6_omitted_scene_filled_by_fallback():
    """Test 6: Scene omitted by LLM is filled by fallback dressing."""
    contexts = [
        {
            "n": 1,
            "phase": "hook",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "Hook",
            "words": [{"i": 0, "text": "hello", "start_ms": 0}],
        },
        {
            "n": 2,
            "phase": "body",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "Body",
            "words": [{"i": 0, "text": "there", "start_ms": 0}],
        },
    ]

    llm_payload = {
        "catalog_version": "v1",
        "scenes": [
            {
                "n": 1,
                "transition_in": "flash",
                "emphasis_word_idx": [],
                "zooms": [],
                "overlays": [],
                "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
            }
        ],
    }

    def mock_genai(model, contents, config):
        return json.dumps(llm_payload)

    set_genai_client(FakeGenAIClient(mock_genai))

    res = await dress_all(contexts, raw_hash="omit", seed_base=10)
    assert len(res["scenes"]) == 2
    assert res["scenes"][0]["n"] == 1
    assert res["scenes"][0]["transition_in"] == "flash"
    assert res["scenes"][1]["n"] == 2
    assert res["scenes"][1]["seed"] == 10002
    Dressing.model_validate(res)


@pytest.mark.asyncio
async def test_7_timeout_invalid_json_and_exception_fallback():
    """Test 7: Timeout, invalid JSON, or exception -> source='fallback'."""
    contexts = [
        {
            "n": 1,
            "phase": "hook",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "Hook",
            "words": [{"i": 0, "text": "word", "start_ms": 0}],
        }
    ]

    # 7A: Timeout
    async def timeout_genai(model, contents, config):
        await asyncio.sleep(0.5)
        return json.dumps({"catalog_version": "v1", "scenes": []})

    set_genai_client(FakeGenAIClient(timeout_genai))
    res_timeout = await dress_all(contexts, raw_hash="t1", seed_base=1, timeout_s=0.01)
    assert res_timeout["source"] == "fallback"

    # 7B: Invalid JSON
    def invalid_json_genai(model, contents, config):
        return "INVALID JSON NOT REAL"

    set_genai_client(FakeGenAIClient(invalid_json_genai))
    res_inv = await dress_all(contexts, raw_hash="t2", seed_base=1)
    assert res_inv["source"] == "fallback"

    # 7C: Exception
    def exc_genai(model, contents, config):
        raise RuntimeError("API Error 500")

    set_genai_client(FakeGenAIClient(exc_genai))
    res_exc = await dress_all(contexts, raw_hash="t3", seed_base=1)
    assert res_exc["source"] == "fallback"


def test_8_fallback_dressing_rules():
    """Test 8: Fallback rules for phase transitions and face scene zooms."""
    catalog = load_catalog()
    contexts = [
        {
            "n": 1,
            "phase": "hook",
            "visual": "face",
            "duration_ms": 2000,
            "has_broll": False,
            "on_screen_text": "Hook",
            "words": [{"i": 0, "text": "hey", "start_ms": 0}],
        },
        {
            "n": 2,
            "phase": "body",
            "visual": "face",
            "duration_ms": 5000,  # > 4s
            "has_broll": False,
            "on_screen_text": "Long Face Scene",
            "words": [
                {"i": 0, "text": "short", "start_ms": 100},
                {"i": 1, "text": "superlongword", "start_ms": 1000},
                {"i": 2, "text": "another", "start_ms": 4200},
            ],
        },
        {
            "n": 3,
            "phase": "rehook",
            "visual": "broll",
            "duration_ms": 2000,
            "has_broll": True,
            "on_screen_text": "",
            "words": [{"i": 0, "text": "watch", "start_ms": 0}],
        },
        {
            "n": 4,
            "phase": "close_cta",
            "visual": "face",
            "duration_ms": 3000,
            "has_broll": False,
            "on_screen_text": "CTA",
            "words": [{"i": 0, "text": "subscribe", "start_ms": 0}],
        },
    ]

    seeds = {1: 1001, 2: 1002, 3: 1003, 4: 1004}
    res = fallback_dressing(contexts, catalog, raw_hash="fb", seeds=seeds)
    assert res["source"] == "fallback"

    scenes = res["scenes"]
    transitions = [s["transition_in"] for s in scenes]

    # Verify no two adjacent transitions are identical
    for i in range(len(transitions) - 1):
        assert (
            transitions[i] != transitions[i + 1]
        ), f"Adjacent duplicate transition found at {i}: {transitions[i]}"

    # Verify phase-specific transitions match expected
    assert transitions[1] == "flash"  # scene following hook
    assert transitions[2] == "zoom_through"  # rehook
    assert transitions[3] == "whip"  # close_cta

    # Verify scene 2 (face scene > 4s) has at least one punch_in zoom
    s2 = scenes[1]
    assert len(s2["zooms"]) >= 1
    assert s2["zooms"][0]["type"] == "punch_in"
    assert s2["zooms"][0]["intensity"] == "medium"
    Dressing.model_validate(res)
