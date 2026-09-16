"""PLC 수집 → MES 연계 (D-224 · D-225) — **신호를 작업지시에 붙이고, 실적을 도출하고, 알람을 올린다.**

수집(`collector.ingest_batch`)은 태그 8종을 `IF_PLC_SIGNALS` → `PRC_EQUIP_SIGNALS` · `DAT_TIMESERIES`
에 적재하는 데서 끝났다. TD5 가 그 다음을 이미 적어 두었다:

  · `PRC_EQUIP_SIGNALS.WORK_ORDER_ID` (FK: PRC_WORK_ORDERS) — 신호가 **어느 작업지시**의 것인가
  · `PRC_PERFORMANCES.COLLECT_METHOD = '자동(PLC)'` — 레이저커팅 실적은 PLC 가 만든다 (D-06)
  · `AGT_RECOMMENDATIONS(RECO_TYPE='알림추천')` — 041 알림 화면이 읽는 자리 (TD4-003 fn2 · TD4-022 fn2)

이 모듈은 그 세 자리를 채운다. **한 트랜잭션 안에서** 부른다 — 적재는 됐는데 연계만 빠진 상태를 남기지 않는다.

## ① 작업지시 매핑 — PLC 신호만으로는 어느 지시인지 알 수 없다

PLC 는 수량·상태·전류를 내지 작업지시번호를 내지 않는다. 지시번호는 **현장POP(두 번째 수집 지점)에서
사람이 고른다.** 그래서 규칙은 둘이다.

  1. 수집 payload 가 `work_order_id` 를 실어 오면(현장POP 지정) — **검증하고** 쓴다.
     가공(레이저커팅) `P40` 이어야 하고, 외주가 아니어야 하고, `완료` 가 아니어야 한다. 아니면 422.
  2. 안 실어 오면 — **진행 중인 P40 사내 작업지시가 정확히 1건**일 때만 그것으로 본다.
     0건이면 붙일 곳이 없고, 2건 이상이면 **고르지 않는다** (어느 것인지 지어내는 것이다).
     둘 다 `WORK_ORDER_ID` 는 NULL 로 남고, 이유가 화면 003·022 실시간 패널에 그대로 뜬다.

## ② 자동 실적 — 저장이 아니라 **도출**이다

`PRC_PERFORMANCES` 의 자동 행은 매핑된 신호에서 **매번 다시 계산**한다 (작업지시 × 수집일 1행).
  START_DT = 첫 신호 · END_DT = 마지막 신호 · GOOD_QTY = Σ PRODUCE_QTY · ACTUAL_MANHOUR = Σ RUN_MINUTE / 60.
같은 배치를 두 번 보내도 신호가 중복 적재되지 않으므로(collector) 실적도 두 배가 되지 않는다.
**DEFECT_QTY 는 비운다** — PLC 는 양·불을 판정하지 않는다. 불량은 검사(품질 담당)가 정한다.

## ③ 알람 — 장비가 낸 것만 올린다

가동상태가 `알람` 인 신호가 **새 에피소드**(직전 신호는 알람이 아니었다)를 열 때 `AGT_RECOMMENDATIONS`
에 `알림추천` 1행을 넣는다(코드 칸은 자유 문자열이라 상태 어휘로 판정한다). 연속 알람 주기마다 넣으면 041 이 같은 알람으로 도배된다.
**임계값 비교는 하지 않는다** — `PRC_STD_CONDITIONS` 가 0건이고(도입기업 제공, D-59) `SYS_CONFIGS`
알림기준 `ALERT_EQUIP` 도 "임계값 미확정" 이다. 임계를 지어내 알림을 만들지 않는다 (D-225).
표준조건이 들어오면 `threshold_check()` 가 그 값으로 편차를 낸다 — 지금은 `blocked` 를 돌려준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

import conn

from ..app.util import http
from . import tags

AUTO_PROCESS = "P40"                    # 가공(레이저커팅) — 자동 수집 대상 1공정 (D-06)
AUTO_EQUIP = "EQ10"                     # 레이저커팅기 — 신호를 내는 설비
METHOD_AUTO = "자동(PLC)"                # TD5 PRC_PERFORMANCES.COLLECT_METHOD 어휘
ALERT_RECO = "알림추천"                  # TD5 AGT_RECOMMENDATIONS.RECO_TYPE — 041 이 읽는 값
REVIEW_INITIAL = "미검토"
STD_COND_DECISION = "D-59"              # 표준 작업조건 초기값 — 도입기업 제공
THRESHOLD_DECISION = "D-225"

# 표준조건 항목명 ↔ PLC 태그. TD3 023 목업이 적은 항목명('절단속도')과 태그 한글명을 함께 받는다.
COND_ITEM_TO_TAG: dict[str, str] = {
    "절단속도": "SPEED_VALUE", "속도": "SPEED_VALUE",
    "압력": "PRESSURE_VALUE",
    "전류": "CURRENT_VALUE", "용접전류": "CURRENT_VALUE",
    "온도": "TEMP_VALUE",
}


@dataclass
class MesLink:
    """한 배치의 연계 결과 — 화면과 API 응답이 그대로 보여 준다."""
    work_order_id: int | None = None
    work_order_no: str | None = None
    project_no: str | None = None
    reason: str = ""                     # 매핑을 못 했으면 왜
    explicit: bool = False               # 현장POP 지정이었나
    attached_rows: int = 0               # WORK_ORDER_ID 를 채운 PRC_EQUIP_SIGNALS 행
    perf_id: int | None = None
    perf_good_qty: float | None = None
    perf_run_minute: float | None = None
    alerts: list[int] = field(default_factory=list)   # 새로 올린 AGT_RECOMMENDATIONS.RECO_ID

    def as_dict(self) -> dict[str, Any]:
        return {"work_order_id": self.work_order_id, "work_order_no": self.work_order_no,
                "project_no": self.project_no, "reason": self.reason, "explicit": self.explicit,
                "attached_rows": self.attached_rows, "perf_id": self.perf_id,
                "perf_good_qty": self.perf_good_qty, "perf_run_minute": self.perf_run_minute,
                "alerts": list(self.alerts)}


# ── ① 작업지시 매핑 ────────────────────────────────────────────────────────
_WO_SQL = ("select w.WORK_ORDER_ID, w.WORK_ORDER_NO, w.PROCESS_CODE, w.ORDER_STATUS, "
           "w.OUTSOURCE_YN, pj.PROJECT_NO "
           "from PRC_WORK_ORDERS w join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID ")


def validate_work_order(cur: Any, work_order_id: int) -> dict[str, Any]:
    """현장POP 이 지정한 작업지시를 검증한다. 어긋나면 **422** — 조용히 NULL 로 두지 않는다."""
    cur.execute(_WO_SQL + "where w.WORK_ORDER_ID = %s", (work_order_id,))
    wo = cur.fetchone()
    if wo is None:
        raise http.fail("validation", f"작업지시 {work_order_id} 가 없다")
    if wo["process_code"] != AUTO_PROCESS:
        raise http.fail("validation",
                        f"자동(PLC) 수집은 가공(레이저커팅) {AUTO_PROCESS} 1공정뿐이다 — "
                        f"{wo['work_order_no']} 는 {wo['process_code']} 다 (D-06)")
    if wo["outsource_yn"] == "Y":
        raise http.fail("validation",
                        f"{wo['work_order_no']} 는 외주 작업지시다 — 실적이 아니라 반출·반입 상태다 (D-41)")
    if wo["order_status"] == "완료":
        raise http.fail("validation",
                        f"{wo['work_order_no']} 는 이미 완료된 작업지시다 — 신호를 붙일 수 없다")
    return dict(wo)


def active_work_orders(cur: Any) -> list[dict[str, Any]]:
    """지금 레이저커팅기가 하고 있을 수 있는 작업지시 — `진행` 상태의 P40 사내 지시."""
    cur.execute(_WO_SQL + "where w.PROCESS_CODE = %s and w.OUTSOURCE_YN = 'N' "
                "and w.ORDER_STATUS = '진행' order by w.WORK_ORDER_ID", (AUTO_PROCESS,))
    return [dict(r) for r in cur.fetchall()]


def resolve(cur: Any, equip_code: str, explicit_id: int | None) -> MesLink:
    """배치가 붙을 작업지시를 정한다. **고를 수 없으면 고르지 않는다.**"""
    if equip_code != AUTO_EQUIP:
        return MesLink(reason=f"자동 실적 연계 대상은 레이저커팅기({AUTO_EQUIP})뿐이다 (D-06) — "
                              f"{equip_code} 신호는 작업지시에 붙이지 않는다")
    if explicit_id is not None:
        wo = validate_work_order(cur, explicit_id)
        return MesLink(int(wo["work_order_id"]), wo["work_order_no"], wo["project_no"],
                       reason="현장POP 지정", explicit=True)
    cands = active_work_orders(cur)
    if len(cands) == 1:
        wo = cands[0]
        return MesLink(int(wo["work_order_id"]), wo["work_order_no"], wo["project_no"],
                       reason="진행 중 레이저커팅 작업지시 1건 — 자동 매핑")
    if not cands:
        return MesLink(reason="작업지시 미매핑 — 진행 중(ORDER_STATUS='진행')인 레이저커팅 "
                              f"{AUTO_PROCESS} 작업지시가 0건이다. 현장POP 에서 지시를 지정하거나 "
                              "작업지시를 진행 상태로 둔다")
    nos = ", ".join(c["work_order_no"] for c in cands[:5])
    return MesLink(reason=f"작업지시 미매핑 — 진행 중 레이저커팅 작업지시가 {len(cands)}건"
                          f"({nos}{' …' if len(cands) > 5 else ''})이라 PLC 신호만으로는 어느 "
                          "지시인지 알 수 없다. 현장POP 에서 지정해야 한다 (지어내지 않는다)")


def attach(cur: Any, equip_code: str, collect_dts: Sequence[datetime], work_order_id: int) -> int:
    """이 배치의 `PRC_EQUIP_SIGNALS` 행에 작업지시를 적는다. 이미 다른 지시가 적힌 행은 건드리지 않는다."""
    if not collect_dts:
        return 0
    cur.execute(
        "update PRC_EQUIP_SIGNALS set WORK_ORDER_ID = %s "
        "where EQUIP_CODE = %s and WORK_ORDER_ID is null and COLLECT_DT = any(%s)",
        (work_order_id, equip_code, list(collect_dts)))
    return int(cur.rowcount or 0)


# ── ② 자동 실적 도출 ──────────────────────────────────────────────────────
def refresh_auto_performance(cur: Any, work_order_id: int, day: datetime) -> tuple[int, float, float]:
    """작업지시 × 수집일의 자동 실적 1행을 신호에서 **다시 계산**한다. 반환 (PERF_ID, 실적수량, 가동분).

    신호가 0건이면 실적을 만들지 않는다 — 0 을 적는 것도 '있다' 는 뜻이 되기 때문이다.
    """
    d0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    cur.execute(
        "select min(COLLECT_DT) as s, max(COLLECT_DT) as e, "
        "coalesce(sum(PRODUCE_QTY), 0) as qty, coalesce(sum(RUN_MINUTE), 0) as mins, count(*) as n "
        "from PRC_EQUIP_SIGNALS where WORK_ORDER_ID = %s and EQUIP_CODE = %s "
        "and COLLECT_DT >= %s and COLLECT_DT < %s + interval '1 day'",
        (work_order_id, AUTO_EQUIP, d0, d0))
    agg = cur.fetchone()
    if not agg or int(agg["n"] or 0) == 0:
        raise RuntimeError("매핑된 신호가 0건인데 실적을 도출하려 했다 — 호출 순서가 틀렸다")
    qty, mins = float(agg["qty"]), float(agg["mins"])
    manhour = round(mins / 60.0, 2)
    cur.execute("select LOT_TRACE_ID from SHP_LOT_TRACES where WORK_ORDER_ID = %s "
                "order by LOT_TRACE_ID limit 1", (work_order_id,))
    lot = cur.fetchone()
    lot_id = int(lot["lot_trace_id"]) if lot else None
    cur.execute(
        "select PERF_ID from PRC_PERFORMANCES where WORK_ORDER_ID = %s and COLLECT_METHOD = %s "
        "and START_DT >= %s and START_DT < %s + interval '1 day' order by PERF_ID limit 1",
        (work_order_id, METHOD_AUTO, d0, d0))
    row = cur.fetchone()
    if row:
        perf_id = int(row["perf_id"])
        cur.execute(
            "update PRC_PERFORMANCES set START_DT = %s, END_DT = %s, GOOD_QTY = %s, "
            "ACTUAL_MANHOUR = %s, LOT_TRACE_ID = coalesce(LOT_TRACE_ID, %s), UPDATED_DT = now() "
            "where PERF_ID = %s", (agg["s"], agg["e"], qty, manhour, lot_id, perf_id))
    else:
        # DEFECT_QTY·DEFECT_TYPE 은 비운다 — PLC 는 양·불을 판정하지 않는다. WORKER_ID 도 없다(장비다).
        cur.execute(
            "insert into PRC_PERFORMANCES (WORK_ORDER_ID, LOT_TRACE_ID, PROCESS_CODE, START_DT, END_DT, "
            "GOOD_QTY, ACTUAL_MANHOUR, COLLECT_METHOD, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s, now()) returning PERF_ID",
            (work_order_id, lot_id, AUTO_PROCESS, agg["s"], agg["e"], qty, manhour, METHOD_AUTO))
        perf_id = int(cur.fetchone()["perf_id"])
    return perf_id, qty, mins


# ── ③ 알람 → 041 알림 ──────────────────────────────────────────────────────
# 알람 에피소드 = **가동상태가 `알람`** 인 신호 구간 (TD5 RUN_STATUS 어휘 `가동/정지/대기/알람`).
# ALARM_CODE 만으로 판정하지 않는다 — 코드 칸은 자유 문자열이라 장비·시험 데이터가 아무 값이나 담을 수
# 있고, 상태가 알람이 아닌데 코드만 남은 행(해제 뒤 잔존)을 새 알림으로 올리면 041 이 거짓 경보로 찬다.
ALARM_STATE = "알람"


def _is_alarm(row: Any) -> bool:
    return bool(row) and str(row["run_status"] or "") == ALARM_STATE


def _alarm_before(cur: Any, equip_code: str, dt: datetime) -> bool:
    """직전 신호가 알람이었나 — 같은 에피소드면 알림을 또 만들지 않는다."""
    cur.execute("select RUN_STATUS from PRC_EQUIP_SIGNALS where EQUIP_CODE = %s and COLLECT_DT < %s "
                "order by COLLECT_DT desc limit 1", (equip_code, dt))
    return _is_alarm(cur.fetchone())


def raise_alarms(cur: Any, equip_code: str, collect_dts: Sequence[datetime],
                 link: MesLink) -> list[int]:
    """이 배치에서 **새로 시작된** 알람 에피소드마다 `알림추천` 1행. 장비가 낸 상태·코드만 쓴다."""
    if not collect_dts:
        return []
    cur.execute(
        "select COLLECT_DT, ALARM_CODE, RUN_STATUS, CURRENT_VALUE, TEMP_VALUE, SPEED_VALUE, PRESSURE_VALUE "
        "from PRC_EQUIP_SIGNALS where EQUIP_CODE = %s and COLLECT_DT = any(%s) "
        "and RUN_STATUS = %s order by COLLECT_DT",
        (equip_code, list(collect_dts), ALARM_STATE))
    rows = cur.fetchall()
    made: list[int] = []
    in_episode: bool | None = None
    for r in rows:
        if in_episode is None:
            in_episode = _alarm_before(cur, equip_code, r["collect_dt"])
        if in_episode:
            continue
        in_episode = True
        target = ("작업지시", link.work_order_id) if link.work_order_id else (None, None)
        summary = (f"레이저커팅기 알람 {r['alarm_code'] or '(코드 없음)'} — {r['collect_dt']:%Y-%m-%d %H:%M:%S} "
                   f"(가동상태 {r['run_status'] or '-'}"
                   + (f" · 작업지시 {link.work_order_no}" if link.work_order_no else " · 작업지시 미매핑")
                   + ")")
        evidence = {"equip_code": equip_code, "alarm_code": r["alarm_code"],
                    "collect_dt": r["collect_dt"].isoformat(),
                    "values": {k: (float(r[k]) if r[k] is not None else None)
                               for k in ("current_value", "temp_value", "speed_value", "pressure_value")},
                    "threshold": f"임계 비교 없음 — 표준 작업조건 미확정 ({STD_COND_DECISION} · {THRESHOLD_DECISION}). "
                                 "장비가 낸 알람 코드다"}
        import json as _json
        cur.execute(
            "insert into AGT_RECOMMENDATIONS (RECO_TYPE, TARGET_TYPE, TARGET_ID, SUMMARY_TEXT, "
            "RECOMMEND_VALUE, EVIDENCE_JSON, REVIEW_STATUS, CREATED_AT_DT, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s, now()) returning RECO_ID",
            (ALERT_RECO, target[0], target[1], summary,
             "현장 확인 — 설비 상태·작업조건 점검 (AI 는 경고까지, 조치는 사람이 한다)",
             _json.dumps(evidence, ensure_ascii=False), REVIEW_INITIAL, r["collect_dt"]))
        made.append(int(cur.fetchone()["reco_id"]))
    # 배치 안에서 알람이 끊겼다가 다시 시작하는 경우는 드물고, 주기 단위 배치에서는 같은 에피소드다.
    return made


# ── 임계 비교 — 표준조건이 있을 때만 (D-225) ─────────────────────────────────
def threshold_check(values: dict[str, float | None]) -> dict[str, Any]:
    """`PRC_STD_CONDITIONS(P40)` 대비 편차. 표준조건이 없으면 **`blocked`** — 임계를 지어내지 않는다."""
    rows = conn.q(
        "select COND_ITEM, STD_VALUE, TOL_MIN, TOL_MAX, UOM from PRC_STD_CONDITIONS "
        "where PROCESS_CODE = %s and USE_YN = 'Y' order by STD_COND_ID", (AUTO_PROCESS,))
    if not rows:
        return {"blocked": True,
                "note": f"임계 비교 불가 — 가공(레이저커팅) 표준 작업조건 0건 "
                        f"(초기값은 도입기업 제공 · {STD_COND_DECISION}). "
                        f"알림기준 ALERT_EQUIP 도 '임계값 미확정' 이다 ({THRESHOLD_DECISION})",
                "items": []}
    items = []
    for r in rows:
        tag = COND_ITEM_TO_TAG.get(str(r["cond_item"]).strip())
        v = values.get(tag) if tag else None
        lo = float(r["tol_min"]) if r["tol_min"] is not None else None
        hi = float(r["tol_max"]) if r["tol_max"] is not None else None
        out = None if v is None else ((lo is not None and v < lo) or (hi is not None and v > hi))
        items.append({"cond_item": r["cond_item"], "tag": tag, "std": float(r["std_value"]),
                      "tol_min": lo, "tol_max": hi, "uom": r["uom"], "actual": v,
                      "out_of_tol": out,
                      "note": None if tag else "표준조건 항목명이 PLC 태그 8종과 맞지 않는다"})
    return {"blocked": False, "note": f"표준 작업조건 {len(rows)}건 대비", "items": items}


# ── 진입점 — collector 가 한 트랜잭션 안에서 부른다 ────────────────────────
def link_batch(cur: Any, equip_code: str, collect_dts: Sequence[datetime],
               explicit_work_order_id: int | None = None) -> MesLink:
    link = resolve(cur, equip_code, explicit_work_order_id)
    if link.work_order_id is not None and collect_dts:
        link.attached_rows = attach(cur, equip_code, collect_dts, link.work_order_id)
        # 자동 실적은 배치가 걸친 날짜마다 다시 도출한다 (보통 하루다).
        days = sorted({d.date() for d in collect_dts})
        for day in days:
            pid, qty, mins = refresh_auto_performance(
                cur, link.work_order_id, datetime(day.year, day.month, day.day))
            link.perf_id, link.perf_good_qty, link.perf_run_minute = pid, qty, mins
    link.alerts = raise_alarms(cur, equip_code, collect_dts, link)
    return link


# ── 실시간 스냅샷 — 화면 003·022 패널과 `GET /api/ingest/live` 가 같은 값을 본다 ──
def live_snapshot(equip_code: str = AUTO_EQUIP, recent: int = 30) -> dict[str, Any]:
    """지금 레이저커팅기가 어떤 상태인지 — **DB 에 적재된 것만** 말한다. 값을 만들지 않는다."""
    from ..app.util import clock, device
    from . import collector

    recent = max(1, min(int(recent), 200))
    st = collector.status()
    now = st["checked_at"]
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last = conn.q1(
        "select s.SIGNAL_ID, s.COLLECT_DT, s.RUN_STATUS, s.RUN_MINUTE, s.PRODUCE_QTY, s.SPEED_VALUE, "
        "s.PRESSURE_VALUE, s.CURRENT_VALUE, s.TEMP_VALUE, s.ALARM_CODE, s.WORK_ORDER_ID, "
        "w.WORK_ORDER_NO, pj.PROJECT_NO "
        "from PRC_EQUIP_SIGNALS s left join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = s.WORK_ORDER_ID "
        "left join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "where s.EQUIP_CODE = %s order by s.COLLECT_DT desc, s.SIGNAL_ID desc limit 1", (equip_code,))
    rows = conn.q(
        "select COLLECT_DT, RUN_STATUS, RUN_MINUTE, PRODUCE_QTY, SPEED_VALUE, PRESSURE_VALUE, "
        "CURRENT_VALUE, TEMP_VALUE, ALARM_CODE, WORK_ORDER_ID "
        "from PRC_EQUIP_SIGNALS where EQUIP_CODE = %s "
        "order by COLLECT_DT desc, SIGNAL_ID desc limit %s", (equip_code, recent))
    rows.reverse()
    today = conn.q1(
        "select count(*) as n, coalesce(sum(RUN_MINUTE),0) as mins, coalesce(sum(PRODUCE_QTY),0) as qty, "
        "count(*) filter (where ALARM_CODE is not null and ALARM_CODE <> '') as alarms, "
        "count(*) filter (where RUN_STATUS = '가동') as run_n, "
        "count(*) filter (where WORK_ORDER_ID is null) as unmapped "
        "from PRC_EQUIP_SIGNALS where EQUIP_CODE = %s and COLLECT_DT >= %s", (equip_code, day0)) or {}
    # 현재 매핑 상태 — 배치가 오지 않아도 화면이 '지금 붙일 곳이 있는가' 를 답한다.
    with conn.tx() as cur:
        cands = active_work_orders(cur)
    if last and last["work_order_id"]:
        wo = {"work_order_id": int(last["work_order_id"]), "work_order_no": last["work_order_no"],
              "project_no": last["project_no"], "source": "마지막 신호에 적힌 작업지시"}
    elif len(cands) == 1:
        c = cands[0]
        wo = {"work_order_id": int(c["work_order_id"]), "work_order_no": c["work_order_no"],
              "project_no": c["project_no"], "source": "진행 중 레이저커팅 작업지시 1건 (다음 배치부터 매핑)"}
    else:
        wo = None
    mapping_note = None if wo else resolve_note(len(cands), cands)
    perf = None
    if wo:
        perf = conn.q1(
            "select PERF_ID, START_DT, END_DT, GOOD_QTY, ACTUAL_MANHOUR from PRC_PERFORMANCES "
            "where WORK_ORDER_ID = %s and COLLECT_METHOD = %s and START_DT >= %s "
            "order by PERF_ID desc limit 1", (wo["work_order_id"], METHOD_AUTO, day0))
    alerts = conn.q(
        "select RECO_ID, CREATED_AT_DT, SUMMARY_TEXT, REVIEW_STATUS from AGT_RECOMMENDATIONS "
        "where RECO_TYPE = %s and CREATED_AT_DT >= %s order by RECO_ID desc limit 5", (ALERT_RECO, day0))
    latest_vals = {t.name: (float(last[t.column.lower()]) if last and last[t.column.lower()] is not None else None)
                   for t in tags.numeric_tags()} if last else {}
    laser = next((d for d in st["devices"] if d["device_type"] == "PLC"), None)
    # 출처 표지 — 등록 IP 선언(D-174)이 없어도 **적재된 행의 COLLECT_PATH 가 시뮬레이터**면 그렇게 말한다.
    # 사이드카(D-233)는 IP 를 등록하지 않으므로 선언만 보면 시뮬레이터 데이터가 실수집처럼 보인다(D-195 계열).
    sim_note = device.simulation_note() or None
    last_path = conn.q1("select COLLECT_PATH from DAT_TIMESERIES where EQUIP_CODE = %s "
                        "order by MEASURE_DT desc, TS_ID desc limit 1", (equip_code,))
    if sim_note is None and last_path and last_path["collect_path"] == collector.COLLECT_PATH_SIM:
        sim_note = (f"시뮬레이터 데이터 — 최근 적재 행의 COLLECT_PATH='{collector.COLLECT_PATH_SIM}' (D-174). "
                    "실물 장비 신호가 아니다 (도입기업 장비 IP 미제공 D-169)")
    return {
        "checked_at": now.isoformat(sep=" ", timespec="seconds"),
        "equip_code": equip_code,
        "poll_sec": int(laser["collect_interval"] or 0) if laser and laser["collect_interval"] else None,
        "stale_sec": st["stale_sec"],
        "device": None if laser is None else {
            "name": laser["device_name"], "last_collect_dt": _iso(laser["last_collect_dt"]),
            "seconds_since": (None if laser["seconds_since"] is None else int(laser["seconds_since"])),
            "stale": laser["stale"], "notice": laser["notice"], "signal_cnt": laser["signal_cnt"]},
        "buffer_pending": st["buffer_pending"],
        "simulation": sim_note,
        "last": None if last is None else {
            "collect_dt": _iso(last["collect_dt"]), "run_status": last["run_status"],
            "alarm_code": last["alarm_code"] or None,
            "tags": [{"name": t.name, "ko": t.ko, "uom": t.uom,
                      "value": _val(last, t)} for t in tags.TAGS]},
        "today": {"date": day0.strftime("%Y-%m-%d"), "signals": int(today.get("n") or 0),
                  "run_minute": float(today.get("mins") or 0), "produce_qty": float(today.get("qty") or 0),
                  "alarms": int(today.get("alarms") or 0),
                  "utilisation_pct": (round(int(today["run_n"]) / int(today["n"]) * 100, 1)
                                      if int(today.get("n") or 0) else None),
                  "unmapped": int(today.get("unmapped") or 0)},
        "recent": [{"collect_dt": _iso(r["collect_dt"]), "run_status": r["run_status"],
                    "alarm_code": r["alarm_code"] or None,
                    "speed": _f(r["speed_value"]), "pressure": _f(r["pressure_value"]),
                    "current": _f(r["current_value"]), "temp": _f(r["temp_value"]),
                    "qty": _f(r["produce_qty"]), "run_minute": _f(r["run_minute"]),
                    "work_order_id": r["work_order_id"]} for r in rows],
        "work_order": wo,
        "mapping_note": mapping_note,
        "performance": None if perf is None else {
            "perf_id": int(perf["perf_id"]), "start_dt": _iso(perf["start_dt"]), "end_dt": _iso(perf["end_dt"]),
            "good_qty": _f(perf["good_qty"]), "manhour": _f(perf["actual_manhour"]),
            "method": METHOD_AUTO, "note": "PLC 신호에서 도출 — 불량 수량은 검사가 정한다"},
        "thresholds": threshold_check(latest_vals),
        "alerts": [{"reco_id": int(a["reco_id"]), "at": _iso(a["created_at_dt"]),
                    "summary": a["summary_text"], "review_status": a["review_status"]} for a in alerts],
        "anchor": clock.anchor().isoformat(sep=" ", timespec="seconds"),
    }


def resolve_note(n: int, cands: list[dict[str, Any]]) -> str:
    if n == 0:
        return (f"작업지시 미매핑 — 진행 중인 레이저커팅 {AUTO_PROCESS} 작업지시가 0건이다. "
                "현장POP 에서 지시를 지정하거나 작업지시를 진행 상태로 둔다")
    nos = ", ".join(c["work_order_no"] for c in cands[:5])
    return (f"작업지시 미매핑 — 진행 중 레이저커팅 작업지시 {n}건({nos}) — PLC 신호만으로는 "
            "어느 지시인지 알 수 없다. 현장POP 지정이 필요하다")


def _iso(v: Any) -> str | None:
    return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else (None if v is None else str(v))


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _val(row: Any, t: tags.Tag) -> Any:
    v = row[t.column.lower()]
    if v is None:
        return None
    return float(v) if t.numeric else str(v)
