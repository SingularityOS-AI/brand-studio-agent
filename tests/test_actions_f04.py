"""Tests for F-04: Action Registry + X-Agent-Action-Id fetch context.

Pure frontend piece (app/static/actions.js, app/static/app.js) -- there is no
Python surface to unit test directly. This file runs the syntax/contract
checks required by AGENTS.md's Definition of Done and re-runs the Node
harness (tests/agent_actions.test.js) that actually loads the real
actions.js + app.js and asserts the exact HTTP calls, so `pytest -q` alone
is enough to catch a regression without a separate `node` invocation.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIONS_JS = REPO_ROOT / "app" / "static" / "actions.js"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"
NODE_TEST = REPO_ROOT / "tests" / "agent_actions.test.js"


def _node_bin() -> str:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    return node_bin


def test_node_check_actions_js():
    res = subprocess.run([_node_bin(), "--check", str(ACTIONS_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed for actions.js: {res.stderr}"


def test_node_check_app_js():
    res = subprocess.run([_node_bin(), "--check", str(APP_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed for app.js: {res.stderr}"


def test_agent_actions_node_harness_passes():
    """Runs tests/agent_actions.test.js, which loads the real actions.js +
    app.js with fetch mocked and asserts the exact HTTP calls (endpoint,
    body, X-Agent-Action-Id header) for script.iterate_scene, plus the
    registry shape and the thrown-run / currentActionId-clearing contract."""
    res = subprocess.run(
        [_node_bin(), str(NODE_TEST)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, (
        f"node tests/agent_actions.test.js failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "All checks passed." in res.stdout


def test_actions_js_registers_the_ten_pieces_actions():
    """Static-loads actions.js alone (no app.js, no DOM) and checks the
    registry contains the 10 actions F-04 calls for (a subset: later pieces
    add more), each with the shape register() requires."""
    node_script = """
    const fs = require('fs');
    global.window = {};
    const code = fs.readFileSync(process.argv[1], 'utf8');
    eval(code);
    const actions = global.window.BrandStudioActions.list();
    const shaped = actions.map(a => ({
      id: a.id,
      step: a.step,
      needsConfirm: a.needsConfirm,
      hasCost: typeof a.cost === 'function',
      hasRun: typeof a.run === 'function',
    }));
    console.log(JSON.stringify(shaped));
    """
    res = subprocess.run(
        [_node_bin(), "-e", node_script, str(ACTIONS_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"

    import json

    actions = json.loads(res.stdout.strip())
    by_id = {a["id"]: a for a in actions}

    expected_script = {
        "script.generate": True,
        "script.iterate_scene": True,
        "script.edit_scene_text": False,
        "script.lock": True,
        "script.audit": False,
    }
    expected_audiovisual = {
        "audiovisual.change_scene_type": False,
        "audiovisual.estimate": False,
        "audiovisual.generate_all": True,
        "audiovisual.regenerate_one": True,
        "audiovisual.open_recording_studio": False,
    }

    missing = (set(expected_script) | set(expected_audiovisual)) - set(by_id)
    assert not missing, f"F-04 actions missing from the registry: {sorted(missing)}"

    for action_id, needs_confirm in expected_script.items():
        assert by_id[action_id]["step"] == "script", action_id
        assert by_id[action_id]["needsConfirm"] == needs_confirm, action_id
        assert by_id[action_id]["hasCost"], action_id
        assert by_id[action_id]["hasRun"], action_id

    for action_id, needs_confirm in expected_audiovisual.items():
        assert by_id[action_id]["step"] == "audiovisual", action_id
        assert by_id[action_id]["needsConfirm"] == needs_confirm, action_id
        assert by_id[action_id]["hasCost"], action_id
        assert by_id[action_id]["hasRun"], action_id


def test_actions_js_never_touches_window_brandstudio_at_top_level():
    """actions.js loads BEFORE app.js (per the piece), so window.BrandStudio
    does not exist yet while register() calls run. Every reference to
    `window.BrandStudio` in actions.js must be inside a run()/cost()
    closure body, never evaluated as part of building the register({...})
    call arguments themselves. A regression here would throw
    'Cannot read properties of undefined' the instant actions.js loads in
    the real page, before app.js ever runs."""
    node_script = """
    global.window = {};  // no BrandStudio -- exactly like actions.js's real load order
    const fs = require('fs');
    const code = fs.readFileSync(process.argv[1], 'utf8');
    eval(code);
    console.log('LOADED_WITHOUT_ERROR');
    """
    res = subprocess.run(
        [_node_bin(), "-e", node_script, str(ACTIONS_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"actions.js must load before window.BrandStudio exists: {res.stderr}"
    assert "LOADED_WITHOUT_ERROR" in res.stdout


def test_authenticated_fetch_sends_agent_action_id_header():
    stripped = re.sub(r"/\*.*?\*/", "", APP_JS.read_text(encoding="utf-8"), flags=re.DOTALL)

    assert "async function authenticatedFetch" in stripped
    fn_start = stripped.index("async function authenticatedFetch")
    fn_body = stripped[fn_start : fn_start + 1500]

    assert "X-Agent-Action-Id" in fn_body
    assert "BrandStudioActions" in fn_body
    assert "currentActionId" in fn_body


def test_app_js_exposes_the_button_functions_the_registry_needs():
    stripped = re.sub(r"/\*.*?\*/", "", APP_JS.read_text(encoding="utf-8"), flags=re.DOTALL)

    assert "window.BrandStudio = {" in stripped
    block_start = stripped.index("window.BrandStudio = {")
    block_end = stripped.index("};", block_start)
    block = stripped[block_start:block_end]

    for exposed in (
        "authenticatedFetch",
        "openRecordingStudio",
        "getCurrentScriptIdeaId",
        "getCurrentScriptData",
        "getCurrentAudiovisualEstimate",
        "handleScriptGenerate",
        "handleScriptRegenerate",
        "handleScriptSceneEdit",
        "handleScriptLock",
        "changeSceneAssetType",
        "fetchAudiovisualEstimate",
        "generateAllAudiovisualAssets",
        "triggerRegenerateScene",
    ):
        assert exposed in block, f"window.BrandStudio must expose {exposed}"


def test_no_new_spanish_ui_strings_in_actions_js():
    """AGENTS.md #4: every string the founder sees is English. actions.js
    only produces `title` strings (read out loud / shown in the panel by a
    later piece) -- assert they don't contain the Spanish confirmation
    vocabulary the CEO uses only in the spec/plan docs."""
    content = ACTIONS_JS.read_text(encoding="utf-8")
    for spanish_word in ("confirmo", "hazlo", "adelante", "espera", "cancela"):
        assert spanish_word not in content.lower(), f"Unexpected Spanish string: {spanish_word}"
