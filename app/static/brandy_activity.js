/**
 * Brand Studio Agent -- "Brandy - live" activity feed (BR-B)
 *
 * A running trail of what Brandy is doing during a voice turn (thinking,
 * saving, locking decisions, clarifying, failing), rendered in the right
 * panel (#Brandy-Activity inside <aside class="prod">). It replaces the
 * "Nothing queued" empty state while it has rows, purely through CSS in
 * index.html keyed on the .has-activity class this file puts on the aside --
 * it never touches the elements owned by production_panel.js.
 *
 * Input contract (emitted by the voice loop, consumed here):
 *   document.dispatchEvent(new CustomEvent('brandy:activity', { detail: {
 *     id,     // same id => that row is updated in place
 *     kind,   // thinking | working | saved | decision | clarifying | error | info
 *     state,  // active | done | failed
 *     text,   // short human sentence (truncated to 160 chars)
 *     at      // Date.now()
 *   }}));
 *
 * API: window.BrandyActivity = { push(detail), clear(), demo() }
 * Rows are built only with createElement / textContent / classList: the
 * founder's own words can appear in `text`, so no markup is ever parsed.
 */
(function () {
  'use strict';

  var MAX_ROWS = 40;
  var MAX_TEXT = 160;
  var TICK_MS = 10000;
  var DEMO_LIVE_MS = 2500;
  var CONTAINER_ID = 'Brandy-Activity';

  var KINDS = {
    thinking: true, working: true, saved: true, decision: true,
    clarifying: true, error: true, info: true,
  };
  var STATES = { active: true, done: true, failed: true };
  var GLYPHS = {
    thinking: '…',   // ...
    working: '◌',    // dotted circle, spun by CSS while active
    saved: '✓',      // check mark
    decision: '◆',   // diamond
    clarifying: '?',
    error: '!',
    info: 'i',
  };

  var rows = [];                       // newest first
  var byId = Object.create(null);
  var container = null;
  var listEl = null;
  var dotEl = null;
  var ticker = null;
  var autoSeq = 0;
  var demoSeq = 0;
  var demoTimers = [];

  /* ------------------------------------------------------------ helpers */

  function now() { return Date.now(); }

  function unref(handle) {
    if (handle && typeof handle.unref === 'function') handle.unref();
    return handle;
  }

  function formatDuration(ms) {
    if (ms < 60000) return (ms / 1000).toFixed(1) + ' s';
    var total = Math.floor(ms / 1000);
    var m = Math.floor(total / 60);
    var s = total % 60;
    return m + ' min' + (s ? ' ' + s + ' s' : '');
  }

  function relativeTime(ageMs) {
    if (!(ageMs > 5000)) return 'now';   // also covers clock skew and NaN
    var s = Math.floor(ageMs / 1000);
    if (s < 60) return s + ' s';
    var m = Math.floor(s / 60);
    if (m < 60) return m + ' min';
    return Math.floor(m / 60) + ' h';
  }

  function metaFor(row) {
    if (row.durationMs !== null) return formatDuration(row.durationMs);
    var since = row.state === 'active' ? row.firstAt : row.at;
    return relativeTime(now() - since);
  }

  function normalize(detail) {
    var d = detail;
    var text = String(d.text === undefined || d.text === null ? '' : d.text);
    if (text.length > MAX_TEXT) text = text.slice(0, MAX_TEXT - 1) + '…';
    var id = d.id === undefined || d.id === null ? '' : String(d.id);
    if (!id) id = 'ba-auto-' + (++autoSeq);
    var at = typeof d.at === 'number' && isFinite(d.at) ? d.at : now();
    return {
      id: id,
      kind: typeof d.kind === 'string' && KINDS[d.kind] === true ? d.kind : 'info',
      state: typeof d.state === 'string' && STATES[d.state] === true ? d.state : 'done',
      text: text,
      at: at,
    };
  }

  function el(tag, className) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  /* ---------------------------------------------------------- container */

  function findProd() {
    var n = container ? container.parentNode : null;
    while (n) {
      if (n.classList && n.classList.contains('prod')) return n;
      n = n.parentNode;
    }
    return typeof document.querySelector === 'function' ? document.querySelector('.prod') : null;
  }

  // Finds #Brandy-Activity lazily (the script can load before the markup
  // exists). The first time it is found, header + list are built and every
  // buffered row is painted, oldest first so the newest ends up on top.
  function attach() {
    if (container) return true;
    var c = document.getElementById(CONTAINER_ID);
    if (!c) return false;
    container = c;

    var head = el('div', 'ba-head');
    dotEl = el('span', 'ba-dot');
    dotEl.setAttribute('aria-hidden', 'true');
    var label = el('span', 'eyebrow ba-eyebrow');
    label.textContent = 'Brandy · live';
    head.appendChild(dotEl);
    head.appendChild(label);
    listEl = el('ol', 'ba-list');
    container.appendChild(head);
    container.appendChild(listEl);

    for (var i = rows.length - 1; i >= 0; i--) paintRow(rows[i]);
    return true;
  }

  function syncVisibility() {
    if (!container) return;
    var prod = findProd();
    if (rows.length > 0) {
      container.removeAttribute('hidden');
      if (prod) prod.classList.add('has-activity');
    } else {
      container.setAttribute('hidden', '');
      if (prod) prod.classList.remove('has-activity');
    }
  }

  function syncDot() {
    if (!dotEl) return;
    var active = false;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].state === 'active') { active = true; break; }
    }
    if (active) dotEl.classList.add('is-active');
    else dotEl.classList.remove('is-active');
  }

  /* ---------------------------------------------------------------- rows */

  function paintRow(row) {
    if (!row.el) {
      row.el = el('li');
      row.glyphEl = el('span', 'ba-glyph');
      row.glyphEl.setAttribute('aria-hidden', 'true');
      row.textEl = el('span', 'ba-text');
      row.metaEl = el('span', 'ba-meta');
      row.metaEl.setAttribute('aria-hidden', 'true');
      row.el.appendChild(row.glyphEl);
      row.el.appendChild(row.textEl);
      row.el.appendChild(row.metaEl);
      listEl.insertBefore(row.el, listEl.firstChild);
    }
    row.el.className = 'ba-row ba-row--' + row.kind + ' ba-row--' + row.state;
    row.glyphEl.textContent = row.state === 'failed' ? '!' : GLYPHS[row.kind];
    row.textEl.textContent = row.text;
    row.metaEl.textContent = metaFor(row);
  }

  function applyUpdate(row, d) {
    var prev = row.state;
    row.kind = d.kind;
    row.text = d.text;
    row.at = d.at;
    if (d.state === 'active') {
      if (prev !== 'active') {      // (re)started: timing begins again
        row.firstAt = d.at;
        row.durationMs = null;
      }
    } else if (prev === 'active') {  // active -> done/failed: how long it took
      row.durationMs = Math.max(0, d.at - row.firstAt);
    }
    row.state = d.state;
  }

  function trim() {
    while (rows.length > MAX_ROWS) {
      var old = rows.pop();
      delete byId[old.id];
      if (old.el && old.el.parentNode) old.el.parentNode.removeChild(old.el);
    }
  }

  function refreshMeta() {
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].metaEl) rows[i].metaEl.textContent = metaFor(rows[i]);
    }
  }

  function startTicker() {
    if (ticker !== null) return;
    ticker = unref(setInterval(refreshMeta, TICK_MS));
  }

  function stopTicker() {
    if (ticker === null) return;
    clearInterval(ticker);
    ticker = null;
  }

  /* ----------------------------------------------------------------- API */

  function push(detail) {
    if (!detail || typeof detail !== 'object') return null;
    try {
      var d = normalize(detail);
      var row = byId[d.id];
      if (row) {
        applyUpdate(row, d);
      } else {
        row = {
          id: d.id, kind: d.kind, state: d.state, text: d.text,
          firstAt: d.at, at: d.at, durationMs: null,
          el: null, glyphEl: null, textEl: null, metaEl: null,
        };
        byId[d.id] = row;
        rows.unshift(row);
        trim();
      }
      startTicker();
      if (attach()) {
        paintRow(row);
        syncVisibility();
        syncDot();
      }
      return d.id;
    } catch (err) {
      if (typeof console !== 'undefined' && console.error) console.error('BrandyActivity.push failed', err);
      return null;
    }
  }

  function clear() {
    for (var i = 0; i < demoTimers.length; i++) clearTimeout(demoTimers[i]);
    demoTimers = [];
    rows = [];
    byId = Object.create(null);
    stopTicker();
    if (listEl) {
      while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
    }
    syncVisibility();
    syncDot();
  }

  // Console helper: BrandyActivity.demo() shows every kind of row, with one
  // row left "active" that finishes on its own a couple of seconds later.
  function demo() {
    var n = ++demoSeq;
    var p = 'demo' + n + '-';
    var t = now();
    push({ id: p + 'turn', kind: 'thinking', state: 'active', text: 'Thinking…', at: t - 9000 });
    push({ id: p + 'turn', kind: 'thinking', state: 'done', text: 'Thought for 1.4 s', at: t - 7600 });
    push({ id: p + 'save', kind: 'working', state: 'active', text: 'Saving symptom → Where you stand', at: t - 7000 });
    push({ id: p + 'save', kind: 'saved', state: 'done', text: 'Saved symptom: "no sales yet" · Where you stand 4/7', at: t - 6300 });
    push({ id: p + 'lock', kind: 'decision', state: 'done', text: 'Locked "Where you stand" with your yes', at: t - 4000 });
    push({ id: p + 'ask', kind: 'clarifying', state: 'done', text: 'Clarifying your question', at: t - 2500 });
    push({ id: p + 'oops', kind: 'error', state: 'failed', text: 'Could not save that answer. Trying again.', at: t - 1000 });
    push({ id: p + 'live', kind: 'working', state: 'active', text: 'Saving offer → What you sell', at: t });
    demoTimers.push(unref(setTimeout(function () {
      push({ id: p + 'live', kind: 'saved', state: 'done', text: 'Saved offer: "done-for-you onboarding" · What you sell 5/7', at: now() });
    }, DEMO_LIVE_MS)));
  }

  window.BrandyActivity = { push: push, clear: clear, demo: demo };

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('brandy:activity', function (e) {
      push(e && e.detail);
    });
  }
})();
