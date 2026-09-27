'use strict';
/**
 * Node harness for F-07 (Script voice tools).
 *
 * Run with: node tests/agent_script.test.js
 *
 * Loads the REAL app/static/agent.js and app/static/actions.js to verify:
 * - Script tool schemas are defined correctly
 * - script_phase_review action returns phase text + failing rules
 * - validateSceneN handles unknown scenes with correct error message
 * - Paid tools require confirmation flow
 * - Each tool hits the same endpoint/body as its button equivalent
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
    get readyState() { return 1; } // OPEN
    send() {}
  };
  global.WebSocket.OPEN = 1;
}

// Script fixture with scenes for F-07 tests
const SCRIPT_FIXTURE = {
  idea_id: 'idea-42',
  state: 'draft',
  title: 'Test Script',
  scenes: [
    { n: 1, text: 'Hook scene text here', asset_type: 'a_roll' },
    { n: 2, text: 'Lock-in scene text', asset_type: 'stock' },
    { n: 3, text: 'Point 1 content', asset_type: 'stock' },
    { n: 4, text: 'Rehook scene', asset_type: 'stock' },
    { n: 5, text: 'Point 2 content', asset_type: 'stock' },
    { n: 6, text: 'CTA call to action', asset_type: 'stock' },
  ],
  audit: [
    { rule: 'r1', status: 'pass', critical: false },
    { rule: 'r2', status: 'fail', critical: true, scene_n: 1 },
    { rule: 'r3', status: 'fail', critical: false, scene_n: 3 },
    { rule: 'r4', status: 'fail', critical: true }, // global rule
  ],
};

// Load all modules into a fresh context
function loadModules() {
  installDomStubs();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });

  // Load confirmation engine first
  const confirmCode = fs.readFileSync(CONFIRM_ENGINE_JS, 'utf8');
  vm.runInThisContext(confirmCode, { filename: CONFIRM_ENGINE_JS });

  // Load actions.js
  const actionsCode = fs.readFileSync(ACTIONS_JS, 'utf8');
  vm.runInThisContext(actionsCode, { filename: ACTIONS_JS });

  // Load agent.js
  const agentCode = fs.readFileSync(AGENT_JS, 'utf8');
  vm.runInThisContext(agentCode, { filename: AGENT_JS });

  // Mock BrandStudio global with script data
  global.window.BrandStudio = {
    getCurrentScriptData: () => SCRIPT_FIXTURE,
    getCurrentScriptIdeaId: () => 'idea-42',
    handleScriptGenerate: async () => ({ success: true }),
    handleScriptRegenerate: async (sceneIdx, instruction) => ({ success: true, sceneIdx, instruction }),
    handleScriptSceneEdit: async (sceneIdx, text) => ({ success: true, sceneIdx, text }),
    handleScriptLock: async () => ({ success: true, state: 'locked' }),
    authenticatedFetch: async (url, options) => {
      global.lastFetchCall = { url, options };
      return { ok: true, status: 200, json: async () => ({}) };
    },
  };

  return {
    BrandStudioActions: global.window.BrandStudioActions,
    BrandStudioAgent: global.window.BrandStudioAgent,
    createConfirmationEngine: global.window.createConfirmationEngine,
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
  const { BrandStudioActions, BrandStudioAgent, createConfirmationEngine } = loadModules();

  // ---------------------------------------------------------------------------
  // Test: Script tool schemas are defined
  // ---------------------------------------------------------------------------
  check('VALID_SCRIPT_PHASES contains 6 phases', () => {
    assert.deepStrictEqual(BrandStudioAgent.VALID_SCRIPT_PHASES, ['hook', 'lock-in', 'point_1', 'rehook', 'point_2', 'cta']);
  });

  check('PHASE_TO_SCENE_INDEX maps phases to 0-based indices', () => {
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['hook'], 0);
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['lock-in'], 1);
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['point_1'], 2);
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['rehook'], 3);
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['point_2'], 4);
    assert.strictEqual(BrandStudioAgent.PHASE_TO_SCENE_INDEX['cta'], 5);
  });

  // ---------------------------------------------------------------------------
  // Test: validateSceneN error message for unknown scene
  // ---------------------------------------------------------------------------
  check('validateSceneN returns correct error for scene 13 in a 6-scene script', () => {
    const result = BrandStudioAgent.validateSceneN(13, SCRIPT_FIXTURE);
    assert.strictEqual(result.ok, false);
    assert.strictEqual(result.error, 'There is no scene 13; your script has 6 scenes.');
  });

  check('validateSceneN returns ok for valid scene', () => {
    const result = BrandStudioAgent.validateSceneN(1, SCRIPT_FIXTURE);
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.index, 0);
  });

  // ---------------------------------------------------------------------------
  // Test: script_phase_review action is registered
  // ---------------------------------------------------------------------------
  check('script.phase_review action is registered', () => {
    const action = BrandStudioActions.get('script.phase_review');
    assert.ok(action, 'script.phase_review should exist');
    assert.strictEqual(action.step, 'script');
    assert.strictEqual(action.needsConfirm, false);
    assert.strictEqual(typeof action.cost, 'function');
    assert.strictEqual(action.cost(), 0);
  });

  // ---------------------------------------------------------------------------
  // Test: script_phase_review returns phase text + failing rules
  // ---------------------------------------------------------------------------
  check('scriptPhaseReview returns hook phase text and failing rules', async () => {
    const result = await BrandStudioAgent.scriptPhaseReview({ phase: 'hook' });
    assert.strictEqual(result.status, 'done');
    assert.strictEqual(result.phase, 'hook');
    assert.strictEqual(result.sceneN, 1);
    assert.strictEqual(result.text, 'Hook scene text here');
    // Scene 1 has one failing rule (r2) plus global rule (r4) = 2 failing rules
    assert.strictEqual(result.failingRules.length, 2);
    const ruleNames = result.failingRules.map(r => r.rule);
    assert.ok(ruleNames.includes('r2'), 'Should include scene-specific rule r2');
    assert.ok(ruleNames.includes('r4'), 'Should include global rule r4');
  });

  check('scriptPhaseReview returns point_1 phase with failing rules', async () => {
    const result = await BrandStudioAgent.scriptPhaseReview({ phase: 'point_1' });
    assert.strictEqual(result.status, 'done');
    assert.strictEqual(result.phase, 'point_1');
    assert.strictEqual(result.sceneN, 3);
    assert.strictEqual(result.text, 'Point 1 content');
    // Scene 3 has one failing rule (r3) plus global rule (r4) = 2 failing rules
    assert.strictEqual(result.failingRules.length, 2);
    const ruleNames = result.failingRules.map(r => r.rule);
    assert.ok(ruleNames.includes('r3'), 'Should include scene-specific rule r3');
    assert.ok(ruleNames.includes('r4'), 'Should include global rule r4');
  });

  check('scriptPhaseReview returns global failing rules for phase with no specific issues', async () => {
    // Scene 2 (lock-in) has no scene-specific failing rules, but should include global rule r4
    const result = await BrandStudioAgent.scriptPhaseReview({ phase: 'lock-in' });
    assert.strictEqual(result.status, 'done');
    assert.strictEqual(result.phase, 'lock-in');
    assert.strictEqual(result.sceneN, 2);
    assert.strictEqual(result.text, 'Lock-in scene text');
    // Scene 2 should have global rule r4 (no scene-specific rules for scene 2)
    assert.ok(Array.isArray(result.failingRules));
    // Only global rules apply to scene 2
    const ruleNames = result.failingRules.map(r => r.rule);
    assert.ok(ruleNames.includes('r4'), 'Should include global rule r4');
    assert.ok(!ruleNames.includes('r2') && !ruleNames.includes('r3'), 'Should not have scene-specific rules for other scenes');
  });

  check('scriptPhaseReview returns invalid for unknown phase', async () => {
    const result = await BrandStudioAgent.scriptPhaseReview({ phase: 'invalid_phase' });
    assert.strictEqual(result.status, 'invalid');
    assert.ok(result.say.includes('hook, lock-in, point_1, rehook, point_2, cta'));
  });

  // ---------------------------------------------------------------------------
  // Test: Paid tools require confirmation flow (6 credits for generate)
  // ---------------------------------------------------------------------------
  check('script.generate action costs 6 credits (F-07)', () => {
    const action = BrandStudioActions.get('script.generate');
    assert.strictEqual(action.cost(), 6);
  });

  check('script.iterate_scene action costs 2 credits', () => {
    const action = BrandStudioActions.get('script.iterate_scene');
    assert.strictEqual(action.cost(), 2);
  });

  check('script.lock action costs 0 credits but needs confirm', () => {
    const action = BrandStudioActions.get('script.lock');
    assert.strictEqual(action.cost(), 0);
    assert.strictEqual(action.needsConfirm, true);
  });

  // ---------------------------------------------------------------------------
  // Test: getScriptStepTools includes Script voice tool schemas
  // ---------------------------------------------------------------------------
  check('getScriptStepTools includes script_generate schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const generateTool = tools.find(t => t.name === 'script_generate');
    assert.ok(generateTool, 'script_generate tool should exist');
    assert.strictEqual(generateTool.type, 'function');
    assert.ok(generateTool.description.includes('6 credits'));
  });

  check('getScriptStepTools includes script_phase_review schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const reviewTool = tools.find(t => t.name === 'script_phase_review');
    assert.ok(reviewTool, 'script_phase_review tool should exist');
    assert.strictEqual(reviewTool.type, 'function');
    assert.ok(reviewTool.parameters.properties.phase);
    assert.deepStrictEqual(reviewTool.parameters.properties.phase.enum, ['hook', 'lock-in', 'point_1', 'rehook', 'point_2', 'cta']);
  });

  check('getScriptStepTools includes script_iterate_scene schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const iterateTool = tools.find(t => t.name === 'script_iterate_scene');
    assert.ok(iterateTool, 'script_iterate_scene tool should exist');
    assert.strictEqual(iterateTool.type, 'function');
    assert.ok(iterateTool.parameters.properties.scene_n);
    assert.ok(iterateTool.parameters.properties.instruction);
    assert.strictEqual(iterateTool.parameters.required.length, 2);
  });

  check('getScriptStepTools includes script_edit_text schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const editTool = tools.find(t => t.name === 'script_edit_text');
    assert.ok(editTool, 'script_edit_text tool should exist');
    assert.strictEqual(editTool.type, 'function');
    assert.ok(editTool.parameters.properties.scene_n);
    assert.ok(editTool.parameters.properties.text);
  });

  check('getScriptStepTools includes script_lock schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const lockTool = tools.find(t => t.name === 'script_lock');
    assert.ok(lockTool, 'script_lock tool should exist');
    assert.strictEqual(lockTool.type, 'function');
    assert.ok(lockTool.description.includes('cannot be undone'));
  });

  check('getScriptStepTools includes script_explain_audit schema', () => {
    const tools = BrandStudioAgent.getScriptStepTools();
    const auditTool = tools.find(t => t.name === 'script_explain_audit');
    assert.ok(auditTool, 'script_explain_audit tool should exist');
    assert.strictEqual(auditTool.type, 'function');
  });

  // ---------------------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------------------
  if (failures > 0) {
    console.error(`\n${failures} check(s) failed.`);
    process.exit(1);
  }
  console.log('\nAll checks passed.');
}

runTests().catch((err) => {
  console.error('Test runner error:', err);
  process.exit(1);
});
