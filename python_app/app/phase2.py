"""2단계 화면 — 조건 설정 · 3권 색인 검색 · AI 자동 코딩"""
from __future__ import annotations

from nicegui import run, ui

from . import gemini, store
from .main import get_index, layout, require_login, user
from .search import norm

DEPTS = ["전체 진료과", "내과", "순환기내과", "신경과", "호흡기내과", "정형외과", "외과", "응급의학과", "가정의학과"]
PURPOSES = ["주진단", "부진단", "외래 청구", "사망원인"]
VERS = ["KCD 8차", "KCD 7차"]
ACCS = {"0": "전체", "50": "50% 이상", "70": "70% 이상", "85": "85% 이상"}
DEFAULT_COND = {"dept": "전체 진료과", "purpose": "주진단", "ver": "KCD 8차", "minAcc": "0"}


def load_cond() -> dict:
    u = user()
    data = store.get(f"user:{u['id']}", "cond", {}) or {}
    return {**DEFAULT_COND, **data}


# ───────────── 조건 설정 ─────────────
@ui.page("/cond")
def cond_page() -> None:
    if not require_login():
        return
    layout("cond")
    cond = load_cond()
    u = user()

    def save() -> None:
        store.put(f"user:{u['id']}", "cond", cond, by=u["id"])
        ui.notify("저장했습니다.", type="positive")

    with ui.column().classes("w-full max-w-3xl gap-3"):
        ui.label("조건 설정").classes("text-xl font-bold")
        ui.label("검색 · 코드 생성, AI 자동 코딩에 적용할 진료과, 코딩 목적, KCD 버전, 정확도를 정합니다.").classes("text-sm text-muted")
        with ui.column().classes("kcm-card w-full gap-3"):
            ui.select(DEPTS, label="진료과", value=cond["dept"], on_change=lambda e: cond.update(dept=e.value)).classes("w-full")
            ui.select(PURPOSES, label="코딩 목적", value=cond["purpose"], on_change=lambda e: cond.update(purpose=e.value)).classes("w-full")
            with ui.row().classes("w-full no-wrap gap-3"):
                ui.select(VERS, label="KCD", value=cond["ver"], on_change=lambda e: cond.update(ver=e.value)).classes("w-1/2")
                ui.select(ACCS, label="정확도", value=cond["minAcc"], on_change=lambda e: cond.update(minAcc=e.value)).classes("w-1/2")
            ui.button("저장", on_click=save).props("no-caps")


# ───────────── 3권 색인 검색 ─────────────
def _node(n: dict, path: str) -> dict:
    mod = n.get("mod") or n.get("term") or ""
    label = n.get("label") or ""
    code = n.get("code") or ""
    text = f"{mod}" + (f" — {label}" if label and label != mod else "")
    nid = f"{path}/{mod}:{code}"
    kids = n.get("kids") or []
    node = {"id": nid, "label": text, "code": code}
    if isinstance(kids, list) and kids:
        node["children"] = [_node(k, nid) for k in kids]
    return node


@ui.page("/index")
def index_page() -> None:
    if not require_login():
        return
    layout("index")
    trees = store.get("global", "ltTrees", []) or []
    trees = [t for t in trees if isinstance(t, dict) and not t.get("retired")]
    idx = get_index()
    names = {r.code: r.ko for r in idx.rows}

    with ui.column().classes("w-full max-w-6xl gap-3"):
        ui.label("3권 색인 검색").classes("text-xl font-bold")
        ui.label(f"색인 주용어 {len(trees)}개 — 주용어를 고르면 수식어 단계별로 KCD 코드를 따라갈 수 있습니다.").classes("text-sm text-muted")
        with ui.row().classes("w-full no-wrap gap-4 items-start"):
            with ui.column().classes("kcm-card gap-2").style("width:300px;flex:none"):
                q = ui.input(placeholder="주용어·동의어·코드 검색").props("outlined dense clearable").classes("w-full")
                lst = ui.column().classes("w-full gap-0").style("max-height:60vh;overflow:auto")
            detail = ui.column().classes("kcm-card gap-2 grow").style("min-width:0")

        def show(t: dict) -> None:
            detail.clear()
            with detail:
                head = t.get("term", "")
                code = t.get("code", "")
                ui.label(head).classes("text-lg font-bold")
                if t.get("syn"):
                    ui.label("동의어: " + ", ".join(t["syn"])).classes("text-sm text-muted")
                if code:
                    ui.label(f"대표 코드 {code} · {names.get(code, '')}").style("color:var(--accent-hi)")
                kids = t.get("kids") or []
                if kids:
                    nodes = [_node(k, head) for k in kids]
                    tree = ui.tree(nodes, node_key="id", label_key="label").props("default-expand-all dark").classes("w-full")
                    tree.add_slot("default-header", r'''
                        <div class="row items-center no-wrap" style="gap:8px">
                          <span>{{ props.node.label }}</span>
                          <q-badge v-if="props.node.code" color="blue-grey-8" :label="props.node.code" />
                        </div>''')
                else:
                    ui.label("세부 수식어가 없습니다.").classes("text-muted")

        def refresh() -> None:
            s = norm(q.value or "")
            lst.clear()
            hits = []
            for t in trees:
                keys = [norm(t.get("term", "")), norm(t.get("code", ""))] + [norm(x) for x in (t.get("syn") or [])]
                if not s or any(s in k for k in keys):
                    hits.append(t)
            with lst:
                for t in hits[:300]:
                    ui.button(t.get("term", ""), on_click=lambda _, t=t: show(t)).props("flat no-caps align=left dense").classes("w-full")
                if not hits:
                    ui.label("결과 없음").classes("text-muted text-sm")

        q.on("update:model-value", refresh, throttle=0.2)
        refresh()
        if trees:
            show(trees[0])


