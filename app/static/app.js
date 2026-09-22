/**
 * Brand Studio Agent — Voice Client with Google OAuth
 *
 * Handles Google OAuth login, JWT authentication, and voice interactions.
 * All API calls require JWT token in Authorization header.
 */
(function() {
  'use strict';

  // JWT Authentication
  let supabase = null;
  let jwtToken = null;
  let user = null;

  // Flag to prevent logout during Stripe checkout return
  let isCheckoutInProgress = false;

  // AssemblyAI Voice Client
  let API_KEY = '';
  let apiKeyRequested = false;

  // API helper with JWT
  async function authenticatedFetch(url, options = {}) {
    if (!jwtToken) {
      throw new Error('Not authenticated');
    }
    options.headers = options.headers || {};
    options.headers['Authorization'] = `Bearer ${jwtToken}`;
    const response = await fetch(url, { ...options, credentials: 'same-origin' });

    // Centralized 402 handling - show paywall
    if (response.status === 402) {
      console.log('[Paywall] 402 response detected, showing paywall');
      showPaywall();
      throw new Error('PAYWALL_402');
    }

    return response;
  }

  // Fetch API key from backend on first interaction
  async function ensureApiKey() {
    if (API_KEY || apiKeyRequested) return API_KEY;
    apiKeyRequested = true;

    try {
      // Token EFIMERO, no la API key maestra. El navegador nunca debe ver la
      // credencial real: quien la vea puede gastar sin tope contra la cuenta.
      const response = await authenticatedFetch('/api/agent-token');
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 401) {
          alert('Authentication required. Please login again.');
          logout();
        } else if (response.status === 429) {
          alert('Too many requests. Please wait a minute.');
        } else {
          alert('Failed to get voice token: ' + (body.detail || response.status));
        }
        apiKeyRequested = false;  // permitir reintento
        return null;
      }
      const data = await response.json();
      API_KEY = data.token;
      console.log('[Voice Client] Temporary token obtained from backend');
      return API_KEY;
    } catch (e) {
      console.error('[Voice Client] Failed to fetch token:', e);
      if (e.message !== 'PAYWALL_402') {
        alert('Could not contact server for voice token.');
      }
      apiKeyRequested = false;
      return null;
    }
  }

  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let workletNode = null;
  let micSource = null;
  let isSessionActive = false;
  let isReady = false;

  // Session generation token to prevent race conditions between concurrent sessions
  let sessionGeneration = 0;

  // Turn detection baseline (ver 06_VOICE_AGENT_API_DOCS.md "Turn detection: recommended
  // defaults"). Se reutiliza aqui y en el patron adaptativo, nunca se copia a mano.
  const TURN_DETECTION_BASELINE = {
    vad_threshold: 0.5,
    min_silence: 1400,
    max_silence: 4000,
    interrupt_response: true
  };
  let waitingForAnswer = false;

  // Voice credits reservation
  let voiceRenewalTimer = null;
  let initialSessionCredits = 500; // Will be fetched from /api/config
  let credits = initialSessionCredits; // Current credits balance (global)

  // Silence auto-suspend (AssemblyAI bills connected time, silence included)
  const SILENCE_SUSPEND_MS = 45000;
  const SILENCE_CHECK_INTERVAL_MS = 5000;
  let lastVoiceActivityAt = 0;
  let silenceWatchdogTimer = null;

  // Audio playback state
  let playT = 0;
  let activeSources = [];
  const RATE = 24000; // AssemblyAI Voice Agent outputs at 24kHz

  // UI elements
  const micBtn = document.getElementById('micBtn');
  const orb = document.querySelector('.orb');
  const orbState = document.querySelector('.orbstate');
  const streamContainer = document.querySelector('.stream');

  // Current partial transcript
  let currentPartialElement = null;

  // Transcript storage for extraction
  let fullTranscript = [];

  // Brand brain cache (durable memory from Supabase)
  let cachedBrain = null;
  let brainFetchInProgress = false;

  // Missing sections tracking for agent guidance
  let missingSections = [];

  // Transcript limits for context window protection
  const MAX_TRANSCRIPT_TURNS = 20;  // Maximum number of recent turns to include
  const MAX_TRANSCRIPT_CHARS = 4000; // Maximum characters for recent transcript

  // Default voice and prompts (can be customized)
  const baseSystemPrompt = `You are Brandy, the Brand Studio Agent. You help entrepreneurs and businesses discover their brand identity through targeted questions about their business.

Speak naturally in short, clear sentences. Be direct and helpful. Keep responses concise - no more than 2-3 sentences unless more detail is needed.

Your goal is to gather information across NINE brand sections. The model is an octagon, not a list — if the founder drops data about section 08 while discussing section 03, note it in section 08. Data said once is never lost by being "out of turn."

THE 9 SECTIONS (in spec order — governs the document, not the conversation):

01 - Where you stand (diagnostico): Founder's HARD triage that governs everything Brandy says afterward.
   • Stage (1-5): 1=not started · 2=invisible pro · 3=stuck creator · 4=not monetizing · 5=authority figure
   • Ramiro level (1-6): 1=invisibility · 2=packaging · 3=bridge · 4=bottleneck · 5=CEO real · 6=transcendence
   • Observable symptom: what you see without asking (e.g. "posts nonstop, 500 views, zero engagement")
   • KEY skill to unlock (ONE thing that matters at that level)
   • What's PROHIBITED (what they must NOT do yet)
   • Posture — THREE VALUES: expert (proven achievement) · student (documenting experiments, never faking expertise) · hypothesis (pure theory without evidence or experiment in progress — most fragile case, frame explicitly)

02 - Brand Journey (brand_journey): THE FOUNDER'S journey, not the customer's.
   • Desired result: what justifies the sacrifice of time, money, and privacy
   • What to be known for: exact reputation needed to achieve it
   • What to DO: to be known for that, what they must DO
   • What to LEARN: to do that, what they must LEARN

03 - The pond (charco): Chosen by real achievements, not ambition.
   • Problem: concrete symptom the prospect falls into daily
   • Level: charco | lago | oceano
   • Achievement that backs you: the receipt giving you the right to speak on this
   • Cost of not resolving: in money, time, or operational wear
   • Failed attempts: what they tried before and why it failed

04 - The ICP (icp): SINGLE ICP required (primary+secondary not accepted).
   • Decision maker: exact job title with signing power
   • Company size: revenue, headcount, or applicable range
   • Urgency trigger: event that makes them buy NOW, not in 6 months
   • Purchasing power: actual budget available
   • Buying committee: who else must say yes (B2B: 30-90 day cycles)
   • Who they report to: who looks good or bad (feeds section 08 result_sonado)

05 - Contrarian stance (contrarian): NOT cheap provocation — honest belief that helps.
   • Common belief: left column, industry-accepted truth you disagree with
   • Opposite stance: right column, your alternative belief
   • Proof: evidence you have of the opposite truth
   • Why not provocation: guardrail. Contrarian = helpful belief. Controversial = cheap attention seeking.

06 - Desired and forbidden associations (asociaciones):
   • Desired: few key associations to pair with per piece
   • Forbidden: people, behaviors, or reputations you DON'T want linked to you
   (Prohibited associations usually deduced from section 05's common belief.)

07 - Identity map (identidad): governs visual packaging.
   • Voice: 3-5 words describing the tone
   • Colors: 2-4 colors
   • Typography: 1-2 fonts
   • Origin narrative: personal story, past defeats, real motivation

08 - The offer (oferta): Value = (Dream Result × Perceived Probability) ÷ (Delay × Effort).
   • Dream result (B2B adaptation): revenue, costs, risk mitigated, OR decision maker's status before their board
   • Perceived probability: validated cases, testimonials, audits, guarantees. B2B buyer risks their job.
   • Delay: time to first benefit. Quick wins in 7-14 days.
   • Effort: how much work remains for the client. "Done For You" justifies up to 5× pricing.
   • Components: specific, not vague (e.g. "3 emails/week for 90 days" not "marketing services").
   • Guarantee: conditional (by result) OR unconditional.

09 - The lead magnet (lead_magnet): Revelation principle — solve Problem A so well it demonstrates authority, and in solving it reveals Problem B (what the paid offer solves).
   • Type: revelador (diagnosis/audit) | muestra (trial/pilot) | primer_paso (template/calculator/checklist)
   • Problem A: what it solves free, complete
   • Problem B that reveals: link to paid offer from section 08
   • Format: PDF, tool, video, session
   • Capture: how data is collected with least friction

CRITICAL RULES (CEO-mandated):

1. CONFIRMED: true ONLY after an EXPLICIT YES from the founder. citation_text must have their exact literal words. If founder says "I don't know" and there's no way to extract it: propose a concrete angle, negotiate until there's agreement, THEN confirm with the citation of where they accepted your proposal. Never leave a section hanging.

2. Call extract_brand_brain AFTER EACH SECTION CLOSED, not once at the end. This is what makes details appear on screen during conversation.

3. SECTIONS OUT OF ORDER: If the founder drops data from section 08 while discussing section 03, note it in section 08. The model is an octagon, not a list. A datum said once is never lost by being said "out of turn."

No gamification. No points, badges, streaks, or celebrations. Be direct and expert.

Always respond in English. Keep your responses conversational and engaging.`;

  const defaultGreeting = "Hello! I'm Brandy, your Brand Studio Agent. I'll help you discover your brand identity through conversation. Tell me what you do and who you do it for.";
  const voice = "alba"; // AssemblyAI voice: alba, anna, charles, estelle, eve, george, giovanni, jane, jean, juergen, lola, mary, michael, paul, rafael, vera

  // Build dynamic system prompt with memory context
  function buildSystemPrompt() {
    let prompt = baseSystemPrompt;
    let hasMemory = false;

    // Add confirmed brand brain sections (durable memory)
    if (cachedBrain && cachedBrain.sections && cachedBrain.sections.length > 0) {
      const confirmedSections = cachedBrain.sections.filter(s => s.status === 'confirmado');
      if (confirmedSections.length > 0) {
        hasMemory = true;
        prompt += '\n\n=== WHAT YOU ALREADY KNOW (confirmed with citations) ===\n';
        confirmedSections.forEach(section => {
          const contentStr = typeof section.content === 'object'
            ? Object.entries(section.content).map(([k, v]) => `${k}: ${v}`).join(', ')
            : section.content || '';
          prompt += `- ${section.id}: ${contentStr}  (user's words: "${section.citation_text || '[no citation]'}")\n`;
        });
        prompt += 'Do NOT ask again about anything in this list. Treat it as established fact.\n';
      }
    }

    // Add recent transcript (ephemeral memory)
    if (fullTranscript.length > 0) {
      hasMemory = true;
      prompt += '\n=== RECENT CONVERSATION ===\n';
      // Get recent turns, respecting both turn and character limits
      let recentTranscript = fullTranscript.slice(-MAX_TRANSCRIPT_TURNS);
      let transcriptText = recentTranscript.map(t => `${t.speaker}: ${t.text}`).join('\n');

      // Trim by character limit if needed (trim from the beginning)
      if (transcriptText.length > MAX_TRANSCRIPT_CHARS) {
        transcriptText = transcriptText.substring(transcriptText.length - MAX_TRANSCRIPT_CHARS);
        const newlinePos = transcriptText.indexOf('\n');
        if (newlinePos !== -1) {
          transcriptText = transcriptText.substring(newlinePos + 1);
        }
        transcriptText = '...[earlier context truncated]...\n' + transcriptText;
      }

      prompt += transcriptText;
      prompt += '\n\n';
    }

    // Add explicit instruction for reconnections
    if (hasMemory) {
      prompt += 'CRITICAL: This is a reconnection within the same conversation. DO NOT repeat your initial greeting or introduce yourself again. Continue naturally from where we left off, using the context above.\n';
    }

    // Add missing sections guidance
    if (missingSections && missingSections.length > 0) {
      prompt += '\n=== SECTIONS STILL MISSING ===\n';
      prompt += `You still need to complete these sections: ${missingSections.join(', ') }. Focus your next questions on these missing areas.\n`;
    }

    // Add guidance when all 9 sections are complete
    if (missingSections && missingSections.length === 0 && cachedBrain && cachedBrain.sections &&
        cachedBrain.sections.filter(s => s.status === 'confirmado').length >= 9) {
      prompt += '\n=== ALL NINE SECTIONS COMPLETE ===\n';
      prompt += 'All nine sections are confirmed. Tell the founder their brand foundation is complete and ' +
                'explicitly instruct them to click the "Generate Brand Soul" button to see their document. ' +
                'Do not ask if they want a summary or want to dive deeper — direct them to the button.\n';
    }

    return prompt;
  }

  // Load brand brain from backend (durable memory)
  async function loadBrandBrain() {
    if (brainFetchInProgress) {
      console.log('[Brain] Fetch already in progress, waiting...');
      return cachedBrain;
    }

    try {
      brainFetchInProgress = true;
      console.log('[Brain] Loading brand brain from backend...');
      const response = await authenticatedFetch('/api/brain');
      if (!response.ok) {
        if (response.status === 404) {
          console.log('[Brain] No brand brain found yet (normal for new users)');
        } else {
          console.warn('[Brain] Failed to load brain:', response.status);
        }
        return null;
      }
      const data = await response.json();
      cachedBrain = data.brand_brain;
      console.log('[Brain] Loaded brand brain with', cachedBrain?.sections?.length || 0, 'sections');
      // Update global progress indicator
      if (typeof initGlobalProgress === 'function') {
        initGlobalProgress();
      }
      return cachedBrain;
    } catch (e) {
      console.error('[Brain] Error loading brand brain:', e);
      return null;
    } finally {
      brainFetchInProgress = false;
    }
  }

  // Reserve voice credits for 1 minute block
  async function reserveVoiceCredits() {
    try {
      const response = await authenticatedFetch('/api/voice/reserve', {
        method: 'POST'
      });

      if (!response.ok) {
        if (response.status === 401) {
          return {
            success: false,
            error: 'unauthorized',
            message: 'Authentication failed. Please login again.'
          };
        } else if (response.status === 429) {
          return {
            success: false,
            error: 'rate_limited',
            message: 'Too many requests. Please wait a moment.'
          };
        } else {
          return {
            success: false,
            error: 'unknown',
            message: 'Failed to reserve voice credits.'
          };
        }
      }

      const data = await response.json();
      return {
        success: true,
        seconds_granted: data.seconds_granted,
        credits_remaining: data.credits_remaining
      };
    } catch (e) {
      console.error('[Voice] Failed to reserve credits:', e);
      if (e.message !== 'PAYWALL_402') {
        return {
          success: false,
          error: 'network',
          message: 'Could not contact server to reserve credits.'
        };
      }
      return {
        success: false,
        error: 'out_of_credits',
        message: 'You ran out of credits.'
      };
    }
  }

  // Stop voice credits renewal
  function stopVoiceRenewal() {
    if (voiceRenewalTimer) {
      clearInterval(voiceRenewalTimer);
      voiceRenewalTimer = null;
      console.log('[Voice] Stopped credit renewal timer');
    }
  }

  // Pure decision function: has silence exceeded the suspend threshold?
  function shouldSuspendForSilence(lastActivityMs, nowMs, thresholdMs) {
    return (nowMs - lastActivityMs) >= thresholdMs;
  }

  function markVoiceActivity() {
    lastVoiceActivityAt = Date.now();
  }

  function startSilenceWatchdog() {
    stopSilenceWatchdog();
    markVoiceActivity();
    silenceWatchdogTimer = setInterval(async () => {
      if (shouldSuspendForSilence(lastVoiceActivityAt, Date.now(), SILENCE_SUSPEND_MS)) {
        console.log('[Voice] Silence threshold exceeded, suspending session');
        await stopSession();
        if (orbState) orbState.textContent = 'Paused — tap the mic to continue';
      }
    }, SILENCE_CHECK_INTERVAL_MS);
  }

  function stopSilenceWatchdog() {
    if (silenceWatchdogTimer) {
      clearInterval(silenceWatchdogTimer);
      silenceWatchdogTimer = null;
    }
  }

  async function startSession() {
    // Capture generation for this session - prevents race conditions
    const myGeneration = ++sessionGeneration;

    // Ensure we have API key before starting
    const key = await ensureApiKey();
    if (!key) {
      return;
    }

    // Check if a newer session started while we were getting the API key
    if (myGeneration !== sessionGeneration) {
      console.log('[startSession] Superseded by newer session, aborting');
      return;
    }

    try {
      stopSession();

      // Check again after stopSession - another session might have started
      if (myGeneration !== sessionGeneration) {
        console.log('[startSession] Superseded after stopSession, aborting');
        return;
      }

      // Load brand brain BEFORE starting session (durable memory)
      await loadBrandBrain();

      // Check race condition after brain loading
      if (myGeneration !== sessionGeneration) {
        console.log('[startSession] Superseded after loading brain, aborting');
        return;
      }

      // Reserve first voice credit block BEFORE opening WebSocket
      console.log('[Voice] Reserving initial voice credits...');
      const reservation = await reserveVoiceCredits();

      if (!reservation.success) {
        // Handle reservation failure
        if (reservation.error === 'out_of_credits') {
          // Paywall already shown by authenticatedFetch, no need for alert
          console.log('[Voice] Out of credits, cannot start session');
        } else if (reservation.error === 'unauthorized') {
          alert('Authentication failed. Please login again.');
          logout();
        } else {
          alert('Failed to reserve voice credits: ' + reservation.message);
        }
        return;
      }

      // Update credits UI with remaining balance
      updateCreditsUI(reservation.credits_remaining, initialSessionCredits);

      console.log('[Voice] Voice credits reserved:', reservation.seconds_granted, 'seconds granted,', reservation.credits_remaining, 'credits remaining');

      // 1. Create AudioContext with 24kHz (matches AssemblyAI requirement)
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioContextClass({ sampleRate: RATE });

      // 2. Get microphone stream
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Check again after getUserMedia - critical race window
      if (myGeneration !== sessionGeneration) {
        console.log('[startSession] Superseded after getUserMedia, aborting');
        return;
      }

      // 3. Create AudioWorklet for PCM16 conversion at 24kHz
      // First, create the worklet script inline
      const processorCode = `
        class AudioProcessor extends AudioWorkletProcessor {
          constructor() {
            super();
            this.bufferSize = 4800; // 200ms at 24kHz
            this.buffer = new Int16Array(this.bufferSize);
            this.offset = 0;
          }

          process(inputs, outputs) {
            const input = inputs[0];
            if (input && input.length > 0) {
              const channel = input[0];
              for (let i = 0; i < channel.length; i++) {
                const sample = channel[i];
                const int16 = Math.max(-1, Math.min(1, sample)) * 32767;
                this.buffer[this.offset++] = int16 < 0 ? int16 | 0 : int16;

                if (this.offset >= this.bufferSize) {
                  this.port.postMessage({ audio: this.buffer.buffer }, [this.buffer.buffer]);
                  this.buffer = new Int16Array(this.bufferSize);
                  this.offset = 0;
                }
              }
            }
            return true;
          }
        }
        registerProcessor('audio-processor', AudioProcessor);
      `;

      const blob = new Blob([processorCode], { type: 'application/javascript' });
      const blobUrl = URL.createObjectURL(blob);
      await audioContext.audioWorklet.addModule(blobUrl);
      URL.revokeObjectURL(blobUrl);

      workletNode = new AudioWorkletNode(audioContext, 'audio-processor');

      micSource = audioContext.createMediaStreamSource(mediaStream);

      // 4. Connect to AssemblyAI Voice Agent WebSocket
      const token = await ensureApiKey();
      const wsUrl = new URL('wss://agents.assemblyai.com/v1/ws');
      wsUrl.searchParams.set('token', await ensureApiKey());
      ws = new WebSocket(wsUrl.toString());

      isReady = false;
      playT = 0;
      activeSources = [];

      // Stream mic PCM16 chunks when ready
      workletNode.port.onmessage = (event) => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        if (!isReady || ws.readyState !== WebSocket.OPEN) return;
        const uint8 = new Uint8Array(event.data.audio);
        let binary = '';
        for (let i = 0; i < uint8.length; i++) {
          binary += String.fromCharCode(uint8[i]);
        }
        ws.send(JSON.stringify({
          type: 'input.audio',
          audio: btoa(binary)
        }));
      };

      micSource.connect(workletNode);

      ws.onopen = () => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        console.log('[WebSocket] Connected to AssemblyAI Voice Agent');
        setUIStatus('connecting', 'Conectando agente...');
        startSilenceWatchdog();

        // Start voice credits renewal timer (renew every 50 seconds, before 60s expire)
        // This timer checks sessionGeneration to prevent old sessions from renewing
        voiceRenewalTimer = setInterval(async () => {
          if (myGeneration !== sessionGeneration) {
            console.log('[Voice Renewal] Old session detected, cancelling renewal');
            stopVoiceRenewal();
            return;
          }

          console.log('[Voice Renewal] Renewing voice credits...');
          const renewal = await reserveVoiceCredits();

          if (!renewal.success) {
            console.error('[Voice Renewal] Failed:', renewal.error);
            stopVoiceRenewal();

            // Close the voice session on credit exhaustion
            if (renewal.error === 'out_of_credits') {
              // Paywall already shown by authenticatedFetch
              console.log('[Voice Renewal] Out of credits, closing session');
              stopSession();
            } else if (renewal.error === 'unauthorized') {
              alert('Authentication failed. Please login again.');
              stopSession();
              logout();
            }
            return;
          }

          // Update credits UI with new balance
          updateCreditsUI(renewal.credits_remaining, initialSessionCredits);
          console.log('[Voice Renewal] Renewal successful:', renewal.seconds_granted, 'seconds granted,', renewal.credits_remaining, 'credits remaining');
        }, 50000); // 50 seconds = 10 seconds before 60s block expires

        // Build dynamic prompt with memory context
        const dynamicPrompt = buildSystemPrompt();
        waitingForAnswer = false;

        // Determine if we should use greeting (skip on reconnection)
        const hasBrainOrTranscript = (
          (cachedBrain && cachedBrain.sections && cachedBrain.sections.length > 0) ||
          fullTranscript.length > 0
        );

        // Send session.update immediately
        const sessionUpdatePayload = {
          type: 'session.update',
          session: {
            system_prompt: dynamicPrompt,
            // Only include greeting on first connection, not on reconnection
            greeting: hasBrainOrTranscript ? undefined : defaultGreeting,
            input: {
              format: { encoding: 'audio/pcm' },
              turn_detection: TURN_DETECTION_BASELINE
            },
            output: {
              voice: voice,
              format: { encoding: 'audio/pcm' }
            },
            // Register extract_brand_brain tool.
            // OJO: el esquema es PLANO y **exige "type": "function"**. Sin ese
            // campo AssemblyAI responde "Invalid session configuration", cierra
            // el socket, y el fallo se disfraza de error de audioWorklet porque
            // stopSession() ya dejo el audioContext en null. No es la forma
            // anidada de OpenAI ({type:"function", function:{...}}), es plana.
            //
            // Agent will call this tool when extraction is ready. The tool
            // expects agent to provide extracted sections with citations.
            tools: [
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
            ]
          }
        };
        ws.send(JSON.stringify(sessionUpdatePayload));
      };

      ws.onmessage = (event) => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        const msg = JSON.parse(event.data);
        handleAgentEvent(msg);
      };

      ws.onerror = (err) => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        console.error('[WebSocket Error]', err);
        appendLogMessage('error', 'Error en conexión WebSocket de AssemblyAI');
        stopSession();
      };

      ws.onclose = () => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        console.log('[WebSocket Closed]');
        stopSession();
      };

    } catch (err) {
      console.error('[StartSession Failed]', err);
      alert('Error al iniciar sesión de voz: ' + err.message);
      stopSession();
    }
  }

  // Manda solo el bloque turn_detection que cambia (patron adaptativo). turn_detection
  // es mutable tras session.ready (06_VOICE_AGENT_API_DOCS.md). No repetir greeting
  // ni system_prompt aqui.
  function sendTurnDetectionUpdate(turnDetection) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: 'session.update',
      session: { input: { turn_detection: turnDetection } }
    }));
  }

  function handleAgentEvent(msg) {
    const type = msg.type;

    switch (type) {
      case 'session.ready':
        isReady = true;
        isSessionActive = true;
        setUIStatus('active');
        if (orbState) orbState.textContent = 'Escuchando...';
        console.log('[Session] Ready:', msg.session_id);
        break;

      case 'input.speech.started':
        markVoiceActivity();
        if (orbState) orbState.textContent = 'Hablando...';
        break;

      case 'transcript.user':
        markVoiceActivity();
        // User final transcript
        appendUserMessage(msg.text);
        // Track turn for extraction
        fullTranscript.push({ speaker: 'user', text: msg.text });
        if (orbState) orbState.textContent = 'Pensando...';
        // Adaptive pattern (06_VOICE_AGENT_API_DOCS.md): el fundador ya respondio,
        // vuelve a la linea base.
        if (waitingForAnswer) {
          waitingForAnswer = false;
          sendTurnDetectionUpdate(TURN_DETECTION_BASELINE);
        }
        break;

      case 'input.speech.stopped':
        break;

      case 'reply.started':
        markVoiceActivity();
        if (orbState) orbState.textContent = 'Brandy hablando...';
        break;

      case 'reply.audio':
        // Play audio chunk from AssemblyAI
        playAudioChunk(msg.data);
        break;

      case 'transcript.agent':
        markVoiceActivity();
        // Agent final transcript
        appendAgentMessage(msg.text);
        // Track turn for extraction
        fullTranscript.push({ speaker: 'agent', text: msg.text });
        // Adaptive pattern (06_VOICE_AGENT_API_DOCS.md): Brandy entrevista, el
        // fundador piensa en voz alta. Si termino en "?" damos mas tiempo de silencio.
        if (/\?\s*$/.test(msg.text || '')) {
          waitingForAnswer = true;
          sendTurnDetectionUpdate({ ...TURN_DETECTION_BASELINE, min_silence: 2200, max_silence: 6000 });
        }
        break;

      case 'tool.call':
        // Agent invoked extract_brand_brain tool
        handleToolCall(msg.name, msg.arguments, msg.call_id);
        break;

      case 'reply.done':
        if (msg.status === 'interrupted') {
          console.log('[Barge-in] Flushing audio');
          flushAudioPlayback();
        }
        if (orbState) orbState.textContent = 'Escuchando...';
        break;

      case 'session.error':
        console.error('[Agent Error]', msg.message);
        appendLogMessage('error', `Error: ${msg.message}`);
        break;

      default:
        console.log('[Event]', type, msg);
    }
  }

  function playAudioChunk(base64Data) {
    if (!audioContext || !base64Data) return;
    try {
      const raw = atob(base64Data);
      const pcm = new Int16Array(raw.length / 2);
      for (let i = 0; i < pcm.length; i++) {
        pcm[i] = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
      }
      const f32 = new Float32Array(pcm.length);
      for (let i = 0; i < pcm.length; i++) {
        f32[i] = pcm[i] / 32768.0;
      }

      const buffer = audioContext.createBuffer(1, f32.length, RATE);
      buffer.getChannelData(0).set(f32);

      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);

      playT = Math.max(playT, audioContext.currentTime);
      source.start(playT);
      playT += buffer.duration;

      activeSources.push(source);
      source.onended = () => {
        const idx = activeSources.indexOf(source);
        if (idx !== -1) activeSources.splice(idx, 1);
      };
    } catch (err) {
      console.error('[Audio Playback Error]', err);
    }
  }

  function flushAudioPlayback() {
    activeSources.forEach(src => {
      try { src.stop(); } catch(e){}
    });
    activeSources = [];
    if (audioContext) {
      playT = audioContext.currentTime;
    }
  }

  async function stopSession() {
    isSessionActive = false;
    isReady = false;
    flushAudioPlayback();

    // CRITICAL: Stop voice credits renewal timer
    // Without this, the timer would continue charging credits even with mic off
    stopVoiceRenewal();
    stopSilenceWatchdog();

    if (ws) {
      try { ws.close(); } catch(e){}
      ws = null;
    }

    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }

    if (micSource) {
      micSource.disconnect();
      micSource = null;
    }

    if (workletNode) {
      workletNode.disconnect();
      workletNode = null;
    }

    if (audioContext && audioContext.state !== 'closed') {
      try { await audioContext.close(); } catch(e){}
      audioContext = null;
    }

    setUIStatus('idle');
  }

  // UI Message Display
  function appendUserMessage(text) {
    const p = document.createElement('p');
    p.className = 'sub';
    p.style.fontStyle = 'italic';
    p.textContent = `Tú: ${text}`;
    streamContainer.appendChild(p);
    streamContainer.scrollTop = streamContainer.scrollHeight;
  }

  function appendAgentMessage(text) {
    clearPartial();
    const p = document.createElement('p');
    p.className = 'first';
    p.textContent = text;
    streamContainer.appendChild(p);
    streamContainer.scrollTop = streamContainer.scrollHeight;
  }

  function createPartial(text) {
    clearPartial();
    const p = document.createElement('p');
    p.className = 'sub partial';
    p.textContent = text;
    streamContainer.appendChild(p);
    currentPartialElement = p;
    streamContainer.scrollTop = streamContainer.scrollHeight;
  }

  function updatePartial(text) {
    if (currentPartialElement) {
      currentPartialElement.textContent = text;
      streamContainer.scrollTop = streamContainer.scrollHeight;
    } else {
      createPartial(text);
    }
  }

  function clearPartial() {
    if (currentPartialElement) {
      currentPartialElement.remove();
      currentPartialElement = null;
    }
  }

  function appendLogMessage(level, text) {
    const p = document.createElement('p');
    p.className = 'sub';
    p.style.color = '#ef4444';
    p.textContent = `⚠️ ${text}`;
    streamContainer.appendChild(p);
  }

  // Handle tool calls (extract_brand_brain)
  async function handleToolCall(toolName, args, callId) {
    markVoiceActivity();
    console.log('[Tool Call]', toolName, args);

    if (toolName === 'extract_brand_brain') {
      try {
        // Build transcript from stored messages
        const transcriptText = fullTranscript.map(t => `${t.speaker}: ${t.text}`).join('\n');
        const turnCount = Math.ceil(fullTranscript.length / 2); // Agent + user pairs

        // args is what the agent extracted - pass it as tool_result directly
        // Agent should have provided sections array with extracted data
        const tool_result = args || {
          sections: []
        };

        console.log('[Tool Call] Sending tool_result to backend:', tool_result);

        // Call backend extraction endpoint
        const response = await authenticatedFetch('/api/brain/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transcript: transcriptText,
            turn_count: turnCount,
            tool_result: tool_result
          })
        });

        if (!response.ok) {
          throw new Error(`Extraction failed: ${response.status}`);
        }

        const result = await response.json();
        console.log('[Extraction Result]', result);

        // Diagnostico para nosotros, nunca para el fundador (vetada la gamificacion
        // y el ruido en pantalla): las secciones descartadas van a consola, no a la UI.
        if (result.skipped_sections && result.skipped_sections.length > 0) {
          console.warn('[Extraction] secciones descartadas', result.skipped_sections);
        }

        // Send tool.result back to agent
        if (ws && ws.readyState === WebSocket.OPEN) {
          // `result` va como STRING, no como objeto: la API lo exige y un objeto
          // se acepta en el envio pero el agente no lo lee.
          ws.send(JSON.stringify({
            type: 'tool.result',
            call_id: callId,
            result: JSON.stringify({
              success: true,
              brand_brain: result.brand_brain,
              sections_count: result.sections_count,
              missing_sections: result.missing_sections
            })
          }));
        }

        // Update UI with extracted sections
        if (result.brand_brain && result.brand_brain.sections) {
          // Save missing_sections for prompt injection
          if (result.missing_sections) {
            missingSections = result.missing_sections;
          }

          appendExtractedSections(result.brand_brain.sections);
          updateBrandSoulButton(result.brand_brain.sections);
          updateCatalogButton(result.brand_brain.sections);

          // Refresh cached brain after successful extraction
          await loadBrandBrain();
        }

      } catch (error) {
        console.error('[Tool Call Error]', error);
        // Send error back to agent
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'tool.result',
            call_id: callId,
            result: JSON.stringify({
              success: false,
              error: error.message
            })
          }));
        }
      }
    }
  }

  function appendExtractedSections(sections) {
    // Render sections one-by-one in the center document zone (Modo A)
    renderModoASections(sections);
  }

  /**
   * Render Modo A: Brand brain sections one-by-one in the center document zone
   * Each section shows citation text in JetBrains Mono, dotted border for proposed vs solid for confirmed
   * Hover links to original transcript location
   */
  function renderModoASections(sections) {
    const docBody = document.querySelector('.docbody');
    if (!docBody) return;

    // Clear existing ghost sections and replace with live sections
    docBody.innerHTML = '';

    const sectionOrder = ['diagnostico', 'brand_journey', 'charco', 'icp', 'contrarian', 'asociaciones', 'identidad', 'oferta', 'lead_magnet'];
    const labels = {
      'diagnostico': 'Where you stand',
      'brand_journey': 'Brand Journey',
      'charco': 'The pond',
      'icp': 'The ICP',
      'contrarian': 'Contrarian stance',
      'asociaciones': 'Desired and forbidden associations',
      'identidad': 'Identity map',
      'oferta': 'The offer',
      'lead_magnet': 'The lead magnet'
    };

    // Render each section in order
    sectionOrder.forEach((sectionId, index) => {
      const section = sections.find(s => s.id === sectionId);
      const sectionNumber = String(index + 1).padStart(2, '0');
      const label = labels[sectionId] || sectionId;

      if (!section || !section.content || Object.keys(section.content).length === 0) {
        // Empty section - show ghost state
        const ghost = document.createElement('div');
        ghost.className = 'ghost';
        ghost.innerHTML = `
          <span class="gnum mono">${sectionNumber}</span>
          <span class="gname">${label}</span>
          <span class="gline" style="width:120px"></span>
        `;
        docBody.appendChild(ghost);
        return;
      }

      // Live section - render with content and citation
      const sectionEl = document.createElement('div');
      sectionEl.className = 'brain-section';
      sectionEl.dataset.sectionId = sectionId;

      // Border style: dotted for propuesto, solid for confirmado
      const isPropuesto = section.status === 'propuesto';
      const borderColor = isPropuesto ? '#D5DAE4' : '#2B4CD8';
      const borderStyle = isPropuesto ? 'dotted' : 'solid';
      const bgColor = isPropuesto ? '#FFFFFF' : '#F5F7FB';
      const statusText = isPropuesto ? 'Proposed' : 'Confirmed';

      sectionEl.style.cssText = `
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 16px 18px;
        margin: 8px 0;
        border: 2px ${borderStyle} ${borderColor};
        border-radius: 8px;
        background: ${bgColor};
        min-height: 60px;
      `;

      // Section header with number and status
      const header = document.createElement('div');
      header.style.cssText = `
        display: flex;
        align-items: center;
        gap: 12px;
      `;
      header.innerHTML = `
        <span class="section-num mono" style="font-size: 11px; color: #5C6675; font-weight: 600;">${sectionNumber}</span>
        <span class="section-label" style="font-size: 14px; font-weight: 500; color: #14181F; flex: 1;">${label}</span>
        <span class="section-status mono" style="font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: ${borderColor}; font-weight: 600;">${statusText}</span>
      `;
      sectionEl.appendChild(header);

      // Section content (handle single values and nested objects)
      const contentEl = document.createElement('div');
      contentEl.className = 'section-content';
      contentEl.style.cssText = `
        padding-left: 26px;
        font-size: 13px;
        line-height: 1.6;
        color: #14181F;
      `;

      if (typeof section.content === 'object' && section.content !== null) {
        // For nested objects (like contrarian, asociaciones), render two-column layout if applicable
        const entries = Object.entries(section.content);
        if (sectionId === 'contrarian' || sectionId === 'asociaciones') {
          const grid = document.createElement('div');
          grid.style.cssText = 'display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 8px;';
          entries.forEach(([key, value]) => {
            const col = document.createElement('div');
            col.style.cssText = 'padding: 8px; background: rgba(43, 76, 216, 0.04); border-radius: 6px;';
            const keyEl = document.createElement('div');
            keyEl.style.cssText = 'font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: #5C6675; margin-bottom: 4px;';
            keyEl.textContent = key;
            const valEl = document.createElement('div');
            valEl.style.cssText = 'font-size: 13px; color: #14181F;';
            valEl.textContent = value || '—';
            col.appendChild(keyEl);
            col.appendChild(valEl);
            grid.appendChild(col);
          });
          contentEl.appendChild(grid);
        } else {
          // For other objects, render as key-value pairs
          entries.forEach(([key, value]) => {
            const row = document.createElement('div');
            row.style.cssText = 'margin-bottom: 4px;';
            const keyEl = document.createElement('strong');
            keyEl.style.cssText = 'font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: #5C6675; margin-right: 8px;';
            keyEl.textContent = `${key}:`;
            const valEl = document.createElement('span');
            valEl.textContent = value || '—';
            row.appendChild(keyEl);
            row.appendChild(valEl);
            contentEl.appendChild(row);
          });
        }
      } else {
        // For simple string values
        contentEl.textContent = section.content || '—';
      }
      sectionEl.appendChild(contentEl);

      // Citation block (always visible, non-empty invariant enforced)
      const citationEl = document.createElement('div');
      citationEl.className = 'citation-block';
      citationEl.style.cssText = `
        padding-left: 26px;
        margin-top: 8px;
        border-left: 2px solid #D5DAE4;
        padding-left: 10px;
        cursor: pointer;
        transition: background-color 0.2s ease;
      `;
      citationEl.title = 'Click to jump to this moment in the conversation';

      const citationLabel = document.createElement('div');
      citationLabel.style.cssText = `
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #5C6675;
        margin-bottom: 4px;
      `;
      citationLabel.textContent = section.citation_source === 'usuario' ? 'Source: You said' : 'Source: Analysis';
      citationEl.appendChild(citationLabel);

      const citationText = document.createElement('div');
      citationText.className = 'mono';
      citationText.style.cssText = `
        font-size: 11px;
        color: #2B4CD8;
        font-style: italic;
        line-height: 1.5;
      `;
      citationText.textContent = section.citation_text || '—';
      citationEl.appendChild(citationText);

      // Add hover effect
      citationEl.addEventListener('mouseenter', () => {
        citationEl.style.backgroundColor = 'rgba(43, 76, 216, 0.04)';
      });
      citationEl.addEventListener('mouseleave', () => {
        citationEl.style.backgroundColor = 'transparent';
      });

      // Add click handler to link to transcript (scroll to matching message in stream)
      citationEl.addEventListener('click', () => {
        highlightTranscriptSection(section.citation_text);
      });

      sectionEl.appendChild(citationEl);
      docBody.appendChild(sectionEl);
    });
  }

  /**
   * Highlight and scroll to the transcript section that matches the citation text
   * Searches through fullTranscript and highlights in the stream container
   */
  function highlightTranscriptSection(citationText) {
    if (!citationText || citationText === '—') return;

    // Search for matching transcript entry
    const matchIndex = fullTranscript.findIndex(t =>
      t.text && t.text.toLowerCase().includes(citationText.toLowerCase().substring(0, 50))
    );

    if (matchIndex !== -1 && streamContainer) {
      // Add visual feedback to the matched transcript
      const paragraphs = streamContainer.querySelectorAll('p.sub, p.stream-msg');
      paragraphs.forEach((p, i) => {
        if (i === matchIndex) {
          p.style.backgroundColor = 'rgba(43, 76, 216, 0.1)';
          p.style.borderRadius = '6px';
          p.style.padding = '8px';
          p.scrollIntoView({ behavior: 'smooth', block: 'center' });

          // Remove highlight after 3 seconds
          setTimeout(() => {
            p.style.backgroundColor = '';
            p.style.borderRadius = '';
            p.style.padding = '';
          }, 3000);
        }
      });
    }
  }

  function setUIStatus(state, message) {
    if (state === 'active') {
      orb.classList.remove('orb--hablando');
      orb.classList.add('orb--escuchando');
      if (orbState) orbState.textContent = message || 'Escuchando...';
      if (micBtn) micBtn.style.background = '#D5DAE4';
    } else if (state === 'connecting') {
      if (orbState) orbState.textContent = message || 'Conectando...';
    } else {
      // Idle
      orb.classList.remove('orb--escuchando');
      orb.classList.add('orb--hablando');
      if (orbState) orbState.textContent = 'Brandy speaking';
      if (micBtn) micBtn.style.background = '';
    }
  }

  // Toggle microphone
  async function toggleMicrophone() {
    if (isSessionActive) {
      stopSession();
    } else {
      // Disable button while starting to prevent race condition from double-clicks
      if (micBtn) micBtn.disabled = true;
      try {
        await startSession();
      } finally {
        // Re-enable button after startSession completes (success or error)
        if (micBtn) micBtn.disabled = false;
      }
    }
  }

  // Wire up button
  if (micBtn) {
    micBtn.addEventListener('click', toggleMicrophone);
  }

  // =============================================================================
  // PAYWALL
  // =============================================================================

  const paywallOverlay = document.getElementById('Paywall-Overlay');
  const paywallCloseBtn = document.getElementById('Paywall-CloseBtn');

  // Show paywall overlay
  function showPaywall() {
    if (paywallOverlay) {
      paywallOverlay.style.display = 'flex';
    }
  }

  // Hide paywall overlay
  function hidePaywall() {
    if (paywallOverlay) {
      paywallOverlay.style.display = 'none';
    }
  }

  // Close paywall when X button clicked
  if (paywallCloseBtn) {
    paywallCloseBtn.addEventListener('click', hidePaywall);
  }

  // Handle plan selection buttons - connect to Stripe checkout
  document.querySelectorAll('.plan-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const plan = btn.dataset.plan;

      try {
        // Disable button and show loading state
        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = 'Processing...';

        // Call billing checkout endpoint
        const response = await authenticatedFetch('/api/billing/checkout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ package: plan })
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || 'Failed to create checkout session');
        }

        // Redirect to Stripe checkout
        console.log(`[Billing] Redirecting to Stripe checkout for plan: ${plan}`);
        window.location.href = data.url;

      } catch (error) {
        console.error('[Billing] Checkout error:', error);
        alert(`Unable to process payment: ${error.message}`);
      } finally {
        // Re-enable button
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  // Track credits state for depleted mode
  let creditsDepleted = false;

  // Update credits UI (helper function)
  function updateCreditsUI(remaining, initial) {
    // Update global credits variable for access in modals and gates
    credits = remaining;

    const creditsLabel = document.getElementById('Credits-Label');
    const creditsBar = document.getElementById('Credits-Bar');

    if (creditsLabel) {
      creditsLabel.innerHTML = `${remaining} <span style="font-size:12px;color:#5C6675">/ ${initial}</span>`;
    }

    // percentage se calcula FUERA del if: abajo se usa en el log, y declararla
    // dentro del bloque lanzaba ReferenceError en cada llamada, abortando la
    // funcion justo antes de la deteccion de saldo agotado. El paywall no se
    // activaba nunca.
    const percentage = Math.max(0, Math.min(100, (remaining / initial) * 100));

    if (creditsBar) {
      creditsBar.style.width = `${percentage}%`;

      // Change color when low
      if (percentage < 20) {
        creditsBar.style.background = '#ef4444';
      } else if (percentage < 50) {
        creditsBar.style.background = '#f59e0b';
      } else {
        creditsBar.style.background = '#2B4CD8';
      }
    }

    console.log(`[Credits] ${remaining} of ${initial} (${percentage.toFixed(1)}%)`);

    // Check if depleted
    const wasDepleted = creditsDepleted;
    creditsDepleted = remaining <= 0;

    // If just became depleted, show paywall and disable controls
    if (!wasDepleted && creditsDepleted) {
      console.log('[Paywall] Credits depleted, enabling depleted mode');
      disableDepletedControls();
      showPaywall();
    } else if (wasDepleted && !creditsDepleted) {
      // If no longer depleted, re-enable controls
      console.log('[Paywall] Credits available again, disabling depleted mode');
      enableDepletedControls();
    }
  }

  // Disable controls when credits are depleted
  function disableDepletedControls() {
    // Disable microphone button
    if (micBtn) {
      micBtn.disabled = true;
      micBtn.style.background = 'var(--line)';
      micBtn.style.cursor = 'not-allowed';
      micBtn.title = 'No credits available - please purchase more to continue';
    }

    // Stop any active session
    if (isSessionActive) {
      stopSession();
    }

    // Note: Brand Soul button is NOT disabled - users can still view/download
    // their existing Brand Soul even with 0 credits
  }

  // Re-enable controls when credits become available again
  function enableDepletedControls() {
    // Re-enable microphone button
    if (micBtn) {
      micBtn.disabled = false;
      micBtn.style.background = '';
      micBtn.style.cursor = 'pointer';
      micBtn.title = '';
    }
  }

  // Fetch fresh credits from server
  async function fetchCredits() {
    try {
      console.log('[Billing] Fetching fresh credits from /api/session...');
      const response = await authenticatedFetch('/api/session');
      if (!response.ok) {
        console.error('[Billing] Failed to fetch credits:', response.status);
        return;
      }
      const data = await response.json();
      const freshCredits = data.credits_remaining;
      console.log('[Billing] Fresh credits loaded:', freshCredits);
      updateCreditsUI(freshCredits, initialSessionCredits);
    } catch (e) {
      console.error('[Billing] Error fetching credits:', e);
      if (e.message !== 'PAYWALL_402') {
        alert('Could not refresh credits. Please refresh the page.');
      }
    }
  }


  // ==============================================================================
  // GOOGLE OAUTH AUTHENTICATION
  // ==============================================================================

  const loginOverlay = document.getElementById('Login-Overlay');
  const mainApp = document.getElementById('Main-App');
  const googleBtn = document.getElementById('GoogleBtn');
  const loginError = document.getElementById('Login-Error');

  // Initialize Supabase
  async function initSupabase() {
    try {
      const configResponse = await fetch('/api/config');
      const config = await configResponse.json();

      supabase = window.supabase.createClient(config.supabase_url, config.supabase_publishable_key);

      // Listen for auth state changes
      supabase.auth.onAuthStateChange((event, session) => {
        // CRITICAL FIX: Prevent logout if we're in the middle of Stripe checkout return
        // When user returns from Stripe, Supabase may temporarily emit SIGNED_OUT event
        // Setting isCheckoutInProgress flag prevents unwanted logout
        if (event === 'SIGNED_IN' && session) {
          jwtToken = session.access_token;
          user = session.user;
          showMainApp();
        } else if (event === 'SIGNED_OUT' && !isCheckoutInProgress) {
          // Only logout if we're NOT returning from Stripe checkout
          logout();
        } else if (event === 'SIGNED_OUT' && isCheckoutInProgress) {
          console.log('[Billing] ⚠️ SIGNED_OUT event detected during checkout - ignoring to prevent logout');
        }
      });

      // Check for existing session
      const { data: { session } } = await supabase.auth.getSession();

      if (session) {
        jwtToken = session.access_token;
        user = session.user;
        showMainApp();
      } else {
        showLogin();
      }
    } catch (e) {
      console.error('[Auth] Failed to initialize Supabase:', e);
      loginError.textContent = 'Failed to initialize authentication. Please refresh.';
      loginError.classList.add('visible');
    }
  }

  function showLogin() {
    loginOverlay.style.display = 'flex';
    mainApp.style.display = 'none';
  }

  async function loadExistingBrain() {
    try {
      const brain = await loadBrandBrain();
      if (brain && brain.sections && brain.sections.length) {
        appendExtractedSections(brain.sections);
        updateBrandSoulButton(brain.sections);
        updateCatalogButton(brain.sections);
      }
    } catch (e) {
      console.error('[Brain] No se pudo cargar el cerebro existente:', e);
    }
  }

  function showMainApp() {
    loginOverlay.style.display = 'none';
    mainApp.style.display = 'flex';
    loadConfig().then(() => {
      updateCreditsDisplay();
      loadExistingBrain();
    });
  }

  function logout() {
    supabase.auth.signOut();
    jwtToken = null;
    user = null;
    API_KEY = '';
    apiKeyRequested = false;
    showLogin();
  }

  // Handle Google OAuth login
  googleBtn.addEventListener('click', async () => {
    try {
      googleBtn.classList.add('loading');
      googleBtn.disabled = true;
      loginError.classList.remove('visible');

      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.href,
          queryParams: {
            access_type: 'offline',
            prompt: 'consent'
          }
        }
      });

      if (error) throw error;

      // OAuth redirect will handle the callback
    } catch (e) {
      console.error('[Auth] Login failed:', e);
      loginError.textContent = e.message || 'Login failed. Please try again.';
      loginError.classList.add('visible');
      googleBtn.classList.remove('loading');
      googleBtn.disabled = false;
    }
  });

  // Handle OAuth callback
  async function handleAuthCallback() {
    const hashParams = new URLSearchParams(window.location.hash);
    const accessToken = hashParams.get('access_token');

    if (accessToken) {
      jwtToken = accessToken;
      showMainApp();
      // Clear hash to prevent re-processing
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }

  // Update credits display
  async function updateCreditsDisplay() {
    try {
      const response = await authenticatedFetch('/api/session');
      if (response.ok) {
        const data = await response.json();
        updateCreditsUI(data.credits_remaining, initialSessionCredits);
      }
    } catch (e) {
      console.error('[Auth] Failed to fetch session:', e);
    }
  }

  // Load configuration from backend
  async function loadConfig() {
    try {
      const response = await fetch('/api/config');
      if (response.ok) {
        const config = await response.json();
        if (config.initial_session_credits !== undefined) {
          initialSessionCredits = config.initial_session_credits;
          console.log('[Config] Initial session credits:', initialSessionCredits);
        }
      }
    } catch (e) {
      console.error('[Config] Failed to load config:', e);
      // Use default value if config fetch fails
      initialSessionCredits = 500;
    }
  }

{}

  // =============================================================================
  // BRAND SOUL GENERATION BUTTON
  // =============================================================================

  const brandSoulBtn = document.getElementById('BrandSoul-Btn');
  const brandSoulLabel = document.getElementById('BrandSoul-Label');
  const brandSoulOverlay = document.getElementById('BrandSoul-Overlay');
  const brandSoulContent = document.getElementById('BrandSoul-Content');
  const brandSoulLoading = document.getElementById('BrandSoul-Loading');
  const brandSoulCloseBtn = document.getElementById('BrandSoul-CloseBtn');
  const brandSoulDownloadBtn = document.getElementById('BrandSoul-DownloadBtn');
  const brandSoulRegenerateBtn = document.getElementById('BrandSoul-RegenerateBtn');

  // Update Brand Soul button state based on confirmed sections count
  function updateBrandSoulButton(sections) {
    if (!brandSoulBtn || !brandSoulLabel) return;

    const confirmedCount = typeof getReadySectionsCount === 'function' 
      ? getReadySectionsCount(sections) 
      : (sections || []).filter(s => {
          const st = (s.status || '').toLowerCase();
          const hasContent = s.content && Object.keys(s.content).length > 0;
          return (st === 'confirmado' || st === 'completado' || st === 'confirmed') && hasContent;
        }).length;

    brandSoulLabel.textContent = `Brand Soul — ${confirmedCount} of 9 sections ready`;

    // Update progress bar width
    const brandSoulBar = document.getElementById('BrandSoul-Bar');
    if (brandSoulBar) {
      const progress = (confirmedCount / 9) * 100;
      brandSoulBar.style.width = `${progress}%`;
    }

    if (confirmedCount >= 9) {
      brandSoulBtn.disabled = false;
    } else {
      brandSoulBtn.disabled = true;
    }

    if (typeof updateCatalogButton === 'function') {
      updateCatalogButton(sections);
    }
  }

  // Generate Brand Soul document
  async function generateBrandSoul() {
    if (!brandSoulBtn || brandSoulBtn.disabled) return;

    try {
      // Show loading state on button
      brandSoulBtn.classList.add('loading');
      brandSoulBtn.disabled = true;

      // Show overlay with loading spinner
      brandSoulOverlay.style.display = 'flex';
      brandSoulContent.style.display = 'none';
      brandSoulContent.innerHTML = '';
      brandSoulLoading.style.display = 'flex';

      // Step 1: Try to get cached Brand Soul first (no credits charged)
      const cacheResponse = await authenticatedFetch('/api/soul', {
        method: 'GET'
      });

      if (cacheResponse.ok) {
        // Cached document exists - display it without charging credits
        const cacheData = await cacheResponse.json();
        brandSoulLoading.style.display = 'none';
        brandSoulContent.style.display = 'block';
        brandSoulContent.innerHTML = cacheData.html;
        
        // Show regenerate button since we have a cached document
        if (brandSoulRegenerateBtn) {
          brandSoulRegenerateBtn.style.display = 'flex';
        }
        
        console.log('[Brand Soul] Loaded from cache - no credits charged');
        return;
      }

      // Step 2: If cache returns 404, generate new document (charges 20 credits)
      if (cacheResponse.status === 404) {
        const response = await authenticatedFetch('/api/soul/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regenerate: false })
        });

        const data = await response.json();
        const body = 'detail' in data ? data.detail : data;

        if (!response.ok) {
          // Handle specific error cases
          if (response.status === 400 && body.error) {
            // Incomplete brain - extract missing sections count
            const match = body.error.match(/(\d+)\s*of\s*9/);
            if (match) {
              const confirmed = parseInt(match[1]);
              const missing = 9 - confirmed;
              alert(`Your brand brain is incomplete. ${missing} section${missing > 1 ? 's' : ''} need${missing > 1 ? '' : 's'} to be confirmed before generating your Brand Soul. Keep talking with Brandy to complete them.`);
            } else {
              alert(`Your brand brain is incomplete: ${body.error}. Keep talking with Brandy to complete all 9 sections.`);
            }
          } else if (response.status === 402) {
            alert('Not enough credits to generate Brand Soul. Please purchase more credits to continue.');
          } else if (response.status === 429) {
            alert("You've reached the rate limit. Please wait a minute before trying again.");
          } else if (response.status === 500 && body.error && body.error.includes('Citation validation failed')) {
            // No se promete que no se cobro: los creditos se descuentan ANTES de
            // llamar al LLM (main.py y generator.py), asi que en este punto ya se
            // fueron. Mentirle al usuario sobre su dinero es peor que el fallo.
            alert('We could not verify that every quote in your Brand Soul came from your own words, so the document was not shown. This is the guarantee that makes it trustworthy. Please try generating it again.');
          } else {
            alert(`Failed to generate Brand Soul: ${body.error || body || response.status}`);
          }

          // Hide overlay on error
          brandSoulOverlay.style.display = 'none';
          return;
        }

        // Success - display the HTML document
        brandSoulLoading.style.display = 'none';
        brandSoulContent.style.display = 'block';
        brandSoulContent.innerHTML = data.html;

        // Update credits display if included in response
        if (data.credits_remaining !== undefined) {
          updateCreditsUI(data.credits_remaining, initialSessionCredits);
        }

        // Show regenerate button since we now have a generated document
        if (brandSoulRegenerateBtn) {
          brandSoulRegenerateBtn.style.display = 'flex';
        }

        console.log('[Brand Soul] Document generated successfully');
        return;
      }

      // Handle other cache errors
      const cacheError = await cacheResponse.json();
      alert(`Failed to load Brand Soul: ${cacheError.error || cacheError.detail || cacheResponse.status}`);
      brandSoulOverlay.style.display = 'none';

    } catch (error) {
      console.error('[Brand Soul] Loading error:', error);
      alert('Failed to load Brand Soul: ' + error.message);
      brandSoulOverlay.style.display = 'none';
    } finally {
      // Remove loading state from button and restore state
      brandSoulBtn.classList.remove('loading');
      if (cachedBrain && cachedBrain.sections) {
        const confirmedCount = cachedBrain.sections.filter(s => s.status === 'confirmado').length;
        brandSoulBtn.disabled = confirmedCount < 9;
      } else {
        brandSoulBtn.disabled = true;
      }
    }
  }

  // Download Brand Soul as HTML file
  function downloadBrandSoul() {
    if (!brandSoulContent || !brandSoulContent.innerHTML) {
      alert('No document to download. Please generate your Brand Soul first.');
      return;
    }

    try {
      const htmlContent = brandSoulContent.innerHTML;

      // Create a complete HTML document
      const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Brand Soul</title>
</head>
<body>
${htmlContent}
</body>
</html>`;

      const blob = new Blob([fullHtml], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'brand-soul.html';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      console.log('[Brand Soul] Document downloaded as brand-soul.html');
    } catch (error) {
      console.error('[Brand Soul] Download error:', error);
      alert('Failed to download document: ' + error.message);
    }
  }

  // Regenerate Brand Soul document (requires 20 credits)
  async function regenerateBrandSoul() {
    try {
      // Confirm cost before proceeding
      const confirmed = confirm("Regenerating costs 20 credits. Your current document will be replaced. Continue?");
      if (!confirmed) {
        return; // User cancelled - don't proceed
      }

      // Show loading state on regenerate button
      if (brandSoulRegenerateBtn) {
        brandSoulRegenerateBtn.classList.add('loading');
        brandSoulRegenerateBtn.disabled = true;
      }

      // Show loading spinner and hide content
      brandSoulLoading.style.display = 'flex';
      brandSoulContent.style.display = 'none';

      const response = await authenticatedFetch('/api/soul/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regenerate: true })
      });

      const data = await response.json();
      const body = 'detail' in data ? data.detail : data;

      if (!response.ok) {
        // Handle specific error cases
        if (response.status === 402) {
          alert('Not enough credits to regenerate Brand Soul. Please purchase more credits to continue.');
        } else if (response.status === 429) {
          alert("You've reached the rate limit. Please wait a minute before trying again.");
        } else if (response.status === 500 && body.error && body.error.includes('Citation validation failed')) {
          alert('We could not verify that every quote in your Brand Soul came from your own words, so the document was not shown. This is the guarantee that makes it trustworthy. Please try generating it again.');
        } else {
          alert(`Failed to regenerate Brand Soul: ${body.error || body || response.status}`);
        }

        // Show previous content on error
        brandSoulLoading.style.display = 'none';
        if (brandSoulContent.innerHTML) {
          brandSoulContent.style.display = 'block';
        }
        return;
      }

      // Success - display the new HTML document
      brandSoulLoading.style.display = 'none';
      brandSoulContent.style.display = 'block';
      brandSoulContent.innerHTML = data.html;

      // Update credits display if included in response
      if (data.credits_remaining !== undefined) {
        updateCreditsUI(data.credits_remaining, initialSessionCredits);
      }

      console.log('[Brand Soul] Document regenerated successfully - 20 credits charged');

    } catch (error) {
      console.error('[Brand Soul] Regeneration error:', error);
      alert('Failed to regenerate Brand Soul: ' + error.message);
      brandSoulLoading.style.display = 'none';
      if (brandSoulContent.innerHTML) {
        brandSoulContent.style.display = 'block';
      }
    } finally {
      // Remove loading state from regenerate button
      if (brandSoulRegenerateBtn) {
        brandSoulRegenerateBtn.classList.remove('loading');
        brandSoulRegenerateBtn.disabled = false;
      }
    }
  }

  // Close Brand Soul overlay
  function closeBrandSoulOverlay() {
    if (brandSoulOverlay) {
      brandSoulOverlay.style.display = 'none';
    }
    // Hide regenerate button when overlay is closed
    if (brandSoulRegenerateBtn) {
      brandSoulRegenerateBtn.style.display = 'none';
    }
  }

  // =============================================================================
  // CATALOG FUNCTIONALITY
  // =============================================================================

  // Catalog DOM elements
  const catalogBtn = document.getElementById('Catalog-Btn');
  const catalogLabel = document.getElementById('Catalog-Label');
  const blockAView = document.getElementById('BlockA-View');
  const blockBView = document.getElementById('BlockB-View');
  const blockCView = document.getElementById('BlockC-View');
  const catalogCategories = document.getElementById('Catalog-Categories');
  const catalogGate = document.getElementById('Catalog-Gate');
  const catalogGateTitle = document.getElementById('Catalog-GateTitle');
  const catalogGateSub = document.getElementById('Catalog-GateSub');
  const catalogGateCount = document.getElementById('Catalog-GateCount');
  const catalogProgress = document.getElementById('Catalog-Progress');
  const creditGateOverlay = document.getElementById('CreditGate-Overlay');
  const gateCancelBtn = document.getElementById('Gate-CancelBtn');
  const gateApproveBtn = document.getElementById('Gate-ApproveBtn');
  const gateBalanceAfter = document.getElementById('Gate-BalanceAfter');

  // Script (BlockC) DOM elements
  const scriptBackBtn = document.getElementById('Script-BackBtn');
  const scriptIdeaTitle = document.getElementById('Script-IdeaTitle');
  const scriptMeta = document.getElementById('Script-Meta');
  const scriptAngle = document.getElementById('Script-Angle');
  const scriptFunnelStage = document.getElementById('Script-FunnelStage');
  const scriptDuration = document.getElementById('Script-Duration');
  const scriptRecordingFormat = document.getElementById('Script-RecordingFormat');
  const scriptMusicPrompt = document.getElementById('Script-MusicPrompt');
  const scriptContent = document.getElementById('Script-Content');
  const scriptEmptyState = document.getElementById('Script-EmptyState');
  const scriptSourceMode = document.getElementById('Script-SourceMode');
  const scriptIdeaKind = document.getElementById('Script-IdeaKind');
  const scriptGenerateBtn = document.getElementById('Script-GenerateBtn');
  const scriptGenerateHelp = document.getElementById('Script-GenerateHelp');
  const scriptFrameZero = document.getElementById('Script-FrameZero');
  const scriptFrameZeroContent = document.getElementById('Script-FrameZeroContent');
  const scriptScenes = document.getElementById('Script-Scenes');
  const scriptAudit = document.getElementById('Script-Audit');
  const scriptLockBtn = document.getElementById('Script-LockBtn');

  // PIEZA 42: Review panel elements (created dynamically in renderScript)
  // Track active regenerate forms to prevent duplicates
  let activeRegenerateForms = new Set();

  // Flag to prevent re-charging for already generated catalog
  let catalogAlreadyGenerated = false;
  // Block C: Track current script data
  let currentScriptData = null;

  // PIEZA 31 (bug B6): faltaba declarar -- openCreditGateModal() la leía
  // (`renderCatalogInPanel(currentCatalog)`) y disparaba un ReferenceError
  // al hacer clic en el gate con un catálogo ya generado. Se asigna en cada
  // punto donde se renderiza/carga un catálogo (renderCatalogInPanel).
  let currentCatalog = null;

  // Script state tracking
  let currentScriptIdeaId = null;  // ID of the idea the script belongs to

  // PIEZA 31 (bug B4): escapa texto de terceros antes de interpolarlo en
  // innerHTML. `demand_signal` viene de comentarios de YouTube / grounding
  // web (texto ajeno, no confiable) y `title`/`subcategory` pueden incluir
  // caracteres de HTML -- sin esto, un XSS almacenado corre con el JWT del
  // founder en memoria.
  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Las 5 categorías maestras (MASTER_CATEGORIES en app/catalog/ideas.py) --
  // hoisted a nivel de módulo para que tanto renderCatalogInPanel() como el
  // handler de "Agregar idea propia" (punto D1) las reutilicen sin duplicar.
  const CATALOG_CATEGORY_NAMES = {
    'autoridad_tecnica': 'Autoridad Técnica e Instrucción',
    'validacion_resultados': 'Validación de Resultados e Impacto',
    'posicionamiento_narrativa': 'Posicionamiento y Tesis de Mercado',
    'narrativa_fundadora': 'Narrativa Fundadora y Origen',
    'discusion_industria': 'Discusión y Co-creación de Industria'
  };
  const CATALOG_CATEGORY_COLORS = {
    'autoridad_tecnica': '#2B4CD8',
    'validacion_resultados': '#1B7F4C',
    'posicionamiento_narrativa': '#B5720B',
    'narrativa_fundadora': '#8A2BE2',
    'discusion_industria': '#C2262E'
  };

  // Helper to check if all ideas are reviewed and enable/disable Lock button
  // Pieza 29 (punto D4): se recalcula tras cada ✓/✗/↻/agregar. Si el catálogo
  // ya está bloqueado (data-locked="true"), no se pisa el texto/estado.
  function checkAndEnableLockButton() {
    const lockBtn = document.getElementById('Catalog-LockBtn');
    if (!lockBtn || lockBtn.dataset.locked === 'true') return;

    const pendingIdeas = document.querySelectorAll('.idea--pending');
    if (pendingIdeas.length === 0) {
      lockBtn.disabled = false;
      lockBtn.textContent = 'Lock Catalog (All Reviewed)';
    } else {
      lockBtn.disabled = true;
      lockBtn.textContent = `Lock Catalog (${pendingIdeas.length} pending)`;
    }
  }

  // Pieza 29 (punto D4): al bloquear el catálogo (o al recargar uno ya
  // bloqueado), deshabilita ✓ ✗ ↻ y el formulario de "Agregar idea propia".
  // Pieza 30 (bug B3): los botones WebSearch/YouTube/Trends se eliminaron
  // del render de cada tarjeta -- cobraban 25 créditos, repetían la
  // investigación del nicho entero y solo mostraban un alert.
  function applyCatalogLockedUI() {
    const lockBtn = document.getElementById('Catalog-LockBtn');
    if (lockBtn) {
      lockBtn.dataset.locked = 'true';
      lockBtn.disabled = true;
      lockBtn.textContent = 'Catálogo bloqueado ✓';
    }

    // PIEZA 36 (bug 4): Skip founder ideas when disabling approve/discard/regenerate buttons
    document.querySelectorAll('.idea').forEach(ideaDiv => {
      const origin = ideaDiv.dataset.origin || 'engine';
      if (origin !== 'founder') {
        ideaDiv.querySelectorAll('.btn-approve, .btn-reject, .btn-regenerate').forEach(btn => {
          btn.disabled = true;
        });
      }
      // The regenerate button is already filtered out for founder ideas in buildIdeaCardHTML(),
      // but this is an extra safety check at the DOM level.

      // PIEZA 36 (bug 4): Script button is still disabled on ALL ideas when catalog is locked
      // - Approved ideas show the "Write script" button (via buildIdeaCardHTML)
      // - Founder can edit their own approved ideas with the script writer
      // - Engine ideas remain locked completely
    });

    // Decisión del CEO: agregar ideas propias sigue SIEMPRE disponible y
    // gratis, incluso con el catálogo bloqueado -- nacen "approved", nunca
    // rompen el candado. El formulario NO se deshabilita aquí.
  }

  // Construye el HTML interno de una tarjeta de idea (compartido entre el
  // render inicial, agregar idea propia sin recargar, y reemplazo por regenerar).
  function buildIdeaCardHTML(idea, color, catalogLocked = false) {
    const founderBadge = idea.origin === 'founder' ? '<span class="badge-founder">Tu idea</span>' : '';
    // Decisión del CEO: una idea propia del fundador no se regenera --
    // regenerar la reemplazaría por una idea del LLM, borrando lo que el
    // fundador escribió a mano. El botón ↻ simplemente no se renderiza.
    // PIEZA 31 (bug B6/B4): idea.id se interpola en un atributo HTML sin
    // comillas escapadas -- es un ID generado por el backend (uuid hex), no
    // texto de terceros, pero se pasa por escapeHtml igual como defensa en
    // profundidad barata.
    const safeId = escapeHtml(idea.id);
    const regenerateBtnHTML = idea.origin === 'founder'
      ? ''
      : `<button class="btn-regenerate" data-idea-id="${safeId}" title="Regenerar (3 créditos)">&#8635;</button>`;
    // PIEZA 34 (bug 3): Add "Write script" / "Open script" button on approved ideas when catalog is locked
    const scriptBtnHTML = (catalogLocked && idea.status === 'approved')
      ? `<button class="btn-script" data-idea-id="${safeId}" title="Write script">📝 Write script</button>`
      : '';
    return `
      <span class="ideatitle">${escapeHtml(idea.title)}${founderBadge}</span>
      <span class="angle" style="border-color:${color};color:${color}">${escapeHtml(idea.subcategory || 'Formato')}</span>
      <span class="signal">${escapeHtml(idea.demand_signal)}</span>
      <div class="idea-actions">
        <button class="btn-approve" data-idea-id="${safeId}" title="Approve idea">&#10003;</button>
        <button class="btn-reject" data-idea-id="${safeId}" title="Discard idea">&#10007;</button>
        ${regenerateBtnHTML}
        ${scriptBtnHTML}
      </div>
    `;
  }

  // Wire de ✓ / ✗ / ↻ para UNA tarjeta de idea puntual (reutilizable para
  // ideas agregadas o regeneradas sin recargar el panel completo).
  function wireIdeaCardActions(ideaDiv) {
    const approveBtn = ideaDiv.querySelector('.btn-approve');
    const rejectBtn = ideaDiv.querySelector('.btn-reject');
    const regenerateBtn = ideaDiv.querySelector('.btn-regenerate');
    const scriptBtn = ideaDiv.querySelector('.btn-script');

    if (approveBtn) {
      approveBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const ideaId = approveBtn.dataset.ideaId;
        try {
          const response = await authenticatedFetch(`/api/catalog/idea/${ideaId}/accept`, { method: 'POST' });
          const data = await response.json();
          if (!response.ok) {
            alert(`Failed to approve idea: ${data.error || data.detail || response.status}`);
            return;
          }
          // PIEZA 36 (bug 3): Update CSS classes
          ideaDiv.classList.remove('idea--pending', 'idea--rejected');
          ideaDiv.classList.add('idea--approved');
          // PIEZA 36 (bug 3): Sync currentCatalog from backend response (source of truth)
          if (currentCatalog && data.catalog && data.catalog.ideas) {
            currentCatalog.ideas = data.catalog.ideas;
          }
          // Disable approve/reject buttons after approval to prevent double-actions
          approveBtn.disabled = true;
          rejectBtn.disabled = true;
          checkAndEnableLockButton();
          // PIEZA 36 (bug 3): Update script button visibility if this is the current idea
          if (currentScriptIdeaId === ideaId) {
            updateScriptGenerateButton();
          }
        } catch (error) {
          console.error('Approve idea error:', error);
          alert(`Failed to approve idea: ${error.message}`);
        }
      });
    }

    if (rejectBtn) {
      rejectBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const ideaId = rejectBtn.dataset.ideaId;
        try {
          const response = await authenticatedFetch(`/api/catalog/idea/${ideaId}/discard`, { method: 'POST' });
          const data = await response.json();
          if (!response.ok) {
            alert(`Failed to discard idea: ${data.error || data.detail || response.status}`);
            return;
          }
          // PIEZA 36 (bug 3): Update CSS classes
          ideaDiv.classList.remove('idea--pending', 'idea--approved');
          ideaDiv.classList.add('idea--rejected');
          // PIEZA 36 (bug 3): Sync currentCatalog from backend response (source of truth)
          if (currentCatalog && data.catalog && data.catalog.ideas) {
            currentCatalog.ideas = data.catalog.ideas;
          }
          // Disable approve/reject/regenerate buttons after rejection to prevent double-actions
          approveBtn.disabled = true;
          rejectBtn.disabled = true;
          if (regenerateBtn) regenerateBtn.disabled = true;
          checkAndEnableLockButton();
          // PIEZA 36 (bug 3): Update script button visibility if this is the current idea
          if (currentScriptIdeaId === ideaId) {
            updateScriptGenerateButton();
          }
        } catch (error) {
          console.error('Discard idea error:', error);
          alert(`Failed to discard idea: ${error.message}`);
        }
      });
    }

    if (regenerateBtn) {
      // Pieza 29 (punto D2): ↻ Regenerar (3 créditos) -- reemplaza la
      // tarjeta con la idea nueva y actualiza créditos, sin recargar el panel.
      regenerateBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const ideaId = regenerateBtn.dataset.ideaId;
        const originalText = regenerateBtn.innerHTML;
        regenerateBtn.disabled = true;
        regenerateBtn.innerHTML = '...';

        try {
          const response = await authenticatedFetch(`/api/catalog/idea/${ideaId}/regenerate`, { method: 'POST' });
          const data = await response.json();

          if (!response.ok) {
            alert(`Failed to regenerate idea: ${data.error || data.detail || response.status}`);
            regenerateBtn.disabled = false;
            regenerateBtn.innerHTML = originalText;
            return;
          }

          if (data.credits_remaining !== undefined) {
            credits = data.credits_remaining;
            // PIEZA 31 (bug B5): faltaban los argumentos -- updateCreditsUI()
            // sin remaining/initial dejaba el saldo mostrado como "undefined".
            updateCreditsUI(data.credits_remaining, initialSessionCredits);
          }

          const newIdea = data.idea;
          if (newIdea) {
            // El id cambia -- se reconstruye la tarjeta completa en el mismo lugar.
            const existingAngle = ideaDiv.querySelector('.angle');
            const color = (existingAngle && existingAngle.style.color) || '#2B4CD8';
            const catalogLocked = currentCatalog && currentCatalog.catalog_locked;
            ideaDiv.id = `idea-${newIdea.id}`;
            ideaDiv.className = `idea idea--${newIdea.status || 'pending'}`;
            // PIEZA 36 (bug 4): Add data-origin attribute to identify founder ideas in applyCatalogLockedUI()
            ideaDiv.dataset.origin = newIdea.origin || 'engine';
            ideaDiv.innerHTML = buildIdeaCardHTML(newIdea, color || '#2B4CD8', catalogLocked);
            wireIdeaCardActions(ideaDiv);
          }

          checkAndEnableLockButton();
        } catch (error) {
          console.error('Regenerate idea error:', error);
          alert(`Failed to regenerate idea: ${error.message}`);
          regenerateBtn.disabled = false;
          regenerateBtn.innerHTML = originalText;
        }
      });
    }

    // Block C: Event listener for script button
    if (scriptBtn) {
      scriptBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const ideaId = scriptBtn.dataset.ideaId;
        showBlockCView(ideaId);
      });
    }
  }

  // Helper to count ready confirmed sections
  function getReadySectionsCount(sections) {
    if (!sections || !Array.isArray(sections)) return 0;
    return sections.filter(s => {
      const st = (s.status || '').toLowerCase();
      const hasContent = s.content && Object.keys(s.content).length > 0;
      return (st === 'confirmado' || st === 'completado' || st === 'confirmed') && hasContent;
    }).length;
  }

  // Update Catalog button state based on confirmed sections count
  function updateCatalogButton(sections) {
    if (!catalogBtn || !catalogLabel) return;

    const confirmedCount = getReadySectionsCount(sections);
    catalogLabel.textContent = `Catalog — ${confirmedCount} of 9 sections ready`;

    if (confirmedCount >= 9) {
      catalogBtn.disabled = false;
    } else {
      catalogBtn.disabled = true;
    }
  }

  // Render Catalog in panel (BlockB view)
  function renderCatalogInPanel(catalog) {
    // PIEZA 31 (bug B6): guardar la referencia -- openCreditGateModal() la
    // usa para re-renderizar sin recargar cuando el catálogo ya existe.
    currentCatalog = catalog;

    const categoryNames = CATALOG_CATEGORY_NAMES;
    const categoryColors = CATALOG_CATEGORY_COLORS;

    let totalIdeas = 0;
    catalogCategories.innerHTML = '';

    const ideas = catalog.ideas || [];
    totalIdeas = ideas.length;

    // Group ideas by master_category
    const grouped = {};
    ideas.forEach(idea => {
      const catKey = idea.master_category || 'autoridad_tecnica';
      if (!grouped[catKey]) grouped[catKey] = [];
      grouped[catKey].push(idea);
    });

    Object.keys(grouped).forEach(catKey => {
      const catIdeas = grouped[catKey];
      const catName = categoryNames[catKey] || catKey;
      const color = categoryColors[catKey] || '#2B4CD8';

      const catDiv = document.createElement('div');
      catDiv.className = 'cat';
      catDiv.dataset.catKey = catKey; // Pieza 29 (punto D1): localizar la categoría al agregar una idea propia

      const catHead = document.createElement('div');
      catHead.className = 'cathead';
      catHead.innerHTML = `<span class="catname">${escapeHtml(catName)}</span><span class="catcount">${catIdeas.length}</span>`;
      catDiv.appendChild(catHead);

      catIdeas.forEach(idea => {
        const ideaDiv = document.createElement('div');
        ideaDiv.id = `idea-${idea.id}`;
        ideaDiv.className = `idea idea--${idea.status || 'pending'}`;
        // PIEZA 36 (bug 4): Add data-origin attribute to identify founder ideas in applyCatalogLockedUI()
        ideaDiv.dataset.origin = idea.origin || 'engine';
        ideaDiv.innerHTML = buildIdeaCardHTML(idea, color, catalog.catalog_locked);
        wireIdeaCardActions(ideaDiv);
        catDiv.appendChild(ideaDiv);
      });

      catalogCategories.appendChild(catDiv);
    });  // Fixed: was missing closing parenthesis for forEach

    // Pieza 29 (punto D4): si el catálogo ya llegó bloqueado desde el
    // backend (recarga de página), aplica el estado bloqueado de inmediato.
    if (catalog.catalog_locked) {
      applyCatalogLockedUI();
    } else {
      checkAndEnableLockButton();
    }

    // Pieza 30 (bug B3): los botones WebSearch/YouTube/Trends (y su listener
    // sobre /api/catalog/investigate) se eliminaron -- cobraban 25 créditos,
    // repetían la investigación del nicho entero y solo mostraban un alert.
    // El endpoint /api/catalog/investigate se queda intacto en el backend,
    // simplemente ya no se llama desde esta UI.

    // Add event listener for Lock Catalog button
    // PIEZA 31 (bug B7): renderCatalogInPanel() se llama en cada carga del
    // catálogo (generate, investigate, cache load, regenerate) y volvía a
    // agregar OTRO listener sobre el MISMO botón del DOM (nunca se recrea) --
    // N renders = N POST /api/catalog/lock + N alerts por un solo clic.
    // Mismo guard dataset.wired que ya usa AddIdea-SubmitBtn más abajo.
    const lockCatalogBtn = document.getElementById('Catalog-LockBtn');
    if (lockCatalogBtn && !lockCatalogBtn.dataset.wired) {
      lockCatalogBtn.dataset.wired = 'true';
      lockCatalogBtn.addEventListener('click', async (e) => {
        e.preventDefault();

        try {
          const response = await authenticatedFetch('/api/catalog/lock', {
            method: 'POST'
          });

          const data = await response.json();

          if (!response.ok) {
            alert(`Failed to lock catalog: ${data.error || data.detail || response.status}`);
            return;
          }

          // Pieza 29 (punto D4): deshabilita ✓ ✗ ↻ y el formulario, muestra
          // "Catálogo bloqueado ✓" -- se persiste solo (catalog_locked viene
          // del backend en cada carga, ver renderCatalogInPanel).
          applyCatalogLockedUI();

          // PIEZA 34 (bug 1): al bloquear, actualizar estado en memoria y re-renderizar
          // las tarjetas para que el botón de guion aparezca en ideas aprobadas.
          currentCatalog.catalog_locked = true;
          renderCatalogInPanel(currentCatalog);

          // BUG 3 (Pieza 35): REMOVED automatic navigation to Block C
          // CEO decision: founder stays in catalog and chooses manually

          // Show warning if no approved ideas (this was already in Pieza 34)
          const firstApprovedIdea = currentCatalog.ideas.find(i => i.status === 'approved');
          if (!firstApprovedIdea) {
            // Caso borde: catálogo bloqueado sin ideas aprobadas
            const lockBtn = document.getElementById('Catalog-LockBtn');
            if (lockBtn) {
              const warning = document.createElement('div');
              warning.style.cssText = 'margin: 12px 40px; padding: 12px 16px; background: #FFF6E5; border: 1px solid #EAB308; border-radius: 4px; color: #854D0E; font-size: 13px;';
              warning.textContent = 'Approve at least one idea to write a script';
              lockBtn.after(warning);
            }
          }

        } catch (error) {
          console.error('Lock catalog error:', error);
          alert(`Failed to lock catalog: ${error.message}`);
        }
      });
    }

    // Pieza 29 (punto D1): "Agregar idea propia" -- gratis, sin recargar el panel.
    const addIdeaSubmitBtn = document.getElementById('AddIdea-SubmitBtn');
    if (addIdeaSubmitBtn && !addIdeaSubmitBtn.dataset.wired) {
      addIdeaSubmitBtn.dataset.wired = 'true';
      addIdeaSubmitBtn.addEventListener('click', async (e) => {
        e.preventDefault();

        const titleInput = document.getElementById('AddIdea-Title');
        const categorySelect = document.getElementById('AddIdea-Category');
        const sourceInput = document.getElementById('AddIdea-Source');

        const title = (titleInput.value || '').trim();
        const masterCategory = categorySelect.value;
        const source = (sourceInput.value || '').trim();

        if (title.length < 5 || title.length > 200) {
          alert('El título debe tener entre 5 y 200 caracteres.');
          return;
        }
        if (source.length < 10) {
          alert('La fuente debe tener al menos 10 caracteres (¿de dónde sale esta idea?).');
          return;
        }

        addIdeaSubmitBtn.disabled = true;
        const originalText = addIdeaSubmitBtn.textContent;
        addIdeaSubmitBtn.textContent = 'Adding...';

        try {
          const response = await authenticatedFetch('/api/catalog/idea', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, master_category: masterCategory, source })
          });

          const data = await response.json();

          if (!response.ok) {
            alert(`Failed to add idea: ${data.error || data.detail || response.status}`);
            return;
          }

          const newCatalog = data.catalog;

          // BUG 2 (Pieza 35): update currentCatalog with backend response
          // The backend returns the complete updated catalog - use it as truth
          currentCatalog = newCatalog;

          const newIdea = newCatalog.ideas[newCatalog.ideas.length - 1];

          // Agrega la tarjeta a la categoría correcta sin recargar el panel entero.
          let catDiv = Array.from(catalogCategories.querySelectorAll('.cat')).find(
            div => div.dataset.catKey === masterCategory
          );
          if (!catDiv) {
            catDiv = document.createElement('div');
            catDiv.className = 'cat';
            catDiv.dataset.catKey = masterCategory;
            const catHead = document.createElement('div');
            catHead.className = 'cathead';
            catHead.innerHTML = `<span class="catname">${escapeHtml(CATALOG_CATEGORY_NAMES[masterCategory] || masterCategory)}</span><span class="catcount">0</span>`;
            catDiv.appendChild(catHead);
            catalogCategories.appendChild(catDiv);
          }

          const ideaDiv = document.createElement('div');
          ideaDiv.id = `idea-${newIdea.id}`;
          ideaDiv.className = `idea idea--${newIdea.status || 'approved'}`;
          // PIEZA 36 (bug 4): Add data-origin attribute to identify founder ideas in applyCatalogLockedUI()
          ideaDiv.dataset.origin = newIdea.origin || 'engine';
          ideaDiv.innerHTML = buildIdeaCardHTML(newIdea, CATALOG_CATEGORY_COLORS[masterCategory] || '#2B4CD8', newCatalog.catalog_locked);
          wireIdeaCardActions(ideaDiv);
          catDiv.appendChild(ideaDiv);

          const catCountEl = catDiv.querySelector('.catcount');
          if (catCountEl) catCountEl.textContent = String(catDiv.querySelectorAll('.idea').length);

          // Limpiar el formulario
          titleInput.value = '';
          sourceInput.value = '';

          checkAndEnableLockButton();

        } catch (error) {
          console.error('Add founder idea error:', error);
          alert(`Failed to add idea: ${error.message}`);
        } finally {
          addIdeaSubmitBtn.disabled = false;
          addIdeaSubmitBtn.textContent = originalText;
        }
      });
    }

    // PIEZA 31 (bug B1): CUALQUIER catálogo ya guardado (30 ideas o menos --
    // ej. uno viejo truncado, o uno con ideas descartadas) se muestra como
    // generado, nunca como "Ready to generate". Antes, un catálogo con
    // menos de 30 ideas caía en el `else if` de abajo, que dejaba el gate
    // en estado "Ready to generate" -- cada clic volvía a abrir el modal de
    // cobro y, si el founder lo aprobaba, /api/catalog/generate se llamaba
    // de nuevo. El backend (bug B1 fix en main.py) ya no cobra dos veces
    // para un catálogo existente, pero la UI tampoco debe OFRECER pagar de
    // nuevo por algo que ya existe.
    if (totalIdeas > 0) {
      catalogAlreadyGenerated = true;
      catalogGateTitle.textContent = 'Catalog ready';
      catalogGateSub.textContent = totalIdeas >= 30
        ? 'Your 30 brand ideas are already generated.'
        : `Your catalog is already generated (${totalIdeas} ideas).`;
      catalogGateCount.textContent = `${totalIdeas}/30`;
      catalogGate.style.background = '#F0F7FF';
      catalogGate.style.borderColor = '#2B4CD8';
    } else {
      catalogAlreadyGenerated = false;
      catalogGateTitle.textContent = 'No ideas yet';
      catalogGateSub.textContent = 'You need to build your catalog first. This is the research phase.';
      catalogGateCount.textContent = '0/30';
      catalogGate.style.background = '#FFF6E5';
      catalogGate.style.borderColor = 'var(--warn)';
    }

    // Update global progress indicator
    initGlobalProgress();
  }

  // Open credit gate inline modal (CEO specifies inline, not overlay)
  function openCreditGateModal() {
    // Prevent re-charging if catalog already generated
    if (catalogAlreadyGenerated) {
      renderCatalogInPanel(currentCatalog);
      return;
    }

    // Calculate balance after 15 credits
    const currentCredits = credits; // FIX: was 'remainingCredits' which is undefined
    const afterCredits = Math.max(0, currentCredits - 15);

    // Create or update inline modal within Catalog-Categories
    let inlineModal = document.getElementById('catalogInlineModal');
    if (!inlineModal) {
      inlineModal = document.createElement('div');
      inlineModal.id = 'catalogInlineModal';
      inlineModal.className = 'catalog-inline-modal';
    }

    inlineModal.innerHTML = `
      <div class="catalog-inline-content">
        <h3 class="catalog-inline-title">🔓 Unlock Your Brand Ideas</h3>
        <p class="catalog-inline-sub">Generate <strong>30 personalized brand ideas</strong> using your Brand Soul and content tools. Each idea includes demand signals and tailored research actions.</p>
        <div class="catalog-inline-cost">
          <span class="cost-label">Cost:</span>
          <span class="cost-value">15 credits</span>
          <span class="cost-cost-after">Balance after: ${afterCredits} credits</span>
        </div>
        <div class="catalog-inline-actions">
          <button id="catalogInlineApprove" class="btn-primary">Generate & Unlock</button>
          <button id="catalogInlineCancel" class="btn-secondary">Cancel</button>
        </div>
      </div>
    `;

    // Insert inline modal at the top of Catalog-Categories
    const catalogCategories = document.getElementById('Catalog-Categories');
    catalogCategories.insertBefore(inlineModal, catalogCategories.firstChild);

    // Wire up buttons
    document.getElementById('catalogInlineApprove').onclick = handleGateApprove;
    document.getElementById('catalogInlineCancel').onclick = () => {
      inlineModal.remove();
    };
  }

  // Close credit gate modal
  function closeCreditGateModal() {
    creditGateOverlay.style.display = 'none';
  }

  // Handle credit gate approval - generate catalog
  async function handleGateApprove() {
    // Close inline modal if exists
    const inlineModal = document.getElementById('catalogInlineModal');
    if (inlineModal) {
      inlineModal.remove();
    }

    try {
      // Show loading state
      catalogGateTitle.textContent = 'Generating...';
      catalogGateSub.textContent = 'Please wait while we create your brand ideas.';
      catalogGate.style.cursor = 'wait';
      catalogGate.style.opacity = '0.7';

      // Add timeout with AbortController
      const controller = new AbortController();
      const timeoutId = setTimeout(() => {
        controller.abort();
      }, 135000); // 135 seconds = 2 min 15 sec (slightly longer than backend 120s)

      // Create a fake progress counter to show activity
      let progressStep = 0;
      const progressInterval = setInterval(() => {
        progressStep = Math.min(progressStep + 1, 30);
        catalogGateCount.textContent = `${progressStep}/30`;
        if (progressStep >= 30) {
          clearInterval(progressInterval);
        }
      }, 3000); // Update every 3 seconds to simulate progress

      const response = await authenticatedFetch('/api/catalog/generate', {
        method: 'POST',
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      clearInterval(progressInterval);

      const data = await response.json();
      const body = data; // Mantener el objeto JSON completo

      if (!response.ok) {
        // Handle errors
        if (response.status === 400 && body.error) {
          // Check if Brand Soul is missing
          if (body.error.includes('Brand Soul')) {
            alert('Brand Soul is a prerequisite for generating your catalog. Please generate your Brand Soul first by clicking the "Brand Soul" button above the catalog section.');
            return;
          }

          // Check for incomplete brand brain (mensaje real del backend trae
          // "N of 9 sections confirmed" -- solo ESE caso especifico usa el
          // mensaje amigable de "brand brain incompleto"; cualquier otro 400
          // (ej. B3: 503 de storage no aplica aqui, pero un ValueError
          // distinto si lo hubiera) debe mostrar el error real, no fingir
          // que el problema es Brand Brain cuando no lo es -- PIEZA 31 (bug
          // menor): antes CUALQUIER 400 que no mencionara "Brand Soul" caia
          // aqui y mentia "Your brand brain is incomplete" sin importar la
          // causa real.
          const match = body.error.match(/(\d+)\s*of\s*9/);
          if (match) {
            const confirmed = parseInt(match[1]);
            const missing = 9 - confirmed;
            alert(`Your brand brain is incomplete. ${missing} section${missing > 1 ? 's' : ''} need${missing > 1 ? '' : 's'} to be confirmed before generating your catalog. Keep talking with Brandy to complete them.`);
          } else {
            alert(`Failed to generate catalog: ${body.error}`);
          }
        } else if (response.status === 402) {
          alert('Not enough credits to generate catalog. Please purchase more credits to continue.');
        } else if (response.status === 429) {
          alert("You've reached the rate limit. Please wait a minute before trying again.");
        } else {
          alert(`Failed to generate catalog: ${body.error || body || response.status}`);
        }

        // Reset gate state
        catalogGateTitle.textContent = 'No ideas yet';
        catalogGateSub.textContent = 'You need to build your catalog first. This is the research phase.';
        catalogGateCount.textContent = '0/30';
        return;
      }

      // Success - render catalog
      renderCatalogInPanel(data.catalog);

      // Update credits display if included in response
      if (data.credits_remaining !== undefined) {
        updateCreditsUI(data.credits_remaining, initialSessionCredits);
      }

      console.log('[Catalog] Document generated successfully');

    } catch (error) {
      console.error('[Catalog] Loading error:', error);

      // Handle timeout specifically
      if (error.name === 'AbortError') {
        alert('Catalog generation timed out. The external APIs may be slow or unavailable. Please try again.');
      } else {
        alert('Failed to load catalog: ' + error.message);
      }

      // Reset gate state
      catalogGateTitle.textContent = 'No ideas yet';
      catalogGateSub.textContent = 'You need to build your catalog first. This is the research phase.';
      catalogGateCount.textContent = '0/30';
    } finally {
      catalogGate.style.cursor = 'pointer';
      catalogGate.style.opacity = '1';
    }
  }

  // Show BlockA view (original ghost sections)
  function showBlockAView() {
    blockAView.style.display = 'block';
    blockBView.style.display = 'none';
    blockCView.style.display = 'none';
  }

  // Show BlockB view (catalog)
  function showBlockBView() {
    blockAView.style.display = 'none';
    blockBView.style.display = 'block';
    blockCView.style.display = 'none';
  }

  // Show BlockC view (script) with empty state for interview mode
  function showBlockCView(ideaId) {
    // Track current idea ID
    currentScriptIdeaId = ideaId;

    // Find the idea data from current catalog
    const idea = currentCatalog?.ideas?.find(i => i.id === ideaId);
    if (!idea) {
      alert('Idea not found in catalog');
      return;
    }

    // Switch view
    blockAView.style.display = 'none';
    blockBView.style.display = 'none';
    blockCView.style.display = 'block';

    // Set idea title
    scriptIdeaTitle.textContent = idea.title;

    // Check if script already exists for this idea
    loadScriptData(ideaId);
  }

  // Block C: Load script data for an idea
  async function loadScriptData(ideaId) {
    try {
      const response = await authenticatedFetch(`/api/script/${ideaId}`, {
        method: 'GET'
      });

      if (response.status === 404) {
        // Script doesn't exist yet - show empty state
        showScriptEmptyState();
        return;
      }

      if (!response.ok) {
        const data = await response.json();
        alert(`Failed to load script: ${data.error || data.detail || response.status}`);
        showScriptEmptyState();
        return;
      }

      const scriptData = await response.json();
      // Backend returns {"script": {...}}
      currentScriptData = scriptData.script || scriptData;
      renderScript();
      initGlobalProgress();
    } catch (error) {
      console.error('Load script error:', error);
      alert(`Failed to load script: ${error.message}`);
      showScriptEmptyState();
      initGlobalProgress();
    }
  }

  // Block C: Show empty state (generate form)
  function showScriptEmptyState() {
    currentScriptData = null;
    scriptMeta.style.display = 'none';
    scriptEmptyState.style.display = 'block';
    scriptFrameZero.style.display = 'none';
    scriptScenes.style.display = 'none';
    scriptAudit.style.display = 'none';
    scriptLockBtn.disabled = true;

    // Enable/disable generate button based on transcript availability
    updateScriptGenerateButton();
  }

  // Block C: Update generate button state based on transcript
  function updateScriptGenerateButton() {
    if (!scriptGenerateBtn) return;
    // Pieza 36B (fallo 1): Use cachedBrain from module state, NOT currentScriptData which is null in empty state
    const sourceMode = scriptSourceMode?.value || 'brand_brain';
    const hasTranscript = fullTranscript && Array.isArray(fullTranscript) && fullTranscript.length > 0;
    // Brand Brain exists if cachedBrain has confirmed sections or any sections at all
    const hasBrandBrain = cachedBrain && cachedBrain.sections && cachedBrain.sections.length > 0;
    // NYC: Client-side HORROR. Where, oh where, does currentCatalog.touch了这个飘渺的存在 (catalog locked state)
    // Answer: It is read from server response onCatalogResponse and then the variable is set like flat.
    // But that variable is... actually ... an updated replica of response.catalog, with .catalog_locked property
    // That's used later here. UGH! For now we recompute it by checking the Catalog-LockBtn element - it's the only persistent UI for locking.
    const lockBtn = document.getElementById('Catalog-LockBtn');
    const catalogLocked = lockBtn && lockBtn.dataset.locked === 'true';

    // Disable if catalog is not locked (most likely scenario when this is called)
    if (!catalogLocked) {
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.title = 'Catalog must be locked to generate scripts';
      if (scriptGenerateHelp) {
        scriptGenerateHelp.style.display = 'block';
        scriptGenerateHelp.textContent = 'Lock the catalog in Block C (Idea Catalog) first';
      }
      return;
    }

    if (sourceMode === 'raw_footage') {
      // Raw footage mode: founder already has material, never depends on transcript
      scriptGenerateBtn.disabled = false;
      scriptGenerateBtn.title = '';
      // Pieza 36B (fallo 3): No help message needed when enabled
      if (scriptGenerateHelp) scriptGenerateHelp.style.display = 'none';
    } else if (sourceMode === 'brand_brain') {
      // Brand Brain mode: need either transcript OR brand brain
      scriptGenerateBtn.disabled = !hasTranscript && !hasBrandBrain;
      scriptGenerateBtn.title = scriptGenerateBtn.disabled ? 'Need transcript or Brand Brain' : '';
      // Pieza 36B (fallo 3): Show concrete help message only when disabled
      if (scriptGenerateHelp) {
        if (scriptGenerateBtn.disabled) {
          // No transcript, no Brand Brain: need to talk to Brandy first
          scriptGenerateHelp.style.display = 'block';
          scriptGenerateHelp.textContent = 'Talk to Brandy about this idea first to enable assisted generation';
        } else {
          scriptGenerateHelp.style.display = 'none';
        }
      }
    } else {
      // Unknown mode: disable
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.title = 'Unknown generation mode';
      if (scriptGenerateHelp) scriptGenerateHelp.style.display = 'none';
    }
  }

  // ==================== Block C Render Functions ====================

  // Phase name mapping
  const PHASE_NAMES = {
    hook: 'Hook',
    lock_in: 'Lock-in',
    body_1: 'Point 1',
    rehook: 'Rehook',
    body_2: 'Point 2',
    close_cta: 'Close & CTA'
  };

  // Asset type name mapping
  const ASSET_TYPE_NAMES = {
    a_roll: 'You on camera',
    stock: 'Stock footage',
    ai_image: 'AI image',
    ai_video: 'AI video',
    motion_graphic: 'Motion graphic'
  };

  // Recording format name mapping
  const RECORDING_FORMAT_NAMES = {
    selfie_natural: 'Selfie (natural)',
    pov: 'Point of view',
    dramatization: 'Dramatization',
    teleprompter_clean: 'Teleprompter (clean)',
    dynamic: 'Dynamic'
  };

  // PIEZA 42: State display names
  const STATE_DISPLAY_NAMES = {
    'draft': 'Draft',
    'reviewed': 'Reviewed',
    'locked': 'Locked'
  };

  // PIEZA 42: Funnel stage display names
  const FUNNEL_STAGE_NAMES = {
    'tofu': 'Awareness (ToFu)',
    'mofu': 'Consideration (MoFu)',
    'bofu': 'Decision (BoFu)'
  };

  // PIEZA 42: Get state transition hint
  function getStateHint(state) {
    switch (state) {
      case 'draft':
        return 'Confirm funnel stage and recording format to proceed to Reviewed';
      case 'reviewed':
        return 'Ready to lock when all critical rules pass';
      case 'locked':
        return 'Script is locked for recording';
      default:
        return '';
    }
  }

  function renderScript() {
    scriptEmptyState.style.display = 'none';
    scriptContent.style.display = 'block';
    scriptGenerateBtn.style.display = 'none';
    scriptMeta.style.display = 'block';

    // PIEZA 42: Render state badge and hint
    const state = currentScriptData.state || 'draft';
    const stateName = STATE_DISPLAY_NAMES[state] || state;
    const stateHint = getStateHint(state);
    const stateColor = state === 'locked' ? '#1B7F4C' : (state === 'reviewed' ? '#B5720B' : '#2B4CD8');

    // Build meta panel with state prominently displayed
    let metaHtml = `
      <div style="margin-bottom:16px;padding:16px;border:1px solid #E2E8F0;border-radius:8px;background:#FAFAFA">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap">
          <span style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675">Script State</span>
          <span style="padding:4px 12px;border-radius:4px;background:${stateColor};color:#fff;font-weight:600;font-size:13px">${escapeHtml(stateName)}</span>
          ${state === 'locked' ? '<span style="font-size:13px;color:#1B7F4C;font-weight:500">✓ Ready for recording</span>' : ''}
        </div>
        <div style="font-size:13px;color:#5C6675;line-height:1.5">
          ${escapeHtml(stateHint)}
        </div>
      </div>
    `;

    // Add "Review before recording" panel if in draft or reviewed state
    if (state !== 'locked') {
      const proposedFunnel = currentScriptData.funnel_stage || 'tofu';
      const proposedFormat = currentScriptData.recording_format || 'selfie_natural';

      metaHtml += `
        <div id="Script-ReviewPanel" style="margin-bottom:16px;padding:16px;border:1px solid #2B4CD8;border-radius:8px;background:#F0F7FF">
          <div style="font-size:14px;font-weight:600;color:#14181F;margin-bottom:12px">Review before recording</div>

          <div style="margin-bottom:12px">
            <label style="display:block;font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:6px">Funnel Stage</label>
            <select id="Review-FunnelStage" style="width:100%;padding:8px;border:1px solid #D5DAE4;border-radius:4px;font-family:inherit;font-size:13px">
              <option value="tofu" ${proposedFunnel === 'tofu' ? 'selected' : ''}>Awareness (ToFu)</option>
              <option value="mofu" ${proposedFunnel === 'mofu' ? 'selected' : ''}>Consideration (MoFu)</option>
              <option value="bofu" ${proposedFunnel === 'bofu' ? 'selected' : ''}>Decision (BoFu)</option>
            </select>
          </div>

          <div style="margin-bottom:12px">
            <label style="display:block;font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:6px">Recording Format</label>
            <select id="Review-RecordingFormat" style="width:100%;padding:8px;border:1px solid #D5DAE4;border-radius:4px;font-family:inherit;font-size:13px">
              <option value="selfie_natural" ${proposedFormat === 'selfie_natural' ? 'selected' : ''}>Natural selfie</option>
              <option value="pov" ${proposedFormat === 'pov' ? 'selected' : ''}>POV (Point of view)</option>
              <option value="dramatization" ${proposedFormat === 'dramatization' ? 'selected' : ''}>Dramatization</option>
              <option value="teleprompter_clean" ${proposedFormat === 'teleprompter_clean' ? 'selected' : ''}>Teleprompter (clean background)</option>
              <option value="dynamic" ${proposedFormat === 'dynamic' ? 'selected' : ''}>Dynamic</option>
            </select>
          </div>

          <button id="Review-ConfirmBtn" class="btn btn--go" style="width:100%;padding:10px;font-size:13px">Confirm & Move to Reviewed</button>
          <div style="margin-top:8px;font-size:11px;color:#5C6675;text-align:center">Free — no credits charged</div>
        </div>
      `;
    }

    // Add basic metadata grid
    metaHtml += `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:4px">Angle</div>
          <div id="Script-Angle" style="font-weight:500;color:#14181F">${escapeHtml(currentScriptData.angle || '—')}</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:4px">Funnel</div>
          <div id="Script-FunnelStage" style="font-weight:500;color:#14181F">${escapeHtml(FUNNEL_STAGE_NAMES[currentScriptData.funnel_stage] || currentScriptData.funnel_stage || '—')}</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:4px">Duration</div>
          <div id="Script-Duration" style="font-weight:500;color:#14181F">${currentScriptData.target_seconds ? `${currentScriptData.target_seconds}s` : '—'}</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:4px">Format</div>
          <div id="Script-RecordingFormat" style="font-weight:500;color:#14181F">${escapeHtml(RECORDING_FORMAT_NAMES[currentScriptData.recording_format] || currentScriptData.recording_format || '—')}</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:4px">Music</div>
          <div id="Script-MusicPrompt" style="font-weight:500;color:#14181F;font-size:12px">${escapeHtml(currentScriptData.music_prompt ? currentScriptData.music_prompt : '—')}</div>
        </div>
      </div>
    `;

    scriptMeta.innerHTML = metaHtml;

    // PIEZA 42: Wire up review panel confirm button if present
    const confirmBtn = document.getElementById('Review-ConfirmBtn');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', handleScriptConfirm);
    }

    // Re-bind DOM references that were replaced
    scriptAngle = document.getElementById('Script-Angle');
    scriptFunnelStage = document.getElementById('Script-FunnelStage');
    scriptDuration = document.getElementById('Script-Duration');
    scriptRecordingFormat = document.getElementById('Script-RecordingFormat');
    scriptMusicPrompt = document.getElementById('Script-MusicPrompt');

    // Render Frame Zero
    scriptFrameZero.style.display = 'block';
    if (scriptFrameZeroContent) {
      scriptFrameZeroContent.textContent = currentScriptData.frame_zero || 'Frame zero not set';
    }

    // Render Scenes
    scriptScenes.style.display = 'block';
    renderScenes();

    // Render Audit
    scriptAudit.style.display = 'block';
    renderAudit();

    // Update Lock Button
    updateScriptLockButton();

    // Update global progress
    initGlobalProgress();
  }

  // PIEZA 42: Handle script confirmation (PATCH /api/script/{idea_id})
  async function handleScriptConfirm() {
    const funnelSelect = document.getElementById('Review-FunnelStage');
    const formatSelect = document.getElementById('Review-RecordingFormat');

    if (!funnelSelect || !formatSelect) return;

    const funnelStage = funnelSelect.value;
    const recordingFormat = formatSelect.value;

    try {
      const response = await authenticatedFetch(`/api/script/${currentScriptData.idea_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ funnel_stage: funnelStage, recording_format: recordingFormat }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || data.detail || response.statusText || 'Failed to confirm script');
      }

      const data = await response.json();
      // PIEZA 42: Update from backend response (source of truth)
      currentScriptData = data.script || data;
      renderScript();

    } catch (error) {
      console.error('Script confirm error:', error);
      alert(`Failed to confirm script: ${error.message}`);
    }
  }

  function formatTime(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function renderScenes() {
    scriptScenes.innerHTML = '';
    if (!currentScriptData.scenes || currentScriptData.scenes.length === 0) {
      scriptScenes.innerHTML = '<div class="script-scenes-empty">No scenes yet</div>';
      return;
    }

    currentScriptData.scenes.forEach((scene, idx) => {
      const sceneEl = document.createElement('div');
      const phase = scene.phase || '';
      const isHook = phase === 'hook';

      sceneEl.className = 'script-scene' + (isHook ? ' hook' : '');
      sceneEl.dataset.sceneIndex = idx;

      // Calculate time range
      const startTime = formatTime(scene.start_s);
      const endTime = formatTime(scene.end_s);
      const timeRange = (scene.start_s !== null && scene.start_s !== undefined &&
                         scene.end_s !== null && scene.end_s !== undefined)
                        ? `${startTime}–${endTime}` : '—';

      // Phase display name
      const phaseName = PHASE_NAMES[phase] || (phase ? phase.replace(/_/g, ' ') : 'Scene');

      // Asset type display name
      const assetType = scene.asset_type || '';
      const assetTypeName = ASSET_TYPE_NAMES[assetType] || (assetType ? assetType.replace(/_/g, ' ') : '—');

      // Build main content
      let html = '';

      // Header: phase name, time estimate, regenerate button
      html += `
        <div class="script-scene-header">
          <span class="script-scene-phase ${isHook ? 'hook' : ''}">${escapeHtml(phaseName)}</span>
          <span class="script-scene-time">
            ${escapeHtml(timeRange)}
            <span class="est-label">est.</span>
          </span>
          <button class="script-scene-regenerate" title="Regenerate this scene">⟳</button>
        </div>
      `;

      // Spoken text (editable)
      html += `
        <div class="script-scene-content" contenteditable="true">${escapeHtml(scene.spoken_text || '')}</div>
      `;

      // Acting note - highlighted for hook
      if (scene.acting_note) {
        html += `
          <div class="script-scene-acting-note ${isHook ? 'hook' : ''}">
            <div class="script-scene-acting-label">How to say it</div>
            <div class="script-scene-acting-text">${escapeHtml(scene.acting_note)}</div>
          </div>
        `;
      }

      // Technical line: subtitle and shot
      const hasSubtitle = scene.on_screen_text !== null && scene.on_screen_text !== undefined && scene.on_screen_text !== '';
      const hasShot = scene.shot !== null && scene.shot !== undefined && scene.shot !== '';
      if (hasSubtitle || hasShot) {
        html += '<div class="script-scene-tech">';
        if (hasSubtitle) {
          html += `<div class="script-scene-tech-item"><span class="script-scene-tech-label">Subtitle:</span> ${escapeHtml(scene.on_screen_text)}</div>`;
        }
        if (hasShot) {
          html += `<div class="script-scene-tech-item"><span class="script-scene-tech-label">Shot:</span> ${escapeHtml(scene.shot)}</div>`;
        }
        html += '</div>';
      }

      // Visual & assets accordion
      html += '<div class="script-scene-visual">';
      html += '<button class="script-scene-visual-toggle" type="button">';
      html += '<span>Visual & assets</span>';
      html += '<span class="toggle-icon">▸</span>';
      html += '</button>';
      html += '<div class="script-scene-visual-content">';
      html += '<div class="script-scene-visual-grid">';

      // Asset type
      html += `
        <div class="script-scene-visual-row">
          <div class="script-scene-visual-label">Asset Type</div>
          <div class="script-scene-visual-value">${escapeHtml(assetTypeName)}</div>
        </div>
      `;

      // B-roll
      const bRollValue = (scene.b_roll !== null && scene.b_roll !== undefined) ? scene.b_roll : null;
      html += `
        <div class="script-scene-visual-row">
          <div class="script-scene-visual-label">B-roll</div>
          <div class="script-scene-visual-value ${bRollValue ? '' : 'null'}">${bRollValue ? escapeHtml(bRollValue) : '—'}</div>
        </div>
      `;

      // Sound
      const soundValue = (scene.sound !== null && scene.sound !== undefined) ? scene.sound : null;
      html += `
        <div class="script-scene-visual-row">
          <div class="script-scene-visual-label">Sound</div>
          <div class="script-scene-visual-value ${soundValue ? '' : 'null'}">${soundValue ? escapeHtml(soundValue) : '—'}</div>
        </div>
      `;

      // Stock query
      const stockQueryValue = (scene.stock_query !== null && scene.stock_query !== undefined) ? scene.stock_query : null;
      html += `
        <div class="script-scene-visual-row">
          <div class="script-scene-visual-label">Stock Search</div>
          <div class="script-scene-visual-value ${stockQueryValue ? '' : 'null'}">${stockQueryValue ? escapeHtml(stockQueryValue) : '—'}</div>
        </div>
      `;

      // Visual prompt
      const visualPromptValue = (scene.visual_prompt !== null && scene.visual_prompt !== undefined) ? scene.visual_prompt : null;
      html += `
        <div class="script-scene-visual-row script-scene-visual-full">
          <div class="script-scene-visual-label">Visual Prompt</div>
          <div class="script-scene-visual-value ${visualPromptValue ? '' : 'null'}">
            ${visualPromptValue ? `<div class="script-scene-visual-prompt">${escapeHtml(visualPromptValue)}</div>` : '—'}
          </div>
        </div>
      `;

      html += '</div></div></div>';

      sceneEl.innerHTML = html;
      scriptScenes.appendChild(sceneEl);
    });

    wireSceneEvents();
  }

  function wireSceneEvents() {
    const sceneContents = scriptScenes.querySelectorAll('.script-scene-content');
    sceneContents.forEach((contentEl) => {
      const sceneIdx = parseInt(contentEl.closest('.script-scene').dataset.sceneIndex);

      // Debounced PATCH on blur/input
      let editTimeout;
      contentEl.addEventListener('input', () => {
        clearTimeout(editTimeout);
        editTimeout = setTimeout(() => handleScriptSceneEdit(sceneIdx, contentEl.innerText), 1500);
      });
      contentEl.addEventListener('blur', () => {
        clearTimeout(editTimeout);
        handleScriptSceneEdit(sceneIdx, contentEl.innerText);
      });
    });

    // PIEZA 42: Regenerate buttons — show inline form instead of confirm()
    const regenerateBtns = scriptScenes.querySelectorAll('.script-scene-regenerate');
    regenerateBtns.forEach((btn) => {
      const sceneIdx = parseInt(btn.closest('.script-scene').dataset.sceneIndex);
      btn.addEventListener('click', () => {
        showRegenerateForm(sceneIdx, btn);
      });
    });

    // Accordion toggles for Visual & assets
    const toggles = scriptScenes.querySelectorAll('.script-scene-visual-toggle');
    toggles.forEach((toggle) => {
      toggle.addEventListener('click', () => {
        const content = toggle.nextElementSibling;
        const isExpanded = content.classList.contains('expanded');
        content.classList.toggle('expanded', !isExpanded);
        toggle.classList.toggle('expanded', !isExpanded);
      });
    });
  }

  function renderAudit() {
    scriptAudit.innerHTML = '';
    if (!currentScriptData.audit || currentScriptData.audit.length === 0) {
      scriptAudit.innerHTML = '<div class="script-audit-empty">No audit records</div>';
      return;
    }

    const auditList = document.createElement('ul');
    auditList.className = 'script-audit-list';
    currentScriptData.audit.forEach((entry) => {
      const li = document.createElement('li');
      li.className = 'script-audit-item';
      li.innerHTML = `<span class="audit-rule">${escapeHtml(entry.rule)}</span>: ${escapeHtml(entry.message || 'Check passed')}`;
      auditList.appendChild(li);
    });
    scriptAudit.appendChild(auditList);
  }

  function updateScriptLockButton() {
    if (!currentScriptData) {
      scriptLockBtn.disabled = true;
      return;
    }

    const isLocked = currentScriptData.state === 'locked';
    const isReviewed = currentScriptData.state === 'reviewed';

    // PIEZA 42B: Lock is final - when locked, button shows "Locked" and is disabled
    if (isLocked) {
      scriptLockBtn.textContent = 'Locked — ready to record';
      scriptLockBtn.disabled = true;
      scriptLockBtn.dataset.locked = 'true';
      scriptLockBtn.title = 'Script is locked for recording';
      return;
    }

    scriptLockBtn.textContent = 'Lock Script';
    scriptLockBtn.dataset.locked = 'false';

    // PIEZA 42: Can only lock from "reviewed" state
    if (!isReviewed) {
      scriptLockBtn.disabled = true;
      scriptLockBtn.title = 'Confirm funnel stage and recording format before locking';
      return;
    }

    // PIEZA 42B: Check critical rules from backend (uses 'critical' field, not hardcoded list)
    let failedCriticalRule = null;

    if (currentScriptData.audit) {
      const failedCritical = currentScriptData.audit.find((a) => a.status === 'fail' && a.critical === true);
      if (failedCritical) {
        failedCriticalRule = failedCritical.rule;
      }
    }

    if (failedCriticalRule) {
      scriptLockBtn.disabled = true;
      scriptLockBtn.title = `Cannot lock: ${failedCriticalRule} must pass`;
    } else {
      scriptLockBtn.disabled = false;
      scriptLockBtn.title = '';
    }
  }

  // PIEZA 42B: Helper to update script UI without rebuilding scenes (preserves text editor focus)
  function updateScriptUIWithoutRebuildingScenes() {
    // Update state badge and hint
    const state = currentScriptData.state || 'draft';
    const stateName = STATE_DISPLAY_NAMES[state] || state;
    const stateHint = getStateHint(state);
    const stateColor = state === 'locked' ? '#1B7F4C' : (state === 'reviewed' ? '#B5720B' : '#2B4CD8');

    // Update only the state badge in meta panel
    const metaPanel = scriptMeta.querySelector('div');
    if (metaPanel) {
      const stateBadge = metaPanel.querySelector('span[style*="background:"]');
      if (stateBadge) {
        stateBadge.style.background = stateColor;
        stateBadge.textContent = stateName;
      }
      const hintDiv = metaPanel.querySelector('div:last-child');
      if (hintDiv) {
        hintDiv.textContent = stateHint;
      }
    }

    // Update metadata grid values (without rebuilding)
    if (scriptAngle) scriptAngle.textContent = currentScriptData.angle || '—';
    if (scriptFunnelStage) scriptFunnelStage.textContent = FUNNEL_STAGE_NAMES[currentScriptData.funnel_stage] || currentScriptData.funnel_stage || '—';
    if (scriptDuration) scriptDuration.textContent = currentScriptData.target_seconds ? `${currentScriptData.target_seconds}s` : '—';
    if (scriptRecordingFormat) scriptRecordingFormat.textContent = RECORDING_FORMAT_NAMES[currentScriptData.recording_format] || currentScriptData.recording_format || '—';
    if (scriptMusicPrompt) scriptMusicPrompt.textContent = currentScriptData.music_prompt ? currentScriptData.music_prompt : '—';

    // Update review panel visibility (show/hide based on state)
    const reviewPanel = document.getElementById('Script-ReviewPanel');
    if (reviewPanel) {
      if (state === 'locked') {
        reviewPanel.style.display = 'none';
      }
    }

    // Update audit and lock button
    renderAudit();
    updateScriptLockButton();
  }

  async function handleScriptSceneEdit(sceneIdx, newContent) {
    try {
      // Backend expects scene_n (1-indexed)
      const sceneN = sceneIdx + 1;
      const response = await authenticatedFetch(`/api/script/${currentScriptData.idea_id}/scene/${sceneN}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spoken_text: newContent }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || data.detail || response.statusText || 'Failed to save edit');
      }

      const data = await response.json();
      // PIEZA 42B: Update from backend response (source of truth)
      currentScriptData = data.script || data;
      // PIEZA 42B: Update only UI parts that may have changed (state, audit, button)
      // Do NOT rebuild scenes - the founder is still typing in the contenteditable
      updateScriptUIWithoutRebuildingScenes();
    } catch (error) {
      console.error('Scene edit error:', error);
      alert(`Failed to save edit: ${error.message}`);
    }
  }

  // PIEZA 42: Handle script scene regeneration with instruction
  async function handleScriptRegenerate(sceneIdx, instruction) {
    try {
      // Backend expects scene_n (1-indexed)
      const sceneN = sceneIdx + 1;
      const response = await authenticatedFetch(`/api/script/${currentScriptData.idea_id}/scene/${sceneN}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: instruction || '' }),
      });

      if (response.status === 402) {
        alert('Insufficient credits to regenerate scene (costs 2 credits).');
        return;
      }

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || data.detail || data.message || response.statusText || 'Failed to regenerate scene');
      }

      // PIEZA 42: Update from backend response (source of truth)
      currentScriptData = data.script || data;
      renderScenes();
      renderAudit();
      updateScriptLockButton();
      renderScript(); // Re-render to update state if it changed
    } catch (error) {
      console.error('Scene regenerate error:', error);
      alert(`Failed to regenerate scene: ${error.message}`);
    }
  }

  // PIEZA 42: Show inline regenerate form for a scene
  function showRegenerateForm(sceneIdx, buttonEl) {
    const sceneEl = buttonEl.closest('.script-scene');
    if (!sceneEl) return;

    // Prevent duplicate forms
    const existingForm = sceneEl.querySelector('.scene-regenerate-form');
    if (existingForm) {
      existingForm.remove();
      activeRegenerateForms.delete(sceneIdx);
      return;
    }

    // Clear any other active forms
    document.querySelectorAll('.scene-regenerate-form').forEach(f => f.remove());
    activeRegenerateForms.clear();
    activeRegenerateForms.add(sceneIdx);

    const formHtml = `
      <div class="scene-regenerate-form" style="margin:12px 0;padding:16px;border:1px solid #D5DAE4;border-radius:8px;background:#FAFAFA">
        <div style="font-size:13px;font-weight:500;color:#14181F;margin-bottom:12px">Regenerate Scene — 2 credits</div>

        <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
          <button type="button" class="regenerate-preset" data-preset="Make it shorter and more concise" style="padding:6px 12px;border:1px solid #D5DAE4;border-radius:4px;background:#fff;font-size:12px;cursor:pointer">
            Shorter
          </button>
          <button type="button" class="regenerate-preset" data-preset="Make it punchier and more direct" style="padding:6px 12px;border:1px solid #D5DAE4;border-radius:4px;background:#fff;font-size:12px;cursor:pointer">
            Punchier
          </button>
        </div>

        <div style="margin-bottom:12px">
          <label style="display:block;font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:#5C6675;margin-bottom:6px">Custom instruction (optional)</label>
          <textarea class="regenerate-custom" rows="2" placeholder="e.g., More energy, slower pace..." style="width:100%;padding:8px;border:1px solid #D5DAE4;border-radius:4px;font-family:inherit;font-size:13px;resize:vertical"></textarea>
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button type="button" class="regenerate-cancel" style="padding:6px 12px;border:1px solid #D5DAE4;border-radius:4px;background:#fff;font-size:12px;cursor:pointer">Cancel</button>
          <button type="button" class="regenerate-confirm btn btn--go" style="padding:6px 16px;font-size:12px">Regenerate (2 credits)</button>
        </div>
      </div>
    `;

    // Insert after the button's parent (script-scene-header)
    const header = buttonEl.closest('.script-scene-header');
    if (header) {
      header.insertAdjacentHTML('afterend', formHtml);
    } else {
      buttonEl.insertAdjacentHTML('afterend', formHtml);
    }

    // Wire up form events
    const form = sceneEl.querySelector('.scene-regenerate-form');
    const customInput = form.querySelector('.regenerate-custom');
    const confirmBtn = form.querySelector('.regenerate-confirm');
    const cancelBtn = form.querySelector('.regenerate-cancel');
    const presetBtns = form.querySelectorAll('.regenerate-preset');

    let selectedPreset = '';

    presetBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        presetBtns.forEach(b => {
          b.style.background = '#fff';
          b.style.borderColor = '#D5DAE4';
        });
        btn.style.background = '#F0F7FF';
        btn.style.borderColor = '#2B4CD8';
        selectedPreset = btn.dataset.preset;
        customInput.value = selectedPreset;
      });
    });

    cancelBtn.addEventListener('click', () => {
      form.remove();
      activeRegenerateForms.delete(sceneIdx);
    });

    confirmBtn.addEventListener('click', async () => {
      const instruction = customInput.value.trim();
      form.remove();
      activeRegenerateForms.delete(sceneIdx);
      await handleScriptRegenerate(sceneIdx, instruction);
    });
  }

  // PIEZA 42B: Show inline message near the lock button (replaces alert)
  function showLockMessage(message, isError = false) {
    // Remove any existing message
    const existingMsg = document.getElementById('Script-LockMessage');
    if (existingMsg) {
      existingMsg.remove();
    }

    const msgDiv = document.createElement('div');
    msgDiv.id = 'Script-LockMessage';
    msgDiv.style.cssText = `
      margin-top: 12px;
      padding: 10px 16px;
      border-radius: 4px;
      font-size: 13px;
      ${isError ? 'background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5;' : 'background: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7;'}
    `;
    msgDiv.textContent = message;

    // Insert after the lock button
    if (scriptLockBtn && scriptLockBtn.parentNode) {
      scriptLockBtn.parentNode.insertBefore(msgDiv, scriptLockBtn.nextSibling);
    }

    // Auto-remove success messages after 5 seconds
    if (!isError) {
      setTimeout(() => {
        msgDiv.remove();
      }, 5000);
    }
  }

  // PIEZA 42B: Handle script locking (lock is final, no unlock)
  async function handleScriptLock() {
    // PIEZA 42B: Lock is final - if already locked, this shouldn't be callable
    // (button is disabled), but guard just in case
    if (currentScriptData?.state === 'locked') {
      showLockMessage('Script is already locked.', true);
      return;
    }

    try {
      const response = await authenticatedFetch(`/api/script/${currentScriptData.idea_id}/lock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || data.detail || response.statusText || 'Failed to lock script');
      }

      const data = await response.json();
      // Backend returns {"script": {...}, "status": "locked"}
      currentScriptData = data.script || data;
      renderScript();
      showLockMessage('Script locked successfully.', false);
    } catch (error) {
      console.error('Lock script error:', error);
      showLockMessage(`Failed to lock script: ${error.message}`, true);
    }
  }

  // Global progress indicator
  function initGlobalProgress() {
    // Find progress steps by data-step attribute
    const progressSteps = document.querySelectorAll('.progress-step');

    // Track brand brain sections (section 01-09)
    const brainSectionsCount = Object.keys(cachedBrain || {}).filter(k => k.startsWith('section_')).length;

    // Brain step: complete if all 9 sections have data
    const brainComplete = brainSectionsCount >= 9;
    updateProgressStep('brain', brainComplete);

    // Catalog step: complete if catalog exists and is locked
    const catalogComplete = currentCatalog && currentCatalog.catalog_locked;
    updateProgressStep('catalog', catalogComplete);

    // Script step: complete if current script exists and is locked
    const scriptComplete = currentScriptData && currentScriptData.state === 'locked';
    updateProgressStep('script', scriptComplete);

    // Video step: always pending
    updateProgressStep('video', false);
  }

  function updateProgressStep(step, isComplete) {
    const progressStep = document.querySelector(`.progress-step[data-step="${step}"]`);
    if (!progressStep) return;

    const progressFill = progressStep.querySelector('.progress-fill');
    if (progressFill) {
      progressFill.style.width = isComplete ? '100%' : '0%';
    }
  }

  // Load cache and show catalog
  async function loadCatalogCache() {
    try {
      catalogProgress.textContent = 'Loading...';

      const cacheResponse = await authenticatedFetch('/api/catalog', {
        method: 'GET'
      });

      if (cacheResponse.ok) {
        const cacheData = await cacheResponse.json();
        renderCatalogInPanel(cacheData.catalog);
        catalogProgress.textContent = 'Cached';
        console.log('[Catalog] Loaded from cache - no credits charged');
      } else if (cacheResponse.status === 404) {
        catalogProgress.textContent = 'Not generated';
        catalogGateTitle.textContent = 'No ideas yet';
        catalogGateSub.textContent = 'You need to build your catalog first. This is the research phase.';
        catalogGateCount.textContent = '0/30';
        catalogAlreadyGenerated = false;
        // FIX: Auto-open credit gate modal when catalog not generated
        openCreditGateModal();
      }
    } catch (error) {
      console.error('[Catalog] Cache load error:', error);
      catalogProgress.textContent = 'Error';
    }
  }

  // Wire up Catalog button to toggle views
  if (catalogBtn) {
    catalogBtn.addEventListener('click', async () => {
      await loadCatalogCache();
      showBlockBView();
    });
  }

  // Wire up credit gate cancel
  if (gateCancelBtn) {
    gateCancelBtn.addEventListener('click', closeCreditGateModal);
  }

  // Wire up credit gate approve
  if (gateApproveBtn) {
    gateApproveBtn.addEventListener('click', handleGateApprove);
  }

  // Wire up gate button to open modal
  if (catalogGate) {
    catalogGate.addEventListener('click', openCreditGateModal);
  }

  // Wire up back button from BlockB to BlockA
  const catalogBackBtn = document.getElementById('Catalog-BackBtn');
  if (catalogBackBtn) {
    catalogBackBtn.addEventListener('click', showBlockAView);
  }

  // Wire up Block C back button
  if (scriptBackBtn) {
    scriptBackBtn.addEventListener('click', showBlockBView);
  }

  // Wire up Block C generate button
  if (scriptGenerateBtn) {
    scriptGenerateBtn.addEventListener('click', async (e) => {
      e.preventDefault();

      // PIEZA 36 (bug 1): Use currentScriptIdeaId (set by showBlockCView) instead of currentScriptData.idea_id
      if (!currentScriptIdeaId) {
        alert('No idea selected. Please select an idea from the catalog first.');
        return;
      }

      const sourceMode = scriptSourceMode?.value || 'brand_brain';
      const finalSourceMode = sourceMode === 'brand_brain' ? 'brand_brain' : 'raw_footage';

      const originalText = scriptGenerateBtn.innerHTML;
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.innerHTML = 'Generating...';

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 135000);

      try {
        const response = await authenticatedFetch(`/api/script/generate?idea_id=${encodeURIComponent(currentScriptIdeaId)}`, {
          method: 'POST',
          signal: controller.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            interview_transcript: Array.isArray(fullTranscript) ? fullTranscript.join('\n') : '',
            source_mode: finalSourceMode
          })
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        if (!response.ok) {
          if (response.status === 402) {
            alert('Paywall: Not enough credits to generate script. You need 10 credits.');
          } else {
            alert(`Failed to generate script: ${data.error || data.detail || response.status}`);
          }
          scriptGenerateBtn.disabled = false;
          scriptGenerateBtn.innerHTML = originalText;
          return;
        }

        if (data.credits_remaining !== undefined) {
          credits = data.credits_remaining;
          updateCreditsUI(data.credits_remaining, initialSessionCredits);
        }

        // Load the generated script
        await loadScriptData(currentScriptIdeaId);

      } catch (error) {
        clearTimeout(timeoutId);
        console.error('Generate script error:', error);
        if (error.name === 'AbortError') {
          alert('Script generation timed out. Please try again.');
        } else {
          alert(`Failed to generate script: ${error.message}`);
        }
        scriptGenerateBtn.disabled = false;
        scriptGenerateBtn.innerHTML = originalText;
      }
    });
  }

  // PIEZA 36 (bug 2): Update script button when source mode changes
  if (scriptSourceMode) {
    scriptSourceMode.addEventListener('change', updateScriptGenerateButton);
  }

  // Wire up Block C lock button
  if (scriptLockBtn && !scriptLockBtn.dataset.wired) {
    scriptLockBtn.addEventListener('click', () => {
      if (currentScriptData && currentScriptData.id) {
        handleScriptLock();
      }
    });
    scriptLockBtn.dataset.wired = 'true';
  }

  // Close modal on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && brandSoulOverlay && brandSoulOverlay.style.display !== 'none') {
      closeBrandSoulOverlay();
    }
    if (e.key === 'Escape' && creditGateOverlay && creditGateOverlay.style.display !== 'none') {
      closeCreditGateModal();
    }
  });

  // Wire up Brand Soul button and overlay controls
  if (brandSoulBtn) {
    brandSoulBtn.addEventListener('click', generateBrandSoul);
  }

  if (brandSoulDownloadBtn) {
    brandSoulDownloadBtn.addEventListener('click', downloadBrandSoul);
  }

  if (brandSoulRegenerateBtn) {
    brandSoulRegenerateBtn.addEventListener('click', regenerateBrandSoul);
  }

  if (brandSoulCloseBtn) {
    brandSoulCloseBtn.addEventListener('click', closeBrandSoulOverlay);
  }

  // Close overlay on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && brandSoulOverlay && brandSoulOverlay.style.display !== 'none') {
      closeBrandSoulOverlay();
    }
  });

  // =============================================================================
  // RESIZABLE COLUMNS
  // =============================================================================

  // DOM elements
  const voz = document.querySelector('.voz');
  const doc = document.querySelector('.doc');
  const prod = document.querySelector('.prod');
  const resizerVDoc = document.getElementById('Resizer-VDoc');
  const resizerDProd = document.getElementById('Resizer-DProd');
  const collapseVoz = document.getElementById('Collapse-Voz');
  const expandVoz = document.getElementById('Expand-Voz');
  const collapseProd = document.getElementById('Collapse-Prod');
  const expandProd = document.getElementById('Expand-Prod');

  // Constants
  const COLAPSE_THRESHOLD = 120;
  const ICON_BAR_WIDTH = 48;
  const MIN_WIDTH = 200;
  const MAX_WIDTH = 600;
  const STORAGE_KEY = 'brandStudioColWidths';

  // State
  let isResizing = false;
  let activeResizer = null;
  let startX = 0;
  let startVozWidth = 0;
  let startProdWidth = 0;

  // Load saved widths from localStorage
  function loadColumnWidths() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const widths = JSON.parse(saved);
        if (widths.voz && widths.voz >= MIN_WIDTH && widths.voz <= MAX_WIDTH) {
          voz.style.width = widths.voz + 'px';
        }
        if (widths.prod && widths.prod >= MIN_WIDTH && widths.prod <= MAX_WIDTH) {
          prod.style.width = widths.prod + 'px';
        }
      }
    } catch (e) {
      console.warn('[Columns] Failed to load widths:', e);
    }
  }

  // Save widths to localStorage
  function saveColumnWidths() {
    try {
      const widths = {
        voz: parseInt(voz.style.width) || 420,
        prod: parseInt(prod.style.width) || 380
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
    } catch (e) {
      console.warn('[Columns] Failed to save widths:', e);
    }
  }

  // Initialize resizer events
  function initResizer(resizer, isLeftResizer) {
    if (!resizer) return;

    resizer.addEventListener('mousedown', (e) => {
      isResizing = true;
      activeResizer = isLeftResizer ? 'vdoc' : 'dprod';
      startX = e.clientX;
      startVozWidth = parseInt(voz.style.width) || 420;
      startProdWidth = parseInt(prod.style.width) || 380;

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      e.preventDefault();
    });
  }

  // Initialize collapse buttons
  function initCollapseButtons() {
    if (collapseVoz) {
      collapseVoz.addEventListener('click', () => {
        voz.classList.add('collapsed');
        collapseVoz.style.display = 'none';
        expandVoz.style.display = 'flex';
      });
    }

    if (expandVoz) {
      expandVoz.addEventListener('click', () => {
        voz.classList.remove('collapsed');
        expandVoz.style.display = 'none';
        collapseVoz.style.display = 'flex';
        // Restore default width
        voz.style.width = '420px';
        saveColumnWidths();
      });
    }

    if (collapseProd) {
      collapseProd.addEventListener('click', () => {
        prod.classList.add('collapsed');
        collapseProd.style.display = 'none';
        expandProd.style.display = 'flex';
      });
    }

    if (expandProd) {
      expandProd.addEventListener('click', () => {
        prod.classList.remove('collapsed');
        expandProd.style.display = 'none';
        collapseProd.style.display = 'flex';
        // Restore default width
        prod.style.width = '380px';
        saveColumnWidths();
      });
    }
  }

  // Handle global mouse move during resizing
  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;

    const deltaX = e.clientX - startX;

    if (activeResizer === 'vdoc') {
      const newVozWidth = startVozWidth + deltaX;
      if (newVozWidth >= MIN_WIDTH && newVozWidth <= MAX_WIDTH) {
        voz.style.width = newVozWidth + 'px';

        // Auto-collapse if dragged below threshold
        if (newVozWidth < COLAPSE_THRESHOLD) {
          voz.classList.add('collapsed');
          collapseVoz.style.display = 'none';
          expandVoz.style.display = 'flex';
          voz.style.width = ICON_BAR_WIDTH + 'px';
        }
      }
    } else if (activeResizer === 'dprod') {
      const newProdWidth = startProdWidth - deltaX;
      if (newProdWidth >= MIN_WIDTH && newProdWidth <= MAX_WIDTH) {
        prod.style.width = newProdWidth + 'px';

        // Auto-collapse if dragged below threshold
        if (newProdWidth < COLAPSE_THRESHOLD) {
          prod.classList.add('collapsed');
          collapseProd.style.display = 'none';
          expandProd.style.display = 'flex';
          prod.style.width = ICON_BAR_WIDTH + 'px';
        }
      }
    }
  });

  // Handle global mouse up after resizing
  document.addEventListener('mouseup', () => {
    if (isResizing) {
      isResizing = false;
      activeResizer = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';

      // Save widths after resize
      saveColumnWidths();
    }
  });

  // Initialize on page load
  loadColumnWidths();
  initResizer(resizerVDoc, true);
  initResizer(resizerDProd, false);
  initCollapseButtons();

  // Handle responsive auto-collapse
  function handleResponsiveCollapse() {
    const width = window.innerWidth;

    if (width <= 768) {
      // Mobile: collapse both columns
      voz.classList.add('collapsed');
      prod.classList.add('collapsed');
      if (collapseVoz) collapseVoz.style.display = 'none';
      if (expandVoz) expandVoz.style.display = 'flex';
      if (collapseProd) collapseProd.style.display = 'none';
      if (expandProd) expandProd.style.display = 'flex';
    } else if (width <= 1200) {
      // Tablet: collapse production only
      prod.classList.add('collapsed');
      if (collapseProd) collapseProd.style.display = 'none';
      if (expandProd) expandProd.style.display = 'flex';
      voz.classList.remove('collapsed');
      if (collapseVoz) collapseVoz.style.display = 'flex';
      if (expandVoz) expandVoz.style.display = 'none';
    } else {
      // Desktop: restore both if not manually collapsed
      if (!voz.classList.contains('collapsed')) {
        voz.classList.remove('collapsed');
        if (collapseVoz) collapseVoz.style.display = 'flex';
        if (expandVoz) expandVoz.style.display = 'none';
      }
      if (!prod.classList.contains('collapsed')) {
        prod.classList.remove('collapsed');
        if (collapseProd) collapseProd.style.display = 'flex';
        if (expandProd) expandProd.style.display = 'none';
      }
    }
  }

  // Listen for window resize
  let resizeTimeout;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(handleResponsiveCollapse, 100);
  });

  // Initial responsive check
  handleResponsiveCollapse();

  console.log('[Columns] Resizable columns initialized');

  // Handle Stripe checkout callback
  async function handleCheckoutCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const checkoutStatus = urlParams.get('checkout');

    if (checkoutStatus === 'success') {
      // CRITICAL FIX: Set flag to prevent logout during checkout return
      console.log('[Billing] 💳 Checkout successful - setting isCheckoutInProgress flag');
      isCheckoutInProgress = true;

      console.log('[Billing] 💳 Checkout successful - refreshing credits in-place...');
      console.log('[Billing] 💳 Checking existing Supabase session...');
      
      // Force Supabase to check existing session from localStorage
      // When returning from Stripe redirect, Supabase may temporarily think we're signed out
      const { data: { session }, error } = await supabase.auth.getSession();
      
      if (error) {
        console.error('[Billing] ❌ Error checking session:', error);
      } else if (session) {
        console.log('[Billing] ✅ Session still valid, restoring user context');
        jwtToken = session.access_token;
        user = session.user;
        // Force UI back to main app regardless of auth state
        console.log('[Billing] ✅ Forcing showMainApp() after successful payment');
        showMainApp();
      } else {
        console.warn('[Billing] ⚠️ No session found - attempting credit refresh anyway');
        // CRITICAL FIX: Even without session, try to refresh credits and stay on page
        // Don't return early - continue to credit refresh
      }
      
      // Clear URL params immediately to prevent re-triggering
      window.history.replaceState({}, document.title, window.location.pathname);
      
      // CRITICAL FIX: Always attempt to refresh credits after successful payment
      console.log('[Billing] 💳 Refreshing credits after successful checkout...');
      try {
        await fetchCredits();
        console.log('[Billing] ✅ Credits refreshed successfully');
      } catch (e) {
        console.error('[Billing] ❌ Error refreshing credits:', e);
        // Continue anyway - payment was successful, credits may be updated on server
      }

      // Show success message
      alert('Payment successful! Your credits have been added.');
      
      // CRITICAL FIX: Ensure we're on main app screen after successful checkout
      if (user || jwtToken) {
        console.log('[Billing] ✅ User authenticated, showing main app');
        showMainApp();
      }
      
      // CRITICAL FIX: Clear the flag after handling is complete
      setTimeout(() => {
        isCheckoutInProgress = false;
        console.log('[Billing] ✅ Checkout handling complete, isCheckoutInProgress cleared');
      }, 2000); // Give it 2 seconds to ensure all auth events have settled
      
    } else if (checkoutStatus === 'cancelled') {
      console.log('[Billing] Checkout cancelled by user');
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }

  // Initialize on page load
  document.addEventListener('DOMContentLoaded', async () => {
    await initSupabase();
    await handleAuthCallback();
    await handleCheckoutCallback();

    // Wire up logout button
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', logout);
    }
  });

  console.log('[Voice Client] Initialized - Connecting directly to AssemblyAI Voice Agent API');
  console.log('[Audio] Sample rate: 24kHz');
  console.log('[Processor] AudioWorklet for PCM16 conversion');
  console.log('[Auth] Google OAuth enabled');

})();
