"""AI 학습 데이터셋 (화면 037) — `DAT_TRAIN_DATASETS` · `_ITEMS` · `_SPLITS` · `_PREPROCESS_RULES`.

D-03 실태를 **데이터로** 들고 있는 곳이다. 총 건수·제외 건수·분포 검증 결과는 전부
`docs/cad/` 실측에서 왔다 — 추정값을 넣지 않는다.

전처리·분할 실행은 **확정 전까지 상태만 바꾼다**(작성 → 검증 → 확정, TD5 `DATASET_STATUS`).
"""
from __future__ import annotations

from typing import Any

import conn

from ..app.util import http

STATUSES = ("작성", "검증", "확정")
SPLIT_TYPES = ("Train", "Validation", "Test")
RULE_STAGES = ("필터링", "변환", "정제", "통합", "축소")
SOURCE_TYPES = ("CAD도면", "견적이력", "공정실적")


def datasets(**f: Any) -> list[dict[str, Any]]:
    conds, params = [], []
    for col, key in (("DATASET_NAME", "dataset_name"), ("TARGET_MODEL", "target_model"),
                     ("DATASET_VERSION", "dataset_version"), ("DATASET_STATUS", "dataset_status")):
        v = f.get(key)
        if v:
            conds.append(f"d.{col} = %s")
            params.append(v)
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    return conn.q(
        "select d.DATASET_ID, d.DATASET_NAME, d.TARGET_MODEL, d.DATASET_VERSION, d.TOTAL_CNT, "
        "       d.EXCLUDED_CNT, d.BALANCE_RESULT, d.DATASET_STATUS, d.CREATED_DT, "
        "       (select count(*) from DAT_DATASET_ITEMS i where i.DATASET_ID = d.DATASET_ID) as items, "
        "       (select count(*) from DAT_DATASET_SPLITS s where s.DATASET_ID = d.DATASET_ID) as splits "
        f"from DAT_TRAIN_DATASETS d {where}order by d.DATASET_NAME, d.DATASET_VERSION", params)


def splits(dataset_id: int | None = None) -> list[dict[str, Any]]:
    sql = ("select s.SPLIT_ID, d.DATASET_NAME, s.SPLIT_TYPE, s.SPLIT_RATIO, s.SPLIT_CNT, "
           "       s.SPLIT_RULE, s.SPLIT_DT "
           "from DAT_DATASET_SPLITS s join DAT_TRAIN_DATASETS d on d.DATASET_ID = s.DATASET_ID ")
    params: list[Any] = []
    if dataset_id:
        sql += "where s.DATASET_ID = %s "
        params.append(dataset_id)
    return conn.q(sql + "order by d.DATASET_NAME, s.SPLIT_ID", params)


def items(dataset_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = ("select i.ITEM_ID, i.SOURCE_TYPE, i.SOURCE_ID, i.LABEL_VALUE, i.IMPUTED_YN, "
           "       i.OUTLIER_REMOVED_YN, i.DEDUP_KEY "
           "from DAT_DATASET_ITEMS i ")
    params: list[Any] = []
    if dataset_id:
        sql += "where i.DATASET_ID = %s "
        params.append(dataset_id)
    params.append(max(1, min(limit, 500)))
    return conn.q(sql + "order by i.ITEM_ID limit %s", params)


def preprocess_rules() -> list[dict[str, Any]]:
    return conn.q(
        "select RULE_ID, RULE_NAME, RULE_STAGE, TARGET_DESC, RULE_EXPR, APPLY_ORDER, USE_YN "
        "from DAT_PREPROCESS_RULES order by APPLY_ORDER, RULE_ID")


def label_coverage(dataset_id: int) -> dict[str, Any]:
    """Label 확보율 — **D-04 판정의 근거다.** 0% 면 학습 게이트는 `차단`이다."""
    row = conn.q1(
        "select count(*) as total, count(LABEL_VALUE) as labeled "
        "from DAT_DATASET_ITEMS where DATASET_ID = %s", (dataset_id,))
    total = int(row["total"]) if row else 0
    labeled = int(row["labeled"]) if row else 0
    return {
        "total": total, "labeled": labeled,
        "rate": (labeled / total) if total else None,
        "verdict": "차단 (D-04)" if labeled == 0 else f"{labeled}/{total}",
        "note": "과거 견적금액·실제 제조원가 Label 확보 여부가 확인되지 않았다 (D-04)",
    }


def set_status(dataset_id: int, status: str) -> int:
    """상태 전이만 한다. 건수·성능을 여기서 만들지 않는다."""
    if status not in STATUSES:
        raise http.fail("validation", f"데이터셋 상태 어휘 위반: {status!r} (TD5 {STATUSES})")
    return conn.x(
        "update DAT_TRAIN_DATASETS set DATASET_STATUS = %s, UPDATED_DT = now() where DATASET_ID = %s",
        (status, dataset_id))
