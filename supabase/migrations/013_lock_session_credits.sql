-- =============================================================================
-- Migration 013: users can no longer write their own credits (security hotfix)
-- =============================================================================
-- Found 2026-09-25 during Bloque E QA. The frontend ships supabase-js with the
-- publishable key and a logged-in user's JWT. With these policies any user could
-- insert a session with arbitrary credits, raise the credits of their own row, or
-- call accrue_credits()/deduct_credits() through PostgREST. The backend never
-- needed them: it uses the service key, which bypasses RLS, and the frontend never
-- writes to sessions. Reading one's own session stays allowed.

drop policy if exists "Users can insert their own sessions" on sessions;
drop policy if exists "Users can update their own sessions" on sessions;
drop policy if exists "Users can delete their own sessions" on sessions;

revoke execute on function accrue_credits(text, integer) from public, anon, authenticated;
revoke execute on function deduct_credits(text, integer) from public, anon, authenticated;
grant execute on function accrue_credits(text, integer) to service_role;
grant execute on function deduct_credits(text, integer) to service_role;
