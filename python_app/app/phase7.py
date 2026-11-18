"""7단계 — 용어 사전 관리 (시스템 관리자): 못 찾은 검색어 → 사전에 등록, 등록 용어 편집, 내장 사전 보기"""
from __future__ import annotations

import html

from nicegui import run, ui

from . import dictionary as dic
from . import lexicon
from .main import get_index, layout, require_login, user
from .search import norm

CSS = """
.kcm-drow{display:grid;grid-template-columns:minmax(120px,1.1fr) minmax(0,2fr) 150px max-content;gap:10px;align-items:center;
  padding:9px 12px;border-bottom:1px solid var(--color-divider);width:100%;box-sizing:border-box}
.kcm-drow.head{font-size:11px;color:var(--muted);font-weight:600;background:var(--surface-2);border-radius:8px 8px 0 0}
.kcm-drow .alt{display:inline-block;margin:2px 4px 2px 0;padding:1px 8px;border-radius:999px;font-size:12px;background:var(--a200);
  border:1px solid var(--a300);color:var(--a900)}
.kcm-drow .miss{font-size:11px;color:var(--warn)}
@media (max-width:760px){.kcm-drow{grid-template-columns:1fr}.kcm-drow.head{display:none}}
"""


@ui.page("/dict")
def dict_page() -> None:
    if not require_login(("sysadmin",)):
        return
    layout("dict")
    ui.add_css(CSS)
    me = user()["id"]
    st = {"q": "", "bq": ""}

    with ui.column().classes("w-full gap-4"):
        ui.label("용어 사전").classes("kcm-h1")
        ui.label("검색이 못 찾은 말(구어·약어·영문)을 공식 상병명이나 코드와 연결해 두면, 다음부터 모든 사용자가 바로 찾을 수 있습니다. "
                 "AI가 풀어 준 해석을 저장한 항목도 여기서 고칠 수 있습니다.").classes("text-muted").style("font-size:13px")

        # ───────── 못 찾은 검색어
        with ui.column().classes("kcm-card w-full gap-2"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("못 찾은 검색어").classes("kicker")
                ui.label("결과가 없거나 일부만 맞았던 검색어 · 많이 검색된 순").classes("text-muted").style("font-size:12px")
            miss_box = ui.column().classes("w-full gap-0")

        # ───────── 등록된 용어
        with ui.column().classes("kcm-card w-full gap-2"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("등록된 용어").classes("kicker")
                ui.button("용어 추가", icon="add", on_click=lambda: edit_dialog("", [])).props("unelevated no-caps dense color=primary")
            q_inp = ui.input(placeholder="입력어·공식 명칭으로 찾기").props("dense outlined clearable").classes("w-full")
            ent_box = ui.column().classes("w-full gap-0")

        # ───────── 내장 사전
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("내장 사전 (읽기 전용)").classes("kicker")
            ui.label(f"기본 제공 {len(lexicon.LEX):,}개 입력어. 같은 입력어를 위에서 등록하면 등록한 내용이 먼저 적용됩니다.").classes("text-muted").style("font-size:12px")
            b_inp = ui.input(placeholder="내장 사전에서 찾기 (예: 디스크, htn)").props("dense outlined clearable").classes("w-full")
            built_box = ui.column().classes("w-full gap-0")

    def alts_html(alts: list[str]) -> str:
        return "".join(f'<span class="alt">{html.escape(a)}</span>' for a in alts)

    def render_missed() -> None:
        miss_box.clear()
        m = sorted(dic.missed().items(), key=lambda kv: (-int(kv[1].get("n", 0)), kv[1].get("last", "")), reverse=False)
        with miss_box:
            if not m:
                ui.label("기록된 검색어가 없습니다. 사용자가 검색해서 못 찾은 말이 여기에 쌓입니다.").classes("text-muted").style("font-size:13px;padding:8px")
                return
            with ui.element("div").classes("kcm-drow head"):
                for t in ("검색어", "횟수", "마지막", ""):
                    ui.label(t)
            for q, v in m[:50]:
                with ui.element("div").classes("kcm-drow"):
                    ui.label(q).style("font-weight:700")
                    ui.label(f"{v.get('n', 1)}회").classes("text-muted").style("font-size:12px")
                    ui.label(v.get("last", "")).classes("text-muted").style("font-size:12px")
                    with ui.row().classes("gap-1 no-wrap"):
                        ui.button("사전에 등록", icon="library_add", color=None, on_click=lambda _, q=q: edit_dialog(q, [])).props(
                            "unelevated dense no-caps").classes("kcm-act pri szs")
                        ui.button("지우기", icon="close", color=None, on_click=lambda _, q=q: forget(q)).props(
                            "unelevated dense no-caps").classes("kcm-act bad szs").tooltip("사전에 넣을 필요가 없는 검색어")
            if len(m) > 50:
                ui.label(f"상위 50개만 표시 · 전체 {len(m)}개").classes("text-muted").style("font-size:12px;padding:6px 12px")

    def forget(q: str) -> None:
        dic.forget_missed(q, me)
        render_missed()

    def render_entries() -> None:
        ent_box.clear()
        f = norm(q_inp.value or "")
        items = sorted(dic.entries().items(), key=lambda kv: kv[1].get("at", ""), reverse=True)
        if f:
            items = [(k, v) for k, v in items if f in norm(k) or any(f in norm(a) for a in v.get("alts", []))]
        with ent_box:
            if not items:
                ui.label("등록된 용어가 없습니다." if not f else "맞는 용어가 없습니다.").classes("text-muted").style("font-size:13px;padding:8px")
                return
            with ui.element("div").classes("kcm-drow head"):
                for t in ("입력어", "공식 명칭 · 코드", "등록", ""):
                    ui.label(t)
            for k, v in items[:200]:
                with ui.element("div").classes("kcm-drow"):
                    ui.label(k).style("font-weight:700")
                    ui.html(alts_html(v.get("alts", [])))
                    ui.label(f"{v.get('src', '')} · {v.get('by', '')} · {v.get('at', '')}").classes("text-muted").style("font-size:11px")
                    with ui.row().classes("gap-1 no-wrap"):
                        ui.button("편집", icon="edit", color=None, on_click=lambda _, k=k, v=v: edit_dialog(k, v.get("alts", []))).props(
                            "unelevated dense no-caps").classes("kcm-act pri szs")
                        ui.button("삭제", icon="delete_outline", color=None, on_click=lambda _, k=k: remove(k)).props(
                            "unelevated dense no-caps").classes("kcm-act bad szs")

    def remove(k: str) -> None:
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("gap:12px"):
            ui.label(f"‘{k}’ 항목을 삭제할까요?").style("font-weight:600")
            ui.label("삭제해도 내장 사전의 같은 입력어는 그대로 남습니다.").classes("text-muted").style("font-size:12px")
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")

                def ok() -> None:
                    dic.delete_entry(k, me)
                    dlg.close()
                    ui.notify("삭제했습니다.")
                    render_entries()
                ui.button("삭제", on_click=ok).props("unelevated no-caps color=negative")
        dlg.open()

    def edit_dialog(key: str, alts: list[str]) -> None:
        idx = get_index()
        with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(640px,94vw);gap:12px"):
            ui.label("용어 등록" if not key or key not in dic.entries() else "용어 편집").style(
                "font-family:var(--font-heading);font-weight:600;font-size:20px")
            k_inp = ui.input("입력어 (사용자가 치는 말)", value=key, placeholder="예: 허리디스크, HTN, hypertension").props("dense outlined").classes("w-full")
            a_inp = ui.textarea("공식 상병명 또는 코드 (쉼표·줄바꿈으로 구분)", value=", ".join(alts),
                                placeholder="예: 추간판장애, M51   —  코드는 입력어를 통째로 쳤을 때만 적용됩니다").props("dense outlined autogrow").classes("w-full")
            prev = ui.column().classes("w-full gap-1").style("font-size:12px")

            def preview() -> None:
                prev.clear()
                parts = dic.parse_alts(a_inp.value or "")
                with prev:
                    if not parts:
                        ui.label("공식 명칭이나 코드를 입력하면 상병마스터에서 몇 건 찾아지는지 보여 줍니다.").classes("text-muted")
                        return
                    for a in parts:
                        hits = idx.search(a, 3)
                        n = len(idx.search(a))
                        if n:
                            ui.label(f"✔ {a} → {n}건 (예: {', '.join(f'{r.code} {r.ko}' for r in hits[:2])})").style("color:var(--ok)")
                        else:
                            ui.label(f"⚠ {a} → 상병마스터에서 찾아지지 않습니다. 공식 명칭이나 코드를 확인하세요.").style("color:var(--warn)")
            a_inp.on("blur", preview)
            ui.button("찾아지는지 확인", icon="fact_check", on_click=preview).props("flat dense no-caps")
            if alts:
                preview()

            def save() -> None:
                try:
                    dic.save_entry(k_inp.value or "", dic.parse_alts(a_inp.value or ""), me, "수동")
                except ValueError as ex:
                    ui.notify(str(ex), type="warning")
                    return
                dlg.close()
                ui.notify("용어 사전에 저장했습니다. 바로 검색에 적용됩니다.", type="positive")
                render_missed()
                render_entries()
            with ui.row().classes("w-full justify-end"):
                ui.button("취소", on_click=dlg.close).props("flat no-caps")
                ui.button("저장", on_click=save).props("unelevated no-caps color=primary")
        dlg.open()

    def render_built() -> None:
        built_box.clear()
        f = norm(b_inp.value or "")
        with built_box:
            if not f:
                ui.label("검색어를 입력하세요.").classes("text-muted").style("font-size:12px;padding:6px")
                return
            hit = [(k, v) for k, v in lexicon.LEX.items() if f in k or any(f in norm(a) for a in v)][:30]
            if not hit:
                ui.label("내장 사전에 없는 말입니다.").classes("text-muted").style("font-size:12px;padding:6px")
            for k, v in hit:
                with ui.element("div").classes("kcm-drow"):
                    ui.label(k).style("font-weight:700")
                    ui.html(alts_html(v))
                    ui.label("")
                    ui.button("복사해 등록", icon="content_copy", color=None, on_click=lambda _, k=k, v=v: edit_dialog(k, list(v))).props(
                        "unelevated dense no-caps").classes("kcm-act pri szs")

    q_inp.on("update:model-value", render_entries, throttle=0.3)
    b_inp.on("update:model-value", render_built, throttle=0.3)
    render_missed()
    render_entries()
    render_built()
