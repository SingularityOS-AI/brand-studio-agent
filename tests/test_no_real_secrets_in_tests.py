"""
Tests that ensure the test suite never sees real production secrets.

These tests act as a safety lock: they prevent regression where someone might
reintroduce TEST_MODE or accidentally expose production secrets.
"""
import os
import re
from pathlib import Path

import pytest

from app.auth.supabase_auth import SupabaseAuth


class TestProductionIsolation:
    """
    Test that production code does not have backdoors for test mode.
    """

    def test_supabase_auth_does_not_enable_legacy_hmac_by_default(self, monkeypatch):
        """
        Test that a fresh SupabaseAuth instance has _force_legacy_hmac=False,
        even when TEST_MODE=true and SUPABASE_JWT_SECRET are set.

        This prevents regression where TEST_MODE accidentally enables legacy mode
        in production.
        """
        # Set TEST_MODE=true (someone might set this in production by mistake)
        monkeypatch.setenv("TEST_MODE", "true")
        monkeypatch.setenv("SUPABASE_JWT_SECRET", "some_secret_value")

        # Create a fresh instance (simulating production initialization)
        fresh_auth = SupabaseAuth(
            supabase_url="https://test.supabase.co",
        )

        # The key assertion: legacy HMAC must NOT be enabled by default
        assert fresh_auth._force_legacy_hmac is False, \
            "Fresh SupabaseAuth must NOT enable legacy HMAC even with TEST_MODE=true"
        assert fresh_auth._legacy_secret is None, \
            "Fresh SupabaseAuth must NOT have legacy_secret set"

    def test_no_test_mode_env_check_in_app_code(self):
        """
        Test that the app/ directory has NO executable reads of TEST_MODE.

        This prevents regression where someone adds:
        - os.environ.get("TEST_MODE")
        - os.getenv("TEST_MODE")
        to production code.

        Comments mentioning TEST_MODE are allowed (they're in app/catalog/ideas.py).
        """
        app_dir = Path(__file__).parent.parent / "app"
        assert app_dir.exists(), f"App directory not found: {app_dir}"

        # Regex to find executable reads of TEST_MODE
        # Matches: os.environ.get("TEST_MODE"), os.getenv("TEST_MODE"),
        # os.environ["TEST_MODE"], os.environ.get('TEST_MODE'), etc.
        test_mode_patterns = [
            re.compile(r'os\.environ\.get\s*\(\s*["\']TEST_MODE["\']\s*\)'),
            re.compile(r'os\.getenv\s*\(\s*["\']TEST_MODE["\']\s*\)'),
            re.compile(r'os\.environ\s*\[\s*["\']TEST_MODE["\']\s*\]'),
        ]

        violations = []

        for py_file in app_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, 1):
                # Skip comments (lines that start with # after strip)
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                # Check if this line contains TEST_MODE access
                for pattern in test_mode_patterns:
                    if pattern.search(line):
                        violations.append(
                            f"{py_file}:{line_num}: {line.strip()}"
                        )

        if violations:
            pytest.fail(
                "Found executable TEST_MODE reads in app/ code:\n"
                + "\n".join(violations)
                + "\n\nTEST_MODE should only be used in tests/, never in app/"
            )


class TestNoRealSecretsLeak:
    """
    Test that the test suite never loads real production secrets.
    """

    def test_supabase_secrets_are_fake(self):
        """
        Test that Supabase secrets are properly configured for tests.

        - SUPABASE_URL: fake test URL (needed for JWT issuer validation)
        - SUPABASE_KEY: empty string (falsy = in-memory mode, no real Supabase connection)
        """
        # URL must be the fake test URL, not a real one
        supabase_url = os.environ.get("SUPABASE_URL", "")
        assert supabase_url == "https://test.supabase.co", \
            f"SUPABASE_URL must be fake test URL, got: {supabase_url}"

        # SUPABASE_KEY should be empty (falsy) to force in-memory mode
        # This prevents tests from trying to connect to a real Supabase
        supabase_key = os.environ.get("SUPABASE_KEY", "")
        assert supabase_key == "", \
            f"SUPABASE_KEY must be empty (in-memory mode), got: '{supabase_key[:20]}...'"

    def test_stripe_secrets_are_test_keys(self):
        """
        Test that Stripe secrets are test keys (sk_test_ or pk_test_), never production.
        """
        stripe_secret = os.environ.get("STRIPE_SECRET_KEY", "")
        assert stripe_secret == "sk_test_fake_stripe_key_for_testing_only", \
            f"STRIPE_SECRET_KEY must be fake test key, got: {stripe_secret}"

        stripe_publishable = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
        assert stripe_publishable == "pk_test_fake_stripe_key_for_testing_only", \
            f"STRIPE_PUBLISHABLE_KEY must be fake test key, got: {stripe_publishable}"

    def test_assemblyai_key_is_fake(self):
        """
        Test that AssemblyAI key is fake, not a real key.
        """
        api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
        assert "test_" in api_key.lower(), \
            f"ASSEMBLYAI_API_KEY must be fake test key, got: {api_key[:20]}..."

    def test_youtube_api_key_is_fake(self):
        """
        Test that YouTube API key is fake, not a real key.
        """
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        assert "test_" in api_key.lower() or "fake" in api_key.lower(), \
            f"YOUTUBE_API_KEY must be fake test key (or empty), got: {api_key[:20]}..."

    def test_payment_url_is_fake(self):
        """
        Test that payment URL is the fake test URL, not a real one.
        """
        payment_url = os.environ.get("PAYMENT_URL", "")
        assert "test" in payment_url.lower() or "example" in payment_url.lower(), \
            f"PAYMENT_URL must be fake test URL, got: {payment_url}"
