'use strict';
/**
 * Node harness for F-04 (Action Registry). Run with: node tests/agent_actions.test.js
 *
 * Loads the REAL app/static/actions.js and app/static/app.js (in that order,
 * same as index.html will load them) into a Node context with a stubbed DOM
 * and `fetch` mocked, then drives BrandStudioActions.execute() the way F-06's
 * confirmation engine will. No network, no framework -- plain `assert`.
 *
 * `let jwtToken = null;` / `let currentScriptData = null;` /
 * `let currentScriptIdeaId = null;` are given fixture values via a targeted
 * text substitution before eval: these are private closure variables with no
 * public setter (by design -- app.js only exposes the getters/handlers the
 * registry needs), and the alternative (a real Google OAuth + Supabase login
 * and a real /api/script fetch just to populate them) would make this a
 * network-dependent integration test instead of a unit test. The
 * substitution changes only the initial value of a `let`, never any logic in
 * either file.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_JS = path.join(REPO_ROOT, 'app', 'static', 'app.js');
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
}

const SCRIPT_FIXTURE = {
  idea_id: 'idea-42',
  state: 'locked',
  scenes: [
    { n: 1, asset_type: 'a_roll' },
    { n: 2, asset_type: 'stock' },
  ],
  audit: [{ rule: 'r1', status: 'pass', critical: false }],
};

// Loads a fresh copy of actions.js + app.js into the global scope with the
// given `fetch` mock. Each test gets its own load so module-level state
// (BrandStudioActions.currentActionId, currentScriptData, ...) never leaks
// between tests.
function loadApp(fetchMock) {
  installDomStubs();
  global.fetch = fetchMock;

  let appCode = fs.readFileSync(APP_JS, 'utf8');
  appCode = appCode.replace("let jwtToken = null;", "let jwtToken = 'TEST_JWT';");
  appCode = appCode.replace(
    "let currentScriptData = null;",
    `let currentScriptData = ${JSON.stringify(SCRIPT_FIXTURE)};`
  );
  appCode = appCode.replace(
    "let currentScriptIdeaId = null;",
    "let currentScriptIdeaId = 'idea-42';"
  );

  const actionsCode = fs.readFileSync(ACTIONS_JS, 'utf8');
  eval(actionsCode);
  eval(appCode);

  return { BrandStudio: global.window.BrandStudio, BrandStudioActions: global.window.BrandStudioActions };
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

async function testIterateSceneMatchesButtonPathAndSendsHeader() {
  const calls = [];
  const fetchMock = async (url, options) => {
    calls.push({ url, options: options || {} });
    if (url === '/api/agent/actions') {
      return { ok: true, status: 201, json: async () => ({ id: 'action-row-1' }) };
    }
    if (url === '/api/script/idea-42/scene/2/regenerate') {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          script: { idea_id: 'idea-42', state: 'locked', scenes: [], audit: [] },
          credits_remaining: 88,
        }),
      };
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const { BrandStudioActions } = loadApp(fetchMock);

  const outcome = await BrandStudioActions.execute(
    'script.iterate_scene',
    { sceneIdx: 1, instruction: 'be punchier' },
    {
      source: 'voice',
      voiceMeta: {
        ideaId: 'idea-42',
        utterance: 'make it punchier',
        restatement: 'Iterate scene 2 -- 2 credits. Say confirm to go ahead.',
      },
    }
  );

  check('execute() returns ok:true for script.iterate_scene', () => {
    assert.strictEqual(outcome.ok, true);
  });

  check('creates the agent_actions row first, for the voice source', () => {
    assert.strictEqual(calls[0].url, '/api/agent/actions');
    assert.strictEqual(calls[0].options.method, 'POST');
    const body = JSON.parse(calls[0].options.body);
    assert.strictEqual(body.step, 'script');
    assert.strictEqual(body.action, 'script.iterate_scene');
    assert.strictEqual(body.credits, 2);
    assert.strictEqual(body.idea_id, 'idea-42');
    assert.strictEqual(body.utterance, 'make it punchier');
  });

  check('calls the exact same endpoint + body the button calls (handleScriptRegenerate)', () => {
    assert.strictEqual(calls[1].url, '/api/script/idea-42/scene/2/regenerate');
    assert.strictEqual(calls[1].options.method, 'POST');
    assert.deepStrictEqual(JSON.parse(calls[1].options.body), { instruction: 'be punchier' });
  });

  check('sends X-Agent-Action-Id matching the row just created', () => {
    assert.strictEqual(calls[1].options.headers['X-Agent-Action-Id'], 'action-row-1');
    assert.strictEqual(calls[1].options.headers['Authorization'], 'Bearer TEST_JWT');
  });

  check('currentActionId is cleared after a successful run', () => {
    assert.strictEqual(BrandStudioActions.currentActionId, null);
  });
}

async function testThrownRunStillClearsCurrentActionId() {
  const calls = [];
  const fetchMock = async (url) => {
    calls.push(url);
    if (url === '/api/agent/actions') {
      return { ok: true, status: 201, json: async () => ({ id: 'action-row-2' }) };
    }
    if (url === '/api/audiovisual/idea-42/scenes/2/asset_type') {
      return { ok: false, status: 422, json: async () => ({ error: 'Cannot change a locked scene' }) };
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const { BrandStudioActions } = loadApp(fetchMock);

  const outcome = await BrandStudioActions.execute(
    'audiovisual.change_scene_type',
    { ideaId: 'idea-42', sceneN: 2, assetType: 'ai_video' },
    { source: 'voice', voiceMeta: { ideaId: 'idea-42' } }
  );

  check('a thrown run() comes back as {ok:false, error}', () => {
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(outcome.error, 'Cannot change a locked scene');
  });

  check('currentActionId is cleared even when run() throws', () => {
    assert.strictEqual(BrandStudioActions.currentActionId, null);
  });
}

async function testButtonSourceSkipsTheAuditRowCreateCall() {
  const calls = [];
  const fetchMock = async (url, options) => {
    calls.push(url);
    if (url === '/api/script/idea-42/scene/1') {
      return { ok: true, status: 200, json: async () => ({ script: SCRIPT_FIXTURE }) };
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const { BrandStudioActions } = loadApp(fetchMock);

  const outcome = await BrandStudioActions.execute(
    'script.edit_scene_text',
    { sceneIdx: 0, text: 'New line' },
    { source: 'button' }
  );

  check('a button-sourced execute() never calls POST /api/agent/actions', () => {
    assert.ok(!calls.includes('/api/agent/actions'), `unexpected calls: ${calls}`);
  });
  check('the free edit_scene_text action still runs and succeeds', () => {
    assert.strictEqual(outcome.ok, true);
  });
}

async function testRegistryShape() {
  const { BrandStudioActions } = loadApp(async () => {
    throw new Error('fetch should not be called by this test');
  });

  check('registers exactly 5 Script actions', () => {
    const ids = BrandStudioActions.list('script').map((a) => a.id).sort();
    assert.deepStrictEqual(ids, [
      'script.audit',
      'script.edit_scene_text',
      'script.generate',
      'script.iterate_scene',
      'script.lock',
    ]);
  });

  check('registers exactly 5 Audiovisual actions', () => {
    const ids = BrandStudioActions.list('audiovisual').map((a) => a.id).sort();
    assert.deepStrictEqual(ids, [
      'audiovisual.change_scene_type',
      'audiovisual.estimate',
      'audiovisual.generate_all',
      'audiovisual.open_recording_studio',
      'audiovisual.regenerate_one',
    ]);
  });

  check('get() returns null for an unregistered id', () => {
    assert.strictEqual(BrandStudioActions.get('does.not_exist'), null);
  });

  const unknownOutcome = await BrandStudioActions.execute('does.not_exist', {}, { source: 'voice' });
  check('execute() on an unknown id fails without touching fetch', () => {
    assert.strictEqual(unknownOutcome.ok, false);
    assert.match(unknownOutcome.error, /Unknown action/);
  });
}

async function main() {
  await testRegistryShape();
  await testIterateSceneMatchesButtonPathAndSendsHeader();
  await testThrownRunStillClearsCurrentActionId();
  await testButtonSourceSkipsTheAuditRowCreateCall();

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed.`);
    process.exit(1);
  }
  console.log('\nAll checks passed.');
}

main();
