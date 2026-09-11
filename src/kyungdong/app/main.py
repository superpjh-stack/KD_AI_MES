"""FastAPI 앱 — 45화면 + 공통 4 + 오류.

웨이브 A(아키텍트): 45화면 전부를 `_placeholder` 로 **200** 에 세운다. 담당 개발자가
`app/routers/<module>.py` 에 `router` 를 만들면 **그것이 이긴다** — main.py 는 덮어쓰지 않고
남은 화면만 placeholder 로 채운다. 한 파일은 한 사람만 만진다(goal.md §3.4).

G-03 은 두 조건이다: ① 전부 200  ② `_placeholder` **0건**. 지금은 ①만 통과한다.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import design, nav
from .settings import settings
from .templating import render
from .util import csrf, http, security, session
from .util.audit import RESULT_ERR, audit

app = FastAPI(title="경동글로벌텍 제조AI 시스템", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# 담당 개발자가 만든 라우터가 있으면 싣는다. 없으면 placeholder 가 맡는다.
COVERED: set[str] = set()
for module in sorted({s.module for s in nav.all_screens()}):
    try:
        mod = importlib.import_module(f".routers.{module}", __package__)
    except ModuleNotFoundError:
        continue
    router = getattr(mod, "router", None)
    if router is None:
        continue
    app.include_router(router)
    COVERED.update(getattr(mod, "SCREENS", ()))


@app.middleware("http")
async def attach_role(request: Request, call_next):
    """세션이 있으면 세션 역할, 없으면 개발용 전환값(D-40).

    **prod 에서는 개발용 전환을 받지 않는다** — 인증 없이 화면이 열리면 보안 결함이다.
    개발1 이 `app/auth.py` 를 넣으면 미인증 요청은 401 로 막히고 이 분기가 사라진다.
    """
    sess = session.load(request.cookies.get(session.COOKIE))
    request.state.session = sess
    if sess is not None:
        request.state.role_code = sess.role_code
    elif settings().is_prod:
        request.state.role_code = ""          # 권한 없음 → 403/401 로 드러난다
    else:
        request.state.role_code = (
            request.query_params.get("as")
            or request.headers.get("x-kyungdong-role")
            or "SYSADMIN"
        ).upper()
    # 세션이 없으면 CSRF 토큰을 묶을 쿠키가 필요하다(util/csrf.py `_bind`).
    # **토큰을 발급하기 전에** 값이 정해져야 한다 — 응답에서 처음 심으면 이 요청에서 렌더한
    # 폼의 토큰이 다음 POST 에서 무효가 된다(D-60 실측).
    new_csrf_cookie = ""
    if sess is None and not request.cookies.get(csrf.COOKIE):
        new_csrf_cookie = csrf.new_cookie_value()
    request.state.csrf_cookie = new_csrf_cookie

    # ── 권한 가드 (D-78) — **폼 파싱보다 먼저** 본다 ──────────────────
    # FastAPI 의 `Form(...)` 은 핸들러 본문보다 앞서 파싱된다. 핸들러 안에서만 권한을 보면
    # 권한 없는 역할이 403 이 아니라 **422** 를 받는다(실측 재현). 계약 §4.0 검사 순서를 지킨다.
    denied = _permission_denied(request)
    if denied is not None:
        if new_csrf_cookie:
            denied.set_cookie(csrf.COOKIE, new_csrf_cookie, httponly=True, samesite="lax",
                              secure=settings().is_prod)
        return denied

    response = await call_next(request)
    for k, v in security.headers().items():
        response.headers.setdefault(k, v)
    if new_csrf_cookie:
        response.set_cookie(csrf.COOKIE, new_csrf_cookie,
                            httponly=True, samesite="lax", secure=settings().is_prod)
    return response


# 업무 화면 경로만 가드한다. `/api/*` 는 자체 검사를 하고, 공통 화면은 권한 영역이 없다.
_SKIP_PREFIXES = ("/api", "/static", "/health", "/login", "/popup", "/error", "/board")


def _screen_for(path: str):
    """`/est/012/confirm` → `/est/012` 화면. 모르면 None."""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    return nav.by_path().get(f"/{parts[0]}/{parts[1]}")


def _permission_denied(request: Request):
    if request.url.path == "/" or request.url.path.startswith(_SKIP_PREFIXES):
        return None
    screen = _screen_for(request.url.path)
    if screen is None:
        return None
    from . import rbac
    role = request.state.role_code
    mutating = request.method in ("POST", "PUT", "PATCH", "DELETE")
    if mutating:
        # **가드는 "권한이 아예 없는 경우" 만 막는다.** 세부 판정은 핸들러가 한다.
        # 총괄PM/경영자는 `조회/승인` — 등록·수정 권한 없이 **승인만** 가능하다.
        # 여기서 can_write 만 요구하면 승인해야 할 역할을 막는다(실측으로 걸렸다).
        allowed = rbac.can_write(role, screen.area) or rbac.can_approve(role, screen.area)
    else:
        allowed = rbac.can_read(role, screen.area)
    if allowed:
        return None
    # **거부도 감사에 남긴다** (G-29 · D-97). 이 가드가 라우터 `guard()` 보다 **앞서** 돌기 때문에
    # 여기서 안 남기면 403 거부는 `SYS_ACCESS_LOGS` 에 한 줄도 남지 않는다 — QA3 실측 `오류` 0건의
    # 실제 원인이다. 화면마다 흩뿌리지 않고 **공용 가드 한 곳**에서 남긴다.
    reason = f"{screen.area} {'쓰기' if mutating else '조회'} 권한 없음 (역할 {role or '없음'})"
    sess = getattr(request.state, "session", None)
    audit(request, screen.id, "쓰기거부" if mutating else "조회거부",
          log_type="오류", result=RESULT_ERR, error=reason,
          user_id=getattr(sess, "user_id", None))
    case = http.BY_KEY["forbidden"]
    return render(request, "_error.html", status_code=case.status, status=case.status,
                  message=case.message,
                  detail=f"{screen.area} {'쓰기' if mutating else '조회'} 권한이 없습니다")


@app.get("/health")
async def health() -> JSONResponse:
    chk = design.selfcheck()
    bad = {k: v for k, (got, want, ok) in chk.items() if not (ok) for v in [f"{got}≠{want}"]}
    return JSONResponse(
        {"status": "ok" if not bad else "정본 불일치", "canon": bad or "45/10/49/68/762 일치"},
        status_code=200 if not bad else 500,
    )


# ── 공통 화면 (td3.common_screens 4종) ───────────────────────────────────
@app.get("/")
async def main_screen(request: Request):
    chk = design.selfcheck()
    return render(request, "common.html",
                  common=design.common_screens()["common"],
                  counts={k: got for k, (got, _w, _o) in chk.items()})


@app.get("/login")
async def login_screen(request: Request):
    s = settings()
    return render(request, "login.html",
                  common=design.common_screens()["login"],
                  policy=[s.h(k) for k in ("PASSWORD_MIN_LEN", "PASSWORD_CHANGE_CYCLE_DAYS",
                                           "LOGIN_FAIL_MAX", "SESSION_IDLE_MINUTES")])


@app.get("/popup")
async def popup_screen(request: Request):
    return render(request, "_popup.html",
                  common=design.common_screens()["popup"], cases=http.CASES)


# `/board` 현황판은 **개발2 소유**다 — `routers/kpi.py` 가 등록한다(D-57).
# 여기에 두면 한 경로에 핸들러가 둘이 된다. 아키텍트는 `board.html` 도 개발2 에게 넘겼다.


@app.get("/error")
async def error_screen(request: Request):
    return render(request, "_error.html", status=500,
                  message="공통 오류 화면", detail="오류 계약 확인용 화면이다.")


# ── 45화면 — 담당 라우터가 없는 것만 placeholder 로 세운다 ────────────────
def _placeholder_route(screen: nav.Screen):
    async def handler(request: Request):
        from . import rbac
        if not rbac.can_read(request.state.role_code, screen.area):
            raise http.fail("forbidden", f"{screen.area} 조회 권한 없음")
        td3 = design.screen(screen.id) or {}
        return render(
            request, "_placeholder.html",
            current=screen, screen=screen, td3=td3,
            requirement=design.requirement(screen.requirement_id),
            program=design.program(screen.program_id),
            tables=[
                {"id": t, "name": (design.table_def(t) or {}).get("name", ""),
                 "columns": design.columns_of(t)}
                for t in design.program_tables(screen.program_id)
            ],
        )
    handler.__name__ = f"placeholder_{screen.prefix}_{screen.no}"
    return handler


PLACEHOLDERS: list[str] = []
for _s in nav.all_screens():
    if _s.id in COVERED:
        continue
    PLACEHOLDERS.append(_s.id)
    app.add_api_route(_s.path, _placeholder_route(_s), methods=["GET"],
                      name=f"screen_{_s.no}", include_in_schema=False)


# ── 오류 계약 (§2.5) — 조용히 200 을 내지 않는다 ──────────────────────────
@app.exception_handler(HTTPException)
async def on_http_error(request: Request, exc: HTTPException):
    d = exc.detail if isinstance(exc.detail, dict) else {}
    case = http.BY_KEY.get(d.get("key", ""))
    return render(request, "_error.html", status_code=exc.status_code,
                  status=exc.status_code,
                  message=d.get("message") or (case.message if case else "오류"),
                  detail=d.get("detail", ""))


@app.exception_handler(Exception)
async def on_unhandled(request: Request, exc: Exception):
    """전역 500 — 예외 내용을 사용자에게 노출하지 않는다(§10-12). 기록은 SYS_ACCESS_LOGS(개발1)."""
    return render(request, "_error.html", status_code=500, status=500,
                  message=http.BY_KEY["internal"].message, detail="")
