# F-08 — Audiovisual tools (incl. regenerate one asset with instruction)

Depends on: F-07
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
Brandy walks Audiovisual scene by scene. Also covers the CEO's B-roll note (E2-D7): "regenerate
the B-roll of scene 2 with someone using a phone".

## Files you may touch
- `app/static/agent.js`, `app/static/actions.js`
- Backend only if the regenerate endpoint cannot take an instruction today: then
  `app/audiovisual/*` minimal optional `instruction` param appended to the asset prompt /
  stock query (same price) + its test.
- `tests/agent_audiovisual.test.js`, `tests/test_agent_f08.py`

## Tools
`av_read_scene {scene_n}` (free) · `av_set_scene_type {scene_n, type}` (free, restate) ·
`av_estimate` (free) · `av_generate_all` (confirm, exact total from the estimate) ·
`av_regenerate_asset {scene_n, instruction?}` (confirm, its price) ·
`av_open_recording {scene_n}` (free; opens the studio - recording itself stays a click).

## Done when
Harness: generate_all restatement contains the exact estimate total; regenerate passes the
instruction; long jobs return immediately (`queued`) and the panel shows them. Evidence in
`docs/specs/evidence/F-08/`.
