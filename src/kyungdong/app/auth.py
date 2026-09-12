"""인증 — 로그인 · 로그아웃 · 비밀번호 정책 (개발1 · contracts/interfaces.md §9).

**DEF-QA3-002 · D-94 — 아키텍트가 만든 `util/session.py` · `util/ratelimit.py` 를
   아무도 부르지 않아 통째로 죽어 있었다. 이 파일이 그 둘을 부르는 유일한 곳이다.**

여기서 정하는 것은 없다. 수치는 전부 `.env` 가설값(D-16)이고 화면에 `가설 (D-16)` 배지로 드러낸다.
  · `PASSWORD_MIN_LEN` · `PASSWORD_COMPLEXITY_CLASSES` — 비밀번호 정책 (9.2-2 "복잡도")
  · `PASSWORD_CHANGE_CYCLE_DAYS` — 주기적 변경 (9.2-2) · `SYS_USERS.PWD_CHANGED_DT` 로 잰다
  · `LOGIN_FAIL_MAX` · `RATE_LIMIT_IP` — 계정 잠금 (`util/ratelimit.py`)
  · `SESSION_IDLE_MINUTES` — 자동 로그아웃 (`util/session.py`)

로그인·로그아웃은 **`SYS_ACCESS_LOGS` 에 `LOG_TYPE='접속'`** 으로 남는다(G-29).
실패도 남긴다 — 조용히 지나가는 인증 실패를 만들지 않는다(G-30).

**해시는 `db/seed.py hash_password()` 와 같은 argon2 다.** 비밀번호 원문은 어디에도 저장·기록하지
않고 **URL 에도 싣지 않는다**(DEF-QA3 High — `/sys/026` 도 같은 이유로 POST 본문 응답으로 바꿨다).
"""
from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "db"))

import conn                                              # noqa: E402
from . import design                                     # noqa: E402
from .settings import settings                           # noqa: E402
from .templating import render                           # noqa: E402
from .util import clock, csrf, http, ratelimit, session  # noqa: E402
from .util.audit import RESULT_ERR, RESULT_OK, audit     # noqa: E402

router = APIRouter()

# 로그인은 TD3 45화면이 아니라 공통화면(login)이다 → `SYS_ACCESS_LOGS.SCREEN_ID` 는 비운다.
# 지어낸 화면 ID 를 넣지 않는다(§0.2). 프로그램은 정본상 MES-TD4-026 이다.
SCREEN_ID: str | None = None

# 비밀번호 복잡도 — 충족 종류를 센다. **종류 수(가설 D-16)는 `.env` 에 있고 여기 상수가 아니다**(§10-1).
CLASSES: tuple[tuple[str, str], ...] = (
    ("영문 소문자", string.ascii_lowercase),
    ("영문 대문자", string.ascii_uppercase),
    ("숫자", string.digits),
    ("특수문자", string.punctuation),
)
# 발급용 특수문자는 **화면에 그대로 읽히는 것**만 쓴다 — `&`·`<`·따옴표는 이스케이프되어
# 사용자가 옮겨 적기 어렵다. 검증(`policy_errors`)은 특수문자 전체를 인정한다.
SAFE_SPECIALS = "!@#$%^*_-+=?"


# ── 비밀번호 정책 (9.2-2 · 가설 D-16) ────────────────────────────────────
def policy_badges() -> list[Any]:
    s = settings()
    return [s.h(k) for k in ("PASSWORD_MIN_LEN", "PASSWORD_COMPLEXITY_CLASSES",
                             "PASSWORD_CHANGE_CYCLE_DAYS", "LOGIN_FAIL_MAX",
                             "SESSION_IDLE_MINUTES")]


def policy_errors(raw: str) -> list[str]:
    """정책 위반 사유. 빈 리스트면 통과. **호출자는 422 로 막는다**(강제하지 않으면 정책이 아니다)."""
    s = settings()
    out: list[str] = []
    min_len = s.h("PASSWORD_MIN_LEN")
    if len(raw) < min_len.as_int():
        out.append(f"최소 {min_len.as_int()}자 이상이어야 한다 {min_len.badge}")
    need = s.h("PASSWORD_COMPLEXITY_CLASSES")
    got = [name for name, chars in CLASSES if any(c in chars for c in raw)]
    if len(got) < need.as_int():
        out.append(f"영문 대/소문자·숫자·특수문자 중 {need.as_int()}종류 이상을 섞는다 — "
                   f"지금 {len(got)}종류({', '.join(got) or '없음'}) {need.badge}")
    return out


