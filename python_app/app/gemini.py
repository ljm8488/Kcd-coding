"""Gemini 호출 — 의무기록 문장에서 KCD 코드 후보를 JSON으로 받는다 (서버에서만 키 사용)."""
from __future__ import annotations

import json
import os
import re
import time

import httpx

from . import store

MODELS = [os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"), "gemini-flash-latest"]

SYSTEM = (
    "당신은 한국 병원 심사·코딩 전문가입니다. 의무기록을 읽고 KCD(한국표준질병·사인분류) 상병코드 후보를 빠짐없이 제안합니다. "
    "코드는 반드시 KCD 형식(예: I10, E11.9)으로, 가능한 한 세분류까지 정확히 제시하세요. "
    "중요: 기록에 나온 모든 진단명·질환·병태·합병증·후유증·만성질환·출혈/빈혈 같은 소견·투석/수술 후 상태를 각각 별도 항목으로 내세요. "
    "한 문장에 질환이 여러 개면 나눠서 각각 코드를 주고, 과거력(h/o)과 의심(R/O)도 포함하되 role 로 구분하세요. "
    "role 은 '주진단'(입원 목적이 된 질환, 정확히 1개) · '부진단'(입원 중 관리·치료한 동반질환·합병증) · '과거력' · '의심'(R/O, 감별) 중 하나입니다. "
    "최대 25개. 확신이 낮으면 confidence 를 낮추고, 근거(reason)는 한국어 한 문장으로 쓰세요. 의무기록에 없는 진단을 만들지 마세요."
)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "codes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "code": {"type": "STRING"},
                    "name_ko": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                    "confidence": {"type": "INTEGER"},
                    "primary": {"type": "BOOLEAN"},
                    "role": {"type": "STRING"},
                },
                "required": ["code", "name_ko", "reason", "confidence"],
            },
        },
        "caution": {"type": "STRING"},
    },
    "required": ["codes"],
}


def api_key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    v = store.get("global", "orgGemKey", "")
    return (v if isinstance(v, str) else (v or {}).get("key", "")).strip()


_live: dict = {"at": 0.0, "models": []}


def candidate_models(key: str) -> list[str]:
    """키로 실제 쓸 수 있는 flash 모델을 조회 (지원 종료된 모델 404 방지). 정식 > 미리보기, 최신 버전 우선."""
    import re
    if time.time() - _live["at"] > 3600:
        try:
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                          headers={"x-goog-api-key": key}, timeout=20)
            names = []
            if r.is_success:
                for m in r.json().get("models", []):
                    n = m["name"].removeprefix("models/")
                    if ("generateContent" in m.get("supportedGenerationMethods", []) and re.match(r"gemini-\d", n)
                            and "flash" in n and not re.search(r"image|tts|audio|live|embedding|omni|thinking-exp|preview|latest", n)):
                        names.append(n)

                def ver(n: str) -> float:
                    return float(re.match(r"gemini-(\d+(?:\.\d+)?)", n).group(1))
                names.sort(key=lambda n: (("lite" in n), -ver(n)))
            _live.update(at=time.time(), models=names)
        except httpx.HTTPError:
            pass
    out = [MODELS[0]] + _live["models"][:4] + MODELS[1:]
    return list(dict.fromkeys(out))[:6]


