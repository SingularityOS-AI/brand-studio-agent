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

  // ---------------------------------------------------------------------------
  // Brand Soul interview: 9 sections, 43 fields. The interview is only finished
  // when EVERY field of EVERY section has been said by the founder.
  // [section, backend key, English alias, what to ask about]
  // ---------------------------------------------------------------------------
  const BRAIN_FIELDS = [
    ['diagnostico', 'etapa', 'stage', 'their stage: not started, invisible pro, stuck creator, not monetizing, or authority'],
    ['diagnostico', 'nivel_ramiro', 'ramiro_level', 'their level from 1 (invisible) to 6 (transcendence)'],
    ['diagnostico', 'sintoma_diagnostico', 'symptom', 'an observable symptom that shows where they are stuck'],
    ['diagnostico', 'habilidad_a_desbloquear', 'skill_to_unlock', 'the one skill they most need to unlock'],
    ['diagnostico', 'prohibicion', 'prohibition', 'what they must avoid doing right now'],
    ['diagnostico', 'postura', 'stance', 'expert, student or hypothesis: how they position themselves'],
    ['diagnostico', 'justificacion_postura', 'stance_reason', 'the proof behind that position'],
    ['brand_journey', 'resultado_deseado', 'desired_result', 'the goal that justifies the sacrifice'],
    ['brand_journey', 'de_que_ser_conocido', 'known_for', 'the exact reputation they need'],
    ['brand_journey', 'que_hacer', 'must_do', 'what they have to DO'],
    ['brand_journey', 'que_aprender', 'must_learn', 'what they have to LEARN'],
    ['charco', 'problema', 'problem', 'the problem their prospect suffers every day'],
    ['charco', 'nivel', 'level', 'pond, lake or ocean: how big the audience of that problem is'],
    ['charco', 'logro_que_lo_respalda', 'proof_achievement', 'the achievement that backs them on this problem'],
    ['charco', 'costo_de_no_resolverlo', 'cost_of_inaction', 'what it costs the prospect not to solve it'],
    ['charco', 'intentos_fallidos', 'failed_attempts', 'what the prospect already tried and why it failed'],
    ['icp', 'quien_decide', 'decision_maker', 'the exact job title of the person who signs'],
    ['icp', 'tamano_empresa', 'company_size', 'company size: revenue or headcount'],
    ['icp', 'disparador_de_urgencia', 'urgency_trigger', 'the event that makes them buy now'],
    ['icp', 'poder_adquisitivo', 'budget', 'their real budget'],
    ['icp', 'comite_de_compra', 'buying_committee', 'who else must say yes'],
    ['icp', 'a_quien_le_rinde_cuentas', 'reports_to', 'who the buyer answers to'],
    ['contrarian', 'creencia_comun', 'common_belief', 'the belief in their industry they disagree with'],
    ['contrarian', 'postura_opuesta', 'opposite_stance', 'their opposite belief'],
    ['contrarian', 'prueba', 'proof', 'evidence for their opposite belief'],
    ['contrarian', 'por_que_no_es_provocacion', 'why_not_provocation', 'why it is a helpful belief and not cheap provocation'],
    ['asociaciones', 'deseadas', 'desired', 'associations they want linked to them'],
    ['asociaciones', 'prohibidas', 'forbidden', 'people or reputations they refuse to be linked to'],
    ['identidad', 'voz', 'voice', 'three to five words for their tone'],
    ['identidad', 'colores', 'colors', 'two to four brand colors'],
    ['identidad', 'tipografias', 'fonts', 'one or two typefaces'],
    ['identidad', 'narrativa_de_origen', 'origin_story', 'their personal origin story'],
    ['oferta', 'resultado_sonado', 'dream_result', 'the result their client dreams of'],
    ['oferta', 'probabilidad_percibida', 'perceived_probability', 'proof it works: cases, testimonials, guarantees'],
    ['oferta', 'retraso', 'delay', 'time until the first benefit'],
    ['oferta', 'esfuerzo', 'effort', 'the work left to the client'],
    ['oferta', 'componentes', 'components', 'the specific deliverables, for example 3 emails a week for 90 days'],
    ['oferta', 'garantia', 'guarantee', 'their guarantee, conditional or unconditional'],
    ['lead_magnet', 'tipo', 'type', 'revealing diagnosis, sample, or first step'],
    ['lead_magnet', 'problema_A', 'problem_a', 'the problem it solves for free'],
    ['lead_magnet', 'problema_B_que_revela', 'problem_b', 'the deeper problem it reveals, linked to the paid offer'],
    ['lead_magnet', 'formato', 'format', 'PDF, tool, video or session'],
    ['lead_magnet', 'captura', 'capture', 'how contact data is collected'],
  ].map(function (r) {
    return { section: r[0], key: r[1], alias: r[0] + '.' + r[2], ask: r[3] };
  });
  const BRAIN_SECTION_ORDER = ['diagnostico', 'brand_journey', 'charco', 'icp', 'contrarian', 'asociaciones', 'identidad', 'oferta', 'lead_magnet'];

  // Tool 1: save ONE field. Flat schema with an enum (voice LLMs fail on nested arrays).
  const EXTRACT_BRAND_BRAIN_TOOL = {
    type: 'function',
    name: 'extract_brand_brain',
    description: 'Save ONE fact the founder just said into one brand field and show it on screen. Call it for every concrete fact, one call per field. Say only "One moment." before calling. Do not call it for small talk or questions.',
    parameters: {
      type: 'object',
      properties: {
        field: {
          type: 'string',
          description: 'Which brand field the fact belongs to (section.field).',
          enum: BRAIN_FIELDS.map(function (f) { return f.alias; })
        },
        value: {
          type: 'string',
          description: 'The fact in a short phrase, using the founder own words.',
          examples: ['Medical interpreter for small clinics', 'Practice managers at family clinics', 'Earn 10,000 dollars per month']
        }
      },
      required: ['field', 'value']
    }
  };

  // Tool 2: lock a whole section after an explicit yes (checked again in code).
  const CONFIRM_BRAND_SECTION_TOOL = {
    type: 'function',
    name: 'confirm_brand_section',
    description: 'Lock one brand section after the founder said an explicit yes to your one-sentence summary of it. Say only "One moment." before calling. Never call it without a yes.',
    parameters: {
      type: 'object',
      properties: {
        section: {
          type: 'string',
          description: 'The section the founder just confirmed.',
          enum: BRAIN_SECTION_ORDER
        }
      },
      required: ['section']
    }
  };
  const BRAIN_INTERVIEW_TOOLS = [EXTRACT_BRAND_BRAIN_TOOL, CONFIRM_BRAND_SECTION_TOOL];

  // Front-loaded (voice prompts: long prompts dilute attention). The loop below is
  // what keeps Brandy from going silent or repeating a question: she speaks BEFORE
  // the tool ("One moment."), and asks the next question AFTER the tool result.
  const BRAIN_TOOL_RULE = 'INTERVIEW LOOP, follow it exactly. 1) The founder answers. 2) You say only "One moment." and call extract_brand_brain once per fact, one field per call. Never ask a question in that same turn. 3) The tool result tells you what to ask next: ask exactly that, one short question. 4) When the result says a section is complete, summarize it in one sentence and ask "Is that right?". On an explicit yes, say only "One moment." and call confirm_brand_section. Never repeat a question you already asked. Example. Founder: "I sell medical interpretation to small clinics." You: "One moment." [call extract_brand_brain field=icp.company_size value="small clinics"]. Then ask what the result says.';

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

    const anns = ctx.pendingAnnouncements || (typeof getPendingAnnouncements === 'function' ? getPendingAnnouncements() : []);
    if (anns && anns.length > 0) {
      summary += ' Notifications: ' + anns.join('. ') + '.';
    }

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
   * Includes: global tools + step-specific actions + confirmation stubs + F-07/F-08/F-09 schemas.
   *
   * @param {string} step - Current step ID
   * @returns {Array} Array of tool definitions
   */
  function toolsForStep(step) {
    // Brain step = the voice interview. The other agentic tools are not wired to
    // tool.call yet (each unanswered call froze the agent), so only the two
    // interview tools are offered here.
    if (step === 'brain') return BRAIN_INTERVIEW_TOOLS.slice();

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
    } else if (step === 'audiovisual') {
      tools.push.apply(tools, AUDIOVISUAL_TOOL_SCHEMAS);
    } else if (step === 'editing') {
      tools.push.apply(tools, EDIT_ACTION_SCHEMAS);
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
      systemPrompt = (step === 'brain' ? BRAIN_TOOL_RULE + '\n\n' : '') + basePrompt + '\n\n=== AGENTIC MODE CONTEXT ===\n' +
        'You are in STEP: ' + step + '. Summary: ' + summary + '\n\n' +
        'Only use the tools listed. If asked about another step, give its status ' +
        'and what must happen first; never act on it.';
      tools = toolsForStep(step);
    } else {
      // Agentic mode OFF: legacy prompt (Brand Soul interview only)
      systemPrompt = (step === 'brain' ? BRAIN_TOOL_RULE + '\n\n' : '') + basePrompt;
      // Only extract_brand_brain tool in legacy mode (existing behavior)
      tools = BRAIN_INTERVIEW_TOOLS.slice();
    }

    const payload = {
      type: 'session.update',
      session: Object.assign({}, ctx.extraSession || {}, {
        system_prompt: systemPrompt,
        tools: tools
      })
    };

    ws.send(JSON.stringify(payload));
    console.log('[Agentic Mode] Sent session.update for step:', step, 'Agentic:', agenticOn,
      'tools:', tools.map(function (t) { return t.name; }).join(','));
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

  // -------------------------------------------------------------------------
  // F-08: Audiovisual tool handlers & schemas
  // -------------------------------------------------------------------------

  /**
   * av_read_scene: Read details for a single scene by number (free)
   */
  function avReadScene(args) {
    const root = typeof window !== 'undefined' ? window : {};
    const bs = root.BrandStudio;
    if (!bs) {
      return { status: 'error', say: 'BrandStudio not ready.' };
    }
    const scriptData = bs.getCurrentScriptData?.();
    if (!scriptData) {
      return { status: 'error', say: 'No script loaded.' };
    }
    const sceneN = args?.scene_n || args?.sceneN;
    const val = validateSceneN(sceneN, scriptData);
    if (!val.ok) {
      return { status: 'invalid', say: val.error };
    }
    const scene = scriptData.scenes[val.index];
    const jobs = bs.getCurrentAudiovisualJobs?.() || [];
    const sceneJobs = jobs.filter(function (j) { return j.scene_n === sceneN; });
    const latestJob = sceneJobs.length ? sceneJobs[sceneJobs.length - 1] : null;
    const status = latestJob ? latestJob.status : 'pending';
    const assetType = scene.asset_type || 'a_roll';
    const text = scene.text || scene.spoken_text || 'No text';

    return {
      status: 'done',
      say: `Scene ${sceneN} (${assetType}): "${text}". Asset status: ${status}.`,
      sceneN: sceneN,
      assetType: assetType,
      text: text,
      jobStatus: status,
      job: latestJob,
    };
  }

  const AUDIOVISUAL_TOOL_SCHEMAS = [
    {
      type: 'function',
      name: 'av_read_scene',
      description: 'Read scene audiovisual details (asset type, text, status). Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
        },
        required: ['scene_n'],
      },
    },
    {
      type: 'function',
      name: 'av_set_scene_type',
      description: 'Set asset type for a scene (a_roll, stock, ai_video, motion_graphic). Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
          type: {
            type: 'string',
            description: 'Asset type: a_roll, stock, ai_video, motion_graphic',
            enum: ['a_roll', 'stock', 'ai_video', 'motion_graphic'],
          },
        },
        required: ['scene_n', 'type'],
      },
    },
    {
      type: 'function',
      name: 'av_estimate',
      description: 'Estimate total credits needed to generate all pending assets. Free.',
      parameters: { type: 'object', properties: {} },
    },
    {
      type: 'function',
      name: 'av_generate_all',
      description: 'Generate all pending assets for the script. Cost is total estimate. Requires confirmation.',
      parameters: { type: 'object', properties: {} },
    },
    {
      type: 'function',
      name: 'av_regenerate_asset',
      description: 'Regenerate single scene asset with optional instruction. Cost is per-unit asset price. Requires confirmation.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
          instruction: {
            type: 'string',
            description: 'Optional instruction for regeneration (e.g. someone using a phone)',
          },
        },
        required: ['scene_n'],
      },
    },
    {
      type: 'function',
      name: 'av_open_recording',
      description: 'Open recording studio for a scene. Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
        },
        required: ['scene_n'],
      },
    },
  ];

  // -------------------------------------------------------------------------
  // F-11: Editing Voice Tools
  // -------------------------------------------------------------------------

  const EDIT_ACTION_SCHEMAS = [
    {
      type: 'function',
      name: 'edit_build_raw',
      description: 'Build the raw editing timeline by loading the script and creating the initial IR. Free.',
      parameters: { type: 'object', properties: {} },
    },
    {
      type: 'function',
      name: 'edit_auto_edit',
      description: 'Apply auto-edit style to the entire video (clean, standard, or bold). Free up to 3 restyles (E2-11).',
      parameters: {
        type: 'object',
        properties: {
          style: {
            type: 'string',
            description: 'Video style: clean (minimal), standard (balanced), or bold (energetic)',
            enum: ['clean', 'standard', 'bold'],
          },
        },
        required: ['style'],
      },
    },
    {
      type: 'function',
      name: 'edit_scene_visual',
      description: 'Toggle face appearance or B-roll for a scene, or reset to default. Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
          visual: {
            type: 'string',
            description: 'Visual setting',
            enum: ['face', 'broll', 'reset'],
          },
        },
        required: ['scene_n', 'visual'],
      },
    },
    {
      type: 'function',
      name: 'edit_trim',
      description: 'Adjust scene start and end trim points by millisecond offset. Free.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
          start_ms: {
            type: 'integer',
            description: 'Adjustment in milliseconds (positive = include more of the original)',
          },
          end_ms: {
            type: 'integer',
            description: 'Adjustment in milliseconds (positive = include more of the original)',
          },
        },
        required: ['scene_n'],
      },
    },
    {
      type: 'function',
      name: 'edit_music',
      description: 'Toggle background music for the video. Free.',
      parameters: {
        type: 'object',
        properties: {
          on: {
            type: 'boolean',
            description: 'Music enabled or disabled',
          },
        },
        required: ['on'],
      },
    },
    {
      type: 'function',
      name: 'edit_sfx',
      description: 'Toggle sound effects for the video. Free.',
      parameters: {
        type: 'object',
        properties: {
          on: {
            type: 'boolean',
            description: 'SFX enabled or disabled',
          },
        },
        required: ['on'],
      },
    },
    {
      type: 'function',
      name: 'edit_fix_caption',
      description: 'Fix a caption word by specifying the word and its replacement. Free.',
      parameters: {
        type: 'object',
        properties: {
          word: {
            type: 'string',
            description: 'The caption word to fix (matches word in captions_words state)',
          },
          text: {
            type: 'string',
            description: 'New text for this word',
          },
        },
        required: ['word', 'text'],
      },
    },
    {
      type: 'function',
      name: 'edit_caption_position',
      description: 'Set vertical position for all captions. Free.',
      parameters: {
        type: 'object',
        properties: {
          position: {
            type: 'string',
            description: 'Caption position',
            enum: ['top', 'middle', 'bottom'],
          },
        },
        required: ['position'],
      },
    },
    {
      type: 'function',
      name: 'edit_overlay_delete',
      description: 'Delete an overlay by its 1-based index or overlay_id string. Free.',
      parameters: {
        type: 'object',
        properties: {
          n: {
            type: 'string',
            description: 'Overlay identifier (1-based index number or overlay_id string)',
          },
        },
        required: ['n'],
      },
    },
    {
      type: 'function',
      name: 'edit_overlays',
      description: 'Toggle all overlays visibility on or off. Free.',
      parameters: {
        type: 'object',
        properties: {
          on: {
            type: 'boolean',
            description: 'Overlays enabled or disabled',
          },
        },
        required: ['on'],
      },
    },
    {
      type: 'function',
      name: 'edit_post_copy',
      description: 'Generate social media post copy text from the video content. Free.',
      parameters: { type: 'object', properties: {} },
    },
    {
      type: 'function',
      name: 'edit_share_link',
      description: 'Copy or retrieve the share link for the rendered video. Free.',
      parameters: { type: 'object', properties: {} },
    },
    {
      type: 'function',
      name: 'edit_try_another_take',
      description: 'Generate another visual variation for a scene with different styling. Costs 2 credits. Requires confirmation.',
      parameters: {
        type: 'object',
        properties: {
          scene_n: {
            type: 'integer',
            description: 'Scene number (1-based)',
            minimum: 1,
          },
        },
        required: ['scene_n'],
      },
    },
    {
      type: 'function',
      name: 'edit_render',
      description: 'Render the final video. Cost varies: first render 20 credits, re-render 5 credits, engine update 0 credits. Requires confirmation.',
      parameters: { type: 'object', properties: {} },
    },
  ];

  // -------------------------------------------------------------------------
  // F-10: Proactive Job Announcements (Spike & Fallback)
  // -------------------------------------------------------------------------

  let pendingAnnouncements = [];

  function addAnnouncement(text) {
    if (!text || typeof text !== 'string') return;
    if (pendingAnnouncements.indexOf(text) === -1) {
      pendingAnnouncements.push(text);
    }
  }

  function getPendingAnnouncements() {
    return pendingAnnouncements.slice();
  }

  function clearPendingAnnouncements() {
    const cleared = pendingAnnouncements.slice();
    pendingAnnouncements = [];
    return cleared;
  }

  function onJobFinished(job) {
    if (!job) return null;
    const sceneN = job.scene_n || job.sceneN || (job.input && job.input.scene_n);
    const kind = job.kind || job.asset_type || 'asset';
    let label = 'asset';
    if (kind === 'ai_video') label = 'AI video';
    else if (kind === 'stock') label = 'stock asset';
    else if (kind === 'motion_graphic') label = 'motion graphic';

    const text = sceneN ? `Your ${label} for scene ${sceneN} is ready` : `Your ${label} is ready`;
    addAnnouncement(text);
    return text;
  }

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
    // F-08 Audiovisual tools
    avReadScene: avReadScene,
    AUDIOVISUAL_TOOL_SCHEMAS: AUDIOVISUAL_TOOL_SCHEMAS,
    // F-09 Catalog & Soul tools
    findIdeaInCatalog: findIdeaInCatalog,
    CATALOG_TOOL_SCHEMAS: CATALOG_TOOL_SCHEMAS,
    SOUL_TOOL_SCHEMAS: SOUL_TOOL_SCHEMAS,
    BRAIN_FIELDS: BRAIN_FIELDS,
    BRAIN_SECTION_ORDER: BRAIN_SECTION_ORDER,
    BRAIN_INTERVIEW_TOOLS: BRAIN_INTERVIEW_TOOLS,
    // F-11 Editing tools
    EDIT_ACTION_SCHEMAS: EDIT_ACTION_SCHEMAS,
    // F-10 Proactive announcements
    addAnnouncement: addAnnouncement,
    getPendingAnnouncements: getPendingAnnouncements,
    clearPendingAnnouncements: clearPendingAnnouncements,
    onJobFinished: onJobFinished,
    // Constants
    STEP_ORDER: STEP_ORDER,
    GLOBAL_TOOL_NAMES: GLOBAL_TOOL_NAMES,
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
