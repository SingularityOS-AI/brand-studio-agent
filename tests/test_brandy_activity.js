'use strict';
/**
 * Node test for BR-B ("Brandy - live" activity feed in the right panel).
 *
 * Run with: node tests/test_brandy_activity.js
 *
 * Loads the real app/static/brandy_activity.js into a fresh vm context per
 * scenario, against a tiny fake DOM (createElement / appendChild / insertBefore /
 * removeChild / classList / textContent / getElementById / querySelector /
 * addEventListener / dispatchEvent). The fake DOM's inner-markup setter throws,
 * so any use of it by the module fails the test.
 *
 * Asserts: a push creates a row; the same id updates in place (no duplicate)
 * and shows a duration on done; cap of 40; unknown kind -> info; unknown state
 * -> done; sanitizing; `has-activity` on the .prod element and `hidden`
 * removed; the `brandy:activity` document-event path; demo(); lazy container
 * lookup with buffering; a single ticker only while rows exist; and that the
 * source file never touches the banned inner-markup APIs.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const REPO_ROOT = path.resolve(__dirname, '..');
const SRC_PATH = path.join(REPO_ROOT, 'app', 'static', 'brandy_activity.js');
const SRC = fs.readFileSync(SRC_PATH, 'utf8');

/* ---------------------------------------------------------------- fake DOM */

function classTokens(el) {
  return String(el.className || '').split(/\s+/).filter(Boolean);
}

function makeClassList(el) {
  return {
    add(...names) {
      const t = classTokens(el);
      names.forEach((n) => { if (t.indexOf(n) === -1) t.push(n); });
      el.className = t.join(' ');
    },
    remove(...names) {
      el.className = classTokens(el).filter((n) => names.indexOf(n) === -1).join(' ');
    },
    contains(n) { return classTokens(el).indexOf(n) !== -1; },
    toggle(n, force) {
      const has = this.contains(n);
      const want = force === undefined ? !has : !!force;
      if (want) this.add(n); else this.remove(n);
      return want;
    },
  };
}

