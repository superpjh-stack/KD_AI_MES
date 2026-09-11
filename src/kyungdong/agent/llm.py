"""LLM·임베딩 공급자 추상화 (D-08) — **키가 없으면 501. 조용한 폴백 금지.**

사업계획서 4.7 은 Bedrock 만 적었고 **모델명·임베딩 모델·인덱스 종류가 미정**이다.
그래서 여기에는 어떤 모델 이름도 상수로 박지 않는다. `.env` 가 정본이다(§10-1).

  KYUNGDONG_LLM_PROVIDER / KYUNGDONG_LLM_MODEL / KYUNGDONG_EMBED_PROVIDER

**지원 공급자 구현이 아직 없다.** 그러므로 값이 들어와도 `501 LLM 미구성` 이 난다 —
"구성됐다고 선언했는데 실제로는 없다" 를 조용히 넘기면 그게 §2.5 위반이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..app.settings import settings
from ..app.util import http

# 계약이 인정하는 공급자 이름. 구현이 붙으면 여기에 핸들러를 등록한다.
KNOWN_PROVIDERS: tuple[str, ...] = ("bedrock",)
_CHAT: dict[str, object] = {}       # provider → callable (아직 비어 있다)
_EMBED: dict[str, object] = {}


@dataclass(frozen=True)
class LlmState:
    configured: bool
    provider: str
    model: str
    reason: str

    @property
    def badge(self) -> str:
        return "LLM 구성됨" if self.configured else "LLM 미구성 (D-08)"


def state() -> LlmState:
    s = settings()
    if not s.llm_provider or not s.llm_model:
        return LlmState(False, s.llm_provider, s.llm_model,
                        "KYUNGDONG_LLM_PROVIDER·KYUNGDONG_LLM_MODEL 미설정 (D-08)")
    if s.llm_provider not in KNOWN_PROVIDERS:
        return LlmState(False, s.llm_provider, s.llm_model,
                        f"지원하지 않는 공급자 {s.llm_provider!r} — 계약 {KNOWN_PROVIDERS} (D-08)")
    if s.llm_provider not in _CHAT:
        return LlmState(False, s.llm_provider, s.llm_model,
                        f"{s.llm_provider} 호출 구현 미착수 — 모델명·엔드포인트 확정 대기 (D-08)")
    return LlmState(True, s.llm_provider, s.llm_model, "")


def require() -> LlmState:
    st = state()
    if not st.configured:
        raise http.fail("llm_unconfigured", st.reason)
    return st


def complete(instructions: str, question: str, context: str) -> str:
    """LLM 호출. 구현이 없으면 **501** 이다. 대신 문장을 만들어 주지 않는다."""
    st = require()
    handler = _CHAT[st.provider]
    return handler(instructions=instructions, question=question, context=context)  # type: ignore[operator]


def embed(text: str) -> list[float]:
    """임베딩. 차원은 **1536**(D-31). 구현이 없으면 501 — 0벡터를 돌려주지 않는다."""
    s = settings()
    if s.embed_provider not in _EMBED:
        raise http.fail(
            "llm_unconfigured",
            f"임베딩 공급자 {s.embed_provider or '(미설정)'} 호출 구현 미착수 — "
            "검색은 tsvector_keyword 로 내려간다 (D-08)",
        )
    return _EMBED[s.embed_provider](text)  # type: ignore[operator]
