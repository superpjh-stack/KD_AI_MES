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

FORM_FIELD = "_csrf"
HEADER = "X-CSRF-Token"
COOKIE = "kyungdong_csrf"


def _secret() -> bytes:
    s = settings()
    if s.is_prod and not s.session_secret:
        raise RuntimeError("prod 에서 SESSION_SECRET 없이 CSRF 토큰을 만들 수 없다")
    return (s.session_secret or "dev-only-not-a-secret").encode()


def _bind(request: Any) -> str:
    """토큰을 묶을 대상. 세션이 있으면 세션, 없으면 CSRF 쿠키."""
    sess = getattr(request.state, "session", None)
    if sess is not None:
        return f"sid:{sess.sid}"
    return f"cookie:{request.cookies.get(COOKIE, '')}"


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
    if not valid(request, token):
        raise http.fail("forbidden", "CSRF 토큰이 없거나 유효하지 않습니다")


def enforced() -> bool:
    return settings().csrf_enforce


def new_cookie_value() -> str:
    """세션이 없을 때 토큰을 묶을 값. 응답에 `COOKIE` 로 심는다."""
    return secrets.token_urlsafe(16)
