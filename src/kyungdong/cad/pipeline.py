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
from ..app.util import assumed, clock, http
from ..ingest import preprocess
from . import archive
from . import dwgconv
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

# ── 파일 형식별 산출 가능 여부 (D-110-b · **D-123 으로 DWG 판정이 또 바뀐다**) ──────
# **D-05 를 "5종 전부 차단" 이라 적은 것은 두 번 틀렸다.**
#   ① `.dxf` 는 순수 텍스트라 group code 파싱만으로 형상이 나온다 (D-110-b).
#   ② `.dwg` 도 `dwg2dxf`(GNU libredwg 0.14)로 변환하면 그 파서가 **그대로** 돈다 (D-123).
# 그래서 DWG 는 더 이상 **구조적 불가가 아니다** — **"변환되면 산출, 변환 실패분은 차단"** 이다.
# 변환율이 100% 가 아니므로 **차단이 사라진 것도 아니다.** 모집단이 줄었을 뿐이다.
#
# **전량 실측** (`tools/dwg_convert.py` → `docs/cad/dwg_features.json`)
#   파일 3,288건 → 내용 해시로 **서로 다른 도면 1,136건** (복사본 2,152 — 파일 수는 표본 수가 아니다)
#   · `.dwg` 802건 → 변환 성공 **772건(96.3%)** · 실패 30건은 전부 `AC1009`(R11/R12)
#   · `.cad` 325건 → 변환 성공 **0건(0%)**. 앞 6바이트가 `V10.00`/`V15.00` 로 **DWG 서명(AC1xxx)이
#     아니다** — AutoCAD DWG 가 아닌 독자 포맷이라 libredwg 가 읽을 대상 자체가 아니다.
#     어느 CAD 의 포맷인지는 확인되지 않았다(도입기업 확인 필요) — 여기서 단정하지 않는다.
#   · 변환 성공분 + 원본 DXF 9건 → 파싱 **781/781(100%)**
# 이 숫자로 **G-14(CAD 객체 인식 80%)를 주장하지 않는다.** 우리가 뽑은 것은 **기하 집계**이고
# G-14 는 **정답 라벨 대비 탐지 정확도**다. 라벨은 여전히 0건이다(`work/cad_labelset.json`).
DXF_SUPPORTED = "DXF 실측 가능 — group code 파싱 (D-110-b)"
CONV_SUPPORTED = ("dwg2dxf 변환 후 DXF 실측 가능 (D-123 — 변환 성공 772/802 = 96.3%). "
                  "**변환 실패분은 차단이다**")
_GEOM_NOTE = {
    "홀 수량": " · CIRCLE 전량(지름 필터 기준 없음)",
    "총 절단장": " · LINE+ARC+POLYLINE 길이합. BLOCK 미전개로 과소 계상",
    "판재 면적": " · 닫힌 POLYLINE shoelace",
    "두께": " · TEXT 표제란 정규식",
}
_MATERIAL_NOTE = ("값은 읽히나 `EST_CAD_FEATURES.FEATURE_VALUE` 가 NUMERIC 이라 문자 재질을 "
                  "적재할 자리가 없다 — 관측값은 `SOURCE_DESC` 에 증거로만 남긴다 "
                  "(D-110-b · D-122)")
_WELD_NOTE = "용접선 레이어·객체 표준이 도면에 없다 — DXF 로도 못 가른다 (D-05)"

FORMAT_FEATURE_SUPPORT: dict[str, dict[str, str]] = {
    "DXF": {**{k: DXF_SUPPORTED + v for k, v in _GEOM_NOTE.items()},
            "재질": _MATERIAL_NOTE, "용접장": _WELD_NOTE},
    # **변환기가 실제로 있을 때만** 산출 가능이다 — `support_for()` 가 `dwgconv.available()` 로
    # 재서 없으면 빈 표(= D-05 그대로 전량 차단)를 돌려준다. 있는 척하지 않는다.
    "DWG": {**{k: CONV_SUPPORTED + v for k, v in _GEOM_NOTE.items()},
            "재질": _MATERIAL_NOTE, "용접장": _WELD_NOTE},
    # `.cad` 는 변환기가 있어도 **0%** 다 — DWG 서명이 아니어서 libredwg 의 대상이 아니다.
    "CAD": {},
}

