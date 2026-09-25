-- =============================================================================
-- Migration 012: Editing store table and refund function (Pieza 70 — Bloque E)
-- =============================================================================

-- Update asset_jobs kind constraint to include editing kinds
alter table asset_jobs drop constraint if exists asset_jobs_kind_check;
alter table asset_jobs add constraint asset_jobs_kind_check check (kind in (
  'a_roll_take',
  'transcript',
  'stock',
  'ai_image',
  'ai_video',
  'motion_graphic',
  'music',
  'sfx',
  'raw_render',
  'render',
  'redress'
));

-- Create edits table
create table if not exists edits (
  id              uuid primary key default gen_random_uuid(),
  session_token   text not null references sessions(token) on delete cascade,
  idea_id         text not null,
  version         int not null default 1,
  timeline        jsonb not null default '{}'::jsonb,
  raw_render      jsonb not null default '{}'::jsonb,
  dressing        jsonb not null default '{}'::jsonb,
  captions        jsonb not null default '{}'::jsonb,
  settings        jsonb not null default '{}'::jsonb,
  render          jsonb not null default '{}'::jsonb,
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (session_token, idea_id)
);

-- Trigger for auto-updating updated_at
drop trigger if exists update_edits_updated_at on edits;
create trigger update_edits_updated_at
  before update on edits
  for each row
  execute function update_updated_at_column();

-- RLS enabled without policies: access only from backend with service key
alter table edits enable row level security;

-- Atomic credit refund function
create or replace function refund_credits(p_token text, p_amount integer)
returns integer
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  new_balance integer;
begin
  if p_amount <= 0 then
    raise exception 'Amount must be positive';
  end if;

  update sessions
  set credits = credits + p_amount
  where token = p_token
  returning credits into new_balance;

  return new_balance;
end;
$$;

-- Only the backend (service_role) may refund. Postgres grants EXECUTE to PUBLIC by
-- default and PostgREST exposes public functions to anon/authenticated users, so
-- without this any logged-in user could call refund_credits and mint credits.
revoke execute on function refund_credits(text, integer) from public, anon, authenticated;
grant execute on function refund_credits(text, integer) to service_role;
