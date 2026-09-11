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

from fastapi import APIRouter, Form, Request

from ..templating import render
from ..util import codes, http
from .dsh import (COLLECT_DECISION, STD_COND_DECISION, anchor, cell, ctx, dt, guard,
                  collection_badges, lot_cell, mock, num, process_names, project_cell)

router = APIRouter()
SCREENS = ("MES-TD3-021", "MES-TD3-022", "MES-TD3-023", "MES-TD3-024", "MES-TD3-025")

AUTO_PROCESS = "P40"              # 가공(레이저커팅) — 자동 수집 대상 1공정 (D-06)
OUTSOURCED = ("P30", "P60")       # 소재가공·버핑 — 발주·반출·반입 상태 (D-41)
METHOD_AUTO, METHOD_MANUAL = "자동(PLC)", "수동(POP·패드)"
PAGE = 50


def _q(request: Request, key: str) -> str:
    return (request.query_params.get(key) or "").strip()


# ── 021 공정실적관리 ────────────────────────────────────────────────────
@router.get("/prc/021")
async def performances(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-021")
    names = process_names()
    f = {k: _q(request, k) for k in ("date", "wo", "process", "lot", "method")}

    rows = conn.q(
        "select p.PERF_ID, w.WORK_ORDER_NO, p.PROCESS_CODE, p.START_DT, p.END_DT, "
        "p.GOOD_QTY, p.DEFECT_QTY, p.COLLECT_METHOD, lt.PRODUCT_LOT_NO, pj.PROJECT_NO "
        "from PRC_PERFORMANCES p "
        "join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = p.WORK_ORDER_ID "
        "left join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = p.LOT_TRACE_ID "
        "left join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "where (%(date)s = '' or to_char(p.START_DT,'YYYY-MM-DD') = %(date)s) "
        "  and (%(wo)s = '' or w.WORK_ORDER_NO ilike '%%' || %(wo)s || '%%') "
        "  and (%(process)s = '' or p.PROCESS_CODE = %(process)s) "
        "  and (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(method)s = '' or p.COLLECT_METHOD ilike '%%' || %(method)s || '%%') "
        "order by p.START_DT desc limit %(lim)s", {**f, "lim": PAGE},
    )
    agg = conn.q1(
        "select count(*) as n, "
        "count(*) filter (where COLLECT_METHOD = %s) as auto_n, "
        "coalesce(sum(GOOD_QTY),0) as good, coalesce(sum(DEFECT_QTY),0) as defect "
        "from PRC_PERFORMANCES", (METHOD_AUTO,),
    ) or {}

    grid_rows = [[
        cell(i, num=True),
        cell(r["work_order_no"]),
        cell(names.get(r["process_code"], r["process_code"])),
        cell(dt(r["start_dt"])),
        cell(num(r["good_qty"], 3), num=True),
        cell(num(r["defect_qty"], 3), num=True),
        cell(r["collect_method"]),
    ] for i, r in enumerate(rows, 1)]

    open_orders = conn.q(
        "select w.WORK_ORDER_ID, w.WORK_ORDER_NO, w.PROCESS_CODE, pj.PROJECT_NO "
        "from PRC_WORK_ORDERS w join EST_PROJECTS pj on pj.PROJECT_ID = w.PROJECT_ID "
        "where w.OUTSOURCE_YN = 'N' order by w.WORK_ORDER_NO limit 200"
    )

    return render(request, "prc/021.html", **ctx(
        request, screen, td3,
        wired={"작업일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD"},
               "작업지시번호": {"name": "wo", "value": f["wo"], "hint": "WO-"},
               "공정": {"name": "process", "value": f["process"], "hint": "공정 코드"},
               "제품 LOT": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "수집 방식": {"name": "method", "value": f["method"], "hint": "자동/수동"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
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


@router.post("/prc/021")
async def create_performance(
    request: Request,
    work_order_id: int = Form(...),
    process_code: str = Form(...),
    start_dt: str = Form(...),
    good_qty: float = Form(...),
    defect_qty: float = Form(0),
    defect_type: str = Form(""),
    collect_method: str = Form(METHOD_MANUAL),
):
    """공정 실적 등록. 등록 권한 없으면 **403**, 계약 위반은 **422**."""
    import conn
    screen, td3 = guard(request, "MES-TD3-021", write=True)

    codes.require_code("PRC_PERFORMANCES", "PROCESS_CODE", process_code)
    codes.require_code("PRC_PERFORMANCES", "DEFECT_TYPE", defect_type or None, allow_empty=True)

    # **자동 수집인 척하지 않는다** — 레이저커팅 외 공정에 자동(PLC)을 붙이면 422 다(D-06).
    if collect_method == METHOD_AUTO and process_code != AUTO_PROCESS:
        raise http.fail("validation",
                        f"자동 수집은 레이저커팅 1공정({AUTO_PROCESS})뿐이다 — "
                        f"{process_code} 실적은 수동 입력이다 (D-06)")
    if process_code in OUTSOURCED:
        raise http.fail("validation",
                        "외주 2공정(소재가공·버핑)은 실적이 아니라 발주·반출·반입 상태 관리다 (D-41)")
    if good_qty < 0 or defect_qty < 0:
        raise http.fail("validation", "실적·불량 수량은 음수가 될 수 없다")

    wo = conn.q1(
        "select WORK_ORDER_ID, PROCESS_CODE from PRC_WORK_ORDERS where WORK_ORDER_ID = %s",
        (work_order_id,),
    )
    if wo is None:
        raise http.fail("validation", f"작업지시 {work_order_id} 가 없다")
    if wo["process_code"] != process_code:
        raise http.fail("validation",
                        f"작업지시 공정({wo['process_code']}) 과 실적 공정({process_code}) 이 다르다")

    lot = conn.q1(
        "select LOT_TRACE_ID from SHP_LOT_TRACES where WORK_ORDER_ID = %s", (work_order_id,))
    conn.x(
        "insert into PRC_PERFORMANCES (WORK_ORDER_ID, LOT_TRACE_ID, PROCESS_CODE, START_DT, "
        "GOOD_QTY, DEFECT_QTY, DEFECT_TYPE, COLLECT_METHOD, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s, now())",
        (work_order_id, int(lot["lot_trace_id"]) if lot else None, process_code, start_dt,
         good_qty, defect_qty, defect_type or None, collect_method),
    )
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/prc/021", status_code=303)


# ── 022 공정 데이터 모니터링 ────────────────────────────────────────────
@router.get("/prc/022")
async def signals(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-022")
    f = {k: _q(request, k) for k in ("equip", "from", "status", "alarm")}

    rows = conn.q(
        "select s.SIGNAL_ID, s.EQUIP_CODE, c.CODE_NAME, s.COLLECT_DT, s.RUN_STATUS, "
        "s.SPEED_VALUE, s.PRESSURE_VALUE, s.CURRENT_VALUE, s.TEMP_VALUE, s.ALARM_CODE "
        "from PRC_EQUIP_SIGNALS s "
        "left join BAS_COMMON_CODES c on c.CODE_GROUP = '설비' and c.CODE_VALUE = s.EQUIP_CODE "
        "where (%(equip)s = '' or s.EQUIP_CODE = %(equip)s) "
        "  and (%(from)s = '' or s.COLLECT_DT >= %(from)s::timestamp) "
        "  and (%(status)s = '' or s.RUN_STATUS = %(status)s) "
        "  and (%(alarm)s = '' or (%(alarm)s = 'Y') = (s.ALARM_CODE is not null)) "
        "order by s.COLLECT_DT desc limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
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
               "수집 기간": {"name": "from", "value": f["from"], "hint": "YYYY-MM-DD 이후"},
               "가동 상태": {"name": "status", "value": f["status"], "hint": "가동/정지/대기/알람"},
               "알람 여부": {"name": "alarm", "value": f["alarm"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
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

    rows = conn.q(
        "select s.STD_COND_ID, s.PROCESS_CODE, s.COND_ITEM, s.STD_VALUE, s.TOL_MIN, s.TOL_MAX, "
        "s.UOM, s.USE_YN, "
        "(select count(*) from PRC_CONDITION_DEVIATIONS d where d.STD_COND_ID = s.STD_COND_ID "
        " and d.OUT_OF_TOL_YN = 'Y') as out_n "
        "from PRC_STD_CONDITIONS s "
        "where (%(process)s = '' or s.PROCESS_CODE = %(process)s) "
        "  and (%(item)s = '' or s.COND_ITEM ilike '%%' || %(item)s || '%%') "
        "  and (%(use)s = '' or s.USE_YN = %(use)s) "
        "  and (%(dev)s = '' or (%(dev)s = 'Y') = (exists (select 1 from PRC_CONDITION_DEVIATIONS d "
        "        where d.STD_COND_ID = s.STD_COND_ID and d.OUT_OF_TOL_YN = 'Y'))) "
        "order by s.PROCESS_CODE, s.COND_ITEM limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
        cell(names.get(r["process_code"], r["process_code"])),
        cell(r["cond_item"]),
        cell(num(r["std_value"], 4), num=True),
        cell(num(r["tol_min"], 4), num=True),
        cell(num(r["tol_max"], 4), num=True),
        cell(r["uom"] or "—"),
    ] for i, r in enumerate(rows, 1)]

    act = conn.q1("select count(*) as n from PRC_ACTUAL_CONDITIONS") or {"n": 0}
    dev = conn.q1(
        "select count(*) as n, count(*) filter (where OUT_OF_TOL_YN = 'Y') as out_n "
        "from PRC_CONDITION_DEVIATIONS") or {"n": 0, "out_n": 0}

    return render(request, "prc/023.html", **ctx(
        request, screen, td3,
        wired={"공정": {"name": "process", "value": f["process"], "hint": "공정 코드"},
               "조건 항목": {"name": "item", "value": f["item"]},
               "사용여부": {"name": "use", "value": f["use"], "hint": "Y / N"},
               "편차 초과 여부": {"name": "dev", "value": f["dev"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        # 표준값이 **없는 것**이지 수집이 안 된 것이 아니다 → '미확정' 이 맞다.
        empty_note=f"{http.undetermined(STD_COND_DECISION)} — "
                   "표준 작업 조건 초기 정의는 도입기업이 제공해야 한다 (TD3 023 제약사항)",
        cards=[
            {"label": "표준 조건", "value": f"{len(rows):,} 건"},
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
    f = {k: _q(request, k) for k in ("lot", "project", "process", "from", "status")}

    rows = conn.q(
        "select h.PRC_HIST_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, h.PROCESS_CODE, h.PROCESS_SEQ, "
        "h.IN_DT, h.OUT_DT, h.DWELL_HOUR, h.HIST_STATUS, h.OUTSOURCE_STEP "
        "from PRC_PROCESS_HISTORIES h "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(process)s = '' or h.PROCESS_CODE = %(process)s) "
        "  and (%(from)s = '' or h.IN_DT >= %(from)s::timestamp) "
        "  and (%(status)s = '' or h.HIST_STATUS = %(status)s) "
        "order by lt.PRODUCT_LOT_NO, h.PROCESS_SEQ limit %(lim)s", {**f, "lim": 200},
    )
    grid_rows = [[
        cell(i, num=True),
        lot_cell(r["product_lot_no"]),
        cell(names.get(r["process_code"], r["process_code"])
             + (f" · {r['outsource_step']}" if r["outsource_step"] else "")),
        cell(r["process_seq"], num=True),
        cell(dt(r["in_dt"])),
        cell(dt(r["out_dt"])),
        cell(num(r["dwell_hour"], 2), num=True),
    ] for i, r in enumerate(rows, 1)]

    broken = [r for r in rows if r["hist_status"] != "정상"]
    thread = _thread(f["lot"], f["project"]) if (f["lot"] or f["project"]) else None

    return render(request, "prc/024.html", **ctx(
        request, screen, td3,
        wired={"제품 LOT 번호": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"], "hint": "프로젝트번호"},
               "공정": {"name": "process", "value": f["process"], "hint": "공정 코드"},
               "기간": {"name": "from", "value": f["from"], "hint": "YYYY-MM-DD 이후"},
               "이력 상태": {"name": "status", "value": f["status"], "hint": "정상 / 단절"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=(f"{http.not_collected(COLLECT_DECISION)} — 해당 조건의 공정 이력이 없다"),
        cards=[
            {"label": "이력 건수", "value": f"{len(rows):,} 건"},
            {"label": "단절 구간", "value": f"{len(broken):,} 건",
             "sub": "외주 공정 실적 회신 전이면 이력이 단절된다 (D-41)"},
        ],
        thread=thread,
        badges=[{"cls": "notice",
                 "text": "최상위 조회 축은 프로젝트(수주)번호·도면번호다. LOT 는 하위 식별자다"}],
        notes=[{"title": "디지털 스레드 (G-08)",
                "body": "EST_PROJECTS → EST_CAD_DRAWINGS → EST_BOM_HEADERS → INV_MATERIAL_LOTS → "
                        "PRC_WORK_ORDERS → PRC_PERFORMANCES → SHP_LOT_TRACES → SHP_INSPECTIONS → "
                        "SHP_SHIPMENTS. 어느 화면에서든 LOT·프로젝트번호를 누르면 이 화면으로 온다."}],
    ))


def _thread(lot_no: str, project_no: str) -> dict[str, Any] | None:
    """G-08 사슬 9단계를 **끊긴 곳까지 그대로** 보여 준다. 없는 단계를 채우지 않는다."""
    import conn
    lt = None
    if lot_no:
        lt = conn.q1(
            "select lt.*, pj.PROJECT_NO, pj.PROJECT_NAME, pj.PROJECT_ID as pid "
            "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
            "where lt.PRODUCT_LOT_NO = %s", (lot_no,))
    if lt is None and project_no:
        lt = conn.q1(
            "select lt.*, pj.PROJECT_NO, pj.PROJECT_NAME, pj.PROJECT_ID as pid "
            "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
            "where pj.PROJECT_NO = %s order by lt.PRODUCT_LOT_NO limit 1", (project_no,))
    if lt is None:
        pj = conn.q1("select PROJECT_NO, PROJECT_NAME, PROJECT_ID from EST_PROJECTS "
                     "where PROJECT_NO = %s", (project_no,)) if project_no else None
        if pj is None:
            return None
        lt = {"pid": pj["project_id"], "project_no": pj["project_no"],
              "project_name": pj["project_name"], "lot_trace_id": None,
              "product_lot_no": None, "bom_id": None, "material_lot_id": None}

    pid, ltid = lt["pid"], lt.get("lot_trace_id")
    one = lambda sql, p: conn.q1(sql, p)                                        # noqa: E731
    draw = one("select DRAWING_NO, REVISION from EST_CAD_DRAWINGS where PROJECT_ID = %s "
               "order by DRAWING_ID limit 1", (pid,))
    bom = one("select BOM_NO, BOM_VERSION from EST_BOM_HEADERS where PROJECT_ID = %s "
              "order by BOM_ID limit 1", (pid,))
    mlot = one("select LOT_NO, MATERIAL from INV_MATERIAL_LOTS where LOT_ID = %s",
               (lt.get("material_lot_id"),)) if lt.get("material_lot_id") else None
    wo = one("select count(*) as n from PRC_WORK_ORDERS where PROJECT_ID = %s", (pid,))
    perf = one("select count(*) as n from PRC_PERFORMANCES where LOT_TRACE_ID = %s",
               (ltid,)) if ltid else None
    insp = one("select count(*) as n, count(*) filter (where JUDGE_RESULT = '합격') as ok "
               "from SHP_INSPECTIONS where LOT_TRACE_ID = %s", (ltid,)) if ltid else None
    ship = one("select s.SHIPMENT_NO, s.SHIP_DT from SHP_SHIPMENT_ITEMS i "
               "join SHP_SHIPMENTS s on s.SHIPMENT_ID = i.SHIPMENT_ID "
               "where i.LOT_TRACE_ID = %s order by s.SHIP_DT desc limit 1",
               (ltid,)) if ltid else None

    miss = http.not_collected(COLLECT_DECISION)
    return {
        "project_no": lt["project_no"], "project_name": lt["project_name"],
        "lot_no": lt.get("product_lot_no"),
        "steps": [
            {"n": 1, "table": "EST_PROJECTS", "key": "PROJECT_NO",
             "value": lt["project_no"], "ok": True},
            {"n": 2, "table": "EST_CAD_DRAWINGS", "key": "DRAWING_NO",
             "value": f"{draw['drawing_no']} rev.{draw['revision']}" if draw else miss,
             "ok": bool(draw)},
            {"n": 3, "table": "EST_BOM_HEADERS", "key": "BOM_NO",
             "value": f"{bom['bom_no']} v{bom['bom_version']}" if bom else miss, "ok": bool(bom)},
            {"n": 4, "table": "INV_MATERIAL_LOTS", "key": "LOT_NO",
             "value": f"{mlot['lot_no']} ({mlot['material']})" if mlot else miss,
             "ok": bool(mlot)},
            {"n": 5, "table": "PRC_WORK_ORDERS", "key": "WORK_ORDER_NO",
             "value": f"{int(wo['n'])} 건" if wo and wo["n"] else miss,
             "ok": bool(wo and wo["n"])},
            {"n": 6, "table": "PRC_PERFORMANCES", "key": "—",
             "value": f"{int(perf['n'])} 건" if perf and perf["n"] else miss,
             "ok": bool(perf and perf["n"])},
            {"n": 7, "table": "SHP_LOT_TRACES", "key": "PRODUCT_LOT_NO",
             "value": lt.get("product_lot_no") or miss, "ok": bool(lt.get("product_lot_no"))},
            {"n": 8, "table": "SHP_INSPECTIONS", "key": "—",
             "value": f"{int(insp['n'])} 건 · 합격 {int(insp['ok'])}" if insp and insp["n"] else miss,
             "ok": bool(insp and insp["n"])},
            {"n": 9, "table": "SHP_SHIPMENTS", "key": "SHIPMENT_NO",
             "value": f"{ship['shipment_no']} · {dt(ship['ship_dt'])}" if ship else miss,
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
    f = {k: _q(request, k) for k in ("from", "process", "project")}

    rows = conn.q(
        "with dwell as ("
        "  select h.PROCESS_CODE, avg(h.DWELL_HOUR) as avg_h, count(*) as hist_n "
        "  from PRC_PROCESS_HISTORIES h "
        "  join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = h.LOT_TRACE_ID "
        "  join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "  where h.OUT_DT is not null "
        "    and (%(from)s = '' or h.IN_DT >= %(from)s::timestamp) "
        "    and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  group by h.PROCESS_CODE), "
        "perf as ("
        "  select p.PROCESS_CODE, coalesce(sum(p.GOOD_QTY),0) as good, "
        "         coalesce(sum(p.DEFECT_QTY),0) as defect "
        "  from PRC_PERFORMANCES p "
        "  where (%(from)s = '' or p.START_DT >= %(from)s::timestamp) "
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
        wired={"분석 기간": {"name": "from", "value": f["from"], "hint": "YYYY-MM-DD 이후"},
               "공정": {"name": "process", "value": f["process"], "hint": "공정 코드"},
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
