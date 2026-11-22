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
def _hwpx_paragraphs(ctx: dict) -> list[str]:
    paras = [ctx["title"], ""]
    paras += list(ctx.get("meta") or [])
    for title, content, kind in _sections(ctx):
        paras.append("")
        if title:
            paras.append("■ " + title)
        if kind == "text":
            paras += content
        else:                                                # 표는 ‘ | ’ 로 나눈 줄로 적는다 (서식이 단순한 한글 문서)
            for i, row in enumerate(content):
                paras.append("   |   ".join(str(x) for x in row))
                if i == 0:
                    paras.append("-" * 40)
    return paras


def build_hwpx(ctx: dict) -> bytes:
    """빈 한글 문서 틀(assets/hwpx_skeleton.hwpx)에 본문 문단만 채워 .hwpx 를 만든다."""
    with zipfile.ZipFile(_SKELETON) as zin:
        parts = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    paras = _hwpx_paragraphs(ctx)

    def run(text: str) -> str:
        return f'<hp:run charPrIDRef="0"><hp:t>{escape(text)}</hp:t></hp:run>' if text else '<hp:run charPrIDRef="0"><hp:t/></hp:run>'

    sec = parts["Contents/section0.xml"].decode("utf-8")
    empty_run = '<hp:run charPrIDRef="0"><hp:t/></hp:run>'
    if empty_run not in sec or "</hs:sec>" not in sec:
        raise RuntimeError("한글 문서 틀의 구조가 예상과 다릅니다.")
    sec = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "", sec, flags=re.S)        # 줄 배치 캐시는 한글이 열 때 다시 계산한다
    sec = sec.replace(empty_run, run(paras[0]), 1)
    body = "".join(f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{run(t)}</hp:p>'
                   for i, t in enumerate(paras[1:], start=1))
    sec = sec.replace("</hs:sec>", body + "</hs:sec>")
    parts["Contents/section0.xml"] = sec.encode("utf-8")

    now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    hpf = parts["Contents/content.hpf"]
    hpf = hpf.replace(b"<opf:title/>", f"<opf:title>{escape(ctx['title'])}</opf:title>".encode("utf-8"))
    hpf = hpf.replace(b"synthetic-fixture-author", "심사 코딩마스터".encode("utf-8"))
    hpf = re.sub(rb'(<opf:meta name="CreatedDate" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    hpf = re.sub(rb'(<opf:meta name="ModifiedDate" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    hpf = re.sub(rb'(<opf:meta name="date" content="text">)[^<]*(</opf:meta>)', rb"\g<1>" + now.encode() + rb"\g<2>", hpf)
    parts["Contents/content.hpf"] = hpf
    parts["Preview/PrvText.txt"] = ("\r\n".join(paras)[:1000]).encode("utf-8")

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zout:
        zout.writestr(zipfile.ZipInfo("mimetype"), parts["mimetype"], compress_type=zipfile.ZIP_STORED)      # 첫 항목 · 무압축
        for name, data in parts.items():
            if name != "mimetype":
                zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return bio.getvalue()
