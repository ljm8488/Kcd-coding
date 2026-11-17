"""6단계 — 비밀번호 변경 (임시 비밀번호로 처음 로그인하면 이 화면으로 먼저 이동한다)"""
from __future__ import annotations

import datetime as dt

from nicegui import app, ui

from . import store
from .main import layout, require_login, user
from .security import hash_strong, password_problem, pw_matches


def _record(uid: str) -> dict | None:
    if uid == "admin":
        return dict(store.sys_admin(fresh=True) or {})
    return next((dict(a) for a in store.accounts(fresh=True) if a.get("id") == uid), None)


def save_password(uid: str, pw: str, temp: bool = False) -> None:
    """새 비밀번호를 안전한 해시(scrypt)로 저장하고, 예전 해시·평문 임시 비밀번호는 지운다."""
    new = hash_strong(pw)
    if uid == "admin":
        rec = dict(store.sys_admin(fresh=True) or {})
        rec.update({"pwHash2": new, "pwTemp": temp, "last": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
        rec.pop("pwHash", None)
        store.put("global", "sysAdmin", rec, by=uid)
        return
    accs = store.accounts(fresh=True)
    for a in accs:
        if a.get("id") == uid:
            a.update({"pwHash2": new, "pwTemp": temp})
            a.pop("pwHash", None)
            a.pop("demoPw", None)
    store.put("global", "accounts", accs, by=uid)


@ui.page("/password")
def password_page() -> None:
    if not require_login():
        return
    layout("password")
    me = user()
    forced = bool(me.get("tempPw"))
    with ui.column().classes("w-full gap-4").style("max-width:520px"):
        ui.label("비밀번호 변경").classes("kcm-h1")
        if forced:
            ui.html('<div style="border:1px solid var(--warn);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--warn)">'
                    "임시 비밀번호로 로그인했습니다. <b>새 비밀번호를 정해야 다른 화면을 쓸 수 있습니다.</b></div>")
        with ui.column().classes("kcm-card w-full gap-3"):
            cur = ui.input("현재 비밀번호", password=True, password_toggle_button=True).props("dense outlined").classes("w-full")
            new = ui.input("새 비밀번호", password=True, password_toggle_button=True).props("dense outlined").classes("w-full")
            new2 = ui.input("새 비밀번호 확인", password=True, password_toggle_button=True).props("dense outlined").classes("w-full")
            ui.label("4자 이상 8자 이내, 숫자만 또는 문자(영문·한글)만 쓸 수 있습니다. 숫자와 문자를 섞거나 특수문자·공백은 쓸 수 없고, "
                     "1111·1234처럼 쉬운 비밀번호는 피하세요.").classes("text-muted").style("font-size:12px")
            msg = ui.label("").style("font-size:13px;color:var(--bad)")

            def submit() -> None:
                rec = _record(me["id"])
                if not rec:
                    msg.set_text("계정 정보를 찾지 못했습니다.")
                    return
                ok, _ = pw_matches(rec, me["id"], cur.value or "")
                if not ok:
                    msg.set_text("현재 비밀번호가 올바르지 않습니다.")
                    return
                if new.value != new2.value:
                    msg.set_text("새 비밀번호 확인이 일치하지 않습니다.")
                    return
                if new.value == cur.value:
                    msg.set_text("현재와 다른 비밀번호를 정하세요.")
                    return
                prob = password_problem(new.value or "")
                if prob:
                    msg.set_text(prob)
                    return
                save_password(me["id"], new.value, temp=False)
                u = dict(user())
                u["tempPw"] = False
                app.storage.user["user"] = u
                ui.notify("비밀번호를 바꿨습니다.", type="positive")
                ui.navigate.to("/search")
            ui.button("비밀번호 변경", on_click=submit).props("no-caps unelevated color=primary").classes("w-full").style("min-height:44px")
            new2.on("keydown.enter", submit)
