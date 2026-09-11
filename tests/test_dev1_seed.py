"""개발1 시드 검증 — G-07 멱등 · §10-3 시간 앵커 · G-11 런타임 전용 표 · D-47 빈 코드그룹.

**0건 경로와 N건 경로를 둘 다 단언한다**(§10-4). `skip` 하지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
import seed_dev1                                         # noqa: E402
from kyungdong.app.util import clock                     # noqa: E402

SEED = ROOT / "db" / "seed_dev1.py"

# 개발1 시드가 만지는 표
COUNTED = ("BAS_COMMON_CODES", "SYS_CONFIGS", "DAT_SOURCES", "DAT_INTEGRATION_JOBS")


def _run() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SEED)], capture_output=True, text=True, cwd=ROOT)


def _counts() -> dict[str, int]:
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in COUNTED}


@pytest.fixture(scope="module", autouse=True)
def seeded():
    r = _run()
    assert r.returncode == 0, r.stderr[-800:]


def test_G07_개발1_시드가_멱등이다():
    before = _counts()
    r = _run()
    assert r.returncode == 0, r.stderr[-800:]
    assert _counts() == before, "두 번 돌렸더니 행 수가 변했다 (G-07)"


def test_시간앵커를_쓰고_흔들지_않는다():
    """§10-3 — 시드가 `date.today()` 를 쓰면 앵커가 움직인다."""
    a1 = clock.anchor()
    assert _run().returncode == 0
    assert clock.anchor() == a1


def test_시드_소스에_date_today_호출이_없다():
    """문서에서 '금지' 라고 적는 것과 실제로 부르는 것은 다르다 — **AST 로 호출을 본다.**"""
    import ast
    tree = ast.parse(SEED.read_text())
    banned = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("today", "now", "utcnow")
    ]
    assert not banned, f"시드가 현재 시각을 부른다 (§10-3): {[n.func.attr for n in banned]}"
    assert "clock.anchor()" in SEED.read_text()


# ── 채번 공표 (progress-dev1.md §1) ───────────────────────────────────────
def test_채번규칙_7건이_LOT채번_그룹에_있다():
    rows = conn.q("select CODE_VALUE, ATTR1, ATTR2 from BAS_COMMON_CODES "
                  "where CODE_GROUP = 'LOT채번' order by SORT_ORDER")
    assert len(rows) == 7, rows
    got = {r["code_value"]: r["attr1"] for r in rows}
    assert got == {
        "PROJECT_NO": "PJ-YYYY-NNN",
        "DRAWING_NO": "DWG-{제품군3}-NNNN",
        "MATERIAL_LOT_NO": "LOT-YYMMDD-NN",
        "RECEIPT_NO": "RC-YYYY-NNNN",
        "WORK_ORDER_NO": "WO-YYYY-NNNN",
        "PRODUCT_LOT_NO": "PLOT-YYYY-NNN",
        "SHIPMENT_NO": "SH-YYYY-NNNN",
    }
    assert all(r["attr2"] for r in rows), "적용 컬럼이 비어 있으면 개발2·3 이 쓸 수 없다"


def test_제품군_약어가_5종_전부_붙었다():
    """도면번호 채번 `DWG-{제품군3}-NNNN` 이 쓰는 값. **코드 행은 늘리지 않는다.**"""
    rows = conn.q("select CODE_VALUE, ATTR2 from BAS_COMMON_CODES "
                  "where CODE_GROUP = '제품군' order by SORT_ORDER")
    assert len(rows) == 5, "제품군은 ETO 5종이다 — 시드가 행을 늘리면 안 된다"
    assert {r["code_value"]: r["attr2"] for r in rows} == seed_dev1.PRODUCT_ABBR


# ── 정본에 값이 있는 것만 넣었는지 ────────────────────────────────────────
def test_인터페이스설정은_EIF_4종이다():
    rows = conn.q("select CONFIG_KEY, CONFIG_VALUE, ALERT_CONDITION from SYS_CONFIGS "
                  "where CONFIG_TYPE = '인터페이스설정' order by CONFIG_KEY")
    assert {r["config_key"] for r in rows} == {"IF_ERP", "IF_IOT_PLC", "IF_CAD_FILE", "IF_EXT_DOC"}
    # 접속 주소·계정은 정본에 없다 → 값을 넣지 않는다
    assert all(r["config_value"] is None for r in rows), "정본에 없는 접속 정보를 시드가 지어냈다"
    assert {r["alert_condition"] for r in rows} == {
        "MES-TD4-046", "MES-TD4-047", "MES-TD4-048", "MES-TD4-049"}


def test_알림기준은_3종이고_임계값이_비어있다():
    rows = conn.q("select CONFIG_KEY, CONFIG_VALUE, TARGET_ROLE_CODE, ALERT_CHANNEL "
                  "from SYS_CONFIGS where CONFIG_TYPE = '알림기준'")
    assert {r["config_key"] for r in rows} == {"ALERT_EQUIP", "ALERT_DUE", "ALERT_QUALITY"}
    assert all(r["config_value"] is None for r in rows), "임계값 수치는 정본에 없다 (D-109)"
    assert all(r["target_role_code"] and r["alert_channel"] for r in rows)


def test_수집대상은_5종이고_수집주기가_비어있다():
    """수집 지점은 레이저커팅기 PLC·현장POP 2개소뿐이다 (D-06)."""
    rows = conn.q("select SOURCE_NAME, DATA_TYPE, COLLECT_CYCLE, CONNECTION_INFO, INTERFACE_CODE "
                  "from DAT_SOURCES order by SOURCE_ID")
    assert len(rows) == 5
    names = {r["source_name"] for r in rows}
    assert {"레이저커팅기 PLC", "현장POP(터치PC)"} <= names
    assert all(r["collect_cycle"] is None for r in rows), "수집 주기는 사업계획서에 없다 (D-06)"
    assert all(r["connection_info"] is None for r in rows), "접속 정보는 암호화 저장 대상이다"
    assert {r["data_type"] for r in rows} <= {"정형", "시계열", "비정형"}


def test_통합작업은_수집대상당_1건이다():
    n_src = int(conn.q1("select count(*) as n from DAT_SOURCES")["n"])
    rows = conn.q("select JOB_TYPE, TARGET_STORE, SCHEDULE_EXPR, TRANSFORM_RULE "
                  "from DAT_INTEGRATION_JOBS")
    assert len(rows) == n_src
    assert all(r["schedule_expr"] is None for r in rows), "Cron 표현식은 정본에 없다"
    assert all(r["transform_rule"] is None for r in rows), "변환 규칙은 정본에 없다"


# ── 지어내지 않았는지 (0건 경로) ──────────────────────────────────────────
def test_D47_빈_코드그룹을_개발1_시드가_채우지_않았다():
    """품목·재질·고객사·보관위치·불량유형·클레임유형·원가대상은 화면 입력 마스터다."""
    for group in ("품목", "재질", "고객사", "보관위치", "불량유형", "클레임유형", "원가대상"):
        n = int(conn.q1("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = %s",
                        (group,))["n"])
        assert n == 0, f"정본에 값이 없는 그룹 '{group}' 을 개발1 시드가 채웠다 (D-47)"


def test_G11_런타임_전용표는_시드가_건드리지_않는다():
    """`make db-reset` 직후 0건이 정상이다. **시드 실행이 행을 만들면 안 된다.**"""
    for table in ("DAT_JOB_LOGS", "DAT_DOWNLOAD_LOGS", "IF_ERP_RECEIPTS",
                  "IF_ERP_SHIPMENTS", "IF_ERP_STOCKS"):
        before = int(conn.q1(f"select count(*) as n from {table}")["n"])
        assert _run().returncode == 0
        after = int(conn.q1(f"select count(*) as n from {table}")["n"])
        assert after == before, f"{table} 은 런타임 전용인데 시드가 건드렸다 (G-11)"


def test_시드하지_않은_표마다_근거가_적혀있다():
    """숫자만 적고 근거를 빼지 않는다 — 근거 없는 0건은 결함과 구분되지 않는다."""
    assert len(seed_dev1.NOT_SEEDED) >= 15
    for table, why in seed_dev1.NOT_SEEDED:
        assert why.strip(), f"{table} 의 미시드 근거가 비어 있다"
        assert len(why) > 20, f"{table} 의 근거가 너무 짧다: {why!r}"


def test_개발1_판정_2건이_적혀있다():
    """db-schema §7.1 '시드 여부 미정' 중 개발1 몫 — 판정을 남겨야 한다."""
    decided = dict(seed_dev1.NOT_SEEDED)
    assert "판정" in decided["INV_MATERIAL_HISTORY"]
    assert "판정" in decided["INV_SUPPLIER_QUALITY"]


def test_시드가_공통시드_영역을_다시_넣지_않는다():
    """공통 시드(db/seed.py)의 6그룹·계정·역할권한을 개발1 이 다시 쓰지 않는다."""
    src = SEED.read_text()
    for table in ("SYS_USERS", "SYS_ROLE_PERMISSIONS"):
        assert f"insert into {table}" not in src, f"{table} 은 공통 시드 몫이다"
    # 공통 6그룹은 개발1 이 다시 넣지 않는다 — 개발1 이 새로 만드는 그룹은 'LOT채번' 뿐이다.
    groups = {r["code_group"] for r in conn.q(
        "select distinct CODE_GROUP from BAS_COMMON_CODES")}
    assert groups == {"공정", "제품군", "검사구분", "공급구분", "외주구간", "설비", "LOT채번"}, groups
    assert seed_dev1.seed_numbering.__doc__ and "LOT채번" in seed_dev1.seed_numbering.__doc__
