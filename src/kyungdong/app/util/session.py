"""세션 — 서명 쿠키 + **서버측 무효화** (goal.md §10-12 · G-27).

쿠키만 쓰면 로그아웃해도 남은 쿠키가 유효하다. 서버가 들고 있는 레지스트리에서 지워야
"서버측 세션 무효화" 가 된다. 유휴 만료는 `SESSION_IDLE_MINUTES`(가설 D-16).

저장소는 **프로세스 메모리**다(D-48). 다중 워커로 가면 공유 저장소가 필요하다.
세션 테이블은 TD5 68표에 없으므로 **테이블을 만들지 않는다**(G-01 68 고정).
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from itsdangerous import BadSignature, URLSafeSerializer

from ..settings import settings

COOKIE = "kyungdong_sid"


@dataclass
class Session:
    sid: str
    user_id: int
    login_id: str
    role_code: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


_store: dict[str, Session] = {}


def _serializer() -> URLSafeSerializer:
    s = settings()
    secret = s.session_secret or "dev-only-not-a-secret"
    if s.is_prod and not s.session_secret:
        raise RuntimeError("prod 에서 SESSION_SECRET 없이 세션을 만들 수 없다")
    return URLSafeSerializer(secret, salt="kyungdong-session")


def _idle_sec() -> int:
    return settings().h("SESSION_IDLE_MINUTES").as_int() * 60


def create(user_id: int, login_id: str, role_code: str) -> tuple[str, Session]:
    sid = secrets.token_urlsafe(24)
    sess = Session(sid=sid, user_id=user_id, login_id=login_id, role_code=role_code)
    _store[sid] = sess
    return _serializer().dumps(sid), sess


def load(cookie_value: str | None) -> Session | None:
    """유효하지 않거나 만료면 `None` — **조용히 기본 역할로 통과시키지 않는다**."""
    if not cookie_value:
        return None
    try:
        sid = _serializer().loads(cookie_value)
    except BadSignature:
        return None
    sess = _store.get(sid)
    if sess is None:
        return None
    now = time.time()
    if now - sess.last_seen > _idle_sec():
        _store.pop(sid, None)          # 유휴 만료 — 서버측에서도 지운다
        return None
    sess.last_seen = now
    return sess


def destroy(cookie_value: str | None) -> bool:
    """로그아웃. 쿠키를 지우는 것으로 끝내지 않고 **레지스트리에서 제거**한다."""
    if not cookie_value:
        return False
    try:
        sid = _serializer().loads(cookie_value)
    except BadSignature:
        return False
    return _store.pop(sid, None) is not None


def destroy_user(user_id: int) -> int:
    """계정 잠금·권한 변경 시 그 사용자의 모든 세션을 끊는다."""
    sids = [s.sid for s in _store.values() if s.user_id == user_id]
    for sid in sids:
        _store.pop(sid, None)
    return len(sids)


def active_count() -> int:
    return len(_store)


def reset_all() -> None:
    """테스트 전용."""
    _store.clear()
