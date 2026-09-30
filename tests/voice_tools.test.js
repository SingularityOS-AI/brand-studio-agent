// Voice tool dispatcher: REAL actions.js (registry, run in a vm with a window stub),
// REAL confirm_engine.js and REAL agent.js. The BrandStudio button functions are
// mocked and record every call, so each test asserts the exact button path hit.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const calls = [];
const rec = (name) => (...args) => { calls.push({ name, args }); return name === 'explainDemand' ? 'Idea 1 demand: high' : { ok: true }; };
const BrandStudio = {
  authenticatedFetch: async () => ({ ok: true, json: async () => ({ id: 'row-1' }) }),
  getCurrentScriptIdeaId: () => 'idea-7',
  getCurrentScriptData: () => ({ scenes: [{ n: 1, asset_type: 'stock' }, { n: 2, asset_type: 'stock' }] }),
  getCurrentAudiovisualEstimate: () => ({ credits_by_type: { stock: 1, ai_video: 12 } }),
  fetchAudiovisualEstimate: async () => { calls.push({ name: 'fetchAudiovisualEstimate', args: [] }); return { credits_pending: 42 }; },
};
['handleScriptGenerate', 'handleScriptRegenerate', 'handleScriptSceneEdit', 'handleScriptLock', 'changeSceneAssetType',
  'generateAllAudiovisualAssets', 'triggerRegenerateScene', 'openRecordingStudio', 'generateBrandSoul', 'regenerateBrandSoul',
  'researchDemand', 'generateCatalogIdeas', 'regenerateCatalogIdea', 'addCatalogIdea', 'acceptCatalogIdea',
  'discardCatalogIdea', 'explainDemand', 'lockCatalog'].forEach((n) => { BrandStudio[n] = rec(n); });
const BrandStudioEditing = { run: rec('editing.run'), loadEditingState: async () => ({ ir: { render_price: 20 } }) };

const win = { BrandStudio, BrandStudioEditing };
const ctxVm = vm.createContext({ window: win, console, Map, Array, Object, String, Error, Promise, JSON });
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'actions.js'), 'utf8'), ctxVm);
const actions = win.BrandStudioActions;
assert.ok(actions && typeof actions.execute === 'function', 'real registry loaded');

global.window = {};
const agent = require('../app/static/agent.js');
const vt = require('../app/static/voice_tools.js');

let step = 'catalog';
let turns = 0;
let words = '';
let navigated = null;
const unlocked = { brain: true, catalog: true, script: true, audiovisual: false, editing: false };
const deps = {
  actions, agent,
  currentStep: () => step,
  ctx: () => ({ brainCount: 9, brainComplete: true, catalogLocked: false, balance: 480 }),
  lastFounderWords: () => words,
  founderTurns: () => turns,
  navigate: async (s) => { if (!unlocked[s]) return { ok: false, error: s + ' is locked' }; navigated = s; return { ok: true }; },
  currentIdeaId: () => 'idea-7',
};
const founder = (text) => { words = text; turns++; };
const last = () => JSON.parse(JSON.stringify(calls[calls.length - 1]));