BLOCKED_FEATURES: dict[str, str] = {
    # **차단의 뜻이 바뀌었다** (D-123). 이전에는 "DWG·CAD 는 구조적으로 못 읽는다" 였고,
    # 지금은 **"변환 후 산출 가능 · 변환 실패분만 차단"** 이다. 남은 차단 모집단은
    # `.cad` 325건(전량 · DWG 서명 아님) + `.dwg` 30건(AC1009 R11/R12) = **서로 다른 도면 355건**.
    # 키 집합·사유 문자열의 결정번호(D-NN)는 `tools/check_ingest.py` ⑤ 와 QA 시험이 읽는다 —
    # **D-05 를 지우지 않는다**: 그 결정이 무효가 된 것이 아니라 모집단이 줄었다는 기록이다.
    "총 절단장": "**변환 후 산출 가능** — dwg2dxf 로 바꾸면 LINE·ARC·POLYLINE 길이합이 나온다 "
                 "(D-123: 서로 다른 도면 1,136 중 777건 실측). 차단은 **변환 실패분 355건** — "
                 "`.cad` 325(DWG 서명 아님) + `.dwg` 30(AC1009 R11/R12). "
                 "변환기가 없는 장비에서는 D-05 그대로 전량 차단이다",
    "판재 면적": "**변환 후 산출 가능** — 닫힌 POLYLINE shoelace (D-123: 564건 실측). 차단은 "
                 "변환 실패분 355건 + 외곽이 닫힌 POLYLINE 으로 안 그려진 217건(781-564)이다. "
                 "변환기가 없는 장비에서는 D-05 그대로 전량 차단이다",
    "용접장": "용접선 객체 유형이 TD5 어휘에 없고 도면에 용접 레이어 표준도 없다 — "
              "**변환해도 못 가른다.** DXF 781건에서 용접장 산출 **0건** (D-05 · D-123)",
    "재질": "**변환 후 값은 읽힌다** — TEXT 표제란에서 586건 실측(STS304 200 · STS316L 199 …, "
            "D-123). 그래도 차단이다: `FEATURE_VALUE` 가 NUMERIC(16,4) 이라 문자 재질을 담을 칸이 "
            "없어 `SOURCE_DESC` 에 증거로만 남긴다 (D-122). 컬럼은 추가하지 않는다(G-02 762 고정). "
            "변환기가 없는 장비에서는 D-05 그대로 읽지도 못한다",
    "두께": "**변환 후 산출 가능** — TEXT 표제란 정규식 (D-123: 591건 실측, 최빈 3.0mm 92건). "
            "차단은 변환 실패분 355건 + 표제란 표기가 정규식에 없는 190건(781-591)이다. "
            "변환기가 없는 장비에서는 D-05 그대로 전량 차단이다",
}


