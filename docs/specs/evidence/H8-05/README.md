# H8-05 evidence (literal outputs)

- `pytest_full.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (run inside a git worktree)
- `pytest_h8_05.txt` — `python -m pytest -v tests/test_h8_05_editing_ui.py -p no:cacheprovider`
- `ruff.txt` — `ruff check tests/test_h8_05_editing_ui.py`
- `node_check.txt` — `node --check app/static/editing.js`

No `.py` file other than the new test was touched.
