# F-01 evidence — Brand Soul long-form prose + health check

Files in this directory are literal command output, not a verdict.

- `pytest_full_suite.txt` — `python -m pytest -q tests/` (the full suite; the bare
  `python -m pytest -q` from the repo root also collects a stray root-level
  `test_frontend_auth.py` that fails to import `playwright` — reproduces identically
  on the unmodified tree before this piece's changes, unrelated to Brand Soul).
- `pytest_brand_soul_suite.txt` — `python -m pytest -q tests/test_soul.py
  tests/test_soul_credit_cost.py tests/test_soul_rate_limit.py tests/test_brain_hash.py
  tests/test_brand_soul_f01_prose.py`.
- `ruff_check.txt` — `ruff check` on every `.py` file this piece touched
  (`app/tools/brand_soul/generator.py`, `app/tools/brand_soul/template.py`,
  `tests/test_soul.py`, `tests/test_soul_credit_cost.py`,
  `tests/test_brand_soul_f01_prose.py`).
- `health_check.md` — the status-code table from walking `/api/brain/extract` ->
  `/api/soul` (404) -> `/api/soul/generate` (LLM mocked) -> `/api/soul` (200) ->
  `/api/soul/generate` again (regenerate), produced by
  `tests/test_brand_soul_f01_prose.py::test_health_check_brand_soul_path_end_to_end`.
- `extract_response.json` — the JSON body `/api/brain/extract` returned during that walk.
- `generated_sample.html` — the Brand Soul document `/api/soul/generate` returned
  during that walk (LLM mocked, deterministic fallback prose).

`pytest_full_suite.txt` (the `tests/` run) shows 6 failures and 1 collection error
outside `tests/test_soul*.py`, `tests/test_brain_hash.py`, and
`tests/test_brand_soul_f01_prose.py`
(`test_guard_jwt.py`, `test_network_lock.py`, `test_render_service_p75_container.py`,
`test_scripts_pieza43.py`, `test_render_service_p92_rebote.py`). Reproduced the same
way against the unmodified tree (`git stash` before running `pytest`) before writing
any code for this piece — same files, same failures.
