"""근거 표기 — 시안 `citations.py` 를 이식한다.

시안은 OpenAI 응답 주석에서 파일명을 뽑았지만, 우리 근거는 **우리가 검색한 `AGT_VECTOR_DOCS` 행**이다.
그래서 "모델이 말한 출처" 가 아니라 **"실제로 조회한 출처"** 만 근거가 된다 —
프롬프트 8번(검색으로 확인되지 않은 문서명을 지어내지 않는다)을 코드로 강제하는 자리다.

`AGT_QUERY_LOGS.REF_DOC_IDS` 는 `VARCHAR(300)` 이라 넘치면 **넘쳤다고 적고 자른다.**
"""
from __future__ import annotations

from typing import Iterable

from .retrieval import Evidence

REF_DOC_IDS_MAX = 300
NO_EVIDENCE_LINE = "근거: 확인된 자료 없음"


def sources(evidence: Iterable[Evidence]) -> list[str]:
    """실제 검색된 문서명만, 순서 유지·중복 제거."""
    out: list[str] = []
    for e in evidence:
        if e.doc_name not in out:
            out.append(e.doc_name)
    return out


def evidence_line(evidence: Iterable[Evidence], db_refs: Iterable[str] = ()) -> str:
    """프롬프트 10번 형식의 마지막 줄. 근거가 없으면 그렇게 적는다."""
    parts = [*db_refs, *sources(evidence)][:3]
    return f"근거: {' / '.join(parts)}" if parts else NO_EVIDENCE_LINE


def ref_doc_ids(evidence: Iterable[Evidence]) -> str | None:
    """`AGT_QUERY_LOGS.REF_DOC_IDS` 용 — 300자를 넘으면 잘린 사실을 남긴다."""
    ids = [str(e.doc_id) for e in evidence]
    if not ids:
        return None
    joined = ",".join(dict.fromkeys(ids))
    if len(joined) <= REF_DOC_IDS_MAX:
        return joined
    cut = joined[: REF_DOC_IDS_MAX - 4]
    return cut[: cut.rfind(",")] + ",…"


def merge(accumulated: list[Evidence], new: Iterable[Evidence]) -> list[Evidence]:
    """도구 라운드마다 근거를 누적한다. 마지막 응답만 보면 앞 라운드 근거가 사라진다(시안 교훈)."""
    seen = {(e.doc_id, e.chunk_seq) for e in accumulated}
    for e in new:
        if (e.doc_id, e.chunk_seq) in seen:
            continue
        seen.add((e.doc_id, e.chunk_seq))
        accumulated.append(e)
    return accumulated
