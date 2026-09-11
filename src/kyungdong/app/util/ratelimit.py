"""로그인 속도 제한 (goal.md §10-12) — 계정 5회 / IP 20회.

**수치 근거**: 사업계획서 9.2 는 "비밀번호 복잡도·주기적 변경" 까지만 적고 **잠금 횟수는 없다**.
계정 한도는 `.env` `LOGIN_FAIL_MAX`(가설 D-16), IP 한도는 `RATE_LIMIT_IP`(가설 D-16).
직전 사업 교훈에서 온 값이므로 **가설이라고 화면에 밝힌다**.

저장소는 **프로세스 메모리**다. 단일 프로세스 개발 환경 기준이고, 다중 워커로 가면
공유 저장소가 필요하다 — 그 사실을 D-48 에 적어 두었다.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from ..settings import settings

WINDOW_SEC = 600          # 10분 창

_by_account: dict[str, deque[float]] = defaultdict(deque)
_by_ip: dict[str, deque[float]] = defaultdict(deque)


def _prune(dq: deque[float], now: float) -> None:
    while dq and now - dq[0] > WINDOW_SEC:
        dq.popleft()


def _limits() -> tuple[int, int]:
    s = settings()
    return s.h("LOGIN_FAIL_MAX").as_int(), s.h("RATE_LIMIT_IP").as_int()


def _badge(key: str) -> str:
    """앱 전체가 같은 배지 문구를 쓴다 — `가설 (D-nn)` (settings.Hypothesis.badge)."""
    return settings().h(key).badge


def record_failure(login_id: str, ip: str | None) -> None:
    now = time.time()
    _by_account[login_id].append(now)
    if ip:
        _by_ip[ip].append(now)


def blocked(login_id: str, ip: str | None) -> tuple[bool, str]:
    """(차단 여부, 사유). 차단이면 호출자가 **403 또는 잠금 안내**를 낸다."""
    now = time.time()
    acc_max, ip_max = _limits()

    dq = _by_account[login_id]
    _prune(dq, now)
    if len(dq) >= acc_max:
        return True, f"계정 실패 {len(dq)}회 / 한도 {acc_max}회 {_badge('LOGIN_FAIL_MAX')}"

    if ip:
        dqi = _by_ip[ip]
        _prune(dqi, now)
        if len(dqi) >= ip_max:
            return True, f"IP 실패 {len(dqi)}회 / 한도 {ip_max}회 {_badge('RATE_LIMIT_IP')}"
    return False, ""


def clear(login_id: str, ip: str | None = None) -> None:
    """로그인 성공 시 푼다. `seed.py` 재실행이 잠금을 푸는지 확인할 때도 쓴다(§10-11)."""
    _by_account.pop(login_id, None)
    if ip:
        _by_ip.pop(ip, None)


def reset_all() -> None:
    """테스트 전용."""
    _by_account.clear()
    _by_ip.clear()
