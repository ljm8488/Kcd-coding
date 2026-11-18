"""심사 코딩마스터 (Python / NiceGUI) — 1단계: 로그인 · 검색 · 사용자 관리 · KCD 데이터"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import random
import re
import time
from pathlib import Path

import httpx
from nicegui import run as nrun
from nicegui import app, ui

from . import kcd_sync, store
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
:root{
--color-bg:#f2f2f3;--color-text:#1d1f20;--color-accent:#5980a6;--color-divider:rgba(29,31,32,.16);
--surface:#ffffff;--surface-2:#f5f5f8;
--n100:#f5f5f8;--n200:#e7e7ea;--n300:#d4d4d7;--n600:#7a7a7d;--n700:#5d5d60;--n800:#424244;
--a100:#eef6ff;--a200:#d6ebff;--a300:#b5d9fd;--a400:#94bce3;--a600:#597ea3;--a700:#416180;--a800:#2c455d;--a900:#1d2d3d;
--elev-1:0 1px 2px rgba(29,31,32,.05),0 4px 14px rgba(29,31,32,.06);
--card-line:rgba(29,31,32,.09);
--warn:#b85c14;--ok:#2f7d4f;--bad:#c9302c;
--font-heading:'Barlow Condensed','Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',system-ui,sans-serif;
--font-body:'Barlow','Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',system-ui,sans-serif;
--muted:rgba(29,31,32,.55);--accent-hi:var(--a700);--accent-bg:var(--a100)}
body.body--dark{
--color-bg:#14181c;--color-text:#e3e7eb;--color-accent:#6a91b7;--color-divider:rgba(255,255,255,.11);
--surface:#1a1f24;--surface-2:#20262c;
--n100:#1f252b;--n200:#262d34;--n300:#333b43;--n600:#8794a0;--n700:#a6b0ba;--n800:#c3ccd5;
--a100:#1f2a35;--a200:#253546;--a300:#2e4862;--a400:#3b5a79;--a600:#6a91b7;--a700:#8fb2d4;--a800:#a9c6e3;--a900:#d6e6f5;
--elev-1:0 1px 2px rgba(0,0,0,.4),0 4px 14px rgba(0,0,0,.25);--card-line:#2c343c;
--warn:#e0a458;--ok:#7bc48a;--bad:#e57373;--muted:#8794a0;--accent-hi:#a9c6e3;--accent-bg:#253546}
/* 별칭은 라이트·다크 각각의 값을 따라가도록 body 에서 계산한다 (:root 에서 계산하면 다크모드에서도 라이트 값이 상속된다) */
body{--bg:var(--color-bg);--text:var(--color-text);--accent:var(--color-accent);--divider:var(--color-divider);--surface2:var(--surface-2)}
body,.q-page,.nicegui-content{background:var(--color-bg)!important;color:var(--color-text)!important;
 font-family:var(--font-body);font-size:15px;line-height:1.55}
body{--q-primary:var(--color-accent)}
.nicegui-content{padding:0!important}
::selection{background:color-mix(in srgb,var(--color-accent) 30%,transparent)}
.text-muted{color:var(--muted)}
.kicker{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-accent)}
.mono{font-family:ui-monospace,'SF Mono',Menlo,monospace}
.kcm-h1,.text-xl.font-bold{font-family:var(--font-heading);font-weight:600;font-size:32px;line-height:1.12;letter-spacing:-.015em}
.kcm-card{background:var(--surface);border:1px solid var(--card-line);border-radius:12px;box-shadow:var(--elev-1);padding:20px}
/* 헤더 · 경로 */
.kcm-header{position:sticky;top:0;z-index:30;background:var(--surface);border-bottom:1px solid var(--color-divider);
 box-shadow:0 1px 0 rgba(29,31,32,.04);width:100%}
.kcm-header-in{max-width:1560px;margin:0 auto;padding:0 20px;min-height:56px;display:flex;align-items:center;gap:8px;width:100%}
.kcm-logo{flex:none;width:30px;height:30px;border-radius:8px;background:var(--color-accent);color:#fff;display:grid;place-items:center;
 font-family:var(--font-heading);font-size:15px;box-shadow:0 1px 2px rgba(29,31,32,.15)}
.kcm-brand{font-family:var(--font-heading);font-size:20px;letter-spacing:.01em;color:var(--color-text);text-decoration:none}
.kcm-crumb{border-top:1px solid var(--color-divider)}
.kcm-crumb-in{max-width:1560px;margin:0 auto;padding:8px 20px;display:flex;gap:6px;align-items:center;font-size:12px;width:100%}
.kcm-crumb a{color:var(--n600);text-decoration:none}
/* 왼쪽 메뉴 */
.kcm-shell{flex:1;width:100%;max-width:1560px;margin:0 auto;display:flex;align-items:flex-start;flex-wrap:nowrap}
.kcm-side{flex:none;width:250px;position:sticky;top:96px;align-self:flex-start;margin:24px 0 24px 20px;
 background:var(--surface);box-shadow:var(--elev-1);border:1px solid var(--color-divider);border-radius:10px;
 height:calc(100vh / var(--z,1) - 148px);display:flex;flex-direction:column;overflow:hidden;padding:0}
.dnd-dragging{opacity:.4}.dnd-over{outline:2px dashed var(--color-accent);outline-offset:2px;border-radius:10px}
.kcm-grp-h{cursor:grab}.kcm-item{-webkit-user-drag:element}
.kcm-side-top{flex:1;min-height:0;overflow-y:auto;padding:10px 0 14px;display:grid;gap:12px;align-content:start}
.kcm-side-head{display:flex;align-items:center;margin:0 10px;padding-bottom:8px;border-bottom:1px solid var(--color-divider)}
.kcm-side-head b{flex:1;font-family:var(--font-heading);font-size:15px;letter-spacing:.04em;color:var(--n800)}
.kcm-grp{display:grid;gap:5px;padding:0 10px}
.kcm-grp-h{display:flex;align-items:center;gap:6px;padding:2px 6px 3px;cursor:pointer;user-select:none}
.kcm-item{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:40px;padding:0 10px 0 8px;border-radius:10px;
 font-size:14px;text-decoration:none;color:var(--color-text);transition:transform .14s,box-shadow .14s,background .14s}
.kcm-item:hover{background:var(--surface-2);transform:translateY(-1px)}
.kcm-item.active{background:var(--a100);box-shadow:inset 0 0 0 1px var(--a300);font-weight:600;color:var(--a800)}
.kcm-tile{flex:none;width:30px;height:30px;border-radius:8px;display:grid;place-items:center;background:var(--surface-2);color:var(--a800);
 box-shadow:inset 0 0 0 1px var(--color-divider)}
.kcm-item.active .kcm-tile{background:var(--color-accent);color:#fff;box-shadow:0 1px 2px rgba(29,31,32,.2)}
.kcm-sub{margin-left:20px;border-left:2px solid var(--a300);border-radius:6px;min-height:34px;font-size:13px}
.kcm-acct{flex:none;border-top:1px solid var(--color-divider);padding:12px;display:grid;gap:10px;background:var(--surface-2);
 box-shadow:0 -6px 12px -8px rgba(0,0,0,.25)}
.kcm-seg{display:inline-flex;overflow:hidden;border:1px solid var(--color-divider);border-radius:8px;background:var(--surface)}
.kcm-seg button{all:unset;cursor:pointer;padding:4px 10px;font-size:12px;border-radius:6px;white-space:nowrap}
.kcm-seg button.on{background:var(--color-accent);color:#fff}
.kcm-tag{display:inline-flex;align-items:center;font-size:11px;letter-spacing:.02em;padding:3px 10px;border-radius:999px;
 background:var(--a100);color:var(--a800);white-space:nowrap}
.kcm-tag-outline{border:1px solid var(--color-accent);background:transparent;color:var(--color-accent)}
.kcm-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;font-family:var(--font-heading);font-weight:600;
 font-size:14px;line-height:1.2;color:var(--color-text);background:var(--surface);border:1px solid var(--color-divider);
 padding:7px 12px;border-radius:8px;white-space:nowrap}
.kcm-btn:hover{background:color-mix(in srgb,var(--color-text) 7%,var(--surface))}
.kcm-btn.primary{background:var(--color-accent);border-color:var(--color-accent);color:#fff;box-shadow:0 1px 2px rgba(29,31,32,.14)}
.kcm-btn.primary:hover{background:var(--a600)}
body.body--dark .kcm-btn.primary{background:linear-gradient(#6a91b7,#4f7598);box-shadow:0 1px 0 rgba(255,255,255,.22) inset,0 2px 4px rgba(0,0,0,.45)}
.kcm-main{flex:1 1 0;min-width:0;padding:24px 20px 24px 8px}
/* Quasar 부품 */
.q-btn{border-radius:8px;font-family:var(--font-heading);font-weight:600;letter-spacing:0}
.q-btn.bg-primary{background:var(--color-accent)!important;color:#fff!important}
.q-field--outlined .q-field__control{border-radius:8px;background:var(--surface)!important;color:var(--color-text)!important}
.q-field--outlined .q-field__control:before{border-color:var(--color-divider)}
.q-field__control,.q-table__container,.q-table thead,.q-table tbody td{background:var(--surface)!important;color:var(--color-text)!important}
.q-field__label,.q-table th{color:var(--muted)!important}
.q-table th{font-size:11px;letter-spacing:.08em;text-transform:uppercase;background:var(--n100)!important}
.q-table__bottom,.q-table__bottom *{color:var(--muted)!important}
.q-table__container{border-radius:10px;border:1px solid var(--color-divider)}
.q-tree__node-header-content{color:var(--color-text)}
.q-tab{font-family:var(--font-heading);font-weight:600}
.q-tab--active{color:var(--color-accent)}
/* ── 반응형: 큰 모니터는 넓게, 작은 화면은 메뉴를 서랍으로 ── */
.kcm-menu-btn{display:none!important}
.kcm-backdrop{display:none}
.kcm-main>*{width:100%;max-width:1260px!important;margin-left:0;margin-right:auto}   /* 본문은 메뉴 바로 옆에서 시작 — 메뉴와 본문 사이 빈 공간 없음 */
@media (max-width:1199px){.kcm-card{padding:16px}.kcm-h1,.text-xl.font-bold{font-size:30px}.kcm-side{width:220px}}
@media (max-width:900px){
 .kcm-menu-btn{display:inline-flex!important}
 .kcm-side{position:fixed;left:0;top:0;bottom:0;margin:0;height:calc(100vh / var(--z,1));border-radius:0;z-index:60;width:min(300px,86vw);
  transform:translateX(-105%);transition:transform .2s}
 .kcm-side.open{transform:none;box-shadow:var(--elev-1),8px 0 30px rgba(0,0,0,.35)}
 .kcm-side.open + .kcm-backdrop{display:block;position:fixed;inset:0;z-index:55;background:rgba(20,24,28,.5)}
 .kcm-main{padding:16px 12px}
 .kcm-header-in,.kcm-crumb-in{padding-left:12px;padding-right:12px}
 .kcm-card{padding:14px}
}
@media (max-width:759px){
 .kcm-h1,.text-xl.font-bold{font-size:26px}
 input,textarea,.q-field__native{font-size:16px!important}
 .kcm-brand{font-size:18px}
 .q-btn{min-height:40px}
 .q-table th,.q-table td{padding:6px 8px}
 .kcm-btnrow{flex-wrap:wrap!important}.kcm-btnrow>.grow{flex:1 1 100%!important}
}
"""

