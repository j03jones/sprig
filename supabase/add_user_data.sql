-- Per-person app data that follows them between devices (starred recipes for now).
-- Safe to run more than once. Existing projects: paste this into Supabase > SQL Editor > Run.
-- (New projects get the same block from schema.sql.)

create table if not exists public.user_data (
  user_id uuid primary key references auth.users (id) on delete cascade,
  stars jsonb not null default '[]'
    check (jsonb_typeof(stars) = 'array' and jsonb_array_length(stars) <= 5000),
  updated_at timestamptz not null default now()
);

create or replace function public.touch_user_data() returns trigger
language plpgsql set search_path = public as $$
begin new.updated_at := now(); return new; end $$;

drop trigger if exists user_data_touch on public.user_data;
create trigger user_data_touch before insert or update on public.user_data
  for each row execute function public.touch_user_data();

alter table public.user_data enable row level security;
drop policy if exists user_data_own on public.user_data;
create policy user_data_own on public.user_data for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
revoke all on public.user_data from anon;
-- Newer Supabase projects do not expose new tables automatically, so say it explicitly.
grant select, insert, update, delete on public.user_data to authenticated;
revoke execute on function public.touch_user_data() from public, anon;
