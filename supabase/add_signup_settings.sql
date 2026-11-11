-- Open sign-up switch for the app, and invite requests that say whether they are new (so the admin is
-- emailed once per person, not every time they press the button).
-- Run after add_invite_links.sql (safe to run again). New projects get it from schema.sql.

-- Can people create an account without an invite code? (Admin tools > Sign-up switches it.)
create or replace function public.signup_open() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select open_signup from public.app_settings), false);
$$;

-- Same as before, but returns true when this made a new waiting request.
drop function if exists public.request_invite(text, text, text, text);
create function public.request_invite(p_name text, p_email text, p_about text default 'other', p_note text default '')
returns boolean
language plpgsql security definer set search_path = public as $$
declare v_email text := lower(trim(coalesce(p_email, ''))); v_new boolean;
begin
  if v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then raise exception 'Please enter a valid email address.'; end if;
  if length(trim(coalesce(p_name, ''))) = 0 then raise exception 'Please enter your name.'; end if;
  if coalesce(p_about, '') not in ('student', 'restaurant', 'other') then p_about := 'other'; end if;
  if (select count(*) from public.invite_requests where status = 'waiting') >= 200 then
    raise exception 'Too many requests are waiting right now. Please try again later.';
  end if;
  v_new := not exists (select 1 from public.invite_requests where lower(email) = v_email and status = 'waiting');
  insert into public.invite_requests (name, email, about, note)
  values (left(trim(p_name), 80), v_email, p_about, left(trim(coalesce(p_note, '')), 500))
  on conflict (lower(email)) where status = 'waiting'
  do update set name = excluded.name, about = excluded.about, note = excluded.note, created_at = now();
  return v_new;
end $$;

revoke execute on function public.signup_open(), public.request_invite(text, text, text, text) from public;
grant execute on function public.signup_open(), public.request_invite(text, text, text, text) to anon, authenticated;
