"""LLM·임베딩 공급자 추상화 (D-08 · D-234) — **키가 없으면 501. 조용한 폴백 금지.**

사업계획서 4.7 은 Bedrock 만 적었고 **모델명·임베딩 모델·인덱스 종류가 미정**이다(D-08).
그래서 여기에는 어떤 모델 이름도 상수로 박지 않는다. `.env` 가 정본이다(§10-1).

  KYUNGDONG_LLM_PROVIDER=anthropic      공급자 — 구현된 것은 `anthropic` 하나다 (공식 SDK, D-234)
  KYUNGDONG_LLM_MODEL=claude-opus-5     모델 ID — 도입기업 확정 전까지 .env 값이다
  KYUNGDONG_LLM_EFFORT=medium           low·medium·high·xhigh·max (답변은 5줄이라 medium 이 기본)
  ANTHROPIC_API_KEY=…                   키 — 환경변수로만. 저장소·로그·화면에 적지 않는다 (G-29)
                                        SDK 가 인정하는 다른 자격도 통한다 — `ANTHROPIC_AUTH_TOKEN` · `ant auth login` 프로필 (D-237)
  KYUNGDONG_EMBED_PROVIDER=             임베딩 — **Anthropic 은 임베딩 API 가 없다.** 비우면 tsvector_keyword

**폐쇄형과의 관계 (D-234).** 검색은 내부 데이터(`AGT_VECTOR_DOCS` · 운영 DB)만 본다 — 외부 *검색* 은 0건이다.
그러나 답변 *생성* 은 LLM API 호출이고, **검색된 근거 발췌와 질문이 공급자(api.anthropic.com)로 전송된다.**
사업계획서 2.4·4.7 이 LLM(Bedrock) 을 AI 서버 구성으로 계상했으므로 설계 안의 통신이지만, 그 사실을 화면·대장에
숨기지 않는다. 이 모듈이 **제품 코드에서 유일하게 밖으로 나가는 자리**다 — 검사기(G-20·G-26)가 그렇게 센다.
Bedrock 으로 옮길 때는 `_client()` 만 `AnthropicBedrockMantle` 로 바꾸면 된다(호출 표면 동일).

**`bedrock` 은 계약 이름으로만 남아 있다** — 값이 들어와도 구현이 없으므로 501 이다.
"구성됐다고 선언했는데 실제로는 없다" 를 조용히 넘기면 그게 §2.5 위반이다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from ..app.settings import settings
from ..app.util import http

# 계약이 인정하는 공급자 이름. 구현이 붙은 것만 `_CHAT` 에 등록된다.
KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "bedrock")
_CHAT: dict[str, Callable[..., str]] = {}
_EMBED: dict[str, Callable[[str], list[float]]] = {}

API_KEY_ENV = "ANTHROPIC_API_KEY"          # 공식 SDK 가 읽는 이름 — KYUNGDONG_ 접두를 붙이지 않는다
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "medium"
AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN"     # SDK 가 두 번째로 읽는 이름
MAX_TOKENS = 4096                          # 답변은 최대 5줄(prompts 원칙 6)이지만 Opus 5 는 thinking 이 기본이라
                                           # 그 토큰까지 이 상한에 든다 — 1024 면 답이 나오기 전에 잘린다 (D-237)
PING_MAX_TOKENS = 256                      # 연결 확인도 같은 이유로 16 이 아니다
EGRESS_NOTE = "답변 생성 시 질문과 검색된 근거 발췌가 LLM API 로 전송된다 (D-234) — 검색 자체는 내부 데이터만"


def api_key() -> str:
    """키는 환경변수로만 받는다. 값은 돌려주되 **어디에도 찍지 않는다**(G-29)."""
    return os.environ.get(API_KEY_ENV, "").strip()


def has_credential() -> bool:
    """SDK 가 실제로 쓸 자격이 있는가 — `ANTHROPIC_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → `ant auth login` 프로필 (D-237).

    환경변수 하나만 보면 프로필로 로그인한 장비에서 501 을 내고, 반대로 SDK 가 못 쓰는 값을 "있다" 고 한다.
    그래서 마지막 단계는 **SDK 자신에게 묻는다**(네트워크 없음 — 생성자는 자격을 해석만 한다). 값은 돌려주지 않는다.
    """
    if api_key() or os.environ.get(AUTH_TOKEN_ENV, "").strip():
        return True
    try:
        import anthropic
        c = anthropic.Anthropic()
        return bool(c.api_key or getattr(c, "auth_token", None))
    except Exception:                     # 프로필 파일 결함 등 — 자격 없음으로 본다. 사유는 state() 가 이름으로 말한다
        return False


def effort() -> str:
    """출력 노력 수준. 계약 밖 값은 **422 가 아니라 기동 결함**이다 — .env 를 고친다."""
    v = os.environ.get("KYUNGDONG_LLM_EFFORT", DEFAULT_EFFORT).strip() or DEFAULT_EFFORT
    if v not in EFFORT_LEVELS:
        raise RuntimeError(f"KYUNGDONG_LLM_EFFORT={v!r} — {EFFORT_LEVELS} 중 하나다")
    return v


@dataclass(frozen=True)
class LlmState:
    configured: bool
    provider: str
    model: str
    reason: str

    @property
    def badge(self) -> str:
        return (f"LLM 구성됨 · {self.provider}/{self.model}" if self.configured
                else "LLM 미구성 (D-08)")


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
    if s.llm_provider == "anthropic" and not has_credential():
        return LlmState(False, s.llm_provider, s.llm_model,
                        f"{API_KEY_ENV} 가 비어 있다 ({AUTH_TOKEN_ENV} · `ant auth login` 프로필도 없음) — "
                        "자격 없이는 부르지 않는다 (D-08 · D-234 · D-237)")
    return LlmState(True, s.llm_provider, s.llm_model, "")


def require() -> LlmState:
    st = state()
    if not st.configured:
        raise http.fail("llm_unconfigured", st.reason)
    return st


def complete(instructions: str, question: str, context: str) -> str:
    """LLM 호출. 구현이 없으면 **501** 이다. 대신 문장을 만들어 주지 않는다."""
    st = require()
    return _CHAT[st.provider](instructions=instructions, question=question, context=context,
                              model=st.model)


def embed(text: str) -> list[float]:
    """임베딩. 차원은 **1536**(D-31). 구현이 없으면 501 — 0벡터를 돌려주지 않는다.

    **Anthropic 은 임베딩 API 를 제공하지 않는다.** 별도 공급자가 정해질 때까지 검색은 `tsvector_keyword` 다.
    """
    s = settings()
    if s.embed_provider not in _EMBED:
        raise http.fail(
            "llm_unconfigured",
            f"임베딩 공급자 {s.embed_provider or '(미설정)'} 호출 구현 미착수 — "
            "검색은 tsvector_keyword 로 내려간다 (D-08)",
        )
    return _EMBED[s.embed_provider](text)


# ── anthropic — 공식 SDK (D-234) ─────────────────────────────────────────────
def _client() -> Any:
    """SDK 클라이언트. 키는 SDK 가 `ANTHROPIC_API_KEY` 에서 읽는다 — 여기서 문자열로 만지지 않는다."""
    import anthropic                      # 제품 코드의 유일한 외부 통신 모듈 (D-234)
    return anthropic.Anthropic(max_retries=2, timeout=float(settings().h("RAG_TIMEOUT_SEC").as_int()))


def _text_of(message: Any) -> str:
    return "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text").strip()


def anthropic_complete(*, instructions: str, question: str, context: str, model: str) -> str:
    """근거 발췌 + 질문 → 5줄 답변. **응답이 비정상이면 문장을 만들지 않고 드러낸다.**"""
    import anthropic

    user = (f"<근거>\n{context}\n</근거>\n\n<질문>\n{question}\n</질문>\n\n"
            "위 근거와 질문만으로 답한다. 근거에 없는 문서명·조항·수치는 만들지 않는다.")
    try:
        msg = _client().messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=instructions,
            output_config={"effort": effort()},
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as e:
        raise http.fail("llm_unconfigured", f"{API_KEY_ENV} 가 유효하지 않다 — {e.message}") from e
    except anthropic.PermissionDeniedError as e:
        raise http.fail("llm_unconfigured", f"키에 권한이 없다 — {e.message}") from e
    except anthropic.NotFoundError as e:
        raise http.fail("llm_unconfigured", f"모델 {model!r} 을 찾을 수 없다 — KYUNGDONG_LLM_MODEL 확인 ({e.message})") from e
    except anthropic.RateLimitError as e:
        raise http.fail("internal", f"LLM 호출 한도 초과 — 잠시 뒤 다시 질의 ({e.message})") from e
    except anthropic.APIStatusError as e:
        raise http.fail("internal", f"LLM 호출 실패 {e.status_code} — {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise http.fail("internal", f"LLM API 에 닿지 못했다 — {e}") from e

    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        return (f"모델이 이 질문에 대한 답변 생성을 거부했다 (사유 분류 {cat or '미상'}). 담당자 검토가 필요하다.\n"
                "근거: 확인된 자료 없음")
    text = _text_of(msg)
    if not text:
        raise http.fail("internal", f"LLM 이 빈 응답을 냈다 (stop_reason={msg.stop_reason})")
    if msg.stop_reason == "max_tokens":
        text += f"\n(응답이 {MAX_TOKENS} 토큰에서 잘렸다 — 원칙 6 의 5줄 형식을 벗어난 출력이다)"
    return text


_CHAT["anthropic"] = anthropic_complete


def ping() -> dict[str, Any]:
    """연결 확인 1회 — **가장 작은 실제 호출**. `make check-llm` 이 부른다 (D-236).

    구성이 안 됐으면 501 을 그대로 낸다(문장으로 덮지 않는다). 성공하면 모델·요청 ID·지연·토큰을
    돌려준다 — 키 문자열은 어디에도 넣지 않는다(G-29). 이 함수도 anthropic 을 이 파일 밖에서
    import 하지 않으려고 여기 있다(check_ai 정적 검사).
    """
    import time
    import anthropic

    st = require()
    t0 = time.perf_counter()
    try:
        msg = _client().messages.create(
            model=st.model, max_tokens=PING_MAX_TOKENS,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "연결 확인. '확인' 한 단어만 답한다."}],
        )
    except anthropic.AuthenticationError as e:
        raise http.fail("llm_unconfigured", f"{API_KEY_ENV} 가 유효하지 않다 — {e.message}") from e
    except anthropic.PermissionDeniedError as e:
        raise http.fail("llm_unconfigured", f"키에 권한이 없다 — {e.message}") from e
    except anthropic.NotFoundError as e:
        raise http.fail("llm_unconfigured", f"모델 {st.model!r} 을 찾을 수 없다 — KYUNGDONG_LLM_MODEL 확인 ({e.message})") from e
    except anthropic.RateLimitError as e:
        raise http.fail("internal", f"LLM 호출 한도 초과 — 잠시 뒤 다시 ({e.message})") from e
    except anthropic.APIStatusError as e:
        raise http.fail("internal", f"LLM 호출 실패 {e.status_code} — {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise http.fail("internal", f"LLM API 에 닿지 못했다 — {e}") from e
    return {
        "provider": st.provider, "model": msg.model, "request_id": getattr(msg, "_request_id", None),
        "latency_ms": round((time.perf_counter() - t0) * 1000),
        "stop_reason": msg.stop_reason, "text": _text_of(msg),
        "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
        "effort": effort(), "egress": EGRESS_NOTE,
    }
