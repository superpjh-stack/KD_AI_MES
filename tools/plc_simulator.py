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

**두 다리로 나눠 돈다 (D-174).** 도입기업이 장비 IP 를 아직 주지 않아 실물을 못 붙인다 —
그래서 **PLC 쪽을 세웠다**: `work/plc_device.db`(SQLite) 가 장비의 레지스터 메모리다.
  ① **PLC 스캔** — 주기마다 8태그를 레지스터에 쓰고 스캔 이력에 남긴다 (`--scan-only`)
  ② **Gateway 폴링** — 아직 안 가져간 스캔을 읽어 적재하고, **성공한 것만** 보냄 표시 (`--poll-only`)
둘을 갈라 두면 **단절 구간에 값이 PLC 안에 남아 있다가 복구 후 올라가는 것**을 잴 수 있다.
곧장 `collector.ingest_batch()` 를 부르면 그 두 다리가 통째로 빠진다.

**연속 모드 `--daemon` (D-222)** — 멈출 때까지 수집 주기마다 한 주기를 만들어 스캔 → 폴링 → 적재를
돈다. 시각은 **벽시계**다(장비의 시계를 흉내 낸다 — 003·022 실시간 패널이 "지금" 을 묻기 때문이다).
가동/대기/정지 상태가 바뀌고, `--anomaly-rate` 로 알람 에피소드가, `--fault-every/--fault-len` 으로
Gateway↔클라우드 단절·복구(버퍼 재전송)가 주기적으로 일어난다. 작업지시는 `--work-order` 로 지정하거나
(현장POP 지정을 흉내), 없으면 서버의 매핑 규칙(D-224)을 따른다. 시험용으로 작업지시를 진행 상태로 두려면
`--start-work-order WO-…` / `--finish-work-order WO-…` 다 — **선언(SYS_CONFIGS)을 남기고 되돌린다.**

`--via` 가 전달 경로를 고른다.
  · `inproc`(기본) — `collector.ingest_batch()` 직접 호출. **HTTP·장비 인증을 지나지 않는다**
  · `http`        — 진짜 `POST /api/ingest/plc`. 미들웨어·장비 인증·태그 검증을 전부 지난다.
                    prod 에서 이 경로가 403 이었다(D-168) — 그것을 재는 유일한 방법이다

주의: 이 값들은 **시뮬레이션**이다. `DAT_TIMESERIES.COLLECT_PATH` 에 그 사실을 남긴다 —
TD5 에 '원천 구분' 컬럼이 없어 그 자리로 표시한다(D-305). 장비 IP 를 등록해 쓰는 경우
`SYS_CONFIGS('시스템설정','PLC_SIMULATOR')` 선언이 **그 IP 가 실물이 아님**을 나른다(D-174).
레지스터 주소 `SIM-D0001…` 도 실물이 아니다 — **PLC 태그맵은 도입기업에게 받아야 한다**(D-176).
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
from kyungdong.app.util import device                 # noqa: E402
from kyungdong.ingest import collector, plcdb, tags   # noqa: E402

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


def _short(p: Path | str) -> str:
    """저장소 안이면 상대경로, 밖이면 그대로. **경로 때문에 죽지 않는다** — 시험은 임시폴더를 쓴다."""
    q = Path(p)
    try:
        return q.relative_to(ROOT).as_posix()
    except ValueError:
        return str(q)


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


# ══ 장비 IP 등록 (D-174) — 실물 IP 가 없는 동안 HTTP 경로를 열어 두는 유일한 방법 ══
SIM_HOST_DEFAULT = "127.0.0.1"
SIM_DECISION = "D-174"