function matchesSimple(el, sel) {
  const parts = sel.split(/(?=[.#])/).filter(Boolean);
  return parts.every((p) => {
    if (p[0] === '.') return el.classList.contains(p.slice(1));
    if (p[0] === '#') return el.id === p.slice(1);
    return el.tagName === p.toUpperCase();
  });
}

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this._attrs = Object.create(null);
    this._text = '';
    this.className = '';
    this.style = {};
    this.classList = makeClassList(this);
  }
  get id() { return this._attrs.id || ''; }
  set id(v) { this._attrs.id = String(v); }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  get childNodes() { return this.children; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) {
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    this._text = String(v);
  }
  get innerHTML() { return ''; }
  set innerHTML(_v) { throw new Error('inner markup must never be assigned by brandy_activity.js'); }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.children.push(c);
    return c;
  }
  insertBefore(c, ref) {
    if (ref === null || ref === undefined) return this.appendChild(c);
    if (c.parentNode) c.parentNode.removeChild(c);
    const i = this.children.indexOf(ref);
    if (i < 0) throw new Error('NotFoundError: ref is not a child');
    c.parentNode = this;
    this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i < 0) throw new Error('NotFoundError: not a child');
    this.children.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  setAttribute(k, v) {
    if (k === 'class') { this.className = String(v); return; }
    this._attrs[k] = String(v);
  }
  getAttribute(k) {
    if (k === 'class') return this.className;
    return k in this._attrs ? this._attrs[k] : null;
  }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  removeAttribute(k) { if (k === 'class') this.className = ''; else delete this._attrs[k]; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => {
      n.children.forEach((c) => {
        if (matchesSimple(c, sel)) out.push(c);
        walk(c);
      });
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

class FakeCustomEvent {
  constructor(type, init) {
    this.type = type;
    this.detail = init && init.detail;
  }
}

function makeDocument() {
  const listeners = Object.create(null);
  const body = new FakeNode('body');
  const doc = {
    body,
    createElement(tag) { return new FakeNode(tag); },
    getElementById(id) { return body.querySelector('#' + id); },
    querySelector(sel) { return body.querySelector(sel); },
    querySelectorAll(sel) { return body.querySelectorAll(sel); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dispatchEvent(ev) { (listeners[ev.type] || []).slice().forEach((fn) => fn(ev)); return true; },
  };
  return doc;
}

/* Mirrors index.html: <aside class="prod"> > #Prod-Empty, #Prod-Jobs, #Brandy-Activity */
function addPanel(doc, opts) {
  const withContainer = !opts || opts.container !== false;
  const prod = doc.createElement('aside');
  prod.className = 'prod';
  const empty = doc.createElement('div');
  empty.id = 'Prod-Empty';
  const jobs = doc.createElement('div');
  jobs.id = 'Prod-Jobs';
  prod.appendChild(empty);
  prod.appendChild(jobs);
  doc.body.appendChild(prod);
  let ba = null;
  if (withContainer) {
    ba = addContainer(doc, prod);
  }
  return { prod, empty, jobs, ba };
}

function addContainer(doc, prod) {
  const ba = doc.createElement('section');
  ba.id = 'Brandy-Activity';
  ba.className = 'ba';
  ba.setAttribute('aria-live', 'polite');
  ba.setAttribute('hidden', '');
  prod.appendChild(ba);
  return ba;
}

/* ------------------------------------------------------------------ harness */

function boot(opts) {
  const doc = makeDocument();
  const panel = addPanel(doc, opts);
  const clock = { t: 1790740605431 };
  class FakeDate extends Date {
    static now() { return clock.t; }
  }
  const timers = { intervals: [], timeouts: [], nextId: 1 };
  const sandbox = {
    document: doc,
    window: {},
    Date: FakeDate,
    setInterval(fn, ms) {
      const rec = { id: timers.nextId++, fn, ms, cleared: false };
      timers.intervals.push(rec);
      return rec.id;
    },
    clearInterval(id) {
      timers.intervals.forEach((r) => { if (r.id === id) r.cleared = true; });
    },
    setTimeout(fn, ms) {
      const rec = { id: timers.nextId++, fn, ms, cleared: false };
      timers.timeouts.push(rec);
      return rec.id;
    },
    clearTimeout(id) {
      timers.timeouts.forEach((r) => { if (r.id === id) r.cleared = true; });
    },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox, { filename: 'brandy_activity.js' });
  const api = sandbox.window.BrandyActivity;
  const liveIntervals = () => timers.intervals.filter((r) => !r.cleared);
  return { doc, panel, clock, timers, api, liveIntervals, sandbox };
}

function rows(env) {
  const ba = env.doc.getElementById('Brandy-Activity');
  const list = ba ? ba.querySelector('.ba-list') : null;
  return list ? list.children : [];
}

function part(row, cls) { return row.querySelector('.' + cls); }

function fire(env, detail) {
  env.doc.dispatchEvent(new FakeCustomEvent('brandy:activity', { detail }));
}

/* ------------------------------------------------------------------- runner */

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
    console.log('ok   - ' + name);
  } catch (err) {
    results.push({ name, ok: false, err });
    console.log('FAIL - ' + name);
    console.log('       ' + (err && err.stack ? err.stack.split('\n').slice(0, 4).join('\n       ') : err));
  }
}

/* -------------------------------------------------------------------- tests */

check('API surface: window.BrandyActivity has push, clear, demo', () => {
  const env = boot();
  assert.strictEqual(typeof env.api, 'object');
  assert.strictEqual(typeof env.api.push, 'function');
  assert.strictEqual(typeof env.api.clear, 'function');
  assert.strictEqual(typeof env.api.demo, 'function');
});

check('nothing rendered and container stays hidden until the first push', () => {
  const env = boot();
  assert.strictEqual(rows(env).length, 0);
  assert.ok(env.panel.ba.hasAttribute('hidden'));
  assert.ok(!env.panel.prod.classList.contains('has-activity'));
});

check('a push creates a row with kind/state classes, glyph and text', () => {
  const env = boot();
  env.api.push({ id: 'tool-c_9', kind: 'saved', state: 'done', text: 'Saved symptom: "no sales yet" · Where you stand 4/7', at: env.clock.t });
  const r = rows(env);
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].tagName, 'LI');
  assert.ok(r[0].classList.contains('ba-row'));
  assert.ok(r[0].classList.contains('ba-row--saved'));
  assert.ok(r[0].classList.contains('ba-row--done'));
  assert.strictEqual(part(r[0], 'ba-glyph').textContent, '✓');
  assert.strictEqual(part(r[0], 'ba-text').textContent, 'Saved symptom: "no sales yet" · Where you stand 4/7');
});

