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

  // Handle plan selection buttons (placeholder - not enabled yet)
  document.querySelectorAll('.plan-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const plan = btn.dataset.plan;
      alert(`Payments are not enabled yet. The ${plan} plan (${btn.textContent.trim()}) will be available when Stripe integration is added.`);
    });
  });

  // Track credits state for depleted mode
  let creditsDepleted = false;

  // Update credits UI (helper function)
  function updateCreditsUI(remaining, initial) {
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
        if (event === 'SIGNED_IN' && session) {
          jwtToken = session.access_token;
          user = session.user;
          showMainApp();
        } else if (event === 'SIGNED_OUT') {
          logout();
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

    const confirmedCount = sections.filter(s => s.status === 'confirmado').length;
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
            alert('You\'ve reached the rate limit. Please wait a minute before trying again.');
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
          alert('You\'ve reached the rate limit. Please wait a minute before trying again.');
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
  const catalogOverlay = document.getElementById('Catalog-Overlay');
  const catalogContent = document.getElementById('Catalog-Content');
  const catalogLoading = document.getElementById('Catalog-Loading');
  const catalogCloseBtn = document.getElementById('Catalog-CloseBtn');

  // Update Catalog button state based on confirmed sections count
  function updateCatalogButton(sections) {
    if (!catalogBtn || !catalogLabel) return;

    const confirmedCount = sections.filter(s => s.status === 'confirmado').length;
    catalogLabel.textContent = `Catalog — ${confirmedCount} of 9 sections ready`;

    if (confirmedCount >= 9) {
      catalogBtn.disabled = false;
    } else {
      catalogBtn.disabled = true;
    }
  }

  // Render Catalog HTML from structured data
  function renderCatalogHTML(catalog) {
    const angleColors = {
      'Útil': '#1B7F4C', 'Inmersivo': '#2B4CD8', 'Reflexivo': '#B5720B', 'Vulnerable': '#C2262E'
    };

    let html = `<div style="margin-bottom:24px">
      <span style="font-family:monospace;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#5C6675">Approach</span>
      <h2 style="margin:4px 0 0;color:#1A1B1D">${catalog.approach}</h2>
    </div>`;

    if (!catalog.gate_passed) {
      html += `<div style="background:#FDF3F3;border-left:3px solid #C2262E;padding:12px 16px;border-radius:6px;margin-bottom:24px">
        <b style="color:#1A1B1D">Catalog not sustainable yet</b><br><span style="color:#5C6675">${catalog.gate_reason || 'Missing valid ideas.'}</span>
      </div>`;
    }

    catalog.categories.forEach(cat => {
      html += `<h3 style="margin:32px 0 12px;color:#1A1B1D;font-size:18px">${cat.name}</h3>`;
      cat.ideas.forEach(idea => {
        const color = angleColors[idea.angle] || '#5C6675';
        html += `<div style="border:1px solid #D5DAE4;border-radius:6px;padding:14px 16px;margin-bottom:10px;background:#FFFFFF">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline">
            <b style="color:#1A1B1D;font-size:15px">${idea.title}</b>
            <span style="font-size:11px;font-weight:600;color:${color};border:1px solid ${color};border-radius:999px;padding:2px 10px;white-space:nowrap">${idea.angle}</span>
          </div>
          <div style="font-family:monospace;font-size:12.5px;color:#5C6675;margin-top:8px">${idea.demand_signal}</div>
        </div>`;
      });
    });

    return html;
  }

  // Generate Catalog
  async function generateCatalog() {
    if (!catalogBtn || catalogBtn.disabled) return;

    try {
      // Show loading state on button
      catalogBtn.classList.add('loading');
      catalogBtn.disabled = true;

      // Show overlay with loading spinner
      catalogOverlay.style.display = 'flex';
      catalogContent.style.display = 'none';
      catalogContent.innerHTML = '';
      catalogLoading.style.display = 'flex';

      // Step 1: Try to get cached catalog first (no credits charged)
      const cacheResponse = await authenticatedFetch('/api/catalog', {
        method: 'GET'
      });

      if (cacheResponse.ok) {
        // Cached catalog exists - display it without charging credits
        const cacheData = await cacheResponse.json();
        catalogLoading.style.display = 'none';
        catalogContent.style.display = 'block';
        catalogContent.innerHTML = renderCatalogHTML(cacheData.catalog);

        console.log('[Catalog] Loaded from cache - no credits charged');
        return;
      }

      // Step 2: If cache returns 404, generate new catalog (charges 15 credits)
      if (cacheResponse.status === 404) {
        // Confirm cost before proceeding
        const confirmed = confirm('Generating your content catalog costs 15 credits. Continue?');
        if (!confirmed) {
          catalogOverlay.style.display = 'none';
          return;
        }

        const response = await authenticatedFetch('/api/catalog/generate', {
          method: 'POST'
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
              alert(`Your brand brain is incomplete. ${missing} section${missing > 1 ? 's' : ''} need${missing > 1 ? '' : 's'} to be confirmed before generating your catalog. Keep talking with Brandy to complete them.`);
            } else {
              alert(`Your brand brain is incomplete: ${body.error}. Keep talking with Brandy to complete all 9 sections.`);
            }
          } else if (response.status === 402) {
            alert('Not enough credits to generate catalog. Please purchase more credits to continue.');
          } else if (response.status === 429) {
            alert('You\'ve reached the rate limit. Please wait a minute before trying again.');
          } else {
            alert(`Failed to generate catalog: ${body.error || body || response.status}`);
          }

          catalogOverlay.style.display = 'none';
          return;
        }

        // Success - display the catalog
        catalogLoading.style.display = 'none';
        catalogContent.style.display = 'block';
        catalogContent.innerHTML = renderCatalogHTML(data.catalog);

        // Update credits display if included in response
        if (data.credits_remaining !== undefined) {
          updateCreditsUI(data.credits_remaining, initialSessionCredits);
        }

        console.log('[Catalog] Document generated successfully');
        return;
      }

      // Handle other cache errors
      const cacheError = await cacheResponse.json();
      alert(`Failed to load catalog: ${cacheError.error || cacheError.detail || cacheResponse.status}`);
      catalogOverlay.style.display = 'none';

    } catch (error) {
      console.error('[Catalog] Loading error:', error);
      alert('Failed to load catalog: ' + error.message);
      catalogOverlay.style.display = 'none';
    } finally {
      // Remove loading state from button and restore state
      catalogBtn.classList.remove('loading');
      if (cachedBrain && cachedBrain.sections) {
        const confirmedCount = cachedBrain.sections.filter(s => s.status === 'confirmado').length;
        catalogBtn.disabled = confirmedCount < 9;
      } else {
        catalogBtn.disabled = true;
      }
    }
  }

  // Close Catalog overlay
  function closeCatalogOverlay() {
    if (catalogOverlay) {
      catalogOverlay.style.display = 'none';
    }
  }

  // Wire up Catalog button and overlay controls
  if (catalogBtn) {
    catalogBtn.addEventListener('click', generateCatalog);
  }

  if (catalogCloseBtn) {
    catalogCloseBtn.addEventListener('click', closeCatalogOverlay);
  }

  // Close overlay on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && brandSoulOverlay && brandSoulOverlay.style.display !== 'none') {
      closeBrandSoulOverlay();
    }
    if (e.key === 'Escape' && catalogOverlay && catalogOverlay.style.display !== 'none') {
      closeCatalogOverlay();
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

  // Initialize on page load
  document.addEventListener('DOMContentLoaded', async () => {
    await initSupabase();
    await handleAuthCallback();
  });

  console.log('[Voice Client] Initialized - Connecting directly to AssemblyAI Voice Agent API');
  console.log('[Audio] Sample rate: 24kHz');
  console.log('[Processor] AudioWorklet for PCM16 conversion');
  console.log('[Auth] Google OAuth enabled');

})();
