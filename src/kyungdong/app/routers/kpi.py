"""KPI관리 043~045 + 공통 현황판 `/board` (개발2).

**산식은 `app/kpi.py` 한 곳에 있다.** 이 화면도, 대시보드 001~004 도, 현황판도 같은 함수를
부른다 — 그래서 카드 값이 화면마다 갈라지지 않는다(goal.md 개발2 · D-21 · D-35).

**044 품질 KPI 는 공식 성과지표가 아니다.** 사업계획서 1.5 성과지표 2건에 포함되지 않는
운영지표이므로 화면에 그렇게 **구분 표기**한다(TD3 common_screens dashboard checks).

`/board` 는 `main.py` 의 기본 `/board` 보다 **먼저 등록**된다(라우터가 먼저 include 된다) —
`main.py` 를 건드리지 않고 현황판을 채우기 위해서다. 근거는 `decisions-dev2.md` D-205.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import design, kpi as kpimod
from ..settings import settings
from ..templating import render
from ..util import http
from .dsh import (COLLECT_DECISION, anchor, cell, ctx, dt, equip_utilisation, guard, mock, num,
                  process_names, project_cell)

router = APIRouter()
SCREENS = ("MES-TD3-043", "MES-TD3-044", "MES-TD3-045")


def _q(request: Request, key: str) -> str:
    return (request.query_params.get(key) or "").strip()


def _measure_chart(code: str) -> list[dict]:
    """월별 측정값 — `KPI_MEASURES` 에 쌓인 것만 그린다. 없으면 빈 리스트다(미수집)."""
    rows = [r for r in kpimod.measures_in_db(code)]
    rows.sort(key=lambda r: r["period_code"])
    return [{"label": r["period_code"], "value": float(r["measure_value"]),
             "text": num(r["measure_value"], 1)} for r in rows[-6:]]


def _official_table() -> list[dict]:
    """공식 성과지표 2종 — 대시보드·현황판·043·045 가 **같은 이 함수**를 쓴다."""
    out = []
    for m in kpimod.summary():
        d = m.definition
        out.append({
            "code": d.code, "name": d.name, "uom": d.uom,
            "base": d.base, "target": d.target, "improve": d.improve_rate, "weight": d.weight,
            "measured": m.value, "measured_text": m.value_text,
            "achieve": m.achieve, "achieve_text": m.achieve_text,
            "sample": m.sample_cnt, "formula": d.formula, "basis": d.basis,
            "source": f"{d.start_label} ~ {d.end_label}",
        })
    return out


# ── 043 생산성 KPI 조회 ─────────────────────────────────────────────────
@router.get("/kpi/043")
async def productivity(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-043")
    names = process_names()
    period = _q(request, "period") or None

    d = kpimod.definition(kpimod.CODE_MFG)
    m = kpimod.measure(kpimod.CODE_MFG, period)

    dwell = conn.q(
        "select PROCESS_CODE, avg(DWELL_HOUR) as avg_h from PRC_PROCESS_HISTORIES "
        "where DWELL_HOUR is not null group by PROCESS_CODE order by 2 desc"
    )
    total = sum(float(r["avg_h"] or 0) for r in dwell) or 1.0

    return render(request, "kpi/043.html", **ctx(
        request, screen, td3,
        cards=[
            {"label": "제조 리드타임(기존)", "value": f"{d.base:,.0f} {d.uom}", "sub": d.basis},
            {"label": "제조 리드타임(목표)", "value": f"{d.target:,.0f} {d.uom}"},
            {"label": "개선율 목표", "value": f"{d.improve_rate} %",
             "sub": "(기존−목표)÷기존×100"},
            {"label": "가중치", "value": f"{d.weight}"},
            {"label": "실측 평균", "value": m.value_text,
             "sub": f"표본 {m.sample_cnt:,}건" if m.sample_cnt else "표본 0건",
             "off": not m.collected},
            {"label": "달성률", "value": m.achieve_text,
             "sub": kpimod.ACHIEVE_FORMULA, "off": m.achieve is None},
        ],
        chart_title="월별 제조 리드타임(h)",
        chart=_measure_chart(kpimod.CODE_MFG),
        list_title="공정별 소요시간 비중",
        progress=[{"label": names.get(r["process_code"], r["process_code"]),
                   "percent": int(round(float(r["avg_h"] or 0) / total * 100)),
                   "text": f"{num(r['avg_h'], 2)} h"} for r in dwell],
        official=_official_table(),
        empty_note=http.not_collected(COLLECT_DECISION),
        badges=[{"cls": "notice", "text": kpimod.OFFICIAL_NOTE}],
        notes=[{"title": "산식", "body": d.formula},
               {"title": "산출 근거", "body": f"{d.start_label} ~ {d.end_label}"},
               {"title": "측정 근거", "body": d.basis}],
    ))


# ── 044 품질 KPI 조회 — **공식 성과지표가 아니다** ─────────────────────────
@router.get("/kpi/044")
async def quality_kpi(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-044")
    names = process_names()
    period = _q(request, "period") or None
    q = kpimod.quality(period)
    a = anchor()

    trend = conn.q(
        "select to_char(START_DT, 'YYYY-MM') as period, "
        "coalesce(sum(DEFECT_QTY),0) as defect, coalesce(sum(GOOD_QTY),0) as good "
        "from PRC_PERFORMANCES group by 1 order by 1 desc limit 6"
    )
    by_type = conn.q(
        "select coalesce(DEFECT_TYPE, '') as defect_type, coalesce(sum(DEFECT_QTY),0) as defect "
        "from PRC_PERFORMANCES where coalesce(DEFECT_QTY,0) > 0 group by 1 order by 2 desc limit 6"
    )
    type_total = sum(float(r["defect"] or 0) for r in by_type) or 1.0

    return render(request, "kpi/044.html", **ctx(
        request, screen, td3,
        cards=[
            {"label": "출하 합격률",
             "value": f"{q.pass_rate:,.1f} %" if q.pass_rate is not None
                      else http.not_collected(COLLECT_DECISION),
             "sub": f"검사 {q.inspect_cnt:,}건 · 합격 {q.pass_cnt:,}건", "off": q.pass_rate is None},
            {"label": "공정 불량률",
             "value": f"{q.defect_rate:,.1f} %" if q.defect_rate is not None
                      else http.not_collected(COLLECT_DECISION),
             "sub": f"양품 {q.good_qty:,.0f} · 불량 {q.defect_qty:,.0f} ea",
             "off": q.defect_rate is None},
            {"label": "클레임 발생률",
             "value": f"{q.claim_rate:,.1f} %" if q.claim_rate is not None
                      else http.not_collected("D-204"),
             "sub": f"출하 {q.shipment_cnt:,}건 · 클레임 {q.claim_cnt:,}건",
             "off": q.claim_rate is None},
            {"label": "집계 기간", "value": period or f"전체 (기준 {dt(a, '%Y-%m-%d')})"},
        ],
        chart_title="월별 불량률(%)",
        chart=[{"label": r["period"],
                "value": kpimod.ratio_pct(r["defect"],
                                          float(r["good"] or 0) + float(r["defect"] or 0)) or 0.0,
                "text": num(kpimod.ratio_pct(r["defect"],
                                             float(r["good"] or 0) + float(r["defect"] or 0)), 1)}
               for r in reversed(trend)],
        list_title="불량 유형 비중",
        progress=[{"label": r["defect_type"] or http.undetermined("D-47"),
                   "percent": int(round(float(r["defect"] or 0) / type_total * 100)),
                   "text": f"{num(r['defect'], 0)} ea"} for r in by_type],
        not_official=kpimod.NOT_OFFICIAL_NOTE,
        official=_official_table(),
        empty_note=http.not_collected(COLLECT_DECISION),
        badges=[{"cls": "bad", "text": "공식 성과지표 아님 — 운영지표"},
                {"cls": "notice", "text": kpimod.NOT_OFFICIAL_NOTE}],
        notes=[{"title": "왜 구분 표기하는가", "body": kpimod.NOT_OFFICIAL_NOTE},
               {"title": "공식 성과지표",
                "body": "제조 리드타임(LEADTIME_MFG) · 수주출하 리드타임(LEADTIME_O2D) 2건뿐이다 "
                        "— 043·045 에서 본다 (사업계획서 1.5 · D-21)."}],
    ))


# ── 045 KPI 관리 ────────────────────────────────────────────────────────
@router.get("/kpi/045")
async def kpi_admin(request: Request):
    screen, td3 = guard(request, "MES-TD3-045")
    f = {k: _q(request, k) for k in ("code", "name", "field", "official", "period")}

    targets = kpimod.targets_in_db()

    def keep(r) -> bool:
        return (
            (not f["code"] or f["code"].upper() in r["kpi_code"].upper())
            and (not f["name"] or f["name"] in r["kpi_name"])
            and (not f["field"] or f["field"].upper() == (r["kpi_field"] or "").upper())
            and (not f["official"] or f["official"].upper() == (r["official_yn"] or "").upper())
        )

    rows = [r for r in targets if keep(r)]
    grid_rows = [[
        cell(i, num=True),
        cell(r["kpi_code"]),
        cell(r["kpi_name"] + ("" if r["official_yn"] == "Y" else " · 공식 성과지표 아님")),
        cell(num(r["base_value"], 4), num=True),
        cell(num(r["target_value"], 4), num=True),
        cell(num(r["improve_rate"], 3), num=True),
        cell(num(r["weight"], 2), num=True),
    ] for i, r in enumerate(rows, 1)]

    measures = kpimod.measures_in_db(f["code"].upper() or None)
    measure_rows = [{
        "code": m["kpi_code"], "name": m["kpi_name"], "period": m["period_code"],
        "sample": m["sample_cnt"], "value": num(m["measure_value"], 2, m["uom"]),
        "achieve": num(m["achieve_rate"], 1, "%"), "source": m["source_type"],
        "at": dt(m["aggregated_dt"]), "remark": m["remark"] or "",
    } for m in measures]

    seeded = {r["kpi_code"] for r in targets}
    missing = [d for c, d in kpimod.DEFS.items() if c not in seeded]

    return render(request, "kpi/045.html", **ctx(
        request, screen, td3,
        wired={"KPI 코드": {"name": "code", "value": f["code"], "hint": "LEADTIME_"},
               "KPI명": {"name": "name", "value": f["name"]},
               "분야": {"name": "field", "value": f["field"], "hint": "P/Q/C/D"},
               "공식 지표 여부": {"name": "official", "value": f["official"], "hint": "Y / N"}},
        columns=mock(td3)["grid_columns"], rows=grid_rows,
        empty_note=f"{http.undetermined('D-21')} — `uv run python db/seed_dev2.py` 로 "
                   "사업계획서 1.5 확정값을 등록한다",
        cards=[
            {"label": "등록 KPI", "value": f"{len(targets):,} 건"},
            {"label": "공식 성과지표",
             "value": f"{sum(1 for r in targets if r['official_yn'] == 'Y'):,} 건",
             "sub": "사업계획서 1.5 (D-21)"},
            {"label": "측정 실적", "value": f"{len(measures):,} 건"},
            {"label": "미등록 정의", "value": f"{len(missing):,} 건",
             "sub": ", ".join(d.code for d in missing) if missing else ""},
        ],
        official=_official_table(),
        measures=measure_rows,
        achieve_formula=kpimod.ACHIEVE_FORMULA,
        badges=[{"cls": "notice",
                 "text": "기존값·목표값은 사업계획서 1.5 확정값이다 — 화면에서 지어내지 않는다"}],
        notes=[{"title": "산식 단일 소스",
                "body": "app/kpi.py 한 곳에 있다. 대시보드·현황판·043·044·045 가 같은 함수를 부른다."},
               {"title": "달성률", "body": kpimod.ACHIEVE_FORMULA + " (가설 D-202)"}],
    ))


# ── 공통 현황판 `/board` — 65" 2대, 조회조건 없이 자동 갱신 ─────────────────
@router.get("/board")
async def board(request: Request):
    import conn
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    s = settings()
    refresh = s.h("BOARD_REFRESH_SEC")

    official = _official_table()
    q = kpimod.quality()
    util, signal_n = equip_utilisation(day0)

    today = conn.q1(
        "select count(*) as n, coalesce(sum(GOOD_QTY),0) as good from PRC_PERFORMANCES "
        "where START_DT >= %s", (day0,)) or {"n": 0, "good": 0}
    ship = conn.q1(
        "select count(*) filter (where SHIP_DT is null) as planned, "
        "count(*) filter (where SHIP_DT is not null) as done from SHP_SHIPMENTS") or {}
    alarms = conn.q1(
        "select count(*) as n from PRC_EQUIP_SIGNALS where ALARM_CODE is not null "
        "and COLLECT_DT >= %s", (day0,)) or {"n": 0}
    progress = conn.q(
        "select pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT, "
        "count(h.PRC_HIST_ID) as total, count(h.OUT_DT) as done "
        "from EST_PROJECTS pj join SHP_LOT_TRACES lt on lt.PROJECT_ID = pj.PROJECT_ID "
        "join PRC_PROCESS_HISTORIES h on h.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        "where pj.PROJECT_STATUS <> '완료' "
        "group by pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT order by pj.DUE_DT limit 6"
    )
    risk = conn.q(
        "select PROJECT_NO, PROJECT_NAME, DUE_DT, PROJECT_STATUS from EST_PROJECTS "
        "where DUE_DT is not null and PROJECT_STATUS <> '완료' order by DUE_DT limit 6"
    )
    # AI 분석·추천은 개발3(AGT_) 영역이라 **읽기만** 한다. 승인 전에는 확정 상태로 표기하지 않는다.
    reco = conn.q(
        "select RECO_TYPE, TARGET_TYPE, SUMMARY_TEXT, REVIEW_STATUS, CREATED_AT_DT "
        "from AGT_RECOMMENDATIONS order by CREATED_AT_DT desc nulls last limit 5"
    )

    return render(request, "board.html",
                  common=design.common_screens()["dashboard"],
                  refresh=refresh,
                  anchor_text=dt(a),
                  official=official,
                  quality=q,
                  not_official=kpimod.NOT_OFFICIAL_NOTE,
                  cards=[
                      {"label": "금일 실적", "value": f"{int(today['n'] or 0):,} 건",
                       "sub": f"수량 {float(today['good'] or 0):,.0f} ea"},
                      {"label": "검사 합격률",
                       "value": f"{q.pass_rate:,.1f} %" if q.pass_rate is not None
                                else http.not_collected(COLLECT_DECISION),
                       "sub": "운영지표 — 공식 성과지표 아님", "off": q.pass_rate is None},
                      {"label": "출하 예정", "value": f"{int(ship.get('planned') or 0):,} 건",
                       "sub": f"확정 {int(ship.get('done') or 0):,} 건"},
                      {"label": "설비 가동률",
                       "value": f"{util:,.1f} %" if util is not None
                                else http.not_collected(COLLECT_DECISION),
                       "sub": f"수집 신호 {signal_n:,}건 · 2개소 (D-06)", "off": util is None},
                      {"label": "설비 알람", "value": f"{int(alarms['n'] or 0):,} 건"},
                  ],
                  progress=[{"label": f"{r['project_no']} {r['project_name']}",
                             "percent": int(round(int(r["done"]) / int(r["total"]) * 100))
                                        if r["total"] else 0,
                             "text": f"{r['done']}/{r['total']} 공정 · 납기 {r['due_dt'] or '—'}"}
                            for r in progress],
                  risk=[{"no": r["project_no"], "name": r["project_name"], "due": r["due_dt"],
                         "left": (r["due_dt"] - a.date()).days if r["due_dt"] else None,
                         "status": r["project_status"]} for r in risk],
                  reco=reco,
                  empty_note=http.not_collected(COLLECT_DECISION),
                  reco_note=http.not_collected("D-08"))
