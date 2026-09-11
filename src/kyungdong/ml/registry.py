"""모델·학습이력·예측·SHAP 읽기 경로 (화면 014·015).

**쓰기 경로가 없다.** 학습은 다음 단독 회전이고, 여기서 성능 수치를 만들지 않는다.
`EST_ML_MODELS` · `EST_ML_TRAIN_RUNS` · `EST_ML_PREDICTIONS` · `EST_SHAP_FACTORS` 는
깨끗한 DB 에서 **0건이 정상**이다(G-11) — 그때 화면은 `미수집` 문구를 렌더한다.
"""
from __future__ import annotations

from typing import Any

import conn

from . import TRAINING_DEFERRED

# 사업계획서 2.6 AI 성능목표 5종 — **목표치이고 달성값이 아니다**(D-22).
TARGETS: tuple[dict[str, str], ...] = (
    {"no": "①", "name": "CAD 객체 인식", "target": "80% 이상",
     "metric": "IoU 0.5 기준 Precision·Recall·F1", "blocked": "D-05 가중치·파서 미확보"},
    {"no": "②", "name": "견적 산출 정확도", "target": "±5% 이내",
     "metric": "MAPE·MAE", "blocked": "D-04 견적·원가 Label 확보 미확인"},
    {"no": "③", "name": "BOM 생성 정확도", "target": "85% 이상",
     "metric": "항목 단위 Precision·Recall·F1", "blocked": "D-04 기준 BOM 부재"},
    {"no": "④", "name": "납기 예측 정확도", "target": "85% 이상",
     "metric": "허용 오차 범위 + RMSE (허용 오차는 가설 D-12)", "blocked": "D-04 실적 Label 부재"},
    {"no": "⑤", "name": "설명가능성", "target": "90%",
     "metric": "SHAP Top-N vs 전문가 · Spearman ρ", "blocked": "D-13 전문가 평가 변수 목록 없음"},
)


def models(**filters: Any) -> list[dict[str, Any]]:
    conds, params = [], []
    for col, key in (("MODEL_NAME", "model_name"), ("MODEL_TYPE", "model_type"),
                     ("MODEL_VERSION", "model_version"), ("DEPLOY_STATUS", "deploy_status")):
        v = filters.get(key)
        if v:
            conds.append(f"m.{col} = %s")
            params.append(v)
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    return conn.q(
        "select m.MODEL_ID, m.MODEL_NAME, m.MODEL_TYPE, m.MODEL_VERSION, m.DEPLOY_STATUS, "
        "       m.METRIC_JSON, m.HYPER_PARAMS, m.DEPLOYED_DT, d.DATASET_NAME, "
        "       (select count(*) from EST_ML_TRAIN_RUNS r where r.MODEL_ID = m.MODEL_ID) as runs "
        "from EST_ML_MODELS m left join DAT_TRAIN_DATASETS d on d.DATASET_ID = m.DATASET_ID "
        f"{where}order by m.MODEL_NAME, m.MODEL_VERSION", params)


def train_runs(model_id: int | None = None) -> list[dict[str, Any]]:
    sql = ("select r.TRAIN_RUN_ID, m.MODEL_NAME, m.MODEL_VERSION, r.START_DT, r.END_DT, "
           "       r.TRAIN_CNT, r.VALID_CNT, r.TEST_CNT, r.VALID_METRIC, r.OVERFIT_RESULT, r.RUN_STATUS "
           "from EST_ML_TRAIN_RUNS r join EST_ML_MODELS m on m.MODEL_ID = r.MODEL_ID ")
    params: list[Any] = []
    if model_id:
        sql += "where r.MODEL_ID = %s "
        params.append(model_id)
    return conn.q(sql + "order by r.START_DT desc, r.TRAIN_RUN_ID desc limit 100", params)


