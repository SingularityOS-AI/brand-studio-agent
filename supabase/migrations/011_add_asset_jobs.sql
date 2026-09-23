-- =============================================================================
-- Migration 011: Add asset_jobs table and brand-assets bucket (Pieza 50 — Bloque D)
-- =============================================================================
-- Implements Block D: Audiovisual generation foundation.
--
-- Table structure:
-- - id: UUID primary key for job identification
-- - session_token: foreign key to sessions table (auth cascade)
-- - idea_id: references catalog idea
-- - scene_n: scene number (null for video-level assets like music)
-- - kind: asset kind check constraint
-- - status: pending | running | done | failed | cancelled
-- - attempts: retry count
-- - credits: credits to charge on successful completion
-- - charged: whether credits have already been deducted
-- - cost_usd: real estimated/actual cost in USD
-- - provider: provider identifier (e.g. vertex, pexels)
-- - model_id: specific model identifier
-- - input: jsonb with generation/resolution inputs
-- - output: jsonb with results (storage_path, mime, duration_s, meta)
-- - error: failure reason if failed
-- - idempotency_key: unique key to prevent duplicate job creation
-- - created_at, updated_at: automatic timestamps
--
-- RLS: enabled without policies (backend access with service key, same as scripts)
-- Bucket: brand-assets private bucket for binary audiovisual media
-- =============================================================================

create table if not exists asset_jobs (
  id              uuid primary key default gen_random_uuid(),
  session_token   text not null references sessions(token) on delete cascade,
  idea_id         text not null,
  scene_n         int null,
  kind            text not null check (kind in ('a_roll_take','transcript','stock','ai_image','ai_video','motion_graphic','music','sfx')),
  status          text not null default 'pending' check (status in ('pending','running','done','failed','cancelled')),
  attempts        int not null default 0,
  credits         int not null default 0,
  charged         boolean not null default false,
  cost_usd        numeric(8,4) not null default 0,
  provider        text null,
  model_id        text null,
  input           jsonb not null default '{}'::jsonb,
  output          jsonb not null default '{}'::jsonb,
  error           text null,
  idempotency_key text unique,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Index for querying jobs by session and idea
create index if not exists asset_jobs_session_idea_idx on asset_jobs(session_token, idea_id);

-- Index for querying by status (worker claiming pending jobs)
create index if not exists asset_jobs_status_idx on asset_jobs(status);

-- Trigger for auto-updating updated_at
drop trigger if exists update_asset_jobs_updated_at on asset_jobs;
create trigger update_asset_jobs_updated_at
  before update on asset_jobs
  for each row
  execute function update_updated_at_column();

-- RLS enabled without policies: access only from backend with service key
alter table asset_jobs enable row level security;

-- Storage bucket for audiovisual media assets (private)
insert into storage.buckets (id, name, public)
values ('brand-assets', 'brand-assets', false)
on conflict (id) do nothing;
