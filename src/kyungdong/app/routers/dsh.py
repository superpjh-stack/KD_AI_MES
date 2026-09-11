"""AI 대시보드 001~004 (개발2) — 그리고 개발2 4개 모듈의 **공용 헬퍼**.

`prc.py` · `shp.py` · `kpi.py` 가 여기서 `guard` · `ctx` · `cell` · `lot_cell` 을 가져다 쓴다.
공용 헬퍼를 새 파일로 빼지 않는 이유는 소유 파일이 `routers/{dsh,prc,shp,kpi}.py` 로 고정돼
있기 때문이다(screen-map §2). 한 파일은 한 사람만 만진다.

**규칙**
  · 화면 문장은 `design.screen(sid)` 정본에서 온다. 없으면 `util.http.undetermined` 다(§0.2).
  · 건수 카드의 `0 건` 은 정답이다. 빈 **그리드**에만 '미수집' 을 쓴다(G-11 · §10-14).
  · LOT·프로젝트번호 셀은 **클릭하면 `/prc/024` 공정이력조회**로 간다(G-08).
  · 수집 범위 밖은 `util.http.not_collected("D-06")` — 전 공정 실시간 수집인 척하지 않는다.
  · DB 장애는 `db/conn.py` 가 503 을 낸다. `try/except` 로 덮지 않는다(G-30).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request

from .. import design, nav, rbac
from ..settings import settings
from ..templating import render
from ..util import clock, http

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "db"))

from fastapi import APIRouter  # noqa: E402

router = APIRouter()
SCREENS = ("MES-TD3-001", "MES-TD3-002", "MES-TD3-003", "MES-TD3-004")

HISTORY_PATH = "/prc/024"          # 공정이력조회 — 디지털 스레드 클릭 목적지 (G-08)
COLLECT_DECISION = "D-06"          # 수집 지점 2개소 한정
STD_COND_DECISION = "D-203"        # 표준 작업조건 초기값 미제공
CLAIM_DECISION = "D-204"           # 클레임 이력 런타임 등록


# ── 공용 헬퍼 ───────────────────────────────────────────────────────────
def guard(request: Request, sid: str, *, write: bool = False, approve: bool = False):
    """권한 확인 + 정본 로드. 권한 없으면 **403**, 정본이 없으면 지어내지 않는다."""
    screen = nav.by_id()[sid]
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, screen.area):
        raise http.fail("forbidden", f"{screen.area} 조회 권한 없음")
    if write and not rbac.can_write(role, screen.area):
        raise http.fail("forbidden", f"{screen.area} 등록·수정 권한 없음")
    if approve and not rbac.can_approve(role, screen.area):
        raise http.fail("forbidden", f"{screen.area} 승인 권한 없음 (G-24)")
    td3 = design.screen(sid)
    if td3 is None:
        raise http.fail("internal", f"{sid} 정본(SF-TD3)이 없다 — {http.undetermined('D-nn')}")
    return screen, td3


def mock(td3: dict[str, Any]) -> dict[str, Any]:
    return td3.get("mockup") or {}


def anchor() -> datetime:
    """시간 앵커. `date.today()` 를 쓰지 않는다(§10-3)."""
    return clock.anchor()


def cell(text: Any, *, href: str | None = None, num: bool = False) -> dict[str, Any]:
    return {"t": "" if text is None else str(text), "href": href, "num": num}


def lot_cell(lot_no: str | None) -> dict[str, Any]:
    """제품 LOT 셀 — 클릭하면 024 공정이력조회로 간다(G-08)."""
    if not lot_no:
        return cell("—")
    return cell(lot_no, href=f"{HISTORY_PATH}?lot={lot_no}")


def project_cell(project_no: str | None) -> dict[str, Any]:
    """프로젝트(수주)번호 셀 — ETO 최상위 조회 축이고 역시 024 로 간다(G-08)."""
    if not project_no:
        return cell("—")
    return cell(project_no, href=f"{HISTORY_PATH}?project={project_no}")


def num(value: Any, digits: int = 0, unit: str = "") -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}{(' ' + unit) if unit else ''}"


def dt(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return value.strftime(fmt) if isinstance(value, datetime) else ("—" if not value else str(value))


def count_card(label: str, n: int, unit: str = "건", sub: str = "") -> dict[str, Any]:
    """**건수 카드는 0 이어도 그대로 `0 건`** 이다 — '미수집' 을 붙이면 거짓 표시다(§10-14)."""
    return {"label": label, "value": f"{n:,} {unit}", "sub": sub}


def ratio_card(label: str, pct: float | None, sub: str = "", decision: str = COLLECT_DECISION):
    """비율 카드는 분모가 없으면 값이 **없는 것**이다 — '미수집' 이 맞다."""
    if pct is None:
        return {"label": label, "value": http.not_collected(decision), "sub": sub, "off": True}
    return {"label": label, "value": f"{pct:,.1f} %", "sub": sub}


def ctx(request: Request, screen: nav.Screen, td3: dict[str, Any], **extra) -> dict[str, Any]:
    return dict(current=screen, screen=screen, td3=td3, mock=mock(td3),
                history_path=HISTORY_PATH, **extra)


def process_names() -> dict[str, str]:
    """공정 코드 → 이름. 화면은 코드가 아니라 이름을 보여 준다."""
    import conn
    rows = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = '공정' order by SORT_ORDER"
    )
    return {r["code_value"]: r["code_name"] for r in rows}


def collection_badges() -> list[dict[str, str]]:
    """수집 범위·중단 상태 배지 (D-06 · G-12). 수집이 끊기면 숨기지 않고 드러낸다."""
    import conn
    row = conn.q1("select max(COLLECT_DT) as last_dt, count(*) as n from PRC_EQUIP_SIGNALS")
    stale_sec = settings().h("INGEST_STALE_SEC").as_int()
    out = [{"cls": "notice", "text": "자동 수집 2개소 (레이저커팅기 PLC · 현장POP) — D-06"}]
    if not row or not row["last_dt"]:
        out.append({"cls": "undetermined", "text": http.not_collected(COLLECT_DECISION)})
        return out
    age = (anchor() - row["last_dt"]).total_seconds()
    if age > stale_sec:
        out.append({"cls": "bad",
                    "text": http.NOTICE_INGEST_STALE.format(ts=dt(row["last_dt"]))})
    return out


def equip_utilisation(since: datetime) -> tuple[float | None, int]:
    """가동률(%) = 가동 신호 ÷ 전체 신호 × 100. 신호가 없으면 `None` 이다."""
    import conn
    from .. import kpi as kpimod
    row = conn.q1(
        "select count(*) as n, count(*) filter (where RUN_STATUS = '가동') as run_n "
        "from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s", (since,),
    ) or {"n": 0, "run_n": 0}
    return kpimod.ratio_pct(row["run_n"], row["n"]), int(row["n"] or 0)


# ── 001 생산현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/001")
async def production_status(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-001")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    names = process_names()

    today = conn.q1(
        "select coalesce(sum(GOOD_QTY),0) as good, count(*) as n from PRC_PERFORMANCES "
        "where START_DT >= %s and START_DT < %s", (day0, day0 + timedelta(days=1)),
    ) or {"good": 0, "n": 0}
    running = conn.q1(
        "select count(*) as n from PRC_WORK_ORDERS where ORDER_STATUS = '진행'") or {"n": 0}
    late = conn.q1(
        "select count(*) as n from EST_PROJECTS "
        "where DUE_DT is not null and DUE_DT < %s and PROJECT_STATUS <> '완료'", (a.date(),),
    ) or {"n": 0}
    util, signal_n = equip_utilisation(day0)

    by_process = conn.q(
        "select PROCESS_CODE, coalesce(sum(GOOD_QTY),0) as good from PRC_PERFORMANCES "
        "group by PROCESS_CODE order by PROCESS_CODE"
    )
    by_project = conn.q(
        "select pj.PROJECT_NO, pj.PROJECT_NAME, "
        "count(h.PRC_HIST_ID) as total, count(h.OUT_DT) as done "
        "from EST_PROJECTS pj "
        "join SHP_LOT_TRACES lt on lt.PROJECT_ID = pj.PROJECT_ID "
        "join PRC_PROCESS_HISTORIES h on h.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        "group by pj.PROJECT_NO, pj.PROJECT_NAME order by pj.PROJECT_NO limit 8"
    )

    return render(request, "dsh/001.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("금일 실적수량", int(float(today["good"] or 0)), "ea",
                       f"실적 {int(today['n'] or 0)}건 · 기준 {dt(a, '%Y-%m-%d')}"),
            count_card("진행 작업지시", int(running["n"] or 0)),
            ratio_card("설비 가동률", util, f"수집 신호 {signal_n:,}건 · 레이저커팅기 1대 (D-06)"),
            count_card("지연 프로젝트", int(late["n"] or 0), "건", "납기일 경과·미완료"),
        ],
        chart_title=mock(td3).get("chart_title", "").replace("(예시)", ""),
        chart=[{"label": names.get(r["process_code"], r["process_code"]),
                "value": float(r["good"] or 0), "text": num(r["good"], 0)} for r in by_process],
        list_title=mock(td3).get("list_title", "").replace("(예시)", ""),
        progress=[{"label": f"{r['project_no']} {r['project_name']}",
                   "percent": int(round(int(r["done"]) / int(r["total"]) * 100)) if r["total"] else 0,
                   "text": f"{r['done']}/{r['total']} 공정"} for r in by_project],
        badges=collection_badges(),
        empty_note=http.not_collected(COLLECT_DECISION),
    ))


# ── 002 품질현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/002")
async def quality_status(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-002")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    names = process_names()

    today = conn.q1(
        "select count(*) as n from SHP_INSPECTIONS where INSPECT_DT >= %s and INSPECT_DT < %s",
        (day0, day0 + timedelta(days=1)),
    ) or {"n": 0}
    q = kpimod.quality()
    bad_lots = conn.q1(
        "select count(distinct LOT_TRACE_ID) as n from SHP_INSPECTIONS where JUDGE_RESULT <> '합격'"
    ) or {"n": 0}

    trend = conn.q(
        "select to_char(START_DT, 'YYYY-MM') as period, coalesce(sum(DEFECT_QTY),0) as defect "
        "from PRC_PERFORMANCES group by 1 order by 1 desc limit 6"
    )
    by_process = conn.q(
        "select PROCESS_CODE, coalesce(sum(DEFECT_QTY),0) as defect from PRC_PERFORMANCES "
        "where coalesce(DEFECT_QTY,0) > 0 group by PROCESS_CODE order by 2 desc limit 6"
    )
    total_defect = sum(float(r["defect"] or 0) for r in by_process) or 1.0

    return render(request, "dsh/002.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("금일 검사 건수", int(today["n"] or 0)),
            ratio_card("합격률", q.pass_rate, f"검사 {q.inspect_cnt:,}건 중 합격 {q.pass_cnt:,}건"),
            count_card("불량 수량", int(q.defect_qty), "ea", f"양품 {q.good_qty:,.0f} ea"),
            count_card("이상 LOT", int(bad_lots["n"] or 0), "건", "불합격 판정이 있는 제품 LOT"),
        ],
        chart_title="기간별 불량 발생 추이",
        chart=[{"label": r["period"], "value": float(r["defect"] or 0),
                "text": num(r["defect"], 0)} for r in reversed(trend)],
        list_title="공정별 불량 비중",
        progress=[{"label": names.get(r["process_code"], r["process_code"]),
                   "percent": int(round(float(r["defect"] or 0) / total_defect * 100)),
                   "text": f"{num(r['defect'], 0)} ea"} for r in by_process],
        badges=[{"cls": "notice",
                 "text": "판정 기준은 기준정보관리 품질기준(BAS_QUALITY_STANDARDS)을 따른다"}],
        empty_note=http.not_collected(COLLECT_DECISION),
    ))


# ── 003 설비상태 모니터링 ───────────────────────────────────────────────
@router.get("/dsh/003")
async def equipment_status(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-003")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)

    laser = conn.q1(
        "select RUN_STATUS, COLLECT_DT from PRC_EQUIP_SIGNALS where EQUIP_CODE = 'EQ10' "
        "order by COLLECT_DT desc limit 1"
    )
    runtime = conn.q1(
        "select coalesce(sum(RUN_MINUTE),0) as m from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s",
        (day0,),
    ) or {"m": 0}
    alarms = conn.q1(
        "select count(*) as n from PRC_EQUIP_SIGNALS "
        "where ALARM_CODE is not null and COLLECT_DT >= %s", (day0,),
    ) or {"n": 0}
    hourly = conn.q(
        "select to_char(COLLECT_DT, 'HH24') as hh, coalesce(sum(RUN_MINUTE),0) as m "
        "from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s group by 1 order by 1", (day0,),
    )
    # 수집 지점은 **2개소뿐**이다(D-06) — 설비 코드 그룹이 그 2개소의 정본이다.
    points = conn.q(
        "select c.CODE_VALUE, c.CODE_NAME, c.ATTR1, "
        "(select count(*) from PRC_EQUIP_SIGNALS s where s.EQUIP_CODE = c.CODE_VALUE) as n, "
        "(select max(s.COLLECT_DT) from PRC_EQUIP_SIGNALS s where s.EQUIP_CODE = c.CODE_VALUE) as last_dt "
        "from BAS_COMMON_CODES c where c.CODE_GROUP = '설비' order by c.SORT_ORDER"
    )
    devices = conn.q1(
        "select count(*) as n from IF_DEVICE_REGISTRY where USE_YN = 'Y'") or {"n": 0}
    signal_total = sum(int(p["n"] or 0) for p in points) or 1

    has_signal = laser is not None
    return render(request, "dsh/003.html", **ctx(
        request, screen, td3,
        cards=[
            {"label": "레이저커팅기 상태",
             "value": laser["run_status"] if has_signal else http.not_collected(COLLECT_DECISION),
             "sub": dt(laser["collect_dt"]) if has_signal else "PLC 수집 신호 없음",
             "off": not has_signal},
            {"label": "금일 가동시간",
             "value": num(runtime["m"], 0, "분") if has_signal else http.not_collected(COLLECT_DECISION),
             "sub": f"기준 {dt(a, '%Y-%m-%d')}", "off": not has_signal},
            count_card("알람 발생", int(alarms["n"] or 0)),
            count_card("수집 지점", 2, "개소", "레이저커팅기 PLC 1 · 현장POP 1 (D-06)"),
        ],
        chart_title="시간대별 가동시간(분)",
        chart=[{"label": f"{r['hh']}시", "value": float(r["m"] or 0),
                "text": num(r["m"], 0)} for r in hourly],
        list_title="수집 지점 상태",
        progress=[{"label": f"{p['code_name']} ({p['code_value']})",
                   "percent": int(round(int(p["n"] or 0) / signal_total * 100)),
                   "text": (f"신호 {int(p['n'] or 0):,}건 · 최종 {dt(p['last_dt'])}"
                            if p["n"] else http.not_collected(COLLECT_DECISION))}
                  for p in points],
        notes=[{"title": "수집 장비",
                "body": f"등록 수집장비 {int(devices['n'] or 0)} 대 (IF_DEVICE_REGISTRY). "
                        f"수집 주기 {settings().h('PLC_POLL_SEC').value}초 "
                        f"{settings().h('PLC_POLL_SEC').badge}"}],
        badges=collection_badges() + [
            {"cls": "notice",
             "text": "설비 예지보전 AI는 본 사업 범위 밖이다 (사업계획서 2.5 현 사업 미적용 · D-01)"}],
        empty_note=http.not_collected(COLLECT_DECISION),
    ))


# ── 004 출하현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/004")
async def shipment_status(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-004")
    a = anchor()

    agg = conn.q1(
        "select count(*) filter (where SHIP_DT is null) as planned, "
        "count(*) filter (where SHIP_DT is not null) as done, "
        "count(*) filter (where SHIP_STATUS = '지연') as late, "
        "count(*) filter (where OTD_YN = 'Y') as otd, "
        "count(*) filter (where OTD_YN is not null) as otd_base from SHP_SHIPMENTS"
    ) or {}
    weekly = conn.q(
        "select to_char(SHIP_DT, 'IYYY-IW') as wk, count(*) as n from SHP_SHIPMENTS "
        "where SHIP_DT is not null group by 1 order by 1 desc limit 6"
    )
    due = conn.q(
        "select pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT, pj.PROJECT_STATUS, "
        "(select count(*) from SHP_LOT_TRACES lt where lt.PROJECT_ID = pj.PROJECT_ID "
        " and lt.TRACE_STATUS = '출하') as shipped "
        "from EST_PROJECTS pj where pj.DUE_DT is not null and pj.PROJECT_STATUS <> '완료' "
        "order by pj.DUE_DT limit 8"
    )

    def days_left(d) -> int:
        return (d - a.date()).days if d else 0

    return render(request, "dsh/004.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("출하 예정", int(agg.get("planned") or 0)),
            count_card("출하 완료", int(agg.get("done") or 0)),
            count_card("지연", int(agg.get("late") or 0)),
            ratio_card("납기 준수율", kpimod.ratio_pct(agg.get("otd"), agg.get("otd_base")),
                       "출하 확정 건 기준 (OTD_YN)"),
        ],
        chart_title="주간 출하 물량",
        chart=[{"label": r["wk"], "value": float(r["n"]), "text": num(r["n"], 0)}
               for r in reversed(weekly)],
        list_title="납기 임박 프로젝트",
        progress=[{"label": f"{r['project_no']} {r['project_name']}",
                   "percent": max(0, min(100, 100 - days_left(r["due_dt"]) * 2)),
                   "text": f"납기 {r['due_dt']} · D{days_left(r['due_dt']):+d} · {r['project_status']}"}
                  for r in due],
        badges=[{"cls": "notice",
                 "text": "납기는 수주 확정 시점의 납기일 기준이다. 출하 확정 시각이 "
                         "수주출하 리드타임(LEADTIME_O2D)의 종료 시각이다"}],
        empty_note=http.not_collected("D-07"),
    ))
