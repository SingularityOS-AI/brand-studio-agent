# Brand Studio Agent - Progress & Changelog

**Last Updated:** 2025-04-20

---

## Recent Changes (v1.3)

### 1. Transcription Scrolling Fix
**Status:** ✅ Completed
**File:** `app/static/index.html` (CSS), `app/static/app.js` (JavaScript)

**Problem:**
- Transcription content was being lost when messages exceeded visible area
- No scrollbar available, users could not access historical conversation

**Solution:**
- Added `overflow-y: auto` and `scroll-behavior: smooth` to `.stream` CSS class
- Added custom scrollbar styling (6px width, rounded thumb with hover effect)
- Enhanced `appendAgentMessage()` and `updatePartial()` functions with auto-scroll to bottom
- Already had `appendUserMessage()` with scroll functionality

**Code Changes:**
```css
.stream{flex:1;padding:14px 34px;display:flex;flex-direction:column;gap:14px;overflow-y:auto;scroll-behavior:smooth}
.stream::-webkit-scrollbar{width:6px}
.stream::-webkit-scrollbar-track{background:transparent}
.stream::-webkit-scrollbar-thumb{background:#D5DAE4;border-radius:3px}
.stream::-webkit-scrollbar-thumb:hover{background:#5C6675}
```

```javascript
streamContainer.scrollTop = streamContainer.scrollHeight; /* Added to appendAgentMessage, createPartial, updatePartial */
```

---

## Previous Changes Archive

### v1.2 - Voice Agent API Migration
**Date:** 2025-04-19
**Status:** ✅ Completed

**Problem:**
- Server stopped responding after first hardcoded greeting
- Audio transmission failing with "Missing 'audio' field" error
- Voice not playing ("no hay permiso de altavoz")

**Root Cause:**
- AudioWorklet message format mismatch
- Using STT-only streaming SDK instead of Voice Agent API WebSocket

**Solution:**
- Rewrote `app/static/app.js` to connect directly to AssemblyAI Voice Agent API
- Fixed AudioWorklet handler to extract `event.data.audio` instead of `event.data`
- Added inline AudioWorklet definition with PCM16 Int16 conversion
- Implemented Web Audio API playback for `reply.audio` events
- Changed voice from "clara" (invalid) to "alba" (valid)
- Set system prompt to English with greeting

**Critical Files:**
- `app/static/app.js` - Complete voice client reimplementation
- `app/main.py` - Added `/api/agent-token` endpoint for API key retrieval

---

### v1.1 - Duplicate Turns & Language Configuration
**Date:** 2025-04-18
**Status:** ✅ Preserved (but unused by v1.2 Voice Agent API client)

**Problem:**
- Same turn text displayed twice in transcription
- Deprecation warning: `language_code` → `language_codes`
- Wrong language detection (Spanish voice with English audio)

**Solution:**
- Added `turn_is_formatted` flag check to filter duplicates in `app/voice/wrapper.py`
- Converted `language_code` string to `language_codes` list (lines 149-159)
- Added `STT_LANGUAGE` environment variable with default `"es"`

**Code Changes (preserved for `/ws/voice` endpoint):**
```python
# Filter duplicate formatted turns
if turn.get('turn_is_formatted'):
    continue

# Convert language_code to language_codes
language_code = turn_config.get('language_code')
if language_code and isinstance(language_code, str):
    turn_config['language_codes'] = [language_code]
    del turn_config['language_code']
```

---

## Architecture Changes

### Voice Agent API (Current - v1.2+)
- **Connection:** Direct WebSocket to AssemblyAI Voice Agent API
- **Audio Format:** PCM16 mono at 24kHz, base64-encoded
- **Features:** Built-in STT + TTS, real-time transcription, audio playback
- **Timing Rule:** Never send `input.audio` before `session.ready` event

### Legacy STT Proxy (Preserved but unused)
- **Connection:** `/ws/voice` endpoint → AssemblyAI Streaming STT v3 SDK
- **Features:** Transcription only, no TTS
- **Fixes Applied:** Duplicate turn filtering, language configuration

---

## Configuration

### Environment Variables
```bash
STT_LANGUAGE="es"  # Default language for legacy STT endpoint
ASSEMBLYAI_API_KEY="..."  # Required for both APIs
```

### Voice Agent API Config
```javascript
{
  system_prompt: "You are a helpful assistant. Always respond in English.",
  speech_model: "v3",
  audio: { encoding: "pcm16", sample_rate: 24000 },
  turn_detection: { ... },
  voice: "alba"
}
```

---

## Technical Notes

### Audio Pipeline (Voice Agent API)
1. Microphone → Float32 audio
2. Convert to PCM16 Int16
3. Add to 512-sample buffer
4. When buffer full: encode to base64 → send as `input.audio`
5. AssemblyAI processes → returns `reply.audio` (base64 PCM16)
6. Decode PCM16 to Float32 → play via Web Audio API

### Critical AudioWorklet Message Format
```javascript
// CORRECT: Extract audio buffer from message
const uint8 = new Uint8Array(event.data.audio);

// WRONG: Using entire message (caused "Missing 'audio' field" error)
// const uint8 = new Uint8Array(event.data);
```

### Session Guard
- Rate limiting by IP address
- Budget enforcement via cookies → `402` error on depletion

---

## Test Results
- All 20 tests passing ✅
- Audio transmission: Working ✅
- Transcription: Working with scrolling ✅
- Agent response: English with "alba" voice ✅
- Duplicate turns: Fixed ✅
- Language detection: Correct ✅

---

## Deployment Notes
⚠️ **IMPORTANT:** Environment variables (`ASSEMBLYAI_API_KEY`, `STT_LANGUAGE`) must NOT be committed to production. Use `.env` file or secure secrets management.

---

## Next Steps (Future)
- Add auto-generation of CHANGELLOG.md from git commits
- Implement sentiment analysis on transcriptions
- Add voice customization options beyond "alba"
- Experiment with different system prompt variations
- Enhanced error handling for network failures
