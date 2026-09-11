"""KPI 산식 **단일 소스** (goal.md 개발2 · D-21 · D-35 · contracts/interfaces.md §9).

대시보드(001~004) · 현황판(`/board`) · KPI 화면(043~045) · `db/seed_dev2.py` 가 **전부 이 모듈**을
부른다. 산식을 다른 곳에 복제하면 화면마다 숫자가 갈라진다 — 그것이 이 파일이 존재하는 이유다.

**확정값 (사업계획서 1.5 · D-21)**

| 코드 | 지표 | 기존 | 목표 | 가중치 | 산식 |
|---|---|---|---|---|---|
| `LEADTIME_MFG` | 제조 리드타임 | 1,320h (55일) | 1,080h (45일) | 0.5 | 작업지시 확정시각 ~ 포장완료 시각 평균 소요시간 |
| `LEADTIME_O2D` | 수주출하 리드타임 | 1,440h (60일) | 1,200h (50일) | 0.5 | 출하시각 − 수주확정시각 |

감소율 = (기존 − 목표) ÷ 기존 × 100 — **여기서 계산한다. 18.2/16.7 을 상수로 박지 않는다.**
측정근거는 2025년 생산 일지(수주출하는 3개월분).

**품질 KPI(044)는 공식 성과지표가 아니다.** 사업계획서 1.5 성과지표 2건에 들어가지 않는
운영지표이므로 `official=False` 로 분리하고 화면이 그렇게 구분 표기한다
(TD3 common_screens dashboard checks).

**0건은 정상이다**(G-11). 표본이 없으면 `None` 을 돌려주고 화면이 `미수집` 을 렌더한다 —
0.0 이나 목표값으로 메우지 않는다. DB 장애는 `db/conn.py` 가 **503** 을 낸다(G-30).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "db"))

CODE_MFG = "LEADTIME_MFG"
CODE_O2D = "LEADTIME_O2D"


@dataclass(frozen=True)
class KpiDef:
    """KPI_TARGETS 한 행의 정본. 시드와 화면이 같은 객체를 본다."""
    code: str
    name: str
    field: str          # KPI_FIELD — TD5 는 'P/Q/C/D 등' 까지만 적었다 (가설 D-201)
    uom: str
    base: float         # BASE_VALUE 기존값
    target: float       # TARGET_VALUE 목표값
    weight: float       # WEIGHT 가중치
    official: bool      # OFFICIAL_YN — 사업계획서 1.5 성과지표인가
    basis: str          # MEASURE_BASIS 측정 근거
    formula: str        # FORMULA_TEXT 산식
    source_type: str    # KPI_MEASURES.SOURCE_TYPE 산출 근거 구분
    start_label: str    # 구간 시작 시각의 정본 컬럼
    end_label: str      # 구간 종료 시각의 정본 컬럼

    @property
    def improve_rate(self) -> float:
        """개선율(%) = (기존 − 목표) ÷ 기존 × 100."""
        return improve_rate(self.base, self.target)


# 사업계획서 1.5 확정값 — **이 두 건이 공식 성과지표의 전부다**(D-21).
DEFS: dict[str, KpiDef] = {
    CODE_MFG: KpiDef(
        code=CODE_MFG,
        name="제조 리드타임 단축",
        field="P",
        uom="h",
        base=1320.0,
        target=1080.0,
        weight=0.5,
        official=True,
        basis="2025년 생산 일지 (사업계획서 1.5)",
        formula="작업지시 확정시각 ~ 포장완료 시각 평균 소요시간(h). 감소율 = (기존−목표)÷기존×100",
        source_type="작업지시~포장완료",
        start_label="PRC_WORK_ORDERS.CONFIRM_DT",
        end_label="SHP_SHIPMENT_ITEMS.PACKING_DT",
    ),
    CODE_O2D: KpiDef(
        code=CODE_O2D,
        name="수주출하 리드타임 감소",
        field="D",
        uom="h",
        base=1440.0,
        target=1200.0,
        weight=0.5,
        official=True,
        basis="2025년 생산 일지 3개월분 (사업계획서 1.5)",
        formula="출하시각 − 수주확정시각 평균(h). 감소율 = (기존−목표)÷기존×100",
        source_type="수주확정~출하",
        start_label="EST_PROJECTS.ORDER_CONFIRM_DT",
        end_label="SHP_SHIPMENTS.SHIP_DT",
    ),
}

OFFICIAL_CODES: tuple[str, ...] = tuple(c for c, d in DEFS.items() if d.official)

# 품질 KPI(044) 가 공식 지표가 아님을 화면마다 같은 문구로 밝힌다.
NOT_OFFICIAL_NOTE = (
    "운영지표 — 사업계획서 1.5 성과지표 2건(제조 리드타임·수주출하 리드타임)에 "
    "포함되지 않는다. 정부 성과지표 산출 근거로 쓰지 않는다."
)
OFFICIAL_NOTE = "공식 성과지표 (사업계획서 1.5 · D-21)"

# 달성률 정의 — 정본에 산식이 없어 여기서 정하고 화면에 함께 띄운다 (가설 D-202).
ACHIEVE_FORMULA = "달성률(%) = (기존값 − 측정값) ÷ (기존값 − 목표값) × 100"


# ── 순수 계산 — DB 없이 단독 재계산할 수 있어야 한다 (테스트가 이걸로 검증한다) ────────
def improve_rate(base: float, target: float) -> float:
    """감소율(%). 소수 1자리 — TD3 045 목업 grid_sample 이 18.200 / 16.700 이다."""
    if not base:
        raise ValueError("기존값이 0이면 감소율을 낼 수 없다")
    return round((float(base) - float(target)) / float(base) * 100.0, 1)


def mean_hours(values: Sequence[float]) -> float | None:
    """평균 소요시간(h). **표본 0건이면 `None`** — 0.0 으로 메우지 않는다(G-11)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def achieve_rate(base: float, target: float, measured: float | None) -> float | None:
    """달성률(%) — 기존값에서 목표값까지의 개선 폭 중 얼마나 왔는가 (D-202)."""
    if measured is None:
        return None
    span = float(base) - float(target)
    if not span:
        return None
    return round((float(base) - float(measured)) / span * 100.0, 1)


