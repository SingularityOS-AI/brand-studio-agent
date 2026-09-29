# H7-04 — Right panel: no auth errors before login, friendly empty/unavailable states

Depends on: —
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P1 · Branch: `agent/H7-04`

## Goal
Finding #8. On first load the panel fetches `/api/agent/actions` before the Supabase session exists
and logs `Error: Not authenticated`. When the audit table is missing (migration 014 not applied) the
panel must say so calmly instead of failing silently.

## Files you may touch   (Scope Whitelist)
- `app/static/production_panel.js`
- `tests/test_h7_04_panel.py` (new; Node DOM like `tests/test_panel_f03.py`)

## Behaviour
- `refresh()` does nothing until `window.BrandStudio.authenticatedFetch` can run (session ready); it
  retries once auth is ready (listen to the existing auth/step hooks; no new globals in `app.js`).
- A thrown `Not authenticated` is swallowed (no console warning). A non-OK response shows
  `Activity log unavailable right now.`; an empty list shows the existing English empty state.
- No `innerHTML` with data (keep F-03's rule).

## Out of scope
`app.js`, the backend, the `hyperframes-player` "zero-size" console warning (cosmetic, preview-only).

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (after H7-02 merges; before that: no NEW failures vs main)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # must show ONLY files from your whitelist
```
Plus DOM tests: before auth → zero fetch calls and zero console warnings; 401/500 → the unavailable line;
[] → empty state; 2 actions → 2 cards.
Reviewer (local session) opens the branch in a browser with Claude in Chrome: console shows no
`[ProductionPanel] Failed` line on load.

## Evidence   (`docs/specs/evidence/H7-04/`)
`pytest_output.txt`, `node_check.txt`, `README.md`.
