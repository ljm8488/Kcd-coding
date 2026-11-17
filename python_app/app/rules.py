"""룰 엔진 — 성별·연령 제한, 주진단 불가, 배타 관계, 불완전 코드 (원본 웹앱의 규칙을 그대로 옮김)"""
from __future__ import annotations

RULE_SEX = [
    (["C53", "C54", "C55", "C56", "D25", "D26", "N70", "N71", "N80", "N81", "N83", "N84", "N92", "N93", "N94",
      "N95", "O0", "O1", "O2", "O3", "O4", "O6", "O7", "O8", "O9", "Z34", "Z32"], "F", "여성에게만 사용하는 코드"),
    (["C61", "C62", "N40", "N41", "N43", "N44", "N45", "N47", "N48", "N50", "N51"], "M", "남성에게만 사용하는 코드"),
]
RULE_AGE = [
    (["P"], 0, 0, "출생전후기 코드 — 생후 28일 이내에만 사용"),
    (["H25"], 40, 120, "노년백내장 — 40세 이상에 사용 (그 외 H26 계열 검토)"),
    (["O"], 10, 60, "임신·출산 코드 — 가임 연령대에만 사용"),
    (["F70", "F71", "F72"], 3, 120, "지적장애 — 3세 이상 평가 후 부여"),
]
RULE_NO_PRIMARY = [
    (["V", "W", "X", "Y"], "손상외인 코드 — 손상의 성질(S·T) 코드를 주진단으로 기재"),
    (["B95", "B96", "B97", "B98"], "병원체 부수코드 — 감염 부위 코드를 주진단으로 기재"),
    (["U8"], "항생제 내성 부수코드 — 단독 주진단 불가"),
    (["Z0", "Z1"], "검진·관찰 코드 — 확정 진단이 있으면 그 코드를 주진단으로 기재"),
    (["I69", "G09", "B90", "B91", "B92", "E64", "O94"], "후유증 코드 — 급성기 진료 시 원질환을 주진단으로 기재"),
    (["R"], "증상 · 징후 코드 — 확정 진단이 있으면 그 코드를 주진단으로 기재 (R장은 원인 미확인 시에만)"),
]
RULE_EXCLUSIVE = [
    (["I10"], ["I11", "I12", "I13"], "본태성 고혈압과 고혈압성 심장·콩팥병은 함께 기재할 수 없습니다 (통합 코드 선택)"),
    (["E10"], ["E11"], "1형과 2형 당뇨병 동시 기재 — 하나로 확정 필요"),
    (["I63"], ["I61", "I62"], "뇌경색과 뇌출혈 동시 기재 — 영상 소견으로 확정 필요"),
    (["J44"], ["J45"], "COPD와 천식 동시 기재 시 중복성 검토 (J44.8 검토)"),
    (["N18"], ["N17"], "급성 콩팥손상과 만성 콩팥병 동시 기재 시 급성악화 여부 명시"),
]


def _c(code: str) -> str:
    return str(code or "").strip().upper()


def sex_issue(code: str, sex: str) -> str | None:
    """sex: 'M' | 'F' | '' (모름이면 검사하지 않음)"""
    code = _c(code)
    if sex not in ("M", "F"):
        return None
    for pre, need, note in RULE_SEX:
        if any(code.startswith(p) for p in pre) and sex != need:
            return note
    return None


def age_issue(code: str, age: int | None) -> str | None:
    code = _c(code)
    if age is None:
        return None
    for pre, lo, hi, note in RULE_AGE:
        if any(code.startswith(p) for p in pre) and not (lo <= age <= hi):
            return note
    return None


def no_primary(code: str) -> str | None:
    code = _c(code)
    for pre, note in RULE_NO_PRIMARY:
        if any(code.startswith(p) for p in pre):
            return note
    return None


def restriction(code: str) -> str:
    """코드 자체의 사용 제한 요약 (검색 결과 표시용)"""
    code = _c(code)
    parts = []
    for pre, need, note in RULE_SEX:
        if any(code.startswith(p) for p in pre):
            parts.append("여성 전용" if need == "F" else "남성 전용")
    for pre, lo, hi, note in RULE_AGE:
        if any(code.startswith(p) for p in pre):
            parts.append(f"{lo}~{hi}세" if hi < 120 else f"{lo}세 이상")
    return " · ".join(dict.fromkeys(parts))


class Family:
    """코드 체계(마스터) 기반 하위·형제 코드 조회"""

    def __init__(self, idx):
        self.names = {r.code.upper(): r.ko for r in idx.rows}
        self.keys = sorted(self.names)
        self.prefixes = {k[:i] for k in self.keys for i in range(1, len(k))}   # 하위 코드 여부를 즉시 판단

    def known(self, code: str) -> bool:
        return _c(code) in self.names

    def children(self, code: str) -> list[str]:
        code = _c(code)
        fam = [k for k in self.keys if k != code and k.startswith(code)]
        return [k for k in fam if not any(m != k and k.startswith(m) for m in fam)]

    def has_child(self, code: str) -> bool:
        return _c(code) in self.prefixes

    def alts(self, code: str, sex: str, age: int | None) -> list[str]:
        root = _c(code)[:3]
        return [k for k in self.keys if k != _c(code) and k.startswith(root) and not self.has_child(k)
                and not sex_issue(k, sex) and not age_issue(k, age)][:6]