def ratio_pct(numerator: float | None, denominator: float | None) -> float | None:
    """비율(%). 분모 0·None 이면 **`None`** — 0% 라고 말하지 않는다."""
    if numerator is None or not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100.0, 1)


# ── 측정 결과 ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Measure:
    definition: KpiDef
    period: str | None
    sample_cnt: int
    value: float | None         # 평균 리드타임(h) — 0건이면 None
    achieve: float | None       # 달성률(%)

    @property
    def collected(self) -> bool:
        return self.value is not None

    @property
    def value_text(self) -> str:
        return "—" if self.value is None else f"{self.value:,.1f} {self.definition.uom}"

    @property
    def achieve_text(self) -> str:
        return "—" if self.achieve is None else f"{self.achieve:,.1f} %"


# ── DB 산출 ──────────────────────────────────────────────────────────────
_SQL_MFG = """
with lot_wo as (
    select LOT_TRACE_ID, WORK_ORDER_ID from SHP_LOT_TRACES  where WORK_ORDER_ID is not null
    union
    select LOT_TRACE_ID, WORK_ORDER_ID from PRC_PERFORMANCES where LOT_TRACE_ID is not null
),
started as (
    select lw.LOT_TRACE_ID, min(wo.CONFIRM_DT) as start_dt
    from lot_wo lw
    join PRC_WORK_ORDERS wo on wo.WORK_ORDER_ID = lw.WORK_ORDER_ID
    where wo.CONFIRM_DT is not null
    group by lw.LOT_TRACE_ID
),
packed as (
    select LOT_TRACE_ID, max(PACKING_DT) as end_dt
    from SHP_SHIPMENT_ITEMS where PACKING_DT is not null
    group by LOT_TRACE_ID
)
select lt.PRODUCT_LOT_NO           as subject_no,
       pj.PROJECT_NO               as project_no,
       s.start_dt                  as start_dt,
       k.end_dt                    as end_dt,
       extract(epoch from (k.end_dt - s.start_dt)) / 3600.0 as hours,
       to_char(k.end_dt, 'YYYY-MM')                         as period_code
from SHP_LOT_TRACES lt
join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID
join started s       on s.LOT_TRACE_ID = lt.LOT_TRACE_ID
join packed  k       on k.LOT_TRACE_ID = lt.LOT_TRACE_ID
where k.end_dt >= s.start_dt
  and (%(period)s::text is null or to_char(k.end_dt, 'YYYY-MM') = %(period)s)
order by k.end_dt desc
"""

_SQL_O2D = """
select sh.SHIPMENT_NO             as subject_no,
       pj.PROJECT_NO              as project_no,
       pj.ORDER_CONFIRM_DT        as start_dt,
       sh.SHIP_DT                 as end_dt,
       extract(epoch from (sh.SHIP_DT - pj.ORDER_CONFIRM_DT)) / 3600.0 as hours,
       to_char(sh.SHIP_DT, 'YYYY-MM')                                  as period_code
from SHP_SHIPMENTS sh
join EST_PROJECTS pj on pj.PROJECT_ID = sh.PROJECT_ID
where sh.SHIP_DT is not null
  and pj.ORDER_CONFIRM_DT is not null
  and sh.SHIP_DT >= pj.ORDER_CONFIRM_DT
  and (%(period)s::text is null or to_char(sh.SHIP_DT, 'YYYY-MM') = %(period)s)
order by sh.SHIP_DT desc
"""

_SQL = {CODE_MFG: _SQL_MFG, CODE_O2D: _SQL_O2D}


def definition(code: str) -> KpiDef:
    """모르는 코드는 **터진다** — 조용히 새 KPI 를 만들지 않는다."""
    return DEFS[code]


