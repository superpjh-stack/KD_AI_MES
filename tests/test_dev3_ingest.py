"""수집 — 유실 0 · 순서 보존 · Gateway 재전송 무손실 · 수집 지점 2개소 (D-06 · G-12)."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                          # noqa: E402
from kyungdong.app.util import clock, http           # noqa: E402
from kyungdong.ingest import collector, tags         # noqa: E402

EQUIP = "EQ10"
DEVICE = "레이저커팅기 PLC"


@pytest.fixture(scope="module")
def device_id() -> int:
    row = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s", (DEVICE,))
    assert row is not None, "seed_dev3 를 먼저 돌린다"
    return int(row["device_id"])


@pytest.fixture
def window():
    """시험 전용 시간 창 — 앵커에서 멀리 떨어뜨려 다른 데이터와 섞이지 않게 한다."""
    t0 = clock.anchor() + timedelta(days=3650)
    yield t0
    conn.x("delete from DAT_TIMESERIES where MEASURE_DT >= %s", (t0,))
    conn.x("delete from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s", (t0,))
    conn.x("delete from IF_PLC_SIGNALS where COLLECT_DT >= %s", (t0,))
    conn.x("delete from IF_GATEWAY_BUFFER where BUFFERED_DT >= %s", (t0,))


def _cycle(t0, i: int) -> list[collector.Sample]:
    dt = t0 + timedelta(seconds=i)
    return [collector.Sample(t.name, "1.0" if t.numeric else "가동", dt) for t in tags.TAGS]


def test_수집_지점은_2개소뿐이다():
    rows = conn.q("select DEVICE_NAME, DEVICE_TYPE from IF_DEVICE_REGISTRY order by DEVICE_ID")
    assert len(rows) == 2, "사업계획서 2.7.1 데이터 집계 포인트는 2개소다 (D-06)"
    assert {r["device_name"] for r in rows} == {DEVICE, "현장POP(터치PC)"}


def test_정본에_없는_태그는_422_다(device_id: int, window):
    bad = [collector.Sample("VIBRATION", "1.0", window)]
    with pytest.raises(http.HTTPException) as e:
        collector.ingest_batch(device_id, EQUIP, bad)
    assert e.value.status_code == 422


def test_모르는_설비코드는_422_다(device_id: int, window):
    with pytest.raises(http.HTTPException) as e:
        collector.ingest_batch(device_id, "EQ99", _cycle(window, 0))
    assert e.value.status_code == 422


def test_유실_0_이고_순서가_보존된다(device_id: int, window):
    total = 0
    for i in range(5):
        r = collector.ingest_batch(device_id, EQUIP, _cycle(window, i))
        assert r.ordered
        total += r.stored
    assert total == 5 * len(tags.TAGS)
    n = conn.q1("select count(*) as n from IF_PLC_SIGNALS where COLLECT_DT >= %s", (window,))["n"]
    assert int(n) == total, "유실 0"
    dts = [r["collect_dt"] for r in conn.q(
        "select COLLECT_DT from IF_PLC_SIGNALS where COLLECT_DT >= %s order by PLC_IF_ID", (window,))]
    assert dts == sorted(dts), "순서 보존"


def test_같은_배치를_다시_보내도_행이_늘지_않는다(device_id: int, window):
    collector.ingest_batch(device_id, EQUIP, _cycle(window, 0))
    before = conn.q1("select count(*) as n from IF_PLC_SIGNALS where COLLECT_DT >= %s", (window,))["n"]
    r = collector.ingest_batch(device_id, EQUIP, _cycle(window, 0))
    after = conn.q1("select count(*) as n from IF_PLC_SIGNALS where COLLECT_DT >= %s", (window,))["n"]
    assert r.stored == 0 and r.duplicated == len(tags.TAGS)
    assert before == after


def test_Gateway_단절_복구_재전송이_무손실이다(device_id: int, window):
    """단절 구간은 버퍼로, 복구 시 **최초 저장 순서대로** 재전송한다."""
    sent = 0
    for i in range(3):                       # 정상 구간
        sent += collector.ingest_batch(device_id, EQUIP, _cycle(window, i)).stored
    buffered = [collector.buffer(device_id, EQUIP, _cycle(window, i)) for i in range(3, 6)]
    assert len(buffered) == 3
    pend = collector.pending_buffer(device_id)
    assert len(pend) == 3
    assert [p["buffer_id"] for p in pend] == sorted(p["buffer_id"] for p in pend), "순서 보존"

    out = collector.resend(device_id)
    assert out["resent_batches"] == 3
    assert out["stored_rows"] == 3 * len(tags.TAGS)
    total = conn.q1("select count(*) as n from IF_PLC_SIGNALS where COLLECT_DT >= %s", (window,))["n"]
    assert int(total) == 6 * len(tags.TAGS), "단절 구간 유실 0"
    assert collector.pending_buffer(device_id) == []


def test_시계열과_설비신호에_같은_시각으로_적재된다(device_id: int, window):
    collector.ingest_batch(device_id, EQUIP, _cycle(window, 0))
    sig = conn.q1("select count(*) as n from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s", (window,))["n"]
    ts = conn.q1("select count(*) as n from DAT_TIMESERIES where MEASURE_DT >= %s", (window,))["n"]
    assert int(sig) == 1, "한 수집 시각 → PRC_EQUIP_SIGNALS 한 행"
    assert int(ts) == len(tags.numeric_tags()), "숫자 태그만 시계열로 간다"


def test_수집_상태_시그니처가_공표한_모양이다():
    """`/dsh/003`·`/prc/022`(개발2)가 이 모양을 쓴다 — 바꾸면 진행률에 공표한다."""
    st = collector.status()
    assert set(st) >= {"checked_at", "stale_sec", "stale_badge", "points", "devices",
                       "buffer_pending", "any_stale"}
    assert st["points"] == 2
    for d in st["devices"]:
        assert set(d) >= {"device_id", "device_name", "device_type", "last_collect_dt",
                          "seconds_since", "stale", "notice", "signal_cnt"}


def test_수집이_없으면_미수집_문구가_나온다():
    pop = [d for d in collector.status()["devices"] if d["device_name"] == "현장POP(터치PC)"]
    assert pop and pop[0]["notice"], "수집이 0건이면 문구가 있어야 한다 (G-11)"


# ══ 시뮬레이터 두 단절 (D-174·D-175) ══════════════════════════════════════
# **끊긴 자리가 다르면 값이 남는 자리도 다르다.** 처음엔 이것을 뭉뚱그려서, 한 번의 단절에
# Gateway 버퍼와 PLC 레지스터가 **같은 값을 둘 다** 들고 있었다 — 복구하면 두 번 올라간다.
# 아래 두 시험이 그 구분을 못박는다.
def _run_sim(tmp_path, *extra: str) -> dict:
    import importlib

    sys.path.insert(0, str(ROOT / "tools"))
    sim = importlib.import_module("plc_simulator")
    from kyungdong.ingest import plcdb

    db = tmp_path / "plc.db"
    argv = sys.argv[:]
    sys.argv = ["plc_simulator", "--plc-db", str(db), "--cycles", "10",
                "--via", "inproc", *extra]
    try:
        assert sim.main() == 0
    finally:
        sys.argv = argv
    c = plcdb.connect(db)
    st = plcdb.stats(c)
    c.close()
    st["buffer"] = int(conn.q1("select count(*) as n from IF_GATEWAY_BUFFER "
                               "where BUFFER_STATUS = '대기'")["n"])
    st["signals"] = int(conn.q1("select count(*) as n from IF_PLC_SIGNALS")["n"])
    return st


@pytest.fixture()
def clean_runtime():
    """런타임 전용 표는 **0건이 정상**이다(G-11). 앞뒤로 확인하고 비운다."""
    tbls = ("IF_PLC_SIGNALS", "DAT_TIMESERIES", "PRC_EQUIP_SIGNALS", "IF_GATEWAY_BUFFER")
    for t in tbls:
        n = int(conn.q1(f"select count(*) as n from {t}")["n"])
        assert n == 0, f"{t} 가 시험 전부터 {n} 행이다 — G-11 을 확인한다"
    yield
    for t in tbls:
        conn.x(f"delete from {t}")


def test_PLC측_단절은_장비에_남고_Gateway_버퍼에는_안_들어간다(tmp_path, clean_runtime):
    """PLC↔Gateway 가 끊기면 Gateway 는 그 값을 **본 적도 없다.** 버퍼에 들어갈 수 없다."""
    st = _run_sim(tmp_path, "--plc-offline", "4")
    assert st["scanned"] == 80
    assert st["unsent"] == 48, f"장비에 남아 있어야 한다: {st}"
    assert st["buffer"] == 0, "Gateway 가 보지도 못한 값이 버퍼에 들어갔다"
    assert st["signals"] == 32, st


def test_클라우드측_단절은_버퍼가_지고_PLC_는_넘긴_것으로_본다(tmp_path, clean_runtime):
    """Gateway↔클라우드가 끊기면 폴링은 **됐다** — 값은 Gateway 손에 있다.

    이때 PLC 에도 미전송으로 남기면 **같은 값을 둘이 들고** 있게 되어 복구 때 두 번 올라간다.
    """
    st = _run_sim(tmp_path, "--disconnect", "4", "--reconnect", "7")
    assert st["scanned"] == 80
    assert st["unsent"] == 0, f"Gateway 가 가져간 값이 장비에 또 남아 있다: {st}"
    assert st["buffer"] == 0, "재전송 뒤에도 대기 버퍼가 남았다"
    assert st["signals"] == 80, f"재전송 포함 유실 0 이어야 한다: {st}"