def generate(system: str, parts: list[dict], schema: dict | None = None, max_tokens: int = 4096) -> str:
    """범용 Gemini 호출 — parts 는 [{"text":..}] 또는 [{"inlineData":{...}}]. 응답 텍스트를 돌려준다."""
    key = api_key()
    if not key:
        raise RuntimeError("Gemini API 키가 없습니다. 환경변수 GEMINI_API_KEY를 설정하거나 공용 DB에 기관 키를 등록하세요.")
    cfg: dict = {"temperature": 0.15, "topP": 0.9, "maxOutputTokens": max_tokens}
    if schema:
        cfg.update(responseMimeType="application/json", responseSchema=schema)
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    last = 0
    for model in candidate_models(key):
        for attempt in range(2):
            try:
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                               headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                               json=body, timeout=90)
            except httpx.TimeoutException:
                last = 504
                break
            last = r.status_code
            if r.is_success:
                ps = r.json()["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in ps)
            if last in (400, 403):
                raise RuntimeError("Gemini 요청이 거부되었습니다 (키 또는 파일 형식·크기를 확인하세요).")
            if last == 404:
                break
            if last in (429, 500, 503):
                time.sleep(1.2 if attempt == 0 else 2.5)
                continue
            break
    if last == 429:
        raise RuntimeError("Gemini 사용량을 잠시 초과했습니다. 1분 후 다시 시도하세요.")
    raise RuntimeError(f"Gemini 응답 오류 ({last})")


class _Fail(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def _one_call(model: str, key: str, body: dict, timeout: float) -> str:
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=timeout)
    except httpx.HTTPError:
        raise _Fail(504)
    if not r.is_success:
        raise _Fail(r.status_code)
    try:
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, ValueError):
        raise _Fail(502)


def generate_race(system: str, parts: list[dict], max_tokens: int = 8192, stagger: float = 5.0, timeout: float = 45.0,
                  schema: dict | None = None) -> str:
    """빠른 응답용 — 첫 모델이 느리거나 실패(429·503·시간초과)하면 기다리지 않고 다음 모델을 곧바로 함께 띄워,
    먼저 성공한 답을 쓴다. (한 모델이 몰려 90초씩 걸리던 문제를 피한다)"""
    import concurrent.futures as cf
    key = api_key()
    if not key:
        raise RuntimeError("Gemini API 키가 없습니다. 환경변수 GEMINI_API_KEY를 설정하거나 공용 DB에 기관 키를 등록하세요.")
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.15, "topP": 0.9, "maxOutputTokens": max_tokens}}
    if schema:
        body["generationConfig"].update(responseMimeType="application/json", responseSchema=schema)
    # 글자 옮기기는 큰 모델이 필요 없고 경량 모델이 훨씬 빠르다(실측 2초 안팎 vs 큰 모델 40초 이상) → 경량 모델을 먼저, 큰 모델은 예비
    cand = candidate_models(key)
    lite = [m for m in _live["models"] if "lite" in m] + ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
    models = list(dict.fromkeys(lite + cand))[:5]
    ex = cf.ThreadPoolExecutor(max_workers=len(models))
    pending: set = set()
    nxt, last = 0, 0
    end = time.time() + timeout + stagger * len(models)
    try:
        while (nxt < len(models) or pending) and time.time() < end:
            if nxt < len(models):
                pending.add(ex.submit(_one_call, models[nxt], key, body, timeout))
                nxt += 1
            done, pending = cf.wait(pending, timeout=stagger if nxt < len(models) else max(1.0, end - time.time()),
                                    return_when=cf.FIRST_COMPLETED)
            for f in done:
                try:
                    return f.result()
                except _Fail as e:
                    last = e.status
                    if last in (400, 403):
                        raise RuntimeError("Gemini 요청이 거부되었습니다 (키 또는 파일 형식·크기를 확인하세요).")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if last == 429:
        raise RuntimeError("Gemini 사용량을 잠시 초과했습니다. 1분 후 다시 시도하세요.")
    raise RuntimeError(f"Gemini 응답 오류 ({last or 504}) — 서비스가 혼잡합니다. 잠시 후 다시 시도하세요.")


SEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ko": {"type": "STRING"}, "en": {"type": "STRING"}, "anatomy": {"type": "STRING"},
        "type": {"type": "STRING"}, "abbr": {"type": "STRING"},
        "synonyms": {"type": "ARRAY", "items": {"type": "STRING"}},
        "guide": {"type": "ARRAY", "items": {"type": "STRING"}},
        "codes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "code": {"type": "STRING"}, "name_ko": {"type": "STRING"}, "reason": {"type": "STRING"},
            "confidence": {"type": "INTEGER"}}, "required": ["code", "name_ko", "confidence"]}},
    },
    "required": ["ko", "codes"],
}


