# E2-03 — Empty-scene guard + English warning

Depends on: E2-02
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
Safety net for B2 (decision E2-D5): no MP4 ever ships a blank scene.

## Files you may touch
- `render_service/ffmpeg_raw.py`, `render_service/manifest.py` (optional response field only)
- `app/editing/dispatch.py`, `app/editing/router.py` (surface the warning in the editing state)
- `app/static/editing.js` (show the warning)
- `tests/test_editing_e2_03_empty_scene.py` (new)

## Behaviour
- After a motion-graphic scene video is produced, sample 1 frame / 250 ms; if luma std-dev
  < 4 on > 90 % of samples the scene is **empty**: replace it with the scene's AI image
  (if the timeline has one for that scene) as a still, else the founder's face take.
- Raw response gains optional
  `scene_fallbacks: [{"scene_n": 3, "used": "face"|"image", "reason": "empty_motion_graphic"}]`.
- Backend stores it with the raw render; the editing state exposes it; Editing shows
  `Scene 3's motion graphic could not be drawn, so we used your face.` (or `the AI image`).

## Done when
A deliberately blank MG HTML yields an MP4 whose scene is the fallback (not near-uniform) and
a state with `scene_fallbacks`; UI string present; evidence frames in `docs/specs/evidence/E2-03/`.
