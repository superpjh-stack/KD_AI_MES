"""CAD 5단계 파이프라인 — 수집 → 인식 → **HITL** → Feature → (BOM·견적·SHAP).

**승인 전에는 확정이 아니다** (TD3 standard_note 4 · G-24).
  · `EST_CAD_OBJECTS.CONFIRM_YN` 을 'Y' 로 바꾸는 경로는 `review_object()` **하나뿐**이고,
    거기서 `rbac.can_approve` 를 통과하지 못하면 403 이다.
  · Feature 는 **확정된 객체만** 집계한다. 확정이 0건이면 Feature 도 0건이다 — 채워 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import conn

from ..app import rbac
from ..app.settings import settings
from ..app.util import http
from ..ingest import preprocess
from . import inventory as inv
from . import provider

AREA = "수주견적AI관리"

# TD5 `EST_CAD_DRAWINGS.ANALYSIS_STATUS` · `IF_CAD_FILES.IF_STATUS` · `IF_CAD_IMPORT_LOGS` 비고
ANALYSIS_STATUSES = ("대기", "분석중", "완료", "오류")
IF_STATUSES = ("수신", "등록", "제외")
STEPS = ("수신", "검증", "중복제거", "등록")
RESULTS = ("성공", "실패", "제외")
REVIEW_RESULTS = ("승인", "수정", "반려")

# TD5 `EST_CAD_FEATURES.FEATURE_TYPE` 비고 어휘
FEATURE_TYPES = ("홀 수량", "총 절단장", "판재 면적", "용접장", "재질", "두께")

# 확정 객체만으로 실제 집계가 가능한 Feature. 나머지는 원천 컬럼이 없어 **차단**이다.
DERIVABLE: dict[str, tuple[str, str, str]] = {
    # FEATURE_TYPE: (집계 대상 OBJECT_TYPE, 단위, 산출 근거)
    "홀 수량": ("홀", "ea", "확정(CONFIRM_YN='Y') 객체 중 유형='홀' 건수 집계"),
}
BLOCKED_FEATURES: dict[str, str] = {
    "총 절단장": "EST_CAD_OBJECTS 에 경로 길이 컬럼이 없다 — Parsing 미구성 (D-05)",
    "판재 면적": "외곽 형상 좌표가 없다 — Parsing 미구성 (D-05)",
    "용접장": "용접선 객체 유형이 TD5 어휘에 없다 — 도면 속성 확보 필요 (D-05)",
    "재질": "도면 표제란 OCR 미구성 (D-05)",
    "두께": "도면 표제란 OCR 미구성 (D-05)",
}


@dataclass
class ImportResult:
    scanned: int = 0
    registered: int = 0
    excluded: int = 0
    skipped: int = 0            # 이미 수집된 파일 (멱등)
    drawings: int = 0
    by_reason: dict[str, int] | None = None
    job_log_id: int | None = None   # DAT_JOB_LOGS 실행 로그 (G-13 처리 건수)


def _log(cur, cad_if_id: int, step: str, result: str,
         reason: str | None = None, error: str | None = None) -> None:
    cur.execute(
        "insert into IF_CAD_IMPORT_LOGS "
        "(CAD_IF_ID, STEP_NAME, RESULT_CODE, EXCLUDE_REASON, PROCESSED_DT, ERROR_MSG, CREATED_DT) "
        "values (%s,%s,%s,%s, now(), %s, now())",
        (cad_if_id, step, result, reason, (error or "")[:500] or None),
    )


def import_inventory(*, limit: int | None = None, scope: str = "product",
                     created_by: int | None = None) -> ImportResult:
    """실측 인벤토리 → `IF_CAD_FILES` → 정제 → `EST_CAD_DRAWINGS` (MES-TD4-048).

    **멱등이다** — 같은 (원본 파일명, 원본 경로) 는 다시 수집하지 않는다.
    정제 **처리 건수는 `DAT_JOB_LOGS` 에 남는다**(G-13 · DEF-QA2-006) —
    단계별 이력(`IF_CAD_IMPORT_LOGS`)과 실행 단위 집계는 다른 것이다.
    """
    started = datetime.now()
    files = inv.read_inventory()
    cleaned = inv.clean(files, scope)
    if limit is not None:
        cleaned = cleaned[:limit]
    res = ImportResult(scanned=len(cleaned), by_reason={})
    for c in cleaned:
        f = c.src
        exists = conn.q1(
            "select CAD_IF_ID from IF_CAD_FILES where ORIGIN_FILE_NAME = %s and SOURCE_PATH = %s",
            (f.file_name, f.path),
        )
        if exists:
            res.skipped += 1
            continue
        with conn.tx() as cur:
            cur.execute(
                "insert into IF_CAD_FILES "
                "(ORIGIN_FILE_NAME, FILE_TYPE, SOURCE_PATH, FILE_SIZE, FILE_MTIME, "
                " COLLECT_METHOD, IF_STATUS, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s, now()) returning CAD_IF_ID",
                (f.file_name, f.file_type, f.path, f.size_bytes, f.mtime, "배치", "수신"),
            )
            cad_if_id = int(cur.fetchone()["cad_if_id"])
            _log(cur, cad_if_id, "수신", "성공")
            _log(cur, cad_if_id, "검증", "성공" if f.size_bytes > 0 else "제외",
                 None if f.size_bytes > 0 else inv.EXCLUDE_ZERO)
            if not c.keep:
                _log(cur, cad_if_id, "중복제거", "제외", c.reason)
                cur.execute("update IF_CAD_FILES set IF_STATUS = %s where CAD_IF_ID = %s",
                            ("제외", cad_if_id))
                res.excluded += 1
                res.by_reason[c.reason] = res.by_reason.get(c.reason, 0) + 1
                continue
            _log(cur, cad_if_id, "중복제거", "성공")
            cur.execute(
                "insert into EST_CAD_DRAWINGS "
                "(DRAWING_NO, FILE_TYPE, FILE_PATH, FILE_SIZE, REVISION, FILE_MTIME, "
                " ANALYSIS_STATUS, DUPLICATE_YN, CREATED_BY, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) returning DRAWING_ID",
                (c.drawing_no[:100], f.file_type, f.path, f.size_bytes,
                 c.revision or None, f.mtime, "대기", "N", created_by),
            )
            drawing_id = int(cur.fetchone()["drawing_id"])
            cur.execute("update IF_CAD_FILES set IF_STATUS = %s, DRAWING_ID = %s where CAD_IF_ID = %s",
                        ("등록", drawing_id, cad_if_id))
            _log(cur, cad_if_id, "등록", "성공")
            res.registered += 1
            res.drawings += 1

    # 실행 1회 = `DAT_JOB_LOGS` 1행. 제외 건수는 **실패가 아니라 정제 결과**지만
    # TD5 에 '제외 건수' 컬럼이 없어 `FAIL_CNT`(= 적재되지 않은 건수)로 남기고 사유를 적는다.
    res.job_log_id = preprocess.log_job(
        preprocess.JOB_CAD, started=started, ended=datetime.now(),
        processed=res.registered, failed=res.excluded,
        result=("성공" if res.registered and not res.excluded
                else "부분성공" if res.registered else "실패"),
        message=(f"스캔 {res.scanned} · 등록 {res.registered} · 제외 {res.excluded} "
                 f"{res.by_reason} · 이미 수집 {res.skipped} (scope={scope}). "
                 "FAIL_CNT 는 정제 제외 건수다 — 오류가 아니다"),
    )
    return res


def analyze(drawing_id: int) -> dict[str, Any]:
    """① Parsing + Vision **병렬** 인식 → `EST_CAD_OBJECTS`.

    두 공급자 중 하나라도 미구성이면 **501** 이다 — 한쪽만으로 정합성 검증(Parsing↔Vision)을
    할 수 없고, 없는 값을 만들어 채우면 D-05 위반이다.
    """
    row = conn.q1("select DRAWING_ID, DRAWING_NO, FILE_PATH from EST_CAD_DRAWINGS where DRAWING_ID = %s",
                  (drawing_id,))
    if row is None:
        raise http.fail("validation", f"도면 {drawing_id} 가 없다")
    avail = provider.availability()
    missing = [a for a in avail if not a.configured]
    if missing:
        raise http.fail("cad_unconfigured", " / ".join(f"{a.method}: {a.reason}" for a in missing))
    objects: list[provider.DetectedObject] = []
    for det in (provider.parsing_detector(), provider.vision_detector()):
        objects += det.detect(row["file_path"])
    return {"drawing_id": drawing_id, "detected": len(objects)}


def review_object(object_id: int, *, reviewer_id: int, role_code: str, result: str,
                  before: str | None = None, after: str | None = None,
                  comment: str | None = None, retrain: bool = True) -> dict[str, Any]:
    """② HITL 검증 — **여기가 `CONFIRM_YN` 을 바꾸는 유일한 경로다** (G-24).

    승인 권한이 없으면 **403**. 수정 이력은 재학습 데이터로 축적한다(TD3 011 체크).
    """
    if result not in REVIEW_RESULTS:
        raise http.fail("validation", f"검토 결과 어휘 위반: {result!r} (TD5 {REVIEW_RESULTS})")
    if not rbac.can_approve(role_code, AREA):
        raise http.fail("forbidden", f"{AREA} 승인 권한 없음 — AI 결과를 확정할 수 없다 (G-24)")
    obj = conn.q1("select OBJECT_ID, CONFIRM_YN from EST_CAD_OBJECTS where OBJECT_ID = %s", (object_id,))
    if obj is None:
        raise http.fail("validation", f"객체 {object_id} 가 없다")
    with conn.tx() as cur:
        cur.execute(
            "insert into EST_OBJECT_REVIEWS "
            "(OBJECT_ID, REVIEWER_ID, REVIEW_RESULT, BEFORE_VALUE, AFTER_VALUE, REVIEW_COMMENT, "
            " RETRAIN_YN, REVIEWED_DT, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s, now(), now()) returning REVIEW_ID",
            (object_id, reviewer_id, result, before, after, comment, "Y" if retrain else "N"),
        )
        review_id = int(cur.fetchone()["review_id"])
        cur.execute(
            "update EST_CAD_OBJECTS set CONFIRM_YN = %s, UPDATED_DT = now() where OBJECT_ID = %s",
            ("Y" if result == "승인" else "N", object_id),
        )
    return {"review_id": review_id, "object_id": object_id, "confirm_yn": "Y" if result == "승인" else "N"}


def build_features(drawing_id: int) -> dict[str, Any]:
    """③ **확정된 객체만** 집계해 `EST_CAD_FEATURES` 를 만든다.

    TD5 어휘 6종 중 실제로 집계 가능한 것은 `홀 수량` 뿐이다. 나머지는 원천 컬럼이 없어
    **차단**으로 돌려준다 — 0 으로 채우거나 추정값을 넣지 않는다(D-05).
    """
    confirmed = conn.q(
        "select OBJECT_TYPE, count(*) as n from EST_CAD_OBJECTS "
        "where DRAWING_ID = %s and CONFIRM_YN = 'Y' group by OBJECT_TYPE",
        (drawing_id,),
    )
    counts = {r["object_type"]: int(r["n"]) for r in confirmed}
    created = 0
    for ftype, (otype, uom, why) in DERIVABLE.items():
        if otype not in counts:
            continue
        exists = conn.q1(
            "select FEATURE_ID from EST_CAD_FEATURES where DRAWING_ID = %s and FEATURE_TYPE = %s",
            (drawing_id, ftype),
        )
        if exists:
            conn.x(
                "update EST_CAD_FEATURES set FEATURE_VALUE = %s, SOURCE_DESC = %s, UPDATED_DT = now() "
                "where FEATURE_ID = %s",
                (counts[otype], why, exists["feature_id"]),
            )
            continue
        conn.x(
            "insert into EST_CAD_FEATURES "
            "(DRAWING_ID, FEATURE_TYPE, FEATURE_VALUE, UOM, SOURCE_DESC, "
            " USED_IN_QUOTE_YN, TRAIN_USE_YN, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,'N','N', now())",
            (drawing_id, ftype, counts[otype], uom, why),
        )
        created += 1
    return {
        "drawing_id": drawing_id,
        "confirmed_objects": sum(counts.values()),
        "created": created,
        "blocked": dict(BLOCKED_FEATURES),
    }


def stage_status() -> list[dict[str, Any]]:
    """화면 010 상단 — 5단계가 각각 어디까지 왔는지 **실측**으로만 적는다."""
    def one(sql: str, params: Iterable[Any] = ()) -> int:
        row = conn.q1(sql, tuple(params))
        return int(row["n"]) if row else 0

    avail = provider.availability()
    return [
        {"no": 1, "name": "수집·인식", "table": "IF_CAD_FILES → EST_CAD_OBJECTS",
         "count": one("select count(*) as n from EST_CAD_OBJECTS"),
         "blocked": not all(a.configured for a in avail),
         "note": " / ".join(f"{a.method} — {a.reason}" for a in avail if not a.configured)},
        {"no": 2, "name": "HITL 검증", "table": "EST_OBJECT_REVIEWS",
         "count": one("select count(*) as n from EST_OBJECT_REVIEWS"),
         "blocked": False, "note": "승인 전에는 확정이 아니다 (G-24)"},
        {"no": 3, "name": "Feature·BOM", "table": "EST_CAD_FEATURES / EST_BOM_HEADERS",
         "count": one("select count(*) as n from EST_CAD_FEATURES"),
         "blocked": True,
         "note": "집계 가능 Feature 는 '홀 수량' 1종뿐 — 나머지는 원천 컬럼 부재 (D-05)"},
        {"no": 4, "name": "견적", "table": "EST_QUOTATIONS / EST_COST_RATES",
         "count": one("select count(*) as n from EST_QUOTATIONS"),
         "blocked": True,
         "note": "과거 견적금액·실제 제조원가 Label 확보 미확인 — 단가 기준 없음 (D-04)"},
        {"no": 5, "name": "SHAP", "table": "EST_SHAP_FACTORS",
         "count": one("select count(*) as n from EST_SHAP_FACTORS"),
         "blocked": True,
         "note": "예측(EST_ML_PREDICTIONS)이 0건이면 SHAP 도 0건이다 — 학습 회전 대기 (D-04)"},
    ]


def config_badges() -> list[dict[str, str]]:
    s = settings()
    return [
        {"label": a.method, "state": "구성됨" if a.configured else "미구성",
         "note": a.reason, "key": a.setting_key} for a in provider.availability()
    ] + [{"label": "IoU 임계", "state": str(s.cad_iou_threshold),
          "note": "사업계획서 2.6-1 '예: 0.5 이상' — 확정값", "key": "KYUNGDONG_CAD_IOU_THRESHOLD"}]
