# H7-03 — The price on the Render button is the price charged

Depends on: H7-01 merged
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P0 · Branch: `agent/H7-03`

## Goal
Finding #7. The state computes the label with `get_cached_engine_version()` (no I/O, `"unknown"`
after each Render.com restart) while the charge uses `get_engine_version()` (live). They must agree.

## Files you may touch   (Scope Whitelist)
- `app/editing/router.py` (`_state` pricing block ~L298-316; `GET /{idea_id}` handler)
- `app/editing/dispatch.py` (`get_engine_version(timeout_s: float = 2.0)` parameter only)
- `app/static/editing.js` (show the label from `render_price` / `render_price_kind` exactly; no hard-coded numbers)
- `tests/test_h7_03_price_label.py` (new)

## Shared semantics
Pricing rule unchanged (CEO 2026-09-28): `first` = 20, `again` = 5, `engine_updated` = 0 only if the
previous done render recorded `engine_version` and `content_hash` and only the engine differs.
Labels: `Render · 20 credits` / `Render again · 5 credits` / `Render again · free (engine updated)`.

## Behaviour
- `GET /api/editing/{idea}` awaits `get_engine_version(timeout_s=2.0)` (5-min cache) before pricing; on
  timeout it uses the cached value and, if still unknown, reports `render_price_kind: "again"` (never free on unknown).
- State also exposes `engine_version` and `last_render_engine_version` (read-only info).
- For the same edit, the state's `render_price` equals what `POST /render` charges.

## Out of scope
Changing the pricing rule, the render key, or anything in `render_service/`.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (after H7-02 merges; before that: no NEW failures vs main)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # must show ONLY files from your whitelist
```
Plus a test matrix (mocks, no network): cold cache + engine changed → label 0 and charge 0; cold cache +
same engine → 5/5; no previous render → 20/20; `/health` timeout → label 5, charge 5 or 0 as the live read says,
never label 0 with charge 5.

## Evidence   (`docs/specs/evidence/H7-03/`)
`pytest_output.txt`, `ruff_output.txt`, `node_check.txt`, `README.md`.
