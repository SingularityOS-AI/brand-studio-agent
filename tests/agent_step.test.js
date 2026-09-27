/**
 * F-05 — Agentic mode toggle + step-scoped Brandy
 * Node harness test
 */
'use strict';
const assert = require('assert');
const agent = require('../app/static/agent.js');
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('? ' + name); }
  catch (e) { failed++; console.log('? ' + name + ': ' + e.message); }
}
console.log('F-05 Agent Step Tests\n');
test('Module exports required functions', () => {
  assert.strictEqual(typeof agent.buildStepSummary, 'function');
  assert.strictEqual(typeof agent.toolsForStep, 'function');
  assert.strictEqual(typeof agent.sendSessionUpdate, 'function');
  assert.strictEqual(typeof agent.getUnlockedSteps, 'function');
});
test('STEP_ORDER contains expected steps', () => {
  assert.deepStrictEqual(agent.STEP_ORDER, ['brain', 'catalog', 'script', 'audiovisual', 'editing']);
});
test('GLOBAL_TOOL_NAMES contains expected tools', () => {
  assert.deepStrictEqual(agent.GLOBAL_TOOL_NAMES, ['get_status', 'get_balance', 'go_to_step']);
});
test('buildStepSummary returns <= 1200 chars', () => {
  const summary = agent.buildStepSummary('brain', { brainCount: 3, balance: 500 });
  assert(summary.length <= 1200);
});
test('toolsForStep returns array', () => {
  const tools = agent.toolsForStep('brain');
  assert(Array.isArray(tools));
  assert(tools.length > 0);
});
test('Global tools present', () => {
  const tools = agent.toolsForStep('brain');
  const names = tools.map(t => t.name);
  assert(names.includes('get_status'));
  assert(names.includes('propose_action'));
  assert(names.includes('confirm_action'));
});
test('getUnlockedSteps returns brain initially', () => {
  assert.deepStrictEqual(agent.getUnlockedSteps({}), ['brain']);
});
test('getUnlockedSteps includes catalog after brainComplete', () => {
  const unlocked = agent.getUnlockedSteps({ brainComplete: true });
  assert(unlocked.includes('brain') && unlocked.includes('catalog'));
});
test('sendSessionUpdate OFF mode sends one tool', () => {
  const sent = [];
  const mockWs = { readyState: 1, send: d => sent.push(JSON.parse(d)) };
  agent.sendSessionUpdate(false, 'brain', {}, mockWs);
  assert.strictEqual(sent.length, 1);
  assert.strictEqual(sent[0].session.tools.length, 1);
  assert.strictEqual(sent[0].session.tools[0].name, 'extract_brand_brain');
});
test('sendSessionUpdate ON mode includes global tools', () => {
  const sent = [];
  const mockWs = { readyState: 1, send: d => sent.push(JSON.parse(d)) };
  agent.sendSessionUpdate(true, 'brain', { brainCount: 5, balance: 100 }, mockWs);
  const names = sent[0].session.tools.map(t => t.name);
  assert(names.includes('get_status'));
  assert(names.includes('propose_action'));
});
console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
