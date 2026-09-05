-- =============================================================================
-- BRAND STUDIO AGENT — Supabase Schema
-- =============================================================================
-- This schema provides persistent session storage for the Guard layer.
-- Run this SQL in your Supabase SQL editor to set up the table.
-- =============================================================================

-- Sessions table: stores session tokens and remaining credits
create table if not exists sessions (
  token        text primary key,
  credits      integer not null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Index on created_at for potential cleanup queries (e.g., old sessions)
create index if not exists sessions_created_at_idx on sessions (created_at);

-- =============================================================================
-- ATOMIC CREDIT DEDUCTION SQL
-- =============================================================================
-- This update atomically deducts N credits from a session, preventing
-- race conditions where concurrent requests could spend the same credit.
-- 
-- The WHERE clause ensures:
--   1. The session exists (token matches)
--   2. The session has enough credits (credits >= :n)
-- 
-- The RETURNING clause gives us the new balance so we know if it worked.
-- 
-- Python usage example (with psycopg3-style parameters):
-- 
--   cursor.execute("""
--     update sessions
--     set credits = credits - %s,
--         updated_at = now()
--     where token = %s and credits >= %s
--     returning credits
--   """, (amount, token, amount))
--   row = cursor.fetchone()
--   if not row:
--     raise InsufficientCreditsError()
--   return row[0]
-- 
-- This ensures that no two concurrent deductions can succeed if the
-- balance would go negative — only one will match the WHERE clause.
-- =============================================================================

-- =============================================================================
-- RLS (Row Level Security) — PENDING
-- =============================================================================
-- Currently, the server uses the Supabase service role key (supabase_admin)
-- to access this table directly. No client-side access is needed for this phase.
-- 
-- RLS will be added in a future piece if:
--   - User accounts are implemented (JWT-based auth)
--   - The browser needs to read session state directly (unlikely with httpOnly cookies)
-- 
-- For now, RLS is disabled and the table is accessed server-side only.
-- =============================================================================

-- Trigger to auto-update updated_at (optional, for cleanliness)
create or replace function update_updated_at_column()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger update_sessions_updated_at
  before update on sessions
  for each row
  execute function update_updated_at_column();

-- =============================================================================
-- ATOMIC CREDIT DEDUCTION FUNCTION
-- =============================================================================
-- This function atomically deducts credits from a session and returns the
-- new balance, or NULL if the session doesn't exist or has insufficient credits.
--
-- Call via: supabase.rpc('deduct_credits', {'p_token': '...', 'p_amount': 1})
--
-- Returns: new credit balance (int) or NULL if deduction failed
-- =============================================================================

create or replace function deduct_credits(p_token text, p_amount integer default 1)
returns integer
language plpgsql
security invoker
set search_path = public, pg_temp  -- sin esto la funcion es secuestrable via search_path
as $$
declare
  new_balance integer;
begin
  -- Ensure amount is positive
  if p_amount <= 0 then
    raise exception 'Amount must be positive';
  end if;

  -- Atomic update: deduct credits only if session exists and has enough balance
  update sessions
  set credits = credits - p_amount,
      updated_at = now()
  where token = p_token and credits >= p_amount
  returning credits into new_balance;

  -- Return new balance (NULL if no rows updated)
  return new_balance;
end;
$$;

-- RLS activado y sin politicas: nadie entra desde el navegador.
-- El unico acceso es el backend con la service key, que salta RLS por diseno.
alter table sessions enable row level security;
