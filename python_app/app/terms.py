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


_EN_CACHE: dict = {"key": None, "map": {}}
_EN_STOP = {"other", "others", "unspecified", "acute", "chronic", "disease", "diseases", "disorder", "disorders", "syndrome", "injury",
            "infection", "tumor", "neoplasm", "failure", "benign", "malignant", "primary", "secondary", "primary", "mild", "severe",
            "left", "right", "both", "pain", "of", "with", "without", "and", "the"}
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")


def has_english(text: str) -> bool:
    """영어 단어(3글자 이상)나 영문 약어(대문자 2~6자)가 본문에 있는지"""
    return bool(re.search(r"[A-Za-z]{3,}", text or "") or re.search(r"\b[A-Z]{2,6}\b", text or ""))


def _english_map(rows: list) -> dict:
    """KCD 영문명 → (한글명, 코드, 영문명). 쉼표·괄호 앞 대표 표기만, 같은 표기는 가장 짧은(상위) 코드를 쓴다."""
    key = (len(rows), rows[0][0] if rows else "", rows[-1][0] if rows else "")
    if _EN_CACHE["key"] == key:
        return _EN_CACHE["map"]
    m: dict[str, tuple] = {}
    for r in rows:
        if len(r) < 3 or not r[2]:
            continue
        head = re.split(r"[,(;]|\bNOS\b|\bunspecified\b", r[2], maxsplit=1, flags=re.I)[0].strip().lower()
        words = head.split()
        if len(head) < 4 or not 1 <= len(words) <= 4 or head in _EN_STOP or not re.fullmatch(r"[a-z][a-z\-' ]+", head):
            continue
        cur = m.get(head)
        rk = (len(r[0].replace(".", "")), len(r[1]))
        if cur is None or rk < (len(cur[1].replace(".", "")), len(cur[0])):
            m[head] = (r[1], r[0], r[2])
    _EN_CACHE.update(key=key, map=m)
    return m


def _clean_ko(ko: str) -> str:
    """KCD 한글명의 ‘상세불명의 · 기타 명시된 · …을 동반한’ 같은 분류용 수식을 떼어 일반 용어에 가깝게 만든다"""
    s = re.sub(r"^(기타 및 )?(상세불명 병원체|상세불명|기타 명시된|기타)(의|인)?\s*", "", ko.strip())
    s = re.sub(r"^[^,]{1,24}(을|를)\s*동반한\s+", "", s)
    return s.strip() or ko


def english_terms(text: str, rows: list) -> list[dict]:
    """본문 속 영어 의학용어(예: pneumonia, hypertension)를 KCD 영문명으로 찾아 한글로 해석한다 — 긴 표현 우선."""
    if not text or not rows:
        return []
    emap = _english_map(rows)
    toks = [t.lower() for t in _WORD.findall(text)]
    orig = _WORD.findall(text)
    used = [False] * len(toks)
    found: dict[str, dict] = {}
    for n in (4, 3, 2, 1):
        for i in range(len(toks) - n + 1):
            if any(used[i:i + n]):
                continue
            ph = " ".join(toks[i:i + n])
            hit = emap.get(ph) or (emap.get(ph[:-1]) if ph.endswith("s") else None)
            if not hit or (n == 1 and (len(ph) < 5 or ph in _EN_STOP)):
                continue
            for j in range(i, i + n):
                used[j] = True
            row = found.setdefault(ph, {"term": " ".join(orig[i:i + n]), "kind": "용어", "meaning": _clean_ko(hit[0]), "english": hit[2],
                                        "note": f"KCD {hit[1]} · {hit[0]}" if _clean_ko(hit[0]) != hit[0] else f"KCD {hit[1]}",
                                        "src": "KCD 영문명", "n": 0})
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
