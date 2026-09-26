# F-05 — Agentic mode toggle + step-scoped Brandy + English voice states

Depends on: F-04
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
The toggle, the warning, and Brandy's per-step context and tools (A-D3, A-D6, toggle row).

## Files you may touch
- `app/static/agent.js` (new): `buildStepSummary()`, `toolsForStep(step)`, `sendSessionUpdate()`
- `app/static/app.js`: the toggle in the voice panel header, calling `agent.js` from the
  existing `session.update` (~L602) and on every step change; English orb states (today
  `'Conectando agente...'` ~L554, `'Escuchando...'` ~L719/780/1422, `'Hablando...'` ~L725,
  `'Pensando...'` ~L734, `'Brandy hablando...'` ~L748, `'Conectando...'` ~L1425 ->
  `Connecting…`, `Listening…`, `Speaking…`, `Thinking…`, `Brandy is speaking…`)
- `tests/test_agent_f05.py` + `tests/agent_step.test.js`

## Behaviour
- Switch `Agentic mode` (default **on** per the original spec; persisted in `localStorage`
  with try/catch). Turning it on shows once per session:
  `Agentic mode lets Brandy run the pipeline for you. Voice time uses credits faster.`
- Off: exactly today's tools and prompt (Brand Soul interview only).
- On: on every step change send `session.update` with the Brand Soul prompt extended by a
  step block: `You are in STEP: <step>. Summary: <≤1200 chars>. Only use the tools listed.
  If asked about another step, give its status and what must happen first; never act on it.`
  Tools = global (`get_status`, `get_balance`, `go_to_step` [unlocked only]) + step tools
  from the registry + `propose_action` / `confirm_action` (implemented in F-06; until then
  they return `{status:"not_available"}`).
- Brandy may speak the founder's language; every UI string is English.

## Done when
Node test: step change -> one `session.update` with the right tool names; off -> legacy
payload byte-identical to today's; `go_to_step` to a locked step refused. Evidence in
`docs/specs/evidence/F-05/`.
