"""Supabase `kcm_store` 표(scope, key, data jsonb) 읽기·쓰기 — 기존 웹앱과 같은 공용 DB를 쓴다.

속도: 연결을 재사용하고(매번 새로 접속하지 않음), 캐시가 만료돼도 먼저 이전 값을 돌려준 뒤 뒤에서 새로 읽는다(stale-while-revalidate).
큰 데이터(상병마스터·색인)는 오래 보관하고, 내가 저장한 값은 곧바로 캐시에 반영한다."""
from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_cache: dict[tuple[str, str], tuple[float, Any]] = {}
TTL = 60  # 초 — 다른 PC에서 바꾼 값을 1분 안에 반영 (만료 후에는 이전 값을 먼저 돌려주고 뒤에서 새로 읽음)
TTL_BY_KEY = {("global", "kcdMaster"): 3600, ("global", "ltTrees"): 3600}   # 크고 자주 안 바뀌는 데이터
_refreshing: set[tuple[str, str]] = set()
_lock = threading.Lock()

# 접속을 재사용하는 공용 클라이언트 (요청마다 TLS 접속을 새로 만들지 않아 훨씬 빠르다)
client = httpx.Client(timeout=30, limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
                      headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
_pool = ThreadPoolExecutor(max_workers=6)


def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if extra:
        h.update(extra)
    return h


def _fetch(scope: str, key: str, default: Any) -> Any:
    r = client.get(f"{SUPABASE_URL}/rest/v1/kcm_store",
                   params={"scope": f"eq.{scope}", "key": f"eq.{key}", "select": "data"}, timeout=60)
    r.raise_for_status()
    rows = r.json()
    val = rows[0]["data"] if rows else default
    _cache[(scope, key)] = (time.time(), val)
    return val


def _refresh_bg(ck: tuple[str, str], default: Any) -> None:
    with _lock:
        if ck in _refreshing:
            return
        _refreshing.add(ck)

    def _w() -> None:
        try:
            _fetch(ck[0], ck[1], default)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _lock:
                _refreshing.discard(ck)
    _pool.submit(_w)


def get(scope: str, key: str, default: Any = None, fresh: bool = False) -> Any:
    ck = (scope, key)
    hit = _cache.get(ck)
    if hit and not fresh:
        age, ttl = time.time() - hit[0], TTL_BY_KEY.get(ck, TTL)
        if age < ttl:
            return hit[1]
        if configured():          # 만료됐어도 이전 값을 바로 돌려주고, 새 값은 뒤에서 읽는다
            _refresh_bg(ck, default)
            return hit[1]
    if not configured():
        return default
    return _fetch(scope, key, default)


def get_many(items: list[tuple[str, str, Any]], fresh: bool = False) -> list[Any]:
    """여러 값을 동시에 읽는다 — (scope, key, default) 목록 → 같은 순서의 값."""
    return list(_pool.map(lambda it: get(it[0], it[1], it[2], fresh), items))


def put(scope: str, key: str, data: Any, by: str = "") -> None:
    if not configured():
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
    body = {"scope": scope, "key": key, "data": data,
            "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "updated_by": by}
    r = client.post(f"{SUPABASE_URL}/rest/v1/kcm_store", params={"on_conflict": "scope,key"},
                    json=body, headers={"Prefer": "resolution=merge-duplicates", "Content-Type": "application/json"}, timeout=120)
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


def warm() -> None:
    """서버가 켜질 때 자주 쓰는 데이터를 미리 읽어 둔다 → 첫 접속자가 기다리지 않는다."""
    try:
        get_many([("global", "accounts", []), ("global", "orgs", []), ("global", "sysAdmin", None),
                  ("global", "kcdMaster", {"name": "", "rows": [], "at": ""}), ("global", "ltTrees", []),
                  ("global", "authCfg", {})])
    except Exception:  # noqa: BLE001
        pass
