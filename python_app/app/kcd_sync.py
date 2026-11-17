"""공공데이터포털의 건강보험심사평가원 ‘상병마스터’(KCD 기반)를 자동으로 불러온다.

- 출처: 공공데이터포털 15067467 (건강보험심사평가원_상병마스터) — 공공누리 1유형(출처 표시) 이용 가능
- 방식: 공식 OpenAPI(ODcloud). 무료 인증키(서비스키)가 필요하다 → data.go.kr 에서 이 데이터셋 ‘활용신청’ 후 발급
- 가져오는 항목: 상병기호 · 한글명 · 영문명 · 완전코드구분 · 주상병사용구분 · 법정감염병구분 · 성별구분 · 상한연령 · 하한연령 · 양한방구분
"""
from __future__ import annotations

import re
from urllib.parse import unquote

import httpx

DATASET_ID = "15067467"
DOCS_URL = f"https://infuser.odcloud.kr/oas/docs?namespace={DATASET_ID}/v1"
API_BASE = "https://api.odcloud.kr/api"
SOURCE_NOTE = "출처: 건강보험심사평가원 상병마스터 (공공데이터포털, 공공누리 제1유형 출처표시)"
PER_PAGE = 1000

FIELD_ALIASES = {
    "code": ("상병기호", "상병코드", "코드"),
    "ko": ("한글명", "상병명", "한글상병명"),
    "en": ("영문명", "영문상병명"),
    "complete": ("완전코드구분",),
    "primary": ("주상병사용구분",),
    "infect": ("법정감염병구분",),
    "sex": ("성별구분",),
    "max": ("상한연령",),
    "min": ("하한연령",),
    "kind": ("양한방구분",),
}


def clean_key(key: str) -> str:
    """‘Encoding’ 키를 붙여 넣어도 동작하게 한 번 디코딩한다."""
    return unquote((key or "").strip())


def dotted(code: str) -> str:
    """상병기호(점 없음: A000) → 이 앱의 표기(A00.0). 3자리 대분류는 그대로 둔다."""
    c = re.sub(r"\s+", "", str(code or "")).upper().replace(".", "")
    return f"{c[:3]}.{c[3:]}" if len(c) > 3 else c


def _pick(rec: dict, names: tuple[str, ...]) -> str:
    norm = {re.sub(r"\s+", "", str(k)): v for k, v in rec.items()}
    for n in names:
        if n in norm and norm[n] is not None:
            return str(norm[n]).strip()
    return ""


def _num(s: str) -> int | None:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def extras_of(rec: dict) -> dict:
    """성별·연령 제한, 주상병 사용 여부 같은 부가 정보 (비어 있으면 생략)."""
    e = {}
    sex = _pick(rec, FIELD_ALIASES["sex"])
    if sex and sex not in ("0", "-", "없음", "N"):
        e["s"] = sex
    mn, mx = _num(_pick(rec, FIELD_ALIASES["min"])), _num(_pick(rec, FIELD_ALIASES["max"]))
    if mn is not None and mn > 0:
        e["mn"] = mn
    if mx is not None and 0 < mx < 999:
        e["mx"] = mx
    for k, names in (("pm", "primary"), ("cc", "complete"), ("inf", "infect"), ("kr", "kind")):
        v = _pick(rec, FIELD_ALIASES[names])
        if v:
            e[k] = v
    return e


def rows_from_records(records: list[dict]) -> list[list]:
    """API/CSV 레코드 → 코드집 행 [코드, 한글명, 영문명, 동의어, 부가정보]"""
    rows, seen = [], set()
    for rec in records:
        code = dotted(_pick(rec, FIELD_ALIASES["code"]))
        ko = _pick(rec, FIELD_ALIASES["ko"])
        if not code or not ko or code in seen or not code[0].isalpha():
            continue
        seen.add(code)
        rows.append([code, ko, _pick(rec, FIELD_ALIASES["en"]), "", extras_of(rec)])
    return rows


# ───────── 공식 API ─────────
def latest_path(client: httpx.Client) -> tuple[str, str]:
    """OpenAPI 설명서에서 가장 최신 기준일의 호출 경로를 찾는다 → (경로, 데이터 이름)"""
    r = client.get(DOCS_URL, timeout=30)
    r.raise_for_status()
    best = ("", "", "")
    for path, spec in (r.json().get("paths") or {}).items():
        summary = (spec.get("get") or {}).get("summary", "")
        m = re.search(r"(\d{8})", summary)
        if m and m.group(1) > best[0]:
            best = (m.group(1), path, summary)
    if not best[1]:
        raise RuntimeError("공공데이터포털 API 설명서에서 상병마스터 경로를 찾지 못했습니다.")
    return best[1], best[2]


def fetch_page(client: httpx.Client, path: str, key: str, page: int) -> dict:
    r = client.get(API_BASE + path, timeout=60, params={"page": page, "perPage": PER_PAGE, "returnType": "JSON", "serviceKey": clean_key(key)})
    if r.status_code in (401, 403):
        raise PermissionError("인증키가 올바르지 않거나, 이 데이터셋의 ‘활용신청’이 승인되지 않았습니다.")
    r.raise_for_status()
    return r.json()
