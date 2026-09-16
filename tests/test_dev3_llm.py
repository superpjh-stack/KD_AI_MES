"""LLM 공급자 어댑터 (D-234) — 공식 anthropic SDK. **네트워크를 부르지 않는다** — 클라이언트를 가짜로 바꾼다.

못박는 것:
  · 키가 없으면 구성됐다고 말하지 않는다 (501, 이유에 환경변수 이름)
  · 호출은 system=원칙 11개 · user=근거+질문 · effort 설정값 · max_tokens 계약값
  · 거부(refusal)·빈 응답·잘림을 문장으로 덮지 않는다
  · SDK 오류는 계약 상태코드로 드러난다 (인증 501 · 나머지 500)
  · 제품 코드에서 anthropic 을 import 하는 파일은 agent/llm.py 하나다
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT))

from kyungdong.agent import llm, prompts               # noqa: E402
from kyungdong.app import settings as settings_mod     # noqa: E402
from kyungdong.app.util import http                    # noqa: E402


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("KYUNGDONG_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("KYUNGDONG_LLM_MODEL", "claude-opus-5")
    monkeypatch.setenv("KYUNGDONG_LLM_EFFORT", "medium")
    monkeypatch.setenv(llm.API_KEY_ENV, "test-only-not-a-real-key")
    settings_mod.settings.cache_clear()
    yield
    settings_mod.settings.cache_clear()


class _Fake:
    """`anthropic.Anthropic().messages.create` 흉내 — 받은 인자를 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, response=None, error=None):
        self.calls: list[dict] = []
        self.response = response
        self.error = error
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.response


def _msg(text: str, stop="end_turn", category=None):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           stop_details=(SimpleNamespace(category=category) if stop == "refusal" else None))


def test_키가_없으면_구성됐다고_말하지_않는다(monkeypatch, configured):
    monkeypatch.delenv(llm.API_KEY_ENV)
    st = llm.state()
    assert st.configured is False and llm.API_KEY_ENV in st.reason
    with pytest.raises(http.HTTPException) as e:
        llm.require()
    assert e.value.status_code == 501


def test_bedrock_은_계약_이름만_있고_구현이_없어_501_이다(monkeypatch, configured):
    monkeypatch.setenv("KYUNGDONG_LLM_PROVIDER", "bedrock")
    settings_mod.settings.cache_clear()
    st = llm.state()
    assert st.configured is False and "구현 미착수" in st.reason


def test_호출_형태는_원칙_근거_질문_effort_max_tokens_다(monkeypatch, configured):
    fake = _Fake(_msg("답변 첫 줄\n근거: 문서 A"))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    out = llm.complete(prompts.AGENT_INSTRUCTIONS, "MTC 검사 기준은?", "[SOP #1] 재질성적서를 대조한다")
    assert out == "답변 첫 줄\n근거: 문서 A"
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5"
    assert kw["system"] == prompts.AGENT_INSTRUCTIONS
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["max_tokens"] == llm.MAX_TOKENS
    user = kw["messages"][0]["content"]
    assert "[SOP #1] 재질성적서를 대조한다" in user and "MTC 검사 기준은?" in user
    assert "만들지 않는다" in user


def test_effort_는_계약_어휘_밖이면_기동_결함이다(monkeypatch, configured):
    monkeypatch.setenv("KYUNGDONG_LLM_EFFORT", "turbo")
    with pytest.raises(RuntimeError):
        llm.effort()


def test_거부_응답은_문장으로_덮지_않는다(monkeypatch, configured):
    fake = _Fake(_msg("", stop="refusal", category="cyber"))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    out = llm.complete("x", "q", "c")
    assert "거부" in out and "cyber" in out and out.endswith("근거: 확인된 자료 없음")


def test_빈_응답은_500_으로_드러난다(monkeypatch, configured):
    fake = _Fake(_msg("", stop="end_turn"))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    with pytest.raises(http.HTTPException) as e:
        llm.complete("x", "q", "c")
    assert e.value.status_code == 500


def test_잘린_응답은_잘렸다고_적는다(monkeypatch, configured):
    fake = _Fake(_msg("첫 줄", stop="max_tokens"))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    assert "잘렸다" in llm.complete("x", "q", "c")


def test_SDK_오류는_계약_상태코드로_나온다(monkeypatch, configured):
    import anthropic
    import httpx2

    def err(cls, status):
        resp = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        return cls("boom", response=resp, body=None)

    for cls, status, want in ((anthropic.AuthenticationError, 401, 501),
                              (anthropic.RateLimitError, 429, 500),
                              (anthropic.InternalServerError, 500, 500)):
        fake = _Fake(error=err(cls, status))
        monkeypatch.setattr(llm, "_client", lambda f=fake: f)
        with pytest.raises(http.HTTPException) as e:
            llm.complete("x", "q", "c")
        assert e.value.status_code == want, cls.__name__


def test_anthropic_import_는_agent_llm_하나뿐이다():
    from tools import check_ai
    assert check_ai._closed_loop_static() == []
    hits = [p for p in (ROOT / "src" / "kyungdong").rglob("*.py")
            if "import anthropic" in p.read_text()]
    assert [p.name for p in hits] == ["llm.py"], hits


def test_구성되면_화면_배지에_모델과_전송_고지가_뜬다(monkeypatch, configured):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    c = TestClient(app)
    body = c.get("/agt/038").text
    assert "LLM 구성됨 · anthropic/claude-opus-5" in body
    assert "D-234" in body and "전송" in body
    # 미비 항목 표의 D-08 원문에도 'LLM 미구성' 이 적혀 있다 — **배지**만 본다
    assert ">LLM 미구성 (D-08)<" not in body
