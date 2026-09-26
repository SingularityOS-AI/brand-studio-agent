# F-02 evidence

- `pytest_f02_and_regression_check.txt`: `pytest -q tests/test_agent_f02_audit.py
  tests/test_audiovisual_p50.py::test_endpoints_409_422_200` -- the piece's own
  new tests plus the specific regression check named in the task (must not break
  after the CRITICAL bug in a previous attempt). 15 passed.
- `pytest_full_suite.txt`: `pytest -q tests/` on this branch. 821 passed, 6 failed,
  1 error, 28 skipped.
- `pytest_full_suite_baseline_main.txt`: same command on `main` (git stash -u),
  i.e. with none of this piece's files present. 807 passed, same 6 failed/1
  error. The delta is exactly the 14 new tests in test_agent_f02_audit.py; the
  failures/error are pre-existing and unrelated to F-02 (network-lock /
  event-loop / external-tool tests that already fail on main).
- `ruff_new_files.txt`: `ruff check` on every new file this piece adds
  (app/agent/__init__.py, store.py, router.py, middleware.py,
  tests/test_agent_f02_audit.py). 2 findings, both BLE001 (blind
  `except Exception:`) in client/auth fallback code -- the same pattern
  already used by app/editing/store.py's `_get_edits_client` and
  app/guard.py, uncommented elsewhere in this codebase.
- `ruff_main_py_full.txt`: `ruff check app/main.py` after this piece's 4-line
  change (2 imports + include_router + add_middleware).
- `ruff_main_py_baseline_before_change.txt`: the same command on `main`
  before this piece's change. Both report 66 errors -- this piece adds zero
  new ruff findings to app/main.py; the pre-existing 66 are out of scope
  (the piece says "app/main.py: include the router + add the middleware;
  nothing else").
