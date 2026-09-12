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
sys.path.insert(0, str(ROOT / "tools"))   # plc_simulator (D-174 등록/거둠 시험)

import conn                                                     # noqa: E402
from conftest import csrf_post                                  # noqa: E402
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


def test_g26_csrf_is_wired_on_every_post_route():
    """**DEF-QA3-001 (D-60·D-73) 해소 실측** — POST 라우트 전부가 `csrf.require()` 를 부른다.

    표지를 뒤집었다: 이제 **연결이 풀리면** 깨진다. 숫자를 낮춰 맞추지 말고 라우터를 고쳐라.
    """
    s = src_text()
    posts = sum(len(re.findall(r"@(?:router|app)\.post\(", t)) for t in s.values())
    calls = sum(len(re.findall(r"csrf\.require\(", t))
                for f, t in s.items() if not f.endswith("util/csrf.py"))
    tokens = [p.relative_to(ROOT).as_posix() for p in TEMPLATES if "csrf_field()" in p.read_text()]
    assert posts >= 27, f"POST 라우트가 {posts} 개다 — 세는 방식이 바뀌었는지 확인하라"
    assert calls >= posts, (
        f"POST 라우트 {posts} 개에 csrf.require() 호출이 {calls} 건뿐이다 — 연결이 풀렸다")
    assert tokens, "화면이 CSRF 토큰 필드를 하나도 찍지 않는다 — 브라우저가 쓰기를 할 수 없다"


def test_g26_모든_화면_POST_form_에_토큰이_실린다():
    """**라우트 수(31/31)를 세는 것으로는 이걸 못 잡는다.**

    라우터에 `csrf.require()` 가 걸려 있어도 화면의 `<form method=post>` 가 토큰을 안
    실으면 그 화면의 쓰기는 **403** 이다. 라우트는 31/31 로 멀쩡해 보이므로 게이트는
    통과하고, 깨진 것은 **사람이 그 버튼을 누를 때** 드러난다.

    D-73 이 정확히 그 사고였다 — `{% from … import csrf_field %}` 에 `with context` 가
    빠져 토큰이 **빈 문자열**로 렌더됐고, 그대로 켰으면 쓰기가 전부 403 이었다.

    면제 경로(`util/csrf.EXEMPT_PATHS`)로 보내는 form 은 토큰이 없는 것이 맞다 —
    세션·쿠키가 없는 기계 엔드포인트라 토큰을 만들 수가 없다.
    """
    from kyungdong.app.util import csrf as csrfmod

    post_forms, missing = 0, []
    for p in TEMPLATES:
        text = p.read_text()
        for m in re.finditer(r"<form\b[^>]*>", text, re.I):
            tag = m.group(0)
            if not re.search(r"method\s*=\s*[\"']?post", tag, re.I):
                continue
            post_forms += 1
            end = text.find("</form>", m.end())
            body = text[m.end(): end if end > 0 else len(text)]
            act = re.search(r"action\s*=\s*[\"']([^\"']+)", tag)
            if "csrf_field" in body or csrfmod.FORM_FIELD in body:
                continue
            if act and csrfmod.exempt(act.group(1)):
                continue
            missing.append(f"{p.relative_to(ROOT).as_posix()} {tag[:60]}")
    assert post_forms >= 10, f"POST form 이 {post_forms} 개다 — 세는 방식이 바뀌었는지 확인하라"
    assert not missing, (
        f"`csrf_field()` 가 빠진 화면 POST form {len(missing)} 개 — 그 화면의 쓰기는 403 이다: "
        f"{missing}")


def test_g26_csrf_off_is_declared_on_screen(client):
    """조용히 꺼진 보안 장치를 만들지 않는다(G-30).

    배지는 설정을 **따라야** 한다 — 꺼져 있으면 뜨고, 켜져 있으면 사라진다. 양쪽을 다 단언한다.
    """
    r = client.get("/", headers={"x-kyungdong-role": "SYSADMIN"})
    if csrf.enforced():
        assert "CSRF 미적용" not in r.text, "CSRF 가 켜졌는데 화면이 아직 '미적용' 이라고 말한다"
    else:
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


