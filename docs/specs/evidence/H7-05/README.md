# H7-05 evidence

Literal command output, no verdicts.

- `ls_files_check.txt` — tracked-file check for `.lnk`, `__pycache__`, `.pyc`, `.log`.
- `secret_scan.txt` — secret-pattern grep over README.md, CHANGELOG.md and .env.example (PR_SUMMARY.md is deleted in this PR).
- `env_vars_diff.txt` — env var names read via `os.getenv` / `os.environ.get` in `app/` and `render_service/`, compared with the names in `.env.example` (active or commented).
- `pytest_branch.txt`, `pytest_main.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` on this branch and on `origin/main` (1d27219), run in the same environment. Each file has the plain command and the same command with `--ignore=tests/test_agent_f11.py` (the plain command stops at a collection error in that file on both).
