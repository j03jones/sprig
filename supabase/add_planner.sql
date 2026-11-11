-- Meal plan and shopping list that follow the person between devices (v0.14.0).
-- Safe to run more than once. Run after add_user_data.sql. Existing projects: paste this into
-- Supabase > SQL Editor > Run. (New projects get the same block from schema.sql.)
--
-- One JSON document per person: { "at": <ms>, "plan": { "days": {...} }, "shop": { "items": [...],
-- "done": [...], "extras": [...] } }. Only its owner can read or write it (the user_data_own policy).

alter table public.user_data add column if not exists planner jsonb not null default '{}'
  check (jsonb_typeof(planner) = 'object' and pg_column_size(planner) <= 262144);
