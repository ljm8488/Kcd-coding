-- 심사 코딩마스터 — 운영 전 데이터베이스 잠금 (현장 사용 필수)
--
-- 왜 필요한가
--   지금은 shared-db.sql 의 정책(shared_rw) 때문에 "공개 키(anon)"만 알면 누구나 모든 데이터를 읽고 고칠 수 있습니다.
--   공개 키는 기존 웹앱(GitHub Pages)의 config.js 에 그대로 들어 있어 인터넷에서 볼 수 있습니다.
--   → 계정(비밀번호 해시) · 환자 코딩 이력 · 기관 Gemini 키가 노출되고, 누구든 계정을 만들거나 데이터를 지울 수 있습니다.
--
-- 순서 (반드시 이 순서로)
--   1) Supabase → Project Settings → API 에서 "service_role" 키를 복사한다. (절대 공개하지 말 것 — 서버에만 둔다)
--   2) Render → Environment → SUPABASE_KEY 의 값을 service_role 키로 바꾸고 재배포한다. 앱이 정상 동작하는지 확인한다.
--   3) 그 다음 아래 SQL 을 Supabase → SQL Editor 에서 실행한다.
--   4) 기존 웹앱(GitHub Pages)은 이후 DB에 접근하지 못합니다 — 파이썬 앱으로 완전히 옮긴 뒤에 실행하세요.
--
-- 되돌리기: shared-db.sql 을 다시 실행하면 이전 상태(전체 공개)로 돌아갑니다.

alter table public.kcm_store enable row level security;

-- 누구에게나 열려 있던 정책 제거
drop policy if exists shared_rw on public.kcm_store;

-- anon / authenticated 에게는 정책이 없으므로 접근이 전부 거부된다.
-- service_role 은 RLS 를 건너뛰므로 서버(파이썬 앱)는 그대로 동작한다.
revoke all on public.kcm_store from anon, authenticated;

-- 확인: 아래 조회가 0건 이어야 정상 (anon 에게 열린 정책이 남아 있지 않음)
-- select policyname, roles from pg_policies where tablename = 'kcm_store';