def support_for(file_type: str | None) -> dict[str, str]:
    """파일 형식별 Feature 산출 가능 표. 모르는 형식은 **전부 차단**으로 본다.

    `DWG` 는 **변환기가 실제로 있을 때만** 산출 가능이다(D-123). `dwg2dxf` 가 없는 장비에서는
    D-05 그대로 전량 차단이고, 그것을 `shutil.which` 로 재서 판정한다 — 있는 척하지 않는다.
    """
    ft = (file_type or "").upper()
    if ft == "DWG" and not dwgconv.available():
        return {}
    return FORMAT_FEATURE_SUPPORT.get(ft, {})


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
    """① Parsing (+ Vision) 인식 → `EST_CAD_OBJECTS` (CONFIRM_YN='N').

    **Parsing 이 미구성이면 501** 이다 — 없는 값을 만들어 채우면 D-05 위반이다.
    **Parsing 만 구성됐으면 Parsing 만 돈다 (D-235).** Vision 이 없으니 Parsing↔Vision 정합성
    검증은 할 수 없고 `CROSS_CHECK_RESULT` 는 NULL 로 남는다 — 결과 dict 의 `vision` 에 그 사유를
    그대로 싣고 화면 011 은 그 칸을 `미수집 (D-05)` 로 보인다. 한쪽만으로 '일치' 를 적지 않는다.

    · 확정(CONFIRM_YN='Y') 객체가 있는 도면은 **재분석하지 않는다(422)** — 사람 승인을 지우게 된다(G-24).
    · 미확정 객체는 같은 방식(DETECT_METHOD) 것만 지우고 다시 넣는다(재분석 = 교체).
    · `ANALYSIS_STATUS` 는 대기 → 분석중 → 완료, 실패하면 오류 (TD5 어휘).
    · 변환·파싱·파일 부재는 **422** 다 — 501(미구성)과 구분한다.
    """
    row = conn.q1("select DRAWING_ID, DRAWING_NO, FILE_TYPE, FILE_PATH, ANALYSIS_STATUS "
                  "from EST_CAD_DRAWINGS where DRAWING_ID = %s", (drawing_id,))
    if row is None:
        raise http.fail("validation", f"도면 {drawing_id} 가 없다")
    parsing, vision = provider.parsing_detector(), provider.vision_detector()
    pa, va = parsing.available(), vision.available()
    if not pa.configured:
        missing = [a for a in (pa, va) if not a.configured]
        raise http.fail("cad_unconfigured", " / ".join(f"{a.method}: {a.reason}" for a in missing))
    confirmed = int(conn.q1("select count(*) as n from EST_CAD_OBJECTS "
                            "where DRAWING_ID = %s and CONFIRM_YN = 'Y'", (drawing_id,))["n"])
    if confirmed:
        raise http.fail("validation",
                        f"도면 {row['drawing_no']} 에 확정 객체 {confirmed}건이 있다 — 재분석은 사람 승인을 "
                        "지우므로 하지 않는다 (G-24). 확정을 반려한 뒤 다시 돌린다")
    detectors = [parsing] + ([vision] if va.configured else [])
    methods = [d.method for d in detectors]
    conn.x("update EST_CAD_DRAWINGS set ANALYSIS_STATUS = '분석중', UPDATED_DT = now() "
           "where DRAWING_ID = %s", (drawing_id,))
    objects: list[provider.DetectedObject] = []
    try:
        for det in detectors:
            objects += det.detect(row["file_path"])
    except http.HTTPException:
        conn.x("update EST_CAD_DRAWINGS set ANALYSIS_STATUS = '오류', UPDATED_DT = now() "
               "where DRAWING_ID = %s", (drawing_id,))
        raise
    by_type: dict[str, int] = {}
    for o in objects:
        if o.object_type not in provider.OBJECT_TYPES:       # 어휘 밖 객체는 만들지 않는다
            raise http.fail("internal", f"객체 유형 어휘 위반: {o.object_type!r} (TD5 {provider.OBJECT_TYPES})")
        by_type[o.object_type] = by_type.get(o.object_type, 0) + 1
    with conn.tx() as cur:
        cur.execute("delete from EST_CAD_OBJECTS where DRAWING_ID = %s and CONFIRM_YN = 'N' "
                    "and DETECT_METHOD = any(%s)", (drawing_id, methods))
        replaced = cur.rowcount
        method = parsing.method
        cur.executemany(
            "insert into EST_CAD_OBJECTS (DRAWING_ID, DETECT_METHOD, OBJECT_TYPE, POS_X, POS_Y, "
            " DIMENSION_VALUE, CONFIDENCE_SCORE, CROSS_CHECK_RESULT, CONFIRM_YN, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s,NULL,'N', now())",
            [(drawing_id, method, o.object_type, o.pos_x, o.pos_y, o.dimension_value, o.confidence)
             for o in objects],
        )
        cur.execute("update EST_CAD_DRAWINGS set ANALYSIS_STATUS = '완료', UPDATED_DT = now() "
                    "where DRAWING_ID = %s", (drawing_id,))
    return {
        "drawing_id": drawing_id, "drawing_no": row["drawing_no"], "detected": len(objects),
        "by_type": by_type, "methods": methods, "replaced": replaced,
        "cross_check": None if not va.configured else "가능",
        "vision": None if va.configured else va.reason,
        "confidence": "없음 — 결정적 파싱은 IoU 신뢰도가 없다 (D-235)",
        "note": ("승인 전에는 확정이 아니다 (G-24) — 011 에서 사람이 검토한다. "
                 "홀은 CIRCLE 전량이라 지름 필터 없이 들어 있다 (D-110-b)"),
    }


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
    """도면 하나를 **실측**한다. DB 에 쓰지 않는다 — 재는 것과 확정은 다른 일이다.

    `.dxf` 는 그대로 읽고, **`.dwg` 는 `dwg2dxf` 로 변환해서 읽는다**(D-123). 변환된 DXF 는
    읽자마자 지운다 — 전량을 남기면 팽창률 약 3배로 8.5GB 다.

    **변환이 되는 것과 전량이 되는 것은 다르다.** 변환 실패는 실패로 돌려준다(`measured=False`
    + `convert_error`). `.cad` 는 DWG 서명(AC1xxx)이 아니어서 실측 **0%** 다 — 차단 그대로다.
    """
    row = conn.q1("select DRAWING_ID, DRAWING_NO, FILE_TYPE, FILE_PATH "
                  "from EST_CAD_DRAWINGS where DRAWING_ID = %s", (drawing_id,))
    if row is None:
        raise http.fail("validation", f"도면 {drawing_id} 가 없다")
    ftype = (row["file_type"] or "").upper()
    base = {"drawing_id": drawing_id, "file_type": ftype, "blocked": blocked_for(ftype)}
    if ftype not in ("DXF", "DWG"):
        return {**base, "measured": False,
                "note": f"{ftype} 는 DWG 서명(AC1xxx)이 아니라 dwg2dxf 의 대상이 아니다 — "
                        f"실측 0% (D-05 · D-123). `.cad` 325건은 앞 6바이트가 `V10.00`/`V15.00` 다"}
    # 통계 xlsx 의 `파일경로` 는 **아카이브 루트 기준 상대경로**다(D-03). 원본이 있는 장비에서만
    # 절대경로로 풀린다 — 없으면 "없다" 고 적는다. 조용히 0 을 돌려주지 않는다.
    path = Path(row["file_path"])
    if not path.is_file():
        path = archive.archive_root() / row["file_path"]
    if not path.is_file():
        return {**base, "measured": False,
                "note": f"원본 파일이 없다: {row['file_path']} "
                        f"(아카이브 루트 {archive.archive_root()} 기준으로도 못 찾았다 — D-109)"}
    if ftype == "DXF":
        m, conv = dxf.parse(path), None
    else:
        if not dwgconv.available():
            return {**base, "measured": False, "note": dwgconv.NOT_INSTALLED}
        m, conv = dwgconv.measured(path)
        if m is None:
            return {**base, "measured": False, "convert_error": conv.reason,
                    "dwg_signature": conv.sig,
                    "note": f"dwg2dxf 변환 실패 — 실패는 실패로 센다 (D-123): {conv.reason}"}
    out = {**base, "measured": m.error is None, "error": m.error, "entities": m.entities,
           "features": m.features(), "uom": m.uom, "inserts": m.inserts}
    if conv is not None:
        out["converted"] = True
        out["dwg_signature"] = conv.sig
        out["convert_warn"] = conv.reason if conv.rc_nonzero else None
    return out


