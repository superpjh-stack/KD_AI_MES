#!/usr/bin/env python
"""개발2 업무 시드 — 공정실적 · 공정이력 · LOT추적 · 검사 · 출하 · KPI 목표/실적.

**규칙 (goal.md)**
  · 멱등이다(G-07). 두 번 돌려도 행 수 diff 0 — 자연키로 upsert 하거나 존재 확인 후 넣는다.
  · 생성 기준일은 **시간 앵커**에 고정한다(§10-3). `date.today()` 금지.
  · **지어내지 않는다**(§0.2). 정본에 값이 없는 것은 넣지 않고 `차단` 으로 보고한다.
  · 코드성 FK 는 넣기 전에 `util.codes.validate_code` 로 확인한다(D-32).
  · **남의 표를 쓰지 않는다.** `EST_*`(개발3) · `BAS_*`(개발1) 는 **읽기만** 한다.

**자동 수집은 레이저커팅 1공정뿐이다(D-06).** 공정실적의 `COLLECT_METHOD` 는 가공(레이저커팅)만
`자동(PLC)` 이고 나머지는 `수동(POP·패드)` 다. 외주 2공정(소재가공·버핑)은 실적이 아니라
**발주·반출·반입 상태**이므로 `PRC_PERFORMANCES` 를 만들지 않는다(D-41).

`PRC_EQUIP_SIGNALS` 는 수집 경로(개발3 `ingest`)가 채운다 — 여기서 만들지 않는다.
자동 수집을 흉내 낸 시드는 결함이다.

의존 (없으면 그 부분만 `차단` 으로 보고하고 나머지를 진행한다):
  · `EST_PROJECTS`          — 개발3. 프로젝트(수주)번호가 디지털 스레드의 최상위 키다(G-08)
  · `BAS_QUALITY_STANDARDS` — 개발1. `SHP_INSPECTIONS.QSTD_ID` 가 NOT NULL 이다
  · `BAS_COMMON_CODES` 고객사·품목 그룹 — 개발1/아키텍트. **D-47 로 비워 둔 그룹**이라
    채워지기 전에는 출하를 만들 수 없다(`SHP_SHIPMENTS.CUSTOMER_CODE` NOT NULL)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                  # noqa: E402
import seed_dev1                                             # noqa: E402
from kyungdong.app import kpi                                # noqa: E402
from kyungdong.app.util import clock, codes                  # noqa: E402

# 합성 표시 — 개발1 이 공표한 문자열을 **그대로 쓴다**(복제하지 않는다, §10-16).
MARK_SYNTH = seed_dev1.MARK_SYNTH
SYNTH_NOTE = seed_dev1.SYNTH_NOTE

# ── 채번 ────────────────────────────────────────────────────────────────
# **개발1 이 `BAS_COMMON_CODES('LOT채번')` 에 공표한 형식을 그대로 읽어 쓴다**(D-200).
# 코드가 아직 없으면 TD3 목업 grid_sample 형식으로 되돌린다 — 지어낸 형식이 아니다.
FALLBACK_PATTERN = {
    "WORK_ORDER_NO": "WO-YYYY-NNNN",      # TD3 021 목업: WO-2026-0031
    "PRODUCT_LOT_NO": "PLOT-YYYY-NNN",    # TD3 024 목업: PLOT-2026-011
    "SHIPMENT_NO": "SH-YYYY-NNNN",        # TD3 016 목업: SH-2026-0011
}
_NUM_RE = re.compile(r"N+")

# ── 공정 구간 (사업계획서 1.3 · seed.py PROCESSES) ───────────────────────
# 제조 구간만 작업지시를 만든다. P10 수주견적관리·P95 출하는 작업지시 대상이 아니다.
MFG_PROCESSES = ("P30", "P40", "P50", "P60", "P70", "P80", "P90")
OUTSOURCED = ("P30", "P60")               # 소재가공·버핑 — 발주·반출·반입 상태 관리 (D-41)
AUTO_COLLECT = ("P40",)                   # 자동 수집은 레이저커팅 1공정뿐이다 (D-06)
METHOD_AUTO, METHOD_MANUAL = "자동(PLC)", "수동(POP·패드)"

# 공정별 체류 비중 — 합이 1.0. TD3 043 목업 list_rows(공정별 소요시간 비중)의 순서를 따른다.
DWELL_SHARE = {"P30": 0.10, "P40": 0.12, "P50": 0.30, "P60": 0.08,
               "P70": 0.20, "P80": 0.12, "P90": 0.08}

# 프로젝트 순번별 실측 리드타임(h). 기존값(1,320/1,440)보다 짧고 목표값 부근에 놓는다.
MFG_HOURS = (1190, 1160, 1130, 1105, 1085, 1065, 1045, 1025)
O2D_HOURS = (1300, 1270, 1240, 1215, 1190, 1170, 1150, 1130)
ORDER_TO_WORKORDER_H = 96                 # 수주 확정 → 작업지시 확정 (4일)

INSPECT_ITEMS = (("수압", "수압시험", "bar"), ("기밀", "기밀시험", "bar"), ("진공", "진공시험", "mmHg"))


class Blocked(list):
    """차단 사유 모음 — 조용히 건너뛰지 않고 마지막에 전부 출력한다."""

    def note(self, what: str, why: str) -> None:
        self.append((what, why))


# ── 읽기 전용 조회 ───────────────────────────────────────────────────────
def numbering() -> dict[str, str]:
    """채번 형식 — 개발1 이 `BAS_COMMON_CODES('LOT채번')` 에 공표한 값이 정본이다."""
    rows = conn.q(
        "select CODE_VALUE, ATTR1 from BAS_COMMON_CODES where CODE_GROUP = 'LOT채번'")
    out = dict(FALLBACK_PATTERN)
    for r in rows:
        if r["code_value"] in out and (r["attr1"] or "").strip():
            out[r["code_value"]] = r["attr1"].strip()
    return out


def apply_pattern(pattern: str, year: int, seq: int) -> str:
    """`WO-YYYY-NNNN` → `WO-2026-0031`. N 의 개수가 자리수다."""
    m = _NUM_RE.search(pattern)
    if not m:
        raise ValueError(f"채번 형식에 순번(N)이 없다: {pattern!r}")
    body = pattern.replace("YYYY", f"{year:04d}")
    m = _NUM_RE.search(body)
    return body[:m.start()] + f"{seq:0{m.end() - m.start()}d}" + body[m.end():]


def process_codes() -> dict[str, str]:
    rows = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = '공정' and USE_YN = 'Y' order by SORT_ORDER"
    )
    return {r["code_value"]: r["code_name"] for r in rows}


def projects() -> list[dict[str, Any]]:
    return conn.q(
        "select PROJECT_ID, PROJECT_NO, PROJECT_NAME, CUSTOMER_CODE, PRODUCT_GROUP, "
        "ORDER_CONFIRM_DT, DUE_DT, PROJECT_STATUS "
        "from EST_PROJECTS order by PROJECT_NO"
    )


def quality_standards() -> dict[tuple[str, str], dict[str, Any]]:
    """(제품군, 검사항목) → 품질기준 행. `BAS_QUALITY_STANDARDS` 는 개발1 소유라 **읽기만** 한다.

    검사 항목명·단위는 **기준 데이터에서 가져온다** — 여기서 지어내지 않는다(§0.2).
    제품군이 없는 행(PRODUCT_GROUP 은 NOT NULL 이라 실제로는 없다)은 `('', key)` 로 떨어진다.
    """
    rows = conn.q(
        "select QSTD_ID, PRODUCT_GROUP, INSPECT_TYPE, INSPECT_ITEM, UOM, STANDARD_SPEC "
        "from BAS_QUALITY_STANDARDS where USE_YN = 'Y' order by QSTD_ID"
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        label = f"{r['inspect_item'] or ''}"
        for key, _fallback_item, _fallback_uom in INSPECT_ITEMS:
            if key in label:
                out.setdefault((r["product_group"] or "", key), r)
    return out


def standards_for(qstd: dict[tuple[str, str], dict[str, Any]],
                  product_group: str) -> dict[str, dict[str, Any]]:
    """그 제품군의 수압·기밀·진공 기준. 3종을 다 못 찾으면 **빈 dict** — 검사를 만들지 않는다."""
    got = {key: qstd[(product_group, key)]
           for key, _i, _u in INSPECT_ITEMS if (product_group, key) in qstd}
    return got if len(got) == len(INSPECT_ITEMS) else {}


def _approver_id() -> int | None:
    """출하 승인자 — `SHIP_DT` 가 있는데 `APPROVER_ID` 가 비면 G-24 가 FAIL 이다.

    실명을 넣지 않는다(G-29·D-39) — 공통 시드의 **직무 계정**(경영자)을 쓴다.
    """
    row = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'exec'")
    return int(row["user_id"]) if row else None


# ── KPI 목표 (의존 없음 — 항상 시드한다) ──────────────────────────────────
def seed_kpi_targets(admin_id: int | None) -> int:
    """사업계획서 1.5 확정값(D-21). 개선율은 `app/kpi.py` 가 **계산**한다 — 상수를 박지 않는다."""
    for d in kpi.DEFS.values():
        conn.x(
            "insert into KPI_TARGETS (KPI_CODE, KPI_NAME, KPI_FIELD, UOM, BASE_VALUE, TARGET_VALUE, "
            "IMPROVE_RATE, WEIGHT, OFFICIAL_YN, MEASURE_BASIS, FORMULA_TEXT, CREATED_BY, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) "
            "on conflict (KPI_CODE) do update set "
            "KPI_NAME = excluded.KPI_NAME, KPI_FIELD = excluded.KPI_FIELD, UOM = excluded.UOM, "
            "BASE_VALUE = excluded.BASE_VALUE, TARGET_VALUE = excluded.TARGET_VALUE, "
            "IMPROVE_RATE = excluded.IMPROVE_RATE, WEIGHT = excluded.WEIGHT, "
            "OFFICIAL_YN = excluded.OFFICIAL_YN, MEASURE_BASIS = excluded.MEASURE_BASIS, "
            "FORMULA_TEXT = excluded.FORMULA_TEXT, UPDATED_DT = now()",
            (d.code, d.name, d.field, d.uom, d.base, d.target, d.improve_rate, d.weight,
             "Y" if d.official else "N", d.basis, d.formula, admin_id),
        )
    return len(kpi.DEFS)


def seed_kpi_measures(anchor: datetime) -> tuple[int, list[str]]:
    """실적은 **`app/kpi.py` 단일 산식**으로 집계한다. 표본 0건이면 행을 만들지 않는다(G-11)."""
    written, empty = 0, []
    targets = {r["kpi_code"]: int(r["kpi_target_id"]) for r in kpi.targets_in_db()}
    for code in kpi.OFFICIAL_CODES:
        tid = targets.get(code)
        if tid is None:
            continue
        periods = sorted({r["period_code"] for r in kpi.samples(code)})
        if not periods:
            empty.append(code)
            continue
        for period in periods:
            m = kpi.measure(code, period)
            if m.value is None:
                continue
            row = conn.q1(
                "select MEASURE_ID from KPI_MEASURES where KPI_TARGET_ID = %s and PERIOD_CODE = %s",
                (tid, period),
            )
            params = (m.sample_cnt, m.value, m.achieve, m.definition.source_type,
                      anchor,
                      f"{SYNTH_NOTE} — 표본 {m.sample_cnt}건. 자재LOT 이후가 합성이라 이 값은 "
                      "성과 실적이 아니다. 산식은 app/kpi.py 단일 소스")
            if row:
                conn.x(
                    "update KPI_MEASURES set SAMPLE_CNT=%s, MEASURE_VALUE=%s, ACHIEVE_RATE=%s, "
                    "SOURCE_TYPE=%s, AGGREGATED_DT=%s, REMARK=%s where MEASURE_ID = %s",
                    (*params, int(row["measure_id"])),
                )
            else:
                conn.x(
                    "insert into KPI_MEASURES (KPI_TARGET_ID, PERIOD_CODE, SAMPLE_CNT, MEASURE_VALUE, "
                    "ACHIEVE_RATE, SOURCE_TYPE, AGGREGATED_DT, REMARK, CREATED_DT) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s, now())",
                    (tid, period, *params),
                )
            written += 1
    return written, empty


# ── 공정·LOT·검사·출하 ───────────────────────────────────────────────────
def seed_chain(anchor: datetime, procs: dict[str, str],
               qstd: dict[tuple[str, str], dict[str, Any]],
               nums: dict[str, str], blocked: Blocked) -> dict[str, Any]:
    """G-08 디지털 스레드 — BOM → 작업지시 → 공정실적 → 제품LOT → 검사 → 출하.

    **상류(프로젝트·도면·BOM·자재LOT)는 개발1 이 만들고 여기서는 읽기만 한다** —
    `seed_dev1.thread_rows()` 가 전역 순번과 **의도적 단절 위치**까지 함께 준다(D-131).
    제품LOT 은 **BOM 1건당 1건**이다.

    ⚠ 자재LOT 이후는 **전부 합성이다.** 사슬을 일부러 끊은 표본을 넣는다 —
    전부 완벽하게 이으면 100% 가 나오고 그건 검사기를 시험하지 못한다.
    """
    counts: dict[str, Any] = dict(work_orders=0, lot_traces=0, performances=0, histories=0,
                                 inspections=0, shipments=0, ship_items=0, shipped=0,
                                 in_progress=0, broken=0, breaks=[])
    rows = seed_dev1.thread_rows()
    if not rows:
        blocked.note("공정·LOT·검사·출하 전부",
                     "상류 골격이 0건이다 — EST_PROJECTS·EST_BOM_HEADERS·INV_MATERIAL_LOTS 를 "
                     "`db/seed_dev1.py` 가 먼저 채운다 (G-08 1~4단계 · D-131)")
        return counts
    if tuple(seed_dev1.ROUTING_PROCESSES) != MFG_PROCESSES:
        blocked.note("공정 구조 대조",
                     f"개발1 ROUTING_PROCESSES {seed_dev1.ROUTING_PROCESSES} 와 "
                     f"개발2 MFG_PROCESSES {MFG_PROCESSES} 가 다르다 — 정본이 갈라졌다")

    pjs = {int(p["project_id"]): p for p in projects()}
    approver = _approver_id()
    if approver is None:
        blocked.note("SHP_SHIPMENTS.APPROVER_ID",
                     "직무 계정 'exec' 가 없다 — SHIP_DT 가 있는데 승인자가 비면 G-24 가 FAIL 이다")

    for b in rows:
        idx = b["index"]
        pj = pjs.get(b["project_id"])
        if pj is None or pj["order_confirm_dt"] is None:
            blocked.note(f"{b['bom_no']}",
                         "EST_PROJECTS.ORDER_CONFIRM_DT 가 비어 있다 — "
                         "수주출하 리드타임 시작 시각이 없어 이 BOM 을 건너뛴다")
            continue
        broke = b["break"]
        if broke:
            counts["broken"] += 1
            counts["breaks"].append(f"#{idx} {b['project_no']} / {b['bom_no']} — {broke}")

        confirm = pj["order_confirm_dt"]
        mfg_h = MFG_HOURS[idx % len(MFG_HOURS)]
        o2d_h = O2D_HOURS[idx % len(O2D_HOURS)]
        wo_confirm = confirm + timedelta(hours=ORDER_TO_WORKORDER_H)
        packing = wo_confirm + timedelta(hours=mfg_h)
        ship_dt = confirm + timedelta(hours=o2d_h)
        year = wo_confirm.year

        std = standards_for(qstd, pj["product_group"])
        if not std:
            blocked.note("SHP_INSPECTIONS · SHP_SHIPMENTS",
                         f"제품군 {pj['product_group']} 의 수압·기밀·진공 기준을 "
                         "BAS_QUALITY_STANDARDS 에서 3종 다 찾지 못했다 — QSTD_ID 가 NOT NULL "
                         "이라 검사 결과를 만들 수 없다 (개발1)")

        wo_ids = _seed_work_orders(pj, idx, b, wo_confirm, procs, nums, blocked)
        if not wo_ids:
            continue
        counts["work_orders"] += len(wo_ids)

        lot_no = apply_pattern(nums["PRODUCT_LOT_NO"], year, idx + 1)
        lot_id = _upsert_lot_trace(lot_no, pj, b, wo_ids, blocked)
        if lot_id is None:
            continue
        counts["lot_traces"] += 1

        if broke and "공정실적 누락" in broke:
            # **의도적 단절** — 공정실적을 만들지 않는다. 이력은 남기되 PERF_ID 가 빈다.
            counts["histories"] += _seed_histories(lot_id, wo_ids, wo_confirm, mfg_h, anchor)
        else:
            counts["performances"] += _seed_performances(wo_ids, lot_id, wo_confirm, mfg_h, procs)
            counts["histories"] += _seed_histories(lot_id, wo_ids, wo_confirm, mfg_h, anchor)

        if broke and "검사·출하 누락" in broke:
            counts["in_progress"] += 1
            continue
        if not std:
            counts["in_progress"] += 1
            continue
        counts["inspections"] += _seed_inspections(lot_id, std, packing)

        if ship_dt > anchor:
            counts["in_progress"] += 1
            continue
        made = _seed_shipment(pj, idx, b, lot_id, packing, ship_dt, year, nums, approver, blocked)
        if made:
            counts["shipments"] += made[0]
            counts["ship_items"] += made[1]
            counts["shipped"] += 1
        else:
            counts["in_progress"] += 1

    _restate_mapping_flag()
    return counts


def _restate_mapping_flag() -> int:
    """`MAPPING_OK_YN` 을 **실제 연결로 다시 쓴다** — 선언만 Y 로 두면 매핑률이 조작된다.

    판정 산식은 `tools/check_data.py` 의 `LOT_FULL_CHAIN`(QA2 독립 재계산)과 같은 9단계다.
    여기서 Y 를 남발하지 않는 것이 요점이다 — 검사기는 이 열을 **믿지 않고** 따로 센다.
    """
    return conn.x("""
