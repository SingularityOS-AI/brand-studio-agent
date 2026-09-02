# agent_mockup

The browser client and token server. This is the working part of the repo today: you can talk to the agent and interrupt it.

## Run it

```bash
pip install -r ../requirements.txt
cp ../.env.example ../.env     # put ASSEMBLYAI_API_KEY in it
python server.py
```

Open `http://localhost:8088` in **Chrome or Edge** and allow the microphone.

Windows users can double-click `RUN_MOCKUP.bat` instead.

## What it does

| Endpoint | Purpose |
|---|---|
| `GET /` | Serves the client |
| `GET /api/health` | Reports whether the API key is configured |
| `GET /api/token` | Mints a short-lived, single-use token from AssemblyAI |

**The API key never reaches the browser.** The server mints a token that expires in minutes; the client passes it as `?token=` on the WebSocket URL and talks to AssemblyAI directly from there.

## The audio path, and why it is fussy

```
getUserMedia → AudioWorklet → PCM16 mono 24 kHz → base64 → WebSocket
                                                              ↓
      playback queue ← Int16 → Float32 ← base64 ← reply.audio
```

Four constraints that are easy to get wrong:

- **24 kHz exactly.** `new AudioContext({ sampleRate: 24000 })` so nothing resamples. Safari ignores this and needs manual resampling, which is why Chrome or Edge is the recommendation.
- **`echoCancellation: true`, `noiseSuppression: false`, `autoGainControl: true`.** Browser noise suppression and server-side processing are independent passes; running both eats real speech in a noisy room.
- **Flush playback on `input.speech.started`**, not on `reply.done`. Waiting for the reply to close leaves roughly a second of stale audio playing after the user interrupts. Flushing early makes barge-in feel noticeably snappier.
- **Do not send `input.audio` before `session.ready`.** Buffer or drop early frames.

## In the panel

Voice selection, greeting and system prompt are editable in the left panel, so you can change the agent's behaviour without touching code. Turn detection thresholds are sent via `session.update` and can be changed mid-session.

## What is not here yet

Tool calling (`tool.call` / `tool.result`) and the async bus (`reply.create`) are not wired in this mockup. It carries the conversation; it does not yet carry the judgment. See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
