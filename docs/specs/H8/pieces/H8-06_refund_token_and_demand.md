# H8-06 — Refund the voice token and demand-validation charges when the upstream call fails

Depends on: — (main @ f926367)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P1 money · Branch: `agent/H8-06`

## Goal
Two endpoints charge before calling an external service and keep the credits when that call fails
(found by the pipeline bug hunt on 2026-09-29, verified by the Capitán):
- `GET /api/agent-token` (`app/main.py` ~L125-180): `guard.deduct_credits(session_token, amount=1)` (~L133),
  then mints an AssemblyAI token; a non-200 (~L164-169), `httpx.RequestError` (~L175) or any exception (~L177)
  raises without refund. The frontend calls it every time the founder presses the microphone (`app/static/app.js:55`).
- `POST /api/catalog/validate-demand` (~L515-550): deducts 10 (~L527); the `except Exception` path (~L543-548)
  returns 500 without refund.
Also two founder-visible Spanish error strings at ~L2418 and ~L2421 ("Body debe ser JSON válido",
"Body debe ser un objeto JSON").

## Files you may touch   (Scope Whitelist)
- `app/main.py` — ONLY the `/api/agent-token` handler, the `/api/catalog/validate-demand` handler, and the two
  strings at ~L2418/L2421. Another PR (H8-02) edits `generate_brand_soul_handler` in the same file: do not touch it.
- `tests/test_h8_06_refunds.py` (new)

## Behaviour
- On any failure after the deduction, refund the same amount with the existing pattern
  `guard.refund_credits(session_token, <amount>, source="refund:<endpoint>:<unix_ts>")`, wrapped so a refund
  failure is logged and never masks the original error; then return/raise the original error unchanged.
- Success paths unchanged (same status codes, same body, `credits_remaining` still the post-charge value).
- Strings become `"Body must be valid JSON"` and `"Body must be a JSON object"`.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures
ruff check app/main.py tests/test_h8_06_refunds.py
git status --short                                      # only whitelist files changed
```
Plus tests (network mocked): AssemblyAI returns 500 → balance back to start; `httpx.RequestError` → balance back;
validate-demand raises → balance back; success → charged exactly once.

## Evidence  (`docs/specs/evidence/H8-06/`) — pytest output, README (no verdicts).