update SHP_LOT_TRACES t set MAPPING_OK_YN = case when (
        t.PROJECT_ID is not null and t.BOM_ID is not null
    and t.MATERIAL_LOT_ID is not null and t.WORK_ORDER_ID is not null
    and exists (select 1 from EST_CAD_DRAWINGS d join EST_BOM_HEADERS b
                 on b.DRAWING_ID = d.DRAWING_ID where b.BOM_ID = t.BOM_ID)
    and exists (select 1 from INV_MATERIAL_LOTS m where m.LOT_ID = t.MATERIAL_LOT_ID)
    and exists (select 1 from PRC_WORK_ORDERS w where w.WORK_ORDER_ID = t.WORK_ORDER_ID)
    and exists (select 1 from PRC_PERFORMANCES f where f.LOT_TRACE_ID = t.LOT_TRACE_ID)
    and exists (select 1 from SHP_INSPECTIONS i where i.LOT_TRACE_ID = t.LOT_TRACE_ID)
    and exists (select 1 from SHP_SHIPMENT_ITEMS s join SHP_SHIPMENTS h
                 on h.SHIPMENT_ID = s.SHIPMENT_ID where s.LOT_TRACE_ID = t.LOT_TRACE_ID)
    ) then 'Y' else 'N' end,
    UPDATED_DT = now()
