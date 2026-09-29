# H8-03 — A new render engine rebuilds the raw cut

Depends on: — (main @ ad93652)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P0 · Branch: `agent/H8-03`

## Goal
The raw cut bakes motion graphics in. Its freshness/idempotency ignores the engine version, so an idea whose
raw was built before E2-02 (idea_982f17b9, raw job 2026-09-26 02:53 UTC) keeps the blank motion graphic
forever; "Rebuild raw cut" reuses the old job (P93 reuse) because the content is identical.

## Files you may touch   (Scope Whitelist)
- `app/editing/router.py` (`POST /{idea_id}/raw` idempotency/reuse and the `raw.fresh` computation in `_state`)
- `app/editing/timeline.py` (only if the raw content hash helper is the right place)
- `tests/test_h8_03_raw_engine.py` (new)

## Shared semantics
Engine version = `await get_engine_version()` (same helper the render key uses). The raw's stored
`timeline_hash` gains the engine: store `engine_version` in `raw_render`; `raw.fresh` requires same content
**and** same engine (unknown engine never makes a raw stale). The dressing freshness (`cut_hash`) does NOT
change: a raw rebuild never discards the paid auto-edit.

## Behaviour
Raw built with engine A, service now on engine B → state shows the raw as not fresh, the UI's existing
auto-rebuild/"Rebuild raw cut" creates a new raw job (free), and the reuse path only reuses a done raw with
the same content and engine.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (main is green at ad93652)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # only whitelist files changed
```
Plus tests: same content + same engine → reused; same content + new engine → new job; engine "unknown" →
reused (never forces rebuilds on a /health hiccup); dressing stays fresh across the rebuild.

## Evidence  (`docs/specs/evidence/H8-03/`) — pytest output, README.
