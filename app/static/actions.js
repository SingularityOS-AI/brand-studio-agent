/**
 * Brand Studio Agent -- Action Registry (Block F, F-04)
 *
 * Principle 2 (docs/specs/F/spec.md): Brandy calls the exact same functions
 * the buttons call. This file never talks to the network directly for a
 * registered action's `run` -- it wraps the same functions app.js exposes on
 * `window.BrandStudio`, which are the literal button handlers.
 *
 * Loaded BEFORE app.js (see docs/specs/F/pieces/F-04_action_registry.md), so
 * registration below must never read `window.BrandStudio` at top level --
 * only inside a `cost`/`run` closure, which only runs later, once app.js has
 * populated it.
 */
(function () {
  'use strict';

  const registry = new Map();

  function register(actionDef) {
    if (!actionDef || typeof actionDef.id !== 'string' || !actionDef.id) {
      throw new Error('BrandStudioActions.register requires a string id');
    }
    if (typeof actionDef.run !== 'function') {
      throw new Error(`BrandStudioActions.register("${actionDef.id}") requires a run(args) function`);
    }
    registry.set(actionDef.id, actionDef);
  }

  function list(step) {
    const all = Array.from(registry.values());
    if (step === undefined || step === null) return all;
    return all.filter((action) => action.step === step);
  }

  function get(id) {
    return registry.get(id) || null;
  }

  async function resolveCost(action, args) {
    if (typeof action.cost !== 'function') return 0;
    return action.cost(args);
  }

  // Creates the agent_actions row for a voice-originated call (F-02 API),
  // so the backend audit middleware can update it via X-Agent-Action-Id
  // instead of logging a bare button row. Never throws -- an audit failure
  // must not block the action itself (same contract as the middleware).
  async function createVoiceActionRow(action, args, voiceMeta) {
    const bs = window.BrandStudio;
    if (!bs || typeof bs.authenticatedFetch !== 'function') return null;
    try {
      const cost = await resolveCost(action, args);
      const response = await bs.authenticatedFetch('/api/agent/actions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step: action.step,
          action: action.id,
          idea_id: voiceMeta.ideaId != null ? voiceMeta.ideaId : null,
          args: args || {},
          utterance: voiceMeta.utterance != null ? voiceMeta.utterance : null,
          restatement: voiceMeta.restatement != null ? voiceMeta.restatement : null,
          credits: cost != null ? cost : null,
          status: 'queued',
        }),
      });
      if (!response.ok) return null;
      const data = await response.json();
      return data.id || null;
    } catch (err) {
      console.error('[BrandStudioActions] Failed to create audit row:', err);
      return null;
    }
  }

  /**
   * Runs a registered action.
   * - source: 'voice' (default) creates the agent_actions row first, so the
   *   audit middleware attributes the request to it via X-Agent-Action-Id.
   * - voiceMeta: { ideaId, utterance, restatement } forwarded to the row.
   * Returns { ok: true, result } or { ok: false, error }. Never throws.
   */
  async function execute(id, args, options) {
    const opts = options || {};
    const source = opts.source || 'voice';
    const voiceMeta = opts.voiceMeta || {};

    const action = get(id);
    if (!action) {
      return { ok: false, error: `Unknown action: ${id}` };
    }

    let actionRowId = null;
    if (source === 'voice') {
      actionRowId = await createVoiceActionRow(action, args, voiceMeta);
    }

    BrandStudioActions.currentActionId = actionRowId;
    try {
      const result = await action.run(args);
      return { ok: true, result };
    } catch (error) {
      return { ok: false, error: error && error.message ? error.message : String(error) };
    } finally {
      BrandStudioActions.currentActionId = null;
    }
  }

  const BrandStudioActions = {
    // Set only while an action's run(args) is in flight (execute() manages
    // it) -- app.js's authenticatedFetch reads this to send
    // X-Agent-Action-Id, so the audit middleware can attribute the request.
    currentActionId: null,
    register,
    list,
    get,
    execute,
  };

  // ---------------------------------------------------------------------
  // Script actions (buttons: Script-GenerateBtn, scene regenerate, scene
  // text editor, Script-LockBtn, the audit list under the script view).
  // ---------------------------------------------------------------------

  register({
    id: 'script.generate',
    step: 'script',
    title: 'Generate the script',
    needsConfirm: true,
    // F-07: 6 credits for script_generate voice tool
    // ( docs/specs/F/pieces/F-07_script_tools.md )
    cost: () => 6,
    run: () => window.BrandStudio.handleScriptGenerate(),
  });

  register({
    id: 'script.iterate_scene',
    step: 'script',
    title: 'Iterate a scene with an instruction',
    needsConfirm: true,
    // Matches the "Regenerate (2 credits)" label on the scene regenerate
    // control and CREDITS_COST_REGENERATE_SCENE in app/scripting/scripts.py.
    cost: () => 2,
    run: (args) => window.BrandStudio.handleScriptRegenerate(args.sceneIdx, args.instruction),
  });

  register({
    id: 'script.edit_scene_text',
    step: 'script',
    title: 'Edit a scene’s dictated text',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => window.BrandStudio.handleScriptSceneEdit(args.sceneIdx, args.text),
  });

  register({
    id: 'script.lock',
    step: 'script',
    title: 'Lock the script',
    needsConfirm: true,
    cost: () => 0,
    run: () => window.BrandStudio.handleScriptLock(),
  });

  register({
    id: 'script.audit',
    step: 'script',
    title: 'Explain the script audit',
    needsConfirm: false,
    cost: () => 0,
    // Read-only: the audit list is already part of the loaded script data
    // (renderAudit() in app.js reads the same field) -- no button/endpoint
    // to wrap, just the same state the founder sees on screen.
    run: () => {
      const scriptData = window.BrandStudio.getCurrentScriptData();
      return (scriptData && scriptData.audit) || [];
    },
  });

  // F-07: script_phase_review returns phase text + failing rules for that phase
  // This is a free read tool used in the phase-by-phase review flow
  register({
    id: 'script.phase_review',
    step: 'script',
    title: 'Review a script phase',
    needsConfirm: false,
    cost: () => 0,
    // Calls BrandStudioAgent.scriptPhaseReview which returns phase text + failing rules
    run: (args) => {
      if (!window.BrandStudioAgent || typeof window.BrandStudioAgent.scriptPhaseReview !== 'function') {
        return { status: 'error', say: 'BrandStudioAgent not ready.' };
      }
      return window.BrandStudioAgent.scriptPhaseReview(args);
    },
  });

  // ---------------------------------------------------------------------
  // Audiovisual actions (buttons: asset-type selector, AV-GenerateBtn ->
  // AV-ConfirmGenerateBtn, per-scene regenerate, A-roll record button).
  // ---------------------------------------------------------------------

  register({
    id: 'audiovisual.change_scene_type',
    step: 'audiovisual',
    title: 'Change a scene’s asset type',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => {
      const ideaId = args.ideaId || window.BrandStudio.getCurrentScriptIdeaId();
      return window.BrandStudio.changeSceneAssetType(ideaId, args.sceneN, args.assetType);
    },
  });

  register({
    id: 'audiovisual.estimate',
    step: 'audiovisual',
    title: 'Estimate the cost to generate the assets',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => {
      const ideaId = args.ideaId || window.BrandStudio.getCurrentScriptIdeaId();
      return window.BrandStudio.fetchAudiovisualEstimate(ideaId);
    },
  });

  register({
    id: 'audiovisual.generate_all',
    step: 'audiovisual',
    title: 'Generate all pending assets',
    needsConfirm: true,
    // Exact total from the same estimate the "Confirm & Generate" panel
    // shows (docs/specs/F/plan.md A-D7: "each pipeline action at its normal
    // button price").
    cost: async (args) => {
      const ideaId = args.ideaId || window.BrandStudio.getCurrentScriptIdeaId();
      const estimate = await window.BrandStudio.fetchAudiovisualEstimate(ideaId);
      if (!estimate) return null;
      return estimate.credits_pending != null ? estimate.credits_pending : (estimate.credits_total || 0);
    },
    run: (args) => {
      const ideaId = args.ideaId || window.BrandStudio.getCurrentScriptIdeaId();
      return window.BrandStudio.generateAllAudiovisualAssets(ideaId);
    },
  });

  register({
    id: 'audiovisual.regenerate_one',
    step: 'audiovisual',
    title: 'Regenerate one scene’s asset',
    needsConfirm: true,
    // Per-unit cost for the scene's current asset type, from the same
    // credits_by_type map the asset-type selector reads.
    cost: (args) => {
      const scriptData = window.BrandStudio.getCurrentScriptData();
      const estimate = window.BrandStudio.getCurrentAudiovisualEstimate();
      const scene = scriptData && scriptData.scenes
        ? scriptData.scenes.find((s) => s.n === args.sceneN)
        : null;
      const assetType = scene && scene.asset_type;
      const creditsByType = estimate && estimate.credits_by_type;
      if (!assetType || !creditsByType || creditsByType[assetType] == null) return null;
      return creditsByType[assetType];
    },
    run: (args) => window.BrandStudio.triggerRegenerateScene(args.sceneN),
  });

  register({
    id: 'audiovisual.open_recording_studio',
    step: 'audiovisual',
    title: 'Open the recording studio for a scene',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => window.BrandStudio.openRecordingStudio(args.sceneN),
  });

  // ---------------------------------------------------------------------
  // F-09: Brand Soul & Catalog actions
  // ---------------------------------------------------------------------

  register({
    id: 'soul.generate',
    step: 'brain',
    title: 'Generate Brand Soul',
    needsConfirm: true,
    cost: () => 20,
    run: () => window.BrandStudio.generateBrandSoul(),
  });

  register({
    id: 'soul.regenerate',
    step: 'brain',
    title: 'Regenerate Brand Soul',
    needsConfirm: true,
    cost: () => 20,
    run: () => window.BrandStudio.regenerateBrandSoul(),
  });

  register({
    id: 'catalog.research_demand',
    step: 'catalog',
    title: 'Research demand for catalog ideas',
    needsConfirm: true,
    cost: () => 5,
    run: () => window.BrandStudio.researchDemand(),
  });

  register({
    id: 'catalog.generate_ideas',
    step: 'catalog',
    title: 'Generate catalog ideas',
    needsConfirm: true,
    cost: () => 5,
    run: () => window.BrandStudio.generateCatalogIdeas(),
  });

  register({
    id: 'catalog.regenerate_idea',
    step: 'catalog',
    title: 'Regenerate a catalog idea',
    needsConfirm: true,
    cost: () => 3,
    run: (args) => window.BrandStudio.regenerateCatalogIdea(args ? args.idea : null),
  });

  register({
    id: 'catalog.add_idea',
    step: 'catalog',
    title: 'Add a custom idea to catalog',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => window.BrandStudio.addCatalogIdea(args ? args.text : null),
  });

  register({
    id: 'catalog.accept',
    step: 'catalog',
    title: 'Accept an idea for scripting',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => window.BrandStudio.acceptCatalogIdea(args ? args.idea : null),
  });

  register({
    id: 'catalog.discard',
    step: 'catalog',
    title: 'Discard a catalog idea',
    needsConfirm: true,
    cost: () => 0,
    run: (args) => window.BrandStudio.discardCatalogIdea(args ? args.idea : null),
  });

  register({
    id: 'catalog.explain_demand',
    step: 'catalog',
    title: 'Explain demand metrics for an idea',
    needsConfirm: false,
    cost: () => 0,
    run: (args) => window.BrandStudio.explainDemand(args ? args.idea : null),
  });

  register({
    id: 'catalog.lock',
    step: 'catalog',
    title: 'Lock catalog selection',
    needsConfirm: true,
    cost: () => 0,
    run: () => window.BrandStudio.lockCatalog(),
  });

  window.BrandStudioActions = BrandStudioActions;
})();
