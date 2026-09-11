#!/usr/bin/env python
"""G-26 ~ G-30 — 보안·운영 게이트 (QA3).

원칙 (goal.md §2 · §10 · 사업계획서 9.2)
  · **게이트를 낮추지 않는다.** 못 맞추면 `차단`, 못 재면 `판정 불가`.
  · **다른 사업의 사양을 정본인 척 적지 않는다** — TLS 버전·저장 암호화 알고리즘은
    사업계획서에 **없다**(D-15). 여기서 정하지 않는다. 로컬은 TLS 종단이 없으므로
    **설정·코드 경로 존재 + prod 프로파일 강제**로만 판정한다.
  · **0건 경로와 N건 경로를 둘 다 명시 단언**한다(§10-4). `skip` 은 결함이다(D-62).
  · **판정 정본 함수를 직접 부른다**(§10-16) — `app.rbac` · `app.settings` ·
    `util.{security,csrf,session,ratelimit,pii,audit}` · `ingest.collector`.
  · 측정 중 동시 변경을 감지하면 FAIL 이 아니라 **판정 불가**다(§10-17).
  · 이 검사기가 넣은 행은 **전부 지운다**.

출력 규약: 게이트별 판정 줄은 `G-NN <판정> — <실측>` 한 줄이다. 섹션 제목은 `──` 로 시작한다.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                      # noqa: E402
from fastapi.testclient import TestClient                        # noqa: E402
from kyungdong.app import nav, rbac                              # noqa: E402
from kyungdong.app.main import app                               # noqa: E402
from kyungdong.app.settings import settings                      # noqa: E402
from kyungdong.app.util import clock, csrf, pii, ratelimit, security, session   # noqa: E402
# D-54/D-106 — `util/__init__` 이 `audit` 를 **함수로** 재노출해 모듈을 가린다.
# `from ..util import audit` 는 함수를 준다. 모듈이 필요하면 importlib 로 직접 가져온다.
auditmod = importlib.import_module("kyungdong.app.util.audit")               # noqa: E402
from kyungdong.agent import service as agent_service             # noqa: E402
from kyungdong.ingest import collector, tags                     # noqa: E402

PASS, FAIL, BLOCKED, UNDET = "PASS", "FAIL", "차단", "판정 불가"
VERDICTS: list[tuple[str, str, str]] = []

ROLES = ("EXEC", "QUALITY", "PRODUCTION", "OPERATOR", "SUPPLIER_OPS", "SYSADMIN")
PERM_AREAS = tuple(rbac.PERM_AREA_TO_AREAS)

# contracts/db-schema.md §6 — 개인정보 6컬럼
PII_COLUMNS = (
    ("IF_DEVICE_REGISTRY", "IP_ADDRESS", "IP 주소"),
    ("INV_SUPPLIERS", "CONTACT_NAME", "담당자명"),
    ("INV_SUPPLIERS", "CONTACT_PHONE", "연락처"),
    ("SYS_USERS", "EMAIL", "이메일"),
    ("SYS_USERS", "PHONE_NO", "연락처"),
    ("SYS_USERS", "USER_NAME", "사용자명"),
)

SRC_DIRS = (ROOT / "src", ROOT / "db", ROOT / "tests", ROOT / "tools")
TEMPLATES = sorted((ROOT / "src" / "kyungdong" / "app" / "templates").rglob("*.html"))


def say(s: str = "") -> None:
    print(s)


def verdict(gate: str, v: str, m: str) -> None:
    VERDICTS.append((gate, v, m))


def n1(sql: str, params: Any = None) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


def count(table: str) -> int:
    return n1(f"select count(*) as n from {table}")


def fingerprint() -> str:
    acc = []
    for d in SRC_DIRS:
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            acc.append(f"{p}:{p.stat().st_mtime_ns}")
    return str(hash("\n".join(acc)))


def sources() -> dict[str, str]:
    out = {}
    for d in SRC_DIRS:
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out[p.relative_to(ROOT).as_posix()] = p.read_text()
    return out


# ══════════════════════════════════════════════════════════════════════════
# G-26 전송·저장 보안
# ══════════════════════════════════════════════════════════════════════════
def gate_26(client: TestClient) -> None:
    say("── G-26 HTTPS(TLS) · 외부 접속 최소화 · 비밀번호 해시 ──────────────")
    say("  ※ TLS 버전·저장 암호화 알고리즘은 **사업계획서에 없다(D-15)**. 여기서 정하지 않는다.")
    say("  ※ 로컬은 TLS 종단이 없다 — 설정·코드 경로 존재 + prod 프로파일 강제로만 판정한다.")
    bad: list[str] = []

    # ① prod 프로파일 강제
    hdr_dev = security.headers()                      # 정본 함수
    say(f"  ① dev 응답 헤더 {sorted(hdr_dev)}")
    say(f"     HSTS(dev) {'있음 — dev 에 HSTS 는 불필요' if 'Strict-Transport-Security' in hdr_dev else '없음 (정상)'}")
    orig_env = os.environ.get("KYUNGDONG_ENV")
    orig_sec = os.environ.get("KYUNGDONG_SESSION_SECRET")
    try:
        # prod + SESSION_SECRET 없음 → 기동 거부여야 한다
        os.environ["KYUNGDONG_ENV"] = "prod"
        os.environ.pop("KYUNGDONG_SESSION_SECRET", None)
        settings.cache_clear()
        refused = False
        try:
            settings()
        except RuntimeError as e:
            refused, why = True, str(e)
        say(f"     prod + SESSION_SECRET 미설정 → 기동 거부 {refused}"
            f"{' — ' + why[:60] if refused else ' **거부하지 않는다**'}")
        if not refused:
            bad.append("prod 에서 SESSION_SECRET 없이 기동된다")
        # prod + SESSION_SECRET → HSTS 가 붙는가
        os.environ["KYUNGDONG_SESSION_SECRET"] = "qa3-probe-secret-not-a-real-key"
        settings.cache_clear()
        hdr_prod = security.headers()
        hsts = hdr_prod.get("Strict-Transport-Security")
        say(f"     prod 응답 헤더 HSTS = {hsts!r}")
        if not hsts:
            bad.append("prod 프로파일에 HSTS 가 없다")
        # prod 에서 개발용 역할 전환이 막히는가 (main.attach_role)
        r = client.get("/dsh/001", headers={"x-kyungdong-role": "SYSADMIN"})
        say(f"     prod 에서 헤더 역할 전환 → GET /dsh/001 {r.status_code} (기대 403 — 인증 없이 열리면 결함)")
        if r.status_code != 403:
            bad.append(f"prod 에서 인증 없이 화면이 {r.status_code} 로 열린다")
    finally:
        if orig_env is None:
            os.environ.pop("KYUNGDONG_ENV", None)
        else:
            os.environ["KYUNGDONG_ENV"] = orig_env
        if orig_sec is None:
            os.environ.pop("KYUNGDONG_SESSION_SECRET", None)
        else:
            os.environ["KYUNGDONG_SESSION_SECRET"] = orig_sec
        settings.cache_clear()
        rbac.roles.cache_clear()

    # ② HTTPS 강제 경로 — 리다이렉트 미들웨어가 있는가
    src = sources()
    https_mw = [f for f, s in src.items()
                if f.startswith("src/")
                and ("HTTPSRedirectMiddleware" in s or "TrustedHostMiddleware" in s)]
    say(f"  ② HTTPS 강제·호스트 제한 미들웨어: {https_mw or '**0곳**'}")
    say("     (배포 형상이 정본에 없다 — 리버스 프록시 종단인지 앱 종단인지 미정. 사실만 적는다)")

    # ③ 외부 접속 최소화
    csp = security.CSP
    say(f"  ③ CSP = {csp}")
    external = [d for d in csp.split("; ") if "http" in d]
    tpl_ext = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
               if re.search(r"https?://(?!localhost)", p.read_text())]
    net_imports = [f"{f}" for f, s in src.items()
                   if re.search(r"^\s*(import|from)\s+(requests|httpx|urllib|aiohttp|boto3|openai)\b",
                                s, re.M) and not f.startswith("tests/")]
    say(f"     CSP 안 외부 출처 {external or '0건'} · 템플릿 외부 URL {tpl_ext or '0건'} · "
        f"외부 통신 모듈 import {net_imports or '0건'}")
    if external or tpl_ext or net_imports:
        bad.append("외부 출처·외부 통신 흔적이 있다")

    # ④ 비밀번호 해시 (bcrypt/Argon2)
    rows = conn.q("select LOGIN_ID, PASSWORD_HASH from SYS_USERS order by USER_ID")
    algos = {}
    for r in rows:
        h = r["password_hash"] or ""
        algo = h.split("$")[1] if h.startswith("$") and h.count("$") >= 2 else "**평문/미상**"
        algos[algo] = algos.get(algo, 0) + 1
    say(f"  ④ SYS_USERS {len(rows)} 계정 — PASSWORD_HASH 알고리즘 {algos}")
    okalgo = all(k.startswith(("argon2", "2a", "2b", "2y")) for k in algos)
    if not rows:
        bad.append("계정이 0건이라 해시를 확인할 수 없다")
    if not okalgo:
        bad.append(f"bcrypt/Argon2 가 아닌 해시가 있다: {algos}")

    # ⑤ CSRF — **직접 센다** (D-60/D-73 재확인)
    post_routes = sum(len(re.findall(r"@(?:router|app)\.post\(", s))
                      for f, s in src.items() if f.startswith("src/"))
    require_calls = sum(len(re.findall(r"csrf\.require\(", s))
                        for f, s in src.items()
                        if f.startswith("src/") and not f.endswith("util/csrf.py"))
    tpl_tokens = [p.relative_to(ROOT).as_posix() for p in TEMPLATES if "_csrf" in p.read_text()]
    enforced = csrf.enforced()                        # 정본 함수
    badge = [p.relative_to(ROOT).as_posix() for p in TEMPLATES if "CSRF 미적용" in p.read_text()]
    say(f"  ⑤ CSRF — POST 라우트 {post_routes} · csrf.require() 호출 {require_calls} · "
        f"템플릿 `_csrf` {len(tpl_tokens)} · CSRF_ENFORCE={enforced}")
    say(f"     화면 배지 '{'CSRF 미적용'}' 선언 위치: {badge or '**없음**'}")
    r = client.get("/", headers={"x-kyungdong-role": "SYSADMIN"})
    shown = "CSRF 미적용" in r.text
    say(f"     실제 렌더 확인: GET / 에 'CSRF 미적용' 배지 {'있음' if shown else '**없음**'}")
    if require_calls == 0 or not tpl_tokens:
        bad.append(f"CSRF 가 POST {post_routes}개 중 {require_calls}곳에만 연결돼 있다 "
                   f"(템플릿 토큰 {len(tpl_tokens)}개) — 요청 위조 방지 미적용 (D-60/D-73)")
    if not enforced:
        bad.append("KYUNGDONG_CSRF_ENFORCE=0 — 보호 장치가 꺼져 있다")

    verdict("G-26", PASS if not bad else FAIL,
            f"prod HSTS·기동거부 코드 경로 있음 · 외부 출처 0 · 해시 {algos} · "
            f"**CSRF {require_calls}/{post_routes}** (템플릿 토큰 {len(tpl_tokens)}, "
            f"ENFORCE={int(enforced)}, 배지 노출 {shown}) · "
            f"TLS 버전·저장 암호화 알고리즘은 정본 부재(D-15)로 판정 대상 아님" +
            ("" if not bad else " · 결함 " + " / ".join(bad[:3])))
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-27 계정·비밀번호·잠금·자동 로그아웃
# ══════════════════════════════════════════════════════════════════════════
def gate_27(client: TestClient) -> None:
    say("── G-27 역할별 계정 분리 · 최소 권한 · 복잡도·주기 · 잠금 · 자동 로그아웃 ──")
    bad: list[str] = []
    src = sources()

    # ① 역할별 계정 분리
    rows = conn.q("select u.LOGIN_ID, u.USER_NAME, u.LOCK_YN, u.USE_YN, u.PWD_CHANGED_DT, "
                  "p.ROLE_CODE from SYS_USERS u "
                  "join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID order by u.USER_ID")
    per_role = {r["role_code"]: r["login_id"] for r in rows}
    say(f"  ① 계정 {len(rows)} · 역할 {len(per_role)} — {per_role}")
    shared = len(rows) - len({r["login_id"] for r in rows})
    if set(per_role) != set(ROLES):
        bad.append(f"역할별 계정이 6종이 아니다: {sorted(per_role)}")
    if shared:
        bad.append(f"중복 로그인 계정 {shared} 건")

    # ② 최소 권한 — DB 권한행이 TD3 정본(rbac)과 같은가
    mismatch = []
    for role in ROLES:
        for area, prefix in sorted({s.area: s.prefix.upper() for s in nav.all_screens()}.items()):
            p = rbac.perm_for(role, area)             # 정본 함수
            row = conn.q1("select READ_YN, WRITE_YN, DOWNLOAD_YN from SYS_ROLE_PERMISSIONS "
                          "where ROLE_CODE = %s and AREA_CODE = %s", (role, prefix))
            if row is None:
                mismatch.append(f"{role}/{prefix} 권한행 없음")
                continue
            if (row["read_yn"] == "Y") != p.read or (row["write_yn"] == "Y") != p.write:
                mismatch.append(f"{role}/{prefix} DB({row['read_yn']}{row['write_yn']}) "
                                f"≠ TD3({int(p.read)}{int(p.write)})")
    say(f"  ② DB 권한행 ↔ TD3 role_matrix 불일치 {len(mismatch)} 건 {mismatch[:3]}")
    if mismatch:
        bad.append(f"권한행 불일치 {len(mismatch)} 건")
    # 최소 권한 관찰 — 넓어 보이는 셀을 실측으로 드러낸다 (판정은 정본이 한다)
    wide = [(r, a, rbac.perm_for(r, rbac.PERM_AREA_TO_AREAS[a][0]).label)
            for r in ROLES for a in ("사용자/시스템관리",)
            if rbac.perm_for(r, rbac.PERM_AREA_TO_AREAS[a][0]).write]
    say(f"     사용자/시스템관리에 등록·수정 권한이 있는 역할: {wide}")

    # ③ 비밀번호 복잡도·주기 — **값은 있는데 검증 코드가 있는가**
    s = settings()
    pol = {k: (s.h(k).value, s.h(k).badge) for k in
           ("PASSWORD_MIN_LEN", "PASSWORD_CHANGE_CYCLE_DAYS", "LOGIN_FAIL_MAX",
            "RATE_LIMIT_IP", "SESSION_IDLE_MINUTES")}
    say(f"  ③ 정책값 {pol}")
    uses = {k: [f for f, t in src.items()
                if f.startswith("src/") and k in t and "settings.py" not in f]
            for k in ("PASSWORD_MIN_LEN", "PASSWORD_CHANGE_CYCLE_DAYS")}
    for k, files in uses.items():
        say(f"     {k} 를 읽는 곳: {files or '**0곳 — 화면 표시 말고 강제하는 코드가 없다**'}")
    enforcing = [f for f in uses["PASSWORD_MIN_LEN"] if "main.py" not in f]
    if not enforcing:
        bad.append("비밀번호 복잡도(최소 길이)를 **검증하는 코드가 0곳**이다 — 값만 화면에 띄운다")
    cycle_use = [f for f in uses["PASSWORD_CHANGE_CYCLE_DAYS"] if "main.py" not in f]
    if not cycle_use:
        bad.append("비밀번호 주기 변경을 **강제하는 코드가 0곳**이다 (PWD_CHANGED_DT 를 읽지 않는다)")

    # ④ 로그인 실패 잠금 — 모듈은 있는가 / 라우트에 연결됐는가
    ratelimit.reset_all()
    acc_max = s.h("LOGIN_FAIL_MAX").as_int()
    ip_max = s.h("RATE_LIMIT_IP").as_int()
    say(f"  ④ 잠금 — 계정 {acc_max} / IP {ip_max} (10분 창 {ratelimit.WINDOW_SEC}초) "
        f"{s.h('LOGIN_FAIL_MAX').badge}")
    say(f"     0건 경로: 실패 0회 → blocked {ratelimit.blocked('qa3probe', '10.0.0.1')}")
    for _ in range(acc_max):
        ratelimit.record_failure("qa3probe", "10.0.0.1")
    blocked_acc = ratelimit.blocked("qa3probe", "10.0.0.1")
    say(f"     N건 경로: 계정 실패 {acc_max}회 → blocked {blocked_acc}")
    ratelimit.reset_all()
    for i in range(ip_max):
        ratelimit.record_failure(f"qa3user{i}", "10.0.0.2")
    blocked_ip = ratelimit.blocked("전혀다른계정", "10.0.0.2")
    say(f"     N건 경로: IP 실패 {ip_max}회 → blocked {blocked_ip}")
    ratelimit.reset_all()
    if not (blocked_acc[0] and blocked_ip[0]):
        bad.append("잠금 모듈이 한도에서 막지 않는다")
    wired = [f for f, t in src.items()
             if f.startswith("src/") and "ratelimit." in t and "util/ratelimit.py" not in f
             and "util/__init__.py" not in f]
    login_post = [f for f, t in src.items()
                  if f.startswith("src/") and re.search(r"@(?:app|router)\.post\(\"/login", t)]
    say(f"     잠금 모듈을 **부르는 라우트**: {wired or '**0곳**'} · POST /login 구현: "
        f"{login_post or '**0곳 — 로그인 처리 자체가 없다**'}")
    if not wired or not login_post:
        bad.append("로그인 실패 잠금이 **어디에도 연결되지 않았다** — POST /login 이 없다 "
                   "(모듈만 있고 경로가 없다)")

    # ⑤ 자동 로그아웃 — 서버측 유휴 만료
    session.reset_all()
    cookie, sess = session.create(1, "qa3probe", "SYSADMIN")
    alive = session.load(cookie) is not None
    sess.last_seen -= (s.h("SESSION_IDLE_MINUTES").as_int() * 60 + 5)
    expired = session.load(cookie) is None
    say(f"  ⑤ 자동 로그아웃 — 생성 직후 유효 {alive} · 유휴 "
        f"{s.h('SESSION_IDLE_MINUTES').value}분 초과 후 무효 {expired} · "
        f"서버측 레지스트리 잔존 {session.active_count()} (0 이어야 한다)")
    session.reset_all()
    if not (alive and expired):
        bad.append("유휴 만료가 동작하지 않는다")
    logout = [f for f, t in src.items()
              if f.startswith("src/") and ("session.destroy" in t or "/logout" in t)]
    say(f"     로그아웃 경로: {logout or '**0곳 — 세션 파기를 부르는 라우트가 없다**'}")
    if not logout:
        bad.append("로그아웃(세션 파기) 라우트가 0곳이다")

    verdict("G-27", PASS if not bad else FAIL,
            f"계정 {len(rows)}/역할 {len(per_role)} 분리 · DB↔TD3 권한 불일치 {len(mismatch)} · "
            f"잠금 모듈 동작(계정 {acc_max}/IP {ip_max}) · 유휴만료 동작 · "
            f"**POST /login {len(login_post)}곳 · 잠금 연결 {len(wired)}곳 · "
            f"복잡도 검증 {len(enforcing)}곳 · 주기 강제 {len(cycle_use)}곳 · 로그아웃 {len(logout)}곳**" +
            ("" if not bad else " · 결함 " + " / ".join(bad[:3])))
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-28 RBAC 6역할 × 8권한영역
# ══════════════════════════════════════════════════════════════════════════
def gate_28(client: TestClient) -> None:
    say("── G-28 RBAC 6역할 × 8권한영역 · 권한 없음 = 403 ──────────────────")
    roles = rbac.roles()                                # 정본 함수
    say(f"  역할 {len(roles)} × 권한영역 {len(PERM_AREAS)} = {len(roles) * len(PERM_AREAS)} 셀")
    bad: list[str] = []
    if len(roles) != 6 or len(PERM_AREAS) != 8:
        bad.append(f"6×8 이 아니다: {len(roles)}×{len(PERM_AREAS)}")

    # ① 총괄PM(EXEC) — 견적AI·출하가 `조회/승인` 이다. 등록·수정 없이 **승인만** (D-84)
    say("  ① 총괄PM/경영자(EXEC) 권한 — 등록·수정 없이 승인만이어야 한다")
    for area in ("수주견적AI관리", "출하물류관리"):
        p = rbac.perm_for("EXEC", area)
        ok = p.read and p.approve and not p.write
        say(f"     {area:<12} 셀 '{p.label}' → 조회 {p.read} 등록·수정 {p.write} 승인 {p.approve}"
            f"  {'OK' if ok else '** 기대 어긋남'}")
        if not ok:
            bad.append(f"EXEC/{area}: 조회/승인 이어야 한다 (D-84)")

    # ② 45화면 × 6역할 GET — 권한 없으면 403, 있으면 403 아님
    say("  ② 45화면 × 6역할 GET 실측 (0건 경로·N건 경로를 둘 다 단언한다)")
    screens = nav.all_screens()
    mism: list[str] = []
    allowed_n = denied_n = 0
    for role in ROLES:
        for sc in screens:
            want = rbac.can_read(role, sc.area)
            r = client.get(sc.path, headers={"x-kyungdong-role": role})
            got = r.status_code
            if want:
                allowed_n += 1
                if got == 403:
                    mism.append(f"{sc.path} as {role}: 403 인데 권한 있음")
            else:
                denied_n += 1
                if got != 403:
                    mism.append(f"{sc.path} as {role}: {got} (기대 403)")
    say(f"     권한 있음 {allowed_n} 회 · 권한 없음 {denied_n} 회 → 불일치 {len(mism)} 건")
    for m in mism[:8]:
        say(f"     ** {m}")
    if denied_n == 0:
        bad.append("권한 없음 경로가 0회다 — 403 을 한 번도 재지 못했다")
    if mism:
        bad.append(f"화면 권한 판정 불일치 {len(mism)} 건")

    # ③ 좌측 메뉴는 권한 있는 것만
    menu_bad = []
    for role in ROLES:
        r = client.get("/", headers={"x-kyungdong-role": role})
        for sc in screens:
            visible = f'href="{sc.path}"' in r.text
            if visible and not rbac.can_read(role, sc.area):
                menu_bad.append(f"{role}: 권한 없는 {sc.path} 가 메뉴에 보인다")
    say(f"  ③ 좌측 메뉴 노출 위반 {len(menu_bad)} 건 {menu_bad[:3]}")
    if menu_bad:
        bad.append(f"메뉴 노출 위반 {len(menu_bad)} 건")

    verdict("G-28", PASS if not bad else FAIL,
            f"{len(roles)}역할×{len(PERM_AREAS)}영역 · 화면 GET {allowed_n + denied_n} 회 "
            f"(허용 {allowed_n}·차단 {denied_n}) 불일치 {len(mism)} · 메뉴 위반 {len(menu_bad)} · "
            f"EXEC 견적AI·출하 = 조회/승인(등록·수정 없음) 확인" +
            ("" if not bad else " · 결함 " + " / ".join(bad[:3])))
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-29 감사추적 · 개인정보 · 비밀번호 리터럴
# ══════════════════════════════════════════════════════════════════════════
def gate_29(client: TestClient) -> dict[str, int]:
    say("── G-29 감사 — 접속·변경·API·오류 · 반출 · AI 질의 · 개인정보 · 리터럴 ──")
    bad: list[str] = []
    src = sources()
    base_access = count("SYS_ACCESS_LOGS")
    base_dl = count("DAT_DOWNLOAD_LOGS")
    base_q = count("AGT_QUERY_LOGS")
    maxa = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    maxd = n1("select coalesce(max(DOWNLOAD_ID),0) as n from DAT_DOWNLOAD_LOGS")
    maxq = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    say(f"  (G-28 화면 270회 조회가 이미 SYS_ACCESS_LOGS 를 채웠다 — "
        f"시작 기준점은 main() 이 잡은 MARKS 다. 여기 숫자는 이 게이트의 증분 기준이다)")
    say(f"  0건 경로: SYS_ACCESS_LOGS {base_access} · DAT_DOWNLOAD_LOGS {base_dl} · "
        f"AGT_QUERY_LOGS {base_q} (깨끗한 DB 0건이 정상 — G-11)")

    # ① 4종 로그타입 — 45화면을 **한 건씩** 열어 접속 기록이 남는지 센다
    say("  ① 접속 로그 — 45화면을 SYSADMIN 으로 한 번씩 열고 SYS_ACCESS_LOGS 증분을 본다")
    logged, unlogged = [], []
    for sc in nav.all_screens():
        m = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
        client.get(sc.path, headers={"x-kyungdong-role": "SYSADMIN"})
        got = n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                 "and LOG_TYPE = '접속'", (m,))
        (logged if got else unlogged).append(f"{sc.path}({sc.owner})")
    say(f"     접속 기록 남음 {len(logged)}/45 · **남지 않음 {len(unlogged)}/45**")
    say(f"     남지 않는 화면: {unlogged}")
    if unlogged:
        bad.append(f"45화면 중 {len(unlogged)}개가 조회해도 SYS_ACCESS_LOGS 에 "
                   f"'접속' 을 남기지 않는다 (모듈별: "
                   f"{sorted({p.split('/')[1] for p in unlogged})})")
    # 변경 · API · 오류
    # API — JSON 엔드포인트 / 화면 Agent(정상 갈래) / 화면 Agent(501 갈래) 를 나눠 잰다
    ma = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    client.post("/api/agent/query", data={"question": "환율 적용 기준은 무엇인가",
                                          "agent_type": "통합"},
                headers={"x-kyungdong-role": "SYSADMIN"})
    api_json = n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s", (ma,))
    ma = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    r_ok = client.post("/inv/009", data={"q1": "환율 적용 기준은 무엇인가"},
                       headers={"x-kyungdong-role": "SYSADMIN"})
    api_screen = n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s "
                    "and LOG_TYPE = 'API'", (ma,))
    ma = n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")
    r_501 = client.post("/inv/009", data={"q1": "문서 누락 자재는 격리구역에 두는가"},
                        headers={"x-kyungdong-role": "SYSADMIN"})
    api_err = n1("select count(*) as n from SYS_ACCESS_LOGS where LOG_ID > %s", (ma,))
    say(f"     API 감사 — JSON /api/agent/query → 기록 {api_json} 행 (기대 1) · "
        f"화면 /inv/009 정상({r_ok.status_code}) → API 기록 {api_screen} 행 (기대 1) · "
        f"화면 /inv/009 LLM 미구성({r_501.status_code}) → 기록 {api_err} 행 (기대 1)")
    if api_json == 0:
        bad.append("`/api/agent/query` 등 JSON Agent API 가 SYS_ACCESS_LOGS 에 "
                   "아무 기록도 남기지 않는다 (AGT_QUERY_LOGS 에만 남는다)")
    if api_err == 0:
        bad.append("화면 Agent 질의가 501 로 끝나면 API 감사 기록이 남지 않는다 "
                   "(audit() 가 호출 뒤에 있어 예외 갈래를 지나친다)")
    client.post("/bas/032", data={"code_group": "", "code_value": ""},
                headers={"x-kyungdong-role": "SYSADMIN"})                        # 변경 시도
    client.get("/est/999", headers={"x-kyungdong-role": "SYSADMIN"})             # 없는 경로
    client.get("/est/010", headers={"x-kyungdong-role": "OPERATOR"})             # 403
    kinds = conn.q("select LOG_TYPE, count(*) as n from SYS_ACCESS_LOGS "
                   "where LOG_ID > %s group by 1 order by 1", (maxa,))
    got_kinds = {k["log_type"]: int(k["n"]) for k in kinds}
    say(f"     기록된 LOG_TYPE {got_kinds} / 계약 {auditmod.LOG_TYPES}")
    audit_calls = {t: sum(len(re.findall(rf'log_type="{t}"', s))
                          for f, s in src.items() if f.startswith("src/"))
                   for t in auditmod.LOG_TYPES}
    say(f"     소스에서 log_type 별 호출 수 {audit_calls} "
        "('접속' 은 기본값이라 인자 없이 불린다)")
    missing_kind = [t for t in auditmod.LOG_TYPES if t not in got_kinds]
    if audit_calls["오류"] == 0:
        bad.append("LOG_TYPE '오류' 를 남기는 코드가 **0곳**이다 — 500·403·422 가 감사에 남지 않는다 "
                   "(main.py 전역 500 핸들러도 SYS_ACCESS_LOGS 를 쓰지 않는다)")
    say(f"     기록되지 않은 LOG_TYPE {missing_kind}")

    # ② 반출 이력 — 권한 있는 경로와 없는 경로를 둘 다 단언
    r_ok = client.post("/sys/027", data={"action": "download"},
                       headers={"x-kyungdong-role": "SYSADMIN"}, follow_redirects=False)
    r_no = client.post("/sys/027", data={"action": "download"},
                       headers={"x-kyungdong-role": "OPERATOR"}, follow_redirects=False)
    dl_added = count("DAT_DOWNLOAD_LOGS") - base_dl
    say(f"  ② 반출 — SYSADMIN {r_ok.status_code} · OPERATOR {r_no.status_code} (기대 403) "
        f"→ DAT_DOWNLOAD_LOGS +{dl_added} 행")
    if r_no.status_code != 403:
        bad.append(f"반출 권한 없는 역할이 {r_no.status_code} 를 받았다")
    if dl_added < 1:
        bad.append("반출을 했는데 DAT_DOWNLOAD_LOGS 에 기록이 없다")

    # ③ AI 질의 이력
    q_added = count("AGT_QUERY_LOGS") - base_q
    say(f"  ③ AI 질의 → AGT_QUERY_LOGS +{q_added} 행 (기대 ≥1)")
    if q_added < 1:
        bad.append("AI 질의가 AGT_QUERY_LOGS 에 기록되지 않았다")

    # ④ 개인정보 6컬럼 — 저장 암호화 · 화면 마스킹
    say("  ④ 개인정보 6컬럼 (contracts/db-schema.md §6)")
    plain = []
    for table, col, label in PII_COLUMNS:
        total = count(table)
        nonnull = n1(f"select count({col}) as n from {table}")
        sample = conn.q1(f"select {col} as v from {table} where {col} is not null limit 1")
        v = sample["v"] if sample else None
        looks_encrypted = bool(v) and re.fullmatch(r"[A-Za-z0-9+/=]{24,}", str(v)) is not None
        say(f"     {table}.{col:<14} {label:<6} 행 {total:>3} · 값 있는 행 {nonnull:>3} · "
            f"표본 {str(v)[:20]!r} · 암호문으로 보임 {looks_encrypted}")
        if nonnull and not looks_encrypted:
            plain.append(f"{table}.{col}")
    say(f"     평문 저장으로 보이는 컬럼 {plain or '없음(값이 0건이라 판정 불가인 컬럼 포함)'}")
    say("     ※ 저장 암호화 **알고리즘이 정본에 없다(D-15)** — 여기서 알고리즘을 정하지 않는다. "
        "'암호화 또는 마스킹' 중 마스킹만 구현돼 있다는 사실만 적는다.")
    # 마스킹 함수 동작 + 화면 적용
    say(f"     pii.mask 실측: name {pii.mask('홍길동','name')!r} · "
        f"phone {pii.mask('010-1234-5678','phone')!r} · email {pii.mask('abcd@x.com','email')!r}")
    r = client.get("/sys/026", headers={"x-kyungdong-role": "SYSADMIN"})
    names = [x["user_name"] for x in conn.q("select USER_NAME from SYS_USERS") if x["user_name"]]
    leaked = [nm for nm in names if nm in r.text and pii.mask(nm, "name") not in r.text]
    say(f"     /sys/026 화면에 원문 사용자명 노출 {len(leaked)} 건 {leaked[:3]}")
    if leaked:
        bad.append(f"사용자명 원문이 화면에 노출된다 {leaked[:2]}")
    mask_users = [f for f, s in src.items() if f.startswith("src/") and "mask(" in s]
    say(f"     mask() 를 쓰는 소스 {len(mask_users)} 곳")

    # ⑤ 비밀번호 리터럴 0건
    say("  ⑤ 시드·소스 비밀번호 리터럴")
    pat = re.compile(r"(password|passwd|pwd)\s*[:=]\s*[\"'][^\"']{3,}[\"']", re.I)
    lits = []
    for f, s in src.items():
        for i, line in enumerate(s.splitlines(), 1):
            m = pat.search(line)
            if m and "hash" not in line.lower() and "env" not in line.lower():
                lits.append(f"{f}:{i} {m.group(0)[:40]}")
    say(f"     리터럴 {len(lits)} 건 {lits[:3]}")
    if lits:
        bad.append(f"비밀번호 리터럴 {len(lits)} 건")
    # 발급 비밀번호가 URL 쿼리로 흐르는가
    url_pw = [f"{f}:{i}" for f, s in src.items() if f.startswith("src/")
              for i, line in enumerate(s.splitlines(), 1)
              if re.search(r"issued=\{?raw|\?.*password=", line)]
    say(f"     발급 비밀번호가 **URL 쿼리스트링**으로 흐르는 곳: {url_pw or '없음'}")
    if url_pw:
        bad.append(f"평문 비밀번호가 URL 쿼리로 전달된다 ({url_pw[0]}) — "
                   "브라우저 이력·Referer·프록시 로그에 남는다")

    verdict("G-29", PASS if not bad else FAIL,
            f"SYS_ACCESS_LOGS 기록 {got_kinds} (미기록 {missing_kind}) · 반출 +{dl_added} "
            f"(무권한 {r_no.status_code}) · AI 질의 +{q_added} · 개인정보 6컬럼 마스킹 O / "
            f"저장 암호화 X(알고리즘 정본 부재 D-15) · 비밀번호 리터럴 {len(lits)} · "
            f"URL 평문 비밀번호 {len(url_pw)}" +
            ("" if not bad else " · 결함 " + " / ".join(bad[:3])))
    return {"maxa": maxa, "maxd": maxd, "maxq": maxq}


# ══════════════════════════════════════════════════════════════════════════
# G-30 조용한 실패 사냥
# ══════════════════════════════════════════════════════════════════════════
def gate_30(client: TestClient) -> dict[str, int]:
    say()
    say("── G-30 조용한 실패 사냥 — 죽였을 때 화면이 멀쩡해 보이면 결함 ────────")
    bad: list[str] = []

    # ① DB 를 죽인다 → 503 이어야 한다. 빈 그리드로 '데이터 없음' 이면 결함이다.
    orig = os.environ.get("KYUNGDONG_PG_DSN")
    os.environ["KYUNGDONG_PG_DSN"] = "postgresql://127.0.0.1:1/nope_qa3"
    settings.cache_clear()
    try:
        r = client.get("/dsh/001", headers={"x-kyungdong-role": "SYSADMIN"})
        body = r.text
        say(f"  ① DB 죽임 → GET /dsh/001 {r.status_code} (기대 503) · "
            f"'서비스 일시 중단' {'있음' if '서비스 일시 중단' in body else '**없음**'}")
        if r.status_code != 503:
            bad.append(f"DB 가 죽었는데 {r.status_code} 를 돌려준다 — 조용한 실패")
        r2 = client.get("/inv/006", headers={"x-kyungdong-role": "SYSADMIN"})
        say(f"     GET /inv/006 {r2.status_code} (기대 503)")
        if r2.status_code != 503:
            bad.append(f"/inv/006: DB 죽음에 {r2.status_code}")
    finally:
        if orig is None:
            os.environ.pop("KYUNGDONG_PG_DSN", None)
        else:
            os.environ["KYUNGDONG_PG_DSN"] = orig
        settings.cache_clear()
    say(f"     DB 복구 확인: GET /dsh/001 "
        f"{client.get('/dsh/001', headers={'x-kyungdong-role': 'SYSADMIN'}).status_code}")

    # ② LLM 을 죽인다(= 미구성) → 501. 조용한 폴백 문장을 만들면 결함이다.
    # **임계를 넘는 질의**여야 LLM 호출 단계까지 간다. 임계 미달 질의는 그 앞에서 200 으로 끝난다.
    hi_q = "문서 누락 자재는 격리구역에 두는가"
    from kyungdong.agent import retrieval as _ret
    hi_ev, _ = _ret.search(hi_q, agent_type="통합")
    hi_score = _ret.confidence(hi_ev)
    r = client.post("/api/agent/query", data={"question": hi_q, "agent_type": "통합"},
                    headers={"x-kyungdong-role": "SYSADMIN"})
    say(f"  ② LLM 미구성 → POST /api/agent/query (신뢰도 {hi_score:.4f} ≥ 임계 "
        f"{settings().h('RAG_CONFIDENCE_MIN').value}) {r.status_code} (기대 501 LLM 미구성) "
        f"· 본문에 'LLM 미구성' {'있음' if 'LLM 미구성' in r.text else '없음'}")
    if r.status_code != 501:
        bad.append(f"LLM 미구성인데 {r.status_code} — 조용한 폴백 가능성")
    r0 = client.post("/api/agent/query", data={"question": "환율 적용 기준", "agent_type": "통합"},
                     headers={"x-kyungdong-role": "SYSADMIN"})
    say(f"     근거 0건 질의 → {r0.status_code} (기대 200 + '검토 필요 — 근거 부족') "
        f"· 문구 {'있음' if '근거 부족' in r0.text else '**없음**'}")
    if r0.status_code != 200 or "근거 부족" not in r0.text:
        bad.append("근거 0건 경로가 200 + '검토 필요 — 근거 부족' 이 아니다")

    # ③ CAD 파서를 죽인다(= 미구성) → 501 또는 명시 배지
    r = client.get("/est/010", headers={"x-kyungdong-role": "SYSADMIN"})
    has_badge = "미구성" in r.text or "CAD Parsing" in r.text
    say(f"  ③ CAD 파서 미구성 → GET /est/010 {r.status_code} · 미구성 배지 "
        f"{'있음' if has_badge else '**없음**'}")
    if not has_badge:
        bad.append("/est/010 에 CAD 미구성 배지가 없다 — 정상으로 보인다")

    # ④ 시뮬레이터를 죽인다 → 003·022 에 '수집 중단' + 마지막 수집시각
    say("  ④ 수집 중단 — 0건 경로와 '오래된 수집' 경로를 둘 다 단언한다")
    for path in ("/dsh/003", "/prc/022"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        say(f"     [0건] {path} {r.status_code} · '미수집' "
            f"{'있음' if '미수집' in r.text else '**없음**'}")
    st0 = collector.status()
    say(f"     collector.status() (수집 0건) = {st0}")
    dev = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                  ("레이저커팅기 PLC",))
    base_ids = {t: n1(f"select coalesce(max({c}),0) as n from {t}")
                for t, c in (("IF_PLC_SIGNALS", "PLC_IF_ID"),
                             ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                             ("DAT_TIMESERIES", "TS_ID"))}
    stale_ok = False
    try:
        old = clock.anchor() - timedelta(hours=2)
        collector.ingest_batch(int(dev["device_id"]), "EQ10",
                               [collector.Sample(t.name, "1" if t.numeric else "가동", old)
                                for t in tags.TAGS])
        st1 = collector.status()
        say(f"     collector.status() (앵커 −2h 1배치) = {st1}")
        for path in ("/dsh/003", "/prc/022"):
            r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
            has_stale = "수집 중단" in r.text
            has_ts = old.strftime("%Y-%m-%d %H:%M") in r.text
            say(f"     [오래된 수집] {path} {r.status_code} · '수집 중단' "
                f"{'있음' if has_stale else '**없음**'} · 마지막 수집시각 "
                f"{'있음' if has_ts else '**없음**'}")
            if not has_stale:
                bad.append(f"{path}: 마지막 수집이 앵커 −2h 인데 '수집 중단' 표시가 없다")
            stale_ok = stale_ok or has_stale
    finally:
        for t, c in (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                     ("IF_PLC_SIGNALS", "PLC_IF_ID")):
            conn.x(f"delete from {t} where {c} > %s", (base_ids[t],))
        say("     (중단 시나리오 1배치 삭제 — 분모를 흐리지 않는다)")

    # ⑤ 백엔드를 죽인다 — 서버를 띄우지 않는 검사기라 **직접 재지 못한다**
    js = [p.relative_to(ROOT).as_posix() for p in
          (ROOT / "src" / "kyungdong" / "app" / "static").rglob("*.js")]
    inline_js = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
                 if re.search(r"<script(?![^>]*src=)", p.read_text())]
    fetches = [p.relative_to(ROOT).as_posix() for p in TEMPLATES
               if re.search(r"fetch\(|XMLHttpRequest", p.read_text())]
    say(f"  ⑤ 백엔드 죽임 — **직접 재지 못했다**(검사기가 서버를 띄우지 않는다). "
        f"대신 클라이언트 폴백 표면을 센다: js 파일 {len(js)} · 인라인 script "
        f"{len(inline_js)} · fetch/XHR {len(fetches)}")
    say("     → 전 화면 서버 렌더이고 클라이언트 비동기 호출이 0건이다. 백엔드가 죽으면 "
        "브라우저가 연결 실패를 그대로 보여 준다(화면이 멀쩡해 보일 표면이 없다). "
        "브라우저 실측은 하지 않았다.")

    # ⑥ 그리드 셀 이스케이프 — `<script>` 시드
    say("  ⑥ 그리드 셀 이스케이프 (<script> 시드)")
    maxq = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    payload = "<script>alert('qa3')</script> 격리구역 기준"
    agent_service.ask(payload, agent_type="통합",
                      user_id=agent_service.resolve_user("SYSADMIN"), role_code="SYSADMIN")
    r = client.get("/agt/042", headers={"x-kyungdong-role": "SYSADMIN"})
    raw = "<script>alert('qa3')</script>" in r.text
    esc = "&lt;script&gt;" in r.text
    say(f"     /agt/042 {r.status_code} · 원문 <script> 그대로 {raw} (기대 False) · "
        f"이스케이프된 &lt;script&gt; {esc} (기대 True)")
    if raw or not esc:
        bad.append("그리드 셀이 이스케이프되지 않는다 — 저장형 XSS")
    unsafe = [f"{p.relative_to(ROOT).as_posix()}" for p in TEMPLATES
              if re.search(r"\{\{[^}]*\|\s*safe", p.read_text())]
    mention = [f"{p.relative_to(ROOT).as_posix()}" for p in TEMPLATES if "|safe" in p.read_text()]
    say(f"     템플릿 `|safe` **실제 사용** {len(unsafe)} 곳 {unsafe[:3]} "
        f"(주석 언급까지 포함하면 {len(mention)} 곳)")
    if unsafe:
        bad.append(f"그리드 템플릿에 |safe 사용 {len(unsafe)} 곳")

    verdict("G-30", PASS if not bad else FAIL,
            f"DB 죽임 503 · LLM 미구성 501 · 근거 0건 200+문구 · CAD 배지 · "
            f"수집 중단 표시 {stale_ok} · 그리드 이스케이프 {esc and not raw} · "
            f"백엔드 죽임은 **직접 재지 못했다**(클라이언트 fetch 0건이라 폴백 표면 없음)" +
            ("" if not bad else " · 결함 " + " / ".join(bad[:3])))
    return {"maxq": maxq}


def cleanup(marks: dict[str, int]) -> None:
    say()
    a = conn.x("delete from SYS_ACCESS_LOGS where LOG_ID > %s", (marks["maxa"],))
    d = conn.x("delete from DAT_DOWNLOAD_LOGS where DOWNLOAD_ID > %s", (marks["maxd"],))
    q = conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (marks["maxq"],))
    say(f"── 정리: SYS_ACCESS_LOGS {a} · DAT_DOWNLOAD_LOGS {d} · AGT_QUERY_LOGS {q} 행 삭제 "
        f"→ 현재 {count('SYS_ACCESS_LOGS')} · {count('DAT_DOWNLOAD_LOGS')} · "
        f"{count('AGT_QUERY_LOGS')}")


def main() -> int:
    fp0 = fingerprint()
    say("tools/check_security.py — G-26~G-30 (QA3)")
    say(f"DSN {settings().pg_dsn} · ENV {settings().env}")
    say()
    client = TestClient(app, raise_server_exceptions=False)
    # 검사기가 만든 런타임 행만 지우려면 **시작 시점**을 기준으로 잡아야 한다.
    marks = {
        "maxa": n1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS"),
        "maxd": n1("select coalesce(max(DOWNLOAD_ID),0) as n from DAT_DOWNLOAD_LOGS"),
        "maxq": n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS"),
    }
    say(f"시작 기준점 {marks} — 이 뒤에 생긴 런타임 행은 끝나고 전부 지운다")

    gate_26(client)
    gate_27(client)
    gate_28(client)
    gate_29(client)
    gate_30(client)
    cleanup(marks)

    if fp0 != fingerprint():
        say()
        say("**측정 중 소스가 바뀌었다 — 이 회차 판정은 전부 `판정 불가` 다 (§10-17)**")
        for i, (g, _v, m) in enumerate(VERDICTS):
            VERDICTS[i] = (g, UNDET, f"동시 변경 감지 — {m}")

    say()
    say("═══ 판정 ═══")
    for g, v, m in VERDICTS:
        say(f"{g} {v} — {m}")
    say()
    say(f"PASS {sum(1 for _g, v, _m in VERDICTS if v == PASS)} · "
        f"FAIL {sum(1 for _g, v, _m in VERDICTS if v == FAIL)} · "
        f"차단 {sum(1 for _g, v, _m in VERDICTS if v == BLOCKED)} · "
        f"판정 불가 {sum(1 for _g, v, _m in VERDICTS if v == UNDET)} / {len(VERDICTS)}")
    return 0 if all(v == PASS for _g, v, _m in VERDICTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
