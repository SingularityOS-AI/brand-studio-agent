# Architecture

How Brand Studio Agent is put together, and why each piece sits where it does.

---

## The shape of the problem

Two things happen on very different timescales:

- **The conversation** is real time. Sub-second. If it stalls, the product feels broken.
- **The work** — transcription, judgment, rendering — takes seconds to minutes.

Most voice agents solve this by blocking: the tool runs, the agent goes quiet, the user stares at a spinner. That is the single worst thing a voice product can do, because silence in a conversation reads as failure.

The whole architecture exists to keep those two timescales apart.

---

## System overview

```mermaid
flowchart TD
    subgraph Browser
        MIC([Microphone]) --> AW[AudioWorklet<br/>PCM16 mono 24 kHz]
        AW --> WS{{WebSocket}}
        WS --> SPK([Playback + flush on barge-in])
        UI[Verdict panel<br/>citations highlighted]
    end

    subgraph AssemblyAI
        VA[Voice Agent API<br/>turn-taking · barge-in · tool calling]
        STT[Streaming STT<br/>word-level timestamps]
        GW[LLM Gateway<br/>forced JSON schema]
    end

    subgraph Backend[FastAPI backend]
        TOK[/api/token<br/>short-lived token minting]
        JUDGE[Judge<br/>rubric orchestration]
        QUEUE[(Job queue)]
        EDL[EDL builder]
    end

    WS <--> VA
    TOK -.mints.-> WS
    VA -->|tool.call| JUDGE
    JUDGE -->|transcript_id| GW
    GW -->|Verdict JSON| JUDGE
    JUDGE -->|tool.result under 1s| VA
    JUDGE --> QUEUE
    QUEUE -->|on completion| RC[reply.create]
    RC --> VA
    VA -->|agent speaks up| SPK
    JUDGE --> UI

    RAW[(Raw footage)] --> STT
    STT --> EDL
    RAW --> GEM[Gemini · vision only]
    GEM --> EDL
    EDL --> QUEUE
```

---

## Why the work is split this way

| Task | Engine | Reason |
|---|---|---|
| Conversation, turn-taking, barge-in | **AssemblyAI Voice Agent API** | Single connection handles STT, LLM routing, TTS and interruption. Rebuilding that stack buys nothing |
| Transcription of uploaded footage | **AssemblyAI Streaming STT** | Word-level timestamps are the raw material of the edit decision list |
| The verdict | **AssemblyAI LLM Gateway** | Forced JSON schema with automatic repair of malformed tool-call responses. `transcript_id` injects the transcript without us storing it |
| Vision | **Gemini** | The Gateway is text-to-text. Visual hooks in footage need a model that sees |

AssemblyAI carries three of the four. Gemini covers only the gap.

---

## The asynchronous pattern

This is the piece worth reading closely.

A tool that takes minutes cannot block a conversation. The docs allow `reply.create` to be sent **at any time**, not only during a hold, so:

```
1. Agent decides to render          → tool.call
2. Backend enqueues the job         → tool.result in under 1s, with a job id
3. Conversation continues           → the user keeps talking about scene 4
4. Job finishes in the background
5. Backend pushes reply.create      → { "type": "reply.create",
                                        "instructions": "Tell them the cut is ready." }
6. Agent speaks up on its own
```

No `hold`, no dead air, no spinner. The user finds out because the agent tells them.

---

## The Judge

The verdict is the product, so its contract is strict.

```json
{
  "purity": 0,
  "score": 0,
  "axes": { "fluff": 0, "logic": 0, "retention": 0 },
  "villain_found": false,
  "missing_elements": [],
  "verdict": "CUT | RESHOOT | DISCARD",
  "citations": [
    { "quote": "...", "rubric_component": "...", "why": "..." }
  ]
}
```

**Invariant, enforced by a test:** `purity` and `score` are never rendered without at least one entry in `citations`. A number with nothing to point at is an opinion wearing a lab coat, and the product exists specifically to not do that.

**The gate:** below 9/10 the script is withheld. The user can override by voice; the override is recorded with its reason.

---

## The Edit Decision List

The atomic unit is the **Thought Unit** — the smallest sentence of the script where a b-roll or an idea belongs.

```json
{
  "video": "raw.mp4",
  "duration_sec": 0,
  "clips":     [ { "start": 0, "end": 0, "type": "keep", "subtitle": "" } ],
  "subtitles": [ { "time": 0, "text": "" } ]
}
```

Editing this list costs milliseconds. Rendering costs minutes. So the user iterates on the list by voice and renders once, at the end.

---

## Security

- **The API key never reaches the browser.** `GET /api/token` mints a short-lived token server-side; the client passes it as `?token=` on the WebSocket URL.
- **Fail-closed configuration.** Missing secrets stop the process at startup rather than falling back to a default. A hardcoded fallback secret in a public repo is the same as no secret at all.
- **Every endpoint that spends credits sits behind authentication, per-account and per-IP rate limits, and a hard budget cap** that shuts the feature off instead of continuing to bill.
- `.env` is gitignored, and so is every internal document in the source workspace.

---

## Browser constraints worth knowing

- Audio is **PCM16 mono at 24 kHz, base64**. Force it with `new AudioContext({ sampleRate: 24000 })` so nothing resamples on the way in.
- **Chrome or Edge.** Safari ignores the constructor's `sampleRate` and needs manual resampling.
- `echoCancellation: true`, `noiseSuppression: **false**`, `autoGainControl: true`. Server-side noise handling and browser noise suppression are independent passes; running both eats real speech.
- **Flush playback on `input.speech.started`**, not on `reply.done`. Waiting for the reply to close leaves about a second of stale audio playing after the user interrupts.
- Never send `input.audio` before `session.ready`. Buffer or drop early frames.
