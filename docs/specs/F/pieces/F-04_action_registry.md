# F-04 — Action Registry + `X-Agent-Action-Id` fetch context

Depends on: F-02
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
Principle 2: one registry that wraps the **exact functions the buttons call**.

## Files you may touch
- `app/static/actions.js` (new, loaded before `app.js`)
- `app/static/app.js`: expose the button handlers the registry needs through
  `window.BrandStudio` (today it exposes `authenticatedFetch, showPaywall, updateCreditsUI,
  refreshCredits, escapeHtml, openRecordingStudio, showAudiovisualView, showBlockCView,
  hideMainViews, renderPipelineRail, getCurrentScriptIdeaId` ~L7395) and make
  `authenticatedFetch` add `X-Agent-Action-Id` when `BrandStudioActions.currentActionId` is
  set. Refactor a listener into a named function only when needed to expose it; do not
  change its behaviour.
- `tests/test_actions_f04.py` + `tests/agent_actions.test.js` (Node, fetch mocked)

## Behaviour
`BrandStudioActions.register({id, step, title, needsConfirm, cost(args), run(args)})`,
`list(step)`, `get(id)`, `async execute(id, args, {source, voiceMeta})`: creates the
`agent_actions` row for voice (F-02 API), sets `currentActionId` during `run`, clears it in
`finally`, returns `{ok, result|error}`. Register now the actions whose button functions
exist for **Script** (generate, iterate scene, edit scene text, lock, audit) and
**Audiovisual** (change scene type, estimate, generate all, regenerate one, open recording
studio) with costs from the same sources the UI shows. Catalog/Brand Soul/Editing are
registered in F-09/F-11.

## Done when
Node test: executing `script.iterate_scene` calls exactly the same endpoint + body as the
button path and sends the header; a thrown `run` still clears `currentActionId`. Evidence in
`docs/specs/evidence/F-04/`.
