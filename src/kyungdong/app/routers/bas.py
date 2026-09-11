"""기준정보관리 030~032 (개발1) + **개발1 4모듈 공통 헬퍼**.

`inv.py` · `sys.py` · `dat.py` 가 이 모듈의 헬퍼를 가져다 쓴다 (한 파일은 한 사람만 — 전부 개발1 소유).

원칙
  · 화면의 모든 칸은 `design.screen(sid)['mockup']` 문장이다. 목업의 `(예시)` 값은 쓰지 않는다.
  · 값이 없으면 `util.http.undetermined("D-nn")`, 그리드가 0건이면 `util.http.not_collected("D-nn")`.
    **건수 카드의 `0 건` 은 정답이다** — 거기엔 문구를 붙이지 않는다(§10-14).
  · `try/except` 로 하드코딩 결과를 끼워넣지 않는다. DB 장애는 `db/conn.py` 가 503 을 낸다(G-30).
  · 코드성 FK 는 저장 전에 `util.codes.require_code()` 로 막는다 — 어기면 422(D-32).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "db"))

import conn                                              # noqa: E402
from .. import design, nav, rbac                         # noqa: E402
from ..templating import render                          # noqa: E402
from ..util import clock, codes, csrf, http              # noqa: E402
from ..util.audit import audit                           # noqa: E402  (util/__init__ 이 함수를 재노출한다)

router = APIRouter()
SCREENS = ("MES-TD3-030", "MES-TD3-031", "MES-TD3-032")

TEMPLATE = "bas/_list.html"
DEFAULT_SIZE = 20


# ── 공통 헬퍼 (inv·sys·dat 가 import 한다) ────────────────────────────────
def guard(request: Request, sid: str, *, write: bool = False) -> tuple[nav.Screen, dict]:
    """권한 확인 + 정본 로드 + 감사 기록. 권한 없음은 **403**(G-28)."""
    scr = nav.by_id()[sid]
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, scr.area):
        raise http.fail("forbidden", f"{scr.area} 조회 권한 없음")
    if write and not rbac.can_write(role, scr.area):
        raise http.fail("forbidden", f"{scr.area} 등록·수정 권한 없음")
    td3 = design.screen(sid)
    if td3 is None:                       # 정본이 없으면 지어내지 않는다(§0.2)
        raise http.fail("internal", f"{sid} 가 SF-TD3 정본에 없다")
    audit(request, sid, "등록" if write else "조회",
                log_type="변경" if write else "접속", user_id=_user_id(request))
    return scr, td3


def _user_id(request: Request) -> int | None:
    sess = getattr(request.state, "session", None)
    return getattr(sess, "user_id", None)


def can_write(request: Request, sid: str) -> bool:
    return rbac.can_write(getattr(request.state, "role_code", "") or "",
                          nav.by_id()[sid].area)


def undetermined(decision: str) -> dict[str, Any]:
    """값이 없는 셀 — `미확정 (D-nn)` 배지로 렌더한다."""
    return {"text": http.undetermined(decision), "notice": True}


def val(value: Any, decision: str, *, fmt: str | None = None) -> Any:
    """`None`·빈값이면 미확정 배지, 아니면 문자열."""
    if value is None or value == "":
        return undetermined(decision)
    return format(value, fmt) if fmt else str(value)


def dt(value: Any, decision: str = "D-101") -> Any:
    return undetermined(decision) if value is None else value.strftime("%Y-%m-%d %H:%M")


def lot_link(lot_no: str | None, decision: str = "D-101") -> Any:
    """LOT·프로젝트번호 열은 클릭하면 024 공정이력조회로 간다 (G-08 · api-contract §0-5)."""
    if not lot_no:
        return undetermined(decision)
    return {"text": lot_no, "href": f"/prc/024?lot={lot_no}", "title": "024 공정이력조회로 이동"}


def project_link(project_no: str | None, decision: str = "D-101") -> Any:
    if not project_no:
        return undetermined(decision)
    return {"text": project_no, "href": f"/prc/024?project={project_no}",
            "title": "024 공정이력조회로 이동"}


def search_spec(td3: dict, request: Request,
                spec: Sequence[tuple[str, str] | tuple[str, str, list]]) -> list[dict]:
    """목업 `search_fields` 라벨 + 내가 정한 파라미터명. **라벨은 정본에서만 온다.**

    `spec` 은 목업 순서에 1:1 로 맞춘다 — 길이가 다르면 즉시 터진다(조용히 자르지 않는다).
    """
    labels = td3.get("mockup", {}).get("search_fields") or []
    if len(labels) != len(spec):
        raise http.fail("internal",
                        f"조회조건 {len(labels)}개(정본) ≠ {len(spec)}개(라우터) — {td3['id']}")
    out = []
    for label, item in zip(labels, spec):
        name, kind = item[0], item[1]
        f: dict[str, Any] = {"label": label, "name": name, "type": kind,
                             "value": request.query_params.get(name, "")}
        if len(item) > 2:
            f["options"] = item[2]
        out.append(f)
    return out


def code_options(group: str) -> list[dict[str, str]]:
    """`BAS_COMMON_CODES` 그룹의 선택지. 비어 있으면 빈 목록 — 지어내지 않는다."""
    rows = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = %s and USE_YN = 'Y' order by SORT_ORDER, CODE_VALUE", (group,))
    return [{"value": r["code_value"], "label": r["code_name"]} for r in rows]


def code_names(group: str) -> dict[str, str]:
    return {o["value"]: o["label"] for o in code_options(group)}


def tables_panel(sid: str) -> list[dict[str, Any]]:
    """우측 패널의 사용 테이블 + 실측 건수. 0건도 그대로 보여준다(G-11)."""
    scr = nav.by_id()[sid]
    out = []
    for tid in design.program_tables(scr.program_id):
        d = design.table_def(tid) or {}
        row = conn.q1(f"select count(*) as n from {tid}")     # tid 는 정본 테이블 ID (외부 입력 아님)
        out.append({"id": tid, "name": d.get("name", ""), "count": int(row["n"]) if row else None})
    return out


def paginate(request: Request, total: int) -> tuple[dict[str, Any], int, int]:
    """`?page=&size=` (기본 20) — api-contract §0-7."""
    try:
        page = max(1, int(request.query_params.get("page", "1")))
        size = min(200, max(1, int(request.query_params.get("size", str(DEFAULT_SIZE)))))
    except ValueError:
        raise http.fail("validation", "page·size 는 정수다") from None
    pages = max(1, -(-total // size))
    page = min(page, pages)
    keep = [(k, v) for k, v in request.query_params.multi_items() if k != "page"]
    base = "?" + "".join(f"{k}={v}&" for k, v in keep)
    return {"page": page, "size": size, "pages": pages, "base": base}, size, (page - 1) * size


def anchor_label() -> str:
    """시간 기준일은 `SYS_CONFIGS` 앵커다 — `date.today()` 금지(§10-3)."""
    return clock.anchor().strftime("%Y-%m-%d %H:%M")


def screen_page(request: Request, sid: str, **ctx: Any):
    """공통 목록 화면 렌더. 목업의 buttons·description 을 그대로 넘긴다."""
    scr, td3 = ctx.pop("_loaded", (None, None))
    if scr is None:
        scr, td3 = guard(request, sid)
    mock = td3.get("mockup") or {}
    base: dict[str, Any] = {
        "screen": scr,
        "current": scr,
        "td3": td3,
        "buttons": mock.get("buttons") or [],
        "description": mock.get("description") or [],
        "columns": mock.get("grid_columns") or [],
        "rows": [],
        "empty_notice": http.not_collected("D-101"),
        "panels": [],
        "notices": [],
        "tables": tables_panel(sid),
        "anchor_dt": anchor_label(),
        "can_write": can_write(request, sid),
        "search": [],
        "cards": [],
        "form": None,
        "pager": None,
    }
    base.update(ctx)
    return render(request, TEMPLATE, **base)


def redirect(path: str) -> RedirectResponse:
    """POST 후 목록으로 — 새로고침 재전송을 막는다."""
    return RedirectResponse(path, status_code=303)


def require_fields(form: Any, names: Iterable[str]) -> dict[str, str]:
    """필수값 누락은 **422**(§2.5 '필수값 누락')."""
    out = {}
    for n in names:
        v = (form.get(n) or "").strip()
        if not v:
            raise http.fail("validation", f"필수값 누락: {n}")
        out[n] = v
    return out


def opt_num(form: Any, name: str) -> float | None:
    v = (form.get(name) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        raise http.fail("validation", f"{name} 은 숫자다: {v!r}") from None


# ═════════════════════════════════════════════════════════════════════════
# 030 품질기준 관리
# ═════════════════════════════════════════════════════════════════════════
@router.get("/bas/030")
async def quality_standards(request: Request):
    sid = "MES-TD3-030"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("code"):
        where.append("QSTD_CODE ilike %s"); params.append(f"%{q['code']}%")
    if q.get("pg"):
        where.append("PRODUCT_GROUP = %s"); params.append(q["pg"])
    if q.get("it"):
        where.append("INSPECT_TYPE = %s"); params.append(q["it"])
    if q.get("item"):
        where.append("INSPECT_ITEM ilike %s"); params.append(f"%{q['item']}%")
    if q.get("spec"):
        where.append("STANDARD_SPEC ilike %s"); params.append(f"%{q['spec']}%")
    if q.get("use"):
        where.append("USE_YN = %s"); params.append(q["use"])
    cond = " and ".join(where)

    total = int(conn.q1(f"select count(*) as n from BAS_QUALITY_STANDARDS where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select QSTD_CODE, PRODUCT_GROUP, INSPECT_ITEM, SPEC_MIN, SPEC_MAX, UOM "
        f"from BAS_QUALITY_STANDARDS where {cond} order by QSTD_CODE limit %s offset %s",
        [*params, size, off])
    pg_names = code_names("제품군")
    grid = [[str(off + i), r["qstd_code"], pg_names.get(r["product_group"], r["product_group"]),
             r["inspect_item"], val(r["spec_min"], "D-104"), val(r["spec_max"], "D-104"),
             val(r["uom"], "D-104")]
            for i, r in enumerate(rows, 1)]

    yn = [{"value": "Y", "label": "Y"}, {"value": "N", "label": "N"}]
    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("code", "text"), ("pg", "text", code_options("제품군")),
            ("it", "text", code_options("검사구분")), ("item", "text"),
            ("spec", "text"), ("use", "text", yn)]),
        rows=grid, total=total, pager=pager, grid_title="품질기준",
        empty_notice=http.not_collected("D-104") +
        " — 현행 검사 기준서는 문서로만 존재한다. 초기 기준 데이터는 도입기업이 제공한다(SF-TD3-030 체크).",
        cards=[{"label": "등록 기준", "value": f"{total} 건"},
               {"label": "제품군 코드", "value": f"{len(pg_names)} 종"},
               {"label": "검사구분 코드", "value": f"{len(code_names('검사구분'))} 종"}],
        notices=[{"kind": "undetermined",
                  "text": "기준값(하한·상한·단위)은 정본에 수치가 없다 — 화면 입력 (D-104)"}],
        form={
            "title": "품질기준 등록", "action": "/bas/030", "submit": "저장",
            "note": "적용 규격(ASME·KS)과 기준값은 도입기업 제공 문서로 입력한다. "
                    "제품군·검사구분은 공통코드에 있는 값만 저장된다(D-32 — 어기면 422).",
            "fields": [
                {"label": "품질기준 코드", "name": "qstd_code", "required": True,
                 "placeholder": "QS-{제품군3}-{검사구분}-NNN"},
                {"label": "제품군", "name": "product_group", "required": True,
                 "options": code_options("제품군")},
                {"label": "검사구분", "name": "inspect_type", "required": True,
                 "options": code_options("검사구분")},
                {"label": "검사항목", "name": "inspect_item", "required": True},
                {"label": "적용 규격", "name": "standard_spec"},
                {"label": "기준값 하한", "name": "spec_min", "type": "number", "step": "any"},
                {"label": "기준값 상한", "name": "spec_max", "type": "number", "step": "any"},
                {"label": "단위", "name": "uom"},
                {"label": "적용 시작일", "name": "apply_from", "type": "date", "required": True},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·엑셀은 미구현이다 — 조용히 성공한 척하지 않는다(G-30).",
    )


@router.post("/bas/030")
async def quality_standards_save(request: Request):
    sid = "MES-TD3-030"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("qstd_code", "product_group", "inspect_type", "inspect_item", "apply_from"))
    # D-32 — DB 가 막지 않는 코드성 FK 는 저장 전에 막는다
    codes.require_code("BAS_QUALITY_STANDARDS", "PRODUCT_GROUP", v["product_group"])
    codes.require_code("BAS_QUALITY_STANDARDS", "INSPECT_TYPE", v["inspect_type"])

    lo, hi = opt_num(f, "spec_min"), opt_num(f, "spec_max")
    if lo is not None and hi is not None and lo > hi:
        raise http.fail("validation", f"상·하한 역전: {lo} > {hi}")
    if conn.q1("select 1 as x from BAS_QUALITY_STANDARDS where QSTD_CODE = %s", (v["qstd_code"],)):
        raise http.fail("validation", f"품질기준 코드 중복: {v['qstd_code']}")

    conn.x(
        "insert into BAS_QUALITY_STANDARDS "
        "(QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, INSPECT_ITEM, STANDARD_SPEC, SPEC_MIN, SPEC_MAX, "
        " UOM, JUDGE_RULE, USE_YN, APPLY_FROM, CREATED_BY, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'Y',%s,%s, now())",
        (v["qstd_code"], v["product_group"], v["inspect_type"], v["inspect_item"],
         (f.get("standard_spec") or "").strip() or None, lo, hi,
         (f.get("uom") or "").strip() or None, (f.get("judge_rule") or "").strip() or None,
         v["apply_from"], _user_id(request)))
    return redirect("/bas/030")


# ═════════════════════════════════════════════════════════════════════════
# 031 작업표준관리
# ═════════════════════════════════════════════════════════════════════════
@router.get("/bas/031")
async def work_standards(request: Request):
    sid = "MES-TD3-031"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("code"):
        where.append("WSTD_CODE ilike %s"); params.append(f"%{q['code']}%")
    if q.get("proc"):
        where.append("PROCESS_CODE = %s"); params.append(q["proc"])
    if q.get("name"):
        where.append("WSTD_NAME ilike %s"); params.append(f"%{q['name']}%")
    if q.get("ver"):
        where.append("STD_VERSION ilike %s"); params.append(f"%{q['ver']}%")
    if q.get("use"):
        where.append("USE_YN = %s"); params.append(q["use"])
    cond = " and ".join(where)

    total = int(conn.q1(f"select count(*) as n from BAS_WORK_STANDARDS where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select WSTD_CODE, PROCESS_CODE, WSTD_NAME, STD_MANHOUR, QUALIFICATION, STD_VERSION, DOC_PATH "
        f"from BAS_WORK_STANDARDS where {cond} order by PROCESS_CODE, WSTD_CODE limit %s offset %s",
        [*params, size, off])
    proc = code_names("공정")
    grid = [[str(off + i), r["wstd_code"], proc.get(r["process_code"], r["process_code"]),
             r["wstd_name"], val(r["std_manhour"], "D-105"),
             val(r["qualification"], "D-105"), r["std_version"]]
            for i, r in enumerate(rows, 1)]

    embedded = int(conn.q1("select count(*) as n from BAS_WORK_STANDARDS "
                           "where DOC_PATH is not null and DOC_PATH <> ''")["n"])
    yn = [{"value": "Y", "label": "Y"}, {"value": "N", "label": "N"}]
    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("code", "text"), ("proc", "text", code_options("공정")),
            ("name", "text"), ("ver", "text"), ("use", "text", yn)]),
        rows=grid, total=total, pager=pager, grid_title="작업표준",
        empty_notice=http.not_collected("D-105") +
        " — 현행 작업표준은 작업자 경험으로 전파되고 있어 초기 표준 정의가 선행되어야 한다(SF-TD3-031 체크).",
        cards=[{"label": "작업표준", "value": f"{total} 건"},
               {"label": "공정", "value": f"{len(proc)} 단계"},
               {"label": "첨부문서", "value": f"{embedded} 건"}],
        notices=[{"kind": "undetermined",
                  "text": "표준 공수·자격 요건은 정본에 수치가 없다 — 화면 입력 (D-105)"},
                 {"kind": "bad",
                  "text": "임베딩 등록은 개발3 의 문서 임베딩(TD4-049) 이 맡는다 — 여기서는 미구현 (D-08)"}],
        form={
            "title": "작업표준 등록", "action": "/bas/031", "submit": "저장",
            "note": "공정 코드는 공통코드 그룹 '공정' 의 10단계만 저장된다(D-32 — 어기면 422). "
                    "외주 2공정(소재가공·버핑)은 발주·반출·반입 상태 관리이지 설비 수집 대상이 아니다.",
            "fields": [
                {"label": "작업표준 코드", "name": "wstd_code", "required": True},
                {"label": "공정", "name": "process_code", "required": True,
                 "options": code_options("공정")},
                {"label": "작업표준명", "name": "wstd_name", "required": True},
                {"label": "표준 공수(시간)", "name": "std_manhour", "type": "number", "step": "any"},
                {"label": "자격 요건", "name": "qualification"},
                {"label": "첨부문서 경로", "name": "doc_path"},
                {"label": "버전", "name": "std_version", "required": True},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·임베딩 등록·엑셀은 미구현이다(G-30).",
    )


@router.post("/bas/031")
async def work_standards_save(request: Request):
    sid = "MES-TD3-031"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("wstd_code", "process_code", "wstd_name", "std_version"))
    codes.require_code("BAS_WORK_STANDARDS", "PROCESS_CODE", v["process_code"])
    if conn.q1("select 1 as x from BAS_WORK_STANDARDS where WSTD_CODE = %s", (v["wstd_code"],)):
        raise http.fail("validation", f"작업표준 코드 중복: {v['wstd_code']}")
    conn.x(
        "insert into BAS_WORK_STANDARDS "
        "(WSTD_CODE, PROCESS_CODE, WSTD_NAME, WORK_PROCEDURE, STD_MANHOUR, QUALIFICATION, "
        " DOC_PATH, STD_VERSION, USE_YN, CREATED_BY, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,'Y',%s, now())",
        (v["wstd_code"], v["process_code"], v["wstd_name"],
         (f.get("work_procedure") or "").strip() or None, opt_num(f, "std_manhour"),
         (f.get("qualification") or "").strip() or None,
         (f.get("doc_path") or "").strip() or None, v["std_version"], _user_id(request)))
    return redirect("/bas/031")


# ═════════════════════════════════════════════════════════════════════════
# 032 코드관리 — 코드성 FK 29건(D-32)의 정본이 여기다
# ═════════════════════════════════════════════════════════════════════════
# 화면이 다루는 코드 그룹 = 코드성 컬럼이 가리키는 그룹 + 채번 그룹.
# **목록을 여기서 지어내지 않는다** — `util.codes.COLUMN_GROUP` 이 정본이다.
KNOWN_GROUPS: tuple[str, ...] = tuple(sorted(set(codes.COLUMN_GROUP.values()) | {"LOT채번"}))


@router.get("/bas/032")
async def common_codes(request: Request):
    sid = "MES-TD3-032"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("grp"):
        where.append("c.CODE_GROUP = %s"); params.append(q["grp"])
    if q.get("code"):
        where.append("c.CODE_VALUE ilike %s"); params.append(f"%{q['code']}%")
    if q.get("name"):
        where.append("c.CODE_NAME ilike %s"); params.append(f"%{q['name']}%")
    if q.get("parent"):
        where.append("p.CODE_VALUE ilike %s"); params.append(f"%{q['parent']}%")
    if q.get("use"):
        where.append("c.USE_YN = %s"); params.append(q["use"])
    cond = " and ".join(where)
    join = ("from BAS_COMMON_CODES c "
            "left join BAS_COMMON_CODES p on p.CODE_ID = c.PARENT_CODE_ID")

    total = int(conn.q1(f"select count(*) as n {join} where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select c.CODE_GROUP, c.CODE_VALUE, c.CODE_NAME, p.CODE_VALUE as parent_value, "
        f"c.SORT_ORDER, c.USE_YN {join} where {cond} "
        f"order by c.CODE_GROUP, c.SORT_ORDER, c.CODE_VALUE limit %s offset %s",
        [*params, size, off])
    grid = [[str(off + i), r["code_group"], r["code_value"], r["code_name"],
             r["parent_value"] or "-", val(r["sort_order"], "D-106"), r["use_yn"]]
            for i, r in enumerate(rows, 1)]

    # 그룹 현황 — 비어 있는 그룹은 **정본에 값이 없어 비운 것**이다(D-47). 채우지 않는다.
    counted = {r["code_group"]: int(r["n"]) for r in conn.q(
        "select CODE_GROUP, count(*) as n from BAS_COMMON_CODES group by CODE_GROUP")}
    group_rows = []
    for i, g in enumerate(sorted(set(KNOWN_GROUPS) | set(counted)), 1):
        n = counted.get(g, 0)
        group_rows.append([
            str(i), g, f"{n} 건",
            "화면 입력 마스터 — 정본에 값이 없어 비웠다 (D-47)" if n == 0 else "시드·화면 입력",
        ])

    yn = [{"value": "Y", "label": "Y"}, {"value": "N", "label": "N"}]
    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("grp", "text", [{"value": g, "label": g} for g in sorted(set(KNOWN_GROUPS) | set(counted))]),
            ("code", "text"), ("name", "text"), ("parent", "text"), ("use", "text", yn)]),
        rows=grid, total=total, pager=pager, grid_title="공통코드",
        empty_notice=http.not_collected("D-47") + " — 이 조건에 맞는 코드가 없다.",
        cards=[{"label": "공통코드", "value": f"{total} 건"},
               {"label": "코드 그룹", "value": f"{len(counted)} / {len(set(KNOWN_GROUPS) | set(counted))} 그룹"},
               {"label": "코드성 FK 컬럼", "value": f"{len(codes.code_columns())} 개"}],
        notices=[{"kind": "notice",
                  "text": f"코드성 참조 {len(codes.code_columns())}건은 DB 가 막지 않는다 — "
                          "저장 전 애플리케이션이 검증한다 (D-32)"}],
        panels=[{
            "title": "코드 그룹 현황",
            "columns": ["No", "코드 그룹", "등록 건수", "비고"],
            "rows": group_rows,
            "empty_notice": http.not_collected("D-47"),
            "note": "비어 있는 그룹은 정본에 값이 없어 비운 것이다(D-47). 화면에서 입력한다 — "
                    "코드가 없으면 그 코드를 쓰는 저장이 422 로 막힌다.",
        }],
        form={
            "title": "코드 등록", "action": "/bas/032", "submit": "저장",
            "note": "코드는 그룹 안에서 중복될 수 없다 — 중복이면 422(SF-TD3-032 체크). "
                    "재질·두께·길이(mm)·중량(kg)·고객사 코드 표준화는 사업계획서 2.7.3 기준을 따른다.",
            "fields": [
                {"label": "코드 그룹", "name": "code_group", "required": True,
                 "options": [{"value": g, "label": g} for g in sorted(set(KNOWN_GROUPS) | set(counted))]},
                {"label": "코드", "name": "code_value", "required": True},
                {"label": "코드명", "name": "code_name", "required": True},
                {"label": "상위 코드", "name": "parent_code", "placeholder": "같은 그룹의 코드"},
                {"label": "정렬 순서", "name": "sort_order", "type": "number"},
                {"label": "속성값1", "name": "attr1"},
                {"label": "속성값2", "name": "attr2"},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·엑셀은 미구현이다(G-30).",
    )


@router.post("/bas/032")
async def common_codes_save(request: Request):
    sid = "MES-TD3-032"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("code_group", "code_value", "code_name"))
    if conn.q1("select 1 as x from BAS_COMMON_CODES where CODE_GROUP = %s and CODE_VALUE = %s",
               (v["code_group"], v["code_value"])):
        raise http.fail("validation",
                        f"코드 중복: 그룹 '{v['code_group']}' 에 '{v['code_value']}' 가 이미 있다")
    parent_id = None
    parent = (f.get("parent_code") or "").strip()
    if parent:
        row = conn.q1("select CODE_ID from BAS_COMMON_CODES where CODE_GROUP = %s and CODE_VALUE = %s",
                      (v["code_group"], parent))
        if not row:
            raise http.fail("validation", f"상위 코드 '{parent}' 가 그룹 '{v['code_group']}' 에 없다")
        parent_id = row["code_id"]
    sort = f.get("sort_order")
    conn.x(
        "insert into BAS_COMMON_CODES "
        "(CODE_GROUP, CODE_VALUE, CODE_NAME, PARENT_CODE_ID, SORT_ORDER, ATTR1, ATTR2, "
        " USE_YN, CREATED_BY, CREATED_DT) values (%s,%s,%s,%s,%s,%s,%s,'Y',%s, now())",
        (v["code_group"], v["code_value"], v["code_name"], parent_id,
         int(sort) if (sort or "").strip() else None,
         (f.get("attr1") or "").strip() or None, (f.get("attr2") or "").strip() or None,
         _user_id(request)))
    return redirect(f"/bas/032?grp={v['code_group']}")
