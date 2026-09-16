"""출하물류관리 016~019 (개발2).

**출하 통제 (goal.md 개발2 · G-24)**
  1. 검사 **합격 LOT 만** 출하 대상으로 고를 수 있다 — 아니면 **422**
  2. 출하 확정은 **승인 권한**이 있어야 한다(`rbac.can_approve`) — 없으면 **403**
  3. 출하 확정 시각(`SHP_SHIPMENTS.SHIP_DT`)을 기록해야 `LEADTIME_O2D` 가 나온다
  4. 승인자(`APPROVER_ID`)를 남긴다 — 승인 이력 없는 확정은 결함이다

**`/shp/020` 출하 AI Agent 는 개발3(`routers/agt.py`) 몫이다. 여기서 만들지 않는다.**
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..templating import render
from ..util import clock, codes, csrf, http
from .dsh import (CLAIM_DECISION, COLLECT_DECISION, HISTORY_PATH, LATE_SQL, anchor, cell,
                  count_total, ctx, date_range, day_prefix, dt, guard, lot_cell, mock, num,
                  page_of, pager, parse_opt_date, process_names, project_cell, range_wired,
                  safe_next, writing)

router = APIRouter()
SCREENS = ("MES-TD3-016", "MES-TD3-017", "MES-TD3-018", "MES-TD3-019")

PASS = "합격"
FAIL = "불합격"
PAGE = 50
MAPPING_TARGET = 85.0        # LOT 기반 데이터 매핑 성공률 ≥ 85% (사업계획서 2.7.4 · D-23)
INSPECT_GROUP = "검사구분"    # BAS_COMMON_CODES 코드 그룹 — 수압·기밀·진공 (공정 10단계 출하검사)
QSTD_DECISION = "D-26"       # 품질기준(BAS_QUALITY_STANDARDS) 미제공


def _q(request: Request, key: str) -> str:
    return (request.query_params.get(key) or "").strip()


def inspect_types() -> dict[str, str]:
    """출하검사 구분 **정본** — `BAS_COMMON_CODES('검사구분')`. 여기서 목록을 지어내지 않는다.

    공정 10단계의 출하검사는 **수압·기밀·진공** 세 가지고, 그 코드값은 기준정보관리(개발1)가
    등록한다. 코드가 비면 이 함수도 비고, 출하 게이트는 **통과가 아니라 차단**이 된다.
    """
    import conn
    rows = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = %s and USE_YN = 'Y' order by SORT_ORDER", (INSPECT_GROUP,),
    )
    return {r["code_value"]: r["code_name"] for r in rows}


def _lot_passed(lot_trace_id: int) -> tuple[bool, str]:
    """검사 합격 여부 — **수압·기밀·진공 세 가지가 전부 합격**이어야 한다(G-24).

    전에는 '불합격 행이 없으면 합격' 이었다. 그러면 수압 1건만 합격한 LOT 도 출하 대상이
    됐다 — 기밀·진공을 **하지 않은 것**과 **통과한 것**을 같게 본 것이다. 검사구분은
    `SHP_INSPECTIONS` 에 없고 `BAS_QUALITY_STANDARDS.INSPECT_TYPE` 에 있으므로 조인해서 센다.
    """
    import conn
    need = inspect_types()
    if not need:
        return False, (f"'{INSPECT_GROUP}' 코드 그룹이 비어 있다 — "
                       f"{http.undetermined(QSTD_DECISION)} (기준정보관리 · 개발1)")
    rows = conn.q(
        "select q.INSPECT_TYPE, "
        "count(*) as n, count(*) filter (where i.JUDGE_RESULT = %(pass)s) as ok "
        "from SHP_INSPECTIONS i join BAS_QUALITY_STANDARDS q on q.QSTD_ID = i.QSTD_ID "
        "where i.LOT_TRACE_ID = %(lot)s group by q.INSPECT_TYPE",
        {"pass": PASS, "lot": lot_trace_id},
    )
    if not rows:
        return False, "출하검사 결과가 없다"
    ok_types = {r["inspect_type"] for r in rows if int(r["ok"] or 0) > 0}
    bad = sum(int(r["n"] or 0) - int(r["ok"] or 0) for r in rows)
    if bad:
        return False, f"불합격 판정 {bad}건"
    missing = [f"{name}({code})" for code, name in need.items() if code not in ok_types]
    if missing:
        return False, ("출하검사 3종(" + " · ".join(need.values()) + ") 중 "
                       + " · ".join(missing) + " 합격 기록이 없다")
    return True, ""


def _passed_lot_sql(alias: str = "lt") -> str:
    """`_lot_passed` 와 **같은 판정**을 SQL 로. 후보 목록과 422 가 갈리면 안 된다."""
    return (
        f"(select count(distinct q.INSPECT_TYPE) from SHP_INSPECTIONS x "
        f" join BAS_QUALITY_STANDARDS q on q.QSTD_ID = x.QSTD_ID "
        f" where x.LOT_TRACE_ID = {alias}.LOT_TRACE_ID and x.JUDGE_RESULT = %(pass)s "
        f"   and q.INSPECT_TYPE = any(%(types)s)) = %(type_n)s "
        f"and not exists (select 1 from SHP_INSPECTIONS x "
        f" where x.LOT_TRACE_ID = {alias}.LOT_TRACE_ID and x.JUDGE_RESULT <> %(pass)s)"
    )


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


# ── 016 출하관리 ────────────────────────────────────────────────────────
@router.get("/shp/016")
async def shipments(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-016")
    f = {k: _q(request, k) for k in ("no", "customer", "project", "status", "otd")}
    f["date"] = day_prefix(request, "date")          # YYYY-MM-DD 또는 YYYY-MM · 그 외 422
    page, offset = page_of(request, PAGE)
    need = inspect_types()
    a = anchor()
    # '지연' 은 저장된 상태값이 아니라 **파생**이다(D-212) — 상태 조회에서만 따로 해석한다.
    late_only = f["status"] == "지연"
    params = {**f, "status": "" if late_only else f["status"], "today": a.date(),
              "pass": PASS, "types": list(need), "type_n": len(need)}

    core = (
        "from SHP_SHIPMENTS s "
        "join EST_PROJECTS pj on pj.PROJECT_ID = s.PROJECT_ID "
        "left join BAS_COMMON_CODES c on c.CODE_GROUP = '고객사' and c.CODE_VALUE = s.CUSTOMER_CODE "
        "where (%(date)s = '' or to_char(s.SHIP_DT,'YYYY-MM-DD') like %(date)s || '%%') "
        "  and (%(no)s = '' or s.SHIPMENT_NO ilike '%%' || %(no)s || '%%') "
        "  and (%(customer)s = '' or s.CUSTOMER_CODE ilike '%%' || %(customer)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(status)s = '' or s.SHIP_STATUS = %(status)s) "
        "  and (%(otd)s = '' or s.OTD_YN = %(otd)s) "
        + (f" and {LATE_SQL} " if late_only else " ")
    )
    total = count_total(core, params)
    rows = conn.q(
        "select s.SHIPMENT_ID, s.SHIPMENT_NO, pj.PROJECT_NO, s.CUSTOMER_CODE, "
        "coalesce(c.CODE_NAME, s.CUSTOMER_CODE) as customer_name, s.SHIP_DT, s.DUE_DT, "
        f"s.SHIP_STATUS, s.OTD_YN, s.ERP_SYNC_STATUS, s.APPROVER_ID, {LATE_SQL} as late_yn "
        + core +
        "order by coalesce(s.SHIP_DT, s.CREATED_DT) desc, s.SHIPMENT_ID desc "
        "limit %(lim)s offset %(off)s", {**params, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
        cell(r["shipment_no"]),
        project_cell(r["project_no"]),
        cell(r["customer_name"]),
        cell(dt(r["ship_dt"])),
        cell(r["due_dt"] or "—"),
        cell(r["ship_status"] + (" · 지연" if r["late_yn"] else "")
             + (" · 승인" if r["approver_id"] else "")),
    ] for i, r in enumerate(rows, 1)]

    # 출하 대상 후보 — **검사 3종 합격 LOT 만** 보여 준다(G-24). 여기서 이미 걸러야 422 가 예외가 된다.
    candidates = conn.q(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT, "
        "pj.CUSTOMER_CODE "
        "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where not exists (select 1 from SHP_SHIPMENT_ITEMS i where i.LOT_TRACE_ID = lt.LOT_TRACE_ID) "
        "  and " + _passed_lot_sql() + " order by lt.PRODUCT_LOT_NO limit 50",
        {"pass": PASS, "types": list(need), "type_n": len(need)},
    ) if need else []
    waiting = conn.q(
        "select s.SHIPMENT_ID, s.SHIPMENT_NO, pj.PROJECT_NO from SHP_SHIPMENTS s "
        "join EST_PROJECTS pj on pj.PROJECT_ID = s.PROJECT_ID "
        "where s.SHIP_DT is null order by s.SHIPMENT_NO limit 50"
    )
    agg = conn.q1(
        "select count(*) as n, count(*) filter (where SHIP_DT is not null) as done, "
        "count(*) filter (where APPROVER_ID is not null) as approved from SHP_SHIPMENTS") or {}
    customers = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = '고객사' and USE_YN = 'Y' order by SORT_ORDER, CODE_VALUE")

    from .. import rbac
    role = getattr(request.state, "role_code", "") or ""
    return render(request, "shp/016.html", **ctx(
        request, screen, td3,
        wired={"출하일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD 또는 YYYY-MM"},
               "출하번호": {"name": "no", "value": f["no"], "hint": "SH-"},
               "고객사": {"name": "customer", "value": f["customer"], "hint": "고객사 코드"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]},
               "출하 상태": {"name": "status", "value": f["status"],
                          "hint": "승인대기/완료 · 지연은 파생값"},
               "납기 준수": {"name": "otd", "value": f["otd"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        empty_note=http.not_collected("D-07"),
        cards=[
            {"label": "출하 건수", "value": f"{int(agg.get('n') or 0):,} 건"},
            {"label": "출하 확정", "value": f"{int(agg.get('done') or 0):,} 건",
             "sub": "SHIP_DT 기록 = LEADTIME_O2D 종료 시각"},
            {"label": "승인 기록", "value": f"{int(agg.get('approved') or 0):,} 건"},
            {"label": "출하 대상 LOT", "value": f"{len(candidates):,} 건",
             "sub": ("수압·기밀·진공 전부 합격한 LOT 만"
                     if need else f"{http.undetermined(QSTD_DECISION)} — 검사구분 코드 0건")},
        ],
        candidates=candidates, waiting=waiting, customers=customers,
        inspect_types=need,
        can_approve=rbac.can_approve(role, screen.area),
        back=request.url.path + (("?" + request.url.query) if request.url.query else ""),
        badges=[{"cls": "notice",
                 "text": "검사 합격 LOT 만 출하 대상이다(422) · 출하 확정은 승인 권한이 필요하다(403)"}],
        notes=[{"title": "ERP 연계",
                "body": "ERP(이카운트) 보유 여부가 사업계획서 안에서 상충한다(D-07). Excel 적재를 "
                        "정식 입력으로 두고 IF_ERP_SHIPMENTS 기록까지가 이번 범위다."}],
    ))


def _int_field(form: Any, name: str, *, minimum: int | None = None) -> int:
    """필수 정수 폼 값. 없거나 숫자가 아니면 **422** 다 (§2.5 validation)."""
    raw = (form.get(name) or "").strip()
    if not raw:
        raise http.fail("validation", f"필수값 누락: {name}")
    try:
        value = int(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 정수여야 한다: {raw!r}") from None
    if minimum is not None and value < minimum:
        raise http.fail("validation", f"{name} 은 {minimum} 이상이어야 한다: {value}")
    return value


def _num_field(form: Any, name: str) -> float:
    """필수 실수 폼 값 (측정값). 비어 있거나 숫자가 아니면 **422**."""
    raw = (form.get(name) or "").strip()
    if not raw:
        raise http.fail("validation", f"필수값 누락: {name}")
    try:
        return float(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 숫자여야 한다: {raw!r}") from None


@router.post("/shp/016")
async def create_shipment(request: Request):
    """출하 등록. **검사 합격 LOT 만** 선택할 수 있다 — 아니면 422.

    `Form(...)` 을 시그니처에 두지 않는다 — FastAPI 가 **핸들러 본문보다 먼저** 파싱해서
    토큰이 없는 요청이 403 이 아니라 422 를 받는다(실측). 검사 순서는 계약 §4.0 이다:
    **CSRF → 권한 → 입력값.**
    """
    import conn
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))  # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3 = guard(request, "MES-TD3-016", write=True)
    with writing(request, "MES-TD3-016", "등록"):
        return _create_shipment(request, form)


def _create_shipment(request: Request, form: Any):
    import conn
    lot_trace_id = _int_field(form, "lot_trace_id")
    customer_code = (form.get("customer_code") or "").strip()

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

    # 수량·예정일은 **출하 가능 판정 다음**에 본다 — 못 나가는 LOT 인데 "수량을 적어라" 고
    # 답하면 진짜 이유(검사 미합격)가 가려진다.
    ship_qty = _int_field(form, "ship_qty", minimum=1)
    # 출하 예정일은 **날짜다** — 문자열을 그대로 SQL 에 넘기면 잘못된 값이 500 이 된다(§2.5).
    plan_dt = parse_opt_date(form.get("plan_dt"), "출하 예정일")

    # 고객사는 화면에서 고르지만 **그 프로젝트의 고객사와 달라선 안 된다** — 다른 고객사로
    # 보내는 출하는 수주 사슬을 끊는다(G-08). 값이 없으면 프로젝트 고객사를 쓴다.
    if customer_code and customer_code != lot["customer_code"]:
        raise http.fail("validation",
                        f"{lot['project_no']} 의 고객사는 {lot['customer_code']} 다 — "
                        f"{customer_code} 로 출하할 수 없다")
    customer_code = customer_code or lot["customer_code"]
    codes.require_code("SHP_SHIPMENTS", "CUSTOMER_CODE", customer_code)
    # 출하 품목 코드는 **그 제품LOT 의 BOM 레벨1 품목**이다. 제품군 코드(PG10 등)는 '제품군'
    # 그룹이고 '품목' 그룹이 아니다 — 제품군을 품목 칸에 넣으면 D-32 검증에서 422 가 난다.
    # BOM 이 안 이어진 LOT(사슬 단절 표본)은 제품군으로 되돌리고, 그것도 없으면 422 로 드러낸다.
    bom_item = conn.q1(
        "select i.ITEM_CODE from SHP_LOT_TRACES lt "
        "join EST_BOM_ITEMS i on i.BOM_ID = lt.BOM_ID "
        "where lt.LOT_TRACE_ID = %s order by i.BOM_LEVEL, i.BOM_ITEM_ID limit 1", (lot_trace_id,))
    item_code = (bom_item or {}).get("item_code") or lot["product_group"]
    codes.require_code("SHP_SHIPMENT_ITEMS", "ITEM_CODE", item_code)

    # 출하번호 `SH-YYYY-NNNN` 의 **연도 자리는 채번 계열**이다 — 시드가 앵커 연도로 계열을
    # 열어 두었으므로 새 번호도 같은 계열에서 이어 받는다(§10-3 생성 기준일). 확정 **시각**은
    # 이것과 다른 물음이라 실시각을 쓴다(아래 `approve_shipment`).
    a = anchor()
    # **`count(*) + 1` 을 쓰지 않는다.** 시드가 연도별 일련번호로 채번해 두면 전체 건수와
    # 그 해의 마지막 번호가 어긋나 같은 번호를 두 번 만들고 UNIQUE 위반 500 이 난다(D-210 실측).
    # 그 해에 이미 발급된 **마지막 일련번호 + 1** 을 쓴다 — 형식은 개발1 공표 `SH-YYYY-NNNN`.
    seq = conn.q1(
        "select coalesce(max(substring(SHIPMENT_NO from '^SH-[0-9]{4}-([0-9]+)$')::int), 0) + 1 "
        "as n from SHP_SHIPMENTS where SHIPMENT_NO ~ %s", (f"^SH-{a.year}-[0-9]+$",))["n"]
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
            (no, lot["project_id"], customer_code, plan_dt, lot["due_dt"],
             "승인대기", "미전송", _actor(request)),
        )
        sid = cur.fetchone()["shipment_id"]
        cur.execute(
            "insert into SHP_SHIPMENT_ITEMS (SHIPMENT_ID, LOT_TRACE_ID, ITEM_CODE, SHIP_QTY, "
            "PACKING_DT, INSPECT_ID, CREATED_DT) values (%s,%s,%s,%s,%s,%s, now())",
            (sid, lot_trace_id, item_code, ship_qty, pack.get("packed"),
             int(insp["inspect_id"]) if insp else None),
        )
    # 저장 뒤에는 **보고 있던 조회 조건 그대로** 돌아간다 — 필터를 지우면 방금 넣은 행을 못 찾는다.
    return RedirectResponse(safe_next(request, form.get("back"), "/shp/016"), status_code=303)


@router.post("/shp/016/approve")
async def approve_shipment(request: Request):
    """출하 확정. **승인 권한이 없으면 403** 이고, 확정 시각과 승인자를 남긴다(G-24)."""
    import conn
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))  # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3 = guard(request, "MES-TD3-016", approve=True)
    with writing(request, "MES-TD3-016", "승인"):
        return _approve_shipment(request, form)


def _approve_shipment(request: Request, form: Any):
    import conn
    shipment_id = _int_field(form, "shipment_id")

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

    # **확정 시각은 실시각이다** (§10-3 · D-213). 앵커는 시드·시뮬레이터의 *생성 기준일*이지
    # "지금 몇 시인가" 가 아니다. 앵커를 찍으면 오늘 승인한 출하가 시드 기준일에 나간 것으로
    # 남아 `LEADTIME_O2D`(출하시각 − 수주확정시각)가 사실과 다른 값이 된다.
    now = clock.real_now()
    otd = "Y" if (sh["due_dt"] is None or now.date() <= sh["due_dt"]) else "N"
    with conn.tx() as cur:
        cur.execute(
            "update SHP_SHIPMENTS set SHIP_DT = %s, APPROVER_ID = %s, SHIP_STATUS = '완료', "
            "OTD_YN = %s, UPDATED_DT = now() where SHIPMENT_ID = %s",
            (now, _actor(request), otd, shipment_id),
        )
        cur.execute(
            "update SHP_LOT_TRACES set TRACE_STATUS = '출하', UPDATED_DT = now() "
            "where LOT_TRACE_ID in (select LOT_TRACE_ID from SHP_SHIPMENT_ITEMS "
            "where SHIPMENT_ID = %s)", (shipment_id,),
        )
    return RedirectResponse(safe_next(request, form.get("back"), "/shp/016"), status_code=303)


# ── 017 LOT추적관리 ─────────────────────────────────────────────────────
@router.get("/shp/017")
async def lot_traces(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-017")
    names = process_names()
    f = {k: _q(request, k) for k in ("lot", "project", "process", "status")}
    f.update(date_range(request))            # 기간 시작·종료 — 잘못된 날짜는 422 (§2.5)
    page, offset = page_of(request, PAGE)

    core = (
        "from SHP_LOT_TRACES lt "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "left join INV_MATERIAL_LOTS ml on ml.LOT_ID = lt.MATERIAL_LOT_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(process)s = '' or lt.CURRENT_PROCESS = %(process)s) "
        "  and (%(status)s = '' or lt.TRACE_STATUS = %(status)s) "
        "  and (%(from)s = '' or lt.CREATED_DT >= %(from)s::date) "
        "  and (%(to_excl)s = '' or lt.CREATED_DT < %(to_excl)s::date) "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, ml.LOT_NO as material_lot, "
        "lt.CURRENT_PROCESS, lt.TRACE_STATUS, lt.MAPPING_OK_YN "
        + core +
        "order by lt.PRODUCT_LOT_NO limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
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
               "현재 공정": {"name": "process", "value": f["process"],
                          "options": [(c, f"{n} ({c})") for c, n in names.items()]},
               "추적 상태": {"name": "status", "value": f["status"], "hint": "생산중/검사/포장/출하"},
               "기간": range_wired("기간", f)},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
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
    f = {k: _q(request, k) for k in ("lot", "item", "judge", "project", "inspector")}
    f["date"] = day_prefix(request, "date")          # YYYY-MM-DD 또는 YYYY-MM · 그 외 422
    page, offset = page_of(request, PAGE)

    core = (
        "from SHP_INSPECTIONS ins "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = ins.LOT_TRACE_ID "
        "join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "left join BAS_QUALITY_STANDARDS q on q.QSTD_ID = ins.QSTD_ID "
        "left join SYS_USERS u on u.USER_ID = ins.INSPECTOR_ID "
        "where (%(lot)s = '' or lt.PRODUCT_LOT_NO ilike '%%' || %(lot)s || '%%') "
        "  and (%(item)s = '' or ins.INSPECT_ITEM ilike '%%' || %(item)s || '%%') "
        "  and (%(judge)s = '' or ins.JUDGE_RESULT = %(judge)s) "
        "  and (%(date)s = '' or to_char(ins.INSPECT_DT,'YYYY-MM-DD') like %(date)s || '%%') "
        "  and (%(project)s = '' or pj.PROJECT_NO ilike '%%' || %(project)s || '%%') "
        "  and (%(inspector)s = '' or coalesce(u.USER_NAME, u.LOGIN_ID) "
        "       ilike '%%' || %(inspector)s || '%%') "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select ins.INSPECT_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, ins.INSPECT_ITEM, "
        "ins.MEASURED_VALUE, ins.UOM, ins.JUDGE_RESULT, ins.INSPECT_DT, ins.REPORT_NO, "
        "q.STANDARD_SPEC, q.SPEC_MIN, q.SPEC_MAX "
        + core +
        "order by ins.INSPECT_DT desc, ins.INSPECT_ID desc limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
        lot_cell(r["product_lot_no"]),
        cell(r["inspect_item"]),
        cell(num(r["measured_value"], 4) if r["measured_value"] is not None
             else http.not_collected(QSTD_DECISION), num=True),
        cell(r["uom"] or "—"),
        cell(r["judge_result"]),
        cell(dt(r["inspect_dt"])),
    ] for i, r in enumerate(rows, 1)]

    q = kpimod.quality()
    need = inspect_types()
    std_n = conn.q1("select count(*) as n from BAS_QUALITY_STANDARDS") or {"n": 0}
    shippable = conn.q1(
        "select count(*) as n from SHP_LOT_TRACES lt where " + _passed_lot_sql(),
        {"pass": PASS, "types": list(need), "type_n": len(need)}) if need else {"n": 0}

    # 등록 폼 — 검사 대상 제품 LOT 과 적용 가능한 품질기준. 기준이 0건이면 등록은 422 다(D-26).
    from .. import rbac
    role = getattr(request.state, "role_code", "") or ""
    can_write = rbac.can_write(role, screen.area)
    lots = conn.q(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PROJECT_NO, pj.PRODUCT_GROUP "
        "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where lt.TRACE_STATUS <> '출하' order by lt.PRODUCT_LOT_NO limit 200")
    standards = conn.q(
        "select QSTD_ID, QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, INSPECT_ITEM, UOM, "
        "SPEC_MIN, SPEC_MAX, STANDARD_SPEC from BAS_QUALITY_STANDARDS "
        "where USE_YN = 'Y' order by INSPECT_TYPE, PRODUCT_GROUP")

    return render(request, "shp/018.html", **ctx(
        request, screen, td3,
        wired={"제품 LOT 번호": {"name": "lot", "value": f["lot"], "hint": "PLOT-"},
               "검사 항목": {"name": "item", "value": f["item"], "hint": "수압/기밀/진공"},
               "판정": {"name": "judge", "value": f["judge"], "hint": "합격 / 불합격"},
               "검사일자": {"name": "date", "value": f["date"], "hint": "YYYY-MM-DD 또는 YYYY-MM"},
               "검사자": {"name": "inspector", "value": f["inspector"], "hint": "이름 일부"},
               "프로젝트(수주)번호": {"name": "project", "value": f["project"]}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
        empty_note=(http.undetermined(QSTD_DECISION) if not int(std_n["n"] or 0)
                    else http.not_collected(COLLECT_DECISION)),
        cards=[
            {"label": "검사 건수", "value": f"{q.inspect_cnt:,} 건"},
            {"label": "합격", "value": f"{q.pass_cnt:,} 건"},
            {"label": "합격률",
             "value": f"{q.pass_rate:,.1f} %" if q.pass_rate is not None
                      else http.not_collected(COLLECT_DECISION),
             "sub": q.pass_rate_caveat, "off": q.pass_rate is None},
            {"label": "출하 가능 LOT", "value": f"{int(shippable['n'] or 0):,} 건",
             "sub": "수압·기밀·진공 전부 합격한 LOT 만 016 출하 대상이 된다"},
        ],
        lots=lots, standards=standards, inspect_types=need,
        can_write=can_write, pass_label=PASS, fail_label=FAIL,
        back=request.url.path + (("?" + request.url.query) if request.url.query else ""),
        badges=([{"cls": "undetermined",
                  "text": f"품질기준 0건 — {http.undetermined(QSTD_DECISION)} (기준정보관리 · 개발1)"}]
                if not int(std_n["n"] or 0) else
                [{"cls": "notice", "text": f"품질기준 {int(std_n['n'])}건 적용 (BAS_QUALITY_STANDARDS)"}]),
        notes=[{"title": "측정값",
                "body": "측정값은 도입기업 실측이다. 시드에 수치를 지어내지 않았다 — "
                        "입력 전에는 '미수집' 으로 그대로 둔다(§0.2). 화면에서 등록하면 "
                        "측정값·검사자·성적서 번호가 그 행에 남는다."},
               {"title": "판정 근거",
                "body": "품질기준에 허용 상·하한이 있으면 측정값으로 **자동 판정**하고, "
                        "기준 수치가 비어 있으면(D-131) 담당자가 고른 판정을 그대로 기록한다. "
                        "어느 쪽이든 측정값 없이는 등록되지 않는다 (G-24)."}],
    ))


@router.post("/shp/018")
async def create_inspection(request: Request):
    """검사결과 등록 — **검사 합격은 사람이 승인한 결과만 반영한다**(G-24 · TD4-018).

    순서는 계약 §4.0 그대로 **CSRF → 권한 → 입력값**이다. `Form(...)` 을 시그니처에 두면
    FastAPI 가 본문보다 먼저 파싱해 토큰 없는 요청이 403 이 아니라 422 를 받는다.
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))  # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3 = guard(request, "MES-TD3-018", write=True)
    with writing(request, "MES-TD3-018", "등록"):
        return _create_inspection(request, form)


