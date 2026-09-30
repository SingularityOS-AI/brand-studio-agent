// app.js handleToolCall must hand every agentic tool to BrandStudioVoiceTools and send
// its payload back as tool.result (before this, they were all answered "not available").
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

global.window = {};
const agent = require('../app/static/agent.js');
const src = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'app.js'), 'utf8');
const start = src.indexOf('// === VOICE PROTOCOL START ===');
const end = src.indexOf('// === VOICE PROTOCOL END ===');

const sent = [];
const activity = [];
const handled = [];
const fakeVoiceTools = {
  isVoiceTool: (n) => n !== 'extract_brand_brain' && n !== 'confirm_brand_section',
  resolveActionId: () => 'catalog.accept',
  handle: async (name, args, deps) => {
    handled.push({ name, args, step: deps.currentStep() });
    const p = { success: true, status: 'done', result: 'Idea 2 accepted.' };
    Object.defineProperty(p, '_activity', { value: { kind: 'saved', state: 'done', text: 'Done: Accept an idea' }, enumerable: false });
    return p;
  },
};
const ctx = {
  window: { BrandStudioAgent: agent, BrandStudioVoiceTools: fakeVoiceTools, BrandStudioActions: { get: () => ({ title: 'Accept an idea for scripting' }) } },
  voiceDeps: () => ({ currentStep: () => 'catalog' }),
  fullTranscript: [], cachedBrain: null, missingSections: [], orbState: { textContent: '' }, activeSources: [],
  markVoiceActivity() {}, appendExtractedSections() {}, updateBrandSoulButton() {}, updateCatalogButton() {},
  WebSocket: { OPEN: 1 }, ws: { readyState: 1, send: (d) => sent.push(JSON.parse(d)) },
  setTimeout: () => 0, clearTimeout: () => {},
  document: { dispatchEvent: (e) => { activity.push(e.detail); return true; } },
  CustomEvent: function (type, init) { this.detail = init && init.detail; },
  localStorage: { getItem: () => null }, performance: { now: () => 0 },
  console: { log() {}, warn() {}, error() {} },
  authenticatedFetch: async () => ({ ok: true, json: async () => ({}) }),
};
vm.createContext(ctx);
vm.runInContext(src.slice(start, end) + '\nvar api = { event: protocolOnEvent, chain: function () { return toolChain; } };', ctx);

(async () => {
  ctx.api.event({ type: 'reply.done', status: 'completed' });
  ctx.api.event({ type: 'tool.call', name: 'catalog_accept', arguments: { idea: '2' }, call_id: 'c1' });
  await ctx.api.chain();
  assert.strictEqual(handled.length, 1);
  assert.strictEqual(handled[0].name, 'catalog_accept');
  const res = sent.filter((m) => m.type === 'tool.result');
  assert.strictEqual(res.length, 1);
  assert.strictEqual(res[0].call_id, 'c1');
  assert.strictEqual(JSON.parse(res[0].result).result, 'Idea 2 accepted.');
  assert.strictEqual(res[0].is_error, false);
  assert.ok(activity.some((a) => a.kind === 'working' && /Acting: Accept an idea/.test(a.text)), 'acting row shown while it runs');
  assert.ok(activity.some((a) => a.kind === 'saved' && a.id === 'tool-c1'));
  console.log('OK: handleToolCall delegates agentic tools to BrandStudioVoiceTools');
})().catch((e) => { console.error(e); process.exit(1); });
