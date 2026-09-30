// BR-A: Brandy voice loop. Slices the "VOICE PROTOCOL" block out of the REAL
// app/static/app.js (same technique as test_brain_flat_tool.js) and runs it in a vm
// with a fake ws, fake timers, a controllable fetch and a fake DOM event target, so
// breaking app.js breaks this test.
//
// Covers: tool.result timing (docs pattern), interrupted-reply scoping, safety and
// force flushes, the stall watchdog, tool argument resolution, optimistic saves,
// activity events (brandy:activity contract), resume greeting, turn detection.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

global.window = {};
const agent = require('../app/static/agent.js');

const appPath = path.join(__dirname, '..', 'app', 'static', 'app.js');
const src = fs.readFileSync(appPath, 'utf8');
const START = '// === VOICE PROTOCOL START ===';
const END = '// === VOICE PROTOCOL END ===';
const start = src.indexOf(START);
const end = src.indexOf(END);
assert.ok(start !== -1 && end > start, 'VOICE PROTOCOL block not found in app.js');
assert.strictEqual(src.indexOf(START, start + 1), -1, 'VOICE PROTOCOL START must appear once');
const blockSrc = src.slice(start, end + END.length);
assert.ok(/function protocolOnEvent\(msg\)/.test(blockSrc), 'protocolOnEvent must live inside the block');

const APPEND_API = `
  var api = {
    event: protocolOnEvent,
    handle: handleToolCall,
    turn: turnDetectionConfig,
    chain: function () { return toolChain; },
    persist: function () { return persistChain; },
    pending: pendingToolResults,
    state: function () {
      return { lastEvent: lastEvent, toolsInFlight: toolsInFlight, calls: callsInCurrentReply.slice(),
               dropped: Array.from(droppedCalls), nudges: nudgesThisTurn };
    },
    confirmed: confirmedSections,
  };`;

const args = (section, field, value) => ({ section, field, value });
const plain = (o) => JSON.parse(JSON.stringify(o));

