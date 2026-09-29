# H8-06 evidence (literal output, no verdicts)

- `pytest_full.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (full suite). Final line: `4 failed, 1316 passed, 15 skipped, 2 deselected`, `exit=1`.
  Failures listed: `test_guard_jwt.py` x2 and `test_fonts_and_sources_hashes` (named in docs/specs/H8/README.md as worktree-only),
  plus `test_render_service_e2_02_seek.py::test_template_seek_render_non_blank[stat-fields0]` (`assert 70.8 < 60.0` wall-clock).
  Re-running that seek file alone gave the same single failure (`1 failed, 4 passed`, wall 70.8s).
- `ruff.txt` — `ruff check app/main.py tests/test_h8_06_refunds.py`: 13 errors, all in `app/main.py` outside the touched handlers; `origin/main:app/main.py` reports the same count (13).
- New tests `tests/test_h8_06_refunds.py`: 6 pass with the change; 3 of them fail against the unmodified `app/main.py`.
