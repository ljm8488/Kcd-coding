"""용어 사전 — 현장에서 쌓는 의학용어·약어 사전 + 못 찾은 검색어 기록.

- 공용 DB: global/termDict  {"entries": {입력어: {"alts": [공식명·코드…], "by", "at", "src"}}}
- 공용 DB: global/missedQueries {검색어: {"n": 횟수, "last": 마지막 시각, "by": 사용자}}
내장 사전(lexicon.py)보다 여기 등록한 항목이 먼저 적용된다."""
from __future__ import annotations

import datetime as dt
import re
import threading

from . import lexicon, store

DICT_KEY, MISS_KEY = "termDict", "missedQueries"
MISS_CAP = 400
_lock = threading.Lock()


def nk(s: str) -> str:
    """검색에서 쓰는 정규화 (search.norm 과 같다)"""
    return re.sub(r"[\s·,()\-/]+", "", str(s or "")).lower()


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def entries(fresh: bool = False) -> dict[str, dict]:
    d = store.get("global", DICT_KEY, {}, fresh) or {}
    return d.get("entries", {}) if isinstance(d, dict) else {}


def _custom_for_search() -> dict[str, list[str]]:
    return {nk(k): list(v.get("alts", [])) for k, v in entries().items() if nk(k) and v.get("alts")}


lexicon.custom_provider = _custom_for_search      # 검색이 부를 때마다 최신 등록 항목을 읽는다 (캐시 60초)


def _put_entries(ents: dict, by: str) -> None:
    store.put("global", DICT_KEY, {"entries": ents}, by=by)
    lexicon.version += 1


def parse_alts(text: str) -> list[str]:
    out: list[str] = []
    for x in re.split(r"[,\n|;]+", text or ""):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def save_entry(key: str, alts: list[str], by: str, src: str = "수동") -> None:
    key = (key or "").strip()
    alts = [a for a in alts if a]
    if not key or not alts:
        raise ValueError("입력어와 공식 명칭(또는 코드)을 모두 입력하세요.")
    with _lock:
        ents = dict(entries(fresh=True))
        old = ents.get(key, {})
        ents[key] = {"alts": alts, "by": old.get("by") or by, "at": now(), "src": src}
        _put_entries(ents, by)
        _drop_missed(key, by)


def delete_entry(key: str, by: str) -> None:
    with _lock:
        ents = dict(entries(fresh=True))
        if ents.pop(key, None) is not None:
            _put_entries(ents, by)


# ───────── 못 찾은 검색어 ─────────
def missed(fresh: bool = False) -> dict[str, dict]:
    d = store.get("global", MISS_KEY, {}, fresh) or {}
    return d if isinstance(d, dict) else {}


def _drop_missed(q: str, by: str) -> None:
    m = dict(missed(fresh=True))
    if m.pop(q, None) is not None or m.pop(q.strip(), None) is not None:
        store.put("global", MISS_KEY, m, by=by)


def forget_missed(q: str, by: str) -> None:
    with _lock:
        _drop_missed(q, by)


def log_missed(q: str, by: str) -> None:
    """결과가 없거나 일부만 맞은 검색어를 기록한다 (화면을 막지 않도록 뒤에서 저장)"""
    q = (q or "").strip()
    if len(q) < 2 or len(q) > 60 or re.fullmatch(r"[A-Za-z]\d{0,2}(\.\d{0,2})?", q):
        return

    def work() -> None:
        try:
            with _lock:
                m = dict(missed(fresh=True))
                cur = m.get(q) or {"n": 0}
                m[q] = {"n": int(cur.get("n", 0)) + 1, "last": now(), "by": by}
                if len(m) > MISS_CAP:       # 오래되고 적게 검색된 것부터 정리
                    for k, _ in sorted(m.items(), key=lambda kv: (kv[1].get("n", 0), kv[1].get("last", "")))[: len(m) - MISS_CAP]:
                        m.pop(k, None)
                store.put("global", MISS_KEY, m, by=by)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=work, daemon=True).start()
