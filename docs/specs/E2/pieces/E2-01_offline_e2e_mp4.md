# E2-01 — Offline end-to-end MP4 test (no credentials)

Depends on: —
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
One pytest that renders a real raw cut and a real dressed final MP4 through the render
service **with no network and no secrets**, so every later piece can prove itself on
MP4 frames.

## Files you may touch
- `tests/test_render_e2e_offline.py` (new)
- `scripts/render_contact_sheet.py` (new, tiny helper: MP4 + times -> one PNG sheet)

## Behaviour
- Generate synthetic media with ffmpeg `lavfi` at test time (never commit media): two 6 s
  1080x1920 "takes" (`testsrc2` + `sine`), one PNG image, one 20 s music bed, one SFX.
- Call `render_service.app.app` in-process with `fastapi.testclient.TestClient`; secret via
  `monkeypatch.setenv("RENDER_SERVICE_SECRET", ...)`.
- Monkeypatch the render service's download/upload helpers in `render_service/io_utils.py`
  so `inputs[*].url` resolve to local files and the output upload writes to `tmp_path`
  (read `io_utils.py` to find them; do not change production code).
- Build the timeline and IR with the real backend functions:
  `app.editing.timeline.build_timeline` -> `app.editing.dressing.fallback_dressing`
  (`load_catalog`, `scene_contexts`, `app.editing.timeline.cut_hash`) ->
  `app.editing.ir.build_ir_stage2` with `app.editing.brand_style.derive_caption_style(None)`
  and frame zero text `"Stop wasting money on ads that never convert"`.
- Assert: both responses `ok`; ffprobe says 1080x1920, h264 + aac, duration within
  +-150 ms of the timeline; extract frames at 0.2 s and at every overlay midpoint.
- Mark it `@pytest.mark.render`; skip cleanly if `ffmpeg` is missing. Chromium comes from
  `CHROME_PATH` if set (overlay cards need it); without it, cards are skipped by the service.
- `python scripts/render_contact_sheet.py final.mp4 0.2 2.8 6.8 --out sheet.png`.

## Done when
- `python -m pytest tests/test_render_e2e_offline.py -v` passes with ffmpeg and skips
  (not fails) without it. Full suite green.
- Evidence: pytest output + `sheet.png` in `docs/specs/evidence/E2-01/`.

## Out of scope
Any production code change.