def _create_inspection(request: Request, form: Any):
    import conn
    lot_trace_id = _int_field(form, "lot_trace_id")
    inspect_type = (form.get("inspect_type") or "").strip()
    qstd_id = _int_field(form, "qstd_id")
    measured = _num_field(form, "measured_value")
    uom = (form.get("uom") or "").strip()
    judge_in = (form.get("judge_result") or "").strip()
    reject_reason = (form.get("reject_reason") or "").strip()
    report_no = (form.get("report_no") or "").strip()

    lot = conn.q1(
        "select lt.LOT_TRACE_ID, lt.PRODUCT_LOT_NO, pj.PRODUCT_GROUP "
        "from SHP_LOT_TRACES lt join EST_PROJECTS pj on pj.PROJECT_ID = lt.PROJECT_ID "
        "where lt.LOT_TRACE_ID = %s", (lot_trace_id,))
    if lot is None:
        raise http.fail("validation", f"제품 LOT {lot_trace_id} 가 없다")

    # 검사구분은 `BAS_COMMON_CODES('검사구분')` 참조다 — 코드성 FK 는 D-32 로 막는다.
    codes.require_code("BAS_QUALITY_STANDARDS", "INSPECT_TYPE", inspect_type)

    std = conn.q1(
        "select QSTD_ID, QSTD_CODE, INSPECT_TYPE, INSPECT_ITEM, UOM, SPEC_MIN, SPEC_MAX "
        "from BAS_QUALITY_STANDARDS where QSTD_ID = %s and USE_YN = 'Y'", (qstd_id,))
    if std is None:
        # 그 검사구분의 기준 자체가 없으면 **지어내지 않는다** — 없는 것을 말한다(§0.2).
        any_for_type = conn.q1(
            "select count(*) as n from BAS_QUALITY_STANDARDS "
            "where INSPECT_TYPE = %s and USE_YN = 'Y'", (inspect_type,)) or {"n": 0}
        if not int(any_for_type["n"] or 0):
            raise http.fail("validation",
                            f"검사구분 {inspect_type} 의 품질기준이 없다 — "
                            f"{http.undetermined(QSTD_DECISION)}. 기준정보관리(030)에서 "
                            "품질기준을 먼저 등록해야 검사결과를 남길 수 있다")
        raise http.fail("validation", f"품질기준 {qstd_id} 가 없거나 사용중이 아니다")
    if std["inspect_type"] != inspect_type:
        raise http.fail("validation",
                        f"품질기준 {std['qstd_code']} 의 검사구분은 {std['inspect_type']} 다 — "
                        f"선택한 검사구분 {inspect_type} 과 다르다")

    lo, hi = std["spec_min"], std["spec_max"]
    if lo is not None or hi is not None:
        # 기준이 있으면 **판정은 사람이 고르는 것이 아니라 기준이 정한다.**
        inside = (lo is None or measured >= float(lo)) and (hi is None or measured <= float(hi))
        judge = PASS if inside else FAIL
        basis = f"기준 {num(lo, 4)} ~ {num(hi, 4)} {std['uom'] or ''}".strip()
    else:
        if judge_in not in (PASS, FAIL):
            raise http.fail("validation",
                            f"판정은 '{PASS}' 또는 '{FAIL}' 이어야 한다: {judge_in!r} "
                            f"(품질기준 {std['qstd_code']} 에 허용 상·하한이 없다 — "
                            f"{http.undetermined('D-131')})")
        judge = judge_in
        basis = f"담당자 판정 — 허용 상·하한 없음 ({http.undetermined('D-131')})"
    if judge == FAIL and not reject_reason:
        raise http.fail("validation", "불합격이면 사유를 적어야 한다 (SHP_INSPECTIONS.REJECT_REASON)")

    actor = _actor(request)
    if actor is None:
        raise http.fail("validation", "검사자를 확인할 수 없다 — 로그인 계정이 필요하다 (G-24)")
    conn.x(
        "insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, MEASURED_VALUE, UOM, "
        "JUDGE_RESULT, INSPECTOR_ID, INSPECT_DT, REPORT_NO, REJECT_REASON, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())",
        (lot_trace_id, int(std["qstd_id"]), std["inspect_item"], measured,
         uom or std["uom"], judge, actor, clock.real_now(), report_no or None,
         reject_reason or (None if judge == PASS else basis)),
    )
    return RedirectResponse(safe_next(request, form.get("back"), "/shp/018"), status_code=303)


