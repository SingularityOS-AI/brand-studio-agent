# H8-01 — No-collision uses the real caption height

Depends on: — (main @ ad93652)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P0 · Branch: `agent/H8-01`

## Goal
E2-07 never moves an overlay. In production (idea_982f17b9, caption_y 1600 and 520) every overlay kept
its original y and `hide_captions` stayed false; the MP4 shows lower-third cards over the captions at
3.8 s, 16 s, 39.2 s. Cause: `app/editing/ir.py` ~L1214
`caption_y = timeline.get("settings", {}).get("caption_y", CAPTION_Y_DEFAULT)` — the timeline dict has no
`caption_y`, so collision math always uses 1250 while the renderers draw the band at the real value
(stage 1 reads it correctly from `settings` at ~L410).

## Files you may touch   (Scope Whitelist)
- `app/editing/ir.py` (stage 2: take caption_y from the `settings` argument / `ir_stage1["layout"]["caption_y"]`, clamped with `clamp_caption_y`; the same value feeds `_resolve_overlay_collisions` and `layout`)
- `tests/test_h8_01_collision_caption_y.py` (new)

## Behaviour
Stage 2 uses exactly the caption_y that stage 1 put in `layout`. Everything else in E2-07 unchanged.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (main is green at ad93652)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # only whitelist files changed
```
Plus: with settings caption_y = 1600 and a `lower_third` overlay (y 1300, h 200) overlapping a caption event,
the IR moves it to a free zone or sets `hide_captions` and drops the overlapped captions; same with
caption_y = 520 and a `top` overlay (y 260, h 300). Property test from E2-07 re-run with caption_y drawn
from {520, 1080, 1250, 1600}: zero intersections.

## Evidence  (`docs/specs/evidence/H8-01/`) — pytest output, README (no verdicts).
