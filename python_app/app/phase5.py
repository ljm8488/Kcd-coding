"""5단계 화면 — 사용자 관리 (기관 관리 · 신규 사용자 등록 · 사용자 목록 · Google 로그인 설정)"""
from __future__ import annotations

import random
import re

from nicegui import app, ui

from . import store
from .main import layout, require_login, user
from .security import ROLE_LABEL, acc_status, is_gmail, pw_key

CSS = """
.kcm-chip{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:12px;background:var(--a100);color:var(--a800);white-space:nowrap}
.kcm-chip.warn{background:transparent;border:1px solid var(--warn);color:var(--warn)}
.kcm-chip.off{background:var(--n200);color:var(--n700)}
.kcm-chip.ok{background:var(--a100);color:var(--a800)}
.kcm-org{display:grid;grid-template-columns:22px auto minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--color-divider)}
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
    def render_orgs() -> None:
        orgs_box.clear()
        orgs = my_orgs()
        accs = store.accounts()
        with orgs_box:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("기관 관리" if is_sys else "소속 기관").classes("kcm-sec-h")
                ui.label("왼쪽 손잡이를 끌어 기관 순서를 바꿉니다. ‘부서 · 직책’을 눌러 기관별 부서와 직책을 추가·수정·삭제합니다. "
                         "사용을 중지한 기관의 사용자는 로그인할 수 없습니다." if is_sys else
                         "‘부서 · 직책’을 눌러 기관의 부서와 직책을 추가·수정·삭제합니다.").classes("text-muted").style("font-size:11px;max-width:640px")
            for o in orgs:
                n = sum(1 for a in accs if a.get("orgId") == o["id"])
                active = o.get("active", True)
                with ui.element("div").classes("kcm-org").props(f'data-dnd="orgs" data-key="{o["id"]}"'):
                    ui.label("⋮⋮").classes("kcm-grip").props(f'draggable="{"true" if is_sys else "false"}"').style(
                        "cursor:grab;font-size:18px" if is_sys else "opacity:.3")
                    pill = ui.element("div").classes("kcm-pill" + ("" if active else " off")).style("" if active else "opacity:.55")
                    with pill:
                        ui.label(o["name"])
                    if is_sys:
                        pill.on("click", lambda _, o=o: rename_dialog(o))
                    with ui.column().classes("gap-0").style("min-width:0;font-size:12px"):
                        d, t = o.get("depts") or [], o.get("titles") or []
                        ui.label(f"부서 {len(d)}  " + ", ".join(d)).style("font-size:12px")
                        ui.label(f"직책 {len(t)}  " + ", ".join(t)).style("font-size:12px")
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.label(f"사용자 {n}명").classes("text-muted").style("font-size:12px;white-space:nowrap")
                        ui.button("부서 · 직책", on_click=lambda _, o=o: dept_dialog(o)).props("outline dense no-caps size=sm")
                        if is_sys:
                            ui.button("사용 중지" if active else "사용 재개", on_click=lambda _, o=o: toggle_org(o)).props("flat dense no-caps size=sm")
                            ui.button("삭제", on_click=lambda _, o=o: delete_org(o)).props("flat dense no-caps size=sm").style("color:var(--muted)")
            if is_sys:
                with ui.row().classes("w-full items-center no-wrap gap-2").style("padding-top:10px"):
                    new_name = ui.input(placeholder="새 기관명").props("dense outlined").classes("w-64")
                    new_depts = ui.input(placeholder="부서 — 예: 1병동, 2병동, 보험심사팀").props("dense outlined").classes("grow")
                    ui.button("기관 추가", on_click=lambda: add_org(new_name.value, new_depts.value)).props("no-caps unelevated color=primary")

    def add_org(name: str, depts: str) -> None:
        name = (name or "").strip()
        if not name:
            ui.notify("기관명을 입력하세요.", type="warning")
            return
        orgs = store.orgs(fresh=True)
        if any(o["name"] == name for o in orgs):
            ui.notify("이미 있는 기관명입니다.", type="negative")
            return
        orgs.append({"id": _new_id(), "name": name, "depts": _split(depts), "titles": [], "active": True})
        save_orgs(orgs)
        ui.notify(f"‘{name}’ 기관을 추가했습니다.", type="positive")
        refresh_all()

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
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")
                ui.button("저장", on_click=ok).props("no-caps unelevated color=primary")
        dlg.open()

    def dept_dialog(o: dict) -> None:
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(560px,94vw)"):
            ui.label(f"{o['name']} — 부서 · 직책").style("font-family:var(--font-heading);font-weight:600;font-size:20px")
            ui.label("쉼표 또는 줄바꿈으로 구분합니다. 저장하면 기관의 선택 목록에 바로 반영됩니다.").classes("text-muted").style("font-size:12px")
            d = ui.textarea("부서", value=", ".join(o.get("depts") or [])).props("outlined autogrow").classes("w-full")
            t = ui.textarea("직책", value=", ".join(o.get("titles") or [])).props("outlined autogrow").classes("w-full")

            def ok() -> None:
                orgs = store.orgs(fresh=True)
                for x in orgs:
                    if x["id"] == o["id"]:
                        x["depts"], x["titles"] = _split(d.value), _split(t.value)
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
                     "pwHash": "", "pwTemp": False})
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
                        ui.button("편집", on_click=lambda _, a=a: edit_dialog(a)).props("flat dense no-caps size=sm").style("color:var(--color-accent)")

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
                x.update({"pwHash": pw_key(acc_id, pw), "pwTemp": temp, "demoPw": pw})
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
