"""폐쇄형 검색 — `AGT_VECTOR_DOCS` **하나만** 본다. 외부 검색 0 (사업계획서 9.2 ⑤).

검색 모드는 두 가지이고 **어느 쪽인지 화면에 라벨로 드러낸다**(D-08 · §2.5).

  · `vector_pgvector`   — 임베딩 공급자가 구성됐을 때. 벡터 차원 **1536**(D-31, TD5 명시)
  · `tsvector_keyword`  — 임베딩 미구성. 200 으로 응답하되 **모드를 숨기지 않는다**

한국어는 조사가 붙어 `to_tsvector('simple', …)` 만으로는 놓치는 것이 많다. 그래서 시안과 같은
**바이그램 보조 검색**을 둔다 — 사전 없이도 조사·띄어쓰기 흔들림을 견딘다.

`ACCESS_ROLE` 이 적힌 문서는 그 역할에게만 준다(TD5 비고 '폐쇄형 접근 통제').
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import conn

from ..app.settings import settings
from ..app.util import http

VECTOR_DIM = 1536          # D-31 — TD5 `AGT_VECTOR_DOCS.EMBEDDING VECTOR(1536)`

MODE_VECTOR = "vector_pgvector"
MODE_KEYWORD = "tsvector_keyword"

# TD5 `AGT_VECTOR_DOCS.DOC_TYPE` 비고 어휘
DOC_TYPES: tuple[str, ...] = ("입고기준서", "검사기준서", "SOP", "출하기준서", "클레임 매뉴얼")

# Agent 3종이 보는 문서 범위 (TD3 009·020·038 '참조 문서 범위')
SCOPE: dict[str, tuple[str, ...]] = {
    "입고": ("입고기준서", "검사기준서", "SOP"),
    "출하": ("출하기준서", "검사기준서", "클레임 매뉴얼"),
    "통합": DOC_TYPES,
}

_WORD = re.compile(r"[가-힣A-Za-z0-9]+")


@dataclass(frozen=True)
class Evidence:
    doc_id: int
    doc_type: str
    doc_name: str
    source_path: str | None
    chunk_seq: int
    chunk_text: str
    score: float
    mode: str

    @property
    def snippet(self) -> str:
        t = " ".join(self.chunk_text.split())
        return t if len(t) <= 200 else t[:200] + "…"


def terms_of(query: str) -> list[str]:
    """단어 + 바이그램. 2글자 미만은 버린다(시안 `search_knowledge` 와 같은 방식)."""
    words = [w.lower() for w in _WORD.findall(query)]
    grams = {w for w in words if len(w) >= 2}
    for w in words:
        grams.update(w[i:i + 2] for i in range(len(w) - 1))
    return sorted(g for g in grams if len(g) >= 2)


def corpus_size(agent_type: str = "통합") -> dict[str, Any]:
    scope = SCOPE.get(agent_type, DOC_TYPES)
    row = conn.q1(
        "select count(*) as chunks, count(distinct DOC_NAME) as docs, "
        "       count(EMBEDDING) as embedded "
        "from AGT_VECTOR_DOCS where DOC_TYPE = any(%s)",
        (list(scope),),
    )
    return {"chunks": int(row["chunks"]), "docs": int(row["docs"]),
            "embedded": int(row["embedded"]), "scope": list(scope)} if row else \
           {"chunks": 0, "docs": 0, "embedded": 0, "scope": list(scope)}


def _accessible(role_code: str) -> tuple[str, list[Any]]:
    return "(ACCESS_ROLE is null or ACCESS_ROLE = %s)", [role_code or ""]


def search(query: str, *, agent_type: str = "통합", role_code: str = "",
           limit: int = 5) -> tuple[list[Evidence], str]:
    """(근거, 검색모드). **없으면 빈 리스트다 — 지어내지 않는다.**"""
    q = (query or "").strip()
    if not q:
        raise http.fail("validation", "질의 내용을 입력해 주세요")
    s = settings()
    scope = list(SCOPE.get(agent_type, DOC_TYPES))
    role_sql, role_params = _accessible(role_code)

    if s.embed_configured:
        # 임베딩 공급자가 구성됐다고 선언됐다면 벡터 검색을 해야 한다.
        # 실제 임베딩 호출은 `llm.embed()` 가 맡고, 구성이 가짜면 거기서 501 이 난다.
        from . import llm
        vec = llm.embed(q)
        rows = conn.q(
            "select DOC_ID, DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT, "
            "       1 - (EMBEDDING <=> %s::vector) as score "
            "from AGT_VECTOR_DOCS "
            f"where EMBEDDING is not null and DOC_TYPE = any(%s) and {role_sql} "
            "order by EMBEDDING <=> %s::vector limit %s",
            [vec, scope, *role_params, vec, limit],
        )
        return ([Evidence(int(r["doc_id"]), r["doc_type"], r["doc_name"], r["source_path"],
                          int(r["chunk_seq"]), r["chunk_text"], float(r["score"]), MODE_VECTOR)
                 for r in rows], MODE_VECTOR)

    # ── tsvector 키워드 (D-08) ───────────────────────────────────────────
    rows = conn.q(
        "select DOC_ID, DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT, "
        "       ts_rank_cd(to_tsvector('simple', DOC_NAME || ' ' || CHUNK_TEXT), "
        "                  plainto_tsquery('simple', %s)) as score "
        "from AGT_VECTOR_DOCS "
        f"where DOC_TYPE = any(%s) and {role_sql} "
        "  and to_tsvector('simple', DOC_NAME || ' ' || CHUNK_TEXT) @@ plainto_tsquery('simple', %s) "
        "order by score desc, DOC_ID, CHUNK_SEQ limit %s",
        [q, scope, *role_params, q, limit],
    )
    if rows:
        return ([Evidence(int(r["doc_id"]), r["doc_type"], r["doc_name"], r["source_path"],
                          int(r["chunk_seq"]), r["chunk_text"],
                          _norm_rank(float(r["score"])), MODE_KEYWORD)
                 for r in rows], MODE_KEYWORD)

    # 바이그램 보조 — 조사·띄어쓰기 때문에 tsquery 가 놓친 것을 잡는다
    grams = terms_of(q)
    if not grams:
        return ([], MODE_KEYWORD)
    patterns = [f"%{g}%" for g in grams]
    rows = conn.q(
        "select DOC_ID, DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT "
        "from AGT_VECTOR_DOCS "
        f"where DOC_TYPE = any(%s) and {role_sql} "
        "  and (DOC_NAME ilike any(%s) or CHUNK_TEXT ilike any(%s)) "
        "order by DOC_ID, CHUNK_SEQ",
        [scope, *role_params, patterns, patterns],
    )
    scored: list[Evidence] = []
    for r in rows:
        hay = f"{r['doc_name']} {r['chunk_text']}".lower()
        hit = sum(1 for g in grams if g in hay)
        if not hit:
            continue
        scored.append(Evidence(int(r["doc_id"]), r["doc_type"], r["doc_name"], r["source_path"],
                               int(r["chunk_seq"]), r["chunk_text"], hit / len(grams), MODE_KEYWORD))
    scored.sort(key=lambda e: (-e.score, e.doc_id, e.chunk_seq))
    return (scored[:limit], MODE_KEYWORD)


def _norm_rank(rank: float) -> float:
    """`ts_rank_cd` 는 상한이 없다 — 0~1 로 눌러서 임계값(D-10)과 비교 가능하게 한다."""
    return rank / (rank + 1.0)


def confidence(evidence: list[Evidence]) -> float:
    """상위 근거 점수. 근거가 없으면 0.0 이다 — 임계와 무관하게 항상 `근거 부족` 분기다(D-10)."""
    return max((e.score for e in evidence), default=0.0)
