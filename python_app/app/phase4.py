"""4단계 화면 — 검색 · 코드 생성(탭·AI 의미 검색·성별/연령 검증) / 정밀 분석"""
from __future__ import annotations

from nicegui import run, ui

from . import gemini, rules, store
from .main import get_index, layout, require_login, user
from .search import norm

ANATOMY = ["손가락", "발가락", "손목", "발목", "무릎", "어깨", "팔꿈치", "고관절", "대퇴골", "경골", "요골", "척추", "허리", "목", "머리",
           "뇌", "눈", "귀", "코", "인두", "후두", "식도", "위", "십이지장", "소장", "대장", "결장", "직장", "간", "담낭", "담관", "췌장",
           "비장", "신장", "콩팥", "방광", "요도", "전립선", "난소", "자궁", "유방", "갑상선", "폐", "기관지", "심장", "피부", "복막",
           "복부", "흉부", "흉막", "치아", "구강", "갈비뼈", "쇄골", "골반", "발", "손", "다리", "팔", "얼굴", "턱", "관절"]
TYPES = ["골절", "탈구", "염좌", "악성신생물", "양성신생물", "염증", "감염", "출혈", "경색", "결석", "궤양", "화상", "열상", "폐렴",
         "협착", "폴립", "낭종", "종양", "마비", "통증", "기형", "천공", "파열"]
