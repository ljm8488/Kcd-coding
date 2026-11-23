"""판독 결과 내려받기 — Excel(.xlsx) · 한글(.hwpx).  PDF 는 브라우저에서 만든다(phase2).
입력은 build_print_doc 과 같은 내용을 담은 dict(ctx):
  title, meta(list[str]), text(원문), annotated(해석을 붙인 글), terms(list[dict]), codes(list[dict]), caution, sel{c1,c2,c2b,c3}, names{code:ko}
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
import zipfile
from xml.sax.saxutils import escape

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKELETON = os.path.join(_HERE, "assets", "hwpx_skeleton.hwpx")


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M")


def _sections(ctx: dict) -> list[tuple[str, list[list[str]] | list[str], str]]:
    """(제목, 내용, 종류) — 종류: 'text'(줄 목록) 또는 'table'(첫 줄이 머리글인 표)"""
    sel = ctx["sel"]
    out = []
    text = ctx.get("text") or ""
    if sel.get("c1"):
        out.append(("① 의무기록(소견서) 판독 — 원문", text.splitlines() or ["(본문 없음)"], "text"))
    if sel.get("c2"):
        out.append(("② 원문 해석 문서 (의학용어·약어 한글 해석 [→] 포함)", (ctx.get("annotated") or "").splitlines() or ["(본문 없음)"], "text"))
        if sel.get("c2b") and ctx.get("terms"):
            rows = [["용어·약어", "구분", "한글 해석", "영문"]] + [[r.get("term", ""), r.get("kind", ""), r.get("meaning", ""), r.get("english", "")] for r in ctx["terms"]]
            out.append(("용어 · 약어 표", rows, "table"))
    if sel.get("c3") and ctx.get("codes"):
        names = ctx.get("names") or {}
        rows = [["코드", "상병명", "구분", "정확도(%)", "근거"]]
        for c in ctx["codes"]:
            code = str(c.get("code", "")).strip().upper()
            rows.append([code, names.get(code) or str(c.get("name_ko", "")), str(c.get("role", "")), str(c.get("confidence", "")), str(c.get("reason", ""))])
        out.append(("③ AI 해석 결과 · 코드 후보", rows, "table"))
        if ctx.get("caution"):
            out.append(("주의", [str(ctx["caution"])], "text"))
        out.append(("", ["※ AI가 제안한 내용은 참고용이며 최종 코딩은 담당자의 확인이 필요합니다."], "text"))
    return out


# ───────────────────────── Excel ─────────────────────────
def build_xlsx(ctx: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "개요"
    ws0["A1"] = ctx["title"]
    ws0["A1"].font = Font(bold=True, size=15)
    for i, line in enumerate(ctx.get("meta") or [], start=3):
        ws0.cell(row=i, column=1, value=line)
    ws0.column_dimensions["A"].width = 110
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDE6F0")
    n = 0
    for title, content, kind in _sections(ctx):
        if not title and kind == "text":                      # 맨 끝 안내 문구는 개요 시트에 붙인다
            r = ws0.max_row + 2
            ws0.cell(row=r, column=1, value=content[0]).font = Font(italic=True, color="666666")
            continue
        n += 1
        name = re.sub(r"[\\/*?:\[\]]", " ", title)[:24] or f"시트{n}"
        ws = wb.create_sheet(name)
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=13)
        if kind == "text":
            ws.column_dimensions["A"].width = 120
            for i, line in enumerate(content, start=3):
                c = ws.cell(row=i, column=1, value=line)
                c.alignment = Alignment(wrap_text=True, vertical="top")
        else:
            widths = {"코드": 12, "상병명": 44, "구분": 10, "정확도(%)": 11, "근거": 70, "용어·약어": 26, "한글 해석": 38, "영문": 40}
            for j, h in enumerate(content[0], start=1):
                c = ws.cell(row=3, column=j, value=h)
                c.font = Font(bold=True)
                c.fill = head_fill
                c.border = box
                c.alignment = Alignment(horizontal="center", vertical="center")
                ws.column_dimensions[chr(64 + j)].width = widths.get(h, 24)
            for i, row in enumerate(content[1:], start=4):
                for j, v in enumerate(row, start=1):
                    val = v
                    if content[0][j - 1] == "정확도(%)" and str(v).isdigit():
                        val = int(v)
                    c = ws.cell(row=i, column=j, value=val)
                    c.border = box
                    c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.freeze_panes = "A4"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ───────────────────────── 한글 (.hwpx) ─────────────────────────
# 문서 틀(header.xml)에 없는 서식(표 테두리 · 머리글 색 · 굵은 글씨 · 가운데 정렬)을 몇 개 더해서 쓴다.
_TEXT_W = 42520            # A4 본문 폭(HWPUNIT) — 틀의 여백 기준
_BF_CELL, _BF_HEAD = 3, 4  # 새 테두리/채움 번호
_CP_TITLE, _CP_H2, _CP_BOLD, _CP_GLOSS = 9, 8, 7, 10
_CP_BODY, _CP_SMALL = 1, 2
_PP_LEFT, _PP_CELL_LEFT, _PP_CENTER = 12, 11, 20

_COLS = {                   # 머리글 → (열 너비, 가운데 정렬 열 번호)
    ("코드", "상병명", "구분", "정확도(%)", "근거"): ([5000, 11500, 3600, 3800, 18620], {0, 2, 3}),
    ("용어·약어", "구분", "한글 해석", "영문"): ([9500, 3600, 13500, 15920], {1}),
}


def _patch_header(hdr: str) -> str:
    """틀에 새 서식을 더한다 (테두리 2 · 글자 4 · 문단 1)."""
    for need in ('<hh:borderFills itemCnt="2">', '<hh:charProperties itemCnt="7">', '<hh:paraProperties itemCnt="20">'):
        if need not in hdr:
            raise RuntimeError("한글 문서 틀의 서식 구조가 예상과 다릅니다.")
    side = '<hh:leftBorder type="SOLID" width="0.12 mm" color="#7F8FA6"/><hh:rightBorder type="SOLID" width="0.12 mm" color="#7F8FA6"/>' \
           '<hh:topBorder type="SOLID" width="0.12 mm" color="#7F8FA6"/><hh:bottomBorder type="SOLID" width="0.12 mm" color="#7F8FA6"/>'
    head = '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
    diag = '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
    bf = (f'<hh:borderFill id="{_BF_CELL}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">{head}{side}{diag}</hh:borderFill>'
          f'<hh:borderFill id="{_BF_HEAD}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">{head}{side}{diag}'
          '<hc:fillBrush><hc:winBrush faceColor="#DCE6F2" hatchColor="#999999" alpha="0"/></hc:fillBrush></hh:borderFill>')
    hdr = hdr.replace('<hh:borderFills itemCnt="2">', '<hh:borderFills itemCnt="4">').replace("</hh:borderFills>", bf + "</hh:borderFills>")

    m = re.search(r'<hh:charPr id="2" .*?</hh:charPr>', hdr, re.S)          # 9pt 돋움 보통 글자를 본으로 삼는다
    if not m:
        raise RuntimeError("한글 문서 틀에서 글자 서식을 찾지 못했습니다.")
    base = m.group(0)

    def cp(cid: int, height: int, color: str, bold: bool) -> str:
        x = re.sub(r'^<hh:charPr id="\d+" height="\d+" textColor="#[0-9A-Fa-f]{6}"',
                   f'<hh:charPr id="{cid}" height="{height}" textColor="{color}"', base)
        return x.replace("<hh:underline", "<hh:bold/><hh:underline", 1) if bold else x
    chars = cp(_CP_BOLD, 900, "#000000", True) + cp(_CP_H2, 1200, "#1F4E79", True) + cp(_CP_TITLE, 1700, "#1F4E79", True) + cp(_CP_GLOSS, 1000, "#0B5EA8", False)
    hdr = hdr.replace('<hh:charProperties itemCnt="7">', '<hh:charProperties itemCnt="11">').replace("</hh:charProperties>", chars + "</hh:charProperties>")

    pm = re.search(r'<hh:paraPr id="11" .*?</hh:paraPr>', hdr, re.S)         # 왼쪽 정렬 문단을 본으로 가운데 정렬 문단을 만든다
    if not pm:
        raise RuntimeError("한글 문서 틀에서 문단 서식을 찾지 못했습니다.")
    center = pm.group(0).replace('<hh:paraPr id="11"', f'<hh:paraPr id="{_PP_CENTER}"', 1).replace('horizontal="LEFT"', 'horizontal="CENTER"', 1)
    return hdr.replace('<hh:paraProperties itemCnt="20">', '<hh:paraProperties itemCnt="21">').replace("</hh:paraProperties>", center + "</hh:paraProperties>")


class _Ids:
    def __init__(self) -> None:
        self.n = 1000000000

    def next(self) -> str:
        self.n += 1
        return str(self.n)


def _run(text: str, cp: int) -> str:
    return f'<hp:run charPrIDRef="{cp}"><hp:t>{escape(text)}</hp:t></hp:run>' if text else f'<hp:run charPrIDRef="{cp}"><hp:t/></hp:run>'


def _para(ids: _Ids, text: str, pp: int, cp: int) -> str:
    return f'<hp:p id="{ids.next()}" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{_run(text, cp)}</hp:p>'


def _table(ids: _Ids, rows: list[list[str]]) -> str:
    """머리글이 있는 표 한 개 — 테두리 · 머리글 배경색 · 열 너비를 정해 한글에서 표로 열린다."""
    key = tuple(rows[0])
    widths, centers = _COLS.get(key) or ([_TEXT_W // len(rows[0])] * len(rows[0]), set())
    widths = list(widths)
    widths[-1] += _TEXT_W - sum(widths)                       # 합이 본문 폭과 정확히 같게
    row_h = 1100
    n_rows, n_cols = len(rows), len(rows[0])
    out = [f'<hp:p id="{ids.next()}" paraPrIDRef="{_PP_LEFT}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
           f'<hp:tbl id="{ids.next()}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
           f'pageBreak="CELL" repeatHeader="1" rowCnt="{n_rows}" colCnt="{n_cols}" cellSpacing="0" borderFillIDRef="{_BF_CELL}" noAdjust="0">'
           f'<hp:sz width="{_TEXT_W}" widthRelTo="ABSOLUTE" height="{row_h * n_rows}" heightRelTo="ABSOLUTE" protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" '
           'vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="141" bottom="141"/>']
    for r, row in enumerate(rows):
        out.append("<hp:tr>")
        for c in range(n_cols):
            head = r == 0
            bf = _BF_HEAD if head else _BF_CELL
            pp = _PP_CENTER if (head or c in centers) else _PP_CELL_LEFT
            cp = _CP_BOLD if head else _CP_SMALL
            val = str(row[c]) if c < len(row) else ""
            out.append(
                f'<hp:tc name="" header="{1 if head else 0}" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
                'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                f'<hp:p id="{ids.next()}" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{_run(val, cp)}</hp:p></hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="{widths[c]}" height="{row_h}"/>'
                '<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')
        out.append("</hp:tr>")
    out.append('</hp:tbl><hp:t/></hp:run></hp:p>')
    return "".join(out)


def _hwpx_blocks(ctx: dict) -> list[tuple]:
    """('p', 글, 문단서식, 글자서식) 또는 ('table', 행 목록)"""
    blocks: list[tuple] = [("p", ctx["title"], _PP_LEFT, _CP_TITLE), ("p", "", _PP_LEFT, _CP_BODY)]
    for m in ctx.get("meta") or []:
        blocks.append(("p", m, _PP_LEFT, _CP_SMALL))
    for title, content, kind in _sections(ctx):
        blocks.append(("p", "", _PP_LEFT, _CP_BODY))
        if title:
            blocks.append(("p", title, _PP_LEFT, _CP_H2))
        if kind == "text":
            for line in content:
                gloss = line.startswith("   → ")
                blocks.append(("p", line.strip() if gloss else line, _PP_LEFT, _CP_GLOSS if gloss else _CP_BODY))
        else:
            blocks.append(("table", content))
            blocks.append(("p", "", _PP_LEFT, _CP_BODY))
    return blocks


def build_hwpx(ctx: dict) -> bytes:
    """빈 한글 문서 틀(assets/hwpx_skeleton.hwpx)에 본문·표를 채워 .hwpx 를 만든다."""
    with zipfile.ZipFile(_SKELETON) as zin:
        parts = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    parts["Contents/header.xml"] = _patch_header(parts["Contents/header.xml"].decode("utf-8")).encode("utf-8")

    sec = parts["Contents/section0.xml"].decode("utf-8")
    empty_run = '<hp:run charPrIDRef="0"><hp:t/></hp:run>'
    if empty_run not in sec or "</hs:sec>" not in sec:
        raise RuntimeError("한글 문서 틀의 구조가 예상과 다릅니다.")
    sec = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "", sec, flags=re.S)        # 줄 배치 캐시는 한글이 열 때 다시 계산한다
    blocks = _hwpx_blocks(ctx)
    first = blocks[0]
    sec = sec.replace(empty_run, _run(first[1], first[3]), 1)
    sec = sec.replace('<hp:p id="0" paraPrIDRef="0"', f'<hp:p id="0" paraPrIDRef="{first[2]}"', 1)
    ids = _Ids()
    body = "".join(_table(ids, b[1]) if b[0] == "table" else _para(ids, b[1], b[2], b[3]) for b in blocks[1:])
    sec = sec.replace("</hs:sec>", body + "</hs:sec>")
    parts["Contents/section0.xml"] = sec.encode("utf-8")

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hpf = parts["Contents/content.hpf"]
    hpf = hpf.replace(b"<opf:title/>", f"<opf:title>{escape(ctx['title'])}</opf:title>".encode("utf-8"))
    hpf = hpf.replace(b"synthetic-fixture-author", "심사 코딩마스터".encode("utf-8"))
    hpf = re.sub(rb'(<opf:meta name="CreatedDate" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    hpf = re.sub(rb'(<opf:meta name="ModifiedDate" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    hpf = re.sub(rb'(<opf:meta name="date" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    parts["Contents/content.hpf"] = hpf
    preview = [b[1] for b in blocks if b[0] == "p" and b[1]]
    parts["Preview/PrvText.txt"] = ("\r\n".join(preview)[:1000]).encode("utf-8")

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zout:
        zout.writestr(zipfile.ZipInfo("mimetype"), parts["mimetype"], compress_type=zipfile.ZIP_STORED)      # 첫 항목 · 무압축
        for name, data in parts.items():
            if name != "mimetype":
                zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return bio.getvalue()