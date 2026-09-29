# H7-01 evidence

Literal output only; the reviewer decides.

- `pytest_output.txt` — full suite (`-m "not e2e"`, `--ignore=tests/test_agent_f11.py`, which cannot be collected on main: H7-02) with the main baseline summary line, then `-v` for the listed tests.
- `ruff_output.txt` — `ruff check` on the touched `.py` files.
- No `.js` file touched, so no `node --check` was run.

Environment: `ffmpeg` was not on PATH in this container, so the ffmpeg-dependent tests (`tests/test_render_e2e_offline.py`, the real-render tests in `tests/test_editing_e2_03_empty_scene.py`) were skipped, not run.

Tests overwrote tracked files under `docs/specs/evidence/` (finding #6, H7-02); those were restored with `git checkout` and are not part of this change.
