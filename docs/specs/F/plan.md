# Block F — plan (Agentic Mode)

Spec: `docs/specs/F/spec.md`. Rules: `AGENTS.md`. Deadline 2026-09-30 11:00 VET.

## 1. Architecture decision — **signed by the CEO 2026-09-26: A**

**A — Browser-side agent over one Action Registry (recommended).** Brandy's WebSocket
stays in the browser (today: `wss://agents.assemblyai.com/v1/ws`, `app/static/app.js`
~L526; `session.update` ~L602; `tool.call` handler ~L770/`handleToolCall` ~L929;
`tool.result` ~L975). A new `app/static/actions.js` registry wraps **the same functions the
buttons call**. On each step change the browser re-sends `session.update` with that step's
tools + a compact state summary. Paid actions go through a **confirmation engine enforced
in code** (below). Every pipeline request carries an `X-Agent-Action-Id` header; a backend
middleware writes the audit trail for voice *and* button requests.

**B — Server-side agent proxy.** The backend holds the AssemblyAI socket and executes
tools itself; the browser only streams audio. Harder to tamper with, but it is a rewrite
of the voice path 4 days before the deadline, and it breaks principle 2 (the server would
need its own copies of the frontend flows).

## 1b. Reference pattern (from the CEO's DeepSeek harness, adapted)
Every tool call Brandy makes goes through one pipeline inside `actions.js`, in this order:
1. **log** `tool.call` (panel shows a *pending* card);
2. **pre-execute guards**: step scope, argument validation, unknown ids → deny with a `say`;
3. **approval**: the confirmation engine (paid/destructive only) — denied/absent skips the body;
4. **execute** the button's function with a timeout (30 s; long jobs return `queued`);
5. **post-execute**: turn the raw result into a short, factual `say` for Brandy (never raw JSON);
6. **result**: frozen `tool.result` back to Brandy + the `agent_actions` row updated.
The `agent_actions` table is the append-only session log that lets anyone replay what happened.

## 2. Shared semantics
- **Action**: `{id, step, title, cost(args) -> credits|Promise, needsConfirm, run(args)}`.
  `run` calls the existing function (e.g. the Script "iterate scene" handler), never a new
  endpoint. Variable costs use the existing free estimate endpoints.
- **Confirmation engine (A-D1), code-enforced:**
  1. Brandy calls `propose_action({action, args})`. The registry validates args (scene
     exists, step matches), computes the cost and a restatement
     (`Iterate scene 3 (the hook) to be more direct — 2 credits. Say "confirm" to go ahead.`),
     stores one pending proposal (token, 45 s TTL, replaces any previous one), and returns
     it in `tool.result`. Brandy reads it out.
  2. Brandy calls `confirm_action({token})` only after the founder confirms. The engine
     executes **only if** the token matches the pending proposal **and** the founder's last
     final transcript (the `transcript.user` / final user-turn event — find the exact event
     name in `app.js`) is an explicit confirmation: ≤ 6 words, contains one of `confirm,
     confirmed, yes do it, go ahead, do it, confirmo, sí hazlo, hazlo, dale, adelante`, and
     none of `no, don't, wait, cancel, stop, espera, cancela, para`. Otherwise
     `{status:"not_confirmed"}` and the proposal is dropped.
  3. Free + reversible actions (`needsConfirm=false`) run directly via `run_action`.
- **Step scoping (A-D3/A-D6):** tools registered = global tools (`get_status`,
  `go_to_step` for unlocked steps only, `get_balance`) + the current step's tools. A tool
  call for another step returns `{status:"wrong_step", say:"..."}`.
- **State summary** (sent in the prompt on every step change, ≤ 1,200 chars): step,
  idea title, done/missing, next action, balance, step specifics (failing script rules,
  scenes without assets, raw/render status).
- **Audit trail:** middleware on `/api/catalog/*`, `/api/script/*`, `/api/audiovisual/*`,
  `/api/editing/*` (not `/internal/*`), `/api/soul/generate`: for every POST/PATCH/DELETE,
  upsert an `agent_actions` row (source = `voice` if the header maps to a voice action,
  else `button`), status from the response (2xx → done or queued if 202, else failed),
  credits = difference reported by the endpoint when available.

## 3. Pieces (1 piece = 1 PR = 1 commit). Lane B = voice/pipeline files.
`app/static/app.js` is huge and shared: **only one Lane B piece touches it at a time**
(merge before starting the next). New logic goes in new files.

| ID | Title | Depends | Priority | Who |
|---|---|---|---|---|
| F-01 | Brand Soul health check + long-form prose document | — | P0 | Jules / Claude cloud |
| F-02 | `agent_actions` table (migration 014) + store + audit middleware + list API | — | P0 | Jules / Claude cloud |
| F-03 | Right panel = audit trail/queue for every step | F-02 | P0 | Antigravity |
| F-04 | Action Registry + `X-Agent-Action-Id` fetch context | F-02 | P0 | Antigravity |
| F-05 | Agentic mode toggle + step-scoped Brandy (tools + state summary) + English voice states | F-04 | P0 | Antigravity |
| F-06 | Confirmation engine (propose / confirm) | F-05 | P0 | Jules / Claude cloud (pure JS module + Node tests) then Antigravity wires it |
| F-07 | Script tools | F-06 | P0 | Antigravity |
| F-08 | Audiovisual tools (incl. regenerate one asset with instruction) | F-07 | P0 | Antigravity |
| F-09 | Catalog + Brand Soul tools | F-08 | P1 | Antigravity |
| F-10 | Proactive "job finished" announcement (spike, then build if feasible) | F-05 | P1 | Claude cloud (spike) |
| F-11 | Editing tools | F-08, E2 P0 closed | P1 | Antigravity |

**Cut line:** 2026-09-29 12:00 VET — anything not merged by then (except fixes) is out of
the hackathon build. Order of sacrifice: F-11 → F-10 → F-09.

## 4. Deploy
Migration 014 is applied by the CEO (Supabase) before F-02 merges. Everything else is
Render.com auto-deploy from `main`. Agents never deploy.

## 5. Verification that matters
Voice cannot be unit-tested end to end, so every tool piece ships a **Node harness**
(`tests/agent_harness.js`, created in F-06) that replays scripted `tool.call` and
transcript events against `actions.js` + the confirmation engine with `fetch` mocked, and
asserts the exact HTTP calls. The CEO's live test (PLAN_DE_PRUEBA_F) is the real gate.
