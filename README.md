# 심사 코딩마스터 — 무료 웹 배포 안내

여러 PC에서 같은 데이터로 쓰기 위한 구성입니다. 모두 무료 플랜입니다.

| 역할 | 서비스 |
|---|---|
| 웹 화면 | GitHub Pages |
| 로그인 · 공용 데이터 | Supabase (Google 로그인 + DB) |
| AI 의미 검색 | Gemini (키는 Supabase 서버에 보관) |

## 올릴 파일 (이 폴더 그대로)
```
index.html        ← 시스템 전체 (한 파일)
config.js         ← 연결 정보 (2단계에서 입력)
supabase.sql      ← DB 초기 설정
supabase/functions/gemini/index.ts  ← Gemini 서버 함수
```

## 1. GitHub Pages
1. GitHub → New repository (예: `kcd-coding`, **Public**)
2. 이 폴더의 파일을 업로드 → Commit
3. Settings → Pages → Branch `main` / `(root)` → Save
4. 1~2분 뒤 주소 생성: `https://계정명.github.io/kcd-coding/`

이 단계까지만 하면 각 PC 브라우저 저장 방식으로 동작합니다.

## 2. Supabase (공용 데이터)
1. supabase.com → GitHub로 로그인 → New project
2. **SQL Editor** → `supabase.sql` 내용 붙여넣기 → 마지막 줄 이메일을 **본인 Gmail**로 바꾸고 Run
3. **Project Settings → API** 에서 `Project URL`, `anon public` 키 복사
4. GitHub의 `config.js`를 열어 연필 아이콘으로 수정:
   ```js
   supabaseUrl: "https://xxxx.supabase.co",
   supabaseAnonKey: "eyJ...",
   ```

## 3. Google 로그인
1. console.cloud.google.com → API 및 서비스 → 사용자 인증 정보 → **OAuth 클라이언트 ID** (웹 애플리케이션)
2. 승인된 리디렉션 URI: `https://xxxx.supabase.co/auth/v1/callback`
3. 발급된 클라이언트 ID · 보안 비밀을 Supabase → **Authentication → Providers → Google** 에 입력 → 사용 설정
4. Supabase → Authentication → **URL Configuration** → Site URL에 GitHub Pages 주소 입력

## 4. Gemini 공용 키 (선택)
1. aistudio.google.com/apikey 에서 무료 키 발급
2. Supabase → **Edge Functions** → Deploy new function → 이름 `gemini` → `index.ts` 내용 붙여넣기 → Deploy
3. Edge Functions → **Secrets** → `GEMINI_API_KEY` = 발급한 키

설정하면 사용자는 키 없이 AI 의미 검색을 씁니다. 등록 · 활성 · 유효기간 내 계정만 호출할 수 있습니다.

## 처음 접속
1. GitHub Pages 주소 → **Google 계정으로 로그인 (공용 데이터)** → 1단계에서 넣은 관리자 Gmail로 로그인
2. 처음 로그인한 PC의 기관 · 부서 · 직책 · 계정 데이터가 공용 저장소 초기값으로 올라갑니다
3. 사용자 관리에서 Gmail 계정을 등록하면 그 사람도 바로 로그인할 수 있습니다

## 동작 방식
- 기관 · 직책 · 계정 · 색인 트리: 모든 사용자 공유 (관리자만 수정)
- 코딩 이력 · 개인 코드집 · 검색 조건: 계정별 저장, 어느 PC에서나 동일
- 다른 PC의 변경은 실시간 반영, 좌측 메뉴 아래 "데이터 · 공용 동기화됨 HH:MM" 표시
- 업로드한 소견서 · 진단서 이미지와 판독 원문은 서버에 올라가지 않습니다

## 무료 플랜 한도
- Supabase: DB 500MB. 7일간 접속이 없으면 일시정지 → 대시보드에서 Restore
- Gemini: 분당 · 일일 호출 한도. 같은 검색어는 저장된 결과 재사용
- GitHub Pages: Public 저장소 필요. 환자 식별정보는 저장하지 마세요
