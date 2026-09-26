# F-06 — Confirmation engine (propose / confirm), code-enforced

Depends on: F-05
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
Principle 3 / A-D1, exactly as `plan.md` §2 "Confirmation engine".

## Files you may touch
- `app/static/confirm_engine.js` (new, pure module, no DOM, exported for Node)
- `app/static/agent.js` (wire `propose_action`, `confirm_action`, `run_action` tool handlers
  and feed it the final user transcripts from the existing event handler)
- `app/static/app.js` only to forward final user transcript events to `agent.js`
- `tests/agent_harness.js` (new reusable harness), `tests/confirm_engine.test.js`, `tests/test_confirm_f06.py` (runs the Node tests)

## Behaviour
Pending proposal = one at a time, token (random), 45 s TTL, replaced by a new proposal,
dropped by any non-confirming final utterance. `confirm_action` executes only with matching
token AND explicit confirmation in the last final user utterance (word lists in plan §2,
case/accents-insensitive). Every outcome updates the `agent_actions` row (proposed ->
queued/cancelled) and returns a short `say` string for Brandy. A visual card mirrors the
pending proposal in the panel (no click needed).

## Done when
Harness cases pass: confirm happy path; "confirm" with nothing pending; "no, wait, confirm";
expired token; "scene 13" restatement then correction -> new proposal; double confirm runs
once; free action runs without confirmation. Evidence = Node output in
`docs/specs/evidence/F-06/`.
