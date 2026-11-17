"""해부학적 부위 이미지 — 검색어에 맞는 인체 의료 이미지(X-ray·CT·MRI·병리·해부도)를 Wikimedia Commons / Wikipedia 에서 찾고,
선택적으로 Gemini 비전으로 연관률을 채점한다. (원본 웹앱의 '질환·부위 이미지 자동 검색'과 같은 방식)"""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import quote

from . import gemini

# 질환어(한글) → [영문, 파일명 판별 정규식] / 부위(한글) → 영문 해부학 용어 (원본 웹앱의 사전)
DIS_EN = json.loads(r'''{"종양":["tumor","tumou?r|neoplasm|cancer|carcinoma|glioma|glioblastoma|meningioma|lymphoma|sarcoma|metasta|adenoma|astrocytoma|blastoma"],"암":["cancer","cancer|carcinoma|tumou?r|neoplasm|malignan|metasta"],"신생물":["tumor","tumou?r|neoplasm|cancer|carcinoma|adenoma"],"골절":["fracture","fracture"],"탈구":["dislocation","dislocat"],"염좌":["sprain","sprain"],"궤양":["ulcer","ulcer"],"경색":["infarction","infarct|stroke"],"출혈":["hemorrhage","ha?emorrhag|bleed|hematoma"],"혈종":["hematoma","ha?ematoma"],"결석":["stone","stone|calcul|lith"],"낭종":["cyst","cyst"],"용종":["polyp","polyp"],"폴립":["polyp","polyp"],"협착":["stenosis","stenosis"],"동맥류":["aneurysm","aneurysm"],"농양":["abscess","abscess"],"탈장":["hernia","hernia"],"폐렴":["pneumonia","pneumonia"],"결핵":["tuberculosis","tubercul"],"간경변":["cirrhosis","cirrhosis"],"경화":["sclerosis","sclerosis|cirrhosis"],"관절염":["arthritis","arthritis"],"골다공증":["osteoporosis","osteoporo"],"백내장":["cataract","cataract"],"녹내장":["glaucoma","glaucoma"],"천공":["perforation","perforat"],"폐색":["obstruction","obstruct|ileus"],"염증":["inflammation","inflamm|itis"],"염":["inflammation","inflamm|itis"],"감염":["infection","infect"],"부종":["edema","o?edema"],"섬유화":["fibrosis","fibrosis"],"위축":["atrophy","atroph"],"비대":["hypertrophy","hypertroph|enlarg"],"손상":["injury","injur|trauma"],"전이":["metastasis","metasta"]}''')
ANAT_EN = json.loads(r'''{"손목뼈":"Carpal bones","손가락뼈":"Phalanges of hand","발목뼈":"Tarsal bones","뇌":"Brain","대뇌":"Cerebrum","소뇌":"Cerebellum","뇌간":"Brainstem","전두엽":"Frontal lobe","측두엽":"Temporal lobe","두정엽":"Parietal lobe","후두엽":"Occipital lobe","수막":"Meninges","척수":"Spinal cord","뇌하수체":"Pituitary gland","갑상선":"Thyroid","눈":"Eye","귀":"Ear","코":"Nose","부비동":"Paranasal sinuses","인두":"Pharynx","후두":"Larynx","구강":"Mouth","혀":"Tongue","식도":"Esophagus","위":"Stomach","십이지장":"Duodenum","소장":"Small intestine","대장":"Large intestine","결장":"Colon","직장":"Rectum","항문":"Anus","충수":"Appendix","간":"Liver","담낭":"Gallbladder","담관":"Bile duct","췌장":"Pancreas","비장":"Spleen","복막":"Peritoneum","복강":"Abdominal cavity","기관":"Trachea","기관지":"Bronchus","폐":"Lung","흉막":"Pleura","심장":"Heart","대동맥":"Aorta","관상동맥":"Coronary arteries","정맥":"Vein","신장":"Kidney","요관":"Ureter","방광":"Urinary bladder","요도":"Urethra","전립선":"Prostate","고환":"Testicle","자궁":"Uterus","자궁경부":"Cervix","난소":"Ovary","유방":"Breast","피부":"Skin","뼈":"Bone","척추":"Vertebral column","경추":"Cervical vertebrae","요추":"Lumbar vertebrae","골반":"Pelvis","대퇴골":"Femur","경골":"Tibia","비골":"Fibula","상완골":"Humerus","요골":"Radius","척골":"Ulna","손":"Hand","손가락":"Finger","손목":"Wrist","발":"Foot","발가락":"Toe","발목":"Ankle","무릎":"Knee","고관절":"Hip joint","어깨":"Shoulder","팔꿈치":"Elbow","림프절":"Lymph node","부신":"Adrenal gland","골수":"Bone marrow","혈관":"Blood vessel","신경":"Nerve"}''')