check('header shows the "Brandy · live" eyebrow and a status dot', () => {
  const env = boot();
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'hi' });
  const ba = env.panel.ba;
  assert.ok(ba.querySelector('.ba-dot'));
  assert.strictEqual(ba.querySelector('.ba-eyebrow').textContent, 'Brandy · live');
  assert.strictEqual(ba.querySelectorAll('.ba-list').length, 1);
  assert.strictEqual(ba.querySelector('.ba-list').tagName, 'OL');
});

check('has-activity toggled on the .prod element and hidden removed on first row', () => {
  const env = boot();
  assert.ok(env.panel.ba.hasAttribute('hidden'));
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'x' });
  assert.ok(!env.panel.ba.hasAttribute('hidden'));
  assert.ok(env.panel.prod.classList.contains('has-activity'));
  // #Prod-Empty is owned by production_panel.js: the module must not touch it
  assert.deepStrictEqual(Object.keys(env.panel.empty.style), []);
  assert.deepStrictEqual(Object.keys(env.panel.jobs.style), []);
});

check('clear() empties the feed, re-hides the container and drops has-activity', () => {
  const env = boot();
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'x' });
  env.api.push({ id: 'b', kind: 'info', state: 'done', text: 'y' });
  env.api.clear();
  assert.strictEqual(rows(env).length, 0);
  assert.ok(env.panel.ba.hasAttribute('hidden'));
  assert.ok(!env.panel.prod.classList.contains('has-activity'));
  env.api.push({ id: 'c', kind: 'info', state: 'done', text: 'z' });
  assert.strictEqual(rows(env).length, 1);
  assert.ok(env.panel.prod.classList.contains('has-activity'));
});

check('same id updates in place (no duplicate) and shows a duration on done', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'turn-3', kind: 'thinking', state: 'active', text: 'Thinking…', at: t0 });
  assert.strictEqual(rows(env).length, 1);
  const el = rows(env)[0];
  assert.ok(el.classList.contains('ba-row--active'));
  env.clock.t = t0 + 1400;
  env.api.push({ id: 'turn-3', kind: 'thinking', state: 'done', text: 'Thought for 1.4 s', at: t0 + 1400 });
  const r = rows(env);
  assert.strictEqual(r.length, 1, 'no duplicate row for the same id');
  assert.strictEqual(r[0], el, 'the same DOM node is updated in place');
  assert.ok(r[0].classList.contains('ba-row--done'));
  assert.ok(!r[0].classList.contains('ba-row--active'));
  assert.strictEqual(part(r[0], 'ba-text').textContent, 'Thought for 1.4 s');
  assert.strictEqual(part(r[0], 'ba-meta').textContent, '1.4 s');
});

check('kind can change on update (working -> saved) and duration uses first "at"', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'tool-c_9', kind: 'working', state: 'active', text: 'Saving symptom', at: t0 });
  env.clock.t = t0 + 700;
  env.api.push({ id: 'tool-c_9', kind: 'saved', state: 'done', text: 'Saved', at: t0 + 700 });
  const r = rows(env);
  assert.strictEqual(r.length, 1);
  assert.ok(r[0].classList.contains('ba-row--saved'));
  assert.ok(!r[0].classList.contains('ba-row--working'));
  assert.strictEqual(part(r[0], 'ba-glyph').textContent, '✓');
  assert.strictEqual(part(r[0], 'ba-meta').textContent, '0.7 s');
});

