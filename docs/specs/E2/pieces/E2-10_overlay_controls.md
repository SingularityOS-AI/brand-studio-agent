# E2-10 — Overlay controls: delete / edit text / on-off

Depends on: E2-07, E2-08
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F3 (E2-D3). The founder cannot remove a card today.

## Files you may touch
- `app/editing/router.py` (`PATCH settings` ops `overlay_delete {id}`, `overlay_text {id, text<=80}`, `overlays_enabled {bool}`)
- `app/editing/ir.py` (apply `settings.overlays` and `overlays_enabled` in stage 2)
- `app/static/editing.js` (an "Overlays" list: text, time, Delete, Edit; a global switch)
- `tests/test_editing_e2_10_overlay_controls.py` (new)

## Behaviour
All free. Never modifies `edit.dressing` (the paid plan): overrides live in
`edit.settings.overlays` keyed by overlay id, applied on top. Text edits use the caption
sanitizer and the E2-04 fit. Switch off -> IR has 0 overlays and their `pop` SFX are dropped.

## Done when
Delete -> overlay absent from IR, dressing byte-identical; edit -> IR text changed; off/on
round-trip restores all. Evidence in `docs/specs/evidence/E2-10/`.