def semantic(query: str) -> dict:
    """AI 의미 검색 — 의학용어·약어·구어를 표준 병명, 부위, 유형, 후보 KCD 코드로 해석"""
    sysmsg = ("당신은 한국의 보건의료정보관리사이자 해부학·의학용어 전문가입니다. 입력된 검색어(구어·약어·영어 포함)를 "
              "표준 병명으로 해석하고 KCD 코드 후보를 제안합니다. anatomy는 해부학적 부위, type은 질환 유형(예: 골절, 염증, 악성신생물), "
              "synonyms는 검색에 쓸 한국어 관련 표기 3~6개, guide는 코딩 시 유의점 1~3문장. 코드는 KCD 형식(예: S62.6)으로 가능한 세분류까지.")
    txt = generate_race(sysmsg, [{"text": f"검색어: {query}"}], 2048, schema=SEM_SCHEMA)
    return json.loads(txt)


TERMS_SCHEMA = {"type": "OBJECT", "properties": {"terms": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "term": {"type": "STRING"}, "kind": {"type": "STRING"}, "meaning": {"type": "STRING"}, "english": {"type": "STRING"},
    "note": {"type": "STRING"}}, "required": ["term", "meaning"]}}}, "required": ["terms"]}


_TERMS_SYS = ("당신은 한국의 보건의료정보관리사이자 의학용어 전문가입니다. 의무기록 본문에 쓰인 영어 의학용어·약어·해부학 용어·약품명·시술명·"
              "검사명·상태 표현을 하나도 빠뜨리지 말고 모두 찾아 표준 한글 의학용어로 해석합니다. "
              "규칙: (1) term 은 본문에 쓰인 표기 그대로(대소문자·마침표·하이픈 포함)이며 본문의 부분 문자열이어야 합니다. "
              "(2) 두 단어 이상으로 한 뜻이 되는 표현은 구 전체를 하나의 term 으로 하세요 "
              "(예: 'renal artery'→신동맥, 'general condition poor'→전신 상태 불량, 'epi injection'→에피네프린 주입, 'S-colon'→S상 결장, "
              "'temporoparietal area'→측두두정부, 'multiple fx.'→다발성 골절). "
              "(3) 좌/우(Lt, Rt), 부위, 증상, 소견(melena, Hb 저하), 질환, 약, 시술(PCI, hemoclipping), 검사 수치 항목(Hb, CRP, Cr)도 모두 포함합니다. "
              "(4) kind 는 '약어' 또는 '용어', meaning 은 표준 한글 용어(번역투 말고 임상에서 쓰는 말), english 는 영문 정식 명칭, "
              "note 는 코딩 시 유의점(없으면 빈 문자열). (5) and·in·with 같은 일반 영어 단어와 이미 한글로 풀어 쓴 말은 제외합니다. "
              "(6) OCR 오탈자로 보이면 note 에 '판독 오류 가능'. 본문에 없는 용어는 만들지 마세요. 최대 80개.")


def _chunks(text: str, n: int = 1800) -> list[str]:
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        if cur and len(cur) + len(line) > n:
            out.append(cur)
            cur = ""
        cur += line
        while len(cur) > n * 1.5:                      # 줄바꿈이 없는 긴 글은 문장 끝에서 자른다
            cut = max(cur.rfind(". ", 0, n), cur.rfind("다. ", 0, n), n - 1)
            out.append(cur[:cut + 1])
            cur = cur[cut + 1:]
    if cur.strip():
        out.append(cur)
    return out


