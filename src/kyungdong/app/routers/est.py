"""수주견적AI관리 010~015 + AI학습 데이터관리 037 (개발3).

`/dat/037` 은 **업무영역은 데이터관리, 구현은 여기**다(D-38). URL·메뉴 위치는 산출물 그대로 둔다.

이 파일이 지키는 것
  · 화면의 모든 칸은 `design.screen(sid)["mockup"]` 에서 온다. `(예시)` 값을 시드·렌더하지 않는다.
  · **CAD 인식은 미구성이면 501**(D-05). 조용한 합성 Feature 0건.
  · **승인 없이 `EST_QUOTATIONS`·`EST_BOM_HEADERS`·`EST_CAD_OBJECTS` 가 바뀌는 경로가 없다**(G-24).
  · 0건은 정상이다 — 그때 그리드는 `미수집` 문구를 렌더한다(G-11).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ...cad import inventory as cad_inventory
from ...cad import pipeline as cad_pipeline
from ...ml import datasets as ml_datasets
from ...ml import registry as ml_registry
from .. import design, nav, rbac
from ..templating import render
from ..util import http
from ..util.audit import audit

import conn  # noqa: E402  (kyungdong.cad 가 db 경로를 붙인 뒤에 들어온다)

router = APIRouter()

SCREENS = (
    "MES-TD3-010", "MES-TD3-011", "MES-TD3-012", "MES-TD3-013",
    "MES-TD3-014", "MES-TD3-015", "MES-TD3-037",
)

EST_AREA = "수주견적AI관리"
DAT_AREA = "데이터관리"
EMPTY = http.not_collected("D-06")


# ── 공통 ──────────────────────────────────────────────────────────────────
def _screen(sid: str) -> nav.Screen:
    s = nav.by_id().get(sid)
    if s is None:                       # 정본이 흔들렸다 — 지어내지 않고 터진다
        raise RuntimeError(f"{sid} 가 nav 에 없다")
    return s


def _guard(request: Request, sid: str) -> tuple[nav.Screen, dict[str, Any], str]:
    screen = _screen(sid)
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, screen.area):
        raise http.fail("forbidden", f"{screen.area} 조회 권한 없음")
    td3 = design.screen(sid)
    if td3 is None:
        raise RuntimeError(f"{sid} 가 TD3 정본에 없다")
    return screen, td3, role


def _filters(request: Request, fields: list[str]) -> dict[str, str]:
    return {f"q{i}": (request.query_params.get(f"q{i}") or "").strip()
            for i in range(len(fields))}


def _page(request: Request) -> tuple[int, int, int]:
    """`?page=&size=` — 기본 size 20 (contracts/api-contract.md §0-7). 그리드 페이징 공통 적용."""
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except ValueError:
        page = 1
    try:
        size = max(1, min(200, int(request.query_params.get("size") or 20)))
    except ValueError:
        size = 20
    return page, size, (page - 1) * size


def _row(cells: list[Any], link: str | None = None, link_index: int = 1) -> dict[str, Any]:
    return {"cells": ["" if c is None else str(c) for c in cells],
            "link": link, "link_index": link_index}


def _cad_badges() -> list[dict[str, str]]:
    from ...cad import provider
    out = [{"text": a.badge, "kind": "bad" if not a.configured else "notice"}
           for a in provider.availability()]
    out.append({"text": "합성 Feature 금지 (D-05)", "kind": "undetermined"})
    return out


def _user_id(request: Request) -> int | None:
    """세션 사용자. 없으면 역할로 찾는다 — **개발용 보조(D-40)**, 인증이 들어오면 사라진다."""
    from ...agent import service as agent_service
    sess = getattr(request.state, "session", None)
    uid = getattr(sess, "user_id", None)
    if uid is not None:
        return int(uid)
    return agent_service.resolve_user(getattr(request.state, "role_code", "") or "")


def _n(sql: str, params: Any = ()) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


# ── 010 CAD 도면분석 ──────────────────────────────────────────────────────
@router.get("/est/010")
async def cad_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-010")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    conds, params = [], []
    for key, sql in (("q0", "d.DRAWING_NO ilike %s"), ("q1", "p.PROJECT_NO ilike %s"),
                     ("q2", "d.FILE_TYPE = %s"), ("q3", "d.ANALYSIS_STATUS = %s"),
                     ("q5", "p.PRODUCT_GROUP = %s")):
        if f.get(key):
            conds.append(sql)
            params.append(f"%{f[key]}%" if "ilike" in sql else f[key])
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    rows = conn.q(
        "select d.DRAWING_ID, d.DRAWING_NO, p.PROJECT_NO, d.FILE_TYPE, d.ANALYSIS_STATUS, "
        "       d.FILE_MTIME, "
        "       (select count(*) from EST_CAD_OBJECTS o where o.DRAWING_ID = d.DRAWING_ID) as objects "
        "from EST_CAD_DRAWINGS d left join EST_PROJECTS p on p.PROJECT_ID = d.PROJECT_ID "
        f"{where}order by d.DRAWING_ID limit %s offset %s", [*params, size, off])
    grid = [
        _row([i, r["drawing_no"], r["project_no"] or http.undetermined("D-03"), r["file_type"],
              r["analysis_status"], r["objects"] or "-",
              r["file_mtime"].date() if r["file_mtime"] else ""],
             link=f"/prc/024?lot={r['project_no']}" if r["project_no"] else None, link_index=2)
        for i, r in enumerate(rows, 1)
    ]
    try:
        files = cad_inventory.read_inventory()
        stats = cad_inventory.stats(files)
        inv_err = ""
    except (FileNotFoundError, ImportError) as e:
        stats, inv_err = None, f"도면 인벤토리를 읽지 못했다: {e}"
    audit(request, screen.id, "조회")
    return render(
        request, "est/010.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY + " — `make cad-ingest` 로 도면을 수집한다",
        badges=_cad_badges(), notices=[],
        actions={"도면 업로드": "POST /api/cad/files (MES-TD4-048)",
                 "분석 실행": "501 CAD Parsing 미구성 (D-05) — Autodesk API·YOLOv8 미확보",
                 "결과보기": "011 객체인식 결과관리로 이동",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①) — 개발1 036 화면"},
        stages=cad_pipeline.stage_status(), config=cad_pipeline.config_badges(),
        inventory=stats, inventory_error=inv_err,
    )


# ── 011 객체인식 결과관리 ─────────────────────────────────────────────────
@router.get("/est/011")
async def object_reviews(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-011")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    conds, params = [], []
    if f.get("q0"):
        conds.append("d.DRAWING_NO ilike %s")
        params.append(f"%{f['q0']}%")
    if f.get("q1"):
        conds.append("o.OBJECT_TYPE = %s")
        params.append(f["q1"])
    if f.get("q2"):
        conds.append("o.DETECT_METHOD = %s")
        params.append(f["q2"])
    if f.get("q4"):
        conds.append("o.CONFIRM_YN = %s")
        params.append(f["q4"])
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    rows = conn.q(
        "select o.OBJECT_ID, d.DRAWING_NO, o.OBJECT_TYPE, o.DETECT_METHOD, o.DIMENSION_VALUE, "
        "       o.CONFIDENCE_SCORE, o.CONFIRM_YN, o.CROSS_CHECK_RESULT "
        "from EST_CAD_OBJECTS o join EST_CAD_DRAWINGS d on d.DRAWING_ID = o.DRAWING_ID "
        f"{where}order by o.OBJECT_ID limit %s offset %s", [*params, size, off])
    grid = [_row([i, r["drawing_no"], r["object_type"], r["detect_method"], r["dimension_value"],
                  r["confidence_score"], r["confirm_yn"]]) for i, r in enumerate(rows, 1)]
    counts = {
        "objects": _n("select count(*) as n from EST_CAD_OBJECTS"),
        "confirmed": _n("select count(*) as n from EST_CAD_OBJECTS where CONFIRM_YN = 'Y'"),
        "reviews": _n("select count(*) as n from EST_OBJECT_REVIEWS"),
        "features": _n("select count(*) as n from EST_CAD_FEATURES"),
    }
    audit(request, screen.id, "조회")
    return render(
        request, "est/011.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY + " — 인식 실행이 501 이라 객체가 0건이다 (D-05)",
        badges=_cad_badges() + [{"text": "HITL — 승인 전 확정 아님 (G-24)", "kind": "notice"}],
        notices=[], actions={"검증": "POST /est/011/review",
                             "수정": "POST /est/011/review (REVIEW_RESULT='수정')",
                             "확정": "POST /est/011/review (REVIEW_RESULT='승인') — 승인 권한 없으면 403",
                             "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
        counts=counts, area=EST_AREA, can_approve=rbac.can_approve(role, EST_AREA),
        derivable={k: v[2] for k, v in cad_pipeline.DERIVABLE.items()},
        blocked=cad_pipeline.BLOCKED_FEATURES,
    )


@router.post("/est/011/review")
async def object_review(request: Request, object_id: int = Form(...), result: str = Form(...),
                        before: str = Form(""), after: str = Form(""), comment: str = Form("")):
    """**`CONFIRM_YN` 을 바꾸는 유일한 HTTP 경로** (G-24). 승인 권한 없으면 403."""
    screen, _td3, role = _guard(request, "MES-TD3-011")
    user_id = _user_id(request)
    if user_id is None:
        raise http.fail("unauthenticated", "검토자 계정을 확인할 수 없다 — EST_OBJECT_REVIEWS.REVIEWER_ID 는 필수다")
    cad_pipeline.review_object(object_id, reviewer_id=int(user_id), role_code=role,
                               result=result, before=before or None, after=after or None,
                               comment=comment or None)
    audit(request, screen.id, f"객체검증:{result}", log_type="변경")
    return RedirectResponse("/est/011", status_code=303)


# ── 012 견적자동산출 ──────────────────────────────────────────────────────
@router.get("/est/012")
async def quotations(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-012")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    conds, params = [], []
    for key, sql in (("q0", "q.QUOTE_NO ilike %s"), ("q1", "p.PROJECT_NO ilike %s"),
                     ("q2", "p.CUSTOMER_CODE = %s"), ("q3", "q.QUOTE_STATUS = %s"),
                     ("q5", "q.CALC_METHOD = %s")):
        if f.get(key):
            conds.append(sql)
            params.append(f"%{f[key]}%" if "ilike" in sql else f[key])
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    rows = conn.q(
        "select q.QUOTE_ID, q.QUOTE_NO, p.PROJECT_NO, q.CALC_METHOD, q.TOTAL_AMOUNT, "
        "       q.CONFIDENCE_SCORE, q.QUOTE_STATUS "
        "from EST_QUOTATIONS q join EST_PROJECTS p on p.PROJECT_ID = q.PROJECT_ID "
        f"{where}order by q.QUOTE_ID limit %s offset %s", [*params, size, off])
    grid = [_row([i, r["quote_no"], r["project_no"], r["calc_method"],
                  f"{int(r['total_amount']):,}" if r["total_amount"] is not None else "",
                  r["confidence_score"], r["quote_status"]],
                 link=f"/prc/024?lot={r['project_no']}", link_index=2)
            for i, r in enumerate(rows, 1)]
    counts = {
        "cost_rates": _n("select count(*) as n from EST_COST_RATES where USE_YN = 'Y'"),
        "features": _n("select count(*) as n from EST_CAD_FEATURES"),
        "models": _n("select count(*) as n from EST_ML_MODELS where DEPLOY_STATUS = '배포'"),
    }
    audit(request, screen.id, "조회")
    return render(
        request, "est/012.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY + " — 단가 기준·Label 미확보 (D-04)",
        badges=[{"text": "Label 미확보 — 정확도 측정 불가 (D-04)", "kind": "bad"},
                {"text": "학습 미실시 — 다음 단독 회전", "kind": "undetermined"}],
        notices=[], counts=counts,
        actions={"견적 산출": "422 — 단가 기준(EST_COST_RATES) 0건 · 견적 Feature 0건 (D-04·D-05)",
                 "저장": "승인 전 견적 확정은 422 (§2.5)",
                 "승인요청": "POST /est/012/confirm — 승인 권한 없으면 403 (G-24)",
                 "리포트": "015 영향요인분석과 함께 본다",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


@router.post("/est/012/confirm")
async def confirm_quote(request: Request, quote_id: int = Form(...)):
    """견적 확정 — **승인 권한이 없으면 403**, 승인 전 확정은 422 (G-24 · §2.5)."""
    screen, _td3, role = _guard(request, "MES-TD3-012")
    if not rbac.can_approve(role, EST_AREA):
        raise http.fail("forbidden", f"{EST_AREA} 승인 권한 없음 — 견적을 확정할 수 없다 (G-24)")
    row = conn.q1("select QUOTE_ID, QUOTE_STATUS from EST_QUOTATIONS where QUOTE_ID = %s", (quote_id,))
    if row is None:
        raise http.fail("validation", f"견적 {quote_id} 가 없다")
    if row["quote_status"] != "검토":
        raise http.fail("validation", f"검토 단계가 아닌 견적은 확정할 수 없다: {row['quote_status']}")
    conn.x("update EST_QUOTATIONS set QUOTE_STATUS = '승인', APPROVER_ID = %s, UPDATED_DT = now() "
           "where QUOTE_ID = %s", (_user_id(request), quote_id))
    audit(request, screen.id, "견적승인", log_type="변경")
    return RedirectResponse("/est/012", status_code=303)


# ── 013 BOM자동생성 ───────────────────────────────────────────────────────
@router.get("/est/013")
async def boms(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-013")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    conds, params = [], []
    for key, sql in (("q0", "b.BOM_NO ilike %s"), ("q1", "p.PROJECT_NO ilike %s"),
                     ("q2", "d.DRAWING_NO ilike %s"), ("q3", "b.GEN_METHOD = %s"),
                     ("q4", "b.CONFIRM_YN = %s")):
        if f.get(key):
            conds.append(sql)
            params.append(f"%{f[key]}%" if "ilike" in sql else f[key])
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    rows = conn.q(
        "select b.BOM_ID, b.BOM_NO, p.PROJECT_NO, b.GEN_METHOD, b.BOM_VERSION, "
        "       b.ACCURACY_RATE, b.CONFIRM_YN "
        "from EST_BOM_HEADERS b join EST_PROJECTS p on p.PROJECT_ID = b.PROJECT_ID "
        "left join EST_CAD_DRAWINGS d on d.DRAWING_ID = b.DRAWING_ID "
        f"{where}order by b.BOM_ID limit %s offset %s", [*params, size, off])
    grid = [_row([i, r["bom_no"], r["project_no"], r["gen_method"], r["bom_version"],
                  r["accuracy_rate"], r["confirm_yn"]],
                 link=f"/prc/024?lot={r['project_no']}", link_index=2)
            for i, r in enumerate(rows, 1)]
    counts = {
        "item_codes": _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = '품목' and USE_YN='Y'"),
        "materials": _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = '재질' and USE_YN='Y'"),
        "confirmed": _n("select count(*) as n from EST_CAD_OBJECTS where CONFIRM_YN = 'Y'"),
        "boms": _n("select count(*) as n from EST_BOM_HEADERS"),
    }
    audit(request, screen.id, "조회")
    return render(
        request, "est/013.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY + " — 품목·재질 코드 그룹이 비어 있다 (D-47)",
        badges=[{"text": "기준 BOM 부재 — 정확도 측정 불가 (D-04)", "kind": "bad"},
                {"text": "대체 표기 (D-41)", "kind": "undetermined"}],
        notices=[], counts=counts,
        actions={"BOM 생성": "422 — 품목·재질 코드 그룹 0건 (D-47) · 확정 객체 0건 (D-05)",
                 "다단계 전개": "EST_BOM_ITEMS.PARENT_ITEM_ID 자기참조. 순환 참조 불허",
                 "저장": "승인 전 BOM 확정은 422 (§2.5)",
                 "삭제": "승인 권한 필요 (G-24)",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


@router.post("/est/013/confirm")
async def confirm_bom(request: Request, bom_id: int = Form(...)):
    """BOM 확정 — **승인 권한이 없으면 403** (G-24)."""
    screen, _td3, role = _guard(request, "MES-TD3-013")
    if not rbac.can_approve(role, EST_AREA):
        raise http.fail("forbidden", f"{EST_AREA} 승인 권한 없음 — BOM 을 확정할 수 없다 (G-24)")
    row = conn.q1("select BOM_ID, CYCLE_CHECK_RESULT from EST_BOM_HEADERS where BOM_ID = %s", (bom_id,))
    if row is None:
        raise http.fail("validation", f"BOM {bom_id} 가 없다")
    if row["cycle_check_result"] not in ("정상", None, ""):
        raise http.fail("validation", f"순환 참조 검증 결과가 정상이 아니다: {row['cycle_check_result']}")
    conn.x("update EST_BOM_HEADERS set CONFIRM_YN = 'Y', UPDATED_DT = now() where BOM_ID = %s", (bom_id,))
    audit(request, screen.id, "BOM확정", log_type="변경")
    return RedirectResponse("/est/013", status_code=303)


# ── 014 ML분석 ────────────────────────────────────────────────────────────
@router.get("/est/014")
async def ml_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-014")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    runs = ml_registry.train_runs()
    grid = [_row([i, f"{r['model_name']}", r["model_version"], r["train_cnt"],
                  r["valid_metric"], r["overfit_result"], r["run_status"]])
            for i, r in enumerate(runs, 1)]
    audit(request, screen.id, "조회")
    return render(
        request, "est/014.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid,
        empty_note=EMPTY + " — 학습을 실행하지 않았다 (다음 단독 회전, goal.md §10-2)",
        badges=[{"text": "학습 미실시 — 다음 단독 회전", "kind": "undetermined"},
                {"text": "성능 수치를 만들지 않는다", "kind": "bad"}],
        notices=[], readiness=ml_registry.readiness(),
        actions={"학습 실행": "이번 회전 범위 밖 — 학습이 있는 회전은 단독 기동 (§10-2)",
                 "성능 비교": "학습 이력 0건 — 비교할 것이 없다",
                 "배포": "검증된 모델이 없다",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


# ── 015 영향요인분석 ──────────────────────────────────────────────────────
@router.get("/est/015")
async def shap_factors(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-015")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    rows = ml_registry.shap_factors(quote_no=f.get("q0") or None,
                                    feature_name=f.get("q2") or None,
                                    rank_no=int(f["q3"]) if f.get("q3", "").isdigit() else None)
    grid = [_row([i, r["quote_no"] or http.undetermined("D-04"), r["feature_name"], r["shap_value"],
                  r["rank_no"], r["impact_direction"], r["expert_match_yn"]])
            for i, r in enumerate(rows, 1)]
    counts = {"predictions": _n("select count(*) as n from EST_ML_PREDICTIONS"),
              "shap": _n("select count(*) as n from EST_SHAP_FACTORS")}
    audit(request, screen.id, "조회")
    return render(
        request, "est/015.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid,
        empty_note=EMPTY + " — 예측이 0건이면 SHAP 도 0건이다 (런타임 전용 표)",
        badges=[{"text": "전문가 평가 변수 목록 없음 — 일치율 차단 (D-13)", "kind": "bad"},
                {"text": "런타임 전용 표 — 시드 대상 아님", "kind": "notice"}],
        notices=[], counts=counts,
        actions={"분석 실행": "예측 결과(EST_ML_PREDICTIONS)가 0건이다 — 학습 회전 이후",
                 "리포트": "전문가 평가 변수 목록 확보 후 (D-13)",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


# ── 037 AI학습 데이터관리 (URL 은 데이터관리, 구현은 여기 — D-38) ──────────
@router.get("/dat/037")
async def train_datasets(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-037")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    rows = ml_datasets.datasets(dataset_name=f.get("q0") or None,
                                target_model=f.get("q1") or None,
                                dataset_version=f.get("q2") or None,
                                dataset_status=f.get("q3") or None)
    grid = [_row([i, r["dataset_name"], r["target_model"], r["dataset_version"],
                  f"{int(r['total_cnt']):,}" if r["total_cnt"] is not None else "",
                  f"{int(r['excluded_cnt']):,}" if r["excluded_cnt"] is not None else "",
                  r["dataset_status"]]) for i, r in enumerate(rows, 1)]
    coverage = []
    for r in rows:
        c = ml_datasets.label_coverage(int(r["dataset_id"]))
        coverage.append({**c, "name": r["dataset_name"]})
    audit(request, screen.id, "조회")
    return render(
        request, "est/037.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY,
        badges=[{"text": "Label 확보 미확인 (D-04)", "kind": "bad"},
                {"text": "합성 데이터 기준 (D-03)", "kind": "undetermined"}],
        notices=[], rules=ml_datasets.preprocess_rules(), splits=ml_datasets.splits(),
        coverage=coverage,
        actions={"등록": "데이터셋 등록은 화면 입력 마스터",
                 "전처리 실행": "DAT_PREPROCESS_RULES 순서대로 — 중복 제거는 tools/cad_ingest.py 와 같은 규칙",
                 "분할": "Train/Validation/Test — DAT_DATASET_SPLITS",
                 "저장": "확정(DATASET_STATUS) 전까지 상태만 바꾼다",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )
