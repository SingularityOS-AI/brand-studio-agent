# Block E.2 — plan (Editing polish)

Spec: `docs/specs/E2/spec.md`. Rules: `AGENTS.md`. Deadline 2026-09-30 11:00 VET.

## 1. Architecture decision (CEO chooses in `architecture-decision-E2-F.html`; plan assumes A)

**A — Seek-capture renderer (recommended).** One small module in the render service
(`render_service/seek_capture.py`) opens an HTML composition in headless Chromium
(Python `playwright` driving the system Chromium — no browser download), **seeks** the
GSAP timeline(s) to each frame time (`tl.seek(t, false)`), screenshots (transparent for
overlays, opaque for full scenes) and hands a PNG sequence to FFmpeg. Only the animated
window is captured at 30 fps (the timeline's `duration()`, capped at 3 s); the rest is the
last frame held. Used for: (1) motion-graphic scenes in the raw cut (fixes B2),
(2) animated overlays in the final render (F3b). The browser preview plays **the same
HTML** in an absolutely positioned layer and seeks the same timeline to
`video.currentTime - start`, so preview = MP4 by construction.
Cost estimate: ~40–90 screenshots per animated element ≈ 3–8 s on 4 vCPU.

**B — HyperFrames pre-render.** Every animated element is rendered by the HyperFrames
CLI as a transparent video when the founder auto-edits, cached by content hash, then
composited. Freer, but measured at ~8 s of CPU per second of video, needs job
orchestration and a cache, and HyperFrames is exactly what timed out in B2.

## 2. Shared semantics (both renderers MUST follow — extends plan-bloque-E §4)
- Canvas 1080×1920. Caption band: `caption_y` = y of the band's **bottom edge**
  (default 1250, today's value). Presets: Top = 520, Middle = 1080, Bottom = 1600.
  Allowed range 360–1700. ASS: `\an2\pos(540,caption_y)` per event; preview:
  `top: caption_y px; transform: translateY(-100%)`.
- Caption box height for collision = `lines × font_px × 1.15 + 2×outline`, width 900.
- Zones for overlays: TOP (y 160–700), MIDDLE (y 700–1220), BOTTOM (y 1220–1760).
  The caption band occupies the zone(s) its box intersects. An overlay keeps its
  requested zone if free, else moves to the nearest free zone of the same height;
  if none fits, the IR emits the overlay with `hide_captions: true` and **drops the
  caption events inside `[start_ms, end_ms]`** (renderers draw nothing special).
- Card text fit: available box `w-80 × h-60`; font starts at the kind's size and
  shrinks in 2 px steps until all lines fit (max 3 lines, min 28 px); words are never
  cut. Same function in Python (`render_service/text_fit.py`) and JS
  (`editing_preview.js::fitCardText`), parity-tested.
- One caption style: every caption event uses `size: "block"` and the Brand Soul style.
  The `hero` size is no longer produced (schema keeps accepting it for old IRs).
- Empty scene: a scene is "empty" if the per-frame luma std-dev of its rendered video is
  < 4 for > 90 % of sampled frames (sample 1 frame / 250 ms).

## 3. Pieces (1 piece = 1 PR = 1 commit)
Lane A = render service + `app/editing/*` + `editing*.js`. Lane B (block F) must not
touch those files; Lane A must not touch `app.js` except E2-12.

| ID | Title | Depends | Priority | Who |
|---|---|---|---|---|
| E2-01 | Offline end-to-end MP4 test (no credentials) | — | P0 | Jules / Claude cloud |
| E2-02 | Seek-capture module + motion-graphic scenes never blank | E2-01 | P0 | Antigravity (needs Chromium) |
| E2-03 | Empty-scene guard + English warning | E2-02 | P0 | Jules / Claude cloud |
| E2-04 | Card text fits its box (Python + JS parity) | E2-01 | P0 | Jules / Claude cloud |
| E2-05 | Engine version in render key + render pricing P1 | — | P0 | Jules / Claude cloud |
| E2-06 | One caption style + `caption_y` in the IR and both renderers | E2-01 | P0 | Antigravity |
| E2-07 | No-collision layout in the IR | E2-06 | P0 | Jules / Claude cloud |
| E2-08 | Editing UX: 3 steps, English, "Auto-edit", loading screen | E2-05 | P0 | Antigravity |
| E2-09 | Caption band drag + presets (UI) | E2-06, E2-08 | P1 | Antigravity |
| E2-10 | Overlay controls: delete / edit text / on-off | E2-07, E2-08 | P1 | Jules / Claude cloud |
| E2-11 | Auto-edit styles Clean / Standard / Bold + free restyles | E2-08 | P1 | Jules / Claude cloud |
| E2-12 | Recording guide (silhouette + tip) | — | P1 | Antigravity |
| E2-13 | Animated overlay library (templates + render + preview) | E2-02, E2-07 | P2 | Antigravity |

**Cut line:** if on 2026-09-28 20:00 VET any P0 is still open, E2-13 is dropped and
E2-11/E2-12 move after block F's P0.

## 4. Deploy order (the CEO runs deploys; agents never deploy)
1. Pieces that change `render_service/` → merge → CEO runs
   `gcloud run deploy brand-studio-render --source render_service --region us-central1 --project singularityos-web-app --quiet`
   → check `/health` shows the new `engine_version`.
2. Backend/frontend pieces → merge to `main` → Render.com auto-deploys.
Contract changes are optional-with-default, so order mistakes don't break production.

## 5. Review
Each PR: the reviewer (Capitán, or a clean Claude Code cloud session acting as auditor)
re-runs the Definition of Done from `AGENTS.md`, reads the full diff, and checks the
evidence against the piece's "Done when". Render pieces are judged on MP4 frames, never
on preview screenshots alone.