def generate_password() -> str:
    """정책을 만족하는 난수. `/sys/026` 계정 발급이 쓴다 — 문서에 적힌 공통 비밀번호를 만들지 않는다(G-29)."""
    need = settings().h("PASSWORD_COMPLEXITY_CLASSES").as_int()
    length = max(settings().h("PASSWORD_MIN_LEN").as_int(), 12)
    safe = [(n, SAFE_SPECIALS if n == "특수문자" else c) for n, c in CLASSES]
    pools = [chars for _n, chars in safe[:max(1, min(need, len(safe)))]]
    alphabet = "".join(chars for _n, chars in safe)
    for _ in range(100):
        raw = ("".join(secrets.choice(p) for p in pools)
               + "".join(secrets.choice(alphabet) for _ in range(length - len(pools))))
        raw = "".join(secrets.SystemRandom().sample(raw, len(raw)))
        if not policy_errors(raw):
            return raw
    raise http.fail("internal", "정책을 만족하는 비밀번호를 생성하지 못했다 — 정책값을 확인한다 (D-16)")


def password_age_notice(pwd_changed_dt: Any) -> str:
    """주기 변경 안내(9.2-2). 값이 없으면 **모른다고 말한다** — 조용히 정상으로 두지 않는다."""
    cycle = settings().h("PASSWORD_CHANGE_CYCLE_DAYS")
    if pwd_changed_dt is None:
        return f"비밀번호 최종 변경일이 없다 — 변경을 권고한다 (주기 {cycle.value}일 {cycle.badge})"
    days = (clock.real_now() - pwd_changed_dt).days
    if days >= cycle.as_int():
        return (f"비밀번호를 바꾼 지 {days}일 지났다 — 변경 주기 {cycle.value}일 초과 "
                f"{cycle.badge}")
    return ""


# ── 해시 (db/seed.py hash_password 와 같은 argon2) ───────────────────────
def hash_password(raw: str) -> str:
    from passlib.hash import argon2
    return argon2.hash(raw)


def verify_password(raw: str, stored: str | None) -> bool:
    if not stored:
        return False
    from passlib.hash import argon2
    try:
        return bool(argon2.verify(raw, stored))
    except ValueError:
        # 해시 형식이 깨진 계정. **통과시키지 않고**, 조용히 넘기지도 않는다.
        return False


# ── 공통 ─────────────────────────────────────────────────────────────────
def _ip(request: Request) -> str | None:
    return getattr(getattr(request, "client", None), "host", None)


def _log(request: Request, action: str, *, ok: bool, error: str | None = None,
         user_id: int | None = None, log_type: str = "접속") -> None:
    audit(request, SCREEN_ID, action, log_type=log_type,
          result=RESULT_OK if ok else RESULT_ERR, error=error, user_id=user_id)


def _user(login_id: str) -> dict | None:
    return conn.q1(
        "select u.USER_ID, u.LOGIN_ID, u.PASSWORD_HASH, u.LOCK_YN, u.USE_YN, "
        "u.PWD_CHANGED_DT, p.ROLE_CODE from SYS_USERS u "
        "left join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID "
        "where u.LOGIN_ID = %s", (login_id,))


def safe_next(raw: str | None) -> str:
    """로그인 뒤 갈 곳. **우리 앱 안의 경로만** 허용한다 (D-205).

    `next` 를 그대로 믿으면 **열린 리다이렉트**가 된다 — `?next=` 에 **외부 절대주소**를 넣어 로그인
    직후 외부로 튕겨 보낼 수 있고, 사용자는 방금 우리 화면에서 로그인했으니 그 페이지를
    믿는다. 그래서 **`/` 로 시작하고 `//` 가 아닌 경로**만 통과시키고 나머지는 `/` 로 보낸다.
    """
    raw = (raw or "").strip()
    # **역슬래시를 먼저 막는다.** 브라우저에 따라 `/\evil` 을 `//evil`(프로토콜 상대)로
    # 읽어 외부로 나간다 — `urlparse` 는 이것을 경로로 보기 때문에 그것만 믿으면 뚫린다.
    if "\\" in raw:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    u = urlparse(raw)
    if u.scheme or u.netloc:
        return "/"
    return raw


