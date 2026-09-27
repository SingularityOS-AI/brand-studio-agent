/**
 * Brand Studio Agent -- Agentic Mode Module (Block F, F-05)
 *
 * Step-scoped Brandy: builds step summaries, manages step-specific tools,
 * and sends session.update payloads when Agentic mode is ON.
 *
 * Depends on: actions.js (F-04) for the action registry.
 *
 * This module never touches the DOM directly; it provides pure functions
 * that app.js calls when the step changes or when the Agentic toggle
 * is switched.
 */
(function () {
  'use strict';

  // Step order and dependencies (mirrors pipeline rail in app.js)
  const STEP_ORDER = ['brain', 'catalog', 'script', 'audiovisual', 'editing'];

  // Global tools available in every step
  const GLOBAL_TOOL_NAMES = ['get_status', 'get_balance', 'go_to_step'];

  // Tool definitions for AssemblyAI session.update
  const GLOBAL_TOOLS = [
    {
      type: 'function',
      name: 'get_status',
      description: 'Get current pipeline status: which step you are on, what is complete, what is missing, and what unlocks next.',
      parameters: {
        type: 'object',
        properties: {}
      }
    },
    {
      type: 'function',
      name: 'get_balance',
      description: 'Get the founder\'s current credit balance.',
      parameters: {
        type: 'object',
        properties: {}
      }
    },
    {
      type: 'function',
      name: 'go_to_step',
      description: 'Navigate to a specific pipeline step. Must be unlocked (previous step complete). Returns status if step is locked.',
      parameters: {
        type: 'object',
        properties: {
          step: {
            type: 'string',
            description: 'Step to navigate to: brain, catalog, script, audiovisual, editing'
          }
        },
        required: ['step']
      }
    }
  ];

  // Step-specific tools from the action registry (populated at runtime)
  // Maps step -> Array of tool definitions
  function getStepToolsFromRegistry(step) {
    const root = typeof window !== 'undefined' ? window :
                 typeof globalThis !== 'undefined' ? globalThis : {};
    if (typeof root.BrandStudioActions === 'undefined' ||
        typeof root.BrandStudioActions.list !== 'function') {
      return [];
    }
    const actions = root.BrandStudioActions.list(step);
    return actions.map(function (action) {
      return {
        type: 'function',
        name: action.id,
        description: action.title || action.id,
        parameters: {
          type: 'object',
          properties: {
            // Actions define their own args; we just declare the tool
            args: {
              type: 'object',
              description: 'Arguments for ' + action.id
            }
          }
        }
      };
    });
  }

  // Confirmation engine stubs (F-06 will implement)
  const CONFIRMATION_TOOLS = [
    {
      type: 'function',
      name: 'propose_action',
      description: 'Propose a paid/destructive action to the founder. Returns a token and restatement for confirmation.',
      parameters: {
        type: 'object',
        properties: {
          action: {
            type: 'string',
            description: 'Action ID from the registry'
          },
          args: {
            type: 'object',
            description: 'Arguments for the action'
          }
        },
        required: ['action']
      }
    },
    {
      type: 'function',
      name: 'confirm_action',
      description: 'Confirm a previously proposed action using the token returned by propose_action.',
      parameters: {
        type: 'object',
        properties: {
          token: {
            type: 'string',
            description: 'Confirmation token from propose_action'
          }
        },
        required: ['token']
      }
    }
  ];

  /**
   * Build a step summary (≤1200 chars) for the current step.
   * This is the compact state summary per A-D3/A-D6.
   *
   * @param {string} step - Current step ID
   * @param {Object} ctx - Context object with state data
   * @returns {string} Step summary
   */
  function buildStepSummary(step, ctx) {
    ctx = ctx || {};
    const brainCount = ctx.brainCount || 0;
    const catalogLocked = ctx.catalogLocked || false;
    const scriptLocked = ctx.scriptLocked || false;
    const hasScript = ctx.hasScript || false;
    const avEstimate = ctx.avEstimate || null;
    const balance = ctx.balance || 0;

    let summary = '';

    switch (step) {
      case 'brain':
        summary = 'STEP: Brand Soul. ' + brainCount + ' of 9 sections confirmed. ';
        if (brainCount < 9) {
          summary += 'Keep talking to Brandy to complete all sections. ';
          summary += 'Once complete, you can generate your Brand Soul document (20 credits). ';
        } else {
          summary += 'All sections complete. Generate your Brand Soul document. ';
        }
        summary += 'Next step (Catalog) unlocks after Brand Soul is complete.';
        break;

      case 'catalog':
        summary = 'STEP: Catalog. ';
        if (catalogLocked) {
          summary += 'Catalog is locked. ';
          summary += 'Next: Go to Script to write for any approved idea.';
        } else {
          summary += 'Review ideas: approve (✓), discard (✗), or regenerate (↻). ';
          summary += 'Add your own ideas anytime. Lock when all reviewed.';
        }
        summary += ' Script step unlocks after locking the catalog.';
        break;

      case 'script':
        summary = 'STEP: Script. ';
        if (scriptLocked) {
          summary += 'Script is locked. Ready for Audiovisual.';
        } else if (hasScript) {
          summary += 'Script loaded. Iterate scenes with instructions (2 credits). ';
          summary += 'Edit dictated text free. Lock when satisfied (requires all scenes complete).';
        } else {
          summary += 'No script yet. Pick an approved idea and generate a script (10 credits). ';
          summary += 'Phase-by-phase mode available.';
        }
        break;

      case 'audiovisual':
        summary = 'STEP: Audiovisual. ';
        if (avEstimate) {
          const pending = avEstimate.credits_pending || 0;
          const byType = avEstimate.credits_by_type || {};
          summary += pending + ' credits to generate all. ';
          const costs = Object.entries(byType).map(function (e) {
            return e[0] + ': ' + e[1] + 'c';
          }).join(', ');
          if (costs) summary += 'Per type: ' + costs + '. ';
        }
        summary += 'Change scene types free, generate assets, or regenerate with instructions. ';
        summary += 'Recording studio available per scene.';
        break;

      case 'editing':
        summary = 'STEP: Editing. Build raw timeline, auto-edit with style, manage captions, ';
        summary += 'overlays, music/SFX, face/B-roll, then render final MP4. ';
        summary += 'Render requires confirmation (paid). Export when done.';
        break;

      default:
        summary = 'Unknown step: ' + step;
    }

    summary += ' Balance: ' + balance + ' credits.';
    // Trim to 1200 chars if needed
    if (summary.length > 1200) {
      summary = summary.substring(0, 1197) + '...';
    }
    return summary;
  }

  /**
   * Get the list of unlocked steps based on completion state.
   *
   * @param {Object} ctx - Context with completion state
   * @returns {Array} Array of unlocked step IDs
   */
  function getUnlockedSteps(ctx) {
    ctx = ctx || {};
    const unlocked = ['brain']; // Brain is always unlocked

    if (ctx.brainComplete) unlocked.push('catalog');
    if (ctx.catalogComplete) unlocked.push('script');
    if (ctx.scriptComplete) unlocked.push('audiovisual');
    if (ctx.scriptComplete) unlocked.push('editing'); // Editing requires script

    return unlocked;
  }

  /**
   * Build the tools list for a given step.
   * Includes: global tools + step-specific actions + confirmation stubs + F-07/F-09 schemas.
   *
   * @param {string} step - Current step ID
   * @returns {Array} Array of tool definitions
   */
  function toolsForStep(step) {
    const tools = GLOBAL_TOOLS.slice(); // Copy global tools

    // Add step-specific tools from registry
    const stepTools = getStepToolsFromRegistry(step);
    tools.push.apply(tools, stepTools);

    // Add confirmation engine stubs
    tools.push.apply(tools, CONFIRMATION_TOOLS);

    // Add step specific schemas
    if (step === 'script') {
      tools.push.apply(tools, SCRIPT_TOOL_SCHEMAS);
    } else if (step === 'catalog') {
      tools.push.apply(tools, CATALOG_TOOL_SCHEMAS);
    } else if (step === 'brain') {
      tools.push.apply(tools, SOUL_TOOL_SCHEMAS);
    }

    return tools;
  }

  /**
   * Get the current step from the UI (read from document).
   * Called from outside this module (in app.js).
   *
   * @returns {string|null} Current step or null
   */
  function getCurrentStepFromUI() {
    // Use the pipeline rail's current step
    if (typeof document === 'undefined') return null;
    const rail = document.getElementById('Pipeline-Rail');
    if (!rail) return null;
    const currentBtn = rail.querySelector('.rail-step-btn.is-current');
    if (currentBtn && currentBtn.dataset.step) {
      return currentBtn.dataset.step;
    }
    // Fallback: check which view is open
    const root = typeof window !== 'undefined' ? window : {};
    if (typeof root.currentOpenView !== 'undefined' && root.currentOpenView) {
      return root.currentOpenView;
    }
    return null;
  }

  /**
   * Send a session.update to AssemblyAI with step-scoped tools and summary.
   * This should be called on every step change when Agentic mode is ON.
   *
   * @param {boolean} agenticOn - Whether Agentic mode is enabled
   * @param {string} step - Current step ID
   * @param {Object} ctx - Context object for summary building
   * @param {WebSocket} ws - Active WebSocket connection
   */
  function sendSessionUpdate(agenticOn, step, ctx, ws) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    ctx = ctx || {};
    const root = typeof window !== 'undefined' ? window : {};
    const basePrompt = ctx.basePrompt || root.baseSystemPrompt || '';

    let systemPrompt;
    let tools;

    if (agenticOn) {
      // Agentic mode ON: step-scoped prompt + tools
      const summary = buildStepSummary(step, ctx);
      systemPrompt = basePrompt + '\n\n=== AGENTIC MODE CONTEXT ===\n' +
        'You are in STEP: ' + step + '. Summary: ' + summary + '\n\n' +
        'Only use the tools listed. If asked about another step, give its status ' +
        'and what must happen first; never act on it.';
      tools = toolsForStep(step);
    } else {
      // Agentic mode OFF: legacy prompt (Brand Soul interview only)
      systemPrompt = basePrompt;
      // Only extract_brand_brain tool in legacy mode (existing behavior)
      tools = [
        {
          type: 'function',
          name: 'extract_brand_brain',
          description: 'Extract nine brand sections from our conversation to backend. Return a JSON object with "sections" array. For EACH section: id, citation_text (literal user words), citation_source ("usuario"|"analisis_publico"), confirmed (true only after explicit yes), content dict with section fields. Skip sections without user support. Sections: diagnostico, brand_journey, charco, icp, contrarian, asociaciones, identidad, oferta, lead_magnet.',
          parameters: {
            type: 'object',
            properties: {
              sections: {
                type: 'array',
                description: 'Extracted brand sections, each with id, citation_text, citation_source, confirmed, and content dict',
                items: {
                  type: 'object',
                  properties: {
                    id: {
                      type: 'string',
                      description: 'Section id (one of: diagnostico, brand_journey, charco, icp, contrarian, asociaciones, identidad, oferta, lead_magnet)'
                    },
                    citation_text: {
                      type: 'string',
                      description: 'Exact literal words from the founder that support this section'
                    },
                    citation_source: {
                      type: 'string',
                      enum: ['usuario', 'analisis_publico'],
                      description: 'Source: "usuario" for founder voice transcript, "analisis_publico" for public analysis'
                    },
                    confirmed: {
                      type: 'boolean',
                      description: 'true only after founder explicitly says yes'
                    },
                    content: {
                      type: 'object',
                      description: 'Section content dict with fields specific to each section type'
                    }
                  },
                  required: ['id', 'citation_text', 'citation_source', 'confirmed', 'content']
                }
              }
            },
            required: ['sections']
          }
        }
      ];
    }

    const payload = {
      type: 'session.update',
      session: {
        system_prompt: systemPrompt,
        tools: tools
      }
    };

    ws.send(JSON.stringify(payload));
    console.log('[Agentic Mode] Sent session.update for step:', step, 'Agentic:', agenticOn);
  }

  // Stub handlers for F-06 to fill in
  function handleProposeAction(actionId, args) {
    // Until F-06: return not_available
    return {
      status: 'not_available',
      error: 'Confirmation engine not yet implemented (F-06)'
    };
  }

  function handleConfirmAction(token) {
    // Until F-06: return not_available
    return {
      status: 'not_available',
      error: 'Confirmation engine not yet implemented (F-06)'
    };
  }

  // -------------------------------------------------------------------------
  // F-07: Script tool handlers for voice operation
  // -------------------------------------------------------------------------

  // Valid phases for script_phase_review tool
  const VALID_SCRIPT_PHASES = ['hook', 'lock-in', 'point_1', 'rehook', 'point_2', 'cta'];

  // Maps phase names to scene indices (0-based)
  // Standard script structure: 6 scenes in order
  const PHASE_TO_SCENE_INDEX = {
    'hook': 0,
    'lock-in': 1,
    'point_1': 2,
    'rehook': 3,
    'point_2': 4,
    'cta': 5,
  };

  /**
   * Validates scene_n and returns the adjusted scene index (0-based) or error.
   * @param {number} sceneN - 1-based scene number from the user
   * @param {object} scriptData - The current script data
   * @returns {{ok: true, index: number}|{ok: false, error: string}}
   */
  function validateSceneN(sceneN, scriptData) {
    const totalScenes = scriptData?.scenes?.length || 0;
    if (typeof sceneN !== 'number' || sceneN < 1 || sceneN > totalScenes) {
      return {
        ok: false,
        error: `There is no scene ${sceneN}; your script has ${totalScenes} scenes.`,
      };
    }
    return { ok: true, index: sceneN - 1 };
  }

  /**
   * script_phase_review: Returns phase text + failing rules for that phase (free)
   *
   * Phases: hook, lock-in, point_1, rehook, point_2, cta
   */
  async function scriptPhaseReview(args) {
    const root = typeof window !== 'undefined' ? window : {};
    const bs = root.BrandStudio;
    if (!bs) {
      return { status: 'error', say: 'BrandStudio not ready.' };
    }

    const scriptData = bs.getCurrentScriptData?.();
    if (!scriptData) {
      return { status: 'error', say: 'No script loaded.' };
    }

    const phase = args?.phase;
    if (!phase || !VALID_SCRIPT_PHASES.includes(phase)) {
      return {
        status: 'invalid',
        say: `Invalid phase. Valid phases are: ${VALID_SCRIPT_PHASES.join(', ')}.`,
      };
    }

    const sceneIndex = PHASE_TO_SCENE_INDEX[phase];
    const totalScenes = scriptData.scenes?.length || 0;

    if (sceneIndex >= totalScenes) {
      return {
        status: 'invalid',
        say: `Phase "${phase}" maps to scene ${sceneIndex + 1}, but your script only has ${totalScenes} scenes.`,
      };
    }

    const scene = scriptData.scenes[sceneIndex];
    const audit = scriptData.audit || [];
    // Find failing rules that apply to this scene
    const sceneFailingRules = audit.filter(function (a) {
      if (a.status !== 'fail') return false;
      // Rule applies if scene_n matches or if no specific scene is mentioned (global rule)
      return a.scene_n === sceneIndex + 1 || a.scene_n === undefined || a.scene_n === null;
    });

    // Build failing rule names list
    const ruleNames = sceneFailingRules.map(function (r) { return r.rule; });

    return {
      status: 'done',
      say: `Phase "${phase}" (scene ${sceneIndex + 1}): ${scene?.text || 'No text'}. ${sceneFailingRules.length > 0 ? 'Failing rules: ' + ruleNames.join(', ') + '.' : 'All rules pass for this phase.'}`,
      phase: phase,
      sceneN: sceneIndex + 1,
      text: scene?.text || '',
      failingRules: sceneFailingRules,
    };
  }

  // -------------------------------------------------------------------------
  // F-07: Script tool schemas for AssemblyAI
  // These are added to the step tools when in 'script' step
  // -------------------------------------------------------------------------

  const SCRIPT_TOOL_SCHEMAS = [
    {
      type: 'function',
      name: 'script_generate',
      description: 'Generate the full script from the locked idea. 6 credits. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    },
    {
      type: 'function',
      name: 'script_explain_audit',
      description: 'Explain audit failures in plain language. Returns failing rules. Free.',
      parameters: { type: 'object', properties: {} }
    },
    {
      type: 'function',
      name: 'script_phase_review',
      description: 'Review one phase of the script, returning the phase text and failing audit rules. Free. Valid phases: hook, lock-in, point_1, rehook, point_2, cta.',
      parameters: {
        type: 'object',
        properties: {
          phase: {
            type: 'string',
            description: 'Phase to review: hook, lock-in, point_1, rehook, point_2, or cta',
            enum: ['hook', 'lock-in', 'point_1', 'rehook', 'point_2', 'cta']
          }
        },
        required: ['phase']
      }
    },
    {
      type: 'function',
      name: 'script_iterate_scene',
      description: 'Iterate one scene with your instruction. 2 credits. Requires confirmation.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1
          },
          instruction: {
            type: 'string',
            description: 'Instruction for how to improve the scene'
          }
        },
        required: ['scene_n', 'instruction']
      }
    },
    {
      type: 'function',
      name: 'script_edit_text',
      description: 'Edit scene text directly. I will restate the new text before saving. Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1
          },
          text: {
            type: 'string',
            description: 'New text for the scene'
          }
        },
        required: ['scene_n', 'text']
      }
    },
    {
      type: 'function',
      name: 'script_lock',
      description: 'Lock the script. This cannot be undone without CEO confirmation. Free but requires confirmation.',
      parameters: { type: 'object', properties: {} }
    }
  ];

  /**
   * Returns step tools including Script-specific tools when in script step.
   * Called by toolsForStep for Script step.
   *
   * @param {string} step - Current step ID
   * @returns {Array} Array of tool definitions
   */
  function getScriptStepTools() {
    // Base tools: global + registry actions + confirmation stubs
    const baseTools = [];

    // Add global tools
    baseTools.push.apply(baseTools, GLOBAL_TOOLS);

    // Add step-specific actions from registry
    const stepTools = getStepToolsFromRegistry('script');
    baseTools.push.apply(baseTools, stepTools);

    // Add confirmation stubs
    baseTools.push.apply(baseTools, CONFIRMATION_TOOLS);

    // Add Script voice tools (F-07)
    baseTools.push.apply(baseTools, SCRIPT_TOOL_SCHEMAS);

    return baseTools;
  }

  // -------------------------------------------------------------------------
  // F-09: Catalog + Brand Soul tool schemas and helpers
  // -------------------------------------------------------------------------

  /**
   * Helper to resolve an idea reference (position or keywords) in catalog data.
   * Handles ambiguity: if multiple match or none match, returns status so Brandy asks.
   *
   * @param {string|number} query - Idea reference e.g. "idea 4", "4", "métricas"
   * @param {object} catalogData - Current catalog object with ideas array
   * @returns {{ok: true, idea: object, index: number} | {ok: false, status: string, say: string}}
   */
  function findIdeaInCatalog(query, catalogData) {
    if (!catalogData || !Array.isArray(catalogData.ideas) || catalogData.ideas.length === 0) {
      return { ok: false, status: 'empty', say: 'Catalog is empty.' };
    }
    const ideas = catalogData.ideas;

    if (query === null || query === undefined) {
      return { ok: false, status: 'missing_query', say: 'Please specify which idea.' };
    }

    // 1. Numeric / position query (e.g. "4", 4, "idea 4", "4th idea", "number 4")
    if (typeof query === 'number' || (typeof query === 'string' && /^\d+$/.test(query.trim()))) {
      const num = typeof query === 'number' ? query : parseInt(query.trim(), 10);
      if (num >= 1 && num <= ideas.length) {
        return { ok: true, idea: ideas[num - 1], index: num - 1 };
      }
    }
    if (typeof query === 'string') {
      const posMatch = query.match(/(?:idea|number|no\.?|#)\s*(\d+)/i) || query.match(/(\d+)(?:st|nd|rd|th)\s*idea/i);
      if (posMatch) {
        const num = parseInt(posMatch[1], 10);
        if (num >= 1 && num <= ideas.length) {
          return { ok: true, idea: ideas[num - 1], index: num - 1 };
        }
      }
    }

    // 2. Keyword search in title/description
    if (typeof query === 'string' && query.trim()) {
      const qLower = query.toLowerCase().trim();
      const matches = ideas.filter(function (idea) {
        const title = (idea.title || '').toLowerCase();
        const desc = (idea.description || idea.text || '').toLowerCase();
        return title.includes(qLower) || desc.includes(qLower);
      });

      if (matches.length === 1) {
        const idx = ideas.indexOf(matches[0]);
        return { ok: true, idea: matches[0], index: idx };
      }

      if (matches.length > 1) {
        const choices = matches.slice(0, 3).map(function (m) { return '"' + m.title + '"'; });
        return {
          ok: false,
          status: 'ambiguous',
          say: `Found ${matches.length} matching ideas (${choices.join(', ')}). Which one did you mean?`
        };
      }
    }

    return { ok: false, status: 'not_found', say: `No idea found matching "${query}".` };
  }

  const CATALOG_TOOL_SCHEMAS = [
    {
      type: 'function',
      name: 'catalog_research_demand',
      description: 'Research market demand for catalog ideas. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    },
    {
      type: 'function',
      name: 'catalog_generate_ideas',
      description: 'Generate personalized brand ideas for the catalog. 5 credits. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    },
    {
      type: 'function',
      name: 'catalog_regenerate_idea',
      description: 'Regenerate one catalog idea. 3 credits. Requires confirmation.',
      parameters: {
        type: 'object',
        properties: {
          idea: { type: 'string', description: 'Idea position ("idea 4") or title words' }
        },
        required: ['idea']
      }
    },
    {
      type: 'function',
      name: 'catalog_add_idea',
      description: 'Add a custom idea to the catalog. Free.',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'Title or topic of the custom idea' }
        },
        required: ['text']
      }
    },
    {
      type: 'function',
      name: 'catalog_accept',
      description: 'Accept an idea and select it for scripting. Free.',
      parameters: {
        type: 'object',
        properties: {
          idea: { type: 'string', description: 'Idea position ("idea 4") or title words' }
        },
        required: ['idea']
      }
    },
    {
      type: 'function',
      name: 'catalog_discard',
      description: 'Discard an idea from the catalog. Requires confirmation.',
      parameters: {
        type: 'object',
        properties: {
          idea: { type: 'string', description: 'Idea position ("idea 4") or title words' }
        },
        required: ['idea']
      }
    },
    {
      type: 'function',
      name: 'catalog_explain_demand',
      description: 'Explain demand metrics and validation score for an idea. Free.',
      parameters: {
        type: 'object',
        properties: {
          idea: { type: 'string', description: 'Idea position ("idea 4") or title words' }
        },
        required: ['idea']
      }
    },
    {
      type: 'function',
      name: 'catalog_lock',
      description: 'Lock the catalog selection and proceed to script. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    }
  ];

  const SOUL_TOOL_SCHEMAS = [
    {
      type: 'function',
      name: 'soul_generate',
      description: 'Generate the Brand Soul from confirmed brand brain sections. 20 credits. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    },
    {
      type: 'function',
      name: 'soul_regenerate',
      description: 'Regenerate the Brand Soul document with updated context. 20 credits. Requires confirmation.',
      parameters: { type: 'object', properties: {} }
    }
  ];

  // Public API
  const BrandStudioAgent = {
    buildStepSummary: buildStepSummary,
    getUnlockedSteps: getUnlockedSteps,
    toolsForStep: toolsForStep,
    getCurrentStepFromUI: getCurrentStepFromUI,
    sendSessionUpdate: sendSessionUpdate,
    handleProposeAction: handleProposeAction,
    handleConfirmAction: handleConfirmAction,
    // F-07 Script tools
    VALID_SCRIPT_PHASES: VALID_SCRIPT_PHASES,
    PHASE_TO_SCENE_INDEX: PHASE_TO_SCENE_INDEX,
    validateSceneN: validateSceneN,
    scriptPhaseReview: scriptPhaseReview,
    getScriptStepTools: getScriptStepTools,
    // F-09 Catalog & Soul tools
    findIdeaInCatalog: findIdeaInCatalog,
    CATALOG_TOOL_SCHEMAS: CATALOG_TOOL_SCHEMAS,
    SOUL_TOOL_SCHEMAS: SOUL_TOOL_SCHEMAS,
    // Constants
    STEP_ORDER: STEP_ORDER,
    GLOBAL_TOOL_NAMES: GLOBAL_TOOL_NAMES
  };

  // Export to window
  if (typeof window !== 'undefined') {
    window.BrandStudioAgent = BrandStudioAgent;
  }
  if (typeof self !== 'undefined') {
    self.BrandStudioAgent = BrandStudioAgent;
  }

  // Node.js compatibility for tests
  if (typeof module === 'object' && module.exports) {
    module.exports = BrandStudioAgent;
  }
})();
