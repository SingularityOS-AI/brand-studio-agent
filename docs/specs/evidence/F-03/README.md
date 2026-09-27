# F-03 evidence

Piece: `docs/specs/F/pieces/F-03_production_panel_audit.md`. Files touched:
`app/static/production_panel.js` (new), `app/static/index.html` (script tag),
`app/static/app.js` (6 guarded `BrandStudioPanel.refresh()` call sites),
`tests/test_panel_f03.py` (new).

- `node_check.txt`: `node --check` on both JS files this piece adds/touches
  (`app/static/production_panel.js`, `app/static/app.js`). No output on
  either = clean syntax.
- `ruff_check.txt`: `ruff check tests/test_panel_f03.py` (the only new Python
  file), run with the repo's ambient `ruff 0.15.8` (matching the version
  F-02/F-04's own evidence used). All checks passed. Note: `pip install -r
  requirements.txt` into a fresh venv pulls `ruff 0.16.9`, which enables
  `PLW1510` (`subprocess.run` without `check=`) by default and flags this
  file's three `subprocess.run(...)` calls -- the exact same pattern already
  used unmodified in `tests/test_actions_f04.py` and
  `tests/test_editing_p82c_editing_js.py`. Not a regression this piece
  introduced; ran the check with the version those pieces' evidence used.
- `dom_render_mixed_list.txt`: literal DOM-text evidence for the piece's
  "Done when" line ("DOM test renders a mixed list correctly and escapes a
  malicious utterance"). Same fake-DOM Node harness as
  `tests/test_panel_f03.py`, pretty-printed. Card 2's utterance is
  `<img src=x onerror=alert(1)>"><script>alert(2)</script>`; it appears
  verbatim as text inside the "You said: ..." line, no `<img>`/`<script>`
  element exists anywhere in the tree, and the fake DOM's `innerHTML` setter
  (which throws if ever assigned) was never invoked -- `pytest` would have
  failed loudly otherwise.
- `pytest_test_panel_f03.txt`: `pytest -q tests/test_panel_f03.py` alone --
  6 passed (node --check x2, script-tag-order + call-site-count statics, no
  `innerHTML` in source, and the DOM harness test itself).
- `pytest_full_suite.txt`: `pytest -q` (minus the repo-root
  `test_frontend_auth.py`, which needs `playwright` not installed in this
  environment -- pre-existing, unrelated to this piece) on this branch.
  859 passed, 6 failed, 1 error, 43 skipped.
- `pytest_full_suite_baseline.txt`: same command via `git stash -u` (none of
  this piece's files present). 853 passed, same 6 failed/1 error. The delta
  is exactly this piece's 6 new tests; the failures/error
  (`test_guard_jwt.py` x2, `test_network_lock.py` x2,
  `test_render_service_p75_container.py`, `test_scripts_pieza43.py`,
  `test_render_service_p92_rebote.py`) are pre-existing and unrelated to
  F-03 (JWT budget assertions, network-lock/event-loop, a container hash
  fixture, an already-flaky async lock test, and an external-tool test that
  already fail on this branch before F-03's files are added).

## Notes on ambiguous points, resolved conservatively per AGENTS.md #1

- **"Action finish events"**: the piece and plan.md mention refreshing "on
  action finish events" alongside the 5s poll. No such event currently
  exists in this codebase (`actions.js`/F-04 has no `dispatchEvent`/
  `CustomEvent`, and F-06's confirmation engine, which would run actions,
  isn't built yet) and `actions.js` is not in this piece's file list to add
  one. Implemented the two concrete mechanisms that do exist: an immediate
  `BrandStudioPanel.refresh()` call at every step-change point and inside
  `loadAudiovisualJobs` (the app.js function every "job refresh point"
  funnels through), plus the panel's own internal 5s poll loop while
  anything is `queued`/`running`. A future piece wiring `actions.js`'s
  `execute()` can call `BrandStudioPanel.refresh()` from its `finally` block
  without touching this piece's files.
- **"Voice cards expand"**: read as "voice cards show extra detail lines
  button cards don't" (each of "You said/Brandy/Confirmed" rendered only
  when the corresponding field is non-empty, since they populate
  progressively as propose -> confirm -> execute happens), not as an
  interactive collapse/expand widget -- the spec doesn't describe toggle
  behaviour and the piece doesn't list any accordion/state requirement.
- **Card title for button rows**: `agent_actions.action` for a button row is
  `"METHOD /api/.../route"` (per F-02's store), with no human title anywhere
  in the audit row. For a registered voice action, the same human `title`
  `actions.js` already defines is reused (e.g. "Iterate a scene with an
  instruction") so the card matches what Brandy would say. For everything
  else (all button rows, and any voice action id not in the registry), the
  title is derived by humanizing the last path/id segment (e.g. `POST
  /api/catalog/idea/{idea_id}/accept` -> "Accept"). Presentation-only, no
  effect on price, routing, or the confirmation engine.
- **"Merge, don't replace" the existing jobs display**: `#Prod-Jobs` is
  currently unused in `app.js` (empty `<div>`, `style="display:none"`,
  nothing renders into it) -- confirmed by grep, no `Prod-Jobs`/`Prod-Empty`
  references anywhere in `app.js` before this piece. Nothing to merge with;
  this piece is the first thing to render into it.
- **`result_ref` -> "Open" link**: defensively only rendered as an `<a
  href>` when the value matches `^(https?://|/)\S*$`, so a non-URL or a
  `javascript:`/`data:` value (which should never happen -- `result_ref` is
  service-role-written per F-02 -- but this stays defensive) never becomes a
  clickable link, per AGENTS.md's OWASP-adjacent guidance.
