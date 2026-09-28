"""
Tests for Piece E2-10: Overlay Controls (delete / edit text / on-off)

Requirements:
- All ops are free (no credit charging)
- Overlay modifications write to edit.settings.overlays only
- Content is validated against spec
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.supabase_auth import supabase_auth
from app.audiovisual.jobs import _reset_local_jobs
from app.editing import dispatch as dispatch_mod
from app.editing import router as router_mod
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_or_create_edit

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"authorization": "Bearer tok_test"}


class MockScript:
    """Mock script model for testing (1 scene, locked)."""

    def __init__(self) -> None:
        self.state = "locked"
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 10
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
        self.scenes = [
            {
                "n": 1,
                "start_s": 0.0,
                "end_s": 5.0,
                "phase": "hook",
                "spoken_text": "Spoken text for scene 1",
                "shot": "medium shot",
                "on_screen_text": "Text scene 1",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            }
        ]

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }



@pytest.fixture(autouse=True)
def reset_local_state(monkeypatch: pytest.MonkeyPatch):
    """Reset local edit state and mock dependencies before each test."""
    _reset_local_jobs()
    _reset_local_edits()
    router_mod._signed_url_cache.clear()
    dispatch_mod._reset_engine_version_cache()

    # Mock auth to accept "Bearer tok_test"
    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test"
    )

    # Mock credits (unused in overlay tests but required by editing codebase)
    monkeypatch.setattr("app.guard.guard.deduct_credits", lambda t, a: 100)
    monkeypatch.setattr("app.guard.guard.get_remaining_credits", lambda t: 100)
    monkeypatch.setattr("app.guard.guard.refund_credits", lambda t, a, s: 100)

    mock_script = MockScript()
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, idea: mock_script)
    yield


def _create_test_edit(idea_id: str = "idea_test_overlay") -> str:
    """Helper to create a test edit state directly."""
    get_or_create_edit(HEADERS["authorization"].replace("Bearer ", ""), idea_id)
    return idea_id


def test_overlay_delete():
    """Test overlay_delete operation"""
    idea_id = _create_test_edit()

    # First, get editing state to have a baseline
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    # Get an overlay id from IR if available
    overlay_id = "ov_s1_0"  # Use a known overlay id format

    # Delete overlay
    payload = {
        "op": "overlay_delete",
        "overlay_id": overlay_id,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()

    # Verify overlay deleted flag is set
    assert result["settings"].get("overlays", {}).get(overlay_id, {}).get("deleted") is True

    # Ensure no credit charge (these are free ops)
    assert result.get("credits_charged", 0) == 0


def test_overlay_text_edit():
    """Test overlay_text operation"""
    idea_id = _create_test_edit()

    # Get editing state
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    overlay_id = "ov_s1_0"
    new_text = "Custom overlay text"

    # Edit overlay text
    payload = {
        "op": "overlay_text",
        "overlay_id": overlay_id,
        "value": new_text,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()

    # Verify overlay text is updated
    assert result["settings"].get("overlays", {}).get(overlay_id, {}).get("text") == new_text

    # Ensure no credit charge
    assert result.get("credits_charged", 0) == 0


def test_overlay_text_max_length():
    """Test overlay_text validates max 80 characters"""
    idea_id = _create_test_edit()

    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    overlay_id = "ov_s1_0"
    # Text with exactly 80 chars
    new_text = "A" * 80

    payload = {
        "op": "overlay_text",
        "overlay_id": overlay_id,
        "value": new_text,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()
    assert result["settings"].get("overlays", {}).get(overlay_id, {}).get("text") == new_text

    # Try with 81 chars - should fail validation
    too_long_text = "B" * 81
    payload["value"] = too_long_text
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 422  # Validation error


def test_overlays_enabled_toggle():
    """Test overlays_enabled operation"""
    idea_id = _create_test_edit()

    # Get editing state
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    # Disable overlays
    payload = {
        "op": "overlays_enabled",
        "value": False,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()
    assert result["settings"].get("overlays_enabled") is False

    # Re-enable overlays
    payload["value"] = True
    payload["expected_version"] = result.get("edit_version", 1)
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()
    assert result["settings"].get("overlays_enabled") is True


def test_overlay_settings_do_not_modify_dressing():
    """Test overlay settings write to edit.settings.overlays, not edit.dressing"""
    idea_id = _create_test_edit()

    # Get initial state
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    initial_dressing = state.get("dressing", {})
    initial_dressing_json = str(initial_dressing)

    # Modify overlay
    payload = {
        "op": "overlay_text",
        "overlay_id": "ov_s1_0",
        "value": "Modified text",
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()

    # Verify dressing is unchanged
    new_dressing = result.get("dressing", {})
    new_dressing_json = str(new_dressing)
    assert initial_dressing_json == new_dressing_json

    # Verify overlay settings are in settings.overlays
    assert result["settings"].get("overlays", {}).get("ov_s1_0", {}).get("text") == "Modified text"


def test_overlay_delete_restore():
    """Test deleting and restoring an overlay"""
    idea_id = _create_test_edit()

    # Get editing state
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    overlay_id = "ov_s1_0"

    # Delete overlay
    payload = {
        "op": "overlay_delete",
        "overlay_id": overlay_id,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()
    assert result["settings"].get("overlays", {}).get(overlay_id, {}).get("deleted") is True

    # Restore by editing text (restores from deleted state per spec)
    payload = {
        "op": "overlay_text",
        "overlay_id": overlay_id,
        "value": "Restored text",
        "expected_version": result.get("edit_version", 1),
    }
    res = client.patch(
        f"/api/editing/{idea_id}/settings",
        headers=HEADERS,
        json=payload,
    )
    assert res.status_code == 200
    result = res.json()

    # Verify overlay is restored (deleted flag is gone or false)
    overlay_data = result["settings"].get("overlays", {}).get(overlay_id, {})
    assert overlay_data.get("deleted") is not True
    assert overlay_data.get("text") == "Restored text"


def test_overlays_disabled_no_sfx():
    """Test that overlays_enabled setting persists correctly (IR behavior is tested in integration)"""
    idea_id = _create_test_edit()

    # Get editing state
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()

    # Disable overlays
    payload = {
        "op": "overlays_enabled",
        "value": False,
        "expected_version": state.get("edit_version", 1),
    }
    res = client.patch(f"/api/editing/{idea_id}/settings", headers=HEADERS, json=payload)
    assert res.status_code == 200
    state = res.json()
    assert state["settings"].get("overlays_enabled") is False

    # Verify the setting is retrieved correctly
    res = client.get(f"/api/editing/{idea_id}", headers=HEADERS)
    assert res.status_code == 200
    state = res.json()
    assert state["settings"].get("overlays_enabled") is False

    # Re-enable overlays
    payload["value"] = True
    payload["expected_version"] = state.get("edit_version", 1)
    res = client.patch(f"/api/editing/{idea_id}/settings", headers=HEADERS, json=payload)
    assert res.status_code == 200
    state = res.json()
    assert state["settings"].get("overlays_enabled") is True

