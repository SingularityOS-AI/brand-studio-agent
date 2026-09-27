"""Tests for F-03: Production panel = audit trail/queue for every step.

Pure frontend piece (app/static/production_panel.js, app/static/index.html,
a handful of call sites in app/static/app.js) -- there is no Python surface
to unit test directly. Following the pattern of test_actions_f04.py /
test_editing_p82c_editing_js.py, this file re-implements a minimal fake DOM
in a Node subprocess (no jsdom dependency in this repo) that loads the real
production_panel.js and drives BrandStudioPanel.refresh() against a mocked
GET /api/agent/actions response, then asserts the resulting node tree.

The fake DOM's `innerHTML` setter throws -- if production_panel.js ever
assigned to it (for user data or otherwise) this test would fail with a
clear stack trace instead of silently passing, which is the property
AGENTS.md #4 ("DOM built without innerHTML for user strings") needs proved,
not just asserted.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = REPO_ROOT / "app" / "static" / "production_panel.js"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "app" / "static" / "index.html"


def _node_bin() -> str:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    return node_bin


def test_node_check_production_panel_js():
    res = subprocess.run(
        [_node_bin(), "--check", str(PANEL_JS)], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, f"node --check failed for production_panel.js: {res.stderr}"


def test_node_check_app_js():
    res = subprocess.run(
        [_node_bin(), "--check", str(APP_JS)], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, f"node --check failed for app.js: {res.stderr}"


def test_index_html_wires_the_script_tag_after_app_js():
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert '<script src="/static/production_panel.js"></script>' in content
    app_pos = content.index('<script src="/static/app.js"></script>')
    panel_pos = content.index('<script src="/static/production_panel.js"></script>')
    assert app_pos < panel_pos, "production_panel.js must load after app.js (needs window.BrandStudio)"


def test_app_js_calls_panel_refresh_after_job_refresh_and_step_changes():
    content = APP_JS.read_text(encoding="utf-8")
    calls = re.findall(r"window\.BrandStudioPanel\.refresh\(\)", content)
    # showBlockAView, showBlockBView, showBlockCView, showAudiovisualView,
    # hideMainViews (editing transition), loadAudiovisualJobs.
    assert len(calls) == 6, f"expected 6 BrandStudioPanel.refresh() call sites, found {len(calls)}"
    assert "if (window.BrandStudioPanel) window.BrandStudioPanel.refresh();" in content


def test_production_panel_js_never_touches_innerHTML():
    content = PANEL_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in content


NODE_HARNESS = r"""
'use strict';

// ---- Minimal fake DOM (no jsdom dependency in this repo) ------------------

const registry = Object.create(null);

function FakeElement(tag) {
  this.tagName = String(tag || '').toUpperCase();
  this._attrs = {};
  this._children = [];
  this.parentNode = null;
  this.style = {};
  this.dataset = {};
  this._classes = [];
  this._text = null;
}
FakeElement.prototype.setAttribute = function (name, value) {
  this._attrs[name] = String(value);
  if (name === 'id') this.id = value;
};
FakeElement.prototype.getAttribute = function (name) {
  return Object.prototype.hasOwnProperty.call(this._attrs, name) ? this._attrs[name] : null;
};
FakeElement.prototype.appendChild = function (child) {
  this._children.push(child);
  child.parentNode = this;
  this._text = null;
  return child;
};
FakeElement.prototype.removeChild = function (child) {
  const i = this._children.indexOf(child);
  if (i >= 0) this._children.splice(i, 1);
  return child;
};
Object.defineProperty(FakeElement.prototype, 'firstChild', {
  get() { return this._children.length ? this._children[0] : null; },
});
Object.defineProperty(FakeElement.prototype, 'childNodes', {
  get() { return this._children; },
});
Object.defineProperty(FakeElement.prototype, 'className', {
  get() { return this._classes.join(' '); },
  set(v) { this._classes = String(v).split(/\s+/).filter(Boolean); },
});
Object.defineProperty(FakeElement.prototype, 'id', {
  get() { return this._id || ''; },
  set(v) { this._id = v; registry[v] = this; },
});
Object.defineProperty(FakeElement.prototype, 'textContent', {
  get() {
    if (this._text !== null) return this._text;
    return this._children.map((c) => c.textContent).join('');
  },
  set(v) {
    this._children = [];
    this._text = String(v);
  },
});
Object.defineProperty(FakeElement.prototype, 'innerHTML', {
  get() { return ''; },
  set() {
    throw new Error('innerHTML must never be assigned by production_panel.js (XSS guard)');
  },
});