# ══ 수집 장비 인증 (D-103 후속 · D-168) ═══════════════════════════════════
# **개발에서는 이 결함이 보이지 않는다.** `x-kyungdong-role` 헤더가 SYSADMIN 을 주기 때문에
# 게이트가 전부 통과한다. prod 로 올려야 드러난다 — 그래서 여기서 prod 로 올려 잰다.
def _prod_client(monkeypatch):
    monkeypatch.setenv("KYUNGDONG_ENV", "prod")
    monkeypatch.setenv("KYUNGDONG_SESSION_SECRET", "test-only-not-a-real-key")
    settings.cache_clear()
    return TestClient(app, raise_server_exceptions=False)


PLC_BODY = {"device_id": 1, "equip_code": "EQ10",
            "samples": [{"tag": "RUN_STATUS", "value": "가동",
                         "collect_dt": "2026-09-12T10:00:00"}]}


def test_prod_에서_수집_장비는_403_이고_이유가_권한이_아니라고_말한다(monkeypatch):
    """**실측 결함** — prod 에서 PLC·Gateway 가 데이터를 넣지 못한다.

    세션이 없으면 `role_code` 가 빈 문자열이고 `rbac.can_write()` 가 막는다. 전에는 이것이
    `데이터관리 등록 권한 없음` 으로 나왔다 — **틀린 진단**이다. 현장에서 이 403 을 보면
    권한 설정을 뒤지는데, 진짜 원인은 `IF_DEVICE_REGISTRY.IP_ADDRESS` 가 비어 있는 것이다.

    **이 테스트는 지금 결함이 사실이라는 것을 못박는다.** 장비 IP 가 등록되면
    아래 `열린다` 테스트가 통과하고 이 테스트의 403 단언이 깨져서 리포트를 갱신하게 만든다.
    """
    c = _prod_client(monkeypatch)
    try:
        r = c.post("/api/ingest/plc", json=PLC_BODY)
        assert r.status_code == 403, r.status_code
        txt = r.text
        assert "등록된 수집 장비" in txt, "왜 막혔는지를 말하지 않는다"
        assert "IP_ADDRESS" in txt or "0건" in txt, "무엇이 비었는지를 말하지 않는다"
        assert "등록 권한 없음" not in txt, (
            "권한 문제라고 말한다 — 진짜 원인은 장비 IP 미등록이다")
        # 강도를 부풀리지 않는다 — IP 대조의 한계가 문장에 함께 나간다.
        assert "암호학적 인증이 아니다" in txt
    finally:
        monkeypatch.undo()
        settings.cache_clear()


def test_IP_가_등록되면_그_장비만_통과한다(monkeypatch):
    """**N건 경로** — 0건만 재면 '막힌다' 만 알고 '열리는지' 는 모른다(§10-4).

    끝나고 IP 를 NULL 로 되돌리고 적재한 행도 지운다 — `IF_PLC_SIGNALS` 는
    **런타임 전용 표라 0건이 정상**이다(G-11).
    """
    c = _prod_client(monkeypatch)
    dev = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where USE_YN = 'Y' "
                  "order by DEVICE_ID limit 1")
    assert dev, "수집 장비가 0건이다 — 시드를 확인한다"
    did = int(dev["device_id"])
    before = {t: int(conn.q1(f"select count(*) as n from {t}")["n"])
              for t in ("IF_PLC_SIGNALS", "DAT_TIMESERIES", "PRC_EQUIP_SIGNALS")}
    try:
        conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = %s where DEVICE_ID = %s",
               ("testclient", did))
        r = c.post("/api/ingest/plc", json=PLC_BODY)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        assert r.json()["stored"] == 1, r.json()

        # **등록되지 않은 출발지는 여전히 막힌다** — 하나 열었다고 전부 열리면 안 된다.
        conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = %s where DEVICE_ID = %s",
               ("10.0.0.99", did))
        r2 = c.post("/api/ingest/plc", json=PLC_BODY)
        assert r2.status_code == 403, "IP 가 다른데 통과했다"
        assert "맞지 않는다" in r2.text, r2.text[:200]
    finally:
        conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = null where DEVICE_ID = %s", (did,))
        for t, n in before.items():
            conn.x(f"delete from {t}")
            assert n == 0, f"{t} 가 검사 전부터 {n} 행이었다 — G-11 을 확인한다"
        monkeypatch.undo()
        settings.cache_clear()


