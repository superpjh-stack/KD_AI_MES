"""개발1 쓰기 경로 — 입고 흐름 · 코드 검증(D-32) · Excel 적재(D-07) · 반출 통제(9.2 ①).

시드는 `INV_*` 를 0건으로 둔다(품목·재질 코드 그룹이 D-47 로 비어 있어 유효한 LOT 을 만들 수 없다).
**N건 경로는 이 테스트가 실제 쓰기로 만든다** — 코드 등록 → 입고 등록 → 재고·이력 → 검증 → 평가.
테스트가 만든 행은 전부 되돌린다(PK 워터마크) — 남기면 `test_arch_seed` 의 '빈 코드그룹' 단언이 깨진다.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.main import app                       # noqa: E402
from kyungdong.app.util import clock                     # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

ITEM, MATERIAL = "TEST-ITEM-01", "TEST-MAT-01"
SUPPLIER_CODE = "TEST-SUP-01"

# (표, PK) — FK 순서대로. 되돌릴 때 이 순서로 지운다.
TRACKED: tuple[tuple[str, str], ...] = (
    ("INV_MATERIAL_HISTORY", "HIST_ID"),
    ("INV_STOCKS", "STOCK_ID"),
    ("INV_RECEIPTS", "RECEIPT_ID"),
    ("INV_SUPPLIER_QUALITY", "SQ_ID"),
    ("INV_MATERIAL_LOTS", "LOT_ID"),
    ("INV_SUPPLIERS", "SUPPLIER_ID"),
    ("IF_ERP_RECEIPTS", "IF_ID"),
    ("DAT_JOB_LOGS", "JOB_LOG_ID"),
    ("DAT_QUALITY_CHECKS", "CHECK_ID"),
    ("DAT_DOWNLOAD_LOGS", "DOWNLOAD_ID"),
    ("SYS_ACCESS_LOGS", "LOG_ID"),
    ("BAS_QUALITY_STANDARDS", "QSTD_ID"),
    ("BAS_WORK_STANDARDS", "WSTD_ID"),
    ("BAS_COMMON_CODES", "CODE_ID"),
    ("SYS_CONFIGS", "CONFIG_ID"),
    ("SYS_USERS", "USER_ID"),
)


def post(path: str, data: dict, role: str = "SYSADMIN", **kw):
    return client.post(path, data=data, headers={"x-kyungdong-role": role}, **kw)


def get(path: str, role: str = "SYSADMIN"):
    return client.get(path, headers={"x-kyungdong-role": role})


@pytest.fixture(scope="module", autouse=True)
def rollback_after():
    """테스트가 만든 행만 되돌린다 — 시드가 넣은 행은 건드리지 않는다."""
    marks = {t: int(conn.q1(f"select coalesce(max({pk}), 0) as m from {t}")["m"])
             for t, pk in TRACKED}
    yield marks
    for table, pk in TRACKED:
        conn.x(f"delete from {table} where {pk} > %s", (marks[table],))
    # 되돌림 확인 — 빈 코드그룹이 다시 비었는지 (D-47)
    for group in ("품목", "재질"):
        n = int(conn.q1("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = %s",
                        (group,))["n"])
        assert n == 0, f"테스트가 그룹 '{group}' 을 남겼다 — D-47 단언이 깨진다"


@pytest.fixture(scope="module")
def codes_registered(rollback_after):
    """032 코드관리로 품목·재질 코드를 등록한다 — 입고의 선행 조건이다(D-47 → 화면 입력)."""
    for group, value, name in (("품목", ITEM, "테스트 품목"), ("재질", MATERIAL, "테스트 재질")):
        r = post("/bas/032", {"code_group": group, "code_value": value,
                              "code_name": name, "sort_order": "10"})
        assert r.status_code == 200, r.text[:300]
    return ITEM, MATERIAL


@pytest.fixture(scope="module")
def supplier(rollback_after):
    """공급처 마스터 등록 화면이 45화면에 없다(D-101) → 테스트가 직접 넣는다."""
    row = conn.q1(
        "insert into INV_SUPPLIERS (SUPPLIER_CODE, SUPPLIER_NAME, SUPPLY_TYPE, CONTACT_NAME, "
        " CONTACT_PHONE, RISK_YN, USE_YN, CREATED_DT) "
        "values (%s, %s, 'ST10', %s, %s, 'N', 'Y', now()) returning SUPPLIER_ID",
        (SUPPLIER_CODE, "테스트 공급처", "자재담당", "02-0000-1234"))
    return int(row["supplier_id"])


# ═══════════════════════════════════════════════════════════════════════
# 032 코드관리 — 중복 검증 (SF-TD3-032 체크: "코드는 중복될 수 없다")
# ═══════════════════════════════════════════════════════════════════════
def test_코드_등록_후_그리드에_보인다(codes_registered):
    html = get("/bas/032?grp=품목").text
    assert ITEM in html and "테스트 품목" in html


def test_같은_그룹_같은_코드는_422다(codes_registered):
    r = post("/bas/032", {"code_group": "품목", "code_value": ITEM, "code_name": "중복"})
    assert r.status_code == 422, r.status_code
    assert "중복" in r.text


def test_없는_상위코드는_422다(codes_registered):
    r = post("/bas/032", {"code_group": "품목", "code_value": "TEST-ITEM-99",
                          "code_name": "x", "parent_code": "없는코드zzz"})
    assert r.status_code == 422


def test_필수값_누락은_422다():
    assert post("/bas/032", {"code_group": "품목", "code_value": ""}).status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# D-32 — 코드성 FK 는 DB 가 막지 않는다. 애플리케이션이 422 로 막는다.
# ═══════════════════════════════════════════════════════════════════════
def test_공통코드에_없는_품목코드_입고는_422다(supplier):
    r = post("/inv/005", {"supplier_id": str(supplier), "item_code": "없는품목zzz",
                          "receipt_qty": "10"})
    assert r.status_code == 422, r.status_code
    assert "D-32" in r.text


def test_공통코드에_없는_재질은_422다(supplier, codes_registered):
    r = post("/inv/005", {"supplier_id": str(supplier), "item_code": ITEM,
                          "material": "없는재질zzz", "receipt_qty": "10"})
    assert r.status_code == 422
    assert "D-32" in r.text


def test_품질기준_상하한_역전은_422다():
    r = post("/bas/030", {"qstd_code": "TEST-QS-01", "product_group": "PG10",
                          "inspect_type": "IT10", "inspect_item": "수압시험",
                          "spec_min": "12", "spec_max": "9", "apply_from": "2026-01-01"})
    assert r.status_code == 422
    assert "역전" in r.text


def test_품질기준_제품군이_코드에_없으면_422다():
    r = post("/bas/030", {"qstd_code": "TEST-QS-02", "product_group": "없는제품군",
                          "inspect_type": "IT10", "inspect_item": "수압시험",
                          "apply_from": "2026-01-01"})
    assert r.status_code == 422


def test_작업표준_공정코드가_10단계_밖이면_422다():
    r = post("/bas/031", {"wstd_code": "TEST-WS-01", "process_code": "P99",
                          "wstd_name": "x", "std_version": "v1.0"})
    assert r.status_code == 422
    assert "D-32" in r.text


# ═══════════════════════════════════════════════════════════════════════
# 005 입고관리 — 채번 · 재고 반영 · 이력 적재 (N건 경로)
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def receipt(supplier, codes_registered):
    r = post("/inv/005", {"supplier_id": str(supplier), "item_code": ITEM,
                          "material": MATERIAL, "thickness_mm": "6", "receipt_qty": "12",
                          "weight_kg": "480", "mtc_no": "TEST-MTC-0001",
                          "inspect_result": "합격", "input_device": "스마트패드"})
    assert r.status_code == 200, r.text[:400]
    return conn.q1("select r.RECEIPT_NO, r.LOT_ID, l.LOT_NO from INV_RECEIPTS r "
                   "join INV_MATERIAL_LOTS l on l.LOT_ID = r.LOT_ID "
                   "order by r.RECEIPT_ID desc limit 1")


def test_채번이_공표한_형식을_따른다(receipt):
    """`progress-dev1.md` §1 공표 — 개발2·3 이 그대로 쓴다."""
    assert re.fullmatch(r"RC-\d{4}-\d{4}", receipt["receipt_no"]), receipt["receipt_no"]
    assert re.fullmatch(r"LOT-\d{6}-\d{2}", receipt["lot_no"]), receipt["lot_no"]


def test_입고일시가_앵커에_고정된다(receipt):
    """입고일시를 비우면 `datetime.now()` 가 아니라 시간 앵커를 쓴다 (§10-3)."""
    row = conn.q1("select RECEIPT_DT from INV_RECEIPTS where RECEIPT_NO = %s",
                  (receipt["receipt_no"],))
    assert row["receipt_dt"] == clock.anchor()


def test_입고가_재고에_반영된다(receipt):
    s = conn.q1("select STOCK_QTY, AVAILABLE_QTY from INV_STOCKS where LOT_ID = %s",
                (receipt["lot_id"],))
    assert s and float(s["stock_qty"]) == 12.0
    assert float(s["available_qty"]) == 12.0, "합격 LOT 은 가용 수량에 들어간다"


def test_입고가_원자재_이력을_남긴다(receipt):
    """D-102 판정 — `INV_MATERIAL_HISTORY` 는 런타임 누적표다."""
    h = conn.q1("select HIST_TYPE, EVENT_QTY, PROCESS_CODE from INV_MATERIAL_HISTORY "
                "where LOT_ID = %s", (receipt["lot_id"],))
    assert h and h["hist_type"] == "입고"
    assert h["process_code"] == "P20", "입고검사 공정이어야 한다"


def test_보류_LOT_은_가용수량에_들어가지_않는다(supplier, codes_registered):
    r = post("/inv/005", {"supplier_id": str(supplier), "item_code": ITEM,
                          "receipt_qty": "5", "inspect_result": "보류"})
    assert r.status_code == 200
    row = conn.q1("select s.STOCK_QTY, s.AVAILABLE_QTY from INV_STOCKS s "
                  "join INV_RECEIPTS r on r.LOT_ID = s.LOT_ID "
                  "order by r.RECEIPT_ID desc limit 1")
    assert float(row["stock_qty"]) == 5.0 and float(row["available_qty"]) == 0.0


def test_수량이_0이하면_422다(supplier, codes_registered):
    r = post("/inv/005", {"supplier_id": str(supplier), "item_code": ITEM, "receipt_qty": "0"})
    assert r.status_code == 422


def test_없는_공급처는_422다(codes_registered):
    r = post("/inv/005", {"supplier_id": "99999999", "item_code": ITEM, "receipt_qty": "1"})
    assert r.status_code == 422


def test_005_N건_경로가_그리드에_보인다(receipt):
    html = get("/inv/005").text
    assert receipt["receipt_no"] in html
    assert receipt["lot_no"] in html
    assert "미수집" not in html.split("<h2>입고")[1].split("</table>")[0]


def test_006_이력_그리드에_N건이_보인다(receipt):
    html = get(f"/inv/006?lot={receipt['lot_no']}").text
    assert receipt["lot_no"] in html
    assert "/prc/024" in html, "LOT 을 누르면 024 공정이력조회로 가야 한다 (G-08)"


def test_006_0건_필터는_미수집을_낸다(receipt):
    html = get("/inv/006?lot=없는LOTzzz").text
    assert "미수집" in html


# ═══════════════════════════════════════════════════════════════════════
# 007 Excel 적재 — D-07 정식 입력 경로
# ═══════════════════════════════════════════════════════════════════════
def _xlsx(rows: list[list[object]]) -> bytes:
    from openpyxl import Workbook
    from kyungdong.app.routers.inv import EXCEL_COLUMNS
    wb = Workbook()
    ws = wb.active
    ws.append(list(EXCEL_COLUMNS))
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_헤더가_다른_엑셀은_422다():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["엉뚱한", "헤더"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/inv/007", headers={"x-kyungdong-role": "SYSADMIN"},
                    data={"action": "upload"},
                    files={"file": ("x.xlsx", buf.getvalue())})
    assert r.status_code == 422
    assert "헤더" in r.text


def test_엑셀_적재가_성공행과_실패행을_모두_기록한다(codes_registered):
    a = clock.anchor()
    raw = _xlsx([
        ["ERP-T-001", ITEM, MATERIAL, 6, SUPPLIER_CODE, "테스트 공급처", 7, 280,
         "TEST-MTC-0002", a, "합격"],
        ["ERP-T-002", "없는품목zzz", None, None, SUPPLIER_CODE, "테스트 공급처", 3, None,
         None, a, "불합격"],
    ])
    r = client.post("/inv/007", headers={"x-kyungdong-role": "SYSADMIN"},
                    data={"action": "upload"}, files={"file": ("in.xlsx", raw)})
    assert r.status_code == 200, r.text[:400]

    ok = conn.q1("select count(*) as n from IF_ERP_RECEIPTS "
                 "where ERP_DOC_NO = 'ERP-T-001' and IF_STATUS = '성공'")
    bad = conn.q1("select ERROR_MSG from IF_ERP_RECEIPTS "
                  "where ERP_DOC_NO = 'ERP-T-002' and IF_STATUS = '실패'")
    assert int(ok["n"]) == 1, "정상 행이 적재되지 않았다"
    assert bad and "D-32" in bad["error_msg"], "실패 사유를 남기지 않았다 (G-30)"
    # 실패 행은 업무 데이터로 들어가면 안 된다
    assert conn.q1("select count(*) as n from INV_MATERIAL_LOTS "
                   "where ITEM_CODE = '없는품목zzz'")["n"] == 0


def test_적재가_정합성_검증을_실측으로_기록한다():
    rows = conn.q("select CHECK_AXIS, TOTAL_CNT, VALID_CNT, ACHIEVE_RATE, JUDGE_RESULT "
                  "from DAT_QUALITY_CHECKS order by CHECK_ID desc limit 2")
    assert len(rows) == 2, "정확성·연계성 두 축을 기록해야 한다"
    assert {r["check_axis"] for r in rows} == {"정확성", "연계성"}
    for r in rows:
        if r["total_cnt"]:
            expected = round(int(r["valid_cnt"]) / int(r["total_cnt"]) * 100, 3)
            assert float(r["achieve_rate"]) == pytest.approx(expected)
            assert r["judge_result"] == ("충족" if expected >= 85 else "미충족")


def test_007_그리드에_적재결과가_보인다():
    html = get("/inv/007").text
    assert "ERP-T-001" in html
    assert "D-07" in html, "ERP 상충을 화면에 드러내야 한다"


def test_ERP_재전송은_보낸_척하지_않는다():
    before = int(conn.q1("select count(*) as n from IF_ERP_RECEIPTS where IF_STATUS='대기'")["n"])
    assert post("/inv/007", {"action": "resend"}).status_code == 200
    rows = conn.q("select ERROR_MSG from IF_ERP_RECEIPTS where IF_STATUS='대기'")
    assert len(rows) > before
    assert all("D-07" in r["error_msg"] for r in rows), "실 연동 범위 밖임을 남겨야 한다"


# ═══════════════════════════════════════════════════════════════════════
# 008 공급처 품질분석 — 누적 집계 (D-103 판정)
# ═══════════════════════════════════════════════════════════════════════
def test_평가산출이_불량률만_실측하고_나머지는_비운다(supplier):
    assert post("/inv/008", {"action": "evaluate"}).status_code == 200
    row = conn.q1("select DELIVERY_CNT, REJECT_CNT, DEFECT_RATE, QUALITY_DEVIATION, "
                  "OTD_RATE, TOTAL_SCORE, GRADE from INV_SUPPLIER_QUALITY "
                  "where SUPPLIER_ID = %s", (supplier,))
    assert row, "평가 행이 만들어지지 않았다"
    delivered, rejected = int(row["delivery_cnt"]), int(row["reject_cnt"])
    assert delivered > 0
    assert float(row["defect_rate"]) == pytest.approx(round(rejected / delivered * 100, 3))
    # 산식이 정본에 없는 값은 지어내지 않는다 (D-107)
    for col in ("quality_deviation", "otd_rate", "total_score", "grade"):
        assert row[col] is None, f"{col} 은 산식이 정본에 없다 — 지어내면 안 된다 (D-107)"


def test_008_그리드가_N건이_되고_미확정이_함께_보인다(supplier):
    html = get("/inv/008").text
    assert "테스트 공급처" in html
    assert "미확정" in html, "납기 준수율·등급은 미확정으로 표기해야 한다 (D-107)"
    assert "자*****" in html or "자***" in html, "담당자명이 마스킹돼야 한다 (G-29)"


def test_평가산출은_두_번_돌려도_행이_늘지_않는다(supplier):
    before = int(conn.q1("select count(*) as n from INV_SUPPLIER_QUALITY")["n"])
    assert post("/inv/008", {"action": "evaluate"}).status_code == 200
    assert int(conn.q1("select count(*) as n from INV_SUPPLIER_QUALITY")["n"]) == before


# ═══════════════════════════════════════════════════════════════════════
# 033 즉시 실행 — 못 하는 것은 실패로 기록한다 (G-30)
# ═══════════════════════════════════════════════════════════════════════
def test_즉시실행이_수집불가_사유를_남긴다():
    assert post("/dat/033", {"action": "run"}).status_code == 200
    rows = conn.q("select g.RESULT_CODE, g.ERROR_MSG, s.SOURCE_NAME from DAT_JOB_LOGS g "
                  "join DAT_INTEGRATION_JOBS j on j.JOB_ID = g.JOB_ID "
                  "join DAT_SOURCES s on s.SOURCE_ID = j.SOURCE_ID")
    assert rows, "실행 로그가 없다"
    plc = [r for r in rows if r["source_name"] == "레이저커팅기 PLC"]
    assert plc and plc[0]["result_code"] == "실패"
    assert "D-06" in plc[0]["error_msg"], "수집 지점 2개소 제약을 밝혀야 한다"
    erp = [r for r in rows if r["source_name"] == "ERP(이카운트)"]
    assert erp and erp[0]["result_code"] in ("성공", "부분성공"), \
        "Excel 적재 실적이 있으면 실측으로 성공을 기록한다"


def test_033_실행로그_0건에서_N건으로_바뀐다():
    html = get("/dat/033").text
    assert "실행 로그" in html
    logs_block = html.split("실행 로그 (DAT_JOB_LOGS)")[1].split("</table>")[0]
    assert "미수집" not in logs_block, "행이 있는데 미수집 문구가 남았다"


# ═══════════════════════════════════════════════════════════════════════
# 036 / 027 반출 통제 (9.2 ① · G-29)
# ═══════════════════════════════════════════════════════════════════════
def test_다운로드가_이력을_남긴다():
    before = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"])
    assert post("/dat/036", {"category": "품질", "fmt": "CSV"}).status_code == 200
    assert int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"]) == before + 1
    html = get("/dat/036").text
    assert "품질" in html and "CSV" in html


def test_반출_권한이_없는_역할은_403이고_이력도_없다():
    before = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"])
    r = post("/dat/036", {"category": "견적", "fmt": "Excel"}, role="EXEC")
    assert r.status_code == 403, r.status_code
    assert int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"]) == before


def test_알_수_없는_데이터구분은_422다():
    assert post("/dat/036", {"category": "없는구분", "fmt": "CSV"}).status_code == 422


def test_로그_반출도_DAT_DOWNLOAD_LOGS에_남는다():
    before = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS "
                         "where SCREEN_ID = 'MES-TD3-027'")["n"])
    assert post("/sys/027", {"action": "download"}).status_code == 200
    assert int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS "
                       "where SCREEN_ID = 'MES-TD3-027'")["n"]) == before + 1


# ═══════════════════════════════════════════════════════════════════════
# 026 사용자 등록 — 난수 비밀번호 1회 발급 (G-29)
# ═══════════════════════════════════════════════════════════════════════
def test_사용자_등록이_난수_비밀번호를_1회만_보여준다():
    r = post("/sys/026", {"login_id": "testuser01", "user_name": "테스트사용자",
                          "dept_name": "테스트", "role_code": "OPERATOR",
                          "phone_no": "010-0000-1234", "email": "t@example.com"})
    assert r.status_code == 200, r.text[:300]
    assert "발급 비밀번호" in r.text
    # 정규식이 `[A-Za-z0-9_-]` 만 허용해 깨졌었다 — 복잡도 정책(D-16)으로 비밀번호에
    # `+`·`!` 같은 특수문자가 들어가면서 앞부분만 잡혀 해시 안에서 우연히 발견됐다.
    # **구현이 맞고 테스트가 낡은 것이다.** 공백 전까지를 통째로 잡는다.
    issued = re.search(r"발급 비밀번호 (\S+)", r.text)
    assert issued, "난수가 화면에 나오지 않았다"
    # 다시 열면 보이지 않는다
    assert "발급 비밀번호" not in get("/sys/026").text
    # 저장된 것은 해시다
    row = conn.q1("select PASSWORD_HASH from SYS_USERS where LOGIN_ID = 'testuser01'")
    assert row["password_hash"].startswith("$argon2")
    assert issued.group(1) not in row["password_hash"]


def test_계정_중복은_422다():
    r = post("/sys/026", {"login_id": "admin", "user_name": "x", "role_code": "OPERATOR"})
    assert r.status_code == 422
    assert "중복" in r.text


def test_알_수_없는_역할은_422다():
    r = post("/sys/026", {"login_id": "testuser02", "user_name": "x", "role_code": "NOPE"})
    assert r.status_code == 422


def test_시간앵커는_화면에서_바꿀_수_없다():
    """§10-3 — 앵커가 흔들리면 ML 수치가 흔들린다."""
    r = post("/sys/029", {"config_type": clock.CONFIG_TYPE, "config_key": clock.CONFIG_KEY,
                          "config_value": "2020-01-01T00:00:00"})
    assert r.status_code == 422
    assert clock.anchor().year >= 2025


def test_인터페이스_설정값은_화면에_다시_나오지_않는다():
    assert post("/sys/029", {"config_type": "인터페이스설정", "config_key": "TEST_ENDPOINT",
                             "config_value": "secret-endpoint-zzz"}).status_code == 200
    html = get("/sys/029?type=인터페이스설정").text
    assert "TEST_ENDPOINT" in html
    assert "secret-endpoint-zzz" not in html, "암호화 저장 대상 값이 화면에 나갔다"
    assert "(암호화 저장)" in html


# ═══════════════════════════════════════════════════════════════════════
# G-30 — 저장형 XSS 는 이스케이프된다 (§10-8)
# ═══════════════════════════════════════════════════════════════════════
def test_그리드_셀이_이스케이프된다():
    payload = "<script>alert(1)</script>"
    assert post("/bas/032", {"code_group": "품목", "code_value": "TEST-XSS-01",
                             "code_name": payload}).status_code == 200
    html = get("/bas/032?grp=품목").text
    assert payload not in html, "그리드 셀에 스크립트가 그대로 나갔다 (§10-8)"
    assert "&lt;script&gt;" in html