check('failed update after active also gets a duration, error color class and "!" glyph', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'tool-x', kind: 'working', state: 'active', text: 'Saving', at: t0 });
  env.clock.t = t0 + 2500;
  env.api.push({ id: 'tool-x', kind: 'working', state: 'failed', text: 'Could not save', at: t0 + 2500 });
  const r = rows(env);
  assert.strictEqual(r.length, 1);
  assert.ok(r[0].classList.contains('ba-row--failed'));
  assert.strictEqual(part(r[0], 'ba-glyph').textContent, '!');
  assert.strictEqual(part(r[0], 'ba-meta').textContent, '2.5 s');
});

check('a row pushed directly as done has no duration, only relative time', () => {
  const env = boot();
  env.api.push({ id: 'd', kind: 'decision', state: 'done', text: 'Locked', at: env.clock.t });
  assert.strictEqual(part(rows(env)[0], 'ba-meta').textContent, 'now');
});

check('newest first: a later row is inserted above earlier ones', () => {
  const env = boot();
  env.api.push({ id: 'one', kind: 'info', state: 'done', text: 'first' });
  env.api.push({ id: 'two', kind: 'info', state: 'done', text: 'second' });
  env.api.push({ id: 'three', kind: 'info', state: 'done', text: 'third' });
  const texts = rows(env).map((r) => part(r, 'ba-text').textContent);
  assert.deepStrictEqual(texts.slice(), ['third', 'second', 'first']);
  // updating the oldest keeps its place (in-place update, not re-sorted)
  env.api.push({ id: 'one', kind: 'info', state: 'done', text: 'first (edited)' });
  const texts2 = rows(env).map((r) => part(r, 'ba-text').textContent);
  assert.deepStrictEqual(texts2.slice(), ['third', 'second', 'first (edited)']);
});

check('cap at 40 rows: oldest dropped, newest kept on top', () => {
  const env = boot();
  for (let i = 0; i < 45; i++) {
    env.api.push({ id: 'r' + i, kind: 'info', state: 'done', text: 'row ' + i });
  }
  const r = rows(env);
  assert.strictEqual(r.length, 40);
  assert.strictEqual(part(r[0], 'ba-text').textContent, 'row 44');
  assert.strictEqual(part(r[39], 'ba-text').textContent, 'row 5');
  // a dropped id that comes back is a brand-new row, not a crash
  env.api.push({ id: 'r0', kind: 'info', state: 'done', text: 'row 0 again' });
  assert.strictEqual(rows(env).length, 40);
  assert.strictEqual(part(rows(env)[0], 'ba-text').textContent, 'row 0 again');
});

check('unknown kind -> info, unknown state -> done', () => {
  const env = boot();
  env.api.push({ id: 'k', kind: 'banana', state: 'sideways', text: 'odd' });
  const el = rows(env)[0];
  assert.ok(el.classList.contains('ba-row--info'));
  assert.ok(el.classList.contains('ba-row--done'));
  assert.strictEqual(part(el, 'ba-glyph').textContent, 'i');
  assert.ok(!/banana|sideways/.test(el.className));
});

check('glyph per kind', () => {
  const env = boot();
  const expect = { thinking: '…', working: '◌', saved: '✓', decision: '◆', clarifying: '?', error: '!', info: 'i' };
  Object.keys(expect).forEach((kind) => {
    env.api.push({ id: 'g-' + kind, kind, state: 'done', text: kind });
  });
  const byText = {};
  rows(env).forEach((r) => { byText[part(r, 'ba-text').textContent] = r; });
  Object.keys(expect).forEach((kind) => {
    assert.strictEqual(part(byText[kind], 'ba-glyph').textContent, expect[kind], 'glyph for ' + kind);
    assert.ok(byText[kind].classList.contains('ba-row--' + kind));
  });
});

