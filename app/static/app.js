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
        } else if (response.status === 402) {
          alert('You ran out of credits.');
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
      alert('Could not contact server for voice token.');
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

  // Voice credits reservation
  let voiceRenewalTimer = null;
  let initialSessionCredits = 250; // Will be fetched from /api/config

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

  // Transcript limits for context window protection
  const MAX_TRANSCRIPT_TURNS = 20;  // Maximum number of recent turns to include
  const MAX_TRANSCRIPT_CHARS = 4000; // Maximum characters for recent transcript

  // Default voice and prompts (can be customized)
  const baseSystemPrompt = `You are Brandy, the Brand Studio Agent. You help entrepreneurs and businesses discover their brand identity through targeted questions about their business.

Speak naturally in short, clear sentences. Be direct and helpful. Keep responses concise - no more than 2-3 sentences unless more detail is needed.

Your goal is to gather information about:
1. What they do and who they do it for
2. THEIR stage as a founder (1-5), not their company's stage
3. Whether they speak as an Expert (proven achievement) or a Student (documenting in real time)
4. THEIR brand journey: where they want to end up and what they want to be known for

After exploring their business, you have access to a tool called "extract_brand_brain" that analyzes our conversation and extracts nine key brand sections:
- Brand Journey (founder's journey: desired result → what they want to be known for → what to DO → what to LEARN)
- Etapa del Fundador (Founder Stage 1-5: not started · invisible pro · stuck creator · not monetizing · authority figure)
- El Charco del Dolor (Core Pain Point)
- Experto o Estudiante (Expert or Student: triage that governs the rest of the session - if "student", frame as scientist documenting, NOT expert claiming)
- Punto Contrarian (Contrarian Position)
- Asociaciones Mentales (Mental Associations)
- Identidad de Marca (Brand Identity)
- Oferta Irresistible (Irresistible Offer)
- Lead Magnet (Lead Magnet)

CRITICAL: Before finalizing ANY section, you must confirm with the user. Repeat what you understood in your own words and ask for correction. Example: "If I understand correctly, your core pain point is X — and it's NOT Y. Am I on track?" This validates the understanding and gets their exact words for citation.

Never propose empty content without a citation. If you don't have a user quote to support a section, leave it blank and ask more questions.

When identifying their FOUNDER stage, always specify:
- The stage name, from this exact scale — never invent one:
  1 = has not started · 2 = invisible professional · 3 = stuck creator
  4 = creator not monetizing · 5 = authority figure
- The ONE key skill to unlock at that level
- What's PROHIBITED at that level (what they must NOT do yet)

For example: "You're at stage 2, the invisible professional. The only thing that matters now is your perspective — your scar. And it's forbidden to optimize posting times: no magic hour saves a message that sounds like everyone else's."

When confirming stages or major conclusions, always include context like: "I see you as Stage 3 because... The key to unlock now is... Before this, avoid..."

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
        if (response.status === 402) {
          // Out of credits
          const body = await response.json();
          return {
            success: false,
            error: 'out_of_credits',
            message: 'You ran out of voice credits. Please purchase more to continue.',
            payment_url: body.payment_url
          };
        } else if (response.status === 401) {
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
      return {
        success: false,
        error: 'network',
        message: 'Could not contact server to reserve credits.'
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
          alert('You ran out of voice credits. Please purchase more to continue: ' + reservation.payment_url);
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
              alert('You ran out of voice credits. The microphone will now close.');
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
              turn_detection: {
                vad_threshold: 0.5,
                min_silence: 200,
                max_silence: 1000,
                interrupt_response: true
              }
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
                description: 'Extract nine brand sections from our conversation to backend. Return a JSON object with "validation_status" ("valid"/"partial"/"invalid") and "brand_brain" dict. For EACH section: provide content AND exact user quote (citation). Skip sections without user support. Sections: brand_journey, etapa, charco, credibilidad, contrarian, asociaciones, identidad, oferta, lead_magnet.',
                parameters: {
                  type: 'object',
                  properties: {
                    validation_status: {
                      type: 'string',
                      enum: ['valid', 'partial', 'invalid'],
                      description: 'Status of extraction'
                    },
                    brand_brain: {
                      type: 'object',
                      description: 'Extracted brand sections with framework names as keys (pain_puddle, segues_stage, ralston_journey, etc.)'
                    }
                  },
                  required: ['validation_status', 'brand_brain']
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
        if (orbState) orbState.textContent = 'Hablando...';
        break;

      case 'transcript.user':
        // User final transcript
        appendUserMessage(msg.text);
        // Track turn for extraction
        fullTranscript.push({ speaker: 'user', text: msg.text });
        if (orbState) orbState.textContent = 'Pensando...';
        break;

      case 'input.speech.stopped':
        break;

      case 'reply.started':
        if (orbState) orbState.textContent = 'Brandy hablando...';
        break;

      case 'reply.audio':
        // Play audio chunk from AssemblyAI
        playAudioChunk(msg.data);
        break;

      case 'transcript.agent':
        // Agent final transcript
        appendAgentMessage(msg.text);
        // Track turn for extraction
        fullTranscript.push({ speaker: 'agent', text: msg.text });
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
    console.log('[Tool Call]', toolName, args);

    if (toolName === 'extract_brand_brain') {
      try {
        // Build transcript from stored messages
        const transcriptText = fullTranscript.map(t => `${t.speaker}: ${t.text}`).join('\n');
        const turnCount = Math.ceil(fullTranscript.length / 2); // Agent + user pairs

        // args is what the agent extracted - pass it as tool_result directly
        // Agent should have provided validation_status and brand_brain with extracted sections
        const tool_result = args || {
          validation_status: 'valid',
          brand_brain: {}
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
              sections_extracted: result.sections_count
            })
          }));
        }

        // Update UI with extracted sections
        if (result.brand_brain && result.brand_brain.sections) {
          appendExtractedSections(result.brand_brain.sections);
          updateBrandSoulButton(result.brand_brain.sections);

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
            result: {
              success: false,
              error: error.message
            }
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

    const sectionOrder = ['brand_journey', 'etapa', 'charco', 'credibilidad', 'contrarian', 'asociaciones', 'identidad', 'oferta', 'lead_magnet'];
    const labels = {
      'brand_journey': 'Brand Journey',
      'etapa': 'Stage',
      'charco': 'The pond',
      'credibilidad': 'Expert or Student',
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
        if (sectionId === 'contrarian' || sectionId === 'asociaciones') {
          const entries = Object.entries(section.content);
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
      initialSessionCredits = 250;
    }
  }

  // Update credits UI (helper function)
  function updateCreditsUI(remaining, initial) {
    const creditsLabel = document.getElementById('Credits-Label');
    const creditsBar = document.getElementById('Credits-Bar');

    if (creditsLabel) {
      creditsLabel.innerHTML = `${remaining} <span style="font-size:12px;color:#5C6675">/ ${initial}</span>`;
    }

    if (creditsBar) {
      const percentage = Math.max(0, Math.min(100, (remaining / initial) * 100));
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
  }

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

  // Update Brand Soul button state based on confirmed sections count
  function updateBrandSoulButton(sections) {
    if (!brandSoulBtn || !brandSoulLabel) return;

    const confirmedCount = sections.filter(s => s.status === 'confirmado').length;
    brandSoulLabel.textContent = `Brand Soul — ${confirmedCount} of 9 sections ready`;

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
          alert('You ran out of credits. Brand Soul generation requires 20 credits.');
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

      console.log('[Brand Soul] Document generated successfully');

    } catch (error) {
      console.error('[Brand Soul] Generation error:', error);
      alert('Failed to generate Brand Soul: ' + error.message);
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

  // Close Brand Soul overlay
  function closeBrandSoulOverlay() {
    if (brandSoulOverlay) {
      brandSoulOverlay.style.display = 'none';
    }
  }

  // Wire up Brand Soul button and overlay controls
  if (brandSoulBtn) {
    brandSoulBtn.addEventListener('click', generateBrandSoul);
  }

  if (brandSoulDownloadBtn) {
    brandSoulDownloadBtn.addEventListener('click', downloadBrandSoul);
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