(async () => {
  // 1. every exposed agentic tool resolves to a registered action (no dead tool)
  const skip = new Set(['extract_brand_brain', 'confirm_brand_section', 'get_status', 'get_balance', 'go_to_step', 'confirm_action']);
  ['brain', 'catalog', 'script', 'audiovisual', 'editing'].forEach((s) => {
    agent.toolsForStep(s).forEach((t) => {
      if (skip.has(t.name)) return;
      const id = vt.resolveActionId(t.name, actions);
      assert.ok(id && actions.get(id), s + ': tool ' + t.name + ' has no registered action');
      assert.strictEqual(actions.get(id).step, s, t.name + ' belongs to step ' + s);
    });
  });
  assert.strictEqual(vt.isVoiceTool('extract_brand_brain'), false);
  assert.strictEqual(vt.isVoiceTool('catalog_accept'), true);

  // 2. free action runs at once, on the button path, with the founder's idea reference
  founder('Accept the second idea');
  let r = await vt.handle('catalog_accept', { idea: 'idea 2' }, deps);
  assert.strictEqual(r.status, 'done', JSON.stringify(r));
  assert.deepStrictEqual(last(), { name: 'acceptCatalogIdea', args: ['idea 2'] });
  assert.ok(r._activity && r._activity.kind === 'saved');
  assert.ok(!('_activity' in JSON.parse(JSON.stringify(r))), '_activity never reaches the model');

  // 3. paid action -> proposal only, nothing executed
  const before = calls.length;
  founder('Generate my ideas');
  r = await vt.handle('catalog_generate_ideas', {}, deps);
  assert.strictEqual(r.status, 'needs_confirmation');
  assert.strictEqual(r.cost, 5);
  assert.ok(/confirm/.test(r.say) && r.token);
  assert.strictEqual(calls.length, before, 'not executed before confirm');

  // 4. Brandy calls confirm_action in the same turn: kept waiting, not executed
  r = await vt.handle('confirm_action', {}, deps);
  assert.strictEqual(r.status, 'not_confirmed');
  assert.strictEqual(calls.length, before);

  // 5. founder says "confirm" -> executed exactly once
  founder('Confirm');
  r = await vt.handle('confirm_action', {}, deps);
  assert.strictEqual(r.status, 'done', JSON.stringify(r));
  assert.strictEqual(r._activity.kind, 'decision');
  assert.strictEqual(calls.filter((c) => c.name === 'generateCatalogIdeas').length, 1);
  founder('Confirm');
  r = await vt.handle('confirm_action', {}, deps);
  assert.strictEqual(r.status, 'not_confirmed', 'double confirm does nothing');
  assert.strictEqual(calls.filter((c) => c.name === 'generateCatalogIdeas').length, 1);

  // 6. "no, wait" cancels
  founder('Discard idea 3');
  r = await vt.handle('catalog_discard', { idea: '3' }, deps);
  assert.strictEqual(r.status, 'needs_confirmation');
  founder('No, wait');
  r = await vt.handle('confirm_action', {}, deps);
  assert.strictEqual(r.status, 'cancelled');
  assert.ok(!calls.some((c) => c.name === 'discardCatalogIdea'));

  // 7. missing argument -> useful error, nothing run
  r = await vt.handle('catalog_accept', {}, deps);
  assert.strictEqual(r.success, false);
  assert.ok(/which idea/.test(r.error));

  // 8. wrong step
  r = await vt.handle('script_lock', {}, deps);
  assert.strictEqual(r.status, 'wrong_step');

  // 9. navigation: locked vs unlocked
  r = await vt.handle('go_to_step', { step: 'Editing' }, deps);
  assert.strictEqual(r.status, 'locked');
  r = await vt.handle('go_to_step', { step: 'script' }, deps);
  assert.strictEqual(r.status, 'done');
  assert.strictEqual(navigated, 'script');

  // 10. script: 1-based scene number -> 0-based index on the button handler
  step = 'script';
  founder('Make scene 3 more direct');
  r = await vt.handle('script_iterate_scene', { scene_n: '3', instruction: 'more direct' }, deps);
  assert.strictEqual(r.status, 'needs_confirmation');
  assert.strictEqual(r.cost, 2);
  founder('Go ahead');
  r = await vt.handle('confirm_action', {}, deps);
  assert.strictEqual(r.status, 'done');
  assert.deepStrictEqual(last(), { name: 'handleScriptRegenerate', args: [2, 'more direct'] });

  // 11. audiovisual: spoken type normalized
  step = 'audiovisual';
  r = await vt.handle('av_set_scene_type', { scene_n: 2, type: 'AI video' }, deps);
  assert.strictEqual(r.status, 'done', JSON.stringify(r));
  assert.deepStrictEqual(last(), { name: 'changeSceneAssetType', args: ['idea-7', 2, 'ai_video'] });
  founder('How much to generate everything?');
  r = await vt.handle('av_generate_all', {}, deps);
  assert.strictEqual(r.status, 'needs_confirmation');
  assert.strictEqual(r.cost, 42, 'exact estimate');

  // 12. editing: booleans from speech
  step = 'editing';
  r = await vt.handle('edit_music', { on: 'false' }, deps);
  assert.strictEqual(r.status, 'done');
  assert.deepStrictEqual(last(), { name: 'editing.run', args: ['mute_music', { value: true }] });

  // 13. status / balance / unknown / thrown error
  r = await vt.handle('get_balance', {}, deps);
  assert.ok(/480/.test(r.result));
  r = await vt.handle('get_status', {}, deps);
  assert.strictEqual(r.status, 'done');
  r = await vt.handle('nope_tool', {}, deps);
  assert.strictEqual(r.success, false);
  const boom = Object.assign({}, deps, { currentStep: () => { throw new Error('boom'); } });
  r = await vt.handle('edit_music', { on: true }, boom);
  assert.strictEqual(r.success, false, 'never rejects');

  console.log('OK: voice tools dispatcher - 13 groups of checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
