# H7-01 — Raw cut never 500s: restore `scene_fallbacks` in the render contract

Depends on: —
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P0 · Branch: `agent/H7-01`

## Goal
Findings #1 and #2. Every raw render currently crashes after upload because `RenderOk`
forbids `scene_fallbacks`, which `render_service/app.py` (~L298) sends; and the E2-03 warning
never shows in the editing state.

## Files you may touch   (Scope Whitelist)
- `render_service/manifest.py` (`RenderOk`: optional `scene_fallbacks: list[SceneFallback] = []`; define a small `SceneFallback` model `{scene_n:int, used: Literal["face","image"], reason:str}`)
- `render_service/version.py` (`ENGINE_VERSION = "2026.09.29"`)
- `app/editing/dispatch.py` (only if `resolve_raw_render` does not persist `scene_fallbacks` into `raw_render`)
- `app/editing/router.py` (only the part of `_state` that exposes `raw.scene_fallbacks` and the English warnings)
- `tests/test_h7_01_render_ok.py` (new)

## Shared semantics
`RenderOk` stays `extra="forbid"`. The new field is optional with default `[]`, so an old
backend and a new service (or the reverse) never break. Warning strings are exactly
E2-03's: `Scene {n}'s motion graphic could not be drawn, so we used your face.` /
`…so we used the AI image.`

## Behaviour
- `RenderOk(..., scene_fallbacks=[...])` validates; the raw endpoint returns 200.
- The backend stores `scene_fallbacks` with `raw_render`; `GET /api/editing/{idea}` exposes them
  under `raw.scene_fallbacks` and `warnings` contains the English sentence per fallback.

## Out of scope
Pricing, the render label (H7-03), any test outside your new file (H7-02 fixes the stale ones).

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (after H7-02 merges; before that: no NEW failures vs main)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # must show ONLY files from your whitelist
```
Plus these must pass: `tests/test_render_service_p73_app.py`, `tests/test_render_service_p75_container.py::test_app_converter_replaces_local_inputs_path`,
`tests/test_render_e2e_offline.py`, all of `tests/test_editing_e2_03_empty_scene.py`, and your new test
(a raw request through `TestClient(render_service.app.app)` with a blank MG returns 200 and a non-empty `scene_fallbacks`).

## Evidence   (`docs/specs/evidence/H7-01/`)
`pytest_output.txt` (full suite tail + the listed tests with -v), `ruff_output.txt`, `README.md` (EVIDENCIA template, no verdicts).
