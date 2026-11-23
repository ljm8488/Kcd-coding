"""AI 자동 코딩 작업 보관 — 다른 메뉴에 다녀와도 판독·해석 내용이 남도록 서버 메모리에 잠시 보관한다.
· 저장 위치는 서버 메모리뿐이다 (DB·파일에 남기지 않는다).
· 접속(브라우저)마다 따로 보관하고, 로그아웃하거나 일정 시간(기본 30분) 쓰지 않으면 지운다.
· 판독이 끝난 첨부 원본(사진·PDF)은 phase2 에서 곧바로 비우고 글자 결과만 남긴다.
"""
from __future__ import annotations

import time

TTL = 30 * 60                       # 마지막 사용 후 보관 시간(초)
_W: dict[str, dict] = {}


def _purge(now: float) -> None:
    for k in [k for k, v in _W.items() if now - v.get("at", 0) > TTL]:
        _W.pop(k, None)


def get(key: str) -> dict | None:
    """보관된 작업(없거나 시간이 지났으면 None)"""
    now = time.time()
    _purge(now)
    st = _W.get(key)
    if st is not None:
        st["prev_at"] = st.get("at", now)         # 이전에 마지막으로 쓴 시각 (되돌아왔을 때 몇 분 전인지 표시용)
        st["at"] = now
    return st


def put(key: str, st: dict) -> dict:
    st["at"] = time.time()
    _W[key] = st
    return st


def touch(st: dict) -> None:
    st["at"] = time.time()


def clear(key: str) -> None:
    _W.pop(key, None)


def clear_user(uid: str) -> None:
    """로그아웃 — 이 사용자의 보관 작업을 모두 지운다"""
    for k in [k for k in _W if k.startswith(f"{uid}|")]:
        _W.pop(k, None)


def minutes_ago(st: dict) -> int:
    return max(0, int((time.time() - st.get("prev_at", st.get("at", time.time()))) // 60))
