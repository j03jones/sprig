-- Admin lists: see and cancel invite codes, see and remove people.
-- Safe to run more than once. Existing projects: paste this into Supabase > SQL Editor > Run.
-- (New projects get the same block from schema.sql.)

-- Remember which code each person signed up with, and let the admin cancel a code early.
alter table public.profiles add column if not exists invite_code text;
alter table public.invites add column if not exists cancelled_at timestamptz;

-- Sign-up gate, now also refusing cancelled codes and recording the code used.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  s public.app_settings;
  inv public.invites;
  v_code text;
  v_name text;
begin
  select * into s from public.app_settings;
  v_name := coalesce(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), split_part(coalesce(new.email, ''), '@', 1));
  v_code := upper(trim(coalesce(new.raw_user_meta_data ->> 'invite_code', '')));

  if lower(coalesce(new.email, '')) = lower(s.admin_email) then
    insert into public.profiles (id, display_name, role) values (new.id, v_name, 'admin');
    return new;
  end if;

  if v_code <> '' then
    select * into inv from public.invites where code = v_code for update;
    if not found or inv.cancelled_at is not null or inv.uses >= inv.max_uses
       or (inv.expires_at is not null and inv.expires_at < now()) then
      raise exception 'That invite code is not valid or has already been used.';
    end if;
    if inv.kind = 'restaurant' then
      if (select count(*) from public.restaurant_members where restaurant_id = inv.restaurant_id)
         >= (select seat_limit from public.restaurants where id = inv.restaurant_id) then
        raise exception 'This restaurant has no free seats left.';
      end if;
      insert into public.profiles (id, display_name, role, invite_code) values (new.id, v_name, 'client', v_code);
      insert into public.restaurant_members (restaurant_id, user_id, member_role)
        values (inv.restaurant_id, new.id, inv.member_role);
    else
      insert into public.profiles (id, display_name, role, invite_code) values (new.id, v_name, 'student', v_code);
    end if;
    update public.invites set uses = uses + 1 where code = v_code;
  elsif s.open_signup then
    insert into public.profiles (id, display_name, role) values (new.id, v_name, 'student');
  else
    raise exception 'Sign-up is by invitation only. Ask for an invite code.';
  end if;
  return new;
end $$;

-- Every invite code, newest first, with who used it.
drop function if exists public.admin_list_invites();
create function public.admin_list_invites()
returns table (code text, kind text, restaurant_name text, member_role text, max_uses int, uses int,
               expires_at timestamptz, cancelled_at timestamptz, created_at timestamptz, status text, used_by text[])
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
                     from public.profiles p where p.invite_code = i.code), '{}')
    from public.invites i
    left join public.restaurants r on r.id = i.restaurant_id
    order by i.created_at desc;
end $$;

-- Stop a code from being used again. People who already joined keep their accounts.
create or replace function public.cancel_invite(p_code text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Only the admin can cancel invite codes.'; end if;
  update public.invites set cancelled_at = now() where code = upper(trim(p_code)) and cancelled_at is null;
  if not found then raise exception 'That code was not found or is already cancelled.'; end if;
end $$;

-- Everyone with an account, newest first.
drop function if exists public.admin_list_people();
create function public.admin_list_people()
returns table (id uuid, display_name text, email text, role text, invite_code text, restaurants text[],
               joined_at timestamptz, email_confirmed boolean, last_sign_in_at timestamptz, private_recipes bigint)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  if not public.is_admin() then raise exception 'Only the admin can see the list of people.'; end if;
  return query
    select p.id, p.display_name, u.email::text, p.role, p.invite_code,
           coalesce((select array_agg(r.name || case when m.member_role = 'owner' then ' (owner)' else '' end order by r.name)
                     from public.restaurant_members m join public.restaurants r on r.id = m.restaurant_id
                     where m.user_id = p.id), '{}'),
           p.created_at, u.email_confirmed_at is not null, u.last_sign_in_at,
           (select count(*) from public.recipes x where x.owner_id = p.id and x.scope = 'private')
    from public.profiles p
    join auth.users u on u.id = p.id
    order by p.created_at desc;
end $$;

-- Delete someone's account and their private recipes. Recipes of theirs that are live in
-- Community stay there (moved to the admin, still credited to them); pending ones are dropped.
create or replace function public.admin_remove_person(p_user uuid) returns void
language plpgsql security definer set search_path = public, auth as $$
declare v_admin uuid := auth.uid();
begin
  if not public.is_admin() then raise exception 'Only the admin can remove people.'; end if;
  if p_user = v_admin then raise exception 'You cannot remove your own account.'; end if;
  if (select role from public.profiles where id = p_user) = 'admin' then
    raise exception 'Admin accounts cannot be removed here.';
  end if;
  if exists (select 1 from public.restaurant_members m
             where m.user_id = p_user and m.member_role = 'owner'
               and (select count(*) from public.restaurant_members o
                    where o.restaurant_id = m.restaurant_id and o.member_role = 'owner') <= 1) then
    raise exception 'This person is the only owner of a restaurant. Make someone else an owner first.';
  end if;
  update public.recipes set owner_id = v_admin, source_recipe_id = null
    where owner_id = p_user and scope = 'community' and status = 'approved';
  delete from auth.users where id = p_user;
  if not found then raise exception 'That person was not found.'; end if;
end $$;

revoke execute on function public.admin_list_invites(), public.cancel_invite(text), public.admin_list_people(),
  public.admin_remove_person(uuid), public.handle_new_user() from public, anon;
grant execute on function public.admin_list_invites(), public.cancel_invite(text), public.admin_list_people(),
  public.admin_remove_person(uuid) to authenticated;
