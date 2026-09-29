# H7-03 evidence

Literal command output; no verdicts.

- `pytest_output.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider --continue-on-collection-errors` on this branch (this sandbox has 10 collection errors and 19 failures unrelated to this piece; the flag lets the rest run).
- `baseline_main_summary.txt` — the same command on `origin/main` @ 1d27219 (sorted FAILED/ERROR lines + summary), for the "no NEW failures vs main" comparison.
- `ruff_output.txt`, `node_check.txt` — `ruff check` on touched `.py`; `node --check` on `app/static/editing.js` (not modified: it already builds the label only from `render_price` / `render_price_kind`).
- New test matrix: `tests/test_h7_03_price_label.py` (real `get_engine_version()` against a mocked `/health`, cold cache).
