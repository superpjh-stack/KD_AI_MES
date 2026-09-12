"""CAD 5단계 파이프라인 — 수집 → 인식 → **HITL** → Feature → (BOM·견적·SHAP).

**승인 전에는 확정이 아니다** (TD3 standard_note 4 · G-24).
  · `EST_CAD_OBJECTS.CONFIRM_YN` 을 'Y' 로 바꾸는 경로는 `review_object()` **하나뿐**이고,
    거기서 `rbac.can_approve` 를 통과하지 못하면 403 이다.
  · Feature 는 **확정된 객체만** 집계한다. 확정이 0건이면 Feature 도 0건이다 — 채워 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import conn

from ..app import rbac
from ..app.settings import settings
from ..app.util import clock, http
from ..ingest import preprocess
from . import archive
from . import dxf
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

# ── 파일 형식별 산출 가능 여부 (D-110-b — D-05 판정 정정) ──────────────────────
# **D-05 를 5종 전부 차단이라고 적은 것은 `.dwg` 에는 맞고 `.dxf` 에는 틀렸다.**
# `.dxf` 는 순수 텍스트라 group code 파싱만으로 형상이 나온다(`cad/dxf.py`). 그래서
# 차단은 **Feature 별**이 아니라 **파일 형식 × Feature** 로 갈린다.
#
# **표본을 숨기지 않는다.** 원본 아카이브 CAD 3,299건 중 dxf 는 **29건(0.9%)** 이고,
# 내용 해시로 복사본을 걷어내면 **서로 다른 도면 9건**이다. 이 숫자로 G-14(80%)를 주장하지 않는다.
DXF_SUPPORTED = "DXF 실측 가능 — group code 파싱 (D-110-b)"
FORMAT_FEATURE_SUPPORT: dict[str, dict[str, str]] = {
    "DXF": {
        "홀 수량": DXF_SUPPORTED + " · CIRCLE 전량(지름 필터 기준 없음)",
        "총 절단장": DXF_SUPPORTED + " · LINE+ARC+POLYLINE 길이합. BLOCK 미전개로 과소 계상",
        "판재 면적": DXF_SUPPORTED + " · 닫힌 POLYLINE shoelace",
        "두께": DXF_SUPPORTED + " · TEXT 표제란 정규식",
        "재질": "DXF 에서 값은 읽히나 `EST_CAD_FEATURES.FEATURE_VALUE` 가 NUMERIC 이라 "
                "문자 재질을 적재할 자리가 없다 (D-110-b)",
        "용접장": "용접선 레이어·객체 표준이 도면에 없다 — DXF 로도 못 가른다 (D-05)",
    },
    "DWG": {},      # 전 항목 차단 — 아래 BLOCKED_FEATURES 와 같다
    "CAD": {},
}

BLOCKED_FEATURES: dict[str, str] = {
    # `.dwg`(2,240) · `.cad`(1,030) 기준의 차단 사유다. `.dxf`(29) 는 위 표를 본다.
    # 키 집합·사유 문자열의 결정번호(D-NN)는 `tools/check_ingest.py` ⑤ 가 읽는다 — 빼지 않는다.
    "총 절단장": "DWG·CAD 는 바이너리라 변환기 없이 못 읽는다 — Parsing 미구성 (D-05). "
                 "DXF 29건은 LINE·ARC·POLYLINE 길이합으로 산출 가능 (D-110-b)",
    "판재 면적": "DWG·CAD 외곽 형상 좌표를 못 읽는다 — Parsing 미구성 (D-05). "
                 "DXF 29건은 닫힌 POLYLINE shoelace 로 산출 가능 (D-110-b)",
    "용접장": "용접선 객체 유형이 TD5 어휘에 없고 도면에 용접 레이어 표준도 없다 — "
              "DXF 를 읽어도 못 가른다 (D-05)",
    "재질": "DWG·CAD 는 표제란 OCR 미구성 (D-05). DXF 는 TEXT 로 읽히지만 "
            "`FEATURE_VALUE` 가 NUMERIC 이라 적재할 자리가 없다 (D-110-b)",
    "두께": "DWG·CAD 는 표제란 OCR 미구성 (D-05). DXF 29건은 TEXT 표제란에서 산출 가능 (D-110-b)",
}


def support_for(file_type: str | None) -> dict[str, str]:
    """파일 형식별 Feature 산출 가능 표. 모르는 형식은 **전부 차단**으로 본다."""
    return FORMAT_FEATURE_SUPPORT.get((file_type or "").upper(), {})


def blocked_for(file_type: str | None) -> dict[str, str]:
    """그 형식에서 **아직 못 만드는** Feature 와 사유. 화면·리포트가 그대로 쓴다."""
    ok = support_for(file_type)
    out = {k: v for k, v in BLOCKED_FEATURES.items() if k not in ok}
    out.update({k: v for k, v in ok.items() if "없다" in v})
    return out


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
    started = clock.real_now()
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
        preprocess.JOB_CAD, started=started, ended=clock.real_now(),
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


def dxf_measure(drawing_id: int) -> dict[str, Any]:
    """`.dxf` 도면 하나를 **실측**한다. DB 에 쓰지 않는다 — 재는 것과 확정은 다른 일이다.

    `.dwg` · `.cad` 는 여전히 **차단**이다(변환기 없음 — D-05). 형식이 맞지 않으면 그렇게 적는다.
    """
    row = conn.q1("select DRAWING_ID, DRAWING_NO, FILE_TYPE, FILE_PATH "
                  "from EST_CAD_DRAWINGS where DRAWING_ID = %s", (drawing_id,))
    if row is None:
        raise http.fail("validation", f"도면 {drawing_id} 가 없다")
    ftype = (row["file_type"] or "").upper()
    if ftype != "DXF":
        return {"drawing_id": drawing_id, "file_type": ftype, "measured": False,
                "blocked": blocked_for(ftype),
                "note": f"{ftype} 는 바이너리라 변환기 없이 못 읽는다 — Parsing 미구성 (D-05)"}
    # 통계 xlsx 의 `파일경로` 는 **아카이브 루트 기준 상대경로**다(D-03). 원본이 있는 장비에서만
    # 절대경로로 풀린다 — 없으면 "없다" 고 적는다. 조용히 0 을 돌려주지 않는다.
    path = Path(row["file_path"])
    if not path.is_file():
        path = archive.archive_root() / row["file_path"]
    if not path.is_file():
        return {"drawing_id": drawing_id, "file_type": ftype, "measured": False,
                "blocked": blocked_for(ftype),
                "note": f"원본 파일이 없다: {row['file_path']} "
                        f"(아카이브 루트 {archive.archive_root()} 기준으로도 못 찾았다 — D-109)"}
    m = dxf.parse(path)
    return {"drawing_id": drawing_id, "file_type": ftype, "measured": m.error is None,
            "error": m.error, "entities": m.entities, "features": m.features(),
            "blocked": blocked_for(ftype), "uom": m.uom, "inserts": m.inserts}


def store_dxf_features(drawing_id: int, *, allow_unconfirmed: bool = False) -> dict[str, Any]:
    """DXF 실측 Feature 를 `EST_CAD_FEATURES` 에 적재한다. **`SOURCE_DESC` 에 'DXF 실측' 을 남긴다.**

    기본값은 **적재하지 않는다**. 이유를 그대로 적는다 —
    QA2 `tools/check_ingest.py` ⑤ 는 "확정(CONFIRM_YN='Y') 객체 0건인데 `EST_CAD_FEATURES` 가
    N행이면 원천 없이 만들어진 합성 Feature 다" 로 판정한다. DXF 실측은 합성이 아니지만
    **그 검사기는 객체 집계만을 Feature 의 원천으로 본다.** 검사기를 고치는 것은 QA 몫이라
    제품 쪽에서는 `allow_unconfirmed=True` 를 **명시로 요구**하고, 그러지 않으면 안 쓴다.
    이것은 값을 숨기는 것이 아니라 **판정 규칙이 아직 한 가지 원천만 안다**는 사실의 기록이다.

    `재질` 은 `FEATURE_VALUE NUMERIC(16,4)` 에 담을 자리가 없어 **적재하지 않는다**(차단).
    """
    got = dxf_measure(drawing_id)
    if not got.get("measured"):
        return {**got, "created": 0, "updated": 0, "skipped_text": 0, "written": False}
    confirmed = conn.q1("select count(*) as n from EST_CAD_OBJECTS "
                        "where DRAWING_ID = %s and CONFIRM_YN = 'Y'", (drawing_id,))["n"]
    if not int(confirmed) and not allow_unconfirmed:
        return {**got, "created": 0, "updated": 0, "skipped_text": 0, "written": False,
                "note": "확정 객체 0건 — `allow_unconfirmed=True` 없이는 적재하지 않는다 "
                        "(check_ingest ⑤ 가 합성으로 판정한다). 실측값은 위 features 에 있다"}
    created = updated = skipped = 0
    for f in got["features"]:
        if f["value"] is None:                  # `재질` — 숫자 컬럼에 담을 자리가 없다
            skipped += 1
            continue
        hit = conn.q1("select FEATURE_ID from EST_CAD_FEATURES "
                      "where DRAWING_ID = %s and FEATURE_TYPE = %s", (drawing_id, f["type"]))
        if hit:
            conn.x("update EST_CAD_FEATURES set FEATURE_VALUE = %s, UOM = %s, "
                   "SOURCE_DESC = %s, UPDATED_DT = now() where FEATURE_ID = %s",
                   (f["value"], (f["uom"] or "")[:20], str(f["source"])[:300], hit["feature_id"]))
            updated += 1
            continue
        conn.x("insert into EST_CAD_FEATURES "
               "(DRAWING_ID, FEATURE_TYPE, FEATURE_VALUE, UOM, SOURCE_DESC, "
               " USED_IN_QUOTE_YN, TRAIN_USE_YN, CREATED_DT) values (%s,%s,%s,%s,%s,'N','N', now())",
               (drawing_id, f["type"], f["value"], (f["uom"] or "")[:20], str(f["source"])[:300]))
        created += 1
    return {**got, "created": created, "updated": updated, "skipped_text": skipped,
            "written": True}


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
         "note": "확정 객체 집계로 만드는 Feature 는 '홀 수량' 1종뿐 (D-05). "
                 "DXF 는 group code 실측으로 4종이 나오지만 표본이 도면 3,299건 중 "
                 "29건(0.9%)뿐이고 DWG·CAD 는 변환기가 없다 (D-110-b)"},
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
