"""4단계 화면 — 검색 · 코드 생성(탭·AI 의미 검색·성별/연령 검증) / 정밀 분석"""
from __future__ import annotations

import asyncio
import json
from html import escape as esc

from nicegui import app, run, ui

from . import dictionary, gemini, rules, store
from .main import get_index, layout, require_login, save_ui_pref, user
from .search import norm

ANATOMY = ["손가락", "발가락", "손목", "발목", "무릎", "어깨", "팔꿈치", "고관절", "대퇴골", "경골", "요골", "척추", "허리", "목", "머리",
           "뇌", "눈", "귀", "코", "인두", "후두", "식도", "위", "십이지장", "소장", "대장", "결장", "직장", "간", "담낭", "담관", "췌장",
           "비장", "신장", "콩팥", "방광", "요도", "전립선", "난소", "자궁", "유방", "갑상선", "폐", "기관지", "심장", "피부", "복막",
           "복부", "흉부", "흉막", "치아", "구강", "갈비뼈", "쇄골", "골반", "발", "손", "다리", "팔", "얼굴", "턱", "관절"]
TYPES = ["골절", "탈구", "염좌", "악성신생물", "양성신생물", "염증", "감염", "출혈", "경색", "결석", "궤양", "화상", "열상", "폐렴",
         "협착", "폴립", "낭종", "종양", "마비", "통증", "기형", "천공", "파열"]
_ANAT_SORTED = sorted(ANATOMY, key=len, reverse=True)

# 진료과별 전용 용어 · 약어 (같은 약어도 진료과마다 뜻이 다름) + 우선 KCD 장 접두 — 원본 웹앱의 사전
DEPT_LEX = {
    "내과": {"pre": ["E", "K", "N", "D5", "D6", "I1"], "terms": [["NB", "신경모세포종"], ["DM", "2형 당뇨병"], ["HTN", "고혈압"], ["CKD", "만성 콩팥병"], ["LC", "간경화증"], ["IDA", "철결핍빈혈"], ["AGE", "급성 위장염"], ["UGIB", "위장관 출혈"], ["PUD", "소화성 궤양"], ["Hypothyroidism", "갑상선기능저하증"]]},
    "순환기내과": {"pre": ["I"], "terms": [["AMI", "급성 심근경색"], ["UA", "불안정 협심증"], ["AF", "심방세동"], ["CHF", "심부전"], ["HCMP", "비대심근병증"], ["DCMP", "확장성 심근병증"], ["AS", "대동맥판 협착"], ["MR", "승모판 역류"], ["PSVT", "발작성 심실상성 빈맥"], ["SSS", "동기능부전증후군"]]},
    "신경과": {"pre": ["G", "I6", "F0"], "terms": [["CVA", "뇌경색"], ["TIA", "일과성 허혈발작"], ["ICH", "뇌내출혈"], ["PD", "파킨슨병"], ["AD", "알츠하이머병"], ["MG", "중증 근무력증"], ["GBS", "길랭-바레 증후군"], ["MS", "다발경화증"], ["Sz", "뇌전증"]]},
    "호흡기내과": {"pre": ["J", "A15", "C34"], "terms": [["COPD", "만성 폐쇄성 폐질환"], ["CAP", "폐렴"], ["BA", "천식"], ["TB", "폐결핵"], ["ILD", "간질성 폐질환"], ["PTX", "기흉"], ["URI", "급성 상기도감염"], ["OSA", "수면 무호흡"], ["NSCLC", "비소세포폐암"]]},
    "정형외과": {"pre": ["M", "S", "T"], "terms": [["HNP", "추간판 탈출"], ["LBP", "허리통증"], ["OA", "골관절염"], ["RA", "류마티스 관절염"], ["ACL", "전방십자인대 파열"], ["RCT", "회전근개 파열"], ["CTS", "손목굴 증후군"], ["Fx", "골절"], ["FNF", "대퇴골 경부 골절"], ["DRF", "요골 원위부 골절"]]},
    "외과": {"pre": ["K", "C", "S3"], "terms": [["NB", "신경모세포종"], ["AA", "급성 충수염"], ["APE", "충수염"], ["GC", "위암"], ["CRC", "대장암"], ["BC", "유방암"], ["IH", "서혜부 탈장"], ["GBS", "담석증"], ["Ileus", "장폐색"], ["Hemorrhoid", "치핵"]]},
    "응급의학과": {"pre": ["S", "T", "R", "V", "W", "X"], "terms": [["TBI", "외상성 뇌손상"], ["LOC", "의식소실"], ["MVA", "교통사고"], ["Burn", "화상"], ["Syncope", "실신"], ["CPA", "심정지"], ["Poisoning", "중독"], ["SOB", "호흡곤란"], ["Lac", "열린 상처"]]},
    "가정의학과": {"pre": ["J0", "E", "I10", "Z", "K2"], "terms": [["NB", "신생아"], ["URI", "급성 상기도감염"], ["HTN", "고혈압"], ["DL", "이상지질혈증"], ["DM", "2형 당뇨병"], ["AGE", "급성 위장염"], ["GERD", "위식도역류병"], ["Obesity", "비만"], ["Insomnia", "불면증"]]},
}


def dept_interpretations(query: str, cur_dept: str, code_for) -> list[dict]:
    """같은 약어가 진료과마다 갖는 뜻 — 현재 진료과가 먼저"""
    k = (query or "").strip().lower()
    out = []
    if not k:
        return out
    for d, lex in DEPT_LEX.items():
        t = next((x for x in lex["terms"] if x[0].lower() == k), None)
        if t:
            out.append({"dept": d, "abbr": t[0], "ko": t[1], "code": code_for(t[1])})
    out.sort(key=lambda r: r["dept"] != cur_dept)
    return out


_NAMES: dict = {}
_NORM_NAMES: dict = {}


def _norm_names_of(idx) -> dict:
    n = _NORM_NAMES.get(id(idx))
    if n is None:
        _NORM_NAMES.clear()
        n = _NORM_NAMES[id(idx)] = {}
        for r in idx.rows:
            n.setdefault(norm(r.ko), r.code)
    return n


def _names_of(idx) -> dict:
    n = _NAMES.get(id(idx))
    if n is None:
        _NAMES.clear()
        n = _NAMES[id(idx)] = {r.code.upper(): r.ko for r in idx.rows}
    return n


def split_query(q: str) -> tuple[str, str]:
    a = next((x for x in _ANAT_SORTED if x in q), "")
    t = next((x for x in TYPES if x in q), "")
    return a, t


def parse_age(v) -> int | None:
    try:
        n = int(float(v))
        return n if 0 <= n <= 120 else None
    except (TypeError, ValueError):
        return None


def tree_paths(code: str) -> list[str]:
    """3권 색인에서 이 코드(또는 하위 코드)가 나오는 경로"""
    trees = [t for t in (store.get("global", "ltTrees", []) or []) if isinstance(t, dict) and not t.get("retired")]
    out: list[str] = []

    def walk(n: dict, trail: list[str]) -> None:
        label = n.get("mod") or n.get("term") or n.get("label") or ""
        here = trail + ([label] if label else [])
        c = str(n.get("code") or "").upper()
        if c and (c == code or c.startswith(code) or code.startswith(c) and len(c) >= 3 and c == code[:len(c)]):
            if c == code or c.startswith(code):
                out.append(" › ".join(here) + f"  [{c}]")
        for k in n.get("kids") or []:
            if isinstance(k, dict):
                walk(k, here)

    for t in trees:
        walk(t, [])
        if len(out) >= 40:
            break
    return out[:40]


