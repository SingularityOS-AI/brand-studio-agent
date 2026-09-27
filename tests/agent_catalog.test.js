'use strict';
/**
 * Node harness for F-09 (Catalog & Brand Soul voice tools).
 *
 * Run with: node tests/agent_catalog.test.js
 *
 * Loads the REAL app/static/agent.js and app/static/actions.js to verify:
 * - Catalog and Soul tool schemas are defined correctly
 * - findIdeaInCatalog handles position queries ("idea 4", "4th idea"), titles, and ambiguous queries
 * - Actions registry has soul.generate, soul.regenerate, catalog.* actions
 * - Costs match spec: soul.generate = 20, catalog.generate_ideas = 5, catalog.regenerate_idea = 3
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO_ROOT = path.resolve(__dirname, '..');
const AGENT_JS = path.join(REPO_ROOT, 'app', 'static', 'agent.js');
const ACTIONS_JS = path.join(REPO_ROOT, 'app', 'static', 'actions.js');

function installDomStubs() {
  global.window = {
    location: { search: '', pathname: '/', href: 'http://localhost/' },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  };
  global.localStorage = global.window.localStorage;
  global.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
  };
}

installDomStubs();

// Load modules
require(ACTIONS_JS);
require(AGENT_JS);

const agent = global.window.BrandStudioAgent;
const actions = global.window.BrandStudioActions;

console.log('--- RUNNING F-09 CATALOG & SOUL HARNESS TESTS ---');

// Test 1: Check exports
assert(agent, 'BrandStudioAgent should be defined');
assert(actions, 'BrandStudioActions should be defined');
assert.strictEqual(typeof agent.findIdeaInCatalog, 'function', 'findIdeaInCatalog must be exported');
assert(Array.isArray(agent.CATALOG_TOOL_SCHEMAS), 'CATALOG_TOOL_SCHEMAS must be exported');
assert(Array.isArray(agent.SOUL_TOOL_SCHEMAS), 'SOUL_TOOL_SCHEMAS must be exported');
console.log('✓ Test 1 Passed: Public API exports for F-09 present');

// Test 2: Verify Catalog tool schemas
const requiredCatalogTools = [
  'catalog_research_demand',
  'catalog_generate_ideas',
  'catalog_regenerate_idea',
  'catalog_add_idea',
  'catalog_accept',
  'catalog_discard',
  'catalog_explain_demand',
  'catalog_lock'
];

requiredCatalogTools.forEach((toolName) => {
  const found = agent.CATALOG_TOOL_SCHEMAS.some((t) => t.name === toolName);
  assert(found, `Catalog tool schema missing: ${toolName}`);
});
console.log('✓ Test 2 Passed: CATALOG_TOOL_SCHEMAS contains all 8 required tools');

// Test 3: Verify Soul tool schemas
const requiredSoulTools = ['soul_generate', 'soul_regenerate'];
requiredSoulTools.forEach((toolName) => {
  const found = agent.SOUL_TOOL_SCHEMAS.some((t) => t.name === toolName);
  assert(found, `Soul tool schema missing: ${toolName}`);
});
console.log('✓ Test 3 Passed: SOUL_TOOL_SCHEMAS contains soul_generate and soul_regenerate');

// Test 4: findIdeaInCatalog matching tests
const MOCK_CATALOG = {
  ideas: [
    { id: 'i1', title: 'Top 7 Métricas para Medir la Eficiencia Operativa' },
    { id: 'i2', title: 'Cómo Automatizar el Diagnóstico de la Clínica' },
    { id: 'i3', title: 'Métricas de Reducción de Costos en Salud' },
    { id: 'i4', title: 'Estrategia de Crecimiento para Doctores' },
  ]
};

// 4a. Position query
let res = agent.findIdeaInCatalog(2, MOCK_CATALOG);
assert(res.ok && res.idea.id === 'i2', 'Numeric 2 should find second idea');

res = agent.findIdeaInCatalog('idea 4', MOCK_CATALOG);
assert(res.ok && res.idea.id === 'i4', '"idea 4" should find fourth idea');

res = agent.findIdeaInCatalog('1st idea', MOCK_CATALOG);
assert(res.ok && res.idea.id === 'i1', '"1st idea" should find first idea');

// 4b. Unique title query
res = agent.findIdeaInCatalog('Diagnóstico', MOCK_CATALOG);
assert(res.ok && res.idea.id === 'i2', '"Diagnóstico" should find second idea');

// 4c. Ambiguous query
res = agent.findIdeaInCatalog('Métricas', MOCK_CATALOG);
assert(!res.ok && res.status === 'ambiguous', 'Query matching multiple ideas must return status="ambiguous"');

// 4d. Not found query
res = agent.findIdeaInCatalog('Inexistente XYZ', MOCK_CATALOG);
assert(!res.ok && res.status === 'not_found', 'Query matching nothing must return status="not_found"');
console.log('✓ Test 4 Passed: findIdeaInCatalog handles position, unique title, ambiguous, and not found cases');

// Test 5: Action registry verification for F-09
const f09Actions = [
  { id: 'soul.generate', step: 'brain', cost: 20 },
  { id: 'soul.regenerate', step: 'brain', cost: 20 },
  { id: 'catalog.generate_ideas', step: 'catalog', cost: 5 },
  { id: 'catalog.regenerate_idea', step: 'catalog', cost: 3 },
  { id: 'catalog.add_idea', step: 'catalog', cost: 0 },
  { id: 'catalog.accept', step: 'catalog', cost: 0 },
  { id: 'catalog.discard', step: 'catalog', cost: 0 },
  { id: 'catalog.lock', step: 'catalog', cost: 0 },
];

f09Actions.forEach((act) => {
  const registered = actions.get(act.id);
  assert(registered, `Action ${act.id} should be registered in BrandStudioActions`);
  assert.strictEqual(registered.step, act.step, `Action ${act.id} step should be ${act.step}`);
  if (act.cost !== undefined) {
    assert.strictEqual(registered.cost(), act.cost, `Action ${act.id} cost should be ${act.cost}`);
  }
});
console.log('✓ Test 5 Passed: All Brand Soul and Catalog actions registered in BrandStudioActions with correct costs');

console.log('ALL F-09 NODE HARNESS TESTS PASSED CLEANLY! 🎉');
