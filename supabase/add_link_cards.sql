-- Community "link cards": share a recipe imported from another website as just its name, the author's
-- credit and a link to the original page. None of the author's text is copied into Community.
-- The admin still approves each one. Run after add_source_credit.sql (safe to run again).
-- New projects get it from schema.sql.

create or replace function public.share_link_to_community(p_recipe uuid) returns uuid
language plpgsql security definer set search_path = public as $$
declare r public.recipes; v_url text; new_id uuid;
begin
  if auth.uid() is null then raise exception 'Please sign in.'; end if;
  select * into r from public.recipes where id = p_recipe and owner_id = auth.uid() and scope = 'private';
  if not found then raise exception 'Recipe not found.'; end if;
  v_url := coalesce(r.body -> 'src' ->> 'url', '');
  if v_url !~* '^https?://' then
    raise exception 'Only recipes imported from a web page can be shared as a link.';
  end if;
  insert into public.recipes (owner_id, scope, status, title, categories, body, source_recipe_id, author_name)
  values (auth.uid(), 'community', 'pending', r.title, r.categories,
          jsonb_build_object(
            'kind', 'link', 'title', r.title, 'categories', to_jsonb(r.categories), 'tags', '[]'::jsonb,
            'yq', '', 'yu', '', 'yr', '', 'dir', '', 'ings', '[]'::jsonb,
            'src', jsonb_build_object('author', coalesce(r.body -> 'src' ->> 'author', ''),
                                      'name', coalesce(r.body -> 'src' ->> 'name', ''), 'url', v_url)),
          r.id, coalesce((select nullif(display_name, '') from public.profiles where id = auth.uid()), 'A chef'))
  returning id into new_id;
  return new_id;
exception when unique_violation then
  raise exception 'This recipe has already been shared and is waiting or live in Community.';
end $$;

revoke execute on function public.share_link_to_community(uuid) from public, anon;
grant execute on function public.share_link_to_community(uuid) to authenticated;