def login_page(request: Request, *, status_code: int = 200, error: str = "",
               notice: str = "", signed_in: dict | None = None) -> HTMLResponse:
    """공통화면 `login` 을 렌더한다. 문구·버튼은 정본(SF-TD3 common)에서 온다."""
    return render(request, "login.html", status_code=status_code,
                  common=design.common_screens()["login"],
                  policy=policy_badges(), error=error, notice=notice,
                  signed_in=signed_in, idle_minutes=settings().h("SESSION_IDLE_MINUTES"))


# ═════════════════════════════════════════════════════════════════════════
# POST /login — 잠금 확인 → 비밀번호 검증 → 세션 발급
# ═════════════════════════════════════════════════════════════════════════
@router.post("/login")
async def login(request: Request):
    form = await request.form()
    csrf.require(request, form.get(csrf.FORM_FIELD))
    login_id = (form.get("login_id") or "").strip()
    password = form.get("password") or ""
    ip = _ip(request)

    if not login_id or not password:
        _log(request, "로그인", ok=False, error="사용자ID·비밀번호 누락")
        raise http.fail("validation", "사용자ID와 비밀번호를 입력한다")

    # ① 잠금을 **먼저** 본다 — 잠긴 계정에 비밀번호 검증을 돌리지 않는다.
    blocked, why = ratelimit.blocked(login_id, ip)
    if blocked:
        _log(request, "로그인", ok=False, error=f"잠금 — {why}")
        return login_page(request, status_code=403,
                          error=f"로그인 시도가 잠겼다 — {why}. 10분 창이 지나면 풀린다 "
                                "(관리자에게 해제를 요청한다).")

    row = _user(login_id)
    if row is None or not verify_password(password, row["password_hash"]):
        ratelimit.record_failure(login_id, ip)
        _log(request, "로그인", ok=False, user_id=(row or {}).get("user_id"),
             error="비밀번호 불일치" if row else "없는 계정")
        now_blocked, why2 = ratelimit.blocked(login_id, ip)      # 이번 실패로 한도에 닿았는가
        if now_blocked:
            return login_page(request, status_code=403,
                              error=f"실패가 한도에 닿아 잠겼다 — {why2}. "
                                    f"{ratelimit.WINDOW_SEC // 60}분 창이 지나면 풀린다.")
        return login_page(request, status_code=401,
                          error="사용자ID 또는 비밀번호가 올바르지 않다 "
                                f"(계정 잠금 한도 {settings().h('LOGIN_FAIL_MAX').value}회 "
                                f"{settings().h('LOGIN_FAIL_MAX').badge}).")

    # ② 계정 상태 — 잠금·미사용은 비밀번호가 맞아도 들여보내지 않는다.
    if row["lock_yn"] == "Y":
        _log(request, "로그인", ok=False, user_id=row["user_id"], error="계정 잠금(LOCK_YN=Y)")
        return login_page(request, status_code=403,
                          error="계정이 잠겨 있다 (SYS_USERS.LOCK_YN=Y) — 관리자가 해제한다.")
    if row["use_yn"] != "Y":
        _log(request, "로그인", ok=False, user_id=row["user_id"], error="미사용 계정(USE_YN≠Y)")
        return login_page(request, status_code=403,
                          error="사용하지 않는 계정이다 (SYS_USERS.USE_YN≠Y).")
    if not row["role_code"]:
        _log(request, "로그인", ok=False, user_id=row["user_id"], error="역할 미배정")
        return login_page(request, status_code=403,
                          error="역할이 배정되지 않은 계정이다 — 권한을 열어주지 않는다 (G-28).")

    # ③ 성공 — 잠금 해제 · 세션 발급 · 접속 기록
    ratelimit.clear(login_id, ip)
    cookie, sess = session.create(int(row["user_id"]), row["login_id"], row["role_code"])
    _log(request, "로그인", ok=True, user_id=int(row["user_id"]))
    # **로그인했으면 업무 화면으로 보낸다** (D-205). 전에는 로그인 페이지를 다시 렌더해
    # `signed_in` 만 보여 줬다 — 운영에서는 로그인하고도 **어디로 가야 할지 모른다.**
    # 비밀번호 주기 경고는 목적지에서 배지로 보이므로 여기서 붙들지 않는다.
    nxt = safe_next(form.get("next") or request.query_params.get("next"))
    resp: Response = RedirectResponse(nxt, status_code=303)
    if not settings().is_prod:
        # dev 에서는 **화면을 그대로 보여 준다** — 세션 발급이 눈에 보여야 시험이 된다.
        resp = login_page(request, notice=password_age_notice(row["pwd_changed_dt"]),
                          signed_in={"login_id": row["login_id"], "role_code": row["role_code"],
                                     "sid": sess.sid[:6] + "…"})
    resp.set_cookie(session.COOKIE, cookie, httponly=True, samesite="lax",
                    secure=settings().is_prod)
    return resp