# ───────── 이미지 검색 (Wikimedia Commons · Wikipedia) ─────────
BAD = re.compile(r"chimp|monkey|ape\b|gorilla|primate|mouse|mice|\brat\b|\bcat\b|feline|dog|canine|\bpig|swine|sheep|goat|\bcow|cattle|bovine|horse|equine|camel|rabbit|chicken|bird|avian|fish|frog|reptile|lizard|snake|whale|dolphin|insect|animal|veterinar|vertebrate|mammal|\bjar\b|food|dish|cuisine|market|[؀-ۿ]", re.I)
FOREIGN = re.compile(r"[-_ (](ar|es|esp|fr|de|ru|fa|he|ur|zh|ja|ko|pt|it|uk|pl|tr|ca|eu|gl|hu|cs|nl|sv|vi|th|id|ro|bg|sr|hr|el|ta|hi|bn|ms|fi|da|no|sk|sl|lt|lv|et|mk|sq|az|ka|hy|kk|uz)(\)|[-_ .]|$)", re.I)
EN_LAB = re.compile(r"[-_ (](en|eng|english|labeled|labelled)(\)|[-_ .]|$)", re.I)
MEDICAL = re.compile(r"mri|\bct\b|x-?ray|radiograph|scan|histo|patholog|micrograph|blausen|diagram|illustration|human|gray|sobotta|patient|tumou?r|carcinoma|fracture", re.I)
HUMAN_ANAT = re.compile(r"gray|sobotta|blausen|human|homo sapiens|\bman\b|woman|male|female|anatomy of the", re.I)
JUNK = re.compile(r"logo|icon|symbol|wiki|commons|question_book|ambox|edit-clear|padlock|flag|portal|disambig|crystal|nuvola|stub|text-x|folder|sound|speaker|lock-|red_pog|blue_pog|location", re.I)
IMG_RE = re.compile(r"x-?ray|radiograph|\bct\b|mri|scan", re.I)

_CACHE: dict = {}
_TTL = 7 * 86400


def _stem(title: str) -> str:
    return re.sub(r"\.\w+$", "", re.sub(r"^File:", "", title, flags=re.I))


# 이미지 목록은 사용자 PC의 브라우저가 Wikimedia 에 직접 요청해 가져온다 (서버 요청은 Wikimedia 정책상 차단되고, 연락처를 보낼 수도 없음).
# 이 모듈은 요청 주소를 만들고, 돌려받은 JSON 을 거르고 순위를 매기는 일만 한다.
def commons_url(q: str) -> str:
    return ("https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrnamespace=6&gsrlimit=16&gsrsearch="
            + quote(q) + "&prop=imageinfo&iiprop=url|mime&iiurlwidth=320")


def wp_url(title: str) -> str:
    return ("https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*&redirects=1&titles=" + quote(title)
            + "&generator=images&gimlimit=30&prop=imageinfo&iiprop=url|mime&iiurlwidth=320")


def _pages(text: str | None) -> list[dict]:
    try:
        return list((((json.loads(text) if text else {}).get("query")) or {}).get("pages", {}).values())
    except (ValueError, AttributeError):
        return []