_FAM: dict = {}


def get_family(idx) -> "Family":
    """마스터가 같으면 하위 코드 표를 다시 만들지 않는다"""
    f = _FAM.get(id(idx))
    if f is None:
        _FAM.clear()
        f = _FAM[id(idx)] = Family(idx)
    return f


def check_claim(rows: list[dict], sex: str, age: int | None, fam: Family) -> list[dict]:
    """rows: [{code, kind('주진단'|'부진단')}] → findings [{sev,code,title,note,alts,fix}]"""
    out: list[dict] = []
    rows = [{"code": _c(r["code"]), "kind": r.get("kind", "부진단")} for r in rows if _c(r.get("code"))]
    codes = [r["code"] for r in rows]
    seen: set[str] = set()
    for r in rows:
        code = r["code"]
        if not fam.known(code) and not fam.has_child(code):
            out.append({"sev": "확인", "code": code, "title": "코드집에 없는 코드",
                        "note": "KCD 마스터에 존재하지 않습니다 — 표제부에서 확인하세요.", "fix": "none", "alts": []})
        if fam.has_child(code):
            out.append({"sev": "삭감", "code": code, "title": "불완전 코드 기재",
                        "note": "하위 세분류가 존재합니다. 최말단 코드까지 지정해야 청구 가능합니다.",
                        "fix": "replace", "alts": fam.children(code)[:8]})
        sx = sex_issue(code, sex)
        if sx:
            a = fam.alts(code, sex, age)
            out.append({"sev": "삭감", "code": code, "title": "성별 불일치",
                        "note": f"{sx} — 현재 환자 성별: {'남' if sex == 'M' else '여'}",
                        "fix": "replace" if a else "remove", "alts": a})
        ag = age_issue(code, age)
        if ag:
            a = fam.alts(code, sex, age)
            out.append({"sev": "삭감", "code": code, "title": "연령 불일치",
                        "note": f"{ag} — 현재 환자 연령: {age}세",
                        "fix": "replace" if a else "remove", "alts": a})
        if r["kind"] == "주진단":
            np_ = no_primary(code)
            if np_:
                alt = [c for c in codes if c != code and not no_primary(c) and not fam.has_child(c)
                       and not sex_issue(c, sex) and not age_issue(c, age)][:6]
                out.append({"sev": "삭감", "code": code, "title": "주진단 불가 코드", "note": np_,
                            "fix": "demote", "alts": alt})
        if code in seen:
            out.append({"sev": "조정", "code": code, "title": "중복 코드",
                        "note": f"동일 명세서 내 {code} 가 2회 이상 기재되었습니다.", "fix": "dedupe", "alts": []})
        seen.add(code)
    primary = [r for r in rows if r["kind"] == "주진단"]
    if rows and not primary:
        out.append({"sev": "삭감", "code": "—", "title": "주진단 누락", "note": "명세서에 주진단이 지정되지 않았습니다.",
                    "fix": "promote", "alts": [c for c in codes if not no_primary(c) and not fam.has_child(c)][:6]})
    if len(primary) > 1:
        out.append({"sev": "삭감", "code": "—", "title": "주진단 중복 지정",
                    "note": f"주진단은 1개만 기재할 수 있습니다. 현재 {len(primary)}개.",
                    "fix": "keepone", "alts": [p["code"] for p in primary]})
    if any(c[0] not in "RZ" for c in codes):
        for c in codes:
            if c.startswith("R"):
                out.append({"sev": "조정", "code": c, "title": "증상 코드 병기",
                            "note": "확정 진단이 함께 기재되어 있습니다. 증상·징후(R장) 코드는 원인 진단이 확인되면 생략합니다.",
                            "fix": "remove", "alts": [c]})
    for a, b, note in RULE_EXCLUSIVE:
        ha = [c for c in codes if any(c.startswith(p) for p in a)]
        hb = [c for c in codes if any(c.startswith(p) for p in b)]
        if ha and hb:
            out.append({"sev": "조정", "code": f"{a[0]} + {b[0]}", "title": "논리 모순 · 배타 관계", "note": note,
                        "fix": "remove", "alts": ha + hb})
    order = {"삭감": 0, "조정": 1, "확인": 2}
    out.sort(key=lambda f: order[f["sev"]])
    return out


def apply_fix(rows: list[dict], f: dict, pick: str) -> list[dict]:
    rows = [dict(r) for r in rows]
    cur = _c(f["code"])
    kind = f["fix"]
    if kind == "replace":
        for r in rows:
            if _c(r["code"]) == cur:
                r["code"] = pick
                break
    elif kind == "remove":
        rows = [r for r in rows if _c(r["code"]) != _c(pick)]
    elif kind == "dedupe":
        seen, new = set(), []
        for r in rows:
            k = _c(r["code"])
            if k not in seen:
                new.append(r)
            seen.add(k)
        rows = new
    elif kind == "demote":
        for r in rows:
            if _c(r["code"]) == cur:
                r["kind"] = "부진단"
            if _c(r["code"]) == pick:
                r["kind"] = "주진단"
    elif kind == "promote":
        for r in rows:
            r["kind"] = "주진단" if _c(r["code"]) == pick else "부진단"
    elif kind == "keepone":
        for r in rows:
            r["kind"] = "주진단" if _c(r["code"]) == pick else ("부진단" if r["kind"] == "주진단" else r["kind"])
    return rows
