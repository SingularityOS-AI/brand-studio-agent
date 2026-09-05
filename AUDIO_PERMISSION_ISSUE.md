# Audio Permission Issue - Solution

## Problem Description
User reports: "no hay permiso de altavoz" (no speaker permission)
- Server logs show WebSocket connects successfully
- Transcription works (STT receives audio)
- BUT no audio is played back to the user

## Root Cause Analysis

Current implementation is **STT-only** (Speech-to-Text):
- Client captures microphone → converts to PCM16 → sends to server
- Server transcribes via AssemblyAI → sends text back to client
- Client displays text in UI (see lines 201-224 in `app/static/app.js`)
- **Missing: TTS (Text-to-Speech) to play back responses**

## What Needs to Be Added

### 1. Server-Side TTS Integration
Choose a TTS provider and integrate it:
- **ElevenLabs** (high quality, requires API key)
- **OpenAI TTS** (good quality, faster)
- **AssemblyAI TTS** (if available in Voice Agent API)

### 2. Client-Side Audio Playback
Modify `app/static/app.js` to:
- Request speaker permission (audio output)
- Receive TTS audio from server (PCM format or MP3)
- Play audio using Web Audio API

### 3. Browser Permission Notes
- **Microphone**: Already implemented (`getUserMedia({ audio: true })`)
- **Speaker**: Usually no permission needed for **playback** (only for capture)
- Exception: Some browsers require permission for **screen sharing** or **system audio capture**
- For **simple playback**, no extra permission needed!

## Verification Steps

To confirm the issue is missing TTS (not permission):

1. Check browser console for TTS-related errors
2. Verify server sends responses (check `/api/session` logs)
3. Test with a simple TTS implementation:

```javascript
// Quick test in browser console
const utterance = new SpeechSynthesisUtterance("Hola, ¿cómo estás?");
window.speechSynthesis.speak(utterance);
```

If this works, the browser can play audio → the issue is missing TTS integration.

## Recommended Fix Options

### Option 1: Use Browser Native TTS (Fastest)
No API key needed, works immediately:
```javascript
function speak(text) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'es-ES'; // Spanish
  window.speechSynthesis.speak(utterance);
}
```

### Option 2: ElevenLabs TTS (Best Quality)
Add to `app/config.py`:
```python
elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
```

Add to `app/main.py`:
- Call ElevenLabs API when response is ready
- Stream audio back to client via WebSocket
- Client plays audio chunks as they arrive

### Option 3: AssemblyAI Voice Agent API (Full Integration)
Use the `AssemblyAIVoiceAgentClient` class from `app/voice/wrapper.py`
- This is already implemented (lines 219-306)
- Provides bidirectional voice (STT + TTS + VAD)
- Requires changing from custom WebSocket to Voice Agent API

## Updated File Status

### ✅ Fixed in Previous Work
- [x] `app/voice/wrapper.py` - Changed `language_code` to `language_codes` (removes deprecation warning)
- [x] All tests passing

### 🔄 Need to Add
- [ ] TTS provider configuration (`app/config.py`)
- [ ] TTS API integration (`app/main.py` or new endpoint)
- [ ] Client-side audio playback (`app/static/app.js`)
- [ ] Audio output permission handling (rarely needed)

## Next Steps for User

1. **Confirm browser can play audio**: Run the console test above
2. **Choose TTS provider**: Native (free), ElevenLabs (quality), or AssemblyAI (full)
3. **Implement chosen option**: See code snippets above
4. **Test with Spanish**: Ensure TTS uses Spanish voice

## Quick Fix (Test Now)

Add this to `app/static/app.js` in `handleTranscription()` function:

```javascript
else if (msg.type === 'final') {
  // Speak the final transcript using browser TTS
  const utterance = new SpeechSynthesisUtterance(msg.text);
  utterance.lang = 'es-ES'; // Use Spanish voice when available
  window.speechSynthesis.speak(utterance);

  // ... existing code ...
}
```

This will immediately play back transcriptions using the browser's built-in TTS!
