"""메인시안(`/`) 데이터 — TD3 `common_screens.common` 목업 4카드·차트·목록을 실측으로 채운다.

정본(design.json common.mockup):
  cards: 진행 프로젝트 · 제조 리드타임 · 수주출하 리드타임 · 납기 위험
  chart: 월별 리드타임 추이(h)
  list : 프로젝트 진행률

- 리드타임 2종은 `app/kpi.py` 한 곳의 산식을 그대로 쓴다(common.checks "동일한 산식").
- **납기 위험·진행률은 정본에 산식이 없다** → 여기서 정하고 화면에 산식과 `가설 (D-210)` 을 함께 띄운다.
  · 납기 위험 = 진행 상태가 `완료` 가 아니면서 납기일이 기준일(앵커) 이전인 프로젝트 수. 임계 일수를
    두지 않는다 — "N일 이내" 는 정본에 없는 값이다.
  · 진행률 = 프로젝트의 작업지시 중 `완료` 비율. 작업지시가 없으면 값이 없다(0% 로 메우지 않는다, G-11).
- 설비 가동 상태는 `ingest.collector.status()` — 수집 지점 2개소 범위(D-06)에서만 표시한다.
"""
from __future__ import annotations

from typing import Any

import conn

from . import kpi
from .util import clock

DECISION = "D-210"
DUE_RISK_FORMULA = "납기 위험 = 진행 상태 ≠ 완료 이면서 납기일 < 기준일 인 프로젝트 수 (임계 일수 없음)"
PROGRESS_FORMULA = "진행률 = 완료 작업지시 ÷ 전체 작업지시 × 100 (작업지시 0건이면 값 없음)"
CHART_MONTHS = 12
LIST_ROWS = 8


def _fmt_h(v: float | None) -> str:
    return f"{v:,.1f} h" if v is not None else "미수집 (표본 0)"


def cards(anchor) -> list[dict[str, Any]]:
    active = conn.q1(
        "select count(*) as n from EST_PROJECTS where PROJECT_STATUS <> '완료'")
    overdue = conn.q1(
        "select count(*) as n from EST_PROJECTS "
        "where PROJECT_STATUS <> '완료' and DUE_DT is not null and DUE_DT < %s::date",
        [anchor.date()])
    out = [{"label": "진행 프로젝트", "value": f"{int(active['n']):,} 건",
            "sub": "진행 상태 ≠ 완료 (EST_PROJECTS.PROJECT_STATUS)"}]
    for m in kpi.summary():
        d = m.definition
        ach = f"달성률 {m.achieve:,.1f} %" if m.achieve is not None else "달성률 —"
        out.append({"label": d.name.replace(" 단축", "").replace(" 감소", ""),
                    "value": _fmt_h(m.value),
                    "sub": f"기존 {d.base:,.0f} h → 목표 {d.target:,.0f} h · {ach} · 표본 {m.sample_cnt} 건",
                    "off": m.value is None})
    out.append({"label": "납기 위험", "value": f"{int(overdue['n']):,} 건",
                "sub": f"가설 산식 ({DECISION}) — 납기 경과·미완료", "hyp": True})
    return out


def chart() -> dict[str, Any]:
    """월별 제조 리드타임 평균(h) — `kpi.samples(CODE_MFG)` 를 월로 묶는다. 마지막 12개월(표본 있는 달)."""
    rows = kpi.samples(kpi.CODE_MFG)
    by_month: dict[str, list[float]] = {}
    for r in rows:
        by_month.setdefault(r["period_code"], []).append(float(r["hours"]))
    months = sorted(by_month)[-CHART_MONTHS:]
    bars = [{"label": m, "value": kpi.mean_hours(by_month[m]), "n": len(by_month[m])} for m in months]
    return {"title": "월별 제조 리드타임 추이 (h)", "bars": bars,
            "target": kpi.definition(kpi.CODE_MFG).target, "base": kpi.definition(kpi.CODE_MFG).base}


def progress() -> list[dict[str, Any]]:
    rows = conn.q(
        "select p.PROJECT_NO, p.PROJECT_NAME, p.PROJECT_STATUS, p.DUE_DT, "
        "       count(w.WORK_ORDER_ID) as total_wo, "
        "       count(w.WORK_ORDER_ID) filter (where w.ORDER_STATUS = '완료') as done_wo "
        "from EST_PROJECTS p left join PRC_WORK_ORDERS w on w.PROJECT_ID = p.PROJECT_ID "
        "group by p.PROJECT_ID, p.PROJECT_NO, p.PROJECT_NAME, p.PROJECT_STATUS, p.DUE_DT "
        "order by (p.PROJECT_STATUS = '완료'), p.DUE_DT desc nulls last, p.PROJECT_NO desc "
        "limit %s", [LIST_ROWS])
    out = []
    for r in rows:
        total, done = int(r["total_wo"]), int(r["done_wo"])
        pct = round(done / total * 100, 1) if total else None
        out.append({"project_no": r["project_no"], "name": r["project_name"],
                    "status": r["project_status"], "due": r["due_dt"],
                    "percent": pct, "done": done, "total": total})
    return out


def equipment() -> dict[str, Any]:
    from ..ingest import collector
    return collector.status()


def build() -> dict[str, Any]:
    anchor = clock.anchor()
    return {"anchor": anchor, "cards": cards(anchor), "chart": chart(), "progress": progress(),
            "equipment": equipment(), "decision": DECISION,
            "due_risk_formula": DUE_RISK_FORMULA, "progress_formula": PROGRESS_FORMULA}
