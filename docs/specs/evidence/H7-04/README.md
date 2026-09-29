# H7-04 evidence (literal outputs, no verdicts)

- `pytest_output.txt` — the literal Done-when command. Stops at collection on `tests/test_agent_f11.py`
  (`No module named 'app.models'`, audit finding #3, owned by H7-02).
- `pytest_vs_main.txt` — same command with `--ignore=tests/test_agent_f11.py`, on this branch and on
  `origin/main` @ 1d27219 (clean worktree). Summary lines and FAILED/ERROR names for both runs.
- `node_check.txt` — `node --check` on `app/static/production_panel.js`, `ruff check` on `tests/test_h7_04_panel.py`.

DOM scenarios are in `tests/test_h7_04_panel.py`: before login, retry after login, thrown
`Not authenticated`, HTTP 401, HTTP 500, empty list, two actions.

Design note: "session ready" = `#Main-App` no longer `display:none` (app.js `showMainApp()` sets it after the
JWT exists). Until then `refresh()` makes no call and retries once per second (max 120 tries); app.js's existing
step-change `refresh()` calls also pass through the same gate. `app.js` is untouched.