def register_sim_ip(host: str) -> None:
    """시뮬레이터 IP 를 등록하고 **동시에 선언을 남긴다.**

    선언 없이 IP 만 넣으면 그 IP 가 **실물 장비가 붙은 것처럼** 읽힌다. 둘은 늘 같이 간다 —
    `unregister_sim_ip()` 도 둘을 같이 거둔다.
    """
    dev = device_id()
    conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = %s, UPDATED_DT = now() "
           "where DEVICE_ID = %s", (host, dev))
    conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
           (device.CONFIG_TYPE, device.CONFIG_KEY))
    conn.x("insert into SYS_CONFIGS (CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, DESCRIPTION, "
           "USE_YN, CREATED_DT) values (%s, %s, %s, %s, 'Y', now())",
           (device.CONFIG_TYPE, device.CONFIG_KEY, SIM_DECISION,
            f"{DEVICE_NAME} IP_ADDRESS={host} 는 tools/plc_simulator.py 가 넣은 "
            f"**시뮬레이터 값**이다 — 실물 장비가 아니다. 도입기업 장비 IP 미제공 (D-169). "
            f"`--unregister` 로 IP 와 선언을 함께 거둔다"))
    print(f"장비 IP 등록      {DEVICE_NAME} ← {host}")
    print(f"선언            SYS_CONFIGS('{device.CONFIG_TYPE}','{device.CONFIG_KEY}') "
          f"= {SIM_DECISION}")
    print(f"                {device.simulation_note()}")


def unregister_sim_ip() -> None:
    """IP 와 선언을 **함께** 거둔다 — 데이터만 남기고 표시만 떼는 것이 되지 않게."""
    dev = device_id()
    n = conn.x("update IF_DEVICE_REGISTRY set IP_ADDRESS = null, UPDATED_DT = now() "
               "where DEVICE_ID = %s and IP_ADDRESS is not null", (dev,))
    m = conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
               (device.CONFIG_TYPE, device.CONFIG_KEY))
    print(f"거둠             장비 IP {n} 행 · 선언 {m} 행 → prod 수집은 다시 403 이다 (D-168)")


# ══ 전달 경로 ═════════════════════════════════════════════════════════════
def deliver_inproc(dev: int, samples: list, path: str, work_order_id: int | None = None):
    """`collector` 직접 호출 — **HTTP·장비 인증을 지나지 않는다.**"""
    return collector.ingest_batch(dev, EQUIP_CODE, samples, collect_path=path,
                                  work_order_id=work_order_id)


# `--via http` 가 닿을 수 있는 곳 — **루프백뿐이다.**
# 사업계획서 9.2 는 외부 접속 최소화이고 RAG 는 폐쇄형이다(외부 검색 0). 시뮬레이터가
# 임의의 호스트로 POST 할 수 있으면 그 경계가 이 파일 하나로 뚫린다. 목적지는 **우리 앱**이고
# 우리 앱은 localhost 에 뜬다 — 그 밖으로 나갈 일이 없으므로 아예 막는다.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def check_loopback(base_url: str) -> str:
    """루프백이 아니면 **거절한다.** 외부로 나가는 경로를 열어 두지 않는다."""
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").strip()
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"--via http 는 루프백에만 보낸다 — 받은 곳: {host or base_url!r}\n"
            f"  허용: {', '.join(LOOPBACK_HOSTS)}\n"
            f"  시뮬레이터가 임의 호스트로 POST 할 수 있으면 사업계획서 9.2 의 "
            f"외부 접속 최소화 경계가 이 파일 하나로 뚫린다")
    return host


