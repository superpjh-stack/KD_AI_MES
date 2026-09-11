"""데이터관리 033~036 (개발1).

**수집 지점은 2개소뿐이다**(레이저커팅기 PLC · 현장POP — D-06). `DAT_TIMESERIES` 를 읽는 화면은
그 범위 밖을 `미수집 (D-06)` 으로 표기한다. 수집 자체는 개발3 의 `ingest`(TD4-047) 소관이고
여기서 수집한 척하지 않는다(G-30).

`/dat/037`(AI학습 데이터관리)는 개발3 의 `routers/est.py` 다 — 여기서 다루지 않는다.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request

from .bas import (anchor_label, code_names, code_options, dt, guard, paginate,  # noqa: F401
                  redirect, require_fields, screen_page, search_spec, undetermined, val)
from .sys import _record_download
from .. import design
from ..util import clock, csrf, http

import conn                                              # noqa: E402

router = APIRouter()
SCREENS = ("MES-TD3-033", "MES-TD3-034", "MES-TD3-035", "MES-TD3-036")

# TD5 비고가 정한 열거값
DATA_TYPES = ("정형", "시계열", "비정형")
IF_METHODS = ("API", "DB", "OPC-UA", "파일")
JOB_TYPES = ("수집", "변환(ETL)", "적재", "정제")
RESULT_CODES = ("성공", "실패", "부분성공")
FILE_FORMATS = ("Excel", "CSV")
QUALITY_FLAGS = ("정상", "노이즈", "결측")
# 반출 통제 대상 (TD5 `DAT_DOWNLOAD_LOGS.DATA_CATEGORY` 비고 — 9.2 ① 핵심 지적 자산)
DATA_CATEGORIES = ("CAD", "견적", "BOM", "생산", "품질")

# 수집대상별 '즉시 실행' 이 실제로 무엇을 할 수 있는지. **못 하는 것은 못 한다고 기록한다**(G-30).
RUNNABLE: dict[str, str] = {
    "ERP(이카운트)": "",          # Excel 적재 실적을 실측해 기록한다
    "레이저커팅기 PLC": "수집 API 는 개발3 의 ingest(MES-TD4-047) 소관이다 — 여기서 실행하지 않는다 (D-06)",
    "현장POP(터치PC)": "현장POP 입력은 공정실적 화면(개발2)이 받는다 — 여기서 실행하지 않는다 (D-06)",
    "CAD 도면함": "CAD Parsing 미구성 — Autodesk API·YOLOv8 미확보 (D-05)",
    "외부 표준문서": "문서 임베딩은 개발3 의 MES-TD4-049 소관이다 (D-08)",
}


def _opts(values) -> list[dict[str, str]]:
    return [{"value": v, "label": v} for v in values]


# ═════════════════════════════════════════════════════════════════════════
# 033 데이터통합관리
# ═════════════════════════════════════════════════════════════════════════
@router.get("/dat/033")
async def integration(request: Request):
    sid = "MES-TD3-033"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("src"):
        where.append("s.SOURCE_NAME ilike %s"); params.append(f"%{q['src']}%")
    if q.get("dtype"):
        where.append("s.DATA_TYPE = %s"); params.append(q["dtype"])
    if q.get("method"):
        where.append("s.IF_METHOD = %s"); params.append(q["method"])
    if q.get("jtype"):
        where.append("j.JOB_TYPE = %s"); params.append(q["jtype"])
    if q.get("result"):
        where.append("g.RESULT_CODE = %s"); params.append(q["result"])
    if q.get("from"):
        where.append("g.START_DT >= %s"); params.append(q["from"])
    cond = " and ".join(where)
    join = ("from DAT_INTEGRATION_JOBS j "
            "join DAT_SOURCES s on s.SOURCE_ID = j.SOURCE_ID "
            "left join lateral (select RESULT_CODE, PROCESS_CNT, FAIL_CNT, ERROR_MSG, START_DT "
            "                   from DAT_JOB_LOGS x where x.JOB_ID = j.JOB_ID "
            "                   order by x.START_DT desc, x.JOB_LOG_ID desc limit 1) g on true")

    total = int(conn.q1(f"select count(*) as n {join} where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select s.SOURCE_NAME, s.DATA_TYPE, s.IF_METHOD, j.TARGET_STORE, g.RESULT_CODE, "
        f"g.PROCESS_CNT, g.ERROR_MSG {join} where {cond} order by j.JOB_ID limit %s offset %s",
        [*params, size, off])
    grid = [[str(off + i), r["source_name"], r["data_type"], r["if_method"], r["target_store"],
             ({"text": f"{r['result_code']} — {(r['error_msg'] or '')[:48]}", "notice": True}
              if r["result_code"] == "실패" else val(r["result_code"], "D-06")),
             val(r["process_cnt"], "D-06")]
            for i, r in enumerate(rows, 1)]

    logs = conn.q(
        "select j.JOB_NAME, g.START_DT, g.END_DT, g.PROCESS_CNT, g.FAIL_CNT, g.RESULT_CODE, "
        "g.ERROR_MSG from DAT_JOB_LOGS g join DAT_INTEGRATION_JOBS j on j.JOB_ID = g.JOB_ID "
        "order by g.START_DT desc, g.JOB_LOG_ID desc limit 20")
    log_rows = [[str(i), g["job_name"], dt(g["start_dt"]), dt(g["end_dt"], "D-06"),
                 val(g["process_cnt"], "D-06"), val(g["fail_cnt"], "D-06"),
                 g["result_code"], val(g["error_msg"], "D-06")]
                for i, g in enumerate(logs, 1)]

    checks = conn.q(
        "select CHECK_AXIS, TARGET_DESC, TOTAL_CNT, VALID_CNT, ACHIEVE_RATE, JUDGE_RESULT "
        "from DAT_QUALITY_CHECKS order by CHECKED_DT desc limit 10")
    check_rows = [[str(i), c["check_axis"], c["target_desc"], str(c["total_cnt"]),
                   str(c["valid_cnt"]), val(c["achieve_rate"], "D-09"),
                   val(c["judge_result"], "D-09")]
                  for i, c in enumerate(checks, 1)]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("src", "text"), ("dtype", "text", _opts(DATA_TYPES)),
            ("method", "text", _opts(IF_METHODS)), ("jtype", "text", _opts(JOB_TYPES)),
            ("result", "text", _opts(RESULT_CODES)), ("from", "date")]),
        rows=grid, total=total, pager=pager, grid_title="통합 작업",
        empty_notice=http.not_collected("D-06") +
        " — 수집대상이 없다. `uv run python db/seed_dev1.py` 로 5종을 넣는다.",
        cards=[{"label": "통합 작업", "value": f"{total} 건"},
               {"label": "실행 로그", "value": f"{len(logs)} 건"},
               {"label": "품질검증", "value": f"{len(checks)} 건"}],
        notices=[{"kind": "notice",
                  "text": "정형(수주·생산·재고·품질) + 시계열(설비·공정) + 비정형(CAD·문서·이미지)을 "
                          "모두 수용한다 (SF-TD3-033 체크)"},
                 {"kind": "bad",
                  "text": "수집 지점은 레이저커팅기 PLC·현장POP 2개소뿐이다 (D-06). "
                          "그 밖의 수집을 실행한 척하지 않는다"},
                 {"kind": "bad",
                  "text": "ERP 연계 대상·실사용 범위가 사업계획서 안에서 상충한다 (D-07) — "
                          "Excel 적재(/inv/007)가 정식 입력 경로다"}],
        panels=[
            {"title": "실행 로그 (DAT_JOB_LOGS)",
             "columns": ["No", "작업명", "시작", "종료", "처리 건수", "실패 건수", "결과", "오류 메시지"],
             "rows": log_rows,
             "empty_notice": http.not_collected("D-06") +
             " — 실행 로그는 런타임 전용이다(G-11). 아래 '즉시 실행' 이 쌓는다."},
            {"title": "데이터 품질 검증 (DAT_QUALITY_CHECKS)",
             "columns": ["No", "검증 축", "대상", "전체", "정상", "달성률(%)", "판정"],
             "rows": check_rows,
             "empty_notice": http.not_collected("D-09") +
             " — 007 입고 데이터관리의 '정합성 검증' 이 실측으로 기록한다.",
             "note": "정확성·정합성·연계성 목표 85% (사업계획서 2.7.4). 시드로 채우지 않는다."},
        ],
        disabled_note="'즉시 실행' 은 아래 버튼이다. 등록·저장·엑셀은 미구현이다(G-30).",
        extra_actions=[{"label": "즉시 실행", "action": "/dat/033", "name": "action", "value": "run"}],
    )


@router.post("/dat/033")
async def integration_run(request: Request):
    """통합 작업 실행 — **할 수 있는 것만 하고, 못 하는 것은 실패로 기록한다**(G-30)."""
    sid = "MES-TD3-033"
    form = await request.form()
    csrf.require(request, form.get("_csrf"))
    guard(request, sid, write=True)
    if (form.get("action") or "").strip() != "run":
        raise http.fail("validation", "알 수 없는 동작")

    started = clock.anchor()
    for job in conn.q("select j.JOB_ID, s.SOURCE_NAME from DAT_INTEGRATION_JOBS j "
                      "join DAT_SOURCES s on s.SOURCE_ID = j.SOURCE_ID order by j.JOB_ID"):
        name = job["source_name"]
        blocked = RUNNABLE.get(name, f"'{name}' 의 실행 경로가 정의되지 않았다")
        if blocked:
            processed, failed, result, msg = 0, 0, "실패", blocked
        else:
            # ERP 경로는 Excel 적재 실적을 **실측**한다 (D-07).
            processed = int(conn.q1("select count(*) as n from IF_ERP_RECEIPTS "
                                    "where IF_STATUS='성공'")["n"])
            failed = int(conn.q1("select count(*) as n from IF_ERP_RECEIPTS "
                                 "where IF_STATUS='실패'")["n"])
            if processed and failed:
                result, msg = "부분성공", f"실패 {failed}건 — /inv/007 에서 사유를 확인한다"
            elif processed:
                result, msg = "성공", None
            else:
                result, msg = "실패", "적재된 입고 연계 이력이 없다 — /inv/007 Excel 적재로 넣는다 (D-07)"
        conn.x(
            "insert into DAT_JOB_LOGS "
            "(JOB_ID, START_DT, END_DT, PROCESS_CNT, FAIL_CNT, RESULT_CODE, ERROR_MSG, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s, now())",
            (job["job_id"], started, started, processed, failed, result, msg))
    return redirect("/dat/033")


# ═════════════════════════════════════════════════════════════════════════
# 034 데이터조회 — 정형·시계열·비정형 통합
# ═════════════════════════════════════════════════════════════════════════
@router.get("/dat/034")
async def data_search(request: Request):
    sid = "MES-TD3-034"
    scr, td3 = guard(request, sid)
    q = request.query_params
    kind = q.get("kind") or ""
    rows: list[list[object]] = []

    if kind in ("", "시계열"):
        w, p = ["1=1"], []
        if q.get("from"):
            w.append("MEASURE_DT >= %s"); p.append(q["from"])
        if q.get("flag"):
            w.append("QUALITY_FLAG = %s"); p.append(q["flag"])
        if q.get("equip"):
            w.append("EQUIP_CODE = %s"); p.append(q["equip"])
        for r in conn.q(
                f"select TAG_NAME, EQUIP_CODE, MEASURE_DT, MEASURE_VALUE, UOM, QUALITY_FLAG "
                f"from DAT_TIMESERIES where {' and '.join(w)} order by MEASURE_DT desc limit 100", p):
            rows.append(["시계열", undetermined("D-06"), r["tag_name"], r["measure_dt"],
                         f"{r['measure_value']:,.4f}" if r["measure_value"] is not None
                         else undetermined("D-06"),
                         val(r["quality_flag"], "D-06")])

    if kind in ("", "비정형"):
        w, p = ["1=1"], []
        if q.get("from"):
            w.append("INGESTED_DT >= %s"); p.append(q["from"])
        for r in conn.q(
                f"select OBJ_TYPE, ORIGIN_FILE_NAME, INGESTED_DT from DAT_LAKE_OBJECTS "
                f"where {' and '.join(w)} order by INGESTED_DT desc limit 100", p):
            rows.append(["비정형", undetermined("D-05"), r["origin_file_name"],
                         r["ingested_dt"], "-", val(r["obj_type"], "D-05")])

    rows.sort(key=lambda r: r[3], reverse=True)
    total = len(rows)
    pager, size, off = paginate(request, total)
    grid = [[str(off + i), r[1], r[0], r[2], dt(r[3]), r[4], r[5]]
            for i, r in enumerate(rows[off:off + size], 1)]

    ts_total = int(conn.q1("select count(*) as n from DAT_TIMESERIES")["n"])
    lake_total = int(conn.q1("select count(*) as n from DAT_LAKE_OBJECTS")["n"])
    hist = int(conn.q1("select count(*) as n from INV_MATERIAL_HISTORY")["n"])
    linked = int(conn.q1("select count(*) as n from INV_MATERIAL_HISTORY "
                         "where PRODUCT_LOT_NO is not null")["n"])

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("lot", "text"), ("from", "date"), ("equip", "text", code_options("설비")),
            ("kind", "text", _opts(DATA_TYPES)), ("flag", "text", _opts(QUALITY_FLAGS))]),
        rows=grid, total=total, pager=pager, grid_title="통합 데이터",
        empty_notice=http.not_collected("D-06") +
        " — 시계열은 레이저커팅기 PLC·현장POP 2개소에서만 수집된다(개발3 TD4-047). "
        "비정형은 CAD Parsing 이 구성돼야 들어온다(D-05).",
        cards=[{"label": "시계열", "value": f"{ts_total} 건"},
               {"label": "비정형", "value": f"{lake_total} 건"},
               {"label": "자재 이력", "value": f"{hist} 건"},
               {"label": "LOT 연계율",
                "value": f"{linked / hist * 100:.1f} %" if hist else "0.0 %"}],
        notices=[{"kind": "notice",
                  "text": "데이터 연계율 목표 85% 이상 (사업계획서 2.7.4 ⓷) — 위 값은 실측이다"},
                 {"kind": "undetermined",
                  "text": "제품 LOT 연결은 SHP_LOT_TRACES(개발2)와 수집 태그 매핑(개발3)이 있어야 "
                          "성립한다 — 지금은 미확정으로 표시한다 (D-06)"}],
        disabled_note="'연계 분석' 은 LOT 연계율 카드가 실측으로 보여준다. 엑셀은 미구현이다(G-30).",
    )


# ═════════════════════════════════════════════════════════════════════════
# 035 데이터시각화 — 목업 kind 가 dashboard 다 (조회 조건 없이 표출)
# ═════════════════════════════════════════════════════════════════════════
@router.get("/dat/035")
async def visualize(request: Request):
    sid = "MES-TD3-035"
    scr, td3 = guard(request, sid)
    mock = td3.get("mockup") or {}
    a = clock.anchor()
    month_start = a.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    produced = int(conn.q1(
        "select coalesce(sum(GOOD_QTY), 0) as n from PRC_PERFORMANCES where END_DT >= %s",
        (month_start,))["n"])
    quote = conn.q1("select avg(TOTAL_AMOUNT) as m from EST_QUOTATIONS")

    # 목업 카드 4장의 **라벨은 정본**이다. 값은 실측이거나 미확정이다 — `(예시)` 값을 쓰지 않는다.
    labels = [c["label"] for c in mock.get("cards", [])]
    values = [
        f"{produced} 건",                                   # 금월 생산량 (0 건은 정답 — §10-14)
        http.undetermined("D-06"),                          # 설비 가동률 — 수집 2개소뿐, 산식 미확정
        http.undetermined("D-35"),                          # 납기 준수율 — KPI 산식은 app/kpi.py(개발2)
        f"{float(quote['m']):,.1f}" if quote and quote["m"] is not None
        else http.undetermined("D-04"),                     # 평균 견적원가 — 견적 0건
    ]
    cards = [{"label": lb, "value": v} for lb, v in zip(labels, values)]

    # 월별 추이 — 앵커 기준 6개월(목업 chart_bars 와 같은 6칸). 막대는 **실측**이고
    # 외부 차트 라이브러리를 쓰지 않는다 — 인라인 CSS 로 그린다(D-50).
    starts, m = [], month_start
    for _ in range(len(mock.get("chart_bars") or [0] * 6)):
        starts.append(m)
        m = (m - timedelta(days=1)).replace(day=1)
    starts.reverse()

    bars, peak = [], 0
    for start in starts:
        nxt = (start + timedelta(days=32)).replace(day=1)
        n = int(conn.q1("select coalesce(sum(GOOD_QTY), 0) as n from PRC_PERFORMANCES "
                        "where END_DT >= %s and END_DT < %s", (start, nxt))["n"])
        peak = max(peak, n)
        bars.append({"label": f"{start:%Y-%m}", "value": n})
    chart = [{"label": b["label"], "value": f"{b['value']} ea",
              "percent": round(b["value"] / peak * 100) if peak else 0} for b in bars]

    projects = conn.q(
        "select p.PROJECT_NO, p.PROJECT_NAME, q.TOTAL_AMOUNT from EST_QUOTATIONS q "
        "join EST_PROJECTS p on p.PROJECT_ID = q.PROJECT_ID "
        "order by q.TOTAL_AMOUNT desc nulls last limit 5")
    top = max((float(p["total_amount"] or 0) for p in projects), default=0)
    bars2 = [{"label": f"{p['project_no']} {p['project_name']}",
              "text": f"{float(p['total_amount'] or 0):,.0f}",
              "percent": round(float(p["total_amount"] or 0) / top * 100) if top else 0}
             for p in projects]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        columns=[], search=[], buttons=[],
        cards=cards,
        description=[{"title": "화면 구성", "lines": [td3.get("composition", "")]},
                     {"title": "화면 항목", "lines": [td3.get("items", "")]},
                     {"title": "검토 사항", "lines": [td3.get("checks", "")]}],
        notices=[{"kind": "notice",
                  "text": f"자동 갱신 주기 {_refresh()} 초 — 현황판 65\" 2대 표출 "
                          "(조회 조건 없이 갱신한다 · TD3 layout_rules)"},
                 {"kind": "undetermined",
                  "text": "설비 가동률 산식은 수집 지점 2개소만으로 정의되지 않는다 (D-06)"},
                 {"kind": "undetermined",
                  "text": "납기 준수율은 KPI 산식 단일 소스(app/kpi.py — 개발2 D-35)가 정본이다 — "
                          "여기서 산식을 복제하지 않는다"},
                 {"kind": "notice",
                  "text": "차트는 인라인 CSS 로 그린다 — 외부 CDN·차트 라이브러리 0건 (D-50)"}],
        panels=[
            {"title": mock.get("chart_title", "").replace("(예시)", "") + " (실측)",
             "chart": chart,
             "note": "막대는 PRC_PERFORMANCES 실측 건수다. 0건이면 0 높이로 그린다 — "
                     "없는 값을 채우지 않는다."},
            {"title": mock.get("list_title", "").replace("(예시)", "") + " (실측)",
             "bars": bars2,
             "columns": [] if bars2 else ["프로젝트", "견적 금액"],
             "rows": [],
             "empty_notice": http.not_collected("D-04") +
             " — 견적은 개발3 의 CAD·ML 파이프라인(TD4-012)이 만든다.",
             "note": "프로젝트(수주)번호가 최상위 조회 축이다 (TD3 standard_note 2)."},
        ],
    )


def _refresh() -> str:
    from ..settings import settings
    return settings().h("BOARD_REFRESH_SEC").value


# ═════════════════════════════════════════════════════════════════════════
# 036 데이터 다운로드 — 반출 통제 (9.2 ① · G-29)
# ═════════════════════════════════════════════════════════════════════════
@router.get("/dat/036")
async def downloads(request: Request):
    sid = "MES-TD3-036"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("from"):
        where.append("d.DOWNLOAD_DT >= %s"); params.append(q["from"])
    if q.get("user"):
        where.append("u.LOGIN_ID ilike %s"); params.append(f"%{q['user']}%")
    if q.get("cat"):
        where.append("d.DATA_CATEGORY = %s"); params.append(q["cat"])
    if q.get("fmt"):
        where.append("d.FILE_FORMAT = %s"); params.append(q["fmt"])
    if q.get("appr"):
        where.append("d.APPROVED_YN = %s"); params.append(q["appr"])
    cond = " and ".join(where)
    join = "from DAT_DOWNLOAD_LOGS d join SYS_USERS u on u.USER_ID = d.USER_ID"

    total = int(conn.q1(f"select count(*) as n {join} where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select d.DOWNLOAD_DT, u.LOGIN_ID, d.DATA_CATEGORY, d.FILE_FORMAT, d.ROW_CNT, "
        f"d.APPROVED_YN {join} where {cond} order by d.DOWNLOAD_DT desc limit %s offset %s",
        [*params, size, off])
    grid = [[str(off + i), dt(r["download_dt"]), r["login_id"], r["data_category"],
             r["file_format"], val(r["row_cnt"], "D-17"), r["approved_yn"]]
            for i, r in enumerate(rows, 1)]

    # 역할별 반출 권한 — `SYS_ROLE_PERMISSIONS.DOWNLOAD_YN` 이 정본이다(공통 시드가 채웠다).
    perm_rows = [[str(i), p["role_name"], p["area_code"], p["read_yn"], p["download_yn"]]
                 for i, p in enumerate(conn.q(
                     "select ROLE_NAME, AREA_CODE, READ_YN, DOWNLOAD_YN from SYS_ROLE_PERMISSIONS "
                     "where AREA_CODE in ('DAT','EST','INV','SHP') "
                     "order by ROLE_CODE, AREA_CODE"), 1)]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("from", "date"), ("user", "text"), ("cat", "text", _opts(DATA_CATEGORIES)),
            ("fmt", "text", _opts(FILE_FORMATS)), ("appr", "text", _opts(("Y", "N")))]),
        rows=grid, total=total, pager=pager, grid_title="다운로드 이력",
        empty_notice=http.not_collected("D-17") +
        " — 반출 이력은 런타임 전용이다(G-11). 깨끗한 DB 에서 0건이 정상이고 "
        "다운로드가 일어나면 쌓인다.",
        cards=[{"label": "반출 이력", "value": f"{total} 건"},
               {"label": "승인", "value": f"{sum(1 for r in rows if r['approved_yn'] == 'Y')} 건"}],
        notices=[{"kind": "bad",
                  "text": "CAD 도면·견적·BOM·원가 정보는 핵심 지적 자산이다 — "
                          "반출 기준과 권한 통제를 적용한다 (9.2 ① · SF-TD3-036 체크)"},
                 {"kind": "notice",
                  "text": "권한 없는 역할의 반출은 403 이고 이력도 남지 않는다 (G-28)"}],
        panels=[{
            "title": "역할별 반출 권한 (SYS_ROLE_PERMISSIONS.DOWNLOAD_YN)",
            "columns": ["No", "역할", "업무영역", "조회", "반출"],
            "rows": perm_rows,
            "empty_notice": http.not_collected("D-108") + " — 먼저 `make db-seed`.",
        }],
        form={
            "title": "데이터 반출", "action": "/dat/036", "submit": "다운로드",
            "note": "권한을 먼저 확인하고 이력을 남긴다. **파일 생성은 미구현이다** — "
                    "내려받은 척하지 않는다(G-30).",
            "fields": [
                {"label": "데이터 구분", "name": "category", "required": True,
                 "options": _opts(DATA_CATEGORIES)},
                {"label": "파일 형식", "name": "fmt", "required": True,
                 "options": _opts(FILE_FORMATS)},
            ],
        },
        disabled_note="'권한 확인'·'다운로드' 는 아래 폼이 담당한다. 엑셀 파일 생성은 미구현이다(G-30).",
    )


@router.post("/dat/036")
async def downloads_record(request: Request):
    sid = "MES-TD3-036"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("category", "fmt"))
    if v["category"] not in DATA_CATEGORIES:
        raise http.fail("validation", f"데이터 구분은 {DATA_CATEGORIES} 중 하나다")
    if v["fmt"] not in FILE_FORMATS:
        raise http.fail("validation", f"파일 형식은 {FILE_FORMATS} 중 하나다")
    _record_download(request, sid, v["category"], v["fmt"], 0)
    return redirect("/dat/036")
