# F-02 — `agent_actions` table + store + audit middleware + list API

Depends on: —
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
The audit trail for every pipeline action (voice and button), per spec "Data".

## Files you may touch
- `supabase/migrations/014_agent_actions.sql` (new; **the CEO applies it** — you never run it)
- `app/agent/__init__.py`, `app/agent/store.py`, `app/agent/router.py`, `app/agent/middleware.py` (new)
- `app/main.py` (include the router + add the middleware; nothing else)
- `tests/test_agent_f02_audit.py` (new)

## Behaviour
- Table per spec; RLS: `select` own rows (same session/user mapping as other tables — copy
  the pattern of `012_editing.sql`); no insert/update policy for `authenticated`
  (backend writes with the service role).
- `POST /api/agent/actions` (auth required) creates a `proposed`/`queued` voice action with
  `utterance, restatement, action, args, step, idea_id, credits` -> `{id}`.
- `PATCH /api/agent/actions/{id}` (auth, own row) -> `confirmation, confirmed_at, status`.
- `GET /api/agent/actions?idea_id=&limit=50` -> newest first.
- Middleware: for POST/PATCH/DELETE under `/api/catalog`, `/api/script`,
  `/api/audiovisual`, `/api/editing` (excluding `/api/editing/internal`) and
  `/api/soul/generate`: if header `X-Agent-Action-Id` belongs to the caller -> update that
  row (status from response: 202 -> queued, 2xx -> done, else failed + error); else insert a
  `button` row (`action` = method + route template). Never blocks or changes the response;
  store failures are logged and swallowed. Never logs request bodies with PHI; `args` only
  for voice rows (already sanitized by the registry).

## Done when
Tests with the Supabase client mocked: button request creates a row; header request
updates the voice row; failure path marks failed; middleware exception doesn't break the
endpoint; list returns only the caller's rows. Evidence in `docs/specs/evidence/F-02/`.
