"""Jinja2 렌더러 — `contracts/interfaces.md` 공표 시그니처: `render(request, name, **ctx)`.

**그리드 셀은 이스케이프가 기본이다**(goal.md §10-8). `|safe` 를 그리드에 쓰지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import nav, rbac
from .settings import settings

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


def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    role = getattr(request.state, "role_code", None) or "SYSADMIN"
    s = settings()
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
        cad_configured=s.cad_configured,
        **ctx,
    )
    return HTMLResponse(html, status_code=status_code)