def test_장비_경로_목록은_CSRF_면제_목록과_같다():
    """둘이 어긋나면 **CSRF 는 면제인데 장비 인증은 안 보는 구멍**이 생긴다."""
    from kyungdong.app.util import csrf as csrfmod
    from kyungdong.app.util import device

    assert set(device.MACHINE_PATHS) == set(csrfmod.EXEMPT_PATHS), (
        sorted(set(device.MACHINE_PATHS) ^ set(csrfmod.EXEMPT_PATHS)))


def test_장비_IP_는_선언_없이는_존재할_수_없다():
    """**방향을 뒤집었다.** 전에는 `IP 가 0건인지` 를 단언했다 — 시드가 IP 를 채워 두면
    `열린다` 가 검사기 자신 때문에 참이 되기 때문이다.

    시뮬레이터(D-174)가 생기면서 IP 가 **있을 수 있게** 됐다. 그래서 이제 단언하는 것은
    `0건인지` 가 아니라 **`있다면 그것이 시뮬레이터라고 선언돼 있는지`** 다.
    선언 없는 IP 는 **실물 장비가 붙은 것처럼** 읽힌다 — 그것이 막는 대상이다.

    도입기업이 실물 IP 를 주면(D-169) 그때 이 테스트를 다시 뒤집는다: 선언을 지우고
    실물 IP 를 넣는 것이 정상 상태가 된다.
    """
    from kyungdong.app.util import device

    ips = conn.q("select DEVICE_ID, DEVICE_NAME, IP_ADDRESS from IF_DEVICE_REGISTRY "
                 "where IP_ADDRESS is not null and length(trim(IP_ADDRESS)) > 0")
    decl = device.simulation()
    if not ips:
        assert decl is None, (
            f"IP 는 0건인데 시뮬레이터 선언 {decl} 이 남아 있다 — "
            "`--unregister` 가 둘을 함께 거두지 않았다")
        return
    assert decl is not None, (
        f"선언 없이 장비 IP 가 {len(ips)} 건 있다 — 실물이 붙은 것처럼 읽힌다. "
        f"도입기업 장비 IP 는 아직 없다(D-169). {[r['ip_address'] for r in ips]}")
    assert "실물이 아니라" in device.simulation_note(), device.simulation_note()


def test_시뮬레이터_IP_와_선언은_함께_붙고_함께_떨어진다():
    """**데이터만 남기고 표시만 떼는 것**이 되지 않아야 한다 (D-131·D-160 과 같은 규칙).

    선언만 지우면 IP 가 남아 실물처럼 보이고, IP 만 지우면 선언이 붕 뜬다.
    `--register` / `--unregister` 가 둘을 한 묶음으로 다루는지 실제로 돌려서 잰다.
    """
    import importlib

    from kyungdong.app.util import device

    sim = importlib.import_module("plc_simulator")
    before_ip = conn.q1("select IP_ADDRESS from IF_DEVICE_REGISTRY "
                        "where DEVICE_NAME = %s", (sim.DEVICE_NAME,))["ip_address"]
    before_decl = device.simulation()
    try:
        sim.register_sim_ip("127.0.0.1")
        assert device.simulation() == sim.SIM_DECISION
        row = conn.q1("select IP_ADDRESS from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                      (sim.DEVICE_NAME,))
        assert row["ip_address"] == "127.0.0.1", row

        sim.unregister_sim_ip()
        assert device.simulation() is None, "선언이 남았다"
        row = conn.q1("select IP_ADDRESS from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                      (sim.DEVICE_NAME,))
        assert row["ip_address"] is None, f"IP 가 남았다: {row['ip_address']}"
    finally:
        conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = %s where DEVICE_NAME = %s",
               (before_ip, sim.DEVICE_NAME))
        if before_decl is None:
            conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
                   (device.CONFIG_TYPE, device.CONFIG_KEY))


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


