import json
import hashlib
from unittest.mock import patch, MagicMock

from app.editing.router import _state

@patch("app.editing.router.build_timeline")
@patch("app.editing.router.get_brand_brain")
@patch("app.editing.router.build_ir_stage2")
@patch("app.editing.router.get_engine_version")
@patch("app.editing.router.guard")
def test_render_price_first_time(mock_guard, mock_engine, mock_stage2, mock_bb, mock_bt):
    # Mocking build_timeline output
    mock_bt.return_value = {
        "timeline": {"scenes": [], "hash": "t1"},
        "captions_words": [],
        "missing_takes": [],
        "warnings": [],
        "inputs": {}
    }
    mock_bb.return_value = None
    mock_stage2.return_value = {"ir": {"foo": "bar"}, "sfx_inputs": {}}
    mock_engine.return_value = "v1"
    mock_guard.get_remaining_credits.return_value = 100

    script = {"frame_zero": {"on_screen_text": "hello"}}
    jobs = []
    edit = {
        "version": 1,
        "settings": {},
        "raw_render": {
            "status": "done",
            "storage_path": "raw.mp4",
            "timeline_hash": "t1"
        },
        "dressing": {
            "scenes": [{}],
            "raw_hash": "t1"
        }
    }

    state = _state("token", "idea_id", script, jobs, edit)
    assert state.get("render_price") == 20

@patch("app.editing.router.build_timeline")
@patch("app.editing.router.get_brand_brain")
@patch("app.editing.router.build_ir_stage2")
@patch("app.editing.router.get_engine_version")
@patch("app.editing.router.guard")
def test_render_price_same_ir_different_engine(mock_guard, mock_engine, mock_stage2, mock_bb, mock_bt):
    mock_bt.return_value = {
        "timeline": {"scenes": [], "hash": "t1"},
        "captions_words": [],
        "missing_takes": [],
        "warnings": [],
        "inputs": {}
    }
    mock_bb.return_value = None

    ir = {"foo": "bar"}
    mock_stage2.return_value = {"ir": ir, "sfx_inputs": {}}
    mock_engine.return_value = "v2"
    mock_guard.get_remaining_credits.return_value = 100

    script = {"frame_zero": {"on_screen_text": "hello"}}

    # We want idempotency key to use v1, which represents an old render.
    # And we need the current hash in the test to mismatch it so it knows it changed.
    old_full_str = json.dumps(ir, sort_keys=True) + "raw.mp4" + "v1"
    old_hash = hashlib.sha256(old_full_str.encode("utf-8")).hexdigest()[:20]

    jobs = [
        {
            "kind": "render",
            "status": "done",
            "created_at": "2024-01-01T00:00:00Z",
            "input": {
                "ir": ir,
                "raw_storage_path": "raw.mp4"
            },
            "idempotency_key": f"token:idea_id:render:{old_hash}:0"
        }
    ]
    edit = {
        "version": 1,
        "settings": {},
        "raw_render": {
            "status": "done",
            "storage_path": "raw.mp4",
            "timeline_hash": "t1"
        },
        "dressing": {
            "scenes": [{}],
            "raw_hash": "t1"
        }
    }

    state = _state("token", "idea_id", script, jobs, edit)
    assert state.get("render_price") == 0


@patch("app.editing.router.build_timeline")
@patch("app.editing.router.get_brand_brain")
@patch("app.editing.router.build_ir_stage2")
@patch("app.editing.router.get_engine_version")
@patch("app.editing.router.guard")
def test_render_price_same_ir_same_engine(mock_guard, mock_engine, mock_stage2, mock_bb, mock_bt):
    mock_bt.return_value = {
        "timeline": {"scenes": [], "hash": "t1"},
        "captions_words": [],
        "missing_takes": [],
        "warnings": [],
        "inputs": {}
    }
    mock_bb.return_value = None

    ir = {"foo": "bar"}
    mock_stage2.return_value = {"ir": ir, "sfx_inputs": {}}
    mock_engine.return_value = "v1"
    mock_guard.get_remaining_credits.return_value = 100

    script = {"frame_zero": {"on_screen_text": "hello"}}

    old_full_str = json.dumps(ir, sort_keys=True) + "raw.mp4" + "v1"
    old_hash = hashlib.sha256(old_full_str.encode("utf-8")).hexdigest()[:20]

    jobs = [
        {
            "kind": "render",
            "status": "done",
            "created_at": "2024-01-01T00:00:00Z",
            "input": {
                "ir": ir,
                "raw_storage_path": "raw.mp4"
            },
            "idempotency_key": f"token:idea_id:render:{old_hash}:0"
        }
    ]
    edit = {
        "version": 1,
        "settings": {},
        "raw_render": {
            "status": "done",
            "storage_path": "raw.mp4",
            "timeline_hash": "t1"
        },
        "dressing": {
            "scenes": [{}],
            "raw_hash": "t1"
        }
    }

    state = _state("token", "idea_id", script, jobs, edit)
    assert state.get("render_price") == 5
