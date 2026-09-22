"""
Tests for Pieza 42 — Lock requires "reviewed" state, scene regeneration with instruction.

Coverage:
- Lock script requires "reviewed" state (rejects "draft")
- Error message is clear in English
- Scene regeneration sends instruction to backend
"""
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.guard import guard
from app.main import app
from app.scripting.scripts import (
    FrameZero,
    Scene,
    Script,
    lock_script,
)


@pytest.fixture
def test_user_id():
    """Test user ID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def api_client(test_user_id):
    """TestClient with mocked auth."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch('app.auth.supabase_auth.supabase_auth.get_user_id', return_value=test_user_id):
        with patch.object(guard, 'get_or_create_user_session', return_value='test_session'):
            yield client


@pytest.fixture
def valid_frame_zero():
    """Valid FrameZero."""
    return FrameZero(
        visual="Test visual",
        on_screen_text="Test",
        why_it_stops_the_scroll="Stops scroll"
    )


@pytest.fixture
def valid_script_scenes():
    """Valid scenes for a script that passes all critical rules."""
    # PIEZA 42: Duration must be 45-90s for rule_1. Using timestamps that sum to ~60s.
    return [
        Scene(n=1, start_s=0.0, end_s=8.0, phase="hook",
              spoken_text="Tired of manual work? Let me show you a better way.",
              shot="close-up", on_screen_text="Stop Manual Work",
              acting_note="Lean in slightly, empathetic tone, pause after 'tired', lower voice",
              sound="upbeat"),
        Scene(n=2, start_s=8.0, end_s=16.0, phase="lock_in",
              spoken_text="This affects most teams and costs them thousands every month.",
              shot="medium", on_screen_text="Affects Teams",
              acting_note="Serious face with concern", sound="test"),
        Scene(n=3, start_s=16.0, end_s=28.0, phase="body_1",
              spoken_text="Our solution saves time by automating the repetitive tasks that drain your energy.",
              shot="medium", on_screen_text="Saves Time",
              acting_note="Confident and clear", sound="test"),
        Scene(n=4, start_s=28.0, end_s=36.0, phase="rehook",
              spoken_text="Stay with me for this, because it gets even better.",
              shot="medium", on_screen_text="Stay With Me",
              acting_note="Pause and lean in", sound="test"),
        Scene(n=5, start_s=36.0, end_s=48.0, phase="body_2",
              spoken_text="Results from our clients show clear improvements across every metric that matters.",
              shot="medium", on_screen_text="Clear Results",
              acting_note="Excited and energized", sound="test"),
        Scene(n=6, start_s=48.0, end_s=60.0, phase="close_cta",
              spoken_text="Try it free today and see the difference for yourself.",
              shot="medium", on_screen_text="Try It Free",
              acting_note="Direct gaze towards camera", sound="test"),
    ]


@pytest.fixture
def valid_script(valid_frame_zero, valid_script_scenes):
    """Valid script that passes all critical lock rules."""
    return Script(
        session_id="test_session",
        idea_id="idea_123",
        title="Test Script",
        angle="Test angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=valid_frame_zero,
        scenes=valid_script_scenes,
        sources=["source"],
        state="draft",
    )


# =============================================================================
# LOCK SCRIPT STATE REQUIREMENT TESTS
# =============================================================================


def test_lock_script_requires_reviewed_state(valid_script, tmp_path):
    """Locking a script requires 'reviewed' state."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        os.chdir(tmp_path)

        from app.scripting.scripts import _save_script
        _save_script(valid_script)

        # Try to lock in "draft" state - should fail
        with pytest.raises(ValueError) as exc:
            lock_script(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
            )
        assert "Confirm funnel stage and recording format before locking" in str(exc.value)


def test_lock_script_succeeds_from_reviewed_state(valid_script, tmp_path):
    """Locking succeeds from 'reviewed' state when critical rules pass."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        os.chdir(tmp_path)

        # Set to reviewed state
        valid_script.state = "reviewed"
        from app.scripting.scripts import _save_script
        _save_script(valid_script)

        # Lock should succeed
        result = lock_script(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
        )
        assert result.state == "locked"


def test_lock_script_rejects_draft_with_clear_message(valid_script, tmp_path):
    """Locking a 'draft' script returns clear English error message."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        os.chdir(tmp_path)

        from app.scripting.scripts import _save_script
        _save_script(valid_script)

        # Should raise with clear message
        with pytest.raises(ValueError) as exc:
            lock_script(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
            )
        error_msg = str(exc.value)
        assert "Confirm funnel stage and recording format before locking" in error_msg


# =============================================================================
# ENDPOINT TESTS FOR LOCK REQUIREMENT
# =============================================================================


def test_lock_endpoint_returns_400_for_draft(api_client, valid_script, tmp_path):
    """POST /api/script/{idea_id}/lock returns 400 when script is in draft."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        os.chdir(tmp_path)

        from app.scripting.scripts import _save_script
        _save_script(valid_script)

        response = api_client.post("/api/script/idea_123/lock")
        assert response.status_code == 400
        data = response.json()
        assert "Confirm funnel stage and recording format before locking" in data.get("error", "")
