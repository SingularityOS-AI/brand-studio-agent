"""Tests for H7-04: the Production panel stays quiet before login and shows
calm states when the audit log cannot be read.

Same approach as tests/test_panel_f03.py: a minimal fake DOM in a Node
subprocess loads the real app/static/production_panel.js and drives
BrandStudioPanel.refresh() against mocked authenticatedFetch responses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = REPO_ROOT / "app" / "static" / "production_panel.js"

NODE_HARNESS = r"""
'use strict';

const registry = Object.create(null);

function FakeElement(tag) {
  this.tagName = String(tag || '').toUpperCase();
  this._attrs = {};
  this._children = [];
  this.style = {};
  this._classes = [];
  this._text = null;
}
FakeElement.prototype.setAttribute = function (n, v) { this._attrs[n] = String(v); };
FakeElement.prototype.getAttribute = function (n) {
  return Object.prototype.hasOwnProperty.call(this._attrs, n) ? this._attrs[n] : null;
};
FakeElement.prototype.appendChild = function (c) { this._children.push(c); this._text = null; return c; };
FakeElement.prototype.removeChild = function (c) {
  const i = this._children.indexOf(c);
  if (i >= 0) this._children.splice(i, 1);
  return c;
};
Object.defineProperty(FakeElement.prototype, 'firstChild', { get() { return this._children[0] || null; } });
Object.defineProperty(FakeElement.prototype, 'childNodes', { get() { return this._children; } });
Object.defineProperty(FakeElement.prototype, 'className', {
  get() { return this._classes.join(' '); },
  set(v) { this._classes = String(v).split(/\s+/).filter(Boolean); },
});
Object.defineProperty(FakeElement.prototype, 'id', {
  get() { return this._id || ''; },
  set(v) { this._id = v; registry[v] = this; },
});
Object.defineProperty(FakeElement.prototype, 'textContent', {
  get() { return this._text !== null ? this._text : this._children.map((c) => c.textContent).join(''); },
  set(v) { this._children = []; this._text = String(v); },
});
Object.defineProperty(FakeElement.prototype, 'innerHTML', {
  get() { return ''; },
  set() { throw new Error('innerHTML must never be assigned by production_panel.js'); },
});

function el(tag, id, display) {
  const e = new FakeElement(tag);
  e.id = id;
  e.style.display = display;
  return e;
}
const mainApp = el('div', 'Main-App', 'none');   // hidden until login, like index.html
const prodJobs = el('div', 'Prod-Jobs', 'none');
const prodEmpty = el('div', 'Prod-Empty', 'flex');
const prodSubtext = el('p', 'Prod-Subtext', '');
prodSubtext.textContent = 'Empty until there is something to produce.';

global.document = {
  createElement: (t) => new FakeElement(t),
  getElementById: (id) => registry[id] || null,
  addEventListener: () => {},
  head: new FakeElement('head'),
};

const warnings = [];
const realConsole = console;
global.console = {
  log: () => {},
  error: (...a) => warnings.push(['error', a.map(String).join(' ')]),
  warn: (...a) => warnings.push(['warn', a.map(String).join(' ')]),
};

const calls = [];
let mode = 'not_authenticated';
const ACTIONS = [
  { id: 'a1', source: 'button', step: 'catalog', action: 'POST /api/catalog/idea/{idea_id}/accept',
    status: 'done', credits: 0, created_at: new Date().toISOString() },
  { id: 'a2', source: 'button', step: 'editing', action: 'POST /api/editing/{idea_id}/render',
    status: 'done', credits: 5, created_at: new Date().toISOString() },
];
global.window = {
  BrandStudio: {
    authenticatedFetch: async (url) => {
      calls.push(url);
      if (mode === 'not_authenticated') throw new Error('Not authenticated');
      if (mode === '401') return { ok: false, status: 401, json: async () => ({}) };
      if (mode === '500') return { ok: false, status: 500, json: async () => ({}) };
      if (mode === 'empty') return { ok: true, json: async () => ({ actions: [] }) };
      return { ok: true, json: async () => ({ actions: ACTIONS }) };
    },
    getCurrentScriptIdeaId: () => null,
  },
};

