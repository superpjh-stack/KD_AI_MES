"""공정관리 021~025 (개발2).

**자동 수집은 레이저커팅 1공정뿐이다(D-06).** 수집 지점은 레이저커팅기 Master PLC 1 +
현장POP 1 = **2개소**다. 나머지 공정 실적은 현장POP·스마트패드 **수동 입력**이고, 외주 2공정
(소재가공·버핑)은 실적이 아니라 **발주·반출·반입 상태 관리**다(D-41). 전 공정 실시간 수집인 척
렌더하면 결함이다.

**024 공정이력조회는 디지털 스레드의 도착지다(G-08).** 다른 화면의 LOT·프로젝트번호 셀이
전부 여기로 들어온다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..templating import render
from ..util import codes, csrf, http
from .dsh import (COLLECT_DECISION, HISTORY_PATH, STD_COND_DECISION, anchor, cell,
                  collection_badges, count_total, ctx, date_range, day_prefix, dt, guard,
                  lot_cell, mock, num, page_of, pager, parse_datetime, process_names,
                  process_options, project_cell, range_wired, safe_next, writing)

router = APIRouter()
SCREENS = ("MES-TD3-021", "MES-TD3-022", "MES-TD3-023", "MES-TD3-024", "MES-TD3-025")

AUTO_PROCESS = "P40"              # 가공(레이저커팅) — 자동 수집 대상 1공정 (D-06)
OUTSOURCED = ("P30", "P60")       # 소재가공·버핑 — 발주·반출·반입 상태 (D-41)
METHOD_AUTO, METHOD_MANUAL = "자동(PLC)", "수동(POP·패드)"
PAGE = 50
# 작업지시 상태 어휘는 TD5 비고 정본이다 — 화면이 따로 정하지 않는다.
ORDER_STATES = ("대기", "진행", "완료", "보류")
ORDER_OPEN = tuple(s for s in ORDER_STATES if s != "완료")


def _q(request: Request, key: str) -> str:
    return (request.query_params.get(key) or "").strip()


def product_groups() -> list[tuple[str, str]]:
    """제품군 조회조건 — `BAS_COMMON_CODES('제품군')` 정본(반응기·교반기·진공건조기·누체필터·저장탱크)."""
    import conn
    return [(r["code_value"], f"{r['code_name']} ({r['code_value']})") for r in conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = '제품군' and USE_YN = 'Y' order by SORT_ORDER")]


# ── 021 공정실적관리 ────────────────────────────────────────────────────
@router.get("/prc/021")
async def performances(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-021")
    names = process_names()
    f = {k: _q(request, k) for k in ("wo", "process", "lot", "method", "worker")}
    f["date"] = day_prefix(request, "date")          # YYYY-MM-DD 또는 YYYY-MM · 그 외 422
    page, offset = page_of(request, PAGE)

    core = (
        "from PRC_PERFORMANCES p "
        "join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = p.WORK_ORDER_ID "
        "left join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = p.LOT_TRACE_ID "
        "left join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "left join SYS_USERS u on u.USER_ID = p.WORKER_ID "
        "where (%(date)s = '' or to_char(p.START_DT,'YYYY-MM-DD') like %(date)s || '%%') "
        "  and (%(wo)s = '' or w.WORK_ORDER_NO ilike '%%' || %(wo)s || '%%') "
        "  and (%(process)s = '' or p.PROCESS_CODE = %(process)s) "
        "  and (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(method)s = '' or p.COLLECT_METHOD ilike '%%' || %(method)s || '%%') "
        "  and (%(worker)s = '' or coalesce(u.USER_NAME, u.LOGIN_ID) "
        "       ilike '%%' || %(worker)s || '%%') "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select p.PERF_ID, w.WORK_ORDER_NO, p.PROCESS_CODE, p.START_DT, p.END_DT, "
        "p.GOOD_QTY, p.DEFECT_QTY, p.COLLECT_METHOD, lt.PRODUCT_LOT_NO, pj.PROJECT_NO "
        + core +
        # 같은 시각 실적이 여러 건이면 순서가 흔들려 페이징이 행을 빠뜨리거나 겹친다 —
        # 2차 정렬 키를 둔다.
        "order by p.START_DT desc, p.PERF_ID desc limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    agg = conn.q1(
        "select count(*) as n, "
        "count(*) filter (where COLLECT_METHOD = %s) as auto_n, "
        "coalesce(sum(GOOD_QTY),0) as good, coalesce(sum(DEFECT_QTY),0) as defect "
        "from PRC_PERFORMANCES", (METHOD_AUTO,),
    ) or {}

    def _thread_href(r) -> str | None:
        """이 실적이 달린 **제품 LOT → 024 공정이력조회**. LOT 이 없으면 프로젝트로 간다(G-08)."""
        if r["product_lot_no"]:
            return f"{HISTORY_PATH}?lot={r['product_lot_no']}"
        if r["project_no"]:
            return f"{HISTORY_PATH}?project={r['project_no']}"
        return None

    # 그리드 열은 **정본 7개 그대로**다(TD3 layout_rules '열은 최대 7개'). 열을 늘리는 대신
    # 작업지시번호 셀에 그 실적의 제품 LOT·프로젝트 스레드를 건다.
    grid_rows = [[
        cell(offset + i, num=True),
        cell(f"{r['work_order_no']}"
             + (f" · {r['product_lot_no']}" if r["product_lot_no"] else
                (f" · {r['project_no']}" if r["project_no"] else "")),
             href=_thread_href(r)),
        cell(names.get(r["process_code"], r["process_code"])),
        cell(dt(r["start_dt"])),
        cell(num(r["good_qty"], 3), num=True),
        cell(num(r["defect_qty"], 3), num=True),
        cell(r["collect_method"]),
    ] for i, r in enumerate(rows, 1)]

    # 실적을 붙일 수 있는 것은 **끝나지 않은 작업지시**다. 상태 어휘는 TD5 비고 정본(ORDER_STATES).
    open_orders = conn.q(
        "select w.WORK_ORDER_ID, w.WORK_ORDER_NO, w.PROCESS_CODE, w.ORDER_STATUS, pj.PROJECT_NO "
        "from PRC_WORK_ORDERS w join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "where w.OUTSOURCE_YN = 'N' and w.ORDER_STATUS = any(%s) "
        "order by w.WORK_ORDER_NO limit 200", (list(ORDER_OPEN),),
    )

    return render(request, "prc/021.html", **ctx(
        request, screen, td3,
        wired={"작업일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD 또는 YYYY-MM"},
               "작업지시번호": {"name": "wo", "value": f["wo"], "hint": "WO-"},
               "공정": {"name": "process", "value": f["process"],
                      "options": process_options(names, OUTSOURCED)},
               "제품 LOT": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "작업자": {"name": "worker", "value": f["worker"], "hint": "이름 일부"},
               "수집 방식": {"name": "method", "value": f["method"], "hint": "자동/수동"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        back=request.url.path + (("?" + request.url.query) if request.url.query else ""),
        open_states=" / ".join(ORDER_OPEN),
        empty_note=http.not_collected(COLLECT_DECISION),
        cards=[
            {"label": "실적 건수", "value": f"{int(agg.get('n') or 0):,} 건"},
            {"label": "자동 수집", "value": f"{int(agg.get('auto_n') or 0):,} 건",
             "sub": "레이저커팅 1공정뿐 (D-06)"},
            {"label": "실적 수량", "value": num(agg.get("good"), 3, "ea")},
            {"label": "불량 수량", "value": num(agg.get("defect"), 3, "ea")},
        ],
        badges=collection_badges(),
        processes=[(c, n) for c, n in names.items() if c not in OUTSOURCED],
        open_orders=open_orders,
        auto_process=AUTO_PROCESS,
        method_manual=METHOD_MANUAL, method_auto=METHOD_AUTO,
        notes=[{"title": "수집 범위",
                "body": "자동 수집 대상은 레이저커팅기 PLC 1지점과 현장POP 1지점뿐이다. "
                        "그 외 공정 실적은 현장POP·스마트패드 수동 입력이고, 외주 2공정"
                        "(소재가공·버핑)은 발주·반출·반입 상태 관리다 (D-06 · D-41)."}],
    ))


def _num_field(form: Any, name: str, default: float | None = None) -> float:
    """수량 폼 값. 비어 있으면 기본값, 숫자가 아니면 **422** (§2.5)."""
    raw = (form.get(name) or "").strip()
    if not raw:
        if default is None:
            raise http.fail("validation", f"필수값 누락: {name}")
        return default
    try:
        return float(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 숫자여야 한다: {raw!r}") from None


@router.post("/prc/021")
async def create_performance(request: Request):
    """공정 실적 등록. 등록 권한 없으면 **403**, 계약 위반은 **422**.

    `Form(...)` 을 시그니처에 두지 않는다 — FastAPI 가 **핸들러 본문보다 먼저** 파싱해서
    빈 POST 가 CSRF·권한 검사 전에 FastAPI 자체 JSON 422 를 받는다(실측). 검사 순서는
    계약 §4.0 이다: **CSRF → 권한 → 입력값.**
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))  # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3 = guard(request, "MES-TD3-021", write=True)
    with writing(request, "MES-TD3-021", "등록"):
        return _create_performance(request, form)


