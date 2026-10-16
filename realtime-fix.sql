-- 이미 supabase.sql을 실행한 경우: 실시간 반영을 위해 이 파일만 추가로 실행하세요 (여러 번 실행해도 안전)
do $$ begin
  alter publication supabase_realtime add table public.kcm_store;
exception when duplicate_object then null; end $$;
alter table public.kcm_store replica identity full;
grant select, insert, update, delete on public.kcm_store, public.kcm_members to authenticated;
grant execute on function public.kcm_role(), public.kcm_org(), public.kcm_email() to authenticated;
