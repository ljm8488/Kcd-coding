"""심사 코딩마스터 (Python / NiceGUI) — 1단계: 로그인 · 검색 · 사용자 관리 · KCD 데이터"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import random
from pathlib import Path

from nicegui import app, ui

from . import store
from .search import KcdIndex
from .security import ROLE_LABEL, acc_status, authenticate, is_gmail, pw_key

_index: dict = {"at": None, "idx": None}


def get_index(fresh: bool = False) -> KcdIndex:
    m = store.kcd_master(fresh)
    key = (m.get("at"), len(m.get("rows", [])))
    if fresh or _index["at"] != key or _index["idx"] is None:
        _index["idx"] = KcdIndex(m.get("rows", []))
        _index["at"] = key
    return _index["idx"]


def user() -> dict | None:
    return app.storage.user.get("user")


def require_login(roles: tuple[str, ...] | None = None) -> bool:
    u = user()
    if not u:
        ui.navigate.to("/login")
        return False
    if roles and u["role"] not in roles:
        ui.label("접근 권한이 없습니다.").classes("text-red-600 p-6")
        return False
    return True


THEME_CSS = """
:root{--bg:#14181c;--surface:#1a1f24;--surface2:#20262c;--text:#e3e7eb;--muted:#8794a0;
--accent:#6a91b7;--accent-hi:#a9c6e3;--accent-bg:#253546;--divider:rgba(255,255,255,.11)}
body,.q-page,.nicegui-content{background:var(--bg)!important;color:var(--text)!important;
 font-family:'Pretendard','Malgun Gothic',system-ui,sans-serif}
.nicegui-content{padding:0!important}
.kcm-header{background:var(--surface);border-bottom:1px solid var(--divider);padding:0 20px;min-height:56px}
.kcm-logo{width:30px;height:30px;border-radius:8px;background:var(--accent);color:#fff;display:grid;place-items:center;font-weight:700}
.kcm-side{width:236px;flex:none;position:sticky;top:76px;align-self:flex-start;margin:24px 0 24px 20px;
 background:var(--surface);border:1px solid var(--divider);border-radius:12px;padding:10px;
 box-shadow:0 1px 2px rgba(0,0,0,.3),0 4px 14px rgba(0,0,0,.25)}
.kcm-nav{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;color:var(--text);
 text-decoration:none;font-size:14px}
.kcm-nav:hover{background:var(--surface2)}
.kcm-nav.active{background:var(--accent-bg);color:var(--accent-hi);font-weight:600}
.kcm-main{flex:1 1 0;min-width:0;padding:24px 24px 24px 20px}
.kcm-card{background:var(--surface);border:1px solid var(--divider);border-radius:12px;padding:20px}
.q-field__control,.q-table__container,.q-table thead,.q-table tbody td{background:var(--surface)!important;color:var(--text)!important}
.q-field__label,.q-table th{color:var(--muted)!important}
.q-table__bottom,.q-table__bottom *{color:var(--muted)!important}
.q-btn.bg-primary{background:var(--accent)!important}
.text-muted{color:var(--muted)}
"""

NAV = [("search", "검색 · 코드 생성", "search", "/search"),
       ("cond", "조건 설정", "tune", "/cond"),
       ("index", "3권 색인 검색", "menu_book", "/index"),
       ("nlp", "AI 자동 코딩", "auto_awesome", "/nlp"),
       ("history", "코딩 이력", "history", "/history"),
       ("favs", "개인 코드집", "star", "/favs"),
       ("dash", "대시보드", "bar_chart", "/dash"),
       ("users", "사용자 관리", "group", "/users"),
       ("kcd", "KCD 데이터", "storage", "/kcd")]
NAV_ROLES = {"dash": ("sysadmin", "orgadmin"), "users": ("sysadmin", "orgadmin"), "kcd": ("sysadmin",)}
TITLES = {k: t for k, t, _, _ in NAV}


def apply_theme() -> None:
    ui.dark_mode(True)
    ui.add_css(THEME_CSS)


def layout(active: str) -> None:
    """원본과 같은 구성 — 상단 헤더(로고·위치) + 왼쪽 메뉴 카드 + 본문. 이후 요소는 본문에 들어간다."""
    u = user()
    apply_theme()
    with ui.row().classes("kcm-header w-full items-center justify-between no-wrap").style("position:sticky;top:0;z-index:30"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label("심").classes("kcm-logo")
            ui.label("심사 코딩마스터").classes("text-xl font-bold")
            ui.label("/").classes("text-muted")
            ui.label(TITLES.get(active, "")).classes("text-sm")
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label(f"{u['name']} · {ROLE_LABEL.get(u['role'], u['role'])}").classes("text-sm text-muted")
            ui.button("로그아웃", on_click=logout).props("flat dense no-caps").style("color:var(--accent-hi)")
    row = ui.row().classes("w-full no-wrap items-start gap-0")
    with row:
        with ui.element("aside").classes("kcm-side"):
            for key, label, icon, href in NAV:
                if key in NAV_ROLES and u["role"] not in NAV_ROLES[key]:
                    continue
                with ui.link(target=href).classes("kcm-nav" + (" active" if key == active else "")).style("text-decoration:none"):
                    ui.icon(icon).classes("text-lg")
                    ui.label(label)
    main = ui.column().classes("kcm-main gap-3")
    main.move(row)
    main.__enter__()


def coming_soon(key: str, desc: str) -> None:
    with ui.column().classes("w-full max-w-4xl gap-3"):
        ui.label(TITLES[key]).classes("text-xl font-bold")
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("이 화면은 파이썬 버전에서 순차적으로 만들고 있습니다.").classes("font-semibold")
            ui.label(desc).classes("text-muted text-sm")
            ui.link("기존 웹앱에서 사용하기", "https://ljm8488.github.io/Kcd-coding/", new_tab=True).style("color:var(--accent-hi)")


def logout() -> None:
    app.storage.user.pop("user", None)
    ui.navigate.to("/login")


# ───────────────────────── 로그인 ─────────────────────────
@ui.page("/login")
def login_page() -> None:
    if user():
        ui.navigate.to("/search")
        return
    orgs = [o for o in store.orgs() if o.get("active", True)]
    org_opts = {o["id"]: o["name"] for o in orgs}
    state = {"mode": "emp", "org": next(iter(org_opts), ""), "id": "", "pw": ""}

    apply_theme()
    with ui.column().classes("kcm-card absolute-center w-96 gap-3"):
        ui.label("심사 코딩마스터").classes("text-2xl font-bold")
        ui.label("소속기관을 선택하고 사번 또는 Gmail로 로그인하십시오.").classes("text-sm text-muted")
        if not store.configured():
            ui.label("⚠ SUPABASE_URL / SUPABASE_KEY 설정이 없어 계정을 불러올 수 없습니다.").classes("text-red-600 text-sm")
        org_sel = ui.select(org_opts, label="소속기관", value=state["org"]).classes("w-full")
        org_sel.bind_value(state, "org")
        mode = ui.toggle({"emp": "사번", "gmail": "Gmail", "admin": "시스템 관리자"}, value="emp").classes("w-full")
        mode.bind_value(state, "mode")
        ident = ui.input("사번 / Gmail / admin").classes("w-full").bind_value(state, "id")
        pw = ui.input("비밀번호", password=True, password_toggle_button=True).classes("w-full").bind_value(state, "pw")
        err = ui.label("").classes("text-red-600 text-sm")

        def do_login() -> None:
            accounts = store.accounts(fresh=True)
            all_orgs = store.orgs(fresh=True)
            u, msg = authenticate(state["mode"], state["id"], state["pw"], state["org"],
                                  accounts, all_orgs, store.sys_admin(fresh=True))
            if not u:
                err.set_text(msg)
                return
            u["tempPw"] = u.pop("pwTemp", False)
            app.storage.user["user"] = u
            ui.navigate.to("/search")

        pw.on("keydown.enter", do_login)
        ui.button("로그인", on_click=do_login).classes("w-full")


@ui.page("/")
def index_page() -> None:
    ui.navigate.to("/search" if user() else "/login")


# ───────────────────────── 검색 ─────────────────────────
@ui.page("/search")
def search_page() -> None:
    if not require_login():
        return
    layout("search")
    idx = get_index()
    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-3"):
        ui.label("검색 · 코드 생성").classes("text-xl font-bold")
        ui.label(f"KCD 상병 {len(idx):,}건 · 코드(예: I10, E11.9), 한글명, 영문명으로 검색합니다.").classes("text-sm text-gray-500")
        box = ui.input(placeholder="질병명 또는 코드를 입력하세요").props("outlined clearable autofocus").classes("w-full")
        info = ui.label("").classes("text-sm text-gray-600")
        table = ui.table(columns=[
            {"name": "code", "label": "코드", "field": "code", "align": "left", "sortable": True},
            {"name": "ko", "label": "한글명", "field": "ko", "align": "left"},
            {"name": "en", "label": "영문명", "field": "en", "align": "left"},
        ], rows=[], row_key="code", pagination=25, selection="single").classes("w-full")

        def picked() -> dict | None:
            if not table.selected:
                ui.notify("표에서 코드를 먼저 선택하세요.", type="warning")
                return None
            return table.selected[0]

        def to_favs() -> None:
            from .phase3 import add_fav
            s = picked()
            if s:
                ui.notify("코드집에 담았습니다." if add_fav(s["code"], s["ko"]) else "이미 코드집에 있습니다.")

        def to_history() -> None:
            from .phase3 import add_history
            s = picked()
            if s:
                add_history(box.value or "", s["code"], s["ko"])
                ui.notify("이력에 기록했습니다.", type="positive")

        with ui.row().classes("gap-2"):
            ui.button("코드집에 담기", icon="star", on_click=to_favs).props("no-caps outline")
            ui.button("이력에 기록", icon="history", on_click=to_history).props("no-caps outline")

        def run() -> None:
            q = box.value or ""
            hits = idx.search(q)
            table.rows = [{"code": r.code, "ko": r.ko, "en": r.en} for r in hits]
            table.update()
            info.set_text(f"{len(hits)}건" + (" (최대 200건 표시)" if len(hits) >= 200 else "") if q.strip() else "")

        box.on("update:model-value", run, throttle=0.3)
        box.on("keydown.enter", run)


# ───────────────────────── 사용자 관리 ─────────────────────────
def _save_accounts(accounts: list[dict]) -> None:
    store.put("global", "accounts", accounts, by=user()["id"])


@ui.page("/users")
def users_page() -> None:
    if not require_login(("sysadmin", "orgadmin")):
        return
    layout("users")
    me = user()
    orgs = store.orgs()
    org_names = {o["id"]: o["name"] for o in orgs}

    @ui.refreshable
    def listing() -> None:
        accounts = store.accounts(fresh=True)
        shown = [a for a in accounts if me["role"] == "sysadmin" or a.get("orgId") == me["orgId"]]
        rows = []
        for a in shown:
            st = acc_status(a, orgs)
            rows.append({"id": a["id"], "name": a.get("name", ""), "empNo": a.get("empNo", ""),
                         "org": org_names.get(a.get("orgId"), a.get("orgId", "")),
                         "role": ROLE_LABEL.get(a.get("role"), a.get("role", "")),
                         "dept": a.get("dept", ""), "title": a.get("title", ""),
                         "status": st["label"], "pw": "지정됨" if a.get("pwHash") else "미지정"})
        t = ui.table(columns=[
            {"name": "name", "label": "이름", "field": "name", "align": "left"},
            {"name": "id", "label": "Gmail", "field": "id", "align": "left"},
            {"name": "empNo", "label": "사번", "field": "empNo", "align": "left"},
            {"name": "org", "label": "기관", "field": "org", "align": "left"},
            {"name": "role", "label": "권한", "field": "role", "align": "left"},
            {"name": "dept", "label": "부서", "field": "dept", "align": "left"},
            {"name": "title", "label": "직위", "field": "title", "align": "left"},
            {"name": "status", "label": "상태", "field": "status", "align": "left"},
            {"name": "pw", "label": "비밀번호", "field": "pw", "align": "left"},
        ], rows=rows, row_key="id", selection="single", pagination=20).classes("w-full")

        def selected() -> dict | None:
            return (t.selected or [None])[0]

        def toggle_active() -> None:
            s = selected()
            if not s:
                ui.notify("사용자를 선택하세요.", type="warning")
                return
            if s["id"] == me["id"]:
                ui.notify("본인 계정은 비활성화할 수 없습니다.", type="negative")
                return
            accs = store.accounts(fresh=True)
            for a in accs:
                if a["id"] == s["id"]:
                    a["active"] = not a.get("active", True)
            _save_accounts(accs)
            ui.notify("상태를 변경했습니다.")
            listing.refresh()

        def reset_pw() -> None:
            s = selected()
            if not s:
                ui.notify("사용자를 선택하세요.", type="warning")
                return
            temp = f"{random.randint(0, 9999):04d}"
            accs = store.accounts(fresh=True)
            for a in accs:
                if a["id"] == s["id"]:
                    a.update({"pwHash": pw_key(a["id"], temp), "pwTemp": True, "demoPw": temp})
            _save_accounts(accs)
            ui.notify(f"{s['name']} 임시 비밀번호: {temp} (첫 로그인 후 변경하게 됩니다)", type="positive", timeout=15000, close_button=True)
            listing.refresh()

        def delete() -> None:
            s = selected()
            if not s:
                ui.notify("사용자를 선택하세요.", type="warning")
                return
            if s["id"] == me["id"]:
                ui.notify("본인 계정은 삭제할 수 없습니다.", type="negative")
                return
            with ui.dialog() as dlg, ui.card():
                ui.label(f"{s['name']} ({s['id']}) 계정을 삭제할까요? 되돌릴 수 없습니다.")
                with ui.row():
                    ui.button("취소", on_click=dlg.close).props("flat")

                    def ok() -> None:
                        _save_accounts([a for a in store.accounts(fresh=True) if a["id"] != s["id"]])
                        dlg.close()
                        listing.refresh()
                    ui.button("삭제", on_click=ok, color="red")
            dlg.open()

        with ui.row().classes("gap-2"):
            ui.button("선택 사용자 활성/비활성", on_click=toggle_active)
            ui.button("비밀번호 초기화", on_click=reset_pw)
            ui.button("삭제", on_click=delete, color="red")

    def add_dialog() -> None:
        my_orgs = orgs if me["role"] == "sysadmin" else [o for o in orgs if o["id"] == me["orgId"]]
        with ui.dialog() as dlg, ui.card().classes("w-96"):
            ui.label("사용자 추가").classes("text-lg font-bold")
            org = ui.select({o["id"]: o["name"] for o in my_orgs}, label="기관", value=my_orgs[0]["id"] if my_orgs else None)
            name = ui.input("이름")
            gmail = ui.input("Gmail (로그인 ID)")
            emp = ui.input("사번")
            dept = ui.input("부서")
            title = ui.input("직위")
            roles = {"user": "사용자", "orgadmin": "기관 관리자"}
            if me["role"] == "sysadmin":
                roles["sysadmin"] = "시스템 관리자"
            role = ui.select(roles, label="권한", value="user")

            def save() -> None:
                gid = (gmail.value or "").strip().lower()
                if not name.value or not is_gmail(gid):
                    ui.notify("이름과 올바른 Gmail 주소를 입력하세요.", type="negative")
                    return
                accs = store.accounts(fresh=True)
                if any(a["id"].lower() == gid for a in accs):
                    ui.notify("이미 등록된 Gmail입니다.", type="negative")
                    return
                temp = f"{random.randint(0, 9999):04d}"
                accs.append({"id": gid, "name": name.value.strip(), "empNo": (emp.value or "").strip(),
                             "orgId": org.value, "role": role.value, "dept": dept.value or "",
                             "title": title.value or "", "active": True, "noLimit": True,
                             "from": "", "to": "", "last": "—",
                             "pwHash": pw_key(gid, temp), "pwTemp": True, "demoPw": temp})
                _save_accounts(accs)
                dlg.close()
                ui.notify(f"추가했습니다. 임시 비밀번호: {temp}", type="positive", timeout=15000, close_button=True)
                listing.refresh()

            with ui.row():
                ui.button("취소", on_click=dlg.close).props("flat")
                ui.button("저장", on_click=save)
        dlg.open()

    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-3"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("사용자 관리").classes("text-xl font-bold")
            ui.button("사용자 추가", on_click=add_dialog)
        listing()


# ───────────────────────── KCD 데이터 ─────────────────────────
def _parse_kcd(name: str, raw: bytes) -> list[list[str]]:
    def norm_code(x: str) -> str:
        return str(x or "").strip().upper()

    table: list[list[str]] = []
    if name.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        best: list[list[str]] = []
        for ws in wb.worksheets:
            t = [["" if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)]
            if len(t) > len(best):
                best = t
        table = best
    else:
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("파일 인코딩을 읽지 못했습니다 (UTF-8 또는 CP949 CSV).")
        table = list(csv.reader(io.StringIO(text)))
    ci = ko = en = sy = -1
    start = 0
    for i, row in enumerate(table[:30]):
        cells = [c.replace(" ", "") for c in row]
        c_i = next((j for j, c in enumerate(cells) if c.endswith("코드") or c.lower() == "code"), -1)
        k_i = next((j for j, c in enumerate(cells) if j != c_i and any(w in c for w in ("한글", "국문", "상병명", "질병명", "분류명", "명칭"))), -1)
        if c_i >= 0 and k_i >= 0:
            ci, ko = c_i, k_i
            en = next((j for j, c in enumerate(cells) if "영문" in c or c.lower() == "english"), -1)
            sy = next((j for j, c in enumerate(cells) if "동의어" in c or "별칭" in c or "약어" in c), -1)
            start = i + 1
            break
    if ci < 0:
        ci, ko, start = 0, 1, 0
    rows, seen = [], set()
    for r in table[start:]:
        if len(r) <= max(ci, ko):
            continue
        code, kname = norm_code(r[ci]), str(r[ko]).strip()
        if not code or not kname or code in seen or not code[0].isalpha():
            continue
        seen.add(code)
        rows.append([code, kname, str(r[en]).strip() if 0 <= en < len(r) else "",
                     "|".join(x.strip() for x in str(r[sy]).replace(";", ",").split(",") if x.strip()) if 0 <= sy < len(r) else ""])
    if len(rows) < 10:
        raise ValueError("코드 · 한글명 열을 찾지 못했습니다. 첫 행에 '코드', '한글명' 머리글이 있는지 확인하세요.")
    return rows


@ui.page("/kcd")
def kcd_page() -> None:
    if not require_login(("sysadmin",)):
        return
    layout("kcd")
    m = store.kcd_master(fresh=True)
    with ui.column().classes("w-full max-w-3xl mx-auto p-4 gap-3"):
        ui.label("KCD 데이터").classes("text-xl font-bold")
        ui.label(f"현재: {m.get('name') or '(없음)'} · {len(m.get('rows', [])):,}건 · 적재 {m.get('at', '')}")
        ui.label("CSV(UTF-8/CP949) 또는 XLSX 파일을 올리면 모든 사용자에게 적용됩니다. 첫 행에 '코드', '한글명' 머리글이 필요합니다.").classes("text-sm text-gray-500")
        status = ui.label("")

        async def on_upload(e) -> None:
            try:
                f = getattr(e, "file", None)
                name = f.name if f else e.name
                raw = await f.read() if f else e.content.read()
                rows = _parse_kcd(name, raw)
                data = {"name": name, "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "by": user()["id"], "rows": rows}
                store.put("global", "kcdMaster", data, by=user()["id"])
                get_index(fresh=True)
                status.set_text(f"적재 완료 — {len(rows):,}건")
                ui.notify(f"KCD {len(rows):,}건을 적재했습니다.", type="positive")
            except Exception as ex:  # noqa: BLE001
                status.set_text(f"적재 실패 — {ex}")
                ui.notify(str(ex), type="negative")

        ui.upload(on_upload=on_upload, auto_upload=True, label="파일 선택").props("accept=.csv,.xlsx,.xlsm").classes("w-full")


PLACEHOLDERS: dict[str, str] = {}  # 모든 화면 구현 완료


def _make_placeholder(key: str) -> None:
    @ui.page(f"/{key}")
    def _page() -> None:
        if not require_login(NAV_ROLES.get(key)):
            return
        layout(key)
        coming_soon(key, PLACEHOLDERS[key])


for _k in PLACEHOLDERS:
    _make_placeholder(_k)

from . import phase2, phase3  # noqa: E402,F401  (2단계: 조건·색인·AI / 3단계: 이력·코드집·대시보드)


def run() -> None:
    port =int(os.environ.get("PORT", "8080"))
    ui.run(title="심사 코딩마스터", host="0.0.0.0", port=port, reload=False, show=False,
           storage_secret=os.environ.get("STORAGE_SECRET", "change-me-in-production"), language="ko-KR")
