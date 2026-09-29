# H7-02 — Green `main`: kill the ghost test, update stale asserts, stop tests writing tracked files

Depends on: —
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P0 · Branch: `agent/H7-02`

## Goal
Findings #3-#6. `main` must be green on Windows and Linux, and running the suite must never
modify tracked files. **Tests only — no product code.**

## Files you may touch   (Scope Whitelist)
- `tests/test_agent_f11.py` (rewrite as a thin wrapper that runs `node tests/agent_editing.test.js`, like `tests/test_agent_f07.py`)
- `tests/agent_actions.test.js`, `tests/test_actions_f04.py` (assert the F-04 actions are a **subset** of the registry, not the exact set)
- `tests/test_editing_p82c_editing_js.py` (derive the expected action list from `EDIT_ACTIONS`; accept ops that `editing.js` maps client-side, e.g. `delete` → `overlay_delete` at L234; parse template-literal routes `/api/editing/${...}` correctly)
- `tests/test_editing_e2_04_card_fit.py` (`subprocess.run(..., encoding="utf-8")`)
- `tests/test_editing_e2_03_empty_scene.py`, `tests/test_editing_e2_04_card_fit.py`, `tests/test_editing_e2_06_caption_y.py`, `tests/test_editing_e2_09_caption_drag.py`, `tests/test_brand_soul_f01_prose.py`, `tests/test_render_e2e_offline.py`, `tests/conftest.py`: evidence files are written **only** when env `WRITE_EVIDENCE=1`, otherwise to `tmp_path`
- `.gitignore` (nothing else in it — H7-05 owns the rest; add nothing if not needed)

## Shared semantics
A test proves behaviour; it never rewrites `docs/specs/evidence/**`. Evidence is produced on purpose:
`WRITE_EVIDENCE=1 python -m pytest ...`.

## Out of scope
Any file under `app/` or `render_service/`. If a test can only pass by changing product code,
stop and write it in the PR as a question.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (after H7-02 merges; before that: no NEW failures vs main)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # must show ONLY files from your whitelist
```
Plus: after the full suite, `git status --short` is **empty** (no evidence churn). Failures that remain
only because H7-01 is not merged yet (p73, p75 converter, e2e offline, E2-03) are allowed and must be
listed in the PR; every other failure must be gone.

## Evidence   (`docs/specs/evidence/H7-02/`)
`pytest_output.txt`, `node_output.txt` (every `tests/*.test.js`), `git_status_after_suite.txt`, `README.md`.
