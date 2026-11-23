"""구어 · 영문 · 통용 병명 → KCD 공식 상병명(또는 코드) 사전.
상병마스터에는 영문명이 없고 '디스크', '맹장염'처럼 현장에서 쓰는 말은 공식 명칭과 달라 그대로는 검색되지 않는다.
한 줄 = `입력어, 입력어: 공식명 | 공식명 | 코드` — 입력어가 검색어에 들어 있으면 그 부분을 공식명으로 바꿔 함께 찾는다."""
from __future__ import annotations

import re

_RAW = """
# ── 점검에서 보강한 약어 · 영문 · 구어 (먼저 적힌 공식명이 결과 앞에 온다 — 같은 입력어의 아래쪽 옛 항목보다 우선)
esrd, 말기신부전, 말기신장병, 말기콩팥병, end stage renal disease: N18.5 | 만성 신장병 | 만성 신부전
ckd, 만성신부전, 만성신장병, 만성콩팥병, chronic kidney disease: N18 | 만성 신장병 | 만성 신부전
요로감염, uti, urinary tract infection: N39.0 | 요로감염 | 방광염
방광염, cystitis: N30 | 방광염
nstemi, 비st분절상승심근경색, 비st분절상승: I21.4 | 급성 심내막하 심근경색증 | 비ST분절상승
stemi, st분절상승심근경색: I21.0 | I21.1 | I21.2 | I21.3 | 급성 투벽성 심근경색증
pci, 경피적관상동맥중재술, 관상동맥중재술, 스텐트시술: I25 | 만성 허혈성 심장질환 | 관상동맥
ards, 급성호흡곤란증후군, 급성호흡부전증후군: J80 | 성인호흡곤란증후군
dvt, 심부정맥혈전증, deep vein thrombosis, 깊은정맥혈전증: I80.2 | I82 | 심부정맥혈전증 | 정맥혈전증
ra, rheumatoid arthritis, 류마티스관절염, 류머티스관절염: M05 | M06 | 류마티스관절염
sle, lupus, 루푸스, 전신홍반루푸스, 전신홍반성루푸스: M32 | 전신 홍반성 루푸스
gi bleeding, gi bleed, gib, 위장관출혈, 소화기출혈, 소화관출혈: K92.2 | K92 | 위장관 출혈
혈변, 하혈, 대변에피: K92.1 | K62.5 | K92.2 | 직장출혈 | 흑색변
토혈, hematemesis: K92.0 | 토혈
흑색변, melena: K92.1 | 흑색변
숨참, 숨이참, 호흡곤란, dyspnea, sob, shortness of breath: R06 | 호흡곤란
물혹, 낭종, cyst: 낭 | 낭종
부종, 부음, edema: R60 | 부종
두통, headache, 머리아픔: R51 | G44 | 두통
편두통, migraine: G43 | 편두통
지방간, fatty liver, 비알코올성지방간, nafld: K76.0 | 지방간
간경변, 간경화, 간경변증, liver cirrhosis, cirrhosis: K74 | K70.3 | 간경변 | 간경화
갑상선기능항진증, 갑상샘기능항진증, 그레이브스, graves, hyperthyroidism: E05 | 갑상선중독증 | 갑상선기능항진증
부정맥, arrhythmia: I49 | I47 | I48 | 부정맥
발목염좌, 발목삐끗, 발목접질림, ankle sprain: S93 | 발목 관절 및 인대의 염좌 | 발목의 염좌
요추염좌, 허리염좌, 허리삐끗, 허리근육통, lumbar sprain: S33.5 | S33 | 요추 염좌
뇌진탕, concussion: S06.0 | 뇌진탕
폐결핵, tb, tuberculosis, 결핵: A15 | A16 | 호흡기결핵 | 결핵
대퇴골골절, 대퇴골 골절, 대퇴경부골절, 고관절골절, 엉덩이뼈골절, femur fracture, hip fracture, fracture of femur: S72 | 대퇴골의 골절
하지정맥류, varicose veins: I83 | 하지의 정맥류
치질, 치핵, hemorrhoid, hemorrhoids, piles: K64 | 치핵
신장결석, 신결석, 콩팥돌, kidney stone, renal stone, renal calculus: N20 | 신장결석 | 요로결석
요로결석, 요석, urolithiasis: N20 | N21 | N22 | 요로결석
회전근개, 어깨힘줄파열, rotator cuff: M75.1 | M75 | 회전근개
쇄골골절, 빗장뼈골절, clavicle fracture: S42.0 | 쇄골
손목골절, 요골원위부골절, colles, distal radius fracture: S52.5 | S52 | 아래팔의 골절
폐기종, emphysema: J43 | 폐기종
melanoma, 흑색종, 악성흑색종: C43 | 악성 흑색종
bipolar, bipolar disorder, 양극성장애, 조울증: F31 | 양극성 정동장애
hypothyroidism, 갑상선기능저하, 갑상샘기능저하, 갑상선기능저하증: E03 | 갑상선기능저하증
urinary retention, 요폐, 요저류: R33 | 요저류
일산화탄소중독, 연탄가스중독, co중독: T58 | 일산화탄소의 독작용
불임, 불임증, infertility: N97 | 여성불임 | 불임
뇌염, encephalitis: G04 | 뇌염 | A86
단독, erysipelas: A46 | 단독
십이지장궤양, duodenal ulcer: K26 | 십이지장궤양
위궤양, gastric ulcer, 위의궤양: K25 | 위궤양
소화성궤양, peptic ulcer: K27 | K25 | K26 | 소화성궤양
족저근막염, 발바닥근막염, plantar fasciitis: M72.2 | 족저근막염
acs, 급성관동맥증후군: I24 | I21 | I20.0 | 급성 심근경색증 | 불안정 협심증
pad, 말초동맥질환, 말초동맥폐쇄질환: I73.9 | I70 | 말초혈관질환
tia, 일과성허혈발작, 일과성뇌허혈: G45 | 일과성 뇌허혈
ibd, 염증성장질환: K50 | K51 | 크론병 | 궤양성 대장염
pid, 골반염증성질환, 골반염: N73 | N70 | N71 | 골반염
mrsa, 메티실린내성황색포도알균: B95.6 | Z16.1 | 포도알균
covid, covid19, 코로나, 코로나19, 코로나바이러스: U07 | U08 | U09 | 코로나-19
용종, 폴립, polyp: 폴립 | 용종
대장용종, 결장용종, 대장폴립: K63.5 | 결장의 폴립 | D12
위용종: K31.7 | 위의 폴립
서혜부탈장, 샅굴탈장: K40 | 서혜탈장
조산, 조기진통: O60 | 조기 진통 | 조산
유방낭종, 유방물혹: N60 | 유방의 낭
총담관결석, 담관결석: K80.5 | K80.3 | 담관결석
월경불순, 생리불순, 월경이상: N92 | N91 | 월경
폐농양: J85 | 폐농양
화농성관절염, 세균성관절염: M00 | 화농성 관절염
복부대동맥류, 대동맥류: I71.4 | I71 | 대동맥류
저혈압: I95 | 저혈압
심방세동, afib, atrial fibrillation, af: I48 | 심방세동
심부전, 심장부전, chf, heart failure, congestive heart failure: I50 | 심부전
뇌졸중, 중풍, stroke, cva, 뇌혈관질환: I64 | I63 | I61 | 뇌졸중
# ── 근골격 · 정형외과
디스크, 허리디스크, 요추디스크, 추간판: M51 | M50 | 추간판장애 | 추간판전위
목디스크, 경추디스크: M50 | 경추간판장애
추간판탈출증, 추간판 탈출증, 디스크탈출, hnp, hivd, 수핵탈출: M51 | M50 | 추간판장애 | 추간판전위
척추관협착증, 협착증: 척추협착
오십견: 유착성 피막염 | 어깨의 유착성관절낭염
테니스엘보, 테니스 엘보: 외측상과염
골프엘보: 내측상과염
손목터널증후군: 손목굴증후군
십자인대: 십자인대
반월상연골, 반월판, 연골판: 반달연골
아킬레스: 아킬레스힘줄
족저근막염: 족저근막염 | 발바닥근막염
통풍: 통풍
퇴행성관절염, 관절염, 골관절염: 관절증 | 골관절염
류마티스, 류머티스: 류마티스관절염
골다공증: 골다공증
디스크파열: 추간판장애
탈구: 탈구
염좌: 염좌 및 긴장
인대파열: 인대의 파열 | 인대 파열
뼈부러짐, 뼈가부러짐: 골절
fracture, fx: 골절
# ── 순환기 · 내분비
고혈압, htn, hypertension, high blood pressure: I10 | 고혈압
저혈압, hypotension: 저혈압
당뇨, 당뇨병, dm, diabetes, diabetes mellitus, 소아당뇨: 당뇨병
고지혈증, 이상지질혈증, 콜레스테롤, hyperlipidemia, dyslipidemia: 이상지질혈증 | 고지질혈증 | 고콜레스테롤혈증
협심증, angina: 협심증
심근경색, 심장마비, mi, myocardial infarction, heart attack: 심근경색증
심부전, 심장부전, chf, heart failure: 심부전
부정맥, 심방세동, af, afib, atrial fibrillation: 심방세동 | 부정맥
뇌졸중, 중풍, 풍, stroke, cva: 뇌졸중 | 뇌경색 | 뇌내출혈 | 중풍
뇌경색, 뇌경색증, 뇌梗塞, cerebral infarction, infarction: 뇌경색
뇌출혈, 뇌내출혈, ich, cerebral hemorrhage, intracerebral hemorrhage: 뇌내출혈
지주막하출혈, 거미막하출혈, sah: 거미막하출혈
정맥류, varicose: 정맥류
폐색전증, pe, pulmonary embolism, 폐동맥색전: 폐색전증
심부정맥혈전증, dvt: 정맥혈전증 | 심부정맥
갑상선기능항진, 갑상샘기능항진, hyperthyroidism: 갑상선기능항진증 | 갑상선중독증
갑상선기능저하, 갑상샘기능저하, hypothyroidism: 갑상선기능저하증
갑상선암, 갑상샘암: 갑상선의 악성 | 갑상선암
비만, obesity: 비만
통풍성: 통풍
# ── 호흡기
폐렴, pneumonia: 폐렴
감기, 코감기, 상기도감염, uri, common cold, cold: 급성 비인두염 | 급성 상기도감염
독감, 인플루엔자, flu, influenza: 인플루엔자
기관지염, bronchitis: 기관지염
천식, asthma: 천식
copd, 만성폐쇄성폐질환, 폐기종: 만성 폐쇄성 폐질환 | 폐기종
폐결핵, 결핵, tb, tuberculosis: 결핵
기흉, pneumothorax: 기흉
편도염, 편도선염, tonsillitis: 급성 편도염 | 편도염
부비동염, 축농증, sinusitis: 부비동염 | 만성 부비동염
비염, 알레르기비염, rhinitis, allergic rhinitis: 알레르기비염 | 비염
코막힘: 비염
중이염, otitis media: 중이염
후두염: 후두염
# ── 소화기 · 간담췌
위염, gastritis: 위염
위궤양, 십이지장궤양, 소화성궤양, gastric ulcer, peptic ulcer: 위궤양 | 십이지장궤양 | 소화성궤양
역류성식도염, 위식도역류, gerd, reflux: 위-식도역류병 | 위식도역류 | 역류식도염
식도염: 식도염
장염, 위장염, 설사, gastroenteritis, diarrhea: 장염 | 위장염 | 설사
변비, constipation: 변비
과민성대장, ibs, irritable bowel: 과민대장증후군 | 과민성 대장
크론병, crohn: 크론병
궤양성대장염, 대장염, colitis: 궤양성 대장염 | 결장염
맹장염, 맹장, 충수염, appendicitis: 급성 충수염 | 충수염
탈장, 헤르니아, 서혜부탈장, hernia: 서혜부 탈장 | 탈장
담석, 담석증, 쓸개돌, gallstone, cholelithiasis: K80 | 담석증 | 담낭의 결석
담낭염, 쓸개염, cholecystitis: 담낭염
췌장염, pancreatitis: 췌장염
간염, hepatitis: 바이러스 간염 | 간염
b형간염, 비형간염, hbv: 만성 바이러스 간염 B | B형 간염
c형간염, 씨형간염, hcv: C형 간염 | 만성 바이러스 간염 C
간경화, 간경변, liver cirrhosis, cirrhosis: 간경변 | 간경화
지방간, fatty liver: 지방간
치질, 치핵, hemorrhoid: 치핵
치루, 항문누공: 항문 누공
항문열상, 치열: 항문 열
위암, gastric cancer, stomach cancer: 위의 악성 | 위암
대장암, 결장암, 직장암, colon cancer, colorectal cancer: 결장의 악성 | 직장의 악성
간암, hcc, 간세포암, liver cancer: 간세포암종 | 간의 악성
췌장암, pancreatic cancer: 췌장의 악성
식도암: 식도의 악성
담도암, 담관암: 담관의 악성 | 담도의 악성
# ── 비뇨 · 신장
요로감염, 방광염, uti, cystitis: 방광염 | 요로감염
신우신염, apn, pyelonephritis: 신우신염
요로결석, 신장결석, 요석, 콩팥돌, kidney stone, urolithiasis: 요로결석 | 신장결석 | 요석
신부전, 콩팥기능상실, renal failure, aki, ckd: 신부전 | 만성 신장병
전립선비대, 전립샘비대, bph: N40 | 전립선증식증
전립선암: 전립선의 악성
방광암: 방광의 악성
신장암, 콩팥암, rcc: C64 | 신장의 악성 신생물
# ── 암 · 종양
폐암, lung cancer: 기관지 및 폐의 악성 | 폐의 악성
유방암, breast cancer: 유방의 악성
자궁경부암, 자궁목암: 자궁경부의 악성
난소암: 난소의 악성
자궁암, 자궁내막암: 자궁체부의 악성 | 자궁내막의 악성
림프종, lymphoma: 림프종
백혈병, leukemia: 백혈병
다발골수종, 골수종: 다발골수종
암, 악성종양, cancer: 악성 신생물
# ── 신경 · 정신
치매, 알츠하이머, 알쯔하이머, dementia, alzheimer: 알츠하이머병 | 치매
파킨슨, parkinson: 파킨슨병
간질, 뇌전증, epilepsy, seizure: 뇌전증 | 간질
편두통, 두통, migraine, headache: 편두통 | 두통
어지럼, 어지러움, 현훈, vertigo, dizziness: 현훈 | 어지럼
불면증, 불면, insomnia: 불면증
우울증, 우울, depression: 우울 | 우울증
불안, 불안장애, anxiety: 불안장애 | 불안
조현병, 정신분열, schizophrenia: 조현병 | 정신분열
공황장애, panic: 공황장애
adhd, 주의력결핍: 주의력결핍 | 과다활동
자폐, 자폐증, autism: 자폐증
안면마비, 구안와사, 벨마비, bell palsy: 벨마비 | 안면신경
대상포진, herpes zoster, shingles: 대상포진
삼차신경통: 삼차신경 | 삼차신경통
# ── 눈 · 귀 · 피부 · 기타
백내장, cataract: 백내장
녹내장, glaucoma: 녹내장
결막염, conjunctivitis: 결막염
다래끼: 맥립종
근시, 원시, 난시: 굴절 | 근시 | 난시
난청, hearing loss: 난청
아토피, 아토피피부염, atopic: 아토피피부염
두드러기, urticaria: 두드러기
습진, eczema: 습진
무좀, 족부백선: 백선
여드름, acne: 여드름
건선, psoriasis: 건선
화상, burn: 화상
욕창, pressure ulcer, bedsore: 욕창
빈혈, anemia: 빈혈
패혈증, sepsis: 패혈증
탈수, dehydration: 탈수
알레르기, allergy: 알레르기
교통사고, 외상: 운수사고
# ── 소아 · 산부인과
수족구, hfmd: B08.4 | 엔테로바이러스소수포구내염
홍역, measles: 홍역
수두, chickenpox, varicella: 수두
임신중독증, 전자간증, preeclampsia: 전자간증 | 임신 중 고혈압
임신성당뇨: 임신 중 당뇨병 | 임신성 당뇨
자궁근종, fibroid, myoma: 자궁의 평활근종
자궁내막증, endometriosis: 자궁내막증
난소낭종: 난소낭종 | 난소의 낭
유산: 유산
제왕절개: 제왕절개
"""

