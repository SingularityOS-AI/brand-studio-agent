# F-07 — Script tools

Depends on: F-06
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
Brandy operates Script by voice (A-D2 order: first).

## Files you may touch
- `app/static/agent.js` (Script tool schemas + mapping to registry actions)
- `app/static/actions.js` (fill gaps in Script actions from F-04, incl. **phase-by-phase mode**:
  a free read tool `script_phase_review({phase})` returning that phase's text + failing audit
  rules so Brandy proposes one improvement per phase: hook -> lock-in -> point 1 -> rehook ->
  point 2 -> CTA; applying it is `iterate_scene` with the instruction, 2 credits, confirmed)
- `tests/agent_script.test.js`, `tests/test_agent_f07.py`

## Tools
`script_generate` (confirm, 6) · `script_explain_audit` (free) · `script_phase_review` (free) ·
`script_iterate_scene {scene_n, instruction}` (confirm, 2) · `script_edit_text {scene_n, text}`
(free; restate the new text before saving) · `script_lock` (confirm, 0).

## Done when
Harness: each tool hits the same endpoint/body as its button; paid ones require the
confirmation flow; unknown scene -> `{status:"invalid", say:"There is no scene 13; your
script has 6 scenes."}`. Evidence in `docs/specs/evidence/F-07/`.
