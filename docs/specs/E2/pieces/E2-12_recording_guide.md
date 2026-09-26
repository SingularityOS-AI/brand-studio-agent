# E2-12 — Recording guide: silhouette + one tip

Depends on: —
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
F5 (E2-D8). Tight framing and glasses glare are fixed at recording time, not in post.

## Files you may touch
- `app/static/app.js` - only the recording studio (`openRecordingStudio`, ~L4918) and its markup
- `tests/test_recording_e2_12_guide.py` (new, static assertions)

## Behaviour
Over the live camera preview: SVG head-and-shoulders outline (stroke only, 40 % opacity, top
of head ~18 % from the top, shoulders reaching the bottom) and one line:
`Frame head and shoulders. Light at 45°, not straight at your glasses.` It is a DOM overlay
and is **never** part of the recorded stream. Toggle `Hide guide`. English only.

## Done when
Static test proves the overlay is outside the recorded stream path; evidence = studio
screenshot in `docs/specs/evidence/E2-12/`.