version = 0                 # 현장 사전이 바뀔 때마다 올려 검색 캐시를 비운다
custom_provider = None     # dictionary.py 가 채운다 — 현장에서 등록한 항목을 돌려주는 함수 {정규화한 입력어: [공식명…]}


def all_entries() -> dict[str, list[str]]:
    """내장 사전 + 현장 등록 항목 (등록 항목이 앞선다)"""
    out = {k: list(v) for k, v in LEX.items()}
    if custom_provider:
        try:
            for k, alts in custom_provider().items():
                out[k] = list(alts) + [a for a in out.get(k, []) if a not in alts]
        except Exception:  # noqa: BLE001
            pass
    return out


LEX: dict[str, list[str]] = {}
for _ln in _RAW.splitlines():
    _ln = _ln.strip()
    if not _ln or _ln.startswith("#") or ":" not in _ln:
        continue
    _keys, _alts = _ln.rsplit(":", 1)
    _alts_l = [a.strip() for a in _alts.split("|") if a.strip()]
    for _k in _keys.split(","):
        _k = re.sub(r"[\s·,()\-/]+", "", _k).lower()
        if _k:
            LEX.setdefault(_k, [])
            for _a in _alts_l:
                if _a not in LEX[_k]:
                    LEX[_k].append(_a)
