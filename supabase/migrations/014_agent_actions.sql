-- =============================================================================
-- Migration 014: agent_actions table (Block F — Agentic Mode audit trail, F-02)
-- =============================================================================
-- Audit trail for every pipeline action, voice and button (spec "Data" in
-- docs/specs/F/spec.md). Follows the same pattern already used by
-- 007_add_catalogs.sql / 010_add_scripts.sql / 012_editing.sql: RLS enabled
-- WITHOUT client policies -- the backend is the only reader/writer, always
-- via the service key, and it always filters by session_token itself before
-- returning rows (see app/agent/store.py). Every other table in this schema
-- uses that same backend-mediated model instead of a client-side auth.uid()
-- policy, so agent_actions keeps it too rather than introducing a new access
-- pattern the day before the deadline.
--
-- THE CEO APPLIES THIS MIGRATION MANUALLY. No agent runs it.
-- =============================================================================

create table if not exists agent_actions (
  id              uuid primary key default gen_random_uuid(),
  session_token   text not null references sessions(token) on delete cascade,
  idea_id         text,
  step            text not null,
  source          text not null check (source in ('voice', 'button')),
  action          text not null,
  args            jsonb not null default '{}'::jsonb,
  utterance       text,
  restatement     text,
  confirmation    text,
  confirmed_at    timestamptz,
  credits         integer,
  status          text not null default 'proposed' check (
    status in ('proposed', 'queued', 'running', 'done', 'failed', 'cancelled')
  ),
  result_ref      text,
  error           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Same listing shape as GET /api/agent/actions?idea_id=&limit=: own session,
-- optionally one idea, newest first.
create index if not exists agent_actions_session_token_idx on agent_actions(session_token);
create index if not exists agent_actions_idea_id_idx on agent_actions(idea_id);
create index if not exists agent_actions_created_at_idx on agent_actions(created_at desc);

-- Trigger for auto-updating updated_at (reuses the function from schema.sql,
-- same as edits/scripts/catalogs).
drop trigger if exists update_agent_actions_updated_at on agent_actions;
create trigger update_agent_actions_updated_at
  before update on agent_actions
  for each row
  execute function update_updated_at_column();

-- RLS enabled without policies: access only from the backend with the service key.
alter table agent_actions enable row level security;
