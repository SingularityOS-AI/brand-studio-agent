# E2-11 — Auto-edit styles Clean / Standard / Bold + free restyles

Depends on: E2-08
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F4 (E2-D4). Density presets for Brandy's auto-edit.

## Files you may touch
- `app/editing/catalog/catalog_v1.json` (add `styles` with per-style limits)
- `app/editing/dressing.py` (`dress_all` / `fallback_dressing` take `style`; the Gemini prompt names the style)
- `app/editing/router.py` (`POST /dress {style}`; `free_restyles_used` per raw cut, 3 free; the 4th -> 409 `restyle_limit`, no charge; UI suggests per-scene "Try another take")
- `app/static/editing.js` (segmented control Clean · Standard · Bold next to Auto-edit)
- `tests/test_editing_e2_11_styles.py` (new)

## Limits
| style | zooms/scene | overlays | transitions |
|---|---|---|---|
| clean | 1 | 1 every 2 scenes | cut, flash |
| standard | today's catalog limits | today | today |
| bold | 3 | 2 per scene | all |

## Done when
Fallback dressing on the same contexts: clean < standard < bold in zoom and overlay counts;
3 restyles free, 4th -> 409, credits untouched. Evidence in `docs/specs/evidence/E2-11/`.
