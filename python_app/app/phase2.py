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
    st = {"claim": [], "docs": []}   # claim: [{code, kind}], docs: [{name, mime, data, sel}]

    with ui.column().classes("w-full max-w-6xl gap-4"):
        ui.label("AI 자동 코딩 · 임상 텍스트 분석").classes("kcm-h1")
        ui.label("의무기록 서식을 붙여 넣거나 문서를 첨부해 판독하면 진단 문구를 추출하고, 상병마스터"
                 f"({len(idx):,}건)로 검증해 주진단 · 부진단을 제안합니다. 적용 조건: {cond['dept']} · {cond['purpose']}") \
            .classes("text-muted").style("font-size:13px;margin-top:-8px")

        # ── 문서 첨부 · 판독
        with ui.column().classes("kcm-card w-full gap-3"):
            ui.label("문서 첨부 — 소견서 · 진단서 · 진료의뢰서").style("font-family:var(--font-heading);font-weight:600;font-size:13px;letter-spacing:.08em")
            with ui.row().classes("items-center w-full no-wrap gap-2").style("font-size:12px"):
                for i, lab in enumerate(["문서 첨부", "판독 파일 선택", "판독 실행"], 1):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.label(str(i)).style("width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-weight:700;"
                                               "font-size:12px;border:1px solid var(--color-accent);color:var(--color-accent)")
                        ui.label(lab)
                    if i < 3:
                        ui.element("span").style("flex:1 1 24px;min-width:16px;height:1px;background:var(--color-divider)")
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

            def render_docs() -> None:
                docs_box.clear()
                with docs_box:
                    if not st["docs"]:
                        ui.label("첨부 파일 목록").style("font-size:13px;text-align:center;width:100%;margin-top:40px")
                        ui.label("첨부한 파일이 여기에 표시됩니다. 판독할 파일만 체크하세요.").classes("text-muted").style("font-size:12px;text-align:center;width:100%")
                        return
                    ui.label(f"첨부 {len(st['docs'])}개 · 선택 {sum(1 for d in st['docs'] if d['sel'])}개").classes("text-muted").style("font-size:12px")
                    for d in st["docs"]:
                        with ui.row().classes("items-center no-wrap gap-2 w-full").style("border:1px solid var(--color-divider);border-radius:8px;padding:4px 8px"):
                            ui.checkbox(value=d["sel"], on_change=lambda e, d=d: d.update(sel=e.value))
                            with ui.column().classes("gap-0 grow").style("min-width:0"):
                                ui.label(d["name"]).style("font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")
                                ui.label(f"{len(d['data']) / 1024:,.0f} KB · {d['state']}").classes("text-muted mono").style("font-size:11px")
                            ui.button(icon="close", on_click=lambda _, d=d: (st["docs"].remove(d), render_docs())).props("flat round dense size=sm")

            async def on_upload(e) -> None:
                f = getattr(e, "file", None)
                name = f.name if f else e.name
                raw = await f.read() if f else e.content.read()
                mime = ocr.guess_mime(name, getattr(f, "content_type", "") if f else getattr(e, "type", ""))
                st["docs"].append({"name": name, "mime": mime, "data": raw, "sel": True, "state": "대기"})
                render_docs()

            with ui.row().classes("items-end gap-3 w-full").style("border-top:1px solid var(--color-divider);padding-top:12px"):
                eng = ui.select(ocr.ENGINES, value="gemini", label="판독 엔진").props("dense outlined").classes("w-72")
                vkey = ui.input("Vision API 키", password=True).props("dense outlined").classes("w-64")
                vkey.bind_visibility_from(eng, "value", backward=lambda v: v == "vision")
                lang = ui.select({"ko+en": "한국어 + 영어", "ko": "한국어", "en": "영어"}, value="ko+en", label="인식 언어").props("dense outlined").classes("w-40")
                ocr_btn = ui.button("판독 실행").props("no-caps unelevated color=primary")

                def clear_docs() -> None:
                    st["docs"].clear()
                    up.reset()
                    render_docs()
                ui.button("첨부 비우기", on_click=clear_docs).props("no-caps flat").style("color:var(--color-accent)")
            ui.label("ⓘ 판독 안내 — 이미지·PDF는 판독을 실행할 때만 서버를 거쳐 선택한 제공자(Gemini 또는 Google)로 전송됩니다. "
                     "환자 식별정보가 포함된 문서의 외부 전송은 원내 개인정보 규정을 먼저 확인하세요.").style("font-size:11px;color:var(--a700)")
            render_docs()

        # ── 본문
        with ui.column().classes("kcm-card w-full gap-3"):
            with ui.row().classes("items-center gap-3 w-full"):
                ui.label("의무기록 본문 (입원사유 · 과거력 · 검사 · 치료경과 · 최종진단)").style("font-size:12px;color:var(--muted);flex:1")
                sex = ui.select({"": "성별 미입력", "M": "남", "F": "여"}, value="").props("dense outlined").classes("w-32")
                age = ui.input(placeholder="연령(세)").props("dense outlined type=number min=0 max=120").classes("w-28")
            box = ui.textarea(placeholder="예) 70세 남자, 기침·발열로 내원, 흉부 X-ray상 우하엽 폐렴, 고혈압 약 복용 중") \
                .props("outlined autogrow input-style='min-height:170px'").classes("w-full")
            with ui.row().classes("gap-2"):
                btn = ui.button("AI 해석 실행", on_click=lambda: analyze()).props("no-caps unelevated color=primary")
                ui.button("비우기", on_click=lambda: box.set_value("")).props("no-caps outline")
            status = ui.label("").classes("text-muted").style("font-size:12px")
            ui.label("성별·연령을 넣으면 아래 룰 점검에서 불일치 코드를 찾아 줍니다.").classes("text-muted").style("font-size:11px")
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

        render_claim()
