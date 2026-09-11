"""외부 표준문서 수집·임베딩 (MES-TD4-049).

  `IF_EXT_DOCUMENTS`(수신) → 텍스트 추출 → 청크 분할 → `AGT_VECTOR_DOCS` → `IF_DOC_EMBED_LOGS`

**임베딩 공급자가 없으면 벡터를 만들지 않는다.** `EMBEDDING` 을 NULL 로 두고
검색은 `tsvector_keyword` 로 내려간다(D-08). 0벡터를 채워 넣어 "임베딩 된 척" 하지 않는다.
벡터 차원은 **1536**(D-31)이고 그 값은 TD5 가 정했다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import conn

from ..app.settings import settings
from ..app.util import http
from . import llm, retrieval

CHUNK_CHARS = 600          # 청크 길이 — 문단 경계를 우선하고 넘치면 자른다
IF_STATUSES = ("수신", "변환", "완료")
_BLANK = re.compile(r"\n\s*\n")


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """문단 단위로 모으고 길이를 넘으면 끊는다. 빈 청크는 만들지 않는다."""
    out: list[str] = []
    buf = ""
    for para in _BLANK.split(text.strip()):
        p = " ".join(para.split())
        if not p:
            continue
        if buf and len(buf) + len(p) + 1 > size:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf} {p}".strip()
        while len(buf) > size:
            out.append(buf[:size])
            buf = buf[size:]
    if buf:
        out.append(buf)
    return out


def register_document(*, doc_name: str, doc_type: str, source_path: str,
                      doc_version: str | None = None, embed_target: bool = True) -> int:
    """`IF_EXT_DOCUMENTS` 등록. 같은 (문서명, 경로) 는 다시 만들지 않는다(멱등)."""
    row = conn.q1("select EXT_DOC_ID from IF_EXT_DOCUMENTS where DOC_NAME = %s and SOURCE_PATH = %s",
                  (doc_name, source_path))
    if row:
        return int(row["ext_doc_id"])
    row = conn.q1(
        "insert into IF_EXT_DOCUMENTS "
        "(DOC_NAME, DOC_TYPE, SOURCE_PATH, DOC_VERSION, COLLECT_DT, EMBED_TARGET_YN, IF_STATUS, CREATED_DT) "
        "values (%s,%s,%s,%s, now(), %s, %s, now()) returning EXT_DOC_ID",
        (doc_name, doc_type, source_path, doc_version, "Y" if embed_target else "N", "수신"))
    return int(row["ext_doc_id"])


def embed_document(ext_doc_id: int, text: str, *, doc_type: str,
                   access_role: str | None = None, log: bool = True) -> dict[str, Any]:
    """청크 분할 → `AGT_VECTOR_DOCS` 적재 → `IF_DOC_EMBED_LOGS` 기록. **멱등**이다.

    `log=False` 는 **시드 전용**이다. `IF_DOC_EMBED_LOGS` 는 런타임 전용 표라
    깨끗한 DB 에서 0건이어야 한다(G-11) — 시드가 로그를 만들면 그 단언이 깨진다.
    """
    doc = conn.q1("select EXT_DOC_ID, DOC_NAME, SOURCE_PATH from IF_EXT_DOCUMENTS where EXT_DOC_ID = %s",
                  (ext_doc_id,))
    if doc is None:
        raise http.fail("validation", f"외부문서 {ext_doc_id} 가 없다")
    if doc_type not in retrieval.DOC_TYPES:
        raise http.fail("validation", f"문서 구분 어휘 위반: {doc_type!r} (TD5 {retrieval.DOC_TYPES})")

    chunks = chunk(text)
    s = settings()
    model, vectors = None, [None] * len(chunks)
    if s.embed_configured:
        # 구성을 선언했으면 실제로 만들어야 한다. 구현이 없으면 여기서 501 이 난다(조용한 폴백 금지).
        vectors = [llm.embed(c) for c in chunks]
        model = s.embed_provider

    first_doc_id, created = None, 0
    with conn.tx() as cur:
        for seq, (body, vec) in enumerate(zip(chunks, vectors), 1):
            cur.execute(
                "select DOC_ID from AGT_VECTOR_DOCS where DOC_NAME = %s and CHUNK_SEQ = %s",
                (doc["doc_name"], seq))
            row = cur.fetchone()
            if row:
                first_doc_id = first_doc_id or int(row["doc_id"])
                continue
            cur.execute(
                "insert into AGT_VECTOR_DOCS "
                "(DOC_TYPE, DOC_NAME, SOURCE_PATH, CHUNK_SEQ, CHUNK_TEXT, EMBEDDING, EMBED_MODEL, "
                " ACCESS_ROLE, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s, now()) returning DOC_ID",
                (doc_type, doc["doc_name"], doc["source_path"], seq, body, vec, model, access_role))
            first_doc_id = first_doc_id or int(cur.fetchone()["doc_id"])
            created += 1
        if log:
            cur.execute(
                "insert into IF_DOC_EMBED_LOGS "
                "(EXT_DOC_ID, DOC_ID, CHUNK_CNT, EMBED_MODEL, RESULT_CODE, ERROR_MSG, PROCESSED_DT, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s, now(), now())",
                (ext_doc_id, first_doc_id, len(chunks), model, "성공",
                 None if model else "임베딩 미구성 — 벡터 없이 본문만 적재, 검색은 tsvector_keyword (D-08)"))
        cur.execute("update IF_EXT_DOCUMENTS set IF_STATUS = %s where EXT_DOC_ID = %s",
                    ("완료", ext_doc_id))
    return {"ext_doc_id": ext_doc_id, "chunks": len(chunks), "created": created,
            "embed_model": model, "search_mode": s.search_mode}


def import_path(path: Path, *, doc_type: str, access_role: str | None = None) -> dict[str, Any]:
    """텍스트 파일 하나를 수집·적재한다. 바이너리는 **읽지 않고 거부**한다(조용한 추출 금지)."""
    if not path.is_file():
        raise http.fail("validation", f"문서 파일이 없다: {path}")
    if path.suffix.lower() not in (".md", ".txt"):
        raise http.fail(
            "validation",
            f"텍스트 추출기가 없는 형식이다: {path.suffix} — PDF·DOCX 추출기는 미구성 (D-30)")
    ext_id = register_document(doc_name=path.name, doc_type=doc_type, source_path=str(path))
    return embed_document(ext_id, path.read_text(), doc_type=doc_type, access_role=access_role)


def embed_logs(limit: int = 100) -> list[dict[str, Any]]:
    return conn.q(
        "select l.EMBED_LOG_ID, d.DOC_NAME, d.DOC_TYPE, l.CHUNK_CNT, l.EMBED_MODEL, "
        "       l.RESULT_CODE, l.ERROR_MSG, l.PROCESSED_DT "
        "from IF_DOC_EMBED_LOGS l join IF_EXT_DOCUMENTS d on d.EXT_DOC_ID = l.EXT_DOC_ID "
        "order by l.PROCESSED_DT desc, l.EMBED_LOG_ID desc limit %s", (max(1, min(limit, 500)),))
