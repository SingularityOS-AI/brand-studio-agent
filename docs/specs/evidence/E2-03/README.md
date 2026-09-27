# Evidence — E2-03 (empty motion-graphic scene guard)

Environment: `ffmpeg 6.1.1` (installed via `apt-get install ffmpeg`) and Chromium
`/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (`CHROME_PATH` set), so both the
pure-Python detection tests and the real HTML->MP4 conversion + build_raw() guard run
(none skipped).

## Files
- `pytest_e2_03_only.txt` — `pytest -q tests/test_editing_e2_03_empty_scene.py` (16 passed).
- `pytest_full_output.txt` — full suite `pytest -q` (897 passed, 15 skipped, 6 failed,
  1 error — the 6 failures + 1 error are pre-existing and unrelated to this piece;
  confirmed identical on the pre-E2-03 checkout via `git stash`).
- `ruff_check_output.txt` — `ruff check` on every .py file this piece touches, plus the
  same command run against the pre-E2-03 checkout for comparison. All 23 findings are
  pre-existing (same rule/column at the same relative code, unmoved by this diff);
  `tests/test_editing_e2_03_empty_scene.py` (new) reports 0.
- `node_check_output.txt` — `node --check app/static/editing.js` (exit 0).
- `blank_mg_source_frame.png` — a frame from the *literal* "deliberately blank MG HTML"
  fixture (`_BLANK_MG_HTML` in the test file: on-screen text colored identically to the
  background) after going through the real `render_service.motion.convert_html()`
  pipeline. Fully black, luma std-dev 0.0 on all 8 sampled frames.
- `raw_cut_scene2_after_fallback_frame.png` — a frame from scene 2 of the raw cut
  `build_raw()` produced from that same blank asset: the founder's face take, not a
  blank frame.
- `luma_stddev_measurement.txt` — the literal sampled std-dev values for both, plus the
  `scene_fallbacks` `build_raw()` returned (`used: "face"`).

## Note on scope (per AGENTS.md §1: write the question, implement the conservative reading)
The piece's file list does not include `render_service/app.py`. That file's `render_v1`
handler builds the HTTP `RenderOk` response with an explicit field list and does not
forward `scene_fallbacks` from the builder's result dict. Everything within this
piece's scope is fully wired end to end and tested (`build_raw()` → `dispatch.py` →
`router.py` → `editing.js`), but the real render service will not populate
`scene_fallbacks` over HTTP until a one-line follow-up adds
`scene_fallbacks=res.get("scene_fallbacks", [])` to that `RenderOk(...)` call in
`app.py`. Flagging this rather than touching a file outside the piece's list.
