"""오류 계약 (goal.md §2.5) — QA1 이 그대로 테스트 케이스로 쓴다.

**조용한 실패 금지.** `try/except` 로 하드코딩 결과를 끼워넣지 않는다. 실패는 사용자에게 보인다.
상태 코드·화면 문구를 여기 한 곳에만 둔다 — 라우터가 각자 문구를 만들면 계약이 깨진다.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class ErrorCase:
    key: str
    status: int
    message: str
    note: str = ""


# §2.5 표 그대로. 순서·문구를 바꾸면 QA1 테스트가 깨진다.
CASES: tuple[ErrorCase, ...] = (
    ErrorCase("validation", 422, "입력값을 확인해 주세요",
              "필수값 누락 / 코드 중복 / 상·하한 역전 / 검사 합격 아닌 LOT 출하 선택 / 승인 전 견적 확정"),
    ErrorCase("unauthenticated", 401, "로그인이 필요합니다"),
    ErrorCase("forbidden", 403, "접근 권한이 없습니다",
              "권한 없음 / 승인 권한 없는 추천값 반영 (G-24·G-28)"),
    ErrorCase("db_down", 503, "서비스 일시 중단"),
    ErrorCase("llm_unconfigured", 501, "LLM 미구성",
              "API 키 없음 — 조용한 폴백 금지 (D-08)"),
    ErrorCase("cad_unconfigured", 501, "CAD Parsing 미구성 (D-05)",
              "Autodesk API·YOLOv8 미확보 — 조용히 합성 Feature 를 내지 않는다"),
    ErrorCase("internal", 500, "처리 중 오류가 발생했습니다",
              "SYS_ACCESS_LOGS 기록 + 공통 오류 화면"),
)

BY_KEY: dict[str, ErrorCase] = {c.key: c for c in CASES}

# 200 으로 렌더하되 **숨기지 않는** 상태 (§2.5 하단 4행)
NOTICE_EMBEDDING = "검색 모드: tsvector_keyword (D-08)"
NOTICE_RAG_NO_EVIDENCE = "검토 필요 — 근거 부족"
NOTICE_INGEST_STALE = "수집 중단 — 마지막 수집 {ts}"
NOTICE_UNDETERMINED = "미확정 ({decision})"
NOTICE_NOT_COLLECTED = "미수집 ({decision})"


def fail(key: str, detail: str = "") -> HTTPException:
    """계약된 오류만 낸다. 없는 key 는 즉시 터진다 — 새 상태를 몰래 만들지 않는다."""
    case = BY_KEY[key]
    return HTTPException(
        status_code=case.status,
        detail={"key": case.key, "message": case.message, "detail": detail},
    )


def undetermined(decision: str) -> str:
    """값이 없을 때 화면에 렌더하는 문구. 지어내지 않는다(goal.md §0.2)."""
    return NOTICE_UNDETERMINED.format(decision=decision)


def not_collected(decision: str) -> str:
    return NOTICE_NOT_COLLECTED.format(decision=decision)
