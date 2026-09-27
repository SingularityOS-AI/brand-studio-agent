# Evidence — E2-04 (card text fit)

Revised after independent review (see PR #9 review comment). Environment for this
revision: `CHROME_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, real
`ffmpeg 6.1.1` (libx264, aac, libass) installed via `apt-get install ffmpeg`, and the
brand fonts (`render_service/fonts/*.ttf`) installed system-wide via
`/usr/local/share/fonts/brandstudio/` + `fc-cache -f` — matching
`render_service/Dockerfile`'s production setup, so this run is not ffmpeg/font-gated
like the first submission was.

- `pytest_e2_04_only.txt` — `pytest -q tests/test_editing_e2_04_card_fit.py -rs -v`: **13 passed, 0 skipped.**
- `pytest_full_output.txt` — `pytest -q` (full suite): **6 failed, 868 passed, 15 skipped, 1 error.**
- `ruff_check_output.txt` — `ruff --version` (0.16.9) + `ruff check` on all 4 touched files: **3 findings, all pre-existing/out of scope** (see below).
- `node_check_output.txt` — `node --check app/static/editing_preview.js`: clean.
- `card_stat_70_chars.png` / `card_stat_70_chars_measurement.txt` — real Chromium render (Inter) of the 70-char `card_stat` acceptance case, 900×400.
- `mp4_frame_card_crop.png` / `mp4_frame_measurement.txt` — the same 70-char card composited into a **real MP4** (libx264 + libass) and cropped back out of the rendered frame at the overlay's midpoint. Fixes the review's blocker #5: the bottom-row-vs-raw-background check (see below) proves the crop isn't an empty/truncated band.
- `caps_digits_{Inter,Montserrat}_*.png` — the two capitals/digits-heavy adversarial cases from the review, rendered in both brand fonts.

## What changed from the first submission (review verdict: FAIL)

Both blocking findings were independently reproduced before fixing:

1. **Chromium headless viewport/window-size mismatch** (`render_service/cards.py`,
   `render_card_png`). `--headless=new --window-size=W,H --screenshot` only actually
   captures the top `H - 87px` of the page and pads the rest with transparent
   pixels — verified with a probe HTML with colored stripes: a `--window-size=900,400`
   capture's own bottom stripe (rows 390-399) came back fully transparent, with real
   content ending at row 312. Fixed by requesting `--window-size=W,H+200` and cropping
   the PNG back to `W×H` in pure Python (`_decode_png_rgba` / `_encode_png_rgba` /
   `_crop_png_top_left` in `cards.py` — no new runtime dependency; `ffmpeg` is already
   in `render_service/Dockerfile` but wasn't needed for this). Re-verified the review's
   exact repro cases (`card_stat` 900×400, `card_lower_third` 900×200, `onscreen_text`
   900×300) now capture to their last pixel row.
2. **Flat K=0.58 underestimates bold capitals/digits** (`render_service/text_fit.py`,
   `app/static/editing_preview.js`). Measured in this sandbox with the real brand fonts
   installed: `"$2,400,000 · SAVED IN YEAR ONE"` in a 900×300 `card_stat` wrapped to 3
   lines in Chromium against 2 computed by the old flat-K formula, and the browser
   silently dropped "ONE" (not visible in the rendered PNG at all — `overflow: hidden`
   swallowed it, no error). Fixed with per-character width factors matching the
   review's measurements: ASCII capitals + `%$&@#` = 0.74, digits = 0.64, everything
   else = 0.58 (mirrored exactly in Python `_char_width_factor`/`_text_width` and JS
   `charWidthFactor`/`cardTextWidth`). Re-verified the same case renders complete in
   both Inter and Montserrat.

The tests added for these (`test_card_box_sizes_fully_captured_and_no_clip`,
`test_caps_and_digits_no_clip_in_brand_fonts`) also assert
`assert_card_box_fully_captured` — a check the first submission's tests didn't have,
which is exactly the gap the review flagged ("The test is blind to truncation"): a
truncated capture reads back with the missing rows at alpha=0, which the
top/bottom-20px "no text pixel" check alone treats as a pass.

3. **Authorized one-line fix**: `tests/test_render_service_p90b_overlays.py:39`
   (`assert "110px" in html_out`) replaced with an assertion against
   `fit_card_text(ov.text, "card_stat", ov.w, ov.h)`'s actual fitted size. Only that
   line (plus the import it needs) changed in that file, per the review's scope
   authorization.
4. Ruff: fixed the 3 findings the review flagged in this piece's own files
   (`text_fit.py` RUF022 sorted `__all__`, an import-order fix ruff's own `--fix`
   applied to `cards.py`, and `tests/test_editing_e2_04_card_fit.py`'s ISC004 wrapped
   in parens). The 3 findings still listed in `ruff_check_output.txt` (`SIM117`,
   `RUF059` ×2) are in `tests/test_render_service_p90b_overlays.py` at lines 66-68 and
   299-305 — pre-existing code, not touched by this piece's authorized one-line edit,
   and present identically on `main` under the same `ruff 0.16.9` (verified by running
   ruff against `origin/main`'s copy of that file).

## Full suite: 6 failed, 868 passed, 15 skipped, 1 error

Same set of pre-existing-on-`main` failures as the first submission, unrelated to
editing: `test_guard_jwt.py::test_normal_request_pass_and_deduct`,
`test_guard_jwt.py::test_budget_exhausted_returns_402`,
`test_network_lock.py::test_network_lock_blocks_sync_httpx_to_external_host`,
`test_network_lock.py::test_network_lock_blocks_async_httpx_client_to_external_host`,
`test_render_service_p75_container.py::test_fonts_and_sources_hashes`,
`test_scripts_pieza43.py::test_manual_patch_during_in_flight_regeneration_not_lost`,
`test_render_service_p92_rebote.py::test_p92_post_progress_host_validation` (error).
`tests/test_render_service_p90b_overlays.py::test_1_card_html_escapes_text_and_includes_font_size`,
which failed in the first submission, now passes (the authorized fix).
