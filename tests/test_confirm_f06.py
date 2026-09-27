"""Tests for F-06: Confirmation engine (propose / confirm), code-enforced.

Pure frontend piece (app/static/confirm_engine.js) -- there is no Python
surface to unit test directly. This file runs the syntax/contract checks
required by AGENTS.md's Definition of Done and re-runs the Node harness
(tests/confirm_engine.test.js, built on tests/agent_harness.js) that loads
the real confirm_engine.js and asserts propose/confirm/cancel/pending
behaviour, so `pytest -q` alone is enough to catch a regression without a
separate `node` invocation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIRM_ENGINE_JS = REPO_ROOT / "app" / "static" / "confirm_engine.js"
NODE_TEST = REPO_ROOT / "tests" / "confirm_engine.test.js"
AGENT_HARNESS_JS = REPO_ROOT / "tests" / "agent_harness.js"


def _node_bin() -> str:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    return node_bin


def test_node_check_confirm_engine_js():
    res = subprocess.run([_node_bin(), "--check", str(CONFIRM_ENGINE_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed for confirm_engine.js: {res.stderr}"


def test_node_check_agent_harness_js():
    res = subprocess.run([_node_bin(), "--check", str(AGENT_HARNESS_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed for agent_harness.js: {res.stderr}"


def test_confirm_engine_node_harness_passes():
    """Runs tests/confirm_engine.test.js, which loads the real
    confirm_engine.js (directly and, for the browser-export case, through
    tests/agent_harness.js's loadBrowserScript) and asserts propose/confirm/
    cancel/pending semantics, including the confirmation gate."""
    res = subprocess.run(
        [_node_bin(), str(NODE_TEST)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, (
        f"node tests/confirm_engine.test.js failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "All checks passed." in res.stdout


def test_confirm_engine_default_ttl_is_45_seconds():
    """docs/specs/F/plan.md #2: "token (random), 45 s TTL" -- checked
    behaviourally (propose() with no maxAgeMs/expiresAt override) rather
    than by grepping the source, so a refactor that keeps the real default
    can't accidentally break this test."""
    node_script = """
    const { createConfirmationEngine } = require(process.argv[1]);
    const engine = createConfirmationEngine();
    const before = Date.now();
    const proposed = engine.propose({ actionId: 'x', args: {}, cost: 0 });
    console.log(JSON.stringify({ ttlMs: proposed.expiresAt - before }));
    """
    res = subprocess.run(
        [_node_bin(), "-e", node_script, str(CONFIRM_ENGINE_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"
    data = json.loads(res.stdout.strip())
    assert 44000 <= data["ttlMs"] <= 45500, f"default TTL should be ~45000ms, got {data['ttlMs']}ms"


def test_confirm_engine_bare_yes_does_not_confirm():
    """docs/specs/F/plan.md #2 only authorizes the full phrase "yes do it",
    not a bare "yes" -- checked behaviourally for the same reason as the
    TTL test above."""
    node_script = """
    const { createConfirmationEngine } = require(process.argv[1]);
    const engine = createConfirmationEngine();
    engine.propose({ actionId: 'x', args: {}, cost: 0 });
    console.log(JSON.stringify(engine.confirm('yes')));
    """
    res = subprocess.run(
        [_node_bin(), "-e", node_script, str(CONFIRM_ENGINE_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"
    data = json.loads(res.stdout.strip())
    assert data["status"] == "not_confirmed", f"a bare 'yes' must not confirm: {data}"