def deliver_http(base_url: str, dev: int, samples: list, path: str,
                 timeout: float = 10.0, work_order_id: int | None = None):
    """진짜 `POST /api/ingest/plc` — **루프백의 우리 앱에만** 보낸다(`check_loopback`).

    **서버가 없으면 소리내어 죽는다** — 조용히 inproc 으로 되돌아가지 않는다(§10-9).
    되돌아가면 '됐다' 는 결과가 나오는데 HTTP 는 한 번도 안 지난다.
    """
    import urllib.error
    import urllib.request

    check_loopback(base_url)

    # **출처 표지를 payload 에 싣는다** (D-196). 안 실으면 수집 API 가 기본값
    # `PLC→Gateway→시계열DB`(실수집 라벨)로 적어서 **시뮬레이터 데이터가 실수집이 된다.**
    # inproc 경로는 `collect_path` 를 직접 넘겨 표지가 붙었는데 HTTP 경로만 빠져 있었다 —
    # 표지를 두 경로가 따로 붙이고 있었던 것이 원인이다.
    payload = {"device_id": dev, "equip_code": EQUIP_CODE, "collect_path": path,
               "samples": [x.as_dict() for x in samples]}
    if work_order_id is not None:
        payload["work_order_id"] = work_order_id      # 현장POP 지정을 흉내 낸다 (D-224)
    body = json.dumps(payload, ensure_ascii=False, default=str).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/ingest/plc", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise SystemExit(
            f"수집 API 가 {e.code} 를 냈다 — {detail}\n"
            f"  403 이면 장비 인증이다: `--register` 로 시뮬레이터 IP 를 넣는다 (D-168·D-174)"
        ) from e
    except urllib.error.URLError as e:
        raise SystemExit(
            f"수집 API 에 닿지 못했다: {base_url} — {e.reason}\n"
            f"  서버를 먼저 띄운다: `make run` (포트 {settings().port})") from e

# ══ 시험용 작업지시 상태 전환 (D-226) — 작업지시를 만드는 화면이 45화면에 없다 ══
WO_CONFIG_KEY = "PLC_SIMULATOR_WO"


def _find_wo(no: str) -> dict:
    row = conn.q1("select WORK_ORDER_ID, WORK_ORDER_NO, PROCESS_CODE, ORDER_STATUS, OUTSOURCE_YN "
                  "from PRC_WORK_ORDERS where WORK_ORDER_NO = %s", (no,))
    if row is None:
        raise SystemExit(f"작업지시 {no} 가 없다 — `SELECT WORK_ORDER_NO FROM PRC_WORK_ORDERS WHERE PROCESS_CODE='P40'`")
    if row["process_code"] != "P40" or row["outsource_yn"] == "Y":
        raise SystemExit(f"{no} 는 {row['process_code']} 다 — 자동(PLC) 수집은 레이저커팅 P40 사내 지시뿐이다 (D-06)")
    return dict(row)


def start_work_order(no: str) -> None:
    """작업지시를 `진행` 으로 둔다 + **시험용 전환이라는 선언**을 남긴다. 실적 승인이 아니다."""
    wo = _find_wo(no)
    conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = '진행', UPDATED_DT = now() where WORK_ORDER_ID = %s",
           (wo["work_order_id"],))
    conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s", (device.CONFIG_TYPE, WO_CONFIG_KEY))
    conn.x("insert into SYS_CONFIGS (CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, DESCRIPTION, USE_YN, CREATED_DT) "
           "values (%s, %s, %s, %s, 'Y', now())",
           (device.CONFIG_TYPE, WO_CONFIG_KEY, no,
            f"{no} 의 ORDER_STATUS='진행' 은 tools/plc_simulator.py --start-work-order 가 넣은 **시험용 전환**이다 "
            f"(이전 상태 {wo['order_status']}). --finish-work-order 로 되돌린다 (D-226)"))
    print(f"작업지시 진행     {no} ({wo['order_status']} → 진행) · 선언 SYS_CONFIGS('{device.CONFIG_TYPE}','{WO_CONFIG_KEY}')")
    print("                레이저커팅기 신호가 이 지시에 붙고 자동(PLC) 실적이 도출된다 (D-224)")


def finish_work_order(no: str) -> None:
    wo = _find_wo(no)
    n = conn.x("update PRC_WORK_ORDERS set ORDER_STATUS = '완료', UPDATED_DT = now() "
               "where WORK_ORDER_ID = %s and ORDER_STATUS = '진행'", (wo["work_order_id"],))
    m = conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s", (device.CONFIG_TYPE, WO_CONFIG_KEY))
    print(f"작업지시 완료     {no} ({n} 행) · 선언 {m} 행 거둠. 붙은 신호·자동 실적은 남는다 — 사실이었기 때문이다")


