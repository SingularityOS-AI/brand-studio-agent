/**
 * Brand Studio Agent -- Agentic Mode Module (Block F, F-05)
 */
(function () {
  'use strict';
  const STEP_ORDER = ['brain', 'catalog', 'script', 'audiovisual', 'editing'];
  const GLOBAL_TOOL_NAMES = ['get_status', 'get_balance', 'go_to_step'];
  const GLOBAL_TOOLS = [
    { type: 'function', name: 'get_status', description: 'Get current pipeline status', parameters: { type: 'object', properties: {} } },
    { type: 'function', name: 'get_balance', description: 'Get credits balance', parameters: { type: 'object', properties: {} } },
    { type: 'function', name: 'go_to_step', description: 'Navigate to step', parameters: { type: 'object', properties: { step: { type: 'string' } }, required: ['step'] } }
  ];
  const CONFIRMATION_TOOLS = [
    { type: 'function', name: 'propose_action', description: 'Propose action for confirmation', parameters: { type: 'object', properties: {}, required: ['action'] } },
    { type: 'function', name: 'confirm_action', description: 'Confirm proposed action', parameters: { type: 'object', properties: {}, required: ['token'] } }
  ];
  function buildStepSummary(step, ctx) {
    ctx = ctx || {};
    let summary = 'STEP: ' + step + '. ';
    summary += 'Balance: ' + (ctx.balance || 0) + ' credits.';
    return summary.length > 1200 ? summary.substring(0, 1197) + '...' : summary;
  }
  function getUnlockedSteps(ctx) {
    ctx = ctx || {};
    const unlocked = ['brain'];
    if (ctx.brainComplete) unlocked.push('catalog');
    if (ctx.catalogComplete) unlocked.push('script');
    if (ctx.scriptComplete) { unlocked.push('audiovisual'); unlocked.push('editing'); }
    return unlocked;
  }
  function toolsForStep(step) {
    const tools = GLOBAL_TOOLS.slice();
    tools.push.apply(tools, CONFIRMATION_TOOLS);
    return tools;
  }
  function getCurrentStepFromUI() {
    if (typeof document === 'undefined') return null;
    const rail = document.getElementById('Pipeline-Rail');
    if (!rail) return null;
    const currentBtn = rail.querySelector('.rail-step-btn.is-current');
    if (currentBtn && currentBtn.dataset.step) return currentBtn.dataset.step;
    const root = typeof window !== 'undefined' ? window : {};
    if (root.currentOpenView) return root.currentOpenView;
    return null;
  }
  function sendSessionUpdate(agenticOn, step, ctx, ws) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ctx = ctx || {};
    const root = typeof window !== 'undefined' ? window : {};
    const basePrompt = ctx.basePrompt || root.baseSystemPrompt || '';
    let systemPrompt, tools;
    if (agenticOn) {
      const summary = buildStepSummary(step, ctx);
      systemPrompt = basePrompt + '\n\nAGENTIC MODE: STEP=' + step + ' | ' + summary;
      tools = toolsForStep(step);
    } else {
      systemPrompt = basePrompt;
      tools = [{ type: 'function', name: 'extract_brand_brain', description: 'Extract brand sections', parameters: { type: 'object', properties: { sections: { type: 'array' } }, required: ['sections'] } }];
    }
    ws.send(JSON.stringify({ type: 'session.update', session: { system_prompt: systemPrompt, tools: tools } }));
  }
  function handleProposeAction(actionId, args) { return { status: 'not_available', error: 'F-06' }; }
  function handleConfirmAction(token) { return { status: 'not_available', error: 'F-06' }; }
  const BrandStudioAgent = { buildStepSummary, getUnlockedSteps, toolsForStep, getCurrentStepFromUI, sendSessionUpdate, handleProposeAction, handleConfirmAction, STEP_ORDER, GLOBAL_TOOL_NAMES };
  if (typeof window !== 'undefined') window.BrandStudioAgent = BrandStudioAgent;
  if (typeof module === 'object' && module.exports) module.exports = BrandStudioAgent;
})();
