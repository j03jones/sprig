-- Easier invites: invite links / QR codes, emailed invites and "request an invite".
-- Run after add_link_cards.sql (safe to run again). New projects get it from schema.sql.

-- Which address an invite was emailed to (blank for codes shared by link or QR).
alter table public.invites add column if not exists email text;

-- What a join link shows before someone signs up: whether the code still works and what it is for.
-- Anyone can ask, but only about a code they already have, and it never says who made or used it.
create or replace function public.invite_info(p_code text)
returns table (status text, kind text, restaurant_name text, member_role text)
language plpgsql stable security definer set search_path = public as $$
declare inv public.invites;
begin
  select * into inv from public.invites where code = upper(trim(coalesce(p_code, '')));
  if not found then
    return query select 'not found'::text, null::text, null::text, null::text;
    return;
  end if;
  return query select
    case when inv.cancelled_at is not null then 'cancelled'
         when inv.uses >= inv.max_uses then 'used up'
         when inv.expires_at is not null and inv.expires_at < now() then 'expired'
         else 'active' end,
    inv.kind,
    (select r.name from public.restaurants r where r.id = inv.restaurant_id),
    inv.member_role;
end $$;

-- People asking for an invite. Only the admin can read them.
create table if not exists public.invite_requests (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 1 and 80),
  email text not null check (length(email) between 3 and 200),
  about text not null default 'other' check (about in ('student', 'restaurant', 'other')),
  note text not null default '' check (length(note) <= 500),
  status text not null default 'waiting' check (status in ('waiting', 'invited', 'dismissed')),
  created_at timestamptz not null default now(),
  handled_at timestamptz
);
create unique index if not exists invite_requests_one_waiting on public.invite_requests (lower(email)) where status = 'waiting';
alter table public.invite_requests enable row level security;
drop policy if exists invite_requests_admin on public.invite_requests;
create policy invite_requests_admin on public.invite_requests for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
revoke all on public.invite_requests from anon;

-- Ask for an invite (no account needed). Asking again with the same email updates the waiting request.
create or replace function public.request_invite(p_name text, p_email text, p_about text default 'other', p_note text default '')
returns void
language plpgsql security definer set search_path = public as $$
declare v_email text := lower(trim(coalesce(p_email, '')));
begin
  if v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then raise exception 'Please enter a valid email address.'; end if;
  if length(trim(coalesce(p_name, ''))) = 0 then raise exception 'Please enter your name.'; end if;
  if coalesce(p_about, '') not in ('student', 'restaurant', 'other') then p_about := 'other'; end if;
  if (select count(*) from public.invite_requests where status = 'waiting') >= 200 then
    raise exception 'Too many requests are waiting right now. Please try again later.';
  end if;
  insert into public.invite_requests (name, email, about, note)
  values (left(trim(p_name), 80), v_email, p_about, left(trim(coalesce(p_note, '')), 500))
  on conflict (lower(email)) where status = 'waiting'
  do update set name = excluded.name, about = excluded.about, note = excluded.note, created_at = now();
end $$;

-- Every invite code, newest first, with who used it and where it was emailed.
drop function if exists public.admin_list_invites();
create function public.admin_list_invites()
returns table (code text, kind text, restaurant_name text, member_role text, max_uses int, uses int,
               expires_at timestamptz, cancelled_at timestamptz, created_at timestamptz, status text, used_by text[],
               email text)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Only the admin can see invite codes.'; end if;
  return query
    select i.code, i.kind, r.name, i.member_role, i.max_uses, i.uses, i.expires_at, i.cancelled_at, i.created_at,
           case when i.cancelled_at is not null then 'cancelled'
                when i.uses >= i.max_uses then 'used up'
                when i.expires_at is not null and i.expires_at < now() then 'expired'
                else 'active' end,
           coalesce((select array_agg(coalesce(nullif(p.display_name, ''), 'Someone') order by p.created_at)
                     from public.profiles p where p.invite_code = i.code), '{}'),
           i.email
    from public.invites i
    left join public.restaurants r on r.id = i.restaurant_id
    order by i.created_at desc;
end $$;

revoke execute on function public.invite_info(text), public.request_invite(text, text, text, text),
  public.admin_list_invites() from public;
grant execute on function public.invite_info(text), public.request_invite(text, text, text, text) to anon, authenticated;
grant execute on function public.admin_list_invites() to authenticated;
grant select, insert, update, delete on public.invite_requests to authenticated;
