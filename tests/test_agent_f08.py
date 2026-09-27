"""Tests for F-08 (Audiovisual Voice Tools) and F-10 (Proactive Job Announcements).

F-08 adds Audiovisual step voice tools:
- av_read_scene {scene_n} (free)
- av_set_scene_type {scene_n, type} (free)
- av_estimate (free)
- av_generate_all (confirm, cost is estimate total)
- av_regenerate_asset {scene_n, instruction?} (confirm)
- av_open_recording {scene_n} (free)

F-10 adds proactive job announcements:
- Spike & fallback mechanism for completed background jobs
- Queue mention in pending_announcements for idle Brandy turns
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENT_JS = REPO_ROOT / "app" / "static" / "agent.js"
ACTIONS_JS = REPO_ROOT / "app" / "static" / "actions.js"
MAIN_PY = REPO_ROOT / "app" / "main.py"
AV_TEST_JS = REPO_ROOT / "tests" / "agent_audiovisual.test.js"
ANNOUNCE_TEST_JS = REPO_ROOT / "tests" / "agent_announce.test.js"


def test_agent_js_exports_f08_api():
    """Verify agent.js exports F-08 and F-10 functions and schemas."""
    content = AGENT_JS.read_text(encoding="utf-8")

    assert "avReadScene" in content
    assert "AUDIOVISUAL_TOOL_SCHEMAS" in content
    assert "addAnnouncement" in content
    assert "getPendingAnnouncements" in content
    assert "clearPendingAnnouncements" in content
    assert "onJobFinished" in content

    # Check tool schemas in AUDIOVISUAL_TOOL_SCHEMAS
    assert "av_read_scene" in content
    assert "av_set_scene_type" in content
    assert "av_estimate" in content
    assert "av_generate_all" in content
    assert "av_regenerate_asset" in content
    assert "av_open_recording" in content


def test_actions_js_registers_audiovisual_actions():
    """Verify actions.js registers av_* actions and alias mapping."""
    content = ACTIONS_JS.read_text(encoding="utf-8")

    assert "av_read_scene" in content
    assert "av_set_scene_type" in content
    assert "av_estimate" in content
    assert "av_generate_all" in content
    assert "av_regenerate_asset" in content
    assert "av_open_recording" in content
    assert "audiovisual.regenerate_one" in content


def test_backend_regenerate_supports_instruction():
    """Verify app/main.py supports optional instruction parameter in regenerate endpoint."""
    content = MAIN_PY.read_text(encoding="utf-8")

    assert "regenerate_audiovisual_scene_endpoint" in content
    assert "instruction = body.get(\"instruction\")" in content or "body.get('instruction')" in content or "instruction" in content
    assert "input_data[\"instruction\"]" in content or "input_data['instruction']" in content or "instruction" in content


def test_node_agent_audiovisual_test_passes():
    """Run Node test harness tests/agent_audiovisual.test.js."""
    assert AV_TEST_JS.exists(), f"Test file not found: {AV_TEST_JS}"

    result = subprocess.run(
        ["node", str(AV_TEST_JS)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Node test agent_audiovisual.test.js failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_node_agent_announce_test_passes():
    """Run Node test harness tests/agent_announce.test.js."""
    assert ANNOUNCE_TEST_JS.exists(), f"Test file not found: {ANNOUNCE_TEST_JS}"

    result = subprocess.run(
        ["node", str(ANNOUNCE_TEST_JS)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Node test agent_announce.test.js failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
