begin;
create table public.pilot_objects (
 user_id uuid not null references auth.users(id) on delete cascade,
 object_key text not null check(length(object_key) between 1 and 100),
 parent_story text not null check(length(parent_story) between 1 and 200),
 title text not null check(length(title) between 1 and 200),
 object_type text not null check(length(object_type) between 1 and 60),
 tools text[] not null default '{}',
 evidence jsonb not null default '[]' check(jsonb_typeof(evidence)='array'),
 workflow text[] not null default '{}',
 related_keys text[] not null default '{}',
 created_at timestamptz not null default now(),
 primary key(user_id,object_key)
);
alter table public.pilot_objects enable row level security;
revoke all on public.pilot_objects from public,anon,authenticated;
grant select,delete on public.pilot_objects to authenticated;
grant all on public.pilot_objects to service_role;
create policy objects_owner_read on public.pilot_objects for select to authenticated using ((select auth.uid())=user_id);
create policy objects_owner_delete on public.pilot_objects for delete to authenticated using ((select auth.uid())=user_id);
commit;