_ANAT_SORTED = sorted(ANATOMY, key=len, reverse=True)


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
    fam = rules.Family(idx)
    names = {r.code.upper(): r.ko for r in idx.rows}
    st = {"q": "", "sex": "", "age": None, "hits": [], "ai": None}

    ui.add_css(".kcm-search .q-field__control{height:58px}.kcm-search input{font-size:17px}")
    st["view"] = "card"
    st["auto"] = True
    with ui.column().classes("w-full max-w-5xl gap-3"):
        with ui.column().classes("kcm-card w-full gap-3"):
            ui.label("질병명 · 진단명 · 의학용어 · 약어 · 코드").style("font-size:12px;color:var(--muted)")
            box = ui.input(placeholder="예: 위암 / gastric cancer / HTN / appendicitis / J18").props("outlined clearable autofocus") \
                .classes("kcm-search w-full")
            with ui.row().classes("w-full no-wrap gap-2 items-stretch"):
                ui.button("코드 생성", on_click=lambda: do_search()).props("no-caps unelevated color=primary").classes("grow").style("min-height:40px;font-size:15px")
                ui.button("AI", icon="auto_awesome", on_click=lambda: run_ai()).props("no-caps outline")
                auto_btn = ui.button("자동 ON", icon="bolt").props("no-caps outline")

                def toggle_auto() -> None:
                    st["auto"] = not st["auto"]
                    auto_btn.set_text("자동 ON" if st["auto"] else "자동 OFF")
                auto_btn.on_click(toggle_auto)
                ui.button("초기화", on_click=lambda: (box.set_value(""), do_search())).props("no-caps outline")
            with ui.row().classes("gap-2"):
                for chip in ["위암", "고혈압", "폐렴", "Appendicitis", "관절염", "두통", "J18", "HTN"]:
                    ui.button(chip, on_click=lambda _, c=chip: set_query(c)).props("outline dense no-caps size=sm").style("padding:0 10px")
            with ui.row().classes("items-center gap-3"):
                ui.label("환자 조건 검증").classes("text-muted").style("font-size:12px")
                sex = ui.select({"": "성별 전체", "M": "남", "F": "여"}, value="").props("dense outlined").classes("w-32")
                age = ui.input(placeholder="연령(세)").props("dense outlined type=number min=0 max=120").classes("w-32")
                ui.label(f"입력하면 성별·연령에 맞지 않는 코드를 표시합니다 · KCD 상병 {len(idx):,}건").classes("text-muted").style("font-size:11px")
        info = ui.label("").classes("text-muted").style("font-size:12px")
        with ui.tabs().classes("w-full").props("dense align=left") as tabs:
            t_res = ui.tab("res", label="결과 · 코드")
            t_ai = ui.tab("ai", label="✦ AI 의미 검색")
            t_sim = ui.tab("sim", label="유사한 용어")
            t_rel = ui.tab("rel", label="연관 질환 · 해부학적 부위")
        with ui.tab_panels(tabs, value="res").classes("w-full").style("background:transparent"):
            with ui.tab_panel("res").classes("p-0"):
                res_box = ui.column().classes("w-full gap-2")
            with ui.tab_panel("ai").classes("p-0"):
                ai_box = ui.column().classes("w-full gap-3 kcm-card")
            with ui.tab_panel("sim").classes("p-0"):
                sim_box = ui.column().classes("w-full gap-2 kcm-card")
            with ui.tab_panel("rel").classes("p-0"):
                rel_box = ui.column().classes("w-full gap-2 kcm-card")

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
                    ui.label("검색어를 입력하고 ‘코드 생성’을 누르세요.").classes("text-muted text-sm")
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
                    for root, rows_ in list(groups.items())[:30]:
                        head = next((r for r in rows_ if r.code == root), rows_[0])
                        with ui.column().classes("kcm-card w-full gap-2"):
                            ui.label((head.en or f"{root} 계열").upper()).classes("kicker")
                            ui.label(head.ko).style("font-family:var(--font-heading);font-weight:600;font-size:24px;line-height:1.15")
                            ui.label(f"{root} 계열 · 코드 {len(rows_)}개").classes("text-muted").style("font-size:13px")
                            with ui.element("div").classes("w-full").style(
                                    "display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px"):
                                for i, r in enumerate(rows_[:6]):
                                    v, _ = verdict(r.code)
                                    with ui.column().classes("gap-1").style(
                                            "border:1px solid var(--color-divider);border-radius:10px;padding:10px 12px;background:var(--surface-2)"
                                            + (";border-color:var(--color-accent)" if i == 0 else "")):
                                        with ui.row().classes("w-full items-center justify-between no-wrap"):
                                            ui.label(r.code).classes("mono").style("font-weight:700;font-size:15px;color:var(--accent-hi)")
                                            if i == 0:
                                                ui.html('<span class="kcm-tag">추천</span>')
                                        ui.label(r.ko).style("font-size:14px;line-height:1.35")
                                        ui.label(unit_label(r.code)).classes("text-muted").style("font-size:11px")
                                        lim = rules.restriction(r.code)
                                        if lim:
                                            ui.label("제한: " + lim).style("font-size:11px;color:var(--warn)")
                                        if v:
                                            ui.label(v).style("font-size:11px;color:var(--warn)")
                                        with ui.row().classes("w-full justify-end gap-1"):
                                            ui.button("정밀 분석", on_click=lambda _, c=r.code: go_detail(c)).props("outline dense no-caps size=sm")
                            if len(rows_) > 6:
                                ui.label(f"… 외 {len(rows_) - 6}개 — 목록형에서 모두 볼 수 있습니다.").classes("text-muted").style("font-size:12px")
                            with ui.row().classes("w-full justify-end gap-2"):
                                ui.button("즐겨찾기", icon="star_outline", on_click=lambda _, c=head.code: to_favs(c)).props("outline dense no-caps size=sm")
                                ui.button("이력에 기록", icon="history", on_click=lambda _, c=head.code: to_hist(c)).props("outline dense no-caps size=sm")
                                ui.button("정밀 분석", on_click=lambda _, c=head.code: go_detail(c)).props("unelevated dense no-caps size=sm color=primary")
                    if len(groups) > 30:
                        ui.label(f"계열 {len(groups) - 30}개 더 있음 — 검색어를 좁혀 보세요.").classes("text-muted text-sm")
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
            with sim_box:
                if not terms:
                    ui.label("유사한 용어가 없습니다.").classes("text-muted text-sm")
                    return
                ui.label("눌러서 다시 검색").classes("text-xs text-muted")
                with ui.row().classes("gap-2 w-full"):
                    for k in list(terms)[:40]:
                        ui.button(k, on_click=lambda _, k=k: set_query(k)).props("outline dense no-caps size=sm")

        def render_related() -> None:
            rel_box.clear()
            a, t = split_query(st["q"])
            with rel_box:
                if not a and not t:
                    ui.label("이 검색어에서 찾은 해부학적 부위·질환 유형이 없습니다. ‘손가락 골절’, ‘복막염’처럼 부위나 질환명이 들어간 단어를 입력해 보세요.").classes("text-muted text-sm")
                    return
                ui.label(f"부위: {a or '—'}   ·   질환 유형: {t or '—'}").classes("font-semibold")

                def count(q: str) -> int:
                    return len(idx.search(q, limit=500))
                if a:
                    ui.label(f"‘{a}’ 관련 질환 유형").classes("text-xs text-muted")
                    with ui.row().classes("gap-2"):
                        for ty in TYPES:
                            n = count(f"{a} {ty}")
                            if n:
                                ui.button(f"{a} {ty} ({n})", on_click=lambda _, q=f"{a} {ty}": set_query(q)).props("outline dense no-caps size=sm")
                if t:
                    ui.label(f"‘{t}’ 발생 부위").classes("text-xs text-muted")
                    with ui.row().classes("gap-2"):
                        shown = 0
                        for an in ANATOMY:
                            n = count(f"{an} {t}")
                            if n:
                                ui.button(f"{an} {t} ({n})", on_click=lambda _, q=f"{an} {t}": set_query(q)).props("outline dense no-caps size=sm")
                                shown += 1
                                if shown >= 24:
                                    break

        def render_ai() -> None:
            ai_box.clear()
            d = st["ai"]
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

        async def run_ai() -> None:
            q = st["q"].strip()
            if not q:
                ui.notify("검색어를 입력하세요.", type="warning")
                return
            tabs.set_value("ai")
            ai_box.clear()
            with ai_box:
                ui.label("AI가 용어를 해석하는 중입니다…").classes("text-sm")
                ui.linear_progress(show_value=False).props("indeterminate")
            try:
                st["ai"] = await run.io_bound(gemini.semantic, q)
            except Exception as ex:  # noqa: BLE001
                st["ai"] = str(ex)
            render_ai()

        def set_query(q: str) -> None:
            box.set_value(q)
            tabs.set_value("res")
            do_search()

        def do_search() -> None:
            q = (box.value or "").strip()
            st["q"] = q
            st["hits"] = idx.search(q)
            st["ai"] = None
            n = len(st["hits"])
            info.set_text((f"{n}건" + (" (최대 200건 표시)" if n >= 200 else "")) if q else "")
            render_results()
            render_similar()
            render_related()
            render_ai()
            if q and n == 0:
                ui.timer(0.05, run_ai, once=True)

        def revalidate() -> None:
            st["sex"], st["age"] = sex.value or "", parse_age(age.value)
            render_results()
            render_ai()

        box.on("keydown.enter", do_search)
        box.on("update:model-value", lambda: do_search() if st["auto"] else None, throttle=0.5)
        sex.on_value_change(lambda _: revalidate())
        age.on("update:model-value", revalidate, throttle=0.4)
        render_results()
        render_similar()
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
