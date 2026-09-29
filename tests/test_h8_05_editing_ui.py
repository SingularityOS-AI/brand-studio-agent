"""H8-05: Editing UI for overlays (E2-10) and styles (E2-11).

Static checks on app/static/editing.js plus a Node run against a tiny fake DOM
(no jsdom): style clicks, overlay edit/delete/switch and the Overlays track.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITING_JS = REPO_ROOT / "app" / "static" / "editing.js"

NODE_HARNESS = r"""
const fs = require('fs');

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.type = '';
    this.maxLength = -1;
  }
  appendChild(c) { this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  async fire(ev) { for (const fn of (this.listeners[ev] || [])) { await fn({ target: this }); } }
  all(pred, out = []) {
    for (const c of this.children) { if (pred(c)) out.push(c); c.all(pred, out); }
    return out;
  }
  byClass(cls) { return this.all((n) => (' ' + n.className + ' ').includes(' ' + cls + ' ')); }
  allText() {
    return [this.textContent].concat(this.children.map((c) => c.allText())).join(' ');
  }
}

global.window = {};
global.document = {
  addEventListener: () => {},
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: (t) => new El(t),
  createTextNode: (t) => { const n = new El('#text'); n.textContent = t; return n; },
};
global.crypto = { randomUUID: () => 'req-1' };

const calls = [];
let version = 5;
global.fetch = async (url, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : null;
  calls.push({ url, method: opts && opts.method, body });
  if (opts && opts.method === 'GET') return { ok: true, status: 200, json: async () => ({ edit_version: version }) };
  version += 1;
  return { ok: true, status: 200, json: async () => ({ edit_version: version, settings: {}, ir: { overlays: [] }, dressing: { fresh: true } }) };
};

eval(fs.readFileSync(process.argv[1], 'utf8'));
const api = global.window.BrandStudioEditing;
const T = api.__test;

const ir = {
  overlays: [
    { id: 'ov_s1_0', kind: 'card_stat', text: 'Save 3 hours', start_ms: 1600, end_ms: 3000 },
    { id: 'ov_s2_0', kind: 'emoji', text: null, asset: 'X', start_ms: 5000, end_ms: 6200 },
    { id: 'ov_s3_0', kind: 'lower_third', text: 'Third', start_ms: 8000, end_ms: 9500 },
  ],
  captions: [], zoom_keys: [], transitions: [], sfx: [],
};
const state = { edit_version: 5, settings: {}, ir, dressing: { fresh: true } };
T.setState('idea-1', state);

const out = {};

(async () => {
  // Style selector
  const sc = T.buildStyleControl(state.dressing);
  const styleBtns = sc.byClass('editing-style-btn');
  out.style_labels = styleBtns.map((b) => b.textContent);
  out.style_pressed_initial = styleBtns.filter((b) => b.attrs['aria-pressed'] === 'true').map((b) => b.dataset.style);
  out.restyles_left = sc.byClass('editing-restyles-left')[0].textContent;
  await styleBtns.find((b) => b.dataset.style === 'bold').fire('click');
  out.style_call = calls.filter((c) => c.method === 'POST');

  // Overlays card
  T.setState('idea-1', state);
  calls.length = 0;
  const card = T.buildOverlaysCard(state);
  out.card_title = card.children[0].textContent;
  out.card_text = card.allText();
  const rows = card.byClass('editing-overlay-row');
  out.row_count = rows.length;
  out.text_inputs = card.byClass('editing-overlay-text').length;
  out.delete_buttons = card.byClass('editing-overlay-delete').length;

  const sw = card.byClass('editing-overlays-switch')[0];
  out.switch_initial = sw.checked;
  sw.checked = false;
  await sw.fire('change');

  const inp = card.byClass('editing-overlay-text')[0];
  inp.value = '  New headline  ';
  await inp.fire('change');

  inp.value = 'x'.repeat(81);
  await inp.fire('change');
  inp.value = '   ';
  await inp.fire('change');

  await rows[2].byClass('editing-overlay-delete')[0].fire('click');
  out.patch_calls = calls.filter((c) => c.method === 'PATCH');
  out.patch_urls = out.patch_calls.map((c) => c.url);

  // Overlays track
  const defs = T.getTrackDefs(ir);
  const ovDef = defs.find((d) => d.label === 'Overlays');
  out.track_labels = defs.map((d) => d.label);
  const rowsDom = defs.map((d) => T.buildTrackRow(d, 10000));
  out.track_row_labels = rowsDom.map((r) => r.children[0].textContent);
  out.track_marks = rowsDom[rowsDom.length - 1].children[1].children.length;
  out.track_first_left = rowsDom[rowsDom.length - 1].children[1].children[0].style.left;

  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def dom_result():
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    res = subprocess.run(
        [node_bin, "-e", NODE_HARNESS, str(EDITING_JS)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_static_no_innerhtml_for_new_controls():
    content = EDITING_JS.read_text(encoding="utf-8")
    start = content.index("function buildStyleControl")
    end = content.index("function getTrackDefs")
    block = content[start:end]
    assert "innerHTML" not in block
    for term in ("Clean", "Standard", "Bold", "Restyles left:", "Show overlays", "Overlays"):
        assert term in content, f"editing.js must contain {term!r}"
    for op in ("overlay_delete", "overlay_text", "overlays_enabled"):
        assert op in content


def test_style_selector_renders_and_sends_style(dom_result):
    assert dom_result["style_labels"] == ["Clean", "Standard", "Bold"]
    assert dom_result["style_pressed_initial"] == ["standard"]
    assert dom_result["restyles_left"] == "Restyles left: 3"
    posts = dom_result["style_call"]
    assert len(posts) == 1
    assert posts[0]["url"] == "/api/editing/idea-1/dress"
    assert posts[0]["body"]["style"] == "bold"
    assert posts[0]["body"]["expected_version"] == 5


def test_overlays_card_rows(dom_result):
    assert dom_result["card_title"] == "Overlays"
    assert "Show overlays" in dom_result["card_text"]
    assert dom_result["row_count"] == 3
    assert dom_result["delete_buttons"] == 3
    # the emoji overlay has no text, so it gets no text input
    assert dom_result["text_inputs"] == 2
    assert "1.6s" in dom_result["card_text"]
    assert dom_result["switch_initial"] is True


def test_overlay_switch_edit_delete_send_ops_with_version(dom_result):
    calls = dom_result["patch_calls"]
    assert all(c["url"] == "/api/editing/idea-1/settings" for c in calls)
    # switch, one valid text edit, one delete. Empty and >80 chars are rejected client side.
    assert [c["body"]["op"] for c in calls] == ["overlays_enabled", "overlay_text", "overlay_delete"]
    enabled, text, delete = (c["body"] for c in calls)
    assert enabled["value"] is False
    assert text["overlay_id"] == "ov_s1_0"
    assert text["value"] == "New headline"
    assert delete["overlay_id"] == "ov_s3_0"
    for body in (enabled, text, delete):
        assert isinstance(body["expected_version"], int)


def test_overlays_track_has_one_mark_per_overlay(dom_result):
    assert dom_result["track_labels"] == ["Captions", "Zoom", "Transitions", "SFX", "Overlays"]
    assert dom_result["track_marks"] == 3
    assert dom_result["track_row_labels"][-1] == "Overlays"
    assert dom_result["track_first_left"] == "16%"
