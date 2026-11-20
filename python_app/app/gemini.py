"""Gemini 호출 — 의무기록 문장에서 KCD 코드 후보를 JSON으로 받는다 (서버에서만 키 사용)."""
from __future__ import annotations

import json
import os
import time

import httpx

from . import store

MODELS = [os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"), "gemini-flash-latest"]

SYSTEM = (
    "당신은 한국 병원 심사·코딩 전문가입니다. 의무기록 문장을 읽고 KCD(한국표준질병·사인분류) 상병코드 후보를 제안합니다. "
    "코드는 반드시 KCD 형식(예: I10, E11.9)으로, 가능한 한 세분류까지 정확히 제시하세요. "
    "확신이 낮으면 confidence를 낮추고, 근거(reason)는 한국어 한 문장으로 쓰세요. 의무기록에 없는 진단을 만들지 마세요."
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


def interpret_terms(text: str) -> list[dict]:
    """의무기록에서 의학용어 · 약어를 찾아 표준 한글 용어로 해석한다 (판독 결과의 약어 풀이)."""
    sysmsg = ("당신은 한국의 보건의료정보관리사이자 의학용어 전문가입니다. 의무기록 본문에서 의학용어와 약어(영문 약어·기호 포함)를 찾아 "
              "표준 한글 의학용어로 해석합니다. term 은 본문에 쓰인 표기 그대로, kind 는 '약어' 또는 '용어', meaning 은 표준 한글 용어, "
              "english 는 영문 정식 명칭, note 는 코딩 시 유의점(없으면 빈 문자열). 이미 쉬운 한글로 풀어 쓴 일반 단어는 제외하고 최대 30개. "
              "OCR 오탈자로 보이면 note 에 '판독 오류 가능' 이라고 적으세요. 본문에 없는 용어를 만들지 마세요.")
    txt = generate_race(sysmsg, [{"text": "의무기록:\n" + text.strip()[:6000]}], 3072, schema=TERMS_SCHEMA)
    return json.loads(txt).get("terms", [])


def suggest(text: str, dept: str = "", purpose: str = "") -> dict:
    """의무기록 → KCD 코드 후보. 경량 모델을 먼저 쓰고 느리면 다른 모델을 함께 띄워 먼저 끝나는 답을 쓴다(실측 2초 안팎)."""
    ctx = f"진료과: {dept or '전체'}\n코딩 목적: {purpose or '주진단'}\n\n의무기록:\n{text.strip()}"
    return json.loads(generate_race(SYSTEM, [{"text": ctx}], 4096, schema=SCHEMA))