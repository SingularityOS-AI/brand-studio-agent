# Block F — Agentic Mode: Brandy runs the pipeline by voice (signed spec, 2026-09-25)

Signed by the CEO "with changes" on 2026-09-25 (source: the CEO's local
`SPEC_MODO_AGENTICO.html`). Builds after Editing consolidation (block E.2 runs in a
parallel lane; Editing-by-voice comes last). Deadline 2026-09-30 11:00 VET.

## Vision
With **Agentic mode** on, Brandy knows which step you are in, what is done, what is missing
and what comes next, and does what the buttons do — by voice. A founder can build a video
end to end while driving: the only clicks are **the microphone, recording the takes in the
teleprompter, and exporting the video**. Everything Brandy does appears in the right panel
as an audit trail.

Principles
1. **Iterative, not autopilot.** The founder decides every action with consequences.
2. **One source of truth.** Brandy calls the same functions and endpoints as the buttons.
   No voice backend with its own rules, prices or bugs.
3. **Never spend on a transcription error.** Anything that charges, discards, locks or
   can't be undone needs a two-turn **voice** confirmation, enforced by code.

## Signed decisions (with the CEO's changes)
| ID | Decision |
|---|---|
| A-D1 | Two turns, **voice only, hands-free, explicit**: Brandy restates action + target + exact cost; the founder says an explicit confirmation ("confirm", "yes, do it" / "confirmo", "sí, hazlo"). Anything else cancels. No button is required (a visual card may mirror it). |
| A-D2 | All steps, built in order **Script → Audiovisual → Catalog → Editing**. Plus: re-verify **Brand Soul** end to end (many changes landed); the right panel works the same in every step; Brand Soul keeps showing the redacted info while it is extracted; the **Brand Soul document** (20 credits) becomes long-form consolidated prose — **no JSON-looking format** (the CEO asked for this before and it never shipped). |
| A-D3 | Serial, except long generations (assets, render) that run in the background while you keep talking. **Brandy is scoped to the current step**: she knows exactly where you are and does not act outside it. |
| A-D4 | Brandy announces finished jobs in the next pause **if the API allows it** (investigate first; fallback: visual notice + Brandy mentions it in her next reply). |
| A-D5 | No autopilot in V1. The only clicks: mic, teleprompter recording, export. |
| A-D6 | Compact per-step state summary, **compartmentalised by step**. If the founder asks about another step, Brandy answers with status and what to do first ("First lock your script; you have 2 scenes left"). |
| A-D7 | Cost = voice minutes while the session is on (today 7.5 credits/min) + each pipeline action at its normal button price. No surcharge. |
| Toggle | **"Agentic mode"** switch, with a warning: `Agentic mode lets Brandy run the pipeline for you. Voice time uses credits faster.` Off = today's behaviour (Brandy only interviews for the Brand Soul; the pipeline works with buttons). |
| Panel | The right panel ("Production") becomes the **audit trail and queue** for every action — voice *and* buttons: queued → running → done / failed, with cost and a link to the result. |

## In scope V1 (what Brandy can do, per step)
| Step | Brandy can | Needs confirmation |
|---|---|---|
| Global | Say where you are, what is done/missing, what is next, your balance; move you to an **unlocked** step | No |
| Brand Soul | Today's interview; generate/regenerate the Brand Soul document (20) | Yes (generate) |
| Catalog | Research demand, generate/regenerate ideas, add your idea, accept/discard, explain demand, lock | Yes for anything that charges, discards or locks |
| Script | Generate (6), explain the audit, phase-by-phase mode, iterate one scene with your instruction (2), edit dictated text (free), lock | Yes for generate, iterate, lock |
| Audiovisual | Walk scene by scene, change a scene type (free), estimate, generate assets (exact total), regenerate one asset **with your instruction**, open the recording studio for a scene | Yes for generate/regenerate |
| Editing | (after E.2) build raw, auto-edit + style, face/B-roll, mute music/SFX, fix a caption, caption position, delete/edit overlay, render, post copy, share link | Yes for render and anything paid |

## Out of scope V1
Autopilot; Brandy recording or starting the camera; paid/destructive actions without
voice confirmation; a separate voice backend; languages other than English/Spanish;
multi-user teams; any price change; Editing by voice before E.2 closes.

## Data
New table `agent_actions` (migration 014 — the CEO approves before it is applied):
`id, session_token, idea_id, step, source ('voice'|'button'), action, args jsonb,
utterance, restatement, confirmation, confirmed_at, credits, status
('proposed'|'queued'|'running'|'done'|'failed'|'cancelled'), result_ref, error, created_at,
updated_at`. RLS: founders read their own rows; only the backend (service role) writes.

## Success criteria (the CEO's test plan checks these)
1. Entering each step with Agentic mode on, Brandy says where you are and what is next.
2. "Iterate the hook to be more direct" → Brandy restates + "2 credits" → "confirm" → the
   scene changes on screen and a card appears in the panel.
3. Saying "confirm" when nothing was proposed does nothing.
4. A wrong transcription ("scene 13") produces a restatement you can correct before paying.
5. "Generate the assets" → exact total → confirm → you keep talking while they generate →
   notice when ready (spoken if A-D4 is feasible).
6. Balance and results identical to doing it with buttons.
7. Every action (voice and button) is in the panel with phrase, confirmation and cost.
8. Asking about another step gets status + "first do X", and no action outside the step.
9. Agentic mode off = today's product; the warning shows when turning it on.
10. Brand Soul: interview → redacted live info → document in long-form prose, no JSON look.
