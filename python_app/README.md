# 심사 코딩마스터 (Python / NiceGUI)

기존 웹앱과 **같은 Supabase 공용 DB**를 쓰는 파이썬 웹 버전입니다. 기존 계정·KCD 마스터·색인 데이터를 그대로 사용합니다.

## 화면
검색·코드 생성 / 조건 설정 / 3권 색인 검색 / AI 자동 코딩 / 코딩 이력 / 개인 코드집 / 대시보드 / 사용자 관리 / KCD 데이터 / 용어 사전

## 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env     # 값 채우기
python run.py            # http://localhost:8080
```
`.env`: `SUPABASE_URL`, `SUPABASE_KEY`(anon/publishable 키), `STORAGE_SECRET`(임의의 긴 문자열),
선택 `GEMINI_API_KEY`(없으면 공용 DB의 기관 키 사용), `GEMINI_MODEL`.

## Render 배포
1. 이 `python_app` 폴더를 GitHub 저장소에 올린다. (저장소 루트에 두면 그대로, 하위 폴더면 Render의 *Root Directory*를 `python_app`으로 지정)
2. Render → New → **Blueprint** (또는 Web Service) → 저장소 선택. `render.yaml`이 자동 적용된다.
3. 환경변수 `SUPABASE_URL`, `SUPABASE_KEY`를 입력한다. `STORAGE_SECRET`은 자동 생성된다.
4. 배포된 `https://….onrender.com` 주소를 다른 PC·사용자에게 공유한다.

무료 플랜은 15분간 접속이 없으면 잠들고 다음 접속 때 약 1분 걸린다.

## 데이터 위치 (Supabase `kcm_store`)
| scope / key | 내용 |
|---|---|
| global / accounts, orgs, sysAdmin | 계정·기관·시스템 관리자 |
| global / kcdMaster, ltTrees | 상병마스터(한글명·영문명), 3권 색인 |
| global / termDict, missedQueries | 현장 용어 사전, 못 찾은 검색어 기록 |
| global / orgGemKey | 기관 공용 Gemini 키 |
| user:<Gmail> / cond, history, favs, uiPref | 사용자별 조건·이력·코드집·화면 설정 |

## 주요 기능
- **검색**: 한글·영문·약어·구어·코드를 한 번에 찾는다(실시간). 용어 사전으로 구어를 공식 상병명으로 풀고, 사전에 없는 `OO암`·`x cancer`는 "OO의 악성 신생물"로 자동 해석한다.
- **AI 자동 코딩**: 문서 첨부·캡처·붙여넣기 → 판독(OCR) → 개인정보 자동 가림 → ② 원문 해석 문서(용어 옆 / 줄 아래 / 좌우 비교, AI 번역) + ③ KCD 코드 후보(주진단·부진단·과거력·의심). 결과는 인쇄·PDF·Excel·한글(.hwpx)로 내려받는다.
- **작업 보관**: 다른 메뉴에 다녀와도 판독·해석 결과가 남는다(서버 메모리, 로그아웃·30분 미사용 시 삭제, 판독 후 첨부 원본은 즉시 삭제).
- **개인정보**: 주민번호·전화·이메일·성명·주소·생년월일·식별번호를 본문·AI 전송·이력·인쇄 모두에서 가린다.

## 점검 · 테스트
```bash
python -m pytest tests -q        # 네트워크 없이 도는 단위 테스트 (개인정보 가림, 용어 해석, 검색 규칙, 내려받기 파일, 작업 보관)
```
검색 정확도는 실제 KCD 데이터로 따로 측정한다(177개 질의 1순위 98%, 튜닝에 쓰지 않은 120개 질의 1순위 98%, 평균 검색 시간 약 3ms).

## 개발용 화면 (저장소에는 올리지 않음)
`dev_preview.py` — 로그인 없이 AI 자동 코딩 화면을 바로 여는 개발 전용 실행기(내 PC 안에서만 열림, 운영에서는 실행 거부).
