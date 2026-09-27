'use strict';
/**
 * Node test for F-06 (Confirmation engine). Run with:
 *   node tests/confirm_engine.test.js
 *
 * Loads the real app/static/confirm_engine.js. Most cases require() it
 * directly (its Node/CommonJS export path); one case uses
 * tests/agent_harness.js's loadBrowserScript() to prove the browser export
 * path (`window.createConfirmationEngine`) also works, and its
 * createMockFetch() to show the engine actually gates a real HTTP call --
 * the "no execution allowed without valid proposal state" contract -- since
 * `app/static/agent.js` (the piece that wires propose_action/confirm_action
 * into Brandy's tool handlers) does not exist in this repo yet.
 *
 * Covers the harness cases from docs/specs/F/pieces/F-06_confirmation_engine.md
 * that belong to the pure engine itself (propose/confirm/cancel/pending).
 */
const assert = require('assert');
const path = require('path');

const { createConfirmationEngine } = require(path.join('..', 'app', 'static', 'confirm_engine.js'));
const { loadBrowserScript, createMockFetch } = require('./agent_harness');

const CONFIRM_ENGINE_JS = path.join(__dirname, '..', 'app', 'static', 'confirm_engine.js');

let passed = 0;
const pendingTests = [];

function test(name, fn) {
  pendingTests.push(async () => {
    await fn();
    passed += 1;
    console.log(`ok - ${name}`);
  });
}

test('propose stores a pending proposal with a token and the 45s default TTL', () => {
  const engine = createConfirmationEngine();
  const before = Date.now();
  const proposed = engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });

  assert.strictEqual(typeof proposed.token, 'string');
  assert.ok(proposed.token.length > 0);
  assert.strictEqual(proposed.actionId, 'script.iterate_scene');
  assert.deepStrictEqual(proposed.args, { sceneN: 3 });
  assert.strictEqual(proposed.cost, 2);

  const ttl = proposed.expiresAt - before;
  assert.ok(ttl >= 44000 && ttl <= 45500, `default TTL should be ~45000ms, got ${ttl}ms`);

  const pending = engine.pending();
  assert.deepStrictEqual(pending, proposed);
});

test('confirm happy path: explicit confirmation word runs the pending proposal once', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });

  const result = engine.confirm('confirm');
  assert.strictEqual(result.status, 'confirmed');
  assert.strictEqual(result.action.actionId, 'script.iterate_scene');
  assert.deepStrictEqual(result.action.args, { sceneN: 3 });
  assert.strictEqual(result.action.cost, 2);

  // double confirm runs once: nothing is pending any more, so a second
  // "confirm" cannot re-execute the same action.
  const again = engine.confirm('confirm');
  assert.strictEqual(again.status, 'not_confirmed');
  assert.strictEqual(again.reason, 'no_pending_proposal');
  assert.strictEqual(again.action, null);
});

test('a bare "yes" is not an explicit confirmation -- only the full "yes do it" phrase is', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'script.iterate_scene', args: {}, cost: 2 });

  const bareYes = engine.confirm('yes');
  assert.strictEqual(bareYes.status, 'not_confirmed');
  assert.strictEqual(bareYes.reason, 'no_match');
  assert.strictEqual(engine.pending(), null);

  const secondEngine = createConfirmationEngine();
  secondEngine.propose({ actionId: 'script.iterate_scene', args: {}, cost: 2 });
  const yesDoIt = secondEngine.confirm('yes do it');
  assert.strictEqual(yesDoIt.status, 'confirmed');
});

test('accepts Spanish confirmation words, case/accent-insensitive', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'catalog.lock', args: {}, cost: 0 });

  const result = engine.confirm('SÍ, HAZLO');
  assert.strictEqual(result.status, 'confirmed');
  assert.strictEqual(result.action.actionId, 'catalog.lock');
});

test('"confirm" with nothing pending does nothing', () => {
  const engine = createConfirmationEngine();
  const result = engine.confirm('confirm');
  assert.strictEqual(result.status, 'not_confirmed');
  assert.strictEqual(result.reason, 'no_pending_proposal');
  assert.strictEqual(result.action, null);
  assert.strictEqual(engine.pending(), null);
});

test('"no, wait, confirm" cancels instead of running', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'render.export', args: {}, cost: 10 });

  const result = engine.confirm('no, wait, confirm');
  assert.strictEqual(result.status, 'cancelled');
  assert.strictEqual(result.action, null);
  assert.strictEqual(engine.pending(), null);
});

