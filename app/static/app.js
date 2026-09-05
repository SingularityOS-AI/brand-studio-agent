/**
 * Brand Studio Agent — Voice Client
 *
 * Handles microphone capture, PCM16 16kHz mono conversion, and direct AssemblyAI Voice Agent WebSocket.
 * Adapted from legacy working version that connected directly to AssemblyAI Agent API.
 */
(function() {
  'use strict';

  let API_KEY = '';
  let apiKeyRequested = false;

  // Fetch API key from backend on first interaction
  async function ensureApiKey() {
    if (API_KEY || apiKeyRequested) return API_KEY;
    apiKeyRequested = true;

    try {
      const response = await fetch('/api/agent-token');
      const data = await response.json();
      API_KEY = data.api_key;
      console.log('[Voice Client] API Key fetched from backend');
      return API_KEY;
    } catch (e) {
      console.error('[Voice Client] Failed to fetch API key:', e);
      alert('Failed to get AssemblyAI API key from server. Check server logs.');
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

  // Default voice and prompts (can be customized)
  const systemPrompt = `You are Brandy, the Brand Studio Agent. You help entrepreneurs and businesses discover their brand identity through targeted questions.

Speak naturally in short, clear sentences. Be direct and helpful. Keep responses concise - no more than 2-3 sentences unless more detail is needed.

Your goal is to gather information about:
1. What they do
2. Who they do it for
3. Their brand's values and personality
4. Their desired positioning in the market

Always respond in English. Keep your responses conversational and engaging.`;

  const greeting = "Hello! I'm Brandy, your Brand Studio Agent. Tell me what you do and who you do it for, and we'll discover your brand identity together.";
  const voice = "alba"; // AssemblyAI voice: alba, anna, charles, estelle, eve, george, giovanni, jane, jean, juergen, lola, mary, michael, paul, rafael, vera

  async function startSession() {
    // Ensure we have API key before starting
    const key = await ensureApiKey();
    if (!key) {
      return;
    }

    try {
      stopSession();

      // 1. Create AudioContext with 24kHz (matches AssemblyAI requirement)
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioContextClass({ sampleRate: RATE });

      // 2. Get microphone stream
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

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
        console.log('[WebSocket] Connected to AssemblyAI Voice Agent');
        setUIStatus('connecting', 'Conectando agente...');

        // Send session.update immediately
        const sessionUpdatePayload = {
          type: 'session.update',
          session: {
            system_prompt: systemPrompt,
            greeting: greeting,
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
            }
          }
        };
        ws.send(JSON.stringify(sessionUpdatePayload));
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleAgentEvent(msg);
      };

      ws.onerror = (err) => {
        console.error('[WebSocket Error]', err);
        appendLogMessage('error', 'Error en conexión WebSocket de AssemblyAI');
        stopSession();
      };

      ws.onclose = () => {
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
      await startSession();
    }
  }

  // Wire up button
  if (micBtn) {
    micBtn.addEventListener('click', toggleMicrophone);
  }

  console.log('[Voice Client] Initialized - Connecting directly to AssemblyAI Voice Agent API');
  console.log('[Audio] Sample rate: 24kHz');
  console.log('[Processor] AudioWorklet for PCM16 conversion');

})();
