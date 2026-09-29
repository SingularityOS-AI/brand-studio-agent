# H8-02 — Brand Soul: Regenerate really regenerates, and failures refund

Depends on: — (main @ ad93652)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P0 · Branch: `agent/H8-02`

## Goal
`POST /api/soul/generate` (`app/main.py` ~L333-429) receives `regenerate: true` from the Regenerate button
(`app/static/app.js` ~L2171) but never uses it: it deducts 20 credits (~L378) and calls
`generate_brand_soul(session_token)` (~L400), which returns the cached HTML when the brain hash is unchanged
(`generator.py` `_check_cache`). Result: the founder pays 20 for the same old document (in production the
CEO's doc is still the pre-F-01 Spanish layout). Also every error path after the deduction (400/500 at
~L401-422) returns without refunding.

## Files you may touch   (Scope Whitelist)
- `app/main.py` (only `generate_brand_soul_handler` and its request model)
- `app/tools/brand_soul/generator.py` (`generate_brand_soul` signature: `force: bool = False` skips `_check_cache`)
- `tests/test_h8_02_soul_regenerate.py` (new)

## Behaviour
- `regenerate=true` → `generate_brand_soul(session_token, force=True)`: fresh generation, cache overwritten.
- `regenerate=false` and a valid cache hit → return the cached doc **without charging** (`cache_status:"cached"`, credits unchanged).
- A fresh generation charges 20 exactly once. If generation raises (any exception), refund the 20 with the
  existing `guard.refund_credits(session_token, 20, source="refund:soul:<ts>")` pattern before returning the error.
- Response always includes `credits_remaining`.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (main is green at ad93652)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # only whitelist files changed
```
Plus tests (LLM mocked): regenerate → generator called with force and 20 charged; cache hit without
regenerate → 0 charged; generator raises → balance back to the start value.

## Evidence  (`docs/specs/evidence/H8-02/`) — pytest output, README.
