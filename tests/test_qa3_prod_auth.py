"""운영계 인증 흐름 (D-204~D-208) — **로그인 없이는 아무 화면도 열리지 않는다.**

사용자: *"로그인 화면이 없고 운영으로 보이지 않아. 운영계 올릴거니 좀 수정해줘."*

실측한 것: prod 에서 `/` 는 **인증 없이 200** 이라 메뉴·화면 구성이 그대로 보였고,
업무 화면은 **403** 이라 로그인 페이지가 있어도 **갈 길이 없었다.** 로그인에 성공해도
로그인 화면에 머물렀다.

**prod 쿠키는 `secure=True`** 라 이 시험은 `https://` 로 돈다 — 평문 HTTP 로는 쿠키가
저장되지 않아 로그인 자체가 성립하지 않는다(운영에서 TLS 종단이 없으면 같은 증상이다).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                    # noqa: E402
from kyungdong.app.auth import hash_password, safe_next        # noqa: E402
from kyungdong.app.settings import settings                    # noqa: E402
from kyungdong.app.util import ratelimit                       # noqa: E402

HTML = {"accept": "text/html"}
TEST_PW = "Prod-Auth-Test-9271!"


@pytest.fixture()
def prod(monkeypatch):
    """prod 프로파일 + 알려진 비밀번호. **끝나면 전부 되돌린다.**"""
    monkeypatch.setenv("KYUNGDONG_ENV", "prod")
    monkeypatch.setenv("KYUNGDONG_SESSION_SECRET", "test-only-not-a-real-key-0123456789")
    settings.cache_clear()
    ratelimit.reset_all()

    from kyungdong.app.main import app

    row = conn.q1("select USER_ID, LOGIN_ID, PASSWORD_HASH from SYS_USERS "
                  "where LOGIN_ID = 'admin'")
    assert row, "admin 계정이 없다"
    before = row["password_hash"]
    conn.x("update SYS_USERS set PASSWORD_HASH = %s where USER_ID = %s",
           (hash_password(TEST_PW), int(row["user_id"])))
    client = TestClient(app, raise_server_exceptions=False,
                        base_url="https://testserver", follow_redirects=False)
    try:
        yield client, row["login_id"]
    finally:
        conn.x("update SYS_USERS set PASSWORD_HASH = %s where USER_ID = %s",
               (before, int(row["user_id"])))
        ratelimit.reset_all()
        monkeypatch.undo()
        settings.cache_clear()


def _login(c: TestClient, login_id: str, nxt: str = ""):
    page = c.get(f"/login{'?next=' + nxt if nxt else ''}", headers=HTML)
    tok = re.search(r'name="_csrf" value="([^"]+)"', page.text).group(1)
    return c.post("/login", headers=HTML,
                  data={"_csrf": tok, "login_id": login_id, "password": TEST_PW,
                        "next": re.search(r'name="next" value="([^"]*)"', page.text).group(1)})


def test_미인증은_403_이_아니라_로그인으로_간다(prod):
    """**403 은 틀린 진단이다.** 사용자는 권한이 부족한 줄 알고 관리자에게 문의한다 —
    실제로는 로그인을 안 한 것이다."""
    c, _ = prod
    for path in ("/", "/dsh/001", "/est/010", "/sys/029"):
        r = c.get(path, headers=HTML)
        assert r.status_code == 303, f"{path} → {r.status_code}"
        assert r.headers["location"].startswith("/login?next="), r.headers["location"]


def test_로그인_페이지와_정적파일은_인증_없이_열린다(prod):
    """로그인 화면까지 막으면 **들어갈 길이 없다.**"""
    c, _ = prod
    assert c.get("/login", headers=HTML).status_code == 200
    assert c.get("/static/app.css").status_code == 200


def test_기계_경로는_리다이렉트하지_않는다(prod):
    """PLC·Gateway 는 302 를 따라가지 않고, 따라가도 로그인 HTML 을 받아 파싱 오류를 낸다."""
    c, _ = prod
    r = c.post("/api/ingest/plc", json={"device_id": 1, "equip_code": "EQ10", "samples": []})
    assert r.status_code in (401, 403), r.status_code
    assert "location" not in {k.lower() for k in r.headers}


def test_로그인하면_가려던_화면으로_간다(prod):
    """전에는 로그인 화면에 머물렀다 — 운영에서는 **어디로 가야 할지 모른다.**"""
    c, login_id = prod
    blocked = c.get("/est/010", headers=HTML)
    nxt = blocked.headers["location"].split("next=", 1)[1]
    r = _login(c, login_id, nxt)
    assert r.status_code == 303, r.status_code
    assert r.headers["location"] == "/est/010", r.headers["location"]
    assert c.get("/est/010", headers=HTML).status_code == 200


def test_로그아웃하면_다시_막힌다(prod):
    c, login_id = prod
    _login(c, login_id)
    assert c.get("/dsh/001", headers=HTML).status_code == 200
    page = c.get("/login", headers=HTML)
    tok = re.search(r'name="_csrf" value="([^"]+)"', page.text).group(1)
    c.post("/logout", data={"_csrf": tok}, headers=HTML)
    r = c.get("/dsh/001", headers=HTML)
    assert r.status_code == 303 and r.headers["location"].startswith("/login"), r.status_code


def test_헤더에_로그인_계정과_로그아웃이_있다(prod):
    """운영 화면은 **누가 보고 있는지**와 **나가는 길**이 있어야 한다 (D-206)."""
    c, login_id = prod
    _login(c, login_id)
    html = c.get("/dsh/001", headers=HTML).text
    head = re.search(r'<header class="top">(.*?)</header>', html, re.S).group(1)
    assert login_id in head, "헤더에 로그인 계정이 없다"
    assert 'action="/logout"' in head, "헤더에 로그아웃이 없다"
    assert "로그인 아님" not in head


def test_dev_는_로그인_아님을_숨기지_않는다():
    """dev 는 세션 없이 역할을 준다 — 그것을 **로그인한 것처럼 보이게 하지 않는다** (D-206)."""
    from kyungdong.app.main import app

    c = TestClient(app, raise_server_exceptions=False)
    head = re.search(r'<header class="top">(.*?)</header>',
                     c.get("/dsh/001", headers=HTML).text, re.S).group(1)
    assert "로그인 아님" in head and "개발 전환" in head


@pytest.mark.parametrize("bad", [
    "https://evil.example/", "//evil.example/", "/\\evil", "\\\\evil",
    "javascript:alert(1)", "", "   ",
])
def test_열린_리다이렉트를_막는다(bad):
    """`next` 를 그대로 믿으면 로그인 직후 **외부로 튕겨 보낼 수 있다** (D-205).

    사용자는 방금 우리 화면에서 로그인했으니 그 다음 페이지를 믿는다.
    """
    assert safe_next(bad) == "/", f"{bad!r} 이 통과했다"


@pytest.mark.parametrize("ok", ["/est/010", "/dsh/001?q=1", "/sys/029#followup"])
def test_앱_안의_경로는_통과한다(ok):
    assert safe_next(ok) == ok


def test_운영_비밀번호_재발급이_비밀번호를_기록하지_않는다():
    """재발급 도구가 로그에 비밀번호를 남기면 그게 유출이다 (D-207 · G-29)."""
    src = (ROOT / "tools" / "ops_password.py").read_text()
    assert "secrets.token_urlsafe" in src, "난수가 아니다"
    # **감사 삽입문만** 본다 — 그 뒤의 `print` 는 의도된 1회 출력이라 여기 섞이면 안 된다.
    i = src.index("insert into SYS_ACCESS_LOGS")
    stmt = src[i:src.index("print(", i)]
    assert "raw" not in stmt, f"감사 로그에 비밀번호를 넣는다:\n{stmt}"
    # 1회 출력은 **있어야** 한다 — 없으면 재발급해도 받을 길이 없다.
    assert 'print(f"비밀번호' in src, "발급한 비밀번호를 보여 주지 않는다"
    assert "--unlock" in src, "잠긴 계정을 조용히 풀지 않는다는 장치가 없다"
    # 파일·환경변수로 새지 않는지 — 쓰기 경로가 아예 없어야 한다.
    assert "write_text" not in src and "open(" not in src, "비밀번호를 파일로 쓴다"
