# H8-02 evidence (literal output, no verdicts)

- `pytest_h8_02.txt` — `python -m pytest tests/test_h8_02_soul_regenerate.py -v -p no:cacheprovider`
- `pytest_full.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (full suite, run inside a git worktree)
- `pytest_full_summary.txt` — the FAILED lines and the final count from `pytest_full.txt`
- `ruff.txt` — `ruff check app/main.py app/tools/brand_soul/generator.py tests/test_h8_02_soul_regenerate.py`
- `git_status.txt` — `git status --short` before staging

Note: the `FAILED` lines in `pytest_full.txt` (test_guard_jwt x2, test_fonts_and_sources_hashes, and
test_render_service_e2_02_seek x2) were not touched by this piece. `test_render_service_e2_02_seek.py`
was re-run alone on a clean `origin/main` worktree: `stat-fields0` failed there too, `list-fields2` passed.

Note on `ruff.txt`: the 13 findings are all in `app/main.py` outside `generate_brand_soul_handler`
(lines 20, 272, 524-627, 1049, 2965). They are present on `origin/main` and were left untouched
because the piece limits `app/main.py` to the soul handler and its request model.
