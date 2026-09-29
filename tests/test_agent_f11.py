"""Tests for F-11: Editing voice tools.

F-11 is a pure frontend piece (app/static/agent.js + app/static/actions.js): the
voice tools call the same functions and endpoints as the Editing buttons, so
there is no Python surface (no app.models / app.agent.tools) to test directly.
The behaviour is covered by the Node harness tests/agent_editing.test.js, which
loads the real agent.js + actions.js with fetch mocked. This wrapper runs it so
`pytest -q` alone catches a regression, like tests/test_agent_f07.py does for F-07.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_TEST = REPO_ROOT / "tests" / "agent_editing.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available in PATH")
def test_node_check_agent_editing_test_js():
    res = subprocess.run(
        ["node", "--check", str(NODE_TEST)],
        capture_output=True,
        encoding="utf-8",
    )
    assert res.returncode == 0, f"node --check failed for {NODE_TEST}: {res.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available in PATH")
def test_agent_editing_node_harness_passes():
    """Runs tests/agent_editing.test.js (F-11 editing voice tools)."""
    res = subprocess.run(
        ["node", str(NODE_TEST)],
        capture_output=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, (
        f"node tests/agent_editing.test.js failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
