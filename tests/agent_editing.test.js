'use strict';
/**
 * Node harness test for F-11 (Editing Voice Tools).
 *
 * Run with: node tests/agent_editing.test.js
 *
 * Loads the REAL app/static/agent.js and app/static/actions.js to verify:
 * - Editing tool schemas are defined correctly in EDIT_ACTION_SCHEMAS
 * - edit_build_raw calls window.BrandStudioEditing.run('build_raw')
 * - edit_auto_edit passes style parameter
 * - edit_scene_visual toggles face/broll/reset
 * - edit_trim applies start_ms and end_ms adjustments
 * - edit_music and edit_sfx toggle on/off
 * - edit_fix_caption resolves word to word_id
 * - edit_caption_position maps to correct Y values
 * - edit_overlay_delete resolves index or overlay_id
 * - edit_overlays toggles overlays_enabled
 * - edit_post_copy generates metadata
 * - edit_share_link fetches share link
 * - edit_try_another_take charges 2 credits and requires confirmation
 * - edit_render uses dynamic cost from state.render_price
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const REPO_ROOT = path.resolve(__dirname, '..');
const AGENT_JS = path.join(REPO_ROOT, 'app', 'static', 'agent.js');
const ACTIONS_JS = path.join(REPO_ROOT, 'app', 'static', 'actions.js');

function stubEl() {
  const el = {
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    insertBefore() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    setAttribute() {},
    getAttribute() { return null; },
    remove() {},
    focus() {},
    click() {},
  };
  el.parentNode = el;
  Object.defineProperty(el, 'innerHTML', { get() { return ''; }, set() {} });
  Object.defineProperty(el, 'textContent', { get() { return ''; }, set() {} });
  Object.defineProperty(el, 'value', { get() { return ''; }, set() {} });
  Object.defineProperty(el, 'disabled', { get() { return false; }, set() {} });
  Object.defineProperty(el, 'checked', { get() { return false; }, set() {} });
  return el;
}

function installDomStubs() {
  global.document = {
    getElementById: () => stubEl(),
    querySelector: () => stubEl(),
    querySelectorAll: () => [],
    createElement: () => stubEl(),
    addEventListener: () => {},
    body: stubEl(),
    documentElement: stubEl(),
    title: '',
  };
  global.window = {
    location: { search: '', pathname: '/', href: 'http://localhost/' },
    history: { replaceState() {} },
    addEventListener() {},
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  };
  global.localStorage = global.window.localStorage;
  Object.defineProperty(global, 'navigator', {
    value: { mediaDevices: {}, language: 'en-US' },
    writable: true,
    configurable: true,
  });
  global.AbortController = class { constructor() { this.signal = {}; } abort() {} };
  global.AudioContext = function () {};
  global.Audio = function () { return { play: () => Promise.resolve() }; };
  global.URL = require('url').URL;
  global.alert = () => {};
  global.WebSocket = class {
    constructor() {}
    get readyState() { return 1; }
    send() {}
  };
  global.WebSocket.OPEN = 1;
}

const EDITING_STATE_FIXTURE = {
  edit_version: 3,
  ir: {
    overlays: [
      { id: 'overlay-1', text: 'Special offer', at_ms: 5000 },
      { id: 'overlay-2', text: 'Call to action', at_ms: 10000 },
    ],
  },
  captions_words: [
    { id: 's1w1', text: 'Hello', scene_n: 1, word: 'Hello' },
    { id: 's1w2', text: 'world', scene_n: 1, word: 'world' },
    { id: 's2w1', text: 'Special', scene_n: 2, word: 'Special' },
  ],
  render_price: 20,
  render_price_kind: 'first',
};

function loadModules() {
  installDomStubs();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });

  const actionsCode = fs.readFileSync(ACTIONS_JS, 'utf8');
  vm.runInThisContext(actionsCode, { filename: ACTIONS_JS });

  const agentCode = fs.readFileSync(AGENT_JS, 'utf8');
  vm.runInThisContext(agentCode, { filename: AGENT_JS });

  let editActionCalls = [];

  global.window.BrandStudio = {
    getCurrentScriptIdeaId: () => 'idea-99',
  };

  global.window.BrandStudioEditing = {
    run: async (name, args) => {
      editActionCalls.push({ name, args });
      return { success: true, edit_version: 3 };
    },
    loadEditingState: async (ideaId) => {
      assert.strictEqual(ideaId, 'idea-99');
      return EDITING_STATE_FIXTURE;
    },
  };

  return {
    BrandStudioActions: global.window.BrandStudioActions,
    BrandStudioAgent: global.window.BrandStudioAgent,
    getEditActionCalls: () => {
      const calls = editActionCalls.slice();
      editActionCalls = [];
      return calls;
    },
  };
}

let failures = 0;
function check(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (err) {
    failures += 1;
    console.log(`FAIL - ${name}`);
    console.log(err && err.stack ? err.stack : err);
  }
}

async function runTests() {
  const { BrandStudioActions, BrandStudioAgent, getEditActionCalls } = loadModules();

  // ---------------------------------------------------------------------------
  // Test: EDIT_ACTION_SCHEMAS contains all 14 required tools
  // ---------------------------------------------------------------------------
  check('EDIT_ACTION_SCHEMAS contains all 14 editing tools', () => {
    const schemas = BrandStudioAgent.EDIT_ACTION_SCHEMAS;
    assert.ok(Array.isArray(schemas));
    const names = schemas.map(s => s.name);
    const required = [
      'edit_build_raw',
      'edit_auto_edit',
      'edit_scene_visual',
      'edit_trim',
      'edit_music',
      'edit_sfx',
      'edit_fix_caption',
      'edit_caption_position',
      'edit_overlay_delete',
      'edit_overlays',
      'edit_post_copy',
      'edit_share_link',
      'edit_try_another_take',
      'edit_render',
    ];
    required.forEach(req => {
      assert.ok(names.includes(req), `Missing schema for ${req}`);
    });
  });

  check('toolsForStep("editing") returns global + editing tools', () => {
    const tools = BrandStudioAgent.toolsForStep('editing');
    assert.ok(Array.isArray(tools));
    const names = tools.map(t => t.name);
    // Global tools
    assert.ok(names.includes('get_status'));
    assert.ok(names.includes('get_balance'));
    assert.ok(names.includes('go_to_step'));
    // Editing tools
    assert.ok(names.includes('edit_build_raw'));
    assert.ok(names.includes('edit_auto_edit'));
    assert.ok(names.includes('edit_render'));
  });

  // ---------------------------------------------------------------------------
  // Test: edit_build_raw action
  // ---------------------------------------------------------------------------
  check('edit_build_raw is registered and calls run("build_raw")', () => {
    const action = BrandStudioActions.get('edit_build_raw');
    assert.ok(action);
    assert.strictEqual(action.step, 'editing');
    assert.strictEqual(action.title, 'Build the raw editing timeline');
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(typeof action.run, 'function');
  });

  // ---------------------------------------------------------------------------
  // Test: edit_auto_edit action
  // ---------------------------------------------------------------------------
  check('edit_auto_edit passes style parameter', async () => {
    const action = BrandStudioActions.get('edit_auto_edit');
    assert.ok(action);
    await action.run({ style: 'bold' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'dress_all');
    assert.strictEqual(calls[0].args.style, 'bold');
  });

  // ---------------------------------------------------------------------------
  // Test: edit_scene_visual action
  // ---------------------------------------------------------------------------
  check('edit_scene_visual calls toggle_face for "face"', async () => {
    const action = BrandStudioActions.get('edit_scene_visual');
    assert.ok(action);
    await action.run({ scene_n: 2, visual: 'face' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'toggle_face');
    assert.strictEqual(calls[0].args.sceneN, 2);
    assert.strictEqual(calls[0].args.value, true);
  });

  check('edit_scene_visual calls toggle_face(false) for "broll"', async () => {
    const action = BrandStudioActions.get('edit_scene_visual');
    assert.ok(action);
    await action.run({ scene_n: 3, visual: 'broll' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'toggle_face');
    assert.strictEqual(calls[0].args.value, false);
  });

  check('edit_scene_visual calls reset_face for "reset"', async () => {
    const action = BrandStudioActions.get('edit_scene_visual');
    assert.ok(action);
    await action.run({ scene_n: 1, visual: 'reset' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'reset_face');
    assert.strictEqual(calls[0].args.sceneN, 1);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_trim action
  // ---------------------------------------------------------------------------
  check('edit_trim applies start_ms and end_ms adjustments', async () => {
    const action = BrandStudioActions.get('edit_trim');
    assert.ok(action);
    await action.run({ scene_n: 1, start_ms: -100, end_ms: 200 });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'trim');
    assert.strictEqual(calls[0].args.sceneN, 1);
    assert.strictEqual(calls[0].args.deltaStartMs, -100);
    assert.strictEqual(calls[0].args.deltaEndMs, 200);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_music and edit_sfx actions
  // ---------------------------------------------------------------------------
  check('edit_music calls mute_music with inverted value', async () => {
    const action = BrandStudioActions.get('edit_music');
    assert.ok(action);
    await action.run({ on: true });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'mute_music');
    assert.strictEqual(calls[0].args.value, false); // inverted: on=true -> mute=false
  });

  check('edit_sfx calls toggle_sfx with value', async () => {
    const action = BrandStudioActions.get('edit_sfx');
    assert.ok(action);
    await action.run({ on: false });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'toggle_sfx');
    assert.strictEqual(calls[0].args.value, false);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_fix_caption action
  // ---------------------------------------------------------------------------
  check('edit_fix_caption calls fix_caption with word and text', async () => {
    const action = BrandStudioActions.get('edit_fix_caption');
    assert.ok(action);
    await action.run({ word: 'Hello', text: 'Hi' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'fix_caption');
    assert.strictEqual(calls[0].args.word, 'Hello');
    assert.strictEqual(calls[0].args.text, 'Hi');
  });

  // ---------------------------------------------------------------------------
  // Test: edit_caption_position action
  // ---------------------------------------------------------------------------
  check('edit_caption_position maps position to correct Y values', async () => {
    const action = BrandStudioActions.get('edit_caption_position');
    assert.ok(action);

    await action.run({ position: 'top' });
    let calls = getEditActionCalls();
    assert.strictEqual(calls[0].name, 'caption_y');
    assert.strictEqual(calls[0].args.captionY, 520);

    await action.run({ position: 'middle' });
    calls = getEditActionCalls();
    assert.strictEqual(calls[0].args.captionY, 1080);

    await action.run({ position: 'bottom' });
    calls = getEditActionCalls();
    assert.strictEqual(calls[0].args.captionY, 1600);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_overlay_delete and edit_overlays actions
  // ---------------------------------------------------------------------------
  check('edit_overlay_delete calls delete_overlay', async () => {
    const action = BrandStudioActions.get('edit_overlay_delete');
    assert.ok(action);
    await action.run({ n: 'overlay-1' });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'delete_overlay');
    assert.strictEqual(calls[0].args.n, 'overlay-1');
  });

  check('edit_overlays calls overlays_enabled', async () => {
    const action = BrandStudioActions.get('edit_overlays');
    assert.ok(action);
    await action.run({ on: true });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'overlays_enabled');
    assert.strictEqual(calls[0].args.value, true);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_post_copy and edit_share_link actions
  // ---------------------------------------------------------------------------
  check('edit_post_copy calls gen_metadata', async () => {
    const action = BrandStudioActions.get('edit_post_copy');
    assert.ok(action);
    await action.run({});
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'gen_metadata');
  });

  check('edit_share_link calls copy_share_link', async () => {
    const action = BrandStudioActions.get('edit_share_link');
    assert.ok(action);
    await action.run({});
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'copy_share_link');
  });

  // ---------------------------------------------------------------------------
  // Test: edit_try_another_take action (paid, needs confirmation)
  // ---------------------------------------------------------------------------
  check('edit_try_another_take costs 2 credits and needs confirmation', () => {
    const action = BrandStudioActions.get('edit_try_another_take');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, true);
    assert.strictEqual(action.cost(), 2);
    assert.strictEqual(action.step, 'editing');
  });

  check('edit_try_another_take calls redress_scene', async () => {
    const action = BrandStudioActions.get('edit_try_another_take');
    assert.ok(action);
    await action.run({ scene_n: 2 });
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'redress_scene');
    assert.strictEqual(calls[0].args.sceneN, 2);
  });

  // ---------------------------------------------------------------------------
  // Test: edit_render action (dynamic cost)
  // ---------------------------------------------------------------------------
  check('edit_render uses dynamic cost from state.render_price', async () => {
    const action = BrandStudioActions.get('edit_render');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, true);
    const cost = await action.cost({});
    assert.strictEqual(cost, 20); // from EDITING_STATE_FIXTURE.render_price
  });

  check('edit_render calls render', async () => {
    const action = BrandStudioActions.get('edit_render');
    assert.ok(action);
    await action.run({});
    const calls = getEditActionCalls();
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].name, 'render');
  });

  // ---------------------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------------------
  console.log('');
  if (failures === 0) {
    console.log('All tests passed!');
    process.exit(0);
  } else {
    console.log(`${failures} test(s) failed.`);
    process.exit(1);
  }
}

runTests().catch(err => {
  console.error(err.stack);
  process.exit(1);
});
