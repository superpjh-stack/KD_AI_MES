"""테스트 공용 인프라 — **아키텍트 소유**. 개발자·QA 가 함께 쓴다.

## CSRF 토큰 헬퍼 (D-102 · D-103)

`KYUNGDONG_CSRF_ENFORCE=1` 이면 쓰기 요청에 토큰이 필요하다. 실제 브라우저는 화면에서 받은
토큰을 폼에 실어 보낸다 — **테스트도 같아야 한다.** 토큰 없이 POST 하던 하네스는 403 을 받는다.

**이것은 게이트를 낮추는 게 아니라 하네스를 현실에 맞추는 일이다.**

```python
from conftest import csrf_post
r = csrf_post(client, "/inv/005", {"...": "..."}, page="/inv/005")
```

면제 경로(`util/csrf.EXEMPT_PATHS` — PLC·Gateway·CAD 배치)는 토큰 없이 그대로 POST 한다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

_TOKEN = re.compile(r'name="_csrf"\s+value="([^"]+)"')


def csrf_token(client: Any, page: str, **kw: Any) -> str | None:
    """화면을 열어 토큰을 꺼낸다. 토큰이 없으면 `None` — 폼이 없는 화면이다."""
    r = client.get(page, **kw)
    m = _TOKEN.search(r.text)
    return m.group(1) if m else None


def csrf_post(client: Any, path: str, data: dict[str, Any] | None = None,
              page: str | None = None, **kw: Any) -> Any:
    """토큰을 붙여 POST 한다. 면제 경로면 그대로 보낸다.

    `page` 를 주지 않으면 `path` 의 앞 두 조각(`/inv/005`)에서 받아온다 —
    `/inv/005/confirm` 처럼 하위 경로로 POST 하는 경우를 위해서다.
    """
    from kyungdong.app.util import csrf as _csrf
    payload = dict(data or {})
    if _csrf.exempt(path) is None:
        if page is None:
            parts = [p for p in path.split("/") if p]
            page = f"/{parts[0]}/{parts[1]}" if len(parts) >= 2 else "/"
        token = csrf_token(client, page, **kw)
        if token:
            payload.setdefault(_csrf.FORM_FIELD, token)
    return client.post(path, data=payload, **kw)
