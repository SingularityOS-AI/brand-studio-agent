# F-11 — Editing tools

Depends on: F-08 + E2 P0 merged
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Files you may touch
`app/static/agent.js`, `app/static/actions.js` (wrap `window.BrandStudioEditing.run`, whose
`EDIT_ACTIONS` live in `app/static/editing.js`), `tests/agent_editing.test.js`, `tests/test_agent_f11.py`.

## Tools
`edit_build_raw` (free) · `edit_auto_edit {style}` (free/limit per E2-11) ·
`edit_scene_visual {scene_n, face|broll|reset}` (free) · `edit_trim {scene_n, start_ms, end_ms}` (free) ·
`edit_music {on}` · `edit_sfx {on}` (free) · `edit_fix_caption {word, text}` (free, restate) ·
`edit_caption_position {top|middle|bottom}` (free) · `edit_overlay_delete {n}` · `edit_overlays {on}` (free) ·
`edit_try_another_take {scene_n}` (confirm, 2) · `edit_render` (confirm, price from state) ·
`edit_post_copy` (free) · `edit_share_link` (free). **Export/download stays a click** (A-D5).

## Done when
Harness: render restatement uses `state.render_price`; every tool calls `BrandStudioEditing.run`
with the same args as its button. Evidence in `docs/specs/evidence/F-11/`.
