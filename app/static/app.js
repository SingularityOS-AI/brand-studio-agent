/**
 * Brand Studio Agent — Voice Client
 *
 * Handles microphone capture, PCM16 16kHz mono conversion, and WebSocket communication.
 */
(function() {
  'use strict';

  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let processor = null;
  let isListening = false;

  const micBtn = document.getElementById('micBtn');
  const orb = document.querySelector('.orb');
  const orbState = document.querySelector('.orbstate');
  const streamContainer = document.querySelector('.stream');

  // Current partial transcript (being updated live)
  let currentPartialElement = null;
  // All final transcripts committed so far
  let finalTranscripts = [];

  /**
   * Initialize microphone and audio conversion pipeline.
   */
  async function startMicrophone() {
    try {
      // Request microphone permission
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Create AudioContext with 16kHz sample rate
      // Note: We do NOT resample if browser ignores the request.
      // Chromium respects it; Safari historically ignores it.
      // If actualSampleRate !== 16000, the voice pipeline will produce incorrect results.
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioContextClass({ sampleRate: 16000 });

      // Check actual sample rate (may differ from requested)
      const actualSampleRate = audioContext.sampleRate;
      console.log(`[Audio] Requested sample rate: 16000 Hz, actual: ${actualSampleRate} Hz`);
      if (actualSampleRate !== 16000) {
        console.error(
          `[Audio] SAMPLE RATE MISMATCH: Expected 16000 Hz, got ${actualSampleRate} Hz. ` +
          "Transcription will NOT work correctly without resampling implementation!"
        );
      }

      const source = audioContext.createMediaStreamSource(mediaStream);

      // AudioWorklet is preferred but we'll use ScriptProcessorNode for simplicity
      // It's deprecated but supported in all browsers. Uncomment below to use Worklet.
      // await audioContext.audioWorklet.addModule('/static/processor.js');
      // processor = new AudioWorkletNode(audioContext, 'audio-processor');
      processor = audioContext.createScriptProcessor(4096, 1, 1);

      // Convert Float32 audio to PCM16 Int16
      processor.onaudioprocess = (event) => {
        const inputBuffer = event.inputBuffer.getChannelData(0);
        const pcm16 = floatToPCM16(inputBuffer);
        sendAudioChunk(pcm16);
      };

      source.connect(processor);

      // Add silent GainNode to prevent audio feedback loop
      // ScriptProcessorNode needs to be connected to trigger onaudioprocess,
      // but we don't want the user's voice coming back through their speakers
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0; // Complete silence
      processor.connect(silentGain);
      silentGain.connect(audioContext.destination);

    } catch (err) {
      console.error('[Microphone Error]', err);
      if (err.name === 'NotAllowedError') {
        alert('Microphone permission denied. Please allow microphone access to use voice.');
      } else {
        alert('Failed to access microphone: ' + err.message);
      }
      stopMicrophone();
      return false;
    }
    return true;
  }

  /**
   * Convert Float32 audio (WebAudio format) to PCM16 Int16 (AssemblyAI format).
   */
  function floatToPCM16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      // Clamp to [-1, 1] and scale to [-32768, 32767]
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array.buffer; // Return ArrayBuffer for WebSocket send
  }

  /**
   * Send audio chunk via WebSocket if connected.
   */
  function sendAudioChunk(buffer) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(buffer);
    }
  }

  /**
   * Ensure session exists before opening WebSocket.
   * Tries /api/session first (no credit cost), falls back to /api/token if needed.
   */
  async function ensureSession() {
    try {
      const sessionResp = await fetch('/api/session', { credentials: 'same-origin' });
      if (sessionResp.ok) return true;
    } catch (e) {
      console.log('[Session] Check failed:', e);
    }

    // No valid session, create one via /api/token (costs 1 credit)
    try {
      const tokenResp = await fetch('/api/token', { credentials: 'same-origin' });
      if (tokenResp.ok) return true;

      // Handle specific error states
      if (tokenResp.status === 402) {
        const data = await tokenResp.json();
        alert(`Session budget exhausted. Credits remaining: ${data.credits_remaining}. Please upgrade.`);
      } else if (tokenResp.status === 429) {
        alert('Rate limit exceeded. Please wait a moment before trying again.');
      } else {
        const data = await tokenResp.json().catch(() => ({}));
        alert(`Failed to create session: ${data.detail || data.error || tokenResp.statusText}`);
      }
    } catch (e) {
      console.error('[Session] Create failed:', e);
      alert('Failed to connect to server. Please check your connection.');
    }

    return false;
  }

  /**
   * Connect to WebSocket and start listening.
   */
  async function startListening() {
    // Ensure session exists before opening WebSocket
    const sessionReady = await ensureSession();
    if (!sessionReady) {
      return; // User already alerted by ensureSession()
    }

    // Connect WebSocket - browser sends session cookie automatically (same-origin)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/voice`;

    try {
      ws = new WebSocket(wsUrl);

      ws.onopen = async () => {
        console.log('[WebSocket] Connected');
        // Start microphone after WebSocket is ready
        const success = await startMicrophone();
        if (!success) {
          ws.close();
          return;
        }

        isListening = true;
        updateUIState('listening');
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleTranscription(msg);
      };

      ws.onerror = (error) => {
        console.error('[WebSocket Error]', error);
      };

      ws.onclose = () => {
        console.log('[WebSocket] Closed');
        stopMicrophone();
        isListening = false;
        ws = null;
        updateUIState('idle');
      };

    } catch (err) {
      console.error('[WebSocket Connection Error]', err);
      alert('Failed to connect: ' + err.message);
    }
  }

  /**
   * Handle transcription messages from server.
   */
  function handleTranscription(msg) {
    if (msg.type === 'partial') {
      // Update current partial text
      if (!currentPartialElement) {
        // Create new partial element with caret
        createPartialElement(msg.text);
      } else {
        currentPartialElement.textContent = msg.text;
        addCaret(currentPartialElement);
      }
    } else if (msg.type === 'final') {
      // Commit final transcript
      if (currentPartialElement) {
        currentPartialElement.textContent = msg.text;
        removeCaret(currentPartialElement);
        currentPartialElement.classList.remove('partial');
        finalTranscripts.push(msg.text);
        currentPartialElement = null;

        // Create new empty partial with caret
        createPartialElement('');
      }
    }
  }

  /**
   * Create a new partial transcript element with caret.
   */
  function createPartialElement(text) {
    const p = document.createElement('p');
    p.className = 'sub partial';
    p.textContent = text;
    addCaret(p);
    streamContainer.appendChild(p);
    currentPartialElement = p;
  }

  /**
   * Add blinking caret to element.
   */
  function addCaret(element) {
    // Remove existing caret if any
    const existingCaret = element.querySelector('.caret');
    if (existingCaret) existingCaret.remove();

    const caret = document.createElement('span');
    caret.className = 'caret';
    element.appendChild(caret);
  }

  /**
   * Remove caret from element.
   */
  function removeCaret(element) {
    const caret = element.querySelector('.caret');
    if (caret) caret.remove();
  }

  /**
   * Stop microphone and clean up audio resources.
   */
  function stopMicrophone() {
    if (processor) {
      processor.disconnect();
      processor = null;
    }
    if (audioContext && audioContext.state !== 'closed') {
      audioContext.close();
      audioContext = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }
  }

  /**
   * Stop listening (user clicked mic button again).
   */
  function stopListening() {
    if (ws) {
      ws.close();
    }
    // WebSocket.onclose will call stopMicrophone() and updateUIState()
  }

  /**
   * Update UI to reflect listening state.
   */
  function updateUIState(state) {
    if (state === 'listening') {
      orb.classList.remove('orb--hablando');
      orb.classList.add('orb--escuchando');
      if (orbState) orbState.textContent = 'Listening...';
      if (micBtn) micBtn.style.background = '#D5DAE4'; // Gray when listening
    } else {
      // Idle state
      orb.classList.remove('orb--escuchando');
      orb.classList.add('orb--hablando'); // Back to default animation
      if (orbState) orbState.textContent = 'Brandy speaking';
      if (micBtn) micBtn.style.background = ''; // Back to accent color
    }
  }

  /**
   * Toggle microphone on/off.
   */
  async function toggleMicrophone() {
    if (isListening) {
      stopListening();
    } else {
      await startListening();
    }
  }

  // Wire up microphone button
  if (micBtn) {
    micBtn.addEventListener('click', toggleMicrophone);
  }

  // Log initialization
  console.log('[Voice Client] Initialized');
  console.log('[Audio] Committed sample rate verification:');
  console.log('  - AudioContext will request 16000 Hz');
  console.log('  - Actual rate will be logged on connection');
  console.log('[Processor] Using ScriptProcessorNode (deprecated but stable)');
  console.log('  - For AudioWorklet, uncomment in startMicrophone() and create processor.js');

})();
