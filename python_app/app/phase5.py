"""5단계 화면 — 사용자 관리 (기관 관리 · 신규 사용자 등록 · 사용자 목록 · Google 로그인 설정)"""
from __future__ import annotations

import html
import random
import re

from nicegui import app, ui

from . import store
from .main import layout, require_login, user
from .security import ROLE_LABEL, acc_status, hash_strong, is_gmail, pw_key

CSS = """
.kcm-chip{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;background:var(--a200);border:1px solid var(--a300);color:var(--a900);white-space:nowrap}
.kcm-chip.warn{background:transparent;border:1px solid var(--warn);color:var(--warn)}
.kcm-chip.off{background:var(--n200);border:1px solid var(--n300);color:var(--n800)}
.kcm-chip.ok{background:var(--a200);border:1px solid var(--a300);color:var(--a900)}
.kcm-chip .q-icon{color:var(--a900);margin-right:4px}
.kcm-org{display:grid;width:100%;box-sizing:border-box;grid-template-columns:22px minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px 14px;margin-bottom:10px;
 border:1px solid var(--color-divider);border-radius:12px;background:var(--surface-2)}
.kcm-org.stopped{background:var(--surface);border-style:dashed}
.kcm-org.stopped .kcm-pill{opacity:.6}
.kcm-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.kcm-orow{display:grid;width:100%;box-sizing:border-box;grid-template-columns:22px minmax(150px,1.4fr) 92px 84px minmax(0,1fr) max-content;gap:10px;align-items:center;
 padding:8px 12px;border-bottom:1px solid var(--color-divider);min-height:50px}
.kcm-orow:not(.head):hover{background:var(--surface-2)}
.kcm-orow.head{min-height:0;padding:6px 12px;font-size:11px;letter-spacing:.06em;color:var(--muted);background:var(--n100);border-radius:8px 8px 0 0}
.kcm-orow.stopped{opacity:.72}
.kcm-oname{display:flex;align-items:center;gap:4px;cursor:pointer;min-width:0}
.kcm-oname:hover{color:var(--color-accent)}
.kcm-odetail{display:grid;gap:8px;padding:10px 14px 12px 44px;background:var(--a100);border-bottom:1px solid var(--color-divider)}
.q-btn.kcm-act.szs{min-height:28px!important;padding:1px 8px!important;font-size:12px}
@media (max-width:1000px){.kcm-orow{grid-template-columns:22px minmax(0,1fr)}.kcm-orow .kcm-actions{grid-column:1/-1;justify-content:flex-start}.kcm-orow.head{display:none}}
.kcm-lab{display:inline-block;font-size:11px;font-weight:700;color:var(--a800);background:var(--a200);border-radius:6px;padding:1px 8px;margin-right:8px;white-space:nowrap}
.q-btn.kcm-act{border:1.5px solid var(--color-divider)!important;border-radius:8px!important;padding:3px 12px!important;min-height:34px!important;font-weight:600;font-size:13px;
 background:var(--surface)!important;color:var(--color-text)!important}
.q-btn.kcm-act .q-icon{font-size:18px;margin-right:4px}
.q-btn.kcm-act:hover{filter:brightness(.96);transform:translateY(-1px)}
.q-btn.kcm-act.pri{border-color:var(--color-accent)!important;color:var(--color-accent)!important;background:var(--a100)!important}
.q-btn.kcm-act.warn{border-color:var(--warn)!important;color:var(--warn)!important}
.q-btn.kcm-act.ok{border-color:var(--ok)!important;color:var(--ok)!important}
.q-btn.kcm-act.bad{border-color:var(--bad)!important;color:var(--bad)!important}
@media (max-width:1000px){.kcm-org{grid-template-columns:22px minmax(0,1fr)}.kcm-org .kcm-actions{grid-column:1/-1;justify-content:flex-start}}
.kcm-pill{border:1px solid var(--color-text);border-radius:8px;padding:6px 12px;font-weight:600;font-size:14px;cursor:pointer;white-space:nowrap}
.kcm-urow{display:grid;grid-template-columns:1.1fr 1.7fr 1.5fr .9fr 1.3fr 64px 64px;gap:12px;align-items:center;padding:12px 8px;border-bottom:1px solid var(--color-divider);min-width:860px}
.kcm-urow.head{font-size:12px;color:var(--muted);padding:9px 8px;background:var(--n100);border-radius:8px 8px 0 0}
.kcm-sec-h{font-family:var(--font-heading);font-weight:600;font-size:13px;letter-spacing:.08em;text-transform:uppercase}
"""


def _by() -> str:
    return user()["id"]


def _split(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n]", s or "") if x.strip()]


def _new_id() -> str:
    return "o" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))


def _status_kind(label: str) -> str:
    if label.startswith("사용 중"):
        return "사용 중"
    if label.startswith("예약"):
        return "예약"
    if label.startswith("만료"):
        return "만료"
    return "비활성"


