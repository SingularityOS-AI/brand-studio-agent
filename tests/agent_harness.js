'use strict';
/**
 * Reusable Node harness for Block F's browser-side agent modules.
 *
 * Voice cannot be unit-tested end to end (docs/specs/F/plan.md #5), so each
 * tool piece drives its real app/static/*.js file from Node instead: this
 * harness supplies the two things every one of those tests needs --
 *   - loadBrowserScript(absPath, context): eval a real browser script (one
 *     written as `(function(){ ...; window.X = ...; })();`, no bundler) in
 *     an isolated vm context instead of the process's own `global`, so
 *     nothing a piece attaches to `window` leaks into another test file.
 *   - createMockFetch(handler): a scriptable `fetch` replacement that
 *     records every call (url, options) so a test can assert the exact
 *     HTTP request a tool call produced, per plan.md #5's "asserts the
 *     exact HTTP calls".
 *   - installDomStubs(context): the minimal `document`/element stand-in
 *     needed for a script that touches the DOM at load time but not for
 *     the assertions under test.
 *
 * F-06 introduces this file (per docs/specs/F/plan.md's F-06 row) so later
 * pieces (F-07 Script tools, F-08 Audiovisual tools, ...) reuse it instead
 * of re-implementing DOM/fetch stubbing in every new Node test.
 */
const fs = require('fs');
const vm = require('vm');

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

function installDomStubs(context) {
  context.document = {
    getElementById: () => stubEl(),
    querySelector: () => stubEl(),
    querySelectorAll: () => [],
    createElement: () => stubEl(),
    addEventListener: () => {},
    removeEventListener: () => {},
    body: stubEl(),
  };
  return context;
}

/**
 * Runs the real script at `absPath` inside `context` (a plain object that
 * becomes the vm's global scope, so `window`/`self` inside the script refer
 * to whatever `context.window`/`context.self` you set before calling this).
 * Returns `context` for chaining.
 */
function loadBrowserScript(absPath, context) {
  context = context || {};
  if (typeof context.console === 'undefined') context.console = console;
  vm.createContext(context);
  const code = fs.readFileSync(absPath, 'utf8');
  vm.runInContext(code, context, { filename: absPath });
  return context;
}

/**
 * A scriptable `fetch`. `handler(url, options, callIndex)` decides the
 * response for each call (defaults to `{ ok: true, json: async () => ({}) }`
 * when `handler` returns undefined). Every call is recorded on `.calls`.
 */
function createMockFetch(handler) {
  const calls = [];
  const fetchFn = async function mockFetch(url, options) {
    const callIndex = calls.length;
    calls.push({ url, options });
    const result = handler ? await handler(url, options, callIndex) : undefined;
    if (result !== undefined) return result;
    return { ok: true, status: 200, json: async () => ({}) };
  };
  fetchFn.calls = calls;
  return fetchFn;
}

module.exports = { stubEl, installDomStubs, loadBrowserScript, createMockFetch };