function makeEnv() {
  const env = {
    sent: [], activity: [], logs: [], errors: [], posts: [], renders: [],
    clock: 1000, timers: [], seq: 0, ls: {}, gate: null, failFetch: false, store: {},
  };
  const ctx = {
    window: { BrandStudioAgent: agent },
    fullTranscript: [],
    cachedBrain: null,
    missingSections: [],
    orbState: { textContent: '' },
    activeSources: [],
    markVoiceActivity() {},
    appendExtractedSections(s) { env.renders.push(plain(s)); },
    updateBrandSoulButton() {},
    updateCatalogButton() {},
    WebSocket: { OPEN: 1 },
    ws: { readyState: 1, send: (d) => env.sent.push(JSON.parse(d)) },
    setTimeout(fn, ms) { const t = { id: ++env.seq, fn, at: env.clock + ms }; env.timers.push(t); return t.id; },
    clearTimeout(id) { const i = env.timers.findIndex((t) => t.id === id); if (i !== -1) env.timers.splice(i, 1); },
    Date: { now: () => env.clock },
    performance: { now: () => env.clock },
    document: { dispatchEvent(e) { env.activity.push(plain(e.detail)); return true; } },
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    localStorage: { getItem: (k) => (Object.prototype.hasOwnProperty.call(env.ls, k) ? env.ls[k] : null) },
    console: {
      log: (...a) => env.logs.push(a.map(String).join(' ')),
      warn() {},
      error: (...a) => env.errors.push(a.map(String).join(' ')),
    },
    authenticatedFetch: async (url, o) => {
      const body = JSON.parse(o.body);
      env.posts.push(body);
      if (env.gate) await env.gate;
      if (env.failFetch) return { ok: false, status: 500, json: async () => ({}) };
      const sec = body.tool_result.sections[0];
      env.store[sec.id] = {
        id: sec.id,
        status: sec.confirmed ? 'confirmado' : 'propuesto',
        content: sec.content,
        citation_text: sec.citation_text,
      };
      return { ok: true, json: async () => ({ brand_brain: { sections: Object.values(env.store) }, missing_sections: [] }) };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(blockSrc + APPEND_API, ctx);
  env.ctx = ctx;
  env.api = ctx.api;
  env.say = (speaker, text) => ctx.fullTranscript.push({ speaker, text });
  // Move fake time forward, firing due timers in order.
  env.advance = (ms) => {
    const target = env.clock + ms;
    for (;;) {
      env.timers.sort((a, b) => a.at - b.at);
      const t = env.timers[0];
      if (!t || t.at > target) break;
      env.timers.shift();
      env.clock = t.at;
      t.fn();
    }
    env.clock = target;
  };
  env.ev = (type, extra) => env.api.event(Object.assign({ type }, extra || {}));
  env.call = (name, a, id) => env.ev('tool.call', { name, arguments: a, call_id: id });
  env.results = () => env.sent.filter((m) => m.type === 'tool.result');
  env.resultOf = (id) => env.results().filter((m) => m.call_id === id).map((m) => JSON.parse(m.result))[0];
  env.creates = () => env.sent.filter((m) => m.type === 'reply.create');
  env.acts = (kind) => env.activity.filter((a) => a.kind === kind);
  return env;
}

const sleepTick = () => new Promise((r) => setImmediate(r));

(async () => {
  // -------------------------------------------------------------------------
  // 1. tool.result timing: held while a turn is in flight, sent on reply.done
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.say('user', 'I have no sales yet.');
    e.ev('reply.started', { reply_id: 'R1' });
    e.call('extract_brand_brain', args('diagnostico', 'symptom', 'no sales yet'), 'c1');
    await e.api.chain();
    assert.strictEqual(e.results().length, 0, 'held while lastEvent is reply.started');
    assert.strictEqual(e.api.pending.length, 1);
    e.ev('reply.done', { reply_id: 'R1', status: 'completed' });
    assert.strictEqual(e.results().length, 1, 'sent on reply.done completed');
    assert.strictEqual(e.results()[0].call_id, 'c1');
    assert.strictEqual(typeof e.results()[0].result, 'string', 'result must be a JSON string');
    assert.strictEqual(e.results()[0].is_error, false);
    assert.strictEqual(e.api.pending.length, 0);

    // held while the founder is speaking (input.speech.started is the latest event)
    e.ev('input.speech.started');
    e.call('extract_brand_brain', args('diagnostico', 'stage', 'no clients'), 'c2');
    await e.api.chain();
    assert.strictEqual(e.results().length, 1, 'held while lastEvent is input.speech.started');
    e.ev('input.speech.stopped');
    e.ev('reply.started', { reply_id: 'R2' });
    assert.strictEqual(e.results().length, 1, 'still held during the next reply');
    e.ev('reply.done', { reply_id: 'R2', status: 'completed' });
    assert.strictEqual(e.results().length, 2, 'flushed at the next reply.done');
    assert.strictEqual(e.results()[1].call_id, 'c2');

    // reply.done already happened -> a result that becomes ready now goes out at once
    e.call('extract_brand_brain', args('diagnostico', 'prohibition', 'no ads'), 'c3');
    await e.api.chain();
    assert.strictEqual(e.results().length, 3, 'sent immediately when reply.done is the latest event');
    assert.strictEqual(e.results()[2].call_id, 'c3');

    // diagnostic logs
    assert.ok(e.logs.includes('[Event] reply.started R1'), e.logs.join('|'));
    assert.ok(e.logs.includes('[Event] reply.done R1 completed'));
    assert.ok(e.logs.includes('[Tool] result sent c1 ok'));
    e.ev('transcript.agent', { text: 'hi', interrupted: true });
    assert.ok(e.logs.includes('[Event] transcript.agent interrupted=true'));
    e.ev('session.error', { code: 'bad', message: 'boom' });
    assert.ok(e.errors.includes('[Agent Error] bad boom'), e.errors.join('|'));
  }

  // -------------------------------------------------------------------------
  // 2. interrupted reply drops only its own calls
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.say('user', 'Mixed answers here.');
    // A is emitted after reply R1 already finished, while the founder talks: held.
    e.ev('reply.started', { reply_id: 'R1' });
    e.ev('reply.done', { reply_id: 'R1', status: 'completed' });
    e.ev('input.speech.started');
    e.call('extract_brand_brain', args('diagnostico', 'stage', 'invisible pro'), 'A');
    await e.api.chain();
    assert.strictEqual(e.results().length, 0, 'A is held');
    // R2 makes call B, then is interrupted: B is dropped, A (earlier reply) is not.
    e.ev('input.speech.stopped');
    e.ev('reply.started', { reply_id: 'R2' });
    e.call('extract_brand_brain', args('diagnostico', 'symptom', 'posts nonstop'), 'B');
    await e.api.chain();
    assert.strictEqual(e.api.pending.length, 2);
    e.ev('reply.done', { reply_id: 'R2', status: 'interrupted' });
    assert.deepStrictEqual(plain(e.api.state().dropped), ['B']);
    assert.strictEqual(e.api.pending.length, 1, 'only B was discarded');
    assert.strictEqual(e.api.pending[0].callId, 'A');
    assert.strictEqual(e.results().length, 0, 'nothing is sent on an interrupted reply.done');
    // a late result of a dropped call is never sent
    e.ev('reply.started', { reply_id: 'R3' });
    e.call('extract_brand_brain', args('diagnostico', 'postura', 'x'), 'D');
    e.ev('reply.done', { reply_id: 'R3', status: 'interrupted' });   // before D's tool finished
    await e.api.chain();
    assert.ok(e.api.state().dropped.indexOf('D') !== -1);
    assert.strictEqual(e.api.pending.filter((p) => p.callId === 'D').length, 0, 'late result of a dropped call is not queued');
    // next completed reply sends A, never B or D
    e.ev('reply.started', { reply_id: 'R4' });
    e.ev('reply.done', { reply_id: 'R4', status: 'completed' });
    assert.deepStrictEqual(e.results().map((m) => m.call_id), ['A']);
    e.advance(20000);
    assert.deepStrictEqual(e.results().map((m) => m.call_id), ['A'], 'force flush must not resurrect dropped calls');
  }

  // -------------------------------------------------------------------------
  // 3. safety flushes: 2.5 s after speech stopped, 6 s per item
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.say('user', 'Talking over the agent.');
    e.ev('input.speech.started');
    e.call('extract_brand_brain', args('icp', 'budget', '5000 a month'), 'S1');
    await e.api.chain();
    e.ev('input.speech.stopped');               // no reply.started follows
    e.advance(2499);
    assert.strictEqual(e.results().length, 0, 'not yet at 2499 ms');
    e.advance(1);
    assert.strictEqual(e.results().length, 1, 'flushed 2.5 s after the founder stopped');
    assert.strictEqual(e.results()[0].call_id, 'S1');

    // a reply.started cancels the 2.5 s net
    const e2 = makeEnv();
    e2.say('user', 'x');
    e2.ev('input.speech.started');
    e2.call('extract_brand_brain', args('icp', 'budget', '5000'), 'S2');
    await e2.api.chain();
    e2.ev('input.speech.stopped');
    e2.ev('reply.started', { reply_id: 'R1' });
    e2.advance(2500);
    assert.strictEqual(e2.results().length, 0, 'reply.started cancelled the 2.5 s flush');
    // ... and the 6 s per-item net still catches a lost reply.done
    e2.advance(3499);
    assert.strictEqual(e2.results().length, 0, 'not yet at 5999 ms after enqueue');
    e2.advance(1);
    assert.strictEqual(e2.results().length, 1, 'force-flushed 6 s after it was enqueued');
    assert.strictEqual(e2.results()[0].call_id, 'S2');
    assert.ok(e2.logs.some((l) => /force flush/.test(l)));
  }

  // -------------------------------------------------------------------------
  // 4. stall watchdog ("Hello?")
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.say('user', 'I sell interpreting to clinics.');
    e.ev('input.speech.started');
    e.ev('input.speech.stopped');
    e.ev('transcript.user', { text: 'I sell interpreting to clinics.' });
    e.ev('reply.started', { reply_id: 'R1' });
    e.ev('reply.done', { reply_id: 'R1', status: 'completed' });   // silent reply, no audio
    e.advance(6999);
    assert.strictEqual(e.creates().length, 0);
    e.advance(1);
    assert.strictEqual(e.creates().length, 1, 'nudged after 7 s of silence');
    const first = e.creates()[0];
    assert.ok(/^Ask ONE short question about/.test(first.instructions), first.instructions);
    assert.ok(/Keep it to one or two short sentences\.$/.test(first.instructions), first.instructions);
    assert.ok(e.logs.includes('[Stall] nudged'));
    const nudgeActs = e.acts('info');
    assert.strictEqual(nudgeActs.length, 1);
    assert.strictEqual(nudgeActs[0].text, 'Nudged Brandy to continue');
    e.advance(7000);
    assert.strictEqual(e.creates().length, 2, 'second nudge');
    e.advance(30000);
    assert.strictEqual(e.creates().length, 2, 'at most 2 nudges per founder turn');
    // a new final transcript resets the budget
    e.ev('input.speech.started');
    e.ev('input.speech.stopped');
    e.ev('transcript.user', { text: 'Hello?' });
    e.advance(7000);
    assert.strictEqual(e.creates().length, 3, 'budget reset by a new founder turn');

    // reply.audio cancels the watchdog
    const e2 = makeEnv();
    e2.say('user', 'x');
    e2.ev('transcript.user', { text: 'x' });
    e2.ev('reply.started', { reply_id: 'R1' });
    e2.ev('reply.audio', { data: 'AAAA' });
    e2.ev('reply.done', { reply_id: 'R1', status: 'completed' });
    e2.advance(20000);
    assert.strictEqual(e2.creates().length, 0, 'no nudge once the agent spoke');

    // a final transcript that lands AFTER the reply audio must not arm a false alarm
    const e3 = makeEnv();
    e3.say('user', 'x');
    e3.ev('input.speech.started');
    e3.ev('input.speech.stopped');
    e3.ev('reply.started', { reply_id: 'R1' });
    e3.ev('reply.audio', { data: 'AAAA' });
    e3.ev('reply.done', { reply_id: 'R1', status: 'completed' });
    e3.ev('transcript.user', { text: 'late transcript' });
    e3.advance(20000);
    assert.strictEqual(e3.creates().length, 0, 'late transcript.user after audio is not a stall');

    // not while a tool is in flight
    const e4 = makeEnv();
    e4.say('user', 'I have no sales yet.');
    e4.ev('transcript.user', { text: 'I have no sales yet.' });
    e4.call('extract_brand_brain', args('diagnostico', 'symptom', 'no sales'), 't1');
    assert.strictEqual(e4.api.state().toolsInFlight, 1);
    e4.advance(7000);                      // watchdog fires while the tool has not answered
    assert.strictEqual(e4.creates().length, 0, 'no nudge while a tool is in flight');
    await e4.api.chain();
    assert.strictEqual(e4.api.state().toolsInFlight, 0);

    // not while audio is playing
    const e5 = makeEnv();
    e5.say('user', 'x');
    e5.ev('transcript.user', { text: 'x' });
    e5.ctx.activeSources.push({});
    e5.advance(7000);
    assert.strictEqual(e5.creates().length, 0, 'no nudge while audio is playing');

    // pending results are force-flushed by the watchdog instead of nudging
    const e6 = makeEnv();
    e6.say('user', 'x');
    e6.ev('reply.started', { reply_id: 'R1' });
    e6.call('extract_brand_brain', args('icp', 'budget', '5000'), 'p1');
    await e6.api.chain();
    e6.ev('transcript.user', { text: 'x' });
    e6.advance(6000);                      // the per-item 6 s net fires first
    assert.strictEqual(e6.results().length, 1);
    assert.strictEqual(e6.creates().length, 0);
  }

  // -------------------------------------------------------------------------
  // 5. tool argument resolution (no enum in the schema)
  // -------------------------------------------------------------------------
  {
    const tools = agent.BRAIN_INTERVIEW_TOOLS;
    assert.deepStrictEqual(tools.map((t) => t.name), ['extract_brand_brain', 'confirm_brand_section']);
    tools.forEach((t) => {
      assert.strictEqual(t.execution_mode, 'interactive');
      assert.strictEqual(t.timeout_seconds, 20);
      Object.keys(t.parameters.properties).forEach((k) => {
        assert.strictEqual(t.parameters.properties[k].type, 'string');
        assert.strictEqual(t.parameters.properties[k].enum, undefined, k + ' must not carry an enum');
        assert.ok(t.parameters.properties[k].description.length > 10);
      });
    });
    assert.deepStrictEqual(tools[0].parameters.required, ['section', 'field', 'value']);
    assert.deepStrictEqual(tools[1].parameters.required, ['section']);
    assert.ok(/Where you stand/.test(tools[0].parameters.properties.section.description));

    const e = makeEnv();
    e.say('user', 'Here are the facts.');
    e.ev('reply.done', { reply_id: 'R0', status: 'completed' });   // lastEvent = reply.done: answers go out at once
    const runs = [
      ['diagnostico', 'diagnostico.symptom', 'via alias'],
      ['diagnostico', 'symptom', 'via suffix'],
      ['diagnostico', 'sintoma_diagnostico', 'via backend key'],
      ['Where you stand', 'stage', 'via English label'],
      ['', 'icp.budget', 'via section.field, no section'],
      ['icp', 'icp.company_size', 'via section.field with section'],
      ['The ICP', 'who signs', 'via token overlap'],
    ];
    for (let i = 0; i < runs.length; i++) {
      e.call('extract_brand_brain', args(runs[i][0], runs[i][1], runs[i][2]), 'r' + i);
      await e.api.chain();
      const res = e.resultOf('r' + i);
      assert.strictEqual(res.success, true, JSON.stringify(runs[i]) + ' -> ' + JSON.stringify(res));
    }
    assert.strictEqual(e.resultOf('r0').saved, 'diagnostico.symptom');
    assert.strictEqual(e.resultOf('r2').saved, 'diagnostico.symptom');
    assert.strictEqual(e.resultOf('r3').saved, 'diagnostico.stage');
    assert.strictEqual(e.resultOf('r4').saved, 'icp.budget');
    assert.strictEqual(e.resultOf('r5').saved, 'icp.company_size');
    assert.strictEqual(e.resultOf('r6').saved, 'icp.decision_maker');
    await e.api.persist();
    const diag = e.store.diagnostico.content;
    assert.strictEqual(diag.sintoma_diagnostico, 'via backend key', 'later value of the same field wins');
    assert.strictEqual(diag.etapa, 'via English label');

    // unknown field: names the field, the section and the valid fields
    e.call('extract_brand_brain', args('diagnostico', 'bogus', 'x'), 'bad1');
    await e.api.chain();
    const bad = e.resultOf('bad1');
    assert.strictEqual(bad.success, false);
    assert.ok(/Unknown field "bogus" for section "Where you stand"\. Valid fields: stage, ramiro_level, symptom, skill_to_unlock, prohibition, stance, stance_reason\. Pick one and call again\./.test(bad.error), bad.error);
    assert.strictEqual(e.results().filter((m) => m.call_id === 'bad1')[0].is_error, true);
    // unknown section
    e.call('extract_brand_brain', args('nowhere', 'bogus', 'x'), 'bad2');
    await e.api.chain();
    const bad2 = e.resultOf('bad2');
    assert.strictEqual(bad2.success, false);
    assert.ok(/Unknown section "nowhere"/.test(bad2.error) && /diagnostico \(Where you stand\)/.test(bad2.error), bad2.error);
    // confirm with an unknown section
    e.call('confirm_brand_section', { section: 'zzz' }, 'bad3');
    await e.api.chain();
    assert.strictEqual(e.resultOf('bad3').success, false);
    // ambiguity is not guessed: "proof" exists as a full name in contrarian only, but "problem" alone
    // with a wrong explicit section must not jump sections
    e.call('extract_brand_brain', args('icp', 'problem', 'x'), 'bad4');
    await e.api.chain();
    assert.strictEqual(e.resultOf('bad4').success, false, 'a known section is never overridden by a guess');
    assert.strictEqual(e.api.pending.length, 0);

    // pure resolvers
    assert.strictEqual(agent.resolveBrainSection('Brand Journey'), 'brand_journey');
    assert.strictEqual(agent.resolveBrainSection('brand_journey'), 'brand_journey');
    assert.strictEqual(agent.resolveBrainSection('the   POND'), 'charco');
    assert.strictEqual(agent.resolveBrainSection('Identity map'), 'identidad');
    assert.strictEqual(agent.resolveBrainSection('The lead magnet'), 'lead_magnet');
    assert.strictEqual(agent.resolveBrainSection('Contrarian stance'), 'contrarian');
    assert.strictEqual(agent.resolveBrainSection('Associations'), 'asociaciones');
    assert.strictEqual(agent.resolveBrainSection('The offer'), 'oferta');
    assert.strictEqual(agent.resolveBrainSection('nothing'), null);
    assert.strictEqual(agent.resolveBrainField('icp', 'budget').key, 'poder_adquisitivo');
    assert.strictEqual(agent.resolveBrainField(null, 'colors').alias, 'identidad.colors');
    assert.strictEqual(agent.resolveBrainField('icp', 'level'), null);
    assert.strictEqual(agent.resolveBrainField('diagnostico', 'level').key, 'nivel_ramiro', 'token overlap inside the given section');
    assert.strictEqual(agent.resolveBrainField(null, 'level').alias, 'charco.level', 'exact name unique across sections beats overlap');
    // every one of the 43 fields resolves from alias, suffix and backend key
    agent.BRAIN_FIELDS.forEach((f) => {
      assert.strictEqual(agent.resolveBrainField(f.section, f.alias), f, f.alias);
      assert.strictEqual(agent.resolveBrainField(f.section, f.name), f, f.name);
      assert.strictEqual(agent.resolveBrainField(f.section, f.key), f, f.key);
      assert.strictEqual(agent.resolveBrainField(null, f.alias), f, 'no section ' + f.alias);
    });
  }

  // -------------------------------------------------------------------------
  // 6. optimistic save: tool.result goes out before the POST resolves
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    let release;
    e.gate = new Promise((r) => { release = r; });
    e.say('user', 'I do not have any sales yet.');
    e.ev('reply.done', { reply_id: 'R0', status: 'completed' });
    e.call('extract_brand_brain', args('diagnostico', 'symptom', 'no sales yet'), 'o1');
    await e.api.chain();
    await sleepTick();
    assert.strictEqual(e.results().length, 1, 'tool.result sent while the POST is still pending');
    assert.strictEqual(e.posts.length, 1, 'the POST was started in the background');
    assert.strictEqual(e.resultOf('o1').success, true);
    // it is on screen before the server answers
    assert.strictEqual(e.renders.length, 1);
    const shown = e.renders[0].filter((s) => s.id === 'diagnostico')[0];
    assert.strictEqual(shown.content.sintoma_diagnostico, 'no sales yet');
    assert.strictEqual(shown.status, 'propuesto');
    // a second save while the first POST is in flight is queued behind it (serialized)
    e.call('extract_brand_brain', args('diagnostico', 'stage', 'not monetizing'), 'o2');
    await e.api.chain();
    await sleepTick();
    assert.strictEqual(e.posts.length, 1, 'POSTs are serialized in one chain');
    assert.strictEqual(e.results().length, 2);
    release();
    await e.api.persist();
    assert.strictEqual(e.posts.length, 2);
    assert.strictEqual(e.posts[1].tool_result.sections[0].content.etapa, 'not monetizing');
    assert.strictEqual(e.posts[1].tool_result.sections[0].content.sintoma_diagnostico, 'no sales yet', 'whole accumulated content is re-posted');
    assert.strictEqual(e.posts[0].tool_result.sections[0].citation_text, 'I do not have any sales yet.', 'citation is the literal last utterance');
    assert.strictEqual(e.ctx.cachedBrain.sections.length, 1, 'server response updates cachedBrain');

    // persist failure: logged, activity error, next save re-posts everything
    const f = makeEnv();
    f.failFetch = true;
    f.say('user', 'Some words.');
    f.ev('reply.done', { reply_id: 'R0', status: 'completed' });
    f.call('extract_brand_brain', args('icp', 'budget', '5000'), 'f1');
    await f.api.chain();
    await f.api.persist();
    assert.strictEqual(f.resultOf('f1').success, true, 'the tool still succeeded');
    assert.ok(f.errors.some((l) => /save failed/.test(l)));
    const err = f.acts('error')[0];
    assert.ok(err && err.state === 'failed', JSON.stringify(f.activity));
    f.failFetch = false;
    f.call('extract_brand_brain', args('icp', 'company_size', 'small clinics'), 'f2');
    await f.api.chain();
    await f.api.persist();
    const lastPost = f.posts[f.posts.length - 1].tool_result.sections[0];
    assert.strictEqual(lastPost.content.poder_adquisitivo, '5000');
    assert.strictEqual(lastPost.content.tamano_empresa, 'small clinics');
  }

  // -------------------------------------------------------------------------
  // 7. confirm invariants + local confirmed set
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.ev('reply.done', { reply_id: 'R0', status: 'completed' });
    e.say('user', 'Everything about my stage.');
    const diag = agent.BRAIN_FIELDS.filter((f) => f.section === 'diagnostico');
    for (const f of diag.slice(0, 3)) {
      e.call('extract_brand_brain', args('diagnostico', f.name, 'v-' + f.name), 'x-' + f.name);
      await e.api.chain();
    }
    e.say('user', 'Yes, that is right.');
    e.call('confirm_brand_section', { section: 'Where you stand' }, 'k1');
    await e.api.chain();
    assert.strictEqual(e.resultOf('k1').success, false, 'incomplete section cannot be confirmed');
    assert.ok(/not complete yet/.test(e.resultOf('k1').error));
    for (const f of diag.slice(3)) {
      e.call('extract_brand_brain', args('diagnostico', f.name, 'v-' + f.name), 'x-' + f.name);
      await e.api.chain();
    }
    e.say('user', 'Hmm, let me think.');
    e.call('confirm_brand_section', { section: 'diagnostico' }, 'k2');
    await e.api.chain();
    assert.ok(/explicit yes/.test(e.resultOf('k2').error));
    assert.strictEqual(e.api.confirmed.has('diagnostico'), false);
    e.say('user', "Yes, that's right.");
    e.call('confirm_brand_section', { section: 'diagnostico' }, 'k3');
    await e.api.chain();
    assert.strictEqual(e.resultOf('k3').success, true);
    assert.strictEqual(e.api.confirmed.has('diagnostico'), true, 'locked locally at once, before the POST');
    // locked right away: the next save to that section is refused even before the server answers
    e.call('extract_brand_brain', args('diagnostico', 'stage', 'changed'), 'k4');
    await e.api.chain();
    assert.strictEqual(e.resultOf('k4').success, false);
    assert.ok(/locked/.test(e.resultOf('k4').error));
    await e.api.persist();
    assert.strictEqual(e.store.diagnostico.status, 'confirmado');
    assert.strictEqual(e.store.diagnostico.citation_text, "Yes, that's right.");
    assert.notStrictEqual(e.store.diagnostico.content.etapa, 'changed');
  }

  // -------------------------------------------------------------------------
  // 8. activity events (brandy:activity contract)
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    e.ev('reply.done', { reply_id: 'R0', status: 'completed' });
    e.say('user', 'I have no sales yet.');
    e.ev('input.speech.started');
    e.ev('input.speech.stopped');
    assert.strictEqual(e.ctx.orbState.textContent, 'Thinking…');
    let a = e.activity[0];
    assert.deepStrictEqual(Object.keys(a).sort(), ['at', 'id', 'kind', 'state', 'text']);
    assert.strictEqual(a.id, 'turn-1');
    assert.strictEqual(a.kind, 'thinking');
    assert.strictEqual(a.state, 'active');
    assert.strictEqual(a.text, 'Thinking…');
    assert.strictEqual(typeof a.at, 'number');
    e.ev('input.speech.stopped');   // a second stop of the same turn does not open another row
    assert.strictEqual(e.acts('thinking').length, 1);
    e.advance(1400);
    e.ev('reply.started', { reply_id: 'R1' });
    e.ev('reply.audio', { data: 'AAAA' });
    assert.strictEqual(e.ctx.orbState.textContent, 'Brandy speaking…');
    const th = e.acts('thinking');
    assert.strictEqual(th.length, 2);
    assert.strictEqual(th[1].id, 'turn-1');
    assert.strictEqual(th[1].state, 'done');
    assert.strictEqual(th[1].text, 'Thought for 1.4 s');
    e.ev('reply.audio', { data: 'BBBB' });
    assert.strictEqual(e.acts('thinking').length, 2, 'only the first audio closes the row');
    e.ev('reply.done', { reply_id: 'R1', status: 'completed' });
    assert.strictEqual(e.ctx.orbState.textContent, 'Listening...');

    // working -> saved (same id)
    e.call('extract_brand_brain', args('diagnostico', 'symptom', 'no sales yet'), 'w1');
    assert.strictEqual(e.ctx.orbState.textContent, 'Working: saving symptom');
    const working = e.activity.filter((x) => x.id === 'tool-w1');
    assert.strictEqual(working.length, 1);
    assert.strictEqual(working[0].kind, 'working');
    assert.strictEqual(working[0].state, 'active');
    assert.strictEqual(working[0].text, 'Saving symptom → Where you stand');
    await e.api.chain();
    const rows = e.activity.filter((x) => x.id === 'tool-w1');
    assert.strictEqual(rows.length, 2);
    assert.strictEqual(rows[1].kind, 'saved');
    assert.strictEqual(rows[1].state, 'done');
    assert.strictEqual(rows[1].text, 'Saved symptom: "no sales yet" · Where you stand 1/7');

    // refused confirm -> clarifying with "Needs: ..."
    e.call('confirm_brand_section', { section: 'diagnostico' }, 'w2');
    await e.api.chain();
    const refused = e.activity.filter((x) => x.id === 'tool-w2').pop();
    assert.strictEqual(refused.kind, 'clarifying');
    assert.strictEqual(refused.state, 'done');
    assert.ok(/^Needs: /.test(refused.text), refused.text);
    // unknown field -> clarifying
    e.call('extract_brand_brain', args('diagnostico', 'bogus', 'x'), 'w3');
    await e.api.chain();
    assert.strictEqual(e.activity.filter((x) => x.id === 'tool-w3').pop().kind, 'clarifying');

    // confirm ok -> decision
    const diag = agent.BRAIN_FIELDS.filter((f) => f.section === 'diagnostico' && f.name !== 'symptom');
    for (const f of diag) {
      e.call('extract_brand_brain', args('diagnostico', f.name, 'v'), 'z-' + f.name);
      await e.api.chain();
    }
    e.say('user', 'Yes, exactly.');
    e.call('confirm_brand_section', { section: 'diagnostico' }, 'w4');
    assert.strictEqual(e.ctx.orbState.textContent, 'Working: locking Where you stand');
    await e.api.chain();
    const dec = e.activity.filter((x) => x.id === 'tool-w4').pop();
    assert.strictEqual(dec.kind, 'decision');
    assert.strictEqual(dec.state, 'done');
    assert.strictEqual(dec.text, 'Locked "Where you stand" with your yes');

    // clarifying question from the founder
    e.ev('transcript.user', { text: 'What do you mean by a symptom?' });
    e.ev('transcript.user', { text: 'Can you explain that' });
    e.ev('transcript.user', { text: 'We sell interpreting.' });
    const cl = e.activity.filter((x) => /^clarify-/.test(x.id));
    assert.strictEqual(cl.length, 2);
    assert.strictEqual(cl[0].kind, 'clarifying');
    assert.strictEqual(cl[0].state, 'done');
    assert.strictEqual(cl[0].text, 'Clarifying your question');
    // the payload the model reads must not leak the internal activity
    assert.strictEqual(Object.keys(e.resultOf('w4')).indexOf('_activity'), -1);
    // every activity has the contract shape
    e.activity.forEach((x) => {
      assert.strictEqual(typeof x.id, 'string');
      assert.ok(['thinking', 'working', 'saved', 'decision', 'clarifying', 'error', 'info'].indexOf(x.kind) !== -1, x.kind);
      assert.ok(['active', 'done', 'failed'].indexOf(x.state) !== -1, x.state);
      assert.strictEqual(typeof x.text, 'string');
      assert.strictEqual(typeof x.at, 'number');
    });
  }

  // -------------------------------------------------------------------------
  // 9. resume greeting via reply.create
  // -------------------------------------------------------------------------
  {
    const fresh = makeEnv();
    fresh.ev('session.ready', { session_id: 's' });
    assert.strictEqual(fresh.creates().length, 0, 'first-time founder gets the normal greeting, not reply.create');

    const back = makeEnv();
    back.ctx.cachedBrain = { sections: [{ id: 'diagnostico', status: 'propuesto', content: { etapa: 'x' } }] };
    back.ev('session.ready', { session_id: 's' });
    assert.strictEqual(back.creates().length, 1);
    assert.ok(/^The founder is back\. Welcome them back in one short sentence, then Ask ONE short question about/.test(back.creates()[0].instructions), back.creates()[0].instructions);
  }

  // -------------------------------------------------------------------------
  // 10. turn detection
  // -------------------------------------------------------------------------
  {
    const e = makeEnv();
    const adaptive = plain(e.api.turn());
    assert.strictEqual('min_silence' in adaptive, false, 'adaptive mode must not send min_silence');
    assert.strictEqual('max_silence' in adaptive, false, 'adaptive mode must not send max_silence');
    assert.deepStrictEqual(adaptive, { vad_threshold: 0.5, interrupt_response: true, interruption_delay: 600 });
    assert.strictEqual(e.logs.filter((l) => /^\[Turn\] mode: adaptive/.test(l)).length, 1);
    e.api.turn();
    assert.strictEqual(e.logs.filter((l) => /^\[Turn\] mode:/.test(l)).length, 1, 'mode is logged once');
    e.ls.brandyTurn = 'fixed';
    const fixed = plain(e.api.turn());
    assert.strictEqual(fixed.min_silence, 1200);
    assert.strictEqual(fixed.max_silence, 3000);
    assert.strictEqual(fixed.interrupt_response, true);
    assert.strictEqual(fixed.interruption_delay, 600);
    e.ls.brandyTurn = 'anything else';
    assert.strictEqual('min_silence' in plain(e.api.turn()), false);
  }

  // -------------------------------------------------------------------------
  // 11. static guards on the real sources
  // -------------------------------------------------------------------------
  {
    const noBlock = src.slice(0, start) + src.slice(end);
    assert.ok(!/TURN_DETECTION_BASELINE/.test(src), 'the fixed baseline is gone');
    assert.ok(!/sendTurnDetectionUpdate/.test(src), 'no code path pushes turn detection updates');
    assert.ok(!/min_silence|max_silence/.test(noBlock), 'min/max_silence only exist inside turnDetectionConfig');
    assert.ok(/turn_detection: turnDetectionConfig\(\)/.test(src));
    assert.ok(!/Say only "One moment\.|say only "One moment\./i.test(src), 'no "say only One moment" instruction in app.js');
    const rule = agent.buildBrainToolRule();
    assert.ok(rule.startsWith('INTERVIEW LOOP'));
    assert.ok(!/say only "One moment/i.test(rule));
    assert.ok(!/One moment/.test(rule), 'the rule must not even mention the old filler (priming)');
    assert.ok(rule.indexOf('[call') === -1, 'no bracketed tool-call example: the voice model reads it out loud');
    assert.ok(/TOOLS ARE SILENT/.test(rule));
    // 4 distinct example phrases from the pool, and they vary between calls
    const exampleList = rule.slice(rule.indexOf('(for example ') + 13, rule.indexOf('), never a generic filler'));
    const used = agent.BRAIN_WORK_PHRASES.filter((p) => exampleList.indexOf('"' + p + '"') !== -1);
    assert.strictEqual(used.length, 4);
    assert.ok(agent.BRAIN_WORK_PHRASES.length >= 12);
    const seen = new Set();
    for (let i = 0; i < 40; i++) seen.add(agent.buildBrainToolRule());
    assert.ok(seen.size > 5, 'the example phrases must be random per session.update');
    // idle orb text
    assert.ok(/orbState\.textContent = 'Tap the mic to talk'/.test(src));
    assert.ok(!/orbState\.textContent = 'Brandy speaking';/.test(src));
  }

  console.log('OK: voice protocol - 11 groups of checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
