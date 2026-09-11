#!/usr/bin/env python
"""G-12 수집 · G-13 전처리 (QA2).

원칙 (goal.md §2.2 · §10)
  · **수집 지점은 2개소뿐이다**(D-06) — 레이저커팅기 Master PLC 1 + 현장POP(터치PC) 1.
    **전 공정 실시간 수집을 전제한 코드가 있으면 결함이다.**
  · 게이트를 낮추지 않는다. 못 맞추면 `차단`, 못 재면 `판정 불가`.
  · **0건 경로와 N건 경로를 둘 다 명시 단언한다**(§10-4). `skip` 은 결함이다(D-62).
  · **정본 함수를 직접 부른다**(§10-16) — `ingest.tags` · `ingest.collector` ·
    `cad.inventory.clean` · `cad.pipeline` · `tools/plc_simulator.py`.
  · 이 검사기가 넣은 행은 **끝나고 전부 지운다**. 남기면 다른 QA 의 0건 경로 측정을 오염시킨다.

G-13 은 **결측·중복·이상치를 주입한 입력으로 전후를 비교**한다. 통과 여부를 묻지 말고
"그 코드가 있는가 · 처리 건수가 어디에 남는가" 를 실측한다.
"""
from __future__ import annotations

import dataclasses
import html as htmllib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                     # noqa: E402
from kyungdong.app import nav                                   # noqa: E402
from kyungdong.app.util import clock                            # noqa: E402
from kyungdong.cad import inventory as cadinv                   # noqa: E402
from kyungdong.cad import pipeline as cadpipe                   # noqa: E402
from kyungdong.ingest import collector, tags                    # noqa: E402

PASS, FAIL, BLOCKED, UNDET = "PASS", "FAIL", "차단", "판정 불가"
VERDICTS: list[tuple[str, str, str]] = []

WARM_CYCLES = 6                                   # ③-1 단절 없는 연속 수집
CYCLES, DISCONNECT, RECONNECT = 12, 8, 11        # ③-2 단절·복구
NUMERIC_TAGS = len(tags.numeric_tags())          # 시계열 적재 대상 태그 수
ALL_TAGS = len(tags.TAGS)

_TAG_RE = re.compile(r"<[^>]+>")


def say(s: str = "") -> None:
    print(s)


def verdict(gate: str, v: str, m: str) -> None:
    VERDICTS.append((gate, v, m))


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG_RE.sub(" ", fragment))).strip()


def one(sql: str, params=None) -> int:
    return int(conn.q1(f"select ({sql}) as n", params)["n"])


def maxid(table: str, col: str) -> int:
    return int(conn.q1(f"select coalesce(max({col}), 0) as n from {table}")["n"])


# ══ Phase 0 — 수집 지점 2개소뿐 (D-06) ═══════════════════════════════════
# 전 공정 실시간 수집을 전제한 코드의 흔적. 있으면 결함이다.
SEED_FILES = ("db/seed.py", "db/seed_dev1.py", "db/seed_dev2.py", "db/seed_dev3.py")
AUTO_TABLES = ("PRC_EQUIP_SIGNALS", "IF_PLC_SIGNALS", "DAT_TIMESERIES")


def check_two_points() -> tuple[int, list[str]]:
    say("── G-12-① 수집 지점 2개소뿐 (D-06) ────────────────────────────")
    bad: list[str] = []

    dev = conn.q("select DEVICE_ID, DEVICE_NAME, DEVICE_TYPE, PROTOCOL, USE_YN "
                 "from IF_DEVICE_REGISTRY order by DEVICE_ID")
    say(f"  IF_DEVICE_REGISTRY {len(dev)} 대")
    for d in dev:
        say(f"    #{d['device_id']} {d['device_name']} · {d['device_type']} · {d['protocol']}"
            f" · 사용 {d['use_yn']}")
    if len(dev) != 2:
        bad.append(f"수집 장비가 {len(dev)} 대다 — 사업계획서 2.7.1 데이터 집계 포인트는 2개소뿐이다(D-06)")

    eq = conn.q("select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
                "where CODE_GROUP = '설비' order by SORT_ORDER")
    say(f"  BAS_COMMON_CODES '설비' {len(eq)} 건: "
        + " · ".join(f"{e['code_value']} {e['code_name']}" for e in eq))
    if len(eq) != 2:
        bad.append(f"'설비' 코드가 {len(eq)} 건이다 — 2개소여야 한다(D-06)")

    # 시드가 수집 데이터를 흉내 내지 않는가 (자동 수집을 시드로 위조하면 G-12 가 무의미해진다)
    for rel in SEED_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        src = p.read_text()
        for t in AUTO_TABLES:
            if re.search(rf"insert\s+into\s+{t}\b", src, re.I):
                bad.append(f"{rel} 가 {t} 에 insert 한다 — 자동 수집을 흉내 낸 시드는 결함이다(D-06)")
    say("  시드가 수집 표(PRC_EQUIP_SIGNALS·IF_PLC_SIGNALS·DAT_TIMESERIES)에 insert: "
        f"{sum(1 for b in bad if 'insert' in b)} 건")

    # 자동 수집으로 기록된 공정실적이 레이저커팅(P40) 밖에 있으면 전 공정 수집을 전제한 것이다
    auto = conn.q("select PROCESS_CODE, count(*) as n from PRC_PERFORMANCES "
                  "where COLLECT_METHOD like '자동%' group by 1 order by 1")
    say("  자동(PLC) 수집으로 기록된 공정실적: "
        + (" · ".join(f"{a['process_code']} {a['n']}" for a in auto) or "0 건"))
    for a in auto:
        if a["process_code"] != "P40":
            bad.append(f"공정 {a['process_code']} 에 자동(PLC) 실적 {a['n']}건 — "
                       "자동 수집은 가공(레이저커팅 P40) 1지점뿐이다(D-06)")

    # 태그는 정본(사업계획서 2.7.1)이 적은 8종뿐
    say(f"  PLC 태그 {ALL_TAGS} 종 (정본 8종): " + " · ".join(t.name for t in tags.TAGS))
    if ALL_TAGS != 8:
        bad.append(f"태그가 {ALL_TAGS} 종이다 — 정본은 8종이다")

    for b in bad:
        say(f"    결함 {b}")
    say()
    return len(dev), bad