def store_dxf_features(drawing_id: int, *, allow_unconfirmed: bool = False) -> dict[str, Any]:
    """DXF 실측 Feature 를 `EST_CAD_FEATURES` 에 적재한다. **`SOURCE_DESC` 에 'DXF 실측' 을 남긴다.**

    기본값은 **적재하지 않는다**. 이유를 그대로 적는다 —
    QA2 `tools/check_ingest.py` ⑤ 는 "확정(CONFIRM_YN='Y') 객체 0건인데 `EST_CAD_FEATURES` 가
    N행이면 원천 없이 만들어진 합성 Feature 다" 로 판정한다. DXF 실측은 합성이 아니지만
    **그 검사기는 객체 집계만을 Feature 의 원천으로 본다.** 검사기를 고치는 것은 QA 몫이라
    제품 쪽에서는 `allow_unconfirmed=True` 를 **명시로 요구**하고, 그러지 않으면 안 쓴다.
    이것은 값을 숨기는 것이 아니라 **판정 규칙이 아직 한 가지 원천만 안다**는 사실의 기록이다.

    `재질` 은 `FEATURE_VALUE NUMERIC(16,4)` 에 담을 자리가 없다(D-122). **행 자체는 남기되**
    `FEATURE_VALUE` 는 NULL 이고 관측값은 `SOURCE_DESC` 에 증거로 적는다 — 숫자 칸에 코드를
    만들어 넣지 않고, 컬럼도 추가하지 않는다(G-02 762 고정).

    `SOURCE_DESC` 접두는 **합성과 구분하려고** 형식별로 다르다 —
    `DXF 실측(dwg2dxf 변환) — <원본파일명>` / `DXF 실측 — <원본파일명>`.

    `$INSUNITS` 가 없는 도면은 **단위 가정 (D-150)** 표지가 접두에 하나 더 붙고 `UOM` 이
    `도면단위` → `mm` 로 바뀐다. 가정 선언(`SYS_CONFIGS('시스템설정','ASSUMED_ANSWERS')`)이
    없으면 표지도 단위 변환도 **일어나지 않는다** — 표지 없이 단위만 바뀌면 그게 거짓 실측이다.
    """
    got = dxf_measure(drawing_id)
    if not got.get("measured"):
        return {**got, "created": 0, "updated": 0, "text_rows": 0, "written": False}
    confirmed = conn.q1("select count(*) as n from EST_CAD_OBJECTS "
                        "where DRAWING_ID = %s and CONFIRM_YN = 'Y'", (drawing_id,))["n"]
    if not int(confirmed) and not allow_unconfirmed:
        return {**got, "created": 0, "updated": 0, "text_rows": 0, "written": False,
                "note": "확정 객체 0건 — `allow_unconfirmed=True` 없이는 적재하지 않는다 "
                        "(check_ingest ⑤ 가 합성으로 판정한다). 실측값은 위 features 에 있다"}
    name = Path(conn.q1("select FILE_PATH from EST_CAD_DRAWINGS where DRAWING_ID = %s",
                        (drawing_id,))["file_path"]).name
    tag = f"{dxf.SOURCE_TAG}(dwg2dxf 변환)" if got.get("converted") else dxf.SOURCE_TAG
    # ── 단위 가정 (D-150) ─────────────────────────────────────────────
    # `$INSUNITS` 가 없는 도면은 길이가 **도면 단위**다. 가정 답변 ③ 은 그것을 mm 로 보라고
    # 했다 — 그러면 **그 도면의 Feature 전부**에 표지를 남긴다. 표지 없이 단위만 바꾸면
    # 도면단위가 실측 mm 로 조용히 승격된다. `mm`·`inch` 가 이미 명시된 도면은 **건드리지 않는다**.
    unit_assumed = str(got.get("uom") or "") == dxf.UNKNOWN_UOM
    tgt = assumed.unit_target()
    utag = assumed.unit_tag() if unit_assumed else ""
    head = " · ".join([tag] + ([utag] if utag else []))
    unit_marked = 0
    created = updated = text_rows = 0
    for f in got["features"]:
        uom = (f["uom"] or "")
        if utag and tgt and uom.startswith(dxf.UNKNOWN_UOM):
            uom = tgt + uom[len(dxf.UNKNOWN_UOM):]     # 도면단위² → mm²
        body = name
        if f["value"] is None:                  # `재질` — 숫자 칸이 없다(D-122)
            body = (f"{body} · 관측 재질={f['text']} · FEATURE_VALUE 는 NUMERIC(16,4) 이라 "
                    "NULL 로 둔다 (D-122 · 컬럼 추가 안 함 G-02)")
            text_rows += 1
        # 표지(`head`)는 절대 자르지 않는다 — 자르면 고지가 사라진다. 본문만 자른다.
        room = 300 - len(head) - 3
        desc = f"{head} — {body if len(body) <= room else body[:max(room, 0)]}"
        if utag:
            unit_marked += 1
        hit = conn.q1("select FEATURE_ID from EST_CAD_FEATURES "
                      "where DRAWING_ID = %s and FEATURE_TYPE = %s", (drawing_id, f["type"]))
        if hit:
            conn.x("update EST_CAD_FEATURES set FEATURE_VALUE = %s, UOM = %s, "
                   "SOURCE_DESC = %s, UPDATED_DT = now() where FEATURE_ID = %s",
                   (f["value"], uom[:20] or None, desc[:300], hit["feature_id"]))
            updated += 1
            continue
        conn.x("insert into EST_CAD_FEATURES "
               "(DRAWING_ID, FEATURE_TYPE, FEATURE_VALUE, UOM, SOURCE_DESC, "
               " USED_IN_QUOTE_YN, TRAIN_USE_YN, CREATED_DT) values (%s,%s,%s,%s,%s,'N','N', now())",
               (drawing_id, f["type"], f["value"], uom[:20] or None, desc[:300]))
        created += 1
    return {**got, "created": created, "updated": updated, "text_rows": text_rows,
            "unit_assumed": unit_assumed, "unit_marked": unit_marked, "written": True}


