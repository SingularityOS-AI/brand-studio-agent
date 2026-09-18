-- =============================================================================
-- Migration 010: Add scripts table (Pieza 32 — Scripting backend)
-- =============================================================================
-- Implements Block C: Scripting with Supabase persistence.
--
-- Table structure:
-- - id: UUID primary key for script identification
-- - session_token: foreign key to sessions table (auth cascade)
-- - idea_id: references catalog idea (stored in data since ideas table doesn't have PK)
-- - status: draft | reviewed | locked
-- - data: jsonb with full script content (frame_zero, scenes, audit, sources)
-- - created_at, updated_at: automatic timestamps
-- - Unique constraint: one script per idea per session (i.e., revision tracking replaced)
--
-- RLS: enabled without policies (backend access with service key, same as catalogs)
-- =============================================================================

create table if not exists scripts (
  id              uuid primary key default gen_random_uuid(),
  session_token   text not null references sessions(token) on delete cascade,
  idea_id         text not null,
  status          text not null default 'draft' check (status in ('draft', 'reviewed', 'locked')),
  data            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique(session_token, idea_id)
);

-- Index for querying by session
create index if not exists scripts_session_token_idx on scripts(session_token);

-- Index for querying by idea_id (for looking up existing scripts)
create index if not exists scripts_idea_id_idx on scripts(idea_id);

-- Index for debugging/monitoring
create index if not exists scripts_updated_at_idx on scripts(updated_at);

-- Trigger for auto-updating updated_at
drop trigger if exists update_scripts_updated_at on scripts;
create trigger update_scripts_updated_at
  before update on scripts
  for each row
  execute function update_updated_at_column();

-- RLS enabled without policies: access only from backend with service key
alter table scripts enable row level security;
