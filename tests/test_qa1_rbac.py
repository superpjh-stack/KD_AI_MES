"""QA1 ② RBAC — 6역할 × 8권한영역 (G-28) · 6역할 × 45화면 전수.

권한 없음 = **403**(api-contract §0-4 · §4). 좌측 메뉴는 **권한 있는 것만** 노출한다.
판정 정본은 `rbac.can_read/can_write/can_approve` 다 — 여기에 권한표를 다시 적지 않는다(§10-16).
역할 전환은 개발용 `?as=` 다(D-40). **prod 에서는 안 먹혀야** 한다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from conftest import csrf_post                             # noqa: E402
from kyungdong.app import design, nav, rbac               # noqa: E402
from kyungdong.app.main import app                        # noqa: E402
from kyungdong.app.settings import settings               # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

# 토큰을 꺼낼 화면. 브라우저는 **세션에 매인 토큰 하나**를 들고 다닌다(util/csrf.py `_bind` —
# 토큰은 경로가 아니라 세션·쿠키에 묶인다). `/login` 은 6역할 전부가 열 수 있어,
# 조회 권한이 없는 역할이 403 을 받는 이유가 **권한**임을 흐리지 않는다.
TOKEN_PAGE = "/login"

ROLES = tuple(rbac.roles())
MATRIX = [(role, screen) for role in ROLES for screen in nav.all_screens()]


def _id(v) -> str:
    return v if isinstance(v, str) else v.no


# ── 권한표 자체 (TD3 role_matrix 정본) ───────────────────────────────────
def test_역할_6개_권한영역_8개다():
    assert len(rbac.roles()) == 6, f"역할 {len(rbac.roles())} ≠ 6"
    assert len(rbac.PERM_AREA_TO_AREAS) == 8
    cols = design.role_matrix()["columns"][1:]
    assert list(cols) == list(rbac.PERM_AREA_TO_AREAS), "권한영역이 정본과 다르다"
    # 8권한영역이 10업무영역을 빠짐없이 덮는가
    covered = {a for areas in rbac.PERM_AREA_TO_AREAS.values() for a in areas}
    assert covered == {s.area for s in nav.all_screens()}, f"덮이지 않는 업무영역: {covered}"


def test_역할_라벨에_실명이_없다():
    """G-29 — TD3 원문에는 실명이 있다. UI 라벨에는 없어야 한다."""
    for role in rbac.roles().values():
        assert "(" not in role.name and ")" not in role.name, f"{role.code}: {role.name}"


def test_현장작업자는_수주견적AI관리가_대시다():
    """screen-map §5 — 현장 작업자 행의 수주견적AI관리 칸은 `-` 다."""
    perm = rbac.perm_for("OPERATOR", "수주견적AI관리")
    assert perm.none and perm.label == "-", f"권한표가 바뀌었다: {perm}"


# ── 6역할 × 45화면 전수 (270건) ─────────────────────────────────────────
@pytest.mark.parametrize("role,screen", MATRIX, ids=lambda v: _id(v))
def test_역할별_화면_응답이_권한표와_같다(role, screen):
    want = 200 if rbac.can_read(role, screen.area) else 403
    r = client.get(screen.path, params={"as": role})
    assert r.status_code == want, (
        f"{role} → {screen.path}({screen.area}): {r.status_code}, 권한표는 {want}")
    if want == 403:
        assert "접근 권한이 없습니다" in r.text, "403 문구가 §2.5 계약과 다르다"


@pytest.mark.parametrize("role", ROLES)
def test_권한없는_영역은_좌측메뉴에도_안_보인다(role):
    page = client.get("/", params={"as": role}).text
    wrong = []
    for s in nav.all_screens():
        visible = f'href="{s.path}"' in page
        if visible != rbac.can_read(role, s.area):
            wrong.append((s.path, s.area, "보임" if visible else "안보임"))
    assert not wrong, f"{role}: 메뉴 노출이 권한표와 다르다 — {wrong}"


def test_현장작업자에게_견적AI_6화면이_전부_403이다():
    """프롬프트 지정 케이스 — `/est/010~015` 전부 403."""
    est = [s for s in nav.all_screens() if s.area == "수주견적AI관리"]
    assert len(est) == 6, f"수주견적AI관리 화면 {len(est)} ≠ 6"
    got = {s.path: client.get(s.path, params={"as": "OPERATOR"}).status_code for s in est}
    assert set(got.values()) == {403}, f"현장 작업자에게 견적AI 가 열렸다: {got}"
    page = client.get("/", params={"as": "OPERATOR"}).text
    assert "견적AI" not in page, "권한 없는 메뉴 그룹이 좌측에 보인다"


def test_권한표_270칸_전수_실측을_남긴다():
    """게이트 숫자를 사람이 다시 셀 수 있게 실측을 남긴다."""
    allow = sum(1 for role in ROLES for s in nav.all_screens()
                if rbac.can_read(role, s.area))
    deny = 6 * 45 - allow
    assert (allow, deny) == (252, 18), f"권한표 실측이 바뀌었다: 허용 {allow} · 거부 {deny}"
    # 거부 18 = 사용자/시스템관리 4화면 × 3역할(품질·생산관리·현장) + 수주견적AI관리 6화면 × 현장 작업자


# ── 등록·수정(W) · 승인(A) ──────────────────────────────────────────────
# (경로, 업무영역, 필요 권한, 계약을 통과하는 최소 폼) — 폼이 부족하면 FastAPI 가 먼저 422 를 낸다.
WRITE_CASES = (
    ("/inv/005", "입고재고관리", "write", {}),
    ("/bas/030", "기준정보관리", "write", {"qstd_code": "QA1-NOPE", "product_group": "PG10",
                                     "inspect_type": "수압시험", "inspect_item": "압력"}),
    ("/bas/032", "기준정보관리", "write", {}),
    ("/sys/026", "사용자/시스템관리", "write", {}),
    # `action=run` 은 **실제로 ETL 을 돌려 DAT_JOB_LOGS 를 쌓는다**. 권한만 보는 테스트가
    # 남의 표를 늘리면 안 된다(§10-17) — 정의되지 않은 동작으로 권한 분기만 지난다.
    ("/dat/033", "데이터관리", "write", {"action": "QA1-정의되지않은동작"}),
    ("/prc/021", "공정관리", "write", {"work_order_id": "999999", "process_code": "P10",
                                   "start_dt": "2026-09-01 08:00", "good_qty": "1"}),
    ("/shp/016", "출하물류관리", "write", {"lot_trace_id": "999999"}),
)
APPROVE_CASES = (
    ("/shp/016/approve", "출하물류관리", {"shipment_id": "999999"}),
    ("/est/012/confirm", "수주견적AI관리", {"quote_id": "999999"}),
    ("/est/013/confirm", "수주견적AI관리", {"bom_id": "999999"}),
    ("/api/agent/recommend/999999/adopt", "AI Agent 통합관리", {"decision": "승인"}),
)


@pytest.mark.parametrize("path,area,_kind,form", WRITE_CASES, ids=lambda v: str(v)[:24])
def test_등록권한_없는_역할은_403이다(path, area, _kind, form):
    for role in ROLES:
        r = csrf_post(client, path, form, page=TOKEN_PAGE, params={"as": role})
        if rbac.can_write(role, area):
            assert r.status_code != 403, f"{role} 은 {area} 등록 권한이 있는데 {path} 가 403 이다"
        else:
            assert r.status_code == 403, (
                f"{role}({area} W 없음) 가 {path} 에서 {r.status_code} 를 받았다 — 403 이어야 한다")


@pytest.mark.parametrize("path,area,form", APPROVE_CASES, ids=lambda v: str(v)[:24])
def test_승인권한_없는_역할은_403이다(path, area, form):
    """G-24 — 승인 없이 확정되면 결함이다. 승인 권한 없는 역할은 403."""
    for role in ROLES:
        r = csrf_post(client, path, form, page=TOKEN_PAGE, params={"as": role})
        if rbac.can_approve(role, area):
            assert r.status_code != 403, f"{role} 은 {area} 승인 권한이 있는데 {path} 가 403 이다"
        else:
            assert r.status_code == 403, (
                f"{role}({area} A 없음) 가 {path} 에서 {r.status_code} 를 받았다 — 403 이어야 한다")


def test_승인권한은_6역할중_정해진_역할만_가진다():
    approvers = {area: sorted(r for r in ROLES if rbac.can_approve(r, area))
                 for area in ("수주견적AI관리", "출하물류관리", "공정관리")}
    assert approvers == {
        "수주견적AI관리": ["EXEC", "SYSADMIN"],
        "출하물류관리": ["EXEC", "SYSADMIN"],
        "공정관리": ["SYSADMIN"],
    }, f"승인 역할이 바뀌었다: {approvers}"


# ── 개발용 역할 전환이 prod 에서 막히는가 (D-40 · D-51) ──────────────────
def test_prod에서는_as파라미터가_안_먹는다():
    old = {k: os.environ.get(k) for k in ("KYUNGDONG_ENV", "KYUNGDONG_SESSION_SECRET")}
    os.environ["KYUNGDONG_ENV"] = "prod"
    os.environ["KYUNGDONG_SESSION_SECRET"] = "q" * 32
    settings.cache_clear()
    try:
        codes = {s.path: client.get(s.path, params={"as": "SYSADMIN"}).status_code
                 for s in nav.all_screens()[:5]}
        assert set(codes.values()) == {403}, f"prod 인데 쿼리 한 줄로 화면이 열렸다: {codes}"
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        settings.cache_clear()


def test_모르는_역할은_열어주지_않는다():
    """`rbac.perm_for` 는 모르는 역할을 권한 없음으로 본다 — 열어주지 않는다.

    빈 값(`?as=`)은 예외다. dev 기본 역할이 SYSADMIN 이기 때문이다(D-40) — 그래서
    `test_prod에서는_as파라미터가_안_먹는다` 가 같이 서 있어야 한다.
    """
    for bogus in ("ADMIN", "ROOT", "SYSADMIN2", "operator "):
        assert rbac.perm_for(bogus, "사용자/시스템관리").none
        r = client.get("/sys/026", params={"as": bogus})
        assert r.status_code == 403, f"as={bogus!r} 로 사용자 관리가 열렸다"
    assert client.get("/sys/026", params={"as": ""}).status_code == 200, \
        "dev 기본 역할(SYSADMIN)이 바뀌었다 — D-40 분기를 확인하라"
