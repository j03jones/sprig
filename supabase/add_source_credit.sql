-- Recipes imported from another website (they carry a credit: body.src.author / body.src.url) stay in
-- the person's private recipes: the app hides the Share button for them and this refuses them too.
-- Run after add_photos.sql. Existing projects run this once in the SQL Editor (safe to run again).
-- New projects get it from schema.sql.

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
  if coalesce(r.body -> 'src' ->> 'url', '') <> '' or coalesce(r.body -> 'src' ->> 'author', '') <> '' then
    raise exception 'This recipe came from another website, so it stays private. Share a link to the original instead.';
  end if;
  insert into public.recipes (owner_id, scope, status, title, categories, body, source_recipe_id, author_name, photo)
  values (auth.uid(), 'community', 'pending', r.title, r.categories, r.body, r.id,
          coalesce((select nullif(display_name, '') from public.profiles where id = auth.uid()), 'A chef'), r.photo)
  returning id into new_id;
  return new_id;
exception when unique_violation then
  raise exception 'This recipe has already been shared and is waiting or live in Community.';
end $$;
