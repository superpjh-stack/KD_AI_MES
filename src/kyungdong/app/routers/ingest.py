"""화면 없는 인터페이스 3종 (개발3) — TD4-047 수집 · TD4-048 CAD · TD4-049 문서.

`contracts/api-contract.md` §3 의 제안 엔드포인트를 그대로 쓴다. **화면이 없으므로 `SCREENS` 는 비어 있다.**
연계 상태 조회는 `/dat/033`(개발1) 가 하고, 수집 중단 배지는 `/dsh/003`·`/prc/022`(개발2)가 쓴다 —
그래서 `GET /api/ingest/status` 와 `ingest.collector.status()` 를 **공표 시그니처**로 둔다.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from ...agent import docs as agent_docs
from ...ingest import collector, mes
from .. import rbac
from ..util import csrf, device, http
from ..util.audit import audit

import conn  # noqa: E402

router = APIRouter()
SCREENS: tuple[str, ...] = ()          # 화면 없음 — placeholder 대상이 아니다

INGEST_AREA = "데이터관리"
CAD_AREA = "수주견적AI관리"


def _role(request: Request) -> str:
    return getattr(request.state, "role_code", "") or ""


def _need_write(request: Request, area: str) -> str:
    """쓰기 권한. **사람은 역할로, 장비는 등록으로** 통과한다 (D-103 · D-168).

    이 라우터의 4개 경로는 **기계가 부른다.** 사람 세션이 없으므로 prod 에서는 역할이 빈
    문자열이고 그대로면 전부 403 이다 — 실측 확인했다: prod `POST /api/ingest/plc` = **403**.
    개발에서는 `x-kyungdong-role` 헤더가 SYSADMIN 을 주기 때문에 게이트가 전부 통과해
    이것이 보이지 않았다. **PLC 와 Gateway 가 운영에서 데이터를 넣지 못한다.**

    그래서 역할로 막힌 뒤 **등록된 장비인지 한 번 더 본다.** 지금은 `IF_DEVICE_REGISTRY` 의
    IP 가 전부 NULL 이라 **아무도 통과하지 못한다** — 동작은 그대로다. 바뀌는 것은
    **진단**이다: `데이터관리 등록 권한 없음`(권한 설정을 뒤지게 된다) 대신 무엇이 비었는지
    말한다. IP 가 등록되면 그때 이 경로가 열린다.
    """
    role = _role(request)
    if rbac.can_write(role, area):
        return role
    dev = device.identify(request)
    if dev is not None:
        request.state.device = dev
        return f"장비:{dev.device_id} {dev.name}"
    if request.url.path in device.MACHINE_PATHS:
        raise http.fail("forbidden",
                        f"{area} 쓰기 — 사람 세션도 등록된 수집 장비도 아니다. "
                        f"{device.reason(request)} · {device.LIMIT_NOTE}")
    raise http.fail("forbidden", f"{area} 등록 권한 없음")


def _device_id(request: Request, body: dict[str, Any]) -> int:
    """`device_id` 검증 — **틀린 입력은 422 다. 500 이 아니다**(§2.5 · DEF-QA1-006).

    전에는 `int(body.get("device_id", 0))` 였다 — `{"device_id": "abc"}` 하나로 **500** 이
    났다(서버 결함처럼 보인다). 그리고 빠뜨리면 `0` 이 되어 FK 위반 500 으로 갔다.

    보내는 쪽이 **등록된 장비로 인증됐으면**(D-168) 그 장비의 번호와 같아야 한다 —
    A 장비가 B 장비 번호로 적재하면 수집 지점 2개소(D-06)의 계보가 깨진다.
    사람 세션이면 `IF_DEVICE_REGISTRY` 에 **쓰는 중인 장비**로 등록돼 있는지 본다.
    """
    raw = body.get("device_id")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise http.fail("validation", "필수값 누락: device_id")
    if isinstance(raw, bool) or not str(raw).strip().lstrip("-").isdigit():
        raise http.fail("validation", f"device_id 는 정수여야 한다: {raw!r}")
    device_id = int(str(raw).strip())

    dev = getattr(request.state, "device", None)
    if dev is not None:
        if int(dev.device_id) != device_id:
            raise http.fail(
                "validation",
                f"device_id 가 인증 장비와 다르다: 본문 {device_id} · 인증 {dev.device_id} "
                f"({dev.name})")
        return device_id

    row = conn.q1("select DEVICE_ID, DEVICE_NAME, USE_YN from IF_DEVICE_REGISTRY "
                  "where DEVICE_ID = %s", (device_id,))
    if row is None:
        raise http.fail("validation",
                        f"IF_DEVICE_REGISTRY 에 없는 장비다: device_id={device_id} — "
                        "수집 지점은 등록된 2개소뿐이다 (D-06)")
    if str(row["use_yn"]).upper() != "Y":
        raise http.fail("validation",
                        f"사용하지 않는 장비다(USE_YN={row['use_yn']}): "
                        f"{row['device_name']} (device_id={device_id})")
    return device_id


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
    device_id = _device_id(request, body)
    samples = collector.parse_samples(body.get("samples") or [])
    res = collector.ingest_batch(device_id, str(body.get("equip_code", "")),
                                 samples, collect_path=str(body.get("collect_path")
                                                           or collector.COLLECT_PATH),
                                 work_order_id=_work_order_id(body))
    audit(request, None, "PLC수집", log_type="API")
    return {"received": res.received, "stored": res.stored, "duplicated": res.duplicated,
            "signal_rows": res.signal_rows, "timeseries_rows": res.timeseries_rows,
            "ordered": res.ordered, "mes": res.mes.as_dict()}


def _work_order_id(body: dict[str, Any]) -> int | None:
    """현장POP 이 지정한 작업지시(선택). 있으면 정수여야 한다 — 아니면 **422** (§2.5)."""
    raw = body.get("work_order_id")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool) or not str(raw).strip().isdigit():
        raise http.fail("validation", f"work_order_id 는 양의 정수여야 한다: {raw!r}")
    return int(str(raw).strip())


LIVE_AREAS = ("AI 대시보드", "공정관리", INGEST_AREA)


@router.get("/api/ingest/live")
async def ingest_live(request: Request, equip: str = mes.AUTO_EQUIP, n: int = 30) -> dict[str, Any]:
    """실시간 패널의 단일 소스 (D-223) — 화면 003·022 가 처음 그릴 때와 갱신할 때 **같은 함수**를 본다.

    조회 권한은 그 두 화면과 같다 — 대시보드·공정관리·데이터관리 중 하나를 읽을 수 있으면 된다.
    값은 전부 DB 에 적재된 것이고, 시뮬레이터 데이터면 `simulation` 에 그 선언이 실린다(D-174).
    """
    role = _role(request)
    if not any(rbac.can_read(role, a) for a in LIVE_AREAS):
        raise http.fail("forbidden", "실시간 조회 권한 없음 — 대시보드·공정관리·데이터관리 중 하나가 필요하다")
    if equip not in (mes.AUTO_EQUIP, "EQ20"):
        raise http.fail("validation", f"수집 지점은 2개소뿐이다 (D-06): {equip!r}")
    if n < 1 or n > 200:
        raise http.fail("validation", f"n 은 1~200 이다: {n}")
    return mes.live_snapshot(equip, n)


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
async def cad_upload(request: Request) -> dict[str, Any]:
    """형식·크기 검증 → 중복·손상 제외 → `IF_CAD_FILES` 등록.

    **원본 바이너리를 저장하지 않는다** — Data Lake(Object Storage) 가 미구성이라
    `DAT_LAKE_OBJECTS` 적재 경로가 없다. 저장한 척하지 않고 그 사실을 응답에 적는다.

    `File(...)`·`Form(...)` 을 시그니처에 두면 FastAPI 가 **검사 순서보다 먼저** 본문을
    파싱해서, 권한 없는 사람이 파일 없이 부르면 403 이 아니라 FastAPI 의 **원시 JSON 422**
    를 받는다 — 계약 §4.0 의 `CSRF → 권한 → 입력값` 이 뒤집힌다. 그래서 `/est/011/review`
    처럼 **핸들러 안에서** 폼을 읽는다.
    """
    from ...cad import inventory as cad_inv

    # multipart 업로드다 — 토큰은 폼 필드(`_csrf`) 또는 헤더로 받는다(§5 · G-26).
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))
    _need_write(request, CAD_AREA)
    file = form.get("file")
    if file is None or not hasattr(file, "read") or not hasattr(file, "filename"):
        raise http.fail("validation", "필수값 누락: file (multipart 파일 1개)")
    collect_method = str(form.get("collect_method") or "업로드")
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
                    + ("분석 실행은 010 화면의 행 버튼이다 — dwg2dxf 파서 (D-235). 업로드 원본은 보관하지 "
                       "않으므로 아카이브에 있는 도면만 분석된다."
                       if __import__("kyungdong.cad.provider", fromlist=["x"]).parsing_configured()
                       else "분석 실행은 CAD Parsing 미구성으로 501 이다 (D-05).")}


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
async def docs_import(request: Request) -> dict[str, Any]:
    """텍스트 → 청크 → `AGT_VECTOR_DOCS`. 임베딩 미구성이면 벡터 없이 본문만 적재한다(D-08).

    폼은 **핸들러 안에서** 읽는다 — 시그니처의 `Form(...)` 은 권한 검사보다 먼저 파싱돼
    403 이어야 할 요청에 FastAPI 원시 422 를 내준다(§4.0 검사 순서).
    """
    form = await request.form()
    csrf.require(request, csrf.token_of(request, form))
    _need_write(request, INGEST_AREA)
    got = {}
    for key in ("doc_name", "doc_type", "source_path", "text"):
        got[key] = str(form.get(key) or "").strip()
        if not got[key]:
            raise http.fail("validation", f"필수값 누락: {key}")
    doc_name, doc_type = got["doc_name"], got["doc_type"]
    source_path, text = got["source_path"], got["text"]
    access_role = str(form.get("access_role") or "").strip()
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
