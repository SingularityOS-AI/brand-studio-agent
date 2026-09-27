'use strict';
/**
 * Node test for F-06 (Confirmation engine). Run with:
 *   node tests/test_confirm_engine.js
 *
 * Loads the real app/static/confirm_engine.js via require() (it exports
 * `createConfirmationEngine` through module.exports) and drives it directly
 * -- no DOM, no network, no fetch mocking needed since the engine itself
 * has none of those dependencies.
 *
 * Covers the harness cases from docs/specs/F/pieces/F-06_confirmation_engine.md
 * that belong to the pure engine (propose/confirm/cancel/pending). The two
 * cases that are about wiring rather than the engine itself -- "double
 * confirm runs once" in the sense of the action only ever being *executed*
 * once, and "free action runs without confirmation" -- are covered here
 * only insofar as the engine's own state supports them; the actual
 * execution-gating and needsConfirm bypass live in the later piece that
 * wires this into agent.js (not yet in this repo).
 */
const assert = require('assert');
const path = require('path');

const { createConfirmationEngine } = require(path.join('..', 'app', 'static', 'confirm_engine.js'));

let passed = 0;

function test(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

test('propose stores a pending proposal with a token and default 45s-style TTL', () => {
  const engine = createConfirmationEngine({ maxAgeMs: 45000 });
  const proposed = engine.propose({ actionId: 'script.iterate_scene', args: { sceneN: 3 }, cost: 2 });

  assert.strictEqual(typeof proposed.token, 'string');
  assert.ok(proposed.token.length > 0);
  assert.strictEqual(proposed.actionId, 'script.iterate_scene');
  assert.deepStrictEqual(proposed.args, { sceneN: 3 });
  assert.strictEqual(proposed.cost, 2);

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
  const engine = createConfirmationEngine({ maxAgeMs: 10 });
  engine.propose({ actionId: 'script.lock', args: {}, cost: 0 });

  // Force expiry deterministically instead of sleeping in a unit test.
  const stillPendingImmediately = engine.pending();
  assert.notStrictEqual(stillPendingImmediately, null);

  const expiredEngine = createConfirmationEngine({ maxAgeMs: 0 });
  expiredEngine.propose({ actionId: 'script.lock', args: {}, cost: 0, expiresAt: Date.now() - 1 });

  assert.strictEqual(expiredEngine.pending(), null);
  const result = expiredEngine.confirm('confirm');
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

console.log(`\nAll checks passed. (${passed} tests)`);