@ui.page("/users")
def users_page() -> None:
    if not require_login(("sysadmin", "orgadmin")):
        return
    layout("users")
    ui.add_css(CSS)
    me = user()
    is_sys = me["role"] == "sysadmin"
    flt = {"org": "", "status": "", "q": ""}

    def my_orgs() -> list[dict]:
        orgs = store.orgs()
        return orgs if is_sys else [o for o in orgs if o["id"] == me.get("orgId")]

    def my_accounts() -> list[dict]:
        accs = store.accounts()
        if is_sys:
            return accs
        return [a for a in accs if a.get("orgId") == me.get("orgId") and a.get("role") != "sysadmin"]

    def save_accounts(a: list[dict]) -> None:
        store.put("global", "accounts", a, by=_by())

    def save_orgs(o: list[dict]) -> None:
        store.put("global", "orgs", o, by=_by())

    def refresh_all() -> None:
        render_orgs()
        render_reg()
        render_list()

    with ui.column().classes("w-full gap-4").style("max-width:1200px"):
        ui.label("사용자 관리").classes("kcm-h1")
        ui.label(("시스템 관리자 — 모든 기관과 사용자를 관리합니다. " if is_sys else "기관 관리자 — 소속 기관의 사용자를 관리합니다. ")
                 + "사용자는 소속기관과 사번 또는 Gmail로 로그인하고, 활성 여부와 유효기간으로 사용을 제어합니다.") \
            .classes("text-muted").style("font-size:13px;margin-top:-8px")
        ui.html('<div style="display:inline-flex;gap:8px;align-items:center;border:1px solid var(--color-divider);padding:5px 12px;font-size:12px;width:fit-content">'
                '<span style="width:8px;height:8px;border-radius:50%;background:var(--ok)"></span><b>자동 저장</b>'
                '<span class="text-muted">수정하면 즉시 저장됩니다</span></div>')
        orgs_box = ui.column().classes("kcm-card w-full gap-2")
        reg_box = ui.column().classes("kcm-card w-full gap-3")
        list_box = ui.column().classes("kcm-card w-full gap-3")
        if is_sys:
            google_box = ui.column().classes("kcm-card w-full gap-2")

    # ───────────── 기관 관리 ─────────────
    # 기관이 많아져도 쓰기 쉽게: 한 줄에 한 기관(요약) · 검색/상태 필터 · 펼쳐서 부서·직책 보기 · 10개씩 더 보기
    ou = {"q": "", "st": "all", "open": set(), "limit": 10}
    refs: dict = {}

    def org_filtered(orgs: list[dict]) -> list[dict]:
        q = ou["q"].strip().lower()
        out = []
        for o in orgs:
            if ou["st"] != "all" and (ou["st"] == "on") != bool(o.get("active", True)):
                continue
            hay = [o.get("name", "")] + list(o.get("depts") or []) + list(o.get("titles") or [])
            if q and not any(q in str(x).lower() for x in hay):
                continue
            out.append(o)
        return out

    def show_org_users(o: dict) -> None:
        """이 기관의 사용자만 아래 목록에 보여 준다"""
        flt["org"] = o["id"]
        render_list()
        ui.run_javascript(f"document.getElementById('c{list_box.id}').scrollIntoView({{behavior:'smooth',block:'start'}})")

    def render_org_rows() -> None:
        box = refs["rows"]
        box.clear()
        allorgs = my_orgs()
        cnt: dict = {}
        for a in store.accounts():
            cnt[a.get("orgId")] = cnt.get(a.get("orgId"), 0) + 1
        shown = org_filtered(allorgs)
        filtering = bool(ou["q"].strip()) or ou["st"] != "all"
        part = shown[:ou["limit"]]
        with box:
            if not shown:
                ui.label("조건에 맞는 기관이 없습니다.").classes("text-muted").style("padding:18px 6px;font-size:13px")
                return
            with ui.element("div").classes("kcm-orow head"):
                for h in ("", "기관", "상태", "사용자", "부서 · 직책", ""):
                    ui.label(h)
            for o in part:
                active = bool(o.get("active", True))
                d, t = o.get("depts") or [], o.get("titles") or []
                opened = o["id"] in ou["open"]
                with ui.element("div").classes("kcm-orow" + ("" if active else " stopped")).props(f'data-dnd="orgs" data-key="{o["id"]}"'):
                    can_drag = is_sys and not filtering
                    ui.label("⋮⋮").classes("kcm-grip").props(f'draggable="{"true" if can_drag else "false"}"').style(
                        "cursor:grab;font-size:18px" if can_drag else "opacity:.25").tooltip(
                        "끌어서 순서 변경" if can_drag else ("검색·필터를 끄면 순서를 바꿀 수 있습니다" if is_sys else ""))
                    nm = ui.element("div").classes("kcm-oname").tooltip("눌러서 부서 · 직책 보기")
                    with nm:
                        ui.icon("expand_more" if opened else "chevron_right").classes("text-lg")
                        ui.label(o["name"]).style("font-weight:700;font-size:15px")
                    nm.on("click", lambda _, o=o: toggle_open(o))
                    ui.html('<span class="kcm-chip ok">● 사용 중</span>' if active else '<span class="kcm-chip warn">⏸ 중지됨</span>')
                    ub = ui.element("div").classes("kcm-chip").style("cursor:pointer").tooltip("이 기관의 사용자만 아래 목록에 보기")
                    with ub:
                        ui.icon("group").classes("text-base")
                        ui.label(f"{cnt.get(o['id'], 0)}명")
                    ub.on("click", lambda _, o=o: show_org_users(o))
                    ui.label(f"부서 {len(d)} · 직책 {len(t)}").classes("text-muted").style("font-size:13px")
                    with ui.element("div").classes("kcm-actions"):
                        ui.button("편집", icon="edit", color=None, on_click=lambda _, o=o: dept_dialog(o)).props("unelevated no-caps dense").classes("kcm-act pri szs").tooltip(
                            "이 기관의 부서와 직책 목록을 추가·삭제합니다")
                        if is_sys:
                            if active:
                                ui.button("중지", icon="pause_circle", color=None, on_click=lambda _, o=o: toggle_org(o)).props("unelevated no-caps dense").classes("kcm-act warn szs").tooltip(
                                    "이 기관 사용자의 로그인을 막습니다 (데이터는 그대로 남습니다)")
                            else:
                                ui.button("재개", icon="play_circle", color=None, on_click=lambda _, o=o: toggle_org(o)).props("unelevated no-caps dense").classes("kcm-act ok szs").tooltip(
                                    "이 기관 사용자가 다시 로그인할 수 있게 합니다")
                            ui.button("삭제", icon="delete_outline", color=None, on_click=lambda _, o=o: delete_org(o)).props("unelevated no-caps dense").classes("kcm-act bad szs").tooltip(
                                "기관을 지웁니다 — 사용자가 없을 때만 가능합니다")
                if opened:
                    with ui.element("div").classes("kcm-odetail"):
                        for lab, items in (("부서", d), ("직책", t)):
                            with ui.row().classes("items-start gap-2 no-wrap w-full"):
                                ui.html(f'<span class="kcm-lab">{lab} {len(items)}</span>')
                                if items:
                                    with ui.row().classes("gap-1").style("flex:1"):
                                        for x in items:
                                            ui.html(f'<span class="kcm-chip">{html.escape(str(x))}</span>')
                                else:
                                    ui.label(f"등록된 {lab} 없음 — ‘편집’에서 추가하세요").classes("text-muted").style("font-size:12px")
                        with ui.row().classes("gap-2").style("padding-top:4px"):
                            if is_sys:
                                ui.button("기관 이름 변경", icon="drive_file_rename_outline", color=None, on_click=lambda _, o=o: rename_dialog(o)).props(
                                    "unelevated no-caps dense").classes("kcm-act szs")
            rest = len(shown) - len(part)
            with ui.row().classes("w-full items-center justify-between").style("padding-top:8px"):
                ui.label(f"{len(part)}개 표시 · 전체 {len(allorgs)}개" + (f" (조건에 맞는 {len(shown)}개)" if filtering else "")).classes("text-muted").style("font-size:12px")
                if rest > 0:
                    with ui.row().classes("gap-2"):
                        ui.button(f"{min(10, rest)}개 더 보기", on_click=lambda: more_orgs(10)).props("outline no-caps dense")
                        if rest > 10:
                            ui.button(f"모두 보기 ({rest}개)", on_click=lambda: more_orgs(10_000)).props("flat no-caps dense")

    def more_orgs(n: int) -> None:
        ou["limit"] += n
        render_org_rows()

    def toggle_open(o: dict) -> None:
        (ou["open"].discard if o["id"] in ou["open"] else ou["open"].add)(o["id"])
        render_org_rows()

    def render_orgs() -> None:
        orgs_box.clear()
        allorgs = my_orgs()
        n_on = sum(1 for o in allorgs if o.get("active", True))
        with orgs_box:
            with ui.row().classes("w-full items-center justify-between").style("gap:10px"):
                with ui.row().classes("items-center gap-3"):
                    ui.label("기관 관리" if is_sys else "소속 기관").classes("kcm-sec-h")
                    ui.html(f'<span class="kcm-chip">전체 {len(allorgs)}개</span><span class="kcm-chip ok" style="margin-left:6px">사용 중 {n_on}</span>'
                            + (f'<span class="kcm-chip warn" style="margin-left:6px">중지 {len(allorgs) - n_on}</span>' if len(allorgs) - n_on else ""))
                if is_sys:
                    ui.button("기관 추가", icon="add", on_click=lambda: add_dialog_org()).props("no-caps unelevated color=primary dense")
            if len(allorgs) > 3:       # 기관이 늘어나면 찾기·거르기 도구를 보여 준다
                with ui.row().classes("w-full items-center gap-2").style("flex-wrap:wrap"):
                    s = ui.input(placeholder="기관·부서·직책 검색", value=ou["q"]).props("dense outlined clearable").classes("grow").style("min-width:220px;max-width:420px")

                    def on_q(e) -> None:
                        ou["q"] = e.value or ""
                        ou["limit"] = 10
                        render_org_rows()
                    s.on_value_change(on_q)
                    with ui.element("div").classes("kcm-seg"):
                        for k, lab in (("all", "전체"), ("on", "사용 중"), ("off", "중지됨")):
                            b = ui.element("button").classes("on" if ou["st"] == k else "")
                            with b:
                                ui.label(lab)
                            b.on("click", lambda _, k=k: set_status(k))
            ui.label(("기관 이름을 누르면 부서·직책이 펼쳐집니다. 사용자 수를 누르면 그 기관의 사용자만 아래에 모아 봅니다. "
                      "중지한 기관의 사용자는 로그인할 수 없습니다." + (" 왼쪽 손잡이를 끌어 순서를 바꿉니다." if is_sys else ""))).classes("text-muted").style("font-size:12px")
            refs["rows"] = ui.column().classes("w-full gap-0")
        render_org_rows()

    def set_status(k: str) -> None:
        ou["st"] = k
        ou["limit"] = 10
        render_orgs()

    def add_dialog_org() -> None:
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(520px,94vw);gap:12px"):
            ui.label("기관 추가").style("font-family:var(--font-heading);font-weight:600;font-size:20px")
            name = ui.input("기관명").props("dense outlined").classes("w-full")
            depts = ui.input("부서 (쉼표로 구분, 나중에 ‘편집’에서 바꿀 수 있습니다)", placeholder="예: 1병동, 2병동, 보험심사팀").props("dense outlined").classes("w-full")

            def ok() -> None:
                if add_org(name.value, depts.value):
                    dlg.close()
            name.on("keydown.enter", ok)
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")
                ui.button("추가", on_click=ok).props("no-caps unelevated color=primary")
        dlg.open()

    def add_org(name: str, depts: str) -> bool:
        name = (name or "").strip()
        if not name:
            ui.notify("기관명을 입력하세요.", type="warning")
            return False
        orgs = store.orgs(fresh=True)
        if any(o["name"] == name for o in orgs):
            ui.notify("이미 있는 기관명입니다.", type="negative")
            return False
        orgs.append({"id": _new_id(), "name": name, "depts": _split(depts), "titles": [], "active": True})
        save_orgs(orgs)
        ui.notify(f"‘{name}’ 기관을 추가했습니다.", type="positive")
        refresh_all()
        return True

    def rename_dialog(o: dict) -> None:
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(420px,92vw)"):
            ui.label("기관명 수정").style("font-family:var(--font-heading);font-weight:600;font-size:20px")
            name = ui.input(value=o["name"]).props("dense outlined").classes("w-full")

            def ok() -> None:
                v = (name.value or "").strip()
                if not v:
                    return
                orgs = store.orgs(fresh=True)
                for x in orgs:
                    if x["id"] == o["id"]:
                        x["name"] = v
                save_orgs(orgs)
                dlg.close()
                refresh_all()
            name.on("keydown.enter", ok)
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")
                ui.button("저장", on_click=ok).props("no-caps unelevated color=primary")
        dlg.open()

    def dept_dialog(o: dict) -> None:
        """부서·직책을 칩으로 편집 — Enter(또는 쉼표)로 추가, ✕ 로 삭제, 여러 개를 붙여 넣어도 된다"""
        data = {"d": list(o.get("depts") or []), "t": list(o.get("titles") or [])}
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(680px,94vw);gap:14px"):
            ui.label(f"{o['name']} — 부서 · 직책").style("font-family:var(--font-heading);font-weight:600;font-size:20px")
            ui.label("항목을 입력하고 Enter 또는 쉼표(,)로 추가합니다. 칩의 ✕ 로 삭제합니다. 여러 개를 한꺼번에 붙여 넣어도 됩니다. "
                     "‘저장’을 눌러야 반영됩니다.").classes("text-muted").style("font-size:12px")

            def section(key: str, label: str) -> None:
                with ui.column().classes("w-full gap-2"):
                    head = ui.label("").style("font-weight:700;font-size:14px")
                    chips = ui.row().classes("w-full gap-1").style("min-height:34px;max-height:160px;overflow:auto;padding:6px;border:1px solid var(--color-divider);border-radius:8px")
                    inp = ui.input(placeholder=f"{label} 추가 — 예: 1병동, 2병동").props("dense outlined").classes("w-full")

                    def draw() -> None:
                        head.set_text(f"{label} {len(data[key])}개")
                        chips.clear()
                        with chips:
                            if not data[key]:
                                ui.label(f"등록된 {label}이 없습니다.").classes("text-muted").style("font-size:12px;padding:4px")
                            for x in data[key]:
                                ui.chip(x, removable=True, color=None).props("dense outline").on("remove", lambda _, x=x: remove(x))

                    def remove(x: str) -> None:
                        if x in data[key]:
                            data[key].remove(x)
                        draw()

                    def add() -> None:
                        have = {s.lower() for s in data[key]}
                        for x in _split(inp.value or ""):
                            if x.lower() not in have:
                                data[key].append(x)
                                have.add(x.lower())
                        inp.set_value("")
                        draw()
                    inp.on("keydown.enter", add)
                    inp.on("blur", lambda: add() if (inp.value or "").strip() else None)
                    inp.on_value_change(lambda e: add() if e.value and e.value.endswith(",") else None)
                    draw()
            section("d", "부서")
            section("t", "직책")

            def ok() -> None:
                orgs = store.orgs(fresh=True)
                for x in orgs:
                    if x["id"] == o["id"]:
                        x["depts"], x["titles"] = list(data["d"]), list(data["t"])
                save_orgs(orgs)
                dlg.close()
                ui.notify("저장했습니다.", type="positive")
                refresh_all()
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")
                ui.button("저장", on_click=ok).props("no-caps unelevated color=primary")
        dlg.open()

    def toggle_org(o: dict) -> None:
        orgs = store.orgs(fresh=True)
        for x in orgs:
            if x["id"] == o["id"]:
                x["active"] = not x.get("active", True)
        save_orgs(orgs)
        refresh_all()

    def delete_org(o: dict) -> None:
        n = sum(1 for a in store.accounts(fresh=True) if a.get("orgId") == o["id"])
        if n:
            ui.notify(f"사용자 {n}명이 있는 기관은 삭제할 수 없습니다. 사용 중지를 사용하세요.", type="negative")
            return
        with ui.dialog() as dlg, ui.card().classes("kcm-card"):
            ui.label(f"‘{o['name']}’ 기관을 삭제할까요? 되돌릴 수 없습니다.")
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")

                def ok() -> None:
                    save_orgs([x for x in store.orgs(fresh=True) if x["id"] != o["id"]])
                    dlg.close()
                    refresh_all()
                ui.button("삭제", on_click=ok, color="red").props("no-caps")
        dlg.open()

    def on_dnd(e) -> None:
        a = e.args or {}
        if a.get("group") != "orgs" or not is_sys:
            return
        new = a.get("order") or []
        orgs = store.orgs(fresh=True)
        by_id = {o["id"]: o for o in orgs}
        ordered = [by_id[i] for i in new if i in by_id] + [o for o in orgs if o["id"] not in new]
        save_orgs(ordered)
        render_orgs()
    ui.on("dnd_reorder", on_dnd)

    # ───────────── 신규 사용자 등록 ─────────────
    def render_reg() -> None:
        reg_box.clear()
        orgs = my_orgs()
        if not orgs:
            return
        f = {"emp": "", "name": "", "org": orgs[0]["id"], "dept": None, "title": None, "mail": "", "role": "user",
             "nolimit": True, "from": "", "to": ""}
        org_map = {o["id"]: o for o in orgs}
        with reg_box:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("신규 사용자 등록").classes("kcm-sec-h")
                ui.label("Gmail 주소로 로그인합니다. 등록 후 목록의 ‘편집’에서 비밀번호를 지정하거나 초기화해 전달하세요.").classes("text-muted").style("font-size:11px")
            with ui.row().classes("w-full items-center gap-2").style("flex-wrap:wrap"):
                ui.input(placeholder="사번").props("dense outlined").classes("w-36").bind_value(f, "emp")
                ui.input(placeholder="이름").props("dense outlined").classes("w-36").bind_value(f, "name")
                org_sel = ui.select({o["id"]: o["name"] for o in orgs}, value=f["org"]).props("dense outlined").classes("w-56")
                dept_sel = ui.select(org_map[f["org"]].get("depts") or [], value=None, label="부서").props("dense outlined clearable").classes("w-40")
                title_sel = ui.select(org_map[f["org"]].get("titles") or [], value=None, label="직책").props("dense outlined clearable").classes("w-40")
                ui.input(placeholder="name@gmail.com").props("dense outlined").classes("grow").style("min-width:200px").bind_value(f, "mail")

                def org_changed(e) -> None:
                    f["org"] = e.value
                    dept_sel.set_options(org_map[e.value].get("depts") or [], value=None)
                    title_sel.set_options(org_map[e.value].get("titles") or [], value=None)
                org_sel.on_value_change(org_changed)
                dept_sel.on_value_change(lambda e: f.update(dept=e.value))
                title_sel.on_value_change(lambda e: f.update(title=e.value))
            with ui.row().classes("w-full items-center gap-4").style("flex-wrap:wrap"):
                ui.label("권한").classes("text-muted").style("font-size:12px")
                roles = {"user": "사용자", "orgadmin": "기관 관리자"}
                if is_sys:
                    roles["sysadmin"] = "시스템 관리자 (admin)"
                role_btns: dict[str, ui.element] = {}
                with ui.element("div").classes("kcm-seg"):
                    for k, lab in roles.items():
                        b = ui.element("button").classes("on" if k == f["role"] else "")
                        with b:
                            ui.label(lab)
                        role_btns[k] = b

                        def pick(_, k=k) -> None:
                            f["role"] = k
                            for kk, bb in role_btns.items():
                                bb.classes(add="on") if kk == k else bb.classes(remove="on")
                        b.on("click", pick)
                ui.label("유효기간").classes("text-muted").style("font-size:12px")
                d1 = ui.input(placeholder="YYYY-MM-DD").props("dense outlined type=date").classes("w-40").bind_value(f, "from")
                ui.label("~")
                d2 = ui.input(placeholder="YYYY-MM-DD").props("dense outlined type=date").classes("w-40").bind_value(f, "to")
                lim = ui.element("div").classes("kcm-chip ok").style("cursor:pointer;border:1px solid var(--color-accent)")
                with lim:
                    lim_lbl = ui.label("기간 제한 없음 ✓")

                def lim_toggle() -> None:
                    f["nolimit"] = not f["nolimit"]
                    lim_lbl.set_text("기간 제한 없음 ✓" if f["nolimit"] else "기간 제한 사용")
                    d1.set_enabled(not f["nolimit"])
                    d2.set_enabled(not f["nolimit"])
                lim.on("click", lim_toggle)
                d1.set_enabled(False)
                d2.set_enabled(False)
                ui.button("등록", on_click=lambda: register(f)).props("no-caps unelevated color=primary").classes("ml-auto")
            ui.label("사용자 · 검색 · 코드 생성 · 색인 · AI 코딩 · 이력 · 개인 코드집을 사용합니다. 기관 관리자는 소속 기관 사용자를 관리합니다."
                     if True else "").classes("text-muted").style("font-size:11px")

    def register(f: dict) -> None:
        mail = (f["mail"] or "").strip().lower()
        name = (f["name"] or "").strip()
        if not name or not is_gmail(mail):
            ui.notify("이름과 올바른 Gmail 주소(@gmail.com)를 입력하세요.", type="negative")
            return
        accs = store.accounts(fresh=True)
        if any(str(a["id"]).lower() == mail for a in accs):
            ui.notify("이미 등록된 Gmail입니다.", type="negative")
            return
        emp = (f["emp"] or "").strip()
        if emp and any(a.get("orgId") == f["org"] and str(a.get("empNo", "")).lower() == emp.lower() for a in accs):
            ui.notify("같은 기관에 이미 있는 사번입니다.", type="negative")
            return
        if not f["nolimit"] and f["from"] and f["to"] and f["from"] > f["to"]:
            ui.notify("유효기간의 시작일이 종료일보다 늦습니다.", type="negative")
            return
        accs.append({"id": mail, "name": name, "empNo": emp, "orgId": f["org"], "role": f["role"], "dept": f["dept"] or "",
                     "title": f["title"] or "", "active": True, "noLimit": bool(f["nolimit"]),
                     "from": "" if f["nolimit"] else f["from"], "to": "" if f["nolimit"] else f["to"], "last": "—",
                     "pwHash": "", "pwTemp": True})
        save_accounts(accs)
        ui.notify(f"{name}님을 등록했습니다. 목록의 ‘편집’에서 비밀번호를 지정하세요.", type="positive", timeout=6000)
        refresh_all()

    # ───────────── 사용자 목록 ─────────────
    def render_list() -> None:
        list_box.clear()
        orgs = my_orgs()
        all_orgs = store.orgs()
        org_name = {o["id"]: o["name"] for o in all_orgs}
        accs = my_accounts()
        rows = []
        for a in accs:
            st = acc_status(a, all_orgs)
            rows.append((a, st, _status_kind(st["label"])))
        counts = {k: sum(1 for r in rows if r[2] == k) for k in ("사용 중", "예약", "만료", "비활성")}
        q = (flt["q"] or "").lower()
        shown = [r for r in rows
                 if (not flt["org"] or r[0].get("orgId") == flt["org"])
                 and (not flt["status"] or r[2] == flt["status"])
                 and (not q or q in " ".join(str(r[0].get(k, "")) for k in ("empNo", "name", "id", "dept", "title")).lower())]
        with list_box:
            with ui.row().classes("w-full items-center gap-2").style("flex-wrap:wrap"):
                opts = {"": "전체 기관"} | {o["id"]: o["name"] for o in orgs}
                ui.select(opts, value=flt["org"], on_change=lambda e: (flt.update(org=e.value), render_list())).props("dense outlined").classes("w-52")
                ui.select({"": "전체 상태", "사용 중": "사용 중", "예약": "예약", "만료": "만료", "비활성": "비활성"}, value=flt["status"],
                          on_change=lambda e: (flt.update(status=e.value), render_list())).props("dense outlined").classes("w-40")
                s = ui.input(placeholder="사번 · 이름 · Gmail · 부서 · 직책 검색", value=flt["q"]).props("dense outlined clearable").classes("grow").style("min-width:200px")
                s.on("keydown.enter", lambda: (flt.update(q=s.value or ""), render_list()))
                s.on("blur", lambda: (flt.update(q=s.value or ""), render_list()) if (s.value or "") != flt["q"] else None)
                for k, n in counts.items():
                    ui.html(f'<span class="kcm-chip {"ok" if k == "사용 중" else ("warn" if k in ("예약", "만료") else "off")}">{k} {n}</span>')
                ui.label(f"{len(shown)}명 표시 · 관리 대상 {len(rows)}명").classes("text-muted").style("font-size:12px")
            with ui.element("div").style("overflow-x:auto;width:100%"):
                with ui.element("div").classes("kcm-urow head"):
                    for h in ("사번 · 이름", "소속기관 · 부서", "Gmail", "권한", "상태 · 유효기간", "활성", ""):
                        ui.label(h)
                if not shown:
                    ui.label("조건에 맞는 사용자가 없습니다.").classes("text-muted").style("padding:16px 8px")
                for a, st, kind in shown:
                    with ui.element("div").classes("kcm-urow"):
                        with ui.column().classes("gap-0"):
                            with ui.row().classes("items-baseline gap-1 no-wrap"):
                                ui.label(str(a.get("empNo", ""))).classes("text-muted mono").style("font-size:11px")
                                ui.label(a.get("name", "")).style("font-weight:700;font-size:15px")
                            ui.label("최근 접속 " + str(a.get("last") or "—")).classes("text-muted").style("font-size:11px")
                        with ui.column().classes("gap-0").style("min-width:0"):
                            ui.label(org_name.get(a.get("orgId"), "") + (f" · {a['dept']}" if a.get("dept") else "")
                                     + (f" · {a['title']}" if a.get("title") else "")).style("font-weight:600;font-size:14px")
                        ui.label(a["id"]).classes("mono").style("font-size:12px;overflow-wrap:anywhere")
                        role = a.get("role", "user")
                        ui.html(f'<span class="kcm-chip">{"admin · 전체" if role == "sysadmin" else ROLE_LABEL.get(role, role)}</span>')
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.html(f'<span class="kcm-chip {"ok" if st["ok"] else "warn"}">{kind}</span>')
                            if a.get("pwTemp"):
                                ui.html('<span class="kcm-chip warn">임시 PW</span>')
                            ui.label("제한 없음" if a.get("noLimit") or not (a.get("from") or a.get("to"))
                                     else f"{a.get('from') or ''} ~ {a.get('to') or ''}").classes("text-muted").style("font-size:11px")
                        sw = ui.switch(value=a.get("active", True)).props("dense")
                        sw.on_value_change(lambda e, a=a: set_active(a, e.value))
                        ui.button("편집", icon="edit", color=None, on_click=lambda _, a=a: edit_dialog(a)).props("unelevated no-caps dense").classes("kcm-act pri")

    def set_active(a: dict, v: bool) -> None:
        if a["id"] == me["id"] and not v:
            ui.notify("본인 계정은 비활성화할 수 없습니다.", type="negative")
            render_list()
            return
        accs = store.accounts(fresh=True)
        for x in accs:
            if x["id"] == a["id"]:
                x["active"] = bool(v)
        save_accounts(accs)
        render_list()

    def edit_dialog(a: dict) -> None:
        orgs = my_orgs()
        org_map = {o["id"]: o for o in store.orgs(fresh=True)}
        f = {"name": a.get("name", ""), "emp": str(a.get("empNo", "")), "org": a.get("orgId"), "dept": a.get("dept") or None,
             "title": a.get("title") or None, "role": a.get("role", "user"), "nolimit": bool(a.get("noLimit", True)),
             "from": a.get("from", ""), "to": a.get("to", ""), "pw": ""}
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(560px,94vw)"):
            ui.label(f"사용자 편집 — {a['id']}").style("font-family:var(--font-heading);font-weight:600;font-size:20px")
            with ui.row().classes("w-full gap-2 no-wrap"):
                ui.input("이름").props("dense outlined").classes("w-1/2").bind_value(f, "name")
                ui.input("사번").props("dense outlined").classes("w-1/2").bind_value(f, "emp")
            org_sel = ui.select({o["id"]: o["name"] for o in orgs}, value=f["org"], label="소속기관").props("dense outlined").classes("w-full")
            with ui.row().classes("w-full gap-2 no-wrap"):
                dept_sel = ui.select(org_map.get(f["org"], {}).get("depts") or [], value=f["dept"], label="부서").props("dense outlined clearable").classes("w-1/2")
                title_sel = ui.select(org_map.get(f["org"], {}).get("titles") or [], value=f["title"], label="직책").props("dense outlined clearable").classes("w-1/2")

            def org_changed(e) -> None:
                f["org"] = e.value
                dept_sel.set_options(org_map.get(e.value, {}).get("depts") or [], value=None)
                title_sel.set_options(org_map.get(e.value, {}).get("titles") or [], value=None)
            org_sel.on_value_change(org_changed)
            dept_sel.on_value_change(lambda e: f.update(dept=e.value))
            title_sel.on_value_change(lambda e: f.update(title=e.value))
            roles = {"user": "사용자", "orgadmin": "기관 관리자"} | ({"sysadmin": "시스템 관리자 (admin)"} if is_sys else {})
            ui.select(roles, value=f["role"], label="권한").props("dense outlined").classes("w-full").bind_value(f, "role")
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.checkbox("기간 제한 없음").bind_value(f, "nolimit")
                ui.input().props("dense outlined type=date").classes("grow").bind_value(f, "from")
                ui.label("~")
                ui.input().props("dense outlined type=date").classes("grow").bind_value(f, "to")
            ui.separator()
            ui.label("비밀번호").classes("kcm-sec-h")
            ui.label("지정됨" if a.get("pwHash") else "미지정 — 아래에서 숫자 4자리를 지정하세요.").classes("text-muted").style("font-size:12px")
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                pw_in = ui.input(placeholder="숫자 4자리").props("dense outlined maxlength=4").classes("grow").bind_value(f, "pw")

                def set_pw() -> None:
                    p = (f["pw"] or "").strip()
                    if not re.fullmatch(r"\d{4}", p):
                        ui.notify("비밀번호는 숫자 4자리입니다.", type="negative")
                        return
                    _write_pw(a["id"], p, temp=False)
                    ui.notify("비밀번호를 지정했습니다.", type="positive")
                    pw_in.set_value("")

                def reset_pw() -> None:
                    p = f"{random.randint(0, 9999):04d}"
                    _write_pw(a["id"], p, temp=True)
                    ui.notify(f"임시 비밀번호: {p} (첫 로그인 후 변경하게 됩니다)", type="positive", timeout=20000, close_button=True)
                ui.button("지정", on_click=set_pw).props("no-caps outline dense")
                ui.button("초기화", on_click=reset_pw).props("no-caps outline dense")

            def save() -> None:
                if not (f["name"] or "").strip():
                    ui.notify("이름을 입력하세요.", type="negative")
                    return
                if a["id"] == me["id"] and f["role"] != a.get("role"):
                    ui.notify("본인의 권한은 바꿀 수 없습니다.", type="negative")
                    return
                accs = store.accounts(fresh=True)
                emp = (f["emp"] or "").strip()
                if emp and any(x["id"] != a["id"] and x.get("orgId") == f["org"] and str(x.get("empNo", "")).lower() == emp.lower() for x in accs):
                    ui.notify("같은 기관에 이미 있는 사번입니다.", type="negative")
                    return
                for x in accs:
                    if x["id"] == a["id"]:
                        x.update({"name": f["name"].strip(), "empNo": emp, "orgId": f["org"], "dept": f["dept"] or "", "title": f["title"] or "",
                                  "role": f["role"], "noLimit": bool(f["nolimit"]),
                                  "from": "" if f["nolimit"] else f["from"], "to": "" if f["nolimit"] else f["to"]})
                save_accounts(accs)
                dlg.close()
                ui.notify("저장했습니다.", type="positive")
                render_list()
                render_orgs()

            def delete() -> None:
                if a["id"] == me["id"]:
                    ui.notify("본인 계정은 삭제할 수 없습니다.", type="negative")
                    return
                with ui.dialog() as d2, ui.card().classes("kcm-card"):
                    ui.label(f"{a.get('name', '')} ({a['id']}) 계정을 삭제할까요? 되돌릴 수 없습니다.")
                    with ui.row().classes("w-full justify-end"):
                        ui.button("취소", on_click=d2.close).props("flat no-caps")

                        def ok() -> None:
                            save_accounts([x for x in store.accounts(fresh=True) if x["id"] != a["id"]])
                            d2.close()
                            dlg.close()
                            refresh_all()
                        ui.button("삭제", on_click=ok, color="red").props("no-caps")
                d2.open()
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("계정 삭제", on_click=delete).props("flat no-caps").style("color:var(--bad)")
                with ui.row().classes("gap-2"):
                    ui.button("닫기", on_click=dlg.close).props("flat no-caps")
                    ui.button("저장", on_click=save).props("no-caps unelevated color=primary")
        dlg.open()

    def _write_pw(acc_id: str, pw: str, temp: bool) -> None:
        accs = store.accounts(fresh=True)
        for x in accs:
            if x["id"] == acc_id:
                x.update({"pwHash2": hash_strong(pw), "pwTemp": True})      # 관리자가 정해 준 비밀번호는 임시 — 첫 로그인 때 본인이 바꾼다
                x.pop("pwHash", None)
                x.pop("demoPw", None)                                        # 평문 임시 비밀번호는 DB에 남기지 않는다
        save_accounts(accs)
        render_list()

    # ───────────── Google 로그인 설정 ─────────────
    def render_google() -> None:
        google_box.clear()
        cfg = store.get("global", "authCfg", {}) or {}
        with google_box:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Google 로그인 설정").classes("kcm-sec-h")
                ui.label(f"Google 로그인 {'사용' if cfg.get('googleClientId') else '미설정'} · 문자 OTP 미설정 · 비밀번호 로그인 사용") \
                    .classes("text-muted").style("font-size:11px")
            ui.label("Google OAuth 클라이언트 ID (선택 — 비밀번호 대신 Google 계정으로 로그인)").classes("text-muted").style("font-size:12px")
            cid = ui.input(value=cfg.get("googleClientId", ""), placeholder="0000000000-xxxxxxxx.apps.googleusercontent.com") \
                .props("dense outlined").classes("w-full mono")

            def save() -> None:
                store.put("global", "authCfg", {**cfg, "googleClientId": (cid.value or "").strip()}, by=_by())
                ui.notify("설정을 저장했습니다.", type="positive")
                render_google()

            def reset_browser() -> None:
                app.storage.user.clear()
                ui.navigate.to("/login")
            with ui.row().classes("items-center gap-3"):
                ui.button("설정 저장", on_click=save).props("no-caps unelevated color=primary")
                ui.button("이 브라우저의 저장 데이터 초기화", on_click=reset_browser).props("no-caps flat")

    refresh_all()
    if is_sys:
        render_google()
