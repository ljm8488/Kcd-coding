"""개인식별정보 가림(블라인드) — 판독한 소견서·의무기록에서 개인정보 표기를 지운다.
가리는 것: 주민(외국인)등록번호 · 전화번호 · 이메일 · 카드/계좌번호 · 성명 · 주소 · 생년월일 · 병록/환자/보험증 번호 등 식별번호.
판독 결과를 본문에 넣을 때, AI(외부 서비스)로 보내기 전, 이력에 저장하기 전, 인쇄할 때 모두 이 함수를 거친다.
(나이·성별·진단·검사 수치처럼 코딩에 필요한 정보는 그대로 둔다.)"""
from __future__ import annotations

import re

MARKS = {"rrn": "[주민번호 가림]", "tel": "[전화번호 가림]", "mail": "[이메일 가림]", "card": "[카드·계좌번호 가림]",
         "name": "[성명 가림]", "addr": "[주소 가림]", "birth": "[생년월일 가림]", "id": "[식별번호 가림]"}
LABELS = {"rrn": "주민등록번호", "tel": "전화번호", "mail": "이메일", "card": "카드·계좌번호",
          "name": "성명", "addr": "주소", "birth": "생년월일", "id": "식별번호"}

# 주민등록번호·외국인등록번호: 6자리 - 7자리 (뒷자리 일부가 이미 *, ●로 가려져 있어도 가린다)
_RRN = re.compile(r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))\s*[-–—~]\s*([1-8][\d*●○ⅹXx]{6})(?!\d)")
_RRN_FLAT = re.compile(r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))([1-8]\d{6})(?!\d)")
# 전화번호: 휴대전화(010 등) · 지역번호(02, 031 …) · 대표번호(1588-0000) · 괄호·점·공백 구분 허용
_TEL = [
    re.compile(r"(?<![\d-])\(?01[016789]\)?[-.\s)]{0,2}\d{3,4}[-.\s]{0,2}\d{4}(?![\d-])"),
    re.compile(r"(?<![\d-])\(?0(?:2|[3-6][1-5]|70|50\d?)\)?[-.\s)]{1,2}\d{3,4}[-.\s]\d{4}(?![\d-])"),
    re.compile(r"(?<![\d-])1[5-9]\d{2}[-.\s]\d{4}(?![\d-])"),
]
_MAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<![\d-])\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?![\d-])")
# 이름 뒤에 ‘2000.01.01생’ 같은 생년월일 표기
_BIRTH = re.compile(r"(?<!\d)(?:19|20)\d{2}[ \t]*[.\-/년][ \t]*\d{1,2}[ \t]*[.\-/월][ \t]*\d{1,2}[ \t]*일?[ \t]*생")
# 도로명 주소: ‘…시/군/구 … 로/길 123(-4)’
_ADDR = re.compile(r"[가-힣]{1,6}(?:특별시|광역시|특별자치시|특별자치도|도|시)\s+[가-힣0-9 ]{1,14}(?:구|군|시)\s+[가-힣0-9 ]{1,16}(?:로|길|동|읍|면)\s*\d{0,5}(?:-\d{1,5})?(?:번길)?\s*\d{0,5}(?:-\d{1,5})?(?:\s*\([^)\n]{1,20}\))?")
# 이름표 뒤의 값 — 라벨은 남기고 값만 가린다
_LABEL_NAME = re.compile(r"((?<!\[)(?:환자[ \t]*)?(?:성[ \t]*명|이[ \t]*름|환자명|보호자[ \t]*명|보호자)[ \t]*+[:：]?+[ \t]*+)(?![ \t]*(?:없음|불상|미상|불명|미기재|생략|가림|\[))([가-힣]{2,4})(?![가-힣])")
_LABEL_ADDR = re.compile(r"((?<!\[)(?:주[ \t]*소|거주지|자택)[ \t]*+[:：]?+[ \t]*+)(?![ \t]*(?:없음|불상|미상|불명|미기재|\[|가림))([^\n]{3,60})")
_LABEL_ID = re.compile(r"((?<!\[)(?:병록|등록|환자|차트|보험증|증|면허|사업자|여권)\s*번호[ \t]*[:：]?[ \t]*)([A-Za-z0-9\-*●]{4,20})")
_LABEL_BIRTH = re.compile(r"((?<!\[)생[ \t]*년[ \t]*월[ \t]*일[ \t]*[:：]?[ \t]*)((?:19|20)?\d{2}[ \t]*[.\-/년]?[ \t]*\d{1,2}[ \t]*[.\-/월]?[ \t]*\d{1,2}[ \t]*일?)")
_LABEL_ACCT = re.compile(r"((?:계좌|카드)[ \t]*번호[ \t]*[:：]?[ \t]*)([\d\- \t]{8,24}\d)")


def mask(text: str) -> tuple[str, dict]:
    """(가린 본문, {분류: 건수})"""
    c = {k: 0 for k in MARKS}
    if not text:
        return text, c

    def sub(pat, repl, key, s):
        s, k = pat.subn(repl, s)
        c[key] += k
        return s

    t = text
    t = sub(_RRN, MARKS["rrn"], "rrn", t)
    t = sub(_RRN_FLAT, MARKS["rrn"], "rrn", t)
    t = sub(_MAIL, MARKS["mail"], "mail", t)
    t = sub(_CARD, MARKS["card"], "card", t)
    t = sub(_LABEL_ACCT, lambda m: m.group(1) + MARKS["card"], "card", t)
    for p in _TEL:
        t = sub(p, MARKS["tel"], "tel", t)
    t = sub(_LABEL_BIRTH, lambda m: m.group(1) + MARKS["birth"], "birth", t)
    t = sub(_BIRTH, MARKS["birth"], "birth", t)
    t = sub(_LABEL_ADDR, lambda m: m.group(1) + MARKS["addr"], "addr", t)
    t = sub(_ADDR, MARKS["addr"], "addr", t)
    t = sub(_LABEL_ID, lambda m: m.group(1) + MARKS["id"], "id", t)
    t = sub(_LABEL_NAME, lambda m: m.group(1) + MARKS["name"], "name", t)
    return t, c


def clean(text: str) -> str:
    return mask(text)[0]


def summary(c: dict) -> str:
    return ", ".join(f"{LABELS[k]} {n}건" for k, n in c.items() if n)
