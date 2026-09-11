"""보안 헤더 · 세션 · 속도 제한 (아키텍트 · goal.md §10-12 · G-26·G-27·G-30).

직전 사업에서 실제로 난 사고를 처음부터 막는다:
  · 시드 계정이 공통 비밀번호를 공유했다(송월) → 계정별 난수 (test_arch_seed.py)
  · 외부 CDN 참조가 남았다 → CSP `default-src 'self'`
  · 로그아웃해도 쿠키가 살아 있었다 → 서버측 세션 무효화
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import nav                                    # noqa: E402
from kyungdong.app.main import app                               # noqa: E402
from kyungdong.app.settings import settings                      # noqa: E402
from kyungdong.app.util import ratelimit, security, session      # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean():
    session.reset_all()
    ratelimit.reset_all()
    yield
    session.reset_all()
    ratelimit.reset_all()


# ── 보안 헤더 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("header,expected", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Cache-Control", "no-store"),
])
def test_보안헤더가_붙는다(header, expected):
    assert client.get("/").headers.get(header) == expected


def test_CSP가_외부를_막는다():
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "cdn" not in csp


def test_렌더에_외부_리소스가_없다():
    """차트도 인라인 CSS/SVG 로 그린다 — 외부 CDN 0 (§10-12)."""
    for path in ["/", "/login", "/board"] + [s.path for s in nav.all_screens()[:5]]:
        body = client.get(path).text
        assert "http://" not in body
        assert "https://" not in body, f"{path} 에 외부 링크"


def test_HSTS는_prod에서만_붙는다():
    assert "Strict-Transport-Security" not in security.BASE_HEADERS
    assert "Strict-Transport-Security" in security.PROD_HEADERS


# ── 세션 ─────────────────────────────────────────────────────────────────
def test_세션_생성과_로드():
    cookie, sess = session.create(1, "admin", "SYSADMIN")
    loaded = session.load(cookie)
    assert loaded is not None and loaded.sid == sess.sid and loaded.role_code == "SYSADMIN"


def test_로그아웃은_서버측에서도_지운다():
    """쿠키만 지우면 남은 쿠키가 계속 유효하다 (§10-12)."""
    cookie, _ = session.create(1, "admin", "SYSADMIN")
    assert session.active_count() == 1
    assert session.destroy(cookie) is True
    assert session.active_count() == 0
    assert session.load(cookie) is None, "지운 세션의 쿠키가 아직 먹힌다"


def test_위조_쿠키는_통과하지_않는다():
    assert session.load("aaaa.bbbb.cccc") is None
    assert session.load("") is None
    assert session.load(None) is None


def test_유휴_만료는_서버측에서도_지운다():
    cookie, sess = session.create(1, "admin", "SYSADMIN")
    sess.last_seen = time.time() - (settings().h("SESSION_IDLE_MINUTES").as_int() * 60 + 10)
    assert session.load(cookie) is None
    assert session.active_count() == 0


def test_계정_잠금시_모든_세션을_끊는다():
    session.create(7, "operator", "OPERATOR")
    session.create(7, "operator", "OPERATOR")
    session.create(8, "prod", "PRODUCTION")
    assert session.destroy_user(7) == 2
    assert session.active_count() == 1


# ── 속도 제한 ────────────────────────────────────────────────────────────
def test_계정_한도는_가설값을_따른다():
    limit = settings().h("LOGIN_FAIL_MAX").as_int()
    for _ in range(limit - 1):
        ratelimit.record_failure("admin", "1.2.3.4")
    assert ratelimit.blocked("admin", "1.2.3.4")[0] is False
    ratelimit.record_failure("admin", "1.2.3.4")
    ok, why = ratelimit.blocked("admin", "1.2.3.4")
    assert ok is True and "가설 (D-16)" in why


def test_IP_한도는_계정과_별개다():
    limit = settings().h("RATE_LIMIT_IP").as_int()
    for i in range(limit):
        ratelimit.record_failure(f"user{i}", "9.9.9.9")
    ok, why = ratelimit.blocked("전혀다른계정", "9.9.9.9")
    assert ok is True and "IP" in why


def test_성공하면_잠금이_풀린다():
    """§10-11 — 시드 재실행·로그인 성공이 잠금을 푸는지 확인한다."""
    for _ in range(10):
        ratelimit.record_failure("admin", "1.1.1.1")
    assert ratelimit.blocked("admin", "1.1.1.1")[0] is True
    ratelimit.clear("admin", "1.1.1.1")
    assert ratelimit.blocked("admin", "1.1.1.1")[0] is False


# ── prod 에서 개발용 우회가 막히는가 ──────────────────────────────────────
def test_prod에서는_개발용_역할전환이_안_먹는다():
    """D-40 — 인증 없이 화면이 열리면 보안 결함이다."""
    old_env = os.environ.get("KYUNGDONG_ENV")
    old_secret = os.environ.get("KYUNGDONG_SESSION_SECRET")
    os.environ["KYUNGDONG_ENV"] = "prod"
    os.environ["KYUNGDONG_SESSION_SECRET"] = "x" * 32
    settings.cache_clear()
    try:
        r = client.get("/inv/005?as=SYSADMIN")
        assert r.status_code == 403, "prod 인데 쿼리 한 줄로 관리자 화면이 열렸다"
    finally:
        for k, v in (("KYUNGDONG_ENV", old_env), ("KYUNGDONG_SESSION_SECRET", old_secret)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings.cache_clear()


def test_prod는_SESSION_SECRET_없이_기동을_거부한다():
    old_env = os.environ.get("KYUNGDONG_ENV")
    old_secret = os.environ.get("KYUNGDONG_SESSION_SECRET")
    os.environ["KYUNGDONG_ENV"] = "prod"
    os.environ.pop("KYUNGDONG_SESSION_SECRET", None)
    settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            settings()
    finally:
        for k, v in (("KYUNGDONG_ENV", old_env), ("KYUNGDONG_SESSION_SECRET", old_secret)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings.cache_clear()
