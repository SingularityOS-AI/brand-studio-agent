# E2-07 — No-collision layout in the IR

Depends on: E2-06
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F2 (E2-D2). Overlays sometimes sit on top of captions (CEO video 0:08).

## Files you may touch
- `app/editing/ir.py` (overlay placement, `POSITION_BOXES` ~L384, caption filtering)
- `render_service/manifest.py` (OverlayCue optional `hide_captions: bool = False`)
- `tests/test_editing_e2_07_collision.py` (new)

## Behaviour (plan §2 zones)
Caption box from `caption_y`, style font size and max lines. Each overlay keeps its zone if
it does not intersect the caption box; else moves to the nearest free zone (TOP, MIDDLE,
BOTTOM) keeping x/w/h; if none, `hide_captions=true` and caption events overlapping
`[start_ms, end_ms]` are dropped (split at the boundary). Deterministic.

## Done when
Property test: 200 random IRs -> no overlay box intersects a caption box active at the same
time. Offline E2E frame at an overlay midpoint shows both, apart. Evidence in
`docs/specs/evidence/E2-07/`.
