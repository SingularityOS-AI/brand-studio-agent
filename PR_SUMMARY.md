# Pull Request: E2-13 Animated Overlay Library (Templates + Render + Preview)

## Summary

Implements Piece E2-13 from the Editing System specification: A closed library of 8 animated overlay templates with GSAP animations, seek-capture rendering for MP4 output, and iframe-based browser preview with GSAP timeline seeking.

## What Changed

### 1. Render Contract (render_service/manifest.py)
- Extended `OverlayCue` with two optional fields:
  - `anim: str | None = None` — Animation name (matches IR kind)
  - `params: dict[str, Any] | None = None` — Template parameters (text, colors, etc.)
- Updated `OVERLAY_KINDS` tuple with 8 animated kinds

### 2. Animated Overlay Templates (render_service/overlay_templates/)
Added 8 HTML templates following the closed library spec:
- `stat_counter.html` — Animated number counter
- `checklist.html` — Item-by-item checklist reveal
- `arrow_callout.html` — Arrow-shaped callout with text
- `lower_third.html` — Lower third nameplate
- `quote_reveal.html` — Large quote with line-by-line reveal
- `icon_pop.html` — Icon with pop animation
- `progress_bar.html` — Animated progress bar
- `keyword_highlight.html` — Highlighted keyword box

Each template:
- 1080×1920 transparent background
- Single paused GSAP timeline at `window.__timelines.main`
- Parameters from `window.__params` JSON
- Brand Soul colors/font from params
- Entrance ≤ 0.8s, exit ≤ 0.4s
- Vendored GSAP (CDN to vendor rewrite supported)

### 3. Seek-Capture Rendering (render_service/ffmpeg_dress.py)
- Added `_render_animated_overlay_png_frames()` — Delegates to `seek_capture.capture()`
- `build_final()` detects animated overlays via `ov.anim && ov.kind in ANIMATED_OVERLAY_KINDS`
- Falls back to static `render_card_png()` if seek-capture fails
- Maps IR kind `lower_third_anim` → template `lower_third.html`

### 4. IR Generation (app/editing/ir.py)
- Conditional `anim` assignment: `anim = kind if kind in animated_kinds else None`
- Animated kinds: `stat_counter`, `checklist`, `arrow_callout`, `lower_third_anim`, `quote_reveal`, `icon_pop`, `progress_bar`, `keyword_highlight`
- Params override handling in overlay_settings

### 5. Browser Preview (app/static/editing_preview.js)
- Animated overlays render in iframe (vs. div for static)
- GSAP timeline seeking: `tl.seek(curTimeMs - stOv.start_ms)`
- Params updates on cue changes
- Seamless seek-capture parity with MP4 render

### 6. Static File Mount (app/main.py)
- `/static/overlay_templates` → `render_service/overlay_templates/`
- Wrapped with existence check

### 7. Catalog Integration (app/editing/catalog/catalog_v1.json)
- Added 8 animated kinds to `overlays.kinds`
- Fixed `overlays.animated_kinds` array entry (`lower_third_anim` → matches IR kind)

### 8. Test Suite (tests/test_editing_e2_13_anim.py)
- 56 tests covering all integration points:
  - E2-13.1: OverlayCue contract
  - E2-13.2: Animated overlay templates
  - E2-13.3: Seek-capture rendering
  - E2-13.4: Catalog integration
  - E2-13.5: Browser preview
  - E2-13.6: Static file mount
  - E2-13.7: Catalog format

All 56 tests pass.

## Zero-Regression Guarantees

1. **Optional Fields**: `anim` and `params` default to `None` — existing overlays with only kind/text/position work unchanged
2. **Safe Deploy Order**: Contract order allows backend and render service to deploy independently
3. **Fallback on Failure**: If seek_capture fails, falls back to static PNG rendering
4. **Preserved E2-01..E2-12**: No changes to existing overlay rendering logic outside conditional paths

## Definition of Done

```
python -m pytest tests/test_editing_e2_13_anim.py -v
# 56 passed, 4 warnings in 0.85s

ruff check render_service/manifest.py render_service/ffmpeg_dress.py app/editing/ir.py tests/test_editing_e2_13_anim.py
# Clean (E2-13 files only; pre-existing issues in app/main.py not modified)

node --check app/static/editing_preview.js
# Clean
```

## Files Modified

- `render_service/manifest.py` — OverlayCue contract, OVERLAY_KINDS
- `render_service/ffmpeg_dress.py` — Seek-capture integration
- `app/editing/ir.py` — Animated overlay IR generation
- `app/main.py` — Static file mount
- `app/static/editing_preview.js` — Iframe preview + GSAP seeking
- `app/editing/catalog/catalog_v1.json` — Catalog entries for LLM
- `render_service/overlay_templates/*.html` — 8 animated templates (new)
- `tests/test_editing_e2_13_anim.py` — Test suite (new)

## Spec Reference

[docs/specs/block_E/Editing_System/pieces/E2-13_animated_overlays.md](docs/specs/block_E/Editing_System/pieces/E2-13_animated_overlays.md)

## Checklist for Reviewers

- [ ] All 8 templates follow the closed library spec (1080×1920 transparent, paused timeline, window.__params)
- [ ] Animation timing: entrance ≤ 0.8s, exit ≤ 0.4s
- [ ] Text follows E2-04 fit rule (font shrink, max 3 lines, min 28px, no word cut)
- [ ] `anim` and `params` are optional with None defaults
- [ ] Seek-capture fallback on failure
- [ ] Iframe preview + GSAP parity with MP4
- [ ] No changes to E2-01..E2-12 behavior

## Evidence Location

Evidence (literal output, no verdicts) saved to:
- `docs/specs/evidence/E2-13/` (test outputs, template inspections)
