"""개발2 **N건 경로** — 디지털 스레드가 실제로 이어지는지 데이터를 넣어 확인한다.

`db/seed_dev2.py` 는 `EST_PROJECTS`(개발3) · `BAS_QUALITY_STANDARDS`(개발1) 가 채워져야
돌아간다. 아직 0건이므로 **이 파일이 그 전제를 임시로 만들고 끝나면 지운다** — 남의 표를
영구히 건드리지 않는다. 픽스처가 끝나면 넣은 행을 전부 되돌리고 그것도 단언한다.

여기서 보는 것
  · 시드 멱등 (G-07) — 두 번 돌려 행 수 diff 0
  · 디지털 스레드 9단계가 이어지는가 (G-08)
  · KPI 가 **독립 재계산**과 일치하는가 — 대시보드 카드 = 043 = 045 = 현황판
  · 검사 합격 LOT 만 출하(422) · 출하 확정은 승인 권한(403) · 확정 시각 기록
  · 자동 수집은 레이저커팅 1공정뿐인가 (D-06)
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                      # noqa: E402
import seed_dev2                                                 # noqa: E402
from kyungdong.app import kpi                                    # noqa: E402
from kyungdong.app.util import clock                             # noqa: E402

PJ = ("PJT-DEV2TEST-001", "PJT-DEV2TEST-002")
CUSTOMER, ITEM = "CUST-DEV2TEST", "PG10"
QSTD_PREFIX = "QSTD-DEV2TEST-"
TEST_ITEMS = (("IT10", "수압시험", "bar"), ("IT20", "기밀시험", "bar"), ("IT30", "진공시험", "mmHg"))

TABLES = ("PRC_WORK_ORDERS", "PRC_PERFORMANCES", "PRC_PROCESS_HISTORIES",
          "SHP_LOT_TRACES", "SHP_INSPECTIONS", "SHP_SHIPMENTS", "SHP_SHIPMENT_ITEMS")


def _counts() -> dict[str, int]:
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in TABLES}


def _project_ids() -> list[int]:
    return [int(r["project_id"]) for r in
            conn.q("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = any(%s)", (list(PJ),))]


def _cleanup() -> None:
    pids = _project_ids()
    if pids:
        conn.x("delete from SHP_SHIPMENT_ITEMS where SHIPMENT_ID in "
               "(select SHIPMENT_ID from SHP_SHIPMENTS where PROJECT_ID = any(%s))", (pids,))
        conn.x("delete from SHP_SHIPMENTS where PROJECT_ID = any(%s)", (pids,))
        conn.x("delete from SHP_INSPECTIONS where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = any(%s))", (pids,))
        conn.x("delete from PRC_PROCESS_HISTORIES where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = any(%s))", (pids,))
        conn.x("delete from PRC_PERFORMANCES where WORK_ORDER_ID in "
               "(select WORK_ORDER_ID from PRC_WORK_ORDERS where PROJECT_ID = any(%s))", (pids,))
        conn.x("delete from SHP_LOT_TRACES where PROJECT_ID = any(%s)", (pids,))
        conn.x("delete from PRC_WORK_ORDERS where PROJECT_ID = any(%s)", (pids,))
        conn.x("delete from EST_PROJECTS where PROJECT_ID = any(%s)", (pids,))
    conn.x("delete from BAS_QUALITY_STANDARDS where QSTD_CODE like %s", (QSTD_PREFIX + "%",))
    conn.x("delete from BAS_COMMON_CODES where CODE_GROUP = '고객사' and CODE_VALUE = %s",
           (CUSTOMER,))
    conn.x("delete from BAS_COMMON_CODES where CODE_GROUP = '품목' and CODE_VALUE = %s", (ITEM,))


@pytest.fixture(scope="module")
def chain():
    """개발1·개발3 의 전제를 임시로 세우고, 끝나면 되돌린다."""
    _cleanup()
    a = clock.anchor()
    kpi_before = {int(r["measure_id"]) for r in conn.q("select MEASURE_ID from KPI_MEASURES")}

    # 코드성 FK (D-32) — 화면 입력 마스터라 D-47 로 비워 둔 그룹이다. **테스트 동안만** 채운다.
    for group, value, name in (("고객사", CUSTOMER, "테스트 고객사"), ("품목", ITEM, "반응기")):
        conn.x("insert into BAS_COMMON_CODES (CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, "
               "USE_YN, ATTR1, CREATED_DT) values (%s,%s,%s,10,'Y',%s, now()) "
               "on conflict (CODE_GROUP, CODE_VALUE) do nothing",
               (group, value, name, "tests/test_dev2_chain.py 임시 — 끝나면 지운다"))
    for n, (itype, item, uom) in enumerate(TEST_ITEMS, 1):
        conn.x("insert into BAS_QUALITY_STANDARDS (QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, "
               "INSPECT_ITEM, STANDARD_SPEC, UOM, USE_YN, APPLY_FROM, CREATED_DT) "
               "values (%s,%s,%s,%s,%s,%s,'Y',%s, now())",
               (f"{QSTD_PREFIX}{n}", ITEM, itype, item, "ASME / KS", uom, a.date()))
    for n, no in enumerate(PJ, 1):
        conn.x("insert into EST_PROJECTS (PROJECT_NO, CUSTOMER_CODE, PRODUCT_GROUP, PROJECT_NAME, "
               "ORDER_CONFIRM_DT, DUE_DT, PROJECT_STATUS, CREATED_DT) "
               "values (%s,%s,%s,%s,%s,%s,%s, now())",
               (no, CUSTOMER, ITEM, f"테스트 프로젝트 {n}", a - timedelta(hours=1400),
                (a + timedelta(days=5)).date(), "생산"))

    procs = seed_dev2.process_codes()
    qstd = seed_dev2.quality_standards()
    nums = seed_dev2.numbering()
    blocked = seed_dev2.Blocked()
    first = seed_dev2.seed_chain(a, procs, qstd, nums, blocked)
    yield {"anchor": a, "counts": _counts(), "first": first, "blocked": list(blocked),
           "procs": procs, "qstd": qstd, "nums": nums}

    new = {int(r["measure_id"]) for r in conn.q("select MEASURE_ID from KPI_MEASURES")} - kpi_before
    for mid in new:
        conn.x("delete from KPI_MEASURES where MEASURE_ID = %s", (mid,))
    _cleanup()
    assert _project_ids() == [], "픽스처가 남긴 행이 있다"


# ── 시드 (G-07) ─────────────────────────────────────────────────────────
def test_전제가_서면_사슬이_시드된다(chain):
    c = chain["counts"]
    assert c["PRC_WORK_ORDERS"] >= 14          # 프로젝트 2 × 제조공정 7
    assert c["SHP_LOT_TRACES"] >= 2
    assert c["PRC_PERFORMANCES"] >= 10         # 외주 2공정은 실적을 만들지 않는다
    assert c["PRC_PROCESS_HISTORIES"] >= 14
    assert c["SHP_INSPECTIONS"] >= 6           # LOT 당 수압·기밀·진공 3건
    assert c["SHP_SHIPMENTS"] >= 2


def test_시드는_멱등이다(chain):
    """두 번 돌려 행 수 diff 0 (G-07)."""
    before = _counts()
    seed_dev2.seed_chain(chain["anchor"], chain["procs"], chain["qstd"], chain["nums"],
                         seed_dev2.Blocked())
    assert _counts() == before


def test_자동_수집은_레이저커팅_1공정뿐이다(chain):
    """D-06 — 그 외 공정 실적의 수집 방식은 전부 수동이다."""
    rows = conn.q(
        "select distinct p.PROCESS_CODE, p.COLLECT_METHOD from PRC_PERFORMANCES p "
        "join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = p.WORK_ORDER_ID "
        "where w.PROJECT_ID = any(%s)", (_project_ids(),))
    assert rows
    auto = {r["process_code"] for r in rows if r["collect_method"] == "자동(PLC)"}
    manual = {r["collect_method"] for r in rows if r["process_code"] != "P40"}
    assert auto <= {"P40"}, f"레이저커팅 밖에 자동 수집이 붙었다: {auto - {'P40'}}"
    assert manual == {"수동(POP·패드)"}, f"수집 범위 밖 공정의 수집 방식: {manual}"


def test_외주_2공정은_실적이_없고_이력만_있다(chain):
    pids = _project_ids()
    perf = conn.q1(
        "select count(*) as n from PRC_PERFORMANCES p "
        "join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = p.WORK_ORDER_ID "
        "where w.PROJECT_ID = any(%s) and p.PROCESS_CODE in ('P30','P60')", (pids,))
    hist = conn.q1(
        "select count(*) as n from PRC_PROCESS_HISTORIES h "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "where lt.PROJECT_ID = any(%s) and h.PROCESS_CODE in ('P30','P60')", (pids,))
    assert int(perf["n"]) == 0          # 발주·반출·반입 상태 관리다 (D-41)
    assert int(hist["n"]) > 0
    steps = conn.q(
        "select distinct h.OUTSOURCE_STEP from PRC_PROCESS_HISTORIES h "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "where lt.PROJECT_ID = any(%s) and h.PROCESS_CODE in ('P30','P60')", (pids,))
    assert {s["outsource_step"] for s in steps} <= {"반출", "반입"}


def test_예시_값이_시드에_들어가지_않았다(chain):
    for table, col in (("PRC_WORK_ORDERS", "WORK_ORDER_NO"),
                       ("SHP_LOT_TRACES", "PRODUCT_LOT_NO"),
                       ("SHP_SHIPMENTS", "SHIPMENT_NO")):
        rows = conn.q(f"select {col} as v from {table}")
        assert all("예시" not in (r["v"] or "") for r in rows), table


# ── 디지털 스레드 (G-08) ────────────────────────────────────────────────
def test_사슬이_작업지시부터_출하까지_이어진다(chain):
    row = conn.q1(
        "select pj.PROJECT_NO, lt.PRODUCT_LOT_NO, w.WORK_ORDER_NO, s.SHIPMENT_NO, "
        "i.PACKING_DT, ins.JUDGE_RESULT "
        "from EST_PROJECTS pj "
        "join SHP_LOT_TRACES lt on lt.PROJECT_ID = pj.PROJECT_ID "
        "join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = lt.WORK_ORDER_ID "
        "join SHP_SHIPMENT_ITEMS i on i.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        "join SHP_SHIPMENTS s on s.SHIPMENT_ID = i.SHIPMENT_ID "
        "join SHP_INSPECTIONS ins on ins.INSPECT_ID = i.INSPECT_ID "
        "where pj.PROJECT_NO = any(%s) limit 1", (list(PJ),))
    assert row is not None, "프로젝트→LOT→작업지시→검사→출하 사슬이 끊겼다"
    assert row["judge_result"] == "합격"
    assert row["packing_dt"] is not None          # 제조 리드타임 종료 시각


def test_024_가_LOT_로_사슬_9단계를_보여_준다(chain):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    lot = conn.q1("select PRODUCT_LOT_NO from SHP_LOT_TRACES where PROJECT_ID = any(%s) limit 1",
                  (_project_ids(),))["product_lot_no"]
    body = c.get(f"/prc/024?lot={lot}").text
    assert "디지털 스레드 —" in body
    assert lot in body
    for table in ("EST_PROJECTS", "SHP_LOT_TRACES", "SHP_SHIPMENTS"):
        assert table in body
    # 개발3·개발1 이 아직 안 채운 단계는 '단절' 로 드러난다 — 지어내지 않는다
    assert "연결" in body


def test_017_LOT_열이_024_링크다(chain):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    lot = conn.q1("select PRODUCT_LOT_NO from SHP_LOT_TRACES where PROJECT_ID = any(%s) limit 1",
                  (_project_ids(),))["product_lot_no"]
    assert f'href="/prc/024?lot={lot}"' in c.get("/shp/017").text


# ── KPI 독립 재계산 ─────────────────────────────────────────────────────
def test_MFG_리드타임이_독립_재계산과_같다(chain):
    rows = kpi.samples(kpi.CODE_MFG)
    assert rows, "제조 리드타임 표본이 0건이다"
    manual = [(r["end_dt"] - r["start_dt"]).total_seconds() / 3600.0 for r in rows]
    m = kpi.measure(kpi.CODE_MFG)
    assert m.sample_cnt == len(rows)
    assert m.value == pytest.approx(round(sum(manual) / len(manual), 2), abs=0.01)
    assert m.achieve == pytest.approx(
        round((1320.0 - m.value) / (1320.0 - 1080.0) * 100.0, 1), abs=0.05)


def test_O2D_리드타임이_독립_재계산과_같다(chain):
    rows = kpi.samples(kpi.CODE_O2D)
    assert rows, "수주출하 리드타임 표본이 0건이다"
    manual = [(r["end_dt"] - r["start_dt"]).total_seconds() / 3600.0 for r in rows]
    m = kpi.measure(kpi.CODE_O2D)
    assert m.value == pytest.approx(round(sum(manual) / len(manual), 2), abs=0.01)


def test_대시보드_카드와_KPI_화면_값이_같다(chain):
    """산식이 한 곳에 있으므로 043 · 045 · 현황판이 **문자 그대로 같은 값**을 낸다."""
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    mfg, o2d = kpi.summary()
    assert mfg.collected and o2d.collected
    for path in ("/kpi/043", "/kpi/045", "/board"):
        body = c.get(path).text
        assert mfg.value_text in body, f"{path}: 제조 리드타임 실측 {mfg.value_text} 없음"
        assert o2d.value_text in body, f"{path}: 수주출하 리드타임 실측 {o2d.value_text} 없음"


def test_KPI_MEASURES_시드가_같은_산식을_쓴다(chain):
    seed_dev2.seed_kpi_measures(chain["anchor"])
    for code in kpi.OFFICIAL_CODES:
        for row in kpi.measures_in_db(code):
            m = kpi.measure(code, row["period_code"])
            assert float(row["measure_value"]) == pytest.approx(m.value, abs=0.01)
            assert int(row["sample_cnt"]) == m.sample_cnt


def test_품질_KPI_는_N건에서도_공식_지표가_아니다(chain):
    q = kpi.quality()
    assert q.inspect_cnt > 0 and q.pass_rate is not None
    assert q.official is False


# ── 출하 통제 (G-24) ────────────────────────────────────────────────────
@pytest.fixture()
def ng_lot(chain):
    """검사 **불합격** 제품 LOT — 출하 대상이 되면 안 된다."""
    pid = _project_ids()[0]
    lot_no = "PLOT-DEV2TEST-NG"
    conn.x("insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, CURRENT_PROCESS, "
           "TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) values (%s,%s,'P80','검사','Y', now()) "
           "on conflict (PRODUCT_LOT_NO) do nothing", (lot_no, pid))
    ltid = int(conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                       (lot_no,))["lot_trace_id"])
    qstd = int(conn.q1("select QSTD_ID from BAS_QUALITY_STANDARDS where QSTD_CODE like %s "
                       "order by QSTD_ID limit 1", (QSTD_PREFIX + "%",))["qstd_id"])
    conn.x("insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, JUDGE_RESULT, "
           "INSPECT_DT, CREATED_DT) values (%s,%s,'수압시험','불합격',%s, now())",
           (ltid, qstd, chain["anchor"]))
    yield ltid
    conn.x("delete from SHP_SHIPMENT_ITEMS where LOT_TRACE_ID = %s", (ltid,))
    conn.x("delete from SHP_INSPECTIONS where LOT_TRACE_ID = %s", (ltid,))
    conn.x("delete from SHP_LOT_TRACES where LOT_TRACE_ID = %s", (ltid,))


def _client(role: str):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    return TestClient(app, raise_server_exceptions=False,
                      headers={"x-kyungdong-role": role})


def test_불합격_LOT_출하_등록은_422(ng_lot):
    r = _client("PRODUCTION").post("/shp/016", data={"lot_trace_id": ng_lot})
    assert r.status_code == 422
    assert "검사 합격 LOT" in r.text


def test_검사가_아예_없는_LOT_도_출하_대상이_아니다(chain):
    pid = _project_ids()[0]
    lot_no = "PLOT-DEV2TEST-NOINSP"
    conn.x("insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, CURRENT_PROCESS, "
           "TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) values (%s,%s,'P70','생산중','Y', now()) "
           "on conflict (PRODUCT_LOT_NO) do nothing", (lot_no, pid))
    ltid = int(conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                       (lot_no,))["lot_trace_id"])
    try:
        r = _client("PRODUCTION").post("/shp/016", data={"lot_trace_id": ltid})
        assert r.status_code == 422
        assert "출하검사 결과가 없다" in r.text
    finally:
        conn.x("delete from SHP_LOT_TRACES where LOT_TRACE_ID = %s", (ltid,))


def test_승인_권한이_없으면_출하_확정은_403(chain):
    sid = conn.q1("select SHIPMENT_ID from SHP_SHIPMENTS where PROJECT_ID = any(%s) limit 1",
                  (_project_ids(),))["shipment_id"]
    r = _client("OPERATOR").post("/shp/016/approve", data={"shipment_id": int(sid)})
    assert r.status_code == 403


def test_승인하면_출하_확정_시각과_승인자가_남는다(chain):
    """확정 시각이 있어야 LEADTIME_O2D 가 나온다. 승인 이력 없는 확정은 결함이다 (G-24)."""
    pid = _project_ids()[0]
    lot_no = "PLOT-DEV2TEST-OK"
    qstd = int(conn.q1("select QSTD_ID from BAS_QUALITY_STANDARDS where QSTD_CODE like %s "
                       "order by QSTD_ID limit 1", (QSTD_PREFIX + "%",))["qstd_id"])
    conn.x("insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, CURRENT_PROCESS, "
           "TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) values (%s,%s,'P90','포장','Y', now()) "
           "on conflict (PRODUCT_LOT_NO) do nothing", (lot_no, pid))
    ltid = int(conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                       (lot_no,))["lot_trace_id"])
    conn.x("insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, JUDGE_RESULT, "
           "INSPECT_DT, CREATED_DT) values (%s,%s,'수압시험','합격',%s, now())",
           (ltid, qstd, chain["anchor"]))
    try:
        c = _client("SYSADMIN")
        r = c.post("/shp/016", data={"lot_trace_id": ltid}, follow_redirects=False)
        assert r.status_code == 303, r.text[:400]
        sid = int(conn.q1(
            "select SHIPMENT_ID from SHP_SHIPMENT_ITEMS where LOT_TRACE_ID = %s",
            (ltid,))["shipment_id"])
        pending = conn.q1("select SHIP_DT, APPROVER_ID, SHIP_STATUS from SHP_SHIPMENTS "
                          "where SHIPMENT_ID = %s", (sid,))
        assert pending["ship_dt"] is None and pending["ship_status"] == "승인대기"

        r = c.post("/shp/016/approve", data={"shipment_id": sid}, follow_redirects=False)
        assert r.status_code == 303, r.text[:400]
        done = conn.q1("select SHIP_DT, APPROVER_ID, SHIP_STATUS, OTD_YN from SHP_SHIPMENTS "
                       "where SHIPMENT_ID = %s", (sid,))
        assert done["ship_dt"] == chain["anchor"]         # 시간 앵커 기준 (§10-3)
        assert done["approver_id"] is not None            # 승인 이력
        assert done["ship_status"] == "완료"
        assert done["otd_yn"] in ("Y", "N")

        # 두 번 확정하면 422
        again = c.post("/shp/016/approve", data={"shipment_id": sid}, follow_redirects=False)
        assert again.status_code == 422
    finally:
        conn.x("delete from SHP_SHIPMENT_ITEMS where LOT_TRACE_ID = %s", (ltid,))
        conn.x("delete from SHP_SHIPMENTS where SHIPMENT_ID not in "
               "(select SHIPMENT_ID from SHP_SHIPMENT_ITEMS) and PROJECT_ID = %s", (pid,))
        conn.x("delete from SHP_INSPECTIONS where LOT_TRACE_ID = %s", (ltid,))
        conn.x("delete from SHP_LOT_TRACES where LOT_TRACE_ID = %s", (ltid,))


# ── 화면이 N건을 보여 준다 ──────────────────────────────────────────────
@pytest.mark.parametrize("path,needle", [
    ("/prc/021", "수동(POP·패드)"),
    ("/prc/024", "PLOT-"),
    ("/shp/016", "SH-"),
    ("/shp/017", "PLOT-"),
    ("/shp/018", "수압시험"),
    ("/dsh/001", "PJT-DEV2TEST"),
    ("/dsh/004", "PJT-DEV2TEST"),
])
def test_N건_경로에서_그리드가_비지_않는다(chain, path, needle):
    body = _client("SYSADMIN").get(path).text
    assert needle in body, f"{path} 에 {needle} 가 없다"
    assert '<td class="empty"' not in body or needle in body