def interpret_terms(text: str) -> list[dict]:
    """의무기록에서 의학용어 · 약어를 찾아 표준 한글 용어로 해석한다. 긴 글은 나눠서 동시에 처리해 빠짐이 없게 한다."""
    import concurrent.futures as cf
    chunks = _chunks(text.strip()[:12000])
    if not chunks:
        return []

    def one(ch: str) -> list[dict]:
        txt = generate_race(_TERMS_SYS, [{"text": "의무기록:\n" + ch}], 4096, schema=TERMS_SCHEMA)
        return json.loads(txt).get("terms", [])

    out: list[dict] = []
    err: Exception | None = None
    with cf.ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        for f in [ex.submit(one, c) for c in chunks]:
            try:
                out += f.result()
            except Exception as e:  # noqa: BLE001
                err = e
    if not out and err:
        raise err
    seen, uniq = set(), []
    for r in out:
        k = str(r.get("term", "")).strip().lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


_TR_SCHEMA = {"type": "OBJECT", "properties": {"lines": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "i": {"type": "INTEGER"}, "ko": {"type": "STRING"}}, "required": ["i", "ko"]}}}, "required": ["lines"]}


def translate_lines(lines: list[str], glossary: list[tuple[str, str]] | None = None) -> dict[int, str]:
    """의무기록 줄 단위 한글 번역 — {줄 번호: 한글 문장}. 이미 한글뿐인 줄은 돌려주지 않는다. 긴 글은 나눠서 동시에 처리."""
    import concurrent.futures as cf
    todo = [(i, l) for i, l in enumerate(lines) if l.strip() and re.search(r"[A-Za-z]{2,}", l)]
    if not todo:
        return {}
    sysmsg = ("당신은 한국 병원의 의무기록 번역가입니다. 번호가 붙은 의무기록 줄을 자연스러운 한국어 임상 문장으로 옮기세요. "
              "의학용어·약어는 임상에서 쓰는 표준 한글 의학용어로(예: ESRD→말기 신장병, HD→혈액투석, s/p→시행 후, R/O→감별 필요, h/o→병력), "
              "좌/우(Lt/Rt)·부위·수치·단위·날짜는 정확히 유지하세요. 줄머리의 '#.' '-' 같은 기호와 번호는 빼도 됩니다. "
              "원문에 없는 내용을 더하거나 추측하지 말고, 모르는 약어는 그대로 두세요. 입력의 i 와 같은 번호로 돌려주고, 한글뿐인 줄은 생략하세요.")
    size = 25
    chunks = [todo[k:k + size] for k in range(0, len(todo), size)]

    def one(ch: list[tuple[int, str]]) -> dict[int, str]:
        body = "\n".join(f"{i}\t{l.strip()}" for i, l in ch)
        gl = ""
        if glossary:      # 앞에서 해석한 용어는 같은 번역어를 쓰게 해 ②칸의 용어 해석과 어긋나지 않게 한다
            gl = "용어집(이 번역어를 우선 사용):\n" + "\n".join(f"- {t} = {m}" for t, m in glossary[:80]) + "\n\n"
        txt = generate_race(sysmsg, [{"text": gl + "줄 목록(번호<TAB>원문):\n" + body}], 4096, schema=_TR_SCHEMA)
        got = {}
        valid = {i for i, _ in ch}
        for r in json.loads(txt).get("lines", []):
            if int(r.get("i", -1)) in valid and str(r.get("ko", "")).strip():
                got[int(r["i"])] = str(r["ko"]).strip()
        return got

    out: dict[int, str] = {}
    err: Exception | None = None
    with cf.ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        for f in [ex.submit(one, c) for c in chunks]:
            try:
                out.update(f.result())
            except Exception as e:  # noqa: BLE001
                err = e
    if not out and err:
        raise err
    return out


