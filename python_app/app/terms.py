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
  "uti":"요로감염","apn":"급성 신우신염","bph":"전립선비대증","gerd":"위식도역류병","ibs":"과민성대장증후군",
  # 자주 쓰는 진료기록 약어 (정확한 표준 용어만)
  "esrd":"말기 신장병(말기 신부전)","ckd":"만성 신장병","hd":"혈액투석","pd":"복막투석","crrt":"지속적 신대체요법",
  "nstemi":"비ST분절상승 심근경색증","stemi":"ST분절상승 심근경색증","mi":"심근경색증","pci":"경피적 관상동맥 중재술",
  "cabg":"관상동맥 우회로 이식술","chf":"울혈성 심부전","af":"심방세동","dm":"당뇨병","htn":"고혈압","copd":"만성 폐쇄성 폐질환",
  "tb":"결핵","cva":"뇌혈관 사고(뇌졸중)","tia":"일과성 허혈 발작","ami":"급성 심근경색증","ihd":"허혈성 심장질환",
  "crp":"C-반응단백","wbc":"백혈구","rbc":"적혈구","hb":"혈색소","hct":"헤마토크릿","plt":"혈소판","bun":"혈액요소질소","cr":"크레아티닌",
  "gfr":"사구체 여과율","lft":"간기능검사","ast":"아스파르테이트 아미노전이효소","alt":"알라닌 아미노전이효소","pt":"프로트롬빈 시간",
  "icu":"중환자실","er":"응급실","opd":"외래","npo":"금식","iv":"정맥 주사","im":"근육 주사","po":"경구","prn":"필요시","bid":"하루 2회",
  "tid":"하루 3회","qid":"하루 4회","qd":"하루 1회","ct":"전산화단층촬영","mri":"자기공명영상","ekg":"심전도","ecg":"심전도",
  "egd":"식도위십이지장내시경","cfs":"대장내시경","ercp":"내시경적 역행성 담췌관조영술","ptbd":"경피경간 담도배액술",
  "gcs":"글래스고 혼수척도","spo2":"산소포화도","bp":"혈압","hr":"심박수","rr":"호흡수","bt":"체온","dnr":"심폐소생술 거부",
  "c/w":"~와 일치","w/u":"정밀 검사","p/o":"수술 후","h/o":"병력","n/v":"오심·구토","uri":"상기도 감염","hbv":"B형 간염 바이러스",
  "hcv":"C형 간염 바이러스","hiv":"인체면역결핍바이러스","fn":"발열성 호중구감소증","ards":"급성 호흡곤란증후군","sirs":"전신 염증 반응 증후군"
}

# 약어 중 일반 영단어와 겹치는 것 — 대문자로 쓰인 경우에만 약어로 본다
AMBIG = {"both", "mass", "ext", "le", "ue", "op", "dx", "hx", "tx", "sx", "ta", "bil", "rt", "lt", "ca", "tu",
         "mi", "af", "tb", "er", "iv", "im", "po", "pt", "ct", "bp", "hr", "rr", "bt", "cr", "hd", "pd", "fn", "ast", "alt", "plt", "ihd"}
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


def annotate_segments(text: str, rows: list[dict]) -> list[tuple[str, dict | None]]:
    """본문을 (조각, 해석 행 또는 None) 목록으로 나눈다 — 해석이 붙는 용어는 행과 함께, 나머지는 None"""
    items = {}
    for r in rows or []:
        t, m = str(r.get("term", "")).strip(), str(r.get("meaning", "")).strip()
        if t and m and t.lower() != m.lower():
            items.setdefault(t.lower(), r)
    if not text:
        return []
    if not items:
        return [(text, None)]

    def alt(k: str) -> str:
        e = re.escape(k)
        return (r"(?<![A-Za-z0-9])" + e + r"(?![A-Za-z0-9])") if re.fullmatch(r"[A-Za-z0-9 .\-/']+", k) else e

    rx = re.compile("|".join(alt(k) for k in sorted(items, key=len, reverse=True)), re.I)
    out: list[tuple[str, dict | None]] = []
    pos = 0
    for m in rx.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], None))
        out.append((m.group(0), items.get(m.group(0).lower())))      # 대소문자·공백 차이로 못 찾으면 해석 없이 그대로
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], None))
    return out


def annotate_html(text: str, rows: list[dict]) -> str:
    """원문 그대로 두고, 의학용어·약어 바로 옆에 한글 해석을 붙인 HTML — 예) HTN<em>고혈압</em>. 줄바꿈은 호출하는 쪽 CSS(pre-wrap)가 살린다."""
    import html as _h
    out = []
    for seg, r in annotate_segments(text, rows):
        if r is None:
            out.append(_h.escape(seg))
        else:
            title = _h.escape(" · ".join(x for x in (r.get("english", ""), r.get("note", "")) if x), quote=True)
            out.append(f'<span class="kcm-tm" title="{title}">{_h.escape(seg)}<em>{_h.escape(str(r["meaning"]))}</em></span>')
    return "".join(out)


def annotate_plain(text: str, rows: list[dict]) -> str:
    """파일(Excel · 한글)용 글자만 — 예) HTN[→고혈압]"""
    return "".join(seg if r is None else f"{seg}[→{r['meaning']}]" for seg, r in annotate_segments(text, rows))


_RES_STOP = {"and", "or", "in", "on", "at", "of", "the", "to", "for", "by", "from", "with", "without", "is", "are", "was", "were", "be", "been",
             "no", "not", "a", "an", "as", "due", "but", "then", "than", "that", "this", "these", "those", "there", "its", "it", "cm", "mm", "kg", "mg",
             "ml", "mmhg", "bpm", "etc", "see", "per", "x", "vs", "or", "both", "also", "after", "before", "during", "about", "which", "while"}
_RES_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'./\-]*(?:[ \t]+[A-Za-z][A-Za-z0-9'./\-]*)*")


def appears(term: str, text: str) -> bool:
    """AI가 돌려준 용어가 실제로 본문에 있는지(대소문자·공백 차이 허용) — 없는 용어를 지어내는 것을 거른다"""
    t = re.sub(r"\s+", " ", term.strip().lower())
    return bool(t) and t in re.sub(r"\s+", " ", (text or "").lower())


def residual_english(text: str, rows: list[dict], limit: int = 70) -> list[str]:
    """이미 해석된 용어를 뺀 뒤에도 본문에 남은 영어 표현(구 단위) — 2차로 AI에게 빠짐없이 해석시키기 위한 목록"""
    if not text:
        return []
    covered = [r["term"] for r in rows or [] if r.get("term") and r.get("meaning")]
    masked = text
    for t in sorted(covered, key=len, reverse=True):
        e = re.escape(t.strip())
        pat = (r"(?<![A-Za-z0-9])" + e + r"(?![A-Za-z0-9])") if re.fullmatch(r"[A-Za-z0-9 .\-/']+", t.strip()) else e
        masked = re.sub(pat, lambda m: "\x00" * len(m.group(0)), masked, flags=re.I)
    out: list[str] = []
    seen = set()
    for m in _RES_RUN.finditer(masked):
        words = [w for w in re.split(r"\s+", m.group(0)) if w]
        while words and words[0].lower().strip(".") in _RES_STOP:
            words.pop(0)
        while words and words[-1].lower().strip(".") in _RES_STOP:
            words.pop()
        if not words:
            continue
        phrase = " ".join(words)
        if len(phrase) < 2 or re.fullmatch(r"[A-Za-z]", phrase) or phrase.lower() in seen:
            continue
        seen.add(phrase.lower())
        out.append(phrase)
        if len(out) >= limit:
            break
    return out


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
