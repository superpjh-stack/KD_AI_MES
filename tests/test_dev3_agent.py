"""RAG Agent — 폐쇄형 · 근거 0건 분기 · LLM 미구성 501 · 로그 100% · 도구 허용목록 (G-20~G-23)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                      # noqa: E402
from kyungdong.agent import citations, llm, prompts, retrieval   # noqa: E402
from kyungdong.agent import service, tools                       # noqa: E402
from kyungdong.app.util import http                              # noqa: E402

ADMIN = None


def _admin() -> int:
    global ADMIN
    if ADMIN is None:
        ADMIN = int(conn.q1("select USER_ID from SYS_USERS where LOGIN_ID='admin'")["user_id"])
    return ADMIN


# ── 폐쇄형 ────────────────────────────────────────────────────────────────
def test_지식베이스는_내부_표_하나뿐이다():
    src = (ROOT / "src" / "kyungdong" / "agent" / "retrieval.py").read_text()
    assert "AGT_VECTOR_DOCS" in src
    for ext in ("requests", "httpx", "urllib", "http://", "https://"):
        assert ext not in src, f"폐쇄형인데 외부 호출 흔적이 있다: {ext}"


def test_Agent_소스에_외부_검색_호출이_없다():
    for f in (ROOT / "src" / "kyungdong" / "agent").glob("*.py"):
        txt = f.read_text()
        for bad in ("requests.get", "httpx.get", "urlopen", "web_search"):
            assert bad not in txt, f"{f.name}: 외부 검색 흔적 {bad}"


def test_임베딩_미구성이면_검색_모드가_라벨로_드러난다():
    ev, mode = retrieval.search("자재 입고 검사", agent_type="입고")
    assert mode in (retrieval.MODE_KEYWORD, retrieval.MODE_VECTOR)
    assert mode == retrieval.MODE_KEYWORD, "임베딩 공급자가 없으면 키워드 모드다 (D-08)"


def test_벡터_차원은_1536_이다():
    assert retrieval.VECTOR_DIM == 1536          # D-31 — TD5 명시
    row = conn.q1("select atttypmod as m from pg_attribute "
                  "where attrelid = 'agt_vector_docs'::regclass and attname = 'embedding'")
    assert row is not None


def test_Agent_별_문서_범위가_다르다():
    assert set(retrieval.SCOPE) == {"입고", "출하", "통합"}
    assert retrieval.SCOPE["입고"] != retrieval.SCOPE["출하"]
    assert set(retrieval.SCOPE["통합"]) == set(retrieval.DOC_TYPES)


# ── 근거 0건 분기 — LLM 을 부르지 않는다 ──────────────────────────────────
def test_근거가_없으면_LLM_을_부르지_않고_검토_필요를_낸다(monkeypatch):
    called = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.append(1) or "x")
    a = service.ask("qqqzzz xywv jjkk", agent_type="통합", user_id=_admin())
    assert called == [], "근거 0건인데 LLM 을 불렀다"
    assert a.text == http.NOTICE_RAG_NO_EVIDENCE
    assert a.grounded is False
    assert a.evidence == [], "매칭이 0건이면 근거도 0건이어야 한다"
    assert "근거 0건" in a.notice
    assert prompts.HANDOVER_NOTE in a.handover


def test_신뢰도_임계_미만이면_같은_분기로_간다(monkeypatch):
    called = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.append(1) or "x")
    a = service.ask("출하 전 성능검사 불합격 기록", agent_type="출하", user_id=_admin())
    if a.confidence < a.threshold:
        assert called == []
        assert a.text == http.NOTICE_RAG_NO_EVIDENCE
        assert "임계" in a.notice


def test_근거가_있으면_LLM_미구성_501_이다():
    with pytest.raises(http.HTTPException) as e:
        service.ask("자재 입고 검사 MTC 바코드 발행", agent_type="입고", user_id=_admin())
    assert e.value.status_code == 501
    assert e.value.detail["message"] == "LLM 미구성"


def test_LLM_상태는_구성됐다고_거짓말하지_않는다():
    st = llm.state()
    assert st.configured is False and st.reason
    with pytest.raises(http.HTTPException) as e:
        llm.require()
    assert e.value.status_code == 501


# ── 로그 100% ─────────────────────────────────────────────────────────────
def test_모든_갈래가_질의이력에_남는다():
    n0 = int(conn.q1("select count(*) as n from AGT_QUERY_LOGS")["n"])
    service.ask("qqqzzz xywv jjkk", agent_type="통합", user_id=_admin())
    try:
        service.ask("자재 입고 검사 MTC 바코드 발행", agent_type="입고", user_id=_admin())
    except http.HTTPException:
        pass
    n1 = int(conn.q1("select count(*) as n from AGT_QUERY_LOGS")["n"])
    assert n1 == n0 + 2, "근거 부족 갈래와 501 갈래 둘 다 기록돼야 한다"
    last = conn.q("select QUESTION_TEXT, ANSWER_TEXT, RESPONSE_MS from AGT_QUERY_LOGS "
                  "order by QUERY_ID desc limit 2")
    for r in last:
        assert r["question_text"] and r["answer_text"] is not None
        assert r["response_ms"] is not None, "응답시간도 기록 대상이다"


def test_빈_질의는_422_다():
    with pytest.raises(http.HTTPException) as e:
        service.ask("   ", agent_type="통합", user_id=_admin())
    assert e.value.status_code == 422


def test_모르는_Agent_구분은_422_다():
    with pytest.raises(http.HTTPException) as e:
        service.ask("질문", agent_type="설비", user_id=_admin())
    assert e.value.status_code == 422


# ── 도구 11종 (D-20) ──────────────────────────────────────────────────────
def test_도구는_11종이고_재배선_표와_1대1이다():
    assert len(tools.HANDLERS) == 11
    assert set(tools.HANDLERS) == set(tools.REWIRING)
    assert set(tools.TOOLSETS["통합"]) == set(tools.HANDLERS)


def test_재배선_표의_테이블은_TD5_에_있는_것이다():
    import re
    from kyungdong.app import design
    known = set(design.tables())
    for name, desc in tools.REWIRING.items():
        refs = set(re.findall(r"\b(?:AGT|BAS|DAT|EST|IF|INV|KPI|PRC|SHP|SYS)_[A-Z0-9_]+", desc))
        if name == "get_db_records":
            continue          # 허용목록 전체(68표)라 특정 표를 적지 않는다
        assert refs, f"{name}: 재배선 표에 TD5 테이블이 적혀 있지 않다"
        for t in refs:
            assert t in known, f"{name}: TD5 에 없는 표 {t}"


def test_허용목록_밖_도구는_거부된다():
    out = json.loads(tools.execute("drop_everything", "{}"))
    assert "error" in out


def test_Agent_범위_밖_도구도_거부된다():
    out = json.loads(tools.execute("get_claim_trace", {"claim_no": "X"}, agent_type="입고"))
    assert "error" in out, "입고 Agent 에게 출하 도구를 열어 주면 안 된다"


def test_쓰기_동사는_실행되지_않는다():
    for sql in ("update EST_QUOTATIONS set TOTAL_AMOUNT = 0",
                "delete from AGT_QUERY_LOGS",
                "insert into AGT_QUERY_LOGS values (1)"):
        with pytest.raises(RuntimeError):
            tools._readonly(sql)


def test_허용목록_밖_테이블은_조회되지_않():
    out = tools.get_db_records("pg_shadow")
    assert "error" in out


def test_스키마는_strict_다():
    for d in tools.definitions("통합"):
        assert d["strict"] is True
        assert d["parameters"]["additionalProperties"] is False
        assert set(d["parameters"]["required"]) == set(d["parameters"]["properties"])


def test_개인정보는_마스킹된다():
    out = tools.get_db_records("SYS_USERS", 5)
    for r in out.get("records", []):
        if r.get("user_name"):
            assert "*" in r["user_name"], "사용자명은 마스킹 대상이다 (G-29)"


# ── 프롬프트 이식 ─────────────────────────────────────────────────────────
def test_프롬프트_11원칙이_그대로_있다():
    t = prompts.AGENT_INSTRUCTIONS
    for i in range(1, 12):
        assert f"\n{i}." in t, f"원칙 {i} 누락"
    assert "지어내지 않으며" in t
    assert "search_knowledge" in t
    assert "근거: 확인된 자료 없음" in t


def test_프롬프트에_타_사업_용어가_없다():
    t = prompts.AGENT_INSTRUCTIONS
    for bad in ("포밍", "롤포밍", "로봇용접", "레토르트", "판금", "예지보전", "프레스", "금형"):
        assert bad not in t, f"프롬프트에 이 사업에 없는 용어: {bad}"
    assert "반응기" in t and "교반기" in t


def test_근거_줄은_실제_검색된_문서만_적는다():
    ev, _ = retrieval.search("자재 입고 검사", agent_type="입고")
    line = citations.evidence_line(ev)
    if ev:
        assert all(e.doc_name in line for e in ev[:3])
    else:
        assert line == citations.NO_EVIDENCE_LINE


def test_참조_문서_ID_는_300자를_넘지_않는다():
    ev = [retrieval.Evidence(i, "SOP", "x.md", None, 1, "t", 1.0, retrieval.MODE_KEYWORD)
          for i in range(1, 400)]
    s = citations.ref_doc_ids(ev)
    assert s is not None and len(s) <= citations.REF_DOC_IDS_MAX
