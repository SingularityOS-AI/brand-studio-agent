# F-02 evidence

**Review round 2 (ruff fix):** round 1 review found `app/agent/middleware.py:84`
and `app/agent/store.py:46` failing ruff with `BLE001` (blind `except Exception`).
Both are the piece's own required behaviour (an audit-write failure must never
break the wrapped endpoint), so each got a
`# noqa: BLE001 — audit trail must never break the endpoint` with the reasoning
kept as a comment, instead of narrowing the exception or removing the guard.
`ruff check` on the new files now reports `All checks passed!`. All evidence
below is post-fix.

- `ruff_new_files.txt`: `ruff --version` followed by `ruff check` on every new
  file this piece adds (app/agent/__init__.py, middleware.py, router.py,
  store.py, tests/test_agent_f02_audit.py). **All checks passed!** (ruff 0.16.9).
- `pytest_full_suite.txt`: `pytest -q tests/` on this branch. 821 passed, 6 failed,
  1 error, 28 skipped.
- `pytest_full_suite_baseline_main.txt`: same command on `main` (git stash -u),
  i.e. with none of this piece's files present. 807 passed, same 6 failed/1
  error. The delta is exactly the 14 new tests in test_agent_f02_audit.py; the
  failures/error are pre-existing and unrelated to F-02 (network-lock /
  event-loop / external-tool tests that already fail on main).
- `pytest_f02_and_regression_check.txt`: `pytest -q tests/test_agent_f02_audit.py
  tests/test_audiovisual_p50.py` -- the piece's own tests plus the *entire*
  audiovisual regression suite (round 2 review ran the whole file, not just
  the single test named in the original task). 27 passed.
- `ruff_main_py_full.txt`: `ruff check app/main.py` after this piece's 4-line
  change (2 imports + include_router + add_middleware).
- `ruff_main_py_baseline_before_change.txt`: the same command on `main`
  before this piece's change. Both report 66 errors -- this piece adds zero
  new ruff findings to app/main.py; the pre-existing 66 are out of scope
  (the piece says "app/main.py: include the router + add the middleware;
  nothing else").

## RLS policy (open question, not changed this round)

Round 2 review left the RLS decision to the CEO ("if you want the policy, add
it to the bounce") and the bounce prompt sent back only asked for the ruff
fix, with an explicit "do not change anything else". So `agent_actions` still
ships RLS-enabled-without-policies (matching `012_editing.sql`, `catalogs`,
`scripts`), as described in the PR body. If a `select` policy for
`auth.uid()` is wanted instead, that's a separate follow-up to migration 014
before the CEO applies it.