# ── 019 클레임분석 ──────────────────────────────────────────────────────
@router.get("/shp/019")
async def claims(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-019")
    names = process_names()
    f = {k: _q(request, k) for k in ("no", "customer", "type", "status", "cause")}
    f.update(date_range(request))            # 접수 기간 시작·종료 — 잘못된 날짜는 422
    page, offset = page_of(request, PAGE)

    core = (
        "from SHP_CLAIMS cl "
        "left join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = cl.LOT_TRACE_ID "
        "left join BAS_COMMON_CODES cc on cc.CODE_GROUP = '고객사' and cc.CODE_VALUE = cl.CUSTOMER_CODE "
        "where (%(no)s = '' or cl.CLAIM_NO ilike '%%' || %(no)s || '%%') "
        "  and (%(customer)s = '' or cl.CUSTOMER_CODE ilike '%%' || %(customer)s || '%%') "
        "  and (%(from)s = '' or cl.RECEIVED_DT >= %(from)s::date) "
        "  and (%(to_excl)s = '' or cl.RECEIVED_DT < %(to_excl)s::date) "
        "  and (%(type)s = '' or cl.CLAIM_TYPE = %(type)s) "
        "  and (%(status)s = '' or cl.CLAIM_STATUS = %(status)s) "
    )
    total = count_total(core, f)
    rows = conn.q(
        "select cl.CLAIM_ID, cl.CLAIM_NO, cl.CUSTOMER_CODE, "
        "coalesce(cc.CODE_NAME, cl.CUSTOMER_CODE) as customer_name, lt.PRODUCT_LOT_NO, "
        "cl.CLAIM_TYPE, cl.CLAIM_STATUS, cl.RECEIVED_DT, "
        "(select ca.CAUSE_PROCESS from SHP_CLAIM_CAUSES ca where ca.CLAIM_ID = cl.CLAIM_ID "
        " order by ca.CAUSE_ID limit 1) as cause_process "
        + core +
        "order by cl.RECEIVED_DT desc, cl.CLAIM_ID desc limit %(lim)s offset %(off)s",
        {**f, "lim": PAGE, "off": offset},
    )
    grid_rows = [[
        cell(offset + i, num=True),
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
               "접수 기간": range_wired("접수 기간", f),
               "클레임 유형": {"name": "type", "value": f["type"]},
               "처리 상태": {"name": "status", "value": f["status"], "hint": "접수/분석/조치/완료"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        page=pager(request, total, page, PAGE),
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