# ══ 연속 모드 (D-222) — 멈출 때까지 주기마다 스캔 → 폴링 → 적재 ═══════════════
# 상태 전이는 **시뮬레이션 가정**이다(정본에 없다). 가동 중 한 주기에 1개가 나올 확률을
# poll_sec/PIECE_SEC 로 두어 대략 PIECE_SEC 초에 한 조각씩 세게 했다.
PIECE_SEC = 90.0
STATE_HOLD = {"가동": (40, 120), "대기": (3, 10), "정지": (5, 20)}      # 주기 수


def _wall_now():
    """장비의 벽시계. `--daemon` 에서만 쓴다 — 실시간 패널이 '지금' 을 묻기 때문이다 (D-222).
    생성 기준일 용도가 아니다(§10-3): 시드·학습은 여전히 clock.anchor() 다."""
    from datetime import datetime
    return datetime.now().replace(microsecond=0)


def run_daemon(a, pc, dev: int, base_url: str, path: str) -> int:
    import signal
    import time

    rng = random.Random(a.seed if a.seed is not None else int(time.time()))
    stop = {"flag": False}

    def _stop(_sig, _frm):
        stop["flag"] = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    wo_id = None
    if a.work_order:
        wo_id = int(_find_wo(a.work_order)["work_order_id"])
    state, hold = "가동", rng.randint(*STATE_HOLD["가동"])
    alarm_left = 0
    fault_left = 0
    stats = {"cycles": 0, "stored": 0, "dup": 0, "buffered": 0, "resent": 0, "alarms": 0, "unmapped": 0}
    print(f"연속 모드         {a.poll_sec}초 주기 · 벽시계 · 알람률 {a.anomaly_rate} · "
          f"단절 매 {a.fault_every or '-'}주기 × {a.fault_len} · 작업지시 {a.work_order or '서버 매핑 규칙 (D-224)'}")
    print("                Ctrl-C 로 멈춘다. 이 값은 시뮬레이션이다 — COLLECT_PATH 에 그렇게 남는다 (D-174)")
    last_mes = None
    while not stop["flag"] and (a.max_cycles is None or stats["cycles"] < a.max_cycles):
        t = _wall_now()
        i = stats["cycles"]
        # ── 상태 전이
        hold -= 1
        if hold <= 0:
            state = rng.choices(["가동", "대기", "정지"], weights=[8, 2, 1])[0]
            hold = rng.randint(*STATE_HOLD[state])
        if alarm_left == 0 and state == "가동" and rng.random() < a.anomaly_rate:
            alarm_left = rng.randint(2, 5)
        bad = alarm_left > 0
        if bad:
            alarm_left -= 1
        run = state == "가동"
        values = {
            "RUN_MINUTE": f"{(a.poll_sec / 60) if run else 0:.4f}",
            "PRODUCE_QTY": str(1 if run and rng.random() < a.poll_sec / PIECE_SEC else 0),
            "RUN_STATUS": "알람" if bad else state,
            "ALARM_CODE": ALARM_CODE if bad else "",
            "SPEED_VALUE": f"{rng.uniform(*BASE['SPEED_VALUE']) if run else 0:.4f}",
            "PRESSURE_VALUE": f"{rng.uniform(*BASE['PRESSURE_VALUE']) if run else 0:.4f}",
            "CURRENT_VALUE": f"{ANOMALY['CURRENT_VALUE'] if bad else (rng.uniform(*BASE['CURRENT_VALUE']) if run else 0):.4f}",
            "TEMP_VALUE": f"{ANOMALY['TEMP_VALUE'] if bad else rng.uniform(*BASE['TEMP_VALUE']):.4f}",
        }
        if bad:
            stats["alarms"] += 1
        # ── ① PLC 스캔
        plcdb.scan_write(pc, t, values)
        # ── ② Gateway 폴링 — 단절이면 버퍼, 복구 주기에 재전송
        if a.fault_every and i > 0 and i % a.fault_every == 0:
            fault_left = a.fault_len
        cycles = plcdb.group_by_cycle(plcdb.poll(pc))
        line = ""
        for dt, group in cycles:
            samples = [collector.Sample(g.tag_name, g.value, dt) for g in group]
            if fault_left > 0:
                collector.buffer(dev, EQUIP_CODE, samples, "네트워크 단절",
                                 collect_path=path, work_order_id=wo_id)
                plcdb.mark_sent(pc, [g.scan_id for g in group], t)
                stats["buffered"] += 1
                line = "Gateway↔클라우드 단절 — 버퍼에 쌓음"
                continue
            if a.via == "http":
                r = deliver_http(base_url, dev, samples, path, work_order_id=wo_id)
                stats["stored"] += int(r.get("stored", 0)); stats["dup"] += int(r.get("duplicated", 0))
                last_mes = r.get("mes") or last_mes
            else:
                res = deliver_inproc(dev, samples, path, work_order_id=wo_id)
                stats["stored"] += res.stored; stats["dup"] += res.duplicated
                last_mes = res.mes.as_dict()
            plcdb.mark_sent(pc, [g.scan_id for g in group], t)
            if last_mes and not last_mes.get("work_order_id"):
                stats["unmapped"] += 1
        if fault_left > 0:
            fault_left -= 1
            if fault_left == 0:
                out = collector.resend(dev)
                stats["resent"] += int(out["resent_batches"])
                line = f"복구 — 버퍼 {out['resent_batches']} 배치 재전송 · 신규 {out['stored_rows']} 행 (유실 0)"
        stats["cycles"] += 1
        wo_txt = (f"WO {last_mes['work_order_no']}" if last_mes and last_mes.get("work_order_no")
                  else "작업지시 미매핑")
        print(f"{t:%H:%M:%S} #{i + 1:<5} {values['RUN_STATUS']:<3} 수량 {values['PRODUCE_QTY']} "
              f"전류 {float(values['CURRENT_VALUE']):6.2f}A 온도 {float(values['TEMP_VALUE']):5.1f}℃ "
              f"· {wo_txt}" + (f" · {line}" if line else ""), flush=True)
        if a.max_cycles is None or stats["cycles"] < a.max_cycles:
            time.sleep(a.poll_sec)
    st = plcdb.stats(pc)
    print(f"멈춤             주기 {stats['cycles']} · 적재 {stats['stored']} 행 · 중복 {stats['dup']} · "
          f"버퍼 {stats['buffered']} 배치 → 재전송 {stats['resent']} · 알람 주기 {stats['alarms']} · "
          f"미매핑 배치 {stats['unmapped']} · PLC 미전송 {st['unsent']}")
    if last_mes:
        print(f"마지막 연계       {last_mes.get('reason')}"
              + (f" · 자동 실적 #{last_mes.get('perf_id')} 수량 {last_mes.get('perf_good_qty')}"
                 if last_mes.get("perf_id") else ""))
    return 0