NAV = [("search", "검색 · 코드 생성", "search", "/search"),
       ("cond", "조건 설정", "tune", "/cond"),
       ("index", "3권 색인 검색", "menu_book", "/index"),
       ("nlp", "AI 자동 코딩", "auto_awesome", "/nlp"),
       ("history", "코딩 이력", "history", "/history"),
       ("favs", "개인 코드집", "star_outline", "/favs"),
       ("dash", "대시보드", "bar_chart", "/dash"),
       ("users", "사용자 관리", "group", "/users"),
       ("kcd", "KCD 데이터", "storage", "/kcd"),
       ("dict", "용어 사전", "spellcheck", "/dict")]
NAV_ROLES = {"dash": ("sysadmin", "orgadmin"), "users": ("sysadmin", "orgadmin"), "kcd": ("sysadmin",), "dict": ("sysadmin",)}
TITLES = {k: t for k, t, _, _ in NAV}
TITLES["password"] = "비밀번호 변경"
NAV_INFO = {k: (icon, href) for k, _, icon, href in NAV}
NAV_GROUPS = [("조회", ["search", "index", "nlp"]), ("내 작업", ["history", "favs"]), ("관리", ["dash", "users", "kcd", "dict"])]
SCOPE_SHORT = {"sysadmin": "시스템 전체 관리", "orgadmin": "소속 기관 관리", "user": "시스템 사용"}


UI_PREF_KEYS = ("dark", "zoom", "panel_order", "panel_mode", "panel_show", "panel_wide", "panel_h", "panel_cols", "nav_groups", "nav_items", "nav_collapsed")


def load_ui_pref() -> None:
    """로그인한 사용자의 화면 설정(라이트/다크 · 크기 · 퍼즐 배치)을 DB에서 불러온다 — 어느 PC에서든 같은 화면으로 시작."""
    u = user()
    if not u or app.storage.user.get("pref_for") == u["id"]:
        return
    try:
        p = store.get(f"user:{u['id']}", "uiPref", {}, fresh=True) or {}
    except Exception:  # noqa: BLE001
        p = {}
    for k in UI_PREF_KEYS:
        if k in p:
            app.storage.user[k] = p[k]
    app.storage.user["pref_for"] = u["id"]


def save_ui_pref(**kw) -> None:
    """화면 설정을 사용자별로 DB에 저장한다 (백그라운드로 — 화면이 멈추지 않게)."""
    u = user()
    if not u:
        return
    import threading
    uid = u["id"]

    def _w() -> None:
        try:
            p = dict(store.get(f"user:{uid}", "uiPref", {}, fresh=True) or {})
            p.update(kw)
            store.put(f"user:{uid}", "uiPref", p, by=uid)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_w, daemon=True).start()