test('a plain cancel word drops the proposal', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'catalog.discard_idea', args: { ideaId: 'abc' }, cost: 0 });

  const result = engine.confirm('cancel that');
  assert.strictEqual(result.status, 'cancelled');
  assert.strictEqual(engine.pending(), null);
});

test('expired proposal cannot be confirmed', () => {
  const engine = createConfirmationEngine({ maxAgeMs: 0 });
  engine.propose({ actionId: 'script.lock', args: {}, cost: 0, expiresAt: Date.now() - 1 });

  assert.strictEqual(engine.pending(), null);
  const result = engine.confirm('confirm');
  assert.strictEqual(result.status, 'not_confirmed');
  assert.strictEqual(result.reason, 'no_pending_proposal');
  assert.strictEqual(result.action, null);
});

test('restatement then correction: a new proposal replaces the pending one', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'audiovisual.regenerate_one', args: { sceneN: 13 }, cost: 3 });
  const corrected = engine.propose({ actionId: 'audiovisual.regenerate_one', args: { sceneN: 3 }, cost: 3 });

  assert.deepStrictEqual(engine.pending().args, { sceneN: 3 });

  const result = engine.confirm('confirm');
  assert.strictEqual(result.status, 'confirmed');
  assert.deepStrictEqual(result.action.args, { sceneN: 3 });
  assert.strictEqual(result.action.token, corrected.token);
});

test('a long unrelated utterance containing "confirm" does not count as explicit confirmation', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });

  const result = engine.confirm('can you confirm what scene three was supposed to say again please');
  assert.strictEqual(result.status, 'not_confirmed');
  assert.strictEqual(result.reason, 'no_match');
  assert.strictEqual(engine.pending(), null);
});

test('an unrelated utterance drops the proposal instead of leaving it pending', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });

  const result = engine.confirm('what does the balance look like');
  assert.strictEqual(result.status, 'not_confirmed');
  assert.strictEqual(result.reason, 'no_match');
  assert.strictEqual(engine.pending(), null);
});

test('cancel() clears a pending proposal directly', () => {
  const engine = createConfirmationEngine();
  engine.propose({ actionId: 'script.lock', args: {}, cost: 0 });

  assert.strictEqual(engine.cancel(), true);
  assert.strictEqual(engine.pending(), null);
  assert.strictEqual(engine.cancel(), false);
});

test('browser export path: loading the script as a page script attaches window.createConfirmationEngine', () => {
  const context = { window: {} };
  context.window.window = context.window; // real browsers make `window` self-referential
  loadBrowserScript(CONFIRM_ENGINE_JS, context);

  assert.strictEqual(typeof context.window.createConfirmationEngine, 'function');
  assert.strictEqual(typeof context.window.BrandStudioConfirmEngine.createConfirmationEngine, 'function');

  const engine = context.window.createConfirmationEngine();
  const proposed = engine.propose({ actionId: 'script.lock', args: {}, cost: 0 });
  assert.strictEqual(typeof proposed.token, 'string');
});

test('integration via agent_harness: no execution allowed without a matching, unexpired confirmation', async () => {
  const engine = createConfirmationEngine();
  const fetchMock = createMockFetch();

  // Simulates what the (not-yet-written) agent.js wiring will do: call the
  // button's real function only after confirm() reports "confirmed".
  async function runIfConfirmed(confirmResult) {
    if (confirmResult.status !== 'confirmed') return;
    await fetchMock(`/api/script/iterate?sceneN=${confirmResult.action.args.sceneN}`, {
      method: 'POST',
      body: JSON.stringify(confirmResult.action.args),
    });
  }

  engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });
  await runIfConfirmed(engine.confirm('no, that is wrong'));
  assert.strictEqual(fetchMock.calls.length, 0, 'a non-confirming utterance must never call the action');

  engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });
  await runIfConfirmed(engine.confirm('confirm'));
  assert.strictEqual(fetchMock.calls.length, 1);
  assert.strictEqual(fetchMock.calls[0].url, '/api/script/iterate?sceneN=3');
  assert.strictEqual(fetchMock.calls[0].options.method, 'POST');
});

(async () => {
  for (const runTest of pendingTests) {
    await runTest();
  }
  console.log(`\nAll checks passed. (${passed} tests)`);
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
