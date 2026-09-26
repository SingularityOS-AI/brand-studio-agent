# E2-06 — One caption style + `caption_y` in the IR and both renderers

Depends on: E2-01
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F6 + data half of F1. One Brand Soul caption style for the whole video (today the first
1.5 s after frame zero produce `size:"hero"` giant words, `app/editing/ir.py` ~L92-110).
The caption band height becomes a setting the IR carries.

## Files you may touch
- `render_service/manifest.py` (RenderIR optional `layout: {caption_y: int = 1250}`, 360-1700)
- `render_service/ffmpeg_dress.py` (`write_ass`: caption events `\an2\pos(540,caption_y)`)
- `app/editing/ir.py` (stop producing `hero`; read `settings.caption_y`)
- `app/editing/router.py` (`PATCH settings` op `caption_y`, clamped 360-1700; never touches the dressing)
- `app/static/editing_preview.js` (band `top = caption_y`, `translateY(-100%)`)
- `tests/test_editing_e2_06_caption_y.py` (new); update existing tests only where they assert the removed `hero` behaviour.

## Done when
- IR for any script has 0 `hero` events.
- Offline E2E with `caption_y=520` and `1600`: caption text bottom edge in the MP4 frame
  within +-20 px of the value (scan rows for caption colour); the preview's `top` equals the
  value (Node test on `stateAt`). Evidence in `docs/specs/evidence/E2-06/`.