def stage_status() -> list[dict[str, Any]]:
    """화면 010 상단 — 5단계가 각각 어디까지 왔는지 **실측**으로만 적는다."""
    def one(sql: str, params: Iterable[Any] = ()) -> int:
        row = conn.q1(sql, tuple(params))
        return int(row["n"]) if row else 0

    avail = provider.availability()
    pa, va = avail[0], avail[1]
    if pa.configured:
        note1 = (f"{pa.method} 구성됨 (D-235) — 홀·치수문자 2종, 신뢰도 없음. "
                 f"{va.method} — {va.reason} → 정합성 검증(CROSS_CHECK_RESULT) 은 NULL"
                 if not va.configured else "Parsing·Vision 구성됨")
    else:
        note1 = " / ".join(f"{a.method} — {a.reason}" for a in avail if not a.configured)
    return [
        {"no": 1, "name": "수집·인식", "table": "IF_CAD_FILES → EST_CAD_OBJECTS",
         "count": one("select count(*) as n from EST_CAD_OBJECTS"),
         # Parsing 만 구성돼도 인식은 **돈다** — 차단이 아니다. Vision 부재는 비고에 적는다 (D-235).
         "blocked": not pa.configured,
         "note": note1},
        {"no": 2, "name": "HITL 검증", "table": "EST_OBJECT_REVIEWS",
         "count": one("select count(*) as n from EST_OBJECT_REVIEWS"),
         "blocked": False, "note": "승인 전에는 확정이 아니다 (G-24)"},
        {"no": 3, "name": "Feature·BOM", "table": "EST_CAD_FEATURES / EST_BOM_HEADERS",
         "count": one("select count(*) as n from EST_CAD_FEATURES"),
         "blocked": True,
         "note": "확정 객체 집계로 만드는 Feature 는 '홀 수량' 1종뿐 (D-05). "
                 "**DWG 는 dwg2dxf 변환으로 풀렸다** — 서로 다른 도면 1,136건 중 781건 파싱 성공, "
                 "절단장 777 · 홀 708 · 두께 591 · 재질 586 · 판재면적 564 실측 (D-123). "
                 "남은 차단은 `.cad` 325건(DWG 서명 아님) + `.dwg` 30건(R11/R12) + 용접장 0건, "
                 "그리고 재질은 `FEATURE_VALUE` 가 NUMERIC 이라 적재 자리가 없다 (D-122)"},
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
