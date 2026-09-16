"""AI Agent — 009 입고 · 020 출하 · 038~042 통합관리 (개발3).

`/inv/009` 와 `/shp/020` 은 **업무영역은 입고·출하, 구현은 여기**다(D-38).

이 파일이 지키는 것
  · **폐쇄형** — 외부 검색 0. 내부 `AGT_VECTOR_DOCS` 와 운영 DB 만 본다(9.2 ⑤).
  · **근거 0건이면 LLM 을 부르지 않는다** — `검토 필요 — 근거 부족` + 담당자 이관(G-22).
  · LLM 키 없음 → **501 `LLM 미구성`**. 임베딩 없음 → 200 + `tsvector_keyword` 라벨(D-08).
  · 질의·응답·근거·응답시간을 `AGT_QUERY_LOGS` 에 **100% 기록**.
  · 추천 채택은 **승인 권한 없으면 403**, 기록은 `AGT_RECOMMENDATIONS`(G-24).
  · **화면에 있는 칸은 전부 쓴다** — 009 자재 LOT · 020 제품 LOT·출하번호 · 038 업무영역은
    `service.ask(context=…)` 로 넘어가 도구 호출이 된다. 렌더만 하고 버리지 않는다.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote as _urlq

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...agent import prompts, retrieval, service, tools
from ...agent import llm as agent_llm
from ...ingest import collector
from .. import design, nav, rbac
from ..settings import settings
from ..templating import render
from ..util import csrf, http
from ..util.audit import RESULT_ERR, audit

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

# 질의 화면의 **나머지 칸** → `service.ask(context=…)` 의 키 (TD3 mockup 실측).
# 009 q0 자재 LOT 번호 · 020 q0 제품 LOT 번호 · q1 출하번호 · 038 q1 대상 업무영역.
CONTEXT_FIELDS: dict[str, dict[str, str]] = {
    "MES-TD3-009": {"q0": "material_lot"},
    "MES-TD3-020": {"q0": "product_lot", "q1": "shipment_no"},
    "MES-TD3-038": {"q1": "area"},
}

# TD5 `AGT_RECOMMENDATIONS.REVIEW_STATUS` 어휘 — 이 밖의 값을 쓰지 않는다
REVIEW_DECISIONS: tuple[str, ...] = ("승인", "수정", "반려")
ADOPT_SCREENS: tuple[str, ...] = ("MES-TD3-039", "MES-TD3-040", "MES-TD3-041")
NO_APPROVE = f"{AGENT_AREA} 승인 권한 없음 — 추천을 반영할 수 없다 (G-24 · G-28)"

QUALITY_RECO = "생산품질분석"
ALERT_RECO = "알림추천"

# 추천 대상(`TARGET_TYPE` + `TARGET_ID`) → 사람이 읽는 번호와 이동 경로.
# 숫자 ID 만 보여 주면 어느 프로젝트인지 화면을 뒤져야 한다.
TARGET_LABELS: dict[str, tuple[str, str, str, str]] = {
    "프로젝트": ("EST_PROJECTS", "PROJECT_ID", "PROJECT_NO", "/prc/024?project="),
    "견적": ("EST_QUOTATIONS", "QUOTE_ID", "QUOTE_NO", "/est/012?quote="),
    "BOM": ("EST_BOM_HEADERS", "BOM_ID", "BOM_NO", "/est/013?bom="),
    "작업지시": ("PRC_WORK_ORDERS", "WORK_ORDER_ID", "WORK_ORDER_NO", ""),
    "출하": ("SHP_SHIPMENTS", "SHIPMENT_ID", "SHIPMENT_NO", ""),
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


def _cell(text: Any, link: str | None = None) -> dict[str, Any]:
    return {"text": "" if text is None else str(text), "link": link}


def _row(cells: list[Any], links: dict[int, str | None] | None = None,
         extra: list[dict[str, Any]] | None = None, form_id: Any = None,
         form_action: str = "") -> dict[str, Any]:
    return {"cells": ["" if c is None else str(c) for c in cells],
            "links": {i: u for i, u in (links or {}).items() if u},
            "extra": extra or [],
            "form_id": "" if form_id is None else str(form_id),
            "form_action": form_action}


def _period_parse(value: str) -> tuple[date, date] | None:
    """`YYYY-MM-DD` 또는 `YYYY-MM-DD~YYYY-MM-DD`. 읽지 못하면 `None`."""
    parts = value.replace(" ", "").split("~")
    if len(parts) > 2 or not parts[0]:
        return None
    try:
        days = [date.fromisoformat(p) for p in parts]
    except ValueError:
        return None
    start, end = days[0], days[-1]
    return None if end < start else (start, end)


def _period_filter(value: str, column: str, label: str, conds: list[str],
                   params: list[Any], notices: list[str]) -> None:
    """기간 조건을 건다. **읽지 못하면 거르지 않은 척하지 않고 0건으로 돌려주고 적는다.**

    §2.5 만 보면 422 감이고 화면 010 기간 칸은 실제로 422 다. 그런데 039·041·042 는
    **기간이 첫 번째 조회조건(q0)** 이라, QA1 이 45화면에 공통으로 거는 계약
    (`존재하지 않는 조회조건 → 200 · 0건 표지`)과 정면으로 부딪힌다. 둘 중 **조용하지 않은
    쪽**을 고른다 — 0건을 내되 왜 0건인지 화면 맨 위에 적는다. 전체 목록을 내주는 것이
    제일 나쁘다: 거른 줄 알고 읽는다. (어느 쪽을 정본으로 할지는 아키텍트 판단 대상)
    """
    got = _period_parse(value)
    if got is None:
        conds.append("false")
        notices.append(
            f"{label} {value!r} 를 날짜로 읽지 못했다 — 'YYYY-MM-DD' 또는 "
            f"'YYYY-MM-DD~YYYY-MM-DD' 다. **조건을 무시하지 않고 0건으로 둔다.**")
        return
    start, end = got
    conds.append(f"{column} >= %s and {column} < %s")
    params += [start, end + timedelta(days=1)]


def _int(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise http.fail("validation", f"{label} 은 정수여야 한다: {value!r}") from None


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
    ctx_fields = [{"field": m["search_fields"][int(k[1:])], "key": v, "value": filters.get(k, "")}
                  for k, v in CONTEXT_FIELDS.get(sid, {}).items()]
    return render(
        request, f"agt/{screen.no}.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=filters, agent_type=agent_type, answer=answer,
        badges=_agent_badges(), closed_note=prompts.CLOSED_LOOP_NOTE,
        threshold_badge=s.h("RAG_CONFIDENCE_MIN").badge,
        question_field=m["search_fields"][qi], context_fields=ctx_fields,
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
    """질의 + **화면의 나머지 칸**(자재 LOT · 제품 LOT · 출하번호 · 업무영역)."""
    agent_type, qi = AGENTS[sid]
    context = {key: filters.get(qk, "") for qk, key in CONTEXT_FIELDS.get(sid, {}).items()}
    return ask_audited(request, sid, filters.get(f"q{qi}", ""), agent_type, context=context)


def ask_audited(request: Request, screen_id: str | None, question: str,
                agent_type: str, context: dict[str, str] | None = None) -> service.Answer:
    """질의 1건 = `SYS_ACCESS_LOGS` 'API' 1행. **성공·실패 갈래를 모두** 남긴다.

    전에는 `audit()` 이 호출 **뒤**에 있어 LLM 미구성 501 갈래가 기록을 건너뛰었다 —
    감사가 성공한 질의만 보게 된다(G-29 실측 '기록 0 행'). 감사는 여기 한 곳에서 한다.
    """
    try:
        answer = service.ask(question, agent_type=agent_type,
                             user_id=_user_id(request), role_code=_role(request),
                             context=context)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        audit(request, screen_id, "AI질의", log_type="API", result=RESULT_ERR,
              error=f"{e.status_code} {detail.get('message', '')}")
        raise
    audit(request, screen_id, "AI질의", log_type="API")
    return answer


# ── 009 입고 AI Agent · 020 출하 AI Agent · 038 통합 AI질의 ────────────────
@router.get("/inv/009")
async def inbound_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-009")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-009", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/inv/009")
async def inbound_agent_ask(request: Request):
    raw = await request.form()
    csrf.require(request, csrf.token_of(request, raw))    # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3, _ = _guard(request, "MES-TD3-009")
    form = dict(raw)
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-009", f)
    return _render_agent(request, "MES-TD3-009", answer, f)


@router.get("/shp/020")
async def outbound_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-020")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-020", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/shp/020")
async def outbound_agent_ask(request: Request):
    raw = await request.form()
    csrf.require(request, csrf.token_of(request, raw))    # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3, _ = _guard(request, "MES-TD3-020")
    form = dict(raw)
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-020", f)
    return _render_agent(request, "MES-TD3-020", answer, f)


@router.get("/agt/038")
async def unified_agent(request: Request):
    screen, td3, _ = _guard(request, "MES-TD3-038")
    audit(request, screen.id, "조회")
    return _render_agent(request, "MES-TD3-038", None,
                         _filters(request, td3["mockup"]["search_fields"]))


@router.post("/agt/038")
async def unified_agent_ask(request: Request):
    raw = await request.form()
    csrf.require(request, csrf.token_of(request, raw))    # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, td3, _ = _guard(request, "MES-TD3-038")
    form = dict(raw)
    f = _filters(request, td3["mockup"]["search_fields"], form)
    answer = _ask(request, "MES-TD3-038", f)
    return _render_agent(request, "MES-TD3-038", answer, f)


# ── 039 생산/품질 분석 · 040 의사결정 지원 · 041 알림 ─────────────────────
def _reco_where(conds: list[str], params: list[Any]) -> str:
    return ("where " + " and ".join(conds) + " ") if conds else ""


_RECO_SRC = ("from AGT_RECOMMENDATIONS r left join SYS_USERS u on u.USER_ID = r.REVIEWER_ID ")


def _recommendations(conds: list[str], params: list[Any],
                     size: int = 20, off: int = 0) -> list[dict[str, Any]]:
    where = _reco_where(conds, params)
    return conn.q(
        "select r.RECO_ID, r.CREATED_AT_DT, r.RECO_TYPE, r.TARGET_TYPE, r.TARGET_ID, "
        "       r.SUMMARY_TEXT, r.RECOMMEND_VALUE, r.EVIDENCE_JSON, r.REVIEW_STATUS, u.LOGIN_ID "
        f"{_RECO_SRC}{where}order by r.CREATED_AT_DT desc, r.RECO_ID desc limit %s offset %s",
        [*params, size, off])


def _reco_count(conds: list[str], params: list[Any]) -> int:
    return _n(f"select count(*) as n {_RECO_SRC}{_reco_where(conds, params)}", params)


def _target(target_type: str | None, target_id: Any) -> dict[str, Any]:
    """`대상` 칸 — 번호로 풀 수 있으면 풀고, 못 풀면 **구분 + ID 를 그대로** 둔다."""
    raw = f"{target_type or ''} {target_id if target_id is not None else ''}".strip()
    spec = TARGET_LABELS.get(str(target_type or ""))
    if spec is None or target_id is None:
        return _cell(raw or "-")
    table, key, label, href = spec
    row = conn.q1(f"select {label} as v from {table} where {key} = %s", (int(target_id),))
    if row is None or row["v"] is None:
        return _cell(f"{raw} (대상 행 없음)")
    return _cell(f"{target_type} {row['v']}", f"{href}{_urlq(str(row['v']))}" if href else None)


def _adopt_form(can: bool, screen_id: str, title: str, button: str) -> dict[str, Any]:
    return {"title": title, "button": button, "can": can, "note": NO_APPROVE,
            "screen_id": screen_id, "id_name": "reco_id",
            "selects": [{"name": "decision", "label": "검토 상태",
                         "options": list(REVIEW_DECISIONS), "required": True}],
            "texts": []}


@router.get("/agt/039")
async def quality_analysis(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-039")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf)
    page, size, off = _page(request)
    conds: list[str] = ["r.RECO_TYPE = %s"]
    params: list[Any] = [QUALITY_RECO]
    notices: list[str] = []
    if f["q0"]:                                   # 분석 기간
        _period_filter(f["q0"], "r.CREATED_AT_DT", sf[0], conds, params, notices)
    if f["q1"] and f["q1"] != QUALITY_RECO:
        # 전에는 `RECO_TYPE` 조건을 **두 번** 걸어 다른 값이면 조용히 0건이었다 —
        # 거른 게 아니라 이 화면의 범위 밖이라는 사실을 말한다.
        raise http.fail("validation",
                        f"{screen.no} 화면은 '{QUALITY_RECO}' 추천만 본다 — "
                        f"{sf[1]} {f['q1']!r} 는 040 의사결정 지원에서 조회한다")
    if f["q2"]:
        conds.append("r.TARGET_TYPE = %s")
        params.append(f["q2"])
    if f["q3"]:
        conds.append("r.REVIEW_STATUS = %s")
        params.append(f["q3"])
    rows = _recommendations(conds, params, size, off)
    total = _reco_count(conds, params)
    can_approve = rbac.can_approve(role, AGENT_AREA)
    grid = [_row([off + i, r["created_at_dt"], r["reco_type"], r["target_type"] or "",
                  r["summary_text"], r["review_status"], r["login_id"] or "-"],
                 extra=[_target(r["target_type"], r["target_id"])],
                 form_id=r["reco_id"],
                 form_action=f"/api/agent/recommend/{r['reco_id']}/adopt")
            for i, r in enumerate(rows, 1)]
    audit(request, screen.id, "조회")
    return render(
        request, "agt/039.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total, extra_columns=["대상 번호"],
        empty_note=EMPTY + " — 분석 원천(공정실적·검사·편차)이 쌓이면 생성된다",
        badges=[{"text": "AI 는 추천까지 — 승인된 것만 반영 (G-24)", "kind": "notice"}],
        notices=notices, can_approve=can_approve,
        row_form=_adopt_form(can_approve, screen.id, "검토·승인 (G-24)", "검토 반영"),
        actions={"분석 실행": "PRC_PERFORMANCES·SHP_INSPECTIONS·PRC_CONDITION_DEVIATIONS 가 0건이면 분석하지 않는다",
                 "검토": "행마다 붙은 '검토 반영' 폼 — POST /api/agent/recommend/{id}/adopt",
                 "승인": "승인 권한 없으면 403 (G-24)",
                 "리포트": "승인된 추천만 운영 반영"},
    )


@router.get("/agt/040")
async def decision_support(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-040")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf)
    page, size, off = _page(request)
    conds: list[str] = []
    params: list[Any] = []
    notices: list[str] = []
    if f["q0"]:                                   # 대상 구분
        conds.append("r.TARGET_TYPE = %s")
        params.append(f["q0"])
    if f["q1"]:                                   # 대상 ID — TD5 는 BIGINT 다
        conds.append("r.TARGET_ID = %s")
        params.append(_int(f["q1"], sf[1]))
    if f["q2"]:                                   # 추천 구분
        conds.append("r.RECO_TYPE = %s")
        params.append(f["q2"])
    if f["q3"]:
        conds.append("r.REVIEW_STATUS = %s")
        params.append(f["q3"])
    if f["q4"]:
        _period_filter(f["q4"], "r.CREATED_AT_DT", sf[4], conds, params, notices)
    rows = _recommendations(conds, params, size, off)
    total = _reco_count(conds, params)
    can_approve = rbac.can_approve(role, AGENT_AREA)
    grid = []
    for i, r in enumerate(rows, 1):
        tgt = _target(r["target_type"], r["target_id"])
        grid.append(_row([off + i, r["created_at_dt"], tgt["text"],
                          r["recommend_value"] or "", r["summary_text"], r["review_status"],
                          r["login_id"] or "-"],
                         links={2: tgt["link"]}, form_id=r["reco_id"],
                         form_action=f"/api/agent/recommend/{r['reco_id']}/adopt"))
    all_n = _n("select count(*) as n from AGT_RECOMMENDATIONS")
    adopted = _n("select count(*) as n from AGT_RECOMMENDATIONS where REVIEW_STATUS = '승인'")
    counts = {"total": all_n, "adopted": adopted,
              "adopt_rate": f"{adopted / all_n:.1%}" if all_n else None,
              "predictions": _n("select count(*) as n from EST_ML_PREDICTIONS")}
    audit(request, screen.id, "조회")
    return render(
        request, "agt/040.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total, empty_note=EMPTY,
        badges=[{"text": "설비 직접 제어형 아님 (D-01)", "kind": "notice"},
                {"text": "AI 는 추천까지 (G-24)", "kind": "notice"}],
        notices=notices, counts=counts, can_approve=can_approve,
        row_form=_adopt_form(can_approve, screen.id, "검토·승인 (G-24)", "검토 반영"),
        actions={"추천 생성": "예측·표준조건이 있어야 생성된다",
                 "검토": "행마다 붙은 '검토 반영' 폼 — POST /api/agent/recommend/{id}/adopt",
                 "승인": "승인 권한 없으면 403 (G-24)",
                 "반영": "승인 이후에만 운영계획에 반영한다"},
    )


# ── 041 알림 및 추천 ──────────────────────────────────────────────────────
@router.get("/agt/041")
async def alerts(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-041")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf)
    page, size, off = _page(request)
    conds: list[str] = ["r.RECO_TYPE = %s"]
    params: list[Any] = [ALERT_RECO]
    notices: list[str] = []
    if f["q0"]:                                   # 발생 기간
        _period_filter(f["q0"], "r.CREATED_AT_DT", sf[0], conds, params, notices)
    if f["q1"]:                                   # 알림 유형 — TD5 는 RECO_TYPE 한 칸뿐이다
        conds.append("r.RECO_TYPE ilike %s")
        params.append(f"%{f['q1']}%")
    if f["q2"]:
        conds.append("r.TARGET_TYPE = %s")
        params.append(f["q2"])
    if f["q4"]:                                   # 확인 여부 — REVIEW_STATUS 로 본다
        want = f["q4"].upper()
        if want not in ("Y", "N"):
            raise http.fail("validation", f"{sf[4]} 는 Y 또는 N 이다: {f['q4']!r}")
        conds.append("r.REVIEW_STATUS <> %s" if want == "Y" else "r.REVIEW_STATUS = %s")
        params.append("미검토")
    rows = _recommendations(conds, params, size, off)
    total = _reco_count(conds, params)
    can_approve = rbac.can_approve(role, AGENT_AREA)
    grid = []
    for i, r in enumerate(rows, 1):
        tgt = _target(r["target_type"], r["target_id"])
        grid.append(_row([off + i, r["created_at_dt"], r["reco_type"], tgt["text"],
                          r["summary_text"], r["recommend_value"] or "",
                          "Y" if r["review_status"] != "미검토" else "N"],
                         links={3: tgt["link"]}, form_id=r["reco_id"],
                         form_action=f"/api/agent/recommend/{r['reco_id']}/adopt"))
    # 발송 채널은 `AGT_RECOMMENDATIONS` 에 컬럼이 없다 — 알림 **기준표**에 건다.
    rule_conds, rule_params = ["CONFIG_TYPE = '알림기준'", "USE_YN = 'Y'"], []
    if f["q3"]:
        rule_conds.append("ALERT_CHANNEL = %s")
        rule_params.append(f["q3"])
    rules = conn.q(
        "select CONFIG_KEY, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL "
        f"from SYS_CONFIGS where {' and '.join(rule_conds)} order by CONFIG_KEY", rule_params)
    audit(request, screen.id, "조회")
    return render(
        request, "agt/041.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total, empty_note=EMPTY,
        badges=[{"text": "수집 지점 2개소 (D-06)", "kind": "notice"},
                {"text": settings().h("INGEST_STALE_SEC").badge, "kind": "undetermined"}],
        notices=notices + [f"{sf[3]} 은 `AGT_RECOMMENDATIONS` 에 컬럼이 없다(TD5) — 아래 "
                           f"'등록된 알림 기준'(SYS_CONFIGS.ALERT_CHANNEL)에만 적용했다"],
        ingest=collector.status(), rules=rules, can_approve=can_approve,
        row_form=_adopt_form(can_approve, screen.id, "확인 처리 (G-24)", "확인 처리"),
        actions={"확인 처리": "행마다 붙은 폼이 REVIEW_STATUS 를 바꾼다 — 승인 권한 필요",
                 "알림 기준": "028 알림 설정(개발1)이 정본",
                 "엑셀": "다운로드는 권한 통제 대상 (9.2 ①)"},
    )


# ── 042 사용자 질문이력 ───────────────────────────────────────────────────
@router.get("/agt/042")
async def query_history(request: Request):
    screen, td3, role = _guard(request, "MES-TD3-042")
    m = td3["mockup"]
    sf = m["search_fields"]
    f = _filters(request, sf)
    page, size, off = _page(request)
    sel: dict[str, Any] = {}
    notices: list[str] = []
    if f["q0"]:                                   # 기간
        pc: list[str] = []
        pp: list[Any] = []
        _period_filter(f["q0"], "l.QUERIED_DT", sf[0], pc, pp, notices)
        sel["period_sql"], sel["period_params"] = pc[0], pp
    if f["q1"]:                                   # 사용자 — 숫자면 USER_ID, 아니면 로그인ID
        if f["q1"].isdigit():
            sel["user_id"] = int(f["q1"])
        else:
            sel["login_id"] = f["q1"]
    if f["q2"]:
        sel["agent_type"] = f["q2"]
    if f["q3"]:                                   # 평가 점수
        score = _int(f["q3"], sf[3])
        if score < service.FEEDBACK_MIN or score > service.FEEDBACK_MAX:
            raise http.fail("validation",
                            f"{sf[3]} 는 {service.FEEDBACK_MIN}~{service.FEEDBACK_MAX} 다: {score}")
        sel["score"] = score
    if f["q4"]:
        sel["keyword"] = f["q4"]
    rows = service.history(limit=size, offset=off, **sel)
    total = service.history_count(**sel)
    grid = [_row([off + i, r["queried_dt"], r["login_id"] or "-", r["agent_type"],
                  r["question_text"], r["response_ms"],
                  r["feedback_score"] if r["feedback_score"] is not None
                  else http.not_collected("D-09")],
                 links={4: f"/agt/042/{r['query_id']}"})
            for i, r in enumerate(rows, 1)]
    audit(request, screen.id, "조회")
    return render(
        request, "agt/042.html", screen=screen, current=screen, td3=td3, mockup=m,
        filters=f, rows=grid, total=total,
        empty_note=EMPTY + " — 질의가 없으면 이력도 없다 (런타임 전용 표)",
        badges=[{"text": "외부 반출 금지 — 접근 권한 통제", "kind": "bad"},
                {"text": "응답시간 목표치 없음 (D-09)", "kind": "undetermined"}],
        notices=notices, stats=service.history_stats(),
        actions={"상세보기": "질의 내용을 누르면 질의·응답·근거 문서를 함께 본다",
                 "재학습 반영": "학습이 있는 회전은 단독 기동 (§10-2)",
                 "엑셀": "질의 로그 반출은 금지 — DAT_DOWNLOAD_LOGS 통제 대상"},
    )


@router.get("/agt/042/{query_id}")
async def query_detail(request: Request, query_id: int):
    """질의 1건 상세 — 질의·응답·**그때 실제로 읽은 근거 문서**와 사용자 평가 폼."""
    screen, td3, role = _guard(request, "MES-TD3-042")
    row = service.query_log(query_id)
    if row is None:
        raise http.fail("validation", f"질의 {query_id} 가 없다")
    docs = service.ref_docs(row["ref_doc_ids"], role)
    listed = {int(d["doc_id"]) for d in docs}
    asked = [int(x) for x in str(row["ref_doc_ids"] or "").split(",") if x.strip().isdigit()]
    hidden = [i for i in asked if i not in listed]
    audit(request, screen.id, "조회")
    return render(
        request, "agt/042_detail.html", screen=screen, current=screen, td3=td3,
        mockup=td3["mockup"], log=row, docs=docs, hidden=hidden,
        scores=list(range(service.FEEDBACK_MIN, service.FEEDBACK_MAX + 1)),
        can_score=rbac.can_read(role, AGENT_AREA),
        badges=[{"text": "외부 반출 금지 — 접근 권한 통제", "kind": "bad"},
                {"text": "근거는 질의 시점 기록뿐 — 다시 검색하지 않는다", "kind": "notice"}],
    )


@router.post("/agt/042/{query_id}/feedback")
async def query_feedback(request: Request, query_id: int):
    """`AGT_QUERY_LOGS.FEEDBACK_SCORE` 를 쓰는 **유일한 경로** — 전에는 쓰는 곳이 없었다."""
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    screen, _td3, role = _guard(request, "MES-TD3-042")
    raw = str(form.get("score") or "").strip()
    if not raw:
        raise http.fail("validation", "필수값 누락: score")
    service.set_feedback(query_id, _int(raw, "사용자 평가"), _user_id(request))
    audit(request, screen.id, f"질의평가:{raw}", log_type="변경")
    return RedirectResponse(f"/agt/042/{query_id}", status_code=303)


@router.get("/agt/doc/{doc_id}")
async def vector_doc(request: Request, doc_id: int):
    """근거 문서 1청크 **읽기 전용**. 검색과 같은 `ACCESS_ROLE` 통제를 지난다(9.2 ⑤)."""
    role = _role(request)
    if not rbac.can_read(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 조회 권한 없음")
    row = conn.q1(
        "select DOC_ID, DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT, ACCESS_ROLE, "
        "       EMBED_MODEL, (EMBEDDING is not null) as embedded "
        "from AGT_VECTOR_DOCS where DOC_ID = %s "
        "  and (ACCESS_ROLE is null or ACCESS_ROLE = %s)", (doc_id, role or ""))
    if row is None:
        # 없는 것과 못 보는 것을 **같은 문구로** 돌려준다 — 존재 여부가 새지 않게 한다.
        raise http.fail("validation", f"문서 {doc_id} 를 이 역할로는 볼 수 없다")
    audit(request, "MES-TD3-042", f"근거문서조회:{doc_id}")
    return render(request, "agt/doc.html", doc=row, current=None,
                  screen=_screen("MES-TD3-042"))


# ── Agent API (contracts/api-contract.md §5) ──────────────────────────────
@router.post("/api/agent/query")
async def api_query(request: Request):
    """Agent 질의 API. 폼 본문이므로 `_csrf` 필드로, 헤더 클라이언트는 `X-CSRF-Token` 으로 싣는다."""
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    question = str(form.get("question") or "").strip()
    agent_type = str(form.get("agent_type") or "통합").strip()
    if not question:
        raise http.fail("validation", "필수값 누락: question")
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 조회 권한 없음")
    a = ask_audited(request, None, question, agent_type)
    return {
        "agent_type": a.agent_type, "grounded": a.grounded, "mode": a.mode,
        "confidence": a.confidence, "threshold": a.threshold, "response_ms": a.response_ms,
        "text": a.text, "notice": a.notice, "handover": a.handover,
        "sources": a.sources, "evidence_line": a.evidence_line, "query_id": a.query_id,
        "tools_used": a.tools_used, "db_refs": a.db_refs,
    }


@router.get("/api/agent/history")
async def api_history(request: Request, agent_type: str | None = None, limit: int = 50):
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 조회 권한 없음")
    return {"rows": service.history(agent_type=agent_type, limit=limit),
            "stats": service.history_stats()}


@router.post("/api/agent/recommend/{reco_id}/adopt")
async def api_adopt(request: Request, reco_id: int):
    """추천 채택 — **승인 권한이 없으면 403** (G-24).

    TD5 에 `ADOPT_YN`·`ADOPT_BY` 컬럼이 없다. `REVIEW_STATUS`·`REVIEWER_ID` 로 기록한다(D-302).
    `decision` 은 **필수**다 — 빈 본문이 '승인' 으로 굳는 기본값을 두지 않는다(G-24).
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    decision = str(form.get("decision") or "").strip()
    screen_id = str(form.get("screen_id") or "").strip()
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_approve(role, AGENT_AREA):
        raise http.fail("forbidden", f"{AGENT_AREA} 승인 권한 없음 — 추천을 반영할 수 없다 (G-24)")
    if not decision:
        raise http.fail("validation", f"필수값 누락: decision (검토 상태 {REVIEW_DECISIONS})")
    if decision not in REVIEW_DECISIONS:
        raise http.fail("validation", "검토 상태는 승인/수정/반려 중 하나다 (TD5)")
    if screen_id and screen_id not in ADOPT_SCREENS:
        raise http.fail("validation", f"이 경로를 부르는 화면이 아니다: {screen_id!r} {ADOPT_SCREENS}")
    user_id = _user_id(request)
    if user_id is None:
        raise http.fail("unauthenticated", "검토자 계정을 확인할 수 없다")
    n = conn.x(
        "update AGT_RECOMMENDATIONS set REVIEW_STATUS = %s, REVIEWER_ID = %s, UPDATED_DT = now() "
        "where RECO_ID = %s", (decision, user_id, reco_id))
    if n == 0:
        raise http.fail("validation", f"추천 {reco_id} 가 없다")
    # **어느 화면에서 눌렀는지** 를 남긴다 — 040 으로 고정하면 039·041 의 승인이 040 기록이 된다.
    audit(request, screen_id or None, f"추천채택:{decision}", log_type="변경")
    back = _screen(screen_id).path if screen_id in ADOPT_SCREENS else "/agt/040"
    return RedirectResponse(back, status_code=303)


# ── 화면 없는 인터페이스 3종을 함께 싣는다 ────────────────────────────────
# `app/main.py` 는 **화면이 있는 모듈만** 임포트한다(`nav.all_screens()` 의 module 집합).
# `routers/ingest.py` 는 화면이 없어 그 집합에 없으므로, 여기서 실어 준다 — main.py 는 건드리지 않는다.
from . import ingest as _ingest  # noqa: E402

router.include_router(_ingest.router)
