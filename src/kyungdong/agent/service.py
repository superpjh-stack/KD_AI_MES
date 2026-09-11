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

    @property
    def sources(self) -> list[str]:
        return citations.sources(self.evidence)

    @property
    def evidence_line(self) -> str:
        return citations.evidence_line(self.evidence)


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


def ask(question: str, *, agent_type: str = "통합", user_id: int | None = None,
        role_code: str = "") -> Answer:
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
        )
        ans.query_id = _log(q, agent_type, user_id, text, evidence, ms, queried_dt)
        return ans

    # ④ 여기서부터 LLM. 키가 없으면 501 — 단, **로그는 먼저 남긴다**(100% 기록)
    st = llm.state()
    if not st.configured:
        ms = int((time.perf_counter() - started) * 1000)
        _log(q, agent_type, user_id, f"{st.badge} — {st.reason}", evidence, ms, queried_dt)
        raise http.fail("llm_unconfigured", st.reason)

    context = "\n\n".join(f"[{e.doc_name} #{e.chunk_seq}] {e.chunk_text}" for e in evidence)
    text = llm.complete(prompts.AGENT_INSTRUCTIONS, q, context)
    ms = int((time.perf_counter() - started) * 1000)
    ans = Answer(question=q, agent_type=agent_type, text=text, evidence=evidence, mode=mode,
                 confidence=score, threshold=threshold, response_ms=ms, grounded=True,
                 llm_state=st, tools_used=[t["name"] for t in tools.definitions(agent_type)])
    ans.query_id = _log(q, agent_type, user_id, text, evidence, ms, queried_dt)
    return ans


# ── 화면 042 사용자 질문이력 ──────────────────────────────────────────────
def history(*, agent_type: str | None = None, user_id: int | None = None,
            keyword: str | None = None, limit: int = 50,
            offset: int = 0) -> list[dict[str, Any]]:
    conds, params = [], []
    if agent_type:
        conds.append("l.AGENT_TYPE = %s")
        params.append(agent_type)
    if user_id:
        conds.append("l.USER_ID = %s")
        params.append(user_id)
    if keyword:
        conds.append("l.QUESTION_TEXT ilike %s")
        params.append(f"%{keyword}%")
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    params.append(max(1, min(limit, 200)))
    params.append(max(0, offset))
    return conn.q(
        "select l.QUERY_ID, l.QUERIED_DT, l.AGENT_TYPE, l.QUESTION_TEXT, l.ANSWER_TEXT, "
        "       l.REF_DOC_IDS, l.RESPONSE_MS, l.FEEDBACK_SCORE, u.LOGIN_ID "
        "from AGT_QUERY_LOGS l left join SYS_USERS u on u.USER_ID = l.USER_ID "
        f"{where}order by l.QUERIED_DT desc, l.QUERY_ID desc limit %s offset %s", params)


def history_stats() -> dict[str, Any]:
    """실측만 적는다 — 응답시간 **목표치는 사업계획서에 없다**(D-09)."""
    row = conn.q1(
        "select count(*) as n, avg(RESPONSE_MS) as avg_ms, max(RESPONSE_MS) as max_ms, "
        "       count(*) filter (where REF_DOC_IDS is not null) as grounded, "
        "       avg(FEEDBACK_SCORE) as avg_score "
        "from AGT_QUERY_LOGS")
    return dict(row) if row else {}
