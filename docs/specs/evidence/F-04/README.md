# F-04 evidence

- `node_check.txt`: `node --check` on both files this piece adds/touches
  (`app/static/actions.js`, `app/static/app.js`). No output on either =
  clean syntax.
- `node_agent_actions_test.txt`: `node tests/agent_actions.test.js` -- the
  Node harness the piece asks for. Loads the *real* `actions.js` + `app.js`
  (in that order, same as index.html will load them once a later piece wires
  the `<script>` tag) into a stubbed DOM with `fetch` mocked, then exercises
  `BrandStudioActions`: registry shape (5 Script + 5 Audiovisual actions),
  `execute('script.iterate_scene', ...)` calling the exact same endpoint +
  body as `handleScriptRegenerate` (the button's own function) with
  `X-Agent-Action-Id` set to the row `execute()` just created via
  `POST /api/agent/actions`, a thrown `run()` (`audiovisual.change_scene_type`
  on a 422) still clearing `currentActionId`, and a `source: 'button'` call
  skipping the audit-row create POST. 12/12 checks pass.
- `ruff_new_files.txt`: `ruff check tests/test_actions_f04.py` (the only new
  Python file). All checks passed (ruff 0.15.8).
- `pytest_f04_own_tests.txt`: `pytest -q tests/test_actions_f04.py` alone --
  8 passed. This file re-runs `node --check` on both JS files and the Node
  harness above as pytest subprocess tests (so `pytest -q` catches a
  regression here without a separate `node` invocation), plus static
  contract checks: the registry's 10 actions have the right step/needsConfirm
  shape, `actions.js` never dereferences `window.BrandStudio` while building
  `register({...})` calls (it loads *before* `window.BrandStudio` exists --
  only `run`/`cost` closures may reference it), `authenticatedFetch` sends
  `X-Agent-Action-Id` from `BrandStudioActions.currentActionId`, and
  `window.BrandStudio` exposes every function the registry calls.
- `pytest_full_suite.txt`: `pytest -q tests/` on this branch. 853 passed, 6
  failed, 1 error, 43 skipped.
- `pytest_full_suite_baseline.txt`: same command via `git stash -u` (none of
  this piece's files present). 845 passed, same 6 failed/1 error. The delta
  is exactly this piece's 8 new tests; the failures/error
  (`test_guard_jwt.py` x2, `test_network_lock.py` x2,
  `test_render_service_p75_container.py`, `test_scripts_pieza43.py`,
  `test_render_service_p92_rebote.py`) are pre-existing and unrelated to
  F-04 (JWT budget assertions, network-lock/event-loop, a container hash
  fixture, and an external-tool test that already fail on this branch before
  F-04's files are added).

## A regression this piece's diff had to route around

`app.js`'s `Script-GenerateBtn` click listener was an inline arrow function.
The first cut named it as a standalone `async function handleScriptGenerate`
declared just above the wiring and moved
`scriptGenerateBtn.addEventListener('click', handleScriptGenerate)` to run
right after the function body -- syntactically fine, but it broke
`tests/test_pieza61_frontend_contracts.py::test_pieza61_static_contracts_in_app_js`,
which locates the handler by scanning backward from
`/api/script/generate?idea_id=` for the literal text
`scriptGenerateBtn.addEventListener` and asserts strings inside that window.
Moving the `addEventListener` call after the endpoint reference broke that
scan. Fixed by keeping `scriptGenerateBtn.addEventListener('click', ...)` at
its original position and instead declaring `let handleScriptGenerate;`
earlier (with the piece's other script-view state) and assigning the arrow
function to it inline at the call site
(`scriptGenerateBtn.addEventListener('click', handleScriptGenerate = async (e) => {...})`).
Same behaviour, same file layout, zero-diff for every other pre-existing
static-contract test that scans `app.js` by string position.

## Files not touched (read as ambiguous, took the conservative reading)

The piece's own description says `app/static/actions.js` is "new, loaded
before `app.js`", but `index.html` (where the `<script>` tag would go) is
not in the piece's "Files you may touch" list, and neither is it in F-05's
list (the very next piece, which wires the Agentic-mode toggle and Brandy's
tools). Per AGENTS.md #1 ("If the piece is ambiguous ... implement the most
conservative reading"), this PR does not add a `<script src="/static/actions.js">`
tag to `index.html`. `actions.js` is fully self-contained and tested via the
Node harness above independent of the real page; whichever later piece wires
the toggle/tools UI into `index.html` is the natural place to also add this
script tag (the two changes ship together, or `actions.js` would load with
nothing yet calling `BrandStudioActions.execute`).

## Costs hardcoded in `actions.js`

`script.generate` (10 credits) and `script.iterate_scene` (2 credits) mirror
the literal button labels in `app/static/index.html`
("Generate Script (10 credits)", "Regenerate (2 credits)") and
`CREDITS_COST_GENERATE` / `CREDITS_COST_REGENERATE_SCENE` in
`app/scripting/scripts.py` -- not the spec.md numbers (which say "Generate
(6)"), since spec.md predates the current pricing and the piece says costs
must come "from the same sources the UI shows". `audiovisual.generate_all`
and `audiovisual.regenerate_one` compute their cost from the same
`/api/audiovisual/{id}/estimate` response (`credits_pending`/`credits_total`,
`credits_by_type`) the Audiovisual UI reads, rather than a hardcoded number,
since the real cost varies by scene count and asset type.
