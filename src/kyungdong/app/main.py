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
from .util import http, security, session

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
    response = await call_next(request)
    for k, v in security.headers().items():
        response.headers.setdefault(k, v)
    return response


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


@app.get("/board")
async def board_screen(request: Request):
    return render(request, "board.html",
                  common=design.common_screens()["dashboard"],
                  refresh=settings().h("BOARD_REFRESH_SEC"))


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
