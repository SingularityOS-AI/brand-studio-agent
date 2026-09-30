// Auto-extraction safety net: after a founder answer, the client asks the backend
// (/api/brain/auto-extract) for field values and saves them through the SAME
// runSaveFact / runConfirmSection path. Runs the REAL VOICE PROTOCOL block of app.js.
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
assert.ok(start !== -1 && end > start);

const sent = [];
const posts = [];
const autoCalls = [];
const activity = [];
const timers = [];
let autoReply = { updates: [] };
const store = {};

const ctx = {
  window: { BrandStudioAgent: agent },
  fullTranscript: [],
  cachedBrain: null,
  missingSections: [],
  currentOpenView: 'brain',
  orbState: { textContent: '' },
  activeSources: [],
  markVoiceActivity() {},
  appendExtractedSections() {},
  updateBrandSoulButton() {},
  updateCatalogButton() {},
  WebSocket: { OPEN: 1 },
  ws: { readyState: 1, send: (d) => sent.push(JSON.parse(d)) },
  setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearTimeout: () => {},
  document: { dispatchEvent: (e) => { activity.push(e.detail); return true; } },
  CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
  localStorage: { getItem: () => null },
  performance: { now: () => 0 },
  console: { log() {}, warn: (...a) => process.stderr.write('WARN ' + a.join(' ') + String.fromCharCode(10)), error: (...a) => process.stderr.write('ERR ' + a.join(' ') + String.fromCharCode(10)) },
  authenticatedFetch: async (url, opts) => {
    const body = JSON.parse(opts.body);
    if (url === '/api/brain/auto-extract') {
      autoCalls.push(body);
      return { ok: true, json: async () => autoReply };
    }
    posts.push(body);
    const sec = body.tool_result.sections[0];
    store[sec.id] = { id: sec.id, status: sec.confirmed ? 'confirmado' : 'propuesto', content: sec.content, citation_text: sec.citation_text };
    return { ok: true, json: async () => ({ brand_brain: { sections: Object.values(store) }, missing_sections: [] }) };
  },
};
vm.createContext(ctx);
vm.runInContext(src.slice(start, end) + `
  var api = { event: protocolOnEvent, run: runAutoExtract, persist: function () { return persistChain; } };`, ctx);
const api = ctx.api;

const agentSays = (text) => { ctx.fullTranscript.push({ speaker: 'agent', text }); api.event({ type: 'transcript.agent', text }); };
const founderSays = (text) => { api.event({ type: 'transcript.user', text }); ctx.fullTranscript.push({ speaker: 'user', text }); };
const tick = () => new Promise((r) => setImmediate(r));
const fireTimers = async () => { const t = timers.splice(0).filter((x) => x.ms === 1200); for (const x of t) x.fn(); for (let i = 0; i < 5; i++) await tick(); await api.persist(); for (let i = 0; i < 3; i++) await tick(); };
const steering = () => sent.filter((m) => m.type === 'conversation.message');

(async () => {
  api.event({ type: 'reply.done', status: 'completed' });

  // 1. a founder answer (split in 2 final transcripts) -> ONE auto-extract call with the question
  agentSays('What is the one key skill you need to unlock at your current stage?');
  autoReply = { updates: [{ field: 'diagnostico.skill_to_unlock', value: 'content production' }] };
  founderSays('I guess content production,');
  founderSays('sir.');
  assert.ok(timers.some((t) => t.ms === 1200), 'debounced');
  await fireTimers();
  assert.strictEqual(autoCalls.length, 1);
  assert.strictEqual(autoCalls[0].question, 'What is the one key skill you need to unlock at your current stage?');
  assert.strictEqual(autoCalls[0].answer, 'I guess content production, sir.');
  assert.strictEqual(autoCalls[0].fields.length, 43);
  // saved through the normal path, citation = founder's literal answer
  const p = posts[posts.length - 1].tool_result.sections[0];
  assert.strictEqual(p.id, 'diagnostico');
  assert.strictEqual(p.content.habilidad_a_desbloquear, 'content production');
  assert.strictEqual(p.citation_text, 'I guess content production, sir.');
  assert.strictEqual(p.confirmed, false);
  // Brandy is steered with a system message (no reply is triggered)
  const st = steering();
  assert.strictEqual(st.length, 1);
  assert.strictEqual(st[0].role, 'system');
  assert.ok(/diagnostico\.skill_to_unlock/.test(st[0].content) && /Ask ONE short question/.test(st[0].content), st[0].content);
  assert.ok(!sent.some((m) => m.type === 'reply.create'), 'no extra reply is forced');
  // right panel shows the acting row and the saved row
  assert.ok(activity.some((a) => a.kind === 'working' && /reading your answer/.test(a.text)));
  assert.ok(activity.some((a) => a.kind === 'saved' && /Captured 1 fact/.test(a.text)));

  // 2. unknown alias from the model is refused, nothing invented
  autoReply = { updates: [{ field: 'nope.nope', value: 'x' }] };
  agentSays('Anything else?');
  founderSays('Well that is all I can say.');
  const before = posts.length;
  await fireTimers();
  assert.strictEqual(posts.length, before);

  // 3. "yes" to a summary of an INCOMPLETE section -> not locked, Brandy asked for the missing field
  agentSays('You are at stage one and need content production. Is that right?');
  founderSays('Yes, that is right.');
  await fireTimers();
  assert.strictEqual(store.diagnostico.status, 'propuesto');
  assert.ok(/Not locked yet/.test(steering().slice(-1)[0].content));

  // 4. fill the section, then "yes" to the summary -> confirmed with the literal yes
  const missing = agent.BRAIN_FIELDS.filter((f) => f.section === 'diagnostico' && f.key !== 'habilidad_a_desbloquear');
  autoReply = { updates: missing.slice(0, 4).map((f) => ({ field: f.alias, value: 'v-' + f.key })) };
  agentSays('Tell me more about where you stand.');
  founderSays('Here are several details about where I stand today.');
  await fireTimers();
  autoReply = { updates: missing.slice(4).map((f) => ({ field: f.alias, value: 'v-' + f.key })) };
  agentSays('And the rest?');
  founderSays('And these are the remaining details about me.');
  await fireTimers();
  agentSays('So that is your diagnosis in one sentence. Is that right?');
  founderSays("Yes, that's right.");
  await fireTimers();
  assert.strictEqual(store.diagnostico.status, 'confirmado');
  assert.strictEqual(store.diagnostico.citation_text, "Yes, that's right.");
  assert.ok(activity.some((a) => a.kind === 'decision'));

  // 5. outside the brain step nothing is extracted
  ctx.currentOpenView = 'catalog';
  const calls = autoCalls.length;
  agentSays('Which idea?');
  founderSays('The second one please.');
  await fireTimers();
  assert.strictEqual(autoCalls.length, calls);

  console.log('OK: auto-extract safety net - 5 groups of checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
