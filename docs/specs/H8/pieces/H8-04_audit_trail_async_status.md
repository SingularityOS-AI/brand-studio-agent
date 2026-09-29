# H8-04 — Audit trail: async jobs finish, the panel refreshes, credits recorded

Depends on: — (main @ ad93652)
Read first: `AGENTS.md`, `docs/specs/H8/README.md`.
Priority: P0 · Branch: `agent/H8-04`

## Goal
In production every `POST /api/editing/{id}/render` row in `agent_actions` stays `queued` forever (no
`result_ref`, `updated_at` = `created_at`), so the right panel shows "Render · QUEUED" for jobs that finished
or failed hours ago. The panel also does not refresh after in-step actions (Script iterate/lock appeared only
after a step change), and `credits` is always null.

## Files you may touch   (Scope Whitelist)
- `app/agent/store.py`, `app/agent/middleware.py` (store the created job id as `result_ref` when the response
  body has `job.id`; store `credits` from the response's charged amount when present)
- `app/editing/dispatch.py`, `app/audiovisual/worker.py` (when a job reaches done/failed/cancelled, update the
  `agent_actions` rows whose `result_ref` = that job id: status + `updated_at`; never raise)
- `app/static/production_panel.js` (refresh after any successful non-GET request: listen for a
  `brandstudio:action-finished` DOM event and also poll every 5 s while any card is queued/running)
- `app/static/app.js` (ONE line inside `authenticatedFetch`: dispatch `brandstudio:action-finished` after a
  non-GET response resolves)
- `tests/test_h8_04_audit_async.py` (new) + a Node DOM test for the panel

## Behaviour
Render/asset rows go queued → done/failed when the worker finishes; failed rows show the job's error in
the card detail; the panel shows new button actions within 1 s of the response; credits column filled
when the endpoint returns a charged amount.

## Done when
```
python -m pytest -q -m "not e2e" -p no:cacheprovider   # FULL suite, 0 failures (main is green at ad93652)
ruff check <every .py you touched>
node --check <every .js you touched>
git status --short                                      # only whitelist files changed
```
Plus tests (Supabase mocked): middleware stores `result_ref` from a 202 body; worker completion updates the
row; update failures are swallowed; DOM: dispatching the event triggers exactly one refresh.

## Evidence  (`docs/specs/evidence/H8-04/`) — pytest + node outputs, README.
