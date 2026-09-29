# H8-01 evidence (literal output, no verdicts)

Files:
- `pytest_full_suite.txt` — `python -m pytest -q -m "not e2e" -p no:cacheprovider` (full suite, this branch).
  Tail: `1 failed, 1718 passed, 15 skipped, 2 deselected` — the failure is
  `tests/test_render_service_e2_02_seek.py::test_template_seek_render_non_blank[list-fields2]`
  (headless Chromium render test; `render_service` does not import `app/editing/ir.py`).
- Isolated re-run of that file (`-k non_blank`, same branch): `1 failed, 3 passed` in 240.35 s; the failing
  parameter was `stat-fields0` this time (a different one than in the full run).
- `pytest_h8_01_and_e2_07.txt` — new H8-01 tests + existing E2-07 tests: `610 passed`.
- `ruff.txt` — `ruff check` on both touched `.py` files. No `.js` touched (`node --check` not applicable).
- Before the fix, `test_stage2_caption_y_1600_moves_lower_third_overlay` and
  `test_stage2_caption_y_520_moves_top_overlay` fail; after it they pass.

Change: `app/editing/ir.py` stage 2 takes `caption_y` from `ir_stage1["layout"]` (already clamped) instead of
`timeline["settings"]`, so collision math and `layout` use the same value.
