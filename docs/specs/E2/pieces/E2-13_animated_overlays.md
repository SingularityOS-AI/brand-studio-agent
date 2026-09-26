# E2-13 — Animated overlay library (templates + render + preview)

Depends on: E2-02, E2-07
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F3b, the CEO's addition: Brandy places **animated** motion-graphic overlays, not only static
cards. Closed library; the LLM only fills parameters. P2: dropped if the cut line is hit.

## Files you may touch
- `render_service/overlay_templates/*.html` (new: `stat_counter`, `checklist`, `arrow_callout`,
  `lower_third`, `quote_reveal`, `icon_pop`, `progress_bar`, `keyword_highlight`): transparent
  1080x1920 page, ONE paused GSAP timeline `window.__timelines.main`, params from
  `window.__params` (JSON), text fitted with the E2-04 rule, Brand Soul colours/font from
  params, entrance <= 0.8 s, exit <= 0.4 s, vendored GSAP (E2-02).
- `render_service/ffmpeg_dress.py` (overlay with `anim`: seek-capture PNGs -> alpha overlay at x/y)
- `render_service/manifest.py` (OverlayCue optional `anim: str`, `params: dict`)
- `app/editing/catalog/catalog_v1.json`, `app/editing/dressing.py`, `app/editing/ir.py`
- `app/main.py` (read-only static mount of `render_service/overlay_templates` at `/static/overlay_templates`)
- `app/static/editing_preview.js` (same template in an iframe layer, seek to `currentTime - start`)
- `tests/test_editing_e2_13_anim.py` (new)

## Done when
Each template non-blank at its midpoint in the offline E2E; preview vs MP4 at the same time
< 8 % mean pixel error inside the overlay box; added render time per animated overlay < 10 s
on 4 vCPU. Evidence in `docs/specs/evidence/E2-13/`.
