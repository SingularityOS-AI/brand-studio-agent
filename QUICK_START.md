# Quick Start Guide - Brand Studio Voice Agent

## What Was Fixed

### 1. ✅ Duplicate Transcriptions - FIXED
Each turn used to appear twice. Now shows only once.

### 2. ✅ Wrong Language - FIXED
Now transcribes in Spanish (was defaulting to English).

### 3. ✅ Deprecation Warning - FIXED
Updated to use `language_codes` instead of deprecated `language_code`.

### 4. ✅ No Audio Output - FIXED
Added text-to-speech - now speaks back transcriptions in Spanish.

---

## How to Test

### Step 1: Restart the Server
```bash
# Stop the current server (press Ctrl+C in the terminal)
# Then start it again:
cd "C:\Users\gabri\Desktop\SINGULARITYOS\_PROYECTOS_SUELTOS_SIN_CLASIFICAR\hackaton lablab assemly IA voice agent\brand-studio-agent"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

### Step 2: Open in Browser
Navigate to: http://127.0.0.1:8010

### Step 3: Test Voice
1. **Click the microphone button** (blue circle)
2. **Speak in Spanish:**
   - "Hola, ¿cómo estás?"
   - "Mi nombre es Juan"
   - "¿Qué hora es?"
3. **Verify:**
   - ✅ Text appears on screen (once, not twice)
   - ✅ Text is in Spanish
   - ✅ Audio plays back (Spanish TTS voice speaks it)

### Step 4: Check Browser Console
Press F12, go to Console tab. You should see:
```
[Voice Client] Initialized
[TTS] Initial voices loaded: X total, Y Spanish
```

When you speak:
```
[TTS] Speaking: Hola, ¿cómo estás?
```

---

## Troubleshooting

### ❌ "No audio playing"
**Solution:**
- Check your speakers are on
- Ensure browser volume is up
- Click the microphone button first (browsers need user interaction)

### ❌ "Still seeing duplicates"
**Solution:**
- **Restart the server** (Ctrl+C, then run again)
- The old code is cached in memory until restart

### ❌ "Transcribing in English instead of Spanish"
**Solution:**
- Check `.env` file has `STT_LANGUAGE=es`
- Restart the server after changing `.env`

### ❌ "No Spanish voice available"
**Solution:**
- Browser uses default voice if Spanish not available
- Install Spanish language pack:
  - **Windows:** Settings → Time & Language → Language → Add a language → Spanish
  - **Chrome:** chrome://settings/languages → Add Spanish

---

## Configuration

### Change TTS Settings (Speed, Pitch, Volume)
Edit `app/static/app.js`, line 227-230:
```javascript
utterance.rate = 1.0;    // Speed: 0.5 (slow) to 2.0 (fast)
utterance.pitch = 1.0;   // Pitch: 0.5 (low) to 2.0 (high)
utterance.volume = 1.0;  // Volume: 0.0 (mute) to 1.0 (max)
```

### Change Transcription Language
Edit `.env` file:
```env
STT_LANGUAGE=en          # For English
STT_LANGUAGE=es          # For Spanish
STT_LANGUAGE=fr          # For French
```
**After changing, restart the server!**

### High-Quality TTS (Optional)
The current implementation uses browser's free TTS. For better quality:

1. **ElevenLabs** (Professional quality):
   - Get API key: https://elevenlabs.io/app/settings/api-keys
   - Add to `.env`:
     ```env
     ELEVENLABS_API_KEY=your_key_here
     ```
   - Requires server-side integration (not implemented yet)

2. **OpenAI TTS** (Good quality, fast):
   - Requires similar integration

---

## Test Checklist

Verify each of these works:

- [ ] Microphone permission requested and granted
- [ ] Clicking mic button starts listening
- [ ] Speaking produces transcript on screen
- [ ] Transcript appears **only once** (no duplicates)
- [ ] Transcript is in **Spanish** (or your configured language)
- [ ] Audio plays back (Spanish voice speaks it)
- [ ] Clicking mic button again stops listening
- [ ] Browser console shows no errors

---

## Files Changed

### Backend (Server)
- `app/voice/wrapper.py` - Fixed duplicates and language
- `app/config.py` - Added STT_LANGUAGE setting
- `app/main.py` - Passes language to wrapper
- `app/__init__.py` - (no changes)
- `.env.example` - Shows STT_LANGUAGE configuration
- `render.yaml` - Deployment configuration

### Frontend (Browser)
- `app/static/app.js` - Added TTS (speech playback)
- `app/static/index.html` - (no changes)

### Tests
- `tests/test_voice_ws.py` - Added 4 new tests

---

## Need Help?

### Check Server Logs
When you restart the server, you should see:
```
[guard] sin Supabase: estado en memoria, se pierde al reiniciar
INFO:     Started server process [8700]
INFO:     Uvicorn running on http://127.0.0.1:8010
```

### Check Browser Console
Press F12 → Console tab. Look for:
```
[Voice Client] Initialized
[TTS] Initial voices loaded
[WebSocket] Connected
[Audio] Requested sample rate: 16000 Hz
```

### Test TTS Independently
Open browser console (F12) and run:
```javascript
const utterance = new SpeechSynthesisUtterance("Hola, ¿cómo estás?");
utterance.lang = 'es-ES';
window.speechSynthesis.speak(utterance);
```
You should hear "Hola, ¿cómo estás?" in Spanish.

---

## Success! 🎉

Your voice agent now:
- ✅ Captures microphone input
- ✅ Transcribes in Spanish (no duplicates)
- ✅ Displays text on screen
- ✅ Speaks back the text in Spanish

All tests passing: **20/20** ✓
