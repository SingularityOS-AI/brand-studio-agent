# F-10 — Proactive 'job finished' announcement (spike, then build)

Depends on: F-05
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
A-D4: Brandy says "Your AI video for scene 5 is ready" in the next pause, if the AssemblyAI
Voice Agent API allows the client to trigger a reply without the founder speaking.

## Spike (write the answer first, in the PR)
Read the official AssemblyAI Voice Agent API docs for client events (e.g. a
`reply.create`-like event, injecting a system/assistant message, or a tool the agent polls).
Record the exact event and a doc link. If none exists: fallback = visual toast + the next
`tool.result`/prompt carries `pending_announcements` so Brandy mentions it in her next reply.

## Files you may touch
`app/static/agent.js`, `app/static/production_panel.js`, `tests/agent_announce.test.js`.

## Done when
Harness: a job moving to done while idle produces exactly one announcement (spoken event or
queued mention) and never interrupts the founder mid-utterance. Evidence (+ doc link) in
`docs/specs/evidence/F-10/`.
