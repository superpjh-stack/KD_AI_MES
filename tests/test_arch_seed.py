"""공통 시드·공용 모듈 검증 (아키텍트).

G-07 시드 멱등 · §10-3 시간 앵커 · §10-11 재실행이 비밀번호를 깨지 않는다 ·
G-29 개인정보 마스킹 · D-32 코드성 FK 검증.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                  # noqa: E402
from kyungdong.app import rbac                               # noqa: E402
from kyungdong.app.util import clock, codes, mask            # noqa: E402

SEED = ROOT / "db" / "seed.py"
COUNTS = ("SYS_CONFIGS", "SYS_ROLE_PERMISSIONS", "SYS_USERS", "BAS_COMMON_CODES")


def _counts() -> dict[str, int]:
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in COUNTS}


def _run_seed() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SEED)], capture_output=True, text=True, cwd=ROOT)


@pytest.fixture(scope="module", autouse=True)
def seeded():
    r = _run_seed()
    assert r.returncode == 0, r.stderr[-600:]


def test_G07_시드가_멱등이다():
    before = _counts()
    r = _run_seed()
    assert r.returncode == 0, r.stderr[-600:]
    assert _counts() == before, "두 번 돌렸더니 행 수가 변했다 (G-07)"


def test_재실행이_비밀번호를_바꾸지_않는다():
    """직전 사업에서 동시 시드가 admin 비밀번호를 바꿔 실패 잠금이 걸렸다 (§10-11)."""
    before = conn.q1("select PASSWORD_HASH from SYS_USERS where LOGIN_ID='admin'")["password_hash"]
    assert _run_seed().returncode == 0
    after = conn.q1("select PASSWORD_HASH from SYS_USERS where LOGIN_ID='admin'")["password_hash"]
    assert before == after


def test_시간앵커가_고정이다():
    """`date.today()` 금지 (§10-3). 재실행해도 앵커가 움직이면 ML 수치가 흔들린다."""
    a1 = clock.anchor()
    assert _run_seed().returncode == 0
    assert clock.anchor() == a1


def test_역할권한이_6역할_10영역이다():
    rows = conn.q("select ROLE_CODE, count(*) as n from SYS_ROLE_PERMISSIONS group by ROLE_CODE")
    assert len(rows) == 6
    assert all(int(r["n"]) == 10 for r in rows), rows
    assert {r["role_code"] for r in rows} == set(rbac.roles())


def test_현장작업자는_견적AI_권한이_없다():
    """TD3 role_matrix 셀이 '-' 다 → DB 에도 N 이어야 한다 (G-28)."""
    row = conn.q1("select READ_YN, WRITE_YN from SYS_ROLE_PERMISSIONS "
                  "where ROLE_CODE='OPERATOR' and AREA_CODE='EST'")
    assert row and row["read_yn"] == "N" and row["write_yn"] == "N"


def test_계정에_실명이_없다():
    """G-29 · D-39 — TD3 역할명의 실명을 시드에 넣지 않는다."""
    names = [r["user_name"] for r in conn.q("select USER_NAME from SYS_USERS")]
    for banned in ("제미애", "김재윤", "주원중", "김형미"):
        assert not any(banned in n for n in names), f"시드에 실명 {banned}"


def test_비밀번호_리터럴이_저장소에_없다():
    """G-29 — 시드는 난수를 1회 출력할 뿐 저장소에 남기지 않는다."""
    txt = SEED.read_text()
    assert "token_urlsafe" in txt
    for suspicious in ("password = \"", "PASSWORD=\"", "1234", "admin123"):
        assert suspicious not in txt


def test_정본에_없는_코드그룹은_비어있다():
    """지어내지 않는다 (§0.2). 화면 입력 마스터는 시드하지 않는다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("seedmod", SEED)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for group in m.EMPTY_GROUPS:
        row = conn.q1("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP=%s", (group,))
        assert int(row["n"]) == 0, f"정본에 값이 없는 그룹 '{group}' 을 시드가 채웠다"


def test_공정은_10단계고_레이저커팅만_자동수집이다():
    rows = conn.q("select CODE_VALUE, CODE_NAME, ATTR1 from BAS_COMMON_CODES "
                  "where CODE_GROUP='공정' order by SORT_ORDER")
    assert len(rows) == 10
    assert [r["code_name"] for r in rows][3] == "가공(레이저커팅)"
    auto = [r for r in rows if "자동 수집" in (r["attr1"] or "")]
    assert len(auto) == 1, "자동 수집 공정은 레이저커팅 하나뿐이다 (D-06 수집 지점 2개소)"


def test_제품군은_ETO_5종이다():
    names = [r["code_name"] for r in conn.q(
        "select CODE_NAME from BAS_COMMON_CODES where CODE_GROUP='제품군' order by SORT_ORDER")]
    assert names == ["반응기", "교반기", "진공건조기", "누체필터", "저장탱크"]


def test_D32_코드성컬럼이_전부_그룹에_매핑됐다():
    assert codes.unmapped_columns() == [], "코드 그룹 미지정 컬럼이 있으면 검증이 차단된다"
    assert len(codes.code_columns()) == 29


def test_validate_code가_실제로_판별한다():
    assert codes.validate_code("공정", "P40") is True
    assert codes.validate_code("공정", "없는코드") is False
    assert codes.validate_code("제품군", "PG10") is True
    assert codes.validate_code("공정", None) is False
    assert codes.validate_code("공정", None, allow_empty=True) is True


def test_require_code가_422를_낸다():
    with pytest.raises(Exception) as e:
        codes.require_code("PRC_WORK_ORDERS", "PROCESS_CODE", "없는코드")
    assert getattr(e.value, "status_code", None) == 422


@pytest.mark.parametrize("raw,kind,expected", [
    ("홍길동", "name", "홍**"),
    ("010-1234-5678", "phone", "010-****-5678"),
    ("someone@example.com", "email", "so*****@example.com"),
    ("", "name", ""),
    (None, "phone", ""),
])
def test_G29_마스킹(raw, kind, expected):
    assert mask(raw, kind) == expected