function createElement(tag) {
  return new FakeElement(tag);
}

// Pre-seed the three containers index.html already ships (#Prod-Jobs etc).
const prodJobs = createElement('div');
prodJobs.id = 'Prod-Jobs';
prodJobs.style.display = 'none';
const prodEmpty = createElement('div');
prodEmpty.id = 'Prod-Empty';
prodEmpty.style.display = 'flex';
const prodSubtext = createElement('p');
prodSubtext.id = 'Prod-Subtext';

const fakeHead = createElement('head');

global.document = {
  createElement,
  getElementById: (id) => registry[id] || null,
  addEventListener: () => {},
  head: fakeHead,
};

// ---- Fixture ----------------------------------------------------------

const MALICIOUS_UTTERANCE = '<img src=x onerror=alert(1)>"><script>alert(2)<\/script>';

const FIXTURE_ACTIONS = [
  {
    id: 'a1', source: 'voice', step: 'script', action: 'script.iterate_scene',
    status: 'done', credits: 2, created_at: new Date(Date.now() - 65000).toISOString(),
    utterance: 'make it punchier',
    restatement: 'Iterate scene 2 -- 2 credits. Say confirm to go ahead.',
    confirmation: 'confirm', result_ref: '/api/script/idea-1/scene/2',
  },
  {
    id: 'a2', source: 'voice', step: 'audiovisual', action: 'audiovisual.regenerate_one',
    status: 'queued', credits: 3, created_at: new Date().toISOString(),
    utterance: MALICIOUS_UTTERANCE,
    restatement: 'Regenerate scene 5 -- 3 credits. Say confirm to go ahead.',
    confirmation: null, result_ref: null,
  },
  {
    id: 'a3', source: 'button', step: 'catalog', action: 'POST /api/catalog/idea/{idea_id}/accept',
    status: 'running', credits: null, created_at: new Date(Date.now() - 5000).toISOString(),
    utterance: null, restatement: null, confirmation: null, result_ref: null,
  },
  {
    id: 'a4', source: 'button', step: 'editing', action: 'POST /api/editing/{idea_id}/render',
    status: 'failed', credits: 0, created_at: new Date(Date.now() - 3600000).toISOString(),
    utterance: null, restatement: null, confirmation: null, result_ref: 'javascript:alert(1)',
  },
];

const fetchCalls = [];
global.window = {
  BrandStudio: {
    authenticatedFetch: async (url) => {
      fetchCalls.push(url);
      return { ok: true, json: async () => ({ actions: FIXTURE_ACTIONS }) };
    },
    getCurrentScriptIdeaId: () => 'idea-1',
  },
  BrandStudioActions: {
    get: (id) => (id === 'script.iterate_scene' ? { title: 'Iterate a scene with an instruction' } : null),
  },
};
global.console = console;

const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
eval(code);

function serialize(el) {
  const out = { tag: el.tagName, className: el.className, text: el.textContent };
  const href = el.getAttribute('href');
  if (href !== null) out.href = href;
  if (el._children && el._children.length) out.children = el._children.map(serialize);
  return out;
}

