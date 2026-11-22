"""2단계 화면 — 조건 설정 · 3권 색인 검색 · AI 자동 코딩"""
from __future__ import annotations

import asyncio
import html
import math
import time
import uuid

from fastapi.responses import Response
from nicegui import app, run, ui

from . import export, gemini, pii, store, terms
from .main import get_index, layout, require_login, save_ui_pref, user
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

# PDF 내려받기 — 브라우저에서 미리보기와 같은 문서를 그려 PDF로 저장 (html2pdf.js · cdnjs). 한글은 사용 중인 PC의 글꼴로 그려진다.
PDF_JS = """(async function(h,fname){
  function load(src){return new Promise(function(res,rej){var s=document.createElement('script');s.src=src;s.onload=res;s.onerror=rej;document.head.appendChild(s);});}
  var wrap=null, box=null;
  try{
    if(!window.html2pdf){await load('https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js');}
    var d=new DOMParser().parseFromString(h,'text/html');
    wrap=document.createElement('div'); wrap.style.cssText='position:fixed;left:-12000px;top:0;width:760px';
    box=document.createElement('div'); box.className='kcm-pdfbox'; box.style.cssText='width:760px;background:#fff;color:#111';
    var st=document.createElement('style');
    st.textContent=d.querySelector('style').textContent.replace(/@page\\{[^}]*\\}/,'').replace('@media print{body{margin:0}}','').replace(/(^|\\})body\\{/,'$1.kcm-pdfbox{');
    box.appendChild(st); box.insertAdjacentHTML('beforeend',d.body.innerHTML); wrap.appendChild(box); document.body.appendChild(wrap);
    await html2pdf().set({margin:[12,12,12,12],filename:fname,image:{type:'jpeg',quality:0.96},html2canvas:{scale:2,useCORS:true},
      jsPDF:{unit:'mm',format:'a4',orientation:'portrait'},pagebreak:{mode:['css','legacy'],avoid:['tr','h2']}}).from(box).save();
    emitEvent('kcm_cap',{msg:'PDF를 내려받았습니다.',type:'positive'});
  }catch(e){ emitEvent('kcm_cap',{msg:'PDF를 만들지 못했습니다. 인터넷 연결을 확인하거나, 인쇄에서 ‘PDF로 저장’을 선택하세요.',type:'negative'}); }
  finally{ if(wrap) wrap.remove(); }
})"""

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

