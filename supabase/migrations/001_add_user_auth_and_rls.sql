-- ============================================================================= 
-- Migration 001: Add Google OAuth User Auth and RLS 
-- ============================================================================= 
-- This migration adds user_id columns to sessions and brand_brains tables, 
-- implements real RLS policies, and adds a platform_spend table to track 
-- the global credit cap. 
-- ============================================================================= 

-- Step 1: Add user_id column to sessions table 
alter table sessions add column if not exists user_id uuid references auth.users(id) on delete cascade; 

-- Step 2: Add user_id column to brand_brains table 
-- Note: brand_brains.session_token references sessions(token), so we can derive user_id 
-- from sessions table through the foreign key relationship. However, for performance and 
-- direct RLS policies, we'll add user_id as a denormalized column. 
alter table brand_brains add column if not exists user_id uuid references auth.users(id) on delete cascade; 

-- Step 3: Create a function to auto-populate user_id in brand_brains when session_token changes 
create or replace function sync_user_id_to_brain() 
returns trigger 
language plpgsql 
security invoker 
set search_path = public, pg_temp 
as $$ 
begin 
  -- When brand_brains row is created or updated, sync user_id from sessions table 
  update brand_brains 
  set user_id = (select user_id from sessions where token = new.session_token) 
  where session_token = new.session_token and user_id is null; 
  return new; 
end; 
$$; 

-- Step 4: Create triggers to sync user_id 
drop trigger if exists sync_brand_brain_user_id on brand_brains; 
create trigger sync_brand_brain_user_id 
  before insert or update of session_token on brand_brains 
  for each row 
  execute function sync_user_id_to_brain(); 

-- Step 5: Create platform_spend table to track total credits granted 
create table if not exists platform_spend ( 
  id serial primary key, 
  total_credits_granted bigint not null default 0, 
  total_usd_granted numeric not null default 0, 
  updated_at timestamptz not null default now() 
); 

-- Step 6: Insert initial row if table was just created 
insert into platform_spend (total_credits_granted, total_usd_granted) 
select 0, 0 
where not exists (select 1 from platform_spend); 

-- Step 7: Drop existing RLS policies (if any) 
drop policy if exists "Users can view their own sessions" on sessions; 
drop policy if exists "Users can insert their own sessions" on sessions; 
drop policy if exists "Users can update their own sessions" on sessions; 
drop policy if exists "Users can delete their own sessions" on sessions; 

drop policy if exists "Users can view their own brand_brains" on brand_brains; 
drop policy if exists "Users can insert their own brand_brains" on brand_brains; 
drop policy if exists "Users can update their own brand_brains" on brand_brains; 
drop policy if exists "Users can delete their own brand_brains" on brand_brains; 

-- Step 8: Create real RLS policies for sessions table 
create policy "Users can view their own sessions" 
  on sessions for select 
  using (auth.uid() = user_id); 

create policy "Users can insert their own sessions" 
  on sessions for insert 
  with check (auth.uid() = user_id); 

create policy "Users can update their own sessions" 
  on sessions for update 
  using (auth.uid() = user_id) 
  with check (auth.uid() = user_id); 

create policy "Users can delete their own sessions" 
  on sessions for delete 
  using (auth.uid() = user_id); 

-- Step 9: Create real RLS policies for brand_brains table 
create policy "Users can view their own brand_brains" 
  on brand_brains for select 
  using (auth.uid() = user_id); 

create policy "Users can insert their own brand_brains" 
  on brand_brains for insert 
  with check (auth.uid() = user_id); 

create policy "Users can update their own brand_brains" 
  on brand_brains for update 
  using (auth.uid() = user_id) 
  with check (auth.uid() = user_id); 

create policy "Users can delete their own brand_brains" 
  on brand_brains for delete 
  using (auth.uid() = user_id); 

-- Step 10: Update deduct_credits function to return just credits 
-- (No changes needed - function already works correctly with RLS) 

-- Step 11: Create function to grant initial credits to a new user 
create or replace function grant_initial_credits(p_user_id uuid) 
returns integer 
language plpgsql 
security invoker 
set search_path = public, pg_temp 
as $$ 
declare 
  v_existing_credits integer; 
  v_total_credits_granted bigint; 
  v_platform_cap_credits bigint := 12000; -- $120 USD = 12,000 credits (1 credit = $0.01) 
begin 
  -- Check if user already has a session 
  select sum(credits) into v_existing_credits 
  from sessions 
  where user_id = p_user_id; 
  
  -- If user already has credits, return the existing balance 
  if v_existing_credits is not null then 
    return v_existing_credits; 
  end if; 
  
  -- Check if platform cap has been reached 
  select total_credits_granted into v_total_credits_granted 
  from platform_spend 
  limit 1; 
  
  if v_total_credits_granted >= v_platform_cap_credits then 
    raise exception 'Platform credit cap reached ($120 USD).'; 
  end if; 
  
  -- Check if granting 250 credits would exceed the cap 
  if v_total_credits_granted + 250 > v_platform_cap_credits then 
    raise exception 'Not enough platform credits remaining to grant full bonus.'; 
  end if; 
  
  -- Insert new session with initial credits (250 credits = $2.50 USD) 
  insert into sessions (token, credits, user_id) 
  values (encode(gen_random_bytes(32), 'hex'), 250, p_user_id) 
  returning credits into v_existing_credits; 
  
  -- Update platform spend 
  update platform_spend 
  set total_credits_granted = total_credits_granted + 250, 
      total_usd_granted = total_usd_granted + 2.50, 
      updated_at = now(); 
  
  return v_existing_credits; 
end; 
$$; 

-- Step 12: Create function to get or create user session 
create or replace function get_or_create_user_session(p_user_id uuid) 
returns text 
language plpgsql 
security invoker 
set search_path = public, pg_temp 
as $$ 
declare 
  v_user_credits integer; 
  v_session_token text; 
begin 
  -- Check if user has any sessions with credits 
  select s.token into v_session_token 
  from sessions s 
  where s.user_id = p_user_id and s.credits > 0 
  order by s.created_at desc 
  limit 1; 
  
  if v_session_token is not null then 
    return v_session_token; 
  end if; 
  
  -- No existing session with credits, grant initial credits 
  v_user_credits := grant_initial_credits(p_user_id); 
  
  -- Return the token of the newly created session 
  select s.token into v_session_token 
  from sessions s 
  where s.user_id = p_user_id 
  order by s.created_at desc 
  limit 1; 
  
  return v_session_token; 
end; 
$$; 
