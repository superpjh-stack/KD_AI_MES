"""환경 설정 — `.env.example` 의 `KYUNGDONG_*` 키가 정본.

goal.md §10-1: 가설값은 **`.env`(설정) 한 곳**에만 둔다. 코드 상수 금지.
`가설 (D-nn)` 배지를 화면에 띄우기 위해 값마다 근거 D-번호를 함께 들고 다닌다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "KYUNGDONG_"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(PREFIX + key, default).strip()


def _load_dotenv() -> None:
    """`.env` 를 읽되 **셸 환경변수가 이긴다**(goal.md §10-5)."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.split("#")[0].strip())


@dataclass(frozen=True)
class Hypothesis:
    """사업계획서에 수치가 없어 임의로 정한 값. 화면에 `가설 (D-nn)` 을 띄운다."""
    value: str
    decision: str
    what: str

    def as_int(self) -> int:
        return int(self.value)

    def as_float(self) -> float:
        return float(self.value)

    @property
    def badge(self) -> str:
        return f"가설 ({self.decision})"


@dataclass(frozen=True)
class Settings:
    pg_dsn: str
    env: str
    port: int
    session_secret: str
    csrf_enforce: bool
    seed_password: str
    llm_provider: str
    llm_model: str
    embed_provider: str
    cad_parser: str
    cad_vision_model: str
    cad_iou_threshold: float
    hypotheses: dict[str, Hypothesis]

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_provider and self.llm_model)

    @property
    def embed_configured(self) -> bool:
        return bool(self.embed_provider)

    @property
    def cad_configured(self) -> bool:
        return bool(self.cad_parser) and self.cad_parser != "none"

    @property
    def search_mode(self) -> str:
        """임베딩 미구성이면 숨기지 않고 모드를 라벨로 드러낸다 (D-08 · §2.5)."""
        return "vector_pgvector" if self.embed_configured else "tsvector_keyword"

    def h(self, key: str) -> Hypothesis:
        return self.hypotheses[key]


# 가설값 — (env 키, 기본값, 결정 번호, 설명). **기본값은 여기 말고 어디에도 두지 않는다.**
_HYPOTHESES: tuple[tuple[str, str, str, str], ...] = (
    ("PASSWORD_MIN_LEN",          "10",   "D-16", "비밀번호 최소 길이"),
    ("PASSWORD_COMPLEXITY_CLASSES", "3",  "D-16", "비밀번호 복잡도 — 문자 종류 수(대/소/숫자/특수)"),
    ("PASSWORD_CHANGE_CYCLE_DAYS", "90",  "D-16", "비밀번호 변경 주기(일)"),
    ("LOGIN_FAIL_MAX",            "5",    "D-16", "로그인 실패 잠금 횟수 (계정 단위)"),
    ("RATE_LIMIT_IP",             "20",   "D-16", "로그인 실패 한도 (IP 단위, 10분 창)"),
    ("SESSION_IDLE_MINUTES",      "30",   "D-16", "자동 로그아웃(분)"),
    ("RAG_CONFIDENCE_MIN",        "0.70", "D-10", "RAG 그라운딩 임계값"),
    ("RAG_TIMEOUT_SEC",           "10",   "D-09", "RAG 응답 제한(초) — 목표치 없음, 실측만 보고"),
    ("DUE_DATE_TOLERANCE_DAYS",   "3",    "D-12", "납기 예측 허용 오차(일)"),
    ("PLC_POLL_SEC",              "1",    "D-06", "레이저커팅기 PLC 수집 주기(초)"),
    ("INGEST_STALE_SEC",          "60",   "D-09", "수집 중단 판정 임계(초)"),
    ("BOARD_REFRESH_SEC",         "30",   "D-09", "현황판 자동 갱신 주기(초)"),
    ("ANCHOR_COUNT",              "5",    "D-03", "시간 앵커 분포 표본 수"),
)


@cache
def settings() -> Settings:
    _load_dotenv()
    env = _env("ENV", "dev")
    secret = _env("SESSION_SECRET")
    if env == "prod" and not secret:
        raise RuntimeError(
            "prod 에서 KYUNGDONG_SESSION_SECRET 이 비어 있다 — 기동을 거부한다(goal.md §8)"
        )
    return Settings(
        pg_dsn=_env("PG_DSN", "postgresql:///kyungdong_db"),
        env=env,
        port=int(_env("PORT", "8020")),
        session_secret=secret,
        csrf_enforce=_env("CSRF_ENFORCE", "1") not in ("0", "false", "False"),
        seed_password=_env("SEED_PASSWORD"),
        llm_provider=_env("LLM_PROVIDER"),
        llm_model=_env("LLM_MODEL"),
        embed_provider=_env("EMBED_PROVIDER"),
        cad_parser=_env("CAD_PARSER"),
        cad_vision_model=_env("CAD_VISION_MODEL"),
        cad_iou_threshold=float(_env("CAD_IOU_THRESHOLD", "0.5")),
        hypotheses={
            k: Hypothesis(_env(k, d), dec, what) for k, d, dec, what in _HYPOTHESES
        },
    )
