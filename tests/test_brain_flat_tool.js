// Brand interview tools (extract_brand_brain per field + confirm_brand_section) and
// tool.result timing. Extracts the REAL source from app.js (VOICE PROTOCOL block; same
// technique as test_silence_watchdog.js), so breaking app.js breaks this test.
// Schema (BR-A): section + field + value as plain strings (no enum), resolved in code.
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
assert.ok(start !== -1 && end > start, 'VOICE PROTOCOL block not found in app.js');

const sent = [];
const posts = [];
const store = {}; // emulated backend: section id -> {id,status,content,citation_text}

const ctx = {
  window: { BrandStudioAgent: agent },
  fullTranscript: [],
  cachedBrain: null,
  missingSections: [],
  orbState: { textContent: '' },
  activeSources: [],
  markVoiceActivity() {},
  appendExtractedSections() {},
  updateBrandSoulButton() {},
  updateCatalogButton() {},
  WebSocket: { OPEN: 1 },
  ws: { readyState: 1, send: (d) => sent.push(JSON.parse(d)) },
  setTimeout: () => 0,
  clearTimeout: () => {},
  document: { dispatchEvent: () => true },
  CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
  localStorage: { getItem: () => null },
  performance: { now: () => 0 },
  console: { log() {}, warn() {}, error() {} },
  authenticatedFetch: async (url, opts) => {
    const body = JSON.parse(opts.body);
    posts.push(body);
    const sec = body.tool_result.sections[0];
    store[sec.id] = {
      id: sec.id,
      status: sec.confirmed ? 'confirmado' : 'propuesto',
      content: sec.content,
      citation_text: sec.citation_text,
    };
    return { ok: true, json: async () => ({ brand_brain: { sections: Object.values(store) }, missing_sections: [] }) };
  },
};
vm.createContext(ctx);
vm.runInContext(src.slice(start, end) + `
  var api = {
    handle: handleToolCall,
    event: protocolOnEvent,
    chain: function () { return toolChain; },
    persist: function () { return persistChain; },
    pending: pendingToolResults,
  };`, ctx);
const api = ctx.api;

const say = (speaker, text) => ctx.fullTranscript.push({ speaker, text });
const lastResult = () => JSON.parse(sent[sent.length - 1].result);
const sec = (section, key) => agent.BRAIN_FIELDS.find((f) => f.section === section && f.key === key);
// Run one tool call and wait for its result AND its background save (POST is optimistic/async).
const call = async (name, args, id) => { await api.handle(name, args, id); await api.persist(); };
const save = (section, field, value, id) => call('extract_brand_brain', { section, field, value }, id);

