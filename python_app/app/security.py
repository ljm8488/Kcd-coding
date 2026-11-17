"""로그인 보안 — 기존 웹앱(JavaScript)과 같은 비밀번호 해시를 사용해 기존 계정을 그대로 쓴다."""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import os
import re

_M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & _M32


def hash_pw(s: str) -> str:
    """JS hashPw()와 동일한 결과 (UTF-16 코드 단위 기준)."""
    h1 = (0xDEADBEEF ^ 7) & _M32
    h2 = (0x41C6CE57 ^ 7) & _M32
    units = s.encode("utf-16-le")
    for i in range(0, len(units), 2):
        ch = units[i] | (units[i + 1] << 8)
        h1 = _imul(h1 ^ ch, 2654435761)
        h2 = _imul(h2 ^ ch, 1597334677)
    h1 = (_imul(h1 ^ (h1 >> 16), 2246822507) ^ _imul(h2 ^ (h2 >> 13), 3266489909)) & _M32
    h2 = (_imul(h2 ^ (h2 >> 16), 2246822507) ^ _imul(h1 ^ (h1 >> 13), 3266489909)) & _M32
    return format(4294967296 * (2097151 & h2) + h1, "x")


def pw_key(mail: str, pw: str) -> str:
    return hash_pw(f"{(mail or '').strip().lower()}|{pw}")


