"""출하물류관리 016~019 (개발2).

**출하 통제 (goal.md 개발2 · G-24)**
  1. 검사 **합격 LOT 만** 출하 대상으로 고를 수 있다 — 아니면 **422**
  2. 출하 확정은 **승인 권한**이 있어야 한다(`rbac.can_approve`) — 없으면 **403**
  3. 출하 확정 시각(`SHP_SHIPMENTS.SHIP_DT`)을 기록해야 `LEADTIME_O2D` 가 나온다
  4. 승인자(`APPROVER_ID`)를 남긴다 — 승인 이력 없는 확정은 결함이다

**`/shp/020` 출하 AI Agent 는 개발3(`routers/agt.py`) 몫이다. 여기서 만들지 않는다.**
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..templating import render
from ..util import codes, http
from .dsh import (CLAIM_DECISION, COLLECT_DECISION, anchor, cell, ctx, dt, guard, lot_cell,
                  mock, num, process_names, project_cell)

router = APIRouter()
SCREENS = ("MES-TD3-016", "MES-TD3-017", "MES-TD3-018", "MES-TD3-019")

PASS = "합격"
PAGE = 50
MAPPING_TARGET = 85.0        # LOT 기반 데이터 매핑 성공률 ≥ 85% (사업계획서 2.7.4 · D-23)


def _q(request: Request, key: str) -> str:
    return (request.query_params.get(key) or "").strip()


def _actor(request: Request) -> int | None:
    """승인자 ID. 세션이 있으면 세션 사용자, 없으면 역할 대표 계정(D-40 개발용 역할 전환)."""
    import conn
    sess = getattr(request.state, "session", None)
    if sess is not None:
        return sess.user_id
    role = getattr(request.state, "role_code", "") or ""
    row = conn.q1(
        "select u.USER_ID from SYS_USERS u "
        "join SYS_ROLE_PERMISSIONS r on r.ROLE_PERM_ID = u.ROLE_ID "
        "where r.ROLE_CODE = %s order by u.USER_ID limit 1", (role,),
    )
    return int(row["user_id"]) if row else None


def _lot_passed(lot_trace_id: int) -> tuple[bool, str]:
    """검사 합격 여부. 검사 자체가 없으면 **합격이 아니다** — 없는 것을 통과로 보지 않는다."""
    import conn
    row = conn.q1(
        "select count(*) as n, count(*) filter (where JUDGE_RESULT = %s) as ok "
        "from SHP_INSPECTIONS where LOT_TRACE_ID = %s", (PASS, lot_trace_id),
    ) or {"n": 0, "ok": 0}
    n, ok = int(row["n"] or 0), int(row["ok"] or 0)
    if n == 0:
        return False, "출하검사 결과가 없다"
    if ok != n:
        return False, f"불합격 판정 {n - ok}건"
    return True, ""


# ── 016 출하관리 ────────────────────────────────────────────────────────
@router.get("/shp/016")
async def shipments(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-016")
    f = {k: _q(request, k) for k in ("date", "no", "customer", "project", "status", "otd")}

    rows = conn.q(
        "select s.SHIPMENT_ID, s.SHIPMENT_NO, pj.PROJECT_NO, s.CUSTOMER_CODE, "
        "coalesce(c.CODE_NAME, s.CUSTOMER_CODE) as customer_name, s.SHIP_DT, s.DUE_DT, "
        "s.SHIP_STATUS, s.OTD_YN, s.ERP_SYNC_STATUS, s.APPROVER_ID "
        "from SHP_SHIPMENTS s "
        "join EST_PROJECTS pj on pj.PROJECT_ID = s.PROJECT_ID "
        "left join BAS_COMMON_CODES c on c.CODE_GROUP = '고객사' and c.CODE_VALUE = s.CUSTOMER_CODE "
        "where (%(date)s = '' or to_char(s.SHIP_DT,'YYYY-MM-DD') = %(date)s) "
        "  and (%(no)s = '' or s.SHIPMENT_NO ilike '%%' || %(no)s || '%%') "
        "  and (%(customer)s = '' or s.CUSTOMER_CODE ilike '%%' || %(customer)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(status)s = '' or s.SHIP_STATUS = %(status)s) "
        "  and (%(otd)s = '' or s.OTD_YN = %(otd)s) "
        "order by coalesce(s.SHIP_DT, s.CREATED_DT) desc limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
        cell(r["shipment_no"]),
        project_cell(r["project_no"]),
        cell(r["customer_name"]),
        cell(dt(r["ship_dt"])),
        cell(r["due_dt"] or "—"),
        cell(r["ship_status"] + (" · 승인" if r["approver_id"] else "")),
    ] for i, r in enumerate(rows, 1)]

    # 출하 대상 후보 — **검사 합격 LOT 만** 보여 준다(G-24). 여기서 이미 걸러야 422 가 예외가 된다.
    candidates = conn.q(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT "
        "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where not exists (select 1 from SHP_SHIPMENT_ITEMS i where i.LOT_TRACE_ID = lt.LOT_TRACE_ID) "
        "  and exists (select 1 from SHP_INSPECTIONS x where x.LOT_TRACE_ID = lt.LOT_TRACE_ID) "
        "  and not exists (select 1 from SHP_INSPECTIONS x where x.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        "                  and x.JUDGE_RESULT <> %s) order by lt.PRODUCT_LOT_NO limit 50", (PASS,),
    )
    waiting = conn.q(
        "select s.SHIPMENT_ID, s.SHIPMENT_NO, pj.PROJECT_NO from SHP_SHIPMENTS s "
        "join EST_PROJECTS pj on pj.PROJECT_ID = s.PROJECT_ID "
        "where s.SHIP_DT is null order by s.SHIPMENT_NO limit 50"
    )
    agg = conn.q1(
        "select count(*) as n, count(*) filter (where SHIP_DT is not null) as done, "
        "count(*) filter (where APPROVER_ID is not null) as approved from SHP_SHIPMENTS") or {}

    from .. import rbac
    role = getattr(request.state, "role_code", "") or ""
    return render(request, "shp/016.html", **ctx(
        request, screen, td3,
        wired={"출하일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD"},
               "출하번호": {"name": "no", "value": f["no"], "hint": "SH-"},
               "고객사": {"name": "customer", "value": f["customer"], "hint": "고객사 코드"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]},
               "출하 상태": {"name": "status", "value": f["status"], "hint": "예정/승인대기/완료/지연"},
               "납기 준수": {"name": "otd", "value": f["otd"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=http.not_collected("D-07"),
        cards=[
            {"label": "출하 건수", "value": f"{int(agg.get('n') or 0):,} 건"},
            {"label": "출하 확정", "value": f"{int(agg.get('done') or 0):,} 건",
             "sub": "SHIP_DT 기록 = LEADTIME_O2D 종료 시각"},
            {"label": "승인 기록", "value": f"{int(agg.get('approved') or 0):,} 건"},
            {"label": "출하 대상 LOT", "value": f"{len(candidates):,} 건", "sub": "검사 합격 LOT 만"},
        ],
        candidates=candidates, waiting=waiting,
        can_approve=rbac.can_approve(role, screen.area),
        badges=[{"cls": "notice",
                 "text": "검사 합격 LOT 만 출하 대상이다(422) · 출하 확정은 승인 권한이 필요하다(403)"}],
        notes=[{"title": "ERP 연계",
                "body": "ERP(이카운트) 보유 여부가 사업계획서 안에서 상충한다(D-07). Excel 적재를 "
                        "정식 입력으로 두고 IF_ERP_SHIPMENTS 기록까지가 이번 범위다."}],
    ))


@router.post("/shp/016")
async def create_shipment(request: Request, lot_trace_id: int = Form(...),
                          plan_dt: str = Form("")):
    """출하 등록. **검사 합격 LOT 만** 선택할 수 있다 — 아니면 422."""
    import conn
    screen, td3 = guard(request, "MES-TD3-016", write=True)

    lot = conn.q1(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_ID, pj.PROJECT_NO, "
        "pj.CUSTOMER_CODE, pj.PRODUCT_GROUP, pj.DUE_DT "
        "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where lt.LOT_TRACE_ID = %s", (lot_trace_id,),
    )
    if lot is None:
        raise http.fail("validation", f"제품 LOT {lot_trace_id} 가 없다")

    ok, why = _lot_passed(lot_trace_id)
    if not ok:
        raise http.fail("validation",
                        f"{lot['product_lot_no']} 는 출하 대상이 아니다 — {why}. "
                        "검사 합격 LOT 만 출하할 수 있다 (G-24)")
    if conn.q1("select 1 as x from SHP_SHIPMENT_ITEMS where LOT_TRACE_ID = %s", (lot_trace_id,)):
        raise http.fail("validation", f"{lot['product_lot_no']} 는 이미 출하 내역에 있다")

    codes.require_code("SHP_SHIPMENTS", "CUSTOMER_CODE", lot["customer_code"])
    codes.require_code("SHP_SHIPMENT_ITEMS", "ITEM_CODE", lot["product_group"])

    a = anchor()
    seq = conn.q1("select count(*) + 1 as n from SHP_SHIPMENTS")["n"]
    no = f"SH-{a.year}-{int(seq):04d}"
    pack = conn.q1(
        "select max(OUT_DT) as packed from PRC_PROCESS_HISTORIES "
        "where LOT_TRACE_ID = %s and PROCESS_CODE = 'P90'", (lot_trace_id,),
    ) or {}
    insp = conn.q1(
        "select INSPECT_ID from SHP_INSPECTIONS where LOT_TRACE_ID = %s and JUDGE_RESULT = %s "
        "order by INSPECT_DT desc limit 1", (lot_trace_id, PASS),
    )
    with conn.tx() as cur:
        cur.execute(
            "insert into SHP_SHIPMENTS (SHIPMENT_NO, PROJECT_ID, CUSTOMER_CODE, PLAN_DT, DUE_DT, "
            "SHIP_STATUS, ERP_SYNC_STATUS, CREATED_BY, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s, now()) returning SHIPMENT_ID",
            (no, lot["project_id"], lot["customer_code"], plan_dt or None, lot["due_dt"],
             "승인대기", "미전송", _actor(request)),
        )
        sid = cur.fetchone()["shipment_id"]
        cur.execute(
            "insert into SHP_SHIPMENT_ITEMS (SHIPMENT_ID, LOT_TRACE_ID, ITEM_CODE, SHIP_QTY, "
            "PACKING_DT, INSPECT_ID, CREATED_DT) values (%s,%s,%s,%s,%s,%s, now())",
            (sid, lot_trace_id, lot["product_group"], 1, pack.get("packed"),
             int(insp["inspect_id"]) if insp else None),
        )
    return RedirectResponse("/shp/016", status_code=303)


@router.post("/shp/016/approve")
async def approve_shipment(request: Request, shipment_id: int = Form(...)):
    """출하 확정. **승인 권한이 없으면 403** 이고, 확정 시각과 승인자를 남긴다(G-24)."""
    import conn
    screen, td3 = guard(request, "MES-TD3-016", approve=True)

    sh = conn.q1(
        "select SHIPMENT_ID, SHIPMENT_NO, SHIP_DT, DUE_DT from SHP_SHIPMENTS where SHIPMENT_ID = %s",
        (shipment_id,),
    )
    if sh is None:
        raise http.fail("validation", f"출하 {shipment_id} 가 없다")
    if sh["ship_dt"] is not None:
        raise http.fail("validation", f"{sh['shipment_no']} 는 이미 확정됐다")

    items = conn.q(
        "select i.LOT_TRACE_ID, lt.PRODUCT_LOT_NO from SHP_SHIPMENT_ITEMS i "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = i.LOT_TRACE_ID where i.SHIPMENT_ID = %s",
        (shipment_id,),
    )
    if not items:
        raise http.fail("validation", f"{sh['shipment_no']} 에 출하 품목이 없다")
    for it in items:
        ok, why = _lot_passed(int(it["lot_trace_id"]))
        if not ok:
            raise http.fail("validation",
                            f"{it['product_lot_no']}: {why} — 검사 합격 LOT 만 출하할 수 있다 (G-24)")

    a = anchor()          # 확정 시각은 시간 앵커 기준이다 (§10-3)
    otd = "Y" if (sh["due_dt"] is None or a.date() <= sh["due_dt"]) else "N"
    with conn.tx() as cur:
        cur.execute(
            "update SHP_SHIPMENTS set SHIP_DT = %s, APPROVER_ID = %s, SHIP_STATUS = '완료', "
            "OTD_YN = %s, UPDATED_DT = now() where SHIPMENT_ID = %s",
            (a, _actor(request), otd, shipment_id),
        )
        cur.execute(
            "update SHP_LOT_TRACES set TRACE_STATUS = '출하', UPDATED_DT = now() "
            "where LOT_TRACE_ID in (select LOT_TRACE_ID from SHP_SHIPMENT_ITEMS "
            "where SHIPMENT_ID = %s)", (shipment_id,),
        )
    return RedirectResponse("/shp/016", status_code=303)


# ── 017 LOT추적관리 ─────────────────────────────────────────────────────
@router.get("/shp/017")
async def lot_traces(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-017")
    names = process_names()
    f = {k: _q(request, k) for k in ("lot", "project", "process", "status", "from")}

    rows = conn.q(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, ml.LOT_NO as material_lot, "
        "lt.CURRENT_PROCESS, lt.TRACE_STATUS, lt.MAPPING_OK_YN "
        "from SHP_LOT_TRACES lt "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "left join INV_MATERIAL_LOTS ml on ml.LOT_ID = lt.MATERIAL_LOT_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(process)s = '' or lt.CURRENT_PROCESS = %(process)s) "
        "  and (%(status)s = '' or lt.TRACE_STATUS = %(status)s) "
        "  and (%(from)s = '' or lt.CREATED_DT >= %(from)s::timestamp) "
        "order by lt.PRODUCT_LOT_NO limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
        lot_cell(r["product_lot_no"]),
        project_cell(r["project_no"]),
        cell(r["material_lot"] or http.not_collected("D-26")),
        cell(names.get(r["current_process"], r["current_process"] or "—")),
        cell(r["trace_status"]),
        cell(r["mapping_ok_yn"]),
    ] for i, r in enumerate(rows, 1)]

    agg = conn.q1(
        "select count(*) as n, count(*) filter (where MAPPING_OK_YN = 'Y') as ok "
        "from SHP_LOT_TRACES") or {"n": 0, "ok": 0}
    rate = kpimod.ratio_pct(agg["ok"], agg["n"])

    return render(request, "shp/017.html", **ctx(
        request, screen, td3,
        wired={"제품 LOT 번호": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]},
               "현재 공정": {"name": "process", "value": f["process"], "hint": "공정 코드"},
               "추적 상태": {"name": "status", "value": f["status"], "hint": "생산중/검사/포장/출하"},
               "기간": {"name": "from", "value": f["from"], "hint": "YYYY-MM-DD 이후"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=http.not_collected(COLLECT_DECISION),
        cards=[
            {"label": "제품 LOT", "value": f"{int(agg['n'] or 0):,} 건"},
            {"label": "매핑 성공", "value": f"{int(agg['ok'] or 0):,} 건"},
            {"label": "매핑 성공률",
             "value": f"{rate:,.1f} %" if rate is not None else http.not_collected(COLLECT_DECISION),
             "sub": f"목표 {MAPPING_TARGET:.0f}% 이상 (사업계획서 2.7.4 · D-23)",
             "off": rate is None},
            {"label": "목표 달성",
             "value": ("달성" if rate >= MAPPING_TARGET else "미달") if rate is not None else "—",
             "off": rate is None},
        ],
        badges=[{"cls": "notice",
                 "text": "수주–CAD–BOM–생산–설비–품질–출하 디지털 스레드를 전제로 한다 (G-08)"}],
        notes=[{"title": "추적도",
                "body": "LOT·프로젝트번호를 누르면 024 공정이력조회에서 9단계 사슬을 그대로 본다."}],
    ))


# ── 018 검사결과관리 ────────────────────────────────────────────────────
@router.get("/shp/018")
async def inspections(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-018")
    f = {k: _q(request, k) for k in ("lot", "item", "judge", "date", "project")}

    rows = conn.q(
        "select ins.INSPECT_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, ins.INSPECT_ITEM, "
        "ins.MEASURED_VALUE, ins.UOM, ins.JUDGE_RESULT, ins.INSPECT_DT, ins.REPORT_NO, "
        "q.STANDARD_SPEC, q.SPEC_MIN, q.SPEC_MAX "
        "from SHP_INSPECTIONS ins "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = ins.LOT_TRACE_ID "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "left join BAS_QUALITY_STANDARDS q on q.QSTD_ID = ins.QSTD_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(item)s = '' or ins.INSPECT_ITEM ilike '%%' || %(item)s || '%%') "
        "  and (%(judge)s = '' or ins.JUDGE_RESULT = %(judge)s) "
        "  and (%(date)s = '' or to_char(ins.INSPECT_DT,'YYYY-MM-DD') = %(date)s) "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "order by ins.INSPECT_DT desc limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
        lot_cell(r["product_lot_no"]),
        cell(r["inspect_item"]),
        cell(num(r["measured_value"], 4) if r["measured_value"] is not None
             else http.not_collected("D-26"), num=True),
        cell(r["uom"] or "—"),
        cell(r["judge_result"]),
        cell(dt(r["inspect_dt"])),
    ] for i, r in enumerate(rows, 1)]

    q = kpimod.quality()
    std_n = conn.q1("select count(*) as n from BAS_QUALITY_STANDARDS") or {"n": 0}
    shippable = conn.q1(
        "select count(*) as n from SHP_LOT_TRACES lt where exists "
        "(select 1 from SHP_INSPECTIONS x where x.LOT_TRACE_ID = lt.LOT_TRACE_ID) and not exists "
        "(select 1 from SHP_INSPECTIONS x where x.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        " and x.JUDGE_RESULT <> %s)", (PASS,)) or {"n": 0}

    return render(request, "shp/018.html", **ctx(
        request, screen, td3,
        wired={"제품 LOT 번호": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "검사 항목": {"name": "item", "value": f["item"], "hint": "수압/기밀/진공"},
               "판정": {"name": "judge", "value": f["judge"], "hint": "합격 / 불합격"},
               "검사일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=(http.undetermined("D-26") if not int(std_n["n"] or 0)
                    else http.not_collected(COLLECT_DECISION)),
        cards=[
            {"label": "검사 건수", "value": f"{q.inspect_cnt:,} 건"},
            {"label": "합격", "value": f"{q.pass_cnt:,} 건"},
            {"label": "합격률",
             "value": f"{q.pass_rate:,.1f} %" if q.pass_rate is not None
                      else http.not_collected(COLLECT_DECISION),
             "off": q.pass_rate is None},
            {"label": "출하 가능 LOT", "value": f"{int(shippable['n'] or 0):,} 건",
             "sub": "합격 LOT 만 016 출하 대상이 된다"},
        ],
        badges=([{"cls": "undetermined",
                  "text": f"품질기준 0건 — {http.undetermined('D-26')} (기준정보관리 · 개발1)"}]
                if not int(std_n["n"] or 0) else
                [{"cls": "notice", "text": f"품질기준 {int(std_n['n'])}건 적용 (BAS_QUALITY_STANDARDS)"}]),
        notes=[{"title": "측정값",
                "body": "측정값은 도입기업 실측이다. 시드에 수치를 지어내지 않았다 — "
                        "입력 전에는 '미수집' 으로 그대로 둔다(§0.2)."}],
    ))


# ── 019 클레임분석 ──────────────────────────────────────────────────────
@router.get("/shp/019")
async def claims(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-019")
    names = process_names()
    f = {k: _q(request, k) for k in ("no", "customer", "from", "type", "status", "cause")}

    rows = conn.q(
        "select cl.CLAIM_ID, cl.CLAIM_NO, cl.CUSTOMER_CODE, "
        "coalesce(cc.CODE_NAME, cl.CUSTOMER_CODE) as customer_name, lt.PRODUCT_LOT_NO, "
        "cl.CLAIM_TYPE, cl.CLAIM_STATUS, cl.RECEIVED_DT, "
        "(select ca.CAUSE_PROCESS from SHP_CLAIM_CAUSES ca where ca.CLAIM_ID = cl.CLAIM_ID "
        " order by ca.CAUSE_ID limit 1) as cause_process "
        "from SHP_CLAIMS cl "
        "left join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = cl.LOT_TRACE_ID "
        "left join BAS_COMMON_CODES cc on cc.CODE_GROUP = '고객사' and cc.CODE_VALUE = cl.CUSTOMER_CODE "
        "where (%(no)s = '' or cl.CLAIM_NO ilike '%%' || %(no)s || '%%') "
        "  and (%(customer)s = '' or cl.CUSTOMER_CODE ilike '%%' || %(customer)s || '%%') "
        "  and (%(from)s = '' or cl.RECEIVED_DT >= %(from)s::timestamp) "
        "  and (%(type)s = '' or cl.CLAIM_TYPE = %(type)s) "
        "  and (%(status)s = '' or cl.CLAIM_STATUS = %(status)s) "
        "order by cl.RECEIVED_DT desc limit %(lim)s", {**f, "lim": PAGE},
    )
    grid_rows = [[
        cell(i, num=True),
        cell(r["claim_no"]),
        cell(r["customer_name"]),
        lot_cell(r["product_lot_no"]),
        cell(r["claim_type"] or http.undetermined("D-47")),
        cell(names.get(r["cause_process"], r["cause_process"] or "—")),
        cell(r["claim_status"]),
    ] for i, r in enumerate(rows, 1)]

    agg = conn.q1(
        "select count(*) as n, count(*) filter (where CLAIM_STATUS = '완료') as closed "
        "from SHP_CLAIMS") or {"n": 0, "closed": 0}
    repeat = conn.q1(
        "select count(*) as n from SHP_CLAIM_CAUSES where REPEAT_YN = 'Y'") or {"n": 0}

    return render(request, "shp/019.html", **ctx(
        request, screen, td3,
        wired={"클레임 번호": {"name": "no", "value": f["no"], "hint": "CL-"},
               "고객사": {"name": "customer", "value": f["customer"], "hint": "고객사 코드"},
               "접수 기간": {"name": "from", "value": f["from"], "hint": "YYYY-MM-DD 이후"},
               "클레임 유형": {"name": "type", "value": f["type"]},
               "처리 상태": {"name": "status", "value": f["status"], "hint": "접수/분석/조치/완료"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=f"{http.not_collected(CLAIM_DECISION)} — "
                   "클레임 이력이 문서로만 존재해 초기 데이터가 없다 (TD3 019 제약사항)",
        cards=[
            {"label": "클레임 건수", "value": f"{int(agg['n'] or 0):,} 건"},
            {"label": "처리 완료", "value": f"{int(agg['closed'] or 0):,} 건"},
            {"label": "반복 발생", "value": f"{int(repeat['n'] or 0):,} 건"},
            {"label": "원인분석 근거", "value": "LOT 역추적",
             "sub": "제품 LOT → 024 공정이력조회 (G-08)"},
        ],
        badges=[{"cls": "undetermined",
                 "text": "'클레임유형'·'고객사' 코드 그룹이 비어 있다 (D-47) — 화면 입력 마스터"}],
        notes=[{"title": "누적 전 신뢰도",
                "body": "현행 클레임 원인분석은 1~2일 이상 소요되고 이력이 문서로만 존재한다. "
                        "누적 데이터 확보 후 분석 신뢰도가 확보된다 (TD3 019 제약사항)."}],
    ))
