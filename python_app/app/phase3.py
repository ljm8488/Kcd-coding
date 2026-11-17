"""3단계 화면 — 코딩 이력 · 개인 코드집 · 대시보드 (+ 검색 결과 저장 도우미)"""
from __future__ import annotations

import collections
import datetime as dt

import httpx
from nicegui import ui

from . import store
from .main import layout, require_login, user

HISTORY_MAX = 500


def _scope() -> str:
    return f"user:{user()['id']}"


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# ───────── 저장 도우미 (검색 · AI 화면에서 호출) ─────────
def add_history(q: str, code: str, ko: str, pct: str = "", status: str = "생성") -> None:
    items = store.get(_scope(), "history", [], fresh=True) or []
    items.insert(0, {"q": q, "at": now_str(), "ko": ko, "pct": pct, "code": code, "status": status})
    store.put(_scope(), "history", items[:HISTORY_MAX], by=user()["id"])


def add_fav(code: str, ko: str, label: str = "") -> bool:
    """코드집에 담는다. 이미 있으면 False."""
    items = store.get(_scope(), "favs", [], fresh=True) or []
    if any(f.get("code") == code for f in items):
        return False
    items.append({"key": code, "en": "", "ko": ko, "code": code, "label": label or ko, "at": now_str()})
    store.put(_scope(), "favs", items, by=user()["id"])
    return True


# ───────── 코딩 이력 ─────────
@ui.page("/history")
def history_page() -> None:
    if not require_login():
        return
    layout("history")
    with ui.column().classes("w-full max-w-5xl gap-3"):
        ui.label("코딩 이력").classes("text-xl font-bold")
        ui.label("내가 생성·확정한 코드 기록입니다 (최근 500건).").classes("text-sm text-muted")

        @ui.refreshable
        def body() -> None:
            items = store.get(_scope(), "history", [], fresh=True) or []
            rows = [{"i": i, **{k: str(v) for k, v in h.items()}} for i, h in enumerate(items)]
            ui.table(columns=[
                {"name": "at", "label": "일시", "field": "at", "align": "left", "sortable": True},
                {"name": "q", "label": "검색어", "field": "q", "align": "left"},
                {"name": "code", "label": "코드", "field": "code", "align": "left", "sortable": True},
                {"name": "ko", "label": "한글명", "field": "ko", "align": "left"},
                {"name": "pct", "label": "정확도", "field": "pct", "align": "left"},
                {"name": "status", "label": "상태", "field": "status", "align": "left"},
            ], rows=rows, row_key="i", pagination=20).classes("w-full")

            def clear() -> None:
                store.put(_scope(), "history", [], by=user()["id"])
                ui.notify("이력을 비웠습니다.")
                body.refresh()
            if items:
                ui.button("이력 모두 지우기", on_click=clear, color="red").props("no-caps flat")
            else:
                ui.label("아직 이력이 없습니다. 검색 화면에서 코드를 선택해 '이력에 기록'을 누르세요.").classes("text-muted")
        body()


# ───────── 개인 코드집 ─────────
@ui.page("/favs")
def favs_page() -> None:
    if not require_login():
        return
    layout("favs")
    with ui.column().classes("w-full max-w-4xl gap-3"):
        ui.label("개인 코드집").classes("text-xl font-bold")
        ui.label("자주 쓰는 코드를 모아 둔 나만의 목록입니다.").classes("text-sm text-muted")

        @ui.refreshable
        def body() -> None:
            items = store.get(_scope(), "favs", [], fresh=True) or []
            if not items:
                ui.label("코드집이 비어 있습니다. 검색 화면에서 코드를 선택해 '코드집에 담기'를 누르세요.").classes("text-muted")
                return
            for f in items:
                with ui.row().classes("kcm-card w-full items-center no-wrap gap-4"):
                    ui.label(f.get("code", "")).classes("text-lg font-bold").style("min-width:80px;color:var(--accent-hi)")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(f.get("ko") or f.get("label", "")).classes("font-semibold")
                        if f.get("en"):
                            ui.label(f["en"]).classes("text-sm text-muted")

                    def remove(code=f.get("code")) -> None:
                        cur = store.get(_scope(), "favs", [], fresh=True) or []
                        store.put(_scope(), "favs", [x for x in cur if x.get("code") != code], by=user()["id"])
                        body.refresh()
                    ui.button(icon="delete", on_click=remove).props("flat round dense")
        body()


