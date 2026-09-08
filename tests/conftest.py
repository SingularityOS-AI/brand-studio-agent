"""
pytest configuration for Brand Studio Agent

Sets TEST_MODE before any app imports to prevent database writes during tests.
"""

import os

# CRITICAL: Set TEST_MODE BEFORE any app.* imports
# This ensures guard.py and store.py use in-memory storage instead of Supabase
os.environ["TEST_MODE"] = "true"