# ───────────── AI 자동 코딩 ─────────────
@ui.page("/nlp")
def nlp_page() -> None:
    if not require_login():
        return
    layout("nlp")
    idx = get_index()
    names = {r.code.upper(): r.ko for r in idx.rows}
    cond = load_cond()

    with ui.column().classes("w-full max-w-5xl gap-3"):
        ui.label("AI 자동 코딩").classes("text-xl font-bold")
        ui.label(f"의무기록 문장을 붙여 넣으면 Gemini가 KCD 후보를 제안하고, 상병마스터({len(idx):,}건)로 코드가 실제 존재하는지 검증합니다. "
                 f"적용 조건: {cond['dept']} · {cond['purpose']}").classes("text-sm text-muted")
        box = ui.textarea(placeholder="예) 70세 남자, 기침·발열로 내원, 흉부 X-ray상 우하엽 폐렴, 고혈압 약 복용 중").props("outlined autogrow").classes("w-full").style("min-height:140px")
        status = ui.label("").classes("text-sm text-muted")
        out = ui.column().classes("w-full gap-2")

        async def analyze() -> None:
            text = (box.value or "").strip()
            if len(text) < 5:
                ui.notify("의무기록 내용을 입력하세요.", type="warning")
                return
            btn.disable()
            status.set_text("AI가 분석 중입니다…")
            out.clear()
            try:
                res = await run.io_bound(gemini.suggest, text, cond["dept"], cond["purpose"])
            except Exception as ex:  # noqa: BLE001
                status.set_text(f"실패 — {ex}")
                btn.enable()
                return
            btn.enable()
            codes = res.get("codes", [])
            min_acc = int(cond["minAcc"])
            shown = [c for c in codes if int(c.get("confidence", 0)) >= min_acc]
            status.set_text(f"후보 {len(shown)}건" + (f" (정확도 {min_acc}% 미만 {len(codes) - len(shown)}건 숨김)" if len(shown) != len(codes) else ""))
            with out:
                for c in shown:
                    code = str(c.get("code", "")).strip().upper()
                    known = names.get(code)
                    with ui.row().classes("kcm-card w-full items-start no-wrap gap-4"):
                        ui.label(code).classes("text-lg font-bold").style("min-width:72px;color:var(--accent-hi)")
                        with ui.column().classes("gap-1 grow"):
                            ui.label(known or c.get("name_ko", "")).classes("font-semibold")
                            ui.label(c.get("reason", "")).classes("text-sm text-muted")
                            if not known:
                                ui.label("⚠ 상병마스터에 없는 코드입니다 — 직접 확인하세요.").classes("text-sm").style("color:#e0a458")
                        with ui.column().classes("items-end gap-1"):
                            ui.label(f"{c.get('confidence', 0)}%").classes("font-bold")
                            if c.get("primary"):
                                ui.badge("주진단 후보")
                            def save_fav(code=code, known=known, c=c) -> None:
                                from .phase3 import add_fav
                                ui.notify("코드집에 담았습니다." if add_fav(code, known or c.get("name_ko", "")) else "이미 코드집에 있습니다.")

                            def save_hist(code=code, known=known, c=c) -> None:
                                from .phase3 import add_history
                                add_history((box.value or "")[:60], code, known or c.get("name_ko", ""), f"{c.get('confidence', 0)}%", "AI 제안")
                                ui.notify("이력에 기록했습니다.", type="positive")
                            with ui.row().classes("gap-1"):
                                ui.button(icon="star", on_click=save_fav).props("flat round dense").tooltip("코드집에 담기")
                                ui.button(icon="history", on_click=save_hist).props("flat round dense").tooltip("이력에 기록")
                if res.get("caution"):
                    ui.label("주의: " + res["caution"]).classes("text-sm text-muted")

        btn = ui.button("AI 분석", on_click=analyze).props("no-caps")
