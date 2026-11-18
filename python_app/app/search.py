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
        self.relaxed: set = set()

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
        from . import lexicon
        key = (query or "").strip(), limit, lexicon.version      # 용어 사전이 바뀌면 이전 검색 결과는 버린다
        hit = self._cache.get(key)
        if hit is not None:
            return list(hit)
        self.relaxed.discard(key[0])
        out = self._search(key[0], limit)
        if len(self._cache) > 300:
            self._cache.clear()
        self._cache[key] = out
        return list(out)

    # ───────── 구어 · 영문 · 약어 → 공식 상병명 ─────────
    @staticmethod
    def _expansions(q: str) -> list[tuple[str, str, list[str]]]:
        """검색어에 들어 있는 구어·영문·약어를 찾는다 → [(입력어, 정규화된 입력어, [공식명…])] (긴 입력어 우선, 최대 3개)"""
        from .lexicon import all_entries
        from .terms import MED_ABBR
        LEX = all_entries()
        qn = norm(q)
        if not qn:
            return []
        found: list[tuple[str, str, list[str]]] = []
        for k in sorted(LEX, key=len, reverse=True):
            if len(k) < 2:
                continue
            ascii_key = k.isascii()
            # 영문 약어는 통째로 일치할 때만(예: 'dm'이 다른 단어 안에 끼어도 약어로 보지 않는다), 한글은 포함돼 있으면 인정
            if (qn == k) or (not ascii_key and k in qn) or (ascii_key and len(k) > 4 and k in qn):
                if not any(k in f[1] for f in found):
                    found.append((k, k, LEX[k]))
            if len(found) >= 3:
                break
        if not found and qn in MED_ABBR:
            found.append((qn, qn, [MED_ABBR[qn]]))
        return found

    def explain(self, query: str) -> str:
        """‘맹장염’ → 급성 충수염 처럼 어떻게 해석해 찾았는지 안내 문구 (없으면 빈 문자열)"""
        ex = self._expansions(query)
        if not ex:
            return ""
        parts = []
        for k, _, alts in ex:
            shown = [a for a in alts if not _CODE_RE.match(a)][:3] or alts[:3]
            parts.append(f"‘{k}’ → {' · '.join(shown)}")
        return " / ".join(parts) + " (용어 사전으로 해석해 함께 검색)"

    def _search(self, query: str, limit: int = 200) -> list[Row]:
        q = (query or "").strip()
        if not q:
            return []
        base = self._core(q, limit)
        ex = self._expansions(q)
        if ex:
            seen = set()
            merged: list[Row] = []
            qn = norm(q)
            for k, kn, alts in ex:
                for alt in alts:
                    # 입력어 자리에 공식명을 넣어 다시 찾는다 (‘급성 맹장염’ → ‘급성 충수염’). 코드는 검색어 전체가 입력어일 때만
                    whole_q = qn == kn or qn.replace(kn, "") in ("증", "병", "환자", "질환", "염증", "진단", "상병")
                    if _CODE_RE.match(alt) and not whole_q:
                        continue
                    qq = alt if whole_q else qn.replace(kn, norm(alt))
                    for r in self._core(qq, limit, relaxed=False):
                        if r.code not in seen:
                            seen.add(r.code)
                            merged.append(r)
            if not merged:        # 수식어가 붙어 정확히 못 찾으면 공식명 자체로 찾는다 (요추 추간판탈출증 → 추간판장애)
                for k, kn, alts in ex:
                    for alt in alts:
                        for r in self._core(alt, limit, relaxed=False):
                            if r.code not in seen:
                                seen.add(r.code)
                                merged.append(r)
            for r in base:
                if r.code not in seen:
                    seen.add(r.code)
                    merged.append(r)
            if merged:
                return merged[:limit]
        if not base:
            base = self._core(q, limit, relaxed=True)
            if base:
                self.relaxed.add(q)
        return base

    def is_relaxed(self, query: str) -> bool:
        """일부 단어만 맞는 결과인지 (정확히 일치하는 결과가 없을 때)"""
        self.search(query)
        return (query or "").strip() in self.relaxed

    def _core(self, query: str, limit: int = 200, relaxed: bool = False) -> list[Row]:
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
        if relaxed:
            return self._relaxed(tokens, limit)
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
        # 같은 점수면 상위 분류(I10 → I10.1)와 짧은 이름을 앞으로
        # (임신·주산기·선천·가족력 같은 특수 장은 같은 점수에서 뒤로)
        out.sort(key=lambda t: (t[0], len(t[2].code.replace(".", "")) > 3, t[2].code[:1] in "OPQUZ", t[1], t[2].code))
        return [t[2] for t in out[:limit]]

    _SUFFIX = re.compile(r"(증후군|질환|장애|증|병|염|성|적|의|및|에|를|을|이|가)$")

    def _relaxed(self, tokens: list[str], limit: int) -> list[Row]:
        """모든 단어가 맞는 결과가 없을 때 — 어미(증·병·염…)를 떼고 일부 단어만 맞아도 맞는 개수 순으로 보여 준다"""
        stems: list[str] = []
        for t in tokens:
            s = self._SUFFIX.sub("", t) if len(t) > 2 else t
            if len(s) >= 2 and s not in stems:
                stems.append(s)
            if len(t) >= 4 and t not in stems:           # 합쳐 쓴 말(허리디스크)은 앞·뒤 절반도 단서로 쓴다
                for part in (t[: len(t) // 2], t[len(t) // 2:]):
                    if len(part) >= 2 and part not in stems:
                        stems.append(part)
        if not stems:
            return []
        out = []
        for r, blob in zip(self.rows, self.blobs):
            n = sum(1 for s in stems if s in blob)
            if n:
                out.append((-n, len(r.ko), r))
        out.sort(key=lambda t: (t[0], t[1], t[2].code))
        return [t[2] for t in out[:limit]]
