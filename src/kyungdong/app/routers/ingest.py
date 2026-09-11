"""화면 없는 인터페이스 3종 (개발3) — TD4-047 수집 · TD4-048 CAD · TD4-049 문서.

`contracts/api-contract.md` §3 의 제안 엔드포인트를 그대로 쓴다. **화면이 없으므로 `SCREENS` 는 비어 있다.**
연계 상태 조회는 `/dat/033`(개발1) 가 하고, 수집 중단 배지는 `/dsh/003`·`/prc/022`(개발2)가 쓴다 —
그래서 `GET /api/ingest/status` 와 `ingest.collector.status()` 를 **공표 시그니처**로 둔다.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from ...agent import docs as agent_docs
from ...ingest import collector
from .. import rbac
from ..util import csrf, http
from ..util.audit import audit

import conn  # noqa: E402

router = APIRouter()
SCREENS: tuple[str, ...] = ()          # 화면 없음 — placeholder 대상이 아니다

INGEST_AREA = "데이터관리"
CAD_AREA = "수주견적AI관리"


def _role(request: Request) -> str:
    return getattr(request.state, "role_code", "") or ""


def _need_write(request: Request, area: str) -> str:
    role = _role(request)
    if not rbac.can_write(role, area):
        raise http.fail("forbidden", f"{area} 등록 권한 없음")
    return role


# ── MES-TD4-047 IoT/PLC 수집 ──────────────────────────────────────────────
@router.post("/api/ingest/plc")
async def ingest_plc(request: Request) -> dict[str, Any]:
    """태그 배열을 한 트랜잭션으로 적재한다. **수집 지점 2개소뿐**(D-06).

    body: `{"device_id": 1, "equip_code": "EQ10", "samples": [{"tag","value","collect_dt"}...]}`
    """
    # 폼이 아니라 **JSON 본문**이다 — 토큰은 헤더 `X-CSRF-Token` 으로 받는다(§5 · G-26).
    csrf.require(request, csrf.token_of(request))         # 핸들러 첫 줄 (contracts §5)
    _need_write(request, INGEST_AREA)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # 본문 파싱 실패는 **422** 다 — 계약 §4.0. 500 을 내면 서버 결함처럼 보인다(DEF-QA1-006).
        raise http.fail("validation", f"수집 payload 를 JSON 으로 읽지 못했다: {e}") from e
    if not isinstance(body, dict):
        raise http.fail("validation", "수집 payload 는 객체여야 한다")
    samples = collector.parse_samples(body.get("samples") or [])
    res = collector.ingest_batch(int(body.get("device_id", 0)), str(body.get("equip_code", "")),
                                 samples, collect_path=str(body.get("collect_path")
                                                           or collector.COLLECT_PATH))
    audit(request, None, "PLC수집", log_type="API")
    return {"received": res.received, "stored": res.stored, "duplicated": res.duplicated,
            "signal_rows": res.signal_rows, "timeseries_rows": res.timeseries_rows,
            "ordered": res.ordered}


@router.get("/api/ingest/status")
async def ingest_status(request: Request) -> dict[str, Any]:
    """수집 상태 — `/dsh/003`·`/prc/022` 배지의 단일 소스. `collector.status()` 와 같은 값이다."""
    if not rbac.can_read(_role(request), INGEST_AREA):
        raise http.fail("forbidden", f"{INGEST_AREA} 조회 권한 없음")
    return collector.status()


@router.post("/api/ingest/gateway/resend")
async def ingest_resend(request: Request) -> dict[str, Any]:
    """Gateway 버퍼 재전송 — 최초 저장 순서대로, 유실 0."""
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))   # 핸들러 첫 줄 (contracts §5 · G-26)
    _need_write(request, INGEST_AREA)
    raw_device = str(form.get("device_id") or "").strip()
    if raw_device and not raw_device.lstrip("-").isdigit():
        raise http.fail("validation", f"device_id 는 정수여야 한다: {raw_device!r}")
    device_id = int(raw_device) if raw_device else None
    out = collector.resend(device_id)
    audit(request, None, "Gateway재전송", log_type="API")
    return out


# ── MES-TD4-048 CAD 파일 수집 ─────────────────────────────────────────────
@router.post("/api/cad/files")
async def cad_upload(request: Request, file: UploadFile = File(...),
                     collect_method: str = Form("업로드")) -> dict[str, Any]:
    """형식·크기 검증 → 중복·손상 제외 → `IF_CAD_FILES` 등록.

    **원본 바이너리를 저장하지 않는다** — Data Lake(Object Storage) 가 미구성이라
    `DAT_LAKE_OBJECTS` 적재 경로가 없다. 저장한 척하지 않고 그 사실을 응답에 적는다.
    """
    from ...cad import inventory as cad_inv

    # multipart 업로드다 — 토큰은 폼 필드(`_csrf`) 또는 헤더로 받는다(§5 · G-26).
    csrf.require(request, csrf.token_of(request, await request.form()))
    _need_write(request, CAD_AREA)
    raw = await file.read()
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].upper() if "." in name else ""
    if ext not in cad_inv.FILE_TYPES:
        raise http.fail("validation", f"지원 형식이 아니다: {ext or '(없음)'} — {cad_inv.FILE_TYPES}")
    dup = conn.q1("select CAD_IF_ID from IF_CAD_FILES where ORIGIN_FILE_NAME = %s", (name,))
    excluded = None
    if len(raw) == 0:
        excluded = cad_inv.EXCLUDE_ZERO
    elif dup:
        excluded = cad_inv.EXCLUDE_DUP
    with conn.tx() as cur:
        cur.execute(
            "insert into IF_CAD_FILES "
            "(ORIGIN_FILE_NAME, FILE_TYPE, SOURCE_PATH, FILE_SIZE, COLLECT_METHOD, IF_STATUS, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s, now()) returning CAD_IF_ID",
            (name, ext, f"upload://{name}", len(raw), collect_method,
             "제외" if excluded else "수신"))
        cad_if_id = int(cur.fetchone()["cad_if_id"])
        cur.execute(
            "insert into IF_CAD_IMPORT_LOGS "
            "(CAD_IF_ID, STEP_NAME, RESULT_CODE, EXCLUDE_REASON, PROCESSED_DT, CREATED_DT) "
            "values (%s,%s,%s,%s, now(), now())",
            (cad_if_id, "검증", "제외" if excluded else "성공", excluded))
    audit(request, "MES-TD3-010", "CAD업로드", log_type="API")
    return {"cad_if_id": cad_if_id, "file_name": name, "size": len(raw),
            "excluded_reason": excluded,
            "note": "원본은 보관하지 않았다 — Data Lake(Object Storage) 미구성. "
                    "분석 실행은 CAD Parsing 미구성으로 501 이다 (D-05)."}


@router.get("/api/cad/import-logs")
async def cad_logs(request: Request, limit: int = 100) -> dict[str, Any]:
    if not rbac.can_read(_role(request), CAD_AREA):
        raise http.fail("forbidden", f"{CAD_AREA} 조회 권한 없음")
    rows = conn.q(
        "select l.CAD_LOG_ID, f.ORIGIN_FILE_NAME, f.FILE_TYPE, l.STEP_NAME, l.RESULT_CODE, "
        "       l.EXCLUDE_REASON, l.PROCESSED_DT, l.ERROR_MSG "
        "from IF_CAD_IMPORT_LOGS l join IF_CAD_FILES f on f.CAD_IF_ID = l.CAD_IF_ID "
        "order by l.CAD_LOG_ID desc limit %s", (max(1, min(limit, 500)),))
    return {"rows": rows, "count": len(rows)}


# ── MES-TD4-049 외부 표준문서 수집 ────────────────────────────────────────
@router.post("/api/docs/import")
async def docs_import(request: Request, doc_name: str = Form(...), doc_type: str = Form(...),
                      source_path: str = Form(...), text: str = Form(...),
                      access_role: str = Form("")) -> dict[str, Any]:
    """텍스트 → 청크 → `AGT_VECTOR_DOCS`. 임베딩 미구성이면 벡터 없이 본문만 적재한다(D-08)."""
    csrf.require(request, csrf.token_of(request, await request.form()))
    _need_write(request, INGEST_AREA)
    ext_id = agent_docs.register_document(doc_name=doc_name, doc_type=doc_type,
                                          source_path=source_path)
    out = agent_docs.embed_document(ext_id, text, doc_type=doc_type,
                                    access_role=access_role or None)
    audit(request, None, "문서임베딩", log_type="API")
    return out


@router.get("/api/docs/embed-logs")
async def docs_logs(request: Request, limit: int = 100) -> dict[str, Any]:
    if not rbac.can_read(_role(request), INGEST_AREA):
        raise http.fail("forbidden", f"{INGEST_AREA} 조회 권한 없음")
    rows = agent_docs.embed_logs(limit)
    return {"rows": rows, "count": len(rows)}