# ───────────── AI 자동 코딩 (문서 판독 · 환자 조건 · 용어 해석) ─────────────
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
    st = {"docs": [], "terms": []}   # docs: [{name, mime, data, sel}]

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
                # 판독 진행 — 판독 실행 중에만 보이며, 버튼과 설정 사이의 빈 공간에 한 줄로 보여 준다 (진행률 · 경과 · 중단)
                ocr_cancel = {"v": False}
                prog_spacer = ui.element("div").classes("grow")
                with ui.column().classes("gap-0").style("flex:1 1 0;min-width:0") as prog_card:
                    with ui.row().classes("items-center no-wrap gap-2 w-full"):
                        prog_title = ui.label("").style("font-weight:700;font-size:13px;white-space:nowrap")
                        prog_bar = ui.linear_progress(value=0, show_value=False, size="8px").props("rounded stripe animated").style("flex:1 1 60px;min-width:60px")
                        prog_pct = ui.label("0%").style("font-family:var(--font-heading);font-weight:700;font-size:16px;color:var(--color-accent);min-width:42px;text-align:right")
                        prog_pct.tooltip("진행률은 단계와 파일 크기로 계산한 예상치입니다. 판독 서비스가 중간 진행 정보를 주지 않아 실제 완료 시각과 약간 다를 수 있습니다.")
                        ui.button(icon="stop", on_click=lambda: ocr_cancel.update(v=True)).props("flat round dense size=sm").style("color:var(--warn)").tooltip("판독 중단")
                    prog_detail = ui.label("").classes("text-muted").style("font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%")
                prog_card.set_visibility(False)

                def show_prog(on: bool) -> None:
                    prog_card.set_visibility(on)
                    prog_spacer.set_visibility(not on)
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

        # ── ① 의무기록 입력 (아래 작업 영역의 첫 칸으로 옮겨진다)
        with ui.column().classes("gap-2 w-full kcm-inputcol") as body_card:
            ui.html('<div class="kcm-tbtn on" style="cursor:default;width:100%"><span class="kcm-step">1</span>의무기록(소견서) 판독</div>').classes("w-full")
            with ui.column().classes("kcm-card gap-3 w-full"):
                ui.label("입원사유 · 과거력 · 검사 · 치료경과 · 최종진단을 붙여 넣거나, 위 ‘문서 첨부’로 판독해 채웁니다.").classes("kcm-note1")
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.label("환자").classes("text-muted").style("font-size:13px")
                    sex = ui.select({"": "성별 미입력", "M": "남", "F": "여"}, value="").props("dense outlined").classes("grow")
                    age = ui.input(placeholder="연령(세)").props("dense outlined type=number min=0 max=120").classes("grow")
                box = ui.textarea(placeholder="예) 소견서 · 의무기록\n"
                                          "입원사유: 기침·발열, 호흡곤란\n"
                                          "과거력: 고혈압(HTN), 당뇨(DM)\n"
                                          "검사: 흉부 X-ray 우하엽 폐렴\n"
                                          "치료경과: 항생제 투여 후 호전\n"
                                          "최종진단: 폐렴, 고혈압, 당뇨병") \
                    .props("outlined input-style='resize:none;font-size:15px;line-height:1.7'").classes("w-full kcm-tarea")
                with ui.row().classes("gap-2 w-full no-wrap"):
                    btn = ui.button("AI 해석 실행", icon="auto_awesome", on_click=lambda: run_both()).props("no-caps unelevated color=primary size=lg").classes("grow").style("white-space:nowrap;min-width:0")
                    ui.button("비우기", on_click=lambda: box.set_value("")).props("no-caps outline").style("white-space:nowrap;flex:none")
                status = ui.label("").classes("text-muted").style("font-size:12px")
                ui.label("한 번 누르면 ② 원문 해석 문서와 ③ 코드 후보가 동시에 진행됩니다. 성별·연령은 코드 후보의 성별·연령 불일치 경고에 쓰입니다.").classes("kcm-note1").style("font-size:12px")
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
            # 큰 화면: 세 칸이 같은 높이(화면에 맞춤)로 나란히 — 입력창과 결과 영역이 칸 안을 가득 채우고 넘치면 칸 안에서만 스크롤
            ".kcm-split{display:grid;grid-template-columns:minmax(300px,.85fr) minmax(0,1.3fr) minmax(0,1fr);gap:14px;align-items:stretch;width:100%;"
            "height:calc(100vh / var(--z, 1) - 330px);min-height:540px}"
            ".kcm-split>*{min-height:0;display:flex;flex-direction:column}"
            ".kcm-split .kcm-scroll{flex:1 1 0;min-height:0;max-height:none}"
            ".kcm-inputcol>.kcm-card{flex:1 1 0;min-height:0}"
            ".kcm-tarea{flex:1 1 0;min-height:140px;display:flex}"
            ".kcm-tarea .q-field__inner,.kcm-tarea .q-field__control{height:100%!important}"
            ".kcm-tarea textarea{height:100%!important;max-height:none!important;min-height:0!important;resize:none}"
            ".kcm-docview{white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:2.05;padding:4px 2px}"
            ".kcm-tm{border-bottom:1.5px dotted var(--color-accent);white-space:normal}"
            ".kcm-tm em{font-style:normal;font-weight:700;font-size:.88em;color:var(--color-accent);background:var(--a100);border-radius:4px;padding:0 5px;margin:0 2px 0 4px;white-space:nowrap}"
            ".kcm-tm em::before{content:'→ '}"
            "@media (max-width:1450px){.kcm-split{grid-template-columns:minmax(0,1fr) minmax(0,1fr);height:auto;min-height:0}"
            ".kcm-split>.kcm-inputcol{grid-column:1/-1}.kcm-split .kcm-scroll{flex:none;max-height:62vh;min-height:260px}.kcm-tarea{min-height:190px}}"
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
            ".kcm-inputcol textarea::placeholder{color:#8e959c!important;opacity:1!important;font-weight:400}"
            ".kcm-steps{padding:10px 14px;border-radius:12px;background:var(--surface);border:1px solid var(--color-divider)}"
            "@keyframes kcm-pulse{0%{box-shadow:0 0 0 0 var(--a300)}70%{box-shadow:0 0 0 9px transparent}100%{box-shadow:0 0 0 0 transparent}}")
        # 판독 결과 전체를 인쇄하는 줄 — 결과 칸들 바로 위에 두어 ①②③ 전체가 대상임을 분명히 한다 (인쇄할 칸은 미리보기 창에서 고른다)
        with ui.row().classes("w-full items-center justify-between no-wrap gap-3").style("margin-bottom:-6px"):
            ui.label("판독 결과  ①  원문  ·  ②  해석 문서  ·  ③  AI 코드 후보").classes("text-muted").style("font-size:12.5px;font-weight:600;letter-spacing:.02em")
            ui.button("인쇄 · 미리보기", icon="print", on_click=lambda: print_result(), color=None).props("outline dense no-caps").style(
                "flex:none;color:var(--color-accent);font-weight:700;padding:0 14px").tooltip("판독 결과 전체(① 원문 · ② 해석 문서 · ③ AI 코드 후보)를 인쇄합니다. 인쇄할 칸은 미리보기 창에서 고릅니다.")
        with ui.element("div").classes("kcm-split") as split_el:
            # ── ② AI 해석 결과 (KCD 코드 후보)
            with ui.column().classes("gap-2 w-full") as col_ai:
                hdr_ai = ui.row().classes("w-full items-center")
                ui.label("의무기록을 AI가 읽고 KCD 상병코드 후보를 제안합니다.").classes("kcm-note1")
                with ui.expansion("자세히 보기", icon="info_outline").props("dense").classes("kcm-more w-full"):
                    ui.html("각 후보에는 <b>정확도(%)</b>와 <b>근거</b>가 붙고, 상병마스터에 실제 있는 코드인지 검증합니다. "
                            "후보의 ★ 버튼으로 개인 코드집에, 🕘 버튼으로 코딩 이력에 담을 수 있습니다.")
                def set_ai_view(v: str) -> None:        # 보기 방식(카드형 · 요약 목록)은 사용자별로 기억
                    app.storage.user["ai_view"] = v
                    save_ui_pref(ai_view=v)
                    render_ai_results()
                ui.toggle({"card": "카드형", "list": "요약 목록"}, value=app.storage.user.get("ai_view", "card"),
                          on_change=lambda e: set_ai_view(e.value)).props("dense no-caps unelevated toggle-color=primary").style("align-self:flex-start")
                out = ui.column().classes("w-full gap-2 kcm-scroll")
                with out:
                    ui.html('<div class="kcm-empty"><span style="font-size:26px">✦</span>‘AI 해석 실행’을 누르면<br>KCD 코드 후보가 여기에 나타납니다.</div>')
            # ── ② 원문 해석 문서 — 원문 그대로 두고 의학용어·약어 옆에 한글 해석을 붙여 보여 준다 (용어표는 아래에 접어 둠)
            with ui.column().classes("gap-2 w-full") as col_terms:
                hdr_terms = ui.row().classes("w-full items-center")
                ui.label("원문 그대로 보여 주고, 의학용어·약어 옆에 한글 해석(→)을 붙입니다. 용어에 마우스를 올리면 영문명이 보입니다.").classes("kcm-note1")
                with ui.column().classes("kcm-card w-full gap-2 kcm-scroll") as terms_panel:
                    terms_status = ui.label("").classes("text-muted").style("font-size:12px")
                    doc_view = ui.html("").classes("kcm-docview w-full")
                with ui.expansion("용어 · 약어 표", icon="table_rows").props("dense").classes("kcm-more w-full") as terms_exp:
                    terms_box = ui.column().classes("w-full gap-0")
        col_terms.move(split_el, target_index=0)
        body_card.move(split_el, target_index=0)

        def render_rbar() -> None:
            for k, hdr, lab in (("ai", hdr_ai, "3|AI 해석 결과 · 코드 후보"), ("terms", hdr_terms, "2|원문 해석 문서")):
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

        def render_doc() -> None:
            """② 원문 해석 문서 — 현재 본문(개인정보 가림 적용)에 해석을 붙여 보여 준다"""
            text = pii.clean(box.value or "").strip()
            if not text:
                doc_view.set_content('<div class="kcm-empty"><span style="font-size:26px">Aa</span>문서를 판독하거나 본문을 입력하면<br>원문이 여기에 나타나고, 의학용어·약어 옆에 한글 해석이 붙습니다.</div>')
                return
            doc_view.set_content(terms.annotate_html(text, st["terms"]))

        def render_terms() -> None:
            terms_box.clear()
            rows = st["terms"]
            render_doc()
            terms_exp._props["label"] = f"용어 · 약어 표 ({len(rows)}건)" if rows else "용어 · 약어 표"
            terms_exp.update()
            with terms_box:
                if not rows:
                    ui.html('<div class="kcm-empty" style="width:100%">아직 해석된 용어가 없습니다.</div>')
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
            text_ = (box.value or "").strip()
            loc = terms.local_terms(text_, DEPT_LEX.get(cond["dept"], {}).get("terms"), _union())
            seen = {r["term"].lower() for r in loc}
            # 영어 의학용어(pneumonia 등)는 KCD 영문명으로 즉시 한글 해석 — AI 없이도 나온다
            loc += [r for r in terms.english_terms(text_, store.kcd_master().get("rows") or []) if r["term"].lower() not in seen]
            st["terms"] = loc
            return st["terms"]

        async def interpret() -> None:
            text = pii.clean((box.value or "")).strip()
            if len(text) < 3:
                ui.notify("해석할 본문이 없습니다.", type="warning")
                return
            local = local_now()
            st["auto_sig"] = hash(text)
            rt["terms"] = "busy"
            render_rbar()
            terms_status.set_text("내장 사전으로 해석했습니다. AI가 나머지 의학용어를 해석하는 중입니다…")
            render_terms()
            try:
                ai = [a for a in await run.io_bound(gemini.interpret_terms, text) if terms.appears(str(a.get("term", "")), text)]
                merged = terms.merge(local, ai)
                # 2차 보완 — 1차에서 해석되지 않고 남은 영어 표현만 모아 다시 해석시킨다 (누락 방지)
                rest = terms.residual_english(text, merged)
                if rest:
                    terms_status.set_text(f"1차 해석 {len(merged)}건 — 남은 영어 표현 {len(rest)}개를 보완 해석하는 중…")
                    try:
                        more = [a for a in await run.io_bound(gemini.interpret_phrases, rest, text) if terms.appears(str(a.get("term", "")), text)]
                        merged = terms.merge(merged, more)
                    except Exception:  # noqa: BLE001
                        pass                       # 보완 실패해도 1차 결과는 그대로 쓴다
                st["terms"] = merged
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
            pii_total: dict = {}
            t_all = time.time()
            docs_exp.set_value(True)             # 진행 표시가 보이도록 첨부 영역을 연다
            show_prog(True)
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
                    t, pc = pii.mask(fut.result())          # 주민번호·전화번호·성명·주소 등 개인정보는 본문에 넣기 전에 가린다
                    for k_, n_ in pc.items():
                        pii_total[k_] = pii_total.get(k_, 0) + n_
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
                ui.notify("판독 결과를 본문에 추가했습니다. AI 해석을 이어서 진행합니다.", type="positive")
                if pii.summary(pii_total):
                    ui.notify(f"개인정보를 가렸습니다 — {pii.summary(pii_total)}", type="info", icon="visibility_off", timeout=7000)
                show_rtab("terms")
                prog_detail.set_text("본문에 추가했습니다. AI 해석(코드 후보)과 용어·약어 해석을 함께 진행합니다…")
                await run_both()                 # 판독이 끝나면 AI 해석 실행을 따로 누르지 않아도 ②코드 후보와 ③용어 해석이 동시에 시작된다
                prog_detail.set_text("본문에 추가했고, AI 코드 후보와 용어·약어 해석도 끝났습니다.")
            else:
                prog_title.set_text(f"판독을 중단했습니다 · {took}초" if ocr_cancel["v"] else f"판독 실패 · 0/{total}개 · {took}초")
                prog_bar.props("color=negative")
                prog_detail.set_text("각 파일의 오류 안내를 확인하세요.")
            ui.timer(12, lambda: show_prog(False), once=True)

        ocr_btn.on_click(run_ocr)

        def current_ctx() -> tuple[str, int | None]:
            return sex.value or "", parse_age(age.value)
        async def analyze() -> None:
            text = pii.clean((box.value or "")).strip()
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
            render_ai_results()

        def render_ai_results() -> None:
            """③ AI 코드 후보 — 사용자가 고른 보기(카드형 · 요약 목록)로 그린다"""
            from .phase3 import add_fav, add_history
            shown = (st.get("ai_last") or {}).get("codes") or []
            caution = (st.get("ai_last") or {}).get("caution", "")
            view = app.storage.user.get("ai_view", "card")
            s, a = current_ctx()
            out.clear()

            def save_fav(code: str, nm: str) -> None:
                ui.notify("코드집에 담았습니다." if add_fav(code, nm) else "이미 코드집에 있습니다.")

            def save_hist(code: str, nm: str, conf) -> None:
                add_history(pii.clean(box.value or "")[:60], code, nm, f"{conf}%", "AI 제안")
                ui.notify("이력에 기록했습니다.", type="positive")

            def actions(code: str, nm: str, conf, dense: bool) -> None:
                with ui.row().classes("gap-1 no-wrap"):
                    sz = "flat round dense size=sm" if dense else "flat round dense"
                    ui.button(icon="star", on_click=lambda _, code=code, nm=nm: save_fav(code, nm)).props(sz).tooltip("코드집에 담기")
                    ui.button(icon="history", on_click=lambda _, code=code, nm=nm, conf=conf: save_hist(code, nm, conf)).props(sz).tooltip("이력에 기록")
                    ui.button(icon="manage_search", on_click=lambda _, code=code: ui.navigate.to(f"/detail?code={code}")).props(sz).tooltip("정밀 분석")

            with out:
                if not shown:
                    ui.html('<div class="kcm-empty"><span style="font-size:26px">✦</span>‘AI 해석 실행’을 누르면<br>KCD 코드 후보가 여기에 나타납니다.</div>')
                elif view == "list":
                    # 요약 목록 — 한 줄에 코드 · 상병명 · 정확도 (근거·경고는 마우스를 올리면 표시)
                    grid = "display:grid;grid-template-columns:78px minmax(0,1fr) 46px auto;gap:8px;align-items:center;padding:6px 4px;border-bottom:1px solid var(--color-divider)"
                    with ui.element("div").classes("w-full text-muted").style(grid + ";font-size:11px;letter-spacing:.06em"):
                        for h in ("코드", "상병명", "정확도", ""):
                            ui.label(h)
                    for c in shown:
                        code = str(c.get("code", "")).strip().upper()
                        known = names.get(code)
                        nm = known or c.get("name_ko", "")
                        warn = [m for m in (rules.sex_issue(code, s), rules.age_issue(code, a)) if m]
                        tip = (c.get("reason", "") + ("\n⚠ 상병마스터에 없는 코드입니다 — 직접 확인하세요." if not known else "") + "".join("\n⚠ " + m for m in warn)).strip()
                        with ui.element("div").classes("w-full").style(grid):
                            ui.label(code).classes("font-bold mono").style("color:var(--accent-hi)")
                            with ui.row().classes("items-center gap-1 no-wrap").style("min-width:0"):
                                ui.label(nm).style("font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap").tooltip(tip or nm)
                                rl = c.get("role") or ("주진단" if c.get("primary") else "")
                                if rl:
                                    ui.html(f'<span class="kcm-chip {"" if rl == "주진단" else "off"}" style="flex:none">{ {"주진단": "주", "부진단": "부"}.get(rl, rl) }</span>').tooltip(rl)
                                if not known or warn:
                                    ui.icon("warning", color="warning").classes("text-base").tooltip(tip)
                            ui.label(f"{c.get('confidence', 0)}%").classes("font-bold")
                            actions(code, nm, c.get("confidence", 0), True)
                else:
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
                                rl = c.get("role") or ("주진단" if c.get("primary") else "")
                                if rl:
                                    ui.badge("주진단 후보" if rl == "주진단" else rl).props("" if rl == "주진단" else "outline")
                                actions(code, known or c.get("name_ko", ""), c.get("confidence", 0), False)
                if caution:
                    ui.label("주의: " + caution).classes("text-sm text-muted")

        def build_print_doc(sel: dict) -> str:
            """고른 칸만 A4 한 문서(HTML)로 만든다 — 미리보기와 실제 인쇄가 같은 문서를 쓴다"""
            import datetime as dt
            e = html.escape
            text = pii.clean((box.value or "")).strip()
            s, a = current_ctx()
            u_ = user()
            parts = [f"<h1>의무기록(소견서) 판독 결과</h1>",
                     f"<p class='meta'>출력 {dt.datetime.now():%Y-%m-%d %H:%M} · 작성자 {e(str(u_.get('name') or u_.get('id') or ''))} · "
                     f"적용 조건 {e(cond['dept'])} / {e(cond['purpose'])} · 환자 {e({'M': '남', 'F': '여'}.get(s, '성별 미입력'))}"
                     f"{f' · {a}세' if a is not None else ''}</p>"]
            if st["docs"]:
                parts.append("<p class='meta'>첨부 문서: " + e(", ".join(d["name"] for d in st["docs"])) + "</p>")
            if sel.get("c1"):
                parts.append(f"<h2>① 의무기록(소견서) 판독 — 원문</h2><pre>{e(text) if text else '(본문 없음)'}</pre>")
            if sel.get("c2"):
                parts.append(f"<h2>② 원문 해석 문서 (의학용어·약어 한글 해석 포함)</h2><pre>{terms.annotate_html(text, st['terms']) if text else '(본문 없음)'}</pre>")
                if sel.get("c2b") and st["terms"]:
                    rows = "".join(f"<tr><td>{e(r['term'])}</td><td class='c'>{e(r['kind'])}</td><td>{e(r['meaning'])}{(' (' + e(r['english']) + ')') if r.get('english') else ''}</td></tr>" for r in st["terms"])
                    parts.append("<h3>용어 · 약어 표</h3><table><tr><th>용어·약어</th><th>구분</th><th>해석</th></tr>" + rows + "</table>")
            ai = (st.get("ai_last") or {}).get("codes") or []
            if sel.get("c3") and ai:
                rows = "".join(f"<tr><td class='c'>{e(str(c.get('code', '')))}</td><td>{e(names.get(str(c.get('code', '')).strip().upper()) or str(c.get('name_ko', '')))}</td>"
                               f"<td class='c'>{e(str(c.get('role', '')))}</td><td class='c'>{e(str(c.get('confidence', '')))}%</td><td>{e(str(c.get('reason', '')))}</td></tr>" for c in ai)
                parts.append("<h2>③ AI 해석 결과 · 코드 후보</h2><table><tr><th>코드</th><th>상병명</th><th>구분</th><th>정확도</th><th>근거</th></tr>" + rows + "</table>")
                if (st.get("ai_last") or {}).get("caution"):
                    parts.append(f"<p class='meta'>주의: {e(st['ai_last']['caution'])}</p>")
            if sel.get("c3"):
                parts.append("<p class='foot'>※ AI가 제안한 내용은 참고용이며 최종 코딩은 담당자의 확인이 필요합니다.</p>")
            if not (sel.get("c1") or sel.get("c2") or sel.get("c3")):
                parts.append("<p class='meta' style='margin-top:40px;text-align:center'>인쇄할 칸을 하나 이상 고르세요.</p>")
            return ("<!doctype html><html><head><meta charset='utf-8'><title>의무기록 판독 결과</title><style>"
                    "@page{size:A4;margin:16mm}body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#111;background:#fff;font-size:12px;line-height:1.55;margin:14px}"
                    "h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;margin:18px 0 6px;padding-bottom:3px;border-bottom:2px solid #333}"
                    ".meta{color:#555;margin:2px 0}pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;border:1px solid #bbb;padding:10px;border-radius:4px}"
                    "table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 6px;vertical-align:top;text-align:left}th{background:#eee}"
                    "td.c{text-align:center;white-space:nowrap}.foot{margin-top:18px;color:#666;font-size:11px}"
                    ".kcm-tm{border-bottom:1px dotted #333}.kcm-tm em{font-style:normal;font-weight:700;color:#0b5ea8;margin-left:3px}"
                    ".kcm-tm em::before{content:'→ '}pre{line-height:1.9}h3{font-size:12.5px;margin:12px 0 4px}"
                    "@media print{body{margin:0}}</style></head><body>" + "".join(parts) + "</body></html>")

        ui.add_css(
            ".kcm-printdlg{width:min(1060px,96vw);height:min(84vh,800px);min-width:600px;min-height:440px;max-width:98vw!important;max-height:96vh!important;"
            "resize:both;overflow:auto;display:flex;flex-direction:column;gap:10px;padding:18px}"
            ".q-dialog__inner--minimized>.kcm-printdlg{max-width:98vw!important}"
            ".kcm-printbody{flex:1 1 0;min-height:0}"
            ".kcm-printprev{flex:1 1 520px;min-width:300px;border:1px solid var(--color-divider);border-radius:8px;background:#fff;align-self:stretch;height:auto}")

        def export_ctx(sel: dict) -> dict:
            """Excel · 한글 파일용 내용 — 미리보기·인쇄와 같은 칸 선택(sel)을 따른다"""
            import datetime as dt
            text = pii.clean((box.value or "")).strip()
            s, a = current_ctx()
            u_ = user()
            meta = [f"출력 {dt.datetime.now():%Y-%m-%d %H:%M} · 작성자 {u_.get('name') or u_.get('id') or ''}",
                    f"적용 조건 {cond['dept']} / {cond['purpose']} · 환자 {({'M': '남', 'F': '여'}).get(s, '성별 미입력')}" + (f" · {a}세" if a is not None else "")]
            if st["docs"]:
                meta.append("첨부 문서: " + ", ".join(d["name"] for d in st["docs"]))
            ai = st.get("ai_last") or {}
            return {"title": "의무기록(소견서) 판독 결과", "meta": meta, "text": text, "annotated": terms.annotate_plain(text, st["terms"]),
                    "terms": st["terms"], "codes": ai.get("codes") or [], "caution": ai.get("caution", ""), "sel": sel, "names": names}

        def print_result() -> None:
            """인쇄 · 미리보기 · 내려받기 창 — 인쇄할 칸을 고르면 오른쪽 미리보기가 바로 바뀌고, 인쇄·PDF·Excel·한글 파일 모두 같은 선택을 따른다.
            창은 오른쪽 아래 모서리를 마우스로 끌어 크기를 바꿀 수 있다."""
            import json
            text = pii.clean((box.value or "")).strip()
            if not text and not st["docs"]:
                ui.notify("내보낼 내용이 없습니다. 문서를 판독하거나 본문을 입력하세요.", type="warning")
                return
            last = app.storage.user.get("print_sel") or {}
            has_ai = bool((st.get("ai_last") or {}).get("codes"))
            # no-backdrop-dismiss: 크기를 끌다가 창 밖에서 마우스를 놓아도 창이 닫히지 않게 한다 (닫기: 취소 · Esc)
            with ui.dialog().props("no-backdrop-dismiss") as dlg, ui.card().classes("kcm-printdlg"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label("인쇄 · 미리보기 · 내려받기").style("font-family:var(--font-heading);font-weight:700;font-size:18px")
                    ui.label("↘ 오른쪽 아래 모서리를 끌어 창 크기를 바꿀 수 있습니다").classes("text-muted").style("font-size:11.5px")
                with ui.row().classes("w-full no-wrap items-stretch gap-4 kcm-printbody"):
                    with ui.column().classes("gap-1").style("flex:0 0 270px;min-width:230px;overflow:auto"):
                        ui.label("내보낼 칸을 고르세요. 오른쪽 미리보기에 바로 반영됩니다.").classes("text-muted").style("font-size:12px")
                        c1 = ui.checkbox("① 의무기록(소견서) 판독 — 원문", value=last.get("c1", True))
                        c2 = ui.checkbox("② 원문 해석 문서 — 한글 해석(→) 포함", value=last.get("c2", True))
                        c2b = ui.checkbox("용어 · 약어 표도 함께", value=last.get("c2b", False)).style("margin-left:26px")
                        c2b.bind_enabled_from(c2, "value")
                        c3 = ui.checkbox("③ AI 해석 결과 · 코드 후보" + ("" if has_ai else "  (아직 결과 없음)"), value=last.get("c3", True) and has_ai)
                        c3.set_enabled(has_ai)
                        with ui.row().classes("gap-1"):
                            ui.button("전체", on_click=lambda: (c1.set_value(True), c2.set_value(True), c3.set_value(has_ai))).props("flat dense no-caps")
                            ui.button("선택 해제", on_click=lambda: (c1.set_value(False), c2.set_value(False), c3.set_value(False))).props("flat dense no-caps")
                    prev = ui.element("iframe").classes("kcm-printprev")

                def cur_sel() -> dict:
                    return {"c1": bool(c1.value), "c2": bool(c2.value), "c2b": bool(c2b.value and c2.value), "c3": bool(c3.value and has_ai)}

                def refresh(_=None) -> None:
                    prev._props["srcdoc"] = build_print_doc(cur_sel())
                    prev.update()
                for c in (c1, c2, c2b, c3):
                    c.on_value_change(refresh)
                refresh()

                def picked() -> dict | None:
                    sel = cur_sel()
                    if not (sel["c1"] or sel["c2"] or sel["c3"]):
                        ui.notify("내보낼 칸을 하나 이상 고르세요.", type="warning")
                        return None
                    app.storage.user["print_sel"] = sel
                    return sel

                def go_print() -> None:
                    sel = picked()
                    if not sel:
                        return
                    dlg.close()
                    # 보이지 않는 틀(iframe)에 같은 문서를 쓰고 인쇄 — 팝업 차단에 걸리지 않는다
                    ui.run_javascript(
                        "(function(h){var f=document.createElement('iframe');f.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';"
                        "document.body.appendChild(f);var d=f.contentWindow.document;d.open();d.write(h);d.close();"
                        "setTimeout(function(){f.contentWindow.focus();f.contentWindow.print();setTimeout(function(){f.remove()},60000)},300)})(" + json.dumps(build_print_doc(sel)) + ")")

                def fname(ext: str) -> str:
                    import datetime as dt
                    return f"의무기록_판독결과_{dt.datetime.now():%Y%m%d_%H%M}.{ext}"

                def dl_pdf() -> None:
                    sel = picked()
                    if not sel:
                        return
                    ui.notify("PDF를 만드는 중입니다…", type="info", timeout=2500)
                    ui.run_javascript(PDF_JS + "(" + json.dumps(build_print_doc(sel)) + "," + json.dumps(fname("pdf")) + ")")

                def dl_xlsx() -> None:
                    sel = picked()
                    if sel:
                        ui.download.content(export.build_xlsx(export_ctx(sel)), fname("xlsx"),
                                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                def dl_hwpx() -> None:
                    sel = picked()
                    if sel:
                        ui.download.content(export.build_hwpx(export_ctx(sel)), fname("hwpx"), "application/haansofthwpx")

                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    with ui.button("내려받기", icon="download").props("outline no-caps").style("color:var(--color-accent)"):
                        with ui.menu():
                            with ui.column().classes("gap-0").style("min-width:230px"):
                                for ico, lab, sub, fn in (("picture_as_pdf", "PDF (.pdf)", "그대로 보이는 문서", dl_pdf),
                                                          ("table_chart", "Excel (.xlsx)", "시트별로 나눠 정리", dl_xlsx),
                                                          ("description", "한글 (.hwpx)", "한글 2014 이상에서 열기", dl_hwpx)):
                                    with ui.item(on_click=fn).props("clickable v-close-popup"):
                                        with ui.item_section().props("avatar"):
                                            ui.icon(ico)
                                        with ui.item_section():
                                            ui.item_label(lab)
                                            ui.item_label(sub).props("caption")
                    with ui.row().classes("gap-2"):
                        ui.button("취소", on_click=dlg.close).props("flat no-caps")
                        ui.button("인쇄", icon="print", on_click=go_print).props("unelevated color=primary no-caps")
            dlg.open()
            # 크기를 끌어 바꿀 때 창이 가운데 기준으로 튀지 않도록, 열린 자리에 고정(왼쪽·위 기준)한다
            ui.timer(0.5, lambda: ui.run_javascript(
                "(function(){var c=document.querySelector('.kcm-printdlg');if(!c||c.dataset.anch)return;var r=c.getBoundingClientRect();c.dataset.anch=1;"
                "c.style.position='fixed';c.style.left=r.left+'px';c.style.top=r.top+'px';c.style.margin='0';})()"), once=True)

        async def on_text_change(_=None) -> None:
            """본문에 영어·의학용어가 있으면 알아서 한글로 해석한다 — 멈추면 먼저 내장 사전·KCD 영문명으로 즉시, 영어가 있으면 이어서 AI로 나머지까지"""
            st["tchg"] = tid = st.get("tchg", 0) + 1
            await asyncio.sleep(1.0)
            raw = box.value or ""
            masked, pc = pii.mask(raw)
            if masked != raw:                      # 직접 입력·붙여넣은 글의 개인정보도 가린다
                box.set_value(masked)
                ui.notify(f"개인정보를 가렸습니다 — {pii.summary(pc)}", type="info", icon="visibility_off", timeout=6000)
            text = masked.strip()
            if st["tchg"] != tid or len(text) < 3 or st.get("ocr") == "busy" or rt["terms"] == "busy":
                return
            rows = local_now()
            rt["terms"], rt["terms_n"] = ("done" if rows else "idle"), len(rows)
            terms_status.set_text(f"본문에서 {len(rows)}건을 찾아 해석했습니다." if rows else "")
            render_terms()
            render_rbar()
            if not terms.has_english(text) or hash(text) == st.get("auto_sig"):
                return
            await asyncio.sleep(1.5)                       # 입력이 더 이어지지 않을 때만 AI 호출
            if st["tchg"] != tid or rt["terms"] == "busy":
                return
            await interpret()
        box.on_value_change(on_text_change)

        render_terms()
