"""Agent 실행 — 근거 우선, 로그 100%, 조용한 폴백 0.

순서를 바꾸지 않는다.
  ① 폐쇄형 검색(`AGT_VECTOR_DOCS`)
  ② **근거 0건이면 LLM 을 부르지 않는다** — `검토 필요 — 근거 부족` + 담당자 이관 (G-22)
  ③ 신뢰도가 임계(`RAG_CONFIDENCE_MIN`, 가설 D-10) 미만이면 같은 분기로 간다
  ④ 그다음에야 LLM. 키가 없으면 **501 `LLM 미구성`** (D-08)
  ⑤ 어느 갈래로 끝나든 `AGT_QUERY_LOGS` 에 **질의·응답·근거·응답시간**을 남긴다

②는 임계값과 무관하게 **항상** 적용된다(D-10 처리란).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import conn

from ..app.settings import settings
from ..app.util import http
from . import citations, llm, prompts, retrieval, tools
from . import AGENT_TYPES


@dataclass
class Answer:
    question: str
    agent_type: str
    text: str
    evidence: list[retrieval.Evidence] = field(default_factory=list)
    mode: str = retrieval.MODE_KEYWORD
    confidence: float = 0.0
    threshold: float = 0.0
    response_ms: int = 0
    grounded: bool = False
    notice: str = ""
    handover: str = ""
    query_id: int | None = None
    tools_used: list[str] = field(default_factory=list)
    llm_state: llm.LlmState | None = None
    lookups: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, str] = field(default_factory=dict)

    @property
    def sources(self) -> list[str]:
        """**실제로 검색된 문서명만.** 운영 DB 조회는 문서가 아니므로 여기 섞지 않는다."""
        return citations.sources(self.evidence)

    @property
    def db_refs(self) -> list[str]:
        """화면 조회조건으로 **실제로 조회한** 운영 DB 근거 (TD5 표 + 건수)."""
        return [f"{o['table']} {o['value']} {o['count']}행" for o in self.lookups]

    @property
    def evidence_line(self) -> str:
        """근거줄. **문서 근거가 0건이면 DB 조회를 근거로 승격하지 않는다** (G-22).

        0건 분기의 문구는 `근거: 확인된 자료 없음` 그대로여야 한다 — DB 행이 있다고
        문서 근거가 생긴 것이 아니다. 조회 결과는 화면의 별도 표로 따로 보인다.
        """
        return citations.evidence_line(self.evidence, self.db_refs if self.evidence else ())


def resolve_user(role_code: str) -> int | None:
    """세션이 없을 때 역할로 계정을 찾는다 — **개발용 보조다(D-40).**

    `AGT_QUERY_LOGS.USER_ID` 는 NOT NULL FK 라 사용자를 모르면 질의를 기록할 수 없고,
    그러면 "질의 100% 기록" 이 깨진다. 개발1 이 인증을 넣으면 세션이 이 자리를 대체하고
    이 함수는 쓰이지 않는다 — 남아 있으면 `main.py` 의 역할 전환 미들웨어와 함께 지운다.
    """
    if not role_code:
        return None
    row = conn.q1(
        "select min(u.USER_ID) as uid from SYS_USERS u "
        "join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID "
        "where p.ROLE_CODE = %s and u.USE_YN = 'Y'", (role_code,))
    return int(row["uid"]) if row and row["uid"] is not None else None


def _log(question: str, agent_type: str, user_id: int | None, answer_text: str,
         evidence: list[retrieval.Evidence], ms: int, queried_dt: Any) -> int | None:
    """**100% 기록.** 로그 실패를 삼키지 않는다 — 여기서 예외가 나면 그대로 올라간다(G-30)."""
    if user_id is None:
        # TD5 `AGT_QUERY_LOGS.USER_ID` 는 NOT NULL FK 다. 사용자를 모르면 기록할 수 없다 —
        # 기록하지 못했다는 사실을 숨기지 않고 호출자에게 알린다.
        return None
    row = conn.q1(
        "insert into AGT_QUERY_LOGS "
        "(USER_ID, AGENT_TYPE, QUESTION_TEXT, ANSWER_TEXT, REF_DOC_IDS, RESPONSE_MS, QUERIED_DT, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s, now()) returning QUERY_ID",
        (user_id, agent_type, question, answer_text,
         citations.ref_doc_ids(evidence), ms, queried_dt),
    )
    return int(row["query_id"]) if row else None


def _lookups(agent_type: str, context: dict[str, str], role_code: str) -> tuple[list[dict[str, Any]], list[str]]:
    """화면 조회조건(자재 LOT · 제품 LOT · 출하번호) → **실제 도구 호출**.

    빈 칸은 부르지 않는다. 부른 것만 `tools_used` 에 남는다 — 전에는 정의 11종을 통째로
    적어 "이 도구를 썼다" 가 거짓이었다. 도구가 오류를 내면 **그 사실을 그대로** 싣는다.
    """
    out: list[dict[str, Any]] = []
    used: list[str] = []
    for spec in tools.CONTEXT_TOOLS.get(agent_type, ()):
        value = (context.get(spec["key"]) or "").strip()
        if not value:
            continue
        args = {**spec["fixed"], spec["arg"]: value}
        payload = json.loads(tools.execute(spec["tool"], args,
                                           agent_type=agent_type, role_code=role_code))
        used.append(spec["tool"])
        rows = (payload.get("result") or {}).get(spec["rows"]) or []
        out.append({"tool": spec["tool"], "label": spec["label"], "value": value,
                    "table": spec["table"], "rows": rows, "count": len(rows),
                    "error": payload.get("error", ""),
                    "note": (payload.get("result") or {}).get("note", "")})
    return out, used


def ask(question: str, *, agent_type: str = "통합", user_id: int | None = None,
        role_code: str = "", context: dict[str, str] | None = None) -> Answer:
    if agent_type not in AGENT_TYPES:
        raise http.fail("validation", f"Agent 구분 어휘 위반: {agent_type!r} (TD5 {AGENT_TYPES})")
    q = (question or "").strip()
    if not q:
        raise http.fail("validation", "질의 내용을 입력해 주세요")

    s = settings()
    threshold = s.h("RAG_CONFIDENCE_MIN").as_float()
    started = time.perf_counter()
    queried_dt = conn.q1("select now() as n")["n"]

    evidence, mode = retrieval.search(q, agent_type=agent_type, role_code=role_code)
    score = retrieval.confidence(evidence)
    ctx = {k: v for k, v in (context or {}).items() if v}
    lookups, used = _lookups(agent_type, ctx, role_code)
    ms = int((time.perf_counter() - started) * 1000)

    # ② · ③ 근거가 없거나 임계 미만 — **LLM 을 부르지 않는다**
    if not evidence or score < threshold:
        text = http.NOTICE_RAG_NO_EVIDENCE
        ans = Answer(
            question=q, agent_type=agent_type, text=text, evidence=evidence, mode=mode,
            confidence=score, threshold=threshold, response_ms=ms, grounded=False,
            notice=(f"근거 0건 — {http.NOTICE_RAG_NO_EVIDENCE}" if not evidence
                    else f"신뢰도 {score:.4f} < 임계 {threshold} ({s.h('RAG_CONFIDENCE_MIN').badge})"),
            handover=prompts.HANDOVER_NOTE, llm_state=llm.state(),
            lookups=lookups, tools_used=used, context=ctx,
        )
        ans.query_id = _log(q, agent_type, user_id, text, evidence, ms, queried_dt)
        return ans

    # ④ 여기서부터 LLM. 키가 없으면 501 — 단, **로그는 먼저 남긴다**(100% 기록)
    st = llm.state()
    if not st.configured:
        ms = int((time.perf_counter() - started) * 1000)
        _log(q, agent_type, user_id, f"{st.badge} — {st.reason}", evidence, ms, queried_dt)
        raise http.fail("llm_unconfigured", st.reason)

    blocks = [f"[{e.doc_name} #{e.chunk_seq}] {e.chunk_text}" for e in evidence]
    # 화면 조회조건은 **조회한 결과만** 맥락에 넣는다. 값만 넣고 조회하지 않으면
    # 모델이 그 LOT 를 아는 것처럼 답한다.
    blocks += [f"[운영 DB {o['table']} · {o['label']} {o['value']}] {o['count']}행: {o['rows']}"
               for o in lookups]
    if ctx.get("area"):
        blocks.append(f"[조회 조건] 대상 업무영역 = {ctx['area']} (검색 범위 표기 — 문서 근거가 아니다)")
    text = llm.complete(prompts.AGENT_INSTRUCTIONS, q, "\n\n".join(blocks))
    ms = int((time.perf_counter() - started) * 1000)
    ans = Answer(question=q, agent_type=agent_type, text=text, evidence=evidence, mode=mode,
                 confidence=score, threshold=threshold, response_ms=ms, grounded=True,
                 llm_state=st, tools_used=used, lookups=lookups, context=ctx)
    ans.query_id = _log(q, agent_type, user_id, text, evidence, ms, queried_dt)
    return ans


# ── 화면 042 사용자 질문이력 ──────────────────────────────────────────────
_HISTORY_SRC = "from AGT_QUERY_LOGS l left join SYS_USERS u on u.USER_ID = l.USER_ID "

FEEDBACK_MIN, FEEDBACK_MAX = 1, 5


def _history_where(*, agent_type: str | None = None, user_id: int | None = None,
                   login_id: str | None = None, keyword: str | None = None,
                   score: int | None = None, period_sql: str | None = None,
                   period_params: list[Any] | None = None) -> tuple[str, list[Any]]:
    conds, params = [], []
    if agent_type:
        conds.append("l.AGENT_TYPE = %s")
        params.append(agent_type)
    if user_id:
        conds.append("l.USER_ID = %s")
        params.append(user_id)
    if login_id:
        conds.append("u.LOGIN_ID ilike %s")
        params.append(f"%{login_id}%")
    if keyword:
        conds.append("l.QUESTION_TEXT ilike %s")
        params.append(f"%{keyword}%")
    if score is not None:
        conds.append("l.FEEDBACK_SCORE = %s")
        params.append(score)
    if period_sql:
        conds.append(period_sql)
        params += list(period_params or [])
    return (("where " + " and ".join(conds) + " ") if conds else ""), params


def history(*, limit: int = 50, offset: int = 0, **f: Any) -> list[dict[str, Any]]:
    where, params = _history_where(**f)
    return conn.q(
        "select l.QUERY_ID, l.QUERIED_DT, l.AGENT_TYPE, l.QUESTION_TEXT, l.ANSWER_TEXT, "
        "       l.REF_DOC_IDS, l.RESPONSE_MS, l.FEEDBACK_SCORE, u.LOGIN_ID "
        f"{_HISTORY_SRC}{where}order by l.QUERIED_DT desc, l.QUERY_ID desc limit %s offset %s",
        [*params, max(1, min(limit, 200)), max(0, offset)])


def history_count(**f: Any) -> int:
    where, params = _history_where(**f)
    row = conn.q1(f"select count(*) as n {_HISTORY_SRC}{where}", params)
    return int(row["n"]) if row else 0


def query_log(query_id: int) -> dict[str, Any] | None:
    """질의 1건. 화면 042 상세보기가 쓴다."""
    return conn.q1(
        "select l.QUERY_ID, l.QUERIED_DT, l.AGENT_TYPE, l.QUESTION_TEXT, l.ANSWER_TEXT, "
        "       l.REF_DOC_IDS, l.RESPONSE_MS, l.FEEDBACK_SCORE, l.USER_ID, u.LOGIN_ID "
        f"{_HISTORY_SRC}where l.QUERY_ID = %s", (query_id,))


def ref_docs(ref_doc_ids: str | None, role_code: str = "") -> list[dict[str, Any]]:
    """`REF_DOC_IDS` 에 적힌 **그 문서들**. 검색과 같은 `ACCESS_ROLE` 통제를 지난다.

    기록에 없는 문서를 보태지 않는다 — 근거는 질의 시점에 실제로 읽은 것뿐이다.
    """
    ids = [int(x) for x in str(ref_doc_ids or "").split(",") if x.strip().isdigit()]
    if not ids:
        return []
    return conn.q(
        "select DOC_ID, DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT, ACCESS_ROLE "
        "from AGT_VECTOR_DOCS where DOC_ID = any(%s) "
        "  and (ACCESS_ROLE is null or ACCESS_ROLE = %s) order by DOC_ID, CHUNK_SEQ",
        (ids, role_code or ""))


def set_feedback(query_id: int, score: int, user_id: int | None = None) -> int:
    """`FEEDBACK_SCORE` 를 쓰는 **유일한 경로**. 어휘 밖 점수는 422 (§2.5).

    TD5 에 평가자 컬럼이 없다 — 질의 주인만 자기 질의를 평가한다(D-nn 제안).
    """
    if score < FEEDBACK_MIN or score > FEEDBACK_MAX:
        raise http.fail("validation",
                        f"사용자 평가는 {FEEDBACK_MIN}~{FEEDBACK_MAX} 점이다: {score}")
    row = conn.q1("select QUERY_ID from AGT_QUERY_LOGS where QUERY_ID = %s", (query_id,))
    if row is None:
        raise http.fail("validation", f"질의 {query_id} 가 없다")
    return conn.x("update AGT_QUERY_LOGS set FEEDBACK_SCORE = %s where QUERY_ID = %s",
                  (score, query_id))


def history_stats() -> dict[str, Any]:
    """실측만 적는다 — 응답시간 **목표치는 사업계획서에 없다**(D-09)."""
    row = conn.q1(
        "select count(*) as n, avg(RESPONSE_MS) as avg_ms, max(RESPONSE_MS) as max_ms, "
        "       count(*) filter (where REF_DOC_IDS is not null) as grounded, "
        "       avg(FEEDBACK_SCORE) as avg_score "
        "from AGT_QUERY_LOGS")
    return dict(row) if row else {}