def apply_theme():
    """라이트/다크 · 화면 크기 — 사용자별로 저장해 두었다가 항상 그 설정으로 시작한다 (기본: 라이트)."""
    load_ui_pref()
    ui.add_head_html('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" '
                     'href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600'
                     '&display=swap">')
    app.storage.user.setdefault("dark", False)
    dm = ui.dark_mode().bind_value(app.storage.user, "dark")
    ui.add_body_html("""<script>(function(){var d=null;
document.addEventListener('dragstart',function(e){var t=e.target.closest&&e.target.closest('[data-dnd]');if(!t)return;d=t;
 e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',t.dataset.key);t.classList.add('dnd-dragging');});
document.addEventListener('dragend',function(){document.querySelectorAll('.dnd-dragging,.dnd-over').forEach(function(x){x.classList.remove('dnd-dragging','dnd-over')});d=null;});
document.addEventListener('dragover',function(e){var t=e.target.closest&&e.target.closest('[data-dnd]');if(!d||!t||t.dataset.dnd!==d.dataset.dnd)return;
 e.preventDefault();document.querySelectorAll('.dnd-over').forEach(function(x){x.classList.remove('dnd-over')});if(t!==d)t.classList.add('dnd-over');});
document.addEventListener('drop',function(e){var t=e.target.closest&&e.target.closest('[data-dnd]');if(!d||!t||t.dataset.dnd!==d.dataset.dnd||t===d)return;e.preventDefault();
 var g=d.dataset.dnd,keys=Array.prototype.map.call(document.querySelectorAll('[data-dnd="'+g+'"]'),function(x){return x.dataset.key});
 var dk=d.dataset.key,tk=t.dataset.key;keys.splice(keys.indexOf(dk),1);keys.splice(keys.indexOf(tk),0,dk);emitEvent('dnd_reorder',{group:g,order:keys});});})();</script>""")
    ui.add_body_html("""<script>document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-kact]');
if(!b)return;emitEvent('kcm_act',{act:b.dataset.kact,code:b.dataset.code});});</script>""")
    ui.add_css(THEME_CSS)
    app.storage.user.setdefault("zoom", 100)
    z0 = int(app.storage.user["zoom"])
    # 화면 폭에 맞춰 글자·화면을 자동 확대(--auto) + 사용자가 고른 크기(--user)를 곱한다
    ui.add_css(""":root{--auto:1}
@media (min-width:1280px){:root{--auto:1.08}}
@media (min-width:1500px){:root{--auto:1.18}}
@media (min-width:1800px){:root{--auto:1.3}}
@media (min-width:2200px){:root{--auto:1.5}}
@media (min-width:2800px){:root{--auto:1.8}}
@media (min-width:3400px){:root{--auto:2.1}}
@media (max-width:759px){:root{--auto:1.05}}""")
    ui.add_css(f"body{{--user:{z0 / 100};--z:calc(var(--auto) * var(--user));zoom:calc(var(--auto) * var(--user))}}")
    return dm


def theme_toggle(dm) -> None:
    btn = ui.button(on_click=lambda: dm.set_value(not dm.value)).props("flat round dense").style("color:var(--color-text)")
    with btn:
        ui.icon("dark_mode").bind_name_from(app.storage.user, "dark", backward=lambda d: "light_mode" if d else "dark_mode")
        ui.tooltip("라이트 / 다크 모드 전환")


