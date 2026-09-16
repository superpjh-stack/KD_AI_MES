"""수주견적AI관리 010~015 + AI학습 데이터관리 037 (개발3).

`/dat/037` 은 **업무영역은 데이터관리, 구현은 여기**다(D-38). URL·메뉴 위치는 산출물 그대로 둔다.

이 파일이 지키는 것
  · 화면의 모든 칸은 `design.screen(sid)["mockup"]` 에서 온다. `(예시)` 값을 시드·렌더하지 않는다.
  · **CAD 인식은 미구성이면 501**(D-05). 조용한 합성 Feature 0건.
  · **승인 없이 `EST_QUOTATIONS`·`EST_BOM_HEADERS`·`EST_CAD_OBJECTS` 가 바뀌는 경로가 없다**(G-24).
  · 0건은 정상이다 — 그때 그리드는 `미수집` 문구를 렌더한다(G-11).
  · **조회조건은 전부 열에 붙는다.** 받아 놓고 안 쓰는 칸을 두지 않는다 — 안 쓰면 사용자는
    거른 줄 알고 전체 목록을 본다. 붙일 열이 없으면 그 사실을 화면에 적는다.
  · **받은 파라미터를 조용히 버리지 않는다** — `?project=`·`?drawing=`·`?quote=` 는 5단계
    스레드 이동이 싣고 오는 값이라 해당 조회조건 칸으로 접힌다(ALIASES).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote as _urlq

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ...cad import inventory as cad_inventory
from ...cad import pipeline as cad_pipeline
from ...ml import datasets as ml_datasets
from ...ml import registry as ml_registry
from .. import design, nav, rbac
from ..templating import render
from ..util import assumed, csrf, http
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

# 5단계 스레드가 실어 오는 이름 → 그 화면의 몇 번째 조회조건인가 (TD3 mockup 실측).
# 전에는 `?project=GD1906` 이 **무시돼 전체 목록**이 나왔다 — 거른 줄 알고 읽게 된다.
ALIASES: dict[str, dict[str, int]] = {
    "MES-TD3-010": {"drawing": 0, "project": 1},
    "MES-TD3-011": {"drawing": 0},
    "MES-TD3-012": {"quote": 0, "project": 1},
    "MES-TD3-013": {"project": 1, "drawing": 2},
    "MES-TD3-015": {"quote": 0},
}

NO_APPROVE = f"{EST_AREA} 승인 권한 없음 — 확정할 수 없다 (G-24 · G-28)"


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


def _filters(request: Request, fields: list[str], sid: str = "") -> dict[str, str]:
    """조회조건 `q0..qN` + **별칭**(`project`·`drawing`·`quote`)을 같은 칸으로 접는다."""
    qp = request.query_params
    out = {f"q{i}": (qp.get(f"q{i}") or "").strip() for i in range(len(fields))}
    for name, idx in ALIASES.get(sid, {}).items():
        v = (qp.get(name) or "").strip()
        if v and not out.get(f"q{idx}"):
            out[f"q{idx}"] = v
    return out


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


def _cell(text: Any, link: str | None = None) -> dict[str, Any]:
    return {"text": "" if text is None else str(text), "link": link}


def _row(cells: list[Any], links: dict[int, str | None] | None = None,
         extra: list[dict[str, Any]] | None = None,
         form_id: Any = None) -> dict[str, Any]:
    """그리드 한 행. `links` 는 **칸 번호 → 링크**(값이 없으면 링크를 걸지 않는다)."""
    return {"cells": ["" if c is None else str(c) for c in cells],
            "links": {i: u for i, u in (links or {}).items() if u},
            "extra": extra or [],
            "form_id": "" if form_id is None else str(form_id)}


def _period_cond(value: str, column: str, label: str) -> tuple[str, list[Any]]:
    """`YYYY-MM-DD` 또는 `YYYY-MM-DD~YYYY-MM-DD`. **형식이 틀리면 422**(§2.5)."""
    parts = value.replace(" ", "").split("~")
    fmt = f"{label} 은 'YYYY-MM-DD' 또는 'YYYY-MM-DD~YYYY-MM-DD' 형식이다: {value!r}"
    if len(parts) > 2 or not parts[0]:
        raise http.fail("validation", fmt)
    try:
        days = [date.fromisoformat(p) for p in parts]
    except ValueError:
        raise http.fail("validation", fmt) from None
    start, end = days[0], days[-1]
    if end < start:
        raise http.fail("validation", f"{label} 의 시작일이 종료일보다 늦다: {value!r}")
    return f"{column} >= %s and {column} < %s", [start, end + timedelta(days=1)]


def _code_value(group: str, value: str, label: str) -> str:
    """코드명·코드값 둘 다 받고 **코드값**을 돌려준다. 목록 밖이면 422 (D-32)."""
    row = conn.q1(
        "select CODE_VALUE from BAS_COMMON_CODES where CODE_GROUP = %s and USE_YN = 'Y' "
        "  and (CODE_VALUE = %s or CODE_NAME = %s)", (group, value, value))
    if row is not None:
        return str(row["code_value"])
    known = [f"{r['code_value']}({r['code_name']})" for r in conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = %s and USE_YN = 'Y' order by SORT_ORDER, CODE_VALUE", (group,))]
    raise http.fail("validation",
                    f"{label} 코드가 BAS_COMMON_CODES('{group}') 에 없다: {value!r} — "
                    f"쓸 수 있는 값 {known or '0건'}")


def _num(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise http.fail("validation", f"{label} 은 숫자여야 한다: {value!r}") from None


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


def _where(conds: list[str]) -> str:
    return ("where " + " and ".join(conds) + " ") if conds else ""


# ── 010 CAD 도면분석 ──────────────────────────────────────────────────────
@router.get("/est/010")
async def cad_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-010")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-010")
    page, size, off = _page(request)
    conds, params = [], []
    if f["q0"]:
        conds.append("d.DRAWING_NO ilike %s")
        params.append(f"%{f['q0']}%")
    if f["q1"]:
        conds.append("p.PROJECT_NO ilike %s")
        params.append(f"%{f['q1']}%")
    if f["q2"]:                          # 파일 구분 — 대소문자를 가리지 않는다(dwg ↔ DWG)
        conds.append("upper(d.FILE_TYPE) = upper(%s)")
        params.append(f["q2"])
    if f["q3"]:
        conds.append("d.ANALYSIS_STATUS = %s")
        params.append(f["q3"])
    if f["q4"]:                          # 기간 — 발행일 메타가 없어 최종수정일(FILE_MTIME)로 본다
        c, p = _period_cond(f["q4"], "d.FILE_MTIME", sf[4])
        conds.append(c)
        params += p
    if f["q5"]:
        conds.append("p.PRODUCT_GROUP = %s")
        params.append(_code_value("제품군", f["q5"], sf[5]))
    src = ("from EST_CAD_DRAWINGS d left join EST_PROJECTS p on p.PROJECT_ID = d.PROJECT_ID ")
    where = _where(conds)
    total = _n(f"select count(*) as n {src}{where}", params)
    rows = conn.q(
        "select d.DRAWING_ID, d.DRAWING_NO, p.PROJECT_NO, d.FILE_TYPE, d.ANALYSIS_STATUS, "
        "       d.FILE_MTIME, "
        "       (select count(*) from EST_CAD_OBJECTS o where o.DRAWING_ID = d.DRAWING_ID) as objects "
        f"{src}{where}order by d.DRAWING_ID limit %s offset %s", [*params, size, off])
    grid = [
        _row([off + i, r["drawing_no"], r["project_no"] or http.undetermined("D-03"), r["file_type"],
              r["analysis_status"], r["objects"] or "-",
              r["file_mtime"].date() if r["file_mtime"] else ""],
             links={1: f"/est/011?drawing={_urlq(r['drawing_no'])}",
                    2: f"/prc/024?project={_urlq(r['project_no'])}" if r["project_no"] else None})
        for i, r in enumerate(rows, 1)
    ]
    try:
        files = cad_inventory.read_inventory()
        stats = cad_inventory.stats(files)
        inv_err = ""
    except (FileNotFoundError, ImportError) as e:
        stats, inv_err = None, f"도면 인벤토리를 읽지 못했다: {e}"
    audit(request, screen.id, "조회")
    result_link = "/est/011" + (f"?project={_urlq(f['q1'])}" if f["q1"] else "")
    return render(
        request, "est/010.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        empty_note=EMPTY + " — `make cad-ingest` 로 도면을 수집한다",
        badges=_cad_badges(), notices=[],
        actions={"도면 업로드": "아래 '도면 파일 업로드' 카드에서 한다 (MES-TD4-048)",
                 "분석 실행": "501 CAD Parsing 미구성 (D-05) — Autodesk API·YOLOv8 미확보",
                 "결과보기": "011 객체인식 결과관리로 이동 — 지금 건 프로젝트 조건을 싣고 간다",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①) — 개발1 036 화면"},
        button_links={"결과보기": result_link},
        stages=cad_pipeline.stage_status(), config=cad_pipeline.config_badges(),
        inventory=stats, inventory_error=inv_err,
        can_upload=rbac.can_write(role, EST_AREA),
        upload_note=(
            "업로드는 인터페이스 MES-TD4-048 `POST /api/cad/files` 가 받는다 — **화면이 없는 "
            "연계**라 응답은 HTML 이 아니라 등록 결과 JSON 이다. 원본 바이너리는 보관하지 "
            "않는다(Data Lake 미구성). 분석 실행은 501 CAD Parsing 미구성 (D-05)."),
        upload_types=sorted(cad_inventory.FILE_TYPES),
    )


# ── 011 객체인식 결과관리 ─────────────────────────────────────────────────
@router.get("/est/011")
async def object_reviews(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-011")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-011")
    page, size, off = _page(request)
    # 010 '결과보기' 가 싣고 오는 프로젝트 조건. **011 mockup 에는 칸이 없다** — 조회조건으로
    # 만들어 넣지 않고(정본 5칸 고정) 상위 필터로 걸고 그 사실을 화면에 적는다.
    project = (request.query_params.get("project") or "").strip()
    conds, params = [], []
    if f["q0"]:
        conds.append("d.DRAWING_NO ilike %s")
        params.append(f"%{f['q0']}%")
    if f["q1"]:
        conds.append("o.OBJECT_TYPE = %s")
        params.append(f["q1"])
    if f["q2"]:
        conds.append("o.DETECT_METHOD = %s")
        params.append(f["q2"])
    if f["q3"]:                          # 신뢰도 범위 — 하한 이상
        conds.append("o.CONFIDENCE_SCORE >= %s")
        params.append(_num(f["q3"], sf[3]))
    if f["q4"]:
        conds.append("o.CONFIRM_YN = %s")
        params.append(f["q4"])
    if project:
        conds.append("p.PROJECT_NO = %s")
        params.append(project)
    src = ("from EST_CAD_OBJECTS o join EST_CAD_DRAWINGS d on d.DRAWING_ID = o.DRAWING_ID "
           "left join EST_PROJECTS p on p.PROJECT_ID = d.PROJECT_ID ")
    where = _where(conds)
    total = _n(f"select count(*) as n {src}{where}", params)
    rows = conn.q(
        "select o.OBJECT_ID, d.DRAWING_NO, p.PROJECT_NO, o.OBJECT_TYPE, o.DETECT_METHOD, "
        "       o.DIMENSION_VALUE, o.CONFIDENCE_SCORE, o.CONFIRM_YN, o.CROSS_CHECK_RESULT "
        f"{src}{where}order by o.OBJECT_ID limit %s offset %s", [*params, size, off])
    grid = [_row([off + i, r["drawing_no"], r["object_type"], r["detect_method"],
                  r["dimension_value"], r["confidence_score"], r["confirm_yn"]],
                 links={1: f"/est/013?drawing={_urlq(r['drawing_no'])}"},
                 extra=[_cell(r["project_no"] or http.undetermined("D-03"),
                              f"/prc/024?project={_urlq(r['project_no'])}" if r["project_no"] else None),
                        _cell(r["cross_check_result"] or http.not_collected("D-05"))],
                 form_id=r["object_id"])
            for i, r in enumerate(rows, 1)]
    counts = {
        "objects": _n("select count(*) as n from EST_CAD_OBJECTS"),
        "confirmed": _n("select count(*) as n from EST_CAD_OBJECTS where CONFIRM_YN = 'Y'"),
        "reviews": _n("select count(*) as n from EST_OBJECT_REVIEWS"),
        "features": _n("select count(*) as n from EST_CAD_FEATURES"),
    }
    can_approve = rbac.can_approve(role, EST_AREA)
    audit(request, screen.id, "조회")
    return render(
        request, "est/011.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        extra_filters={"project": project} if project else {},
        extra_columns=["프로젝트번호", "교차검증 근거"],
        empty_note=EMPTY + " — 인식 실행이 501 이라 객체가 0건이다 (D-05)",
        badges=_cad_badges() + [{"text": "HITL — 승인 전 확정 아님 (G-24)", "kind": "notice"}],
        notices=([f"상위 필터: 프로젝트(수주)번호 = {project} — 010 결과보기가 싣고 온 조건이다"]
                 if project else []),
        actions={"검증": "행마다 붙은 '검증 기록' 폼 — POST /est/011/review",
                 "수정": "같은 폼에서 검토 결과를 '수정' 으로 보낸다",
                 "확정": "같은 폼에서 '승인' — 승인 권한 없으면 403",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
        counts=counts, area=EST_AREA, can_approve=can_approve,
        derivable={k: v[2] for k, v in cad_pipeline.DERIVABLE.items()},
        blocked=cad_pipeline.BLOCKED_FEATURES,
        unit_note=assumed.unit_note(),
        grid_badges=[{"text": "승인 전에는 확정이 아니다 (G-24)", "kind": "notice"}],
        row_form={
            "action": "/est/011/review", "id_name": "object_id", "title": "HITL 검증 (G-24)",
            "button": "검증 기록", "can": can_approve, "note": NO_APPROVE,
            "selects": [{"name": "result", "label": "검토 결과",
                         "options": list(cad_pipeline.REVIEW_RESULTS), "required": True}],
            "texts": [{"name": "before", "label": "수정 전"},
                      {"name": "after", "label": "수정 후"},
                      {"name": "comment", "label": "의견"}],
        },
    )


def _form_int(form: Any, name: str) -> int:
    """필수 정수 폼 값. 없거나 숫자가 아니면 **422** (§2.5 validation)."""
    raw = str(form.get(name) or "").strip()
    if not raw:
        raise http.fail("validation", f"필수값 누락: {name}")
    try:
        return int(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 정수여야 한다: {raw!r}") from None


def _form_str(form: Any, name: str, *, required: bool = False) -> str:
    raw = str(form.get(name) or "").strip()
    if required and not raw:
        raise http.fail("validation", f"필수값 누락: {name}")
    return raw


@router.post("/est/011/review")
async def object_review(request: Request):
    """**`CONFIRM_YN` 을 바꾸는 유일한 HTTP 경로** (G-24). 승인 권한 없으면 403.

    `Form(...)` 을 시그니처에 두면 FastAPI 가 본문보다 먼저 파싱해서 토큰 없는 요청이
    403 이 아니라 422 를 받는다 — 검사 순서는 **CSRF → 권한 → 입력값** 이다(계약 §4.0).
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, _td3, role = _guard(request, "MES-TD3-011")
    object_id = _form_int(form, "object_id")
    result = _form_str(form, "result", required=True)
    before = _form_str(form, "before")
    after = _form_str(form, "after")
    comment = _form_str(form, "comment")
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
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-012")
    page, size, off = _page(request)
    conds, params = [], []
    if f["q0"]:
        conds.append("q.QUOTE_NO ilike %s")
        params.append(f"%{f['q0']}%")
    if f["q1"]:
        conds.append("p.PROJECT_NO ilike %s")
        params.append(f"%{f['q1']}%")
    if f["q2"]:
        conds.append("p.CUSTOMER_CODE = %s")
        params.append(_code_value("고객사", f["q2"], sf[2]))
    if f["q3"]:
        conds.append("q.QUOTE_STATUS = %s")
        params.append(f["q3"])
    if f["q4"]:                          # 기간 — TD5 에 견적일자 컬럼이 없다. 생성일시로 본다
        c, p = _period_cond(f["q4"], "q.CREATED_DT", sf[4])
        conds.append(c)
        params += p
    if f["q5"]:
        conds.append("q.CALC_METHOD = %s")
        params.append(f["q5"])
    src = "from EST_QUOTATIONS q join EST_PROJECTS p on p.PROJECT_ID = q.PROJECT_ID "
    where = _where(conds)
    total = _n(f"select count(*) as n {src}{where}", params)
    rows = conn.q(
        "select q.QUOTE_ID, q.QUOTE_NO, p.PROJECT_NO, q.CALC_METHOD, q.TOTAL_AMOUNT, "
        "       q.CONFIDENCE_SCORE, q.QUOTE_STATUS "
        f"{src}{where}order by q.QUOTE_ID limit %s offset %s", [*params, size, off])
    grid = [_row([off + i, r["quote_no"], r["project_no"], r["calc_method"],
                  f"{int(r['total_amount']):,} 원" if r["total_amount"] is not None else "",
                  r["confidence_score"], r["quote_status"]],
                 links={1: f"/est/015?quote={_urlq(r['quote_no'])}",
                        2: f"/prc/024?project={_urlq(r['project_no'])}"},
                 form_id=r["quote_id"])
            for i, r in enumerate(rows, 1)]
    counts = {
        "cost_rates": _n("select count(*) as n from EST_COST_RATES where USE_YN = 'Y'"),
        "features": _n("select count(*) as n from EST_CAD_FEATURES"),
        "models": _n("select count(*) as n from EST_ML_MODELS where DEPLOY_STATUS = '배포'"),
    }
    can_approve = rbac.can_approve(role, EST_AREA)
    audit(request, screen.id, "조회")
    return render(
        request, "est/012.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        empty_note=EMPTY + " — 단가 기준·Label 미확보 (D-04)",
        badges=[{"text": "Label 미확보 — 정확도 측정 불가 (D-04)", "kind": "bad"},
                {"text": "학습 미실시 — 다음 단독 회전", "kind": "undetermined"}],
        grid_badges=[{"text": "견적 Label 없음 (D-04)", "kind": "bad"}],
        notices=[], counts=counts,
        actions={"견적 산출": "422 — 단가 기준(EST_COST_RATES) 0건 · 견적 Feature 0건 (D-04·D-05)",
                 "저장": "승인 전 견적 확정은 422 (§2.5)",
                 "승인요청": "행마다 붙은 '견적 확정' 폼 — POST /est/012/confirm (G-24)",
                 "리포트": "015 영향요인분석과 함께 본다 — 견적번호를 누르면 간다",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
        row_form={
            "action": "/est/012/confirm", "id_name": "quote_id", "title": "확정 (G-24)",
            "button": "견적 확정", "can": can_approve, "note": NO_APPROVE,
            "selects": [], "texts": [],
        },
    )


@router.post("/est/012/confirm")
async def confirm_quote(request: Request):
    """견적 확정 — **승인 권한이 없으면 403**, 승인 전 확정은 422 (G-24 · §2.5)."""
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, _td3, role = _guard(request, "MES-TD3-012")
    quote_id = _form_int(form, "quote_id")
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
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-013")
    page, size, off = _page(request)
    conds, params = [], []
    if f["q0"]:
        conds.append("b.BOM_NO ilike %s")
        params.append(f"%{f['q0']}%")
    if f["q1"]:
        conds.append("p.PROJECT_NO ilike %s")
        params.append(f"%{f['q1']}%")
    if f["q2"]:
        conds.append("d.DRAWING_NO ilike %s")
        params.append(f"%{f['q2']}%")
    if f["q3"]:
        conds.append("b.GEN_METHOD = %s")
        params.append(f["q3"])
    if f["q4"]:
        conds.append("b.CONFIRM_YN = %s")
        params.append(f["q4"])
    src = ("from EST_BOM_HEADERS b join EST_PROJECTS p on p.PROJECT_ID = b.PROJECT_ID "
           "left join EST_CAD_DRAWINGS d on d.DRAWING_ID = b.DRAWING_ID ")
    where = _where(conds)
    total = _n(f"select count(*) as n {src}{where}", params)
    rows = conn.q(
        "select b.BOM_ID, b.BOM_NO, p.PROJECT_NO, b.GEN_METHOD, b.BOM_VERSION, "
        "       b.ACCURACY_RATE, b.CONFIRM_YN, b.CYCLE_CHECK_RESULT "
        f"{src}{where}order by b.BOM_ID limit %s offset %s", [*params, size, off])
    grid = [_row([off + i, r["bom_no"], r["project_no"], r["gen_method"], r["bom_version"],
                  r["accuracy_rate"] if r["accuracy_rate"] is not None else http.undetermined("D-04"),
                  r["confirm_yn"]],
                 links={1: f"/est/013?bom={_urlq(r['bom_no'])}",
                        2: f"/prc/024?project={_urlq(r['project_no'])}"},
                 extra=[_cell("012 견적", f"/est/012?project={_urlq(r['project_no'])}"),
                        _cell(r["cycle_check_result"] or http.not_collected("D-06"))],
                 form_id=r["bom_id"])
            for i, r in enumerate(rows, 1)]
    counts = {
        "item_codes": _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = '품목' and USE_YN='Y'"),
        "materials": _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP = '재질' and USE_YN='Y'"),
        "confirmed": _n("select count(*) as n from EST_CAD_OBJECTS where CONFIRM_YN = 'Y'"),
        "boms": _n("select count(*) as n from EST_BOM_HEADERS"),
    }
    can_approve = rbac.can_approve(role, EST_AREA)
    bom_no = (request.query_params.get("bom") or "").strip()
    audit(request, screen.id, "조회")
    return render(
        request, "est/013.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        extra_filters={"bom": bom_no} if bom_no else {},
        extra_columns=["견적", "순환 참조 검증"],
        empty_note=EMPTY + " — 품목·재질 코드 그룹이 비어 있다 (D-47)",
        badges=[{"text": "기준 BOM 부재 — 정확도 측정 불가 (D-04)", "kind": "bad"},
                {"text": "대체 표기 (D-41)", "kind": "undetermined"}],
        grid_badges=[{"text": "합성 데이터 기준 (D-131)", "kind": "undetermined"}],
        notices=[], counts=counts,
        actions={"BOM 생성": "422 — 품목·재질 코드 그룹 0건 (D-47) · 확정 객체 0건 (D-05)",
                 "다단계 전개": "BOM 번호를 누르면 아래에 EST_BOM_ITEMS 전개표가 열린다",
                 "저장": "승인 전 BOM 확정은 422 (§2.5)",
                 "삭제": "승인 권한 필요 (G-24)",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
        row_form={
            "action": "/est/013/confirm", "id_name": "bom_id", "title": "확정 (G-24)",
            "button": "BOM 확정", "can": can_approve, "note": NO_APPROVE,
            "selects": [], "texts": [],
        },
        bom_no=bom_no, bom_items=_bom_items(bom_no) if bom_no else None,
    )


def _bom_items(bom_no: str) -> dict[str, Any]:
    """**다단계 전개** — `EST_BOM_ITEMS.PARENT_ITEM_ID` 자기참조를 레벨 순으로 편다."""
    head = conn.q1(
        "select b.BOM_ID, b.BOM_NO, b.BOM_VERSION, b.GEN_METHOD, b.CONFIRM_YN, "
        "       b.CYCLE_CHECK_RESULT, p.PROJECT_NO "
        "from EST_BOM_HEADERS b join EST_PROJECTS p on p.PROJECT_ID = b.PROJECT_ID "
        "where b.BOM_NO = %s", (bom_no,))
    if head is None:
        return {"header": None, "rows": [],
                "note": f"BOM 번호 {bom_no} 가 EST_BOM_HEADERS 에 없다"}
    rows = conn.q(
        "select i.BOM_ITEM_ID, i.PARENT_ITEM_ID, i.BOM_LEVEL, i.ITEM_CODE, i.MATERIAL, "
        "       i.SPEC_TEXT, i.REQUIRE_QTY, i.UOM, c.CODE_NAME as ITEM_NAME "
        "from EST_BOM_ITEMS i "
        "left join BAS_COMMON_CODES c on c.CODE_GROUP = '품목' and c.CODE_VALUE = i.ITEM_CODE "
        "where i.BOM_ID = %s order by i.BOM_LEVEL, i.BOM_ITEM_ID", (int(head["bom_id"]),))
    return {"header": head, "rows": rows,
            "note": "" if rows else EMPTY + " — 이 BOM 에 하위 항목이 없다"}


@router.post("/est/013/confirm")
async def confirm_bom(request: Request):
    """BOM 확정 — **승인 권한이 없으면 403** (G-24).

    `CYCLE_CHECK_RESULT` 는 **'정상' 일 때만** 확정한다. 전에는 `not in ('정상', None, '')` 이라
    **검증하지 않은(NULL) BOM 이 그대로 통과**했다 — 순환 참조를 안 본 것과 통과한 것은 다르다.
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, _td3, role = _guard(request, "MES-TD3-013")
    bom_id = _form_int(form, "bom_id")
    if not rbac.can_approve(role, EST_AREA):
        raise http.fail("forbidden", f"{EST_AREA} 승인 권한 없음 — BOM 을 확정할 수 없다 (G-24)")
    row = conn.q1("select BOM_ID, CYCLE_CHECK_RESULT from EST_BOM_HEADERS where BOM_ID = %s", (bom_id,))
    if row is None:
        raise http.fail("validation", f"BOM {bom_id} 가 없다")
    got = row["cycle_check_result"]
    if got != "정상":
        raise http.fail(
            "validation",
            f"순환 참조 검증 결과가 '정상' 이 아니다: {got if got else '미검증(비어 있음)'} — "
            "검증하지 않은 BOM 은 확정할 수 없다 (TD5 CYCLE_CHECK_RESULT)")
    conn.x("update EST_BOM_HEADERS set CONFIRM_YN = 'Y', UPDATED_DT = now() where BOM_ID = %s", (bom_id,))
    audit(request, screen.id, "BOM확정", log_type="변경")
    return RedirectResponse("/est/013", status_code=303)


# ── 014 ML분석 ────────────────────────────────────────────────────────────
@router.get("/est/014")
async def ml_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-014")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-014")
    page, size, off = _page(request)
    sel: dict[str, Any] = {}
    if f["q0"]:
        sel["model_name"] = f["q0"]
    if f["q1"]:
        sel["model_type"] = f["q1"]
    if f["q2"]:
        sel["model_version"] = f["q2"]
    if f["q3"]:
        sel["deploy_status"] = f["q3"]
    if f["q4"]:                          # 학습 기간 — EST_ML_TRAIN_RUNS.START_DT
        c, p = _period_cond(f["q4"], "r.START_DT", sf[4])
        sel["period_sql"], sel["period_params"] = c, p
    runs = ml_registry.train_runs(limit=size, offset=off, **sel)
    total = ml_registry.train_runs_count(**sel)
    grid = [_row([off + i, f"{r['model_name']}", r["model_version"], r["train_cnt"],
                  r["valid_metric"], r["overfit_result"], r["run_status"]])
            for i, r in enumerate(runs, 1)]
    audit(request, screen.id, "조회")
    model_sel = {k: v for k, v in sel.items() if not k.startswith("period")}
    return render(
        request, "est/014.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        empty_note=EMPTY + " — 학습을 실행하지 않았다 (다음 단독 회전, goal.md §10-2)",
        badges=[{"text": "학습 미실시 — 다음 단독 회전", "kind": "undetermined"},
                {"text": "성능 수치를 만들지 않는다", "kind": "bad"}],
        notices=[], readiness=ml_registry.readiness(),
        actions={"학습 실행": "이번 회전 범위 밖 — 학습이 있는 회전은 단독 기동 (§10-2)",
                 "성능 비교": "학습 이력 0건 — 비교할 것이 없다",
                 "배포": "아래 '배포·롤백' 카드에서 한다 (G-25)",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
        models=ml_registry.models(**model_sel), deploy_note=_deploy_note(),
        can_approve=rbac.can_approve(role, EST_AREA),
    )


def _deploy_note() -> str:
    """배포·롤백 카드의 상태 문구. **0건이면 0건이라고 말한다** (G-11)."""
    rows = ml_registry.models()
    if not rows:
        return (http.not_collected("D-04") +
                " — 학습을 실행하지 않아 EST_ML_MODELS 가 0건이다. 배포·롤백 경로는 있지만 "
                "되돌릴 버전이 없다(422).")
    names = sorted({r["model_name"] for r in rows})
    out = []
    for name in names:
        cur = ml_registry.deployed_model(name)
        prev = ml_registry.previous_version(name)
        out.append(f"{name}: 배포 {cur['model_version'] if cur else '없음'} · "
                   f"직전 {prev['model_version'] if prev else '없음'}")
    return " / ".join(out)


@router.post("/est/014/deploy")
async def deploy_model(request: Request):
    """모델 **배포 · 직전 버전 롤백** (G-25 MLOps).

    승인 권한이 없으면 **403**. 되돌릴 버전이 없으면 **422** — 없는데 성공한 척하지 않는다.
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, _td3, role = _guard(request, "MES-TD3-014")
    if not rbac.can_approve(role, EST_AREA):
        raise http.fail("forbidden", f"{EST_AREA} 승인 권한 없음 — 모델을 배포·롤백할 수 없다 (G-24)")
    action = _form_str(form, "action", required=True)
    if action == "롤백":
        out = ml_registry.rollback(_form_str(form, "model_name", required=True))
    elif action == "배포":
        out = ml_registry.deploy(_form_int(form, "model_id"))
    else:
        raise http.fail("validation", "action 은 배포 또는 롤백이다")
    audit(request, screen.id, f"모델{action}:{out.get('model_version')}", log_type="변경")
    return RedirectResponse("/est/014", status_code=303)


# ── 015 영향요인분석 ──────────────────────────────────────────────────────
@router.get("/est/015")
async def shap_factors(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-015")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-015")
    page, size, off = _page(request)
    sel: dict[str, Any] = {}
    if f["q0"]:
        sel["quote_no"] = f["q0"]                    # 부분 일치 (ilike)
    if f["q1"]:
        sel["target_type"] = f["q1"]                 # 예측 대상 구분 — EST_ML_PREDICTIONS
    if f["q2"]:
        sel["feature_name"] = f["q2"]
    if f["q3"]:
        if not f["q3"].isdigit():
            raise http.fail("validation", f"{sf[3]} 은 정수여야 한다: {f['q3']!r}")
        sel["rank_no"] = int(f["q3"])
    if f["q4"]:                                      # 기간 — 예측 일시
        c, p = _period_cond(f["q4"], "p.PREDICTED_DT", sf[4])
        sel["period_sql"], sel["period_params"] = c, p
    rows = ml_registry.shap_factors(limit=size, offset=off, **sel)
    total = ml_registry.shap_count(**sel)
    grid = [_row([off + i, r["quote_no"] or http.undetermined("D-04"), r["feature_name"],
                  f"{float(r['shap_value']):.4f}" if r["shap_value"] is not None else "",
                  r["rank_no"], r["impact_direction"],
                  r["expert_match_yn"] or http.undetermined("D-13")])
            for i, r in enumerate(rows, 1)]
    counts = {"predictions": _n("select count(*) as n from EST_ML_PREDICTIONS"),
              "shap": _n("select count(*) as n from EST_SHAP_FACTORS")}
    audit(request, screen.id, "조회")
    return render(
        request, "est/015.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
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
    sf = m["search_fields"]
    f = _filters(request, sf, "MES-TD3-037")
    page, size, off = _page(request)
    sel: dict[str, Any] = {}
    if f["q0"]:
        sel["dataset_name"] = f["q0"]
    if f["q1"]:
        sel["target_model"] = f["q1"]
    if f["q2"]:
        sel["dataset_version"] = f["q2"]
    if f["q3"]:
        sel["dataset_status"] = f["q3"]
    if f["q4"]:                                      # 기간 — 데이터셋 생성일시
        c, p = _period_cond(f["q4"], "d.CREATED_DT", sf[4])
        sel["period_sql"], sel["period_params"] = c, p
    rows = ml_datasets.datasets(limit=size, offset=off, **sel)
    total = ml_datasets.datasets_count(**sel)
    grid = [_row([off + i, r["dataset_name"], r["target_model"], r["dataset_version"],
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
        filters=f, rows=grid, total=total, empty_note=EMPTY,
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
