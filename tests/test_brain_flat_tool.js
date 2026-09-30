// Flat voice tool {section, fact, confirmed} -> backend format, and tool.result timing.
// Extracts the real source from app.js (same technique as test_silence_watchdog.js).
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'app.js'), 'utf8');
const start = src.indexOf('  let agentReplying = false;');
const end = src.indexOf('  function appendExtractedSections');
assert.ok(start !== -1 && end > start, 'flat tool block not found in app.js');

const sent = [];
const ctx = {
  fullTranscript: [],
  cachedBrain: null,
  WebSocket: { OPEN: 1 },
  ws: { readyState: 1, send: (d) => sent.push(JSON.parse(d)) },
  JSON, String, Object, Array,
};
vm.createContext(ctx);
// `let`/`const` inside vm scripts are not visible on the context object: expose via var wrapper.
vm.runInContext(src.slice(start, end) + `
  var api = { build: buildToolResultFromFlatCall, send: sendToolResult, flush: flushToolResults,
              setReplying: function (v) { agentReplying = v; } };`, ctx);
const api = ctx.api;

// 1. no founder words yet -> error, nothing invented
assert.ok(api.build({ section: 'icp', fact: 'x', confirmed: false }).error);

// 2. proposed keeps the founder's literal last utterance as citation
ctx.fullTranscript.push({ speaker: 'user', text: 'I sell medical interpretation to small clinics.' });
let r = api.build({ section: 'icp', fact: 'small clinics', confirmed: false });
let sec = r.tool_result.sections[0];
assert.strictEqual(sec.id, 'icp');
assert.strictEqual(sec.confirmed, false);
assert.strictEqual(sec.citation_text, 'I sell medical interpretation to small clinics.');
assert.strictEqual(sec.content.quien_decide, 'small clinics');

// 3. confirmed=true WITHOUT an explicit yes in the founder's words is downgraded
r = api.build({ section: 'icp', fact: 'small clinics', confirmed: true });
assert.strictEqual(r.tool_result.sections[0].confirmed, false);

// 4. explicit yes -> confirmed, citation is the yes
ctx.fullTranscript.push({ speaker: 'user', text: "Yes, that's right." });
r = api.build({ section: 'icp', fact: 'small clinics', confirmed: true });
assert.strictEqual(r.tool_result.sections[0].confirmed, true);
assert.strictEqual(r.tool_result.sections[0].citation_text, "Yes, that's right.");

// 5. unknown section rejected
assert.ok(api.build({ section: 'nope', fact: 'x', confirmed: false }).error);

// 6. tool.result is held while the agent is replying and flushed after reply.done
api.setReplying(true);
api.send('c1', { success: true });
assert.strictEqual(sent.length, 0, 'must not send tool.result mid-reply');
api.setReplying(false);
api.flush();
assert.strictEqual(sent.length, 1);
assert.strictEqual(sent[0].type, 'tool.result');
assert.strictEqual(sent[0].call_id, 'c1');
assert.strictEqual(typeof sent[0].result, 'string');

console.log('OK: flat brain tool + tool.result timing — 6 checks passed');
