# E2-08 — Editing UX: 3 steps, English, Auto-edit, loading screen

Depends on: E2-05
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F7 + F8. The CEO did not understand "Vestir". Editing reads **1 Cut · 2 Auto-edit · 3 Export**,
fully in English, with the same loading pattern as the other steps.

## Files you may touch
- `app/static/editing.js` (and `app/static/index.html` only if a CSS class is missing)
- `tests/test_editing_e2_08_ux.py` (new; static + Node DOM like `tests/test_editing_p82c_editing_js.py`)

## Behaviour
- Stepper: `1 Cut` · `2 Auto-edit` · `3 Export`, active step highlighted.
- Labels: `Vestir todo · free` -> `Auto-edit · free`; `Your cut changed — dress again · free`
  -> `Your cut changed — auto-edit again · free`; `Otra versión · 2 credits` ->
  `Try another take on this scene · 2 credits`; `Dressed ✓` -> `Auto-edited ✓`.
  Zero visible strings matching `[áéíóúñ¿¡]` or "Vestir"/"dress" (identifiers may stay).
- Loading: while the first `GET /api/editing/{idea}` is in flight show the loading component
  the other steps use (`.doc-loading-content` + `.doc-loading-spinner`, see
  `#Doc-LoadingIndicator` in `index.html`) with `Loading your edit…`.
- Render label from `state.render_price` (E2-05).

## Done when
Static test: no Spanish in visible strings; DOM test shows stepper + loading state; evidence
in `docs/specs/evidence/E2-08/`.
