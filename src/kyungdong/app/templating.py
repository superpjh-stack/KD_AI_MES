"""Jinja2 렌더러 — `contracts/interfaces.md` 공표 시그니처: `render(request, name, **ctx)`.

**그리드 셀은 이스케이프가 기본이다**(goal.md §10-8). `|safe` 를 그리드에 쓰지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import followup, nav, rbac
from .util import csrf
from .settings import settings


def _synthetic_note() -> str:
    """합성 데이터 고지 — `SYS_CONFIGS('시스템설정','SYNTHETIC_THREAD')` 선언 **한 곳**에서 읽는다.

    사용자 지시로 디지털 스레드를 합성으로 채웠다(D-131). 그러면 그 데이터를 읽는 화면 전부에
    고지가 붙어야 한다 — goal.md §2.3 이 광성정밀 사업에서 실제로 요구한 처리다.
    **DB 를 못 읽으면 배지를 숨기지 않는다** — 숨기면 합성이 실측처럼 보인다.
    """
    import conn                      # 지연 임포트 — 템플릿 모듈이 db 를 끌고 들어오지 않게
    try:
        row = conn.q1(
            "select CONFIG_VALUE from SYS_CONFIGS where CONFIG_TYPE = '시스템설정' "
            "and CONFIG_KEY = 'SYNTHETIC_THREAD' and USE_YN = 'Y'")
    except Exception:                # DB 장애는 다른 게이트(G-30)가 잡는다 — 여기서 삼키지 않게 빈 값
        return ""
    if not row or not row["config_value"]:
        return ""
    return f"합성 데이터 기준 ({row['config_value']})"

def _sample_note() -> str:
    """표본 확대 고지 (D-199) — 기본 40 이면 **빈 문자열**이다(평소에는 안 뜬다).

    `합성 데이터 기준 (D-131)` 이 *지어낸 것*을 말한다면 이것은 *몇 건을 지어냈는지*를
    말한다. 기본 40 은 실측(프로젝트 12 × 갑지 근거 BOM 4)에 묶여 있고, 그보다 키운
    표본은 **화면을 굴려 보려고 늘린 것**이라 같은 근거가 없다.
    """
    import conn

    try:
        row = conn.q1(
            "select DESCRIPTION from SYS_CONFIGS where CONFIG_TYPE = '시스템설정' "
            "and CONFIG_KEY = 'SAMPLE_SCALE' and USE_YN = 'Y'")
    except Exception:                # noqa: BLE001 — DB 장애는 G-30 이 잡는다
        return ""
    if not row or not row["description"]:
        return ""
    head = str(row["description"]).split(".")[0].replace("**", "")
    return f"표본 확대 (D-199) — {head}"


TEMPLATES = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(("html", "xml")),   # 기본 이스케이프 (§10-8)
    trim_blocks=True,
    lstrip_blocks=True,
)


def _visible_menu(role_code: str) -> list[tuple[str, list[nav.Screen]]]:
    """권한 있는 것만 노출 (G-28)."""
    out = []
    for shortcut, group in nav.menu():
        allowed = [s for s in group if rbac.can_read(role_code, s.area)]
        if allowed:
            out.append((shortcut, allowed))
    return out


def _followups(request: Request) -> list:
    """이 화면에 걸린 **미비 항목**. 경로로 화면을 찾고 `decisions.md` 에서 읽는다(D-188).

    **화면이 자기 목록을 들지 않는다** — 대장이 정본이고 여기가 읽기만 한다. 화면마다
    목록을 박아 두면 대장과 어긋나고, 그 사고를 이미 두 번 겪었다(D-163 · D-181).
    화면을 못 찾으면 **빈 목록**이다. 아무 화면에나 붙이지 않는다.
    """
    sc = nav.by_path().get(request.url.path)
    if sc is None:
        return []
    try:
        return followup.for_screen(sc.no)
    except Exception:                # noqa: BLE001 — 대장을 못 읽어도 화면은 떠야 한다
        return []


def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    role = getattr(request.state, "role_code", None) or "SYSADMIN"
    s = settings()
    # 로그인한 계정 (D-206). 운영 화면은 **누가 보고 있는지**와 **나가는 길**이 있어야 한다.
    # 세션이 없으면 `None` 이고, dev 에서는 그 사실을 배지로 드러낸다 — 자동 로그인을
    # 로그인한 것처럼 보이게 하지 않는다.
    sess = getattr(request.state, "session", None)
    tpl = _env.get_template(name)
    html = tpl.render(
        request=request,
        menu=_visible_menu(role),
        role=rbac.roles().get(role),
        system_name="경동글로벌텍 제조AI 시스템",
        env=s.env,
        search_mode=s.search_mode,
        llm_configured=s.llm_configured,
        csrf_enforced=s.csrf_enforce,
        csrf_token=csrf.issue(request),
        cad_configured=s.cad_configured,
        synthetic_note=_synthetic_note(),
        sample_note=_sample_note(),
        signed_in_id=getattr(sess, "login_id", None),
        followups=_followups(request),
        **ctx,
    )
    return HTMLResponse(html, status_code=status_code)