async function main() {
  await global.window.BrandStudioPanel.refresh();

  const result = {
    fetchCalls,
    jobsDisplay: prodJobs.style.display,
    emptyDisplay: prodEmpty.style.display,
    subtext: prodSubtext.textContent,
    cards: prodJobs._children.map(serialize),
  };
  console.log(JSON.stringify(result));

  // Second pass: empty list -> empty state.
  global.window.BrandStudio.authenticatedFetch = async () => ({ ok: true, json: async () => ({ actions: [] }) });
  await global.window.BrandStudioPanel.refresh();
  console.log(JSON.stringify({
    emptyJobsDisplay: prodJobs.style.display,
    emptyEmptyDisplay: prodEmpty.style.display,
    emptyCardCount: prodJobs._children.length,
  }));
  // One fixture row is queued, so refresh() schedules a real 5s poll timer
  // (production_panel.js's own polling loop) -- exit explicitly instead of
  // leaving the Node process alive waiting on it.
  process.exit(0);
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""


def _run_harness() -> tuple[dict, dict]:
    res = subprocess.run(
        [_node_bin(), "-e", NODE_HARNESS, str(PANEL_JS)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert res.returncode == 0, f"Node harness failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    lines = [line for line in res.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 2, f"expected 2 JSON lines, got: {res.stdout}"
    return json.loads(lines[0]), json.loads(lines[1])


def _find(nodes, class_name):
    for node in nodes:
        if class_name in (node.get("className") or "").split(" "):
            return node
        found = _find(node.get("children") or [], class_name)
        if found:
            return found
    return None


def test_panel_renders_mixed_list_and_escapes_malicious_utterance():
    result, empty_result = _run_harness()

    assert result["fetchCalls"] == ["/api/agent/actions?limit=50&idea_id=idea-1"]
    assert result["jobsDisplay"] == "block"
    assert result["emptyDisplay"] == "none"
    assert result["subtext"] == "4 actions for this idea."

    cards = result["cards"]
    assert len(cards) == 4
    for card in cards:
        assert card["tag"] == "DIV"
        assert "pp-card" in card["className"]

    # Card 1: voice, done, registered title, safe Open link, all three
    # voice detail lines present verbatim.
    card1 = cards[0]
    assert _find([card1], "pp-title")["text"] == "Iterate a scene with an instruction"
    assert _find([card1], "pp-chip")["text"] == "Done"
    assert _find([card1], "pp-step")["text"] == "Script"
    assert _find([card1], "pp-cost")["text"] == "−2 credits"
    open_link = _find([card1], "pp-open")
    assert open_link is not None
    assert open_link["tag"] == "A"
    assert open_link["href"] == "/api/script/idea-1/scene/2"
    voice_lines = [c["text"] for c in _find([card1], "pp-voice-detail")["children"]]
    assert voice_lines == [
        "You said: make it punchier",
        "Brandy: Iterate scene 2 -- 2 credits. Say confirm to go ahead.",
        "Confirmed: confirm",
    ]

    # Card 2: voice, queued, malicious utterance comes through as literal
    # text (never parsed as markup -- the fake DOM's innerHTML setter would
    # have thrown and failed this whole test if the code touched it).
    card2 = cards[1]
    assert _find([card2], "pp-chip")["text"] == "Queued"
    assert _find([card2], "pp-step")["text"] == "Audiovisual"
    # No registry entry for this id -> falls back to a humanized action id.
    assert _find([card2], "pp-title")["text"] == "Regenerate one"
    malicious_line = _find([card2], "pp-voice-detail")["children"][0]
    assert malicious_line["text"] == "You said: " + (
        "<img src=x onerror=alert(1)>\"><script>alert(2)</script>"
    )
    # No "Confirmed" line since confirmation is null.
    assert len(_find([card2], "pp-voice-detail")["children"]) == 2
    assert _find([card2], "pp-open") is None
    # No literal <img>/<script> element was ever created for the payload.
    def collect_tags(node, out):
        out.add(node["tag"])
        for child in node.get("children") or []:
            collect_tags(child, out)
    tags = set()
    collect_tags(card2, tags)
    assert "SCRIPT" not in tags
    assert "IMG" not in tags

    # Card 3: button, running, humanized title from the route, no voice
    # detail, unknown cost renders blank rather than "None credits".
    card3 = cards[2]
    assert _find([card3], "pp-title")["text"] == "Accept"
    assert _find([card3], "pp-chip")["text"] == "Running"
    assert _find([card3], "pp-cost")["text"] == ""
    assert _find([card3], "pp-voice-detail") is None

    # Card 4: button, failed, zero credits reads "Free", and an unsafe
    # result_ref (javascript: URI) never becomes a clickable link.
    card4 = cards[3]
    assert _find([card4], "pp-title")["text"] == "Render"
    assert _find([card4], "pp-chip")["text"] == "Failed"
    assert _find([card4], "pp-cost")["text"] == "Free"
    assert _find([card4], "pp-open") is None

    # Empty list -> empty state, panel hidden.
    assert empty_result["emptyJobsDisplay"] == "none"
    assert empty_result["emptyEmptyDisplay"] == "flex"
    assert empty_result["emptyCardCount"] == 0
