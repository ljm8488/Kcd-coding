# 심사 코딩마스터 (Python / NiceGUI)

기존 웹앱과 **같은 Supabase 공용 DB**를 쓰는 파이썬 웹 버전입니다. 기존 계정·KCD 마스터·색인 데이터를 그대로 사용합니다.

## 화면
검색·코드 생성 / 조건 설정 / 3권 색인 검색 / AI 자동 코딩 / 코딩 이력 / 개인 코드집 / 대시보드 / 사용자 관리 / KCD 데이터

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
| global / kcdMaster, ltTrees | 상병마스터, 3권 색인 |
| global / orgGemKey | 기관 공용 Gemini 키 |
| user:<Gmail> / cond, history, favs | 사용자별 조건·이력·코드집 |

## 4단계에서 추가된 기능
- **검색**: 결과·코드 / ✦AI 의미 검색 / 유사한 용어 / 연관 질환·해부학적 부위 탭, 성별·연령 검증 표시, 코드별 사용 제한 표시
- **정밀 분석** (`/detail?code=…`): 하위 세분류·같은 계열, 사용 규칙(성별·연령·주진단 불가·배타), 3권 색인 위치, AI 코딩 지침
- **AI 자동 코딩**: 환자 성별·연령, 문서 첨부 + 판독(OCR, 기본 Gemini 비전 · 선택 Google Cloud Vision), 청구 코드 목록, 룰 점검과 제안 적용
- OCR 파일 한도 약 10MB. Google Vision 은 환경변수 `GOOGLE_VISION_KEY` 또는 화면에서 키 입력.

## 아직 없는 기능
영문명 검색(마스터에 영문명 없음), 진료과별 해석 탭, 이미지(해부도) 자동 검색, 개정 버전별 코드 변경 이력.