def test_g27_login_and_lockout_are_wired(client):
    """**DEF-QA3-004 해소 실측.** 표지를 뒤집었다 — 이제 **연결이 풀리면** 깨진다.

    회전 6 까지 `util/session.py` · `util/ratelimit.py` 는 만들어져 있는데 부르는 곳이 0곳이라
    통째로 죽어 있었다(POST /login 도 0곳). 지금은 `app/auth.py` 가 그 둘을 부르는 곳이다.
    **코드가 있다** 로 끝내지 않고 세 갈래를 다 태워서 잰다 — 맞는 비번·틀린 비번·한도 초과.
    """
    s = src_text()
    wired = [f for f, t in s.items()
             if "ratelimit." in t and not f.endswith(("util/ratelimit.py", "util/__init__.py"))]
    login_post = [f for f, t in s.items() if re.search(r"@(?:app|router)\.post\(\"/login", t)]
    assert wired and login_post, (
        f"로그인·잠금 연결이 풀렸다 (잠금 {wired}, POST /login {login_post}) — "
        "모듈만 남고 부르는 곳이 사라지면 G-27 은 회전 6 상태로 되돌아간 것이다")

    from kyungdong.app import auth
    pw = "Qa3!Login#2026x"
    assert auth.policy_errors(pw) == [], "시험용 비밀번호가 정책을 못 넘는다 — 값을 바꿔라"
    row = conn.q1("select USER_ID, LOGIN_ID, PASSWORD_HASH from SYS_USERS "
                  "where LOGIN_ID = 'admin'")
    assert row is not None, "admin 계정이 없다 — `make db-seed`"
    mark = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    fail_max = settings().h("LOGIN_FAIL_MAX").as_int()
    try:
        conn.x("update SYS_USERS set PASSWORD_HASH = %s where USER_ID = %s",
               (auth.hash_password(pw), row["user_id"]))
        ratelimit.reset_all()
        session.reset_all()

        # ① 맞는 비밀번호 → 200 + **서버측** 세션. 쿠키만 주고 마는 것은 세션이 아니다.
        ok = csrf_post(client, "/login", {"login_id": "admin", "password": pw}, page="/login")
        assert ok.status_code == 200, f"맞는 비밀번호인데 {ok.status_code}"
        assert session.COOKIE in ok.cookies, "세션 쿠키를 내려주지 않는다"
        assert session.active_count() == 1, "쿠키만 주고 서버측 세션을 만들지 않았다 (G-27)"

        # ② 틀린 비밀번호 → 401. 조용히 통과시키지 않는다.
        bad = csrf_post(client, "/login", {"login_id": "admin", "password": "틀린비번"},
                        page="/login")
        assert bad.status_code == 401, f"틀린 비밀번호인데 {bad.status_code}"

        # ③ 한도까지 실패 → 잠금 403. 맞는 비밀번호로도 못 들어간다.
        for _ in range(fail_max):
            csrf_post(client, "/login", {"login_id": "admin", "password": "x"}, page="/login")
        locked = csrf_post(client, "/login", {"login_id": "admin", "password": pw}, page="/login")
        assert locked.status_code == 403, (
            f"실패 {fail_max}회(LOGIN_FAIL_MAX) 뒤에도 {locked.status_code} — 계정 잠금이 안 걸린다")

        # 실패도 **남는다** — 조용히 지나가는 인증 실패를 만들지 않는다 (G-29·G-30).
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                  "and LOG_TYPE = '접속' and RESULT_CODE = '오류'", (mark,)) >= 1
    finally:
        conn.x("update SYS_USERS set PASSWORD_HASH = %s where USER_ID = %s",
               (row["password_hash"], row["user_id"]))
        conn.x("delete from SYS_ACCESS_LOGS where LOG_ID > %s", (mark,))
        ratelimit.reset_all()
        session.reset_all()


