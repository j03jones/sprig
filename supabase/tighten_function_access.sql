-- Tighten who may call the database functions (v0.13.0). Safe to run more than once.
--
-- Nothing here was exploitable: admin_list_invites() refuses anyone who is not the admin, and
-- trigger functions cannot be called through the API at all. But Supabase grants EXECUTE on new
-- functions to the signed-out role (anon) by default, and "revoke ... from public" does not take
-- that grant away, so the Supabase security advisor flagged them. This removes the unneeded grants.

-- Admin-only list: signed-out visitors have no business calling it.
revoke execute on function public.admin_list_invites() from public, anon;
grant execute on function public.admin_list_invites() to authenticated;

-- Trigger functions run from their triggers whatever the caller's rights are; nobody calls them directly.
revoke execute on function
  public.handle_new_user(), public.guard_profile(), public.guard_recipe_update(),
  public.enforce_free_limit(), public.guard_recipe_photo(), public.touch_user_data()
  from public, anon, authenticated;