def samples(code: str, period: str | None = None) -> list[dict[str, Any]]:
    """구간 표본. 화면이 '산출 근거' 로 그대로 보여 준다 (디지털 스레드 G-08)."""
    import conn
    return conn.q(_SQL[code], {"period": period})


def measure(code: str, period: str | None = None) -> Measure:
    d = definition(code)
    rows = samples(code, period)
    value = mean_hours([r["hours"] for r in rows])
    return Measure(
        definition=d,
        period=period,
        sample_cnt=len(rows),
        value=value,
        achieve=achieve_rate(d.base, d.target, value),
    )


def summary(period: str | None = None) -> list[Measure]:
    """**공식 성과지표 2종.** 대시보드·현황판·043·045 가 전부 이것을 쓴다."""
    return [measure(code, period) for code in OFFICIAL_CODES]


def targets_in_db() -> list[dict[str, Any]]:
    """`KPI_TARGETS` 실적재 행. 시드 전이면 0건이고 화면은 `미수집` 을 낸다."""
    import conn
    return conn.q(
        "select KPI_TARGET_ID, KPI_CODE, KPI_NAME, KPI_FIELD, UOM, BASE_VALUE, TARGET_VALUE, "
        "IMPROVE_RATE, WEIGHT, OFFICIAL_YN, MEASURE_BASIS, FORMULA_TEXT "
        "from KPI_TARGETS order by OFFICIAL_YN desc, KPI_CODE"
    )


def measures_in_db(code: str | None = None) -> list[dict[str, Any]]:
    import conn
    return conn.q(
        "select t.KPI_CODE, t.KPI_NAME, t.UOM, t.BASE_VALUE, t.TARGET_VALUE, t.OFFICIAL_YN, "
        "m.PERIOD_CODE, m.SAMPLE_CNT, m.MEASURE_VALUE, m.ACHIEVE_RATE, m.SOURCE_TYPE, "
        "m.AGGREGATED_DT, m.REMARK "
        "from KPI_MEASURES m join KPI_TARGETS t on t.KPI_TARGET_ID = m.KPI_TARGET_ID "
        "where (%(code)s::text is null or t.KPI_CODE = %(code)s) "
        "order by t.KPI_CODE, m.PERIOD_CODE desc",
        {"code": code},
    )


# ── 품질 KPI (044) — **공식 성과지표가 아니다** ─────────────────────────────
@dataclass(frozen=True)
class QualityKpi:
    inspect_cnt: int
    pass_cnt: int
    pass_rate: float | None        # 출하 합격률(%)
    good_qty: float
    defect_qty: float
    defect_rate: float | None      # 공정 불량률(%)
    shipment_cnt: int
    claim_cnt: int
    claim_rate: float | None       # 클레임 발생률(%)
    official = False

    @property
    def note(self) -> str:
        return NOT_OFFICIAL_NOTE


def quality(period: str | None = None) -> QualityKpi:
    """검사·실적·클레임 집계. 분모가 0이면 비율은 `None` 이고 화면은 `미수집` 을 낸다."""
    import conn
    ins = conn.q1(
        "select count(*) as cnt, count(*) filter (where JUDGE_RESULT = '합격') as pass_cnt "
        "from SHP_INSPECTIONS "
        "where (%(period)s::text is null or to_char(INSPECT_DT, 'YYYY-MM') = %(period)s)",
        {"period": period},
    ) or {"cnt": 0, "pass_cnt": 0}
    perf = conn.q1(
        "select coalesce(sum(GOOD_QTY), 0) as good_qty, coalesce(sum(DEFECT_QTY), 0) as defect_qty "
        "from PRC_PERFORMANCES "
        "where (%(period)s::text is null or to_char(START_DT, 'YYYY-MM') = %(period)s)",
        {"period": period},
    ) or {"good_qty": 0, "defect_qty": 0}
    shp = conn.q1(
        "select count(*) as cnt from SHP_SHIPMENTS where SHIP_DT is not null "
        "and (%(period)s::text is null or to_char(SHIP_DT, 'YYYY-MM') = %(period)s)",
        {"period": period},
    ) or {"cnt": 0}
    clm = conn.q1(
        "select count(*) as cnt from SHP_CLAIMS "
        "where (%(period)s::text is null or to_char(RECEIVED_DT, 'YYYY-MM') = %(period)s)",
        {"period": period},
    ) or {"cnt": 0}

    good = float(perf["good_qty"] or 0)
    bad = float(perf["defect_qty"] or 0)
    return QualityKpi(
        inspect_cnt=int(ins["cnt"] or 0),
        pass_cnt=int(ins["pass_cnt"] or 0),
        pass_rate=ratio_pct(ins["pass_cnt"], ins["cnt"]),
        good_qty=good,
        defect_qty=bad,
        defect_rate=ratio_pct(bad, good + bad),
        shipment_cnt=int(shp["cnt"] or 0),
        claim_cnt=int(clm["cnt"] or 0),
        claim_rate=ratio_pct(clm["cnt"], shp["cnt"]),
    )
