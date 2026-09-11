"""폐쇄형 RAG Agent (MES-TD4-009·020·038) — **외부 검색 0.**

사업계획서 9.2 ⑤: RAG AI Agent 는 **내부 데이터만 접근 가능한 폐쇄형 구조**다.
근거 문서는 `AGT_VECTOR_DOCS`(작업표준·품질기준·검사기준·MTC 기준·클레임 이력) 뿐이고,
운영 데이터는 D-20 재배선 표가 정한 TD5 테이블에서만 읽는다.

지키는 것
  · **근거 0건이면 LLM 을 부르지 않는다** — `검토 필요 — 근거 부족` + 담당자 이관.
  · **검색하지 않은 문서명·조항·페이지를 지어내지 않는다**(프롬프트 7~10).
  · 질의·응답·근거·응답시간을 `AGT_QUERY_LOGS` 에 **100% 기록**한다.
  · LLM 키가 없으면 **501 `LLM 미구성`** — 조용한 폴백을 만들지 않는다(D-08).
  · 임베딩이 없으면 200 + `tsvector_keyword` 라벨(D-08). 벡터 차원은 1536(D-31).
  · AI 는 **추천까지**다. 쓰기 동사 금지 · 승인 필요 명시(G-24).

시안(`08 AI Agent Making Agent/.../kyungdong-globaltech-ai-agent`)에서 **이식**한 것:
`factory_tools.py` 도구 시그니처 · `prompts.py` 11원칙 · `citations.py`.
**버린 것**: SQLite 스키마 · `demo_data` · 데모 예측 상수 · Streamlit · `voice.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DB = str(Path(__file__).resolve().parents[3] / "db")
if _DB not in sys.path:
    sys.path.insert(0, _DB)

AGENT_TYPES: tuple[str, ...] = ("입고", "출하", "통합")   # TD5 AGT_QUERY_LOGS.AGENT_TYPE 비고