# ══ G-12 — 유실 0 · 순서 보존 · Gateway 재전송 무손실 · 화면 표시 ═════════
def gate_12() -> tuple[dict, list[str]]:
    n_dev, bad = check_two_points()

    base = {
        "IF_PLC_SIGNALS": (maxid("IF_PLC_SIGNALS", "PLC_IF_ID"), one("select count(*) from IF_PLC_SIGNALS")),
        "PRC_EQUIP_SIGNALS": (maxid("PRC_EQUIP_SIGNALS", "SIGNAL_ID"), one("select count(*) from PRC_EQUIP_SIGNALS")),
        "DAT_TIMESERIES": (maxid("DAT_TIMESERIES", "TS_ID"), one("select count(*) from DAT_TIMESERIES")),
        "IF_GATEWAY_BUFFER": (maxid("IF_GATEWAY_BUFFER", "BUFFER_ID"), one("select count(*) from IF_GATEWAY_BUFFER")),
    }
    clean_start = all(v[1] == 0 for v in base.values())

    say("── G-12-② 0건 경로 (수집 전) ─────────────────────────────────")
    say("  " + " · ".join(f"{k} {v[1]}행" for k, v in base.items()))
    zero_screens = screen_ingest_state()
    if clean_start:
        for path, info in zero_screens.items():
            ok = "미수집" in info["badges"] or "미수집" in info["body_head"]
            say(f"  {path}  미수집 문구 {'있음' if ok else '**없음**'} — 배지: {info['badges'][:90]}")
            if not ok:
                bad.append(f"{path}: 수집 0건인데 '미수집' 문구가 없다 (G-11·G-12)")
    else:
        say("  **0건 경로를 이 실행에서 재현하지 못했다** — 수집 표가 비어 있지 않다."
            " `make db-reset` 직후에 다시 돌린다 (skip 이 아니라 판정 불가로 남긴다)")
    say()

    # ── ③a 수집 **중단** 표시 — 앵커보다 오래된 수집 1배치로만 만든 상태 ──
    say("── G-12-③a 수집 중단 경로 (화면 003·022 에 마지막 수집시각 + 중단 상태) ──")
    stale_note = ""
    if clean_start:
        old_dt = clock.anchor() - timedelta(hours=2)
        collector.ingest_batch(
            int(conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                        ("레이저커팅기 PLC",))["device_id"]),
            "EQ10",
            [collector.Sample(t.name, "1" if t.numeric else "가동", old_dt) for t in tags.TAGS],
        )
        st_old = collector.status()
        scr = screen_ingest_state()
        for path, info in scr.items():
            has_ts = old_dt.strftime("%Y-%m-%d %H:%M") in info["text"]
            has_stale = "수집 중단" in info["badges"] or "수집 중단" in info["text"]
            say(f"  {path}  마지막 수집시각 {'있음' if has_ts else '**없음**'}"
                f" · '수집 중단' 표시 {'있음' if has_stale else '**없음**'}")
            if not has_ts:
                bad.append(f"{path}: 앵커보다 2시간 오래된 수집만 있는데 마지막 수집시각이 화면에 없다")
            if not has_stale:
                bad.append(f"{path}: 마지막 수집이 앵커 −2h 인데 '수집 중단' 상태 표시가 없다 (G-12)")
        stale_note = (f"collector.status() 중단 판정 {st_old['any_stale']}"
                      f" · 임계 {st_old['stale_sec']}초")
        say(f"  {stale_note}")
        for table, col in (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                           ("IF_PLC_SIGNALS", "PLC_IF_ID")):
            conn.x(f"delete from {table} where {col} > %s", (base[table][0],))
        say("  (중단 시나리오용 1배치는 지웠다 — 이어지는 측정의 분모를 흐리지 않는다)")
    else:
        say("  수집 표가 비어 있지 않아 중단 시나리오를 만들 수 없다 — **판정 불가**")
    say()

    say("── G-12-③ 시뮬레이터 수집 (유실 0 · 순서 보존 · Gateway 재전송) ──")
    say(f"  ③-1 연속 수집  uv run python tools/plc_simulator.py --cycles {WARM_CYCLES}")
    r0 = subprocess.run(
        ["uv", "run", "python", "tools/plc_simulator.py", "--cycles", str(WARM_CYCLES)],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    live_only = one("select count(*) from IF_PLC_SIGNALS") - base["IF_PLC_SIGNALS"][1]
    ord_live = one(
        "select count(*) from (select COLLECT_DT, lag(COLLECT_DT) over "
        "(partition by DEVICE_ID, TAG_NAME order by PLC_IF_ID) as prev "
        "from IF_PLC_SIGNALS where PLC_IF_ID > %s) x where prev is not null and COLLECT_DT < prev",
        (base["IF_PLC_SIGNALS"][0],))
    say(f"      적재 {live_only} / 기대 {WARM_CYCLES * ALL_TAGS} · **전역 순서 위반 {ord_live}** "
        "(단절이 없는 구간은 적재 순서 = 수집 시각 순서여야 한다)")
    if clean_start and live_only != WARM_CYCLES * ALL_TAGS:
        bad.append(f"연속 수집 적재 {live_only} ≠ {WARM_CYCLES * ALL_TAGS} — 유실/중복")
    if ord_live:
        bad.append(f"단절 없는 연속 수집에서 순서 위반 {ord_live}건")
    if r0.returncode != 0:
        bad.append(f"시뮬레이터(연속) exit {r0.returncode}")

    say(f"  ③-2 단절·복구  --cycles {CYCLES} --disconnect {DISCONNECT} --reconnect {RECONNECT}")
    r1 = subprocess.run(
        ["uv", "run", "python", "tools/plc_simulator.py", "--cycles", str(CYCLES),
         "--disconnect", str(DISCONNECT), "--reconnect", str(RECONNECT)],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    for ln in r1.stdout.strip().splitlines():
        say(f"    {ln}")
    if r1.returncode != 0:
        say(f"    stderr: {r1.stderr.strip()[:400]}")
        bad.append(f"시뮬레이터 exit {r1.returncode}")

    got = {
        "IF_PLC_SIGNALS": one("select count(*) from IF_PLC_SIGNALS") - base["IF_PLC_SIGNALS"][1],
        "PRC_EQUIP_SIGNALS": one("select count(*) from PRC_EQUIP_SIGNALS") - base["PRC_EQUIP_SIGNALS"][1],
        "DAT_TIMESERIES": one("select count(*) from DAT_TIMESERIES") - base["DAT_TIMESERIES"][1],
        "IF_GATEWAY_BUFFER": one("select count(*) from IF_GATEWAY_BUFFER") - base["IF_GATEWAY_BUFFER"][1],
    }
    want = {
        "IF_PLC_SIGNALS": CYCLES * ALL_TAGS,          # ③-1 의 6주기는 ③-2 에서 중복으로 걸러진다
        "PRC_EQUIP_SIGNALS": CYCLES,
        "DAT_TIMESERIES": CYCLES * NUMERIC_TAGS,
        "IF_GATEWAY_BUFFER": RECONNECT - DISCONNECT,
    }
    for k in want:
        if not clean_start:
            # 같은 앵커 구간이 이미 적재돼 있으면 전부 중복으로 걸러진다 — 유실이 아니다.
            say(f"  적재 {k:<20} 신규 {got[k]:>4} / 기대 {want[k]:>4}  **판정 불가** "
                "(검사 시작 시 수집 표가 비어 있지 않았다 — `make db-reset` 뒤에 다시 잰다)")
            continue
        mark = "일치" if got[k] == want[k] else "**불일치**"
        say(f"  적재 {k:<20} 신규 {got[k]:>4} / 기대 {want[k]:>4}  {mark}")
        if got[k] != want[k]:
            bad.append(f"{k}: 신규 {got[k]} ≠ 기대 {want[k]} — 유실 또는 중복")

    # 순서 보존 — store-and-forward 에서는 **구간별로** 본다.
    #   · 라이브 구간(단절 밖) 안에서 순서가 보존되는가
    #   · 재전송 구간(버퍼에 담겼던 것) 안에서 순서가 보존되는가
    # 재전송분이 라이브 뒤에 붙어 전역 PK 순서가 한 번 역전되는 것은 **설계상 정상**이다
    # (버퍼는 복구된 뒤에야 보낼 수 있다). 전역 위반만 세면 정상 동작을 결함으로 오판한다.
    bufs = conn.q("select BUFFER_ID, BUFFER_STATUS, RETRY_CNT, RESENT_DT, PAYLOAD "
                  "from IF_GATEWAY_BUFFER where BUFFER_ID > %s order by BUFFER_ID",
                  (base["IF_GATEWAY_BUFFER"][0],))
    buffered_dts = sorted({datetime.fromisoformat(s["collect_dt"])
                           for b in bufs for s in json.loads(b["payload"])["samples"]})
    dts_literal = ", ".join("%s" for _ in buffered_dts) or "null"
    seg_sql = (
        "select count(*) from (select COLLECT_DT, lag(COLLECT_DT) over "
        "(partition by DEVICE_ID, TAG_NAME order by PLC_IF_ID) as prev "
        f"from IF_PLC_SIGNALS where PLC_IF_ID > %s and COLLECT_DT {{op}} ({dts_literal})) x "
        "where prev is not null and COLLECT_DT < prev")
    params = (base["IF_PLC_SIGNALS"][0], *buffered_dts)
    ord_resent = one(seg_sql.format(op="in"), params) if buffered_dts else 0
    ord_livepart = one(seg_sql.format(op="not in"), params) if buffered_dts else 0
    ord_global = one(
        "select count(*) from (select COLLECT_DT, lag(COLLECT_DT) over "
        "(partition by DEVICE_ID, TAG_NAME order by PLC_IF_ID) as prev "
        "from IF_PLC_SIGNALS where PLC_IF_ID > %s) x where prev is not null and COLLECT_DT < prev",
        (base["IF_PLC_SIGNALS"][0],))
    dup = one(
        "select count(*) from (select DEVICE_ID, TAG_NAME, COLLECT_DT from IF_PLC_SIGNALS "
        "group by 1,2,3 having count(*) > 1) x")
    say(f"  순서 보존  라이브 구간 위반 {ord_livepart} · 재전송 구간 위반 {ord_resent} "
        f"· (참고) 전역 위반 {ord_global} = 복구 재전송이 라이브 뒤에 붙는 설계상 역전 "
        f"(태그 {ALL_TAGS}종 × 경계 1회)")
    say(f"  (장비,태그,수집시각) 중복 {dup}")
    if ord_livepart or ord_resent:
        bad.append(f"순서 보존 위반 — 라이브 {ord_livepart} · 재전송 {ord_resent}")
    if dup:
        bad.append(f"(장비,태그,수집시각) 중복 {dup}건 — 재전송이 행을 두 번 만들었다")

    # Gateway 버퍼 — 단절 구간이 전부 재전송됐는가 (무손실)
    buffered_samples = sum(len(json.loads(b["payload"])["samples"]) for b in bufs)
    resent = [b for b in bufs if b["buffer_status"] == "전송완료" and b["resent_dt"] is not None]
    say(f"  Gateway 버퍼 {len(bufs)} 배치 · 담긴 샘플 {buffered_samples} · "
        f"전송완료 {len(resent)} · 대기 {sum(1 for b in bufs if b['buffer_status'] == '대기')}")
    if len(resent) != len(bufs) or not bufs:
        bad.append(f"버퍼 재전송 미완: 배치 {len(bufs)} 중 전송완료 {len(resent)}")
    # 버퍼에 담긴 수집시각이 전부 적재됐는가 = **재전송 무손실**
    lost = 0
    for b in bufs:
        body = json.loads(b["payload"])
        for s in body["samples"]:
            if one("select count(*) from IF_PLC_SIGNALS where TAG_NAME = %s and COLLECT_DT = %s",
                   (s["tag"], datetime.fromisoformat(s["collect_dt"]))) == 0:
                lost += 1
    say(f"  재전송 무손실  버퍼 샘플 {buffered_samples} 중 적재 안 된 것 {lost} 건")
    if lost:
        bad.append(f"재전송 유실 {lost}건 — IF_GATEWAY_BUFFER 복구 경로가 무손실이 아니다")

    # 같은 배치를 한 번 더 — 무중복(멱등) 확인
    r2 = subprocess.run(
        ["uv", "run", "python", "tools/plc_simulator.py", "--cycles", str(CYCLES)],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    again = one("select count(*) from IF_PLC_SIGNALS") - base["IF_PLC_SIGNALS"][1]
    say(f"  재전송 중복 방지  같은 배치 재수집 후 총 신규 {again} (증가 {again - got['IF_PLC_SIGNALS']})")
    if again != got["IF_PLC_SIGNALS"]:
        bad.append(f"재수집이 행을 늘렸다 (+{again - got['IF_PLC_SIGNALS']}) — 중복 차단 실패")
    if r2.returncode != 0:
        bad.append(f"시뮬레이터 재실행 exit {r2.returncode}")
    say()

    # ── 단위 표준화 실측 (G-13 과 공유) — 적재된 UOM 이 태그 정본과 같은가 ──
    uom_bad = []
    for t in tags.numeric_tags():
        rows = conn.q("select distinct UOM from DAT_TIMESERIES where TAG_NAME = %s", (t.name,))
        found = sorted(r["uom"] or "" for r in rows)
        if found != [t.uom]:
            uom_bad.append(f"{t.name}: 적재 UOM {found} ≠ 정본 {t.uom!r}")

    # ── 화면 표시 (N건 경로) ────────────────────────────────────────
    say("── G-12-④ N건 경로 — 화면 `/dsh/003`·`/prc/022` 마지막 수집시각 + 상태 ──")
    last = conn.q1("select max(COLLECT_DT) as d from PRC_EQUIP_SIGNALS")["d"]
    st = collector.status()                     # 정본 함수 (§10-16) — **실시각 기준**
    say(f"  DB 마지막 수집시각 {last}")
    say(f"  collector.status() — 지점 {st['points']} · 중단 판정 {st['any_stale']}"
        f" · 임계 {st['stale_sec']}초 · 대기 버퍼 {st['buffer_pending']}")
    n_screens = screen_ingest_state()
    for path, info in n_screens.items():
        # 화면은 `routers/dsh.dt()` 기본 포맷 "%Y-%m-%d %H:%M" 으로 찍는다 — 초 단위를 요구하지 않는다
        shown = last is not None and last.strftime("%Y-%m-%d %H:%M") in info["text"]
        shown_short = last is not None and last.strftime("%H:%M:%S") in info["text"]
        say(f"  {path}  마지막 수집시각 표시 {'있음' if (shown or shown_short) else '**없음**'}"
            f" · 상태 배지: {info['badges'][:110]}")
        if not (shown or shown_short):
            bad.append(f"{path}: 수집 {got['PRC_EQUIP_SIGNALS']}건인데 마지막 수집시각이 화면에 없다 (G-12)")

    # 수집 중단 표시 — 두 구현이 서로 다른 시간축을 쓴다면 화면과 모듈 판정이 갈린다
    screen_stale = any("수집 중단" in i["badges"] or "수집 중단" in i["text"]
                       for i in n_screens.values())
    say(f"  '수집 중단' 배지 화면 {screen_stale} ↔ collector.status() 중단 판정 {st['any_stale']}")
    if screen_stale != st["any_stale"]:
        bad.append(
            "수집 중단 판정이 화면(routers/dsh.collection_badges — **앵커** 기준)과 "
            "수집 모듈(ingest.collector.status — **실시각** 기준)에서 갈린다. "
            "같은 사실에 대해 두 곳이 다른 답을 낸다 (§10-16 로직 복제)")
    say()

    # ── ③b 운영 시각(실시각) 데이터에서 '수집 중단' 배지가 뜰 수 있는가 ──
    say("── G-12-③b 실시각 수집에서 중단 배지 도달 가능성 ─────────────────")
    rrt = subprocess.run(
        ["uv", "run", "python", "tools/plc_simulator.py", "--cycles", "3", "--realtime"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    rt_last = conn.q1("select max(COLLECT_DT) as d from PRC_EQUIP_SIGNALS")["d"]
    rt_status = collector.status()
    rt_screens = screen_ingest_state()
    rt_screen_stale = any("수집 중단" in i["badges"] or "수집 중단" in i["text"]
                          for i in rt_screens.values())
    age_anchor = (clock.anchor() - rt_last).total_seconds() if rt_last else None
    say(f"  실시각 적재 마지막 {rt_last} · 앵커 기준 경과 {age_anchor:.0f}초 "
        f"(음수면 앵커보다 미래다 → 화면 배지는 영원히 뜨지 않는다)")
    say(f"  화면 '수집 중단' {rt_screen_stale} ↔ collector.status() 중단 {rt_status['any_stale']}")
    if rt_last is not None and age_anchor is not None and age_anchor < 0 and not rt_screen_stale:
        bad.append(
            "운영 시각(실시각)으로 수집하면 `COLLECT_DT > anchor()` 라 "
            "`routers/dsh.collection_badges()` 의 `anchor() - last_dt` 가 항상 음수다 → "
            "**003·022 의 '수집 중단' 배지가 구조적으로 뜰 수 없다** (G-12 요구 미충족)")
    if rrt.returncode != 0:
        say(f"  시뮬레이터(--realtime) exit {rrt.returncode}: {rrt.stderr.strip()[:200]}")
    say()

    verdict("G-12", (PASS if not bad else FAIL) if clean_start else UNDET,
            f"수집 지점 {n_dev}개소 · 적재 {got['IF_PLC_SIGNALS']}/{want['IF_PLC_SIGNALS']}행 "
            f"· 순서 위반 라이브 {ord_livepart}/재전송 {ord_resent} · 중복 {dup} "
            f"· 버퍼 {len(bufs)}배치 재전송 유실 {lost} "
            f"· 결함 {len(bad)}건")
    for b in bad:
        say(f"  결함 G-12 {b}")
    say()
    return base, uom_bad


def screen_ingest_state() -> dict[str, dict]:
    """`/dsh/003` · `/prc/022` 렌더 결과에서 배지·본문 문자열을 뽑는다."""
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    out: dict[str, dict] = {}
    for path in ("/dsh/003", "/prc/022"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        body = r.text if r.status_code == 200 else ""
        badges = " | ".join(
            text_of(b) for b in re.findall(r'<span class="badge[^"]*">(.*?)</span>', body, re.S))
        out[path] = {"status": r.status_code, "badges": badges,
                     "text": text_of(body), "body_head": text_of(body)[:400]}
    return out


# ══ G-13 전처리 — 주입한 입력으로 전후 비교 ═══════════════════════════════
REQUIRED_FEATURES = ("홀 수량", "절단 길이", "형상 복잡도", "두께", "재질", "용접 길이")


def gate_13(uom_bad: list[str]) -> None:
    say("── G-13 전처리 (단위 표준화·중복 제거·결측 보정·이상치 제거·Feature 생성) ──")
    bad: list[str] = []

    # ① 단위 표준화 — 코드(정본 태그표) + 적재 실측
    say(f"  ① 단위 표준화  ingest/tags.py 가 태그별 단위를 고정한다: "
        + " · ".join(f"{t.name}={t.uom or '-'}" for t in tags.TAGS))
    say(f"     적재 실측  DAT_TIMESERIES UOM 불일치 {len(uom_bad)} 건")
    for u in uom_bad:
        say(f"       {u}")
    bad += uom_bad

    # ② 중복 제거 — 도면번호+버전+고객사. **중복·0KB(이상치)를 주입해 전후 비교**
    files = cadinv.read_inventory()
    base_clean = cadinv.clean(files)
    base_kept = sum(1 for c in base_clean if c.keep)
    inject = [
        files[0],                                                    # 완전 중복 1
        files[0],                                                    # 완전 중복 2
        files[1],                                                    # 완전 중복 3
        dataclasses.replace(files[2], size_kb=0.0),                  # 이상치: 0KB 손상
        dataclasses.replace(files[3], mtime=None, file_name="QA2주입_결측발행일.dwg"),  # 결측
    ]
    inj_clean = cadinv.clean(list(files) + inject)
    inj_kept = sum(1 for c in inj_clean if c.keep)
    reasons = {}
    for c in inj_clean:
        if not c.keep:
            reasons[c.reason] = reasons.get(c.reason, 0) + 1
    say(f"  ② 중복 제거  주입 전 {len(files)}건 → 등록 {base_kept} · 제외 {len(files) - base_kept}")
    say(f"     주입 후 {len(files) + len(inject)}건 → 등록 {inj_kept} · 제외 "
        f"{len(files) + len(inject) - inj_kept}  (제외 사유 {reasons})")
    say(f"     DEDUP_KEY 규약 = 도면번호+버전+고객사. **고객사 메타데이터가 인벤토리에 없어** "
        f"제품 폴더명을 대체 축으로 쓴다 — `{cadinv.CUSTOMER_UNKNOWN}` (D-03)")
    dup_blocked = inj_kept - base_kept
    say(f"     주입한 중복 3 · 0KB 1 · 결측(mtime) 1 → 새로 등록된 것 {dup_blocked} 건 "
        f"(기대 1 = 결측 mtime 건만 통과)")
    if dup_blocked != 1:
        bad.append(f"중복·0KB 주입 후 등록 증가가 {dup_blocked} 건이다 (기대 1)")

    # ③ 결측 보정 — 치수 누락·OCR 오류·재질 미입력을 유사 도면·기준값으로 **보정**하는 코드
    mtime_missing = sum(1 for f in files if f.mtime is None)
    corrective = []
    for p in sorted((ROOT / "src").rglob("*.py")):
        src = p.read_text()
        if re.search(r"(impute|보정|대체값|fillna|유사\s*도면)", src):
            corrective.append(p.relative_to(ROOT).as_posix())
    say(f"  ③ 결측 보정  인벤토리 mtime 결측 {mtime_missing} 건 · "
        f"PLC 비숫자값은 `QUALITY_FLAG='결측'` 으로 **표시만** 하고 버리지 않는다")
    say(f"     보정(대체값 산출) 코드 후보: {corrective or '없음'}")
    if not corrective:
        bad.append("결측 **보정**(유사 도면·기준값으로 채우는) 코드가 없다 — "
                   "표시(플래그)만 있고 보정은 미구현이다 (D-05 Parsing·OCR 미구성)")

    # 결측 주입 전후 — 비숫자 값을 넣으면 '결측' 으로 남고 행이 사라지지 않는가
    miss_before = one("select count(*) from DAT_TIMESERIES where QUALITY_FLAG = '결측'")
    say(f"     DAT_TIMESERIES QUALITY_FLAG='결측' {miss_before} 건 (주입 전)")

    # ④ 이상치 제거
    # '노이즈' 가 **어휘로만** 있는지, 실제로 적재 경로가 쓰는지를 나눠서 본다.
    vocab_only, writers = [], []
    for p in sorted((ROOT / "src").rglob("*.py")):
        src = p.read_text()
        if "노이즈" not in src:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if re.search(r"insert\s+into\s+DAT_TIMESERIES", src, re.I) or \
           re.search(r"QUALITY_FLAG\s*=\s*['\"]?노이즈", src):
            writers.append(rel)
        else:
            vocab_only.append(rel)
    noise_rows = one("select count(*) from DAT_TIMESERIES where QUALITY_FLAG = '노이즈'")
    say(f"  ④ 이상치 제거  QUALITY_FLAG='노이즈' 행 {noise_rows} 건")
    say(f"     '노이즈' 를 **어휘로만** 가진 파일 {vocab_only}")
    say(f"     '노이즈' 를 실제로 **적재하는** 코드 {writers or '없음'}")
    writes_noise = bool(writers)
    if not writes_noise:
        bad.append("이상치를 걸러 `QUALITY_FLAG='노이즈'` 로 남기거나 제거하는 코드가 없다 — "
                   "어휘만 정의돼 있고 판정 로직이 없다")
    # 이상치 주입 — 시뮬레이터 --anomaly 로 전류·온도 임계 초과를 넣고 전후를 본다
    before = one("select count(*) from DAT_TIMESERIES")
    hi_before = one("select count(*) from DAT_TIMESERIES "
                    "where TAG_NAME = 'CURRENT_VALUE' and MEASURE_VALUE > 40")
    r = subprocess.run(["uv", "run", "python", "tools/plc_simulator.py",
                        "--cycles", "14", "--anomaly", "--seed", "20260912"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    after = one("select count(*) from DAT_TIMESERIES")
    hi_after = one("select count(*) from DAT_TIMESERIES "
                   "where TAG_NAME = 'CURRENT_VALUE' and MEASURE_VALUE > 40")
    noise_after = one("select count(*) from DAT_TIMESERIES where QUALITY_FLAG = '노이즈'")
    say(f"     이상치 주입(--anomaly) 전후: 시계열 {before}→{after} · "
        f"전류 40A 초과 {hi_before}→{hi_after} · '노이즈' 플래그 {noise_rows}→{noise_after}")
    if hi_after > hi_before and noise_after == noise_rows:
        bad.append(f"임계 초과값 {hi_after - hi_before}건이 그대로 적재됐는데 "
                   "'노이즈' 플래그도 제거도 없다 — 이상치 처리 부재")
    if r.returncode != 0:
        say(f"     시뮬레이터 exit {r.returncode}: {r.stderr.strip()[:200]}")

    # ⑤ Feature 생성 6종
    say(f"  ⑤ Feature 생성  게이트 요구 6종: {' · '.join(REQUIRED_FEATURES)}")
    say(f"     TD5 `EST_CAD_FEATURES.FEATURE_TYPE` 어휘: {' · '.join(cadpipe.FEATURE_TYPES)}")
    say(f"     코드로 산출 가능: {sorted(cadpipe.DERIVABLE)}")
    for k, why in sorted(cadpipe.BLOCKED_FEATURES.items()):
        say(f"     차단 {k}: {why}")
    alias = {"절단 길이": "총 절단장", "용접 길이": "용접장"}
    missing_vocab = [f for f in REQUIRED_FEATURES
                     if alias.get(f, f) not in cadpipe.FEATURE_TYPES]
    derivable = [f for f in REQUIRED_FEATURES if alias.get(f, f) in cadpipe.DERIVABLE]
    say(f"     TD5 어휘에도 없는 요구 Feature: {missing_vocab or '없음'}")
    say(f"     6종 중 실제 산출 코드가 있는 것 {len(derivable)}종 {derivable}")
    if len(derivable) < len(REQUIRED_FEATURES):
        bad.append(f"Feature 6종 중 {len(REQUIRED_FEATURES) - len(derivable)}종이 산출 불가 — "
                   f"{[f for f in REQUIRED_FEATURES if f not in derivable]}")
    feat_rows = one("select count(*) from EST_CAD_FEATURES")
    say(f"     EST_CAD_FEATURES {feat_rows} 행 (확정 객체 0건이면 Feature 도 0건이다)")

    # ⑥ 처리 건수가 DAT_JOB_LOGS · DAT_PREPROCESS_RULES 에 남는가
    rules = conn.q("select RULE_NAME, RULE_STAGE, APPLY_ORDER from DAT_PREPROCESS_RULES "
                   "order by APPLY_ORDER")
    jobs = conn.q("select j.JOB_ID, s.SOURCE_NAME, "
                  "(select count(*) from DAT_JOB_LOGS g where g.JOB_ID = j.JOB_ID) as logs "
                  "from DAT_INTEGRATION_JOBS j join DAT_SOURCES s on s.SOURCE_ID = j.SOURCE_ID "
                  "order by j.JOB_ID")
    jl = one("select count(*) from DAT_JOB_LOGS")
    cadlogs = one("select count(*) from IF_CAD_IMPORT_LOGS")
    say(f"  ⑥ 처리 건수 기록  DAT_PREPROCESS_RULES {len(rules)} 건: "
        + " · ".join(f"{r['apply_order']} {r['rule_name']}({r['rule_stage']})" for r in rules))
    say(f"     DAT_JOB_LOGS {jl} 건 · 통합작업 {len(jobs)} 건 · IF_CAD_IMPORT_LOGS {cadlogs} 건")
    say("     `DAT_PREPROCESS_RULES` 에는 **처리 건수 컬럼이 없다**(TD5 10컬럼: 규칙 정의뿐). "
        "전처리 실행 건수는 `DAT_JOB_LOGS.PROCESS_CNT` 에 남아야 한다")
    writes_joblog = [
        p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "src").rglob("*.py"))
        if re.search(r"insert\s+into\s+DAT_JOB_LOGS", p.read_text(), re.I)]
    writes_joblog += [
        p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "tools").rglob("*.py"))
        if not p.name.startswith("check_")
        and re.search(r"insert\s+into\s+DAT_JOB_LOGS", p.read_text(), re.I)]
    say(f"     DAT_JOB_LOGS 에 쓰는 코드: {writes_joblog or '없음'}")
    if not any("cad" in w or "ingest" in w for w in writes_joblog):
        bad.append("CAD 정제·PLC 수집 전처리의 처리 건수가 `DAT_JOB_LOGS` 에 남지 않는다 — "
                   "쓰는 곳은 `routers/dat.py`(ERP 통합작업 POST) 하나뿐이다 (G-13 요구 미충족)")

    say()
    verdict("G-13", PASS if not bad else FAIL,
            f"단위 표준화 위반 {len(uom_bad)} · 중복 제거 주입 후 신규등록 {dup_blocked}(기대 1) · "
            f"결측 보정 코드 {'있음' if corrective else '없음'} · "
            f"이상치 처리 {'있음' if writes_noise else '없음'} · "
            f"Feature {len(derivable)}/{len(REQUIRED_FEATURES)}종 · 결함 {len(bad)}건")
    for b in bad:
        say(f"  결함 G-13 {b}")
    say()


def cleanup(base: dict) -> None:
    """이 검사기가 넣은 행을 **전부 지운다**. 남기면 다른 QA 의 0건 경로가 오염된다."""
    say("── 정리 (검사기가 넣은 행만 삭제) ────────────────────────────")
    for table, col in (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                       ("IF_GATEWAY_BUFFER", "BUFFER_ID"), ("IF_PLC_SIGNALS", "PLC_IF_ID")):
        n = conn.x(f"delete from {table} where {col} > %s", (base[table][0],))
        left = one(f"select count(*) from {table}")
        say(f"  {table:<20} 삭제 {n:>4} · 남은 {left} (검사 전 {base[table][1]})")
        if left != base[table][1]:
            say(f"    **검사 전 상태로 돌아가지 않았다** — 남은 행을 확인한다")
    say()


def main() -> int:
    if conn.table_count() != 68:
        say(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-reset`")
        return 1
    try:
        a = clock.anchor()
    except RuntimeError as e:
        say(f"시간 앵커가 없다: {e}")
        return 1

    say("경동글로벌텍 제조AI — G-12 수집 · G-13 전처리 (QA2)")
    say(f"시간 앵커 {a.isoformat(sep=' ')} · 수집 지점 2개소뿐 (D-06)")
    say()
    base, uom_bad = gate_12()
    gate_13(uom_bad)
    cleanup(base)

    say("═══ 판정표 (게이트별 — §10-6) ═══")
    for gate, v, m in VERDICTS:
        say(f"{gate:<6} {v:<8} {m}")
    say()
    say(" · ".join(f"{g} {v}" for g, v, _m in VERDICTS))
    return 0 if all(v == PASS for _g, v, _m in VERDICTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