def parse_commons(text: str | None, need: re.Pattern | None, rel: re.Pattern | None, brand: re.Pattern) -> list[dict]:
    ok = []
    for p in _pages(text):
        ii = (p.get("imageinfo") or [None])[0]
        t = _stem(p.get("title", ""))
        if not ii or not re.search(r"image/(png|svg|jpeg)", ii.get("mime", "")) or BAD.search(p.get("title", "")):
            continue
        if (need and not need.search(t)) or (rel and not rel.search(t)):
            continue
        ok.append((p, ii, t))

    def rank(x) -> int:
        f, br = bool(FOREIGN.search(x[2])), bool(brand.search(x[2]))
        if not f and br:
            return 0
        if not f:
            return 1
        return 2 if EN_LAB.search(x[2]) else 3
    ok.sort(key=lambda x: (rank(x), x[0].get("index", 99)))
    return [{"img": ii.get("thumburl") or ii.get("url"), "full": ii.get("url"), "title": t.replace("_", " "),
             "url": ii.get("descriptionurl") or "https://commons.wikimedia.org/wiki/" + quote(p.get("title", "")),
             "src": "Wikimedia Commons"} for p, ii, t in ok[:6]]


def parse_wp(text: str | None) -> list[dict]:
    out = []
    for p in _pages(text):
        ii = (p.get("imageinfo") or [None])[0]
        if not ii or not re.search(r"image/(png|jpeg)", ii.get("mime", "")) or JUNK.search(p.get("title", "")) or BAD.search(p.get("title", "")):
            continue
        out.append({"img": ii.get("thumburl") or ii.get("url"), "full": ii.get("url"), "title": _stem(p["title"]).replace("_", " "),
                    "url": ii.get("descriptionurl") or "https://commons.wikimedia.org/wiki/" + quote(p["title"]), "src": "Wikipedia · Commons"})
    return out[:8]


async def find_images(site_ko: str, dis_ko: str, en_label: str, fetch_many) -> dict:
    """부위(한글)·질환어(한글)로 인체 의료 이미지 후보를 찾는다.
    fetch_many(urls) → 같은 순서의 응답 본문 목록(실패는 None) — 브라우저에서 실행된다."""
    key = (site_ko, dis_ko, en_label)
    hit = _CACHE.get(key)
    if hit and time.time() - hit["at"] < _TTL:
        return hit["val"]
    term = ANAT_EN.get(site_ko, "")
    dk = next((k for k in sorted(DIS_EN, key=len, reverse=True) if dis_ko and k in dis_ko), "")
    d_en, d_rel = (DIS_EN[dk][0], re.compile(DIS_EN[dk][1], re.I)) if dk else ("", None)
    site_rel = re.compile("|".join(re.sub(r"[^a-z]", "", w, flags=re.I) for w in term.split() if len(w) > 3) or re.escape(term), re.I) if term else None
    en_label = (en_label or "").strip()
    either_src = [x.pattern for x in (d_rel, site_rel) if x is not None]
    if en_label:
        either_src.append("|".join(w for w in en_label.split() if len(w) > 4) or ".")
    either = re.compile("|".join(either_src) or ".", re.I)
    xr = re.compile(r"x-?ray|radiograph|mri|\bct\b", re.I)
    cand: list[dict] = []

    def add(lst: list[dict]) -> None:
        for x in lst or []:
            if len(cand) < 24 and not any(y["url"] == x["url"] for y in cand):
                cand.append(x)

    jobs: list[tuple[str, str, object]] = []   # (url, 종류, 해석 함수)
    kind = ""
    if d_en and term:
        both = re.compile(rf"(?=.*({site_rel.pattern if site_rel else re.escape(term)}))(?=.*({d_rel.pattern}))", re.I)
        for q, rel in ((f"{term} {d_en}", both), (f"{term} {d_en} x-ray OR MRI OR CT", both), (f"{term} {d_en}", either), (f"{d_en} {term} xray", either)):
            jobs.append((commons_url(q), "c", lambda tx, rel=rel: parse_commons(tx, None, rel, xr)))
        jobs.append((wp_url(f"{term} {d_en}"), "w", parse_wp))
        kind = "dis"
    elif d_en:    # 부위 없이 질환만 (예: 폐렴) — 질환 문서의 영상 · 병리 사진
        jobs.append((wp_url(d_en.capitalize()), "w", parse_wp))
        jobs.append((commons_url(f"{d_en} MRI OR CT OR x-ray"), "c", lambda tx: parse_commons(tx, None, either, xr)))
        jobs.append((commons_url(d_en), "c", lambda tx: parse_commons(tx, MEDICAL, either, re.compile(r"blausen|mri|\bct\b|histo|patholog", re.I))))
        kind = "dis"
    if en_label:
        jobs.append((wp_url(en_label), "w", parse_wp))
        jobs.append((commons_url(f"{en_label} MRI OR CT"), "c", lambda tx: parse_commons(tx, None, either, xr)))
        kind = kind or "dis"
    if jobs:
        texts = await fetch_many([j[0] for j in jobs])
        for (u, _, fn), tx in zip(jobs, texts):
            add(fn(tx))
    if not cand and term:   # 질환 이미지가 없으면 부위 해부도
        brand = re.compile(r"gray|sobotta|blausen", re.I)
        qs = [f"Gray {term}", f"Sobotta {term}"]
        texts = await fetch_many([commons_url(q) for q in qs])
        for tx in texts:
            add(parse_commons(tx, HUMAN_ANAT, site_rel, brand))
        kind = "anat"

    def has_s(x: dict) -> bool:
        return bool(site_rel and site_rel.search(x["title"]))

    def has_d(x: dict) -> bool:
        return bool(d_rel and d_rel.search(x["title"]))

    def pr(x: dict) -> int:
        if has_s(x) and has_d(x):
            return 0
        if has_s(x) or has_d(x):
            return 1 if IMG_RE.search(x["title"]) else 2
        return 3
    cand = [c for _, c in sorted(enumerate(cand), key=lambda t: (pr(t[1]), t[0]))][:6]
    val = {"list": cand, "kind": kind, "term": term, "dis": d_en}
    if cand:
        _CACHE[key] = {"at": time.time(), "val": val}
    return val


