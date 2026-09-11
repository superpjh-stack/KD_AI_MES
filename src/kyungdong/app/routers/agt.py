"""AI Agent — 009 입고 · 020 출하 · 038~042 통합관리 (개발3).

`/inv/009` 와 `/shp/020` 은 **업무영역은 입고·출하, 구현은 여기**다(D-38).

이 파일이 지키는 것
  · **폐쇄형** — 외부 검색 0. 내부 `AGT_VECTOR_DOCS` 와 운영 DB 만 본다(9.2 ⑤).
  · **근거 0건이면 LLM 을 부르지 않는다** — `검토 필요 — 근거 부족` + 담당자 이관(G-22).
  · LLM 키 없음 → **501 `LLM 미구성`**. 임베딩 없음 → 200 + `tsvector_keyword` 라벨(D-08).
  · 질의·응답·근거·응답시간을 `AGT_QUERY_LOGS` 에 **100% 기록**.
  · 추천 채택은 **승인 권한 없으면 403**, 기록은 `AGT_RECOMMENDATIONS`(G-24).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ...agent import prompts, retrieval, service, tools
from ...agent import llm as agent_llm
from ...ingest import collector
from .. import design, nav, rbac
from ..settings import settings
from ..templating import render
from ..util import http
from ..util.audit import audit

import conn  # noqa: E402

router = APIRouter()

SCREENS = (
    "MES-TD3-009", "MES-TD3-020",
    "MES-TD3-038", "MES-TD3-039", "MES-TD3-040", "MES-TD3-041", "MES-TD3-042",
)

AGENT_AREA = "AI Agent 통합관리"
EMPTY = http.not_collected("D-06")

# 화면 ↔ Agent 구분 ↔ '질의 내용(자연어)' 가 몇 번째 조회조건인지 (TD3 mockup 실측)
AGENTS: dict[str, tuple[str, int]] = {
    "MES-TD3-009": ("입고", 1),
    "MES-TD3-020": ("출하", 2),
    "MES-TD3-038": ("통합", 0),
}


def _screen(sid: str) -> nav.Screen:
    s = nav.by_id().get(sid)
    if s is None:
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


def _filters(request: Request, fields: list[str], form: dict[str, str] | None = None) -> dict[str, str]:
    src = form if form is not None else request.query_params
    return {f"q{i}": (src.get(f"q{i}") or "").strip() for i in range(len(fields))}


def _page(request: Request) -> tuple[int, int, int]:
    """`?page=&size=` — 기본 size 20 (contracts/api-contract.md §0-7)."""
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


def _n(sql: str, params: Any = ()) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


def _agent_badges() -> list[dict[str, str]]:
    s = settings()
    st = agent_llm.state()
    return [
        {"text": st.badge, "kind": "bad" if not st.configured else "notice"},
        {"text": f"검색 모드 {s.search_mode}", "kind": "notice"},
        {"text": s.h("RAG_CONFIDENCE_MIN").badge, "kind": "undetermined"},
        {"text": "폐쇄형 — 외부 검색 0", "kind": "notice"},
    ]


def _render_agent(request: Request, sid: str, answer: service.Answer | None,
                  filters: dict[str, str]):
    screen, td3, role = _guard(request, sid)
    agent_type, qi = AGENTS[sid]
    m = td3["mockup"]
    s = settings()
    return render(
        request, f"agt/{screen.no}.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=filters, agent_type=agent_type, answer=answer,
        badges=_agent_badges(), closed_note=prompts.CLOSED_LOOP_NOTE,
        threshold_badge=s.h("RAG_CONFIDENCE_MIN").badge,
        question_field=m["search_fields"][qi],
        toolset=tools.TOOLSETS[agent_type], rewiring=tools.REWIRING,
        corpus=retrieval.corpus_size(agent_type), vector_dim=retrieval.VECTOR_DIM,
        actions={"초기화": "조회조건을 비운다",
                 "리스크 확인": "get_fat_quality · get_claim_trace 도구로 조회한다",
                 "근거 보기": "응답 아래 근거 표에 실제 검색된 문서만 나온다"},
    )


def _user_id(request: Request) -> int | None:
    """세션 사용자. 없으면 역할로 찾는다 — **개발용 보조(D-40)**, 인증이 들어오면 사라진다."""
    sess = getattr(request.state, "session", None)
    uid = getattr(sess, "user_id", None)
    return int(uid) if uid is not None else service.resolve_user(_role(request))


def _role(request: Request) -> str:
    return getattr(request.state, "role_code", "") or ""


def _ask(request: Request, sid: str, filters: dict[str, str]) -> service.Answer:
    agent_type, qi = AGENTS[sid]
    return service.ask(filters.get(f"q{qi}", ""), agent_type=agent_type,
                       user_id=_user_id(request), role_code=_role(request))


# ── 009 입고 AI Agent · 020 출하 AI Agent · 038 통합 AI질의 ────────────────
@router.get("/inv/009")
async def inbound_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-009")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-009", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/inv/009")
async def inbound_agent_ask(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-009")
    form = dict(await request.form())
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-009", f)
    audit(request, screen.id, "AI질의", log_type="API")
    return _render_agent(request, "MES-TD3-009", answer, f)


@router.get("/shp/020")
async def outbound_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-020")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-020", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/shp/020")
async def outbound_agent_ask(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-020")
    form = dict(await request.form())
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-020", f)
    audit(request, screen.id, "AI질의", log_type="API")
    return _render_agent(request, "MES-TD3-020", answer, f)


@router.get("/agt/038")
async def unified_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-038")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-038", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/agt/038")
async def unified_agent_ask(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-038")
    form = dict(await request.form())
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-038", f)
    audit(request, screen.id, "AI질의", log_type="API")
    return _render_agent(request, "MES-TD3-038", answer, f)


# ── 039 생산/품질 분석 · 040 의사결정 지원 ────────────────────────────────
def _recommendations(reco_type: str | None, f: dict[str, str],
                     size: int = 20, off: int = 0) -> list[dict[str, Any]]:
    conds, params = [], []
    if reco_type:
        conds.append("r.RECO_TYPE = %s")
        params.append(reco_type)
    if f.get("q1"):
        conds.append("r.RECO_TYPE = %s")
        params.append(f["q1"])
    if f.get("q2"):
        conds.append("r.TARGET_TYPE = %s")
        params.append(f["q2"])
    if f.get("q3"):
        conds.append("r.REVIEW_STATUS = %s")
        params.append(f["q3"])
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    return conn.q(
        "select r.RECO_ID, r.CREATED_AT_DT, r.RECO_TYPE, r.TARGET_TYPE, r.TARGET_ID, "
        "       r.SUMMARY_TEXT, r.RECOMMEND_VALUE, r.EVIDENCE_JSON, r.REVIEW_STATUS, u.LOGIN_ID "
        "from AGT_RECOMMENDATIONS r left join SYS_USERS u on u.USER_ID = r.REVIEWER_ID "
        f"{where}order by r.CREATED_AT_DT desc, r.RECO_ID desc limit %s offset %s",
        [*params, size, off])


@router.get("/agt/039")
async def quality_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-039")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    rows = _recommendations("생산품질분석", f, size, off)
    grid = [_row([i, r["created_at_dt"], r["reco_type"], r["target_type"] or "",
                  r["summary_text"], r["review_status"], r["login_id"] or "-"])
            for i, r in enumerate(rows, 1)]
    audit(request, screen.id, "조회")
    return render(
        request, "agt/039.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid,
        empty_note=EMPTY + " — 분석 원천(공정실적·검사·편차)이 쌓이면 생성된다",
        badges=[{"text": "AI 는 추천까지 — 승인된 것만 반영 (G-24)", "kind": "notice"}],
        notices=[], can_approve=rbac.can_approve(role, AGENT_AREA),
        actions={"분석 실행": "PRC_PERFORMANCES·SHP_INSPECTIONS·PRC_CONDITION_DEVIATIONS 가 0건이면 분석하지 않는다",
                 "검토": "POST /api/agent/recommend/{id}/adopt",
                 "승인": "승인 권한 없으면 403 (G-24)",
                 "리포트": "승인된 추천만 운영 반영"},
    )


@router.get("/agt/040")
async def decision_support(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-040")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    rows = _recommendations(None, {**f, "q1": f.get("q2", ""), "q2": f.get("q0", ""),
                                   "q3": f.get("q3", "")}, size, off)
    grid = [_row([i, r["created_at_dt"], f"{r['target_type'] or ''} {r['target_id'] or ''}".strip(),
                  r["recommend_value"] or "", r["summary_text"], r["review_status"],
                  r["login_id"] or "-"]) for i, r in enumerate(rows, 1)]
    total = _n("select count(*) as n from AGT_RECOMMENDATIONS")
    adopted = _n("select count(*) as n from AGT_RECOMMENDATIONS where REVIEW_STATUS = '승인'")
    counts = {"total": total, "adopted": adopted,
              "adopt_rate": f"{adopted / total:.1%}" if total else None,
              "predictions": _n("select count(*) as n from EST_ML_PREDICTIONS")}
    audit(request, screen.id, "조회")
    return render(
        request, "agt/040.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY,
        badges=[{"text": "설비 직접 제어형 아님 (D-01)", "kind": "notice"},
                {"text": "AI 는 추천까지 (G-24)", "kind": "notice"}],
        notices=[], counts=counts, can_approve=rbac.can_approve(role, AGENT_AREA),
        actions={"추천 생성": "예측·표준조건이 있어야 생성된다",
                 "검토": "POST /api/agent/recommend/{id}/adopt",
                 "승인": "승인 권한 없으면 403 (G-24)",
                 "반영": "승인 이후에만 운영계획에 반영한다"},
    )


# ── 041 알림 및 추천 ──────────────────────────────────────────────────────
@router.get("/agt/041")
async def alerts(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-041")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    rows = conn.q(
        "select r.RECO_ID, r.CREATED_AT_DT, r.RECO_TYPE, r.TARGET_TYPE, r.TARGET_ID, "
        "       r.SUMMARY_TEXT, r.RECOMMEND_VALUE, r.REVIEW_STATUS "
        "from AGT_RECOMMENDATIONS r where r.RECO_TYPE = '알림추천' "
        "order by r.CREATED_AT_DT desc limit %s offset %s", (size, off))
    grid = [_row([i, r["created_at_dt"], r["reco_type"],
                  f"{r['target_type'] or ''} {r['target_id'] or ''}".strip(),
                  r["summary_text"], r["recommend_value"] or "",
                  "Y" if r["review_status"] != "미검토" else "N"])
            for i, r in enumerate(rows, 1)]
    rules = conn.q(
        "select CONFIG_KEY, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL "
        "from SYS_CONFIGS where CONFIG_TYPE = '알림기준' and USE_YN = 'Y' order by CONFIG_KEY")
    audit(request, screen.id, "조회")
    return render(
        request, "agt/041.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY,
        badges=[{"text": "수집 지점 2개소 (D-06)", "kind": "notice"},
                {"text": settings().h("INGEST_STALE_SEC").badge, "kind": "undetermined"}],
        notices=[], ingest=collector.status(), rules=rules,
        actions={"확인 처리": "AGT_RECOMMENDATIONS.REVIEW_STATUS 변경 — 승인 권한 필요",
                 "알림 기준": "028 알림 설정(개발1)이 정본",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


# ── 042 사용자 질문이력 ───────────────────────────────────────────────────
@router.get("/agt/042")
async def query_history(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-042")
    m = td3["mockup"]
    f = _filters(request, m["search_fields"])
    page, size, off = _page(request)
    rows = service.history(agent_type=f.get("q2") or None, keyword=f.get("q4") or None,
                           limit=size, offset=off)
    grid = [_row([i, r["queried_dt"], r["login_id"] or "-", r["agent_type"],
                  r["question_text"], r["response_ms"], r["feedback_score"]])
            for i, r in enumerate(rows, 1)]
    audit(request, screen.id, "조회")
    return render(
        request, "agt/042.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, empty_note=EMPTY + " — 질의가 없으면 이력도 없다 (런타임 전용 표)",
        badges=[{"text": "외부 반출 금지 — 접근 권한 통제", "kind": "bad"},
                {"text": "응답시간 목표치 없음 (D-09)", "kind": "undetermined"}],
        notices=[], stats=service.history_stats(),
        actions={"상세보기": "질의·응답·근거 문서 ID 를 함께 본다",
                 "재학습 반영": "학습이 있는 회전은 단독 기동 (§10-2)",
                 "엑셀": "질의 로그 반출은 금지 — DAT_DOWNLOAD_LOGS 통제 대상"},
    )


# ── Agent API (contracts/api-contract.md §5) ──────────────────────────────
@router.post("/api/agent/query")
async def api_query(request: Request, question: str = Form(...),
                    agent_type: str = Form("통합")):
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 조회 권한 없음")
    a = service.ask(question, agent_type=agent_type,
                    user_id=_user_id(request), role_code=role)
    return {
        "agent_type": a.agent_type, "grounded": a.grounded, "mode": a.mode,
        "confidence": a.confidence, "threshold": a.threshold, "response_ms": a.response_ms,
        "text": a.text, "notice": a.notice, "handover": a.handover,
        "sources": a.sources, "evidence_line": a.evidence_line, "query_id": a.query_id,
    }


@router.get("/api/agent/history")
async def api_history(request: Request, agent_type: str | None = None, limit: int = 50):
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 조회 권한 없음")
    return {"rows": service.history(agent_type=agent_type, limit=limit),
            "stats": service.history_stats()}


@router.post("/api/agent/recommend/{reco_id}/adopt")
async def api_adopt(request: Request, reco_id: int, decision: str = Form("승인")):
    """추천 채택 — **승인 권한이 없으면 403** (G-24).

    TD5 에 `ADOPT_YN`·`ADOPT_BY` 컬럼이 없다. `REVIEW_STATUS`·`REVIEWER_ID` 로 기록한다(D-302).
    """
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_approve(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 승인 권한 없음 — 추천을 반영할 수 없다 (G-24)")
    if decision not in ("승인", "수정", "반려"):
        raise http.fail("validation", "검토 상태는 승인/수정/반려 중 하나다 (TD5)")
    user_id = _user_id(request)
    if user_id is None:
        raise http.fail("unauthenticated", "검토자 계정을 확인할 수 없다")
    n = conn.x(
        "update AGT_RECOMMENDATIONS set REVIEW_STATUS = %s, REVIEWER_ID = %s, UPDATED_DT = now() "
        "where RECO_ID = %s", (decision, user_id, reco_id))
    if n == 0:
        raise http.fail("validation", f"추천 {reco_id} 가 없다")
    audit(request, "MES-TD3-040", f"추천채택:{decision}", log_type="변경")
    return RedirectResponse("/agt/040", status_code=303)


# ── 화면 없는 인터페이스 3종을 함께 싣는다 ────────────────────────────────
# `app/main.py` 는 **화면이 있는 모듈만** 임포트한다(`nav.all_screens()` 의 module 집합).
# `routers/ingest.py` 는 화면이 없어 그 집합에 없으므로, 여기서 실어 준다 — main.py 는 건드리지 않는다.
from . import ingest as _ingest  # noqa: E402

router.include_router(_ingest.router)
