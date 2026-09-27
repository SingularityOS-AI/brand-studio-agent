/**
 * Brand Studio Agent -- Production panel (Block F, F-03)
 *
 * The right panel ("Production", #Prod-Jobs in index.html) becomes the audit
 * trail/queue for every pipeline action -- voice and button -- in every
 * step, per docs/specs/F/spec.md ("Panel") and
 * docs/specs/F/pieces/F-03_production_panel_audit.md. It reads the F-02 API
 * (GET /api/agent/actions) and never talks to any other endpoint.
 *
 * app.js calls BrandStudioPanel.refresh() after its existing job refresh
 * points and on step change so the list updates immediately; this module
 * also polls every 5s on its own while anything is queued/running, so it
 * stays current even without an explicit refresh() call.
 */
(function () {
  'use strict';

  var POLL_MS = 5000;
  var pollTimer = null;
  var lastActions = [];
  var styleInjected = false;

  function brandStudio() {
    return (typeof window !== 'undefined' && window.BrandStudio) ? window.BrandStudio : null;
  }

  function actionRegistry() {
    return (typeof window !== 'undefined' && window.BrandStudioActions) ? window.BrandStudioActions : null;
  }

  function panelEls() {
    return {
      jobs: document.getElementById('Prod-Jobs'),
      empty: document.getElementById('Prod-Empty'),
      subtext: document.getElementById('Prod-Subtext'),
    };
  }

  function capitalize(value) {
    var s = String(value || '');
    if (!s) return '';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // Voice rows carry a registered action id (e.g. "script.iterate_scene") --
  // look up the same human title actions.js already defines for it (the
  // exact label read out loud / shown next to the button). Button rows carry
  // "METHOD /api/.../route" (per F-02); fall back to the last path segment,
  // humanized, since there is no title registry for those.
  function titleForAction(row) {
    if (row.source === 'voice') {
      var registry = actionRegistry();
      var def = registry ? registry.get(row.action) : null;
      if (def && def.title) return def.title;
    }
    var raw = String(row.action || '').trim();
    if (!raw) return 'Action';
    var pathPart = raw.indexOf(' ') >= 0 ? raw.slice(raw.indexOf(' ') + 1) : raw;
    var segments = pathPart.split(/[./]+/).filter(function (part) {
      return part && part.indexOf('{') !== 0;
    });
    var last = segments.length ? segments[segments.length - 1] : raw;
    last = last.replace(/[{}]/g, '').replace(/[_-]+/g, ' ').trim();
    if (!last) last = raw;
    return capitalize(last);
  }

  function relativeTime(iso) {
    if (!iso) return '';
    var then = new Date(iso).getTime();
    if (Number.isNaN(then)) return '';
    var diffSec = Math.round((Date.now() - then) / 1000);
    if (diffSec < 5) return 'just now';
    if (diffSec < 60) return diffSec + 's ago';
    var diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return diffMin + 'm ago';
    var diffHour = Math.round(diffMin / 60);
    if (diffHour < 24) return diffHour + 'h ago';
    var diffDay = Math.round(diffHour / 24);
    return diffDay + 'd ago';
  }

  function costLabel(credits) {
    if (credits === null || credits === undefined) return '';
    if (credits <= 0) return 'Free';
    return '−' + credits + ' credits';
  }

  // Guards the "Open" link: result_ref is backend-written (service role
  // only, per F-02), but this stays defensive against ever getting a
  // javascript:/data: URI into an href.
  function isSafeHref(value) {
    return typeof value === 'string' && /^(https?:\/\/|\/)\S*$/i.test(value);
  }

  function addVoiceLine(container, label, value) {
    if (value === null || value === undefined || value === '') return;
    var p = document.createElement('p');
    p.className = 'pp-voice-line';
    var strong = document.createElement('strong');
    strong.textContent = label + ': ';
    p.appendChild(strong);
    var span = document.createElement('span');
    span.textContent = value;
    p.appendChild(span);
    container.appendChild(p);
  }

  function buildCard(row) {
    var card = document.createElement('div');
    card.className = 'pp-card';
    card.setAttribute('data-status', row.status || '');
    card.setAttribute('data-source', row.source || '');

    var head = document.createElement('div');
    head.className = 'pp-card__head';

    var icon = document.createElement('span');
    icon.className = 'pp-icon pp-icon--' + (row.source === 'voice' ? 'voice' : 'button');
    icon.setAttribute('aria-hidden', 'true');
    // Static glyphs, never derived from row data.
    icon.textContent = row.source === 'voice' ? '\u{1F3A4}' : '\u{1F5B1}';
    head.appendChild(icon);

    var title = document.createElement('span');
    title.className = 'pp-title';
    title.textContent = titleForAction(row);
    head.appendChild(title);

    var chip = document.createElement('span');
    chip.className = 'pp-chip pp-chip--' + (row.status || 'unknown');
    chip.textContent = capitalize(row.status);
    head.appendChild(chip);

    card.appendChild(head);

    var meta = document.createElement('div');
    meta.className = 'pp-meta';

    var step = document.createElement('span');
    step.className = 'pp-step';
    step.textContent = capitalize(row.step);
    meta.appendChild(step);

    var cost = document.createElement('span');
    cost.className = 'pp-cost';
    cost.textContent = costLabel(row.credits);
    meta.appendChild(cost);

    var time = document.createElement('span');
    time.className = 'pp-time';
    time.textContent = relativeTime(row.created_at);
    meta.appendChild(time);

    card.appendChild(meta);

    if (row.source === 'voice') {
      var detail = document.createElement('div');
      detail.className = 'pp-voice-detail';
      addVoiceLine(detail, 'You said', row.utterance);
      addVoiceLine(detail, 'Brandy', row.restatement);
      addVoiceLine(detail, 'Confirmed', row.confirmation);
      if (detail.childNodes && detail.childNodes.length) {
        card.appendChild(detail);
      }
    }

    if (row.result_ref && isSafeHref(row.result_ref)) {
      var link = document.createElement('a');
      link.className = 'pp-open';
      link.textContent = 'Open';
      link.setAttribute('href', row.result_ref);
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
      card.appendChild(link);
    }

    return card;
  }

  function render(actions) {
    var elements = panelEls();
    if (!elements.jobs) return;

    while (elements.jobs.firstChild) {
      elements.jobs.removeChild(elements.jobs.firstChild);
    }

    if (!actions || actions.length === 0) {
      elements.jobs.style.display = 'none';
      if (elements.empty) elements.empty.style.display = 'flex';
      if (elements.subtext) elements.subtext.textContent = 'Empty until there is something to produce.';
      return;
    }

    if (elements.empty) elements.empty.style.display = 'none';
    elements.jobs.style.display = 'block';

    for (var i = 0; i < actions.length; i++) {
      elements.jobs.appendChild(buildCard(actions[i]));
    }

    if (elements.subtext) {
      elements.subtext.textContent = actions.length + (actions.length === 1 ? ' action' : ' actions') + ' for this idea.';
    }
  }

  function hasActiveJobs(actions) {
    return (actions || []).some(function (row) {
      return row.status === 'queued' || row.status === 'running';
    });
  }

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setInterval(function () {
      if (!hasActiveJobs(lastActions)) {
        clearInterval(pollTimer);
        pollTimer = null;
        return;
      }
      refresh();
    }, POLL_MS);
  }

  function refresh(ideaIdArg) {
    var bs = brandStudio();
    if (!bs || typeof bs.authenticatedFetch !== 'function') return Promise.resolve();

    var ideaId = ideaIdArg;
    if (!ideaId && typeof bs.getCurrentScriptIdeaId === 'function') {
      ideaId = bs.getCurrentScriptIdeaId();
    }

    var url = '/api/agent/actions?limit=50';
    if (ideaId) url += '&idea_id=' + encodeURIComponent(ideaId);

    return bs.authenticatedFetch(url)
      .then(function (res) {
        if (!res || !res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        lastActions = (data && data.actions) || [];
        render(lastActions);
        if (hasActiveJobs(lastActions)) schedulePoll();
      })
      .catch(function (err) {
        console.warn('[ProductionPanel] Failed to refresh actions:', err);
      });
  }

  function injectStyleOnce() {
    if (styleInjected || typeof document === 'undefined' || !document.head) return;
    styleInjected = true;
    var style = document.createElement('style');
    style.setAttribute('data-source', 'production_panel.js');
    style.textContent = [
      '.pp-card{border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin:0 16px 10px;background:var(--surface)}',
      '.pp-card__head{display:flex;align-items:center;gap:8px}',
      '.pp-icon{font-size:13px;line-height:1}',
      '.pp-title{flex:1;font-size:13px;font-weight:600;color:var(--ink)}',
      '.pp-chip{font-size:10px;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:10px;border:1px solid var(--line);color:var(--ink-soft)}',
      '.pp-chip--done{color:#1E7B4D;border-color:#1E7B4D}',
      '.pp-chip--failed{color:#B5311C;border-color:#B5311C}',
      '.pp-chip--running{color:var(--accent);border-color:var(--accent)}',
      '.pp-chip--queued{color:var(--warn);border-color:var(--warn)}',
      '.pp-chip--cancelled{color:var(--ink-soft);border-color:var(--line)}',
      '.pp-meta{display:flex;gap:10px;margin-top:6px;font-size:11px;color:var(--ink-soft)}',
      '.pp-voice-detail{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}',
      '.pp-voice-line{margin:0 0 4px;font-size:12px;color:var(--ink-soft);word-break:break-word}',
      '.pp-voice-line strong{color:var(--ink)}',
      '.pp-open{display:inline-block;margin-top:8px;font-size:12px;color:var(--accent);text-decoration:none}',
      '.pp-open:hover{text-decoration:underline}',
    ].join('\n');
    document.head.appendChild(style);
  }

  var BrandStudioPanel = {
    refresh: refresh,
  };

  if (typeof window !== 'undefined') {
    window.BrandStudioPanel = BrandStudioPanel;
    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
      document.addEventListener('DOMContentLoaded', function () {
        injectStyleOnce();
        refresh();
      });
    }
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = BrandStudioPanel;
  }
})();
