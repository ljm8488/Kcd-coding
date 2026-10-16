-- 심사 코딩마스터 — Supabase 초기 설정 (SQL Editor에 붙여 넣고 Run)
-- 마지막 줄의 이메일을 본인 Gmail로 바꾼 뒤 실행하세요.

create table if not exists public.kcm_members (
  email       text primary key,
  org_id      text,
  role        text not null default 'user' check (role in ('sysadmin','orgadmin','user')),
  active      boolean not null default true,
  valid_from  date,
  valid_to    date,
  updated_at  timestamptz not null default now()
);

create table if not exists public.kcm_store (
  scope       text not null,          -- 'global' 또는 'user:이메일'
  key         text not null,
  data        jsonb,
  updated_at  timestamptz not null default now(),
  updated_by  text,
  primary key (scope, key)
);

create or replace function public.kcm_email() returns text
language sql stable as $$ select lower(coalesce(auth.jwt() ->> 'email', '')) $$;

create or replace function public.kcm_role() returns text
language sql stable security definer set search_path = public as $$
  select role from kcm_members
  where email = kcm_email() and active
    and (valid_from is null or valid_from <= current_date)
    and (valid_to   is null or valid_to   >= current_date)
  limit 1 $$;

create or replace function public.kcm_org() returns text
language sql stable security definer set search_path = public as $$
  select org_id from kcm_members where email = kcm_email() limit 1 $$;

alter table public.kcm_members enable row level security;
alter table public.kcm_store   enable row level security;

drop policy if exists m_read  on public.kcm_members;
drop policy if exists m_write on public.kcm_members;
create policy m_read on public.kcm_members for select
  using (email = kcm_email() or kcm_role() = 'sysadmin' or (kcm_role() = 'orgadmin' and org_id = kcm_org()));
create policy m_write on public.kcm_members for all
  using      (kcm_role() = 'sysadmin' or (kcm_role() = 'orgadmin' and org_id = kcm_org() and role <> 'sysadmin'))
  with check (kcm_role() = 'sysadmin' or (kcm_role() = 'orgadmin' and org_id = kcm_org() and role <> 'sysadmin'));

drop policy if exists s_read  on public.kcm_store;
drop policy if exists s_write on public.kcm_store;
create policy s_read on public.kcm_store for select
  using ((scope = 'global' and kcm_role() is not null) or scope = 'user:' || kcm_email());
create policy s_write on public.kcm_store for all
  using      ((scope = 'global' and kcm_role() in ('sysadmin','orgadmin')) or (scope = 'user:' || kcm_email() and kcm_role() is not null))
  with check ((scope = 'global' and kcm_role() in ('sysadmin','orgadmin')) or (scope = 'user:' || kcm_email() and kcm_role() is not null));

-- 다른 PC 변경을 실시간 반영
do $$ begin
  alter publication supabase_realtime add table public.kcm_store;
exception when duplicate_object then null; end $$;
alter table public.kcm_store replica identity full;
grant select, insert, update, delete on public.kcm_store, public.kcm_members to authenticated;
grant execute on function public.kcm_role(), public.kcm_org(), public.kcm_email() to authenticated;

-- 최초 시스템 관리자 (본인 Gmail로 변경)
insert into public.kcm_members (email, org_id, role)
values ('your.name@gmail.com', 'o1', 'sysadmin')
on conflict (email) do update set role = 'sysadmin', active = true;
