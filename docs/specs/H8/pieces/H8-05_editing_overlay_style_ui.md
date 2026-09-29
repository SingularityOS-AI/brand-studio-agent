# H8-05 — Editing UI for overlays (E2-10) and styles (E2-11)

Depends on: — (main @ ad93652)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P1 · Branch: `agent/H8-05`

## Goal
E2-10 and E2-11 merged backend-only (commits 3c63d88, 95532b5 touched no `editing.js`). The backend ops
exist (`PATCH settings` ops `overlay_delete`, `overlay_text`, `overlays_enabled`; `POST /dress {style}` with
3 free restyles and 409 `restyle_limit`, already handled at `editing.js` ~L225) and the voice tools call them,
but a founder using buttons has no controls, and the timeline has no Overlays track.

## Files you may touch   (Scope Whitelist)
- `app/static/editing.js`
- `tests/test_h8_05_editing_ui.py` (new; static + Node DOM like `tests/test_editing_p82c_editing_js.py`)

## Behaviour (English UI, DOM built without innerHTML for data)
- Next to "Auto-edit": segmented control **Clean · Standard · Bold** (current = `state.dressing.style` or
  Standard). Choosing a style calls the existing dress action with `{style}`; show "Restyles left: N".
- New card **"Overlays"** under Sound & Effects: a switch "Show overlays" (op `overlays_enabled`) and one
  row per `state.ir.overlays` item: time range, text (inline edit → op `overlay_text`, ≤80 chars), Delete
  (op `overlay_delete`). Free, never re-runs auto-edit.
- Timeline gets an **Overlays** track row (same style as Captions/Zoom/Transitions/SFX).

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (main is green at ad93652)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # only whitelist files changed
```
Plus DOM tests: style click sends `{style}`; delete/edit/switch send the right ops with `expected_version`;
Overlays track rendered with N marks for N overlays.

## Evidence  (`docs/specs/evidence/H8-05/`) — pytest + node outputs, README.