def interpret_phrases(phrases: list[str], context: str = "") -> list[dict]:
    """1차에서 빠진 영어 표현만 따로 모아 다시 해석한다 (2차 보완)"""
    items = [p for p in phrases if p.strip()][:70]
    if not items:
        return []
    sysmsg = ("당신은 한국의 보건의료정보관리사이자 의학용어 전문가입니다. 아래 영어 표현 목록은 의무기록에서 뽑은 것입니다. "
              "각 항목을 표준 한글 의학용어로 해석하세요. 한 항목에 의학용어가 여러 개 섞여 있으면 의학용어 단위로 쪼개 각각 term 으로 돌려주세요"
              "(term 은 항목 안의 부분 문자열 그대로). 의학과 무관한 일반 영어 단어(접속사·관사 등)는 제외합니다. "
              "kind 는 '약어' 또는 '용어', meaning 은 임상에서 쓰는 한글 용어, english 는 영문 정식 명칭, note 는 유의점(없으면 빈 문자열).")
    ctx = ("참고 문맥:\n" + context.strip()[:1500] + "\n\n") if context.strip() else ""
    txt = generate_race(sysmsg, [{"text": ctx + "영어 표현 목록:\n" + "\n".join(f"- {p}" for p in items)}], 4096, schema=TERMS_SCHEMA)
    return json.loads(txt).get("terms", [])


def _norm_code(c: str) -> str:
    return str(c).strip().upper().replace(".", "")


def suggest_more(text: str, found: list[dict], dept: str = "", purpose: str = "") -> list[dict]:
    """2차 점검 — 1차에서 빠진 진단·병태만 골라 추가 코드로 제안한다 (이미 나온 코드는 제외)"""
    have = "\n".join(f"- {c.get('code', '')} {c.get('name_ko', '')}" for c in found) or "(없음)"
    sysmsg = (SYSTEM + " 지금은 보완 단계입니다. 이미 제안된 코드 목록을 줄 테니, 의무기록에 있으나 목록에 없는 진단·병태·합병증·소견·만성질환·과거력·"
              "투석/수술 후 상태만 찾아 각각 새 항목으로 내세요. 이미 있는 코드는 다시 내지 마세요. 더 없으면 빈 배열을 주세요. role 은 '부진단' '과거력' '의심' 중에서 고르고 '주진단'은 쓰지 마세요.")
    ctx = f"진료과: {dept or '전체'}\n코딩 목적: {purpose or '주진단'}\n\n이미 제안된 코드:\n{have}\n\n의무기록:\n{text.strip()}"
    return json.loads(generate_race(sysmsg, [{"text": ctx}], 4096, schema=SCHEMA)).get("codes", [])


def suggest(text: str, dept: str = "", purpose: str = "") -> dict:
    """의무기록 → KCD 코드 후보. 경량 모델을 먼저 쓰고 느리면 다른 모델을 함께 띄워 먼저 끝나는 답을 쓴다.
    1차로 주진단·주요 질환을 뽑고, 2차 점검에서 빠진 동반질환·합병증·과거력을 보태 누락을 줄인다."""
    text = text.strip()[:20000]                          # 너무 긴 입력은 잘라서 보낸다 (응답 지연·비용 보호)
    ctx = f"진료과: {dept or '전체'}\n코딩 목적: {purpose or '주진단'}\n\n의무기록:\n{text}"
    res = json.loads(generate_race(SYSTEM, [{"text": ctx}], 4096, schema=SCHEMA))
    codes = list(res.get("codes", []))
    try:
        have = {_norm_code(c.get("code", "")) for c in codes}
        for c in suggest_more(text, codes, dept, purpose):
            k = _norm_code(c.get("code", ""))
            if k and k not in have and not any(k.startswith(h) or h.startswith(k) for h in have):   # 같은 계열(L89.9 / L89.90)의 중복은 뺀다
                have.add(k)
                c["primary"] = False
                codes.append(c)
    except Exception:  # noqa: BLE001
        pass                                          # 보완 실패해도 1차 결과는 그대로 쓴다
    # 주진단은 정확히 하나만 — role 이 '주진단'인 첫 항목, 없으면 primary 표시된 첫 항목
    prim = next((c for c in codes if c.get("role") == "주진단"), None) or next((c for c in codes if c.get("primary")), None)
    for c in codes:
        c["primary"] = c is prim
        if c["primary"]:
            c["role"] = "주진단"
        elif not c.get("role") or c.get("role") == "주진단":
            c["role"] = "부진단"
    res["codes"] = codes
    return res