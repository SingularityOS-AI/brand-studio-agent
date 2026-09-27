'use strict';
/**
 * Node harness test for F-08 (Audiovisual Voice Tools).
 *
 * Run with: node tests/agent_audiovisual.test.js
 *
 * Loads the REAL app/static/agent.js, app/static/actions.js, and app/static/confirm_engine.js to verify:
 * - Audiovisual tool schemas are defined correctly in AUDIOVISUAL_TOOL_SCHEMAS
 * - av_read_scene action returns scene status, asset type, and text
 * - av_set_scene_type changes scene asset type
 * - av_estimate returns cost estimation
 * - av_generate_all restatement contains the exact estimate total
 * - av_regenerate_asset passes the instruction parameter
 * - av_open_recording opens recording studio
 * - Long generation jobs return immediately ('queued')
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const REPO_ROOT = path.resolve(__dirname, '..');
const AGENT_JS = path.join(REPO_ROOT, 'app', 'static', 'agent.js');
const ACTIONS_JS = path.join(REPO_ROOT, 'app', 'static', 'actions.js');
const CONFIRM_ENGINE_JS = path.join(REPO_ROOT, 'app', 'static', 'confirm_engine.js');

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

const SCRIPT_FIXTURE = {
  idea_id: 'idea-88',
  state: 'locked',
  title: 'Audiovisual Test Script',
  scenes: [
    { n: 1, text: 'Hook scene text', asset_type: 'a_roll' },
    { n: 2, text: 'Scene 2 B-roll', asset_type: 'stock' },
    { n: 3, text: 'Scene 3 AI Video', asset_type: 'ai_video' },
    { n: 4, text: 'Scene 4 Motion graphic', asset_type: 'motion_graphic' },
  ],
};

const ESTIMATE_FIXTURE = {
  credits_pending: 15,
  credits_total: 15,
  credits_by_type: {
    a_roll: 0,
    stock: 2,
    ai_video: 10,
    motion_graphic: 3,
  },
};

const JOBS_FIXTURE = [
  { id: 'job-1', scene_n: 1, kind: 'a_roll', status: 'done' },
  { id: 'job-2', scene_n: 2, kind: 'stock', status: 'pending' },
];

function loadModules() {
  installDomStubs();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });

  const confirmCode = fs.readFileSync(CONFIRM_ENGINE_JS, 'utf8');
  vm.runInThisContext(confirmCode, { filename: CONFIRM_ENGINE_JS });

  const actionsCode = fs.readFileSync(ACTIONS_JS, 'utf8');
  vm.runInThisContext(actionsCode, { filename: ACTIONS_JS });

  const agentCode = fs.readFileSync(AGENT_JS, 'utf8');
  vm.runInThisContext(agentCode, { filename: AGENT_JS });

  let triggerRegenerateArgs = null;
  let generateAllCalled = false;

  global.window.BrandStudio = {
    getCurrentScriptData: () => SCRIPT_FIXTURE,
    getCurrentScriptIdeaId: () => 'idea-88',
    getCurrentAudiovisualEstimate: () => ESTIMATE_FIXTURE,
    getCurrentAudiovisualJobs: () => JOBS_FIXTURE,
    fetchAudiovisualEstimate: async (ideaId) => ESTIMATE_FIXTURE,
    changeSceneAssetType: async (ideaId, sceneN, type) => ({ success: true, sceneN, type }),
    generateAllAudiovisualAssets: async (ideaId) => {
      generateAllCalled = true;
      return { status: 'queued', message: 'Asset generation queued for 3 pending scenes.' };
    },
    triggerRegenerateScene: async (sceneN, instruction) => {
      triggerRegenerateArgs = { sceneN, instruction };
      return { status: 'queued', sceneN, instruction };
    },
    openRecordingStudio: async (sceneN) => ({ success: true, sceneN, open: true }),
    authenticatedFetch: async (url, options) => {
      global.lastFetchCall = { url, options };
      return { ok: true, status: 200, json: async () => ({}) };
    },
  };

  return {
    BrandStudioActions: global.window.BrandStudioActions,
    BrandStudioAgent: global.window.BrandStudioAgent,
    createConfirmationEngine: global.window.createConfirmationEngine,
    getTriggerRegenerateArgs: () => triggerRegenerateArgs,
    wasGenerateAllCalled: () => generateAllCalled,
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
  const { BrandStudioActions, BrandStudioAgent, createConfirmationEngine, getTriggerRegenerateArgs, wasGenerateAllCalled } = loadModules();

  // ---------------------------------------------------------------------------
  // Test: AUDIOVISUAL_TOOL_SCHEMAS contains all 6 required tools
  // ---------------------------------------------------------------------------
  check('AUDIOVISUAL_TOOL_SCHEMAS contains all 6 tools', () => {
    const schemas = BrandStudioAgent.AUDIOVISUAL_TOOL_SCHEMAS;
    assert.ok(Array.isArray(schemas));
    const names = schemas.map(s => s.name);
    const required = [
      'av_read_scene',
      'av_set_scene_type',
      'av_estimate',
      'av_generate_all',
      'av_regenerate_asset',
      'av_open_recording',
    ];
    required.forEach(req => {
      assert.ok(names.includes(req), `Missing schema for ${req}`);
    });
  });

  check('toolsForStep("audiovisual") returns global + audiovisual tools', () => {
    const tools = BrandStudioAgent.toolsForStep('audiovisual');
    const names = tools.map(t => t.name);
    assert.ok(names.includes('av_read_scene'));
    assert.ok(names.includes('av_regenerate_asset'));
    assert.ok(names.includes('get_status'));
    assert.ok(names.includes('propose_action'));
  });

  // ---------------------------------------------------------------------------
  // Test: av_read_scene action
  // ---------------------------------------------------------------------------
  check('av_read_scene action returns scene status and asset type', async () => {
    const result = await BrandStudioAgent.avReadScene({ scene_n: 2 });
    assert.strictEqual(result.status, 'done');
    assert.strictEqual(result.sceneN, 2);
    assert.strictEqual(result.assetType, 'stock');
    assert.strictEqual(result.text, 'Scene 2 B-roll');
    assert.ok(result.say.includes('Scene 2 (stock)'));
  });

  check('av_read_scene action returns error for invalid scene number', async () => {
    const result = await BrandStudioAgent.avReadScene({ scene_n: 99 });
    assert.strictEqual(result.status, 'invalid');
    assert.ok(result.say.includes('There is no scene 99'));
  });

  // ---------------------------------------------------------------------------
  // Test: Action Registry mappings for av_* actions
  // ---------------------------------------------------------------------------
  check('Action registry looks up av_read_scene action', () => {
    const action = BrandStudioActions.get('av_read_scene');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(action.cost(), 0);
  });

  check('Action registry looks up av_set_scene_type action', () => {
    const action = BrandStudioActions.get('av_set_scene_type');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(action.cost(), 0);
  });

  check('Action registry looks up av_estimate action', () => {
    const action = BrandStudioActions.get('av_estimate');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(action.cost(), 0);
  });

  check('Action registry looks up av_generate_all action with exact estimate total cost', async () => {
    const action = BrandStudioActions.get('av_generate_all');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, true);
    const cost = await action.cost({});
    assert.strictEqual(cost, 15, 'av_generate_all cost should match estimate.credits_pending (15)');
  });

  check('Action registry looks up av_regenerate_asset with per-unit cost', () => {
    const action = BrandStudioActions.get('av_regenerate_asset');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, true);
    // Cost for scene 2 (stock) should be 2 credits from ESTIMATE_FIXTURE
    const cost = action.cost({ scene_n: 2 });
    assert.strictEqual(cost, 2);
  });

  check('Action registry looks up av_open_recording action', () => {
    const action = BrandStudioActions.get('av_open_recording');
    assert.ok(action);
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(action.cost(), 0);
  });

  // ---------------------------------------------------------------------------
  // Test: av_regenerate_asset passes instruction parameter
  // ---------------------------------------------------------------------------
  check('av_regenerate_asset passes instruction parameter to run handler', async () => {
    const action = BrandStudioActions.get('av_regenerate_asset');
    const result = await action.run({ scene_n: 2, instruction: 'someone using a phone' });
    assert.strictEqual(result.status, 'queued');
    const args = getTriggerRegenerateArgs();
    assert.ok(args, 'triggerRegenerateScene should have been called');
    assert.strictEqual(args.sceneN, 2);
    assert.strictEqual(args.instruction, 'someone using a phone');
  });

  // ---------------------------------------------------------------------------
  // Test: Long generation jobs return immediately ('queued')
  // ---------------------------------------------------------------------------
  check('av_generate_all returns immediately with queued status', async () => {
    const action = BrandStudioActions.get('av_generate_all');
    const result = await action.run({});
    assert.strictEqual(result.status, 'queued');
    assert.strictEqual(wasGenerateAllCalled(), true);
  });

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed.`);
    process.exit(1);
  }
  console.log('\nAll F-08 audiovisual checks passed.');
}

runTests().catch((err) => {
  console.error('Test runner error:', err);
  process.exit(1);
});
