"""PLC 측 저장소 (D-174) — **장비가 값을 들고 있다가 복구 후 올려보내는 것**을 잰다.

도입기업 장비 IP 가 없어 실물을 못 붙인다(D-169). 그래서 PLC 쪽을 세워 돌린다.
여기서 못박는 것은 **유실이 숨지 않는 것**이다 — 스캔한 수와 보낸 수를 갈라서 세고,
적재에 성공한 것만 보냄 표시를 한다. 먼저 표시하면 적재가 실패해도 보낸 것이 된다.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.ingest import plcdb, tags                       # noqa: E402

T0 = datetime(2026, 9, 11, 9, 0, 0)


@pytest.fixture()
def pc(tmp_path):
    c = plcdb.connect(tmp_path / "plc.db")
    plcdb.init(c)
    yield c
    c.close()


def cycle(i: int) -> dict[str, str]:
    return {t.name: ("가동" if t.name == "RUN_STATUS" else
                     "" if t.name == "ALARM_CODE" else f"{i}.0") for t in tags.TAGS}


def test_레지스터는_정본_8종뿐이고_주소가_고정이다(pc):
    rows = plcdb.registers(pc)
    assert [r["tag_name"] for r in rows] == [t.name for t in tags.TAGS]
    assert [r["addr"] for r in rows] == [f"SIM-D{i:04d}" for i in range(1, 9)]
    # **실물 주소인 척하지 않는다** — 태그맵은 도입기업 제공이다 (D-176).
    assert all(r["addr"].startswith("SIM-") for r in rows)


def test_정본_밖의_태그는_조용히_버리지_않고_예외다(pc):
    with pytest.raises(ValueError, match="8종 밖"):
        plcdb.scan_write(pc, T0, {"VIBRATION": "1.0"})
    with pytest.raises(ValueError):
        plcdb.address_of("VIBRATION")


def test_init_은_여러_번_불러도_같다(pc):
    before = plcdb.registers(pc)
    plcdb.init(pc)
    plcdb.init(pc)
    assert plcdb.registers(pc) == before


def test_스캔만_하면_아무것도_보내지_않은_상태다(pc):
    for i in range(3):
        plcdb.scan_write(pc, T0 + timedelta(seconds=i), cycle(i))
    st = plcdb.stats(pc)
    assert st == {"scanned": 24, "sent": 0, "unsent": 24}, st


def test_폴링은_읽기만_하고_보냄_표시를_하지_않는다(pc):
    """읽자마자 `Y` 로 적으면 **적재가 실패해도 보낸 것**이 되어 유실이 숨는다."""
    plcdb.scan_write(pc, T0, cycle(0))
    got = plcdb.poll(pc)
    assert len(got) == 8
    assert plcdb.stats(pc)["unsent"] == 8, "폴링이 보냄 표시를 했다"
    plcdb.mark_sent(pc, [g.scan_id for g in got])
    assert plcdb.stats(pc)["unsent"] == 0


def test_보낸_것은_다시_폴링되지_않는다(pc):
    plcdb.scan_write(pc, T0, cycle(0))
    first = plcdb.poll(pc)
    plcdb.mark_sent(pc, [g.scan_id for g in first])
    plcdb.scan_write(pc, T0 + timedelta(seconds=1), cycle(1))
    second = plcdb.poll(pc)
    assert len(second) == 8, "새로 스캔한 것만 나와야 한다"
    assert {g.scan_id for g in first} & {g.scan_id for g in second} == set()


def test_단절_구간의_값이_장비에_남았다가_복구_후_전부_올라간다(pc):
    """**이 시험이 PLC 저장소를 만든 이유다.**

    곧장 `collector.ingest_batch()` 를 부르면 PLC 메모리와 Gateway 폴링이 통째로 빠져서
    '끊긴 동안 장비가 들고 있다' 를 잴 수가 없다.
    """
    for i in range(10):
        plcdb.scan_write(pc, T0 + timedelta(seconds=i), cycle(i))
    cycles = plcdb.group_by_cycle(plcdb.poll(pc))
    assert len(cycles) == 10, "주기 단위로 묶이지 않았다"

    # 앞 4주기만 전달 — 5주기째부터 PLC↔Gateway 단절이라고 본다.
    for dt, group in cycles[:4]:
        plcdb.mark_sent(pc, [g.scan_id for g in group], dt)
    held = plcdb.stats(pc)
    assert held == {"scanned": 80, "sent": 32, "unsent": 48}, held

    # 복구 — 남아 있던 것이 그때 올라간다. **유실 0.**
    rest = plcdb.group_by_cycle(plcdb.poll(pc))
    assert len(rest) == 6, "남은 주기가 6이 아니다"
    for dt, group in rest:
        plcdb.mark_sent(pc, [g.scan_id for g in group], dt)
    after = plcdb.stats(pc)
    assert after == {"scanned": 80, "sent": 80, "unsent": 0}, after


def test_주기_묶음은_스캔_시각과_정본_순서를_지킨다(pc):
    """순서 보존을 시험하려면 **들어온 순서가 고정**이어야 한다."""
    for i in range(2):
        plcdb.scan_write(pc, T0 + timedelta(seconds=i), cycle(i))
    cycles = plcdb.group_by_cycle(plcdb.poll(pc))
    assert [dt for dt, _ in cycles] == [T0, T0 + timedelta(seconds=1)]
    for _, group in cycles:
        assert [g.tag_name for g in group] == [t.name for t in tags.TAGS]


def test_PLC_파일은_우리_DB_가_아니다():
    """같은 DB 에 넣으면 **장비가 들고 있던 값**과 **우리가 적재한 값**이 구분되지 않는다."""
    assert plcdb.DEFAULT_PATH.suffix == ".db"
    assert plcdb.DEFAULT_PATH.parent.name == "work"
    src = (ROOT / "src" / "kyungdong" / "ingest" / "plcdb.py").read_text()
    assert "sqlite3" in src and "psycopg" not in src, "PLC 저장소가 우리 DB 를 쓴다"
