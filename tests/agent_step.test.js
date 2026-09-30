/**
 * F-05 � Agentic mode toggle + step-scoped Brandy
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
test('Global tools present (non-brain steps; brain step is interview-only)', () => {
  const tools = agent.toolsForStep('catalog');
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
  assert.strictEqual(sent[0].session.tools.length, 2);
  assert.strictEqual(sent[0].session.tools[0].name, 'extract_brand_brain');
});
test('sendSessionUpdate ON mode includes global tools', () => {
  const sent = [];
  const mockWs = { readyState: 1, send: d => sent.push(JSON.parse(d)) };
  agent.sendSessionUpdate(true, 'catalog', { brainCount: 5, balance: 100 }, mockWs);
  const names = sent[0].session.tools.map(t => t.name);
  assert(names.includes('get_status'));
  assert(names.includes('propose_action'));
});
test('Agentic ON on brain step registers extract_brand_brain (fills the Brand Soul screen)', () => {
  const sent = [];
  const mockWs = { readyState: 1, send: d => sent.push(JSON.parse(d)) };
  agent.sendSessionUpdate(true, 'brain', { basePrompt: 'BRANDY INTERVIEW PROMPT' }, mockWs);
  const names = sent[0].session.tools.map(t => t.name);
  assert(names.includes('extract_brand_brain') && names.includes('confirm_brand_section'), 'interview tools missing in agentic brain step');
  assert.strictEqual(names.length, 2, 'brain step must expose only the interview tools');
  assert(sent[0].session.system_prompt.includes('BRANDY INTERVIEW PROMPT'), 'basePrompt not propagated');
  assert(sent[0].session.system_prompt.startsWith('INTERVIEW LOOP'), 'tool rule must be front-loaded');
});
test('extract_brand_brain is not offered outside the brain step', () => {
  const names = agent.toolsForStep('catalog').map(t => t.name);
  assert(!names.includes('extract_brand_brain'));
});
test('Interview tool schemas keep the shape proven in production (field enum + value)', () => {
  const [save, confirm] = agent.toolsForStep('brain');
  assert.strictEqual(save.name, 'extract_brand_brain');
  assert.deepStrictEqual(save.parameters.required, ['field', 'value']);
  assert.strictEqual(save.parameters.properties.field.enum.length, 43);
  assert.deepStrictEqual(confirm.parameters.required, ['section']);
  assert.strictEqual(save.execution_mode, undefined);
});
test('Session prompt: work phrases vary, no "One moment" instruction, few-shot uses the new schema', () => {
  const sent = [];
  const mockWs = { readyState: 1, send: d => sent.push(JSON.parse(d)) };
  const prompts = new Set();
  for (let i = 0; i < 30; i++) {
    sent.length = 0;
    agent.sendSessionUpdate(true, 'brain', { basePrompt: 'BASE' }, mockWs);
    prompts.add(sent[0].session.system_prompt);
  }
  assert(prompts.size > 3, 'the example phrases must change between session.updates');
  const p = [...prompts][0];
  assert(!/say only "One moment/i.test(p));
  assert(!p.includes('[call'), 'no bracketed tool-call example: the voice model reads it out loud');
  assert(p.includes('TOOLS ARE SILENT'));
  assert(/2 to 5 word phrase/.test(p));
});
console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