# ═════════════════════ 검색 · 코드 생성 ═════════════════════
@ui.page("/search")
def search_page() -> None:
    if not require_login():
        return
    layout("search")
    idx = get_index()
    fam = rules.get_family(idx)
    names = _names_of(idx)
    from .phase2 import load_cond
    cond = load_cond()
    st = {"q": "", "sex": "", "age": None, "hits": [], "ai": None, "cmp": [], "orig": "", "note": ""}
    norm_name = _norm_names_of(idx)

    def code_for(ko: str) -> str:
        n = norm(ko)
        if not n:
            return ""
        if n in norm_name:
            return norm_name[n]
        return next((r.code for r in idx.rows if n in norm(r.ko)), "")

    ui.add_css(""".kcm-search .q-field__control{height:44px}.kcm-search input{font-size:16px}
.kcm-sbar{display:flex;align-items:center;gap:8px;width:100%}.kcm-sbar .kcm-search{flex:1 1 auto;min-width:0}
.kcm-sbar .q-btn{height:44px}
.kcm-chips{display:flex;flex-wrap:wrap;align-items:center;gap:6px;width:100%}
.kcm-chips .sep{width:1px;height:16px;background:var(--color-divider);margin:0 2px}
.kcm-chips .lab{font-size:11px;color:var(--muted)}
.kcm-chips .push{margin-left:auto}
@media (max-width:560px){.kcm-aibtn .q-btn__content span.block{display:none}}""")
    st["view"] = "card"
    st["limit"] = 12
    st["auto"] = True
    with ui.column().classes("w-full max-w-5xl gap-3"):
        with ui.column().classes("kcm-card w-full gap-2").style("padding:12px 14px"):
            # ── 1줄: 검색창 · AI · 옵션
            with ui.element("div").classes("kcm-sbar"):
                box = ui.input(placeholder="질병명 · 진단명 · 의학용어 · 약어 · 코드  (예: 위암, HTN, appendicitis, J18)").props(
                    "outlined dense clearable autofocus").classes("kcm-search")
                with box.add_slot("prepend"):
                    ui.icon("search").style("color:var(--muted)")
                ui.button("AI 해석", icon="auto_awesome", on_click=lambda: run_ai()).props("no-caps outline").classes("kcm-aibtn").tooltip(
                    "색인에서 못 찾을 때 AI가 용어를 해석하고 코드를 제안합니다")
                with ui.button(icon="tune").props("outline round dense").style("width:44px").tooltip("검색 옵션"):
                    with ui.menu():
                        with ui.column().classes("gap-1").style("padding:10px 14px;min-width:260px"):
                            ui.switch("실시간 검색", value=True, on_change=lambda e: st.__setitem__("auto", e.value)).tooltip(
                                "켜면 입력하는 동안 바로 결과가 바뀝니다. 끄면 Enter로 검색합니다.")
                            ui.label("끄면 Enter 또는 돋보기로만 검색").classes("text-muted").style("font-size:11px;margin-top:-6px")
                            ui.separator()
                            ui.button("검색어 지우기", icon="restart_alt", on_click=lambda: reset_search()).props("flat dense no-caps align=left").style("justify-content:flex-start")
            # ── 2줄: 예시 · 진료과 용어 · 환자 조건 (한 줄에 모아 공간 절약)
            lex0 = DEPT_LEX.get(cond["dept"])
            with ui.element("div").classes("kcm-chips"):
                ui.label("예시").classes("lab")
                for chip in ["위암", "고혈압", "폐렴", "Appendicitis", "관절염", "두통", "J18", "HTN"]:
                    ui.button(chip, on_click=lambda _, c=chip: set_query(c)).props("outline dense no-caps size=sm").style("padding:0 10px")
                if lex0:
                    ui.element("span").classes("sep")
                    ui.label(f"{cond['dept']} 용어").classes("lab").tooltip(
                        f"{len(lex0['terms'])}개 · {'·'.join(lex0['pre'])} 코드 우선 (조건 설정에서 변경)")
                    for abbr, ko in lex0["terms"]:
                        ui.button(abbr, on_click=lambda _, a=abbr: set_query(a)).props("outline dense no-caps size=xs").style("padding:0 8px").tooltip(ko)
                cond_btn = ui.button("환자 조건 검증", icon="rule").props("flat dense no-caps size=sm").classes("push").tooltip(
                    "필요할 때만 사용 — 성별·연령에 맞지 않는 코드를 표시합니다")
            # ── 3줄: 환자 조건 (눌렀을 때만 펼침)
            cond_row = ui.row().classes("items-center gap-3 w-full")
            with cond_row:
                sex = ui.select({"": "성별 전체", "M": "남", "F": "여"}, value="").props("dense outlined").classes("w-32")
                age = ui.input(placeholder="연령(세)").props("dense outlined type=number min=0 max=120").classes("w-32")
                ui.label(f"성별·연령에 맞지 않는 코드를 표시합니다 · KCD 상병 {len(idx):,}건").classes("text-muted").style("font-size:11px")
            cond_row.set_visibility(False)

            def toggle_cond() -> None:
                on = not cond_row.visible
                cond_row.set_visibility(on)
                cond_btn.props("color=primary" if on else "color=grey-7")
                if not on:                       # 닫으면 조건을 비워 검증을 끈다
                    sex.set_value("")
                    age.set_value(None)
            cond_btn.on_click(toggle_cond)
        info = ui.label("").classes("text-muted").style("font-size:12px")
        ui.add_css(""".kcm-tbtn{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--color-divider);border-radius:8px;min-height:40px;
 padding:0 14px;background:var(--surface);cursor:grab;user-select:none;font-family:var(--font-heading);font-weight:600;font-size:15px}
.kcm-tbtn:hover{background:var(--surface-2)}
.kcm-tbtn.on{background:var(--a200);border-color:var(--color-accent);color:var(--a800);box-shadow:inset 0 0 0 1px var(--a300)}
.kcm-grip{color:var(--n600);font-weight:400}
.kcm-cnt{background:var(--a300);color:var(--a900);font-weight:700;border-radius:999px;padding:0 8px;font-size:12px}
.kcm-done{border:1px solid var(--color-accent);color:var(--color-accent);border-radius:4px;padding:0 6px;font-size:12px}
.kcm-pz-grid{display:grid;grid-template-columns:repeat(var(--cols,2),minmax(0,1fr));grid-auto-flow:row dense;gap:12px;align-items:stretch;width:100%}
@media (max-width:900px){.kcm-pz-grid{grid-template-columns:minmax(0,1fr)}}
.kcm-pz{display:flex;flex-direction:column;height:var(--pzh,440px);border:1px solid var(--card-line);border-radius:12px;background:var(--surface);box-shadow:var(--elev-1);overflow:hidden;min-width:0}
.kcm-pz-body{flex:1;min-height:0;overflow:auto;padding:12px}
.kcm-gc{display:flex;flex-direction:column;gap:6px}.kcm-gc .gt{font-family:var(--font-heading);font-weight:600;font-size:24px;line-height:1.15}
.kcm-gc .mu,.kcm-cc .mu{font-size:12px;color:var(--muted)}.kcm-gc .cg{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.kcm-gc .gf{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.kcm-cc{border:1px solid var(--color-divider);border-radius:10px;padding:10px 12px;background:var(--surface-2);display:flex;flex-direction:column;gap:4px}
.kcm-cc.first{border-color:var(--color-accent)}.kcm-cc .r1{display:flex;justify-content:space-between;align-items:center}
.kcm-cc .cd{font-family:ui-monospace,Menlo,monospace;font-weight:700;font-size:15px;color:var(--accent-hi)}
.kcm-cc .nm{font-size:14px;line-height:1.35}.kcm-cc .wr{font-size:11px;color:var(--warn)}.kcm-cc .ft{display:flex;justify-content:flex-end}
.kcm-sb{font-family:var(--font-heading);font-weight:600;font-size:13px;cursor:pointer;color:var(--color-text);background:var(--surface);border:1px solid var(--color-divider);border-radius:8px;padding:3px 10px}
.kcm-sb:hover{background:var(--surface-2)}.kcm-sb.pri{background:var(--color-accent);border-color:var(--color-accent);color:#fff}
.kcm-pz.wide{grid-column:1/-1}
.kcm-pz-h{display:flex;align-items:center;gap:8px;padding:6px 8px 6px 14px;border-bottom:1px solid var(--color-divider);cursor:grab;background:var(--surface-2);
 font-family:var(--font-heading);font-weight:600;font-size:15px}
.kcm-busy{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--color-accent);font-weight:600}
.kcm-spin{width:12px;height:12px;border:2px solid var(--a300);border-top-color:var(--color-accent);border-radius:50%;animation:kcmSpin .8s linear infinite;display:inline-block}
@keyframes kcmSpin{to{transform:rotate(360deg)}}
.kcm-none{font-size:12px;color:var(--muted);font-weight:400}
.kcm-err{font-size:12px;color:var(--warn);font-weight:600}
.kcm-imgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;width:100%}
.kcm-fig{margin:0;border:1px solid var(--color-divider);border-radius:10px;overflow:hidden;background:var(--surface-2)}
.kcm-fig img{width:100%;height:130px;object-fit:contain;background:#fff;display:block}
.kcm-fig figcaption{font-size:11px;padding:6px 8px;color:var(--muted);line-height:1.35}.kcm-fig .src{color:var(--color-accent)}
.dnd-dragging{opacity:.4}.dnd-over{outline:2px dashed var(--color-accent);outline-offset:2px}""")

        PANELS = {"res": "결과 · 코드", "ai": "✦ AI 의미 검색", "sim": "유사한 용어", "dept": "진료과별 해석", "rel": "연관 질환 · 해부학적 부위"}
        pref = app.storage.user
        order = [k for k in pref.get("panel_order", []) if k in PANELS]
        order += [k for k in PANELS if k not in order]
        view = {"mode": pref.get("panel_mode", "tab"), "tab": "res", "h": pref.get("panel_h", "md"), "cols": int(pref.get("panel_cols", 2)),
                "show": [k for k in pref.get("panel_show", list(PANELS)) if k in PANELS] or ["res"],
                "wide": [k for k in pref.get("panel_wide", ["res"]) if k in PANELS]}
        counts: dict[str, int] = {"res": 0, "sim": 0, "dept": 0}
        ai_done = {"v": False}
        status: dict[str, str] = {}   # 탭별 진행 상태: busy(검색중) / done / error

        def save_pref() -> None:
            pref["panel_order"], pref["panel_mode"] = list(order), view["mode"]
            pref["panel_show"], pref["panel_wide"] = list(view["show"]), list(view["wide"])
            pref["panel_h"], pref["panel_cols"] = view["h"], view["cols"]
            save_ui_pref(panel_order=list(order), panel_mode=view["mode"], panel_show=list(view["show"]),
                         panel_wide=list(view["wide"]), panel_h=view["h"], panel_cols=view["cols"])

        holder = ui.column().classes("hidden")
        with holder:
            res_box = ui.column().classes("w-full gap-2")
            ai_box = ui.column().classes("w-full gap-3")
            sim_box = ui.column().classes("w-full gap-2")
            dept_box = ui.column().classes("w-full gap-2")
            rel_box = ui.column().classes("w-full gap-2")
        boxes = {"res": res_box, "ai": ai_box, "sim": sim_box, "dept": dept_box, "rel": rel_box}
        bar_box = ui.column().classes("w-full gap-2")
        area = ui.element("div").classes("w-full")

        def pick(k: str) -> None:
            if view["mode"] == "tab":
                view["tab"] = k
            elif k in view["show"]:
                if len(view["show"]) > 1:
                    view["show"].remove(k)
            else:
                view["show"].append(k)
            save_pref()
            render_bar()
            render_area()

        def set_mode(m: str) -> None:
            view["mode"] = m
            save_pref()
            render_bar()
            render_area()

        def render_bar() -> None:
            bar_box.clear()
            with bar_box:
                with ui.row().classes("w-full items-center justify-between").style("gap:8px"):
                    with ui.row().classes("items-center").style("gap:8px;flex-wrap:wrap"):
                        for k in order:
                            on = (k == view["tab"]) if view["mode"] == "tab" else (k in view["show"])
                            btn = ui.element("div").classes("kcm-tbtn" + (" on" if on else "")).props(
                                f'draggable="true" data-dnd="tabs" data-key="{k}"')
                            btn.on("click", lambda _, k=k: pick(k))
                            with btn:
                                ui.label("⋮").classes("kcm-grip")
                                ui.label(PANELS[k])
                                s_ = status.get(k, "idle")
                                if s_ == "busy":
                                    ui.html(f'<span class="kcm-busy"><i class="kcm-spin"></i>{"분석중" if k == "ai" else "검색중"}</span>')
                                elif s_ == "error":
                                    ui.html('<span class="kcm-err">⚠ 실패</span>')
                                elif s_ == "done":
                                    if k == "ai":
                                        ui.html('<span class="kcm-done">✓ 완료</span>')
                                    elif k not in counts:
                                        ui.html('<span class="kcm-done">✓ 완료</span>')
                                    elif counts[k]:
                                        ui.html(f'<span class="kcm-cnt">{counts[k]}</span>')
                                    else:
                                        ui.html('<span class="kcm-none">결과 없음</span>')
                    with ui.row().classes("items-center gap-2"):
                        ui.label("끌어서 순서 변경").classes("text-muted").style("font-size:11px")
                        with ui.element("div").classes("kcm-seg"):
                            b1 = ui.element("button").classes("on" if view["mode"] == "tab" else "").on("click", lambda: set_mode("tab"))
                            with b1:
                                ui.label("탭 보기")
                            b2 = ui.element("button").classes("on" if view["mode"] == "puzzle" else "").on("click", lambda: set_mode("puzzle"))
                            with b2:
                                ui.label("퍼즐 보기")
                if view["mode"] == "puzzle":
                    with ui.row().classes("items-center gap-3"):
                        ui.label("퍼즐 보기 — 보일 기능을 고르고, 카드 머리글을 끌어 자리를 바꾸세요. 내용이 많으면 카드 안에서 스크롤합니다.").classes("text-muted").style("font-size:11px")
                        with ui.element("div").classes("kcm-seg"):
                            for ck in (1, 2, 3):
                                cb = ui.element("button").classes("on" if view["cols"] == ck else "").on("click", lambda _, ck=ck: set_cols(ck))
                                with cb:
                                    ui.label(f"{ck}열")
                        with ui.element("div").classes("kcm-seg"):
                            for hk, hl in (("sm", "작게"), ("md", "보통"), ("lg", "크게")):
                                hb = ui.element("button").classes("on" if view["h"] == hk else "").on("click", lambda _, hk=hk: set_h(hk))
                                with hb:
                                    ui.label(hl)

        def set_cols(c: int) -> None:
            view["cols"] = c
            save_pref()
            render_bar()
            render_area()

        def set_h(h: str) -> None:
            view["h"] = h
            save_pref()
            render_bar()
            render_area()

        def toggle_wide(k: str) -> None:
            (view["wide"].remove if k in view["wide"] else view["wide"].append)(k)
            save_pref()
            render_area()

        def render_area() -> None:
            for b in boxes.values():
                b.move(holder)
            area.clear()
            with area:
                if view["mode"] == "tab":
                    k = view["tab"]
                    wrap = ui.column().classes("w-full gap-2" + (" kcm-card" if k in ("ai", "sim", "rel") else ""))
                    boxes[k].move(wrap)
                else:
                    with ui.element("div").classes("kcm-pz-grid").style(f"--cols:{view['cols']};--pzh:{ {'sm': 340, 'md': 440, 'lg': 600}.get(view['h'], 440) }px"):
                        for k in [x for x in order if x in view["show"]]:
                            wide = k in view["wide"]
                            card = ui.element("div").classes("kcm-pz" + (" wide" if wide else "")).props(f'data-dnd="cards" data-key="{k}"')
                            with card:
                                with ui.element("div").classes("kcm-pz-h").props('draggable="true"'):
                                    ui.label("⋮⋮").classes("kcm-grip")
                                    ui.label(PANELS[k]).classes("grow")
                                    ui.button(icon="close_fullscreen" if wide else "open_in_full",
                                              on_click=lambda _, k=k: toggle_wide(k)).props("flat round dense size=sm").tooltip("넓게 / 좁게")
                                    ui.button(icon="close", on_click=lambda _, k=k: pick(k)).props("flat round dense size=sm").tooltip("이 카드 닫기")
                                body = ui.column().classes("w-full gap-2 kcm-pz-body")
                            boxes[k].move(body)

        def on_dnd(e) -> None:
            a = e.args or {}
            grp, new = a.get("group"), [k for k in (a.get("order") or []) if k in PANELS]
            if grp == "tabs" and len(new) == len(order):
                order[:] = new
            elif grp == "cards" and new:
                pos = [i for i, k in enumerate(order) if k in new]
                for p, k in zip(pos, new):
                    order[p] = k
            else:
                return
            save_pref()
            render_bar()
            render_area()

        ui.on("dnd_reorder", on_dnd)

        class _Tabs:
            def set_value(self, k: str) -> None:
                if view["mode"] == "tab":
                    view["tab"] = k
                elif k not in view["show"]:
                    view["show"].append(k)
                save_pref()
                render_bar()
                render_area()
        tabs = _Tabs()
        render_bar()
        render_area()

        def render_dept() -> None:
            dept_box.clear()
            cmp_ = st["cmp"]
            n = len(cmp_)
            counts["dept"] = n
            render_bar()
            with dept_box:
                if st["note"]:
                    ui.label(st["note"]).style("font-size:12px;color:var(--a700)")
                if not cmp_:
                    with ui.column().classes("kcm-card w-full gap-1"):
                        ui.label("진료과별로 다르게 해석되는 용어가 아닙니다").style("font-weight:600;font-size:15px")
                        q0 = st["orig"] or st["q"]
                        ui.label(f"‘{q0}’은(는) 진료과 전용 용어 목록에 없어 모든 진료과에서 같은 뜻으로 검색됩니다. "
                                 "진료과마다 뜻이 다른 약어(예: MS, AF, PE)를 입력하면 여기에서 비교할 수 있습니다.").classes("text-muted").style("font-size:13px")
                    return
                with ui.column().classes("kcm-card w-full gap-0").style("padding:0;overflow:hidden"):
                    with ui.row().classes("w-full items-center justify-between").style("padding:10px 16px;border-bottom:1px solid var(--color-divider)"):
                        with ui.row().classes("items-center gap-2"):
                            ui.html('<span class="kcm-tag">진료과 용어</span>')
                            ui.label("같은 약어, 진료과별 해석").style("font-weight:600;font-size:14px")
                        ui.label(f"진료과별 해석 {n}건").classes("text-muted").style("font-size:12px")
                    if not any(r["dept"] == cond["dept"] for r in cmp_):
                        ui.label(f"현재 진료과({cond['dept']})에는 이 약어의 전용 해석이 없습니다. 아래에서 적용할 해석을 고르세요.") \
                            .classes("text-muted").style("font-size:12px;padding:8px 16px;border-bottom:1px solid var(--color-divider)")
                    grid = "display:grid;grid-template-columns:minmax(90px,150px) minmax(0,1fr) 90px 100px;gap:12px;align-items:center;padding:{p} 16px;border-bottom:1px solid var(--color-divider)"
                    with ui.element("div").classes("w-full text-muted").style(grid.format(p="7px") + ";font-size:12px"):
                        for h in ("진료과", "해석", "코드", ""):
                            ui.label(h)
                    for r in cmp_:
                        cur = r["dept"] == cond["dept"]
                        with ui.element("div").classes("w-full").style(
                                grid.format(p="11px") + (";background:var(--a100);box-shadow:inset 3px 0 0 var(--color-accent)" if cur else "")):
                            ui.label(r["dept"]).style("font-size:14px;" + ("font-weight:700" if cur else ""))
                            with ui.column().classes("gap-0"):
                                ui.label(r["ko"]).style("font-size:15px;" + ("font-weight:700" if cur else ""))
                                ui.label(r["abbr"]).classes("text-muted mono").style("font-size:12px")
                            ui.label(r["code"] or "—").classes("mono").style("font-weight:700;font-size:16px;color:var(--accent-hi)")
                            ui.button("적용됨" if cur else "이 해석 적용", on_click=lambda _, r=r: apply_dept(r)).props(
                                "dense no-caps size=sm " + ("unelevated color=primary" if cur else "outline")).style("white-space:nowrap")

        def apply_dept(r: dict) -> None:
            cond["dept"] = r["dept"]
            u = user()
            store.put(f"user:{u['id']}", "cond", cond, by=u["id"])
            ui.notify(f"진료과를 {r['dept']}(으)로 바꿔 검색합니다.", type="positive")
            ui.navigate.to("/search")

        def go_detail(code: str) -> None:
            ui.navigate.to(f"/detail?code={code}")

        def verdict(code: str) -> tuple[str, str]:
            """(문구, 색) — 성별·연령 검증"""
            s, a = sex.value or "", parse_age(age.value)
            msgs = [m for m in (rules.sex_issue(code, s), rules.age_issue(code, a)) if m]
            if msgs:
                return "⚠ " + msgs[0], "var(--warn)"
            return "", ""

        def to_favs(code: str) -> None:
            from .phase3 import add_fav
            ui.notify("코드집에 담았습니다." if add_fav(code, names.get(code, "")) else "이미 코드집에 있습니다.")

        def to_hist(code: str) -> None:
            from .phase3 import add_history
            add_history(st["q"], code, names.get(code, ""))
            ui.notify("이력에 기록했습니다.", type="positive")

        def unit_label(code: str) -> str:
            n = len(code.replace(".", ""))
            tail = "하위 세분류 있음" if fam.has_child(code) else "최말단 · 청구 가능"
            return f"{n}단위 · {tail}"

        def render_results() -> None:
            res_box.clear()
            hits = st["hits"]
            with res_box:
                if not st["q"].strip():
                    ui.label("위 검색창에 입력하면 결과가 바로 표시됩니다.").classes("text-muted text-sm")
                    return
                if not hits:
                    ui.label("결과가 없습니다. ‘AI 의미 검색’ 탭에서 구어·약어도 해석해 볼 수 있습니다.").classes("text-muted text-sm")
                    return
                groups: dict[str, list] = {}
                for r in hits:
                    groups.setdefault(r.code[:3], []).append(r)
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label(f"결과는 · 코드 {len(hits)}개 · 계열 {len(groups)}개").classes("text-muted").style("font-size:12px")
                    with ui.element("div").classes("kcm-seg"):
                        b1 = ui.element("button").classes("on" if st["view"] == "card" else "").on("click", lambda: set_view("card"))
                        with b1:
                            ui.label("카드형")
                        b2 = ui.element("button").classes("on" if st["view"] == "list" else "").on("click", lambda: set_view("list"))
                        with b2:
                            ui.label("목록형")
                if st["view"] == "card":
                    shown_groups = list(groups.items())[:st["limit"]]
                    parts = []
                    for root, rows_ in shown_groups:
                        head = next((r for r in rows_ if r.code == root), rows_[0])
                        cards = []
                        for i, r in enumerate(rows_[:6]):
                            v, _ = verdict(r.code)
                            lim = rules.restriction(r.code)
                            cards.append(
                                f'<div class="kcm-cc{" first" if i == 0 else ""}">'
                                f'<div class="r1"><span class="cd">{esc(r.code)}</span>{"<span class=kcm-tag>추천</span>" if i == 0 else ""}</div>'
                                f'<div class="nm">{esc(r.ko)}</div><div class="mu">{esc(unit_label(r.code))}</div>'
                                + (f'<div class="wr">제한: {esc(lim)}</div>' if lim else "")
                                + (f'<div class="wr">{esc(v)}</div>' if v else "")
                                + f'<div class="ft"><button class="kcm-sb" data-kact="detail" data-code="{esc(r.code)}">정밀 분석</button></div></div>')
                        more = f'<div class="mu">… 외 {len(rows_) - 6}개 — 목록형에서 모두 볼 수 있습니다.</div>' if len(rows_) > 6 else ""
                        parts.append(
                            f'<div class="kcm-card kcm-gc"><div class="kicker">{esc((head.en or f"{root} 계열").upper())}</div>'
                            f'<div class="gt">{esc(head.ko)}</div><div class="mu">{esc(root)} 계열 · 코드 {len(rows_)}개</div>'
                            f'<div class="cg">{"".join(cards)}</div>{more}'
                            f'<div class="gf"><button class="kcm-sb" data-kact="fav" data-code="{esc(head.code)}">☆ 즐겨찾기</button>'
                            f'<button class="kcm-sb" data-kact="hist" data-code="{esc(head.code)}">이력에 기록</button>'
                            f'<button class="kcm-sb pri" data-kact="detail" data-code="{esc(head.code)}">정밀 분석</button></div></div>')
                    ui.html("".join(parts)).classes("w-full").style("display:grid;gap:12px")
                    if len(groups) > st["limit"]:
                        ui.button(f"계열 {len(groups) - st['limit']}개 더 보기", on_click=lambda: more_groups()).props("outline no-caps")
                    return
                rows = []
                for r in hits:
                    v, _ = verdict(r.code)
                    rows.append({"code": r.code, "ko": r.ko, "en": r.en, "limit": rules.restriction(r.code),
                                 "flag": v or ("하위 세분류 필요" if fam.has_child(r.code) else "")})
                t = ui.table(columns=[
                    {"name": "code", "label": "코드", "field": "code", "align": "left", "sortable": True},
                    {"name": "ko", "label": "한글명", "field": "ko", "align": "left"},
                    {"name": "en", "label": "영문명", "field": "en", "align": "left"},
                    {"name": "limit", "label": "사용 제한", "field": "limit", "align": "left"},
                    {"name": "flag", "label": "검증", "field": "flag", "align": "left"},
                    {"name": "act", "label": "", "field": "code", "align": "right"},
                ], rows=rows, row_key="code", pagination=25).classes("w-full")
                t.add_slot("body-cell-act", r'''
                    <q-td :props="props" auto-width>
                      <q-btn flat dense size="sm" no-caps label="정밀 분석" @click="() => $parent.$emit('detail', props.row)" />
                      <q-btn flat dense size="sm" icon="star" @click="() => $parent.$emit('fav', props.row)"><q-tooltip>코드집에 담기</q-tooltip></q-btn>
                      <q-btn flat dense size="sm" icon="history" @click="() => $parent.$emit('hist', props.row)"><q-tooltip>이력에 기록</q-tooltip></q-btn>
                    </q-td>''')
                t.add_slot("body-cell-flag", r'''
                    <q-td :props="props"><span :style="props.row.flag.startsWith('⚠') ? 'color:var(--warn)' : 'color:var(--muted)'">{{ props.row.flag }}</span></q-td>''')
                t.on("detail", lambda e: go_detail(e.args["code"]))
                t.on("fav", lambda e: to_favs(e.args["code"]))
                t.on("hist", lambda e: to_hist(e.args["code"]))

        def set_view(v: str) -> None:
            st["view"] = v
            render_results()

        def more_groups() -> None:
            st["limit"] += 24
            render_results()

        def on_kact(e) -> None:
            a = e.args or {}
            code = str(a.get("code", ""))
            act = a.get("act")
            if act == "detail":
                go_detail(code)
            elif act == "fav":
                to_favs(code)
            elif act == "hist":
                to_hist(code)
        ui.on("kcm_act", on_kact)
        def render_similar() -> None:
            sim_box.clear()
            q = norm(st["q"])
            terms: dict[str, str] = {}
            if q:
                for tr in store.get("global", "ltTrees", []) or []:
                    if not isinstance(tr, dict) or tr.get("retired"):
                        continue
                    keys = [tr.get("term", "")] + list(tr.get("syn") or [])
                    ks = [norm(k) for k in keys if k]
                    if any(q in k or (len(k) >= 2 and k in q) for k in ks):
                        for k in keys:
                            if k and norm(k) != q:
                                terms[k] = tr.get("term", "")
                for r in st["hits"][:60]:
                    for k in [r.ko, *r.syn]:
                        if k and norm(k) != q and len(k) <= 24:
                            terms.setdefault(k, r.ko)
            counts["sim"] = min(len(terms), 40)
            render_bar()
            with sim_box:
                if not terms:
                    ui.label("유사한 용어가 없습니다.").classes("text-muted text-sm")
                    return
                ui.label("눌러서 다시 검색").classes("text-xs text-muted")
                with ui.row().classes("gap-2 w-full"):
                    for k in list(terms)[:40]:
                        ui.button(k, on_click=lambda _, k=k: set_query(k)).props("outline dense no-caps size=sm")

        async def browser_fetch(urls: list[str]) -> list:
            """Wikimedia 요청은 사용자 PC의 브라우저가 직접 보낸다."""
            js = ("const urls=%s;return await Promise.all(urls.map(async u=>{try{const ac=new AbortController();setTimeout(()=>ac.abort(),9000);"
                  "const r=await fetch(u,{signal:ac.signal});return r.ok?await r.text():null}catch(e){return null}}))" % json.dumps(urls))
            return await ui.run_javascript(js, timeout=25)

        async def browser_images(urls: list[str]) -> list:
            js = ("const urls=%s;return await Promise.all(urls.map(async u=>{try{const r=await fetch(u);if(!r.ok)return null;const b=await r.blob();"
                  "if(!/^image\\/(png|jpeg|webp)/.test(b.type)||b.size>4e6)return null;return await new Promise(res=>{const fr=new FileReader();"
                  "fr.onload=()=>res({mime:b.type,data:String(fr.result).split(',')[1]});fr.onerror=()=>res(null);fr.readAsDataURL(b)})}catch(e){return null}}))" % json.dumps(urls))
            return await ui.run_javascript(js, timeout=40)

        def gallery_html(items: list[dict], scored: bool) -> str:
            figs = []
            for x in items:
                pct = f'<span class="kcm-cnt">{x["score"]}%</span> ' if scored else ""
                figs.append(f'<figure class="kcm-fig"><a href="{esc(x["url"])}" target="_blank" rel="noopener">'
                            f'<img src="{esc(x["img"])}" loading="lazy" referrerpolicy="no-referrer" alt="{esc(x["title"])}"></a>'
                            f'<figcaption>{pct}{esc(x["title"][:70])}<br><span class="src">{esc(x["src"])} ↗</span></figcaption></figure>')
            return '<div class="kcm-imgs">' + "".join(figs) + "</div>"

        async def load_images(site: str, dis: str, box_: ui.element, q_ver: str) -> None:
            from . import anatomy
            status["rel"] = "busy"
            render_bar()
            box_.clear()
            with box_:
                ui.label("관련 이미지를 찾는 중입니다…").classes("text-muted").style("font-size:12px")
            en = st["ai"].get("en", "") if isinstance(st["ai"], dict) else ""
            try:
                res = await anatomy.find_images(site, dis, en, browser_fetch)
            except Exception as ex:  # noqa: BLE001
                res = {"list": [], "kind": "", "err": str(ex)}
            if st["q"] != q_ver:     # 그 사이 검색어가 바뀌었으면 버린다
                return
            items = res["list"]
            counts["rel"] = len(items)
            status["rel"] = "done"
            render_bar()
            box_.clear()
            with box_:
                label = " ".join(x for x in (site, dis) if x)
                kind_txt = "  — 질환 영상" if res["kind"] == "dis" else ("  — 부위 해부도" if res["kind"] == "anat" else "")
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label(f"해부학적 부위 이미지 · {label}{kind_txt}").classes("kicker")
                    score_btn = ui.button("AI 연관률 확인", icon="auto_awesome").props("outline dense no-caps size=sm") if items else None
                if not items:
                    ui.label("이 검색어에 맞는 인체 이미지를 찾지 못했습니다." + (f" ({res['err']})" if res.get("err") else "")).classes("text-muted").style("font-size:12px")
                    return
                holder_ = ui.html(gallery_html(items, False)).classes("w-full")
                note = ui.label("출처: Wikimedia Commons · Wikipedia — 참고용 이미지이며 라이선스는 각 이미지 페이지에서 확인하세요.").classes("text-muted").style("font-size:11px")

                async def do_score() -> None:
                    score_btn.disable()
                    note.set_text("AI가 이미지와 검색어의 연관률을 확인하는 중입니다…")
                    try:
                        got = await browser_images([x["img"] for x in items])
                        loaded = [(x, g["mime"], g["data"]) for x, g in zip(items, got) if g]
                        target = f"{label} ({res.get('term', '')} {res.get('dis', '')})".strip()
                        scored_ = await run.io_bound(anatomy.score_images, loaded, target, res["kind"])
                    except Exception as ex:  # noqa: BLE001
                        note.set_text(f"연관률 확인 실패 — {ex}")
                        score_btn.enable()
                        return
                    keep = [x for x in scored_ if x["score"] >= 50]
                    holder_.set_content(gallery_html(keep, True) if keep else '<div class="text-muted">연관률 50% 이상인 이미지가 없습니다.</div>')
                    note.set_text(f"AI 연관률 {len(keep)}/{len(items)}개 (50% 이상) — 높은 순. 출처: Wikimedia Commons · Wikipedia, 참고용입니다.")
                if score_btn is not None:
                    score_btn.on_click(do_score)

        def render_related() -> None:
            rel_box.clear()
            a, t = split_query(st["q"])
            with rel_box:
                if not a and not t:
                    ui.label("이 검색어에서 찾은 해부학적 부위·질환 유형이 없습니다. ‘손가락 골절’, ‘복막염’처럼 부위나 질환명이 들어간 단어를 입력해 보세요.").classes("text-muted text-sm")
                    return
                ui.label(f"부위: {a or '—'}   ·   질환 유형: {t or '—'}").classes("font-semibold")
                img_box = ui.column().classes("w-full gap-2")
                ui.timer(0.05, lambda a=a, t=t, q=st["q"]: load_images(a, t, img_box, q), once=True)

                def count(a_: str, b_: str) -> int:
                    return idx.count_pair(a_, b_)
                if a:
                    ui.label(f"‘{a}’ 관련 질환 유형").classes("text-xs text-muted")
                    with ui.row().classes("gap-2"):
                        for ty in TYPES:
                            n = count(a, ty)
                            if n:
                                ui.button(f"{a} {ty} ({n})", on_click=lambda _, q=f"{a} {ty}": set_query(q)).props("outline dense no-caps size=sm")
                if t:
                    ui.label(f"‘{t}’ 발생 부위").classes("text-xs text-muted")
                    with ui.row().classes("gap-2"):
                        shown = 0
                        for an in ANATOMY:
                            n = count(an, t)
                            if n:
                                ui.button(f"{an} {t} ({n})", on_click=lambda _, q=f"{an} {t}": set_query(q)).props("outline dense no-caps size=sm")
                                shown += 1
                                if shown >= 24:
                                    break

        def render_ai() -> None:
            ai_box.clear()
            d = st["ai"]
            ai_done["v"] = isinstance(d, dict)
            if st["ai"] is None:
                status.pop("ai", None)
            elif isinstance(d, dict):
                status["ai"] = "done"
            elif status.get("ai") != "busy":
                status["ai"] = "error"
            render_bar()
            with ai_box:
                if d is None:
                    ui.label("색인 검색으로 부족할 때 사용하세요. 제안 코드는 상병마스터로 검증합니다.").classes("text-sm text-muted")
                    ui.button("AI로 해석 · 코드 찾기", on_click=run_ai).props("no-caps outline")
                    return
                if isinstance(d, str):
                    ui.label(f"AI 검색 실패 — {d}").classes("text-sm text-muted")
                    ui.button("다시 시도", on_click=run_ai).props("no-caps flat")
                    return
                with ui.row().classes("w-full gap-6"):
                    for lab, val in (("표준 병명", d.get("ko", "")), ("영문", d.get("en", "")),
                                     ("해부학적 부위", d.get("anatomy", "")), ("질환 유형", d.get("type", "")),
                                     ("약어 풀이", d.get("abbr", ""))):
                        if val:
                            with ui.column().classes("gap-0"):
                                ui.label(lab).classes("text-xs text-muted")
                                ui.label(val).classes("font-semibold")
                if d.get("synonyms"):
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("관련 표기").classes("text-xs text-muted")
                        for s in d["synonyms"][:8]:
                            ui.button(s, on_click=lambda _, s=s: set_query(s)).props("outline dense no-caps size=sm")
                if d.get("guide"):
                    with ui.column().classes("gap-1 w-full").style("border-left:3px solid var(--accent);padding:6px 10px;background:var(--accent-bg)"):
                        ui.label("코딩 지침").classes("text-xs text-muted")
                        for g in d["guide"]:
                            ui.label("· " + g).classes("text-sm")
                codes = d.get("codes", [])
                ok = sum(1 for c in codes if str(c.get("code", "")).strip().upper() in names)
                ui.label(f"제안 코드 · Gemini    색인 확인 {ok} / {len(codes)}").classes("text-xs text-muted")
                with ui.element("div").classes("w-full").style("display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px"):
                    for c in codes:
                        code = str(c.get("code", "")).strip().upper()
                        known = names.get(code)
                        v, _ = verdict(code)
                        with ui.column().classes("gap-1 cursor-pointer").style(
                                "border:1px solid var(--divider);border-radius:10px;padding:10px 12px;background:var(--surface2)") \
                                .on("click", lambda _, code=code: set_query(code)):
                            with ui.row().classes("w-full justify-between items-baseline no-wrap"):
                                ui.label(code).classes("text-lg font-bold").style("color:var(--accent-hi)")
                                ui.label(f"{c.get('confidence', 0)}%").classes("text-xs font-bold")
                            ui.label(known or c.get("name_ko", "")).classes("text-sm")
                            ui.label("✔ 색인 확인" if known else "⚠ 색인 미수록 — 표제부 확인").classes("text-xs").style(
                                "color:var(--ok)" if known else "color:var(--warn)")
                            if v:
                                ui.label(v).classes("text-xs").style("color:var(--warn)")
                            if c.get("reason"):
                                ui.tooltip(c["reason"])
                ui.label("코드를 누르면 색인을 다시 검색합니다.").classes("text-xs text-muted")
                # AI 해석이 맞다면 용어 사전에 저장 → 다음부터는 AI 없이 바로 찾는다
                key = (st.get("orig") or st["q"] or "").strip()
                good = [str(c.get("code", "")).strip().upper() for c in codes if str(c.get("code", "")).strip().upper() in names][:3]
                alts = [a for a in [d.get("ko", "").strip()] if a and idx.search(a, 1)] + good
                if key and alts:
                    saved = key in dictionary.entries()

                    with ui.row().classes("items-center gap-2"):
                        b = ui.button("이 해석을 용어 사전에 저장", icon="library_add").props("outline dense no-caps size=sm")
                        ui.label(f"‘{key}’ → {' · '.join(alts)}").classes("text-xs text-muted")

                        def save_dict(b=b, key=key, alts=alts) -> None:
                            try:
                                dictionary.save_entry(key, alts, user()["id"], "AI 해석")
                            except ValueError as ex:
                                ui.notify(str(ex), type="warning")
                                return
                            ui.notify(f"‘{key}’을(를) 용어 사전에 저장했습니다. 다음부터 AI 없이 바로 찾습니다.", type="positive")
                            b.disable()
                            b.set_text("사전에 저장됨")
                        if saved:
                            b.disable()
                            b.set_text("이미 사전에 있음")
                        else:
                            b.on_click(save_dict)

        async def run_ai() -> None:
            q = st["q"].strip()
            if not q:
                ui.notify("검색어를 입력하세요.", type="warning")
                return
            tabs.set_value("ai")
            status["ai"] = "busy"
            render_bar()
            ai_box.clear()
            with ai_box:
                ui.label("AI가 용어를 해석하는 중입니다…").classes("text-sm")
                ui.linear_progress(show_value=False).props("indeterminate")
            try:
                st["ai"] = await run.io_bound(gemini.semantic, q)
            except Exception as ex:  # noqa: BLE001
                st["ai"] = str(ex)
                status["ai"] = "error"
            render_ai()

        async def set_query(q: str) -> None:
            box.set_value(q)
            tabs.set_value("res")
            await do_search(True)

        async def reset_search() -> None:
            box.set_value("")
            await do_search()

        async def do_search(now: bool = False) -> None:
            q = (box.value or "").strip()
            st["rid"] = rid = st.get("rid", 0) + 1     # 겹쳐 실행된 이전 검색이 나중에 끝나도 화면을 덮어쓰지 않게
            q2, note = q, ""
            lex = DEPT_LEX.get(cond["dept"])
            if lex and q:   # 현재 진료과의 전용 약어면 그 뜻으로 검색
                hit = next((t for t in lex["terms"] if t[0].lower() == q.lower()), None)
                if hit:
                    q2, note = hit[1], f"‘{q}’ → {hit[1]} ({cond['dept']} 해석으로 검색)"
            if not note and q:      # 구어·영문·약어를 공식 명칭으로 풀어 찾았다면 어떻게 풀었는지 알려 준다
                note = idx.explain(q)
            st["q"], st["orig"], st["note"] = q2, q, note
            st["limit"] = 12
            st["ai"] = None
            ai_done["v"] = False
            status.pop("ai", None)
            steps = ("res", "sim", "dept", "rel")
            if not q:           # 빈 검색어 — 모든 상태 초기화
                for k in steps:
                    status.pop(k, None)
                st["hits"], st["cmp"] = [], []
                counts.update(res=0, sim=0, dept=0)
                info.set_text("")
                render_results(); render_similar(); render_dept(); render_related(); render_ai(); render_bar()
                return
            for k in steps:     # 진행 상황: 모두 ‘검색중’
                status[k] = "busy"
            render_bar()
            await asyncio.sleep(0)
            if st["rid"] != rid:
                return
            hits = await run.io_bound(idx.search, q2)
            if st["rid"] != rid:
                return
            if lex:             # 진료과 우선 코드 장을 앞으로 (안정 정렬)
                hits.sort(key=lambda r: not any(r.code.upper().startswith(p) for p in lex["pre"]))
            st["hits"] = hits
            n = len(hits)
            counts["res"] = n
            info.set_text(f"{n}건" + (" (최대 200건 표시)" if n >= 200 else ""))
            render_results()
            status["res"] = "done"
            render_bar()
            await asyncio.sleep(0)
            if st["rid"] != rid:
                return
            render_similar()
            status["sim"] = "done"
            render_bar()
            await asyncio.sleep(0)
            if st["rid"] != rid:
                return
            st["cmp"] = dept_interpretations(q, cond["dept"], code_for)
            render_dept()
            status["dept"] = "done"
            render_bar()
            await asyncio.sleep(0)
            if st["rid"] != rid:
                return
            render_related()
            status["rel"] = "done"
            render_ai()
            render_bar()
            if n == 0 or idx.is_relaxed(q2):
                # 결과가 없거나 일부 단어만 맞으면 → 입력이 1.2초 멈춘 뒤에만 기록하고 AI가 해석한다
                # (타이핑 도중의 미완성 단어마다 AI를 부르거나 기록하지 않게)
                async def settle(q_=q) -> None:
                    if st.get("orig") != q_ or st["rid"] != rid:
                        return
                    dictionary.log_missed(q_, user()["id"])     # 관리자가 용어 사전에 넣을 수 있게 기록
                    await run_ai()
                ui.timer(0.05 if now or not st["auto"] else 1.2, settle, once=True)
        def revalidate() -> None:
            st["sex"], st["age"] = sex.value or "", parse_age(age.value)
            render_results()
            render_ai()

        box.on("keydown.enter", lambda: do_search(True))
        async def on_typing(e) -> None:
            """글자를 칠 때마다 (잠깐 멈추면) 바로 검색 — 엔터 없이 실시간으로 결과가 바뀐다"""
            if not st["auto"]:
                return
            st["typing"] = tid = st.get("typing", 0) + 1
            await asyncio.sleep(0.18)
            if st["typing"] != tid:           # 그 사이 더 쳤으면 마지막 글자 기준으로만 검색
                return
            await do_search()
        box.on_value_change(on_typing)
        sex.on_value_change(lambda _: revalidate())
        age.on("update:model-value", revalidate, throttle=0.4)
        render_results()
        render_similar()
        render_dept()
        render_related()
        render_ai()