def test_g27_password_policy_is_enforced():
    """**DEF-QA3-005 해소 실측.** 값이 화면에 뜨는 것과 **강제하는 것**은 다른 사실이다.

    표지를 뒤집었다 — 강제 코드가 사라지면 깨진다. 임계값 자체는 여전히 `.env` 가설(D-16)이고
    **여기서 정하지 않는다**: 배지가 `가설` 인지도 함께 단언해 수치가 조용히 정본이 되는 것을 막는다.
    """
    from kyungdong.app import auth
    s = src_text()
    users = {k: [f for f, t in s.items()
                 if k in t and "settings.py" not in f and "main.py" not in f]
             for k in ("PASSWORD_MIN_LEN", "PASSWORD_CHANGE_CYCLE_DAYS")}
    assert users["PASSWORD_MIN_LEN"] and users["PASSWORD_CHANGE_CYCLE_DAYS"], (
        f"비밀번호 정책을 강제·안내하는 코드가 사라졌다: {users} — 값만 있고 강제가 없으면 정책이 아니다")

    # 0건 경로(위반 없음)와 N건 경로(위반) 를 둘 다 단언한다.
    min_len = settings().h("PASSWORD_MIN_LEN").as_int()
    assert auth.policy_errors("Qa3!Login#2026x") == []
    short = auth.policy_errors("Ab1!")
    assert short, "최소 길이 미달을 통과시킨다"
    assert any(str(min_len) in e for e in short), f"길이 위반 사유에 임계가 안 적힌다: {short}"
    assert auth.policy_errors("a" * (min_len + 5)), "복잡도(문자 종류)를 보지 않는다"

    # 주기 안내 — 값이 없으면 **모른다고 말한다**. 조용히 정상으로 두지 않는다.
    assert "변경" in auth.password_age_notice(None)

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


def test_g29_error_log_type_is_written(client):
    """**DEF-QA3-007 해소 실측.** `LOG_TYPE='오류'` 가 어휘로만 있고 쓰는 곳이 0곳이었다.

    표지를 뒤집었다 — **거부가 감사에 안 남으면** 깨진다. 문자열 개수만 세면 주석에도 걸리므로
    권한 없는 조합을 **전부 태워서** 거부 횟수와 `오류` 행 수가 같은지 본다.
    감사에 안 남는 거부는 없는 것과 같다(G-29 · D-97).
    """
    assert "오류" in auditmod.LOG_TYPES
    s = src_text()
    calls = sum(len(re.findall(r'log_type="오류"', t)) for t in s.values())
    assert calls >= 1, "`오류` 감사를 남기는 코드가 사라졌다 — 거부가 조용해진다"

    denied = [(role, sc) for role in ROLES for sc in nav.all_screens()
              if not rbac.can_read(role, sc.area)]
    assert denied, "권한 없는 조합이 0건이다 — 거부 경로를 한 번도 재지 못했다 (0건 경로 아님)"
    mark = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    try:
        for role, sc in denied:
            r = client.get(sc.path, headers={"x-kyungdong-role": role})
            assert r.status_code == 403, f"{sc.path} as {role}: {r.status_code} (기대 403)"
        got = n1("select count(*) as n from SYS_ACCESS_LOGS "
                 "where LOG_ID > %s and LOG_TYPE = '오류'", (mark,))
        assert got == len(denied), (
            f"거부 {len(denied)}회인데 `오류` 감사가 {got}행이다 — 조용히 지나가는 거부가 있다")
        row = conn.q1("select ACTION_NAME, RESULT_CODE, ERROR_MSG from SYS_ACCESS_LOGS "
                      "where LOG_ID > %s and LOG_TYPE = '오류' order by LOG_ID limit 1", (mark,))
        assert row["result_code"] == "오류" and "권한" in (row["error_msg"] or ""), (
            f"거부 사유가 감사에 안 적힌다: {row}")
    finally:
        conn.x("delete from SYS_ACCESS_LOGS where LOG_ID > %s", (mark,))


