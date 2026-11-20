"""2단계 화면 — 조건 설정 · 3권 색인 검색 · AI 자동 코딩"""
from __future__ import annotations

import asyncio
import html
import math
import time
import uuid

from fastapi.responses import Response
from nicegui import app, run, ui

from . import gemini, store, terms
from .main import get_index, layout, require_login, user
from .search import norm

# 첨부 파일 미리보기용 임시 보관 (메모리, 2시간) — 추측할 수 없는 토큰 주소로만 열린다
_TMP: dict = {}


def tmp_put(data: bytes, mime: str) -> str:
    now = time.time()
    for k in [k for k, v in _TMP.items() if now - v[2] > 7200]:
        _TMP.pop(k, None)
    token = uuid.uuid4().hex
    _TMP[token] = (data, mime, now)
    return token


@app.get("/_kcm/preview/{token}")
def _preview(token: str) -> Response:
    item = _TMP.get(token)
    if not item:
        return Response(status_code=404)
    return Response(content=item[0], media_type=item[1], headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": "inline"})

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
        ui.notify("조건을 저장했습니다.", type="positive", timeout=1200)

    def setv(key: str):
        def _f(e) -> None:
            cond[key] = e.value
            save()
        return _f

    srcs = cond.get("sources") or ["내부 사전", "AI 해석"]

    def toggle_src(name: str, on: bool) -> None:
        cur = set(cond.get("sources") or ["내부 사전", "AI 해석"])
        (cur.add if on else cur.discard)(name)
        cond["sources"] = sorted(cur)
        save()

    with ui.column().classes("w-full max-w-3xl gap-4"):
        ui.label("조건 설정").classes("kcm-h1")
        ui.label("검색 · 코드 생성에 적용할 진료과, 코딩 목적, KCD 버전, 정확도, 데이터 소스를 정합니다.").classes("text-muted").style("font-size:13px;margin-top:-8px")
        with ui.column().classes("kcm-card w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("조건 설정").style("font-family:var(--font-heading);font-weight:600;font-size:13px;letter-spacing:.08em")
                ui.label("바꾼 조건은 자동 저장되며 검색 · 코드 생성에 바로 적용됩니다.").classes("text-muted").style("font-size:11px")
            ui.select(DEPTS, label="진료과", value=cond["dept"], on_change=setv("dept")).props("dense outlined").classes("w-full")
            ui.select(PURPOSES, label="코딩 목적", value=cond["purpose"], on_change=setv("purpose")).props("dense outlined").classes("w-full")
            with ui.row().classes("w-full no-wrap gap-3"):
                ui.select(VERS, label="KCD", value=cond["ver"], on_change=setv("ver")).props("dense outlined").classes("w-1/2")
                ui.select(ACCS, label="정확도", value=cond["minAcc"], on_change=setv("minAcc")).props("dense outlined").classes("w-1/2")
            ui.label("데이터 소스").classes("text-muted").style("font-size:12px")
            with ui.row().classes("gap-4"):
                for name in ["내부 사전", "AI 해석", "공공 API"]:
                    ui.checkbox(name, value=name in srcs, on_change=lambda e, n=name: toggle_src(n, e.value))
        ui.button("검색 · 코드 생성으로 이동", on_click=lambda: ui.navigate.to("/search")).props("no-caps unelevated color=primary").classes("self-start")

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
    cur = {"t": None}

    with ui.column().classes("w-full max-w-5xl gap-4"):
        ui.label("KCD 제3권 색인 검색").classes("kcm-h1")
        ui.label("선도어를 고르고 수식어(하위어)를 따라가면 최종 분류코드에 도달합니다. 1권 분류표의 분류명이 단계마다 표시됩니다.") \
            .classes("text-muted").style("font-size:13px;margin-top:-8px")
        with ui.column().classes("kcm-card w-full gap-2"):
            ui.label("선도어 (MAIN TERM)").classes("kicker")
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                q = ui.input(placeholder="선도어 찾기 — 예: 골절, 폐렴, 당뇨").props("outlined dense clearable").classes("w-72")
                cnt = ui.label("").classes("text-muted").style("font-size:12px")
            chips = ui.row().classes("w-full gap-2").style("max-height:190px;overflow:auto")
        detail = ui.column().classes("kcm-card w-full gap-2")

        def walk(nodes: list, depth: int) -> None:
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                label = n.get("mod") or n.get("label") or n.get("term") or ""
                code = n.get("code") or ""
                kids = n.get("kids") or []
                with ui.row().classes("w-full items-center justify-between no-wrap").style(
                        f"padding:7px 8px 7px {8 + depth * 20}px;border-bottom:1px solid var(--color-divider)"):
                    ui.label("– " + label).style("font-size:14px;" + ("" if not kids else "font-weight:600"))
                    if code:
                        with ui.row().classes("items-center gap-3 no-wrap"):
                            ui.label(code).classes("mono").style("font-weight:700;color:var(--accent-hi)").on(
                                "click", lambda _, c=code: ui.navigate.to(f"/detail?code={c}")).classes("cursor-pointer")
                            ui.label("하위 있음" if kids else "최종").classes("text-muted").style("font-size:11px;width:52px;text-align:right")
                if isinstance(kids, list) and kids:
                    walk(kids, depth + 1)

        def show(t: dict) -> None:
            cur["t"] = t
            detail.clear()
            with detail:
                code = t.get("code", "")
                with ui.row().classes("w-full items-baseline justify-between no-wrap"):
                    ui.label(f"{t.get('term', '')} (선도어) {code}").classes("kicker")
                ui.label(names.get(code, t.get("term", ""))).style("font-family:var(--font-heading);font-weight:600;font-size:24px")
                if t.get("syn"):
                    ui.label("동의어: " + ", ".join(t["syn"])).classes("text-muted").style("font-size:12px")
                kids = t.get("kids") or []
                if kids:
                    walk(kids, 0)
                else:
                    ui.label("세부 수식어가 없습니다.").classes("text-muted")
            refresh()

        def refresh() -> None:
            s = norm(q.value or "")
            chips.clear()
            hits = [t for t in trees if not s or any(s in k for k in [norm(t.get("term", "")), norm(t.get("code", ""))] + [norm(x) for x in (t.get("syn") or [])])]
            cnt.set_text(f"선도어 {len(hits)}개")
            with chips:
                for t in hits[:300]:
                    on = cur["t"] is t
                    ui.button(t.get("term", ""), on_click=lambda _, t=t: show(t)).props("dense no-caps size=sm " + ("unelevated color=primary" if on else "outline")).style("padding:0 12px")
                if not hits:
                    ui.label("결과 없음").classes("text-muted text-sm")

        q.on("update:model-value", refresh, throttle=0.2)
        refresh()
        if trees:
            show(trees[0])

# ───────────── AI 자동 코딩 (문서 판독 · 환자 조건 · 청구 목록 · 룰 점검) ─────────────
SEV_COLOR = {"삭감": "var(--bad)", "조정": "var(--warn)", "확인": "#6a91b7"}


@ui.page("/nlp")
def nlp_page() -> None:
    if not require_login():
        return
    from . import ocr, rules
    from .phase4 import parse_age

    layout("nlp")
    ui.add_css(".kcm-chip{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:12px;background:var(--a100);"
               "color:var(--a800);white-space:nowrap}.kcm-chip.off{background:var(--n200);color:var(--n700)}")
    # ── 화면 캡처 · 붙여넣기 · 끌어다 놓기 · 캡처 자동 첨부 (브라우저에서 실행 → 업로드 요청으로 서버에 전달)
    ui.add_body_html("""<script>(function(){
var KEY='kcm_clip_auto',lastSig='',primed=false,busy=false,timer=null,state='',pasteAt=0,wired=false;
function zone(){return document.querySelector('[data-kcm-url]');}
function say(m,t){try{emitEvent('kcm_cap',{msg:m,type:t||'info'});}catch(e){}}
function p2(n){return String(n).padStart(2,'0');}
function stamp(){var d=new Date();return '캡처_'+d.getFullYear()+p2(d.getMonth()+1)+p2(d.getDate())+'_'+p2(d.getHours())+p2(d.getMinutes())+p2(d.getSeconds())+'.png';}
function autoOn(){try{return localStorage.getItem(KEY)!=='0';}catch(e){return true;}}
function setChip(){var c=document.getElementById('kcm-clip-chip');if(!c)return;var l,col;
 if(!autoOn()){l='자동 첨부 꺼짐';col='var(--n500)';}
 else if(state==='denied'){l='자동 첨부 차단됨 – 권한 필요';col='var(--warn)';}
 else if(state==='need'){l='자동 첨부 대기 – 눌러서 권한 허용';col='var(--warn)';}
 else if(state==='unsupported'){l='자동 첨부 미지원 – Ctrl+V 사용';col='var(--muted)';}
 else{l='자동 첨부 켜짐';col='var(--ok)';}
 c.querySelector('span').textContent=l;c.querySelector('i').style.background=col;}
async function send(file){var z=zone();if(!z)return false;var fd=new FormData();fd.append('file',file,file.name);
 try{var r=await fetch(z.dataset.kcmUrl,{method:'POST',body:fd});return r.ok;}catch(e){return false;}}
async function pull(quiet){
 if(!(navigator.clipboard&&navigator.clipboard.read)){state='unsupported';setChip();if(!quiet)say('이 브라우저는 자동 첨부를 지원하지 않습니다 — Ctrl+V로 붙여넣으세요.','warning');return false;}
 try{var items=await navigator.clipboard.read();if(state){state='';setChip();}
  for(var i=0;i<items.length;i++){var t=items[i].types.find(function(x){return /^image\\//.test(x);});
   if(t){var blob=await items[i].getType(t);var sig=blob.size+':'+t;if(sig===lastSig)return false;
    if(quiet&&!primed){primed=true;lastSig=sig;return false;}
    if(quiet&&pasteAt&&Date.now()-pasteAt<4000){lastSig=sig;return false;}
    lastSig=sig;var ok=await send(new File([blob],stamp(),{type:t}));if(ok)say('캡처 이미지를 첨부했습니다.','positive');return ok;}}
  primed=true;
 }catch(e){
  if(quiet){var st='';try{var p=await navigator.permissions.query({name:'clipboard-read'});st=p.state;}catch(_){}
   if(st==='denied'){state='denied';stop();}else if(e&&e.name==='NotAllowedError'&&st!=='granted'){state='need';}
   setChip();return false;}
  if(e&&e.name==='NotAllowedError')say('클립보드 접근이 막혀 있습니다 — Ctrl+V로 붙여넣으세요.','warning');}
 return false;}
function tick(){if(!zone()||document.hidden||!document.hasFocus()||busy)return;busy=true;pull(true).finally(function(){busy=false;});}
function start(){if(timer||!autoOn())return;primed=false;timer=setInterval(tick,1200);tick();}
function stop(){if(timer){clearInterval(timer);timer=null;}}
window.kcmInit=function(){if(!wired){wired=true;
  window.addEventListener('focus',function(){setTimeout(tick,300);});
  document.addEventListener('paste',function(e){if(!zone())return;var its=(e.clipboardData&&e.clipboardData.items)||[];var fs=[];
   for(var i=0;i<its.length;i++){if(its[i].kind==='file'){var f=its[i].getAsFile();if(f&&(/^image\\//.test(f.type)||f.type==='application/pdf'))fs.push(f);}}
   if(!fs.length)return;e.preventDefault();pasteAt=Date.now();
   fs.forEach(async function(f){var nm=(f.name&&f.name!=='image.png')?f.name:stamp();var ok=await send(new File([f],nm,{type:f.type}));if(ok)say('붙여넣은 파일을 첨부했습니다.','positive');});});
  document.addEventListener('dragover',function(e){var z=e.target.closest&&e.target.closest('[data-kcm-url]');if(z){e.preventDefault();z.style.background='var(--a100)';}});
  document.addEventListener('dragleave',function(e){var z=e.target.closest&&e.target.closest('[data-kcm-url]');if(z)z.style.background='';});
  document.addEventListener('drop',function(e){var z=e.target.closest&&e.target.closest('[data-kcm-url]');if(!z)return;e.preventDefault();z.style.background='';
   Array.prototype.forEach.call((e.dataTransfer&&e.dataTransfer.files)||[],async function(f){
    if(!/\\.(pdf|jpe?g|png|txt)$/i.test(f.name)){say(f.name+' — 지원하지 않는 형식입니다.','warning');return;}
    var ok=await send(f);if(ok)say(f.name+' 첨부했습니다.','positive');});});}
 setChip();start();};
window.kcmClipToggle=function(){
 if(autoOn()&&state==='need'){primed=false;pull(true);return;}
 if(autoOn()){try{localStorage.setItem(KEY,'0');}catch(e){}stop();state='';setChip();say('캡처 자동 첨부를 껐습니다.');}
 else{try{localStorage.setItem(KEY,'1');}catch(e){}state='';setChip();start();say('캡처 자동 첨부를 켰습니다. Win + Shift + S 로 캡처하세요.');}};
window.kcmSnip=function(){
 if(!/Windows/i.test(navigator.userAgent)){say('Windows가 아닙니다. 캡처 후 Ctrl+V로 붙여넣으세요.','warning');return;}
 var t0=Date.now(),a=document.createElement('a');a.href='ms-screenclip:';a.rel='noopener';document.body.appendChild(a);a.click();a.remove();
 var to,onFocus=function(){setTimeout(function(){pull(false).then(function(ok){if(ok||Date.now()-t0>60000)done();});},350);};
 var done=function(){window.removeEventListener('focus',onFocus);clearTimeout(to);};
 window.addEventListener('focus',onFocus);
 to=setTimeout(function(){done();say('캡처가 감지되지 않았습니다. 캡처 후 Ctrl+V로 붙여넣으세요.','warning');},60000);
 say('캡처 도구가 열립니다. 열리지 않으면 Win + Shift + S 를 누르세요.');};
})();</script>""")
    ui.on("kcm_cap", lambda e: ui.notify((e.args or {}).get("msg", ""), type=(e.args or {}).get("type", "info")))
    ui.timer(0.6, lambda: ui.run_javascript("kcmInit()"), once=True)
    idx = get_index()
    fam = rules.Family(idx)
    names = {r.code.upper(): r.ko for r in idx.rows}
    cond = load_cond()
    st = {"claim": [], "docs": [], "terms": []}   # claim: [{code, kind}], docs: [{name, mime, data, sel}]

    with ui.column().classes("w-full max-w-6xl gap-4"):
        ui.label("AI 자동 코딩 · 임상 텍스트 분석").classes("kcm-h1")
        ui.label("의무기록 서식을 붙여 넣거나 문서를 첨부해 판독하면 진단 문구를 추출하고, 상병마스터"
                 f"({len(idx):,}건)로 검증해 주진단 · 부진단을 제안합니다. 적용 조건: {cond['dept']} · {cond['purpose']}") \
            .classes("text-muted").style("font-size:13px;margin-top:-8px")

        # ── 문서 첨부 · 판독
        with ui.expansion().classes("kcm-card w-full kcm-docs").props("dense") as docs_exp:
            def docs_head_html(n: int = 0) -> str:
                tag = f"첨부 {n}개" if n else "선택"
                return ('<div class="kcm-docs-head"><span class="kcm-docs-ic"><i class="q-icon material-icons">attach_file</i></span>'
                        f'<span class="kcm-docs-tx"><b>문서 첨부 · 판독 <em>{tag}</em></b>'
                        '<small>소견서 · 진단서 · 진료의뢰서를 파일 · 캡처 · 붙여넣기로 첨부하면 자동으로 읽어 줍니다</small></span>'
                        '</div>')
            with docs_exp.add_slot("header"):
                with ui.row().classes("items-center w-full no-wrap gap-2"):
                    docs_head = ui.html(docs_head_html()).classes("grow").style("min-width:0")
                    # 펼치지 않고도 바로 첨부할 수 있는 두 버튼 (클릭이 펼침 동작으로 번지지 않게 .stop)
                    ui.button("파일 선택", icon="folder_open", on_click=lambda: (docs_exp.set_value(True), up.run_method("pickFiles"))) \
                        .props("unelevated no-caps color=primary").on("click.stop", lambda: None).style("flex:none")
                    ui.button("화면 캡처", icon="screenshot_monitor", on_click=lambda: ui.run_javascript("kcmSnip()")) \
                        .props("outline no-caps").on("click.stop", lambda: None).style("flex:none;background:var(--surface)") \
                        .tooltip("Windows 캡처 도구 실행 (Win + Shift + S) — 캡처하면 자동 첨부")
            steps_row = ui.row().classes("items-center w-full no-wrap gap-3 kcm-steps").style("font-size:14px")

            def render_steps() -> None:
                """1 문서 첨부 → 2 판독 파일 선택 → 3 판독 실행 — 사용자가 어디까지 했는지 단계마다 표시한다."""
                docs_ = st["docs"]
                sel_ = [d for d in docs_ if d["sel"]]
                o = st.setdefault("ocr", "idle")
                s1 = "done" if docs_ else "current"
                s2 = "todo" if not docs_ else ("done" if sel_ else "current")
                s3 = {"busy": "busy", "done": "done", "error": "error"}.get(o, "current" if sel_ else "todo")
                labels = [("문서 첨부", f" · {len(docs_)}개" if docs_ else ""),
                          ("판독 파일 선택", f" · {len(sel_)}개" if docs_ else ""),
                          ("판독 실행", {"busy": " · 진행 중", "done": " · 완료", "error": " · 실패"}.get(o, ""))]
                steps_row.clear()
                with steps_row:
                    for i, ((lab, extra), s_) in enumerate(zip(labels, (s1, s2, s3)), 1):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            circ = {"todo": "border:2px solid var(--color-divider);color:var(--muted);background:var(--surface)",
                                    "current": "border:2px solid var(--color-accent);color:var(--color-accent);background:var(--a100);animation:kcm-pulse 1.6s ease-out infinite",
                                    "done": "border:2px solid var(--color-accent);background:var(--color-accent);color:#fff;box-shadow:0 2px 6px rgba(0,0,0,.25)",
                                    "busy": "border:2px solid var(--color-accent);color:var(--color-accent);background:var(--a100);animation:kcm-pulse 1.1s ease-out infinite",
                                    "error": "border:2px solid var(--warn);color:var(--warn);background:var(--surface)"}[s_]
                            with ui.element("span").style("flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:15px;" + circ):
                                if s_ == "busy":
                                    ui.html('<i class="kcm-spin"></i>')
                                else:
                                    ui.label({"done": "✓", "error": "!"}.get(s_, str(i)))
                            ui.label(lab + extra).style("white-space:nowrap;font-size:14px;font-weight:700;" + ("color:var(--color-accent)" if s_ in ("current", "busy") else
                                                                                    ("color:var(--muted);font-weight:600" if s_ == "todo" else "color:var(--color-text)")))
                        if i < 3:
                            nxt = (s1, s2, s3)[i - 1]
                            ui.element("span").style("flex:1 1 24px;min-width:16px;height:4px;border-radius:2px;background:"
                                                     + ("var(--color-accent)" if nxt == "done" else "var(--color-divider)"))
            with ui.row().classes("w-full gap-3 items-stretch").style("flex-wrap:wrap"):
                up = ui.upload(on_upload=lambda e: on_upload(e), multiple=True, auto_upload=True) \
                    .props("accept=.pdf,.jpg,.jpeg,.png,.txt").style("position:absolute;width:0;height:0;overflow:hidden;opacity:0")
                with ui.column().classes("kcm-dropzone items-center").props(f'data-kcm-url="{up._props.get("url", "")}"').style(
                        "flex:0 1 320px;min-width:250px;border:1px dashed var(--color-accent);border-radius:10px;padding:14px;justify-content:center;gap:10px"):
                    with ui.row().classes("items-center justify-center gap-2"):
                        ui.button("파일 선택", on_click=lambda: up.run_method("pickFiles")).props("outline no-caps")
                        ui.button("화면 캡처", icon="screenshot_monitor", on_click=lambda: ui.run_javascript("kcmSnip()")) \
                            .props("unelevated color=primary no-caps").tooltip("Windows 캡처 도구 실행 (Win + Shift + S) — 캡처하면 자동 첨부")
                    ui.label("또는 여기에 끌어다 놓기 · 캡처 붙여넣기 (Ctrl+V)").style("font-size:13px;text-align:center")
                    ui.label("PDF · JPG · PNG · TXT — 여러 개 동시 첨부").classes("text-muted").style("font-size:11px;text-align:center")
                    ui.html('<button id="kcm-clip-chip" type="button" onclick="kcmClipToggle()" title="Win + Shift + S 로 캡처하면 이 화면으로 돌아올 때 자동으로 첨부됩니다. 누르면 켜기/끄기." '
                            'style="all:unset;cursor:pointer;display:inline-flex;gap:6px;align-items:center;font-size:12px;padding:3px 10px;border-radius:999px;'
                            'border:1px solid var(--color-divider)"><i style="width:8px;height:8px;border-radius:50%;background:var(--n500)"></i>'
                            '<span>자동 첨부 확인 중…</span></button>')
                docs_box = ui.column().classes("gap-1").style(
                    "flex:1 1 360px;min-width:0;border:1px solid var(--color-divider);border-radius:10px;padding:12px;min-height:150px;max-height:300px;overflow:auto")

            def drop_doc(d: dict) -> None:
                if d in st["docs"]:
                    st["docs"].remove(d)
                _TMP.pop(d.get("token"), None)
                render_docs()

            def open_preview(d: dict) -> None:
                """첨부 파일 · 캡처 이미지 미리보기 — 이미지는 크게, PDF는 보기 창, TXT는 본문, 여러 개면 ◀ ▶ 로 넘겨 봄"""
                cur = {"i": max(0, st["docs"].index(d))}
                with ui.dialog() as dlg, ui.card().classes("kcm-card").style("width:min(1000px,94vw);max-width:94vw;gap:10px"):
                    with ui.row().classes("w-full items-center justify-between no-wrap"):
                        title = ui.label("").style("font-family:var(--font-heading);font-weight:600;font-size:18px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            pos = ui.label("").classes("text-muted").style("font-size:12px")
                            ui.button(icon="chevron_left", on_click=lambda: go(-1)).props("flat round dense")
                            ui.button(icon="chevron_right", on_click=lambda: go(1)).props("flat round dense")
                            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
                    view = ui.column().classes("w-full items-center")

                    def show() -> None:
                        dd = st["docs"][cur["i"]]
                        title.set_text(dd["name"])
                        pos.set_text(f"{cur['i'] + 1} / {len(st['docs'])}")
                        view.clear()
                        url = f"/_kcm/preview/{dd.get('token', '')}"
                        with view:
                            if dd["mime"].startswith("image/"):
                                ui.html(f'<img src="{url}" style="max-width:100%;max-height:78vh;object-fit:contain;border-radius:8px;'
                                        f'background:#fff;box-shadow:0 6px 24px rgba(0,0,0,.3)" alt="{dd["name"]}">')
                            elif dd["mime"] == "application/pdf":
                                ui.html(f'<iframe src="{url}" style="width:100%;height:78vh;border:1px solid var(--color-divider);border-radius:8px;background:#fff"></iframe>')
                            else:
                                txt = dd["data"].decode("utf-8", "ignore")[:20000]
                                ui.html(f'<pre style="width:100%;max-height:78vh;overflow:auto;white-space:pre-wrap;font-size:13px;margin:0">'
                                        f'{html.escape(txt)}</pre>')
                        ui.label(f"{len(dd['data']) / 1024:,.0f} KB · {dd['state']}").classes("text-muted mono").style("font-size:11px")

                    def go(step: int) -> None:
                        cur["i"] = (cur["i"] + step) % len(st["docs"])
                        show()
                    show()
                dlg.open()

            def render_docs() -> None:
                render_steps()
                docs_head.set_content(docs_head_html(len(st["docs"])))
                docs_box.clear()
                with docs_box:
                    if not st["docs"]:
                        ui.label("첨부 파일 목록").style("font-size:13px;text-align:center;width:100%;margin-top:40px")
                        ui.label("첨부한 파일이 여기에 표시됩니다. 판독할 파일만 체크하세요.").classes("text-muted").style("font-size:12px;text-align:center;width:100%")
                        return
                    ui.label(f"첨부 {len(st['docs'])}개 · 선택 {sum(1 for d in st['docs'] if d['sel'])}개").classes("text-muted").style("font-size:12px")
                    for d in st["docs"]:
                        with ui.row().classes("items-center no-wrap gap-2 w-full").style("border:1px solid var(--color-divider);border-radius:8px;padding:4px 8px"):
                            ui.checkbox(value=d["sel"], on_change=lambda e, d=d: (d.update(sel=e.value), render_steps()))
                            thumb = ui.element("div").style("flex:none;width:52px;height:42px;border:1px solid var(--color-divider);border-radius:6px;overflow:hidden;"
                                                            "display:grid;place-items:center;cursor:zoom-in;background:var(--surface-2)")
                            with thumb:
                                if d["mime"].startswith("image/"):
                                    ui.html(f'<img src="/_kcm/preview/{d.get("token", "")}" style="width:52px;height:42px;object-fit:cover;display:block" alt="">')
                                else:
                                    ui.label({"application/pdf": "PDF", "text/plain": "TXT"}.get(d["mime"], "FILE")).classes("mono text-muted").style("font-size:11px")
                            thumb.on("click", lambda _, d=d: open_preview(d))
                            with ui.column().classes("gap-0 grow").style("min-width:0"):
                                ui.label(d["name"]).style("font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
                                ui.label(f"{len(d['data']) / 1024:,.0f} KB · {d['state']}" + (f" · {d['pct']}%" if d.get("pct") is not None and d['state'] == "판독 중" else "")).classes("text-muted mono").style("font-size:11px")
                                if d.get("pct") is not None and d["state"] == "판독 중":
                                    ui.linear_progress(value=d["pct"] / 100, show_value=False, size="4px").props("rounded").classes("w-full")
                            ui.button(icon="visibility", on_click=lambda _, d=d: open_preview(d)).props("flat round dense size=sm").tooltip("미리보기")
                            ui.button(icon="close", on_click=lambda _, d=d: drop_doc(d)).props("flat round dense size=sm").tooltip("삭제")

            async def on_upload(e) -> None:
                f = getattr(e, "file", None)
                name = f.name if f else e.name
                raw = await f.read() if f else e.content.read()
                mime = ocr.guess_mime(name, getattr(f, "content_type", "") if f else getattr(e, "type", ""))
                st["docs"].append({"name": name, "mime": mime, "data": raw, "sel": True, "state": "대기", "token": tmp_put(raw, mime)})
                st["ocr"] = "idle"
                docs_exp.set_value(True)
                render_docs()

            def clear_docs() -> None:
                for d_ in st["docs"]:
                    _TMP.pop(d_.get("token"), None)
                st["docs"].clear()
                st["ocr"] = "idle"
                up.reset()
                render_docs()

            # 실행 줄 — 판독 실행 · 첨부 비우기 · 판독 설정(필요할 때만 펼침) · 안내(마우스를 올리면 표시)
            with ui.row().classes("items-center gap-2 w-full").style("border-top:1px solid var(--color-divider);padding-top:10px"):
                ocr_btn = ui.button("판독 실행", icon="document_scanner").props("no-caps unelevated color=primary")
                ui.button("첨부 비우기", on_click=clear_docs).props("no-caps flat dense").style("color:var(--color-accent)")
                ui.element("div").classes("grow")
                set_sum = ui.label("").classes("text-muted").style("font-size:12px")
                with ui.button("판독 설정", icon="tune").props("flat dense no-caps").style("color:var(--color-text)"):
                    with ui.menu().props("anchor='bottom right' self='top right'"):
                        with ui.column().classes("gap-3").style("padding:14px;min-width:300px"):
                            ui.label("판독 설정").style("font-family:var(--font-heading);font-weight:600;font-size:16px")
                            eng = ui.select(ocr.ENGINES, value="gemini", label="판독 엔진").props("dense outlined").classes("w-full")
                            vkey = ui.input("Vision API 키", password=True).props("dense outlined").classes("w-full")
                            vkey.bind_visibility_from(eng, "value", backward=lambda v: v == "vision")
                            lang = ui.select({"ko+en": "한국어 + 영어", "ko": "한국어", "en": "영어"}, value="ko+en", label="인식 언어").props("dense outlined").classes("w-full")
                            ui.label("기본값(Gemini · 한국어+영어)으로 충분합니다. 영문 위주 문서이거나 Google Vision을 쓸 때만 바꾸세요.").classes("text-muted").style("font-size:11px")

                def refresh_sum(_=None) -> None:
                    set_sum.set_text(f"{'Gemini' if eng.value == 'gemini' else 'Google Vision'} · {dict(ko_en='한국어+영어', ko='한국어', en='영어')[lang.value.replace('+', '_')]}")
                eng.on_value_change(refresh_sum)
                lang.on_value_change(refresh_sum)
                refresh_sum()
                ui.button(icon="info_outline").props("flat round dense size=sm").tooltip(
                    "이미지·PDF는 판독을 실행할 때만 서버를 거쳐 선택한 제공자(Gemini 또는 Google)로 전송됩니다. "
                    "환자 식별정보가 포함된 문서의 외부 전송은 원내 개인정보 규정을 먼저 확인하세요.")
            render_docs()

        ocr_cancel = {"v": False}
        # ── 판독 진행 표시 — 판독 실행 중에만 보이는 얇은 한 줄
        with ui.row().classes("kcm-card w-full items-center gap-3 no-wrap").style("padding:8px 14px;min-height:0") as prog_card:
            prog_title = ui.label("").style("font-weight:600;font-size:14px;white-space:nowrap")
            prog_detail = ui.label("").classes("text-muted").style("font-size:12px;flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
            prog_bar = ui.linear_progress(value=0, show_value=False, size="8px").props("rounded stripe animated").style("width:min(220px,26%);flex:none")
            prog_pct = ui.label("0%").style("font-family:var(--font-heading);font-weight:700;font-size:18px;color:var(--color-accent);min-width:44px;text-align:right")
            prog_pct.tooltip("진행률은 단계와 파일 크기로 계산한 예상치입니다. 판독 서비스가 중간 진행 정보를 주지 않아 실제 완료 시각과 약간 다를 수 있습니다.")
            ui.button(icon="stop", on_click=lambda: ocr_cancel.update(v=True)).props("flat round dense size=sm").style("color:var(--warn)").tooltip("판독 중단")
        prog_card.set_visibility(False)
        # ── ① 의무기록 입력 (아래 작업 영역의 첫 칸으로 옮겨진다)
        with ui.column().classes("gap-2 w-full kcm-inputcol") as body_card:
            ui.html('<div class="kcm-tbtn on" style="cursor:default;width:100%"><span class="kcm-step">1</span>의무기록(소견서) 판독</div>').classes("w-full")
            with ui.column().classes("kcm-card gap-3 w-full"):
                ui.label("입원사유 · 과거력 · 검사 · 치료경과 · 최종진단을 붙여 넣거나, 위 ‘문서 첨부’로 판독해 채웁니다.").classes("kcm-note1")
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.label("환자").classes("text-muted").style("font-size:13px")
                    sex = ui.select({"": "성별 미입력", "M": "남", "F": "여"}, value="").props("dense outlined").classes("grow")
                    age = ui.input(placeholder="연령(세)").props("dense outlined type=number min=0 max=120").classes("grow")
                box = ui.textarea(placeholder="예) 70세 남자, 기침·발열로 내원, 흉부 X-ray상 우하엽 폐렴, 고혈압 약 복용 중") \
                    .props("outlined input-style='min-height:210px;max-height:210px;"
                           "resize:none;font-size:15px;line-height:1.7'").classes("w-full")
                with ui.row().classes("gap-2 w-full no-wrap"):
                    btn = ui.button("AI 해석 실행", icon="auto_awesome", on_click=lambda: run_both()).props("no-caps unelevated color=primary size=lg").classes("grow")
                    ui.button("비우기", on_click=lambda: box.set_value("")).props("no-caps outline size=lg").style("white-space:nowrap;flex:none")
                    ui.button(icon="print", on_click=lambda: print_result(), color=None).props("outline size=lg").style(
                        "flex:none;color:var(--color-accent)").tooltip("판독 결과 인쇄 (본문 · AI 코드 후보 · 용어 해석 · 청구 목록)")
                status = ui.label("").classes("text-muted").style("font-size:12px")
                ui.label("한 번 누르면 ② 코드 후보와 ③ 용어 해석이 동시에 진행됩니다. 성별·연령은 아래 ④ 청구 코드 점검에 쓰입니다.").classes("kcm-note1").style("font-size:12px")
        # ── 해석 결과 — AI 해석(코드 후보)과 의학용어·약어 해석을 두 탭으로 나눠 보여 주고, 실행하면 동시에 진행한다
        ui.add_css(""".kcm-tbtn{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--color-divider);border-radius:8px;min-height:40px;
 padding:0 14px;background:var(--surface);cursor:pointer;user-select:none;font-family:var(--font-heading);font-weight:600;font-size:15px}
.kcm-tbtn:hover{background:var(--surface-2)}
.kcm-tbtn.on{background:var(--a200);border-color:var(--color-accent);color:var(--a800);box-shadow:inset 0 0 0 1px var(--a300)}
.kcm-cnt{background:var(--a300);color:var(--a900);font-weight:700;border-radius:999px;padding:0 8px;font-size:12px}
.kcm-done{border:1px solid var(--color-accent);color:var(--color-accent);border-radius:4px;padding:0 6px;font-size:12px}
.kcm-busy{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--color-accent);font-weight:600}
.kcm-spin{width:12px;height:12px;border:2px solid var(--a300);border-top-color:var(--color-accent);border-radius:50%;animation:kcmSpin .8s linear infinite;display:inline-block}
@keyframes kcmSpin{to{transform:rotate(360deg)}}
.kcm-err{font-size:12px;color:var(--warn);font-weight:600}""")
        rt = {"ai": "idle", "terms": "idle", "ai_n": 0, "terms_n": 0}
        ui.add_css(
            ".kcm-split{display:grid;grid-template-columns:minmax(300px,.85fr) minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start;width:100%}"
            "@media (max-width:1450px){.kcm-split{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.kcm-split>.kcm-inputcol{grid-column:1/-1}}"
            "@media (max-width:820px){.kcm-split{grid-template-columns:minmax(0,1fr)}}"
            ".kcm-note1{font-size:13px;line-height:1.55;color:var(--color-text);opacity:.82}"
            ".kcm-step{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--color-accent);color:#fff;"
            "font-size:12px;font-weight:700;margin-right:2px}"
            ".kcm-scroll{max-height:calc(100vh / var(--z, 1) - 420px);min-height:300px;overflow:auto;padding-right:4px}"
            ".kcm-empty{display:grid;justify-items:center;gap:6px;padding:34px 12px;text-align:center;color:var(--muted);font-size:13px;"
            "border:1px dashed var(--color-divider);border-radius:12px}"
            ".kcm-more .q-item{min-height:30px;padding:0;font-size:12px;color:var(--color-accent)}"
            ".kcm-more .q-item__section--avatar{min-width:24px}"
            ".kcm-more .q-expansion-item__content{font-size:13px;line-height:1.6;opacity:.9;padding:2px 0 4px}"
            ".kcm-docs{padding:0 14px;border:1.5px solid var(--a300);border-left:5px solid var(--color-accent);background:var(--a100)}"
            ".kcm-docs .q-item{padding:10px 0}"
            ".kcm-docs-head{display:flex;align-items:center;gap:12px;width:100%;color:var(--color-text)}"
            ".kcm-docs-ic{flex:none;width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:var(--color-accent);color:#fff}"
            ".kcm-docs-ic .q-icon{font-size:22px;color:#fff}"
            ".kcm-docs-tx{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1}"
            ".kcm-docs-tx b{font-family:var(--font-heading);font-size:16px;font-weight:700}"
            ".kcm-docs-tx em{font-style:normal;font-size:11px;font-weight:600;margin-left:8px;padding:2px 8px;border-radius:999px;"
            "border:1px solid var(--color-accent);color:var(--color-accent);vertical-align:middle}"
            ".kcm-docs-tx small{font-size:12.5px;color:var(--muted);line-height:1.4}"
            ".kcm-docs .q-item__section--side{color:var(--color-accent)}"
            ".kcm-steps{padding:10px 14px;border-radius:12px;background:var(--surface);border:1px solid var(--color-divider)}"
            "@keyframes kcm-pulse{0%{box-shadow:0 0 0 0 var(--a300)}70%{box-shadow:0 0 0 9px transparent}100%{box-shadow:0 0 0 0 transparent}}")
        with ui.element("div").classes("kcm-split") as split_el:
            # ── ② AI 해석 결과 (KCD 코드 후보)
            with ui.column().classes("gap-2 w-full") as col_ai:
                hdr_ai = ui.row().classes("w-full items-center")
                ui.label("의무기록을 AI가 읽고 KCD 상병코드 후보를 제안합니다.").classes("kcm-note1")
                with ui.expansion("자세히 보기", icon="info_outline").props("dense").classes("kcm-more w-full"):
                    ui.html("각 후보에는 <b>정확도(%)</b>와 <b>근거</b>가 붙고, 상병마스터에 실제 있는 코드인지 검증합니다. "
                            "후보의 <b>＋</b> 버튼으로 아래 청구 목록에 담아 룰 점검(성별·연령·주진단 등)을 할 수 있습니다.")
                out = ui.column().classes("w-full gap-2 kcm-scroll")
                with out:
                    ui.html('<div class="kcm-empty"><span style="font-size:26px">✦</span>‘AI 해석 실행’을 누르면<br>KCD 코드 후보가 여기에 나타납니다.</div>')
            # ── ③ 의학용어 · 약어 해석
            with ui.column().classes("gap-2 w-full") as col_terms:
                hdr_terms = ui.row().classes("w-full items-center")
                ui.label("본문의 약어와 의학용어를 표준 한글 용어로 풀어 줍니다.").classes("kcm-note1")
                with ui.expansion("자세히 보기", icon="info_outline").props("dense").classes("kcm-more w-full"):
                    ui.html("내장 약어 사전과 AI가 함께 해석하고, 진료과마다 뜻이 다른 약어는 모든 뜻을 보여 줍니다. "
                            "<b>본문에 해석 반영</b>을 누르면 ‘HTN(고혈압)’처럼 본문에 풀어 적고, 이 해석은 AI 코드 제안에도 함께 전달됩니다.")
                with ui.column().classes("kcm-card w-full gap-2 kcm-scroll") as terms_panel:
                    terms_status = ui.label("").classes("text-muted").style("font-size:12px")
                    terms_box = ui.column().classes("w-full gap-0")
        body_card.move(split_el, target_index=0)

        def render_rbar() -> None:
            for k, hdr, lab in (("ai", hdr_ai, "2|AI 해석 결과"), ("terms", hdr_terms, "3|의학용어 · 약어 해석")):
                hdr.clear()
                with hdr:
                    b = ui.element("div").classes("kcm-tbtn on").style("cursor:default;width:100%;justify-content:space-between")
                    with b:
                        num, name = lab.split("|")
                        ui.html(f"<span class=\"kcm-step\">{num}</span>{name}").style("display:inline-flex;align-items:center;gap:6px")
                        s_ = rt[k]
                        if s_ == "busy":
                            ui.html('<span class="kcm-busy"><i class="kcm-spin"></i>해석중</span>')
                        elif s_ == "error":
                            ui.html('<span class="kcm-err">⚠ 실패</span>')
                        elif s_ == "done":
                            ui.html(f'<span class="kcm-cnt">{rt[k + "_n"]}건</span>' if rt[k + "_n"] else '<span class="kcm-done">✓ 완료</span>')
                        else:
                            ui.html('<span class="kcm-none" style="font-size:12px;color:var(--muted)">대기</span>')

        def show_rtab(k: str) -> None:   # 두 해석이 항상 함께 보이므로 따로 전환할 것이 없다
            return None
        render_rbar()

        def _union() -> dict:
            from .phase4 import DEPT_LEX
            u: dict = {}
            for dname, v in DEPT_LEX.items():
                for ab, ko in v["terms"]:
                    u.setdefault(ab.lower(), {}).setdefault(ko, []).append(dname)
            return u

        def render_terms() -> None:
            terms_box.clear()
            rows = st["terms"]
            with terms_box:
                if not rows:
                    ui.html('<div class="kcm-empty" style="width:100%"><span style="font-size:26px">Aa</span>‘AI 해석 실행’을 누르면<br>본문의 약어·의학용어가 여기에 해석됩니다.</div>')
                    return
                grid = "display:grid;grid-template-columns:minmax(64px,100px) 52px minmax(0,1fr) 78px;gap:10px;align-items:start;padding:8px 4px;border-bottom:1px solid var(--color-divider)"
                with ui.element("div").classes("text-muted w-full").style(grid + ";font-size:11px;letter-spacing:.06em"):
                    for h in ("용어 · 약어", "구분", "해석 (표준 한글 용어)", "출처"):
                        ui.label(h)
                for r in rows:
                    with ui.element("div").classes("w-full").style(grid):
                        ui.label(r["term"]).classes("mono").style("font-weight:700;color:var(--accent-hi);overflow-wrap:anywhere")
                        ui.html(f'<span class="kcm-chip {"" if r["kind"] == "약어" else "off"}">{html.escape(r["kind"])}</span>')
                        with ui.column().classes("gap-0").style("min-width:0"):
                            ui.label(r["meaning"]).style("font-size:14px;font-weight:600")
                            if r.get("english"):
                                ui.label(r["english"]).classes("text-muted").style("font-size:12px")
                            if r.get("note"):
                                ui.label(r["note"]).style("font-size:11px;color:var(--warn)")
                        ui.label(r["src"] + (f" · {r['n']}회" if r.get("n", 1) > 1 else "")).classes("text-muted").style("font-size:11px")
                with ui.row().classes("gap-2").style("padding-top:8px"):
                    ui.button("본문에 해석 반영", icon="edit_note", on_click=lambda: apply_terms()).props("no-caps outline dense")
                    ui.label("약어를 ‘HTN(고혈압)’처럼 본문에 풀어 적습니다. 첫 등장만 바꿉니다.").classes("text-muted").style("font-size:11px;align-self:center")

        def apply_terms() -> None:
            new, n = terms.apply_to_text(box.value or "", st["terms"])
            if n:
                box.set_value(new)
                ui.notify(f"약어 {n}개의 해석을 본문에 반영했습니다.", type="positive")
            else:
                ui.notify("반영할 약어가 없거나 이미 해석이 붙어 있습니다.")

        def local_now() -> list:
            """내장 사전으로 즉시 해석 — AI 코딩에도 함께 전달된다"""
            from .phase4 import DEPT_LEX
            st["terms"] = terms.local_terms((box.value or "").strip(), DEPT_LEX.get(cond["dept"], {}).get("terms"), _union())
            return st["terms"]

        async def interpret() -> None:
            text = (box.value or "").strip()
            if len(text) < 3:
                ui.notify("해석할 본문이 없습니다.", type="warning")
                return
            local = local_now()
            rt["terms"] = "busy"
            render_rbar()
            terms_status.set_text("내장 사전으로 해석했습니다. AI가 나머지 의학용어를 해석하는 중입니다…")
            render_terms()
            try:
                ai = await run.io_bound(gemini.interpret_terms, text)
                st["terms"] = terms.merge(local, ai)
                terms_status.set_text(f"해석 {len(st['terms'])}건 — 내장 사전 {sum(1 for r in st['terms'] if r['src'] == '내장 사전')}건 · AI {sum(1 for r in st['terms'] if r['src'] == 'AI')}건")
                rt["terms"] = "done"
            except Exception as ex:  # noqa: BLE001
                terms_status.set_text(f"AI 해석은 건너뛰었습니다 — {ex} (내장 사전 결과만 표시)")
                rt["terms"] = "done" if local else "error"
            rt["terms_n"] = len(st["terms"])
            render_terms()
            render_rbar()

        async def run_both() -> None:
            """AI 해석(코드 후보)과 의학용어·약어 해석을 동시에 실행한다"""
            if len((box.value or "").strip()) < 5:
                ui.notify("의무기록 내용을 입력하세요.", type="warning")
                return
            local_now()
            await asyncio.gather(analyze(), interpret())

        async def run_ocr() -> None:
            """판독 실행 — 파일별·전체 진행률과 경과 시간을 표시한다.
            판독 서비스는 중간 진행 정보를 주지 않으므로 진행률은 단계(준비→전송·판독→정리)와 파일 크기에 따른 예상치다."""
            sel = [d for d in st["docs"] if d["sel"]]
            if not sel:
                ui.notify("판독할 파일을 첨부·선택하세요.", type="warning")
                return
            ocr_btn.disable()
            st["ocr"] = "busy"
            render_steps()
            ocr_cancel["v"] = False
            for d in st["docs"]:
                d.pop("pct", None)
            total, texts, chars = len(sel), [], 0
            t_all = time.time()
            prog_card.set_visibility(True)
            prog_title.set_text(f"판독 중 · 0 / {total}개")
            prog_pct.set_text("0%")
            prog_bar.set_value(0)
            prog_bar.props("color=primary")
            prog_detail.set_text("준비 중…")
            for i, d in enumerate(sel):
                d["state"], d["pct"] = "판독 중", 2
                render_docs()
                t0 = time.time()
                tau = 6 + len(d["data"]) / 1e6 * 5          # 큰 파일일수록 오래 걸린다고 보고 예상 곡선을 늦춘다
                finished = {"v": False}

                async def ticker(d=d, i=i, t0=t0, tau=tau) -> None:
                    while not finished["v"]:
                        el = time.time() - t0
                        pct = 8 + 84 * (1 - math.exp(-el / tau))        # 8% 전송 준비 → 최대 92% (끝나면 100%)
                        d["pct"] = int(pct)
                        overall = (i + pct / 100) / total
                        prog_bar.set_value(overall)
                        prog_pct.set_text(f"{int(overall * 100)}%")
                        if pct >= 88:
                            prog_detail.set_text(f"{d['name']} — 마무리 중입니다. 판독 서비스 응답이 평소보다 늦어지고 있습니다 · 경과 {int(time.time() - t_all)}초 "
                                                 "(기다리기 어려우면 ‘중단’을 누르세요)")
                        else:
                            prog_detail.set_text(f"{d['name']} — 서버로 보내 글자를 읽는 중 (이 파일 약 {int(pct)}%) · 경과 {int(time.time() - t_all)}초")
                        render_docs()
                        await asyncio.sleep(0.6)
                task = asyncio.create_task(ticker())
                try:
                    if ocr_cancel["v"]:
                        raise RuntimeError("사용자가 판독을 중단했습니다.")
                    fut = asyncio.ensure_future(run.io_bound(ocr.read_document, d["name"], d["data"], d["mime"], eng.value, vkey.value or "", lang.value))
                    while not fut.done():
                        if ocr_cancel["v"]:
                            raise RuntimeError("사용자가 판독을 중단했습니다.")
                        await asyncio.sleep(0.3)
                    t = fut.result()
                    d["state"] = f"완료 · {len(t)}자"
                    texts.append(f"[{d['name']}]\n{t}")
                    chars += len(t)
                except Exception as ex:  # noqa: BLE001
                    d["state"] = "중단" if ocr_cancel["v"] else "실패"
                    ui.notify(str(ex), type="warning" if ocr_cancel["v"] else "negative", timeout=8000)
                finally:
                    finished["v"] = True
                    task.cancel()
                d["pct"] = 100
                overall = (i + 1) / total
                prog_bar.set_value(overall)
                prog_pct.set_text(f"{int(overall * 100)}%")
                prog_title.set_text(f"판독 중 · {i + 1} / {total}개")
                render_docs()
            ocr_btn.enable()
            st["ocr"] = "done" if texts else "error"
            took = int(time.time() - t_all)
            for d in st["docs"]:
                d.pop("pct", None)
            render_docs()
            if texts:
                prog_title.set_text(f"✓ 판독 완료 · 파일 {len(texts)}/{total}개 · {chars:,}자 · {took}초")
                prog_detail.set_text("본문에 추가했습니다. 이어서 의학용어·약어를 해석합니다.")
                box.set_value(((box.value or "").rstrip() + "\n\n" if (box.value or "").strip() else "") + "\n\n".join(texts))
                ui.notify("판독 결과를 본문에 추가했습니다. 의학용어·약어를 해석합니다.", type="positive")
                show_rtab("terms")
                await interpret()
                prog_detail.set_text("본문에 추가했고, 의학용어·약어 해석도 끝났습니다.")
            else:
                prog_title.set_text(f"판독을 중단했습니다 · {took}초" if ocr_cancel["v"] else f"판독 실패 · 0/{total}개 · {took}초")
                prog_bar.props("color=negative")
                prog_detail.set_text("각 파일의 오류 안내를 확인하세요.")
            ui.timer(12, lambda: prog_card.set_visibility(False), once=True)

        ocr_btn.on_click(run_ocr)

        # ── 청구 목록 · 룰 점검
        with ui.column().classes("w-full gap-2"):
            ui.html('<div class="kcm-tbtn on" style="cursor:default;width:100%"><span class="kcm-step">4</span>청구 코드 점검 · 삭감 위험 확인</div>').classes("w-full")
        with ui.column().classes("kcm-card w-full gap-2").style("margin-top:-6px"):
            ui.html("② AI 후보의 <b>＋</b> 버튼으로 담거나 코드를 직접 입력해 <b>청구할 상병 목록</b>을 만든 뒤 <b>[점검 실행]</b>을 누르면, "
                    "청구 전에 <b>삭감·조정 위험</b>을 미리 알려 드립니다. "
                    "<span class='text-muted'>(주진단 1개 여부 · 성별/연령 불일치 · 불완전 코드 · 중복 · 증상코드 병기 · 배타 관계 등)</span>").style("font-size:13px;line-height:1.6")
            with ui.row().classes("items-center gap-2"):
                new_code = ui.input(placeholder="코드 직접 추가 (예: J18.9)").props("dense outlined").classes("w-52")

                def add_manual() -> None:
                    c = (new_code.value or "").strip().upper()
                    if c:
                        add_claim(c)
                        new_code.set_value("")
                new_code.on("keydown.enter", add_manual)
                ui.button("추가", on_click=add_manual).props("no-caps outline dense")
            claim_box = ui.column().classes("w-full gap-1")
            find_box = ui.column().classes("w-full gap-2")
            ui.button("점검 실행", icon="rule", on_click=lambda: run_rules()).props("no-caps unelevated color=primary")

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
                    ui.html('<div class="kcm-empty" style="padding:14px 12px">아직 담은 코드가 없습니다. 위 ② AI 해석 결과의 <b>＋</b>를 누르거나 코드를 직접 입력하세요.</div>')
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
                    ui.label("✔ 점검 규칙에 걸리는 항목이 없습니다.").style("color:var(--ok)")
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
            rt["ai"] = "busy"
            render_rbar()
            out.clear()
            try:
                extra = "; ".join(f"{r['term']}={r['meaning']}" for r in st["terms"][:30])
                send_text = text + (f"\n\n[약어·용어 해석] {extra}" if extra else "")
                res = await run.io_bound(gemini.suggest, send_text, cond["dept"], cond["purpose"])
            except Exception as ex:  # noqa: BLE001
                status.set_text(f"실패 — {ex}")
                rt["ai"] = "error"
                render_rbar()
                with out:
                    ui.label(f"AI 해석 실패 — {ex}").classes("text-muted").style("font-size:13px")
                btn.enable()
                return
            btn.enable()
            codes = res.get("codes", [])
            min_acc = int(cond["minAcc"])
            shown = [c for c in codes if int(c.get("confidence", 0)) >= min_acc]
            st["ai_last"] = {"codes": shown, "caution": res.get("caution", "")}      # 인쇄용으로 보관
            rt["ai"], rt["ai_n"] = "done", len(shown)
            render_rbar()
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
                                ui.label("⚠ 상병마스터에 없는 코드입니다 — 직접 확인하세요.").classes("text-sm").style("color:var(--warn)")
                            for m in warn:
                                ui.label("⚠ " + m).classes("text-sm").style("color:var(--warn)")
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

        def print_result() -> None:
            """판독 결과 인쇄 — 본문 · AI 코드 후보 · 용어 해석 · 청구 목록을 A4 한 문서로 만들어 인쇄창을 연다"""
            import json
            import datetime as dt
            e = html.escape
            text = (box.value or "").strip()
            if not text and not st["docs"]:
                ui.notify("인쇄할 내용이 없습니다. 문서를 판독하거나 본문을 입력하세요.", type="warning")
                return
            s, a = current_ctx()
            u_ = user()
            parts = [f"<h1>의무기록(소견서) 판독 결과</h1>",
                     f"<p class='meta'>출력 {dt.datetime.now():%Y-%m-%d %H:%M} · 작성자 {e(str(u_.get('name') or u_.get('id') or ''))} · "
                     f"적용 조건 {e(cond['dept'])} / {e(cond['purpose'])} · 환자 {e({'M': '남', 'F': '여'}.get(s, '성별 미입력'))}"
                     f"{f' · {a}세' if a is not None else ''}</p>"]
            if st["docs"]:
                parts.append("<p class='meta'>첨부 문서: " + e(", ".join(d["name"] for d in st["docs"])) + "</p>")
            parts.append(f"<h2>판독 본문</h2><pre>{e(text) if text else '(본문 없음)'}</pre>")
            ai = (st.get("ai_last") or {}).get("codes") or []
            if ai:
                rows = "".join(f"<tr><td class='c'>{e(str(c.get('code', '')))}</td><td>{e(names.get(str(c.get('code', '')).strip().upper()) or str(c.get('name_ko', '')))}</td>"
                               f"<td class='c'>{e(str(c.get('confidence', '')))}%</td><td>{e(str(c.get('reason', '')))}</td></tr>" for c in ai)
                parts.append("<h2>AI 코드 후보</h2><table><tr><th>코드</th><th>상병명</th><th>정확도</th><th>근거</th></tr>" + rows + "</table>")
                if (st.get("ai_last") or {}).get("caution"):
                    parts.append(f"<p class='meta'>주의: {e(st['ai_last']['caution'])}</p>")
            if st["terms"]:
                rows = "".join(f"<tr><td>{e(r['term'])}</td><td class='c'>{e(r['kind'])}</td><td>{e(r['meaning'])}{(' (' + e(r['english']) + ')') if r.get('english') else ''}</td></tr>" for r in st["terms"])
                parts.append("<h2>의학용어 · 약어 해석</h2><table><tr><th>용어·약어</th><th>구분</th><th>해석</th></tr>" + rows + "</table>")
            if st["claim"]:
                rows = "".join(f"<tr><td class='c'>{e(r['code'])}</td><td>{e(names.get(r['code'], '코드집에 없음'))}</td><td class='c'>{e(r['kind'])}</td></tr>" for r in st["claim"])
                parts.append("<h2>청구 코드 목록</h2><table><tr><th>코드</th><th>상병명</th><th>구분</th></tr>" + rows + "</table>")
            parts.append("<p class='foot'>※ AI가 제안한 내용은 참고용이며 최종 코딩은 담당자의 확인이 필요합니다.</p>")
            doc = ("<!doctype html><html><head><meta charset='utf-8'><title>의무기록 판독 결과</title><style>"
                   "@page{size:A4;margin:16mm}body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#111;font-size:12px;line-height:1.55}"
                   "h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;margin:18px 0 6px;padding-bottom:3px;border-bottom:2px solid #333}"
                   ".meta{color:#555;margin:2px 0}pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;border:1px solid #bbb;padding:10px;border-radius:4px}"
                   "table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 6px;vertical-align:top;text-align:left}th{background:#eee}"
                   "td.c{text-align:center;white-space:nowrap}.foot{margin-top:18px;color:#666;font-size:11px}</style></head><body>" + "".join(parts) + "</body></html>")
            # 보이지 않는 틀(iframe)에 문서를 쓰고 인쇄 — 팝업 차단에 걸리지 않는다
            ui.run_javascript(
                "(function(h){var f=document.createElement('iframe');f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
                "document.body.appendChild(f);var d=f.contentWindow.document;d.open();d.write(h);d.close();"
                "setTimeout(function(){f.contentWindow.focus();f.contentWindow.print();setTimeout(function(){f.remove()},60000)},300)})(" + json.dumps(doc) + ")")

        render_claim()
        render_terms()
