#!/usr/bin/env python
"""레이저커팅기 Master PLC 시뮬레이터 — **1대만** (D-06).

사업계획서 2.7.1 의 데이터 집계 포인트는 두 곳뿐이고, 그중 **자동 수집은 레이저커팅기 1지점**이다.
현장POP(터치PC)는 사람이 입력한다. 다른 공정에는 수집원이 없다 —
전 공정 실시간 수집을 만들면 결함이다.

만드는 태그는 정본이 적은 8종뿐이다: 작업시간·수량·가동상태·알람·속도·압력·전류·온도.

**시간은 `clock.anchor()` 에 고정한다**(§10-3). `date.today()` 를 쓰지 않는다 — 날짜가 바뀔 때마다
수치가 흔들리는 사고를 되풀이하지 않기 위해서다. 실제 벽시계로 넣고 싶으면 `--realtime` 을 쓴다.

시험할 수 있는 것
  · `--anomaly`     전류·온도 임계 초과 주입 (알람 상태 전이)
  · `--disconnect N --reconnect M`  N 주기에 Gateway 단절, M 주기에 복구 → **버퍼 재전송 무손실** 확인
  · `--dry-run`     DB 에 쓰지 않고 만들 payload 만 보여 준다

주의: 이 값들은 **시뮬레이션**이다. `DAT_TIMESERIES.COLLECT_PATH` 에 그 사실을 남긴다 —
TD5 에 '원천 구분' 컬럼이 없어 그 자리로 표시한다(D-305).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                          # noqa: E402
from kyungdong.app.settings import settings          # noqa: E402
from kyungdong.app.util import clock                 # noqa: E402
from kyungdong.ingest import collector, tags         # noqa: E402

DEVICE_NAME = "레이저커팅기 PLC"
EQUIP_CODE = "EQ10"        # BAS_COMMON_CODES '설비' 그룹 — 시드가 넣는다

# 정상 운전 범위. 사업계획서에 수치가 없어 **시뮬레이션 값**이고, 화면·리포트에 그렇게 적는다.
BASE = {
    "SPEED_VALUE": (1000.0, 1300.0),      # mm/min
    "PRESSURE_VALUE": (8.0, 12.0),        # bar
    "CURRENT_VALUE": (18.0, 26.0),        # A
    "TEMP_VALUE": (35.0, 55.0),           # ℃
}
ANOMALY = {"CURRENT_VALUE": 41.5, "TEMP_VALUE": 88.0}
ALARM_CODE = "AL-CUR-HI"


def device_id() -> int:
    row = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s", (DEVICE_NAME,))
    if row is None:
        raise SystemExit(f"'{DEVICE_NAME}' 가 IF_DEVICE_REGISTRY 에 없다 — `uv run python db/seed_dev3.py`")
    return int(row["device_id"])


def cycle_samples(t0, i: int, poll: int, rng: random.Random, anomaly: bool) -> list[collector.Sample]:
    """한 주기의 8태그. 순서는 `tags.TAGS` 를 따른다 — 순서 보존을 시험하려면 순서가 고정이어야 한다."""
    dt = t0 + timedelta(seconds=i * poll)
    bad = anomaly and i % 7 == 6
    values = {
        "RUN_MINUTE": f"{poll / 60:.2f}",
        "PRODUCE_QTY": str(rng.randint(0, 2)),
        "RUN_STATUS": "알람" if bad else "가동",
        "ALARM_CODE": ALARM_CODE if bad else "",
        **{k: f"{ANOMALY[k]:.4f}" if (bad and k in ANOMALY) else f"{rng.uniform(*v):.4f}"
           for k, v in BASE.items()},
    }
    return [collector.Sample(t.name, values[t.name], dt) for t in tags.TAGS]


def main() -> int:
    s = settings()
    p = argparse.ArgumentParser(
        description="레이저커팅기 Master PLC 1대 시뮬레이터 (수집 지점 2개소뿐 — D-06)")
    p.add_argument("--cycles", type=int, default=20, help="수집 주기 반복 횟수 (기본 20)")
    p.add_argument("--poll-sec", type=int, default=s.h("PLC_POLL_SEC").as_int(),
                   help=f"수집 주기(초). 기본은 .env KYUNGDONG_PLC_POLL_SEC — {s.h('PLC_POLL_SEC').badge}")
    p.add_argument("--seed", type=int, default=20260911, help="난수 시드 (재현 가능하게 고정)")
    p.add_argument("--anomaly", action="store_true", help="전류·온도 임계 초과 주입")
    p.add_argument("--disconnect", type=int, default=None, help="이 주기부터 Gateway 단절")
    p.add_argument("--reconnect", type=int, default=None, help="이 주기에 복구 + 버퍼 재전송")
    p.add_argument("--realtime", action="store_true",
                   help="시간 앵커 대신 **실시각**으로 적재한다 (003·022 수집 배지 확인용)")
    p.add_argument("--dry-run", action="store_true", help="DB 에 쓰지 않고 payload 만 출력")
    a = p.parse_args()

    if a.realtime:
        from datetime import datetime
        t0 = datetime.now().replace(microsecond=0) - timedelta(seconds=a.cycles * a.poll_sec)
        path = collector.COLLECT_PATH
        basis = "실시각 (--realtime)"
    else:
        t0 = clock.anchor()
        path = collector.COLLECT_PATH_SIM
        basis = f"시간 앵커 {t0.isoformat(sep=' ')} (§10-3 date.today() 금지)"

    rng = random.Random(a.seed)
    dev = None if a.dry_run else device_id()
    print(f"수집 지점        레이저커팅기 1대 ({EQUIP_CODE}) — 현장POP(터치PC)는 수동 입력이다 (D-06)")
    print(f"기준 시각        {basis}")
    print(f"수집 주기        {a.poll_sec}초 · {a.cycles}주기 · 태그 {len(tags.TAGS)}종")

    stored = dup = buffered = 0
    disconnected = False
    for i in range(a.cycles):
        samples = cycle_samples(t0, i, a.poll_sec, rng, a.anomaly)
        if a.dry_run:
            print(json.dumps([x.as_dict() for x in samples], ensure_ascii=False))
            continue
        if a.disconnect is not None and i >= a.disconnect:
            disconnected = True
        if a.reconnect is not None and i >= a.reconnect:
            disconnected = False
        if disconnected:
            collector.buffer(dev, EQUIP_CODE, samples, "네트워크 단절")
            buffered += 1
            continue
        r = collector.ingest_batch(dev, EQUIP_CODE, samples, collect_path=path)
        stored += r.stored
        dup += r.duplicated
        if not r.ordered:
            raise SystemExit("순서 보존 위반 — 수집 시각이 들어온 순서를 벗어났다")

    if a.dry_run:
        return 0

    print(f"적재            IF_PLC_SIGNALS {stored} 행 신규 · 중복 건너뜀 {dup}")
    if buffered:
        print(f"Gateway 버퍼     {buffered} 배치 (사유 네트워크 단절)")
        if a.reconnect is not None:
            out = collector.resend(dev)
            print(f"재전송          배치 {out['resent_batches']} · 신규 행 {out['stored_rows']} (유실 0)")
        else:
            print("재전송          하지 않았다 — `--reconnect` 로 복구 시험을 한다")

    st = collector.status()
    for d in st["devices"]:
        mark = d["notice"] or "수집 중"
        print(f"상태            {d['device_name']:<16} 마지막 {d['last_collect_dt'] or '-'} — {mark}")
    print(f"대기 버퍼        {st['buffer_pending']} 배치")
    n = conn.q1("select count(*) as n from DAT_TIMESERIES")["n"]
    m = conn.q1("select count(*) as n from PRC_EQUIP_SIGNALS")["n"]
    print(f"시계열/설비신호   DAT_TIMESERIES {n} · PRC_EQUIP_SIGNALS {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