eval(require('fs').readFileSync(process.argv[1], 'utf8'));
const panel = global.window.BrandStudioPanel;

function snap(label) {
  return {
    label,
    calls: calls.length,
    warnings: warnings.length,
    jobsDisplay: prodJobs.style.display,
    emptyDisplay: prodEmpty.style.display,
    subtext: prodSubtext.textContent,
    cards: prodJobs._children.length,
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const out = [];

  // 1. Before login: Main-App hidden -> no fetch at all, no warnings.
  await panel.refresh();
  await panel.refresh();
  out.push(snap('before_login'));

  // 2. Login happens (Main-App revealed) while the auth retry is pending:
  //    the panel picks it up on its own without any call from app.js.
  mode = 'ok';
  mainApp.style.display = 'flex';
  await sleep(1300);
  out.push(snap('retry_after_login'));

  // 3. Session token race: authenticatedFetch throws "Not authenticated"
  //    even though the UI is visible -> swallowed, no warning.
  mode = 'not_authenticated';
  const beforeCalls = calls.length;
  await panel.refresh();
  const swallowed = snap('not_authenticated_thrown');
  swallowed.newCalls = calls.length - beforeCalls;
  out.push(swallowed);

  // 4. 401 / 500 -> calm unavailable line.
  for (const m of ['401', '500']) {
    mode = m;
    await panel.refresh();
    out.push(snap('http_' + m));
  }

  // 5. [] -> existing empty state.
  mode = 'empty';
  await panel.refresh();
  out.push(snap('empty_list'));

  // 6. Two actions -> two cards.
  mode = 'ok';
  await panel.refresh();
  out.push(snap('two_actions'));

  realConsole.log(JSON.stringify({ steps: out, warnings }));
  process.exit(0);
}
main().catch((e) => { realConsole.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
"""


def _run() -> dict:
    node = shutil.which("node")
    assert node is not None, "Node.js must be in PATH"
    res = subprocess.run(
        [node, "-e", NODE_HARNESS, str(PANEL_JS)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), check=False,
    )
    assert res.returncode == 0, f"Node harness failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    return json.loads(res.stdout.strip().splitlines()[-1])


def _steps() -> dict[str, dict]:
    return {s["label"]: s for s in _run()["steps"]}


def test_before_login_no_fetch_and_no_console_output():
    s = _steps()["before_login"]
    assert s["calls"] == 0
    assert s["warnings"] == 0


def test_panel_loads_by_itself_once_the_session_is_ready():
    s = _steps()["retry_after_login"]
    assert s["calls"] == 1
    assert s["cards"] == 2


def test_not_authenticated_error_is_swallowed_without_warning():
    data = _run()
    s = {x["label"]: x for x in data["steps"]}["not_authenticated_thrown"]
    assert s["newCalls"] == 1
    assert data["warnings"] == []


def test_non_ok_response_shows_unavailable_line():
    steps = _steps()
    for label in ("http_401", "http_500"):
        assert steps[label]["subtext"] == "Activity log unavailable right now."
        assert steps[label]["jobsDisplay"] == "none"
        assert steps[label]["emptyDisplay"] == "flex"
        assert steps[label]["cards"] == 0


def test_empty_list_shows_existing_empty_state():
    s = _steps()["empty_list"]
    assert s["subtext"] == "Empty until there is something to produce."
    assert s["jobsDisplay"] == "none"
    assert s["emptyDisplay"] == "flex"


def test_two_actions_render_two_cards():
    s = _steps()["two_actions"]
    assert s["cards"] == 2
    assert s["jobsDisplay"] == "block"
    assert s["subtext"] == "2 actions for this idea."


def test_panel_never_touches_innerhtml():
    assert "innerHTML" not in PANEL_JS.read_text(encoding="utf-8")
