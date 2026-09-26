-- =============================================================================
-- Migration 014: Agent Actions Audit (Pieza F-02)
-- =============================================================================

create table if not exists agent_actions (
  id              uuid primary key default gen_random_uuid(),
  session_token   text not null references sessions(token) on delete cascade,
  idea_id         text,
  step            text,
  source          text not null check (source in ('voice', 'button')),
  action          text not null,
  args            jsonb,
  utterance       text,
  restatement     text,
  confirmation    text,
  confirmed_at    timestamptz,
  credits         integer,
  status          text not null check (status in ('proposed', 'queued', 'running', 'done', 'failed', 'cancelled')),
  result_ref      text,
  error           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Trigger for auto-updating updated_at
drop trigger if exists update_agent_actions_updated_at on agent_actions;
create trigger update_agent_actions_updated_at
  before update on agent_actions
  for each row
  execute function update_updated_at_column();

-- RLS
alter table agent_actions enable row level security;

-- Founders read their own rows
drop policy if exists "Users can view their own agent_actions" on agent_actions;
create policy "Users can view their own agent_actions"
  on agent_actions for select
  using (session_token in (select token from sessions where user_id = auth.uid()));

-- Only the backend (service role) writes, so no insert/update policies for authenticated users.
