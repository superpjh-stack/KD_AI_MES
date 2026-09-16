"""PLC → MES 연계 (D-224~D-227) · 실시간 패널 (D-223) · 연속 시뮬레이터 (D-222).

**0건 경로와 N건 경로를 둘 다 단언한다**(§10-4). 이 파일이 넣은 행은 픽스처가 전부 지운다 —
`AGT_RECOMMENDATIONS`·`PRC_EQUIP_SIGNALS` 는 런타임 전용 표라 깨끗한 DB 에서 0건이 정상이다(G-11).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.util import clock, http               # noqa: E402
from kyungdong.ingest import collector, mes, tags        # noqa: E402

EQUIP = "EQ10"


@pytest.fixture(scope="module")
def device_id() -> int:
    row = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s", ("레이저커팅기 PLC",))
    assert row is not None
    return int(row["device_id"])


@pytest.fixture()
def window():
    """앵커에서 멀리 떨어진 시간 창. 끝나면 이 창의 신호·자동 실적·알림을 전부 지운다."""
    t0 = clock.anchor() + timedelta(days=4000)
    yield t0
    conn.x("delete from PRC_PERFORMANCES where COLLECT_METHOD = %s and START_DT >= %s", (mes.METHOD_AUTO, t0))
    conn.x("delete from AGT_RECOMMENDATIONS where RECO_TYPE = %s and CREATED_AT_DT >= %s", (mes.ALERT_RECO, t0))
    conn.x("delete from DAT_TIMESERIES where MEASURE_DT >= %s", (t0,))
    conn.x("delete from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s", (t0,))
    conn.x("delete from IF_PLC_SIGNALS where COLLECT_DT >= %s", (t0,))
    conn.x("delete from IF_GATEWAY_BUFFER where BUFFERED_DT >= %s", (t0,))


@pytest.fixture()
def running_wo():
    """레이저커팅 P40 작업지시 하나를 `진행` 으로 두고, 끝나면 원래 상태로 되돌린다."""
    wo = conn.q1("select WORK_ORDER_ID, WORK_ORDER_NO, ORDER_STATUS from PRC_WORK_ORDERS "
                 "where PROCESS_CODE = 'P40' and OUTSOURCE_YN = 'N' order by WORK_ORDER_ID limit 1")
    assert wo is not None, "시드에 P40 작업지시가 없다"
    conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = '진행' where WORK_ORDER_ID = %s", (wo["work_order_id"],))
    try:
        yield dict(wo)
    finally:
        conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = %s where WORK_ORDER_ID = %s",
               (wo["order_status"], wo["work_order_id"]))


def _cycle(t0, i: int, *, qty: str = "1", alarm: bool = False) -> list[collector.Sample]:
    dt = t0 + timedelta(seconds=i)
    vals = {"RUN_MINUTE": "0.5", "PRODUCE_QTY": qty, "RUN_STATUS": "알람" if alarm else "가동",
            "ALARM_CODE": "AL-CUR-HI" if alarm else "", "SPEED_VALUE": "1200", "PRESSURE_VALUE": "9",
            "CURRENT_VALUE": "41.5" if alarm else "20", "TEMP_VALUE": "40"}
    return [collector.Sample(t.name, vals[t.name], dt) for t in tags.TAGS]


# ── ① 작업지시 매핑 ─────────────────────────────────────────────────────────
def test_진행_작업지시가_0건이면_붙이지_않고_이유를_남긴다(device_id, window):
    assert not conn.q("select 1 from PRC_WORK_ORDERS where PROCESS_CODE = 'P40' and ORDER_STATUS = '진행'")
    r = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0))
    assert r.mes.work_order_id is None
    assert "0건" in r.mes.reason and "미매핑" in r.mes.reason
    row = conn.q1("select WORK_ORDER_ID from PRC_EQUIP_SIGNALS where COLLECT_DT = %s", (window,))
    assert row["work_order_id"] is None
    assert r.mes.perf_id is None, "매핑이 없는데 실적을 만들었다"


def test_진행_작업지시가_정확히_1건이면_자동_매핑하고_실적을_도출한다(device_id, window, running_wo):
    r = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0) + _cycle(window, 1, qty="2"))
    assert r.mes.work_order_id == running_wo["work_order_id"]
    assert r.mes.explicit is False and r.mes.attached_rows == 2
    perf = conn.q1("select GOOD_QTY, ACTUAL_MANHOUR, DEFECT_QTY, COLLECT_METHOD, PROCESS_CODE, START_DT, END_DT "
                   "from PRC_PERFORMANCES where PERF_ID = %s", (r.mes.perf_id,))
    assert float(perf["good_qty"]) == 3.0 and perf["collect_method"] == mes.METHOD_AUTO
    assert perf["process_code"] == "P40"
    assert perf["defect_qty"] is None, "PLC 는 양·불을 판정하지 않는다 — 불량 수량을 적으면 지어낸 것이다"
    assert perf["start_dt"] == window and perf["end_dt"] == window + timedelta(seconds=1)
    assert float(perf["actual_manhour"]) == round(1.0 / 60, 2)


def test_같은_배치를_다시_보내도_실적이_두_배가_되지_않는다(device_id, window, running_wo):
    a = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0) + _cycle(window, 1))
    b = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0) + _cycle(window, 1))
    assert b.duplicated == 16 and b.stored == 0
    n = conn.q1("select count(*) as n, max(GOOD_QTY) as q from PRC_PERFORMANCES "
                "where WORK_ORDER_ID = %s and COLLECT_METHOD = %s and START_DT >= %s",
                (running_wo["work_order_id"], mes.METHOD_AUTO, window))
    assert int(n["n"]) == 1 and float(n["q"]) == 2.0, "실적은 신호에서 도출된 1행이어야 한다"
    assert a.mes.perf_id == conn.q1("select PERF_ID from PRC_PERFORMANCES where WORK_ORDER_ID = %s "
                                    "and COLLECT_METHOD = %s and START_DT >= %s",
                                    (running_wo["work_order_id"], mes.METHOD_AUTO, window))["perf_id"]


def test_진행_작업지시가_2건이면_고르지_않는다(device_id, window, running_wo):
    other = conn.q1("select WORK_ORDER_ID, ORDER_STATUS from PRC_WORK_ORDERS where PROCESS_CODE = 'P40' "
                    "and OUTSOURCE_YN = 'N' and WORK_ORDER_ID <> %s order by WORK_ORDER_ID limit 1",
                    (running_wo["work_order_id"],))
    conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = '진행' where WORK_ORDER_ID = %s", (other["work_order_id"],))
    try:
        r = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0))
        assert r.mes.work_order_id is None
        assert "2건" in r.mes.reason and "현장POP" in r.mes.reason
    finally:
        conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = %s where WORK_ORDER_ID = %s",
               (other["order_status"], other["work_order_id"]))


def test_현장POP_지정은_검증하고_쓴다(device_id, window, running_wo):
    r = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0), work_order_id=running_wo["work_order_id"])
    assert r.mes.explicit and r.mes.work_order_id == running_wo["work_order_id"]


@pytest.mark.parametrize("pick", ["없음", "외주", "완료", "다른공정"])
def test_틀린_작업지시_지정은_422_다(device_id, window, pick):
    if pick == "없음":
        bad = 999_999_999
    elif pick == "외주":
        bad = int(conn.q1("select WORK_ORDER_ID from PRC_WORK_ORDERS where OUTSOURCE_YN = 'Y' limit 1")["work_order_id"])
    elif pick == "완료":
        bad = int(conn.q1("select WORK_ORDER_ID from PRC_WORK_ORDERS where PROCESS_CODE = 'P40' "
                          "and ORDER_STATUS = '완료' limit 1")["work_order_id"])
    else:
        bad = int(conn.q1("select WORK_ORDER_ID from PRC_WORK_ORDERS where PROCESS_CODE = 'P50' limit 1")["work_order_id"])
    with pytest.raises(http.HTTPException) as e:
        collector.ingest_batch(device_id, EQUIP, _cycle(window, 0), work_order_id=bad)
    assert e.value.status_code == 422
    assert not conn.q("select 1 from PRC_EQUIP_SIGNALS where COLLECT_DT = %s", (window,)), \
        "422 인데 신호가 적재됐다 — 한 트랜잭션이어야 한다"


def test_현장POP_신호는_작업지시에_붙이지_않는다(device_id, window):
    dev20 = int(conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s", ("현장POP(터치PC)",))["device_id"])
    r = collector.ingest_batch(dev20, "EQ20", _cycle(window, 0))
    assert r.mes.work_order_id is None and "EQ10" in r.mes.reason


# ── ③ 알람 → 041 ────────────────────────────────────────────────────────────
def test_알람_에피소드마다_알림추천_1행이고_연속_주기는_또_만들지_않는다(device_id, window, running_wo):
    r1 = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0) + _cycle(window, 1, alarm=True))
    assert len(r1.mes.alerts) == 1
    r2 = collector.ingest_batch(device_id, EQUIP, _cycle(window, 2, alarm=True) + _cycle(window, 3, alarm=True))
    assert r2.mes.alerts == [], "같은 알람 에피소드인데 알림을 또 만들었다"
    r3 = collector.ingest_batch(device_id, EQUIP, _cycle(window, 4) + _cycle(window, 5, alarm=True))
    assert len(r3.mes.alerts) == 1, "알람이 끝났다가 다시 시작하면 새 에피소드다"
    rows = conn.q("select RECO_TYPE, TARGET_TYPE, TARGET_ID, REVIEW_STATUS, SUMMARY_TEXT, EVIDENCE_JSON "
                  "from AGT_RECOMMENDATIONS where CREATED_AT_DT >= %s order by RECO_ID", (window,))
    assert len(rows) == 2
    assert all(r["reco_type"] == mes.ALERT_RECO and r["review_status"] == "미검토" for r in rows)
    assert rows[0]["target_type"] == "작업지시" and int(rows[0]["target_id"]) == running_wo["work_order_id"]
    assert running_wo["work_order_no"] in rows[0]["summary_text"]
    assert "임계 비교 없음" in rows[0]["evidence_json"]["threshold"], "임계값을 지어내 비교한 것처럼 적으면 안 된다"


def test_임계_비교는_표준조건이_없으면_차단이다():
    assert int(conn.q1("select count(*) as n from PRC_STD_CONDITIONS where PROCESS_CODE = 'P40'")["n"]) == 0, \
        "표준조건이 생겼다 — 이 테스트와 D-225 를 같이 갱신한다"
    th = mes.threshold_check({"SPEED_VALUE": 1200.0})
    assert th["blocked"] and "D-59" in th["note"] and th["items"] == []


# ── ② 재전송도 표지·작업지시를 잃지 않는다 (D-227) ─────────────────────────────
def test_버퍼_재전송이_시뮬레이터_표지와_작업지시를_잃지_않는다(device_id, window, running_wo):
    collector.buffer(device_id, EQUIP, _cycle(window, 0), "네트워크 단절",
                     collect_path=collector.COLLECT_PATH_SIM, work_order_id=running_wo["work_order_id"])
    out = collector.resend(device_id)
    assert out["resent_batches"] == 1 and out["stored_rows"] == 8
    paths = {r["collect_path"] for r in conn.q("select distinct COLLECT_PATH from DAT_TIMESERIES where MEASURE_DT = %s", (window,))}
    assert paths == {collector.COLLECT_PATH_SIM}, f"재전송이 표지를 실수집으로 바꿨다: {paths}"
    sig = conn.q1("select WORK_ORDER_ID from PRC_EQUIP_SIGNALS where COLLECT_DT = %s", (window,))
    assert int(sig["work_order_id"]) == running_wo["work_order_id"]


# ── 실시간 스냅샷 · API · 화면 (D-223) ───────────────────────────────────────────
def test_스냅샷_0건_경로는_값을_만들지_않는다():
    assert int(conn.q1("select count(*) as n from PRC_EQUIP_SIGNALS")["n"]) == 0, "런타임 표가 비어 있어야 0건 경로다"
    s = mes.live_snapshot()
    assert s["last"] is None and s["recent"] == [] and s["today"]["signals"] == 0
    assert s["today"]["utilisation_pct"] is None, "분모 0 인데 가동률이 있다"
    assert s["work_order"] is None and "미매핑" in s["mapping_note"]
    assert s["thresholds"]["blocked"] and s["performance"] is None and s["alerts"] == []


def test_스냅샷_N건_경로는_적재된_값만_돌려준다(device_id, window, running_wo):
    collector.ingest_batch(device_id, EQUIP, _cycle(window, 0) + _cycle(window, 1, alarm=True))
    s = mes.live_snapshot(recent=5)
    assert s["last"]["alarm_code"] == "AL-CUR-HI" and s["last"]["run_status"] == "알람"
    assert [t["name"] for t in s["last"]["tags"]] == [t.name for t in tags.TAGS]
    assert len(s["recent"]) == 2 and s["recent"][-1]["current"] == 41.5
    assert s["work_order"]["work_order_no"] == running_wo["work_order_no"]
    assert s["alerts"] and s["alerts"][0]["review_status"] == "미검토"


def test_live_API_와_화면_003_022_가_같은_모양을_낸다():
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app)
    r = c.get("/api/ingest/live")
    assert r.status_code == 200
    body = r.json()
    for k in ("checked_at", "device", "last", "today", "recent", "work_order", "mapping_note",
              "performance", "thresholds", "alerts", "buffer_pending"):
        assert k in body, k
    assert c.get("/api/ingest/live?equip=EQ99").status_code == 422
    assert c.get("/api/ingest/live?n=0").status_code == 422
    for path in ("/dsh/003", "/prc/022"):
        h = c.get(path)
        assert h.status_code == 200
        assert 'id="live"' in h.text and "/static/live.js" in h.text, f"{path} 에 실시간 패널이 없다"
        assert "data-live=\"/api/ingest/live" in h.text
    assert c.get("/static/live.js").status_code == 200
    # 현장 작업자는 대시보드·공정을 읽을 수 있으므로 실시간 패널도 갱신된다
    assert c.get("/api/ingest/live", headers={"x-kyungdong-role": "OPERATOR"}).status_code == 200


def test_수집_API_가_현장POP_지정을_받고_틀리면_422_다(device_id, running_wo, window):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app)
    payload = {"device_id": device_id, "equip_code": EQUIP, "collect_path": collector.COLLECT_PATH_SIM,
               "samples": [x.as_dict() for x in _cycle(window, 0)]}
    r = c.post("/api/ingest/plc", json={**payload, "work_order_id": running_wo["work_order_id"]})
    assert r.status_code == 200 and r.json()["mes"]["work_order_no"] == running_wo["work_order_no"]
    r = c.post("/api/ingest/plc", json={**payload, "work_order_id": "abc"})
    assert r.status_code == 422


# ── 연속 시뮬레이터 (D-222) ────────────────────────────────────────────────────
def test_연속_모드는_정해진_주기_뒤_멈추고_유실_0_이다(tmp_path, window, running_wo):
    import importlib
    sys.path.insert(0, str(ROOT / "tools"))
    sim = importlib.import_module("plc_simulator")
    from kyungdong.ingest import plcdb
    before = int(conn.q1("select count(*) as n from IF_PLC_SIGNALS")["n"])
    db = tmp_path / "plc.db"
    argv = sys.argv[:]
    sys.argv = ["plc_simulator", "--daemon", "--via", "inproc", "--plc-db", str(db), "--plc-reset",
                "--poll-sec", "1", "--max-cycles", "4", "--fault-every", "2", "--fault-len", "1",
                "--anomaly-rate", "0", "--seed", "1"]
    try:
        assert sim.main() == 0
    finally:
        sys.argv = argv
        # 연속 모드는 벽시계로 적재한다 — 이 테스트가 넣은 실시각 행을 지운다
        conn.x("delete from PRC_PERFORMANCES where COLLECT_METHOD = %s and START_DT >= now() - interval '10 minutes'",
               (mes.METHOD_AUTO,))
        conn.x("delete from DAT_TIMESERIES where MEASURE_DT >= now() - interval '10 minutes'")
        conn.x("delete from PRC_EQUIP_SIGNALS where COLLECT_DT >= now() - interval '10 minutes'")
        conn.x("delete from IF_PLC_SIGNALS where COLLECT_DT >= now() - interval '10 minutes'")
        conn.x("delete from IF_GATEWAY_BUFFER where BUFFERED_DT >= now() - interval '10 minutes'")
    c = plcdb.connect(db)
    st = plcdb.stats(c)
    c.close()
    assert st["scanned"] == 32 and st["unsent"] == 0, st


def test_연속_모드의_벽시계는_허용_목록에_있고_시드는_앵커를_쓴다():
    """`_wall_now` 하나만 벽시계다. 다른 곳에 `datetime.now()` 가 생기면 G-07 검사기가 잡는다."""
    sys.path.insert(0, str(ROOT))
    from tools import check_data
    assert ("tools/plc_simulator.py", "_wall_now") in check_data.NOW_ALLOWED
    banned, _ = check_data.scan_clock()
    assert not [b for b in banned if "plc_simulator" in b or "ingest/mes" in b], banned