# ═════════════════════════════════════════════════════════════════════════
# POST /logout — 쿠키 삭제로 끝내지 않고 **서버측 레지스트리에서 지운다** (G-27)
# ═════════════════════════════════════════════════════════════════════════
@router.post("/logout")
async def logout(request: Request):
    form = await request.form()
    csrf.require(request, form.get(csrf.FORM_FIELD))
    sess = getattr(request.state, "session", None)
    user_id = getattr(sess, "user_id", None)
    destroyed = session.destroy(request.cookies.get(session.COOKIE))
    _log(request, "로그아웃", ok=destroyed, user_id=user_id,
         error=None if destroyed else "끊을 세션이 없다 (이미 로그아웃·만료)")
    resp = login_page(
        request,
        notice="로그아웃했다 — 서버측 세션 레지스트리에서도 지웠다 (G-27)." if destroyed
        else "끊을 세션이 없었다 — 이미 로그아웃했거나 유휴 시간이 지나 만료됐다.")
    resp.delete_cookie(session.COOKIE)
    return resp


# ═════════════════════════════════════════════════════════════════════════
# POST /password — 비밀번호 변경. **정책을 여기서 강제한다** (9.2-2 · DEF-QA3 High)
# ═════════════════════════════════════════════════════════════════════════
@router.post("/password")
async def change_password(request: Request):
    form = await request.form()
    csrf.require(request, form.get(csrf.FORM_FIELD))
    sess = getattr(request.state, "session", None)
    if sess is None:
        _log(request, "비밀번호 변경", ok=False, error="미인증", log_type="변경")
        raise http.fail("unauthenticated", "로그인한 뒤에 비밀번호를 바꾼다")

    current = form.get("current_password") or ""
    new = form.get("new_password") or ""
    confirm = form.get("confirm_password") or ""
    row = _user(sess.login_id)
    if row is None:
        _log(request, "비밀번호 변경", ok=False, user_id=sess.user_id,
             error="계정이 사라졌다", log_type="변경")
        raise http.fail("internal", "세션의 계정을 찾을 수 없다")
    if not verify_password(current, row["password_hash"]):
        ratelimit.record_failure(sess.login_id, _ip(request))
        _log(request, "비밀번호 변경", ok=False, user_id=sess.user_id,
             error="현재 비밀번호 불일치", log_type="변경")
        return login_page(request, status_code=401,
                          error="현재 비밀번호가 올바르지 않다.",
                          signed_in={"login_id": sess.login_id, "role_code": sess.role_code,
                                     "sid": sess.sid[:6] + "…"})
    if new != confirm:
        _log(request, "비밀번호 변경", ok=False, user_id=sess.user_id,
             error="확인값 불일치", log_type="변경")
        raise http.fail("validation", "새 비밀번호와 확인값이 다르다")
    if new == current:
        _log(request, "비밀번호 변경", ok=False, user_id=sess.user_id,
             error="직전과 동일", log_type="변경")
        raise http.fail("validation", "직전과 같은 비밀번호로 바꿀 수 없다")
    errs = policy_errors(new)
    if errs:
        _log(request, "비밀번호 변경", ok=False, user_id=sess.user_id,
             error="정책 위반: " + " · ".join(errs), log_type="변경")
        raise http.fail("validation", "비밀번호 정책 위반 — " + " · ".join(errs))

    conn.x("update SYS_USERS set PASSWORD_HASH = %s, PWD_CHANGED_DT = now(), UPDATED_DT = now() "
           "where USER_ID = %s", (hash_password(new), int(sess.user_id)))
    ratelimit.clear(sess.login_id, _ip(request))
    cut = session.destroy_user(int(sess.user_id))       # 변경했으면 기존 세션을 전부 끊는다
    _log(request, "비밀번호 변경", ok=True, user_id=sess.user_id, log_type="변경")
    resp = login_page(request,
                      notice=f"비밀번호를 바꿨다 — 기존 세션 {cut}건을 끊었다. 다시 로그인한다.")
    resp.delete_cookie(session.COOKIE)
    return resp
