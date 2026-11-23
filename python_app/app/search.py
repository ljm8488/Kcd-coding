"""KCD 코드 검색 — 코드(접두 일치) · 한글명 · 영문명 · 동의어를 한 번에 찾는다."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

_CODE_RE = re.compile(r"^[A-Za-z]\d{0,2}(\.?\d{0,3})?$")      # J18.9 · j189 · J189 · I10 · I1 · M51.2 모두 코드로 본다


# 영문 형용사형 장기명 → KCD 영문 명칭에 쓰이는 낱말 (영국식 철자 포함)
_ORGAN_EN = {"ovarian": "ovary", "cervical": "cervix", "esophageal": "oesophag", "oesophageal": "oesophag", "esophagus": "oesophag", "gastric": "stomach",
             "hepatic": "liver", "renal": "kidney", "pancreatic": "pancreas", "colonic": "colon", "colorectal": "colon", "rectal": "rectal",
             "prostatic": "prostate", "uterine": "uterus", "endometrial": "corpus uteri", "bronchial": "bronch", "laryngeal": "larynx",
             "lung": "bronchus and lung", "pulmonary": "bronchus and lung", "skin": "skin", "oral": "mouth", "gallbladder": "gallbladder",
             "biliary": "biliary", "testicular": "testis", "vaginal": "vagina", "thyroid": "thyroid", "brain": "brain", "bone": "bone"}


def _late_chapter(code: str, ko: str) -> bool:
    """같은 점수일 때 뒤로 보낼 코드 — 임신·주산기·선천·특수목적·요인(OPQUZ), 외인(V~Y), 후유증(T90~T98 · 이름에 ‘후유증’)"""
    c = code[:1].upper()
    if c in "OPQUZVWXY":
        return True
    if c == "T" and code[1:3].isdigit() and 90 <= int(code[1:3]) <= 98:
        return True
    return "후유증" in ko


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
        self._all = "\n".join(self.blobs)                         # 어떤 글자 조각이 데이터에 있는지 빠르게 확인하는 용도
        self._en = [(r.en + " " + " ".join(s for s in r.syn if s.isascii())).lower() for r in self.rows]    # 영어 낱말 경계 확인용(띄어쓰기 유지)
        self._starts: list[int] = []          # 합친 문자열 안에서 각 행이 시작하는 위치 — 글자 조각이 어느 행에 있는지 바로 찾기 위한 표
        pos = 0
        for b in self.blobs:
            self._starts.append(pos)
            pos += len(b) + 1
        self._codes = [r.code.upper().replace(".", "") for r in self.rows]
        self._cache: dict = {}
        self._word_rows: dict[str, frozenset] = {}
        self.relaxed: set = set()

    def __len__(self) -> int:
        return len(self.rows)

    def rows_with(self, word: str) -> frozenset:
        """이 단어가 이름·동의어에 들어 있는 행 번호 집합 (캐시) — 합친 문자열에서 한 번에 찾아 행 번호로 바꾼다(2만 행을 줄마다 보지 않음)"""
        w = norm(word)
        got = self._word_rows.get(w)
        if got is None:
            found: set[int] = set()
            if w:
                al, st, n = self._all, self._starts, len(self._starts)
                pos = al.find(w)
                while pos >= 0:
                    i = bisect.bisect_right(st, pos) - 1
                    found.add(i)
                    pos = al.find(w, st[i + 1] if i + 1 < n else len(al))     # 같은 행의 다음 출현은 건너뛴다
            got = frozenset(found)
            if len(self._word_rows) > 4000:
                self._word_rows.clear()
            self._word_rows[w] = got
        return got

    def count_pair(self, a: str, b: str) -> int:
        return len(self.rows_with(a) & self.rows_with(b))

    def search(self, query: str, limit: int = 200) -> list[Row]:
        from . import lexicon
        key = (query or "").strip()[:120], limit, lexicon.version      # 용어 사전이 바뀌면 이전 검색 결과는 버린다 (검색어는 120자까지만 — 아주 긴 입력으로 서버가 느려지지 않게)
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
        if qn not in LEX:   # 사전에 없는 영문 ‘x cancer’ 는 공식 명칭 ‘malignant neoplasm of x’ 로 푼다 (사전의 일반 낱말 ‘cancer’ 보다 먼저)
            m2 = re.fullmatch(r"(.+?)\s+(cancer|carcinoma|tumou?r|neoplasm|malignancy)", q.strip(), re.I)
            if m2 and m2.group(1).isascii():
                organ = m2.group(1).strip().lower()
                organ = _ORGAN_EN.get(organ, organ)          # ovarian → ovary · esophageal → oesophag …
                return [(qn, qn, [organ + " malignant neoplasm"])]
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
        if not found:      # 사전에 없는 OO암 · OO종양 · x cancer 는 공식 명칭 "OO의 악성 신생물"로 푼다
            m = re.fullmatch(r"([가-힣]{1,8})(암|악성종양|종양)", q.replace(" ", ""))
            if m and m.group(1) not in ("항", "발", "암"):
                found.append((qn, qn, [m.group(1) + " 악성 신생물"]))
            else:
                m2 = re.fullmatch(r"(.+?)\s+(cancer|carcinoma|tumou?r|neoplasm|malignancy)", q.strip(), re.I)
                if m2:
                    found.append((qn, qn, [m2.group(1).strip() + " malignant neoplasm"]))
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
                wn = norm(q)
                exact = [r for r in base if wn in r.keys]       # 검색어와 공식명이 똑같은 코드는 사전 풀이보다 앞에 둔다 (예: 사전에 없는 용어)
                if exact and not any(kn == wn for _, kn, _a in ex):      # 사전에 직접 올라 있는 입력어(당뇨 등)는 사전의 순서를 따른다
                    ex_codes = {r.code for r in exact}
                    merged = exact + [r for r in merged if r.code not in ex_codes]
                elif False:
                    ex_codes = {r.code for r in exact}
                    merged = exact + [r for r in merged if r.code not in ex_codes]
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
            for r, c in zip(self.rows, self._codes):
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
        # 영어 낱말은 낱말 앞머리부터 일치해야 한다 (bladder 가 gallbladder 에 걸리지 않게)
        wb = [(t, re.compile(r"(?<![a-z0-9])" + re.escape(t))) for t in tokens if t.isascii() and t.isalpha() and len(t) >= 4]
        cand: frozenset | None = None
        for t in tokens:                       # 모든 낱말이 들어 있는 행만 후보로 (낱말마다 미리 찾아 둔 행 번호의 교집합)
            s = self.rows_with(t)
            cand = s if cand is None else cand & s
            if not cand:
                return []
        for i in sorted(cand or ()):
            r, blob = self.rows[i], self.blobs[i]
            if wb:
                en = self._en[i]
                if any(t in en and not p.search(en) for t, p in wb):      # 영문명에 들어 있어도 낱말 중간(gallbladder 속 bladder)이면 제외
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
        out.sort(key=lambda t: (t[0], _late_chapter(t[2].code, t[2].ko), len(t[2].code.replace(".", "")) > 3, t[1], t[2].code))
        return [t[2] for t in out[:limit]]

    def _segment(self, tok: str) -> list[str]:
        """합쳐 쓴 낱말을 데이터에 실제로 있는 가장 긴 조각들로 나눈다 (한 글자 조각은 버린다)"""
        n = len(tok)
        if n < 2 or n > 16:            # 너무 긴 덩어리는 나누지 않는다 (조합 수가 급격히 늘어 느려짐)
            return []
        if tok in self._all:
            return [tok]
        for ln in range(n - 1, 1, -1):
            for i in range(0, n - ln + 1):
                sub = tok[i:i + ln]
                if sub in self._all:
                    return self._segment(tok[:i]) + [sub] + self._segment(tok[i + ln:])
        return []

    _SUFFIX = re.compile(r"(증후군|질환|장애|증|병|염|성|적|의|및|에|를|을|이|가)$")

    def _relaxed(self, tokens: list[str], limit: int) -> list[Row]:
        """모든 단어가 맞는 결과가 없을 때 — 어미(증·병·염…)를 떼고 일부 단어만 맞아도 맞는 개수 순으로 보여 준다"""
        stems: list[str] = []
        for t in tokens[:8]:
            s = self._SUFFIX.sub("", t) if len(t) > 2 else t
            if len(s) >= 2 and s not in stems:
                stems.append(s)
            if len(t) >= 4 and t not in stems:           # 합쳐 쓴 말(허리디스크 · 총담관결석)은 데이터에 있는 가장 긴 조각들로 나눠 단서로 쓴다
                parts = self._segment(t) or [t[: len(t) // 2], t[len(t) // 2:]]
                for part in parts:
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