# ═════════════════════ 정밀 분석 ═════════════════════
@ui.page("/detail")
def detail_page(code: str = "") -> None:
    if not require_login():
        return
    layout("search")
    idx = get_index()
    fam = rules.Family(idx)
    code = (code or "").strip().upper()
    row = next((r for r in idx.rows if r.code.upper() == code), None)

    with ui.column().classes("w-full max-w-5xl gap-3"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/search")).props("flat round dense")
            ui.label("정밀 분석").classes("text-xl font-bold")
        if not code:
            ui.label("검색 화면에서 코드를 골라 ‘정밀 분석’을 누르세요.").classes("text-muted")
            return

        with ui.column().classes("kcm-card w-full gap-1"):
            ui.label(code).classes("text-3xl font-bold").style("color:var(--accent-hi)")
            if row:
                ui.label(row.ko).classes("text-lg font-semibold")
                if row.en:
                    ui.label(row.en).classes("text-sm text-muted")
                if row.syn:
                    ui.label("동의어: " + ", ".join(row.syn)).classes("text-sm text-muted")
            else:
                ui.label("상병마스터에 없는 코드입니다 — 상위 계열만 표시합니다.").style("color:var(--warn)")
            kids = fam.children(code)
            if fam.has_child(code):
                ui.label("⚠ 하위 세분류가 있습니다. 최말단 코드까지 지정해야 청구할 수 있습니다.").classes("text-sm").style("color:var(--warn)")
            elif row:
                ui.label("✔ 최말단 코드 — 청구 가능").classes("text-sm").style("color:var(--ok)")

            def to_favs() -> None:
                from .phase3 import add_fav
                ui.notify("코드집에 담았습니다." if add_fav(code, row.ko if row else "") else "이미 코드집에 있습니다.")

            def to_hist() -> None:
                from .phase3 import add_history
                add_history(code, code, row.ko if row else "", "", "정밀 분석")
                ui.notify("이력에 기록했습니다.", type="positive")
            with ui.row().classes("gap-2 pt-2"):
                ui.button("코드집에 담기", icon="star", on_click=to_favs).props("no-caps outline")
                ui.button("이력에 기록", icon="history", on_click=to_hist).props("no-caps outline")

        # 사용 규칙
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("사용 규칙 점검").classes("font-semibold")
            lim = rules.restriction(code)
            np_ = rules.no_primary(code)
            notes = []
            for pre, need, note in rules.RULE_SEX:
                if any(code.startswith(p) for p in pre):
                    notes.append(f"성별 — {note}")
            for pre, lo, hi, note in rules.RULE_AGE:
                if any(code.startswith(p) for p in pre):
                    notes.append(f"연령 — {note}")
            if np_:
                notes.append(f"주진단 불가 — {np_}")
            for a, b, note in rules.RULE_EXCLUSIVE:
                if any(code.startswith(p) for p in a + b):
                    notes.append(f"배타 관계 — {note}")
            if not notes:
                ui.label("해당하는 사전 점검 규칙이 없습니다 (성별·연령 제한 없음, 주진단 가능).").classes("text-sm text-muted")
            for n in notes:
                ui.label("· " + n).classes("text-sm")

        with ui.row().classes("w-full no-wrap gap-3 items-start"):
            with ui.column().classes("kcm-card gap-2").style("flex:1 1 0;min-width:0"):
                ui.label("하위 세분류").classes("font-semibold")
                if not kids:
                    ui.label("하위 코드가 없습니다.").classes("text-sm text-muted")
                for k in kids[:60]:
                    with ui.row().classes("items-baseline gap-3 no-wrap cursor-pointer").on("click", lambda _, k=k: ui.navigate.to(f"/detail?code={k}")):
                        ui.label(k).classes("font-bold").style("min-width:64px;color:var(--accent-hi)")
                        ui.label(fam.names.get(k, "")).classes("text-sm")
            with ui.column().classes("kcm-card gap-2").style("flex:1 1 0;min-width:0"):
                ui.label("같은 계열 코드").classes("font-semibold")
                root = code[:3]
                sib = [k for k in fam.keys if k.startswith(root) and k != code and not fam.has_child(k)][:40]
                if not sib:
                    ui.label("같은 계열 코드가 없습니다.").classes("text-sm text-muted")
                for k in sib:
                    with ui.row().classes("items-baseline gap-3 no-wrap cursor-pointer").on("click", lambda _, k=k: ui.navigate.to(f"/detail?code={k}")):
                        ui.label(k).classes("font-bold").style("min-width:64px;color:var(--accent-hi)")
                        ui.label(fam.names.get(k, "")).classes("text-sm")

        with ui.column().classes("kcm-card w-full gap-1"):
            ui.label("3권 색인에서의 위치").classes("font-semibold")
            paths = tree_paths(code)
            if not paths:
                ui.label("3권 색인에서 이 코드를 찾지 못했습니다.").classes("text-sm text-muted")
            for p in paths:
                ui.label(p).classes("text-sm")

        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("AI 코딩 지침").classes("font-semibold")
            out = ui.markdown("").classes("text-sm")
            status = ui.label("").classes("text-sm text-muted")

            async def ask() -> None:
                status.set_text("AI가 분석 중입니다…")
                sysmsg = ("당신은 한국 병원 심사·코딩 전문가입니다. 주어진 KCD 코드에 대해 코딩 시 주의점을 한국어로 간결히 정리합니다. "
                          "형식: 1) 이 코드가 쓰이는 상황 2) 흔한 오류·삭감 사유 3) 함께/대신 고려할 코드. 각 항목 2~3줄 이내, 불확실하면 확인이 필요하다고 쓰세요.")
                try:
                    txt = await run.io_bound(gemini.generate, sysmsg,
                                             [{"text": f"코드: {code}\n명칭: {row.ko if row else ''}\n영문: {row.en if row else ''}"}], None, 1500)
                    out.set_content(txt)
                    status.set_text("AI 해석은 참고용입니다 — 최종 판단은 코더가 합니다.")
                except Exception as ex:  # noqa: BLE001
                    status.set_text(f"실패 — {ex}")
            ui.button("AI 지침 보기", icon="auto_awesome", on_click=ask).props("no-caps outline")
