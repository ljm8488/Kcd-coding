"""순수 기능 단위 테스트 (네트워크·DB 없이 실행) — python_app 폴더에서:  python -m pytest tests -q"""
import io
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import export, pii, terms, work  # noqa: E402
from app.search import KcdIndex  # noqa: E402


# ───────── 개인정보 가림 ─────────
def test_pii_masks_identifiers():
    t, c = pii.mask("성명: 홍길동 주민등록번호 900101-1234567 연락처 010-1234-5678\n주소: 서울특별시 강남구 테헤란로 123")
    assert "900101" not in t and "010-1234" not in t and "홍길동" not in t and "테헤란로" not in t
    assert c["rrn"] == 1 and c["tel"] == 1 and c["name"] == 1 and c["addr"] == 1


def test_pii_keeps_clinical_text():
    s = "환자는 multifocal pressure ulcer를 주소로 입원하여 보호자 면담 시행. CRP 15.2, BP 120/80, 2026-11-20"
    assert pii.mask(s)[0] == s            # '주소로'(주호소) · '보호자 면담' 은 개인정보가 아니다


def test_pii_idempotent():
    once = pii.mask("성명: 홍길동 010-1234-5678 생년월일: 1954.03.02")[0]
    assert pii.mask(once)[0] == once


# ───────── 용어 해석 ─────────
ROWS = [{"term": "ESRD", "kind": "약어", "meaning": "말기 신장병", "english": ""},
        {"term": "HD", "kind": "약어", "meaning": "혈액투석", "english": ""},
        {"term": "multifocal pressure ulcer", "kind": "용어", "meaning": "다발성 욕창", "english": ""}]


def test_josa_after_substitution():
    out = terms.substitute_line("환자는 multifocal pressure ulcer를 주소로 입원", ROWS)
    assert "다발성 욕창을" in out and "욕창를" not in out


def test_wrapped_lines_become_one_sentence():
    text = "#. h/o NSTEMI\n환자는 multifocal pressure ulcer를 주소로 입원하여 치료 중이며 영상검사에서\n보이나 상태 불량하여 수술적 처치를 못한 상태로 중환자실 입\n원치료 진행하였습니다.\n\n#. ESRD on HD"
    bl = terms.blocks(text)
    assert ["#. h/o NSTEMI"] in bl and ["#. ESRD on HD"] in bl
    para = next(b for b in bl if len(b) == 3)
    assert "입원치료" in terms.block_text(para)           # '입' + '원치료' 를 이어 붙인다


def test_annotate_html_escapes():
    html = terms.annotate_html("<b>ESRD</b> on HD", ROWS)
    assert "<b>" not in html.replace("<span", "").replace("</span>", "") or "&lt;b&gt;" in html
    assert "말기 신장병" in html and "혈액투석" in html


# ───────── 작업 보관 ─────────
def test_work_expiry_and_logout():
    work.put("u1|b1", {"text": "a"})
    work.put("u1|b2", {"text": "b"})
    work.put("u2|b1", {"text": "c"})
    work.clear_user("u1")
    assert work.get("u1|b1") is None and work.get("u2|b1") is not None
    old = work.TTL
    work.TTL = 0.05
    time.sleep(0.1)
    assert work.get("u2|b1") is None
    work.TTL = old


# ───────── 내려받기 파일 ─────────
def _ctx():
    return {"title": "의무기록(소견서) 판독 결과", "meta": ["출력 2026-11-23"], "text": "#. ESRD on HD\n<주소> & 'x'",
            "annotated": terms.pairs_plain(terms.doc_pairs("#. ESRD on HD", ROWS)), "terms": ROWS,
            "codes": [{"code": "N18.5", "name_ko": "만성 신장병", "role": "주진단", "confidence": 95, "reason": "ESRD on HD"}],
            "caution": "", "sel": {"c1": True, "c2": True, "c2b": True, "c3": True}, "names": {}}


def test_hwpx_is_well_formed_with_real_tables():
    z = zipfile.ZipFile(io.BytesIO(export.build_hwpx(_ctx())))
    assert z.namelist()[0] == "mimetype" and z.infolist()[0].compress_type == zipfile.ZIP_STORED
    for n in z.namelist():
        if n.endswith((".xml", ".hpf")):
            ET.fromstring(z.read(n))
    sec = z.read("Contents/section0.xml").decode("utf8")
    assert sec.count("<hp:tbl ") == 2 and "&lt;주소&gt;" in sec
    hdr = z.read("Contents/header.xml").decode("utf8")
    assert 'borderFills itemCnt="4"' in hdr and 'charProperties itemCnt="11"' in hdr


def test_xlsx_opens():
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(export.build_xlsx(_ctx())))
    assert any("AI" in n for n in wb.sheetnames)


# ───────── 검색 ─────────
SAMPLE = [["J18", "폐렴, 상세불명", "Pneumonia, unspecified", ""], ["J18.9", "상세불명의 폐렴", "Pneumonia, unspecified", ""],
          ["J43", "폐기종", "Emphysema", ""], ["J44", "기타 만성 폐쇄성 폐질환", "COPD", "만성폐쇄성폐질환"],
          ["C61", "전립선의 악성 신생물", "Malignant neoplasm of prostate", ""], ["C23", "담낭의 악성 신생물", "Malignant neoplasm of gallbladder", ""],
          ["C67", "방광의 악성 신생물", "Malignant neoplasm of bladder", ""], ["T93.1", "대퇴골골절의 후유증", "Sequelae of fracture of femur", ""],
          ["S72", "대퇴골의 골절", "Fracture of femur", ""]]


def test_search_code_forms():
    ix = KcdIndex(SAMPLE)
    for q in ("J18.9", "j189", "J189"):
        assert ix.search(q)[0].code == "J18.9"


def test_search_generic_cancer_rules():
    ix = KcdIndex(SAMPLE)
    assert ix.search("전립선암")[0].code == "C61"           # OO암 → OO의 악성 신생물
    assert ix.search("prostate cancer")[0].code == "C61"
    assert ix.search("bladder cancer")[0].code == "C67"     # gallbladder 속 bladder 는 제외


def test_search_sequela_ranked_late_and_long_input_fast():
    ix = KcdIndex(SAMPLE)
    assert ix.search("대퇴골 골절")[0].code == "S72"
    t = time.time()
    ix.search("가" * 500)
    assert time.time() - t < 1.0
