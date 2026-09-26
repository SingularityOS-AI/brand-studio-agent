# E2-05 — Engine version in the render key + render pricing (P1)

Depends on: —
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
Bug B3 + pricing P1. `POST /api/editing/{idea_id}/render` (`app/editing/router.py` ~L657)
keys on IR + raw path only, so after an engine fix the founder gets the old MP4.
Pricing (Capitán proposal, CEO confirms in the test plan): first final render of an idea 20,
later renders 5, a re-render whose only change is the engine = free.

## Files you may touch
- `render_service/version.py` (new, `ENGINE_VERSION = "2026.09.26-1"`), `render_service/app.py` (`/health` returns it)
- `app/editing/config.py` (`RERENDER_CREDITS=5`), `app/editing/dispatch.py` (cached `/health` read, 5 min TTL, `"unknown"` on failure)
- `app/editing/router.py` (render endpoint + `render_price` in the state)
- `app/static/editing.js` (label from state: `Render · 20 credits` / `Render again · 5 credits` / `Render again · free (engine updated)`)
- `tests/test_editing_e2_05_pricing.py` (new)

## Behaviour
- Key = sha256(IR canonical + raw path + engine_version)[:20] + the existing failed-count suffix.
- Price: no previous **done** render for this idea -> `RENDER_CREDITS`; previous done render
  with same IR+raw and different engine_version -> 0; otherwise `RERENDER_CREDITS`.
- Write-ahead charge / refund-on-failure paths untouched. UI never hard-codes 20.

## Done when
Tests cover the 3 prices, double-click idempotency and refund on failure; evidence = pytest
output in `docs/specs/evidence/E2-05/`.
