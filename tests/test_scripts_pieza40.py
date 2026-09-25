"""
Tests for Pieza 40 — Bug fixes, rule redefinitions, and "reviewed" state.

Coverage:
- Critical rules fix: rule_3 and rule_7 now block locking
- Rule redefinitions: rule_2 (hook acting note), rule_11 (rhetorical devices), rule_13 (blacklist)
- New endpoint: PATCH /api/script/{idea_id} for confirming script
- State transitions: reviewed -> draft on content change
- 401 without token, 422 with invalid values
- Confirming doesn't charge credits
"""
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.guard import guard
from app.main import app
from app.scripting.scripts import (
    AUDIT_RULES,
    confirm_script,
    Script,
    Scene,
    FrameZero,
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
    return [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Tired of manual work? Let me show you a better way.",
              shot="close-up", on_screen_text="Stop Manual Work",
              acting_note="Lean in slightly, empathetic tone, pause after 'tired', lower voice",
              sound="upbeat"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="This affects most teams.",
              shot="medium", on_screen_text="Affects Teams",
              acting_note="Serious face", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Our solution saves time.",
              shot="medium", on_screen_text="Saves Time",
              acting_note="Confident", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Stay with me for this.",
              shot="medium", on_screen_text="Stay With Me",
              acting_note="Pause", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Results show clear improvements.",
              shot="medium", on_screen_text="Clear Results",
              acting_note="Excited", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Try it free today.",
              shot="medium", on_screen_text="Try It Free",
              acting_note="Direct gaze", sound="test"),
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
# CRITICAL RULES TESTS
# =============================================================================


def test_critical_rules_from_audit_rules():
    """
    Verify that critical rules are defined correctly in AUDIT_RULES.
    This test ensures the critical field is synced with the lock requirements.
    """
    critical_rules = [r for r in AUDIT_RULES if r.get("critical", False)]
    critical_ids = {r["rule"] for r in critical_rules}

    # Expected critical rules per PIEZA 40 & PIEZA 65 specs
    expected_ids = {
        "rule_1",   # Duration 45-90s
        "rule_3",   # Has all 6 phases
        "rule_4",   # Exactly 2 key points
        "rule_5",   # FrameZero stops scroll
        "rule_7",   # No "not X, it's Y" patterns
        "rule_8",   # No AI counterexamples
        "rule_9",   # All numbers have citations
        "rule_12",  # Has CTA
        "rule_14",  # Single language
    }

    assert critical_ids == expected_ids, f"Critical rules mismatch. Got: {critical_ids}"
    assert len(critical_rules) == 9, f"Expected 9 critical rules, got {len(critical_rules)}"


def test_critical_rules_have_names_matching_ids():
    """
    Verify critical rule names match their actual meaning.
    This catches docstring/code mismatches like the one fixed in PIEZA 40.
    """
    for rule in AUDIT_RULES:
        if rule.get("critical", False):
            # Verify the name is correct for the rule_id
            if rule["rule"] == "rule_1":
                assert "duration" in rule["name"].lower(), f"rule_1 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_3":
                assert "6 phases" in rule["name"].lower(), f"rule_3 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_4":
                assert "2 key points" in rule["name"].lower(), f"rule_4 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_5":
                assert "framezero" in rule["name"].lower() or "scroll" in rule["name"].lower(), f"rule_5 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_7":
                assert "not x, it's y" in rule["name"].lower(), f"rule_7 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_8":
                assert "ai counterexample" in rule["name"].lower(), f"rule_8 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_9":
                assert "citation" in rule["name"].lower(), f"rule_9 name mismatch: {rule['name']}"
            elif rule["rule"] == "rule_12":
                assert "cta" in rule["name"].lower(), f"rule_12 name mismatch: {rule['name']}"


# =============================================================================
# RULE 2: Hook acting note concrete
# =============================================================================

def test_rule_2_hook_acting_note_concrete_pass():
    """Rule 2 passes if hook acting_note is specific (>= 6 words)."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Hook text",
              shot="medium", on_screen_text="Hook",
              acting_note="Lean in with energy emphasizing the first word",  # 9 words
              sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_2 = next((f for f in findings if f.rule == "rule_2"), None)
    assert rule_2 is not None
    assert rule_2.status == "pass"


def test_rule_2_hook_acting_note_generic_fail():
    """Rule 2 fails if hook acting_note is generic (< 6 words)."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Hook text",
              shot="medium", on_screen_text="Hook",
              acting_note="Say it confidently",  # 3 words - too generic
              sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_2 = next((f for f in findings if f.rule == "rule_2"), None)
    assert rule_2 is not None
    assert rule_2.status == "fail"


# =============================================================================
# RULE 11: Rhetorical devices
# =============================================================================

def test_rule_11_rhetorical_question_ok():
    """Rule 11 passes with one rhetorical question."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Tired of work?",  # 1 question - OK
              shot="medium", on_screen_text="Hook",
              acting_note="test test test test test", sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_11 = next((f for f in findings if f.rule == "rule_11"), None)
    assert rule_11 is not None
    assert rule_11.status == "pass"


def test_rule_11_too_many_questions_fail():
    """Rule 11 fails with more than one rhetorical question."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Tired? Want help? Try this.",  # 2 questions - FAIL
              shot="medium", on_screen_text="Hook",
              acting_note="test test test test test", sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_11 = next((f for f in findings if f.rule == "rule_11"), None)
    assert rule_11 is not None
    assert rule_11.status == "fail"


# =============================================================================
# RULE 13: AI Blacklist
# =============================================================================

def test_rule_13_no_blacklist_words():
    """Rule 13 passes when no blacklist words present."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="Clean text without patterns",  # No blacklist words
              shot="medium", on_screen_text="Hook",
              acting_note="test test test test test", sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_13 = next((f for f in findings if f.rule == "rule_13"), None)
    assert rule_13 is not None
    assert rule_13.status == "pass"


def test_rule_13_blacklist_word_detected():
    """Rule 13 fails when blacklist word present (case insensitive)."""
    scenes = [
        Scene(n=1, start_s=0.0, end_s=3.0, phase="hook",
              spoken_text="We will DELVE into this",  # Blacklist word in caps
              shot="medium", on_screen_text="Hook",
              acting_note="test test test test test", sound="test"),
        Scene(n=2, start_s=3.0, end_s=8.0, phase="lock_in",
              spoken_text="Test", shot="medium", on_screen_text="L",
              acting_note="test", sound="test"),
        Scene(n=3, start_s=8.0, end_s=13.0, phase="body_1",
              spoken_text="Test", shot="medium", on_screen_text="B1",
              acting_note="test", sound="test"),
        Scene(n=4, start_s=13.0, end_s=18.0, phase="rehook",
              spoken_text="Test", shot="medium", on_screen_text="R",
              acting_note="test", sound="test"),
        Scene(n=5, start_s=18.0, end_s=23.0, phase="body_2",
              spoken_text="Test", shot="medium", on_screen_text="B2",
              acting_note="test", sound="test"),
        Scene(n=6, start_s=23.0, end_s=28.0, phase="close_cta",
              spoken_text="Test", shot="medium", on_screen_text="CTA",
              acting_note="test", sound="test"),
    ]

    script = Script(
        session_id="test", idea_id="idea_123", title="Test", angle="test",
        funnel_stage="tofu", target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="t", why_it_stops_the_scroll="w"),
        scenes=scenes,
    )

    from app.scripting.scripts import audit_script
    findings = audit_script(script)
    rule_13 = next((f for f in findings if f.rule == "rule_13"), None)
    assert rule_13 is not None
    assert rule_13.status == "fail"


# =============================================================================
# CONFIRM ENDPOINT TESTS (PATCH /api/script/{idea_id})
# =============================================================================

def test_confirm_script_endpoint_401_without_token(api_client):
    """Confirm endpoint returns 401 without JWT token."""
    # Create a client without auth token
    unauth_client = TestClient(app)
    response = unauth_client.patch(
        "/api/script/idea_123",
        json={"funnel_stage": "mofu", "recording_format": "dynamic"}
    )
    assert response.status_code == 401


def test_confirm_script_endpoint_422_invalid_funnel_stage(api_client):
    """Confirm endpoint returns 422 with invalid funnel_stage."""
    response = api_client.patch(
        "/api/script/idea_123",
        json={"funnel_stage": "invalid_stage", "recording_format": "dynamic"}
    )
    assert response.status_code == 422


def test_confirm_script_endpoint_422_invalid_recording_format(api_client):
    """Confirm endpoint returns 422 with invalid recording_format."""
    response = api_client.patch(
        "/api/script/idea_123",
        json={"funnel_stage": "tofu", "recording_format": "invalid_format"}
    )
    assert response.status_code == 422


# =============================================================================
# STATE TRANSITION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edit_scene_returns_to_draft(valid_script, tmp_path):
    """Editing scene text on reviewed script returns to draft."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        import os
        os.chdir(tmp_path)

        # Start as reviewed
        valid_script.state = "reviewed"
        from app.scripting.scripts import _save_script, update_scene_text, _check_script
        _save_script(valid_script)

        # Edit a scene
        updated = await update_scene_text(
            session_id=valid_script.session_id,
            idea_id=valid_script.idea_id,
            scene_n=1,
            spoken_text="Updated text"
        )

        # Should be back to draft
        assert updated.state == "draft"


def test_regenerate_scene_returns_to_draft(valid_script, tmp_path):
    """Regenerating scene on reviewed script returns to draft."""
    import asyncio
    os.chdir(tmp_path)

    # Start as reviewed
    valid_script.state = "reviewed"

    mock_response = Mock()
    mock_response.text = json.dumps({
        "spoken_text": "Regenerated text that is longer now",
        "shot": "close-up",
        "b_roll": None,
        "on_screen_text": "Regenerated",
        "acting_note": "New note is here with enough words",
        "sound": "upbeat"
    })

    with patch("app.scripting.scripts.get_brand_brain") as mock_get_brain, \
         patch("app.catalog.ideas._check_catalog_cache") as mock_cat_cache, \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel") as mock_model_class:

        mock_bb = Mock()
        type(mock_bb).sections = property(lambda self: [])
        mock_get_brain.return_value = mock_bb
        mock_cat_cache.return_value = Mock()
        mock_cat_cache.return_value.catalog_locked = True

        mock_model = AsyncMock()
        mock_model_class.return_value = mock_model
        mock_model.generate_content_async.return_value = mock_response

        from app.scripting.scripts import _save_script, regenerate_scene
        _save_script(valid_script)

        async def run_test():
            result = await regenerate_scene(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                scene_n=1,
                instruction="Make it punchier"
            )
            return result

        result = asyncio.run(run_test())

        # Should be back to draft
        assert result.state == "draft"


def test_cannot_confirm_locked_script(valid_script, tmp_path):
    """Cannot confirm (PATCH) a locked script."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        import os
        os.chdir(tmp_path)

        # Make script valid and lock it
        valid_script.state = "locked"
        from app.scripting.scripts import _save_script, confirm_script
        _save_script(valid_script)

        with pytest.raises(ValueError) as exc:
            confirm_script(
                session_id=valid_script.session_id,
                idea_id=valid_script.idea_id,
                funnel_stage="mofu",
                recording_format="dynamic"
            )
        assert "locked" in str(exc.value).lower()


def test_confirm_script_no_credit_charge(api_client, valid_script, tmp_path):
    """Confirming a script should NOT charge credits."""
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        import os
        os.chdir(tmp_path)

        from app.scripting.scripts import _save_script
        _save_script(valid_script)

        # Get initial credits
        from app.guard import guard
        initial_credits = guard.get_remaining_credits("test_session")

        # Confirm script
        response = api_client.patch(
            "/api/script/idea_123",
            json={"funnel_stage": "mofu", "recording_format": "dynamic"}
        )

        assert response.status_code == 200
        data = response.json()

        # Credits should be unchanged
        assert data["credits_remaining"] == initial_credits