def score_images(loaded: list[tuple[dict, str, str]], target: str, kind: str) -> list[dict]:
    """loaded: [(후보, mime, base64)] — Gemini 비전으로 연관률(0~100)을 채점해 score 를 붙여 높은 순으로 돌려준다."""
    if not loaded:
        raise RuntimeError("이미지를 불러오지 못했습니다.")
    parts: list[dict] = []
    for i, (_, mime, b64) in enumerate(loaded, 1):
        parts += [{"text": f"[이미지 {i}]"}, {"inlineData": {"mimeType": mime, "data": b64}}]
    parts.append({"text": f"대상: {target}\n이미지 {len(loaded)}개를 채점하세요."})
    sysmsg = ("당신은 의료 영상·해부학 검수자입니다. 각 이미지가 대상과 얼마나 직접 관련되는지 0~100으로 채점합니다.\n"
              "90~100: 대상 부위의 인체 이미지이고 " + ("그 질환을 보여줌(X-ray·CT·MRI·병리·도해)" if kind == "dis" else "그 부위의 인체 해부도·도해") + ".\n"
              "60~89: 부위는 맞지만 질환이 불분명하거나 질환은 맞지만 다른 부위가 함께 크게 나옴.\n"
              "30 이하: 다른 부위·다른 질환. 0~20: 사람이 아님, 글자·표·책 표지·장비 사진.\n작거나 흐려도 대상이 식별되면 감점하지 않습니다.")
    schema = {"type": "OBJECT", "properties": {"scores": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "i": {"type": "INTEGER"}, "score": {"type": "INTEGER"}}, "required": ["i", "score"]}}}, "required": ["scores"]}
    j = json.loads(gemini.generate(sysmsg, parts, schema, 1024))
    out = []
    for s in j.get("scores", []):
        idx = int(s.get("i", 0)) - 1
        if 0 <= idx < len(loaded):
            out.append({**loaded[idx][0], "score": max(0, min(100, int(s.get("score", 0))))})
    return sorted(out, key=lambda x: -x["score"])
