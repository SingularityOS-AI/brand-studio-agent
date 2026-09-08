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

  // Transcript storage for extraction
  let fullTranscript = [];

  // Default voice and prompts (can be customized)
  const systemPrompt = `You are Brandy, the Brand Studio Agent. You help entrepreneurs and businesses discover their brand identity through targeted questions about their business.

Speak naturally in short, clear sentences. Be direct and helpful. Keep responses concise - no more than 2-3 sentences unless more detail is needed.

Your goal is to gather information about:
1. What they do and who they do it for
2. Their business stage and challenges
3. Their brand's values and unique positioning
4. Understanding their target customer's journey

After exploring their business, you have access to a tool called "extract_brand_brain" that analyzes our conversation and extracts nine key brand sections:
- Viaje del Cliente (Customer Journey)
- Etapa del Negocio (Business Stage)
- El Charco del Dolor (Core Pain Point)
- Credibilidad del Problema (Problem Credibility)
- Punto Contrarian (Contrarian Position)
- Asociaciones Mentales (Mental Associations)
- Identidad de Marca (Brand Identity)
- Oferta Irresistible (Irresistible Offer)
- Lead Magnet (Lead Magnet)

Always cite what the user says when you propose content. For example: "Based on what you said about 'losing 50% of leads', I see your charco (pain point) as..."

If the user corrects you, acknowledge it and confirm the correction with their words. Never propose empty content without a citation.

Always respond in English. Keep your responses conversational and engaging.`;

  const greeting = "Hello! I'm Brandy, your Brand Studio Agent. I'll help you discover your brand identity through conversation. Tell me what you do and who you do it for.";
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
            },
            // Register extract_brand_brain tool
            tools: [
              {
                name: 'extract_brand_brain',
                description: 'Extract nine brand sections from our conversation: brand_journey, etapa, charco, credibilidad, contrarian, asociaciones, identidad, oferta, lead_magnet. Always cite what the user said as the source.',
                parameters: {
                  type: 'object',
                  properties: {
                    transcript: {
                      type: 'string',
                      description: 'Full conversation transcript'
                    },
                    turn_count: {
                      type: 'integer',
                      description: 'Number of turns in the conversation'
                    }
                  },
                  required: ['transcript', 'turn_count']
                }
              }
            ]
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

        // Call backend extraction endpoint
        const response = await fetch('/api/brain/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include', // Include cookies for session token
          body: JSON.stringify({
            transcript: transcriptText,
            turn_count: turnCount,
            // For now, pass a minimal tool_result (in production this would come from actual LLM call)
            tool_result: {
              validation_status: 'valid',
              brand_brain: {} // Backend will handle real extraction
            }
          })
        });

        if (!response.ok) {
          throw new Error(`Extraction failed: ${response.status}`);
        }

        const result = await response.json();
        console.log('[Extraction Result]', result);

        // Send tool.result back to agent
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'tool.result',
            call_id: callId,
            result: {
              success: true,
              brand_brain: result.brand_brain,
              sections_extracted: result.sections_count
            }
          }));
        }

        // Update UI with extracted sections
        if (result.brand_brain && result.brand_brain.sections) {
          appendExtractedSections(result.brand_brain.sections);
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