def _create_performance(request: Request, form: Any):
    import conn
    from fastapi.responses import RedirectResponse

    raw_wo = (form.get("work_order_id") or "").strip()
    if not raw_wo:
        raise http.fail("validation", "필수값 누락: work_order_id")
    try:
        work_order_id = int(raw_wo)
    except ValueError:
        raise http.fail("validation", f"work_order_id 는 정수여야 한다: {raw_wo!r}") from None

    start_dt = parse_datetime(form.get("start_dt"), "작업 시작일시")
    good_qty = _num_field(form, "good_qty")
    defect_qty = _num_field(form, "defect_qty", 0.0)
    defect_type = (form.get("defect_type") or "").strip()
    collect_method = (form.get("collect_method") or METHOD_MANUAL).strip()

    wo = conn.q1(
        "select WORK_ORDER_ID, PROCESS_CODE, ORDER_STATUS, OUTSOURCE_YN "
        "from PRC_WORK_ORDERS where WORK_ORDER_ID = %s", (work_order_id,),
    )
    if wo is None:
        raise http.fail("validation", f"작업지시 {work_order_id} 가 없다")
    # 공정은 **작업지시가 정한다** — 화면이 보낸 값을 그대로 믿지 않는다(D-214).
    # 다만 보낸 값 자체가 계약 위반(D-06 자동 수집 · D-41 외주)이면 그것부터 말해 준다 —
    # "공정이 다르다" 로 바꿔치면 무엇이 틀렸는지 사용자가 모른다.
    sent = (form.get("process_code") or "").strip()
    claim = sent or wo["process_code"]
    codes.require_code("PRC_PERFORMANCES", "PROCESS_CODE", claim)
    codes.require_code("PRC_PERFORMANCES", "DEFECT_TYPE", defect_type or None, allow_empty=True)

    # **자동 수집인 척하지 않는다** — 레이저커팅 외 공정에 자동(PLC)을 붙이면 422 다(D-06).
    if collect_method == METHOD_AUTO and claim != AUTO_PROCESS:
        raise http.fail("validation",
                        f"자동 수집은 레이저커팅 1공정({AUTO_PROCESS})뿐이다 — "
                        f"{claim} 실적은 수동 입력이다 (D-06)")
    if claim in OUTSOURCED or wo["outsource_yn"] == "Y":
        raise http.fail("validation",
                        "외주 2공정(소재가공·버핑)은 실적이 아니라 발주·반출·반입 상태 관리다 (D-41)")
    process_code = wo["process_code"]
    if sent and sent != process_code:
        raise http.fail("validation",
                        f"작업지시 공정({process_code}) 과 실적 공정({sent}) 이 다르다")
    if good_qty < 0 or defect_qty < 0:
        raise http.fail("validation", "실적·불량 수량은 음수가 될 수 없다")

    lot = conn.q1(
        "select LOT_TRACE_ID from SHP_LOT_TRACES where WORK_ORDER_ID = %s", (work_order_id,))
    conn.x(
        "insert into PRC_PERFORMANCES (WORK_ORDER_ID, LOT_TRACE_ID, PROCESS_CODE, START_DT, "
        "GOOD_QTY, DEFECT_QTY, DEFECT_TYPE, COLLECT_METHOD, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s, now())",
        (work_order_id, int(lot["lot_trace_id"]) if lot else None, process_code, start_dt,
         good_qty, defect_qty, defect_type or None, collect_method),
    )
    return RedirectResponse(safe_next(request, form.get("back"), "/prc/021"), status_code=303)


