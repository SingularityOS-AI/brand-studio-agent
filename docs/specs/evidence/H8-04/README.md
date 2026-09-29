# H8-04 evidence (literal outputs, no verdicts)

- `pytest_full.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (final run, after the app.js guard).
- `pytest_full_run1_before_app_js_guard.txt` — first full run, before `app.js` was guarded with `typeof document.dispatchEvent === 'function'` (it lists 7 failures).
- `pytest_h8_04_new_tests.txt` — `tests/test_h8_04_audit_async.py -v`.
- `lint_and_node_check.txt` — `ruff check` on touched .py, `node --check` on touched .js.
- `git_status.txt` — `git status --short` and `git diff --stat` before commit.

Notes: `test_guard_jwt.py` (2) and `test_fonts_and_sources_hashes` are the failures the H8 README documents as worktree-only. Cancelled jobs are not settled: `mark_cancelled` is in `app/audiovisual/jobs.py`, outside the whitelist.