def main() -> int:
    s = settings()
    p = argparse.ArgumentParser(
        description="레이저커팅기 Master PLC 1대 시뮬레이터 (수집 지점 2개소뿐 — D-06)")
    p.add_argument("--cycles", type=int, default=20, help="수집 주기 반복 횟수 (기본 20)")
    p.add_argument("--poll-sec", type=int, default=s.h("PLC_POLL_SEC").as_int(),
                   help=f"수집 주기(초). 기본은 .env KYUNGDONG_PLC_POLL_SEC — {s.h('PLC_POLL_SEC').badge}")
    p.add_argument("--seed", type=int, default=None,
                   help="난수 시드 (단발 모드 기본 20260911 — 재현 가능 · 연속 모드 기본은 시각)")
    p.add_argument("--anomaly", action="store_true", help="전류·온도 임계 초과 주입")
    # **단절은 두 가지다 — 끊긴 자리가 다르면 값이 남는 자리도 다르다.**
    p.add_argument("--disconnect", type=int, default=None,
                   help="이 주기부터 **Gateway↔클라우드** 단절 — 폴링은 되고 적재만 안 된다 "
                        "→ IF_GATEWAY_BUFFER 에 쌓인다 (PLC 는 넘겼으므로 보냄 처리)")
    p.add_argument("--reconnect", type=int, default=None, help="이 주기에 복구 + 버퍼 재전송")
    p.add_argument("--plc-offline", type=int, default=None,
                   help="이 주기부터 **PLC↔Gateway** 단절 — 폴링 자체가 안 된다 "
                        "→ 값이 **PLC 레지스터에 미전송으로 남는다**")
    p.add_argument("--plc-online", type=int, default=None,
                   help="이 주기에 PLC 링크 복구 — 남아 있던 것이 그때 올라간다")
    p.add_argument("--realtime", action="store_true",
                   help="시간 앵커 대신 **실시각**으로 적재한다 (003·022 수집 배지 확인용)")
    p.add_argument("--dry-run", action="store_true", help="DB 에 쓰지 않고 payload 만 출력")
    # ── PLC 측 저장소 (D-174) ──
    p.add_argument("--plc-db", default=None,
                   help=f"PLC 레지스터 파일 (기본 {plcdb.DEFAULT_PATH.relative_to(ROOT)})")
    p.add_argument("--scan-only", action="store_true",
                   help="① PLC 스캔만 — 레지스터에 쓰고 멈춘다. Gateway 는 돌리지 않는다")
    p.add_argument("--poll-only", action="store_true",
                   help="② Gateway 폴링만 — PLC 에 쌓인 미전송분을 가져가 적재한다")
    p.add_argument("--via", choices=("inproc", "http"), default="inproc",
                   help="전달 경로. http 는 진짜 POST /api/ingest/plc (장비 인증을 지난다)")
    p.add_argument("--base-url", default=None, help="--via http 의 대상 (기본 localhost:포트)")
    p.add_argument("--plc-reset", action="store_true", help="PLC 파일을 지우고 시작한다")
    # ── 장비 IP 등록 (D-174) ──
    p.add_argument("--register", nargs="?", const=SIM_HOST_DEFAULT, default=None,
                   metavar="HOST", help="시뮬레이터 IP 를 장비에 등록 + 선언 (기본 127.0.0.1)")
    p.add_argument("--unregister", action="store_true", help="IP 와 선언을 함께 거둔다")
    p.add_argument("--plc-status", action="store_true", help="PLC 레지스터·미전송 현황만 본다")
    # ── 연속 모드 (D-222) ──
    p.add_argument("--daemon", action="store_true",
                   help="멈출 때까지 주기마다 생성·스캔·폴링·적재를 돈다 (벽시계 · 기본 --via http)")
    p.add_argument("--max-cycles", type=int, default=None, help="--daemon 을 이 주기 수에서 멈춘다 (시험용)")
    p.add_argument("--anomaly-rate", type=float, default=0.02,
                   help="--daemon 가동 주기당 알람 에피소드 시작 확률 (시뮬레이션 가정, 기본 0.02)")
    p.add_argument("--fault-every", type=int, default=0,
                   help="--daemon 에서 N 주기마다 Gateway↔클라우드 단절을 일으킨다 (0=안 함)")
    p.add_argument("--fault-len", type=int, default=3, help="단절 지속 주기 수 (기본 3) — 복구 시 버퍼 재전송")
    p.add_argument("--work-order", default=None, metavar="WO_NO",
                   help="현장POP 지정을 흉내 — 이 작업지시번호를 payload 에 싣는다 (서버가 검증, D-224)")
    p.add_argument("--start-work-order", default=None, metavar="WO_NO",
                   help="시험용: P40 작업지시를 진행 상태로 둔다 + 선언 (D-226)")
    p.add_argument("--finish-work-order", default=None, metavar="WO_NO",
                   help="시험용: 진행으로 뒀던 작업지시를 완료로 되돌리고 선언을 거둔다")
    a = p.parse_args()
    if a.daemon and "--via" not in sys.argv:
        a.via = "http"                     # 연속 모드는 기본이 진짜 HTTP 다 — 장비 인증까지 지난다

    # ── 단독 명령 ───────────────────────────────────────────────────────
    if a.start_work_order:
        start_work_order(a.start_work_order)
        return 0
    if a.finish_work_order:
        finish_work_order(a.finish_work_order)
        return 0
    if a.unregister:
        unregister_sim_ip()
        return 0
    if a.register is not None:
        register_sim_ip(a.register)
        return 0
    if a.plc_status:
        c = plcdb.connect(a.plc_db)
        plcdb.init(c)
        st = plcdb.stats(c)
        print(f"PLC 파일         {Path(a.plc_db or plcdb.DEFAULT_PATH)}")
        print(f"스캔 {st['scanned']} · 보냄 {st['sent']} · **미전송 {st['unsent']}**")
        for r in plcdb.registers(c):
            print(f"  {r['addr']}  {r['tag_name']:<15} {r['ko']:<5} "
                  f"{str(r['value'] or '-'):>12} {r['uom']:<7} {r['updated_dt'] or '-'}")
        print("  ※ 주소 `SIM-` 은 시뮬레이터 값이다 — 실물 태그맵은 도입기업 제공 (D-176)")
        return 0

    # **시각 기준과 데이터 출처는 다른 축이다.** `--realtime` 은 *언제로 적을지*를 바꿀 뿐,
    # 이 값이 시뮬레이터에서 나왔다는 사실을 바꾸지 않는다. 전에는 `--realtime` 이면
    # `COLLECT_PATH` 를 실수집 라벨(`PLC→Gateway→시계열DB`)로 적어서 **시뮬레이터 데이터가
    # 실수집과 구분되지 않았다**(D-195). 표지는 언제나 붙는다.
    path = collector.COLLECT_PATH_SIM
    if a.realtime:
        from datetime import datetime
        t0 = datetime.now().replace(microsecond=0) - timedelta(seconds=a.cycles * a.poll_sec)
        basis = "실시각 (--realtime) — **출처 표지는 그대로 시뮬레이터다**"
    else:
        t0 = clock.anchor()
        basis = f"시간 앵커 {t0.isoformat(sep=' ')} (§10-3 date.today() 금지)"

    rng = random.Random(a.seed if a.seed is not None else 20260911)
    dev = None if a.dry_run else device_id()
    base_url = a.base_url or f"http://127.0.0.1:{s.port}"
    if a.via == "http":
        check_loopback(base_url)      # **보낼 것이 0건이어도** 목적지는 먼저 따진다
    if a.plc_reset:
        print(f"PLC 초기화       {plcdb.reset(a.plc_db)}")
    pc = plcdb.connect(a.plc_db)
    plcdb.init(pc)
    print(f"수집 지점        레이저커팅기 1대 ({EQUIP_CODE}) — 현장POP(터치PC)는 수동 입력이다 (D-06)")
    print(f"기준 시각        {basis}")
    print(f"수집 주기        {a.poll_sec}초 · {a.cycles}주기 · 태그 {len(tags.TAGS)}종")
    print(f"PLC 레지스터     {_short(a.plc_db or plcdb.DEFAULT_PATH)} "
          f"(장비 메모리 — 우리 DB 가 아니다)")
    print(f"전달 경로        {a.via}" + (f" → {base_url}" if a.via == "http" else
                                        " (HTTP·장비 인증을 지나지 않는다)"))
    if a.daemon:
        return run_daemon(a, pc, dev, base_url, path)

    # ── ① PLC 스캔 — 레지스터에 쓴다. 아직 아무것도 보내지 않는다 ──────────
    scanned = 0
    if not a.poll_only:
        for i in range(a.cycles):
            samples = cycle_samples(t0, i, a.poll_sec, rng, a.anomaly)
            if a.dry_run:
                print(json.dumps([x.as_dict() for x in samples], ensure_ascii=False))
                continue
            scanned += plcdb.scan_write(pc, samples[0].collect_dt,
                                        {x.tag: x.value for x in samples})
        st = plcdb.stats(pc)
        print(f"① PLC 스캔      {scanned} 행 기록 → 미전송 {st['unsent']} "
              f"(**아직 아무것도 안 보냈다**)")
    if a.dry_run or a.scan_only:
        if a.scan_only:
            print("   `--poll-only` 로 Gateway 를 돌리면 그때 올라간다")
        return 0

    # ── ② Gateway 폴링 — 미전송분을 주기 단위로 가져가 적재한다 ────────────
    stored = dup = buffered = 0
    disconnected = False
    cycles = plcdb.group_by_cycle(plcdb.poll(pc))
    plc_held = 0
    plc_down = False
    for i, (dt, group) in enumerate(cycles):
        samples = [collector.Sample(g.tag_name, g.value, dt) for g in group]
        if a.disconnect is not None and i >= a.disconnect:
            disconnected = True
        if a.reconnect is not None and i >= a.reconnect:
            disconnected = False
        if a.plc_offline is not None and i >= a.plc_offline:
            plc_down = True
        if a.plc_online is not None and i >= a.plc_online:
            plc_down = False
        if plc_down:
            # ── PLC↔Gateway 단절 — **폴링 자체가 안 된다.**
            # `sent_yn` 을 건드리지 않는다: 값은 장비 메모리에 남고 링크가 살아나야 올라간다.
            # Gateway 버퍼에는 **넣지 않는다** — Gateway 는 이 값을 본 적도 없다.
            plc_held += 1
            continue
        if disconnected:
            # ── Gateway↔클라우드 단절 — 폴링은 **됐다.** 값은 Gateway 손에 있다.
            # 그래서 PLC 에서는 **보냄 처리**하고 Gateway 버퍼(TD5 IF_GATEWAY_BUFFER)가 진다.
            # 여기서 PLC 에도 남기면 같은 값을 둘이 들고 있게 되어 복구 때 **두 번 올라간다**.
            collector.buffer(dev, EQUIP_CODE, samples, "네트워크 단절", collect_path=path)
            plcdb.mark_sent(pc, [g.scan_id for g in group], dt)
            buffered += 1
            continue
        if a.via == "http":
            r = deliver_http(base_url, dev, samples, path)
            stored += int(r.get("stored", 0))
            dup += int(r.get("duplicated", 0))
            if not r.get("ordered", True):
                raise SystemExit("순서 보존 위반 — 수집 시각이 들어온 순서를 벗어났다")
        else:
            res = deliver_inproc(dev, samples, path)
            stored += res.stored
            dup += res.duplicated
            if not res.ordered:
                raise SystemExit("순서 보존 위반 — 수집 시각이 들어온 순서를 벗어났다")
        # **적재에 성공한 뒤에만** 보냄 표시. 먼저 찍으면 유실이 숨는다.
        plcdb.mark_sent(pc, [g.scan_id for g in group], dt)

    st = plcdb.stats(pc)
    delivered = len(cycles) - buffered - plc_held
    print(f"② Gateway 폴링   주기 {len(cycles)} 중 전달 {delivered} · "
          f"Gateway버퍼 {buffered} · PLC보류 {plc_held}")
    print(f"   PLC 잔량      스캔 {st['scanned']} · 보냄 {st['sent']} · "
          f"**미전송 {st['unsent']}**"
          + (" ← PLC↔Gateway 단절분이 장비에 남아 있다 (`--poll-only` 로 올린다)"
             if st['unsent'] else ""))
    if buffered and plc_held:
        print("   ※ 두 단절이 겹쳤다 — Gateway버퍼분과 PLC보류분은 **다른 값**이다. "
              "같은 값을 둘이 들고 있으면 복구 때 두 번 올라간다")

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
