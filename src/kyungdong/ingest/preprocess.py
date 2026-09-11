"""전처리 (G-13) — 이상치 판정 · 결측 보정 · 처리 건수 기록.

**DEF-QA2-003 · 004 · 006 을 여기서 고친다.** 회전 6 까지 `노이즈` 는 `ingest/tags.QUALITY_FLAGS`
어휘로만 있었고 보정 코드는 0건이었으며, 처리 건수는 `DAT_JOB_LOGS` 에 한 줄도 남지 않았다.

세 가지를 **서로 다른 단계**에 둔다 — 섞으면 원천이 오염된다.

| 단계 | 무엇 | 어디 |
|---|---|---|
| ① 적재 시(인라인) | 이상치 **판정** → `DAT_TIMESERIES.QUALITY_FLAG='노이즈'` | `collector.ingest_batch` 가 부른다 |
| ② 명시 실행 | 결측 **보정**(선형 보간·Forward Fill) | `preprocess.run()` · `POST /dat/037/preprocess` |
| ③ 실행마다 | 처리·실패 건수 | `DAT_JOB_LOGS.PROCESS_CNT` · `FAIL_CNT` |

**이상치를 지우지 않는다.** 결측을 버리지 않는 것과 같은 이유다(§2.5 조용한 실패 금지) —
값은 남기고 `QUALITY_FLAG` 로 표시한다. 학습에서 빼는 것은 데이터셋 단계
(`DAT_DATASET_ITEMS.OUTLIER_REMOVED_YN`)의 일이지 수집 단계의 일이 아니다.

**보정은 적재의 일부가 아니다.** `ingest_batch()` 는 비숫자값을 `MEASURE_VALUE=NULL` ·
`QUALITY_FLAG='결측'` 으로 그대로 남긴다(QA2 가 실측으로 확인한 옳은 동작이다).
보정은 **별도 실행**이고, 보정 뒤에도 `QUALITY_FLAG='결측'` 은 **지우지 않는다** —
`MEASURE_VALUE` 가 채워진 `결측` 행이 곧 "보정된 행" 이다(D-314).
원본은 `IF_PLC_SIGNALS.RAW_VALUE` 에 그대로 남아 있어 되돌릴 수 있다.

**판정 기준의 출처 (D-315)**
  1순위 `PRC_STD_CONDITIONS`(표준조건 허용 상·하한) — **정본이다.** 현재 0건이다(D-203).
  2순위 **조작적 정의** — 중앙값·MAD 로버스트 z-score. 임계는 `Z_LIMIT` 이고 **정본 수치가 아니다.**
  표본이 `MIN_HISTORY` 미만이거나 MAD·표준편차가 0이면 **판정하지 않는다**(`판정 불가`).
  없는 상·하한을 지어내지 않는다 — 사업계획서에 전류·온도 정상 범위 표가 없다(missing-policy §4).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

import conn

from ..app.util import http
from . import tags

# ── 판정 상수 ────────────────────────────────────────────────────────────
#   정본 수치가 아니다. `DAT_PREPROCESS_RULES.RULE_EXPR` 에 같은 문장이 적혀 있고
#   화면 037 이 그대로 렌더한다. 도입기업이 상·하한 표를 주면 1순위 경로로 넘어간다.
Z_LIMIT = 3.5            # 로버스트 z-score 임계 (조작적 정의 — D-315)
MIN_HISTORY = 8          # 이만큼 모이기 전에는 판정하지 않는다
HISTORY_LIMIT = 500      # 판정에 쓰는 직전 표본 상한
MAD_SCALE = 0.6745       # 정규분포에서 MAD → σ 환산 상수

BASIS_TOLERANCE = "표준조건 허용범위 (PRC_STD_CONDITIONS)"
BASIS_ROBUST_Z = f"로버스트 z-score |z| > {Z_LIMIT} (중앙값·MAD — 조작적 정의 D-315)"
BASIS_UNDECIDABLE = f"표본 {MIN_HISTORY}건 미만 또는 산포 0 — 판정 불가"

IMPUTE_LINEAR = "선형 보간"
IMPUTE_FFILL = "Forward Fill"
IMPUTE_NONE = "미보정"
IMPUTE_METHODS = (IMPUTE_LINEAR, IMPUTE_FFILL, IMPUTE_NONE)

# `DAT_PREPROCESS_RULES.RULE_NAME` — 시드(`db/seed_dev3.py`)가 넣는다. `USE_YN='N'` 이면 끈다.
RULE_OUTLIER = "센서 이상치 판정"
RULE_IMPUTE = "시계열 결측 보정"

# `DAT_INTEGRATION_JOBS.JOB_NAME` — 시드(`db/seed_dev1.py`)가 수집대상 1건당 1건 만든다.
JOB_PLC = "레이저커팅기 PLC 수집"
JOB_CAD = "CAD 도면함 수집"

# `DAT_JOB_LOGS.RESULT_CODE` 비고 어휘
RESULT_CODES = ("성공", "실패", "부분성공")

# 도면 쪽 결측 보정(치수 누락·재질 미입력을 **유사 도면·기준값**으로)은 **차단**이다.
# 원천이 없다 — `EST_CAD_OBJECTS` 에 치수·재질 컬럼을 채울 Parsing·OCR 이 미구성이다(D-05).
# 0 이나 최빈값으로 채우면 합성 Feature 를 만드는 것이라 §10-18 위반이다.
BLOCKED_IMPUTATION: dict[str, str] = {
    "도면 치수 누락": "EST_CAD_OBJECTS 0행 — Parsing 미구성이라 유사 도면 비교 대상이 없다 (D-05)",
    "OCR 오류": "도면 표제란 OCR 미구성 — 오인식 원문이 없어 대조할 수 없다 (D-05)",
    "재질 미입력": "재질 기준값 원천(표제란 OCR · 품목/재질 코드 그룹)이 둘 다 비어 있다 (D-05 · D-47)",
}


@dataclass
class OutlierVerdict:
    flag: str                       # '정상' | '노이즈'
    basis: str                      # 판정 근거 문장
    decided: bool = True            # False 면 판정하지 않았다(표본 부족)
    score: float | None = None      # 로버스트 z (1순위 경로면 None)

    @property
    def noise(self) -> bool:
        return self.flag == "노이즈"


@dataclass
class PreprocessResult:
    """전처리 1회 실행의 실측. 여기 숫자가 그대로 `DAT_JOB_LOGS` 로 간다."""
    started: datetime | None = None
    ended: datetime | None = None
    scanned: int = 0                # 검사 대상 행
    imputed: int = 0                # 보정 성공
    unimputed: int = 0             # 앞선 정상값이 없어 보정하지 못한 것 = 실패 건수
    by_method: dict[str, int] = field(default_factory=dict)
    outliers: int = 0              # 이미 '노이즈' 로 표시된 행 (집계용 — 여기서 새로 찍지 않는다)
    job_log_id: int | None = None
    blocked: dict[str, str] = field(default_factory=lambda: dict(BLOCKED_IMPUTATION))

    @property
    def result_code(self) -> str:
        if self.unimputed and self.imputed:
            return "부분성공"
        return "실패" if self.unimputed else "성공"


# ── 규칙 on/off ──────────────────────────────────────────────────────────
def rule_on(rule_name: str) -> bool:
    """`DAT_PREPROCESS_RULES` 가 규칙 정본이다. 행이 없으면 **끈 것으로 본다** —
    코드가 DB 에 없는 규칙을 몰래 적용하지 않는다."""
    row = conn.q1("select USE_YN from DAT_PREPROCESS_RULES where RULE_NAME = %s", (rule_name,))
    return bool(row) and row["use_yn"] == "Y"


def rules() -> list[dict[str, Any]]:
    return conn.q(
        "select RULE_NAME, RULE_STAGE, TARGET_DESC, RULE_EXPR, APPLY_ORDER, USE_YN "
        "from DAT_PREPROCESS_RULES order by APPLY_ORDER, RULE_ID")


# ── ① 이상치 판정 ────────────────────────────────────────────────────────
def tolerance(cur, tag_name: str) -> tuple[float, float] | None:
    """정본 허용 상·하한. `PRC_STD_CONDITIONS` 는 현재 0건이다(D-203) → `None`."""
    t = tags.tag(tag_name)
    if t is None:
        return None
    cur.execute(
        "select TOL_MIN, TOL_MAX from PRC_STD_CONDITIONS "
        "where USE_YN = 'Y' and COND_ITEM = %s and TOL_MIN is not null and TOL_MAX is not null "
        "order by STD_COND_ID limit 1",
        (t.ko,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return float(row["tol_min"]), float(row["tol_max"])


def history(cur, tag_name: str, equip_code: str | None, before_dt: datetime) -> list[float]:
    """판정 표본 — 같은 태그·설비의 **직전 정상값**. 노이즈·결측은 표본에 넣지 않는다."""
    cur.execute(
        "select MEASURE_VALUE from DAT_TIMESERIES "
        "where TAG_NAME = %s and EQUIP_CODE is not distinct from %s and MEASURE_DT < %s "
        "  and MEASURE_VALUE is not null and QUALITY_FLAG = '정상' "
        "order by MEASURE_DT desc limit %s",
        (tag_name, equip_code, before_dt, HISTORY_LIMIT),
    )
    return [float(r["measure_value"]) for r in cur.fetchall()]


def robust_z(value: float, sample: Sequence[float]) -> float | None:
    """중앙값·MAD 기반 z. 산포가 0이면 **판정하지 않는다**(`None`) — 0 나눗셈을 숨기지 않는다."""
    if len(sample) < MIN_HISTORY:
        return None
    med = statistics.median(sample)
    mad = statistics.median([abs(x - med) for x in sample])
    if mad > 0:
        return MAD_SCALE * (value - med) / mad
    sd = statistics.pstdev(sample)
    if sd > 0:
        return (value - med) / sd
    return None                     # 완전 상수 계열 — 변화를 이상치로 단정하지 않는다


def judge(cur, tag_name: str, equip_code: str | None, value: float | None,
          measure_dt: datetime, *, enabled: bool = True) -> OutlierVerdict:
    """한 측정값의 품질 플래그를 정한다. **값을 바꾸거나 지우지 않는다.**

    `enabled` 는 호출자가 `rule_on(RULE_OUTLIER)` 로 **배치당 한 번** 읽어 넘긴다 —
    샘플마다 규칙 표를 다시 읽지 않는다.
    """
    if value is None:
        return OutlierVerdict("결측", "숫자로 변환되지 않았다 — 버리지 않고 표시만 한다", True)
    if not enabled:
        return OutlierVerdict("정상", f"규칙 '{RULE_OUTLIER}' 가 꺼져 있다 (USE_YN='N')", False)
    tol = tolerance(cur, tag_name)
    if tol is not None:
        lo, hi = tol
        out = value < lo or value > hi
        return OutlierVerdict("노이즈" if out else "정상",
                              f"{BASIS_TOLERANCE} [{lo}, {hi}]", True)
    z = robust_z(value, history(cur, tag_name, equip_code, measure_dt))
    if z is None:
        return OutlierVerdict("정상", BASIS_UNDECIDABLE, False)
    return OutlierVerdict("노이즈" if abs(z) > Z_LIMIT else "정상",
                          BASIS_ROBUST_Z, True, score=z)


# ── ② 결측 보정 ──────────────────────────────────────────────────────────
def _neighbour(cur, tag_name: str, equip_code: str | None, dt: datetime, direction: str):
    op, order = ("<", "desc") if direction == "prev" else (">", "asc")
    cur.execute(
        f"select MEASURE_DT, MEASURE_VALUE from DAT_TIMESERIES "
        f"where TAG_NAME = %s and EQUIP_CODE is not distinct from %s and MEASURE_DT {op} %s "
        f"  and MEASURE_VALUE is not null and QUALITY_FLAG = '정상' "
        f"order by MEASURE_DT {order} limit 1",
        (tag_name, equip_code, dt),
    )
    row = cur.fetchone()
    return (row["measure_dt"], float(row["measure_value"])) if row else None


def impute_one(cur, row: dict[str, Any]) -> tuple[float | None, str]:
    """한 결측 행의 대체값과 방법. 앞선 정상값이 없으면 **채우지 않는다**(`미보정`)."""
    tag_name, equip, dt = row["tag_name"], row["equip_code"], row["measure_dt"]
    prev = _neighbour(cur, tag_name, equip, dt, "prev")
    if prev is None:
        return None, IMPUTE_NONE            # 앞이 없으면 back-fill 하지 않는다 — 미래를 끌어오지 않는다
    nxt = _neighbour(cur, tag_name, equip, dt, "next")
    if nxt is None:
        return prev[1], IMPUTE_FFILL
    (t0, v0), (t1, v1) = prev, nxt
    span = (t1 - t0).total_seconds()
    if span <= 0:
        return v0, IMPUTE_FFILL
    ratio = (dt - t0).total_seconds() / span
    return v0 + (v1 - v0) * ratio, IMPUTE_LINEAR


def impute_missing(*, equip_code: str | None = None, tag_name: str | None = None,
                   limit: int = 10_000) -> PreprocessResult:
    """`MEASURE_VALUE` 가 비어 있는 `결측` 행을 **선형 보간 · Forward Fill** 로 채운다.

    `QUALITY_FLAG='결측'` 은 그대로 둔다 — 원천이 결측이었다는 사실이고 지우면 추적이 끊긴다(D-314).
    같은 행을 두 번 보정하지 않는다(`MEASURE_VALUE is null` 조건이 곧 멱등 조건이다).
    """
    res = PreprocessResult(started=datetime.now())
    if not rule_on(RULE_IMPUTE):
        res.ended = datetime.now()
        return res
    where, params = ["QUALITY_FLAG = '결측'", "MEASURE_VALUE is null"], []
    if equip_code:
        where.append("EQUIP_CODE = %s")
        params.append(equip_code)
    if tag_name:
        where.append("TAG_NAME = %s")
        params.append(tag_name)
    with conn.tx() as cur:
        cur.execute(
            "select TS_ID, TAG_NAME, EQUIP_CODE, MEASURE_DT from DAT_TIMESERIES "
            f"where {' and '.join(where)} order by TAG_NAME, MEASURE_DT limit %s",
            (*params, limit),
        )
        targets = cur.fetchall()
        res.scanned = len(targets)
        for row in targets:
            value, method = impute_one(cur, row)
            res.by_method[method] = res.by_method.get(method, 0) + 1
            if value is None:
                res.unimputed += 1
                continue
            cur.execute("update DAT_TIMESERIES set MEASURE_VALUE = %s where TS_ID = %s",
                        (round(value, 4), row["ts_id"]))
            res.imputed += 1
    res.ended = datetime.now()
    return res


# ── ③ 처리 건수 기록 ─────────────────────────────────────────────────────
def job_id(job_name: str) -> int:
    row = conn.q1("select JOB_ID from DAT_INTEGRATION_JOBS where JOB_NAME = %s", (job_name,))
    if row is None:
        raise RuntimeError(
            f"`DAT_INTEGRATION_JOBS` 에 '{job_name}' 이 없다 — `uv run python db/seed_dev1.py`. "
            "통합작업 없이 실행 로그를 남길 수 없다(JOB_ID 는 NOT NULL FK)")
    return int(row["job_id"])


def log_job(job_name: str, *, started: datetime, ended: datetime | None,
            processed: int, failed: int, result: str, message: str | None = None) -> int:
    """`DAT_JOB_LOGS` 에 **전처리 실행 1회 = 1행**. 못 한 것도 실패로 남긴다(G-30)."""
    if result not in RESULT_CODES:
        raise http.fail("validation", f"실행 결과 어휘 위반: {result!r} (TD5 {RESULT_CODES})")
    row = conn.q1(
        "insert into DAT_JOB_LOGS "
        "(JOB_ID, START_DT, END_DT, PROCESS_CNT, FAIL_CNT, RESULT_CODE, ERROR_MSG, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s, now()) returning JOB_LOG_ID",
        (job_id(job_name), started, ended, processed, failed, result, (message or "")[:500] or None),
    )
    return int(row["job_log_id"])


def job_logs(job_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = ("select g.JOB_LOG_ID, j.JOB_NAME, g.START_DT, g.END_DT, g.PROCESS_CNT, g.FAIL_CNT, "
           "       g.RESULT_CODE, g.ERROR_MSG "
           "from DAT_JOB_LOGS g join DAT_INTEGRATION_JOBS j on j.JOB_ID = g.JOB_ID ")
    params: list[Any] = []
    if job_name:
        sql += "where j.JOB_NAME = %s "
        params.append(job_name)
    params.append(max(1, min(limit, 500)))
    return conn.q(sql + "order by g.JOB_LOG_ID desc limit %s", params)


# ── 실행 진입점 ──────────────────────────────────────────────────────────
def run(*, equip_code: str | None = None, job_name: str = JOB_PLC) -> PreprocessResult:
    """전처리 1회 실행 — 결측 보정 + 이상치 집계 → `DAT_JOB_LOGS` 1행.

    이상치는 **적재 시 이미 판정됐다**(`collector.ingest_batch`). 여기서는 건수만 센다 —
    같은 판정을 두 곳에서 하면 §10-16 로직 복제다.
    """
    res = impute_missing(equip_code=equip_code)
    noise = conn.q1(
        "select count(*) as n from DAT_TIMESERIES where QUALITY_FLAG = '노이즈'"
        + (" and EQUIP_CODE = %s" if equip_code else ""),
        (equip_code,) if equip_code else (),
    )
    res.outliers = int(noise["n"]) if noise else 0
    note = (f"결측 보정 {res.imputed}건({res.by_method}) · 미보정 {res.unimputed}건 · "
            f"이상치 표시 누계 {res.outliers}건. "
            f"도면 결측 보정은 차단: {' / '.join(BLOCKED_IMPUTATION)} (D-05)")
    res.job_log_id = log_job(
        job_name, started=res.started, ended=res.ended,
        processed=res.imputed, failed=res.unimputed,
        result=res.result_code, message=note)
    return res
