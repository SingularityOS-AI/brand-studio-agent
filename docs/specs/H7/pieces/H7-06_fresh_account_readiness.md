# H7-06 — Proof a brand-new account can run the whole lap (report only)

Depends on: —
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P0 · Branch: `agent/H7-06`

## Goal
Finding #11. Tomorrow the CEO runs the full pipeline from a brand-new account in production. Prove,
before that, that nothing depends on seeded/demo data and that the starting credits cover a lap.
**Report piece: no product code changes.** If you find a blocker, describe it; the Capitán writes the fix piece.

## Files you may touch   (Scope Whitelist)
- `tests/test_h7_06_fresh_user.py` (new)
- `docs/specs/evidence/H7-06/*` (the report)

## Behaviour
1. Seed/demo independence: grep `app/` for hard-coded session tokens, founder ids (`founder-001`, emails),
   `seed`, `demo`, `fixture`, sample idea ids, and paths into `tests/` or `cache/`. List every hit with file:line and whether a new user hits it.
2. Fresh-session walk (TestClient, all external APIs mocked, network locked by `tests/conftest.py`): new
   session → `/api/session` credits = `initial_session_credits` → brain extract → soul generate → catalog
   generate → script generate → audiovisual estimate → editing state. Record status codes and credits after each step.
3. Cost of one full lap from code constants (Brand Soul, catalog research + ideas, script, typical assets for
   a 6-scene script with 2 B-roll + 1 motion graphic, render 20, one re-render 5) + voice at 7.5 credits/min for
   15 and 30 minutes. Compare with `initial_session_credits` (today 500). Flag if a lap cannot finish.

## Out of scope
Changing prices, credits or any file under `app/`, `render_service/`, `app/static/`.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (after H7-02 merges; before that: no NEW failures vs main)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # must show ONLY files from your whitelist
```
Plus the report `docs/specs/evidence/H7-06/REPORT.md` has the 3 sections with numbers and file:line references.

## Evidence   (`docs/specs/evidence/H7-06/`)
`REPORT.md`, `pytest_output.txt`.
