'use strict';
/**
 * Node harness test for F-10 (Proactive Job Announcements).
 *
 * Run with: node tests/agent_announce.test.js
 *
 * Loads app/static/agent.js and app/static/production_panel.js to verify:
 * - A job moving from queued/running to done produces exactly one announcement
 * - Announcements are queued in pendingAnnouncements and included in buildStepSummary
 * - Clearing announcements removes them from queue so they are never duplicated
 * - The announcement text format matches "Your <kind> for scene <n> is ready"
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const REPO_ROOT = path.resolve(__dirname, '..');
const AGENT_JS = path.join(REPO_ROOT, 'app', 'static', 'agent.js');
const PANEL_JS = path.join(REPO_ROOT, 'app', 'static', 'production_panel.js');

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
    head: stubEl(),
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
}

function loadModules() {
  installDomStubs();

  const agentCode = fs.readFileSync(AGENT_JS, 'utf8');
  vm.runInThisContext(agentCode, { filename: AGENT_JS });

  const panelCode = fs.readFileSync(PANEL_JS, 'utf8');
  vm.runInThisContext(panelCode, { filename: PANEL_JS });

  return {
    BrandStudioAgent: global.window.BrandStudioAgent,
    BrandStudioPanel: global.window.BrandStudioPanel,
  };
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

async function runTests() {
  const { BrandStudioAgent, BrandStudioPanel } = loadModules();

  // Reset announcements state before testing
  BrandStudioAgent.clearPendingAnnouncements();

  // ---------------------------------------------------------------------------
  // Test: onJobFinished creates formatted announcement
  // ---------------------------------------------------------------------------
  check('onJobFinished creates formatted announcement for scene 5 AI video', () => {
    BrandStudioAgent.clearPendingAnnouncements();
    const job = { id: 'job-105', scene_n: 5, kind: 'ai_video', status: 'done' };
    const text = BrandStudioAgent.onJobFinished(job);
    assert.strictEqual(text, 'Your AI video for scene 5 is ready');

    const pending = BrandStudioAgent.getPendingAnnouncements();
    assert.strictEqual(pending.length, 1);
    assert.strictEqual(pending[0], 'Your AI video for scene 5 is ready');
  });

  // ---------------------------------------------------------------------------
  // Test: buildStepSummary includes pending announcements
  // ---------------------------------------------------------------------------
  check('buildStepSummary includes pending announcements', () => {
    const summary = BrandStudioAgent.buildStepSummary('audiovisual', {
      balance: 50,
      pendingAnnouncements: ['Your AI video for scene 5 is ready'],
    });
    assert.ok(summary.includes('Notifications: Your AI video for scene 5 is ready.'));
  });

  // ---------------------------------------------------------------------------
  // Test: Announcements are not duplicated
  // ---------------------------------------------------------------------------
  check('addAnnouncement prevents duplicate announcements', () => {
    BrandStudioAgent.clearPendingAnnouncements();
    BrandStudioAgent.addAnnouncement('Your stock asset for scene 2 is ready');
    BrandStudioAgent.addAnnouncement('Your stock asset for scene 2 is ready');

    const pending = BrandStudioAgent.getPendingAnnouncements();
    assert.strictEqual(pending.length, 1, 'Should contain exactly 1 announcement, no duplicates');
  });

  // ---------------------------------------------------------------------------
  // Test: clearPendingAnnouncements empties the queue
  // ---------------------------------------------------------------------------
  check('clearPendingAnnouncements empties the queue', () => {
    BrandStudioAgent.addAnnouncement('Test announcement');
    assert.ok(BrandStudioAgent.getPendingAnnouncements().length > 0);

    const cleared = BrandStudioAgent.clearPendingAnnouncements();
    assert.ok(cleared.length > 0);
    assert.strictEqual(BrandStudioAgent.getPendingAnnouncements().length, 0);
  });

  // ---------------------------------------------------------------------------
  // Test: Production Panel job transition detection
  // ---------------------------------------------------------------------------
  check('Production Panel detects job transition from running to done', () => {
    BrandStudioAgent.clearPendingAnnouncements();

    // Mock brandStudio with authenticatedFetch returning done job
    const initialActions = [
      { id: 'act-1', action: 'audiovisual.generate_all', step: 'audiovisual', status: 'running', scene_n: 5, kind: 'ai_video' }
    ];
    const completedActions = [
      { id: 'act-1', action: 'audiovisual.generate_all', step: 'audiovisual', status: 'done', scene_n: 5, kind: 'ai_video' }
    ];

    let fetchCount = 0;
    global.window.BrandStudio = {
      authenticatedFetch: async () => {
        fetchCount++;
        const actions = fetchCount === 1 ? initialActions : completedActions;
        return { ok: true, json: async () => ({ actions: actions }) };
      },
      getCurrentScriptIdeaId: () => 'idea-88',
    };

    // First refresh: loads initial running action
    return BrandStudioPanel.refresh().then(() => {
      assert.strictEqual(BrandStudioAgent.getPendingAnnouncements().length, 0, 'No announcement on initial load of running job');

      // Second refresh: action transitions to done
      return BrandStudioPanel.refresh().then(() => {
        const pending = BrandStudioAgent.getPendingAnnouncements();
        assert.strictEqual(pending.length, 1, 'Job transition to done should produce 1 announcement');
        assert.ok(pending[0].includes('scene 5'), 'Announcement should mention scene 5');
      });
    });
  });

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed.`);
    process.exit(1);
  }
  console.log('\nAll F-10 proactive announcement checks passed.');
}

runTests().catch((err) => {
  console.error('Test runner error:', err);
  process.exit(1);
});
