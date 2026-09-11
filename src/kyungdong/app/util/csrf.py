"""CSRF 토큰 (goal.md §10-12 · G-26).

**D-105 — 회전 5 에서 `csrf_enforce` 설정만 만들고 구현을 빠뜨렸다.** 개발1 이 잡아냈다.
설정 플래그가 켜져 있는데 검증 코드가 없으면 **켜져 있다고 착각하게 만드는** 최악의 형태다.

사용법 (쓰기 폼이 있는 화면 전부):
```python
# 렌더할 때
return render(request, "inv/005.html", csrf_token=csrf.issue(request))
# 템플릿
<input type="hidden" name="_csrf" value="{{ csrf_token }}">
# POST 처리 첫 줄
csrf.require(request, form.get("_csrf"))     # 위반 시 403
```

토큰은 **세션에 묶는다**. 세션이 없으면(개발 중 미인증) 토큰도 세션 독립 키로 발급하되
`ENV=prod` 에서는 세션 없는 쓰기를 애초에 허용하지 않는다(D-51).
"""
from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from typing import Any

from ..settings import settings
from . import http, session

# ── 기계 대 기계 엔드포인트 면제 (D-103) ────────────────────────────────
# CSRF 는 **브라우저가 쿠키를 자동으로 실어 보내는 것**을 막는 장치다.
# 아래 경로는 PLC·Gateway·배치가 부르고 **쿠키를 쓰지 않는다** — 이 위협에 해당하지 않는다.
# "막을 수 없으니 끈다" 가 아니라 **"적용 대상이 아니다"** 는 판단이다.
# **대신 다른 수단으로 보호해야 한다** — 장비 등록(`IF_DEVICE_REGISTRY`) 기반 인증. 미구현이면 차단으로 남긴다.
EXEMPT_PATHS: dict[str, str] = {
    "/api/ingest/plc": "레이저커팅기 Master PLC → Gateway. 세션·쿠키 없음 (D-06 수집 지점 2개소)",
    "/api/ingest/gateway/resend": "Gateway 버퍼 재전송. 세션·쿠키 없음",
    "/api/cad/files": "CAD 배치 수집. 세션·쿠키 없음 (D-05)",
    "/api/docs/import": "외부 표준문서 배치 수집. 세션·쿠키 없음",
}


def exempt(path: str) -> str | None:
    """면제 사유. 면제가 아니면 None. **목록에 없으면 무조건 검사한다.**"""
    return EXEMPT_PATHS.get(path)


FORM_FIELD = "_csrf"
HEADER = "X-CSRF-Token"
COOKIE = "kyungdong_csrf"


def _secret() -> bytes:
    s = settings()
    if s.is_prod and not s.session_secret:
        raise RuntimeError("prod 에서 SESSION_SECRET 없이 CSRF 토큰을 만들 수 없다")
    return (s.session_secret or "dev-only-not-a-secret").encode()


def pending_cookie(request: Any) -> str:
    """세션이 없을 때 토큰을 묶을 쿠키 값.

    **요청에 쿠키가 아직 없으면 그 요청에서 발급한 값**(`request.state.csrf_cookie`)을 쓴다.
    이게 없으면 첫 화면에서 발급한 토큰이 다음 POST 에서 항상 무효가 된다 —
    쿠키는 응답에 심기는데 토큰은 쿠키가 없던 시점에 만들어지기 때문이다(실측 재현).
    """
    got = request.cookies.get(COOKIE)
    if got:
        return got
    state = getattr(request, "state", None)
    return getattr(state, "csrf_cookie", "") or "" if state is not None else ""


def _bind(request: Any) -> str:
    """토큰을 묶을 대상. 세션이 있으면 세션, 없으면 CSRF 쿠키."""
    sess = getattr(request.state, "session", None)
    if sess is not None:
        return f"sid:{sess.sid}"
    return f"cookie:{pending_cookie(request)}"


def _sign(nonce: str, bind: str) -> str:
    return hmac.new(_secret(), f"{nonce}:{bind}".encode(), sha256).hexdigest()[:32]


def issue(request: Any) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_sign(nonce, _bind(request))}"


def valid(request: Any, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, sig = token.partition(".")
    return hmac.compare_digest(sig, _sign(nonce, _bind(request)))


def require(request: Any, token: str | None) -> None:
    """쓰기 처리 **첫 줄**에서 부른다. 위반이면 **403**(§2.5 forbidden).

    `KYUNGDONG_CSRF_ENFORCE=0` 이면 통과시키되, **그 사실이 화면에 드러나야** 한다 —
    조용히 꺼진 보안 장치를 만들지 않는다(G-30).
    """
    if not settings().csrf_enforce:
        return
    why = exempt(request.url.path)
    if why is not None:
        return                      # D-103 — 기계 대 기계. 사유는 EXEMPT_PATHS 에 적혀 있다
    if not valid(request, token):
        raise http.fail("forbidden", "CSRF 토큰이 없거나 유효하지 않습니다")


def token_of(request: Any, form: Any = None) -> str | None:
    """요청이 실어 온 토큰. **폼 필드 → 헤더** 순으로 본다.

    화면 폼은 `_macros.html` 의 `csrf_field()` 로 `_csrf` 를 싣고,
    **폼이 아닌 JSON API**(`/api/ingest/plc` 등)는 헤더 `X-CSRF-Token` 으로 싣는다(§5).
    """
    if form is not None:
        got = form.get(FORM_FIELD)
        if got:
            return str(got)
    return request.headers.get(HEADER)


def enforced() -> bool:
    return settings().csrf_enforce


def new_cookie_value() -> str:
    """세션이 없을 때 토큰을 묶을 값. 응답에 `COOKIE` 로 심는다."""
    return secrets.token_urlsafe(16)