# ── 022 공정 데이터 모니터링 ────────────────────────────────────────────
@router.get("/prc/022")
async def signals(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-022")
    f = {k: _q(request, k) for k in ("equip", "status", "alarm")}
    f.update(date_range(request))            # 수집 기간 시작·종료 — 잘못된 날짜는 422 (§2.5)
    page, offset = page_of(request, PAGE)

    core = (
        "from PRC_EQUIP_SIGNALS s "
        "left join BAS_COMMON_CODES c on c.CODE_GROUP = '설비' and c.CODE_VALUE = s.EQUIP_CODE "
        "where (%(equip)s = '' or s.EQUIP_CODE = %(equip)s) "
        "  and (%(from)s = '' or s.COLLECT_DT >= %(from)s::date) "
        "  and (%(to_excl)s = '' or s.COLLECT_DT < %(to_excl)s::date) "
        "  and (%(status)s = '' or s.RUN_STATUS = %(status)s) "
        "  and (%(alarm)s = '' or (%(alarm)s = 'Y') = (s.ALARM_CODE is not null)) "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select s.SIGNAL_ID, s.EQUIP_CODE, c.CODE_NAME, s.COLLECT_DT, s.RUN_STATUS, "
        "s.SPEED_VALUE, s.PRESSURE_VALUE, s.CURRENT_VALUE, s.TEMP_VALUE, s.ALARM_CODE "
        + core +
        "order by s.COLLECT_DT desc, s.SIGNAL_ID desc limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
        cell(f"{r['code_name'] or ''} ({r['equip_code']})".strip()),
        cell(dt(r["collect_dt"], "%Y-%m-%d %H:%M:%S")),
        cell(num(r["speed_value"], 4), num=True),
        cell(num(r["pressure_value"], 4), num=True),
        cell(num(r["current_value"], 4), num=True),
        cell(num(r["temp_value"], 4), num=True),
    ] for i, r in enumerate(rows, 1)]

    return render(request, "prc/022.html", **ctx(
        request, screen, td3,
        wired={"설비 코드": {"name": "equip", "value": f["equip"], "hint": "EQ10 / EQ20"},
               "수집 기간": range_wired("수집 기간", f),
               "가동 상태": {"name": "status", "value": f["status"], "hint": "가동/정지/대기/알람"},
               "알람 여부": {"name": "alarm", "value": f["alarm"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        empty_note=http.not_collected(COLLECT_DECISION),
        badges=collection_badges(),
        notes=[{"title": "수집 경로",
                "body": "레이저커팅기 PLC → Data Gateway → IF_PLC_SIGNALS → PRC_EQUIP_SIGNALS·"
                        "DAT_TIMESERIES. 수집은 개발3 ingest 가 적재한다. 기존 설비의 IoT 수집과 "
                        "품질 예측은 사업계획서 2.5 에서 '현 사업 미적용' 으로 명시돼 포함하지 않는다."}],
    ))


# ── 023 작업조건관리 ────────────────────────────────────────────────────
@router.get("/prc/023")
async def conditions(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-023")
    names = process_names()
    f = {k: _q(request, k) for k in ("process", "item", "use", "dev")}
    page, offset = page_of(request, PAGE)

    core = (
        "from PRC_STD_CONDITIONS s "
        "where (%(process)s = '' or s.PROCESS_CODE = %(process)s) "
        "  and (%(item)s = '' or s.COND_ITEM ilike '%%' || %(item)s || '%%') "
        "  and (%(use)s = '' or s.USE_YN = %(use)s) "
        "  and (%(dev)s = '' or (%(dev)s = 'Y') = (exists (select 1 from PRC_CONDITION_DEVIATIONS d "
        "        where d.STD_COND_ID = s.STD_COND_ID and d.OUT_OF_TOL_YN = 'Y'))) "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select s.STD_COND_ID, s.PROCESS_CODE, s.COND_ITEM, s.STD_VALUE, s.TOL_MIN, s.TOL_MAX, "
        "s.UOM, s.USE_YN, "
        "(select count(*) from PRC_CONDITION_DEVIATIONS d where d.STD_COND_ID = s.STD_COND_ID "
        " and d.OUT_OF_TOL_YN = 'Y') as out_n "
        + core +
        "order by s.PROCESS_CODE, s.COND_ITEM, s.STD_COND_ID limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
        cell(names.get(r["process_code"], r["process_code"])),
        cell(r["cond_item"]),
        cell(num(r["std_value"], 4), num=True),
        cell(num(r["tol_min"], 4), num=True),
        cell(num(r["tol_max"], 4), num=True),
        cell(r["uom"] or "—"),
    ] for i, r in enumerate(rows, 1)]

    std_total = (conn.q1("select count(*) as n from PRC_STD_CONDITIONS") or {"n": 0})["n"] or 0
    act = conn.q1("select count(*) as n from PRC_ACTUAL_CONDITIONS") or {"n": 0}
    dev = conn.q1(
        "select count(*) as n, count(*) filter (where OUT_OF_TOL_YN = 'Y') as out_n "
        "from PRC_CONDITION_DEVIATIONS") or {"n": 0, "out_n": 0}

    return render(request, "prc/023.html", **ctx(
        request, screen, td3,
        wired={"공정": {"name": "process", "value": f["process"],
                      "options": process_options(names)},
               "조건 항목": {"name": "item", "value": f["item"]},
               "사용여부": {"name": "use", "value": f["use"], "hint": "Y / N"},
               "편차 초과 여부": {"name": "dev", "value": f["dev"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        # 표준값이 **없는 것**이지 수집이 안 된 것이 아니다 → '미확정' 이 맞다.
        empty_note=f"{http.undetermined(STD_COND_DECISION)} — "
                   "표준 작업 조건 초기 정의는 도입기업이 제공해야 한다 (TD3 023 제약사항)",
        cards=[
            # 카드는 **표 전체**를 센다 — 이 쪽에 보이는 건수를 적으면 페이지를 넘길 때마다
            # '표준 조건' 수가 달라져 화면이 서로 다른 사실을 말한다.
            {"label": "표준 조건", "value": f"{int(std_total):,} 건",
             "sub": f"이 조회 조건 {total:,} 건"},
            {"label": "실측 조건", "value": f"{int(act['n'] or 0):,} 건"},
            {"label": "편차 기록", "value": f"{int(dev['n'] or 0):,} 건"},
            {"label": "허용범위 초과", "value": f"{int(dev['out_n'] or 0):,} 건"},
        ],
        badges=[{"cls": "undetermined", "text": http.undetermined(STD_COND_DECISION)}],
        notes=[{"title": "왜 비어 있는가",
                "body": "현행 작업 조건은 작업자 경험으로 전파되고 문서화되어 있지 않다"
                        "(TD3 023 제약사항). 표준값을 시드에 지어내지 않았다 — 도입기업 제공 후 "
                        "등록하면 실측·편차가 파생된다."}],
    ))


# ── 024 공정이력조회 — 디지털 스레드 도착지 (G-08) ────────────────────────
@router.get("/prc/024")
async def history(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-024")
    names = process_names()
    f = {k: _q(request, k) for k in ("lot", "project", "process", "status")}
    f.update(date_range(request))            # 기간 시작·종료 — 잘못된 날짜는 422 (§2.5)
    page, offset = page_of(request, PAGE)

    # `?lot=` 은 **제품 LOT 이 아닐 수도 있다** — 005·006 입고 화면은 자재 LOT 번호를 걸고
    # 이리로 보낸다(D-215). 자재 LOT 이면 그것이 투입된 제품 LOT 으로 옮겨 조회한다.
    material_lot, lot_filter = _resolve_material_lot(f["lot"])

    core = (
        "from PRC_PROCESS_HISTORIES h "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(lots)s::text[] is null or lt.PRODUCT_LOT_NO = any(%(lots)s)) "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(process)s = '' or h.PROCESS_CODE = %(process)s) "
        "  and (%(from)s = '' or h.IN_DT >= %(from)s::date) "
        "  and (%(to_excl)s = '' or h.IN_DT < %(to_excl)s::date) "
        "  and (%(status)s = '' or h.HIST_STATUS = %(status)s) "
    )
    params = {**f, "lot": lot_filter, "lots": material_lot["product_lots"] if material_lot else None}
    total = count_total(core, params)
    rows = conn.q(
        "select h.PRC_HIST_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, h.PROCESS_CODE, h.PROCESS_SEQ, "
        "h.IN_DT, h.OUT_DT, h.DWELL_HOUR, h.HIST_STATUS, h.OUTSOURCE_STEP "
        + core +
        "order by lt.PRODUCT_LOT_NO, h.PROCESS_SEQ, h.PRC_HIST_ID limit %(lim)s offset %(off)s",
        {**params, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
        lot_cell(r["product_lot_no"]),
        cell(names.get(r["process_code"], r["process_code"])
             + (f" · {r['outsource_step']}" if r["outsource_step"] else "")),
        cell(r["process_seq"], num=True),
        cell(dt(r["in_dt"])),
        cell(dt(r["out_dt"])),
        cell(num(r["dwell_hour"], 2), num=True),
    ] for i, r in enumerate(rows, 1)]

    broken = [r for r in rows if r["hist_status"] != "정상"]
    broken_total = count_total(core + " and h.HIST_STATUS <> '정상' ", params)

    # 스레드 패널 — 제품 LOT 하나면 그 사슬, 프로젝트면 **LOT 마다 한 줄**이다.
    # 전에는 프로젝트로 조회하면 `limit 1` 로 아무 LOT 이나 골라 그 사슬만 보여 줬다.
    # 나머지 LOT 이 화면에서 사라지는데 그것이 티가 나지 않았다(D-216).
    thread = chains = None
    if material_lot:
        chains = _chains_of(material_lot["product_lots"])
        if len(material_lot["product_lots"]) == 1:
            thread, chains = _thread(material_lot["product_lots"][0], ""), None
    elif f["lot"]:
        thread = _thread(f["lot"], "")
    elif f["project"]:
        lots = [r["product_lot_no"] for r in conn.q(
            "select lt.PRODUCT_LOT_NO from SHP_LOT_TRACES lt "
            "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
            "where upper(pj.PROJECT_NO) = upper(%s) order by lt.PRODUCT_LOT_NO", (f["project"],))]
        if len(lots) == 1:
            thread = _thread(lots[0], f["project"])
        elif lots:
            chains = _chains_of(lots)
        else:
            thread = _thread("", f["project"])       # LOT 이 아직 없는 프로젝트도 1단계는 보인다

    return render(request, "prc/024.html", **ctx(
        request, screen, td3,
        wired={"제품 LOT 번호": {"name": "lot", "value": f["lot"], "hint": "PLOT- / LOT-(자재)"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"], "hint": "프로젝트번호"},
               "공정": {"name": "process", "value": f["process"],
                      "options": process_options(names)},
               "기간": range_wired("기간", f),
               "이력 상태": {"name": "status", "value": f["status"], "hint": "정상 / 단절"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        empty_note=(f"{http.not_collected(COLLECT_DECISION)} — 해당 조건의 공정 이력이 없다"),
        cards=[
            {"label": "이력 건수", "value": f"{total:,} 건",
             "sub": f"이 쪽 {len(rows):,} 건"},
            {"label": "단절 구간", "value": f"{broken_total:,} 건",
             "sub": "외주 공정 실적 회신 전이면 이력이 단절된다 (D-41)"},
        ],
        thread=thread, chains=chains, material_lot=material_lot,
        broken_shown=len(broken),
        badges=[{"cls": "notice",
                 "text": "최상위 조회 축은 프로젝트(수주)번호·도면번호다. LOT 는 하위 식별자다"}]
               + ([{"cls": "notice",
                    "text": f"자재 LOT {material_lot['lot_no']} 로 조회했다 — 그 자재가 투입된 "
                            f"제품 LOT {len(material_lot['product_lots'])}건의 이력이다"}]
                  if material_lot else []),
        notes=[{"title": "디지털 스레드 (G-08)",
                "body": "EST_PROJECTS → EST_CAD_DRAWINGS → EST_BOM_HEADERS → INV_MATERIAL_LOTS → "
                        "PRC_WORK_ORDERS → PRC_PERFORMANCES → SHP_LOT_TRACES → SHP_INSPECTIONS → "
                        "SHP_SHIPMENTS. 어느 화면에서든 LOT·프로젝트번호를 누르면 이 화면으로 온다."}],
    ))


def _resolve_material_lot(lot: str) -> tuple[dict[str, Any] | None, str]:
    """`?lot=` 이 **자재 LOT** 이면 그 자재가 투입된 제품 LOT 으로 바꾼다 (D-215).

    005 입고검사·006 자재LOT 화면의 LOT 셀이 이리로 링크한다. 전에는 자재 LOT 번호가
    `SHP_LOT_TRACES.PRODUCT_LOT_NO` 와 겹치지 않아 **0건 화면**이 떴다 — 링크는 있는데
    도착지가 비는 것이 사슬 단절보다 나쁘다(사슬은 멀쩡한데 화면만 못 찾은 것이다).

    돌려주는 것: (자재LOT 정보 or None, 제품 LOT 이름 필터로 쓸 문자열).
    """
    import conn
    if not lot:
        return None, ""
    # 제품 LOT 으로 먼저 본다 — 이름이 겹치면 제품 LOT 이 우선이다(이 화면의 1차 축).
    if conn.q1("select 1 as x from SHP_LOT_TRACES where upper(PRODUCT_LOT_NO) = upper(%s)", (lot,)):
        return None, lot
    ml = conn.q1(
        "select LOT_ID, LOT_NO, ITEM_CODE, MATERIAL from INV_MATERIAL_LOTS "
        "where upper(LOT_NO) = upper(%s)", (lot,))
    if ml is None:
        return None, lot                      # 자재 LOT 도 아니면 원래대로 부분일치 조회다
    lots = [r["product_lot_no"] for r in conn.q(
        "select PRODUCT_LOT_NO from SHP_LOT_TRACES where MATERIAL_LOT_ID = %s "
        "order by PRODUCT_LOT_NO", (int(ml["lot_id"]),))]
    return ({"lot_no": ml["lot_no"], "item_code": ml["item_code"], "material": ml["material"],
             "product_lots": lots}, "")


def _chains_of(lot_nos: list[str]) -> list[dict[str, Any]]:
    """LOT **마다 한 줄**로 사슬 요약. 프로젝트로 조회했을 때 LOT 을 하나만 고르지 않는다."""
    return [c for c in (_thread(no, "") for no in lot_nos) if c]


def _rev(value: Any) -> str:
    """리비전 표기. 값이 없으면 `—` 다 — 파이썬 `None` 을 화면에 흘리지 않는다."""
    return str(value) if value not in (None, "") else "—"


def _thread(lot_no: str, project_no: str) -> dict[str, Any] | None:
    """G-08 사슬 9단계를 **끊긴 곳까지 그대로** 보여 준다. 없는 단계를 채우지 않는다.

    **연결은 그 LOT 의 것으로 따라간다**(D-216). 전에는 도면·BOM·작업지시를 '그 프로젝트의
    첫 행' 으로 골랐다 — LOT 이 실제로 쓴 BOM·작업지시가 아니라서 사슬이 맞는 것처럼 보였다.
    이제 `SHP_LOT_TRACES.BOM_ID` · `WORK_ORDER_ID` 를 따라가고, 링크가 `null` 이면
    그 단계는 **단절**이다(TD3 024 버튼 '단절 구간 표시').
    """
    import conn
    lt = None
    if lot_no:
        lt = conn.q1(
            "select lt.*, pj.PROJECT_NO, pj.PROJECT_NAME, pj.PROJECT_ID as pid "
            "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
            "where upper(lt.PRODUCT_LOT_NO) = upper(%s)", (lot_no,))
    if lt is None:
        # LOT 을 못 찾았으면 **프로젝트 단계까지만** 보여 준다. 다른 LOT 으로 갈아타지 않는다.
        pj = conn.q1("select PROJECT_NO, PROJECT_NAME, PROJECT_ID from EST_PROJECTS "
                     "where upper(PROJECT_NO) = upper(%s)", (project_no,)) if project_no else None
        if pj is None:
            return None
        lt = {"pid": pj["project_id"], "project_no": pj["project_no"],
              "project_name": pj["project_name"], "lot_trace_id": None,
              "product_lot_no": None, "bom_id": None, "material_lot_id": None,
              "work_order_id": None}

    pid, ltid = lt["pid"], lt.get("lot_trace_id")
    one = lambda sql, p: conn.q1(sql, p)                                        # noqa: E731
    # BOM 은 **이 LOT 이 쓴 것**이고, 도면은 그 BOM 이 가리키는 것이다.
    bom = one("select b.BOM_ID, b.BOM_NO, b.BOM_VERSION, b.DRAWING_ID from EST_BOM_HEADERS b "
              "where b.BOM_ID = %s", (lt.get("bom_id"),)) if lt.get("bom_id") else None
    draw = one("select DRAWING_NO, REVISION from EST_CAD_DRAWINGS where DRAWING_ID = %s",
               (bom["drawing_id"],)) if bom and bom.get("drawing_id") else None
    mlot = one("select LOT_NO, MATERIAL from INV_MATERIAL_LOTS where LOT_ID = %s",
               (lt.get("material_lot_id"),)) if lt.get("material_lot_id") else None
    wo = one("select w.WORK_ORDER_NO, w.PROCESS_CODE, w.ORDER_STATUS from PRC_WORK_ORDERS w "
             "where w.WORK_ORDER_ID = %s", (lt.get("work_order_id"),)) \
        if lt.get("work_order_id") else None
    perf = one("select count(*) as n from PRC_PERFORMANCES where LOT_TRACE_ID = %s",
               (ltid,)) if ltid else None
    insp = one("select count(*) as n, count(*) filter (where JUDGE_RESULT = '합격') as ok "
               "from SHP_INSPECTIONS where LOT_TRACE_ID = %s", (ltid,)) if ltid else None
    ship = one("select s.SHIPMENT_NO, s.SHIP_DT from SHP_SHIPMENT_ITEMS i "
               "join SHP_SHIPMENTS s on s.SHIPMENT_ID = i.SHIPMENT_ID "
               "where i.LOT_TRACE_ID = %s order by s.SHIP_DT desc nulls last limit 1",
               (ltid,)) if ltid else None

    # 끊긴 단계의 문구 — '수집이 안 됐다' 가 아니라 **연결이 없다**. 둘은 다른 사실이다.
    cut = "단절"
    return {
        "project_no": lt["project_no"], "project_name": lt["project_name"],
        "lot_no": lt.get("product_lot_no"),
        "href": f"?lot={lt['product_lot_no']}" if lt.get("product_lot_no") else None,
        "steps": [
            {"n": 1, "table": "EST_PROJECTS", "key": "PROJECT_NO",
             "value": lt["project_no"], "ok": True},
            {"n": 2, "table": "EST_CAD_DRAWINGS", "key": "DRAWING_NO",
             "value": f"{draw['drawing_no']} rev.{_rev(draw['revision'])}" if draw else cut,
             "ok": bool(draw)},
            {"n": 3, "table": "EST_BOM_HEADERS", "key": "BOM_NO",
             "value": f"{bom['bom_no']} v{_rev(bom['bom_version'])}" if bom else cut,
             "ok": bool(bom)},
            {"n": 4, "table": "INV_MATERIAL_LOTS", "key": "LOT_NO",
             "value": f"{mlot['lot_no']} ({mlot['material'] or '—'})" if mlot else cut,
             "ok": bool(mlot)},
            {"n": 5, "table": "PRC_WORK_ORDERS", "key": "WORK_ORDER_NO",
             "value": f"{wo['work_order_no']} · {wo['order_status']}" if wo else cut,
             "ok": bool(wo)},
            {"n": 6, "table": "PRC_PERFORMANCES", "key": "—",
             "value": f"{int(perf['n'])} 건" if perf and perf["n"] else cut,
             "ok": bool(perf and perf["n"])},
            {"n": 7, "table": "SHP_LOT_TRACES", "key": "PRODUCT_LOT_NO",
             "value": lt.get("product_lot_no") or cut, "ok": bool(lt.get("product_lot_no"))},
            {"n": 8, "table": "SHP_INSPECTIONS", "key": "—",
             "value": f"{int(insp['n'])} 건 · 합격 {int(insp['ok'])}" if insp and insp["n"] else cut,
             "ok": bool(insp and insp["n"])},
            {"n": 9, "table": "SHP_SHIPMENTS", "key": "SHIPMENT_NO",
             "value": f"{ship['shipment_no']} · {dt(ship['ship_dt'])}" if ship else cut,
             "ok": bool(ship)},
        ],
    }


# ── 025 공정데이터 분석 ─────────────────────────────────────────────────
@router.get("/prc/025")
async def analysis(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-025")
    names = process_names()
    f = {k: _q(request, k) for k in ("process", "project", "group", "metric")}
    f.update(date_range(request))            # 분석 기간 시작·종료 — 잘못된 날짜는 422

    rows = conn.q(
        "with dwell as ("
        "  select h.PROCESS_CODE, avg(h.DWELL_HOUR) as avg_h, count(*) as hist_n "
        "  from PRC_PROCESS_HISTORIES h "
        "  join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "  join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "  where h.OUT_DT is not null "
        "    and (%(from)s = '' or h.IN_DT >= %(from)s::date) "
        "    and (%(to_excl)s = '' or h.IN_DT < %(to_excl)s::date) "
        "    and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "    and (%(group)s = '' or pj.PRODUCT_GROUP = %(group)s) "
        "  group by h.PROCESS_CODE), "
        # **실적도 같은 프로젝트 조건을 받는다**(D-217). 전에는 체류시간만 걸러지고 실적 수량은
        # 전사 합계가 나와, 프로젝트를 골라도 수량이 그대로였다 — 같은 표에 다른 모집단이 섞였다.
        "perf as ("
        "  select p.PROCESS_CODE, coalesce(sum(p.GOOD_QTY),0) as good, "
        "         coalesce(sum(p.DEFECT_QTY),0) as defect "
        "  from PRC_PERFORMANCES p "
        "  join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = p.WORK_ORDER_ID "
        "  join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "  where (%(from)s = '' or p.START_DT >= %(from)s::date) "
        "    and (%(to_excl)s = '' or p.START_DT < %(to_excl)s::date) "
        "    and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "    and (%(group)s = '' or pj.PRODUCT_GROUP = %(group)s) "
        "  group by p.PROCESS_CODE) "
        "select coalesce(d.PROCESS_CODE, p.PROCESS_CODE) as process_code, "
        "       d.avg_h, coalesce(p.good,0) as good, coalesce(p.defect,0) as defect "
        "from dwell d full outer join perf p on p.PROCESS_CODE = d.PROCESS_CODE "
        "where (%(process)s = '' or coalesce(d.PROCESS_CODE, p.PROCESS_CODE) = %(process)s) "
        "order by 1", f,
    )
    worst = max((float(r["avg_h"] or 0) for r in rows), default=0.0)
    bottleneck = next((names.get(r["process_code"], r["process_code"]) for r in rows
                       if worst and float(r["avg_h"] or 0) == worst), None)
    grid_rows = [[
        cell(i, num=True),
        cell(names.get(r["process_code"], r["process_code"])),
        cell(num(r["avg_h"], 2), num=True),
        cell(num(r["good"], 3), num=True),
        cell(num(r["defect"], 3), num=True),
        cell(num(kpimod.ratio_pct(r["defect"], float(r["good"] or 0) + float(r["defect"] or 0)), 3),
             num=True),
        cell("Y" if worst and float(r["avg_h"] or 0) == worst else "N"),
    ] for i, r in enumerate(rows, 1)]

    dev = conn.q1(
        "select count(*) as n from PRC_CONDITION_DEVIATIONS where OUT_OF_TOL_YN = 'Y'") or {"n": 0}
    q = kpimod.quality()

    return render(request, "prc/025.html", **ctx(
        request, screen, td3,
        wired={"분석 기간": range_wired("분석 기간", f),
               "공정": {"name": "process", "value": f["process"],
                      "options": process_options(names)},
               "제품군": {"name": "group", "value": f["group"], "options": product_groups()},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=http.not_collected(COLLECT_DECISION),
        cards=[
            {"label": "분석 공정", "value": f"{len(rows):,} 건"},
            {"label": "병목 공정",
             "value": bottleneck or http.not_collected(COLLECT_DECISION),
             "sub": f"평균 체류 {num(worst, 2)} h" if bottleneck else "",
             "off": not bottleneck},
            {"label": "허용범위 초과 편차", "value": f"{int(dev['n'] or 0):,} 건",
             "sub": http.undetermined(STD_COND_DECISION) if not dev["n"] else ""},
            {"label": "출하 검사", "value": f"{q.inspect_cnt:,} 건",
             "sub": f"합격 {q.pass_cnt:,}건"},
        ],
        notes=[{"title": "정확도 한계",
                "body": "공정별 체류시간·병목은 공정 실적 입력 성실도에 좌우된다"
                        "(TD3 025 제약사항). 자동 수집은 레이저커팅 1공정뿐이다 (D-06)."}],
    ))
