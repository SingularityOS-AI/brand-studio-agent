/**
 * Brand Studio Agent -- voice tool dispatcher (the missing F-06 wiring).
 *
 * Brandy's agentic tools (catalog_*, script_*, av_*, edit_*, soul_generate,
 * get_status, get_balance, go_to_step, confirm_action) were declared in agent.js
 * but no code ever executed them: every tool.call was answered "not available".
 * This module maps each tool name to the SAME registered action the buttons use
 * (window.BrandStudioActions, principle 2), and runs paid or irreversible actions
 * only after the founder says "confirm" (confirm_engine.js, principle 3).
 *
 * Contract (used by app.js handleToolCall):
 *   BrandStudioVoiceTools.isVoiceTool(name)      -> boolean
 *   BrandStudioVoiceTools.resolveActionId(name)  -> registry id | null
 *   BrandStudioVoiceTools.handle(name, args, deps) -> Promise<payload>, never rejects
 *   payload = { success, status, say?, error?, token?, cost?, result? }
 *           + non-enumerable payload._activity { kind, state, text } (right panel)
 *   deps = { actions, agent, currentStep(), ctx(), lastFounderWords(), founderTurns(),
 *            navigate(step) -> Promise<{ok, error?}>, currentIdeaId() }
 */
(function () {
  'use strict';

  const INTERVIEW_TOOLS = { extract_brand_brain: true, confirm_brand_section: true };
  const GLOBAL = { get_status: true, get_balance: true, go_to_step: true, confirm_action: true, propose_action: true };
  const STEP_LABELS = { brain: 'Brand Soul', catalog: 'Catalog', script: 'Script', audiovisual: 'Audiovisual', editing: 'Editing' };
  const STEP_ORDER = ['brain', 'catalog', 'script', 'audiovisual', 'editing'];
  const EXPLICIT = {
    script_explain_audit: 'script.audit',
    script_edit_text: 'script.edit_scene_text',
    soul_generate: 'soul.generate',
    soul_regenerate: 'soul.regenerate',
  };

  let engine = null;
  let pendingMeta = null;   // { actionId, args, title, cost, turnsAtProposal }

  function getEngine() {
    if (engine) return engine;
    const root = typeof window !== 'undefined' ? window : {};
    const mod = root.BrandStudioConfirmEngine ||
      (typeof require === 'function' ? require('./confirm_engine.js') : null);
    engine = mod.createConfirmationEngine({ maxAgeMs: 45000 });
    return engine;
  }

  function withActivity(payload, activity) {
    Object.defineProperty(payload, '_activity', { value: activity, enumerable: false, configurable: true, writable: true });
    return payload;
  }

  function clip(value, max) {
    const t = String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
    return t.length > max ? t.slice(0, max - 1) + '…' : t;
  }

  function summarize(result) {
    if (result == null) return 'Done.';
    if (typeof result === 'string') return clip(result, 400);
    if (Array.isArray(result)) {
      if (!result.length) return 'Nothing to report.';
      return clip(result.map(function (r) {
        return typeof r === 'string' ? r : (r && (r.message || r.rule || r.title || r.say)) || JSON.stringify(r);
      }).join(' | '), 400);
    }
    if (typeof result === 'object') {
      const text = result.say || result.message || result.summary || result.text;
      if (text) return clip(text, 400);
      try { return clip(JSON.stringify(result), 400); } catch (e) { return 'Done.'; }
    }
    return clip(result, 400);
  }

  function resolveActionId(name, actions) {
    const reg = actions || (typeof window !== 'undefined' ? window.BrandStudioActions : null);
    if (!reg || !name) return null;
    const exists = function (id) { return !!reg.get(id); };
    if (EXPLICIT[name] && exists(EXPLICIT[name])) return EXPLICIT[name];
    if (exists(name)) return reg.get(name).id;
    const dotted = String(name).replace('_', '.');
    if (exists(dotted)) return reg.get(dotted).id;
    return null;
  }

  function isVoiceTool(name) {
    return !!name && !INTERVIEW_TOOLS[name];
  }

  function toInt(v) {
    if (typeof v === 'number') return Math.round(v);
    const m = String(v == null ? '' : v).match(/\d+/);
    return m ? parseInt(m[0], 10) : NaN;
  }
  function toBool(v) {
    if (typeof v === 'boolean') return v;
    return /^(true|on|yes|1|enable|enabled)$/i.test(String(v || '').trim());
  }

  // Tool schema params -> what each registered run(args) reads.
  function normalizeArgs(actionId, raw, deps) {
    const a = Object.assign({}, raw || {});
    const needScene = function () {
      const n = toInt(a.scene_n != null ? a.scene_n : (a.scene != null ? a.scene : a.sceneN));
      if (!(n >= 1)) return { error: 'Need the scene number. Ask the founder which scene (1, 2, 3...).' };
      a.scene_n = n; a.sceneN = n;
      return null;
    };
    switch (actionId) {
      case 'script.iterate_scene':
      case 'script.edit_scene_text': {
        const e = needScene(); if (e) return e;
        a.sceneIdx = a.scene_n - 1;
        if (actionId === 'script.iterate_scene' && !String(a.instruction || '').trim()) {
          return { error: 'Need the instruction for scene ' + a.scene_n + '. Ask the founder how to change it.' };
        }
        if (actionId === 'script.edit_scene_text' && !String(a.text || '').trim()) {
          return { error: 'Need the new text for scene ' + a.scene_n + '. Ask the founder to dictate it.' };
        }
        return { args: a };
      }
      case 'av_read_scene':
      case 'audiovisual.change_scene_type':
      case 'audiovisual.regenerate_one':
      case 'audiovisual.open_recording_studio':
      case 'edit_scene_visual':
      case 'edit_trim':
      case 'edit_try_another_take': {
        const e = needScene(); if (e) return e;
        if (actionId === 'audiovisual.change_scene_type') {
          a.type = String(a.type || a.asset_type || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
          if (!a.type) return { error: 'Need the asset type: a_roll, stock, ai_video or motion_graphic.' };
        }
        return { args: a };
      }
      case 'catalog.regenerate_idea':
      case 'catalog.accept':
      case 'catalog.discard':
      case 'catalog.explain_demand':
        if (a.idea == null || String(a.idea).trim() === '') return { error: 'Need which idea (its number or title). Ask the founder.' };
        return { args: a };
      case 'catalog.add_idea':
        if (!String(a.text || a.title || '').trim()) return { error: 'Need the idea title. Ask the founder for it.' };
        a.text = a.text || a.title;
        return { args: a };
      case 'edit_music':
      case 'edit_sfx':
      case 'edit_overlays':
        a.on = toBool(a.on);
        return { args: a };
      case 'edit_overlay_delete': {
        const n = toInt(a.n);
        if (!(n >= 1)) return { error: 'Need the overlay number. Ask the founder which one.' };
        a.n = n;
        return { args: a };
      }
      case 'edit_render':
        a._ideaId = deps && deps.currentIdeaId ? deps.currentIdeaId() : null;
        return { args: a };
      default:
        return { args: a };
    }
  }

  async function costOf(action, args) {
    try {
      if (typeof action.cost !== 'function') return 0;
      const c = await action.cost(args);
      return typeof c === 'number' && isFinite(c) ? c : null;
    } catch (e) {
      return null;
    }
  }

  async function runAction(deps, actionId, action, args, voiceMeta) {
    const out = await deps.actions.execute(actionId, args, { source: 'voice', voiceMeta: voiceMeta || {} });
    if (out && out.ok) {
      return withActivity({ success: true, status: 'done', result: summarize(out.result) },
        { kind: 'saved', state: 'done', text: 'Done: ' + action.title });
    }
    const err = (out && out.error) || 'unknown error';
    return withActivity({ success: false, status: 'error', error: action.title + ' failed: ' + clip(err, 160) + '. Tell the founder in one sentence and offer to retry.' },
      { kind: 'error', state: 'failed', text: action.title + ' failed' });
  }

  async function handleAction(name, rawArgs, deps) {
    const actionId = resolveActionId(name, deps.actions);
    const action = actionId ? deps.actions.get(actionId) : null;
    if (!action) {
      return withActivity({ success: false, status: 'error', error: 'Unknown tool "' + name + '". Use only the tools listed.' },
        { kind: 'error', state: 'failed', text: 'Unknown tool ' + clip(name, 40) });
    }
    const step = deps.currentStep();
    if (action.step && action.step !== step) {
      const label = STEP_LABELS[action.step] || action.step;
      return withActivity({ success: false, status: 'wrong_step', say: 'That is done in ' + label + '. Say "go to ' + label + '" first.' },
        { kind: 'clarifying', state: 'done', text: 'Needs: go to ' + label + ' first' });
    }
    const norm = normalizeArgs(actionId, rawArgs, deps);
    if (norm.error) {
      return withActivity({ success: false, status: 'error', error: norm.error },
        { kind: 'clarifying', state: 'done', text: 'Needs: ' + clip(norm.error.replace(/^Need /, ''), 80) });
    }
    if (action.needsConfirm) {
      const cost = await costOf(action, norm.args);
      getEngine().propose({ actionId: actionId, args: norm.args, cost: cost });
      const snap = getEngine().pending();
      pendingMeta = { actionId: actionId, args: norm.args, title: action.title, cost: cost,
        turnsAtProposal: deps.founderTurns ? deps.founderTurns() : 0 };
      const price = cost ? (cost + ' credits') : (cost === 0 ? 'no credits' : 'the listed price');
      return withActivity({
        success: true, status: 'needs_confirmation', token: snap && snap.token, cost: cost,
        say: action.title + ' for ' + price + '. Ask the founder to say "confirm" to go ahead.'
      }, { kind: 'clarifying', state: 'done', text: 'Waiting for your "confirm": ' + action.title + ' · ' + price });
    }
    return runAction(deps, actionId, action, norm.args, { utterance: deps.lastFounderWords ? deps.lastFounderWords() : null });
  }

  async function handleConfirm(args, deps) {
    const eng = getEngine();
    const snap = eng.pending();
    if (!snap || !pendingMeta) {
      pendingMeta = null;
      return withActivity({ success: false, status: 'not_confirmed', error: 'Nothing is waiting for confirmation. Ask the founder what they want to do.' },
        { kind: 'info', state: 'done', text: 'Nothing to confirm' });
    }
    if (args && args.token && args.token !== snap.token) {
      return withActivity({ success: false, status: 'error', error: 'That token does not match the pending action. Use the latest proposal.' },
        { kind: 'clarifying', state: 'done', text: 'Needs: the latest proposal' });
    }
    // Brandy may call confirm_action in the same turn she proposed: the founder has
    // not answered yet, so keep the proposal and wait.
    if (deps.founderTurns && deps.founderTurns() <= pendingMeta.turnsAtProposal) {
      return withActivity({ success: false, status: 'not_confirmed', error: 'The founder has not answered yet. Ask them to say "confirm", then wait.' },
        { kind: 'clarifying', state: 'done', text: 'Waiting for your "confirm": ' + pendingMeta.title });
    }
    const meta = pendingMeta;
    const words = deps.lastFounderWords ? deps.lastFounderWords() : '';
    const verdict = eng.confirm(words);
    pendingMeta = null;
    if (verdict.status !== 'confirmed') {
      return withActivity({ success: false, status: verdict.status === 'cancelled' ? 'cancelled' : 'not_confirmed',
        say: 'Cancelled: ' + meta.title + '. Nothing was charged.' },
        { kind: 'info', state: 'done', text: 'Cancelled: ' + meta.title });
    }
    const action = deps.actions.get(meta.actionId);
    const res = await runAction(deps, meta.actionId, action, meta.args,
      { utterance: words, restatement: meta.title + (meta.cost ? ' for ' + meta.cost + ' credits' : '') });
    const act = res._activity;
    return withActivity(res, res.success
      ? { kind: 'decision', state: 'done', text: 'Confirmed: ' + meta.title + (meta.cost ? ' · ' + meta.cost + ' credits' : '') }
      : act);
  }

  async function handleGlobal(name, args, deps) {
    const ctx = deps.ctx ? deps.ctx() : {};
    const step = deps.currentStep();
    if (name === 'get_status') {
      const summary = deps.agent && deps.agent.buildStepSummary ? deps.agent.buildStepSummary(step, ctx) : ('Step: ' + step);
      return withActivity({ success: true, status: 'done', result: clip(summary, 400) },
        { kind: 'info', state: 'done', text: 'Checked where you are: ' + (STEP_LABELS[step] || step) });
    }
    if (name === 'get_balance') {
      return withActivity({ success: true, status: 'done', result: 'Balance: ' + (ctx.balance != null ? ctx.balance : 'unknown') + ' credits.' },
        { kind: 'info', state: 'done', text: 'Checked your balance' });
    }
    if (name === 'go_to_step') {
      const raw = String((args && (args.step || args.to)) || '').toLowerCase().trim();
      const target = STEP_ORDER.find(function (s) { return raw === s || raw.indexOf(s) !== -1 || raw === (STEP_LABELS[s] || '').toLowerCase(); }) ||
        (/soul/.test(raw) ? 'brain' : (/edit/.test(raw) ? 'editing' : (/audio|visual|asset/.test(raw) ? 'audiovisual' : null)));
      if (!target) {
        return withActivity({ success: false, status: 'error', error: 'Unknown step. Valid: brain, catalog, script, audiovisual, editing.' },
          { kind: 'clarifying', state: 'done', text: 'Needs: which step' });
      }
      const nav = deps.navigate ? await deps.navigate(target) : { ok: false, error: 'navigation unavailable' };
      if (nav && nav.ok) {
        return withActivity({ success: true, status: 'done', result: 'Now in ' + STEP_LABELS[target] + '.' },
          { kind: 'decision', state: 'done', text: 'Moved to ' + STEP_LABELS[target] });
      }
      return withActivity({ success: false, status: 'locked', say: (nav && nav.error) || (STEP_LABELS[target] + ' is locked until the previous step is complete.') },
        { kind: 'clarifying', state: 'done', text: STEP_LABELS[target] + ' is still locked' });
    }
    if (name === 'propose_action') {
      const id = args && (args.action || args.action_id || args.actionId);
      return handleAction(String(id || ''), (args && args.args) || {}, deps);
    }
    return handleConfirm(args || {}, deps);
  }

  async function handle(name, args, deps) {
    try {
      if (typeof args === 'string') { try { args = JSON.parse(args); } catch (e) { args = {}; } }
      args = args || {};
      if (GLOBAL[name]) return await handleGlobal(name, args, deps);
      return await handleAction(name, args, deps);
    } catch (error) {
      return withActivity({ success: false, status: 'error', error: 'Internal error (' + clip(error && error.message, 120) + '). Tell the founder in one sentence.' },
        { kind: 'error', state: 'failed', text: 'Tool failed: ' + clip(name, 40) });
    }
  }

  const api = {
    isVoiceTool: isVoiceTool,
    resolveActionId: resolveActionId,
    handle: handle,
    _resetForTests: function () { engine = null; pendingMeta = null; },
  };
  if (typeof window !== 'undefined') window.BrandStudioVoiceTools = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})();