check('sanitize: text coerced to String and truncated to 160; missing id/at handled', () => {
  const env = boot();
  env.api.push({ id: 't1', kind: 'info', state: 'done', text: 12345 });
  env.api.push({ id: 't2', kind: 'info', state: 'done', text: 'x'.repeat(500) });
  env.api.push({ kind: 'info', state: 'done', text: 'no id one' });
  env.api.push({ kind: 'info', state: 'done', text: 'no id two' });
  env.api.push({ id: 't5', kind: 'info', state: 'done' });
  const r = rows(env);
  assert.strictEqual(r.length, 5, 'two id-less pushes are two distinct rows');
  const t = (i) => part(r[i], 'ba-text').textContent;
  assert.strictEqual(t(4), '12345');
  assert.ok(t(3).length <= 160, 'truncated');
  assert.ok(t(3).length >= 150, 'but not gutted');
  assert.strictEqual(t(2), 'no id one');
  assert.strictEqual(t(1), 'no id two');
  assert.strictEqual(t(0), '');
  assert.strictEqual(part(r[2], 'ba-meta').textContent, 'now', 'missing at defaults to Date.now()');
});

check('sanitize: hostile markup stays inert text, no elements are created from it', () => {
  const env = boot();
  const evil = '<img src=x onerror=alert(1)><script>alert(2)</script>';
  env.api.push({ id: 'evil', kind: 'error', state: 'failed', text: evil });
  const el = rows(env)[0];
  assert.strictEqual(part(el, 'ba-text').textContent, evil);
  assert.strictEqual(el.querySelectorAll('img').length, 0);
  assert.strictEqual(el.querySelectorAll('script').length, 0);
  assert.strictEqual(part(el, 'ba-text').children.length, 0);
});

check('non-object detail is ignored without throwing', () => {
  const env = boot();
  assert.doesNotThrow(() => env.api.push(null));
  assert.doesNotThrow(() => env.api.push(undefined));
  assert.doesNotThrow(() => env.api.push('nope'));
  assert.doesNotThrow(() => env.doc.dispatchEvent(new FakeCustomEvent('brandy:activity', {})));
  assert.doesNotThrow(() => env.doc.dispatchEvent({ type: 'brandy:activity' }));
  assert.strictEqual(rows(env).length, 0);
  assert.ok(env.panel.ba.hasAttribute('hidden'));
});

check('document "brandy:activity" event path creates and updates rows', () => {
  const env = boot();
  const t0 = env.clock.t;
  fire(env, { id: 'turn-7', kind: 'thinking', state: 'active', text: 'Thinking…', at: t0 });
  assert.strictEqual(rows(env).length, 1);
  env.clock.t = t0 + 1000;
  fire(env, { id: 'turn-7', kind: 'thinking', state: 'done', text: 'Thought for 1.0 s', at: t0 + 1000 });
  fire(env, { id: 'clarify-3', kind: 'clarifying', state: 'done', text: 'Clarifying your question', at: t0 + 1000 });
  const r = rows(env);
  assert.strictEqual(r.length, 2);
  assert.ok(r[0].classList.contains('ba-row--clarifying'));
  assert.strictEqual(part(r[1], 'ba-meta').textContent, '1.0 s');
  assert.ok(env.panel.prod.classList.contains('has-activity'));
});

check('status dot pulses (is-active) only while a row is active', () => {
  const env = boot();
  env.api.push({ id: 'a', kind: 'thinking', state: 'active', text: '...', at: env.clock.t });
  const dot = env.panel.ba.querySelector('.ba-dot');
  assert.ok(dot.classList.contains('is-active'));
  env.api.push({ id: 'b', kind: 'working', state: 'active', text: '...', at: env.clock.t });
  env.api.push({ id: 'a', kind: 'thinking', state: 'done', text: 'done', at: env.clock.t });
  assert.ok(dot.classList.contains('is-active'), 'still one active row');
  env.api.push({ id: 'b', kind: 'saved', state: 'done', text: 'done', at: env.clock.t });
  assert.ok(!dot.classList.contains('is-active'), 'idle once nothing is active');
});