def test_g29_every_screen_logs_access(client):
    """**DEF-QA3-006 해소 실측.** 45화면 중 16개가 조회해도 접속 로그를 남기지 않았다.

    표지를 뒤집었다 — **한 화면이라도 빠지면** 깨진다. 원인이었던 것은 개발2 16화면이 공용
    가드를 안 지난 것이라, 가드에서 `audit()` 이 빠지면 다시 16개가 통째로 조용해진다.
    """
    unlogged = []
    for sc in nav.all_screens():
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        client.get(sc.path, headers={"x-kyungdong-role": "SYSADMIN"})
        got = n1("select count(*) as n from SYS_ACCESS_LOGS "
                 "where LOG_ID > %s and LOG_TYPE = '접속'", (m,))
        if not got:
            unlogged.append(sc.path)
    assert len(nav.all_screens()) == 45, "화면 수가 45가 아니다 — 분모를 먼저 확인하라"
    assert unlogged == [], (
        f"접속 로그를 남기지 않는 화면이 {len(unlogged)}개 생겼다: {unlogged} — "
        "DEF-QA3-006 으로 되돌아갔다")


def test_g29_api_audit_covers_json_api_and_501(client):
    """**DEF-QA3-009 해소 실측.** API 감사가 두 갈래에서 빠져 있었다.

    표지를 뒤집었다 — 둘 중 하나라도 다시 빠지면 깨진다.
      ① JSON Agent API(`/api/agent/query`) 가 `SYS_ACCESS_LOGS` 에 아무 것도 안 남겼다.
      ② 화면 Agent 질의가 501 로 끝나면 `audit()` 가 호출 **뒤**에 있어 지나쳤다.
    **못 한 것도 남겨야 한다**(G-30) — 501 갈래의 감사는 `RESULT_CODE='오류'` 여야 한다.
    """
    mq = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    ma = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    try:
        # ① JSON API — 화면이 없으므로 토큰은 `/login` 에서 받는다 (D-102).
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        csrf_post(client, "/api/agent/query",
                  {"question": "환율 적용 기준은 무엇인가", "agent_type": "통합"},
                  page="/login", headers={"x-kyungdong-role": "SYSADMIN"})
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                  "and LOG_TYPE = 'API'", (m,)) == 1, \
            "JSON Agent API 가 감사 기록을 남기지 않는다 — DEF-QA3-009 ① 로 되돌아갔다"

        # ② 정상 갈래(200)
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        r = csrf_post(client, "/inv/009", {"q1": "환율 적용 기준은 무엇인가"},
                      headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200
        assert n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                  "and LOG_TYPE = 'API'", (m,)) == 1, "정상 갈래의 API 감사가 사라졌다"

        # ③ 501 갈래 — 남되 **오류로** 남는다. 못 한 것을 정상으로 적으면 그게 조용한 실패다.
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        r = csrf_post(client, "/inv/009", {"q1": "문서 누락 자재는 격리구역에 두는가"},
                      headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 501
        row = conn.q1("select LOG_TYPE, RESULT_CODE from SYS_ACCESS_LOGS "
                      "where LOG_ID > %s and LOG_TYPE = 'API' order by LOG_ID limit 1", (m,))
        assert row is not None, "501 갈래가 감사에 안 남는다 — DEF-QA3-009 ② 로 되돌아갔다"
        assert row["result_code"] == "오류", f"501 인데 감사에 {row['result_code']} 로 적힌다"
    finally:
        conn.x("delete from SYS_ACCESS_LOGS where LOG_ID > %s", (ma,))
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (mq,))


