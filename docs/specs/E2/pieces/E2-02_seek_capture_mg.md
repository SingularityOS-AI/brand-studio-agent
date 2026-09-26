# E2-02 — Seek-capture module; motion-graphic scenes never blank

Depends on: E2-01
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
Fix bug B2 at its root. Motion-graphic templates build a paused GSAP timeline
(`window.__timelines[name]`). Today `render_service/motion.py::convert_html` tries the
HyperFrames CLI (120 s timeout, times out on long scenes) and falls back to one Chromium
screenshot at t=0 -> everything at opacity 0 -> blank scene (CEO video 0:29-0:41).

## Files you may touch
- `render_service/seek_capture.py` (new)
- `render_service/motion.py`
- `render_service/requirements.txt` (add `playwright` - Python package only; never run
  `playwright install`; launch the system Chromium via `executable_path=motion.chromium_path()`)
- `render_service/vendor/gsap.min.js` (new, vendored GSAP 3.14.x). At load time
  `seek_capture.py` rewrites the CDN `<script src>` to the vendored file. Do not edit
  `app/audiovisual/motion_templates/`.
- `tests/test_render_service_e2_02_seek.py` (new)

## Behaviour
- `seek_capture.capture(html_path, out_dir, *, width, height, fps=30, transparent, max_anim_s=3.0) -> list[Path]`:
  open the page, wait for `window.__timelines`, `D = min(longest tl.duration(), max_anim_s)`,
  for each frame `t in [0, D]` step `1/fps` call `tl.seek(t, false)` on every timeline and
  screenshot (`omit_background=transparent`). The last PNG is the hold frame.
- `convert_html` new order: **seek-capture first** -> FFmpeg builds the scene video from the
  PNG sequence + last frame held until `duration_s` -> HyperFrames only if seek-capture
  raises -> last-resort still screenshot must first run `tl.progress(1)` on every timeline.
- Hard timeout per MG: 60 s. Log `mg_path=seek|hyperframes|still`.

## Tests
- Each template (`stat`, `quote`, `list`, `lower_third` via
  `app.audiovisual.motion_graphics.build_html`) rendered for 6 s: the frame at 3 s is NOT
  near-uniform (luma std-dev > 8) and differs from the frame at 0.0 s.
- With seek-capture forced to fail, `convert_html` still produces a non-blank video.

## Done when
Tests pass; offline E2E (E2-01) green; evidence = sheet of the 4 templates at 0 s, 0.5 s,
3 s + wall seconds per template in `docs/specs/evidence/E2-02/`.
