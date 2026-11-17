"""의학용어 · 약어 해석 — 내장 임상 약어 사전(원본 웹앱의 사전) + AI 해석"""
from __future__ import annotations

import re

# 임상 약어 (진료기록 · 판독지에서 흔한 표기) → 표준 한글 용어
MED_ABBR = {
  "fx":"골절","ca":"암","ca.":"암","tu":"종양","mass":"종괴","bx":"조직검사","op":"수술","s/p":"시행 후",
  "r/o":"감별 필요","dx":"진단","hx":"병력","sx":"증상","tx":"치료","f/u":"추적관찰",
  "rt":"우측","rt.":"우측","lt":"좌측","lt.":"좌측","bil":"양측","both":"양측",
  "abd":"복부","ext":"사지","ue":"상지","le":"하지","lbp":"허리통증","hnp":"추간판탈출","hivd":"추간판탈출",
  "acs":"급성 관상동맥증후군","cad":"관상동맥질환","ards":"급성 호흡곤란증후군","aki":"급성 신손상",
  "ich":"뇌내출혈","sah":"거미막하출혈","sdh":"경막하출혈","edh":"경막외출혈","tbi":"외상성 뇌손상",
  "pud":"소화성 궤양","ugib":"상부위장관 출혈","lgib":"하부위장관 출혈","gib":"위장관 출혈",
  "sob":"호흡곤란","doe":"운동시 호흡곤란","loc":"의식소실","rta":"교통사고","ta":"교통사고",
  "hcc":"간세포암","rcc":"신세포암","nsclc":"비소세포폐암","sclc":"소세포폐암","gbm":"교모세포종",
  "pe":"폐색전증","dvt":"심부정맥혈전증","pvd":"말초혈관질환","pad":"말초동맥질환",
  "uti":"요로감염","apn":"급성 신우신염","bph":"전립선비대증","gerd":"위식도역류병","ibs":"과민성대장증후군"
}

# 약어 중 일반 영단어와 겹치는 것 — 대문자로 쓰인 경우에만 약어로 본다
AMBIG = {"both", "mass", "ext", "le", "ue", "op", "dx", "hx", "tx", "sx", "ta", "bil", "rt", "lt", "ca", "tu"}
_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,12}(?:/[A-Za-z]{1,6})?\.?)(?![A-Za-z0-9])")


def local_terms(text: str, dept_terms: list[list[str]] | None = None, union: dict | None = None) -> list[dict]:
    """본문에서 내장 사전(현재 진료과 전용 약어 · 임상 약어 · 전 진료과 약어)에 있는 약어를 찾아 해석한다.
    union: {약어(소문자): {해석: [진료과…]}} — 진료과마다 뜻이 다른 약어는 모든 해석을 함께 보여 준다."""
    dept_map = {t[0].lower(): t[1] for t in (dept_terms or [])}
    union = union or {}
    found: dict[str, dict] = {}
    for m in _TOKEN.finditer(text or ""):
        raw = m.group(1)
        key = raw.lower().rstrip(".")
        meaning = dept_map.get(key) or MED_ABBR.get(key) or MED_ABBR.get(raw.lower())
        note = ""
        if not meaning and key in union:
            ms = union[key]
            meaning = " / ".join(ms)
            if len(ms) > 1:
                note = "진료과마다 뜻이 다릅니다 — " + ", ".join(f"{d[0]}: {m}" for m, d in ms.items())
        if not meaning:
            continue
        if key in AMBIG and not raw.isupper() and not raw.endswith("."):
            continue
        row = found.setdefault(key, {"term": raw.rstrip("."), "kind": "약어", "meaning": meaning, "english": "", "note": note, "src": "내장 사전", "n": 0})
        row["n"] += 1
    return sorted(found.values(), key=lambda r: -r["n"])


def merge(local: list[dict], ai: list[dict]) -> list[dict]:
    """내장 사전 결과 + AI 해석을 합친다 (같은 표기는 내장 사전을 우선하고 AI 의 영문·비고만 보탠다)."""
    out = {r["term"].lower(): dict(r) for r in local}
    for a in ai or []:
        t = str(a.get("term", "")).strip()
        if not t:
            continue
        k = t.lower()
        if k in out:
            out[k]["english"] = out[k]["english"] or a.get("english", "")
            out[k]["note"] = out[k]["note"] or a.get("note", "")
        else:
            out[k] = {"term": t, "kind": a.get("kind", "용어"), "meaning": a.get("meaning", ""), "english": a.get("english", ""),
                      "note": a.get("note", ""), "src": "AI", "n": 1}
    return list(out.values())


def apply_to_text(text: str, rows: list[dict]) -> tuple[str, int]:
    """본문의 약어를 ‘약어(해석)’ 형태로 바꾼다 — 각 약어의 첫 등장만, 이미 괄호 해석이 붙은 곳은 건너뜀."""
    n = 0
    for r in rows:
        if r.get("kind") != "약어" or not r.get("meaning"):
            continue
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(r["term"]) + r"(?![A-Za-z0-9])(?!\s*\()", re.I)
        m = pat.search(text)
        if m:
            text = text[:m.end()] + f"({r['meaning']})" + text[m.end():]
            n += 1
    return text, n