check('done -> active again restarts the timing (no stale duration)', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'z', kind: 'working', state: 'active', text: 'a', at: t0 });
  env.api.push({ id: 'z', kind: 'working', state: 'done', text: 'a', at: t0 + 1000 });
  assert.strictEqual(part(rows(env)[0], 'ba-meta').textContent, '1.0 s');
  env.clock.t = t0 + 5000;
  env.api.push({ id: 'z', kind: 'working', state: 'active', text: 'again', at: t0 + 5000 });
  assert.notStrictEqual(part(rows(env)[0], 'ba-meta').textContent, '1.0 s');
  env.clock.t = t0 + 5900;
  env.api.push({ id: 'z', kind: 'working', state: 'done', text: 'again', at: t0 + 5900 });
  assert.strictEqual(part(rows(env)[0], 'ba-meta').textContent, '0.9 s');
});

check('demo() produces rows across every kind and leaves one live row', () => {
  const env = boot();
  env.api.demo();
  const r = rows(env);
  assert.ok(r.length >= 5, 'at least 5 rows, got ' + r.length);
  const has = (k) => r.some((x) => x.classList.contains('ba-row--' + k));
  ['thinking', 'saved', 'decision', 'clarifying', 'error'].forEach((k) => {
    assert.ok(has(k), 'demo shows kind ' + k);
  });
  assert.ok(r.some((x) => x.classList.contains('ba-row--failed')), 'demo shows a failed row');
  assert.ok(r.some((x) => x.classList.contains('ba-row--active')), 'demo leaves an active row');
  assert.ok(env.panel.prod.classList.contains('has-activity'));
  // the demo's delayed completion resolves the active row in place
  const live = env.timers.timeouts.filter((t) => !t.cleared);
  assert.ok(live.length >= 1, 'demo schedules the completion of its live row');
  const before = rows(env).length;
  live.forEach((t) => t.fn());
  assert.strictEqual(rows(env).length, before, 'completion updates in place');
  assert.ok(!rows(env).some((x) => x.classList.contains('ba-row--active')));
});

check('clear() cancels a pending demo completion (no ghost row afterwards)', () => {
  const env = boot();
  env.api.demo();
  env.api.clear();
  env.timers.timeouts.filter((t) => !t.cleared).forEach((t) => t.fn());
  assert.strictEqual(rows(env).length, 0);
});

check('lazy container: rows are buffered until #Brandy-Activity exists, then rendered on next push', () => {
  const env = boot({ container: false });
  assert.doesNotThrow(() => env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'first' }));
  assert.doesNotThrow(() => env.api.push({ id: 'b', kind: 'saved', state: 'done', text: 'second' }));
  assert.ok(!env.panel.prod.classList.contains('has-activity'), 'empty state must stay while nothing can render');
  const ba = addContainer(env.doc, env.panel.prod);
  env.api.push({ id: 'c', kind: 'decision', state: 'done', text: 'third' });
  const list = ba.querySelector('.ba-list');
  assert.ok(list, 'list built once the container appeared');
  const texts = list.children.map((r) => part(r, 'ba-text').textContent);
  assert.deepStrictEqual(texts.slice(), ['third', 'second', 'first']);
  assert.ok(!ba.hasAttribute('hidden'));
  assert.ok(env.panel.prod.classList.contains('has-activity'));
});

check('lazy container: works when the container is added before any push (script loaded first)', () => {
  const env = boot({ container: false });
  const ba = addContainer(env.doc, env.panel.prod);
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'hello' });
  assert.strictEqual(ba.querySelector('.ba-list').children.length, 1);
});

check('one ticker: none before rows, exactly one while rows exist (10 s), none after clear()', () => {
  const env = boot();
  assert.strictEqual(env.liveIntervals().length, 0);
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: '1' });
  env.api.push({ id: 'b', kind: 'info', state: 'done', text: '2' });
  env.api.push({ id: 'c', kind: 'info', state: 'done', text: '3' });
  assert.strictEqual(env.liveIntervals().length, 1);
  assert.strictEqual(env.liveIntervals()[0].ms, 10000);
  env.api.clear();
  assert.strictEqual(env.liveIntervals().length, 0);
  env.api.push({ id: 'd', kind: 'info', state: 'done', text: '4' });
  assert.strictEqual(env.liveIntervals().length, 1, 'ticker restarts with new rows');
});