def predictions(target_type: str | None = None) -> list[dict[str, Any]]:
    sql = ("select p.PREDICT_ID, m.MODEL_NAME, p.TARGET_TYPE, p.TARGET_ID, p.PREDICT_VALUE, "
           "       p.ACTUAL_VALUE, p.ERROR_RATE, p.CONFIDENCE_SCORE, p.PREDICTED_DT "
           "from EST_ML_PREDICTIONS p join EST_ML_MODELS m on m.MODEL_ID = p.MODEL_ID ")
    params: list[Any] = []
    if target_type:
        sql += "where p.TARGET_TYPE = %s "
        params.append(target_type)
    return conn.q(sql + "order by p.PREDICTED_DT desc, p.PREDICT_ID desc limit 100", params)


def shap_factors(*, quote_no: str | None = None, feature_name: str | None = None,
                 rank_no: int | None = None) -> list[dict[str, Any]]:
    """`EST_SHAP_FACTORS` 는 `EST_ML_PREDICTIONS`(런타임 전용)를 FK 로 본다 — 예측 없이 행이 없다."""
    conds, params = [], []
    if feature_name:
        conds.append("s.FEATURE_NAME = %s")
        params.append(feature_name)
    if rank_no:
        conds.append("s.RANK_NO = %s")
        params.append(rank_no)
    if quote_no:
        conds.append("q.QUOTE_NO = %s")
        params.append(quote_no)
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    return conn.q(
        "select s.SHAP_ID, s.PREDICT_ID, q.QUOTE_NO, s.FEATURE_NAME, s.SHAP_VALUE, s.RANK_NO, "
        "       s.IMPACT_DIRECTION, s.EXPERT_MATCH_YN, s.OPTIMIZE_COMMENT "
        "from EST_SHAP_FACTORS s "
        "left join EST_ML_PREDICTIONS p on p.PREDICT_ID = s.PREDICT_ID "
        "left join EST_QUOTATIONS q on q.QUOTE_ID = p.TARGET_ID and p.TARGET_TYPE = '견적원가' "
        f"{where}order by s.PREDICT_ID desc, s.RANK_NO limit 100", params)


def readiness() -> dict[str, Any]:
    """학습 준비 상태 — **측정 가능한 것만 센다.** 못 재는 것은 `차단` 으로 남긴다."""
    def n(sql: str) -> int:
        row = conn.q1(sql)
        return int(row["n"]) if row else 0

    labeled = n("select count(*) as n from DAT_DATASET_ITEMS where LABEL_VALUE is not null")
    return {
        "status": TRAINING_DEFERRED,
        "datasets": n("select count(*) as n from DAT_TRAIN_DATASETS"),
        "dataset_items": n("select count(*) as n from DAT_DATASET_ITEMS"),
        "labeled_items": labeled,
        "splits": n("select count(*) as n from DAT_DATASET_SPLITS"),
        "drawings": n("select count(*) as n from EST_CAD_DRAWINGS"),
        "confirmed_objects": n("select count(*) as n from EST_CAD_OBJECTS where CONFIRM_YN = 'Y'"),
        "features": n("select count(*) as n from EST_CAD_FEATURES"),
        "cost_rates": n("select count(*) as n from EST_COST_RATES where USE_YN = 'Y'"),
        "models": n("select count(*) as n from EST_ML_MODELS"),
        "runs": n("select count(*) as n from EST_ML_TRAIN_RUNS"),
        "blockers": [
            "D-04 과거 견적금액·실제 제조원가 Label 확보 여부 미확인 — 견적·BOM·납기 정확도 측정 불가",
            "D-05 Autodesk API 계정·YOLOv8 가중치·OCR 미확보 — 객체 인식 학습 불가",
            "D-13 전문가 평가 변수 목록 없음 — 설명가능성 일치율 차단",
            "D-47 품목·재질·고객사 코드 그룹이 비어 있다 — BOM Rule 전개 불가",
        ],
        "targets": TARGETS,
    }
