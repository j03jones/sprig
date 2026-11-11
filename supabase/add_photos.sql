-- Photos: a dish photo on recipes and a profile photo for each person.
-- Safe to run more than once. Existing projects: paste this into Supabase > SQL Editor > Run.
-- (New projects get the same block from schema.sql.)
--
-- Files live in one private Storage bucket, "photos":
--   recipes/<person id>/<random>.jpg   dish photo on a recipe in the database (recipes.photo points at it)
--   library/<person id>/<random>.jpg   someone's own photo of a built-in library recipe (user_data.library_photos)
--   avatars/<person id>/<random>.jpg   profile photo (profiles.avatar)
-- Anyone signed in may see profile photos. A dish photo can be seen by whoever can see a recipe
-- that uses it, so private stays private and Community photos appear once the recipe is approved.
-- Library photos are only ever visible to the person who took them.

alter table public.recipes add column if not exists photo text;
alter table public.profiles add column if not exists avatar text;
alter table public.user_data add column if not exists library_photos jsonb not null default '{}'
  check (jsonb_typeof(library_photos) = 'object');

-- A recipe can only point at a photo its author uploaded (otherwise pointing at someone
-- else's file would be a way to read it).
create or replace function public.guard_recipe_photo() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.photo is not null
     and (tg_op = 'INSERT' or new.photo is distinct from old.photo)
     and not public.is_admin()
     and new.photo not like 'recipes/' || auth.uid()::text || '/%' then
    raise exception 'That photo does not belong to you.';
  end if;
  return new;
end $$;
drop trigger if exists guard_recipe_photo on public.recipes;
create trigger guard_recipe_photo before insert or update on public.recipes
  for each row execute function public.guard_recipe_photo();

-- Sharing to Community copies the photo along with the recipe.
create or replace function public.submit_to_community(p_recipe uuid, p_confirm boolean) returns uuid
language plpgsql security definer set search_path = public as $$
declare r public.recipes; new_id uuid;
begin
  if auth.uid() is null then raise exception 'Please sign in.'; end if;
  if p_confirm is not true then
    raise exception 'Please confirm this is your own recipe or that you have the right to share it.';
  end if;
  select * into r from public.recipes where id = p_recipe and owner_id = auth.uid() and scope = 'private';
  if not found then raise exception 'Recipe not found.'; end if;
  insert into public.recipes (owner_id, scope, status, title, categories, body, source_recipe_id, author_name, photo)
  values (auth.uid(), 'community', 'pending', r.title, r.categories, r.body, r.id,
          coalesce((select nullif(display_name, '') from public.profiles where id = auth.uid()), 'A chef'), r.photo)
  returning id into new_id;
  return new_id;
exception when unique_violation then
  raise exception 'This recipe has already been shared and is waiting or live in Community.';
end $$;

-- Profile photos of the people whose recipes are live in Community (shown next to "Shared by").
create or replace function public.community_avatars()
returns table (id uuid, avatar text)
language sql stable security definer set search_path = public as $$
  select distinct p.id, p.avatar
  from public.recipes r join public.profiles p on p.id = r.owner_id
  where r.scope = 'community' and r.status = 'approved' and p.avatar is not null and auth.uid() is not null;
$$;

-- The bucket: private, photos only, at most 2 MB each (the app shrinks photos to about 200 KB).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', false, 2097152, array['image/jpeg', 'image/webp', 'image/png'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists photos_read on storage.objects;
create policy photos_read on storage.objects for select to authenticated using (
  bucket_id = 'photos' and (
    public.is_admin()
    or storage.objects.name like 'avatars/%'
    or storage.objects.name like 'library/' || auth.uid()::text || '/%'
    or storage.objects.name like 'recipes/' || auth.uid()::text || '/%'
    -- recipes' own access rules apply inside this check, so it only finds recipes this person may see
    or exists (select 1 from public.recipes r where r.photo = storage.objects.name)
  ));

drop policy if exists photos_insert on storage.objects;
create policy photos_insert on storage.objects for insert to authenticated with check (
  bucket_id = 'photos' and (
    public.is_admin()
    or storage.objects.name like 'avatars/' || auth.uid()::text || '/%'
    or storage.objects.name like 'library/' || auth.uid()::text || '/%'
    or storage.objects.name like 'recipes/' || auth.uid()::text || '/%'
  ));

drop policy if exists photos_update on storage.objects;
create policy photos_update on storage.objects for update to authenticated using (
  bucket_id = 'photos' and (
    public.is_admin()
    or storage.objects.name like 'avatars/' || auth.uid()::text || '/%'
    or storage.objects.name like 'library/' || auth.uid()::text || '/%'
    or storage.objects.name like 'recipes/' || auth.uid()::text || '/%'
  ));

drop policy if exists photos_delete on storage.objects;
create policy photos_delete on storage.objects for delete to authenticated using (
  bucket_id = 'photos' and (
    public.is_admin()
    or storage.objects.name like 'avatars/' || auth.uid()::text || '/%'
    or storage.objects.name like 'library/' || auth.uid()::text || '/%'
    or storage.objects.name like 'recipes/' || auth.uid()::text || '/%'
  ));

revoke execute on function public.guard_recipe_photo(), public.community_avatars(),
  public.submit_to_community(uuid, boolean) from public, anon;
grant execute on function public.community_avatars(), public.submit_to_community(uuid, boolean) to authenticated;