# ───────── 대시보드 ─────────
def _all_histories() -> list[dict]:
    r = httpx.get(f"{store.SUPABASE_URL}/rest/v1/kcm_store",
                  params={"key": "eq.history", "select": "scope,data"}, headers=store._headers(), timeout=30)
    r.raise_for_status()
    out = []
    for row in r.json():
        for h in row.get("data") or []:
            if isinstance(h, dict):
                out.append({**h, "_scope": row["scope"]})
    return out


@ui.page("/dash")
def dash_page() -> None:
    if not require_login(("sysadmin", "orgadmin")):
        return
    layout("dash")
    hist = _all_histories()
    accounts = store.accounts()
    today = dt.date.today()
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    per_day = collections.Counter(str(h.get("at", ""))[:10] for h in hist)
    top = collections.Counter(h.get("code", "") for h in hist if h.get("code")).most_common(10)
    status = collections.Counter(h.get("status", "") or "기타" for h in hist)
    week = sum(per_day.get(d, 0) for d in days[-7:])

    with ui.column().classes("w-full max-w-6xl gap-3"):
        ui.label("대시보드").classes("kcm-h1")
        def pct_of(h: dict) -> float | None:
            try:
                return float(str(h.get("pct", "")).replace("%", ""))
            except ValueError:
                return None
        pcts = [p for p in (pct_of(h) for h in hist) if p is not None]
        avg = sum(pcts) / len(pcts) if pcts else 0.0
        month = sum(1 for h in hist if str(h.get("at", ""))[:7] == today.strftime("%Y-%m"))
        active = sum(1 for a_ in accounts if a_.get("active", True))
        rings = [("이번 달 코딩", month, min(100, month), "이번 달 기록 건수"),
                 ("평균 정확도", f"{avg:.1f}%", avg, "AI 제안·생성 기록 기준"),
                 ("최근 7일", week, min(100, week * 5), "최근 7일 코딩 건수"),
                 ("활성 사용자", active, (active / len(accounts) * 100) if accounts else 0, f"등록 {len(accounts)}명 중")]
        with ui.element("div").classes("w-full").style("display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px"):
            for label, shown, ratio, sub in rings:
                with ui.column().classes("kcm-card items-center gap-1").style("padding:14px"):
                    ui.echart({
                        "series": [{"type": "pie", "radius": ["68%", "86%"], "silent": True, "label": {"show": False},
                                    "data": [{"value": ratio, "itemStyle": {"color": "#6a91b7"}},
                                             {"value": max(0, 100 - ratio), "itemStyle": {"color": "rgba(135,148,160,.25)"}}]}],
                        "graphic": [{"type": "text", "left": "center", "top": "center",
                                     "style": {"text": str(shown), "fill": "#8794a0", "fontSize": 22, "fontWeight": 600}}],
                    }).style("height:110px;width:110px")
                    ui.label(label).style("font-family:var(--font-heading);font-weight:600;font-size:16px")
                    ui.label(sub).classes("text-muted").style("font-size:11px")
        with ui.row().classes("w-full gap-3 no-wrap items-stretch"):
            with ui.column().classes("kcm-card grow").style("min-width:0"):
                ui.label("최근 14일 코딩 건수").classes("font-semibold")
                ui.echart({
                    "grid": {"left": 36, "right": 12, "top": 16, "bottom": 28},
                    "xAxis": {"type": "category", "data": [d[5:] for d in days]},
                    "yAxis": {"type": "value", "minInterval": 1},
                    "series": [{"type": "bar", "data": [per_day.get(d, 0) for d in days], "itemStyle": {"color": "#6a91b7"}}],
                }).classes("w-full").style("height:240px")
            with ui.column().classes("kcm-card grow").style("min-width:0"):
                ui.label("많이 쓰인 코드 TOP 10").classes("font-semibold")
                ui.echart({
                    "grid": {"left": 70, "right": 16, "top": 8, "bottom": 20},
                    "xAxis": {"type": "value", "minInterval": 1},
                    "yAxis": {"type": "category", "inverse": True, "data": [c for c, _ in top]},
                    "series": [{"type": "bar", "data": [n for _, n in top], "itemStyle": {"color": "#8fb2d4"}}],
                }).classes("w-full").style("height:240px")
        with ui.column().classes("kcm-card w-full gap-1"):
            ui.label("상태별 건수").classes("font-semibold")
            ui.label("  ·  ".join(f"{k} {v:,}건" for k, v in status.most_common()) or "데이터 없음").classes("text-sm text-muted")
            ui.label("이력은 사용자(PC)별로 저장된 기록을 모두 합산한 값입니다.").classes("text-xs text-muted")