check('ticker refreshes relative time: now -> 12 s -> 3 min', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'a', kind: 'info', state: 'done', text: 'x', at: t0 });
  const meta = () => part(rows(env)[0], 'ba-meta').textContent;
  assert.strictEqual(meta(), 'now');
  env.clock.t = t0 + 12000;
  env.liveIntervals()[0].fn();
  assert.strictEqual(meta(), '12 s');
  env.clock.t = t0 + 3 * 60000 + 5000;
  env.liveIntervals()[0].fn();
  assert.strictEqual(meta(), '3 min');
});

check('active row shows elapsed time since its first "at" and keeps ticking', () => {
  const env = boot();
  const t0 = env.clock.t;
  env.api.push({ id: 'a', kind: 'thinking', state: 'active', text: '...', at: t0 });
  env.clock.t = t0 + 20000;
  env.liveIntervals()[0].fn();
  assert.strictEqual(part(rows(env)[0], 'ba-meta').textContent, '20 s');
});

check('source contains no inner-markup APIs (innerHTML / outerHTML / insertAdjacentHTML / document.write)', () => {
  assert.ok(!/innerHTML/.test(SRC), 'innerHTML');
  assert.ok(!/outerHTML/.test(SRC), 'outerHTML');
  assert.ok(!/insertAdjacentHTML/.test(SRC), 'insertAdjacentHTML');
  assert.ok(!/document\.write/.test(SRC), 'document.write');
  assert.ok(!/\beval\s*\(|new Function/.test(SRC), 'eval');
});

check('source is a strict-mode IIFE and does not touch production_panel.js territory', () => {
  assert.ok(/'use strict'/.test(SRC));
  assert.ok(/^\s*(\/\*[\s\S]*?\*\/\s*)?\(function/.test(SRC), 'starts with an IIFE');
  assert.ok(!/Prod-Empty|Prod-Jobs|Prod-Subtext/.test(SRC), 'must not reference production_panel.js elements');
});

check('index.html wiring: container after #Prod-Jobs in .prod, has-activity CSS, script after production_panel.js', () => {
  const html = fs.readFileSync(path.join(REPO_ROOT, 'app', 'static', 'index.html'), 'utf8');
  const asideStart = html.indexOf('<aside class="prod">');
  const asideEnd = html.indexOf('</aside>', asideStart);
  assert.ok(asideStart > 0 && asideEnd > asideStart);
  const aside = html.slice(asideStart, asideEnd);
  const jobsAt = aside.indexOf('id="Prod-Jobs"');
  const baAt = aside.indexOf('id="Brandy-Activity"');
  assert.ok(jobsAt > 0 && baAt > jobsAt, '#Brandy-Activity goes after #Prod-Jobs inside the aside');
  assert.ok(/<section class="ba" id="Brandy-Activity" aria-live="polite" hidden>/.test(aside));
  assert.ok(/\.prod\.has-activity #Prod-Empty\s*\{\s*display:\s*none\s*!important/.test(html));
  assert.ok(/@media\s*\(prefers-reduced-motion:\s*reduce\)/.test(html));
  const panelTag = '<script src="/static/production_panel.js"></script>';
  const baTag = '<script src="/static/brandy_activity.js"></script>';
  const panelPos = html.indexOf(panelTag);
  const baPos = html.indexOf(baTag);
  assert.ok(panelPos > 0 && baPos > panelPos, 'script tag after production_panel.js');
  assert.strictEqual(html.slice(panelPos + panelTag.length).replace(/^\r?\n/, '').indexOf(baTag), 0, 'on the line right after');
});

/* ------------------------------------------------------------------ verdict */

const failed = results.filter((r) => !r.ok);
if (failed.length) {
  console.log('\n' + failed.length + ' of ' + results.length + ' checks failed');
  process.exit(1);
}
console.log('\nOK (' + results.length + ' checks)');
