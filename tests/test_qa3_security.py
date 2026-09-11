"""QA3 — G-26~G-30 보안·비기능 게이트 불변식.

판정은 `tools/check_security.py` 가 한다. 여기서는 **되돌아가면 안 되는 것**과
**지금 결함이라는 사실**을 못박는다.

규칙
  · **`skip` 금지**(§10-4 · D-62). 0건 경로와 N건 경로를 둘 다 단언한다.
  · **결함 표지 테스트**: 지금은 결함이 사실이다. 고쳐지면 이 테스트가 **실패해서**
    리포트를 갱신하게 만든다(`tests/test_qa1_ui.py` 선례).
  · **TLS 버전·저장 암호화 알고리즘을 여기서 정하지 않는다**(D-15).
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                     # noqa: E402
from kyungdong.app import nav, rbac                             # noqa: E402
from kyungdong.app.main import app                              # noqa: E402
from kyungdong.app.settings import settings                     # noqa: E402
from kyungdong.app.util import csrf, pii, ratelimit, security, session   # noqa: E402

# D-54/D-106 — `util/__init__` 이 `audit` 를 함수로 재노출해 모듈을 가린다.
auditmod = importlib.import_module("kyungdong.app.util.audit")

SRC = sorted((ROOT / "src").rglob("*.py"))
TEMPLATES = sorted((ROOT / "src" / "kyungdong" / "app" / "templates").rglob("*.html"))
ROLES = ("EXEC", "QUALITY", "PRODUCTION", "OPERATOR", "SUPPLIER_OPS", "SYSADMIN")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def n1(sql: str, params=None) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


def src_text() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): p.read_text() for p in SRC}


# ══ G-26 ═════════════════════════════════════════════════════════════════
def test_g26_password_hash_is_argon2_or_bcrypt():
    rows = conn.q("select LOGIN_ID, PASSWORD_HASH from SYS_USERS order by USER_ID")
    assert rows, "계정이 0건이다 — `make db-seed` 먼저"
    for r in rows:
        h = r["password_hash"] or ""
        assert h.startswith(("$argon2", "$2a$", "$2b$", "$2y$")), \
            f"{r['login_id']}: bcrypt/Argon2 해시가 아니다 ({h[:12]!r})"


def test_g26_csrf_is_not_wired_yet():
    """**결함 표지 (DEF-QA3-001 / D-60·D-73)** — CSRF 가 POST 27개 중 0곳에 연결돼 있다.

    연결되면 이 테스트가 실패한다 → 그때 G-26 을 다시 재고 리포트를 갱신한다.
    """
    s = src_text()
    posts = sum(len(re.findall(r"@(?:router|app)\.post\(", t)) for t in s.values())
    calls = sum(len(re.findall(r"csrf\.require\(", t))
                for f, t in s.items() if not f.endswith("util/csrf.py"))
    tokens = [p.relative_to(ROOT).as_posix() for p in TEMPLATES if "_csrf" in p.read_text()]
    assert posts >= 27, f"POST 라우트가 {posts} 개다 — 세는 방식이 바뀌었는지 확인하라"
    assert calls == 0 and tokens == [], (
        f"CSRF 가 연결되기 시작했다 (호출 {calls}, 템플릿 {tokens}) — "
        "DEF-QA3-001 해소 여부를 다시 재고 outputs/qa3-AI비기능보안.md 를 갱신하라")


def test_g26_csrf_off_is_declared_on_screen(client):
    """조용히 꺼진 보안 장치를 만들지 않는다(G-30). 꺼져 있으면 화면이 그렇게 말해야 한다."""
    assert csrf.enforced() is False
    r = client.get("/", headers={"x-kyungdong-role": "SYSADMIN"})
    assert "CSRF 미적용" in r.text, "CSRF 가 꺼져 있는데 화면이 그 사실을 말하지 않는다"


def test_g26_csrf_token_binds_to_session():
    """구현 자체는 동작한다 — 다른 바인딩의 토큰은 거부된다(0건 경로·N건 경로)."""
    class Req:
        def __init__(self, sess=None, cookie=""):
            self.state = type("S", (), {"session": sess})()
            self.cookies = {csrf.COOKIE: cookie}

    a, b = Req(cookie="aaa"), Req(cookie="bbb")
    tok = csrf.issue(a)
    assert csrf.valid(a, tok) is True
    assert csrf.valid(b, tok) is False
    assert csrf.valid(a, None) is False
    assert csrf.valid(a, "쓰레기") is False


def test_g26_no_external_origins():
    assert "http" not in security.CSP, f"CSP 에 외부 출처가 있다: {security.CSP}"
    ext = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
           if re.search(r"https?://(?!localhost)", p.read_text())]
    assert ext == [], f"템플릿에 외부 URL 이 있다: {ext}"


def test_g26_prod_profile_is_enforced(monkeypatch):
    """prod 프로파일 — SESSION_SECRET 없으면 기동 거부, 있으면 HSTS. 끝나고 되돌린다."""
    monkeypatch.setenv("KYUNGDONG_ENV", "prod")
    monkeypatch.delenv("KYUNGDONG_SESSION_SECRET", raising=False)
    settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            settings()
        monkeypatch.setenv("KYUNGDONG_SESSION_SECRET", "test-only-not-a-real-key")
        settings.cache_clear()
        assert settings().is_prod is True
        assert "Strict-Transport-Security" in security.headers()
    finally:
        monkeypatch.undo()
        settings.cache_clear()
    assert "Strict-Transport-Security" not in security.headers()


# ══ G-27 ═════════════════════════════════════════════════════════════════
def test_g27_one_account_per_role():
    rows = conn.q("select u.LOGIN_ID, p.ROLE_CODE from SYS_USERS u "
                  "join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID")
    by_role = {r["role_code"] for r in rows}
    assert by_role == set(ROLES), f"역할별 대표 계정이 6종이 아니다: {sorted(by_role)}"
    logins = [r["login_id"] for r in rows]
    assert len(logins) == len(set(logins)), "중복 로그인 계정이 있다"


def test_g27_lockout_thresholds_come_from_env():
    s = settings()
    ratelimit.reset_all()
    acc, ipm = s.h("LOGIN_FAIL_MAX").as_int(), s.h("RATE_LIMIT_IP").as_int()
    try:
        assert ratelimit.blocked("t", "1.1.1.1")[0] is False          # 0건 경로
        for _ in range(acc - 1):
            ratelimit.record_failure("t", "1.1.1.1")
        assert ratelimit.blocked("t", "1.1.1.1")[0] is False          # 한도 직전
        ratelimit.record_failure("t", "1.1.1.1")
        ok, why = ratelimit.blocked("t", "1.1.1.1")                   # N건 경로
        assert ok and "가설" in why, why
        ratelimit.reset_all()
        for i in range(ipm):
            ratelimit.record_failure(f"u{i}", "2.2.2.2")
        assert ratelimit.blocked("전혀다른계정", "2.2.2.2")[0] is True
    finally:
        ratelimit.reset_all()


def test_g27_login_and_lockout_are_not_wired_yet():
    """**결함 표지 (DEF-QA3-004)** — 잠금 모듈은 있는데 부르는 라우트가 0곳, POST /login 도 0곳."""
    s = src_text()
    wired = [f for f, t in s.items()
             if "ratelimit." in t and not f.endswith(("util/ratelimit.py", "util/__init__.py"))]
    login_post = [f for f, t in s.items() if re.search(r"@(?:app|router)\.post\(\"/login", t)]
    assert wired == [] and login_post == [], (
        f"로그인·잠금이 붙기 시작했다 (잠금 {wired}, POST /login {login_post}) — "
        "G-27 을 다시 재고 리포트를 갱신하라")


def test_g27_password_policy_is_displayed_but_not_enforced():
    """**결함 표지 (DEF-QA3-005)** — 복잡도·주기 값은 있는데 **강제하는 코드가 0곳**이다."""
    s = src_text()
    users = {k: [f for f, t in s.items()
                 if k in t and "settings.py" not in f and "main.py" not in f]
             for k in ("PASSWORD_MIN_LEN", "PASSWORD_CHANGE_CYCLE_DAYS")}
    assert users["PASSWORD_MIN_LEN"] == [] and users["PASSWORD_CHANGE_CYCLE_DAYS"] == [], (
        f"비밀번호 정책을 강제하는 코드가 생겼다: {users} — G-27 을 다시 재라")
    s2 = settings()
    assert s2.h("PASSWORD_MIN_LEN").badge.startswith("가설")
    assert s2.h("PASSWORD_CHANGE_CYCLE_DAYS").badge.startswith("가설")


def test_g27_idle_logout_expires_server_side():
    session.reset_all()
    try:
        cookie, sess = session.create(1, "t", "SYSADMIN")
        assert session.load(cookie) is not None                       # N건 경로
        sess.last_seen -= settings().h("SESSION_IDLE_MINUTES").as_int() * 60 + 5
        assert session.load(cookie) is None                           # 만료 경로
        assert session.active_count() == 0, "만료된 세션이 서버측에 남아 있다"
    finally:
        session.reset_all()


# ══ G-28 ═════════════════════════════════════════════════════════════════
def test_g28_matrix_is_6_by_8():
    assert len(rbac.roles()) == 6
    assert len(rbac.PERM_AREA_TO_AREAS) == 8


@pytest.mark.parametrize("area", ["수주견적AI관리", "출하물류관리"])
def test_g28_exec_is_read_and_approve_only(area):
    """D-84 — 총괄PM/경영자(EXEC)는 `조회/승인`. 등록·수정 없이 **승인만** 가능하다."""
    p = rbac.perm_for("EXEC", area)
    assert p.label == "조회/승인"
    assert p.read is True and p.approve is True and p.write is False


def test_g28_no_permission_is_403(client):
    """권한 없는 조합이 실제로 존재하고(0건 경로 아님), 전부 403 인지 본다."""
    denied = allowed = 0
    for role in ROLES:
        for sc in nav.all_screens():
            want = rbac.can_read(role, sc.area)
            r = client.get(sc.path, headers={"x-kyungdong-role": role})
            if want:
                allowed += 1
                assert r.status_code != 403, f"{sc.path} as {role}: 권한 있는데 403"
            else:
                denied += 1
                assert r.status_code == 403, f"{sc.path} as {role}: {r.status_code} (기대 403)"
    assert denied > 0, "권한 없음 경로가 0회다 — 403 을 한 번도 재지 못했다"
    assert allowed > 0


def test_g28_db_permissions_match_td3():
    area_code = {s.area: s.prefix.upper() for s in nav.all_screens()}
    for role in ROLES:
        for area, code in area_code.items():
            p = rbac.perm_for(role, area)
            row = conn.q1("select READ_YN, WRITE_YN from SYS_ROLE_PERMISSIONS "
                          "where ROLE_CODE = %s and AREA_CODE = %s", (role, code))
            assert row is not None, f"{role}/{code} 권한행이 없다"
            assert (row["read_yn"] == "Y") == p.read
            assert (row["write_yn"] == "Y") == p.write


# ══ G-29 ═════════════════════════════════════════════════════════════════
def test_g29_pii_masking():
    assert pii.mask("홍길동", "name") == "홍**"
    assert pii.mask("010-1234-5678", "phone") == "010-****-5678"
    assert pii.mask("abcd@example.com", "email") == "ab**@example.com"
    assert pii.mask(None) == "" and pii.mask("") == ""


def test_g29_error_log_type_is_never_written():
    """**결함 표지 (DEF-QA3-007)** — `LOG_TYPE='오류'` 를 남기는 코드가 0곳이다."""
    s = src_text()
    calls = sum(len(re.findall(r'log_type="오류"', t)) for t in s.values())
    assert "오류" in auditmod.LOG_TYPES
    assert calls == 0, ("오류 감사 기록이 붙었다 — G-29 를 다시 재고 리포트를 갱신하라")


def test_g29_sixteen_screens_do_not_log_access(client):
    """**결함 표지 (DEF-QA3-006)** — 45화면 중 16개가 조회해도 접속 로그를 남기지 않는다."""
    unlogged = []
    for sc in nav.all_screens():
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        client.get(sc.path, headers={"x-kyungdong-role": "SYSADMIN"})
        got = n1("select count(*) as n from SYS_ACCESS_LOGS "
                 "where LOG_ID > %s and LOG_TYPE = '접속'", (m,))
        if not got:
            unlogged.append(sc.path)
    assert len(unlogged) == 16, (
        f"접속 로그를 남기지 않는 화면이 {len(unlogged)}개다 (측정 당시 16개): {unlogged} — "
        "늘었으면 새 결함이고 줄었으면 DEF-QA3-006 이 해소된 것이다. 리포트를 갱신하라")


def test_g29_api_audit_has_two_holes(client):
    """**결함 표지 (DEF-QA3-009)** — API 감사 기록이 두 갈래에서 빠진다.

    ① JSON Agent API(`/api/agent/query`)는 `SYS_ACCESS_LOGS` 에 아무 것도 남기지 않는다.
    ② 화면 Agent 질의가 501 로 끝나면 `audit()` 가 호출 뒤에 있어 지나친다.
    정상 갈래(200)는 남는다 — 그것까지 함께 단언해 '아예 안 남는다' 와 구분한다.
    """
    mq = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    ma = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    try:
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        client.post("/api/agent/query",
                    data={"question": "환율 적용 기준은 무엇인가", "agent_type": "통합"},
                    headers={"x-kyungdong-role": "SYSADMIN"})
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s", (m,)) == 0, \
            "JSON Agent API 가 감사 기록을 남기기 시작했다 — 리포트를 갱신하라"

        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        r = client.post("/inv/009", data={"q1": "환율 적용 기준은 무엇인가"},
                        headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                  "and LOG_TYPE = 'API'", (m,)) == 1, "정상 갈래의 API 감사까지 사라졌다"

        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        r = client.post("/inv/009", data={"q1": "문서 누락 자재는 격리구역에 두는가"},
                        headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 501
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s", (m,)) == 0, \
            "501 갈래에도 감사가 남기 시작했다 — 리포트를 갱신하라"
    finally:
        conn.x("delete from SYS_ACCESS_LOGS where LOG_ID > %s", (ma,))
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (mq,))


def test_g29_issued_password_goes_through_url_query():
    """**결함 표지 (DEF-QA3-008)** — 발급 비밀번호가 URL 쿼리스트링으로 흐른다."""
    s = src_text()
    hits = [f"{f}:{i}" for f, t in s.items()
            for i, line in enumerate(t.splitlines(), 1)
            if re.search(r"issued=\{?raw", line)]
    assert hits == ["src/kyungdong/app/routers/sys.py:151"], (
        f"URL 평문 비밀번호 위치가 바뀌었다: {hits} — 고쳐졌으면 리포트를 갱신하라")


def test_g29_no_password_literal_in_repo():
    pat = re.compile(r"(password|passwd|pwd)\s*[:=]\s*[\"'][^\"']{3,}[\"']", re.I)
    lits = []
    for d in (ROOT / "src", ROOT / "db"):
        for p in d.rglob("*.py"):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                m = pat.search(line)
                if m and "hash" not in line.lower() and "env" not in line.lower():
                    lits.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    assert lits == [], f"비밀번호 리터럴 {lits}"


def test_g29_download_requires_permission_and_is_logged(client):
    """반출 — 권한 없음 403(0건 경로) · 권한 있음 기록(N건 경로). 넣은 행은 지운다."""
    mark = n1("select coalesce(max(DOWNLOAD_ID),0) as n from DAT_DOWNLOAD_LOGS")
    try:
        r_no = client.post("/sys/027", data={"action": "download"},
                           headers={"x-kyungdong-role": "OPERATOR"}, follow_redirects=False)
        assert r_no.status_code == 403
        assert n1("select count(*) as n from DAT_DOWNLOAD_LOGS where DOWNLOAD_ID > %s",
                  (mark,)) == 0, "권한 없는 반출 시도가 기록을 남겼다"
        r_ok = client.post("/sys/027", data={"action": "download"},
                           headers={"x-kyungdong-role": "SYSADMIN"}, follow_redirects=False)
        assert r_ok.status_code in (200, 303)
        assert n1("select count(*) as n from DAT_DOWNLOAD_LOGS where DOWNLOAD_ID > %s",
                  (mark,)) == 1
    finally:
        conn.x("delete from DAT_DOWNLOAD_LOGS where DOWNLOAD_ID > %s", (mark,))


# ══ G-30 ═════════════════════════════════════════════════════════════════
def test_g30_db_down_is_503_not_empty_screen(client, monkeypatch):
    """DB 가 죽으면 **503**. 빈 그리드로 '데이터 없음' 처럼 보이면 조용한 실패다."""
    monkeypatch.setenv("KYUNGDONG_PG_DSN", "postgresql://127.0.0.1:1/nope_qa3")
    settings.cache_clear()
    try:
        r = client.get("/dsh/001", headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 503
        assert "서비스 일시 중단" in r.text
    finally:
        monkeypatch.undo()
        settings.cache_clear()
    assert client.get("/dsh/001", headers={"x-kyungdong-role": "SYSADMIN"}).status_code == 200


def test_g30_llm_unconfigured_is_501_not_a_made_up_answer(client):
    """근거가 임계를 넘는 질의는 LLM 단계까지 간다 — 키가 없으면 **501**이다."""
    from kyungdong.agent import retrieval
    q = "문서 누락 자재는 격리구역에 두는가"
    ev, _ = retrieval.search(q, agent_type="통합")
    assert retrieval.confidence(ev) >= settings().h("RAG_CONFIDENCE_MIN").as_float(), \
        "이 질의가 더 이상 임계를 넘지 못한다 — 501 경로를 재려면 다른 질의를 골라라"
    mark = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    try:
        r = client.post("/api/agent/query", data={"question": q, "agent_type": "통합"},
                        headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 501 and "LLM 미구성" in r.text
        assert n1("select count(*) as n from AGT_QUERY_LOGS where QUERY_ID > %s", (mark,)) == 1, \
            "501 로 끝난 질의도 AGT_QUERY_LOGS 에 남아야 한다 (100% 기록)"
    finally:
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (mark,))


def test_g30_grid_cells_are_escaped(client):
    """`<script>` 를 질의로 넣고 042 질의이력 화면에서 이스케이프를 확인한다. 넣은 행은 지운다."""
    from kyungdong.agent import service
    mark = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    try:
        service.ask("<script>alert('qa3')</script> 격리구역", agent_type="통합",
                    user_id=service.resolve_user("SYSADMIN"), role_code="SYSADMIN")
        r = client.get("/agt/042", headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200
        assert "<script>alert('qa3')</script>" not in r.text, "저장형 XSS — 셀이 이스케이프되지 않는다"
        assert "&lt;script&gt;" in r.text, "이스케이프된 흔적이 없다 — 값이 아예 렌더되지 않았는지 확인하라"
    finally:
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (mark,))


def test_g30_no_safe_filter_in_templates():
    used = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
            if re.search(r"\{\{[^}]*\|\s*safe", p.read_text())]
    assert used == [], f"그리드 템플릿에 |safe 가 쓰였다: {used}"


def test_g30_no_client_side_async_fallback():
    """전 화면 서버 렌더 — 백엔드가 죽었을 때 '멀쩡해 보일' 클라이언트 표면이 0이다.

    (브라우저로 백엔드를 죽여 본 것은 아니다. 그 사실을 리포트에 적었다.)
    """
    js = list((ROOT / "src" / "kyungdong" / "app" / "static").rglob("*.js"))
    fetches = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
               if re.search(r"fetch\(|XMLHttpRequest", p.read_text())]
    assert js == [] and fetches == [], (
        f"클라이언트 비동기 호출이 생겼다 (js {js}, fetch {fetches}) — "
        "백엔드 죽음에 화면이 어떻게 보이는지 다시 재라")


def test_g30_ingest_stale_badge_shows(client):
    """수집 중단 — 0건 경로('미수집')와 오래된 수집 경로('수집 중단')를 **둘 다** 단언한다."""
    from datetime import timedelta

    from kyungdong.app.util import clock
    from kyungdong.ingest import collector, tags

    for path in ("/dsh/003", "/prc/022"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200

    base = {t: n1(f"select coalesce(max({c}),0) as n from {t}")
            for t, c in (("IF_PLC_SIGNALS", "PLC_IF_ID"),
                         ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"), ("DAT_TIMESERIES", "TS_ID"))}
    dev = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                  ("레이저커팅기 PLC",))
    assert dev is not None, "수집 장비 시드가 없다 — `make db-seed`"
    old = clock.anchor() - timedelta(hours=2)
    try:
        collector.ingest_batch(int(dev["device_id"]), "EQ10",
                               [collector.Sample(t.name, "1" if t.numeric else "가동", old)
                                for t in tags.TAGS])
        st = collector.status()
        assert st["any_stale"] is True
        for path in ("/dsh/003", "/prc/022"):
            r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
            assert "수집 중단" in r.text, f"{path}: 앵커 −2h 수집인데 '수집 중단' 표시가 없다"
            assert old.strftime("%Y-%m-%d %H:%M") in r.text, f"{path}: 마지막 수집시각이 없다"
    finally:
        for t, c in (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                     ("IF_PLC_SIGNALS", "PLC_IF_ID")):
            conn.x(f"delete from {t} where {c} > %s", (base[t],))
