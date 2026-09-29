# H8-03 evidence (literal output, no verdicts)

- `pytest_full.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (tail), run in a git worktree on this branch.
- `pytest_h8_03.txt` — `pytest -v tests/test_h8_03_raw_engine.py`.
- `ruff.txt` — `ruff check app/editing/router.py tests/test_h8_03_raw_engine.py`.
- `git_status.txt` — `git status --short` before commit.
- No .js touched, so no `node --check`.
- Baseline note: on unmodified origin/main (same worktree, same machine) `tests/test_render_service_e2_02_seek.py`
  also produced `1 failed, 4 passed` (`stat-fields0`).