(async () => {
  assert.strictEqual(agent.BRAIN_FIELDS.length, 43);
  // Proven production shape (live test #5): field enum of section.name aliases + value.
  {
    const [sv, cf] = agent.BRAIN_INTERVIEW_TOOLS;
    assert.deepStrictEqual(sv.parameters.required, ['field', 'value']);
    assert.strictEqual(sv.parameters.properties.field.enum.length, 43);
    assert.ok(sv.parameters.properties.field.enum.includes('diagnostico.stage'));
    assert.deepStrictEqual(cf.parameters.required, ['section']);
    assert.strictEqual(cf.parameters.properties.section.enum.length, 9);
    assert.strictEqual(sv.execution_mode, undefined, 'no execution_mode: keep the proven shape');
  }

  // Protocol: reply.done is the latest event, so every answer goes out at once.
  api.event({ type: 'reply.done', reply_id: 'R0', status: 'completed' });

  // 1. unknown tool is answered (an unanswered call freezes the agent)
  await api.handle('get_status', {}, 'c0');
  assert.strictEqual(sent[0].call_id, 'c0');
  assert.strictEqual(sent[0].is_error, true);

  // 2. save one field: citation = founder's own words, status propuesto, next question asked
  say('agent', 'Hi, I am Brandy. Tell me what you do and who you do it for.');
  say('user', 'I am a qualified medical interpreter and I have no clients yet.');
  await save('diagnostico', 'stage', 'no clients yet', 'c1');
  let post = posts[posts.length - 1].tool_result.sections[0];
  assert.strictEqual(post.id, 'diagnostico');
  assert.strictEqual(post.confirmed, false);
  assert.strictEqual(post.citation_text, 'I am a qualified medical interpreter and I have no clients yet.');
  assert.strictEqual(post.content.etapa, 'no clients yet');
  let res = lastResult();
  assert.strictEqual(res.success, true);
  assert.ok(/Ask ONE short question about/.test(res.next), res.next);
  assert.ok(/1 of 7/.test(res.section_progress), res.section_progress);

  // 3. unknown field rejected, with the valid fields listed for the model
  await save('diagnostico', 'nope.nope', 'x', 'c2');
  res = lastResult();
  assert.strictEqual(res.success, false);
  assert.strictEqual(sent[sent.length - 1].is_error, true);
  assert.ok(/Unknown field "nope\.nope" for section "Where you stand"\. Valid fields: stage, ramiro_level, symptom/.test(res.error), res.error);

  // 4. cannot confirm an incomplete section (every variable of the node is required)
  say('user', 'Yes, that is right.');
  await call('confirm_brand_section', { section: 'diagnostico' }, 'c3');
  res = lastResult();
  assert.strictEqual(res.success, false);
  assert.ok(/not complete yet/.test(res.error), res.error);

  // 5. fill the remaining 6 fields; then the result asks for a summary + explicit yes
  const diag = agent.BRAIN_FIELDS.filter((f) => f.section === 'diagnostico' && f.key !== 'etapa');
  say('user', 'Here is everything else about where I stand.');
  for (const f of diag) await save('diagnostico', f.alias, 'v-' + f.key, 'f-' + f.key);
  res = lastResult();
  assert.ok(/is complete\. Summarize it in ONE short sentence/.test(res.next), res.next);

  // 6. confirm without an explicit yes in the founder's last words -> refused
  say('user', 'Hmm, let me think about it.');
  await call('confirm_brand_section', { section: 'diagnostico' }, 'c4');
  res = lastResult();
  assert.strictEqual(res.success, false);
  assert.ok(/explicit yes/.test(res.error), res.error);
  assert.strictEqual(store.diagnostico.status, 'propuesto');

  // 7. explicit yes -> confirmed, citation is the yes, next section starts
  say('user', "Yes, that's right.");
  await call('confirm_brand_section', { section: 'Where you stand' }, 'c5');
  res = lastResult();
  assert.strictEqual(res.success, true);
  assert.strictEqual(store.diagnostico.status, 'confirmado');
  assert.strictEqual(store.diagnostico.citation_text, "Yes, that's right.");
  assert.strictEqual(Object.keys(store.diagnostico.content).length, 7);
  ctx.cachedBrain = { sections: Object.values(store) };
  assert.ok(/section "Brand Journey"/.test(res.next), res.next);

  // 8. a confirmed section is locked
  await save('diagnostico', 'stage', 'changed', 'c6');
  assert.strictEqual(lastResult().success, false);
  assert.strictEqual(store.diagnostico.content.etapa, 'no clients yet');

  // 9. tool.result is held while a turn is in flight and flushed after reply.done
  sent.length = 0;
  api.event({ type: 'reply.started', reply_id: 'R1' });
  await save('brand_journey', 'desired_result', 'ten clients', 'h1');
  assert.strictEqual(sent.length, 0, 'must not send tool.result mid-turn');
  api.event({ type: 'reply.done', reply_id: 'R1', status: 'completed' });
  assert.strictEqual(sent.length, 1);
  assert.strictEqual(sent[0].type, 'tool.result');
  assert.strictEqual(sent[0].call_id, 'h1');
  assert.strictEqual(typeof sent[0].result, 'string');

  // 10. interview is done only when all 9 sections are confirmed
  const order = agent.BRAIN_SECTION_ORDER.slice(1);
  say('user', 'Answering everything for the remaining sections.');
  for (const s of order) {
    for (const f of agent.BRAIN_FIELDS.filter((x) => x.section === s)) {
      await save(s, f.name, 'v-' + f.key, 's-' + f.alias);
    }
    say('user', 'Yes, exactly.');
    await call('confirm_brand_section', { section: s }, 'k-' + s);
    ctx.cachedBrain = { sections: Object.values(store) };
  }
  assert.ok(/All 9 sections are confirmed/.test(lastResult().next), lastResult().next);
  assert.strictEqual(Object.values(store).filter((x) => x.status === 'confirmado').length, 9);

  console.log('OK: brand interview tools - 10 groups of checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
