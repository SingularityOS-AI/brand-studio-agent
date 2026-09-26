# E2-09 — Caption band drag + presets (UI)

Depends on: E2-06, E2-08
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F1 UI. Drag the caption band in the preview; presets Top (520) · Middle (1080) · Bottom (1600).

## Files you may touch
- `app/static/editing.js`, `app/static/editing_preview.js`
- `tests/test_editing_e2_09_caption_drag.py` (new)

## Behaviour
Pointer drag (mouse + touch) on the band inside the 9:16 preview; screen px -> canvas px via
the preview scale; live update while dragging; on release one
`PATCH settings {op:"caption_y", value, expected_version}` (never one per move). Presets
= 3 small buttons under the player. Up/Down arrows move 20 px when the band is focused.
Free; never re-runs auto-edit.

## Done when
DOM test: simulated drag -> exactly one PATCH with the clamped value; presets send
520/1080/1600. Evidence in `docs/specs/evidence/E2-09/`.
