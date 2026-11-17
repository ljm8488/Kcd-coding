"""Supabase `kcm_store` 표(scope, key, data jsonb) 읽기·쓰기 — 기존 웹앱과 같은 공용 DB를 쓴다."""
from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Any

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_cache: dict[tuple[str, str], tuple[float, Any]] = {}
TTL = 60  # 초 — 다른 PC에서 바꾼 값을 1분 안에 반영


def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if extra:
        h.update(extra)
    return h


def get(scope: str, key: str, default: Any = None, fresh: bool = False) -> Any:
    ck = (scope, key)
    hit = _cache.get(ck)
    if hit and not fresh and time.time() - hit[0] < TTL:
        return hit[1]
    if not configured():
        return default
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/kcm_store",
                  params={"scope": f"eq.{scope}", "key": f"eq.{key}", "select": "data"},
                  headers=_headers(), timeout=30)
    r.raise_for_status()
    rows = r.json()
    val = rows[0]["data"] if rows else default
    _cache[ck] = (time.time(), val)
    return val


def put(scope: str, key: str, data: Any, by: str = "") -> None:
    if not configured():
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
    body = {"scope": scope, "key": key, "data": data,
            "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "updated_by": by}
    r = httpx.post(f"{SUPABASE_URL}/rest/v1/kcm_store", params={"on_conflict": "scope,key"},
                   json=body, headers=_headers({"Prefer": "resolution=merge-duplicates",
                                                "Content-Type": "application/json"}), timeout=60)
    r.raise_for_status()
    _cache[(scope, key)] = (time.time(), data)


# 편의 함수
def accounts(fresh: bool = False) -> list[dict]:
    return get("global", "accounts", [], fresh) or []


def orgs(fresh: bool = False) -> list[dict]:
    return get("global", "orgs", [], fresh) or []


def sys_admin(fresh: bool = False) -> dict | None:
    return get("global", "sysAdmin", None, fresh)


def kcd_master(fresh: bool = False) -> dict:
    return get("global", "kcdMaster", {"name": "", "rows": [], "at": ""}, fresh) or {"rows": []}