def account_panel(dm, u: dict) -> None:
    """왼쪽 메뉴 하단 고정 패널 — 역할 · 데이터 상태 · 화면 모드 · 화면 크기 · 계정 · 로그아웃 (원본과 같은 구성)"""
    def set_zoom(z: int) -> None:
        z = max(70, min(150, z))
        app.storage.user["zoom"] = z
        zoom_lbl.set_text(f"{z}%")
        save_ui_pref(zoom=z)
        ui.run_javascript(f"document.body.style.setProperty('--user','{z / 100}')")

    def set_dark(v: bool) -> None:
        dm.set_value(v)
        save_ui_pref(dark=bool(v))
        (dark_b.classes(add="on"), light_b.classes(remove="on")) if v else (light_b.classes(add="on"), dark_b.classes(remove="on"))

    with ui.element("div").classes("kcm-acct"):
        with ui.row().classes("items-center gap-2 no-wrap").style("flex-wrap:wrap"):
            ui.html(f'<span class="kcm-tag">{ROLE_LABEL.get(u["role"], u["role"])}</span>')
            ui.label(SCOPE_SHORT.get(u["role"], "")).classes("text-muted").style("font-size:11px")
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label("데이터 · PC 화면").classes("text-muted").style("font-size:12px")
            ui.label(f"● 실시간 · {dt.datetime.now().strftime('%H:%M')}").style("font-size:11px;color:var(--ok);white-space:nowrap")
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label("화면 모드").classes("text-muted").style("font-size:12px")
            with ui.element("div").classes("kcm-seg"):
                dark_now = bool(app.storage.user.get("dark"))
                light_b = ui.element("button").classes("" if dark_now else "on").on("click", lambda: set_dark(False))
                with light_b:
                    ui.label("라이트")
                dark_b = ui.element("button").classes("on" if dark_now else "").on("click", lambda: set_dark(True))
                with dark_b:
                    ui.label("다크")
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label("화면 크기").classes("text-muted").style("font-size:12px")
            with ui.row().classes("items-center gap-1 no-wrap"):
                with ui.element("div").classes("kcm-btn").style("min-height:30px;padding:0 8px").on(
                        "click", lambda: set_zoom(int(app.storage.user["zoom"]) - 10)):
                    ui.label("가-")
                zoom_btn = ui.element("div").classes("kcm-btn mono").style("min-height:30px;min-width:56px;padding:0 8px;font-size:12px")
                with zoom_btn:
                    zoom_lbl = ui.label(f"{int(app.storage.user['zoom'])}%")
                zoom_btn.on("click", lambda: set_zoom(100))
                with ui.element("div").classes("kcm-btn").style("min-height:30px;padding:0 8px").on(
                        "click", lambda: set_zoom(int(app.storage.user["zoom"]) + 10)):
                    ui.label("가+")
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(u.get("id", "")).classes("text-muted mono").style(
                "font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.button("비밀번호 변경", on_click=lambda: ui.navigate.to("/password")).props("flat dense no-caps").style("color:var(--muted);font-size:12px")
                ui.button("로그아웃", on_click=logout).props("flat dense no-caps").style("color:var(--color-accent)")


def layout(active: str) -> None:
    """원본과 같은 구성 — 상단 헤더(K 로고) + 경로 표시줄 + 그룹형 왼쪽 메뉴(하단 계정 패널) + 본문. 이후 요소는 본문에 들어간다."""
    u = user()
    dm = apply_theme()
    if u.get("tempPw") and active != "password":   # 임시 비밀번호로 들어왔으면 먼저 비밀번호를 바꾸게 한다
        ui.navigate.to("/password")
    with ui.element("header").classes("kcm-header"):
        with ui.element("div").classes("kcm-header-in"):
            ui.button(icon="menu").props("flat round dense").classes("kcm-menu-btn").style("color:var(--color-text)").on(
                "click", js_handler="() => document.querySelector('.kcm-side').classList.toggle('open')")
            with ui.link(target="/search").style("text-decoration:none;display:flex;align-items:center;gap:8px"):
                ui.label("K").classes("kcm-logo")
                ui.label("심사 코딩마스터").classes("kcm-brand")
        with ui.element("div").classes("kcm-crumb"):
            with ui.element("nav").classes("kcm-crumb-in"):
                ui.link("홈", "/search")
                ui.label("/").classes("text-muted")
                ui.label(TITLES.get(active, ""))
    shell = ui.element("div").classes("kcm-shell")
    with shell:
        with ui.element("aside").classes("kcm-side"):
            with ui.element("div").classes("kcm-side-top"):
                with ui.element("div").classes("kcm-side-head"):
                    ui.html("<b>메뉴</b>").style("flex:1")
                    ui.label("끌어서 순서 변경").classes("text-muted").style("font-size:10px")
                    ui.button(icon="restart_alt", on_click=lambda: reset_nav()).props("flat round dense size=sm").tooltip("메뉴 순서 초기화")
                nav_box = ui.element("div").style("display:grid;gap:12px")

                default_groups = dict(NAV_GROUPS)

                def ordered_groups() -> list[tuple[str, list[str]]]:
                    """저장된 사용자별 순서 → (그룹, 메뉴) 목록. 새 메뉴나 권한 없는 메뉴는 알아서 맞춘다."""
                    gp = app.storage.user.get("nav_groups") or []
                    its = app.storage.user.get("nav_items") or {}
                    titles = [t for t in gp if t in default_groups] + [t for t, _ in NAV_GROUPS if t not in gp]
                    out = []
                    for title in titles:
                        saved = [k for k in (its.get(title) or []) if k in default_groups[title]]
                        keys = saved + [k for k in default_groups[title] if k not in saved]
                        keys = [k for k in keys if not (k in NAV_ROLES and u["role"] not in NAV_ROLES[k])]
                        if keys:
                            out.append((title, keys))
                    return out

                def render_nav() -> None:
                    nav_box.clear()
                    with nav_box:
                        for title, keys in ordered_groups():
                            with ui.element("nav").classes("kcm-grp").props(f'data-dnd="navgrp" data-key="{title}"'):
                                body = ui.element("div").style("display:grid;gap:5px")
                                with ui.element("div").classes("kcm-grp-h").props(
                                        'draggable="true" title="끌어서 그룹 순서 변경 · 클릭: 접기/펴기"') as head:
                                    caret = ui.label("▾").style("font-size:10px;width:10px;color:var(--n600)")
                                    ui.label(title).classes("kicker").style("flex:1")

                                hidden_grp = title in (app.storage.user.get("nav_collapsed") or [])
                                if hidden_grp:
                                    body.set_visibility(False)
                                    caret.set_text("▸")

                                def toggle(_=None, body=body, caret=caret, title=title) -> None:
                                    body.set_visibility(not body.visible)
                                    caret.set_text("▾" if body.visible else "▸")
                                    set_collapsed(title, not body.visible)
                                head.on("click", toggle)
                                body.move(head.parent_slot.parent)  # 머리글 아래에 본문 배치
                                with body:
                                    for key in keys:
                                        icon, href = NAV_INFO[key]
                                        with ui.link(target=href).classes("kcm-item" + (" active" if key == active else "")).props(
                                                f'draggable="true" data-dnd="nav:{title}" data-key="{key}" title="끌어서 순서 변경"'):
                                            with ui.row().classes("items-center no-wrap gap-2"):
                                                with ui.element("span").classes("kcm-tile"):
                                                    ui.icon(icon).classes("text-lg")
                                                ui.label(TITLES[key]).style("white-space:nowrap")
                                            if key == "search":      # 하위 메뉴(조건 설정) 접기·펴기 — 선택은 사용자별로 기억
                                                sub_hidden = "sub:search" in (app.storage.user.get("nav_collapsed") or [])
                                                ui.button(icon="chevron_right" if sub_hidden else "expand_more", color=None,
                                                          on_click=lambda: toggle_sub("sub:search")).props("flat dense round size=sm").classes("kcm-subtoggle").style(
                                                    "margin-left:auto").tooltip("하위 메뉴 펴기" if sub_hidden else "하위 메뉴 숨기기").on("click.stop.prevent", lambda: None)
                                        if key == "search" and ("sub:search" not in (app.storage.user.get("nav_collapsed") or []) or active == "cond"):
                                            with ui.link(target="/cond").classes("kcm-item kcm-sub" + (" active" if active == "cond" else "")):
                                                with ui.row().classes("items-center no-wrap gap-2"):
                                                    with ui.element("span").classes("kcm-tile").style("width:24px;height:24px;border-radius:6px"):
                                                        ui.icon("tune").classes("text-base")
                                                    ui.label("조건 설정").style("white-space:nowrap")

                def set_collapsed(name: str, on: bool) -> None:
                    cur = [x for x in (app.storage.user.get("nav_collapsed") or []) if x != name]
                    if on:
                        cur.append(name)
                    app.storage.user["nav_collapsed"] = cur
                    save_ui_pref(nav_collapsed=cur)

                def toggle_sub(name: str) -> None:
                    set_collapsed(name, name not in (app.storage.user.get("nav_collapsed") or []))
                    render_nav()

                def save_nav() -> None:
                    save_ui_pref(nav_groups=app.storage.user.get("nav_groups") or [], nav_items=app.storage.user.get("nav_items") or {})

                def on_nav_dnd(e) -> None:
                    a = e.args or {}
                    g, new = str(a.get("group", "")), list(a.get("order") or [])
                    if g == "navgrp":
                        app.storage.user["nav_groups"] = [t for t in new if t in default_groups]
                    elif g.startswith("nav:") and g[4:] in default_groups:
                        title = g[4:]
                        its = dict(app.storage.user.get("nav_items") or {})
                        its[title] = [k for k in new if k in default_groups[title]]
                        app.storage.user["nav_items"] = its
                    else:
                        return
                    save_nav()
                    render_nav()

                def reset_nav() -> None:
                    app.storage.user["nav_groups"] = []
                    app.storage.user["nav_items"] = {}
                    save_nav()
                    render_nav()
                    ui.notify("메뉴 순서를 처음대로 되돌렸습니다.")
                ui.on("dnd_reorder", on_nav_dnd)
                render_nav()
            account_panel(dm, u)
        ui.element("div").classes("kcm-backdrop").on(
            "click", js_handler="() => document.querySelector('.kcm-side').classList.remove('open')")
    main = ui.column().classes("kcm-main gap-3")
    main.move(shell)
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
    app.storage.user.pop("pref_for", None)
    ui.navigate.to("/login")


# ───────────────────────── 로그인 ─────────────────────────
_FAILS: dict[str, list[float]] = {}     # 로그인 실패 기록 {키: [시각…]} — 무차별 대입 방지
MAX_FAIL, FAIL_WINDOW, IP_MAX_FAIL = 5, 600, 25


def client_ip() -> str:
    try:
        h = ui.context.client.request.headers
        return (h.get("x-forwarded-for") or "").split(",")[0].strip() or ui.context.client.request.client.host
    except Exception:  # noqa: BLE001
        return "?"


def _recent(key: str) -> list[float]:
    now = time.time()
    lst = [t for t in _FAILS.get(key, []) if now - t < FAIL_WINDOW]
    if lst:
        _FAILS[key] = lst
    else:
        _FAILS.pop(key, None)
    return lst


def login_wait(ip: str, ident: str) -> int:
    """잠금 중이면 남은 분(올림), 아니면 0"""
    for key, limit in ((f"id|{ident}", MAX_FAIL), (f"ip|{ip}", IP_MAX_FAIL)):
        lst = _recent(key)
        if len(lst) >= limit:
            return max(1, -(-int(lst[0] + FAIL_WINDOW - time.time()) // 60))
    return 0


def login_failed(ip: str, ident: str) -> None:
    for key in (f"id|{ident}", f"ip|{ip}"):
        _FAILS.setdefault(key, []).append(time.time())


def upgrade_password(u: dict, pw: str) -> None:
    """기존(약한) 해시로 로그인에 성공하면 안전한 해시로 바꿔 저장한다."""
    try:
        from .phase6 import save_password
        save_password(u["id"], pw, temp=bool(u.get("pwTemp")))
    except Exception:  # noqa: BLE001
        pass


@ui.page("/login")
def login_page() -> None:
    if user():
        ui.navigate.to("/search")
        return
    orgs = [o for o in store.orgs() if o.get("active", True)]
    org_opts = {o["id"]: o["name"] for o in orgs}
    state = {"mode": "emp", "org": next(iter(org_opts), ""), "id": "", "pw": "", "save": False}
    MODES = {"emp": ("사번", "사번", "예: 1001"), "gmail": ("Gmail", "Gmail 주소", "name@gmail.com"),
             "admin": ("시스템 관리자", "관리자 ID", "admin")}

    dm = apply_theme()
    with ui.row().classes("absolute-top-right p-3"):
        theme_toggle(dm)
    with ui.element("div").style("min-height:calc(100vh / var(--z, 1));width:100%;display:grid;place-items:center;padding:40px 20px"):
        with ui.column().classes("gap-0").style("width:min(420px,100%)"):
            ui.label("심사 코딩마스터").style("font-family:var(--font-heading);font-weight:600;font-size:38px;line-height:1.12;white-space:nowrap")
            ui.label("사번 또는 Gmail을 입력하면 소속기관이 표시됩니다.").classes("text-muted").style("font-size:13px;margin:6px 0 24px")
            with ui.column().classes("kcm-card w-full gap-4").style("padding:22px"):
                err = ui.label("").style("display:none;border:1px solid var(--color-accent);border-radius:10px;background:var(--a100);"
                                         "padding:10px 12px;font-size:13px;color:var(--a900)")
                if not store.configured():
                    ui.label("⚠ SUPABASE_URL / SUPABASE_KEY 설정이 없어 계정을 불러올 수 없습니다.").style("color:var(--bad);font-size:13px")
                with ui.column().classes("w-full gap-1"):
                    ui.label("소속기관").style("font-size:12px;color:var(--muted)")
                    # 기관 목록을 보여 주지 않는다 — 아이디를 입력하면 그 아이디가 속한 기관만 표시된다
                    org_sel = ui.select({}, value=None).props("dense outlined readonly hide-dropdown-icon").classes("w-full")
                    org_hint = ui.label("").style("font-size:11px;color:var(--muted)")
                with ui.column().classes("w-full gap-1"):
                    ui.label("로그인 방식").style("font-size:12px;color:var(--muted)")
                    with ui.element("div").style("display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;width:100%"):
                        mode_btns = {}
                        for k, (lab, _, _) in MODES.items():
                            b = ui.element("button").style("display:flex;align-items:center;justify-content:center;min-height:46px;padding:6px 8px;"
                                                           "border-radius:10px;cursor:pointer;font-size:14px;border:1px solid var(--color-divider)")
                            with b:
                                ui.label(lab)
                            mode_btns[k] = b
                lbl_id = ui.label("").style("font-size:12px;color:var(--muted);margin-bottom:-12px")
                ident = ui.input().props("dense outlined").classes("w-full mono").bind_value(state, "id")
                def refresh_org(*_: object) -> None:
                    """아이디에 해당하는 소속기관만 보여 준다 (여러 기관에 같은 사번이 있으면 그 기관들만 고르게 한다)"""
                    mode, ident_v = state["mode"], (state["id"] or "").strip().lower()
                    if mode == "admin":
                        org_sel.set_options({}, value=None)
                        org_sel.props("readonly hide-dropdown-icon")
                        state["org"] = next(iter(org_opts), "")
                        org_hint.set_text("시스템 관리자는 소속기관 없이 로그인합니다.")
                        return
                    ids: list[str] = []
                    if ident_v:
                        for a in store.accounts():
                            hit = str(a.get("empNo", "")).lower() == ident_v if mode == "emp" else str(a.get("id", "")).lower() == ident_v
                            if hit and a.get("orgId") not in ids:
                                ids.append(a.get("orgId"))
                    names = {o["id"]: o["name"] for o in store.orgs()}
                    opts = {i: names.get(i, i) for i in ids}
                    if not ident_v:
                        state["org"] = ""
                        org_sel.set_options({}, value=None)
                        org_hint.set_text("아이디를 입력하면 소속기관이 표시됩니다.")
                        return
                    if not opts:
                        state["org"] = ""
                        org_sel.set_options({}, value=None)
                        org_hint.set_text("등록된 아이디가 아닙니다. 아이디를 다시 확인하세요.")
                        return
                    keep = state["org"] if state["org"] in opts else next(iter(opts))
                    state["org"] = keep
                    org_sel.set_options(opts, value=keep)
                    if len(opts) > 1:
                        org_sel.props(remove="readonly hide-dropdown-icon")
                        org_hint.set_text("같은 사번이 여러 기관에 있습니다. 소속기관을 선택하세요.")
                    else:
                        org_sel.props("readonly hide-dropdown-icon")
                        org_hint.set_text("")
                org_sel.on_value_change(lambda e: state.__setitem__("org", e.value or ""))
                ident.on_value_change(refresh_org)
                refresh_org()
                ui.label("비밀번호").style("font-size:12px;color:var(--muted);margin-bottom:-12px")
                pw = ui.input(password=True, password_toggle_button=True, placeholder="비밀번호").props("dense outlined").classes("w-full").bind_value(state, "pw")

                # 로그인 방식(사번 / Gmail / 시스템 관리자)마다 아이디를 따로 저장·복원한다 — 이 PC의 브라우저(localStorage)에 보관, 비밀번호는 저장하지 않음
                saved_ids: dict[str, str] = {}      # 저장된 아이디 {방식: 아이디}
                typed: dict[str, str] = {}          # 이 화면에서 입력 중인 값 (방식을 바꿨다 돌아와도 유지)

                def set_mode(k: str) -> None:
                    typed[state["mode"]] = state["id"]
                    state["mode"] = k
                    lbl_id.set_text(MODES[k][1])
                    ident.props(f'placeholder="{MODES[k][2]}"')
                    for kk, b in mode_btns.items():
                        on = kk == k
                        b.style("background:var(--a100);border-color:var(--color-accent);color:var(--a800);font-weight:600" if on
                                else "background:var(--surface);border-color:var(--color-divider);color:var(--color-text);font-weight:400")
                    ident.set_value(typed.get(k) or saved_ids.get(k, ""))      # 이 방식에 저장된 아이디를 채운다
                    refresh_org()
                    chk.set_value(bool(saved_ids.get(k)))
                    forget_btn.set_visibility(bool(saved_ids.get(k)))
                for k, b in mode_btns.items():
                    b.on("click", lambda _, k=k: set_mode(k))
                with ui.row().classes("w-full items-center justify-between"):
                    chk = ui.checkbox("아이디 저장").bind_value(state, "save").style("font-size:13px")
                    forget_btn = ui.button("저장된 아이디 지우기", on_click=lambda: forget()).props("flat dense no-caps").style(
                        "font-size:12px;color:var(--color-accent)")
                    forget_btn.set_visibility(False)
                set_mode("emp")

                async def load_saved() -> None:
                    try:
                        raw = await ui.run_javascript("return localStorage.getItem('kcm_login')", timeout=5)
                        d = json.loads(raw) if raw else None
                    except Exception:  # noqa: BLE001
                        return
                    if not isinstance(d, dict):
                        return
                    ids = d.get("ids") if isinstance(d.get("ids"), dict) else {}
                    if d.get("id") and d.get("mode") in MODES:          # 이전 저장 형식(방식 하나) 호환
                        ids.setdefault(d["mode"], d["id"])
                    saved_ids.update({k: str(v) for k, v in ids.items() if k in MODES and v})
                    if not saved_ids:
                        return
                    last = d.get("mode") if d.get("mode") in MODES else next(iter(saved_ids))
                    typed.pop(last, None)
                    set_mode(last)
                    pw.run_method("focus")
                ui.timer(0.3, load_saved, once=True)

                def forget() -> None:
                    """지금 선택한 방식의 저장된 아이디만 지운다"""
                    k = state["mode"]
                    saved_ids.pop(k, None)
                    typed.pop(k, None)
                    ui.run_javascript("(function(){var d={};try{d=JSON.parse(localStorage.getItem('kcm_login')||'{}')||{}}catch(e){}"
                                      f"d.ids=d.ids||{{}};delete d.ids[{json.dumps(k)}];delete d.id;"
                                      "if(Object.keys(d.ids).length){localStorage.setItem('kcm_login',JSON.stringify(d))}else{localStorage.removeItem('kcm_login')}})()")
                    ident.set_value("")
                    chk.set_value(False)
                    forget_btn.set_visibility(False)
                    ui.notify(f"{MODES[k][0]} 아이디를 지웠습니다.")

                async def do_login() -> None:
                    accounts, all_orgs, sysad = store.get_many([("global", "accounts", []), ("global", "orgs", []), ("global", "sysAdmin", None)], fresh=True)
                    ip, ident_key = client_ip(), f"{state['mode']}|{state['id'].strip().lower()}"
                    wait = login_wait(ip, ident_key)
                    if wait:
                        err.set_text(f"로그인 시도가 너무 많습니다. {wait}분 뒤에 다시 시도하세요.")
                        err.style("display:block")
                        return
                    if state["mode"] != "admin" and not state["org"]:
                        login_failed(ip, ident_key)
                        err.set_text("등록된 아이디가 아닙니다. 사번 또는 Gmail을 다시 확인하세요." if state["id"].strip() else "아이디를 입력하세요.")
                        err.style("display:block")
                        return
                    u, msg = authenticate(state["mode"], state["id"], state["pw"], state["org"], accounts or [], all_orgs or [], sysad)
                    if not u:
                        login_failed(ip, ident_key)
                        err.set_text(msg)
                        err.style("display:block")
                        return
                    _FAILS.pop(f"id|{ident_key}", None)
                    u["tempPw"] = u.pop("pwTemp", False)
                    if u.pop("legacyPw", False):
                        upgrade_password(u, state["pw"])
                    app.storage.user["user"] = u
                    try:
                        k = state["mode"]
                        if state["save"] and state["id"].strip():
                            saved_ids[k] = state["id"].strip()
                        else:
                            saved_ids.pop(k, None)           # 체크를 끄면 이 방식의 저장값만 지운다
                        if saved_ids:
                            payload = json.dumps({"mode": k, "org": state["org"], "ids": saved_ids}, ensure_ascii=False)
                            await ui.run_javascript(f"localStorage.setItem('kcm_login', {json.dumps(payload)})", timeout=5)
                        else:
                            await ui.run_javascript("localStorage.removeItem('kcm_login')", timeout=5)
                    except Exception:  # noqa: BLE001
                        pass
                    ui.navigate.to("/search")

                pw.on("keydown.enter", do_login)
                ident.on("keydown.enter", do_login)
                ui.button("로그인", on_click=do_login).props("no-caps unelevated color=primary").classes("w-full").style("min-height:46px;font-size:15px")
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("● 공용 DB 연결" if store.configured() else "● 연결 안 됨").style(
                        "font-size:11px;color:var(--ok)" if store.configured() else "font-size:11px;color:var(--bad)")
                    ui.label("비밀번호를 모르면 소속 기관 관리자에게 초기화를 요청하세요.").classes("text-muted").style("font-size:11px")

@ui.page("/")
def index_page() -> None:
    ui.navigate.to("/search" if user() else "/login")



# ───────────────────────── KCD 데이터 ─────────────────────────
def _parse_kcd(name: str, raw: bytes) -> list[list]:
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
    hdr: list[str] = []
    for i, row in enumerate(table[:30]):
        cells = [c.replace(" ", "") for c in row]
        c_i = next((j for j, c in enumerate(cells) if c.endswith("코드") or c.endswith("기호") or c.lower() == "code"), -1)
        k_i = next((j for j, c in enumerate(cells) if j != c_i and any(w in c for w in ("한글", "국문", "상병명", "질병명", "분류명", "명칭"))), -1)
        if c_i >= 0 and k_i >= 0:
            ci, ko = c_i, k_i
            en = next((j for j, c in enumerate(cells) if "영문" in c or c.lower() == "english"), -1)
            sy = next((j for j, c in enumerate(cells) if "동의어" in c or "별칭" in c or "약어" in c), -1)
            start = i + 1
            hdr = cells
            break
    if ci < 0:
        ci, ko, start = 0, 1, 0
    rows, seen = [], set()
    for r in table[start:]:
        if len(r) <= max(ci, ko):
            continue
        code, kname = norm_code(r[ci]), str(r[ko]).strip()
        if not code or not kname or code in seen or not code[0].isalpha() or not re.fullmatch(r"[A-Z]\d{2}(\.?[0-9A-Z]{1,3})?[*†]?", code):
            continue          # 장·절 범위(A00-A09 등)나 설명 행은 코드가 아니므로 건너뜀
        seen.add(code)
        row = [code, kname, str(r[en]).strip() if 0 <= en < len(r) else "",
               "|".join(x.strip() for x in str(r[sy]).replace(";", ",").split(",") if x.strip()) if 0 <= sy < len(r) else ""]
        if hdr and any(h in kcd_sync.FIELD_ALIASES["sex"] + kcd_sync.FIELD_ALIASES["max"] + kcd_sync.FIELD_ALIASES["primary"] for h in hdr):
            rec = {h: (r[j] if j < len(r) else "") for j, h in enumerate(hdr)}
            row.append(kcd_sync.extras_of(rec))
            if "." not in code and len(code) > 3 and code[1:].isdigit():   # 점 없는 공공데이터 상병기호 → A00.0 형태
                row[0] = kcd_sync.dotted(code)
        rows.append(row)
    if len(rows) < 10:
        raise ValueError("코드 · 한글명 열을 찾지 못했습니다. 첫 행에 '코드', '한글명' 머리글이 있는지 확인하세요.")
    return rows


@ui.page("/kcd")
def kcd_page() -> None:
    if not require_login(("sysadmin",)):
        return
    layout("kcd")
    from . import kcd_sync
    m = store.kcd_master()
    env_key = os.environ.get("DATA_GO_KR_KEY", "").strip()

    def stored_key() -> str:
        v = store.get("global", "dataGoKey", "")
        return (v if isinstance(v, str) else (v or {}).get("key", "")).strip()

    with ui.column().classes("w-full gap-4").style("max-width:1000px"):
        ui.label("KCD 데이터").classes("kcm-h1")
        ui.label("검색·AI 코딩·룰 점검이 쓰는 상병마스터를 관리합니다. 적재하면 모든 사용자에게 적용됩니다.").classes("text-muted").style("font-size:13px;margin-top:-8px")

        # ── 현재 데이터
        with ui.column().classes("kcm-card w-full gap-1"):
            ui.label("현재 적재된 데이터").classes("kicker")
            cur = ui.label("").style("font-family:var(--font-heading);font-weight:600;font-size:22px")
            cur_sub = ui.label("").classes("text-muted").style("font-size:12px")

            def show_current() -> None:
                mm = store.kcd_master()
                rows = mm.get("rows", [])
                en_n = sum(1 for r in rows if len(r) > 2 and r[2])
                ex_n = sum(1 for r in rows if len(r) > 4 and r[4])
                cur.set_text(f"{mm.get('name') or '(없음)'}")
                cur_sub.set_text(f"{len(rows):,}건 · 영문명 {en_n:,}건 · 성별/연령/주상병 부가정보 {ex_n:,}건 · 적재 {mm.get('at', '')}"
                                 + (f" · {mm['source']}" if mm.get("source") else ""))
            show_current()

        # ── 공공데이터포털 자동 불러오기
        with ui.column().classes("kcm-card w-full gap-3"):
            ui.label("공공데이터포털에서 자동 불러오기").classes("kicker")
            ui.label("건강보험심사평가원 ‘상병마스터’(KCD 기반 공식 데이터)를 공공데이터포털의 공식 API로 내려받아 적재합니다. "
                     "한글명·영문명, 성별·연령 제한, 주상병 사용 여부가 함께 들어옵니다. 연 1회 갱신되며, 이용 조건은 ‘출처 표시’입니다.").classes("kcm-note")
            with ui.column().classes("gap-1").style("font-size:12px"):
                ui.html("<b>처음 한 번만 필요한 준비</b> — 무료 인증키 발급")
                ui.html("1) <a href='https://www.data.go.kr/data/15067467/fileData.do' target='_blank' rel='noopener' style='color:var(--color-accent)'>"
                        "공공데이터포털 ‘상병마스터’ 페이지 ↗</a>에서 로그인 후 <b>활용신청</b> (자동 승인)<br>"
                        "2) 마이페이지 → 개발계정 → <b>일반 인증키</b> 복사<br>"
                        "3) 아래 칸에 붙여 넣고 <b>저장</b> (또는 서버 환경변수 <span class='mono'>DATA_GO_KR_KEY</span>에 설정)").classes("text-muted")
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                key_in = ui.input(placeholder="공공데이터포털 일반 인증키 (Decoding 또는 Encoding 키)" if not env_key else "서버 환경변수의 키를 사용 중입니다",
                                  password=True, password_toggle_button=True).props("dense outlined").classes("grow mono")
                key_in.set_value("" if env_key else stored_key())

                def save_key() -> None:
                    store.put("global", "dataGoKey", (key_in.value or "").strip(), by=user()["id"])
                    ui.notify("인증키를 저장했습니다.", type="positive")
                if not env_key:
                    ui.button("저장", on_click=save_key).props("no-caps outline")
            with ui.row().classes("items-center gap-3"):
                go_btn = ui.button("최신 상병마스터 불러오기", icon="cloud_download").props("no-caps unelevated color=primary")
                prog_txt = ui.label("").classes("text-muted").style("font-size:12px")
            prog = ui.linear_progress(value=0, show_value=False).classes("w-full")
            prog.set_visibility(False)
            sync_msg = ui.label("").style("font-size:13px")

            async def run_sync() -> None:
                key = env_key or (key_in.value or "").strip() or stored_key()
                if not key:
                    ui.notify("공공데이터포털 인증키를 먼저 입력하세요.", type="warning")
                    return
                go_btn.disable()
                prog.set_visibility(True)
                prog.set_value(0)
                sync_msg.set_text("")
                records: list[dict] = []
                try:
                    with httpx.Client(headers={"Accept": "application/json"}) as client:
                        prog_txt.set_text("최신 데이터 위치를 확인하는 중…")
                        path, title = await nrun.io_bound(kcd_sync.latest_path, client)
                        page, total = 1, None
                        while True:
                            res = await nrun.io_bound(kcd_sync.fetch_page, client, path, key, page)
                            data = res.get("data") or []
                            total = res.get("totalCount") or res.get("matchCount") or total or 0
                            records.extend(data)
                            pages = max(1, -(-int(total) // kcd_sync.PER_PAGE)) if total else page
                            prog.set_value(min(1.0, len(records) / total) if total else 0)
                            prog_txt.set_text(f"{title} — {len(records):,} / {int(total):,}건 내려받는 중 ({page}/{pages}쪽)")
                            if not data or len(records) >= int(total or 0):
                                break
                            page += 1
                    prog_txt.set_text("변환하고 저장하는 중…")
                    rows = await nrun.io_bound(kcd_sync.rows_from_records, records)
                    if len(rows) < 1000:
                        raise RuntimeError(f"내려받은 항목이 너무 적습니다({len(rows)}건). 데이터 형식이 바뀌었는지 확인이 필요합니다.")
                    data = {"name": title, "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "by": user()["id"],
                            "source": kcd_sync.SOURCE_NOTE, "rows": rows}
                    await nrun.io_bound(store.put, "global", "kcdMaster", data, user()["id"])
                    get_index(fresh=True)
                    prog.set_value(1)
                    prog_txt.set_text("")
                    sync_msg.set_text(f"적재 완료 — {len(rows):,}건 ({title}). {kcd_sync.SOURCE_NOTE}")
                    ui.notify(f"상병마스터 {len(rows):,}건을 적재했습니다.", type="positive")
                    show_current()
                except PermissionError as ex:
                    sync_msg.set_text(f"불러오기 실패 — {ex}")
                    prog_txt.set_text("")
                except Exception as ex:  # noqa: BLE001
                    sync_msg.set_text(f"불러오기 실패 — {ex}")
                    prog_txt.set_text("")
                finally:
                    go_btn.enable()
            go_btn.on_click(run_sync)
            ui.label(kcd_sync.SOURCE_NOTE).classes("text-muted").style("font-size:11px")

        # ── 파일 올리기
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("파일로 올리기").classes("kicker")
            ui.label("직접 받은 CSV(UTF-8/CP949) 또는 XLSX 파일을 올립니다. 공공데이터포털의 ‘상병마스터’ CSV(상병기호·한글명·영문명 …)도 그대로 읽습니다. "
                     "첫 행에 머리글이 필요합니다.").classes("text-muted").style("font-size:12px")
            status = ui.label("").style("font-size:13px")
            merge_en = ui.checkbox("기존 데이터는 그대로 두고 영문명만 보태기 (코드가 같은 행에 영문명을 채웁니다)", value=bool(m.get("rows"))).style("font-size:13px")

            async def on_upload(e) -> None:
                try:
                    f = getattr(e, "file", None)
                    name = f.name if f else e.name
                    raw = await f.read() if f else e.content.read()
                    rows = _parse_kcd(name, raw)
                    if merge_en.value and (store.kcd_master(fresh=True).get("rows") or []):
                        cur = store.kcd_master(fresh=True)
                        eng = {r[0].replace(".", "").upper(): r[2] for r in rows if len(r) > 2 and r[2]}
                        if not eng:
                            raise ValueError("이 파일에는 영문명 열이 없습니다. 머리글에 ‘영문명’(English)이 있는 파일을 올리세요.")
                        n = 0
                        for r in cur["rows"]:
                            en = eng.get(r[0].replace(".", "").upper())
                            if en:
                                while len(r) < 3:
                                    r.append("")
                                if r[2] != en:
                                    r[2] = en
                                    n += 1
                        cur.update({"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "by": user()["id"]})
                        store.put("global", "kcdMaster", cur, by=user()["id"])
                        get_index(fresh=True)
                        status.set_text(f"영문명 {n:,}건을 보탰습니다 (파일의 영문명 {len(eng):,}건 중)")
                        ui.notify(f"영문명 {n:,}건을 적용했습니다.", type="positive")
                        show_current()
                        return
                    data = {"name": name, "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "by": user()["id"], "rows": rows}
                    store.put("global", "kcdMaster", data, by=user()["id"])
                    get_index(fresh=True)
                    status.set_text(f"적재 완료 — {len(rows):,}건")
                    ui.notify(f"KCD {len(rows):,}건을 적재했습니다.", type="positive")
                    show_current()
                except Exception as ex:  # noqa: BLE001
                    status.set_text(f"적재 실패 — {ex}")
                    ui.notify(str(ex), type="negative")

            ui.upload(on_upload=on_upload, auto_upload=True, label="파일 선택").props("accept=.csv,.xlsx,.xlsm flat bordered").classes("w-full")


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

from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1024)   # 화면 · 스크립트를 압축해서 보낸다 (전송량 1/3~1/5)


# ── 연결 안정성 ──────────────────────────────────────────────
# 화면은 웹소켓으로 서버와 계속 이야기한다. 아래 설정으로 일시적인 지연·절전·프록시 유휴 끊김에도 연결이 유지되게 한다.
from nicegui import core  # noqa: E402

def _tune_ping() -> None:
    # NiceGUI 는 서버가 시작될 때 reconnect_timeout 으로 이 값을 다시 계산해 덮어쓴다(60초 → 간격 48초 · 대기 24초).
    # 그래서 시작이 끝난 뒤(on_startup)에 다시 지정해야 실제로 적용된다.
    core.sio.eio.ping_interval = 12   # 12초마다 연결 확인 신호 → 중간 프록시·방화벽이 "놀고 있는 연결"로 보고 끊지 않게 함
    core.sio.eio.ping_timeout = 90    # 응답이 90초까지 늦어도 끊지 않음 — 브라우저 탭 절전·잠깐의 서버 정체 대비


_tune_ping()
app.on_startup(_tune_ping)


@app.get("/healthz")
def healthz() -> dict:
    """살아 있는지 확인용 (외부 모니터링 · 서버 자체 깨우기 신호가 호출)"""
    return {"ok": True}


def _keepalive() -> None:
    """Render 무료 플랜은 15분 동안 요청이 없으면 서버를 재우고 그때마다 연결이 끊긴다.
    서버가 깨어 있는 동안 9분마다 자기 주소로 가벼운 요청을 보내 잠들지 않게 한다. (RENDER_EXTERNAL_URL 은 Render가 자동으로 넣어 준다.)"""
    url = (os.environ.get("KEEPALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not url:
        return
    import threading
    import time as _t

    def loop() -> None:
        while True:
            _t.sleep(540)
            try:
                httpx.get(url + "/healthz", timeout=20)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=loop, daemon=True).start()


@app.middleware("http")
async def _security_headers(request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), clipboard-read=(self), clipboard-write=(self)")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


def _warm() -> None:
    import threading
    def go() -> None:
        store.warm()
        try:
            get_index()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=go, daemon=True).start()
    _keepalive()


app.on_startup(_warm)

from . import phase2, phase3, phase4, phase5, phase6, phase7  # noqa: E402,F401  (2단계: 조건·색인·AI / 3단계: 이력·코드집·대시보드 / 4단계: 검색·정밀 분석)


def run() -> None:
    port = int(os.environ.get("PORT", "8080"))
    secret = os.environ.get("STORAGE_SECRET", "")
    if not secret and (os.environ.get("RENDER") or os.environ.get("PRODUCTION")):
        raise SystemExit("운영 환경에서는 STORAGE_SECRET(임의의 긴 문자열) 환경변수가 반드시 필요합니다.")
    ui.run(title="심사 코딩마스터", host="0.0.0.0", port=port, reload=False, show=False, reconnect_timeout=60,
           storage_secret=secret or "dev-only-not-for-production", language="ko-KR")
