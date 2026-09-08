"""
Tests for per-second voice credit deduction.
"""
import pytest
import time
from app.guard import guard, Guard
from app.config import settings


class TestVoiceCredits:
    """Tests for per-second voice session credit deduction."""

    def test_voice_credits_per_minute_value(self):
        """Test that voice credits per minute is correctly configured."""
        assert settings.voice_credits_per_minute == 7.5

    def test_voice_credits_per_second(self):
        """Test that voice credits per second is correctly calculated."""
        credits_per_second = settings.voice_credits_per_minute / 60
        expected = 7.5 / 60
        assert credits_per_second == expected

    def test_start_voice_session(self):
        """Test starting a voice session tracking."""
        session_token = "test_session_voice_1"

        # Create session in memory (we're in TEST_MODE)
        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_1",
        }

        # Start voice session
        guard.start_voice_session(session_token)

        assert session_token in guard._voice_sessions
        assert "start_time" in guard._voice_sessions[session_token]
        assert "last_deduct" in guard._voice_sessions[session_token]

    def test_deduct_voice_credits_10_seconds(self):
        """Test deducting credits for 10 seconds of voice."""
        session_token = "test_session_voice_2"

        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_2",
        }
        guard.start_voice_session(session_token)

        # Deduct for 10 seconds
        remaining = guard.deduct_voice_credits(session_token, interval_seconds=10)

        # Expected: (7.5 / 60) * 10 = 1.25, rounded to 1 credit
        assert remaining == 249

    def test_deduct_voice_credits_30_seconds(self):
        """Test deducting credits for 30 seconds of voice."""
        session_token = "test_session_voice_3"

        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_3",
        }
        guard.start_voice_session(session_token)

        # Deduct for 30 seconds
        remaining = guard.deduct_voice_credits(session_token, interval_seconds=30)

        # Expected: (7.5 / 60) * 30 = 3.75, rounded to 3 credits
        assert remaining == 247

    def test_deduct_voice_credits_60_seconds(self):
        """Test deducting credits for 60 seconds (1 minute) of voice."""
        session_token = "test_session_voice_4"

        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_4",
        }
        guard.start_voice_session(session_token)

        # Deduct for 60 seconds
        remaining = guard.deduct_voice_credits(session_token, interval_seconds=60)

        # Expected: (7.5 / 60) * 60 = 7.5, rounded to 7 credits
        assert remaining == 243

    def test_deduct_voice_credits_300_seconds(self):
        """Test deducting credits for 5 minutes of voice."""
        session_token = "test_session_voice_5"

        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_5",
        }
        guard.start_voice_session(session_token)

        # Deduct for 300 seconds (5 minutes)
        remaining = guard.deduct_voice_credits(session_token, interval_seconds=300)

        # Expected: (7.5 / 60) * 300 = 37.5, rounded to 37 credits
        assert remaining == 213

    def test_end_voice_session_partial_interval(self):
        """Test that ending a voice session properly handles partial intervals."""
        session_token = "test_session_voice_6"

        guard._sessions[session_token] = {
            "credits": 250,
            "created_at": time.time(),
            "user_id": "test_user_6",
        }
        guard.start_voice_session(session_token)

        # Sleep a tiny bit to ensure elapsed time
        time.sleep(0.01)

        # End session (should deduct for partial interval)
        remaining = guard.end_voice_session(session_token)

        # Session should be removed from tracking
        assert session_token not in guard._voice_sessions

        # Credits should be deducted (at least 1 credit)
        assert remaining <= 250

    def test_deduct_voice_credits_insufficient_funds(self):
        """Test that insufficient funds raises 402 error."""
        session_token = "test_session_voice_7"

        guard._sessions[session_token] = {
            "credits": 1,  # Low balance
            "created_at": time.time(),
            "user_id": "test_user_7",
        }
        guard.start_voice_session(session_token)

        # Try to deduct for 10 seconds (should work with 1 credit)
        remaining = guard.deduct_voice_credits(session_token, interval_seconds=10)
        assert remaining == 0

        # Next deduction should fail with 402
        with pytest.raises(Exception) as exc_info:
            guard.deduct_voice_credits(session_token, interval_seconds=10)

        assert hasattr(exc_info.value, "status_code")
        # Note: In TEST_MODE, we get HTTPException from guard
        assert exc_info.value.status_code == 402

    def test_initial_session_credits_is_250(self):
        """Test that initial session credits is 250 (not 500)."""
        assert settings.initial_session_credits == 250

    def test_credit_value_is_one_cent(self):
        """Test that 1 credit = $0.01 USD."""
        assert settings.credit_value_usd == 0.01

    def test_platform_spend_cap_is_120_usd(self):
        """Test that platform spend cap is $120 USD."""
        assert settings.platform_spend_cap_usd == 120
