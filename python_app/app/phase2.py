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


# ───────────── AI 자동 코딩 (문서 판독 · 환자 조건 · 청구 목록 · 룰 점검) ─────────────
SEV_COLOR = {"삭감": "#e57373", "조정": "#e0a458", "확인": "#6a91b7"}


@ui.page("/nlp")
def nlp_page() -> None:
    if not require_login():
        return
    from . import ocr, rules
    from .phase4 import parse_age

    layout("nlp")
    idx = get_index()
    fam = rules.Family(idx)
    names = {r.code.upper(): r.ko for r in idx.rows}
    cond = load_cond()
    st = {"claim": [], "docs": []}   # claim: [{code, kind}], docs: [{name, mime, data, sel}]

    with ui.column().classes("w-full max-w-6xl gap-3"):
        ui.label("AI 자동 코딩 · 임상 텍스트 분석").classes("text-xl font-bold")
        ui.label(f"의무기록 문장을 붙여 넣거나 문서를 첨부해 판독하면 Gemini가 KCD 후보를 제안하고, 상병마스터({len(idx):,}건)로 검증합니다. "
                 f"적용 조건: {cond['dept']} · {cond['purpose']}").classes("text-sm text-muted")

        # ── 환자 조건
        with ui.row().classes("kcm-card w-full items-center gap-4"):
            ui.label("환자").classes("font-semibold")
            sex = ui.select({"": "성별 미입력", "M": "남", "F": "여"}, value="", label="성별").props("dense outlined").classes("w-36")
            age = ui.input("연령(세)").props("dense outlined type=number min=0 max=120").classes("w-32")
            ui.label("성별·연령을 넣으면 룰 점검에서 불일치 코드를 찾아 줍니다.").classes("text-xs text-muted")

        # ── 문서 첨부 · 판독
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("문서 첨부 — 소견서 · 진단서 · 진료의뢰서").classes("font-semibold")
            ui.label("PDF · JPG · PNG · TXT (최대 10MB). 판독할 파일만 체크하세요.").classes("text-xs text-muted")
            docs_box = ui.column().classes("w-full gap-1")

            def render_docs() -> None:
                docs_box.clear()
                with docs_box:
                    if not st["docs"]:
                        ui.label("첨부한 파일이 여기에 표시됩니다.").classes("text-sm text-muted")
                    for d in st["docs"]:
                        with ui.row().classes("items-center no-wrap gap-2 w-full"):
                            ui.checkbox(value=d["sel"], on_change=lambda e, d=d: d.update(sel=e.value))
                            ui.label(d["name"]).classes("text-sm grow")
                            ui.label(f"{len(d['data']) / 1024:,.0f} KB · {d['state']}").classes("text-xs text-muted")
                            ui.button(icon="close", on_click=lambda _, d=d: (st["docs"].remove(d), render_docs())).props("flat round dense size=sm")

            async def on_upload(e) -> None:
                f = getattr(e, "file", None)
                name = f.name if f else e.name
                raw = await f.read() if f else e.content.read()
                mime = ocr.guess_mime(name, getattr(f, "content_type", "") if f else getattr(e, "type", ""))
                st["docs"].append({"name": name, "mime": mime, "data": raw, "sel": True, "state": "대기"})
                render_docs()

            up = ui.upload(on_upload=on_upload, multiple=True, auto_upload=True, label="파일 선택 (여러 개 가능)") \
                .props("accept=.pdf,.jpg,.jpeg,.png,.txt flat bordered").classes("w-full")
            up.on("removed", lambda: None)
            with ui.row().classes("items-end gap-3"):
                eng = ui.select(ocr.ENGINES, value="gemini", label="판독 엔진").props("dense outlined").classes("w-72")
                vkey = ui.input("Vision API 키", password=True).props("dense outlined").classes("w-64")
                vkey.bind_visibility_from(eng, "value", backward=lambda v: v == "vision")
                lang = ui.select({"ko+en": "한국어 + 영어", "ko": "한국어", "en": "영어"}, value="ko+en", label="인식 언어").props("dense outlined").classes("w-40")
                ocr_btn = ui.button("판독(OCR) 실행", icon="document_scanner").props("no-caps")

                def clear_docs() -> None:
                    st["docs"].clear()
                    up.reset()
                    render_docs()
                ui.button("첨부 비우기", on_click=clear_docs).props("no-caps flat")
            ui.label("이미지·PDF는 판독을 실행할 때만 서버를 거쳐 선택한 제공자(Gemini 또는 Google)로 전송됩니다. "
                     "환자 식별정보가 포함된 문서의 외부 전송은 원내 개인정보 규정을 먼저 확인하세요.").classes("text-xs text-muted")
            render_docs()

        # ── 본문
        box = ui.textarea(label="의무기록 본문 (입원사유 · 과거력 · 검사 · 치료경과 · 최종진단)",
                          placeholder="예) 70세 남자, 기침·발열로 내원, 흉부 X-ray상 우하엽 폐렴, 고혈압 약 복용 중") \
            .props("outlined autogrow").classes("w-full").style("min-height:140px")

        async def run_ocr() -> None:
            sel = [d for d in st["docs"] if d["sel"]]
            if not sel:
                ui.notify("판독할 파일을 첨부·선택하세요.", type="warning")
                return
            ocr_btn.disable()
            texts = []
            for d in sel:
                d["state"] = "판독 중…"
                render_docs()
                try:
                    t = await run.io_bound(ocr.read_document, d["name"], d["data"], d["mime"], eng.value, vkey.value or "", lang.value)
                    d["state"] = f"완료 · {len(t)}자"
                    texts.append(f"[{d['name']}]\n{t}")
                except Exception as ex:  # noqa: BLE001
                    d["state"] = "실패"
                    ui.notify(str(ex), type="negative", timeout=8000)
                render_docs()
            ocr_btn.enable()
            if texts:
                box.set_value(((box.value or "").rstrip() + "\n\n" if (box.value or "").strip() else "") + "\n\n".join(texts))
                ui.notify("판독 결과를 본문에 추가했습니다. 원문과 대조한 뒤 분석하세요.", type="positive")

        ocr_btn.on_click(run_ocr)
        status = ui.label("").classes("text-sm text-muted")
        btn = ui.button("AI 분석", icon="auto_awesome", on_click=lambda: analyze()).props("no-caps")
        out = ui.column().classes("w-full gap-2")

        # ── 청구 목록 · 룰 점검
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("청구 코드 목록 · 룰 점검").classes("font-semibold")
            ui.label("AI 후보의 ＋ 버튼으로 담거나 직접 입력하세요. 주진단은 1개여야 합니다.").classes("text-xs text-muted")
            with ui.row().classes("items-center gap-2"):
                new_code = ui.input(placeholder="코드 (예: J18.9)").props("dense outlined").classes("w-40")

                def add_manual() -> None:
                    c = (new_code.value or "").strip().upper()
                    if c:
                        add_claim(c)
                        new_code.set_value("")
                new_code.on("keydown.enter", add_manual)
                ui.button("추가", on_click=add_manual).props("no-caps outline dense")
            claim_box = ui.column().classes("w-full gap-1")
            find_box = ui.column().classes("w-full gap-2")
            ui.button("룰 점검 실행", icon="rule", on_click=lambda: run_rules()).props("no-caps")

        def add_claim(code: str) -> None:
            if any(r["code"] == code for r in st["claim"]):
                ui.notify("이미 목록에 있습니다.")
                return
            st["claim"].append({"code": code, "kind": "주진단" if not st["claim"] else "부진단"})
            render_claim()

        def render_claim() -> None:
            claim_box.clear()
            with claim_box:
                if not st["claim"]:
                    ui.label("목록이 비어 있습니다.").classes("text-sm text-muted")
                for r in st["claim"]:
                    with ui.row().classes("items-center no-wrap gap-3 w-full"):
                        ui.label(r["code"]).classes("font-bold").style("min-width:72px;color:var(--accent-hi)")
                        ui.label(names.get(r["code"], "⚠ 코드집에 없음")).classes("text-sm grow")
                        ui.toggle(["주진단", "부진단"], value=r["kind"], on_change=lambda e, r=r: r.update(kind=e.value)).props("dense no-caps")
                        ui.button(icon="delete", on_click=lambda _, r=r: (st["claim"].remove(r), render_claim())).props("flat round dense size=sm")

        def current_ctx() -> tuple[str, int | None]:
            return sex.value or "", parse_age(age.value)

        def run_rules() -> None:
            find_box.clear()
            s, a = current_ctx()
            findings = rules.check_claim(st["claim"], s, a, fam)
            with find_box:
                if not st["claim"]:
                    ui.label("점검할 코드가 없습니다.").classes("text-sm text-muted")
                    return
                if not findings:
                    ui.label("✔ 점검 규칙에 걸리는 항목이 없습니다.").style("color:#7bc48a")
                for f in findings:
                    with ui.column().classes("w-full gap-1").style(
                            f"border-left:4px solid {SEV_COLOR[f['sev']]};padding:6px 12px;background:var(--surface2);border-radius:6px"):
                        ui.label(f"[{f['sev']}] {f['code']} · {f['title']}").classes("font-semibold text-sm")
                        ui.label(f["note"]).classes("text-sm text-muted")
                        if f["alts"] and f["fix"] != "none":
                            with ui.row().classes("items-center gap-2"):
                                ui.label({"replace": "교체:", "remove": "삭제:", "demote": "주진단으로:", "promote": "주진단으로:",
                                          "keepone": "주진단으로 남길 코드:", "dedupe": ""}.get(f["fix"], "")).classes("text-xs text-muted")
                                for alt in f["alts"]:
                                    ui.button(f"{alt} {names.get(alt, '')[:14]}", on_click=lambda _, f=f, alt=alt: apply(f, alt)) \
                                        .props("outline dense no-caps size=sm")
                        elif f["fix"] in ("dedupe",):
                            ui.button("중복 행 삭제", on_click=lambda _, f=f: apply(f, f["code"])).props("outline dense no-caps size=sm")
                        elif f["fix"] == "remove":
                            ui.button(f"{f['code']} 삭제", on_click=lambda _, f=f: apply(f, f["code"])).props("outline dense no-caps size=sm")

        def apply(f: dict, pick: str) -> None:
            st["claim"] = rules.apply_fix(st["claim"], f, pick)
            render_claim()
            run_rules()

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
            s, a = current_ctx()
            with out:
                for c in shown:
                    code = str(c.get("code", "")).strip().upper()
                    known = names.get(code)
                    warn = [m for m in (rules.sex_issue(code, s), rules.age_issue(code, a)) if m]
                    with ui.row().classes("kcm-card w-full items-start no-wrap gap-4"):
                        ui.label(code).classes("text-lg font-bold").style("min-width:72px;color:var(--accent-hi)")
                        with ui.column().classes("gap-1 grow"):
                            ui.label(known or c.get("name_ko", "")).classes("font-semibold")
                            ui.label(c.get("reason", "")).classes("text-sm text-muted")
                            if not known:
                                ui.label("⚠ 상병마스터에 없는 코드입니다 — 직접 확인하세요.").classes("text-sm").style("color:#e0a458")
                            for m in warn:
                                ui.label("⚠ " + m).classes("text-sm").style("color:#e0a458")
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

                            def to_claim(code=code, c=c) -> None:
                                add_claim(code)
                                if c.get("primary") and not any(r["kind"] == "주진단" and r["code"] != code for r in st["claim"]):
                                    for r in st["claim"]:
                                        r["kind"] = "주진단" if r["code"] == code else "부진단"
                                    render_claim()
                            with ui.row().classes("gap-1"):
                                ui.button(icon="playlist_add", on_click=to_claim).props("flat round dense").tooltip("청구 목록에 담기")
                                ui.button(icon="star", on_click=save_fav).props("flat round dense").tooltip("코드집에 담기")
                                ui.button(icon="history", on_click=save_hist).props("flat round dense").tooltip("이력에 기록")
                                ui.button(icon="manage_search", on_click=lambda _, code=code: ui.navigate.to(f"/detail?code={code}")).props("flat round dense").tooltip("정밀 분석")
                if shown:
                    def add_all() -> None:
                        for c in shown:
                            code = str(c.get("code", "")).strip().upper()
                            if code and not any(r["code"] == code for r in st["claim"]):
                                st["claim"].append({"code": code, "kind": "주진단" if (c.get("primary") and not any(r["kind"] == "주진단" for r in st["claim"])) else "부진단"})
                        if st["claim"] and not any(r["kind"] == "주진단" for r in st["claim"]):
                            st["claim"][0]["kind"] = "주진단"
                        render_claim()
                    ui.button("후보 모두 청구 목록에 담기", icon="playlist_add", on_click=add_all).props("no-caps outline")
                if res.get("caution"):
                    ui.label("주의: " + res["caution"]).classes("text-sm text-muted")

        render_claim()