def test_g29_issued_password_never_goes_through_url(client):
    """**해소 실측** — 발급 비밀번호가 URL 쿼리스트링(`?issued=…`)으로 흘렀다.

    표지를 뒤집었다 — 다시 URL 로 새면 깨진다. URL 은 브라우저 히스토리·Referer·
    액세스 로그에 남아 해시를 아무리 잘 걸어도 원문이 그 자리에 박힌다.
    """
    s = src_text()
    hits = [f"{f}:{i}" for f, t in s.items()
            for i, line in enumerate(t.splitlines(), 1)
            if re.search(r"issued=\{?raw", line)]
    assert hits == [], f"발급 비밀번호가 다시 URL 로 흐른다: {hits}"

    # 응답 자체로도 확인한다 — 코드 grep 만으로는 다른 이름의 쿼리로 새는 것을 못 잡는다.
    mark = n1("select coalesce(max(USER_ID),0) as n from SYS_USERS")
    role_id = n1("select min(ROLE_PERM_ID) as n from SYS_ROLE_PERMISSIONS")
    try:
        r = csrf_post(client, "/sys/026",
                      {"action": "create", "login_id": "qa3tmp", "user_name": "임시",
                       "dept_name": "QA", "role_id": str(role_id)},
                      page="/sys/026", headers={"x-kyungdong-role": "SYSADMIN"},
                      follow_redirects=False)
        loc = r.headers.get("location") or ""
        assert "issued" not in loc and "password" not in loc.lower(), \
            f"발급 응답의 Location 에 비밀번호가 실렸다: {loc}"
    finally:
        conn.x("delete from SYS_USERS where USER_ID > %s", (mark,))


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
        # 토큰은 6역할 전부가 열 수 있는 `/login` 에서 받는다 — 아래 403 이 **권한** 때문임을
        # 흐리지 않기 위해서다(권한 없는 역할은 `/sys/027` 화면 자체를 열 수 없다).
        r_no = csrf_post(client, "/sys/027", {"action": "download"}, page="/login",
                         headers={"x-kyungdong-role": "OPERATOR"}, follow_redirects=False)
        assert r_no.status_code == 403
        assert n1("select count(*) as n from DAT_DOWNLOAD_LOGS where DOWNLOAD_ID > %s",
                  (mark,)) == 0, "권한 없는 반출 시도가 기록을 남겼다"
        r_ok = csrf_post(client, "/sys/027", {"action": "download"}, page="/login",
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
        r = csrf_post(client, "/api/agent/query", {"question": q, "agent_type": "통합"},
                      page="/login", headers={"x-kyungdong-role": "SYSADMIN"})
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


def test_시뮬레이터는_루프백_밖으로_못_나간다():
    """사업계획서 9.2 외부 접속 최소화 · RAG 폐쇄형(외부 검색 0)의 경계다.

    시뮬레이터가 임의 호스트로 POST 할 수 있으면 그 경계가 **이 파일 하나로** 뚫린다.
    목적지는 우리 앱이고 우리 앱은 localhost 에 뜬다 — 그 밖은 아예 막는다.
    """
    import importlib

    sim = importlib.import_module("plc_simulator")
    for ok in ("http://127.0.0.1:8020", "http://localhost:8020", "http://[::1]:8020"):
        assert sim.check_loopback(ok) in sim.LOOPBACK_HOSTS, ok
    for bad in ("http://example.com", "https://api.openai.com", "http://10.0.0.5:8020"):
        with pytest.raises(SystemExit, match="루프백"):
            sim.check_loopback(bad)


def test_제품_코드에는_통신_모듈이_없다():
    """`tools/` 는 개발 도구라 통신이 있을 수 있지만 **`src/` 는 아니다.**

    검사기를 느슨하게 한 것이 아니라 **정밀하게** 만들었다(D-179) — 전에는 import 만 보고
    잡아서 '우리 앱에 POST 하는 시뮬레이터' 와 '외부 API 호출' 이 구분되지 않았다.
    제품 코드 쪽 기준은 그대로 **0건**이다.
    """
    net = re.compile(r"^\s*(import|from)\s+(requests|httpx|urllib|aiohttp|boto3|openai)\b", re.M)
    hits = [p.relative_to(ROOT).as_posix()
            for p in (ROOT / "src").rglob("*.py")
            if "__pycache__" not in p.parts and net.search(p.read_text())]
    assert hits == [], f"제품 코드에 통신 모듈이 있다: {hits}"
