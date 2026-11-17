"""KCD 코드 검색 — 코드(접두 일치) · 한글명 · 영문명 · 동의어를 한 번에 찾는다."""
from __future__ import annotations

import re
from dataclasses import dataclass

_CODE_RE = re.compile(r"^[A-Za-z]\d{0,2}(\.\d{0,2})?$")


def norm(s: str) -> str:
    return re.sub(r"[\s·,()\-/]+", "", str(s or "")).lower()


@dataclass
class Row:
    code: str
    ko: str
    en: str
    syn: list[str]
    keys: list[str]


class KcdIndex:
    def __init__(self, rows: list[list[str]]):
        self.rows: list[Row] = []
        for r in rows:
            code, ko = r[0], r[1]
            en = r[2] if len(r) > 2 else ""
            syn = [x for x in (r[3] if len(r) > 3 else "").split("|") if x]
            keys = [norm(x) for x in [ko, en, *syn] if x]
            self.rows.append(Row(code, ko, en, syn, keys))
        self.blobs = ["\x00".join(r.keys) for r in self.rows]   # 부분 일치를 한 번에 확인하기 위한 합친 문자열
        self._cache: dict = {}
        self._word_rows: dict[str, frozenset] = {}

    def __len__(self) -> int:
        return len(self.rows)

    def rows_with(self, word: str) -> frozenset:
        """이 단어가 이름·동의어에 들어 있는 행 번호 집합 (캐시)"""
        w = norm(word)
        got = self._word_rows.get(w)
        if got is None:
            got = frozenset(i for i, b in enumerate(self.blobs) if w in b)
            self._word_rows[w] = got
        return got

    def count_pair(self, a: str, b: str) -> int:
        return len(self.rows_with(a) & self.rows_with(b))

    def search(self, query: str, limit: int = 200) -> list[Row]:
        key = (query or "").strip(), limit
        hit = self._cache.get(key)
        if hit is not None:
            return list(hit)
        out = self._search(key[0], limit)
        if len(self._cache) > 300:
            self._cache.clear()
        self._cache[key] = out
        return list(out)

    def _search(self, query: str, limit: int = 200) -> list[Row]:
        q = (query or "").strip()
        if not q:
            return []
        out: list[tuple[int, int, Row]] = []
        if _CODE_RE.match(q):
            qc = q.upper().replace(".", "")
            for r in self.rows:
                c = r.code.upper().replace(".", "")
                if c == qc:
                    out.append((0, len(r.code), r))
                elif c.startswith(qc):
                    out.append((1, len(r.code), r))
            if out:
                out.sort(key=lambda t: (t[0], t[1], t[2].code))
                return [t[2] for t in out[:limit]]
        tokens = [norm(t) for t in re.split(r"\s+", q) if norm(t)]
        if not tokens:
            return []
        whole = norm(q)
        for r, blob in zip(self.rows, self.blobs):
            if not all(t in blob for t in tokens):
                continue
            if whole in r.keys:
                score = 0
            elif any(k.endswith(whole) for k in r.keys):
                score = 1          # 한국어 병명은 핵심어가 끝에 온다 (예: 세균성 폐렴)
            elif any(k.startswith(whole) for k in r.keys):
                score = 2
            elif any(whole in k for k in r.keys):
                score = 3
            else:
                score = 4
            out.append((score, len(r.ko), r))
        out.sort(key=lambda t: (t[0], t[1], t[2].code))
        return [t[2] for t in out[:limit]]
