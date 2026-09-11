"""모델·학습이력·예측·SHAP 읽기 경로 (화면 014·015).

**쓰기 경로가 없다.** 학습은 다음 단독 회전이고, 여기서 성능 수치를 만들지 않는다.
`EST_ML_MODELS` · `EST_ML_TRAIN_RUNS` · `EST_ML_PREDICTIONS` · `EST_SHAP_FACTORS` 는
깨끗한 DB 에서 **0건이 정상**이다(G-11) — 그때 화면은 `미수집` 문구를 렌더한다.
"""
from __future__ import annotations

from typing import Any

import conn

from ..app.util import http
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


# ── MLOps 배포·롤백 (G-25) ────────────────────────────────────────────────
# TD5 `EST_ML_MODELS.DEPLOY_STATUS` 어휘 그대로. 어휘 밖 값을 쓰지 않는다.
DEPLOY_STATUSES: tuple[str, ...] = ("학습중", "검증", "배포", "폐기")
DEPLOYED, VALIDATED, RETIRED = "배포", "검증", "폐기"


def deployed_model(model_name: str) -> dict[str, Any] | None:
    """지금 배포 중인 버전. 모델명당 **하나만** 배포 상태다."""
    return conn.q1(
        "select MODEL_ID, MODEL_NAME, MODEL_VERSION, DEPLOY_STATUS, DEPLOYED_DT "
        "from EST_ML_MODELS where MODEL_NAME = %s and DEPLOY_STATUS = %s "
        "order by DEPLOYED_DT desc nulls last, MODEL_ID desc limit 1",
        (model_name, DEPLOYED))


def previous_version(model_name: str) -> dict[str, Any] | None:
    """직전에 배포됐던 버전 — **롤백 대상**.

    지금 배포 중인 것보다 `DEPLOYED_DT`(없으면 MODEL_ID)가 앞서고, 폐기되지 않은 것 중
    가장 최근 것이다. 없으면 `None` — 되돌릴 곳이 없다는 사실을 그대로 돌려준다.
    """
    cur = deployed_model(model_name)
    if cur is None:
        return None
    return conn.q1(
        "select MODEL_ID, MODEL_NAME, MODEL_VERSION, DEPLOY_STATUS, DEPLOYED_DT, METRIC_JSON "
        "from EST_ML_MODELS "
        "where MODEL_NAME = %s and MODEL_ID <> %s and DEPLOY_STATUS <> %s "
        "  and (DEPLOYED_DT is not null or DEPLOY_STATUS = %s) "
        "order by DEPLOYED_DT desc nulls last, MODEL_ID desc limit 1",
        (model_name, cur["model_id"], RETIRED, VALIDATED))


def deploy(model_id: int) -> dict[str, Any]:
    """한 버전을 배포한다. 같은 모델명의 다른 배포본은 **검증**으로 내린다 (동시 배포 금지)."""
    row = conn.q1("select MODEL_ID, MODEL_NAME, MODEL_VERSION, DEPLOY_STATUS "
                  "from EST_ML_MODELS where MODEL_ID = %s", (model_id,))
    if row is None:
        raise http.fail("validation", f"모델 {model_id} 가 없다")
    with conn.tx() as cur:
        cur.execute(
            "update EST_ML_MODELS set DEPLOY_STATUS = %s, UPDATED_DT = now() "
            "where MODEL_NAME = %s and MODEL_ID <> %s and DEPLOY_STATUS = %s",
            (VALIDATED, row["model_name"], model_id, DEPLOYED))
        demoted = cur.rowcount
        cur.execute(
            "update EST_ML_MODELS set DEPLOY_STATUS = %s, DEPLOYED_DT = now(), UPDATED_DT = now() "
            "where MODEL_ID = %s", (DEPLOYED, model_id))
    return {"model_id": model_id, "model_name": row["model_name"],
            "model_version": row["model_version"], "deploy_status": DEPLOYED,
            "demoted": demoted}


def rollback(model_name: str) -> dict[str, Any]:
    """**직전 버전으로 되돌린다** (G-25 MLOps 롤백 경로).

    지금 배포본은 `검증` 으로 내리고 직전 버전을 `배포` 로 올린다. 이력을 지우지 않는다 —
    어느 버전이 언제 배포됐는지가 `DEPLOY_STATUS` · `DEPLOYED_DT` 에 남아야 되돌린 사실도 남는다.
    되돌릴 버전이 없으면 **422** 다. 없는데 성공한 척하지 않는다(§2.5).
    """
    cur_model = deployed_model(model_name)
    if cur_model is None:
        raise http.fail("validation", f"'{model_name}' 은 지금 배포 중인 버전이 없다 — 되돌릴 것이 없다")
    prev = previous_version(model_name)
    if prev is None:
        raise http.fail("validation",
                        f"'{model_name}' 의 직전 버전이 없다 — 되돌릴 곳이 없다 "
                        f"(현재 {cur_model['model_version']} 하나뿐)")
    out = deploy(int(prev["model_id"]))
    return {**out, "rolled_back_from": cur_model["model_version"],
            "rolled_back_to": prev["model_version"]}
