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
        appendLogMessage('error', 'AssemblyAI WebSocket connection error');
        stopSession();
      };

      ws.onclose = () => {
        if (myGeneration !== sessionGeneration) return; // Not the active session
        console.log('[WebSocket Closed]');
        stopSession();
      };

    } catch (err) {
      console.error('[StartSession Failed]', err);
      alert('Error starting voice session: ' + err.message);
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
    p.textContent = `You: ${text}`;
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

  // PIEZA 46: Humanized translations for Brand Brain fields
  const BRAIN_FIELD_LABELS = {
    // Diagnostico
    etapa: 'Stage',
    nivel_ramiro: 'Awareness level',
    sintoma_diagnostico: 'Diagnostic symptom',
    habilidad_a_desbloquear: 'Skill to unlock',
    prohibicion: 'Prohibition',
    postura: 'Stance',
    justificacion_postura: 'Posture justification',

    // Brand Journey
    resultado_deseado: 'Desired outcome',
    de_que_ser_conocido: 'Known for',
    que_hacer: 'What to do',
    que_aprender: 'What to learn',

    // Charco
    problema: 'Problem',
    nivel: 'Level',
    logro_que_lo_respalda: 'Backing achievement',
    costo_de_no_resolverlo: 'Cost of inaction',
    intentos_fallidos: 'Failed attempts',

    // ICP
    quien_decide: 'Decision maker',
    tamano_empresa: 'Company size',
    disparador_de_urgencia: 'Urgency trigger',
    poder_adquisitivo: 'Purchasing power',
    comite_de_compra: 'Buying committee',
    a_quien_le_rinde_cuentas: 'Accountable to',

    // Contrarian
    creencia_comun: 'Common belief',
    postura_opuesta: 'Opposing stance',
    prueba: 'Evidence / proof',
    por_que_no_es_provocacion: 'Why not a provocation',

    // Asociaciones
    deseadas: 'Desired associations',
    prohibidas: 'Forbidden associations',

    // Identidad
    voz: 'Tone of voice',
    colores: 'Colors',
    tipografias: 'Typography',
    narrativa_de_origen: 'Origin story',

    // Oferta
    resultado_sonado: 'Dream outcome',
    probabilidad_percibida: 'Perceived likelihood',
    retraso: 'Time delay',
    esfuerzo: 'Effort & sacrifice',
    componentes: 'Components',
    garantia: 'Guarantee',

    // Lead Magnet
    tipo: 'Type',
    problema_A: 'Problem A',
    problema_B_que_revela: 'Problem B revealed',
    formato: 'Format',
    captura: 'Lead capture'
  };

  function humanizeBrainField(key) {
    if (BRAIN_FIELD_LABELS[key]) return BRAIN_FIELD_LABELS[key];
    const cleaned = String(key || '').replace(/_/g, ' ').trim();
    if (!cleaned) return 'Insight';
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
  }

  function buildMaskForValue(rawVal) {
    let len = 20;
    if (typeof rawVal === 'string') {
      len = rawVal.trim().length;
    } else if (Array.isArray(rawVal)) {
      len = rawVal.join(', ').length;
    } else if (typeof rawVal === 'object' && rawVal !== null) {
      len = JSON.stringify(rawVal).length;
    } else if (rawVal !== null && rawVal !== undefined) {
      len = String(rawVal).length;
    }
    const maskCount = Math.max(10, Math.min(len, 32));
    return '█'.repeat(maskCount);
  }

  /**
   * Render Modo A: Brand brain sections one-by-one in the center document zone
   * PIEZA 46: Confirmed sections are obfuscated with 100% animated progress bars.
   * Real values NEVER enter the DOM for confirmed sections.
   * Proposed sections remain in clear text for founder review/correction.
   */
  function renderModoASections(sections) {
    const docBody = document.querySelector('.docbody');
    if (!docBody) return;
    currentModoASections = sections || [];

    // Clear existing ghost sections and replace with live sections
    docBody.innerHTML = '';

    // PIEZA 49: Action bar container and actions above sections
    let actionBarContainer = document.getElementById('BrandSoul-ActionBar-Container');
    if (!actionBarContainer) {
      actionBarContainer = document.createElement('div');
      actionBarContainer.id = 'BrandSoul-ActionBar-Container';
      docBody.appendChild(actionBarContainer);
    }
    if (typeof renderBrandSoulActionBar === 'function') {
      renderBrandSoulActionBar(currentModoASections);
    }

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

      // PIEZA 46: Obfuscate ONLY confirmed/completado/confirmed sections.
      // Proposed sections remain in clear text so founder can review/correct.
      const isConfirmed = section.status === 'confirmado' || section.status === 'completado' || section.status === 'confirmed';
      const isPropuesto = !isConfirmed;
      const borderColor = isPropuesto ? '#D5DAE4' : '#1B7F4C';
      const borderStyle = isPropuesto ? 'dotted' : 'solid';
      const bgColor = isPropuesto ? '#FFFFFF' : '#F5F7FB';

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

      if (isConfirmed) {
        const count = (typeof section.content === 'object' && section.content !== null)
          ? Object.keys(section.content).length
          : 1;
        const insightsText = `${count} ${count === 1 ? 'insight' : 'insights'} captured`;

        header.innerHTML = `
          <span class="section-num mono" style="font-size: 11px; color: #5C6675; font-weight: 600;">${sectionNumber}</span>
          <span class="section-label" style="font-size: 14px; font-weight: 500; color: #14181F; flex: 1;">${escapeHtml(label)}</span>
          <span class="section-insights mono" style="font-size: 11px; color: #5C6675; font-weight: 500;">${escapeHtml(insightsText)}</span>
          <span class="section-status mono" style="font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #1B7F4C; font-weight: 600; padding: 2px 8px; background: rgba(27, 127, 76, 0.08); border-radius: 4px;">Confirmed · 100%</span>
        `;
      } else {
        header.innerHTML = `
          <span class="section-num mono" style="font-size: 11px; color: #5C6675; font-weight: 600;">${sectionNumber}</span>
          <span class="section-label" style="font-size: 14px; font-weight: 500; color: #14181F; flex: 1;">${escapeHtml(label)}</span>
          <span class="section-status mono" style="font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #5C6675; font-weight: 600;">Proposed</span>
        `;
      }
      sectionEl.appendChild(header);

      // Section content
      const contentEl = document.createElement('div');
      contentEl.className = 'section-content';
      contentEl.style.cssText = `
        padding-left: 26px;
        font-size: 13px;
        line-height: 1.6;
        color: #14181F;
      `;

      if (isConfirmed) {
        // PIEZA 46: Obfuscated fields - real value NEVER enters DOM
        if (typeof section.content === 'object' && section.content !== null) {
          const entries = Object.entries(section.content);
          entries.forEach(([key, value]) => {
            const row = document.createElement('div');
            row.className = 'brain-field-row';
            row.style.cssText = 'display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.04); font-size: 12.5px;';
            const mask = buildMaskForValue(value);
            row.innerHTML = `
              <span style="color: #1B7F4C; font-weight: 700; font-size: 13px; flex-shrink: 0;">✓</span>
              <span style="font-weight: 600; color: #14181F; min-width: 160px; max-width: 220px; flex-shrink: 0;">${escapeHtml(humanizeBrainField(key))}</span>
              <span class="mono" style="color: #94A3B8; letter-spacing: 1px; user-select: none; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px;">${mask}</span>
              <div style="display: flex; align-items: center; gap: 8px; width: 120px; flex-shrink: 0;">
                <div style="flex: 1; height: 6px; background: #E2E8F0; border-radius: 3px; overflow: hidden;">
                  <div class="progress-fill-anim" style="width: 100%; height: 100%; background: #1B7F4C; border-radius: 3px;"></div>
                </div>
                <span class="mono" style="font-size: 10px; font-weight: 600; color: #1B7F4C;">100%</span>
              </div>
            `;
            contentEl.appendChild(row);
          });
        } else {
          // Single value
          const row = document.createElement('div');
          row.className = 'brain-field-row';
          row.style.cssText = 'display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid rgba(0, 0, 0, 0.04); font-size: 12.5px;';
          const mask = buildMaskForValue(section.content);
          row.innerHTML = `
            <span style="color: #1B7F4C; font-weight: 700; font-size: 13px; flex-shrink: 0;">✓</span>
            <span style="font-weight: 600; color: #14181F; min-width: 160px; max-width: 220px; flex-shrink: 0;">${escapeHtml(label)}</span>
            <span class="mono" style="color: #94A3B8; letter-spacing: 1px; user-select: none; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px;">${mask}</span>
            <div style="display: flex; align-items: center; gap: 8px; width: 120px; flex-shrink: 0;">
              <div style="flex: 1; height: 6px; background: #E2E8F0; border-radius: 3px; overflow: hidden;">
                <div class="progress-fill-anim" style="width: 100%; height: 100%; background: #1B7F4C; border-radius: 3px;"></div>
              </div>
              <span class="mono" style="font-size: 10px; font-weight: 600; color: #1B7F4C;">100%</span>
            </div>
          `;
          contentEl.appendChild(row);
        }
        sectionEl.appendChild(contentEl);

        // PIEZA 46: Citation block for confirmed section - no quote in DOM
        const citationEl = document.createElement('div');
        citationEl.className = 'citation-block';
        citationEl.style.cssText = `
          padding-left: 26px;
          margin-top: 8px;
          border-left: 2px solid #1B7F4C;
          padding-left: 10px;
        `;
        const citationLabel = document.createElement('div');
        citationLabel.style.cssText = `
          font-size: 11px;
          font-weight: 500;
          color: #1B7F4C;
        `;
        citationLabel.textContent = 'Source: your interview ✓';
        citationEl.appendChild(citationLabel);
        sectionEl.appendChild(citationEl);

      } else {
        // Proposed section - clear text display
        if (typeof section.content === 'object' && section.content !== null) {
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
          contentEl.textContent = section.content || '—';
        }
        sectionEl.appendChild(contentEl);

        // Citation block with quote for proposed section
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

        citationEl.addEventListener('mouseenter', () => {
          citationEl.style.backgroundColor = 'rgba(43, 76, 216, 0.04)';
        });
        citationEl.addEventListener('mouseleave', () => {
          citationEl.style.backgroundColor = 'transparent';
        });
        citationEl.addEventListener('click', () => {
          highlightTranscriptSection(section.citation_text);
        });

        sectionEl.appendChild(citationEl);
      }

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
  let maxCreditsSeenInSession = 0;

  // Update credits UI (helper function)
  function updateCreditsUI(remaining, initial) {
    // Update global credits variable for access in modals and gates
    credits = remaining;

    const num = Number(remaining) || 0;
    const initNum = Number(initial) || 0;
    maxCreditsSeenInSession = Math.max(maxCreditsSeenInSession, initNum, num);
    const denominator = Math.max(1, maxCreditsSeenInSession);

    const creditsLabel = document.getElementById('Credits-Label');
    const creditsBar = document.getElementById('Credits-Bar');

    if (creditsLabel) {
      creditsLabel.textContent = `${num.toLocaleString('en-US')} credits`;
    }

    const percentage = Math.max(0, Math.min(100, (num / denominator) * 100));

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

    console.log(`[Credits] ${num} of ${denominator} (${percentage.toFixed(1)}%)`);

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
      if (typeof checkBrandSoulStatus === 'function') {
        await checkBrandSoulStatus();
      }
      const brain = await loadBrandBrain();
      if (brain && brain.sections && brain.sections.length) {
        appendExtractedSections(brain.sections);
        updateBrandSoulButton(brain.sections);
        updateCatalogButton(brain.sections);
      } else {
        if (typeof renderBrandSoulActionBar === 'function') {
          renderBrandSoulActionBar([]);
        }
      }
      // Pieza 44B: Si Brand Soul está completo, pedir en silencio el catálogo para no mentir en el riel
      const sections = (brain && brain.sections) || (cachedBrain && cachedBrain.sections);
      const brainCount = getReadySectionsCount(sections);
      if (brainCount >= 9) {
        await refreshCatalogStatusSilently();
      }
      return brain;
    } catch (e) {
      console.error('[Brain] No se pudo cargar el cerebro existente:', e);
    }
  }

  function showMainApp() {
    loginOverlay.style.display = 'none';
    mainApp.style.display = 'flex';
    loadConfig().then(async () => {
      updateCreditsDisplay();
      await loadExistingBrain();
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

  const brandSoulOverlay = document.getElementById('BrandSoul-Overlay');
  const brandSoulContent = document.getElementById('BrandSoul-Content');
  const brandSoulLoading = document.getElementById('BrandSoul-Loading');
  const brandSoulCloseBtn = document.getElementById('BrandSoul-CloseBtn');
  const brandSoulDownloadBtn = document.getElementById('BrandSoul-DownloadBtn');
  const brandSoulRegenerateBtn = document.getElementById('BrandSoul-RegenerateBtn');

  // PIEZA 49: Brand Soul door state & action bar
  let brandSoulExists = false;
  let currentModoASections = [];

  // Silent check of GET /api/soul (free, no credits)
  async function checkBrandSoulStatus() {
    try {
      const response = await authenticatedFetch('/api/soul', { method: 'GET' });
      if (response.ok) {
        brandSoulExists = true;
      } else {
        brandSoulExists = false;
      }
    } catch (e) {
      console.warn('[Brand Soul] Silent check error:', e);
      brandSoulExists = false;
    }
    return brandSoulExists;
  }

  // Free view of cached Brand Soul document in overlay
  async function openBrandSoulViewer() {
    if (!brandSoulOverlay) return;
    brandSoulOverlay.style.display = 'flex';
    if (brandSoulContent) {
      brandSoulContent.style.display = 'none';
      brandSoulContent.innerHTML = '';
    }
    if (brandSoulLoading) {
      brandSoulLoading.style.display = 'flex';
    }

    try {
      const response = await authenticatedFetch('/api/soul', { method: 'GET' });
      if (response.ok) {
        const data = await response.json();
        if (brandSoulLoading) brandSoulLoading.style.display = 'none';
        if (brandSoulContent) {
          brandSoulContent.style.display = 'block';
          brandSoulContent.innerHTML = data.html;
        }
        if (brandSoulRegenerateBtn) {
          brandSoulRegenerateBtn.style.display = 'flex';
        }
        brandSoulExists = true;
        renderBrandSoulActionBar(currentModoASections);
        console.log('[Brand Soul] Viewed cached document - 0 credits charged');
      } else {
        if (brandSoulLoading) brandSoulLoading.style.display = 'none';
        brandSoulOverlay.style.display = 'none';
        alert('Brand Soul not found. Generate it first.');
      }
    } catch (e) {
      console.error('[Brand Soul] View error:', e);
      if (brandSoulLoading) brandSoulLoading.style.display = 'none';
      brandSoulOverlay.style.display = 'none';
      alert('Failed to load Brand Soul: ' + e.message);
    }
  }

  // Render the Brand Soul Action Bar according to piece 49 specs
  function renderBrandSoulActionBar(sections) {
    let container = document.getElementById('BrandSoul-ActionBar-Container');
    if (!container) {
      const docBody = document.querySelector('.docbody');
      if (docBody) {
        container = document.createElement('div');
        container.id = 'BrandSoul-ActionBar-Container';
        docBody.insertBefore(container, docBody.firstChild);
      } else {
        return;
      }
    }

    const sectionsList = sections || currentModoASections || (cachedBrain && cachedBrain.sections) || [];
    const confirmedCount = getReadySectionsCount(sectionsList);

    let actionButtonsHtml = '';
    if (brandSoulExists) {
      actionButtonsHtml = `
        <button type="button" id="BrandSoul-ViewBtn" class="btn btn--primary" style="padding:8px 16px;font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:6px;cursor:pointer;background:var(--accent);color:#fff;border:none;border-radius:6px;">
          📖 View your Brand Soul
        </button>
        <button type="button" id="BrandSoul-ActionRegenerateBtn" class="btn btn--secondary" style="padding:8px 14px;font-size:13px;font-weight:500;display:inline-flex;align-items:center;gap:6px;cursor:pointer;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:6px;">
          ⟳ Regenerate · 20 credits
        </button>
      `;
    } else if (confirmedCount >= 9) {
      actionButtonsHtml = `
        <button type="button" id="BrandSoul-GenerateActionBtn" class="btn btn--go" style="padding:8px 16px;font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:6px;cursor:pointer;border-radius:6px;">
          ✨ Generate your Brand Soul · 20 credits
        </button>
      `;
    } else {
      actionButtonsHtml = `
        <button type="button" id="BrandSoul-DisabledActionBtn" class="btn" disabled style="padding:8px 16px;font-size:13px;opacity:0.65;cursor:not-allowed;background:var(--surface-alt);color:var(--ink-soft);border:1px solid var(--line);border-radius:6px;">
          Finish your interview with Brandy to generate your Brand Soul (${confirmedCount} of 9)
        </button>
      `;
    }

    const isClickable = Boolean(brandSoulExists);
    const noticeStyle = 'margin:0 0 12px;padding:10px 14px;background:rgba(43,76,216,0.05);border:1px solid rgba(43,76,216,0.15);border-radius:6px;font-size:13px;color:var(--accent);display:flex;align-items:center;gap:8px;font-weight:500;' + (isClickable ? 'cursor:pointer;transition:all 0.15s ease;' : '');
    const noticeTitle = isClickable ? 'title="Click to view your Brand Soul"' : '';
    const noticeHint = isClickable ? '<span style="font-size:11px;font-weight:600;text-decoration:underline;margin-left:auto;">Click to view →</span>' : '';

    container.innerHTML = `
      <div id="BrandSoul-UnlockNotice" class="brand-soul-unlock-notice" style="${noticeStyle}" ${noticeTitle}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
        </svg>
        <span>Your full Brand Soul is unlocked in the Brand Soul document.</span>
        ${noticeHint}
      </div>
      <div class="brand-soul-action-buttons" style="display:flex;align-items:center;gap:10px;margin-bottom:20px;flex-wrap:wrap;">
        ${actionButtonsHtml}
      </div>
    `;

    // Wire clicks
    const unlockNoticeEl = container.querySelector('#BrandSoul-UnlockNotice');
    if (unlockNoticeEl && isClickable) {
      unlockNoticeEl.addEventListener('click', openBrandSoulViewer);
    }

    const viewBtn = container.querySelector('#BrandSoul-ViewBtn');
    if (viewBtn) {
      viewBtn.addEventListener('click', openBrandSoulViewer);
    }

    const regenBtn = container.querySelector('#BrandSoul-ActionRegenerateBtn');
    if (regenBtn) {
      regenBtn.addEventListener('click', regenerateBrandSoul);
    }

    const genBtn = container.querySelector('#BrandSoul-GenerateActionBtn');
    if (genBtn) {
      genBtn.addEventListener('click', generateBrandSoul);
    }
  }

  // Update Brand Soul state
  function updateBrandSoulButton(sections) {
    if (typeof initGlobalProgress === 'function') {
      initGlobalProgress();
    }
    renderBrandSoulActionBar(sections);
  }

  // Generate Brand Soul document
  async function generateBrandSoul() {
    try {

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

        brandSoulExists = true;
        renderBrandSoulActionBar(currentModoASections);
        
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

        brandSoulExists = true;
        renderBrandSoulActionBar(currentModoASections);

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
      if (typeof initGlobalProgress === 'function') {
        initGlobalProgress();
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

      brandSoulExists = true;
      renderBrandSoulActionBar(currentModoASections);

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
  const blockAView = document.getElementById('BlockA-View');
  const blockBView = document.getElementById('BlockB-View');
  const blockCView = document.getElementById('BlockC-View');
  const audiovisualView = document.getElementById('Audiovisual-View');
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
  const scriptIdeaTitle = document.getElementById('Script-IdeaTitle');
  const scriptMeta = document.getElementById('Script-Meta');
  let scriptAngle = document.getElementById('Script-Angle');
  let scriptFunnelStage = document.getElementById('Script-FunnelStage');
  let scriptDuration = document.getElementById('Script-Duration');
  let scriptRecordingFormat = document.getElementById('Script-RecordingFormat');
  let scriptMusicPrompt = document.getElementById('Script-MusicPrompt');
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
  // In-flight guards: which scene indices currently have a regenerate POST
  // pending, and whether a script-level lock POST is pending. Prevents
  // double-charging when the founder double-clicks while a request is out.
  let regeneratingSceneIndices = new Set();
  let scriptLockInFlight = false;

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
    'autoridad_tecnica': 'Technical Authority & Instruction',
    'validacion_resultados': 'Results Validation & Impact',
    'posicionamiento_narrativa': 'Positioning & Market Thesis',
    'narrativa_fundadora': 'Founder Story & Origin',
    'discusion_industria': 'Industry Discussion & Co-creation'
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
      lockBtn.textContent = 'Catalog locked ✓';
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
    const founderBadge = idea.origin === 'founder' ? '<span class="badge-founder">Your idea</span>' : '';
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
      : `<button class="btn-regenerate" data-idea-id="${safeId}" title="Regenerate (3 credits)">&#8635;</button>`;
    // PIEZA 45: "Write script" vs "Open script" button on approved ideas when catalog is locked
    let scriptBtnLabel = '📝 Write script';
    let scriptBtnTitle = 'Write script';
    if (idea.script_state === 'locked') {
      scriptBtnLabel = '📂 Open script · locked 🔒';
      scriptBtnTitle = 'Open script (locked)';
    } else if (idea.script_state === 'reviewed') {
      scriptBtnLabel = '📂 Open script · reviewed';
      scriptBtnTitle = 'Open script (reviewed)';
    } else if (idea.script_state === 'draft') {
      scriptBtnLabel = '📂 Open script · draft';
      scriptBtnTitle = 'Open script (draft)';
    } else if (idea.script_state) {
      scriptBtnLabel = `📂 Open script · ${escapeHtml(idea.script_state)}`;
      scriptBtnTitle = `Open script (${escapeHtml(idea.script_state)})`;
    }
    const scriptBtnHTML = (catalogLocked && idea.status === 'approved')
      ? `<button class="btn-script" data-idea-id="${safeId}" title="${scriptBtnTitle}">${scriptBtnLabel}</button>`
      : '';
    return `
      <span class="ideatitle">${escapeHtml(idea.title)}${founderBadge}</span>
      <span class="angle" style="border-color:${color};color:${color}">${escapeHtml(idea.subcategory || 'Format')}</span>
      <span class="signal">${escapeHtml(idea.demand_signal)}</span>
      <div class="idea-actions">
        <button class="btn-approve" data-idea-id="${safeId}" title="Approve idea">&#10003;</button>
        <button class="btn-reject" data-idea-id="${safeId}" title="Discard idea">&#10007;</button>
        ${regenerateBtnHTML}
        ${scriptBtnHTML}
      </div>
    `;
  }

  // PIEZA 45: Update an idea card's script button without reloading the catalog
  function updateIdeaCardScriptButton(ideaId, scriptState) {
    const scriptBtns = document.querySelectorAll('.btn-script');
    for (const btn of scriptBtns) {
      if (btn.dataset.ideaId === ideaId) {
        if (scriptState === 'locked') {
          btn.textContent = '📂 Open script · locked 🔒';
          btn.title = 'Open script (locked)';
        } else if (scriptState === 'reviewed') {
          btn.textContent = '📂 Open script · reviewed';
          btn.title = 'Open script (reviewed)';
        } else if (scriptState === 'draft') {
          btn.textContent = '📂 Open script · draft';
          btn.title = 'Open script (draft)';
        } else if (scriptState) {
          btn.textContent = `📂 Open script · ${scriptState}`;
          btn.title = `Open script (${scriptState})`;
        } else {
          btn.textContent = '📝 Write script';
          btn.title = 'Write script';
        }
        break;
      }
    }
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

  // Update Catalog state
  function updateCatalogButton(sections) {
    if (typeof initGlobalProgress === 'function') {
      initGlobalProgress();
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
          alert('Title must be between 5 and 200 characters.');
          return;
        }
        if (source.length < 10) {
          alert('Source must be at least 10 characters (where does this idea come from?).');
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

  // Current active view tracking for Pipeline Rail ('brain' | 'catalog' | 'script' | 'audiovisual')
  let currentOpenView = 'brain';

  function hideEditingView() {
    const el = document.getElementById('Editing-View');
    if (el) el.style.display = 'none';
    if (window.BrandStudioEditing && typeof window.BrandStudioEditing.onHide === 'function') {
      window.BrandStudioEditing.onHide();
    }
  }

  function hideMainViews() {
    if (blockAView) blockAView.style.display = 'none';
    if (blockBView) blockBView.style.display = 'none';
    if (blockCView) blockCView.style.display = 'none';
    if (audiovisualView) audiovisualView.style.display = 'none';
    currentOpenView = 'editing';
    if (typeof renderPipelineRail === 'function') {
      renderPipelineRail();
    }
  }

  // Show BlockA view (brand soul)
  async function showBlockAView() {
    hideEditingView();
    if (typeof cleanupAudiovisualBlobUrls === 'function') {
      cleanupAudiovisualBlobUrls();
    }
    currentOpenView = 'brain';
    if (blockAView) blockAView.style.display = 'block';
    if (blockBView) blockBView.style.display = 'none';
    if (blockCView) blockCView.style.display = 'none';
    if (audiovisualView) audiovisualView.style.display = 'none';
    if (typeof renderPipelineRail === 'function') {
      renderPipelineRail();
    }
    // Pieza 49: Silent check on view load
    if (typeof checkBrandSoulStatus === 'function') {
      await checkBrandSoulStatus();
    }
    const sectionsToRender = (cachedBrain && cachedBrain.sections && cachedBrain.sections.length)
      ? cachedBrain.sections
      : currentModoASections;
    if (sectionsToRender && sectionsToRender.length) {
      renderModoASections(sectionsToRender);
    } else {
      if (typeof renderBrandSoulActionBar === 'function') {
        renderBrandSoulActionBar([]);
      }
    }
  }

  // Show BlockB view (catalog)
  function showBlockBView() {
    hideEditingView();
    if (typeof cleanupAudiovisualBlobUrls === 'function') {
      cleanupAudiovisualBlobUrls();
    }
    currentOpenView = 'catalog';
    if (blockAView) blockAView.style.display = 'none';
    if (blockBView) blockBView.style.display = 'block';
    if (blockCView) blockCView.style.display = 'none';
    if (audiovisualView) audiovisualView.style.display = 'none';
    if (typeof renderPipelineRail === 'function') {
      renderPipelineRail();
    }
  }

  // Show BlockC view (script) with empty state for interview mode
  function showBlockCView(ideaId) {
    hideEditingView();
    if (typeof cleanupAudiovisualBlobUrls === 'function') {
      cleanupAudiovisualBlobUrls();
    }
    // Track current idea ID
    currentScriptIdeaId = ideaId;
    currentOpenView = 'script';

    // Find the idea data from current catalog
    const idea = currentCatalog?.ideas?.find(i => i.id === ideaId);
    if (!idea) {
      alert('Idea not found in catalog');
      return;
    }

    // Switch view
    if (blockAView) blockAView.style.display = 'none';
    if (blockBView) blockBView.style.display = 'none';
    if (blockCView) blockCView.style.display = 'block';
    if (audiovisualView) audiovisualView.style.display = 'none';

    // Set idea title
    if (scriptIdeaTitle) scriptIdeaTitle.textContent = idea.title;

    // Check if script already exists for this idea
    loadScriptData(ideaId);

    if (typeof renderPipelineRail === 'function') {
      renderPipelineRail();
    }
  }

  // =============================================================================
  // AUDIOVISUAL STUDIO VIEW (Pieza 46)
  // =============================================================================

  const ASSET_ORIGIN_CONFIG = {
    a_roll: {
      label: 'You record · free',
      style: 'background:#DCFCE7;color:#166534;border:1px solid #BBF7D0;font-weight:600;',
      iconBg: 'rgba(22, 101, 52, 0.1)',
      iconColor: '#166534',
      borderStyle: '#86EFAC'
    },
    stock: {
      label: 'Stock · free',
      style: 'background:#DBEAFE;color:#1E40AF;border:1px solid #BFDBFE;font-weight:600;',
      iconBg: 'rgba(30, 64, 175, 0.1)',
      iconColor: '#1E40AF',
      borderStyle: '#93C5FD'
    },
    ai_image: {
      label: 'AI image · premium',
      style: 'background:#F3E8FF;color:#6B21A8;border:1px solid #E9D5FF;font-weight:600;',
      iconBg: 'rgba(107, 33, 168, 0.1)',
      iconColor: '#6B21A8',
      borderStyle: '#D8B4FE'
    },
    ai_video: {
      label: 'AI video · premium ★',
      style: 'background:linear-gradient(135deg, #FEF08A, #FDE047);color:#854D0E;border:1px solid #EAB308;font-weight:700;box-shadow:0 1px 3px rgba(234,179,8,0.25);',
      iconBg: 'rgba(234, 179, 8, 0.15)',
      iconColor: '#854D0E',
      borderStyle: '#FACC15'
    },
    motion_graphic: {
      label: 'Motion graphic',
      style: 'background:#F3F4F6;color:#374151;border:1px solid #E5E7EB;font-weight:600;',
      iconBg: 'rgba(55, 65, 81, 0.1)',
      iconColor: '#374151',
      borderStyle: '#D1D5DB'
    }
  };

  function getAssetTypeIcon(type) {
    if (type === 'a_roll') {
      return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7 16 12 23 17 23 7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`;
    }
    if (type === 'stock') {
      return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>`;
    }
    if (type === 'ai_image') {
      return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>`;
    }
    if (type === 'ai_video') {
      return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`;
    }
    return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>`;
  }

  // Pieza 51 / 58: Teleprompter & Audiovisual state
  let currentAudiovisualJobs = [];
  let currentAudiovisualEstimate = null;
  let audiovisualPollInterval = null;
  let isSoundtrackFetchInFlight = false;
  let soundtrackFetchFailed = false;

  async function ensureSoundtrackLoaded(ideaId, jobs) {
    if (!ideaId || !currentScriptData || currentScriptData.state !== 'locked') return;
    const currentList = jobs || currentAudiovisualJobs || [];
    const hasMusic = currentList.some(j => j.kind === 'music' && j.status !== 'cancelled' && j.status !== 'failed');
    if (!hasMusic && !isSoundtrackFetchInFlight) {
      isSoundtrackFetchInFlight = true;
      soundtrackFetchFailed = false;
      renderAudiovisualView();
      try {
        const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/soundtrack`, {
          method: 'POST',
        });
        if (res.ok) {
          soundtrackFetchFailed = false;
          await loadAudiovisualJobs(ideaId);
          pollAudiovisualJobs(ideaId);
        } else {
          soundtrackFetchFailed = true;
        }
      } catch (err) {
        console.warn('[Audiovisual] Soundtrack endpoint failed:', err);
        soundtrackFetchFailed = true;
      } finally {
        isSoundtrackFetchInFlight = false;
        renderAudiovisualView();
      }
    }
  }

  async function fetchAudiovisualEstimate(ideaId) {
    if (!ideaId) return null;
    try {
      const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/estimate`);
      if (res.ok) {
        currentAudiovisualEstimate = await res.json();
        return currentAudiovisualEstimate;
      }
    } catch (err) {
      console.warn('[Audiovisual] Failed to fetch estimate:', err);
    }
    return null;
  }

  // Pieza 54 / 54B: HyperFrames Motion Graphics preview caching and blob lifecycle
  let activeMotionBlobUrls = [];
  const motionHtmlCache = new Map();
  let currentAudiovisualRenderId = 0;

  function cleanupAudiovisualBlobUrls() {
    if (activeMotionBlobUrls.length > 0) {
      activeMotionBlobUrls.forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch (e) {
          // ignore
        }
      });
      activeMotionBlobUrls = [];
    }
  }

  async function isHyperframesPlayerAvailable() {
    if (typeof window === 'undefined' || !window.customElements) return false;
    if (customElements.get('hyperframes-player')) return true;
    if (document.readyState === 'complete') {
      return !!customElements.get('hyperframes-player');
    }
    try {
      const definedPromise = customElements.whenDefined('hyperframes-player');
      const timeoutPromise = new Promise((resolve) => setTimeout(() => resolve(false), 2000));
      await Promise.race([definedPromise, timeoutPromise]);
      return !!customElements.get('hyperframes-player');
    } catch (e) {
      return false;
    }
  }

  function renderMotionGraphicFallback(player, template, fields) {
    const parent = player.parentElement;
    if (!parent) return;

    let fieldListHtml = '';
    const entries = Object.entries(fields || {});
    if (entries.length > 0) {
      fieldListHtml = entries
        .filter(([_, v]) => v !== null && v !== undefined && String(v).trim() !== '')
        .map(([k, v]) => {
          const valStr = Array.isArray(v) ? v.join(', ') : String(v);
          return `<div style="font-size:10px;color:var(--ink-soft);line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:130px;" title="${escapeHtml(valStr)}"><strong style="color:var(--ink);">${escapeHtml(k)}:</strong> ${escapeHtml(valStr)}</div>`;
        })
        .join('');
    }

    parent.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;padding:8px 8px 24px;text-align:center;width:100%;height:100%;box-sizing:border-box;background:var(--surface-alt);">
        <div style="font-size:10px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:0.04em;">
          ${escapeHtml(template)}
        </div>
        <div style="display:flex;flex-direction:column;gap:3px;width:100%;align-items:center;margin-top:2px;">
          ${fieldListHtml || '<div style="font-size:10px;color:var(--ink-soft);font-style:italic;">Motion graphic preview</div>'}
        </div>
      </div>
    `;
  }

  async function hydrateMotionGraphicPlayers(container, renderId) {
    const motionPlayers = container.querySelectorAll('hyperframes-player[data-motion-scene]');
    if (!motionPlayers || motionPlayers.length === 0) return;

    const isAvailable = await isHyperframesPlayerAvailable();

    motionPlayers.forEach(async (player) => {
      const sceneN = parseInt(player.dataset.motionScene, 10);
      const scene = (currentScriptData?.scenes || []).find(s => s.n === sceneN);
      const motionJob = (currentAudiovisualJobs || []).find(j => j.scene_n === sceneN && j.kind === 'motion_graphic');
      const template = motionJob?.output?.template || 'lower_third';
      const fields = motionJob?.output?.fields || {};

      if (renderId !== currentAudiovisualRenderId || !player.isConnected) return;

      if (!isAvailable) {
        renderMotionGraphicFallback(player, template, fields);
        return;
      }

      const ideaId = currentScriptData?.idea_id;
      if (!ideaId) {
        renderMotionGraphicFallback(player, template, fields);
        return;
      }

      const jobId = motionJob?.id || motionJob?.output?.storage_path || 'done';
      const cacheKey = `${ideaId}:${sceneN}:${jobId}`;

      let htmlContent = motionHtmlCache.get(cacheKey);
      if (!htmlContent) {
        try {
          const previewUrl = `/api/audiovisual/${encodeURIComponent(ideaId)}/motion/${sceneN}`;
          const res = await authenticatedFetch(previewUrl);
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
          htmlContent = await res.text();
          motionHtmlCache.set(cacheKey, htmlContent);
        } catch (err) {
          console.warn(`[MotionGraphic] Failed to fetch preview HTML for scene ${sceneN}:`, err);
          if (renderId === currentAudiovisualRenderId && player.isConnected) {
            renderMotionGraphicFallback(player, template, fields);
          }
          return;
        }
      }

      if (renderId !== currentAudiovisualRenderId || !player.isConnected) return;

      try {
        const blob = new Blob([htmlContent], { type: 'text/html' });
        const blobUrl = URL.createObjectURL(blob);
        if (renderId !== currentAudiovisualRenderId || !player.isConnected) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        activeMotionBlobUrls.push(blobUrl);
        player.setAttribute('src', blobUrl);
      } catch (err) {
        console.warn(`[MotionGraphic] Failed to create blob URL for scene ${sceneN}:`, err);
        if (renderId === currentAudiovisualRenderId && player.isConnected) {
          renderMotionGraphicFallback(player, template, fields);
        }
      }
    });
  }

  async function loadAudiovisualJobs(ideaId) {
    if (!ideaId) return [];
    try {
      const res = await authenticatedFetch(`/api/audiovisual/${ideaId}/jobs`);
      if (res.ok) {
        const data = await res.json();
        currentAudiovisualJobs = data.jobs || [];
        return currentAudiovisualJobs;
      }
    } catch (err) {
      console.warn('[Audiovisual] Failed to load jobs:', err);
    }
    return [];
  }

  function pollAudiovisualJobs(ideaId) {
    if (audiovisualPollInterval) {
      clearInterval(audiovisualPollInterval);
      audiovisualPollInterval = null;
    }
    if (!ideaId) return;

    audiovisualPollInterval = setInterval(async () => {
      if (currentOpenView !== 'audiovisual' || !currentScriptData || currentScriptData.idea_id !== ideaId) {
        clearInterval(audiovisualPollInterval);
        audiovisualPollInterval = null;
        cleanupAudiovisualBlobUrls();
        return;
      }

      const jobs = await loadAudiovisualJobs(ideaId);
      renderAudiovisualView();

      const hasActiveJobs = (jobs || []).some(j => (j.kind === 'transcript' || j.kind === 'a_roll_take' || j.kind === 'stock' || j.kind === 'ai_image' || j.kind === 'ai_video' || j.kind === 'motion_graphic' || j.kind === 'music' || j.kind === 'sfx') && (j.status === 'pending' || j.status === 'running'));
      if (!hasActiveJobs) {
        clearInterval(audiovisualPollInterval);
        audiovisualPollInterval = null;
        await fetchAudiovisualEstimate(ideaId);
        renderAudiovisualView();
      }
    }, 2500);
  }

  let selectedTimelineSceneIdx = null;

  function renderSelectedSceneDetail(sceneIdx) {
    const detailPanel = document.getElementById('AV-DetailPanel');
    if (!detailPanel || !currentScriptData || !currentScriptData.scenes) return;

    const scene = currentScriptData.scenes[sceneIdx];
    if (!scene) {
      detailPanel.style.display = 'none';
      return;
    }

    selectedTimelineSceneIdx = sceneIdx;

    // Highlight active card
    const allCards = document.querySelectorAll('.av-card');
    allCards.forEach((card) => {
      const idx = parseInt(card.dataset.sceneIndex, 10);
      if (idx === sceneIdx) {
        card.classList.add('is-active');
      } else {
        card.classList.remove('is-active');
      }
    });

    const phaseName = PHASE_NAMES[scene.phase] || (scene.phase ? scene.phase.replace(/_/g, ' ') : 'Scene');
    const startTime = formatTime(scene.start_s);
    const endTime = formatTime(scene.end_s);
    const timeRange = (scene.start_s !== null && scene.start_s !== undefined && scene.end_s !== null && scene.end_s !== undefined)
      ? `${startTime}–${endTime}` : '—';
    const assetType = scene.asset_type || 'a_roll';
    const badgeInfo = ASSET_ORIGIN_CONFIG[assetType] || ASSET_ORIGIN_CONFIG.a_roll;

    const isARoll = assetType === 'a_roll';
    const isStock = assetType === 'stock';
    const isAIImage = assetType === 'ai_image';
    const isAIVideo = assetType === 'ai_video';
    const isMotionGraphic = assetType === 'motion_graphic';

    const takeJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'a_roll_take' && j.status === 'done');
    const transcriptJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'transcript' && j.status !== 'cancelled');
    const stockJob = isStock ? (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'stock' && j.status === 'done') : null;
    const aiImageJob = isAIImage ? (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'ai_image' && j.status === 'done') : null;
    const aiVideoJob = isAIVideo ? (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'ai_video' && j.status === 'done') : null;
    const motionGraphicJob = isMotionGraphic ? (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'motion_graphic' && j.status === 'done') : null;

    let badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#F1F5F9;border:1px solid #CBD5E1;font-size:10px;font-weight:600;color:#64748B;">Pending</span>';
    if (isARoll && takeJob) {
      badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">Recorded ✓</span>';
    } else if (isStock && stockJob) {
      badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">Stock ✓</span>';
    } else if (isAIImage && aiImageJob) {
      badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">AI Image ✓</span>';
    } else if (isAIVideo && aiVideoJob) {
      badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">AI Video ✓</span>';
    } else if (isMotionGraphic && motionGraphicJob) {
      badgeStatusHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">Motion ✓</span>';
    }

    let takeBadgeHtml = '';
    if (!isARoll && takeJob) {
      takeBadgeHtml = '<span style="padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;">🎙 Your take ✓</span>';
    }

    let spokenTextSectionHtml = `
      <div>
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">Spoken Text (Founder Voice)</div>
        <div style="color:var(--ink);background:var(--surface);padding:10px 12px;border-radius:6px;border:1px solid var(--line);min-height:54px;">
          ${escapeHtml(scene.spoken_text || '—')}
        </div>
      </div>
    `;

    if (transcriptJob && transcriptJob.status === 'done' && transcriptJob.output?.text) {
      spokenTextSectionHtml = `
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">Original Guide Script</div>
          <div style="color:var(--ink-soft);background:var(--surface);padding:8px 12px;border-radius:6px;border:1px solid var(--line);font-size:12px;margin-bottom:8px;">
            ${escapeHtml(scene.spoken_text || '—')}
          </div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#15803D;font-weight:700;margin-bottom:4px;">Real Spoken Subtitles (AssemblyAI)</div>
          <div style="color:#166534;background:#F0FDF4;padding:10px 12px;border-radius:6px;border:1px solid #BBF7D0;font-weight:500;">
            "${escapeHtml(transcriptJob.output.text)}"
          </div>
        </div>
      `;
    }

    const label = takeJob ? '🎥 Retake (free)' : '🎥 Record Scene';
    const takeActionBtn = `<button type="button" class="btn btn--secondary btn-aroll-record" data-scene-n="${scene.n || (sceneIdx + 1)}" style="padding:4px 10px;font-size:11px;">${label}</button>`;

    let videoPreviewHtml = '';
    if (takeJob && takeJob.signed_url) {
      const takeTitle = isARoll ? 'Recorded Take Preview' : 'Your Take Preview (Voiceover / Backup)';
      videoPreviewHtml += `
        <div style="margin-top:12px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:6px;">${takeTitle}</div>
          <video src="${escapeHtml(takeJob.signed_url)}" controls playsinline style="max-width:240px;max-height:160px;border-radius:6px;border:1px solid var(--line);background:#000;display:block;"></video>
        </div>
      `;
    }
    if (isStock && stockJob && stockJob.output?.video_url) {
      videoPreviewHtml += `
        <div style="margin-top:12px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:6px;">Stock Video Preview</div>
          <video src="${escapeHtml(stockJob.output.video_url)}" controls playsinline style="max-width:240px;max-height:160px;border-radius:6px;border:1px solid var(--line);background:#000;display:block;"></video>
          <div id="AV-InspectorStockAttribution" style="font-size:11px;color:var(--ink-soft);margin-top:4px;"></div>
        </div>
      `;
    } else if (isAIImage && aiImageJob && aiImageJob.signed_url) {
      videoPreviewHtml += `
        <div style="margin-top:12px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:6px;">AI Image Preview</div>
          <img src="${escapeHtml(aiImageJob.signed_url)}" alt="AI Image" style="max-width:240px;max-height:160px;border-radius:6px;border:1px solid var(--line);display:block;">
        </div>
      `;
    } else if (isAIVideo && aiVideoJob && aiVideoJob.signed_url) {
      videoPreviewHtml += `
        <div style="margin-top:12px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:6px;">AI Video Preview</div>
          <video src="${escapeHtml(aiVideoJob.signed_url)}" controls playsinline style="max-width:240px;max-height:160px;border-radius:6px;border:1px solid var(--line);background:#000;display:block;"></video>
        </div>
      `;
    }

    // Asset Type Selector & SFX (Pieza 58)
    const creditsByType = currentAudiovisualEstimate?.credits_by_type;
    const isAiPaused = Boolean(currentAudiovisualEstimate?.ai_paused);
    const isSceneGenerating = (currentAudiovisualJobs || []).some(j => j.scene_n === scene.n && (j.status === 'pending' || j.status === 'running'));
    const otherAiVideoScene = (currentScriptData.scenes || []).find(s => s.n !== scene.n && s.asset_type === 'ai_video');

    const assetTypeConfigs = [
      { type: 'a_roll', label: '🎥 Camera (you)' },
      { type: 'stock', label: '🎞 Stock' },
      { type: 'motion_graphic', label: '✦ Motion graphic' },
      { type: 'ai_image', label: '🖼 AI image' },
      { type: 'ai_video', label: '🎬 AI video' }
    ];

    const SUGGESTED_NAMES = {
      a_roll: 'Camera (you)',
      stock: 'Stock',
      motion_graphic: 'Motion graphic',
      ai_image: 'AI image',
      ai_video: 'AI video'
    };

    let selectorBtnsHtml = assetTypeConfigs.map(opt => {
      let costLabel = '…';
      let isDisabled = isSceneGenerating || !creditsByType;
      let reasonTooltip = '';

      if (creditsByType && creditsByType[opt.type] !== undefined) {
        const cost = creditsByType[opt.type];
        costLabel = cost === 0 ? 'free' : `${cost} credits`;
      }

      const isSelected = assetType === opt.type;

      if (isAiPaused && (opt.type === 'ai_image' || opt.type === 'ai_video')) {
        isDisabled = true;
        reasonTooltip = 'AI generation is paused right now — Stock and Motion graphic are free';
      } else if (otherAiVideoScene && opt.type === 'ai_video' && !isSelected) {
        isDisabled = true;
        reasonTooltip = `Only 1 AI video per script — scene ${otherAiVideoScene.n} has it`;
      }

      const activeStyle = isSelected
        ? 'background:var(--accent);color:#fff;border-color:var(--accent);font-weight:700;'
        : 'background:var(--surface);color:var(--ink);border-color:var(--line);';
      const disabledStyle = isDisabled ? 'opacity:0.45;cursor:not-allowed;' : 'cursor:pointer;';

      return `
        <button type="button" class="av-asset-type-btn" data-asset-type="${opt.type}" ${isDisabled ? 'disabled' : ''} title="${escapeHtml(reasonTooltip)}" style="padding:6px 10px;font-size:11px;border:1px solid;border-radius:6px;transition:all 0.15s ease;display:inline-flex;align-items:center;gap:4px;box-sizing:border-box;${activeStyle}${disabledStyle}">
          ${escapeHtml(opt.label)} · ${escapeHtml(costLabel)}
        </button>
      `;
    }).join('');

    let selectorHelperText = '';
    if (isSceneGenerating) {
      selectorHelperText = `<div style="font-size:11px;color:var(--ink-soft);margin-top:4px;">Generating — wait to change type</div>`;
    } else if (isAiPaused) {
      selectorHelperText = `<div style="font-size:11px;color:#B45309;margin-top:4px;">AI generation is paused right now — Stock and Motion graphic are free</div>`;
    } else if (otherAiVideoScene) {
      selectorHelperText = `<div style="font-size:11px;color:var(--ink-soft);margin-top:4px;">Only 1 AI video per script — scene ${otherAiVideoScene.n} has it</div>`;
    }

    let suggestedTextHtml = '';
    if (scene.suggested_asset_type && scene.suggested_asset_type !== assetType) {
      const suggestedName = SUGGESTED_NAMES[scene.suggested_asset_type] || scene.suggested_asset_type;
      suggestedTextHtml = `<div style="font-size:11.5px;color:var(--accent);font-weight:500;margin-top:4px;">Suggested by your script: ${escapeHtml(suggestedName)}</div>`;
    }

    const assetTypeSelectorSectionHtml = `
      <div style="margin-bottom:14px;padding:12px;background:var(--surface-alt);border:1px solid var(--line);border-radius:8px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:8px;">Asset Type for Scene #${scene.n || (sceneIdx + 1)}</div>
        <div id="AV-AssetTypeSelector" style="display:flex;flex-wrap:wrap;gap:6px;">
          ${selectorBtnsHtml}
        </div>
        ${suggestedTextHtml}
        ${selectorHelperText}
        <div id="AV-AssetTypeErrorInline" style="font-size:11.5px;color:#DC2626;font-weight:600;margin-top:6px;display:none;"></div>
      </div>
    `;

    const sfxJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'sfx' && j.status === 'done');
    let sfxInspectorHtml = '';
    if (sfxJob) {
      const sfxTitle = sfxJob.output_display?.tag || sfxJob.output_display?.title || sfxJob.output?.tag || 'sound effect';
      sfxInspectorHtml = `
        <div style="margin-top:12px;padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;">
          <div style="font-weight:600;color:var(--ink);margin-bottom:4px;">Sound effect: ${escapeHtml(sfxTitle)}</div>
          ${sfxJob.signed_url ? `<audio controls preload="none" src="${escapeHtml(sfxJob.signed_url)}" style="height:30px;width:100%;max-width:300px;display:block;margin-top:4px;"></audio>` : ''}
        </div>
      `;
    }

      const hasQuery = scene.stock_query && scene.stock_query !== 'null';
      const hasPrompt = scene.visual_prompt && scene.visual_prompt !== 'null';

      let promptDetailsHtml = '';
      if (scene.asset_type === 'stock') {
        if (hasQuery) {
          promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>Stock Query:</strong> <span class="mono" style="color:var(--accent);">${escapeHtml(scene.stock_query)}</span></div>`;
        } else {
          promptDetailsHtml += `<div style="margin-bottom:4px;color:var(--ink-soft);"><strong>Stock Query:</strong> <span style="font-style:italic;">written automatically when this scene is generated</span></div>`;
        }
      } else if (hasQuery) {
        promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>Stock Query:</strong> <span class="mono" style="color:var(--accent);">${escapeHtml(scene.stock_query)}</span></div>`;
      }

      if (scene.asset_type === 'ai_image' || scene.asset_type === 'ai_video') {
        if (hasPrompt) {
          promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>Visual Prompt:</strong> <span class="mono" style="color:var(--accent);">${escapeHtml(scene.visual_prompt)}</span></div>`;
        } else {
          promptDetailsHtml += `<div style="margin-bottom:4px;color:var(--ink-soft);"><strong>Visual Prompt:</strong> <span style="font-style:italic;">written automatically when this scene is generated</span></div>`;
        }
      } else if (hasPrompt) {
        promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>Visual Prompt:</strong> <span class="mono" style="color:var(--accent);">${escapeHtml(scene.visual_prompt)}</span></div>`;
      }

      if (scene.shot) {
        promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>Camera Shot:</strong> ${escapeHtml(scene.shot)}</div>`;
      }
      if (scene.acting_note) {
        promptDetailsHtml += `<div style="margin-bottom:4px;"><strong>How to say it:</strong> ${escapeHtml(scene.acting_note)}</div>`;
      }
      if (!promptDetailsHtml) {
        promptDetailsHtml = '<div style="color:var(--ink-soft);font-style:italic;">A-roll spoken scene · no visual generation prompt needed</div>';
      }

      detailPanel.style.display = 'block';
      detailPanel.innerHTML = `
        <div style="display:flex;align-items:start;justify-content:space-between;margin-bottom:14px;border-bottom:1px solid var(--line);padding-bottom:10px;flex-wrap:wrap;gap:8px;">
          <div>
            <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);">Scene Inspector</div>
            <div style="font-size:16px;font-weight:700;color:var(--ink);margin-top:2px;">
              Scene #${scene.n || (sceneIdx + 1)} · ${escapeHtml(phaseName)}
              <span style="font-size:12px;font-weight:400;color:var(--ink-soft);margin-left:8px;">${escapeHtml(timeRange)} est.</span>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="padding:3px 8px;border-radius:4px;font-size:10px;${badgeInfo.style}">${badgeInfo.label}</span>
            ${badgeStatusHtml}
            ${takeBadgeHtml}
            ${takeActionBtn}
          </div>
        </div>

        ${assetTypeSelectorSectionHtml}

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;font-size:13px;line-height:1.5;">
          ${spokenTextSectionHtml}
          <div>
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">On-Screen Text (Subtitle)</div>
            <div style="color:var(--ink);background:var(--surface);padding:10px 12px;border-radius:6px;border:1px solid var(--line);min-height:54px;">
              ${escapeHtml(scene.on_screen_text || '—')}
            </div>
          </div>
        </div>

        ${videoPreviewHtml}
        ${sfxInspectorHtml}

        <div style="margin-top:12px;font-size:13px;line-height:1.5;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">Prompt & Direction Details</div>
          <div style="background:var(--surface);padding:10px 12px;border-radius:6px;border:1px solid var(--line);font-size:12px;color:var(--ink);">
            ${promptDetailsHtml}
          </div>
        </div>

      <div style="margin-top:12px;font-size:11.5px;color:var(--ink-soft);display:flex;align-items:center;gap:6px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
        <span>Record takes at step 1. Arranging, trimming, and reordering clips take place in Step 5 (Editing).</span>
      </div>
    `;

    // Wire asset type selector buttons
    const selectorBtns = detailPanel.querySelectorAll('.av-asset-type-btn');
    selectorBtns.forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const newType = btn.dataset.assetType;
        if (newType === assetType) return;

        selectorBtns.forEach(b => b.disabled = true);
        const errEl = detailPanel.querySelector('#AV-AssetTypeErrorInline');
        if (errEl) errEl.style.display = 'none';

        const ideaId = currentScriptData.idea_id;
        try {
          const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/scenes/${scene.n}/asset_type`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ asset_type: newType })
          });
          if (res.ok) {
            const data = await res.json();
            // TRAMPA REPO: Actualizar PRIMERO currentScriptData.scenes[sceneIdx] con data.scene
            if (data.scene) {
              currentScriptData.scenes[sceneIdx] = data.scene;
            }
            if (data.estimate) {
              currentAudiovisualEstimate = data.estimate;
            } else {
              await fetchAudiovisualEstimate(ideaId);
            }
            renderAudiovisualView();
          } else {
            const errData = await res.json().catch(() => ({}));
            if (errEl) {
              errEl.textContent = errData.error || 'Failed to change asset type';
              errEl.style.display = 'block';
            }
            selectorBtns.forEach(b => b.disabled = false);
          }
        } catch (err) {
          if (err.message !== 'PAYWALL_402') {
            if (errEl) {
              errEl.textContent = err.message || 'Error changing asset type';
              errEl.style.display = 'block';
            }
          }
          selectorBtns.forEach(b => b.disabled = false);
        }
      });
    });

    // Wire record button in detail panel if present
    const recordBtnInDetail = detailPanel.querySelector('.btn-aroll-record');
    if (recordBtnInDetail) {
      recordBtnInDetail.addEventListener('click', (e) => {
        e.stopPropagation();
        const scN = parseInt(recordBtnInDetail.dataset.sceneN, 10);
        openRecordingStudio(scN);
      });
    }

    if (isStock && stockJob && stockJob.output) {
      const inspectorAttrEl = detailPanel.querySelector('#AV-InspectorStockAttribution');
      if (inspectorAttrEl) {
        if (stockJob.output.attribution_text) {
          inspectorAttrEl.textContent = stockJob.output.attribution_text;
        } else {
          const prov = stockJob.output.provider === 'pixabay' ? 'Pixabay' : 'Pexels';
          const aut = stockJob.output.author || 'Unknown';
          inspectorAttrEl.textContent = `Video by ${aut} on ${prov}`;
        }
      }
    }
  }

  function getEstimatedDurationText(scriptData) {
    const scenes = scriptData?.scenes;
    if (!scenes || !scenes.length) return '—';
    const lastScene = scenes[scenes.length - 1];
    if (lastScene && lastScene.end_s !== null && lastScene.end_s !== undefined && !isNaN(Number(lastScene.end_s))) {
      return `${Math.round(Number(lastScene.end_s))}s est.`;
    }
    return '—';
  }

  function renderAudiovisualView() {
    cleanupAudiovisualBlobUrls();
    const renderId = ++currentAudiovisualRenderId;
    const container = document.getElementById('Audiovisual-Content');
    if (!container || !currentScriptData) return;

    const creditsByType = currentAudiovisualEstimate?.credits_by_type;

    const matchedIdea = currentCatalog?.ideas?.find(i => i.id === currentScriptData.idea_id);
    const scriptTitle = currentScriptData.title || matchedIdea?.title || 'Video Script';
    const recordingFormatText = RECORDING_FORMAT_NAMES[currentScriptData.recording_format] || currentScriptData.recording_format || 'Natural selfie';
    const durationText = getEstimatedDurationText(currentScriptData);
    const scenes = currentScriptData.scenes || [];

    // Step 1: All scenes for takes (Pieza 56)
    const totalTakesCount = scenes.length;
    const recordedTakesCount = scenes.filter(s => {
      return (currentAudiovisualJobs || []).some(j => j.scene_n === s.n && j.kind === 'a_roll_take' && j.status === 'done');
    }).length;

    let takesListHtml = '';
    if (scenes.length === 0) {
      takesListHtml = `<div style="padding:12px 14px;background:var(--surface);border:1px dashed var(--line);border-radius:6px;font-size:13px;color:var(--ink-soft);font-style:italic;">No scenes in this script.</div>`;
    } else {
      takesListHtml = scenes.map((scene, idx) => {
        const isARoll = (scene.asset_type || 'a_roll') === 'a_roll';
        const phaseName = PHASE_NAMES[scene.phase] || (scene.phase ? scene.phase.replace(/_/g, ' ') : 'Scene');
        const startTime = formatTime(scene.start_s);
        const endTime = formatTime(scene.end_s);
        const timeRange = (scene.start_s !== null && scene.start_s !== undefined && scene.end_s !== null && scene.end_s !== undefined)
          ? `${startTime}–${endTime}` : '—';

        const takeJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'a_roll_take' && j.status === 'done');
        const transcriptJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'transcript' && j.status !== 'cancelled');

        const hasTake = !!takeJob;
        const btnLabel = hasTake ? 'Recorded ✓ · Retake' : '🎥 Record';
        const btnClass = hasTake ? 'btn btn--secondary btn-aroll-record' : 'btn btn--primary btn-aroll-record';

        const roleLabelHtml = isARoll
          ? `<span style="font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:4px;background:rgba(43,76,216,0.08);color:var(--accent);border:1px solid rgba(43,76,216,0.2);">On camera</span>`
          : `<span style="font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:4px;background:#F1F5F9;color:#475569;border:1px solid #CBD5E1;">Voice over B-roll — you may or may not appear (decided in Editing)</span>`;

        let takeDetailsHtml = '';
        if (hasTake) {
          let videoPreviewHtml = '';
          if (takeJob.signed_url) {
            videoPreviewHtml = `
              <div style="margin-top:10px;">
                <video src="${escapeHtml(takeJob.signed_url)}" controls playsinline style="max-width:220px;max-height:140px;border-radius:6px;border:1px solid var(--line);background:#000;display:block;"></video>
              </div>
            `;
          }

          let transcriptHtml = '';
          if (transcriptJob && transcriptJob.status === 'done' && transcriptJob.output?.text) {
            transcriptHtml = `
              <div style="margin-top:8px;padding:8px 12px;background:#F0FDF4;border:1px solid #BBF7D0;border-radius:6px;font-size:12.5px;color:#166534;line-height:1.45;">
                <span style="font-weight:700;text-transform:uppercase;font-size:10px;letter-spacing:0.04em;display:block;margin-bottom:2px;color:#15803D;">Real Subtitles (AssemblyAI):</span>
                "${escapeHtml(transcriptJob.output.text)}"
              </div>
            `;
          } else if (transcriptJob && (transcriptJob.status === 'pending' || transcriptJob.status === 'running')) {
            transcriptHtml = `
              <div style="margin-top:8px;padding:6px 10px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:6px;font-size:12px;color:#1D4ED8;display:inline-flex;align-items:center;gap:6px;">
                <span class="spinner" style="width:12px;height:12px;border:2px solid #3B82F6;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></span>
                <span>Transcribing founder audio with AssemblyAI…</span>
              </div>
            `;
          }

          takeDetailsHtml = `
            ${videoPreviewHtml}
            ${transcriptHtml}
          `;
        }

        return `
          <div style="padding:12px 16px;background:var(--surface);border:1px solid var(--line);border-radius:6px;display:flex;gap:16px;align-items:flex-start;">
            <div style="flex-shrink:0;min-width:70px;">
              <span style="font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase;">Scene ${scene.n || (idx + 1)}</span>
              <div style="font-size:10px;color:var(--ink-soft);margin-top:2px;">${escapeHtml(timeRange)} <span style="font-size:9px;">est.</span></div>
            </div>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                  <span style="font-size:11px;font-weight:600;color:var(--ink-soft);text-transform:uppercase;letter-spacing:0.06em;">${escapeHtml(phaseName)}</span>
                  ${roleLabelHtml}
                </div>
                <button type="button" class="${btnClass}" data-scene-n="${scene.n || (idx + 1)}" style="padding:5px 12px;font-size:12px;">
                  ${btnLabel}
                </button>
              </div>
              <div style="font-size:13px;color:var(--ink);line-height:1.45;">"${escapeHtml(scene.spoken_text || '—')}"</div>
              ${takeDetailsHtml}
            </div>
          </div>
        `;
      }).join('');
    }

    // Step 2: Timeline cards
    let timelineCardsHtml = '';
    scenes.forEach((scene, idx) => {
      const phaseName = PHASE_NAMES[scene.phase] || (scene.phase ? scene.phase.replace(/_/g, ' ') : 'Scene');
      const startTime = formatTime(scene.start_s);
      const endTime = formatTime(scene.end_s);
      const timeRange = (scene.start_s !== null && scene.start_s !== undefined && scene.end_s !== null && scene.end_s !== undefined)
        ? `${startTime}–${endTime}` : '—';
      const assetType = scene.asset_type || 'a_roll';
      const badgeInfo = ASSET_ORIGIN_CONFIG[assetType] || ASSET_ORIGIN_CONFIG.a_roll;
      const iconSvg = getAssetTypeIcon(assetType);

      const isARoll = assetType === 'a_roll';
      const isStock = assetType === 'stock';
      const sceneTake = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'a_roll_take' && j.status === 'done');
      const sceneTranscript = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'transcript' && j.status !== 'cancelled');
      const stockJob = isStock ? (currentAudiovisualJobs || []).filter(j => j.scene_n === scene.n && j.kind === 'stock' && j.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0] : null;

      let bRollTakeBadgeHtml = '';
      if (!isARoll && sceneTake) {
        bRollTakeBadgeHtml = `
          <div style="position:absolute;top:6px;left:6px;z-index:4;padding:2px 6px;border-radius:4px;background:rgba(21,128,61,0.92);color:#fff;font-size:9.5px;font-weight:700;letter-spacing:0.02em;box-shadow:0 1px 3px rgba(0,0,0,0.3);display:inline-flex;align-items:center;gap:3px;" title="Take recorded (voiceover under visual)">
            🎙 Your take ✓
          </div>
        `;
      }

      let cardBadgeHtml = `
        <div style="margin-top:10px;padding:2px 8px;border-radius:10px;background:#F1F5F9;border:1px solid #CBD5E1;font-size:10px;font-weight:600;color:#64748B;letter-spacing:0.04em;">
          Pending
        </div>
      `;
      let visualContentHtml = `
        <div style="width:36px;height:36px;border-radius:50%;background:${badgeInfo.iconBg};color:${badgeInfo.iconColor};display:flex;align-items:center;justify-content:center;margin-bottom:8px;">
          ${iconSvg}
        </div>
        <div style="padding:3px 6px;border-radius:4px;font-size:9.5px;line-height:1.2;text-align:center;${badgeInfo.style}">
          ${badgeInfo.label}
        </div>
      `;

      const isAIImage = assetType === 'ai_image';
      const isAIVideo = assetType === 'ai_video';
      const isMotionGraphic = assetType === 'motion_graphic';
      const aiImageJob = isAIImage ? (currentAudiovisualJobs || []).filter(j => j.scene_n === scene.n && j.kind === 'ai_image' && j.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0] : null;
      const aiVideoJob = isAIVideo ? (currentAudiovisualJobs || []).filter(j => j.scene_n === scene.n && j.kind === 'ai_video' && j.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0] : null;
      const motionGraphicJob = isMotionGraphic ? (currentAudiovisualJobs || []).filter(j => j.scene_n === scene.n && j.kind === 'motion_graphic' && j.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0] : null;

      if (isARoll && sceneTake) {
        cardBadgeHtml = `
          <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;letter-spacing:0.04em;">
            Recorded ✓
          </div>
        `;
        if (sceneTake.signed_url) {
          visualContentHtml = `
            <video src="${escapeHtml(sceneTake.signed_url)}" playsinline muted style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:5px;"></video>
            <div style="position:absolute;top:6px;right:6px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,0.6);color:#fff;display:flex;align-items:center;justify-content:center;font-size:10px;z-index:2;">▶</div>
          `;
        }
      } else if (isStock && stockJob) {
        if (stockJob.status === 'done' && stockJob.output) {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;letter-spacing:0.04em;">
              Stock ✓
            </div>
          `;
          if (stockJob.output.preview_url) {
            visualContentHtml = `
              <img src="${escapeHtml(stockJob.output.preview_url)}" alt="Stock preview" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:5px;">
              <div style="position:absolute;top:6px;right:6px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,0.6);color:#fff;display:flex;align-items:center;justify-content:center;font-size:10px;z-index:2;">▶</div>
            `;
          }
        } else if (stockJob.status === 'pending' || stockJob.status === 'running') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEF3C7;border:1px solid #FDE68A;font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.04em;">
              Searching…
            </div>
          `;
          visualContentHtml = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;">
              <div class="spinner" style="width:24px;height:24px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>
              <div style="font-size:10px;color:var(--ink-soft);text-align:center;line-height:1.3;">Searching stock…</div>
            </div>
          `;
        } else if (stockJob.status === 'failed') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEE2E2;border:1px solid #FECACA;font-size:10px;font-weight:700;color:#DC2626;letter-spacing:0.04em;">
              Failed
            </div>
          `;
          visualContentHtml = `
            <div style="font-size:10px;color:#DC2626;text-align:center;line-height:1.3;padding:8px;">
              ${stockJob.error ? escapeHtml(stockJob.error.substring(0, 100)) : 'No stock found'}
            </div>
          `;
        }
      } else if (isAIImage && aiImageJob) {
        // AI Image: show generating spinner or the generated image
        if (aiImageJob.status === 'done' && aiImageJob.signed_url) {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;letter-spacing:0.04em;">
              AI Image ✓
            </div>
          `;
          visualContentHtml = `
            <img src="${escapeHtml(aiImageJob.signed_url)}" alt="AI generated image" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:5px;">
          `;
        } else if (aiImageJob.status === 'pending' || aiImageJob.status === 'running') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEF3C7;border:1px solid #FDE68A;font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.04em;">
              Generating…
            </div>
          `;
          visualContentHtml = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;">
              <div class="spinner" style="width:24px;height:24px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>
              <div style="font-size:10px;color:var(--ink-soft);text-align:center;line-height:1.3;">Generating…<br>(up to a few minutes)</div>
            </div>
          `;
        } else if (aiImageJob.status === 'failed') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEE2E2;border:1px solid #FECACA;font-size:10px;font-weight:700;color:#DC2626;letter-spacing:0.04em;">
              Failed
            </div>
          `;
          visualContentHtml = `
            <div style="font-size:10px;color:#DC2626;text-align:center;line-height:1.3;padding:8px;">
              ${aiImageJob.error ? escapeHtml(aiImageJob.error.substring(0, 100)) : 'Generation failed'}
            </div>
          `;
        }
      } else if (isAIVideo && aiVideoJob) {
        // AI Video: show generating spinner or the generated video
        if (aiVideoJob.status === 'done' && aiVideoJob.signed_url) {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;letter-spacing:0.04em;">
              AI Video ✓
            </div>
          `;
          visualContentHtml = `
            <video src="${escapeHtml(aiVideoJob.signed_url)}" muted loop playsinline autoplay style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:5px;"></video>
          `;
        } else if (aiVideoJob.status === 'pending' || aiVideoJob.status === 'running') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEF3C7;border:1px solid #FDE68A;font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.04em;">
              Generating…
            </div>
          `;
          visualContentHtml = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;">
              <div class="spinner" style="width:24px;height:24px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>
              <div style="font-size:10px;color:var(--ink-soft);text-align:center;line-height:1.3;">Generating…<br>(up to a few minutes)</div>
            </div>
          `;
        } else if (aiVideoJob.status === 'failed') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEE2E2;border:1px solid #FECACA;font-size:10px;font-weight:700;color:#DC2626;letter-spacing:0.04em;">
              Failed
            </div>
          `;
          visualContentHtml = `
            <div style="font-size:10px;color:#DC2626;text-align:center;line-height:1.3;padding:8px;">
              ${aiVideoJob.error ? escapeHtml(aiVideoJob.error.substring(0, 100)) : 'Generation failed'}
            </div>
          `;
        }
      } else if (isMotionGraphic && motionGraphicJob) {
        // Motion Graphic Preview (Pieza 54 / 54B)
        if (motionGraphicJob.status === 'done' && motionGraphicJob.output?.storage_path) {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#DCFCE7;border:1px solid #86EFAC;font-size:10px;font-weight:700;color:#15803D;letter-spacing:0.04em;">
              Motion ✓
            </div>
          `;
          const template = motionGraphicJob.output?.template || 'lower_third';
          const fields = motionGraphicJob.output?.fields || {};
          visualContentHtml = `
            <div style="position:absolute;inset:0;width:100%;height:100%;border-radius:5px;overflow:hidden;">
              <hyperframes-player
                data-motion-scene="${scene.n}"
                width="1080"
                height="1920"
                autoplay
                loop
                muted
                style="width:100%;height:100%;"
              ></hyperframes-player>
            </div>
            <div style="position:absolute;bottom:6px;left:6px;z-index:3;padding:2px 6px;border-radius:4px;background:rgba(0,0,0,0.7);font-size:9px;font-weight:600;color:#fff;letter-spacing:0.04em;">
              ${escapeHtml(template)}
            </div>
          `;
        } else if (motionGraphicJob.status === 'pending' || motionGraphicJob.status === 'running') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEF3C7;border:1px solid #FDE68A;font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.04em;">
              Generating…
            </div>
          `;
          visualContentHtml = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;">
              <div class="spinner" style="width:24px;height:24px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>
              <div style="font-size:10px;color:var(--ink-soft);text-align:center;line-height:1.3;">Generating…<br>(motion graphic)</div>
            </div>
          `;
        } else if (motionGraphicJob.status === 'failed') {
          cardBadgeHtml = `
            <div style="margin-top:auto;position:relative;z-index:2;padding:2px 8px;border-radius:10px;background:#FEE2E2;border:1px solid #FECACA;font-size:10px;font-weight:700;color:#DC2626;letter-spacing:0.04em;">
              Failed
            </div>
          `;
          visualContentHtml = `
            <div style="font-size:10px;color:#DC2626;text-align:center;line-height:1.3;padding:8px;">
              ${motionGraphicJob.error ? escapeHtml(motionGraphicJob.error.substring(0, 100)) : 'Generation failed'}
            </div>
          `;
        }
      }

      const isCleanQuery = (val) => typeof val === 'string' && val.trim() !== '' && val.trim().toLowerCase() !== 'null';

      let queryLabel = 'Prompt';
      let fullQuery = '';
      if (assetType === 'stock') {
        queryLabel = 'Stock';
        fullQuery = isCleanQuery(scene.stock_query) ? scene.stock_query.trim() : 'written automatically when generated';
      } else if (assetType === 'ai_image' || assetType === 'ai_video') {
        queryLabel = 'Prompt';
        fullQuery = isCleanQuery(scene.visual_prompt) ? scene.visual_prompt.trim() : 'written automatically when generated';
      } else if (assetType === 'a_roll') {
        queryLabel = 'A-roll';
        if (sceneTranscript && sceneTranscript.status === 'done' && sceneTranscript.output?.text) {
          fullQuery = sceneTranscript.output.text;
        } else {
          fullQuery = scene.spoken_text || 'Founder spoken take';
        }
      } else {
        queryLabel = 'Motion';
        fullQuery = isCleanQuery(scene.visual_prompt) ? scene.visual_prompt.trim() : 'written automatically when generated';
      }

      let stockAttributionHtml = '';
      if (isStock && stockJob && stockJob.output) {
        const prov = stockJob.output.provider === 'pixabay' ? 'Pixabay' : 'Pexels';
        const aut = stockJob.output.author || 'Unknown';
        const attrText = stockJob.output.attribution_text || '';
        stockAttributionHtml = `
          <div class="av-stock-attribution-tag" data-author="${escapeHtml(aut)}" data-provider="${escapeHtml(prov)}" data-attribution="${escapeHtml(attrText)}" style="font-size:9.5px;color:var(--ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px;"></div>
        `;
      }

      let cardRegenHtml = '';
      if (!isARoll) {
        const bRollJob = (currentAudiovisualJobs || []).filter(j => j.scene_n === scene.n && j.kind === assetType && j.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0];
        const cost = creditsByType ? creditsByType[assetType] : undefined;
        const costUnknown = cost === undefined;
        const costAttr = costUnknown ? '' : cost;
        if (bRollJob && (bRollJob.status === 'done' || bRollJob.status === 'failed')) {
          const regenLabel = costUnknown ? '⟳ Regenerate · …' : (cost === 0 ? '⟳ Another option · free' : `⟳ Regenerate · ${cost} credits`);
          cardRegenHtml = `
            <div class="av-card-regen-wrap" data-scene-n="${scene.n}" data-cost="${costAttr}" style="margin-top:auto;padding-top:2px;">
              <button type="button" class="btn-card-regen" data-scene-n="${scene.n}" data-cost="${costAttr}" ${costUnknown ? 'disabled' : ''} style="width:100%;padding:4px 6px;font-size:10px;font-weight:600;border-radius:4px;border:1px solid var(--line);background:var(--surface-alt);color:var(--ink);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:3px;white-space:nowrap;box-sizing:border-box;">
                ${escapeHtml(regenLabel)}
              </button>
              <div class="av-card-regen-confirm" style="display:none;align-items:center;justify-content:center;gap:4px;padding:3px;background:var(--surface-alt);border-radius:4px;border:1px solid var(--line);font-size:10px;">
                <span style="font-weight:600;color:var(--ink-soft);font-size:9.5px;">${cost > 0 ? `${cost} cr?` : 'Another?'}</span>
                <button type="button" class="btn-card-regen-confirm-yes" data-scene-n="${scene.n}" data-cost="${costAttr}" style="padding:2px 6px;background:var(--accent);color:#fff;border:none;border-radius:3px;font-size:9.5px;font-weight:700;cursor:pointer;">Yes</button>
                <button type="button" class="btn-card-regen-confirm-no" style="padding:2px 5px;background:transparent;color:var(--ink-soft);border:1px solid var(--line);border-radius:3px;font-size:9.5px;cursor:pointer;">✕</button>
              </div>
            </div>
          `;
        } else if (!bRollJob || (bRollJob.status !== 'pending' && bRollJob.status !== 'running')) {
          const genBtnLabel = costUnknown ? 'Generate · …' : (cost === 0 ? 'Generate · free' : `Generate · ${cost} credits`);
          cardRegenHtml = `
            <div class="av-card-gen-wrap" data-scene-n="${scene.n}" style="margin-top:auto;padding-top:2px;">
              <button type="button" class="btn-card-gen-direct" data-scene-n="${scene.n}" ${costUnknown ? 'disabled' : ''} style="width:100%;padding:4px 6px;font-size:10px;font-weight:600;border-radius:4px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:3px;white-space:nowrap;box-sizing:border-box;">
                ✨ ${escapeHtml(genBtnLabel)}
              </button>
            </div>
          `;
        }
      }

      const sfxJob = (currentAudiovisualJobs || []).find(j => j.scene_n === scene.n && j.kind === 'sfx' && j.status === 'done');
      let cardSfxChipHtml = '';
      if (sfxJob) {
        const tag = sfxJob.output_display?.tag || sfxJob.output_display?.title || sfxJob.output?.tag || 'sound effect';
        cardSfxChipHtml = `
          <div class="av-sfx-chip" data-signed-url="${escapeHtml(sfxJob.signed_url || '')}" style="margin-top:4px;font-size:10px;font-weight:600;color:var(--ink);display:inline-flex;align-items:center;gap:3px;background:var(--surface-alt);padding:2px 6px;border-radius:4px;border:1px solid var(--line);cursor:pointer;" title="Click to play sound effect">
            🔊 ${escapeHtml(tag)}
          </div>
        `;
      }

      timelineCardsHtml += `
        <div class="av-card" data-scene-index="${idx}" style="flex:0 0 160px;width:160px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px;cursor:pointer;display:flex;flex-direction:column;gap:8px;user-select:none;box-sizing:border-box;">
          <div style="display:flex;align-items:baseline;justify-content:space-between;gap:4px;">
            <span style="font-size:12px;font-weight:700;color:var(--ink);">#${scene.n || (idx + 1)} <span style="font-weight:500;color:var(--accent);">${escapeHtml(phaseName)}</span></span>
            <span style="font-size:10px;color:var(--ink-soft);white-space:nowrap;">${escapeHtml(timeRange)} <span style="font-size:9px;">est.</span></span>
          </div>

          <div style="width:100%;aspect-ratio:9/16;border-radius:6px;background:var(--surface-alt);border:1px dashed ${badgeInfo.borderStyle};display:flex;flex-direction:column;align-items:center;justify-content:center;position:relative;padding:10px 8px;text-align:center;box-sizing:border-box;overflow:hidden;">
            ${bRollTakeBadgeHtml}
            ${visualContentHtml}
            ${cardBadgeHtml}
          </div>

          <div style="font-size:11px;color:var(--ink-soft);line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:2px 0;" title="${escapeHtml(fullQuery)}">
            <span style="font-weight:600;color:var(--ink);">${escapeHtml(queryLabel)}:</span> ${escapeHtml(fullQuery)}
          </div>
          ${stockAttributionHtml}
          ${cardSfxChipHtml}
          ${cardRegenHtml}
        </div>
      `;
    });

    // Summary counts
    const counts = { a_roll: 0, stock: 0, ai_image: 0, ai_video: 0, motion_graphic: 0 };
    scenes.forEach(s => {
      const type = s.asset_type || 'a_roll';
      if (counts[type] !== undefined) counts[type]++;
      else counts[type] = 1;
    });

    const parts = [];
    if (counts.a_roll) parts.push(`${counts.a_roll} you record`);
    if (counts.stock) parts.push(`${counts.stock} stock`);
    if (counts.ai_image) parts.push(`${counts.ai_image} AI image`);
    if (counts.ai_video) parts.push(`${counts.ai_video} AI video`);
    if (counts.motion_graphic) parts.push(`${counts.motion_graphic} motion graphic`);
    const summaryCountsText = parts.length > 0 ? parts.join(' · ') : '0 scenes';

    const bRollScenes = scenes.filter(s => s.asset_type !== 'a_roll');
    const totalBroll = bRollScenes.length;
    const readyBroll = bRollScenes.filter(s => {
      const j = (currentAudiovisualJobs || []).find(job => job.scene_n === s.n && job.kind === s.asset_type && job.status === 'done');
      return !!j;
    }).length;
    const counterBadgeHtml = totalBroll > 0 ? `
      <span id="AV-ReadyCounter" style="font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:12px;background:${readyBroll === totalBroll ? '#DCFCE7' : 'var(--surface-alt)'};color:${readyBroll === totalBroll ? '#15803D' : 'var(--ink-soft)'};border:1px solid ${readyBroll === totalBroll ? '#86EFAC' : 'var(--line)'};margin-left:6px;">
        ${readyBroll} of ${totalBroll} assets ready
      </span>
    ` : '';

    const bRollJobs = (currentAudiovisualJobs || []).filter(j => j.kind !== 'a_roll_take' && j.kind !== 'transcript' && j.kind !== 'music' && j.kind !== 'sfx');
    const isGeneratingAny = bRollJobs.some(j => j.status === 'pending' || j.status === 'running');
    const hasPendingAiVideo = (currentAudiovisualJobs || []).some(j => j.kind === 'ai_video' && (j.status === 'pending' || j.status === 'running'));
    const failedBRollScenes = bRollScenes.filter(s => {
      const j = (currentAudiovisualJobs || []).filter(job => job.scene_n === s.n && job.kind === s.asset_type && job.status !== 'cancelled').sort((a,b) => (b.created_at || '').localeCompare(a.created_at || ''))[0];
      return j && j.status === 'failed';
    });
    const allBRollDone = totalBroll > 0 && readyBroll === totalBroll;

    const progressPct = totalBroll > 0 ? Math.round((readyBroll / totalBroll) * 100) : 0;
    let progressBarText = `${readyBroll} of ${totalBroll} assets ready`;
    if (!isGeneratingAny && readyBroll === totalBroll && totalBroll > 0) {
      progressBarText = 'Assets generated ✓';
    } else if (!isGeneratingAny && failedBRollScenes.length > 0) {
      progressBarText = `Retry failed (${failedBRollScenes.length})`;
    }

    const progressBarHtml = totalBroll > 0 ? `
      <div style="margin-top:14px;width:100%;max-width:520px;">
        <div style="display:flex;align-items:center;justify-content:space-between;font-size:12px;font-weight:600;color:var(--ink);margin-bottom:6px;">
          <span>${escapeHtml(progressBarText)}</span>
          ${hasPendingAiVideo ? '<span style="font-size:11.5px;font-weight:500;color:var(--accent);">AI video takes 1–3 minutes — you can keep working.</span>' : ''}
        </div>
        <div style="width:100%;height:8px;background:var(--surface-alt);border-radius:4px;overflow:hidden;border:1px solid var(--line);">
          <div style="height:100%;width:${progressPct}%;background:${readyBroll === totalBroll ? '#16A34A' : '#2B4CD8'};transition:width 0.4s ease;"></div>
        </div>
      </div>
    ` : '';

    const musicJob = (currentAudiovisualJobs || []).find(j => j.kind === 'music' && j.status !== 'cancelled');
    let soundtrackHtml = '';
    if (isSoundtrackFetchInFlight || (musicJob && (musicJob.status === 'pending' || musicJob.status === 'running'))) {
      soundtrackHtml = `
        <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;">
          <span style="font-weight:600;color:var(--ink);">♪ Soundtrack:</span> <span style="color:var(--ink-soft);font-style:italic;">choosing…</span>
        </div>
      `;
    } else if (!musicJob && soundtrackFetchFailed) {
      soundtrackHtml = `
        <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;color:var(--ink-soft);display:flex;align-items:center;justify-content:space-between;">
          <div><span style="font-weight:600;color:var(--ink);">♪ Soundtrack:</span> <span style="color:var(--ink-soft);">not chosen yet</span></div>
          <button id="AV-SoundtrackRetryBtn" style="padding:3px 8px;font-size:11px;background:var(--surface-alt);border:1px solid var(--line);border-radius:4px;cursor:pointer;">Retry</button>
        </div>
      `;
    } else if (musicJob && musicJob.status === 'failed') {
      soundtrackHtml = `
        <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;color:var(--ink-soft);display:flex;align-items:center;justify-content:space-between;">
          <div><span style="font-weight:600;color:var(--ink);">♪ Soundtrack:</span> <span style="color:var(--ink-soft);">couldn't choose one</span></div>
          <button id="AV-SoundtrackRetryBtn" style="padding:3px 8px;font-size:11px;background:var(--surface-alt);border:1px solid var(--line);border-radius:4px;cursor:pointer;">Retry</button>
        </div>
      `;
    } else if (!musicJob) {
      soundtrackHtml = `
        <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;">
          <span style="font-weight:600;color:var(--ink);">♪ Soundtrack:</span> <span style="color:var(--ink-soft);font-style:italic;">choosing…</span>
        </div>
      `;
    } else if (musicJob.status === 'done') {
      const isNoMusic = musicJob.output?.use_music === false || musicJob.output_display?.use_music === false;
      if (isNoMusic) {
        const reason = musicJob.output_display?.reason || musicJob.output?.reason || 'No background music requested';
        soundtrackHtml = `
          <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;color:var(--ink-soft);">
            <span style="font-weight:600;color:var(--ink);">♪ No background music</span> — ${escapeHtml(reason)}
          </div>
        `;
      } else {
        const title = musicJob.output_display?.title || musicJob.output?.title || 'Background Track';
        const mood = musicJob.output_display?.mood || musicJob.output?.mood || '';
        const energy = musicJob.output_display?.energy || musicJob.output?.energy || '';
        const reason = musicJob.output_display?.reason || musicJob.output?.reason || '';
        const signedUrl = musicJob.signed_url || musicJob.output?.signed_url || '';

        const moodEnergyText = [mood, energy].filter(Boolean).join(', ');
        const trackDetails = moodEnergyText ? ` — ${moodEnergyText}` : '';

        soundtrackHtml = `
          <div style="margin-top:12px;padding:12px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font-size:12.5px;">
            <div style="font-weight:600;color:var(--ink);margin-bottom:4px;">
              ♪ Soundtrack: ${escapeHtml(title)}${escapeHtml(trackDetails)}
            </div>
            ${signedUrl ? `<audio controls preload="none" src="${escapeHtml(signedUrl)}" style="height:32px;width:100%;max-width:360px;margin-top:4px;display:block;"></audio>` : ''}
            ${reason ? `<div style="font-size:11px;color:var(--ink-soft);margin-top:4px;">${escapeHtml(reason)}</div>` : ''}
          </div>
        `;
      }
    }

    let mainActionBtnHtml = '';
    if (totalBroll === 0) {
      mainActionBtnHtml = `
        <button class="btn btn--secondary" disabled style="padding:10px 22px;font-size:14px;opacity:0.7;cursor:default;">
          All scenes recorded
        </button>
      `;
    } else if (isGeneratingAny) {
      mainActionBtnHtml = `
        <button id="AV-GenerateBtn" class="btn btn--go" disabled style="padding:10px 22px;font-size:14px;opacity:0.7;cursor:wait;display:inline-flex;align-items:center;gap:8px;">
          <span class="spinner" style="width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;display:inline-block;"></span>
          Generating assets…
        </button>
      `;
    } else if (failedBRollScenes.length > 0) {
      mainActionBtnHtml = `
        <button id="AV-RetryFailedBtn" class="btn btn--go" style="padding:10px 22px;font-size:14px;background:#DC2626;border-color:#DC2626;cursor:pointer;">
          Retry failed (${failedBRollScenes.length})
        </button>
      `;
    } else if (allBRollDone) {
      mainActionBtnHtml = `
        <button class="btn btn--go" disabled style="padding:10px 22px;font-size:14px;background:#16A34A;border-color:#16A34A;opacity:1;cursor:default;">
          Assets generated ✓
        </button>
      `;
    } else {
      mainActionBtnHtml = `
        <button id="AV-GenerateBtn" class="btn btn--go" style="padding:10px 22px;font-size:14px;cursor:pointer;">
          ✨ Generate assets
        </button>
      `;
    }

    container.innerHTML = `
      <!-- Cabecera -->
      <div class="dochead" style="display:flex;align-items:start;justify-content:space-between;padding:26px 40px 16px;border-bottom:1px solid var(--line);">
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">Audiovisual Studio · Locked Script</div>
          <h1 class="disp" style="margin:0 0 10px;font-size:26px;font-weight:600;letter-spacing:-.02em;color:var(--ink);">${escapeHtml(scriptTitle)}</h1>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-soft);">
            <span style="display:inline-flex;align-items:center;gap:6px;background:var(--surface-alt);padding:4px 10px;border-radius:4px;border:1px solid var(--line);font-weight:500;color:var(--ink);">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg>
              Vertical 9:16
            </span>
            <span style="display:inline-flex;align-items:center;gap:6px;background:var(--surface-alt);padding:4px 10px;border-radius:4px;border:1px solid var(--line);font-weight:500;color:var(--ink);">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              ${escapeHtml(durationText)}
            </span>
            <span style="display:inline-flex;align-items:center;gap:6px;background:var(--surface-alt);padding:4px 10px;border-radius:4px;border:1px solid var(--line);font-weight:500;color:var(--ink);">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 7 16 12 23 17 23 7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              ${escapeHtml(recordingFormatText)}
            </span>
          </div>
        </div>
      </div>

      <!-- Paso 1: Record your takes -->
      <div style="padding:24px 40px;border-bottom:1px solid var(--line);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px;">
          <div>
            <h2 style="font-size:16px;font-weight:600;color:var(--ink);margin:0 0 4px;display:flex;align-items:center;gap:8px;">
              <span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:700;">1</span>
              <span>Record your takes</span>
              <span id="AV-TakesCounter" style="font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:12px;background:${recordedTakesCount === totalTakesCount && totalTakesCount > 0 ? '#DCFCE7' : 'var(--surface-alt)'};color:${recordedTakesCount === totalTakesCount && totalTakesCount > 0 ? '#15803D' : 'var(--ink-soft)'};border:1px solid ${recordedTakesCount === totalTakesCount && totalTakesCount > 0 ? '#86EFAC' : 'var(--line)'};margin-left:6px;">
                Takes recorded: ${recordedTakesCount} of ${totalTakesCount}
              </span>
            </h2>
            <div style="font-size:13px;color:var(--ink-soft);">Recorded takes cost nothing. Record before generating AI assets.</div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:11.5px;font-weight:600;color:#1B7F4C;">Takes recorded: ${recordedTakesCount} of ${totalTakesCount}</span>
            <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#1B7F4C;background:rgba(27,127,76,0.08);padding:3px 8px;border-radius:4px;border:1px solid rgba(27,127,76,0.2);">
              Step 1 of 2
            </span>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px;">
          ${takesListHtml}
        </div>

        <div style="padding:10px 14px;background:#FFF9EB;border:1px solid #FDE68A;border-radius:6px;font-size:12.5px;color:#92400E;line-height:1.5;margin-bottom:6px;display:flex;align-items:flex-start;gap:8px;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;margin-top:2px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
          <span>The teleprompter is a guide, not a script — improvise freely. What you say becomes your real subtitles.</span>
        </div>
      </div>

      <!-- Paso 2: Assets - timeline -->
      <div style="padding:24px 40px;border-bottom:1px solid var(--line);overflow:hidden;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px;">
          <div>
            <h2 style="font-size:16px;font-weight:600;color:var(--ink);margin:0 0 4px;display:flex;align-items:center;gap:8px;">
              <span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:700;">2</span>
              <span>Assets — timeline</span>
              ${counterBadgeHtml}
            </h2>
            <div style="font-size:13px;color:var(--ink-soft);">Ordered scene storyboard. Click any scene to inspect spoken text, subtitle, and prompt.</div>
          </div>
          <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:var(--accent);background:rgba(43,76,216,0.08);padding:3px 8px;border-radius:4px;border:1px solid rgba(43,76,216,0.2);">
            Step 2 of 2
          </span>
        </div>

        <!-- Horizontal strip carousel: scroll ONLY inside the strip with small ‹ › arrows -->
        <div class="av-timeline-carousel" style="display:flex;align-items:center;gap:8px;position:relative;margin-bottom:6px;">
          <button type="button" id="AV-Timeline-PrevBtn" class="av-timeline-nav-btn" aria-label="Previous scene" title="Previous scene">‹</button>
          <div class="av-timeline-strip-wrapper" style="flex:1;min-width:0;overflow-x:auto;overflow-y:hidden;scroll-behavior:smooth;">
            <div class="av-timeline-strip" style="display:inline-flex;gap:14px;min-width:100%;padding:4px 2px;">
              ${timelineCardsHtml}
            </div>
          </div>
          <button type="button" id="AV-Timeline-NextBtn" class="av-timeline-nav-btn" aria-label="Next scene" title="Next scene">›</button>
        </div>

        <!-- Detail panel expanded on click -->
        <div id="AV-DetailPanel" style="margin-top:12px;padding:16px 20px;border:1px solid var(--line);border-radius:8px;background:var(--surface-alt);display:none;"></div>
      </div>

      <!-- Resumen -->
      <div style="padding:24px 40px 32px;background:var(--surface-alt);border-radius:0 0 8px 8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;">
          <div>
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--ink-soft);font-weight:600;margin-bottom:4px;">Asset Breakdown</div>
            <div style="font-size:15px;font-weight:600;color:var(--ink);margin-bottom:4px;">
              ${escapeHtml(summaryCountsText)}
            </div>
            <div style="font-size:13px;color:var(--ink-soft);">
              AI-generated video is the most expensive asset. Stock and your own takes cost nothing.
            </div>
          </div>
          <div id="AV-MainActionContainer">
            ${mainActionBtnHtml}
          </div>
        </div>
        ${progressBarHtml}
        ${soundtrackHtml}
        <!-- Estimate & Confirmation Panel (Pieza 55) -->
        <div id="AV-ConfirmPanel" style="display:none;margin-top:18px;padding:20px;background:var(--surface);border:1px solid var(--line);border-radius:8px;"></div>
      </div>
    `;

    // Pieza 54B: Hydrate HyperFrames Motion Graphic players with authenticated blobs
    hydrateMotionGraphicPlayers(container, renderId);

    // Populate stock card attribution text using textContent
    container.querySelectorAll('.av-stock-attribution-tag').forEach((el) => {
      if (el.dataset.attribution) {
        el.textContent = el.dataset.attribution;
      } else {
        const author = el.dataset.author || 'Unknown';
        const provider = el.dataset.provider || 'Pexels';
        el.textContent = `Video by ${author} on ${provider}`;
      }
    });

    // Wire direct generate buttons on cards
    container.querySelectorAll('.btn-card-gen-direct').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const scN = parseInt(btn.dataset.sceneN, 10);
        triggerRegenerateScene(scN, btn);
      });
    });

    // Wire SFX chips on cards
    container.querySelectorAll('.av-sfx-chip').forEach((chip) => {
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = chip.dataset.signedUrl;
        if (url) {
          const audio = new Audio(url);
          audio.play().catch(console.warn);
        }
      });
    });

    // Wire Generate assets button (Pieza 55)
    const genBtn = container.querySelector('#AV-GenerateBtn');
    if (genBtn) {
      genBtn.addEventListener('click', async () => {
        genBtn.disabled = true;
        genBtn.innerHTML = '<span class="spinner" style="width:13px;height:13px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;display:inline-block;"></span> Estimating…';
        const ideaId = currentScriptData.idea_id;
        try {
          const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/estimate`);
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            alert(errData.error || 'Failed to estimate audiovisual generation');
            renderAudiovisualView();
            return;
          }
          const estData = await res.json();
          renderAudiovisualEstimatePanel(container, estData, ideaId);
        } catch (err) {
          if (err.message !== 'PAYWALL_402') {
            console.error('[Audiovisual] Estimate error:', err);
            alert('Failed to estimate assets: ' + err.message);
          }
          renderAudiovisualView();
        }
      });
    }

    // Wire Retry failed button (Pieza 55)
    const retryFailedBtn = container.querySelector('#AV-RetryFailedBtn');
    if (retryFailedBtn) {
      retryFailedBtn.addEventListener('click', async () => {
        retryFailedBtn.disabled = true;
        retryFailedBtn.innerHTML = '<span class="spinner" style="width:13px;height:13px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;display:inline-block;"></span> Retrying…';
        const ideaId = currentScriptData.idea_id;
        for (const s of failedBRollScenes) {
          try {
            const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/scenes/${s.n}/regenerate`, {
              method: 'POST',
            });
            if (res.ok) {
              const resData = await res.json();
              if (resData.credits_remaining !== undefined) {
                credits = resData.credits_remaining;
                updateCreditsUI(resData.credits_remaining, initialSessionCredits);
              }
            }
          } catch (e) {
            console.error('[Audiovisual] Retry scene error:', e);
          }
        }
        await loadAudiovisualJobs(ideaId);
        pollAudiovisualJobs(ideaId);
        renderAudiovisualView();
      });
    }

    const prevBtn = container.querySelector('#AV-Timeline-PrevBtn');
    const nextBtn = container.querySelector('#AV-Timeline-NextBtn');

    function updateTimelineArrows(currentIdx, totalScenes) {
      if (prevBtn) {
        prevBtn.disabled = currentIdx <= 0;
      }
      if (nextBtn) {
        nextBtn.disabled = currentIdx >= totalScenes - 1;
      }
    }

    function selectScene(idx, shouldScroll = true) {
      if (idx < 0 || idx >= scenes.length) return;
      renderSelectedSceneDetail(idx);
      updateTimelineArrows(idx, scenes.length);

      if (shouldScroll) {
        const targetCard = container.querySelector(`.av-card[data-scene-index="${idx}"]`);
        if (targetCard) {
          targetCard.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
      }
    }

    // Wire timeline card clicks: open inspector and scroll so next card is visible on right
    const cardEls = container.querySelectorAll('.av-card');
    cardEls.forEach((cardEl) => {
      cardEl.addEventListener('click', () => {
        const idx = parseInt(cardEl.dataset.sceneIndex, 10);
        selectScene(idx, true);
      });
    });

    // Wire ‹ › navigation arrows
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        const currentIdx = selectedTimelineSceneIdx !== null ? selectedTimelineSceneIdx : 0;
        if (currentIdx > 0) {
          selectScene(currentIdx - 1, true);
        }
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const currentIdx = selectedTimelineSceneIdx !== null ? selectedTimelineSceneIdx : 0;
        if (currentIdx < scenes.length - 1) {
          selectScene(currentIdx + 1, true);
        }
      });
    }

    // Default select first scene
    if (scenes.length > 0) {
      selectScene(0, false);
    }

    // Wire A-roll record buttons
    const aRollRecordBtns = container.querySelectorAll('.btn-aroll-record');
    aRollRecordBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const scN = parseInt(btn.dataset.sceneN, 10);
        openRecordingStudio(scN);
      });
    });

    const soundtrackRetryBtn = container.querySelector('#AV-SoundtrackRetryBtn');
    if (soundtrackRetryBtn) {
      soundtrackRetryBtn.addEventListener('click', () => {
        if (currentScriptData && currentScriptData.idea_id) {
          ensureSoundtrackLoaded(currentScriptData.idea_id, currentAudiovisualJobs);
        }
      });
    }
  }

  async function triggerRegenerateScene(sceneN, btnEl) {
    if (!currentScriptData || !currentScriptData.idea_id) return;
    const ideaId = currentScriptData.idea_id;
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = 'Regenerating…';
    }
    try {
      const res = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/scenes/${sceneN}/regenerate`, {
        method: 'POST',
      });
      if (res.ok) {
        const data = await res.json();
        if (data.credits_remaining !== undefined) {
          credits = data.credits_remaining;
          updateCreditsUI(data.credits_remaining, initialSessionCredits);
        }
        await loadAudiovisualJobs(ideaId);
        pollAudiovisualJobs(ideaId);
        renderAudiovisualView();
      } else {
        const errData = await res.json().catch(() => ({}));
        alert(errData.error || 'Failed to regenerate asset');
        if (btnEl) btnEl.disabled = false;
      }
    } catch (err) {
      if (err.message !== 'PAYWALL_402') {
        console.error('[Audiovisual] Regenerate scene error:', err);
        alert('Failed to regenerate asset: ' + err.message);
      }
      if (btnEl) btnEl.disabled = false;
    }
  }

  function renderAudiovisualEstimatePanel(container, estData, ideaId) {
    if (estData) {
      currentAudiovisualEstimate = estData;
    }
    const confirmPanel = container.querySelector('#AV-ConfirmPanel');
    if (!confirmPanel) return;

    const scenesList = (estData.scenes || []).filter(s => s.asset_type !== 'a_roll');
    const creditsNeeded = (estData.credits_pending !== undefined) ? estData.credits_pending : (estData.credits_total || 0);
    const userBalance = Number(credits) || 0;
    const balanceAfter = userBalance - creditsNeeded;
    const hasEnoughBalance = balanceAfter >= 0;

    const allNonARollReady = scenesList.length > 0 && scenesList.every(s => Boolean(s.has_live_asset));
    const isAllAssetsReady = creditsNeeded === 0 && allNonARollReady;

    const isAiPaused = Boolean(estData.ai_paused || currentAudiovisualEstimate?.ai_paused);
    const hasAiScenes = (estData.scenes || []).some(s => s.asset_type === 'ai_image' || s.asset_type === 'ai_video');
    const overAiVideo = Boolean(estData.over_ai_video_limit);
    const overCeiling = Boolean(estData.over_ceiling);
    const isBlocked = overAiVideo || overCeiling || !hasEnoughBalance || (isAiPaused && hasAiScenes) || isAllAssetsReady;

    let rowsHtml = scenesList.map(s => {
      const phaseName = PHASE_NAMES[s.phase] || (s.phase ? s.phase.replace(/_/g, ' ') : 'Scene');
      const badge = ASSET_ORIGIN_CONFIG[s.asset_type] || ASSET_ORIGIN_CONFIG.a_roll;
      const isReady = Boolean(s.has_live_asset);
      const rowStyle = isReady ? 'border-bottom:1px solid var(--line);opacity:0.65;' : 'border-bottom:1px solid var(--line);';
      const creditsDisplay = isReady ? '0 credits' : `${s.credits} credits`;
      const readyBadge = isReady ? ' <span style="font-size:10.5px;color:var(--ink-soft);margin-left:4px;">✓ ready</span>' : '';
      return `
        <tr style="${rowStyle}">
          <td style="padding:8px 10px;font-weight:600;color:var(--ink);">Scene #${s.scene_n}</td>
          <td style="padding:8px 10px;color:var(--ink-soft);">${escapeHtml(phaseName)}</td>
          <td style="padding:8px 10px;"><span style="padding:2px 6px;border-radius:4px;font-size:10px;${badge.style}">${badge.label}</span>${readyBadge}</td>
          <td style="padding:8px 10px;text-align:right;font-weight:600;color:var(--ink);">${creditsDisplay}</td>
        </tr>
      `;
    }).join('');

    let warningHtml = '';
    if (isAiPaused && hasAiScenes) {
      warningHtml = `
        <div style="margin-bottom:12px;padding:10px 14px;background:#FEF2F2;border:1px solid #FCA5A5;border-radius:6px;font-size:12.5px;color:#991B1B;font-weight:600;">
          AI generation is paused right now. Switch AI scenes to Stock or Motion graphic (free) to continue.
        </div>
      `;
    } else if (overAiVideo) {
      warningHtml = `
        <div style="margin-bottom:12px;padding:8px 12px;background:#FEE2E2;border:1px solid #FECACA;border-radius:6px;font-size:12px;color:#DC2626;font-weight:500;">
          AI video limit exceeded: maximum 1 AI video scene allowed per script.
        </div>
      `;
    } else if (overCeiling) {
      warningHtml = `
        <div style="margin-bottom:12px;padding:8px 12px;background:#FEE2E2;border:1px solid #FECACA;border-radius:6px;font-size:12px;color:#DC2626;font-weight:500;">
          Cost ceiling exceeded: script exceeds cost limit.
        </div>
      `;
    } else if (!hasEnoughBalance) {
      warningHtml = `
        <div style="margin-bottom:12px;padding:8px 12px;background:#FEF3C7;border:1px solid #FDE68A;border-radius:6px;font-size:12px;color:#92400E;display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <span>Insufficient balance (${userBalance} credits available, ${creditsNeeded} needed).</span>
          <button type="button" id="AV-EstimatePaywallBtn" class="btn btn--primary" style="padding:4px 10px;font-size:11px;">Get credits</button>
        </div>
      `;
    }

    const buttonLabel = isAllAssetsReady ? 'All assets ready' : `Generate · ${creditsNeeded} credits`;

    confirmPanel.style.display = 'block';
    confirmPanel.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <h3 style="margin:0;font-size:15px;font-weight:600;color:var(--ink);">Generate Assets Confirmation</h3>
        <button type="button" id="AV-CancelEstimateBtn" class="btn btn--secondary" style="padding:3px 8px;font-size:11px;">✕</button>
      </div>

      <table style="width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:14px;">
        <thead>
          <tr style="border-bottom:1px solid var(--line);text-align:left;font-size:10.5px;text-transform:uppercase;color:var(--ink-soft);letter-spacing:0.04em;">
            <th style="padding:6px 10px;">Scene</th>
            <th style="padding:6px 10px;">Phase</th>
            <th style="padding:6px 10px;">Asset Type</th>
            <th style="padding:6px 10px;text-align:right;">Credits</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>

      <div style="background:var(--surface-alt);border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:12.5px;display:flex;flex-direction:column;gap:5px;">
        <div style="display:flex;justify-content:space-between;">
          <span style="color:var(--ink-soft);">Total credits needed:</span>
          <span style="font-weight:700;color:var(--ink);">${creditsNeeded} credits</span>
        </div>
        <div style="display:flex;justify-content:space-between;">
          <span style="color:var(--ink-soft);">Current balance:</span>
          <span style="font-weight:600;color:var(--ink);">${userBalance} credits</span>
        </div>
        <div style="display:flex;justify-content:space-between;border-top:1px solid var(--line);padding-top:5px;">
          <span style="color:var(--ink-soft);">Balance after generation:</span>
          <span style="font-weight:700;color:${hasEnoughBalance ? 'var(--ink)' : '#DC2626'};">${hasEnoughBalance ? `${balanceAfter} credits` : 'Insufficient balance'}</span>
        </div>
      </div>

      ${warningHtml}

      <div style="display:flex;align-items:center;justify-content:flex-end;gap:10px;">
        <button type="button" id="AV-CloseEstimateBtn" class="btn btn--secondary" style="padding:8px 16px;font-size:13px;">Cancel</button>
        <button type="button" id="AV-ConfirmGenerateBtn" class="btn btn--go" ${isBlocked ? 'disabled style="padding:8px 20px;font-size:13px;opacity:0.5;cursor:not-allowed;"' : 'style="padding:8px 20px;font-size:13px;cursor:pointer;"'}>
          ${escapeHtml(buttonLabel)}
        </button>
      </div>
    `;

    const cancelBtn = confirmPanel.querySelector('#AV-CancelEstimateBtn');
    const closeBtn = confirmPanel.querySelector('#AV-CloseEstimateBtn');
    const paywallBtn = confirmPanel.querySelector('#AV-EstimatePaywallBtn');
    const confirmBtn = confirmPanel.querySelector('#AV-ConfirmGenerateBtn');

    if (cancelBtn) cancelBtn.onclick = () => renderAudiovisualView();
    if (closeBtn) closeBtn.onclick = () => renderAudiovisualView();
    if (paywallBtn) paywallBtn.onclick = () => showPaywall();

    if (confirmBtn && !isBlocked) {
      confirmBtn.addEventListener('click', async () => {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<span class="spinner" style="width:13px;height:13px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;display:inline-block;"></span> Launching…';
        try {
          const genRes = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/generate`, {
            method: 'POST',
          });
          if (genRes.ok) {
            const genData = await genRes.json();
            if (genData.credits_remaining !== undefined) {
              credits = genData.credits_remaining;
              updateCreditsUI(genData.credits_remaining, initialSessionCredits);
            }
            currentAudiovisualJobs = genData.jobs || [];
            pollAudiovisualJobs(ideaId);
            renderAudiovisualView();
          } else {
            const errData = await genRes.json().catch(() => ({}));
            if (genRes.status === 503 && (errData.code === 'ai_paused' || errData.ai_paused)) {
              estData.ai_paused = true;
              if (currentAudiovisualEstimate) currentAudiovisualEstimate.ai_paused = true;
              renderAudiovisualEstimatePanel(container, estData, ideaId);
            } else {
              alert(errData.error || 'Failed to generate assets');
              renderAudiovisualView();
            }
          }
        } catch (err) {
          if (err.message !== 'PAYWALL_402') {
            console.error('[Audiovisual] Generate assets error:', err);
            alert('Failed to generate assets: ' + err.message);
          }
          renderAudiovisualView();
        }
      });
    }
  }

  // =============================================================================
  // PIEZA 49: LIGHT DOC NAVIGATION LOADING INDICATOR
  // =============================================================================
  function showDocLoading(text = 'Loading…') {
    const el = document.getElementById('Doc-LoadingIndicator');
    if (!el) return;
    const textEl = el.querySelector('.doc-loading-text');
    if (textEl) textEl.textContent = text;
    el.style.display = 'flex';
  }

  function hideDocLoading() {
    const el = document.getElementById('Doc-LoadingIndicator');
    if (!el) return;
    el.style.display = 'none';
  }

  // Show Audiovisual view (Pieza 46 / Pieza 51)
  function showAudiovisualView() {
    hideEditingView();
    showDocLoading('Loading audiovisual studio…');
    try {
      currentOpenView = 'audiovisual';
      if (blockAView) blockAView.style.display = 'none';
      if (blockBView) blockBView.style.display = 'none';
      if (blockCView) blockCView.style.display = 'none';
      if (audiovisualView) audiovisualView.style.display = 'block';

      const guardEl = document.getElementById('Audiovisual-Guard');
      const contentEl = document.getElementById('Audiovisual-Content');

      // Guard: currentScriptData must exist and state must be 'locked'
      if (!currentScriptData || currentScriptData.state !== 'locked') {
        if (contentEl) contentEl.style.display = 'none';
        if (guardEl) {
          guardEl.style.display = 'block';
          const goScriptBtn = document.getElementById('Audiovisual-Guard-GoScriptBtn');
          if (goScriptBtn) {
            goScriptBtn.onclick = () => {
              if (currentScriptIdeaId) {
                showBlockCView(currentScriptIdeaId);
              } else {
                loadCatalogCache().then(() => showBlockBView());
              }
            };
          }
        }
        if (typeof renderPipelineRail === 'function') {
          renderPipelineRail();
        }
        return;
      }

      if (guardEl) guardEl.style.display = 'none';
      if (contentEl) {
        contentEl.style.display = 'block';
        const ideaId = currentScriptData.idea_id;
        fetchAudiovisualEstimate(ideaId).then(() => {
          renderAudiovisualView();
        });
        loadAudiovisualJobs(ideaId).then(async (jobs) => {
          renderAudiovisualView();
          await ensureSoundtrackLoaded(ideaId, jobs);
          try {
            const prepRes = await authenticatedFetch(`/api/audiovisual/${encodeURIComponent(ideaId)}/prepare`, {
              method: 'POST',
            });
            if (prepRes.ok) {
              const prepData = await prepRes.json();
              if (prepData.changed && Array.isArray(prepData.scenes) && currentScriptData && Array.isArray(currentScriptData.scenes)) {
                const sceneMap = new Map(prepData.scenes.map(s => [s.n, s]));
                currentScriptData.scenes = currentScriptData.scenes.map(s => sceneMap.get(s.n) || s);
                renderAudiovisualView();
              }
            }
          } catch (prepErr) {
            console.warn('[Audiovisual] Prepare asset prompts failed:', prepErr);
          }
          const currentJobs = currentAudiovisualJobs || jobs || [];
          const hasActiveJobs = (currentJobs).some(j => (j.kind === 'transcript' || j.kind === 'a_roll_take' || j.kind === 'stock' || j.kind === 'ai_image' || j.kind === 'ai_video' || j.kind === 'motion_graphic' || j.kind === 'music' || j.kind === 'sfx') && (j.status === 'pending' || j.status === 'running'));
          if (hasActiveJobs) {
            pollAudiovisualJobs(ideaId);
          }
        });
        renderAudiovisualView();
      }

      if (typeof renderPipelineRail === 'function') {
        renderPipelineRail();
      }
    } finally {
      hideDocLoading();
    }
  }

  // =============================================================================
  // PIEZA 51: RECORDING STUDIO & TELEPROMPTER CONTROLLER
  // =============================================================================
  let studioActiveSceneN = null;
  let studioCameraStream = null;
  let studioMediaRecorder = null;
  let studioRecordedChunks = [];
  let studioRecordedBlob = null;
  let studioRecordedMime = 'video/webm';
  let studioRecordStartTime = null;
  let studioTimerInterval = null;
  let studioCountdownTimer = null;
  let studioRafId = null;
  let studioLastTs = null;
  let studioScrollY = 0;
  let studioIsPlaying = false;
  let studioIsRecording = false;

  async function openRecordingStudio(sceneN) {
    if (!currentScriptData || !currentScriptData.scenes) return;
    const allScenes = currentScriptData.scenes;
    if (!allScenes.length) return;

    const targetScene = allScenes.find(s => s.n === sceneN) || allScenes[0];
    studioActiveSceneN = targetScene.n;

    const overlay = document.getElementById('Recording-Studio-Overlay');
    if (!overlay) return;

    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    updateStudioSceneUI(targetScene, allScenes);
    resetStudioTeleprompter();
    resetStudioRecordingState();

    await startStudioCamera();
  }

  function closeRecordingStudio() {
    stopStudioRecording();
    stopStudioCamera();

    if (studioCountdownTimer) {
      clearInterval(studioCountdownTimer);
      studioCountdownTimer = null;
    }

    const previewVideo = document.getElementById('Studio-PreviewVideo');
    if (previewVideo && previewVideo.src) {
      URL.revokeObjectURL(previewVideo.src);
      previewVideo.src = '';
    }

    const overlay = document.getElementById('Recording-Studio-Overlay');
    if (overlay) overlay.style.display = 'none';
    document.body.style.overflow = '';

    renderAudiovisualView();
  }

  function setStudioCameraAvailable(hasStream) {
    const recordBtn = document.getElementById('Studio-RecordBtn');
    const retryBarBtn = document.getElementById('Studio-RetryCameraBarBtn');

    if (recordBtn) {
      if (hasStream) {
        recordBtn.disabled = false;
        recordBtn.style.opacity = '1';
        recordBtn.style.cursor = 'pointer';
        recordBtn.innerHTML = '<span style="width:10px;height:10px;border-radius:50%;background:#fff;display:inline-block;"></span> Record';
      } else {
        recordBtn.disabled = true;
        recordBtn.style.opacity = '0.6';
        recordBtn.style.cursor = 'not-allowed';
        recordBtn.innerHTML = '<span style="width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,0.4);display:inline-block;"></span> Camera needed';
      }
    }

    if (retryBarBtn) {
      retryBarBtn.style.display = hasStream ? 'none' : 'inline-flex';
    }
  }

  async function startStudioCamera() {
    const cameraVideo = document.getElementById('Studio-CameraVideo');
    const previewVideo = document.getElementById('Studio-PreviewVideo');
    const errorEl = document.getElementById('Studio-CameraError');

    if (previewVideo) previewVideo.style.display = 'none';
    if (cameraVideo) cameraVideo.style.display = 'block';
    if (errorEl) errorEl.style.display = 'none';

    stopStudioCamera();
    setStudioCameraAvailable(false);

    try {
      const constraints = {
        video: {
          facingMode: 'user',
          aspectRatio: 9 / 16,
          height: { ideal: 1280 }
        },
        audio: true
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      studioCameraStream = stream;
      if (cameraVideo) {
        cameraVideo.srcObject = stream;
        try {
          await cameraVideo.play();
        } catch (e) {
          console.warn('[Studio] Camera play error:', e);
        }
      }
      setStudioCameraAvailable(true);
      if (errorEl) errorEl.style.display = 'none';
    } catch (err) {
      console.error('[Studio] getUserMedia error:', err);
      studioCameraStream = null;
      setStudioCameraAvailable(false);
      if (errorEl) {
        const titleEl = document.getElementById('Studio-CameraErrorTitle');
        const descEl = document.getElementById('Studio-CameraErrorDesc');
        const retryBtn = document.getElementById('Studio-RetryCameraBtn');
        if (retryBtn) retryBtn.textContent = 'Try again';

        const isNotAllowed = err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
        const isNotFound = err && (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError');

        if (isNotAllowed) {
          if (titleEl) titleEl.textContent = 'Camera and microphone blocked';
          if (descEl) descEl.textContent = 'Click the 🔒/camera icon in the address bar → set Camera and Microphone to Allow → press Try again';
        } else if (isNotFound) {
          if (titleEl) titleEl.textContent = 'No camera/microphone found';
          if (descEl) descEl.textContent = 'No camera/microphone found';
        } else {
          if (titleEl) titleEl.textContent = 'Camera error';
          if (descEl) descEl.textContent = (err && err.message) ? err.message : 'Unable to access camera and microphone.';
        }
        errorEl.style.display = 'flex';
      }
    }
  }

  function stopStudioCamera() {
    if (studioCameraStream) {
      try {
        studioCameraStream.getTracks().forEach(track => track.stop());
      } catch (e) {
        console.warn('[Studio] Error stopping camera tracks:', e);
      }
      studioCameraStream = null;
    }
    const cameraVideo = document.getElementById('Studio-CameraVideo');
    if (cameraVideo) cameraVideo.srcObject = null;
    setStudioCameraAvailable(false);
  }

  function triggerStudioRecord() {
    if (studioIsRecording || !studioCameraStream) return;
    const countdownEl = document.getElementById('Studio-Countdown');
    const recordBtn = document.getElementById('Studio-RecordBtn');
    if (recordBtn) recordBtn.disabled = true;

    let count = 3;
    if (countdownEl) {
      countdownEl.textContent = count;
      countdownEl.style.display = 'flex';
    }

    studioCountdownTimer = setInterval(() => {
      count--;
      if (count > 0) {
        if (countdownEl) countdownEl.textContent = count;
      } else {
        clearInterval(studioCountdownTimer);
        studioCountdownTimer = null;
        if (countdownEl) countdownEl.style.display = 'none';
        if (recordBtn) recordBtn.disabled = false;
        startStudioRecording();
      }
    }, 1000);
  }

  function startStudioRecording() {
    if (!studioCameraStream) return;
    studioRecordedChunks = [];
    studioRecordedBlob = null;

    const preferredMimes = [
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm',
      'video/mp4'
    ];
    let selectedMime = 'video/webm';
    for (const m of preferredMimes) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) {
        selectedMime = m;
        break;
      }
    }
    studioRecordedMime = selectedMime;

    try {
      studioMediaRecorder = new MediaRecorder(studioCameraStream, { mimeType: selectedMime });
    } catch (e) {
      try {
        studioMediaRecorder = new MediaRecorder(studioCameraStream);
        studioRecordedMime = studioMediaRecorder.mimeType || 'video/webm';
      } catch (err2) {
        console.error('[Studio] Failed to initialize MediaRecorder:', err2);
        return;
      }
    }

    studioMediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        studioRecordedChunks.push(e.data);
      }
    };

    studioMediaRecorder.onstop = () => {
      studioRecordedBlob = new Blob(studioRecordedChunks, { type: studioRecordedMime });
      showStudioPreview();
    };

    studioMediaRecorder.start(250);
    studioIsRecording = true;
    studioRecordStartTime = Date.now();

    const recordBtn = document.getElementById('Studio-RecordBtn');
    const stopBtn = document.getElementById('Studio-StopBtn');
    const recBadge = document.getElementById('Studio-RecBadge');
    if (recordBtn) recordBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'inline-flex';
    if (recBadge) recBadge.style.display = 'flex';

    startStudioTeleprompterScroll();
    startStudioTimer();
  }

  function stopStudioRecording() {
    if (!studioIsRecording) return;
    studioIsRecording = false;

    if (studioMediaRecorder && studioMediaRecorder.state !== 'inactive') {
      try {
        studioMediaRecorder.stop();
      } catch (e) {
        console.warn('[Studio] Error stopping MediaRecorder:', e);
      }
    }

    stopStudioTeleprompterScroll();
    stopStudioTimer();

    const stopBtn = document.getElementById('Studio-StopBtn');
    const recBadge = document.getElementById('Studio-RecBadge');
    if (stopBtn) stopBtn.style.display = 'none';
    if (recBadge) recBadge.style.display = 'none';
  }

  function showStudioPreview() {
    const cameraVideo = document.getElementById('Studio-CameraVideo');
    const previewVideo = document.getElementById('Studio-PreviewVideo');
    const retakeBtn = document.getElementById('Studio-RetakeBtn');
    const useTakeBtn = document.getElementById('Studio-UseTakeBtn');
    const recordBtn = document.getElementById('Studio-RecordBtn');
    const stopBtn = document.getElementById('Studio-StopBtn');

    if (cameraVideo) cameraVideo.style.display = 'none';
    if (previewVideo && studioRecordedBlob) {
      if (previewVideo.src) URL.revokeObjectURL(previewVideo.src);
      previewVideo.src = URL.createObjectURL(studioRecordedBlob);
      previewVideo.style.display = 'block';
      previewVideo.play().catch(() => {});
    }

    if (recordBtn) recordBtn.style.display = 'none';
    const retryBarBtn = document.getElementById('Studio-RetryCameraBarBtn');
    if (retryBarBtn) retryBarBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'none';
    if (retakeBtn) retakeBtn.style.display = 'inline-flex';
    if (useTakeBtn) useTakeBtn.style.display = 'inline-flex';
  }

  function retakeStudioRecording() {
    const previewVideo = document.getElementById('Studio-PreviewVideo');
    const cameraVideo = document.getElementById('Studio-CameraVideo');
    const retakeBtn = document.getElementById('Studio-RetakeBtn');
    const useTakeBtn = document.getElementById('Studio-UseTakeBtn');
    const recordBtn = document.getElementById('Studio-RecordBtn');

    if (previewVideo) {
      if (previewVideo.src) URL.revokeObjectURL(previewVideo.src);
      previewVideo.src = '';
      previewVideo.style.display = 'none';
    }
    if (cameraVideo) cameraVideo.style.display = 'block';

    studioRecordedBlob = null;
    studioRecordedChunks = [];

    if (retakeBtn) retakeBtn.style.display = 'none';
    if (useTakeBtn) useTakeBtn.style.display = 'none';
    if (recordBtn) recordBtn.style.display = 'inline-flex';
    setStudioCameraAvailable(Boolean(studioCameraStream));

    resetStudioTeleprompter();
  }

  async function useStudioTake() {
    if (!studioRecordedBlob || !currentScriptData || studioActiveSceneN === null) return;
    const ideaId = currentScriptData.idea_id;
    const sceneN = studioActiveSceneN;

    const retakeBtn = document.getElementById('Studio-RetakeBtn');
    const useTakeBtn = document.getElementById('Studio-UseTakeBtn');
    const uploadStatus = document.getElementById('Studio-UploadStatus');
    const uploadText = document.getElementById('Studio-UploadText');

    if (retakeBtn) retakeBtn.disabled = true;
    if (useTakeBtn) useTakeBtn.disabled = true;
    if (uploadStatus) uploadStatus.style.display = 'inline-flex';
    if (uploadText) uploadText.textContent = 'Requesting upload URL…';

    try {
      const ext = studioRecordedMime.includes('mp4') ? 'mp4' : 'webm';
      const urlRes = await authenticatedFetch(`/api/audiovisual/${ideaId}/takes/${sceneN}/upload-url?ext=${ext}`, {
        method: 'POST'
      });
      if (!urlRes.ok) {
        const errJson = await urlRes.json().catch(() => ({}));
        throw new Error(errJson.error || 'Failed to obtain upload URL');
      }
      const { storage_path, signed_upload_url, token } = await urlRes.json();

      if (uploadText) uploadText.textContent = 'Uploading take to storage…';
      if (supabase && supabase.storage) {
        const { data, error } = await supabase.storage.from('brand-assets').uploadToSignedUrl(storage_path, token, studioRecordedBlob);
        if (error) {
          console.warn('[Studio] supabase uploadToSignedUrl error:', error);
          if (signed_upload_url) {
            const putRes = await fetch(signed_upload_url, {
              method: 'PUT',
              headers: { 'Content-Type': studioRecordedMime },
              body: studioRecordedBlob
            });
            if (!putRes.ok) throw new Error('Upload to storage failed');
          } else {
            throw error;
          }
        }
      } else if (signed_upload_url) {
        const putRes = await fetch(signed_upload_url, {
          method: 'PUT',
          headers: { 'Content-Type': studioRecordedMime },
          body: studioRecordedBlob
        });
        if (!putRes.ok) throw new Error('Upload to storage failed');
      }

      if (uploadText) uploadText.textContent = 'Enqueuing AssemblyAI transcript…';
      const durationS = studioRecordStartTime ? (Date.now() - studioRecordStartTime) / 1000 : null;
      const commitRes = await authenticatedFetch(`/api/audiovisual/${ideaId}/takes/${sceneN}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          storage_path: storage_path,
          mime: studioRecordedMime,
          duration_s: durationS
        })
      });
      if (!commitRes.ok) {
        const errJson = await commitRes.json().catch(() => ({}));
        throw new Error(errJson.error || 'Failed to commit take');
      }

      await loadAudiovisualJobs(ideaId);
      pollAudiovisualJobs(ideaId);
      closeRecordingStudio();
    } catch (err) {
      console.error('[Studio] Upload/commit error:', err);
      alert('Upload failed: ' + (err.message || 'Please try again'));
      if (retakeBtn) retakeBtn.disabled = false;
      if (useTakeBtn) useTakeBtn.disabled = false;
      if (uploadStatus) uploadStatus.style.display = 'none';
    }
  }

  function updateStudioSceneUI(scene, allScenes) {
    const sceneInfoEl = document.getElementById('Studio-SceneInfo');
    const prevBtn = document.getElementById('Studio-PrevSceneBtn');
    const nextBtn = document.getElementById('Studio-NextSceneBtn');
    const spokenTextEl = document.getElementById('Studio-SpokenText');
    const actingNoteEl = document.getElementById('Studio-ActingNote');

    const sceneIdx = allScenes.findIndex(s => s.n === scene.n);
    const phaseName = PHASE_NAMES[scene.phase] || (scene.phase ? scene.phase.replace(/_/g, ' ') : 'Scene');

    if (sceneInfoEl) {
      const takeNum = (sceneIdx >= 0 ? sceneIdx : 0) + 1;
      const totalTakes = allScenes.length || 1;
      sceneInfoEl.textContent = `Take ${takeNum} of ${totalTakes} · Scene ${scene.n} · ${phaseName}`;
    }
    if (prevBtn) prevBtn.disabled = sceneIdx <= 0;
    if (nextBtn) nextBtn.disabled = sceneIdx >= allScenes.length - 1;

    if (spokenTextEl) {
      spokenTextEl.textContent = scene.spoken_text || '—';
    }

    if (actingNoteEl) {
      actingNoteEl.textContent = scene.acting_note ? `How to say it: ${scene.acting_note}` : '';
    }
  }

  function startStudioTeleprompterScroll() {
    studioIsPlaying = true;
    studioLastTs = null;
    function tick(ts) {
      if (!studioIsPlaying) return;
      if (!studioLastTs) studioLastTs = ts;
      const dt = (ts - studioLastTs) / 1000;
      studioLastTs = ts;

      const speedInput = document.getElementById('Studio-Speed');
      const speed = speedInput ? parseFloat(speedInput.value) : 50;

      studioScrollY -= speed * dt;
      const track = document.getElementById('Studio-ScrollTrack');
      if (track) {
        track.style.transform = `translateY(${studioScrollY}px)`;
      }

      studioRafId = requestAnimationFrame(tick);
    }
    studioRafId = requestAnimationFrame(tick);
  }

  function stopStudioTeleprompterScroll() {
    studioIsPlaying = false;
    if (studioRafId) {
      cancelAnimationFrame(studioRafId);
      studioRafId = null;
    }
    studioLastTs = null;
  }

  function resetStudioTeleprompter() {
    stopStudioTeleprompterScroll();
    studioScrollY = 0;
    const track = document.getElementById('Studio-ScrollTrack');
    if (track) track.style.transform = 'translateY(0px)';
    const timerEl = document.getElementById('Studio-Timer');
    if (timerEl) timerEl.textContent = '00:00';
  }

  function startStudioTimer() {
    stopStudioTimer();
    const timerEl = document.getElementById('Studio-Timer');
    studioTimerInterval = setInterval(() => {
      if (studioRecordStartTime) {
        const sec = Math.floor((Date.now() - studioRecordStartTime) / 1000);
        const m = Math.floor(sec / 60).toString().padStart(2, '0');
        const s = (sec % 60).toString().padStart(2, '0');
        if (timerEl) timerEl.textContent = `${m}:${s}`;
      }
    }, 500);
  }

  function stopStudioTimer() {
    if (studioTimerInterval) {
      clearInterval(studioTimerInterval);
      studioTimerInterval = null;
    }
  }

  function resetStudioRecordingState() {
    const recordBtn = document.getElementById('Studio-RecordBtn');
    const stopBtn = document.getElementById('Studio-StopBtn');
    const retakeBtn = document.getElementById('Studio-RetakeBtn');
    const useTakeBtn = document.getElementById('Studio-UseTakeBtn');
    const uploadStatus = document.getElementById('Studio-UploadStatus');
    const recBadge = document.getElementById('Studio-RecBadge');
    const countdownEl = document.getElementById('Studio-Countdown');
    const previewVideo = document.getElementById('Studio-PreviewVideo');
    const cameraVideo = document.getElementById('Studio-CameraVideo');

    if (recordBtn) { recordBtn.style.display = 'inline-flex'; }
    setStudioCameraAvailable(Boolean(studioCameraStream));
    if (stopBtn) stopBtn.style.display = 'none';
    if (retakeBtn) { retakeBtn.style.display = 'none'; retakeBtn.disabled = false; }
    if (useTakeBtn) { useTakeBtn.style.display = 'none'; useTakeBtn.disabled = false; }
    if (uploadStatus) uploadStatus.style.display = 'none';
    if (recBadge) recBadge.style.display = 'none';
    if (countdownEl) countdownEl.style.display = 'none';
    if (previewVideo) {
      if (previewVideo.src) URL.revokeObjectURL(previewVideo.src);
      previewVideo.src = '';
      previewVideo.style.display = 'none';
    }
    if (cameraVideo) cameraVideo.style.display = 'block';

    studioRecordedBlob = null;
    studioRecordedChunks = [];
    studioIsRecording = false;
  }

  function initRecordingStudio() {
    const overlay = document.getElementById('Recording-Studio-Overlay');
    if (!overlay) return;

    const closeBtn = document.getElementById('Studio-CloseBtn');
    if (closeBtn) closeBtn.onclick = () => closeRecordingStudio();

    const recordBtn = document.getElementById('Studio-RecordBtn');
    if (recordBtn) recordBtn.onclick = () => triggerStudioRecord();

    const stopBtn = document.getElementById('Studio-StopBtn');
    if (stopBtn) stopBtn.onclick = () => stopStudioRecording();

    const retakeBtn = document.getElementById('Studio-RetakeBtn');
    if (retakeBtn) retakeBtn.onclick = () => retakeStudioRecording();

    const useTakeBtn = document.getElementById('Studio-UseTakeBtn');
    if (useTakeBtn) useTakeBtn.onclick = () => useStudioTake();

    const resetBtn = document.getElementById('Studio-ResetBtn');
    if (resetBtn) resetBtn.onclick = () => resetStudioTeleprompter();

    const retryBtn = document.getElementById('Studio-RetryCameraBtn');
    if (retryBtn) retryBtn.onclick = () => startStudioCamera();

    const retryBarBtn = document.getElementById('Studio-RetryCameraBarBtn');
    if (retryBarBtn) retryBarBtn.onclick = () => startStudioCamera();

    const speedInput = document.getElementById('Studio-Speed');
    const speedVal = document.getElementById('Studio-SpeedVal');
    if (speedInput && speedVal) {
      speedInput.oninput = () => {
        speedVal.textContent = speedInput.value;
      };
    }

    const fontScaleInput = document.getElementById('Studio-FontScale');
    const fontScaleVal = document.getElementById('Studio-FontScaleVal');
    const spokenText = document.getElementById('Studio-SpokenText');
    if (fontScaleInput && fontScaleVal) {
      fontScaleInput.oninput = () => {
        fontScaleVal.textContent = fontScaleInput.value + '%';
        if (spokenText) {
          spokenText.style.fontSize = (26 * parseFloat(fontScaleInput.value) / 100) + 'px';
        }
      };
    }

    const mirrorBtn = document.getElementById('Studio-MirrorBtn');
    const scrollTrack = document.getElementById('Studio-ScrollTrack');
    const cameraVideo = document.getElementById('Studio-CameraVideo');
    if (mirrorBtn) {
      mirrorBtn.onclick = () => {
        if (scrollTrack) scrollTrack.classList.toggle('mirrored');
        if (cameraVideo) {
          const isMirrored = cameraVideo.style.transform === 'scaleX(-1)';
          cameraVideo.style.transform = isMirrored ? 'scaleX(1)' : 'scaleX(-1)';
        }
      };
    }

    const prevSceneBtn = document.getElementById('Studio-PrevSceneBtn');
    const nextSceneBtn = document.getElementById('Studio-NextSceneBtn');
    if (prevSceneBtn) {
      prevSceneBtn.onclick = () => {
        if (!currentScriptData || !currentScriptData.scenes) return;
        const allScenes = currentScriptData.scenes;
        const currIdx = allScenes.findIndex(s => s.n === studioActiveSceneN);
        if (currIdx > 0) {
          const prevScene = allScenes[currIdx - 1];
          studioActiveSceneN = prevScene.n;
          updateStudioSceneUI(prevScene, allScenes);
          resetStudioTeleprompter();
          resetStudioRecordingState();
        }
      };
    }
    if (nextSceneBtn) {
      nextSceneBtn.onclick = () => {
        if (!currentScriptData || !currentScriptData.scenes) return;
        const allScenes = currentScriptData.scenes;
        const currIdx = allScenes.findIndex(s => s.n === studioActiveSceneN);
        if (currIdx >= 0 && currIdx < allScenes.length - 1) {
          const nextScene = allScenes[currIdx + 1];
          studioActiveSceneN = nextScene.n;
          updateStudioSceneUI(nextScene, allScenes);
          resetStudioTeleprompter();
          resetStudioRecordingState();
        }
      };
    }

    window.addEventListener('keydown', (e) => {
      if (overlay.style.display !== 'none' && overlay.style.display !== '') {
        if (e.code === 'Space') {
          if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            e.preventDefault();
            if (studioIsRecording) {
              stopStudioRecording();
            } else if (!studioRecordedBlob && studioCameraStream) {
              triggerStudioRecord();
            }
          }
        } else if (e.key === 'r' || e.key === 'R') {
          if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            resetStudioTeleprompter();
          }
        } else if (e.key === 'Escape') {
          closeRecordingStudio();
        }
      }
    });
  }

  // Block C: Load script data for an idea
  async function loadScriptData(ideaId) {
    showDocLoading('Loading script…');
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
    } finally {
      hideDocLoading();
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
    // renderScript() hides this button once a script exists; restore it here
    // so navigating Back and opening an idea with no script yet still shows it.
    scriptGenerateBtn.style.display = '';

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
    // Catalog lock state has no dedicated module variable to read from, so
    // we recompute it from the Catalog-LockBtn element's dataset -- it's the
    // only persistent UI signal for whether the catalog has been locked.
    const lockBtn = document.getElementById('Catalog-LockBtn');
    const catalogLocked = lockBtn && lockBtn.dataset.locked === 'true';

    // Disable if catalog is not locked (most likely scenario when this is called)
    if (!catalogLocked) {
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.title = 'Catalog must be locked to generate scripts';
      if (scriptGenerateHelp) {
        scriptGenerateHelp.style.display = 'block';
        scriptGenerateHelp.textContent = 'Lock the catalog in Block B (Idea Catalog) first';
      }
      return;
    }

    if (sourceMode === 'raw_footage') {
      // Video ingestion is not built yet (pending a CEO decision). The
      // <option> itself is disabled in the DOM so a founder can't actually
      // select this value -- this branch is defense in depth so no code
      // path can ever fire a generate call in raw_footage mode.
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.title = 'Raw footage upload is coming soon';
      if (scriptGenerateHelp) {
        scriptGenerateHelp.style.display = 'block';
        scriptGenerateHelp.textContent = 'Raw footage upload is coming soon. Use Assisted mode for now.';
      }
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

  // Shows/hides the inline note in the Review panel when the founder picks
  // a recording format different from the one the system proposed. Does
  // NOT auto-regenerate scenes -- pricing that is a CEO decision.
  function updateReviewFormatNote(formatSelect, noteEl) {
    const proposedFormat = formatSelect.dataset.proposedFormat || '';
    const selectedFormat = formatSelect.value;
    if (!proposedFormat || selectedFormat === proposedFormat) {
      noteEl.style.display = 'none';
      noteEl.textContent = '';
      return;
    }
    const proposedName = RECORDING_FORMAT_NAMES[proposedFormat] || proposedFormat;
    const selectedName = RECORDING_FORMAT_NAMES[selectedFormat] || selectedFormat;
    noteEl.textContent = `Camera shots and "How to say it" cues were written for ${proposedName}. Consider regenerating scenes (⟳) to adapt them to ${selectedName}.`;
    noteEl.style.display = 'block';
  }

  // PIEZA 42: Get state transition hint
  function getStateHint(state) {
    switch (state) {
      case 'draft':
        return 'Choose funnel stage and recording format, then lock to start recording.';
      case 'reviewed':
        return 'Lock to start recording.';
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
          ${state === 'locked' ? '<span style="font-size:13px;color:#1B7F4C;font-weight:500">✓ Ready for recording</span><button id="Script-OpenAudiovisualBtn" class="btn btn--go" style="padding:6px 14px;font-size:12px;margin-left:auto">Open in Audiovisual →</button>' : ''}
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
      const criticalFailures = (currentScriptData.audit || []).filter(a => a.status === 'fail' && a.critical === true);
      const hasCriticalFailures = criticalFailures.length > 0;

      let criticalHtml = '';
      if (hasCriticalFailures) {
        const failureItems = criticalFailures.map(f =>
          `<div style="margin-bottom:4px"><strong>${escapeHtml(f.rule || '')}</strong> — ${escapeHtml(f.detail || 'Check failed')}</div>`
        ).join('');

        criticalHtml = `
          <div id="Review-CriticalBox" style="margin-bottom:12px;padding:12px;border:1px solid #FCA5A5;border-radius:6px;background:#FEE2E2;color:#991B1B;font-size:12px;line-height:1.4">
            <div style="font-weight:600;margin-bottom:6px">Fix these before locking:</div>
            ${failureItems}
            <div style="margin-top:6px;color:#7F1D1D;font-size:11px">Iterate (⟳) or edit a scene to fix it. The audit re-runs on every change.</div>
          </div>
        `;
      }

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
            <select id="Review-RecordingFormat" data-proposed-format="${escapeHtml(proposedFormat)}" style="width:100%;padding:8px;border:1px solid #D5DAE4;border-radius:4px;font-family:inherit;font-size:13px">
              <option value="selfie_natural" ${proposedFormat === 'selfie_natural' ? 'selected' : ''}>Natural selfie</option>
              <option value="pov" ${proposedFormat === 'pov' ? 'selected' : ''}>POV (Point of view)</option>
              <option value="dramatization" ${proposedFormat === 'dramatization' ? 'selected' : ''}>Dramatization</option>
              <option value="teleprompter_clean" ${proposedFormat === 'teleprompter_clean' ? 'selected' : ''}>Teleprompter (clean background)</option>
              <option value="dynamic" ${proposedFormat === 'dynamic' ? 'selected' : ''}>Dynamic</option>
            </select>
            <div id="Review-FormatNote" style="display:none;margin-top:8px;padding:8px 10px;font-size:12px;line-height:1.5;color:#8A5A00;background:#FFF6E0;border:1px solid #F0D583;border-radius:4px"></div>
          </div>

          ${criticalHtml}

          <div id="Review-ErrorMsg" style="display:none;margin-bottom:12px;padding:10px 14px;border:1px solid #FCA5A5;border-radius:6px;background:#FEE2E2;color:#991B1B;font-size:12px;line-height:1.4"></div>

          <button id="Review-ConfirmBtn" class="btn btn--go" style="width:100%;padding:10px;font-size:13px" ${hasCriticalFailures ? 'disabled' : ''}>Confirm & Lock script</button>
          <div style="margin-top:8px;font-size:11px;color:#5C6675;text-align:center">Free — no credits charged · you can't edit the script after locking</div>
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
          <div id="Script-Duration" style="font-weight:500;color:#14181F">${getEstimatedDurationText(currentScriptData)}</div>
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

    // PIEZA 61: Wire up button to open Audiovisual view if present
    const openAudiovisualBtn = document.getElementById('Script-OpenAudiovisualBtn');
    if (openAudiovisualBtn) {
      openAudiovisualBtn.addEventListener('click', () => {
        showAudiovisualView();
      });
    }

    // PIEZA 42: Wire up review panel confirm button if present
    const confirmBtn = document.getElementById('Review-ConfirmBtn');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', handleScriptConfirm);
    }

    // Warn when the founder picks a recording format different from the
    // one the system proposed: the camera shots and "How to say it" cues
    // were written for the proposed format, and won't auto-update -- that
    // is a CEO pricing decision, not something this UI does on its own.
    const reviewFormatSelect = document.getElementById('Review-RecordingFormat');
    const reviewFormatNote = document.getElementById('Review-FormatNote');
    if (reviewFormatSelect && reviewFormatNote) {
      reviewFormatSelect.addEventListener('change', () => {
        updateReviewFormatNote(reviewFormatSelect, reviewFormatNote);
      });
    }

    // Re-bind DOM references that were replaced
    scriptAngle = document.getElementById('Script-Angle');
    scriptFunnelStage = document.getElementById('Script-FunnelStage');
    scriptDuration = document.getElementById('Script-Duration');
    scriptRecordingFormat = document.getElementById('Script-RecordingFormat');
    scriptMusicPrompt = document.getElementById('Script-MusicPrompt');

    // Render Frame Zero (object with visual/on_screen_text/why_it_stops_the_scroll)
    scriptFrameZero.style.display = 'block';
    if (scriptFrameZeroContent) {
      const fz = currentScriptData.frame_zero;
      if (fz && typeof fz === 'object') {
        scriptFrameZeroContent.innerHTML = `
          <div style="margin-bottom:8px"><strong>Visual:</strong> ${escapeHtml(fz.visual || '—')}</div>
          <div style="margin-bottom:8px"><strong>On-screen text:</strong> ${escapeHtml(fz.on_screen_text || '—')}</div>
          <div><strong>Why it stops the scroll:</strong> ${escapeHtml(fz.why_it_stops_the_scroll || '—')}</div>
        `;
      } else {
        scriptFrameZeroContent.textContent = 'Frame zero not set';
      }
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

  // Helper for locking script (used by handleScriptConfirm and handleScriptLock)
  async function performLockScript(ideaId) {
    const response = await authenticatedFetch(`/api/script/${ideaId}/lock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || data.detail || response.statusText || 'Failed to lock script');
    }

    const data = await response.json();
    return data.script || data;
  }

  // PIEZA 62: Handle script confirmation & locking in one step
  async function handleScriptConfirm() {
    const funnelSelect = document.getElementById('Review-FunnelStage');
    const formatSelect = document.getElementById('Review-RecordingFormat');
    const confirmBtn = document.getElementById('Review-ConfirmBtn');
    const errorEl = document.getElementById('Review-ErrorMsg');

    if (!currentScriptData || !currentScriptData.idea_id) return;

    // In-flight guard: ignore re-entry while action is in progress.
    if (confirmBtn && confirmBtn.disabled) return;

    if (errorEl) {
      errorEl.style.display = 'none';
      errorEl.textContent = '';
    }

    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Locking…';
    }

    const state = currentScriptData.state || 'draft';
    const ideaId = currentScriptData.idea_id;

    try {
      if (state === 'draft') {
        if (!funnelSelect || !formatSelect) return;
        const funnelStage = funnelSelect.value;
        const recordingFormat = formatSelect.value;

        const response = await authenticatedFetch(`/api/script/${ideaId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ funnel_stage: funnelStage, recording_format: recordingFormat }),
        });

        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.error || data.detail || response.statusText || 'Failed to confirm script');
        }

        const data = await response.json();
        currentScriptData = data.script || data;
        if (data.credits_remaining !== undefined) {
          credits = data.credits_remaining;
          updateCreditsUI(data.credits_remaining, initialSessionCredits);
        }
        if (currentCatalog && currentCatalog.ideas && currentScriptData?.idea_id) {
          const matchedIdea = currentCatalog.ideas.find(i => i.id === currentScriptData.idea_id);
          if (matchedIdea) {
            matchedIdea.script_state = 'reviewed';
            updateIdeaCardScriptButton(currentScriptData.idea_id, 'reviewed');
          }
        }
      }

      // Step 2: Lock script
      const lockedData = await performLockScript(ideaId);
      currentScriptData = lockedData;

      if (currentCatalog && currentCatalog.ideas && currentScriptData?.idea_id) {
        const matchedIdea = currentCatalog.ideas.find(i => i.id === currentScriptData.idea_id);
        if (matchedIdea) {
          matchedIdea.script_state = 'locked';
          updateIdeaCardScriptButton(currentScriptData.idea_id, 'locked');
        }
      }

      renderScript();

    } catch (error) {
      if (error.message === 'PAYWALL_402') {
        console.log('[Script] Confirm/Lock blocked by paywall');
      } else {
        console.error('Script confirm/lock error:', error);
        if (errorEl) {
          errorEl.textContent = error.message;
          errorEl.style.display = 'block';
        }
      }
      if (confirmBtn) {
        const criticalFailures = (currentScriptData.audit || []).filter(a => a.status === 'fail' && a.critical === true);
        confirmBtn.disabled = criticalFailures.length > 0;
        confirmBtn.textContent = 'Confirm & Lock script';
      }
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

    // Lock is final per spec: locked scenes render read-only, no regenerate.
    const isLocked = currentScriptData.state === 'locked';

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
          ${isLocked ? '' : '<button class="script-scene-regenerate" title="Regenerate this scene">⟳</button>'}
        </div>
      `;

      // Spoken text (editable, unless the script is locked -- lock is final)
      html += `
        <div class="script-scene-content"${isLocked ? '' : ' contenteditable="true"'}>${escapeHtml(scene.spoken_text || '')}</div>
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
    // Lock is final: locked scenes have no contenteditable and no
    // regenerate button in the DOM, so skip wiring their handlers entirely.
    const isLocked = currentScriptData.state === 'locked';

    if (!isLocked) {
      const sceneContents = scriptScenes.querySelectorAll('.script-scene-content[contenteditable="true"]');
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
    }

    // PIEZA 42: Regenerate buttons — show inline form instead of confirm()
    const regenerateBtns = scriptScenes.querySelectorAll('.script-scene-regenerate');
    regenerateBtns.forEach((btn) => {
      const sceneIdx = parseInt(btn.closest('.script-scene').dataset.sceneIndex);
      // In-flight guard: keep the button disabled if a regenerate for this
      // scene is already out (e.g. this render happened mid-request).
      if (regeneratingSceneIndices.has(sceneIdx)) {
        btn.disabled = true;
        btn.title = 'Regenerating...';
        btn.classList.add('is-regenerating');
      }
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

    // AuditFinding backend fields: rule, status ("pass"|"fail"), detail, critical.
    // There is no `message` and no `passed` -- read the real fields and make
    // failures (especially critical ones) visibly distinct from passes.
    const auditList = document.createElement('ul');
    auditList.className = 'script-audit-list';
    currentScriptData.audit.forEach((entry) => {
      const li = document.createElement('li');
      const isFail = entry.status === 'fail';
      const isCritical = isFail && entry.critical === true;
      li.className = 'script-audit-item' + (isFail ? ' script-audit-item--fail' : ' script-audit-item--pass') + (isCritical ? ' script-audit-item--critical' : '');
      const statusLabel = isFail ? (isCritical ? 'FAIL (critical)' : 'FAIL') : 'PASS';
      const statusColor = isFail ? (isCritical ? '#991B1B' : '#B5720B') : '#1B7F4C';
      const detail = entry.detail || (isFail ? 'Check failed' : 'Check passed');
      li.innerHTML = `<span class="audit-status" style="display:inline-block;min-width:110px;font-weight:700;color:${statusColor}">${escapeHtml(statusLabel)}</span><span class="audit-rule">${escapeHtml(entry.rule)}</span>: ${escapeHtml(detail)}`;
      auditList.appendChild(li);
    });
    scriptAudit.appendChild(auditList);
  }

  // PIEZA 62: Update top lock button (disabled in draft/reviewed, directs to Confirm & Lock script below)
  function updateScriptLockButton() {
    let hintEl = document.getElementById('Script-LockHint');
    if (!hintEl && scriptLockBtn && scriptLockBtn.parentNode) {
      hintEl = document.createElement('span');
      hintEl.id = 'Script-LockHint';
      hintEl.style.cssText = 'font-size:12px;color:#5C6675';
      scriptLockBtn.parentNode.insertBefore(hintEl, scriptLockBtn);
    }

    if (!currentScriptData) {
      scriptLockBtn.disabled = true;
      if (hintEl) hintEl.textContent = '';
      return;
    }

    const state = currentScriptData.state || 'draft';
    const isLocked = state === 'locked';

    // PIEZA 42B: Lock is final - when locked, button shows "Locked" and is disabled
    if (isLocked) {
      scriptLockBtn.textContent = 'Locked — ready to record';
      scriptLockBtn.disabled = true;
      scriptLockBtn.dataset.locked = 'true';
      scriptLockBtn.title = 'Script is locked for recording';
      if (hintEl) hintEl.textContent = '';
      return;
    }

    // PIEZA 62: Top lock button is disabled in draft/reviewed (use "Confirm & Lock script" in panel below)
    scriptLockBtn.textContent = 'Lock Script';
    scriptLockBtn.dataset.locked = 'false';
    scriptLockBtn.disabled = true;

    let failedCriticalRule = null;
    if (currentScriptData.audit) {
      const failedCritical = currentScriptData.audit.find((a) => a.status === 'fail' && a.critical === true);
      if (failedCritical) {
        failedCriticalRule = failedCritical.rule;
      }
    }

    if (failedCriticalRule) {
      scriptLockBtn.title = `Fix ${failedCriticalRule} first`;
      if (hintEl) hintEl.textContent = `Fix ${failedCriticalRule} first`;
    } else {
      scriptLockBtn.title = 'Use "Confirm & Lock script" below';
      if (hintEl) hintEl.textContent = 'Use "Confirm & Lock script" below';
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
    if (scriptDuration) scriptDuration.textContent = getEstimatedDurationText(currentScriptData);
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
    // In-flight guard: ignore re-entry for a scene already regenerating.
    if (regeneratingSceneIndices.has(sceneIdx)) return;
    regeneratingSceneIndices.add(sceneIdx);
    const regenBtn = scriptScenes.querySelector(`.script-scene[data-scene-index="${sceneIdx}"] .script-scene-regenerate`);
    if (regenBtn) {
      regenBtn.disabled = true;
      regenBtn.title = 'Regenerating...';
      regenBtn.classList.add('is-regenerating');
    }

    try {
      // Backend expects scene_n (1-indexed)
      const sceneN = sceneIdx + 1;
      const response = await authenticatedFetch(`/api/script/${currentScriptData.idea_id}/scene/${sceneN}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: instruction || '' }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || data.detail || data.message || response.statusText || 'Failed to regenerate scene');
      }

      // PIEZA 42: Update from backend response (source of truth)
      currentScriptData = data.script || data;
      if (data.credits_remaining !== undefined) {
        credits = data.credits_remaining;
        updateCreditsUI(data.credits_remaining, initialSessionCredits);
      }
      renderScenes();
      renderAudit();
      updateScriptLockButton();
      renderScript(); // Re-render to update state if it changed
    } catch (error) {
      if (error.message === 'PAYWALL_402') {
        // authenticatedFetch throws this BEFORE the response reaches the
        // caller when the backend answers 402 -- the paywall overlay is
        // already shown at that point, nothing else to do here.
        console.log('[Script] Regenerate blocked by paywall');
      } else {
        console.error('Scene regenerate error:', error);
        alert(`Failed to regenerate scene: ${error.message}`);
      }
    } finally {
      regeneratingSceneIndices.delete(sceneIdx);
      const btnAfter = scriptScenes.querySelector(`.script-scene[data-scene-index="${sceneIdx}"] .script-scene-regenerate`);
      if (btnAfter) {
        btnAfter.disabled = false;
        btnAfter.title = 'Regenerate this scene';
        btnAfter.classList.remove('is-regenerating');
      }
    }
  }

  // PIEZA 42: Show inline regenerate form for a scene
  function showRegenerateForm(sceneIdx, buttonEl) {
    const sceneEl = buttonEl.closest('.script-scene');
    if (!sceneEl) return;

    // In-flight guard: don't let the founder open a new form (and fire a
    // second regenerate POST) while this scene's request is still out.
    if (regeneratingSceneIndices.has(sceneIdx)) return;

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

  // PIEZA 42B / PIEZA 62: Handle script locking (lock is final, uses performLockScript helper)
  async function handleScriptLock() {
    if (currentScriptData?.state === 'locked') {
      showLockMessage('Script is already locked.', true);
      return;
    }

    if (scriptLockInFlight) return;
    scriptLockInFlight = true;
    if (scriptLockBtn) scriptLockBtn.disabled = true;

    try {
      const lockData = await performLockScript(currentScriptData.idea_id);
      currentScriptData = lockData;
      if (currentCatalog && currentCatalog.ideas && currentScriptData?.idea_id) {
        const matchedIdea = currentCatalog.ideas.find(i => i.id === currentScriptData.idea_id);
        if (matchedIdea) {
          matchedIdea.script_state = 'locked';
          updateIdeaCardScriptButton(currentScriptData.idea_id, 'locked');
        }
      }
      renderScript();
      showLockMessage('Script locked successfully.', false);
    } catch (error) {
      if (error.message === 'PAYWALL_402') {
        console.log('[Script] Lock blocked by paywall');
      } else {
        console.error('Lock script error:', error);
        showLockMessage(`Failed to lock script: ${error.message}`, true);
      }
    } finally {
      scriptLockInFlight = false;
      updateScriptLockButton();
    }
  }

  // Global progress indicator
  // =============================================================================
  // PIPELINE RAIL (Pieza 44)
  // =============================================================================

  let railNoticeTimeout = null;

  function showRailNotice(text, buttonText, buttonAction) {
    const noticeEl = document.getElementById('Rail-Notice');
    const textEl = document.getElementById('Rail-Notice-Text');
    const btnEl = document.getElementById('Rail-Notice-Btn');
    if (!noticeEl || !textEl || !btnEl) return;

    textEl.textContent = text;

    if (buttonText && typeof buttonAction === 'function') {
      btnEl.textContent = buttonText;
      btnEl.style.display = 'inline-block';
      btnEl.onclick = (e) => {
        e.preventDefault();
        buttonAction();
      };
    } else {
      btnEl.style.display = 'none';
      btnEl.onclick = null;
    }

    noticeEl.style.display = 'flex';

    if (railNoticeTimeout) clearTimeout(railNoticeTimeout);
    railNoticeTimeout = setTimeout(() => {
      hideRailNotice();
    }, 8000);
  }

  function hideRailNotice() {
    const noticeEl = document.getElementById('Rail-Notice');
    if (noticeEl) {
      noticeEl.style.display = 'none';
    }
    if (railNoticeTimeout) {
      clearTimeout(railNoticeTimeout);
      railNoticeTimeout = null;
    }
  }

  function handleRailStepClick(stepId) {
    const brainCount = getReadySectionsCount(cachedBrain && cachedBrain.sections);
    const brainComplete = brainCount >= 9;
    const catalogComplete = Boolean(currentCatalog && currentCatalog.catalog_locked);
    const scriptComplete = Boolean(currentScriptData && currentScriptData.state === 'locked');

    if (stepId === 'brain') {
      hideRailNotice();
      showBlockAView();
    } else if (stepId === 'catalog') {
      if (brainComplete) {
        hideRailNotice();
        loadCatalogCache().then(() => showBlockBView());
      } else {
        showRailNotice('Finish your Brand Soul first', 'Go to Brand Soul', () => {
          hideRailNotice();
          showBlockAView();
        });
      }
    } else if (stepId === 'script') {
      if (catalogComplete) {
        hideRailNotice();
        if (currentScriptIdeaId) {
          showBlockCView(currentScriptIdeaId);
        } else {
          loadCatalogCache().then(() => showBlockBView());
        }
      } else {
        showRailNotice('Lock your catalog first', 'Go to Catalog', () => {
          hideRailNotice();
          loadCatalogCache().then(() => showBlockBView());
        });
      }
    } else if (stepId === 'audiovisual') {
      if (scriptComplete) {
        hideRailNotice();
        showAudiovisualView();
      } else {
        showRailNotice('Lock your script first', 'Go to Script', () => {
          hideRailNotice();
          if (currentScriptIdeaId) {
            showBlockCView(currentScriptIdeaId);
          } else {
            loadCatalogCache().then(() => showBlockBView());
          }
        });
      }
    } else if (stepId === 'editing') {
      if (scriptComplete && currentScriptIdeaId) {
        hideRailNotice();
        hideMainViews();
        if (window.BrandStudioEditing && typeof window.BrandStudioEditing.show === 'function') {
          window.BrandStudioEditing.show(currentScriptIdeaId);
        }
      } else {
        showRailNotice('Lock your script first', 'Go to Script', () => {
          hideRailNotice();
          if (currentScriptIdeaId) {
            showBlockCView(currentScriptIdeaId);
          } else {
            loadCatalogCache().then(() => showBlockBView());
          }
        });
      }
    }
  }

  function isAudiovisualComplete() {
    if (!currentScriptData || currentScriptData.state !== 'locked') return false;
    if (!currentAudiovisualJobs || currentAudiovisualJobs.length === 0) return false;
    const scenes = currentScriptData.scenes || [];
    if (scenes.length === 0) return false;
    for (const scene of scenes) {
      const hasTake = currentAudiovisualJobs.some(j =>
        j.kind === 'a_roll_take' && j.scene_n === scene.n && j.status === 'done'
      );
      if (!hasTake) return false;
    }
    return true;
  }

  function renderPipelineRail() {
    const rail = document.getElementById('Pipeline-Rail');
    if (!rail) return;

    // 1. Completion criteria
    const brainCount = getReadySectionsCount(cachedBrain && cachedBrain.sections);
    const brainComplete = brainCount >= 9;
    const catalogComplete = Boolean(currentCatalog && currentCatalog.catalog_locked);
    const scriptComplete = Boolean(currentScriptData && currentScriptData.state === 'locked');
    const audiovisualComplete = isAudiovisualComplete();
    const editingComplete = Boolean(window.BrandStudioEditing && typeof window.BrandStudioEditing.hasFinalRender === 'function' && window.BrandStudioEditing.hasFinalRender());

    const completed = [brainComplete, catalogComplete, scriptComplete, audiovisualComplete, editingComplete];
    const completedCount = completed.filter(Boolean).length;
    const overallPct = Math.round((completedCount / 5) * 100);

    const pctEl = document.getElementById('Rail-OverallPct');
    if (pctEl) {
      pctEl.textContent = `${overallPct}%`;
    }

    // 2. Connector fill: fills up to the last completed step (4 segments between 5 nodes)
    const fillEl = document.getElementById('Rail-Connector-Fill');
    if (fillEl) {
      const fillPct = Math.min(100, Math.round((completedCount / 4) * 100));
      fillEl.style.width = `${fillPct}%`;
    }

    // 3. States for 5 nodes: exactly one of 'done', 'in_progress', 'blocked'
    const steps = [
      { id: 'brain', name: 'Brand Soul', complete: brainComplete, prevComplete: true },
      { id: 'catalog', name: 'Catalog', complete: catalogComplete, prevComplete: brainComplete },
      { id: 'script', name: 'Script', complete: scriptComplete, prevComplete: catalogComplete },
      { id: 'audiovisual', name: 'Audiovisual', complete: audiovisualComplete, prevComplete: scriptComplete },
      { id: 'editing', name: 'Editing', complete: editingComplete, prevComplete: scriptComplete }
    ];

    let frontierFound = false;
    steps.forEach((s) => {
      if (s.complete) {
        s.state = 'done';
      } else if (!frontierFound && s.prevComplete) {
        s.state = 'in_progress';
        frontierFound = true;
      } else {
        s.state = 'blocked';
      }
    });

    // 4. Update DOM for each node
    steps.forEach((s) => {
      const btn = rail.querySelector(`.rail-step-btn[data-step="${s.id}"]`);
      if (!btn) return;

      btn.classList.remove('is-done', 'is-in-progress', 'is-blocked', 'is-current');
      btn.classList.add(`is-${s.state.replace('_', '-')}`);
      if (currentOpenView === s.id) {
        btn.classList.add('is-current');
      }

      // Update icon container
      const iconWrap = btn.querySelector('.rail-node-icon');
      if (iconWrap) {
        if (s.state === 'done') {
          iconWrap.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        } else if (s.state === 'in_progress') {
          iconWrap.innerHTML = '<div class="rail-spinner"></div>';
        } else {
          iconWrap.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>';
        }
      }

      // Sub-state line for open view
      const subEl = btn.querySelector('.rail-step-sub');
      if (subEl) {
        if (currentOpenView === s.id) {
          subEl.style.display = 'block';
          if (s.id === 'brain') {
            subEl.textContent = `${brainCount} of 9 sections`;
          } else if (s.id === 'catalog') {
            const catProg = catalogProgress ? catalogProgress.textContent.trim() : '';
            const isLocked = Boolean(currentCatalog && currentCatalog.catalog_locked);
            if (isLocked) {
              subEl.textContent = catProg && catProg !== 'Cached' ? `${catProg} · Locked ✓` : 'Locked ✓';
            } else {
              subEl.textContent = catProg || 'In progress';
            }
          } else if (s.id === 'script' || s.id === 'audiovisual') {
            const activeIdea = currentCatalog?.ideas?.find(i => i.id === currentScriptIdeaId);
            const scriptState = currentScriptData?.state || 'draft';
            if (activeIdea && activeIdea.title) {
              const shortTitle = activeIdea.title.length > 18
                ? activeIdea.title.slice(0, 16) + '…'
                : activeIdea.title;
              subEl.textContent = `${shortTitle} · ${scriptState}`;
            } else {
              subEl.textContent = s.id === 'script' ? 'No idea selected' : 'Ready for script';
            }
          } else if (s.id === 'editing') {
            subEl.textContent = scriptComplete ? 'Ready to edit' : 'Locked';
          }
        } else {
          subEl.textContent = '';
          subEl.style.display = 'none';
        }
      }
    });
  }

  function initPipelineRail() {
    const rail = document.getElementById('Pipeline-Rail');
    if (!rail) return;

    rail.querySelectorAll('.rail-step-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const step = btn.dataset.step;
        if (step) {
          handleRailStepClick(step);
        }
      });
    });

    const closeBtn = document.getElementById('Rail-Notice-Close');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.preventDefault();
        hideRailNotice();
      });
    }

    // Responsive compact/mid rail states (Pieza 44B)
    function applyRailResponsive(width) {
      if (width < 480) {
        rail.classList.add('is-compact');
        rail.classList.remove('is-mid');
      } else if (width <= 700) {
        rail.classList.remove('is-compact');
        rail.classList.add('is-mid');
      } else {
        rail.classList.remove('is-compact', 'is-mid');
      }
    }

    if (rail.offsetWidth > 0) {
      applyRailResponsive(rail.offsetWidth);
    }

    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          applyRailResponsive(entry.contentRect.width);
        }
      });
      ro.observe(rail);
    }

    renderPipelineRail();
  }

  // Global progress indicator (migrated to Pipeline Rail)
  function initGlobalProgress() {
    renderPipelineRail();
  }

  // Refresh catalog status silently on app startup without opening modals or panels (Pieza 44B)
  async function refreshCatalogStatusSilently() {
    try {
      const response = await authenticatedFetch('/api/catalog', {
        method: 'GET'
      });
      if (response.ok) {
        const data = await response.json();
        if (data && data.catalog) {
          currentCatalog = data.catalog;
        }
      } else if (response.status === 404) {
        // Silencioso: si responde 404, NO abrir modal de créditos, NO cambiar de vista, NO renderizar catálogo
      } else {
        console.warn('[Catalog] Silent catalog status check returned status:', response.status);
      }
    } catch (err) {
      console.warn('[Catalog] Silent catalog status check network error:', err);
    } finally {
      if (typeof initGlobalProgress === 'function') {
        initGlobalProgress();
      } else if (typeof renderPipelineRail === 'function') {
        renderPipelineRail();
      }
    }
  }

  // Load cache and show catalog
  async function loadCatalogCache() {
    showDocLoading('Loading catalog…');
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
    } finally {
      hideDocLoading();
    }
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
      if (sourceMode === 'raw_footage') {
        // Video ingestion is not built yet. The <option> is disabled and
        // updateScriptGenerateButton() keeps this button disabled in that
        // mode, so this should be unreachable -- kept as a hard stop so no
        // code path can ever generate against footage that doesn't exist.
        return;
      }
      const finalSourceMode = 'brand_brain';

      const originalText = scriptGenerateBtn.innerHTML;
      scriptGenerateBtn.disabled = true;
      scriptGenerateBtn.innerHTML = 'Generating...';

      const scriptEmptyState = document.getElementById('Script-EmptyState');
      let scriptLoadingState = document.getElementById('Script-LoadingState');
      if (!scriptLoadingState && scriptEmptyState && scriptEmptyState.parentNode) {
        scriptLoadingState = document.createElement('div');
        scriptLoadingState.id = 'Script-LoadingState';
        scriptLoadingState.style.cssText = 'padding:48px 0;text-align:center';
        scriptLoadingState.innerHTML = `
          <div style="display:flex;justify-content:center;margin-bottom:20px">
            <div class="spinner" style="width:36px;height:36px;border:3px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>
          </div>
          <div style="font-size:18px;font-weight:600;color:#14181F;margin-bottom:8px">Brandy is writing your script…</div>
          <div style="font-size:13px;color:#5C6675;margin-bottom:16px;max-width:440px;margin-left:auto;margin-right:auto;line-height:1.5">Usually 30–90 seconds. She checks 14 rules before showing it to you.</div>
          <div id="Script-LoadingTimer" style="font-size:14px;font-weight:600;color:var(--accent)">0s elapsed</div>
        `;
        scriptEmptyState.parentNode.insertBefore(scriptLoadingState, scriptEmptyState.nextSibling);
      }

      if (scriptEmptyState) scriptEmptyState.style.display = 'none';
      if (scriptLoadingState) scriptLoadingState.style.display = 'block';

      let elapsedSeconds = 0;
      const scriptLoadingTimer = document.getElementById('Script-LoadingTimer');
      if (scriptLoadingTimer) scriptLoadingTimer.textContent = '0s elapsed';
      const timerInterval = setInterval(() => {
        elapsedSeconds++;
        const timerEl = document.getElementById('Script-LoadingTimer');
        if (timerEl) timerEl.textContent = `${elapsedSeconds}s elapsed`;
      }, 1000);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 135000);

      try {
        const response = await authenticatedFetch(`/api/script/generate?idea_id=${encodeURIComponent(currentScriptIdeaId)}`, {
          method: 'POST',
          signal: controller.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            // fullTranscript is an array of {speaker, text} objects -- join()
            // alone stringifies each entry to "[object Object]". Format it
            // the same way the /api/brain/extract call does above.
            interview_transcript: Array.isArray(fullTranscript)
              ? fullTranscript.map(t => `${t.speaker}: ${t.text}`).join('\n')
              : '',
            source_mode: finalSourceMode
          })
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        if (!response.ok) {
          alert(`Failed to generate script: ${data.error || data.detail || response.status}`);
          if (scriptEmptyState) scriptEmptyState.style.display = 'block';
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

        // PIEZA 45: Update currentCatalog and card button without reloading
        if (currentCatalog && currentCatalog.ideas && currentScriptIdeaId) {
          const matchedIdea = currentCatalog.ideas.find(i => i.id === currentScriptIdeaId);
          if (matchedIdea) {
            matchedIdea.script_state = data.script?.state || 'draft';
            updateIdeaCardScriptButton(currentScriptIdeaId, matchedIdea.script_state);
          }
        }

      } catch (error) {
        clearTimeout(timeoutId);
        if (error.message === 'PAYWALL_402') {
          // authenticatedFetch throws this BEFORE the response reaches us
          // when the backend answers 402 -- it has already shown the
          // paywall overlay, so `response.status === 402` above can never
          // run. Nothing else to do here.
          console.log('[Script] Generate blocked by paywall');
        } else {
          console.error('Generate script error:', error);
          if (error.name === 'AbortError') {
            alert('Script generation timed out. Please try again.');
          } else {
            alert(`Failed to generate script: ${error.message}`);
          }
        }
        if (scriptEmptyState) scriptEmptyState.style.display = 'block';
        scriptGenerateBtn.disabled = false;
        scriptGenerateBtn.innerHTML = originalText;
      } finally {
        clearInterval(timerInterval);
        if (scriptLoadingState) scriptLoadingState.style.display = 'none';
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

  // Wire up Brand Soul overlay controls

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

    // Initialize pipeline rail
    initPipelineRail();

    // Initialize recording studio
    initRecordingStudio();
  });

  // Expose minimal API for editing and submodules (Pieza 82)
  window.BrandStudio = {
    authenticatedFetch,
    showPaywall,
    updateCreditsUI,
    refreshCredits: fetchCredits,
    escapeHtml,
    openRecordingStudio,
    showAudiovisualView,
    showBlockCView,
    hideMainViews,
    renderPipelineRail,
    getCurrentScriptIdeaId: () => currentScriptIdeaId,
  };

  console.log('[Voice Client] Initialized - Connecting directly to AssemblyAI Voice Agent API');
  console.log('[Audio] Sample rate: 24kHz');
  console.log('[Processor] AudioWorklet for PCM16 conversion');
  console.log('[Auth] Google OAuth enabled');

})();
