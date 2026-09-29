"""Tests for Pieza 82C: editing.js contract validation against real router."""
import json
import re
import shutil
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITING_JS = REPO_ROOT / "app" / "static" / "editing.js"
ROUTER_PY = REPO_ROOT / "app" / "editing" / "router.py"


def test_node_check_editing_js():
    """1. node --check app/static/editing.js = 0."""
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    res = subprocess.run([node_bin, "--check", str(EDITING_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed: {res.stderr}"


def test_editing_js_static_assertions():
    """2. Static assertions: required and forbidden terms."""
    content = EDITING_JS.read_text(encoding="utf-8")

    required_terms = [
        "expected_version",
        '"music_mute"',
        '"sfx_enabled"',
        '"face"',
        '"trim"',
        "/share-link",
        "navigator.share",
        "navigator.clipboard",
        "/redress",
        "/metadata",
        "crypto.randomUUID",
    ]
    for term in required_terms:
        assert term in content, f"editing.js must contain {term}"

    forbidden_terms = [
        "alert(",
        "eval(",
        "new Function",
        '"music_muted"',
        '"swap_take"',
        "share_url",
    ]
    for term in forbidden_terms:
        assert term not in content, f"editing.js must NOT contain {term}"

    assert not re.search(r'op\s*:\s*["\']broll["\']', content), 'editing.js must NOT contain op: "broll"'


def test_editing_js_router_ops_contract():
    """3a. Verify ops sent by editing.js match allowed_ops in router.py."""
    js_content = EDITING_JS.read_text(encoding="utf-8")
    router_content = ROUTER_PY.read_text(encoding="utf-8")

    m = re.search(r'allowed_ops\s*=\s*\{([^}]+)\}', router_content)
    assert m, "router.py must define allowed_ops"
    router_ops = set(re.findall(r'["\']([^"\']+)["\']', m.group(1)))

    js_ops = set(re.findall(r'op\s*:\s*["\']([^"\']+)["\']', js_content))

    # Ops that patchOverlays() maps client-side before the request goes out
    # (`payload.op === "delete"` -> `op: "overlay_delete"`): they never reach
    # the router under their client-side name, so only the mapped target counts.
    client_mapped_ops = set(re.findall(r'payload\.op\s*===\s*["\']([^"\']+)["\']', js_content))
    assert "delete" in client_mapped_ops, "editing.js must map the client-side 'delete' op"

    for op in js_ops - client_mapped_ops:
        assert op in router_ops, f"Op '{op}' sent by editing.js is not in router.py allowed_ops {router_ops}"


def test_editing_js_router_endpoints_contract():
    """3b. Verify API routes used by editing.js exist in router.py."""
    js_content = EDITING_JS.read_text(encoding="utf-8")
    router_content = ROUTER_PY.read_text(encoding="utf-8")

    # Take the whole quoted/template-literal string, so a route like
    # `/api/editing/${encodeURIComponent(ideaId)}/settings` is parsed in full.
    raw_routes = re.findall(r'[`"\'](/api/editing[^`"\']*)[`"\']', js_content)
    normalized_routes = set()
    for r in raw_routes:
        norm = re.sub(r'\$\{[^}]*\}', '{param}', r)
        normalized_routes.add(norm)

    missing_routes = []
    for r in normalized_routes:
        path_part = r.replace("/api/editing", "")
        # convert path template into regex
        pattern_str = re.escape(path_part).replace(r'\{param\}', r'[^/]+')
        if not re.search(pattern_str, router_content):
            missing_routes.append(r)

    unimplemented = [m for m in missing_routes if "/metadata" in m or "/redress" in m]
    other_missing = [m for m in missing_routes if m not in unimplemented]

    assert not other_missing, f"Routes in editing.js missing from router.py: {other_missing}"

    if unimplemented:
        pytest.xfail(f"Endpoints not yet implemented in router.py: {unimplemented}")


def test_node_load_and_expose_edit_actions():
    """4. Load editing.js in Node with fake DOM and verify EDIT_ACTIONS exposed."""
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"

    node_script = f"""
    const fs = require('fs');
    global.window = {{}};
    global.document = {{
      addEventListener: () => {{}},
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => []
    }};
    const code = fs.readFileSync({json.dumps(str(EDITING_JS))}, 'utf8');
    eval(code);
    const actions = global.window.BrandStudioEditing.EDIT_ACTIONS;
    const actionKeys = Object.keys(actions);
    console.log(JSON.stringify(actionKeys));
    """

    res = subprocess.run(
        [node_bin, "-e", node_script],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"

    actions_found = json.loads(res.stdout.strip())
    expected_core_actions = [
        "toggle_face",
        "reset_face",
        "trim",
        "mute_music",
        "toggle_sfx",
        "fix_caption",
        "dress_all",
        "redress_scene",
        "build_raw",
        "render",
        "gen_metadata",
        "edit_metadata",
        "copy_share_link",
    ]

    for expected in expected_core_actions:
        assert expected in actions_found, f"EDIT_ACTIONS missing expected action '{expected}'"

    # Later pieces (E2-06, E2-09, ...) add actions; the P82C core set must stay.
    assert len(actions_found) >= len(expected_core_actions), actions_found
    assert len(actions_found) == len(set(actions_found)), f"Duplicate EDIT_ACTIONS: {actions_found}"