# ───────── 안전한 비밀번호 저장 (scrypt + 무작위 salt) ─────────
# 기존 해시(hash_pw)는 계산이 가볍고 값이 짧아 DB가 유출되면 쉽게 풀린다. 새 비밀번호는 scrypt 로 저장하고,
# 기존 계정은 로그인에 성공하는 순간 자동으로 옮긴다.
def hash_strong(pw: str, n: int = 2 ** 14) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=n, r=8, p=1, dklen=32)
    return f"s1${n}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_strong(stored: str, pw: str) -> bool:
    try:
        _, n, salt, dk = stored.split("$")
        calc = hashlib.scrypt(pw.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:  # noqa: BLE001
        return False


def password_problem(pw: str) -> str:
    """새 비밀번호 정책 — 문제가 있으면 안내 문구, 없으면 빈 문자열"""
    # 정책: 4~8자 · 숫자만 또는 문자(영문·한글)만 — 숫자와 문자를 섞는 조합 규칙은 두지 않는다
    if re.search(r"\s", pw):
        return "비밀번호에 공백은 쓸 수 없습니다."
    if not 4 <= len(pw) <= 8:
        return "비밀번호는 4자 이상 8자 이내여야 합니다."
    if not (re.fullmatch(r"\d+", pw) or re.fullmatch(r"[A-Za-z가-힣]+", pw)):
        return "비밀번호는 숫자만 또는 문자(영문·한글)만 쓸 수 있습니다. 특수문자는 사용할 수 없습니다."
    if len(set(pw)) == 1:
        return "같은 글자만 반복한 비밀번호는 쓸 수 없습니다."
    if pw.lower() in ("1234", "12345", "123456", "1234567", "12345678", "0000", "4321", "abcd", "abcdef", "qwer", "password"):
        return "너무 흔한 비밀번호입니다. 다른 비밀번호를 쓰세요."
    return ""


def pw_matches(rec: dict, ident: str, pw: str) -> tuple[bool, bool]:
    """(일치 여부, 기존 방식으로 확인했는지)"""
    if rec.get("pwHash2"):
        return verify_strong(rec["pwHash2"], pw), False
    if rec.get("pwHash"):
        return pw_key(ident, pw) == rec["pwHash"], True
    return False, False


def is_gmail(x: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9._%+-]+@(gmail|googlemail)\.com", (x or "").strip(), re.I))


def today_str() -> str:
    return _dt.date.today().isoformat()


def map_role(r: str | None) -> str:
    return {"admin": "sysadmin", "lead": "orgadmin", "coder": "user"}.get(r or "", r or "user")


ROLE_LABEL = {"sysadmin": "시스템 관리자", "orgadmin": "기관 관리자", "user": "사용자"}


def acc_status(a: dict, orgs: list[dict], today: str | None = None) -> dict:
    """계정 상태 — 활성 여부 · 기관 사용 여부 · 유효기간."""
    today = today or today_str()
    org = next((o for o in orgs if o.get("id") == a.get("orgId")), None)
    if not a.get("active", True):
        return {"ok": False, "label": "비활성", "msg": "비활성 계정입니다. 소속 기관 관리자에게 문의하세요."}
    if org and org.get("active") is False:
        return {"ok": False, "label": "기관 사용 중지", "msg": f"소속 기관({org['name']})의 사용이 중지되었습니다."}
    if not a.get("noLimit") and a.get("from") and today < a["from"]:
        return {"ok": False, "label": f"예약 · {a['from']} 시작", "msg": f"사용 기간 전입니다 — {a['from']}부터 로그인할 수 있습니다."}
    if not a.get("noLimit") and a.get("to") and today > a["to"]:
        return {"ok": False, "label": f"만료 · {a['to']}", "msg": f"사용 기간({a['to']}까지)이 끝났습니다. 관리자에게 연장을 요청하세요."}
    label = "사용 중" if a.get("noLimit") or not a.get("to") else f"사용 중 · {a['to']}까지"
    return {"ok": True, "label": label, "msg": ""}


def authenticate(mode: str, ident: str, pw: str, org_id: str, accounts: list[dict],
                 orgs: list[dict], sys_admin: dict | None) -> tuple[dict | None, str]:
    """로그인 검증. 성공 시 (사용자 dict, ""), 실패 시 (None, 오류 메시지)."""
    ident = (ident or "").strip()
    if mode == "admin":
        sa = sys_admin or {"pwHash": pw_key("admin", "1234"), "pwTemp": True}
        ok, legacy = pw_matches(sa, "admin", pw)
        if ident.lower() != "admin" or not ok:
            return None, "시스템 관리자 아이디 또는 비밀번호가 올바르지 않습니다."
        return {"id": "admin", "role": "sysadmin", "orgId": org_id, "name": "시스템 관리자",
                "via": "admin", "pwTemp": bool(sa.get("pwTemp")) or not sys_admin, "legacyPw": legacy}, ""
    if not ident or not pw:
        return None, ("사번" if mode == "emp" else "Gmail") + "과 비밀번호를 입력하세요."
    if mode == "emp":
        acc = next((x for x in accounts if x.get("orgId") == org_id
                    and str(x.get("empNo", "")).lower() == ident.lower()), None)
        if not acc:
            return None, f"선택한 소속기관에 등록되지 않은 사번입니다 ({ident})."
    else:
        if not is_gmail(ident):
            return None, "Gmail 주소(@gmail.com)로 입력하세요."
        acc = next((x for x in accounts if str(x.get("id", "")).lower() == ident.lower()), None)
        if not acc or acc.get("orgId") != org_id:
            return None, f"선택한 소속기관에 등록되지 않은 Gmail입니다 ({ident})."
    if not acc.get("pwHash") and not acc.get("pwHash2"):
        return None, "비밀번호가 아직 지정되지 않았습니다 — 기관 관리자에게 비밀번호 초기화를 요청하세요."
    ok, legacy = pw_matches(acc, acc["id"], pw)
    if not ok:
        return None, "비밀번호가 올바르지 않습니다."
    st = acc_status(acc, orgs)
    if not st["ok"]:
        return None, st["msg"]
    return {"id": acc["id"], "role": map_role(acc.get("role")), "orgId": acc.get("orgId"),
            "name": acc.get("name", ""), "via": "사번" if mode == "emp" else "Gmail",
            "pwTemp": bool(acc.get("pwTemp")), "legacyPw": legacy}, ""
