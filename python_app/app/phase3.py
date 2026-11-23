"""3단계 화면 — 코딩 이력 · 개인 코드집 · 대시보드 (+ 검색 결과 저장 도우미)"""
from __future__ import annotations

import collections
import datetime as dt
import time

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
            items = store.get(_scope(), "history", []) or []
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
            items = store.get(_scope(), "favs", []) or []
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
_HIST_CACHE: dict = {"at": 0.0, "rows": []}


def _all_histories() -> list[dict]:
    """모든 사용자의 코딩 이력 — 집계라서 60초 동안은 이전 결과를 다시 쓴다 (대시보드를 열 때마다 전부 내려받지 않게)."""
    if time.time() - _HIST_CACHE["at"] < 60 and _HIST_CACHE["rows"]:
        return _HIST_CACHE["rows"]
    try:
        r = store.client.get(f"{store.SUPABASE_URL}/rest/v1/kcm_store",
                             params={"key": "eq.history", "select": "scope,data"}, timeout=60)
        r.raise_for_status()
    except Exception:  # noqa: BLE001        # 공용 DB가 안 될 때는 이전 집계(없으면 빈 목록)로 대시보드를 연다
        return _HIST_CACHE["rows"]
    out = []
    for row in r.json():
        for h in row.get("data") or []:
            if isinstance(h, dict):
                out.append({**h, "_scope": row["scope"]})
    _HIST_CACHE.update(at=time.time(), rows=out)
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

    ui.add_css("""
.kcm-kpi{background:linear-gradient(160deg,var(--surface),var(--surface-2));border:1px solid var(--card-line);border-radius:14px;
 box-shadow:0 1px 0 rgba(255,255,255,.7) inset,0 12px 28px -10px rgba(20,40,70,.28),0 3px 8px rgba(20,40,70,.10);
 transition:transform .2s ease,box-shadow .2s ease}
.kcm-kpi:hover{transform:translateY(-4px);box-shadow:0 1px 0 rgba(255,255,255,.8) inset,0 20px 38px -10px rgba(20,40,70,.36),0 5px 12px rgba(20,40,70,.14)}
body.body--dark .kcm-kpi{box-shadow:0 1px 0 rgba(255,255,255,.07) inset,0 14px 30px -10px rgba(0,0,0,.7),0 3px 8px rgba(0,0,0,.35)}
body.body--dark .kcm-kpi:hover{box-shadow:0 1px 0 rgba(255,255,255,.10) inset,0 22px 40px -10px rgba(0,0,0,.85),0 5px 12px rgba(0,0,0,.45)}
.kcm-chartcard{background:linear-gradient(180deg,var(--surface),var(--surface-2));border-radius:16px;
 box-shadow:0 1px 0 rgba(255,255,255,.6) inset,0 16px 34px -14px rgba(20,40,70,.30),0 3px 8px rgba(20,40,70,.08)}
body.body--dark .kcm-chartcard{box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 36px -14px rgba(0,0,0,.75),0 3px 8px rgba(0,0,0,.35)}
.kcm-chartcard .ctitle{font-family:var(--font-heading);font-weight:600;font-size:18px;letter-spacing:.01em}
""")
    GRAD = lambda c1, c2: {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": c1}, {"offset": 1, "color": c2}]}
    AX = {"color": "#8794a0", "fontSize": 11}
    SPLIT = {"lineStyle": {"color": "rgba(135,148,160,.22)", "type": "dashed"}}

    # 세로 입체 막대 — 앞면 · 옆면 · 윗면을 다각형으로 그리고 그림자를 준다
    CUBE_V = """(params, api) => {
      const xv = api.value(0), yv = api.value(1);
      const top = api.coord([xv, yv]), base = api.coord([xv, 0]);
      const bw = api.size([1, 0])[0] * 0.46, d = Math.min(bw * 0.4, 14);
      const l = top[0] - bw / 2, r = top[0] + bw / 2, t = top[1], b = base[1];
      const txt = {type: 'text', style: {text: String(yv), x: top[0] + d / 2, y: (yv > 0 ? t - d : b) - 6, textAlign: 'center',
        textVerticalAlign: 'bottom', fill: '#8794a0', font: '600 12px sans-serif'}};
      if (yv <= 0) return txt;
      return {type: 'group', children: [
        {type: 'polygon', shape: {points: [[l, t], [r, t], [r, b], [l, b]]}, style: {fill: {type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{offset: 0, color: '#8fb2d4'}, {offset: 1, color: '#4a7096'}]}, shadowBlur: 16, shadowColor: 'rgba(0,0,0,.45)',
          shadowOffsetX: 6, shadowOffsetY: 8}},
        {type: 'polygon', shape: {points: [[r, t], [r + d, t - d], [r + d, b - d], [r, b]]}, style: {fill: '#2f4a65'}},
        {type: 'polygon', shape: {points: [[l, t], [l + d, t - d], [r + d, t - d], [r, t]]}, style: {fill: '#c4dcf0'}},
        txt]};
    }"""
    # 가로 입체 막대
    CUBE_H = """(params, api) => {
      const yi = api.value(0), v = api.value(1);
      const end = api.coord([v, yi]), base = api.coord([0, yi]);
      const bh = api.size([0, 1])[1] * 0.5, d = Math.min(bh * 0.45, 9);
      const l = base[0], r = end[0], t = end[1] - bh / 2, b = end[1] + bh / 2;
      const txt = {type: 'text', style: {text: String(v), x: r + d + 6, y: end[1] - d / 2, textAlign: 'left', textVerticalAlign: 'middle',
        fill: '#8794a0', font: '600 12px sans-serif'}};
      if (r - l < 1) return txt;
      return {type: 'group', children: [
        {type: 'polygon', shape: {points: [[l, t], [r, t], [r, b], [l, b]]}, style: {fill: {type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{offset: 0, color: '#4a7096'}, {offset: 1, color: '#8fb2d4'}]}, shadowBlur: 14, shadowColor: 'rgba(0,0,0,.4)',
          shadowOffsetX: 5, shadowOffsetY: 7}},
        {type: 'polygon', shape: {points: [[r, t], [r + d, t - d], [r + d, b - d], [r, b]]}, style: {fill: '#2f4a65'}},
        {type: 'polygon', shape: {points: [[l, t], [l + d, t - d], [r + d, t - d], [r, t]]}, style: {fill: '#c4dcf0'}},
        txt]};
    }"""

    with ui.column().classes("w-full max-w-6xl gap-4"):
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
        rings = [("이번 달 코딩", month, min(100, month), "이번 달 기록 건수", ("#a9c6e3", "#4a7096")),
                 ("평균 정확도", f"{avg:.1f}%", avg, "AI 제안·생성 기록 기준", ("#9fe0c0", "#2f8f6a")),
                 ("최근 7일", week, min(100, week * 5), "최근 7일 코딩 건수", ("#f3d38f", "#c98a2b")),
                 ("활성 사용자", active, (active / len(accounts) * 100) if accounts else 0, f"등록 {len(accounts)}명 중", ("#c9b6f0", "#7a58c9"))]
        with ui.element("div").classes("w-full").style("display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px"):
            for label, shown, ratio, sub, (c1, c2) in rings:
                with ui.column().classes("kcm-kpi items-center gap-1").style("padding:16px 14px"):
                    ui.echart({
                        "animationDuration": 1100, "animationEasing": "cubicOut",
                        "series": [
                            # 바닥 홈(트랙) — 안쪽 그림자로 파인 느낌
                            {"type": "pie", "radius": ["66%", "88%"], "silent": True, "label": {"show": False}, "animation": False,
                             "data": [{"value": 1, "itemStyle": {"color": "rgba(135,148,160,.22)", "shadowBlur": 10, "shadowColor": "rgba(0,0,0,.35)",
                                                                  "shadowOffsetY": 3}}]},
                            # 진행 링 — 그라데이션 + 빛 번짐
                            {"type": "pie", "radius": ["66%", "88%"], "silent": True, "label": {"show": False}, "startAngle": 90, "clockwise": True,
                             "itemStyle": {"borderRadius": 8},
                             "data": [{"value": max(ratio, 0.0001), "itemStyle": {"color": GRAD(c1, c2), "shadowBlur": 22, "shadowColor": c2,
                                                                                    "shadowOffsetY": 4}},
                                      {"value": max(0, 100 - ratio), "itemStyle": {"color": "transparent"}}]}],
                        "graphic": [{"type": "text", "left": "center", "top": "center",
                                     "style": {"text": str(shown), "fill": "#8794a0", "fontSize": 24, "fontWeight": 700,
                                               "shadowBlur": 6, "shadowColor": "rgba(0,0,0,.35)", "shadowOffsetY": 2}}],
                    }).style("height:124px;width:124px")
                    ui.label(label).style("font-family:var(--font-heading);font-weight:600;font-size:17px")
                    ui.label(sub).classes("text-muted").style("font-size:11px")

        with ui.row().classes("w-full gap-4 items-stretch").style("flex-wrap:wrap"):
            with ui.column().classes("kcm-chartcard grow gap-1").style("min-width:min(100%,380px);flex:1 1 480px;padding:18px"):
                ui.label("최근 14일 코딩 건수").classes("ctitle")
                ui.echart({
                    "animationDuration": 900, "animationEasing": "cubicOut",
                    "grid": {"left": 34, "right": 22, "top": 26, "bottom": 28},
                    "xAxis": {"type": "category", "data": [d[5:] for d in days], "axisLine": {"show": False}, "axisTick": {"show": False}, "axisLabel": AX},
                    "yAxis": {"type": "value", "minInterval": 1, "axisLabel": AX, "splitLine": SPLIT},
                    "series": [{"type": "custom", ":renderItem": CUBE_V, "encode": {"x": 0, "y": 1},
                                "data": [[i, per_day.get(d, 0)] for i, d in enumerate(days)]}],
                }).classes("w-full").style("height:280px")
            with ui.column().classes("kcm-chartcard grow gap-1").style("min-width:min(100%,380px);flex:1 1 480px;padding:18px"):
                ui.label("많이 쓰인 코드 TOP 10").classes("ctitle")
                ui.echart({
                    "animationDuration": 900, "animationEasing": "cubicOut",
                    "grid": {"left": 64, "right": 40, "top": 14, "bottom": 22},
                    "xAxis": {"type": "value", "minInterval": 1, "axisLabel": AX, "splitLine": SPLIT},
                    "yAxis": {"type": "category", "inverse": True, "data": [c for c, _ in top], "axisLine": {"show": False},
                              "axisTick": {"show": False}, "axisLabel": {**AX, "fontFamily": "monospace", "fontWeight": 600}},
                    "series": [{"type": "custom", ":renderItem": CUBE_H, "encode": {"x": 1, "y": 0},
                                "data": [[i, n] for i, (_, n) in enumerate(top)]}],
                }).classes("w-full").style("height:280px")

        with ui.column().classes("kcm-chartcard w-full gap-1").style("padding:18px"):
            ui.label("상태별 건수").classes("ctitle")
            palette = [("#a9c6e3", "#4a7096"), ("#9fe0c0", "#2f8f6a"), ("#f3d38f", "#c98a2b"), ("#c9b6f0", "#7a58c9"), ("#f5a8a8", "#c24d4d")]
            data = [{"name": k, "value": v, "itemStyle": {"color": GRAD(*palette[i % len(palette)]), "shadowBlur": 16,
                                                           "shadowColor": palette[i % len(palette)][1], "shadowOffsetY": 5}}
                    for i, (k, v) in enumerate(status.most_common(5))]
            if data:
                ui.echart({
                    "animationDuration": 1000, "animationEasing": "cubicOut",
                    "tooltip": {"trigger": "item", "formatter": "{b}: {c}건 ({d}%)"},
                    "legend": {"orient": "vertical", "right": 10, "top": "middle", "textStyle": {"color": "#8794a0"}},
                    "series": [{"type": "pie", "radius": ["42%", "72%"], "center": ["36%", "50%"], "roseType": "radius",
                                "itemStyle": {"borderRadius": 8, "borderColor": "rgba(0,0,0,0)", "borderWidth": 2},
                                "label": {"color": "#8794a0", "formatter": "{b}\n{c}건"}, "data": data}],
                }).classes("w-full").style("height:260px")
            else:
                ui.label("데이터 없음").classes("text-sm text-muted")
            ui.label("이력은 사용자(PC)별로 저장된 기록을 모두 합산한 값입니다.").classes("text-xs text-muted")