where MAPPING_OK_YN is distinct from (case when (
        t.PROJECT_ID is not null and t.BOM_ID is not null
    and t.MATERIAL_LOT_ID is not null and t.WORK_ORDER_ID is not null
    and exists (select 1 from EST_CAD_DRAWINGS d join EST_BOM_HEADERS b
                 on b.DRAWING_ID = d.DRAWING_ID where b.BOM_ID = t.BOM_ID)
    and exists (select 1 from INV_MATERIAL_LOTS m where m.LOT_ID = t.MATERIAL_LOT_ID)
    and exists (select 1 from PRC_WORK_ORDERS w where w.WORK_ORDER_ID = t.WORK_ORDER_ID)
    and exists (select 1 from PRC_PERFORMANCES f where f.LOT_TRACE_ID = t.LOT_TRACE_ID)
    and exists (select 1 from SHP_INSPECTIONS i where i.LOT_TRACE_ID = t.LOT_TRACE_ID)
    and exists (select 1 from SHP_SHIPMENT_ITEMS s join SHP_SHIPMENTS h
                 on h.SHIPMENT_ID = s.SHIPMENT_ID where s.LOT_TRACE_ID = t.LOT_TRACE_ID)
    ) then 'Y' else 'N' end)
""")


def _seed_work_orders(pj: dict, idx: int, b: dict[str, Any], confirm: datetime,
                      procs: dict[str, str], nums: dict[str, str],
                      blocked: Blocked) -> list[tuple[str, int]]:
    """제품LOT 1건당 제조 7공정. `ROUTING_ID` 는 개발1 이 만든 BOM 공정구조를 가리킨다."""
    routing = {r["process_code"]: int(r["routing_id"]) for r in conn.q(
        "select PROCESS_CODE, ROUTING_ID from EST_BOM_ROUTINGS where BOM_ID = %s", (b["bom_id"],))}
    out: list[tuple[str, int]] = []
    for n, code in enumerate(MFG_PROCESSES):
        if code not in procs:
            blocked.note("PRC_WORK_ORDERS", f"공정 코드 {code} 가 BAS_COMMON_CODES 에 없다")
            return []
        if not codes.validate_code("공정", code):
            blocked.note("PRC_WORK_ORDERS", f"공정 코드 {code} 검증 실패 (D-32)")
            return []
        no = apply_pattern(nums["WORK_ORDER_NO"], confirm.year,
                           idx * len(MFG_PROCESSES) + n + 1)
        conn.x(
            "insert into PRC_WORK_ORDERS (WORK_ORDER_NO, PROJECT_ID, ROUTING_ID, PROCESS_CODE, "
            "ORDER_QTY, CONFIRM_DT, PLAN_START_DT, PLAN_END_DT, OUTSOURCE_YN, ORDER_STATUS, "
            "CREATED_DT) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) "
            "on conflict (WORK_ORDER_NO) do update set "
            "PROJECT_ID = excluded.PROJECT_ID, ROUTING_ID = excluded.ROUTING_ID, "
            "PROCESS_CODE = excluded.PROCESS_CODE, "
            "ORDER_QTY = excluded.ORDER_QTY, CONFIRM_DT = excluded.CONFIRM_DT, "
            "PLAN_START_DT = excluded.PLAN_START_DT, PLAN_END_DT = excluded.PLAN_END_DT, "
            "OUTSOURCE_YN = excluded.OUTSOURCE_YN, ORDER_STATUS = excluded.ORDER_STATUS, "
            "UPDATED_DT = now()",
            (no, pj["project_id"], routing.get(code), code, 1,
             confirm, confirm.date(), pj["due_dt"],
             "Y" if code in OUTSOURCED else "N", "완료"),
        )
        row = conn.q1("select WORK_ORDER_ID from PRC_WORK_ORDERS where WORK_ORDER_NO = %s", (no,))
        out.append((code, int(row["work_order_id"])))
    return out


def _upsert_lot_trace(lot_no: str, pj: dict, b: dict[str, Any],
                      wo_ids: list[tuple[str, int]], blocked: Blocked) -> int | None:
    """제품LOT — BOM·자재LOT·작업지시를 잇는다. **의도적 단절이면 그 칸을 비운다.**

    `MAPPING_OK_YN` 은 여기서 'N' 으로 두고 마지막에 `_restate_mapping_flag()` 가
    **실제 연결을 확인해** 다시 쓴다. 선언만 Y 로 적어 매핑률을 올리지 않는다.
    """
    broke = b["break"] or ""
    bom_id = None if "BOM 미연결" in broke else b["bom_id"]
    mat_id = None if "자재LOT 미투입" in broke else b["material_lot_id"]
    current = wo_ids[-1][0]
    if not codes.validate_code("공정", current):
        blocked.note("SHP_LOT_TRACES", f"현재 공정 코드 {current} 검증 실패 (D-32)")
        return None
    conn.x(
        "insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, BOM_ID, MATERIAL_LOT_ID, "
        "WORK_ORDER_ID, CURRENT_PROCESS, TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,'출하','N', now()) "
        "on conflict (PRODUCT_LOT_NO) do update set "
        "PROJECT_ID = excluded.PROJECT_ID, BOM_ID = excluded.BOM_ID, "
        "MATERIAL_LOT_ID = excluded.MATERIAL_LOT_ID, WORK_ORDER_ID = excluded.WORK_ORDER_ID, "
        "CURRENT_PROCESS = excluded.CURRENT_PROCESS, TRACE_STATUS = excluded.TRACE_STATUS, "
        "UPDATED_DT = now()",
        (lot_no, pj["project_id"], bom_id, mat_id, wo_ids[0][1], current),
    )
    row = conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s", (lot_no,))
    return int(row["lot_trace_id"]) if row else None


def _seed_performances(wo_ids: list[tuple[str, int]], lot_id: int, start: datetime,
                       mfg_h: int, procs: dict[str, str]) -> int:
    """외주 2공정은 실적을 만들지 않는다 — 발주·반출·반입 상태 관리다(D-41)."""
    made, cursor = 0, start
    for code, wo_id in wo_ids:
        span = timedelta(hours=mfg_h * DWELL_SHARE[code])
        if code in OUTSOURCED:
            cursor += span
            continue
        method = METHOD_AUTO if code in AUTO_COLLECT else METHOD_MANUAL
        exists = conn.q1(
            "select PERF_ID from PRC_PERFORMANCES "
            "where WORK_ORDER_ID = %s and PROCESS_CODE = %s and START_DT = %s",
            (wo_id, code, cursor),
        )
        if not exists:
            conn.x(
                "insert into PRC_PERFORMANCES (WORK_ORDER_ID, LOT_TRACE_ID, PROCESS_CODE, "
                "START_DT, END_DT, GOOD_QTY, DEFECT_QTY, ACTUAL_MANHOUR, COLLECT_METHOD, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())",
                # DEFECT_TYPE 은 비운다 — '불량유형' 코드 그룹이 D-47 로 비어 있다. 지어내지 않는다.
                (wo_id, lot_id, code, cursor, cursor + span, 1, 0,
                 round(span.total_seconds() / 3600.0, 2), method),
            )
            made += 1
        cursor += span
    return made


def _seed_histories(lot_id: int, wo_ids: list[tuple[str, int]], start: datetime,
                    mfg_h: int, anchor: datetime) -> int:
    """`PRC_PROCESS_HISTORIES` 는 **시드 대상**으로 판정했다 (db-schema §7.1 · progress-dev2 §3)."""
    made, cursor = 0, start
    for seq, (code, wo_id) in enumerate(wo_ids, start=1):
        span = timedelta(hours=mfg_h * DWELL_SHARE[code])
        out_dt = cursor + span
        reached = anchor >= out_dt
        perf = conn.q1(
            "select PERF_ID from PRC_PERFORMANCES where WORK_ORDER_ID = %s and LOT_TRACE_ID = %s",
            (wo_id, lot_id),
        )
        # 외주 구간은 반출/반입으로 기록한다 (D-41 대체 표기). 반입 전이면 이력이 단절된다.
        step = ("반입" if reached else "반출") if code in OUTSOURCED else None
        status = "정상" if reached else "단절"
        exists = conn.q1(
            "select PRC_HIST_ID from PRC_PROCESS_HISTORIES "
            "where LOT_TRACE_ID = %s and PROCESS_SEQ = %s", (lot_id, seq),
        )
        params = (code, cursor, out_dt if reached else None,
                  round(span.total_seconds() / 3600.0, 2) if reached else None,
                  int(perf["perf_id"]) if perf else None, step, status)
        if exists:
            conn.x(
                "update PRC_PROCESS_HISTORIES set PROCESS_CODE=%s, IN_DT=%s, OUT_DT=%s, "
                "DWELL_HOUR=%s, PERF_ID=%s, OUTSOURCE_STEP=%s, HIST_STATUS=%s "
                "where PRC_HIST_ID = %s", (*params, int(exists["prc_hist_id"])),
            )
        else:
            conn.x(
                "insert into PRC_PROCESS_HISTORIES (LOT_TRACE_ID, PROCESS_CODE, PROCESS_SEQ, "
                "IN_DT, OUT_DT, DWELL_HOUR, PERF_ID, OUTSOURCE_STEP, HIST_STATUS, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())",
                (lot_id, code, seq, cursor, out_dt if reached else None,
                 round(span.total_seconds() / 3600.0, 2) if reached else None,
                 int(perf["perf_id"]) if perf else None, step, status),
            )
            made += 1
        cursor = out_dt
    return made


def _seed_inspections(lot_id: int, qstd: dict[str, dict[str, Any]], packing: datetime) -> int:
    """출하검사 — 수압·기밀·진공(사업계획서 1.3). **측정값은 도입기업 실측**이라
    판정만 기록하고 `MEASURED_VALUE` 는 비운다(§0.2 지어내지 않는다).

    `SHP_INSPECTIONS` 에는 비고 칸이 없다 — `REJECT_REASON` 은 **불합격 사유** 칸이라
    합격 행에 합성 표시를 넣으면 거짓이 된다. 표시는 화면 배지·게이트 줄이 진다(D-131).
    """
    made = 0
    for n, (key, _fallback_item, _fallback_uom) in enumerate(INSPECT_ITEMS):
        std = qstd[key]
        item = std["inspect_item"]
        exists = conn.q1(
            "select INSPECT_ID from SHP_INSPECTIONS where LOT_TRACE_ID = %s and INSPECT_ITEM = %s",
            (lot_id, item),
        )
        if exists:
            continue
        conn.x(
            "insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, UOM, JUDGE_RESULT, "
            "INSPECT_DT, CREATED_DT) values (%s,%s,%s,%s,%s,%s, now())",
            (lot_id, int(std["qstd_id"]), item, std["uom"], "합격",
             packing - timedelta(hours=12 - n)),
        )
        made += 1
    return made


def _seed_shipment(pj: dict, idx: int, b: dict[str, Any], lot_id: int, packing: datetime,
                   ship_dt: datetime, year: int, nums: dict[str, str], approver: int | None,
                   blocked: Blocked) -> tuple[int, int] | None:
    """검사 **합격 LOT 만** 출하 대상이다. 코드성 FK 는 넣기 전에 확인한다(D-32).

    `APPROVER_ID` 를 반드시 채운다 — `SHIP_DT` 가 있는데 승인자가 비면 G-24 가 FAIL 이다.
    출하 품목 코드는 **그 제품LOT 의 BOM 레벨1 품목**이다. 제품군 코드(PG10 등)를 품목 칸에
    넣지 않는다 — 제품군과 품목은 다른 코드 그룹이다.
    """
    failed = conn.q1(
        "select 1 as x from SHP_INSPECTIONS where LOT_TRACE_ID = %s and JUDGE_RESULT <> '합격'",
        (lot_id,),
    )
    if failed:
        return None
    if not codes.validate_code("고객사", pj["customer_code"]):
        blocked.note("SHP_SHIPMENTS",
                     f"고객사 코드 '{pj['customer_code']}' 가 BAS_COMMON_CODES 에 없다 — "
                     "고객사 19종은 개발1 시드가 넣는다 (확정 D-139)")
        return None
    item_code = b.get("item_code")
    if not codes.validate_code("품목", item_code):
        blocked.note("SHP_SHIPMENT_ITEMS",
                     f"품목 코드 '{item_code}' 가 BAS_COMMON_CODES 에 없다 — "
                     "품목 179종은 개발1 시드가 넣는다 (가설 D-131)")
        return None

    no = apply_pattern(nums["SHIPMENT_NO"], year, idx + 1)
    otd = "Y" if (pj["due_dt"] is None or ship_dt.date() <= pj["due_dt"]) else "N"
    conn.x(
        "insert into SHP_SHIPMENTS (SHIPMENT_NO, PROJECT_ID, CUSTOMER_CODE, PLAN_DT, SHIP_DT, "
        "DUE_DT, OTD_YN, SHIP_STATUS, APPROVER_ID, ERP_SYNC_STATUS, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) "
        "on conflict (SHIPMENT_NO) do update set PROJECT_ID = excluded.PROJECT_ID, "
        "CUSTOMER_CODE = excluded.CUSTOMER_CODE, PLAN_DT = excluded.PLAN_DT, "
        "SHIP_DT = excluded.SHIP_DT, DUE_DT = excluded.DUE_DT, OTD_YN = excluded.OTD_YN, "
        "SHIP_STATUS = excluded.SHIP_STATUS, APPROVER_ID = excluded.APPROVER_ID, "
        "UPDATED_DT = now()",
        (no, pj["project_id"], pj["customer_code"], ship_dt.date(), ship_dt,
         pj["due_dt"], otd, "완료", approver, "미전송"),
    )
    row = conn.q1("select SHIPMENT_ID from SHP_SHIPMENTS where SHIPMENT_NO = %s", (no,))
    sid = int(row["shipment_id"])
    insp = conn.q1(
        "select INSPECT_ID from SHP_INSPECTIONS where LOT_TRACE_ID = %s "
        "and JUDGE_RESULT = '합격' order by INSPECT_DT desc limit 1", (lot_id,),
    )
    remark = (f"{MARK_SYNTH} — 출하 이후 전 구간이 합성이다. 실제 출하 기록의 원천이 없다. "
              f"투입 BOM {b['bom_no']}")
    exists = conn.q1(
        "select SHIP_ITEM_ID from SHP_SHIPMENT_ITEMS where SHIPMENT_ID = %s and LOT_TRACE_ID = %s",
        (sid, lot_id),
    )
    items = 0
    if exists:
        conn.x("update SHP_SHIPMENT_ITEMS set ITEM_CODE = %s, PACKING_DT = %s, INSPECT_ID = %s, "
               "REMARK = %s, UPDATED_DT = now() where SHIP_ITEM_ID = %s",
               (item_code, packing, int(insp["inspect_id"]) if insp else None, remark,
                int(exists["ship_item_id"])))
    else:
        conn.x(
            "insert into SHP_SHIPMENT_ITEMS (SHIPMENT_ID, LOT_TRACE_ID, ITEM_CODE, SHIP_QTY, "
            "PACKING_DT, INSPECT_ID, REMARK, CREATED_DT) values (%s,%s,%s,%s,%s,%s,%s, now())",
            (sid, lot_id, item_code, 1, packing, int(insp["inspect_id"]) if insp else None, remark),
        )
        items = 1
    return 1, items


# ── 실행 ────────────────────────────────────────────────────────────────
def counts_now() -> dict[str, int]:
    tables = ("PRC_WORK_ORDERS", "PRC_PERFORMANCES", "PRC_PROCESS_HISTORIES",
              "PRC_STD_CONDITIONS", "PRC_ACTUAL_CONDITIONS", "PRC_CONDITION_DEVIATIONS",
              "PRC_EQUIP_SIGNALS", "SHP_LOT_TRACES", "SHP_INSPECTIONS", "SHP_SHIPMENTS",
              "SHP_SHIPMENT_ITEMS", "SHP_CLAIMS", "SHP_CLAIM_CAUSES",
              "KPI_TARGETS", "KPI_MEASURES")
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in tables}


def main() -> int:
    if conn.table_count() != 68:
        print(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-schema`", file=sys.stderr)
        return 1
    anchor = clock.anchor()          # 없으면 여기서 터진다 — date.today() 로 대체하지 않는다(§10-3)
    blocked = Blocked()

    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    admin_id = int(admin["user_id"]) if admin else None

    procs = process_codes()
    if not procs:
        print("BAS_COMMON_CODES '공정' 그룹이 비어 있다 — 먼저 `make db-seed`", file=sys.stderr)
        return 1
    qstd = quality_standards()

    seed_kpi_targets(admin_id)
    nums = numbering()
    chain = seed_chain(anchor, procs, qstd, nums, blocked)
    measures, empty_kpi = seed_kpi_measures(anchor)
    for code in empty_kpi:
        d = kpi.definition(code)
        blocked.note(f"KPI_MEASURES {code}",
                     f"표본 0건 — {d.start_label} ~ {d.end_label} 구간이 아직 없다. "
                     "0건은 정상이고 화면은 '미수집' 을 렌더한다(G-11)")

    # 시드하지 않기로 판정한 표 (contracts/db-schema.md §7.1)
    blocked.note("PRC_STD_CONDITIONS · PRC_ACTUAL_CONDITIONS · PRC_CONDITION_DEVIATIONS",
                 "표준 작업조건 초기 정의는 도입기업 제공이다(TD3 023 제약사항) — "
                 "표준값을 지어내지 않는다. 023 은 '미확정' 을 렌더한다 (D-203)")
    blocked.note("SHP_CLAIMS · SHP_CLAIM_CAUSES",
                 "클레임 이력이 문서로만 존재한다(TD3 019 제약사항) — 런타임 등록 대상으로 판정. "
                 "'클레임유형' 코드 그룹도 D-47 로 비어 있다. 고객사는 확정됐지만(D-139) "
                 "클레임 사실 자체를 지어내지 않는다 (D-204)")
    blocked.note("PRC_EQUIP_SIGNALS",
                 "수집 경로(개발3 ingest · 레이저커팅기 PLC 1지점)가 채운다 — "
                 "자동 수집을 흉내 낸 시드를 만들지 않는다 (D-06)")

    now = counts_now()
    print(f"시간 앵커        {anchor.isoformat(sep=' ')}")
    print(f"프로젝트(읽기)    {len(projects())} 건  · 공정코드 {len(procs)}"
          f" · 품질기준 {len(qstd)} 행(제품군×검사항목)")
    print(f"채번(개발1 공표)   " + " · ".join(f"{k}={v}" for k, v in nums.items()))
    print()
    print(f"═══ {SYNTH_NOTE} — 자재LOT 이후는 전부 합성이다 ═══")
    print(f"작업지시         {chain['work_orders']} 건 (제품LOT 1건당 제조 7공정)")
    print(f"제품 LOT         {chain['lot_traces']} 건   · 출하완료 {chain['shipped']} · 진행중 {chain['in_progress']}")
    print(f"공정실적         {chain['performances']} 건   (자동 수집은 레이저커팅 1공정뿐 — D-06)")
    print(f"공정이력         {chain['histories']} 건")
    print(f"출하검사         {chain['inspections']} 건   · 출하 {chain['shipments']} · 출하품목 {chain['ship_items']}")
    print(f"KPI 목표         {len(kpi.DEFS)} 건   · KPI 실적 {measures} 건 (REMARK 에 합성 표시)")
    print()
    lots = chain["lot_traces"] or 1
    print(f"의도적 단절       {chain['broken']} / {chain['lot_traces']} 건"
          f" = {round(chain['broken'] / lots * 100, 1)}%  — 개발1 `BREAKS` 가 정본이다")
    for line in chain["breaks"]:
        print(f"  {line}")
    print("  **단절을 빼서 100% 를 만들지 않는다.** G-08 이 이것을 잡아내는지가 검사기의 실력이다")
    print()
    mapped = conn.q1("select count(*) filter (where MAPPING_OK_YN = 'Y') as y, count(*) as n "
                     "from SHP_LOT_TRACES") or {"y": 0, "n": 0}
    print(f"MAPPING_OK_YN    Y {mapped['y']} / 전체 {mapped['n']}"
          f" — 실제 9단계 연결을 확인해 다시 쓴 값이다(선언만 Y 로 적지 않는다)")
    print()
    print("KPI 확정값 (사업계획서 1.5 · D-21) — 개선율은 app/kpi.py 가 계산한다")
    for d in kpi.DEFS.values():
        print(f"  {d.code:<14} {d.base:>8,.0f}{d.uom} → {d.target:>8,.0f}{d.uom}"
              f"  −{d.improve_rate}%  가중치 {d.weight}")
    print()
    print("테이블 행 수 (개발2 15표)")
    for t, n in now.items():
        print(f"  {t:<26} {n:>6}")
    if blocked:
        print()
        print("차단·미시드 — 지어내지 않는다")
        for what, why in blocked:
            print(f"  · {what}\n      {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
