"""문서 판독(OCR) — 기본은 Gemini 비전(서버 키 사용, 별도 키 불필요), 선택으로 Google Cloud Vision 키 사용.
텍스트 레이어가 있는 PDF 는 Gemini 가 그대로 읽는다. 업로드 한도 약 10MB."""
from __future__ import annotations

import base64
import os

import httpx

from . import gemini

MAX_BYTES = 10 * 1024 * 1024
ENGINES = {"gemini": "Gemini 비전 (서버 키 · 권장)", "vision": "Google Cloud Vision (API 키 필요)"}
SYS = ("당신은 의무기록 문서 판독기입니다. 이미지 또는 PDF 안의 글자를 보이는 그대로 옮겨 적으세요. "
       "요약·해석·번역을 하지 말고, 줄바꿈과 표 구조는 최대한 유지하세요. 읽을 수 없는 부분은 [판독불가]로 표시합니다.")


def guess_mime(name: str, given: str = "") -> str:
    n = name.lower()
    if given and "/" in given and given != "application/octet-stream":
        return given
    for ext, m in ((".pdf", "application/pdf"), (".png", "image/png"), (".jpg", "image/jpeg"),
                   (".jpeg", "image/jpeg"), (".webp", "image/webp"), (".txt", "text/plain")):
        if n.endswith(ext):
            return m
    return "application/octet-stream"


def read_document(name: str, data: bytes, mime: str, engine: str = "gemini", vision_key: str = "", lang: str = "ko+en") -> str:
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"{name}: 파일이 너무 큽니다 (최대 10MB).")
    if mime == "text/plain":
        for enc in ("utf-8-sig", "cp949"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise RuntimeError(f"{name}: 텍스트 인코딩을 읽지 못했습니다.")
    if mime not in ("application/pdf", "image/png", "image/jpeg", "image/webp"):
        raise RuntimeError(f"{name}: 지원하지 않는 형식입니다 (PDF · JPG · PNG · TXT).")
    if engine == "vision":
        if mime == "application/pdf":
            raise RuntimeError("Google Cloud Vision 은 이 화면에서 이미지(JPG·PNG)만 판독합니다. PDF 는 Gemini 비전을 선택하세요.")
        key = vision_key.strip() or os.environ.get("GOOGLE_VISION_KEY", "").strip()
        if not key:
            raise RuntimeError("Google Cloud Vision API 키를 입력하세요.")
        r = httpx.post("https://vision.googleapis.com/v1/images:annotate", params={"key": key}, timeout=60,
                       json={"requests": [{"image": {"content": base64.b64encode(data).decode()},
                                           "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                                           "imageContext": {"languageHints": ["ko", "en"]}}]})
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"].get("message", "Vision API 오류"))
        res = (j.get("responses") or [{}])[0]
        if "error" in res:
            raise RuntimeError(res["error"].get("message", "Vision API 오류"))
        return (res.get("fullTextAnnotation") or {}).get("text", "").strip()
    hint = {"ko": "한국어 문서입니다.", "en": "영어 문서입니다."}.get(lang, "한국어와 영어가 섞여 있을 수 있습니다.")
    parts = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}},
             {"text": f"위 문서의 글자를 모두 옮겨 적으세요. {hint}"}]
    return gemini.generate(SYS, parts, None, 8192).strip()
