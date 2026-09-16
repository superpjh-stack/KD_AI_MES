"""AI 대시보드 001~004 (개발2) — 그리고 개발2 4개 모듈의 **공용 헬퍼**.

`prc.py` · `shp.py` · `kpi.py` 가 여기서 `guard` · `ctx` · `cell` · `lot_cell` 을 가져다 쓴다.
공용 헬퍼를 새 파일로 빼지 않는 이유는 소유 파일이 `routers/{dsh,prc,shp,kpi}.py` 로 고정돼
있기 때문이다(screen-map §2). 한 파일은 한 사람만 만진다.

**규칙**
  · 화면 문장은 `design.screen(sid)` 정본에서 온다. 없으면 `util.http.undetermined` 다(§0.2).
  · 건수 카드의 `0 건` 은 정답이다. 빈 **그리드**에만 '미수집' 을 쓴다(G-11 · §10-14).
  · LOT·프로젝트번호 셀은 **클릭하면 `/prc/024` 공정이력조회**로 간다(G-08).
  · 수집 범위 밖은 `util.http.not_collected("D-06")` — 전 공정 실시간 수집인 척하지 않는다.
  · DB 장애는 `db/conn.py` 가 503 을 낸다. `try/except` 로 덮지 않는다(G-30).
"""
from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, Request

from .. import design, nav, rbac
from ..settings import settings
from ..templating import render
from ..util import clock, http
from ..util.audit import RESULT_ERR, RESULT_OK, audit

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "db"))

from fastapi import APIRouter  # noqa: E402

router = APIRouter()
SCREENS = ("MES-TD3-001", "MES-TD3-002", "MES-TD3-003", "MES-TD3-004")

HISTORY_PATH = "/prc/024"          # 공정이력조회 — 디지털 스레드 클릭 목적지 (G-08)
COLLECT_DECISION = "D-06"          # 수집 지점 2개소 한정
STD_COND_DECISION = "D-203"        # 표준 작업조건 초기값 미제공
CLAIM_DECISION = "D-204"           # 클레임 이력 런타임 등록


# ── 공용 헬퍼 ───────────────────────────────────────────────────────────
def user_id(request: Request) -> int | None:
    sess = getattr(request.state, "session", None)
    return getattr(sess, "user_id", None)


def _audit(request: Request, sid: str, action: str, *, log_type: str = "접속",
           result: str = RESULT_OK, error: str | None = None) -> None:
    """감사 기록 **한 곳**. 개발2 4모듈의 `audit()` 호출은 여기 하나뿐이다(D-97 · G-29)."""
    audit(request, sid, action, log_type=log_type, result=result, error=error,
          user_id=user_id(request))


def guard(request: Request, sid: str, *, write: bool = False, approve: bool = False):
    """권한 확인 + 정본 로드 + **감사 기록**. 권한 없으면 **403**, 정본이 없으면 지어내지 않는다.

    **감사는 여기 한 곳에서 남긴다**(D-97 · G-29). 개발2 16화면(`dsh`·`prc`·`shp`·`kpi`)이
    전부 이 가드를 지나므로 화면마다 `audit()` 을 흩뿌리지 않는다 — 한 곳이 빠지면
    16화면이 통째로 빠진다는 것이 QA3 가 잡은 결함이다. 개발1 `bas.guard` 와 같은 방식이다.
    거부(403)도 **`오류`** 로 남긴다 — 감사에 안 남는 거부는 없는 것과 같다.

    **쓰기(write/approve)는 여기서 `변경` 을 남기지 않는다.** 전에는 진입 시점에 `정상` 으로
    적어서 뒤따르는 422 가 성공 기록을 남겼다(개발2 감사 #17). 쓰기 핸들러는 `writing()` 으로
    본문을 감싸 **커밋 뒤에 `변경`, 실패 분기에 `오류`** 를 남긴다.
    """
    screen = nav.by_id()[sid]
    role = getattr(request.state, "role_code", "") or ""

    def denied(reason: str):
        _audit(request, sid, "조회거부" if not (write or approve) else "쓰기거부",
               log_type="오류", result=RESULT_ERR, error=reason)
        return http.fail("forbidden", reason)

    if not rbac.can_read(role, screen.area):
        raise denied(f"{screen.area} 조회 권한 없음")
    if write and not rbac.can_write(role, screen.area):
        raise denied(f"{screen.area} 등록·수정 권한 없음")
    if approve and not rbac.can_approve(role, screen.area):
        raise denied(f"{screen.area} 승인 권한 없음 (G-24)")
    td3 = design.screen(sid)
    if td3 is None:
        raise http.fail("internal", f"{sid} 정본(SF-TD3)이 없다 — {http.undetermined('D-nn')}")
    if not (write or approve):
        _audit(request, sid, "조회")
    return screen, td3


BOARD_AREA = "AI 대시보드"      # 현황판이 보여 주는 것 — 생산·품질·출하·KPI 요약


def board_guard(request: Request) -> None:
    """현황판 `/board` 의 조회 권한 확인 + 감사 (G-28 · G-29).

    현황판은 `nav` 화면이 아니라 **공통 화면**(TD3 common_screens)이라 `guard()` 를 쓸 수
    없다. 그렇다고 아무나 여는 화면도 아니다 — 65" 두 대에 수주·납기·KPI 가 그대로 뜬다.
    `main.py` 의 `_SKIP_PREFIXES` 에 `/board` 가 있어 공통 가드를 지나지 않으므로
    **여기서 막는다.** 감사 기록도 여기서 남긴다(개발2 감사 호출은 이 파일 한 곳이다).
    """
    role = getattr(request.state, "role_code", "") or ""
    if not rbac.can_read(role, BOARD_AREA):
        _audit(request, None, "현황판 조회거부", log_type="오류", result=RESULT_ERR,
               error=f"{BOARD_AREA} 조회 권한 없음")
        raise http.fail("forbidden", f"{BOARD_AREA} 조회 권한 없음")
    _audit(request, None, "현황판 조회")


@contextmanager
def writing(request: Request, sid: str, action: str):
    """쓰기 핸들러 본문을 감싼다 — **성공하면 `변경`, 실패하면 `오류`** 를 남긴다.

    `guard(write=True)` 는 이 블록 **밖**에서 먼저 부른다(403 은 가드가 이미 남긴다).
    """
    try:
        yield
    except HTTPException as e:
        d = e.detail if isinstance(e.detail, dict) else {}
        _audit(request, sid, action, log_type="오류", result=RESULT_ERR,
               error=f"{e.status_code} {d.get('detail') or d.get('message') or ''}".strip())
        raise
    _audit(request, sid, action, log_type="변경")


# ── 입력값 검증 — 잘못된 조회값은 500 이 아니라 422 다 (§2.5) ─────────────
_DAY = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def opt_date(request: Request, key: str) -> str:
    """`YYYY-MM-DD` 또는 빈 값. 형식이 틀리면 **422**."""
    v = (request.query_params.get(key) or "").strip()
    if not v:
        return ""
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise http.fail("validation", f"{key}: 날짜 형식은 YYYY-MM-DD 다: {v!r}") from None


def day_prefix(request: Request, key: str) -> str:
    """일자 조회 — `YYYY-MM-DD` 는 그 날, `YYYY-MM` 은 그 달. 그 외는 **422**.
    SQL 은 `to_char(col,'YYYY-MM-DD') like %(key)s || '%%'` 로 쓴다."""
    v = (request.query_params.get(key) or "").strip()
    if not v:
        return ""
    if not _DAY.match(v):
        raise http.fail("validation", f"{key}: YYYY-MM-DD 또는 YYYY-MM 이어야 한다: {v!r}")
    if len(v) == 10:
        opt_date(request, key)
    return v


def date_range(request: Request, from_key: str = "from", to_key: str = "to") -> dict[str, str]:
    """기간 — 시작일 이상 · 종료일 **포함**(`< 종료일 + 1일`). 둘 다 선택이다."""
    f, t = opt_date(request, from_key), opt_date(request, to_key)
    if f and t and t < f:
        raise http.fail("validation", f"기간 종료일({t})이 시작일({f})보다 앞선다")
    t_excl = (date.fromisoformat(t) + timedelta(days=1)).isoformat() if t else ""
    return {from_key: f, to_key: t, f"{to_key}_excl": t_excl}


def parse_datetime(value: str, name: str) -> datetime:
    """폼의 일시 문자열 → datetime. `YYYY-MM-DD HH:MM`·ISO 만 받고 아니면 **422**."""
    raw = (value or "").strip()
    if not raw:
        raise http.fail("validation", f"필수값 누락: {name}")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 YYYY-MM-DD HH:MM 형식이다: {raw!r}") from None


def parse_opt_date(value: str, name: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise http.fail("validation", f"{name} 은 YYYY-MM-DD 형식이다: {raw!r}") from None


def range_wired(label_from: str, f: dict[str, str], from_key: str = "from", to_key: str = "to",
                hint: str = "YYYY-MM-DD") -> dict[str, Any]:
    """조회조건 '기간' 한 칸에 시작·종료 두 입력을 넣는다(정본 항목 수는 그대로)."""
    return {"name": from_key, "value": f[from_key], "hint": f"{hint} 시작",
            "to": {"name": to_key, "value": f[to_key], "hint": f"{hint} 종료(포함)"}}


# ── 페이징 — 200 건에서 잘라 놓고 말하지 않으면 사용자는 그것이 전부인 줄 안다 ──
def page_of(request: Request, size: int) -> tuple[int, int]:
    raw = (request.query_params.get("page") or "1").strip()
    try:
        page = max(1, int(raw))
    except ValueError:
        raise http.fail("validation", f"page 는 정수여야 한다: {raw!r}") from None
    return page, (page - 1) * size


def pager(request: Request, total: int, page: int, size: int) -> dict[str, Any]:
    pages = max(1, (int(total) + size - 1) // size)
    keep = [(k, v) for k, v in request.query_params.multi_items() if k != "page"]
    base = urlencode(keep)
    sep = "&" if base else ""
    return {"total": int(total), "page": page, "size": size, "pages": pages,
            "prev": f"?{base}{sep}page={page - 1}" if page > 1 else None,
            "next": f"?{base}{sep}page={page + 1}" if page < pages else None}


def count_total(core_sql: str, params: Any) -> int:
    """`from … where …` 조각으로 총 건수를 센다(그리드 note 에 '총 N 건' 으로 적는다)."""
    import conn
    row = conn.q1(f"select count(*) as n {core_sql}", params)
    return int(row["n"]) if row else 0


def safe_next(request: Request, value: str | None, default: str) -> str:
    """저장 뒤 돌아갈 곳 — **같은 화면 경로**로 시작하는 상대 경로만 받는다(열린 리다이렉트 금지)."""
    v = (value or "").strip()
    if v.startswith(default) and not v.startswith("//") and "\\" not in v:
        return v
    return default


def process_options(names: dict[str, str], exclude: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """'공정' 조회조건은 코드가 아니라 **이름으로 고른다**(select)."""
    return [(c, f"{n} ({c})") for c, n in names.items() if c not in exclude]


# 출하 '지연' 은 저장된 상태값이 아니라 **파생**이다 — 확정됐는데 납기를 넘겼거나(OTD_YN='N'),
# 미확정인데 납기일이 기준일 이전이면 지연이다. `SHIP_STATUS='지연'` 은 아무 데서도 쓰지 않는다.
LATE_SQL = "(s.OTD_YN = 'N' or (s.SHIP_DT is null and s.DUE_DT is not null and s.DUE_DT < %(today)s))"


def mock(td3: dict[str, Any]) -> dict[str, Any]:
    return td3.get("mockup") or {}


def anchor() -> datetime:
    """시간 앵커. `date.today()` 를 쓰지 않는다(§10-3)."""
    return clock.anchor()


def cell(text: Any, *, href: str | None = None, num: bool = False) -> dict[str, Any]:
    return {"t": "" if text is None else str(text), "href": href, "num": num}


def lot_cell(lot_no: str | None) -> dict[str, Any]:
    """제품 LOT 셀 — 클릭하면 024 공정이력조회로 간다(G-08)."""
    if not lot_no:
        return cell("—")
    return cell(lot_no, href=f"{HISTORY_PATH}?lot={lot_no}")


def project_cell(project_no: str | None) -> dict[str, Any]:
    """프로젝트(수주)번호 셀 — ETO 최상위 조회 축이고 역시 024 로 간다(G-08)."""
    if not project_no:
        return cell("—")
    return cell(project_no, href=f"{HISTORY_PATH}?project={project_no}")


def num(value: Any, digits: int = 0, unit: str = "") -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}{(' ' + unit) if unit else ''}"


def dt(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return value.strftime(fmt) if isinstance(value, datetime) else ("—" if not value else str(value))


def count_card(label: str, n: int, unit: str = "건", sub: str = "",
               href: str | None = None) -> dict[str, Any]:
    """**건수 카드는 0 이어도 그대로 `0 건`** 이다 — '미수집' 을 붙이면 거짓 표시다(§10-14).
    `href` 가 있으면 카드를 누르면 그 화면으로 간다(TD4-001 fn4 드릴다운)."""
    return {"label": label, "value": f"{n:,} {unit}", "sub": sub, "href": href}


def ratio_card(label: str, pct: float | None, sub: str = "", decision: str = COLLECT_DECISION,
               href: str | None = None):
    """비율 카드는 분모가 없으면 값이 **없는 것**이다 — '미수집' 이 맞다."""
    if pct is None:
        return {"label": label, "value": http.not_collected(decision), "sub": sub, "off": True,
                "href": href}
    return {"label": label, "value": f"{pct:,.1f} %", "sub": sub, "href": href}


# 진행 중 프로젝트가 정말 0건일 때의 문구 — 조회는 됐고 결과가 0 이다. '미수집' 이 아니다(§10-14).
ZERO_ACTIVE_NOTE = "진행 중 프로젝트 0 건 — 등록된 프로젝트가 전부 완료 상태다"


def ctx(request: Request, screen: nav.Screen, td3: dict[str, Any], **extra) -> dict[str, Any]:
    return dict(current=screen, screen=screen, td3=td3, mock=mock(td3),
                history_path=HISTORY_PATH, **extra)


def process_names() -> dict[str, str]:
    """공정 코드 → 이름. 화면은 코드가 아니라 이름을 보여 준다."""
    import conn
    rows = conn.q(
        "select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
        "where CODE_GROUP = '공정' order by SORT_ORDER"
    )
    return {r["code_value"]: r["code_name"] for r in rows}


def collection_status() -> dict[str, Any]:
    """수집 중단 판정 **정본** — `kyungdong.ingest.collector.status()` 한 벌뿐이다.

    **DEF-QA2-002 · §10-16.** 전에는 이 파일이 시간 앵커에서 마지막 수집시각을 빼서 따로
    판정했고, 같은 DB·같은 시각에 `collector.status()` 와 **반대 결론**을 냈다.
    판정도 임계값도 여기서 다시 읽지 않는다 — 화면은 정본 함수를 부르고
    `devices[].notice` 문구를 **그대로** 띄운다(개발3 공표 시그니처).

    기준선은 **실시각**이다(DEF-QA2-001). 수집이 살아 있는지를 묻는 물음이라, 시드·시뮬레이터의
    생성 기준일(§10-3)로 재면 운영 수집에서 경과가 **항상 음수**가 되어 임계를 넘을 수 없었다
    (QA2 실측 −108,426초).
    """
    from ...ingest import collector
    return collector.status()


def collection_badges() -> list[dict[str, str]]:
    """수집 범위·중단 상태 배지 (D-06 · G-12). 수집이 끊기면 숨기지 않고 드러낸다."""
    st = collection_status()
    out = [{"cls": "notice",
            "text": f"자동 수집 {st['points']}개소 (레이저커팅기 PLC · 현장POP) — {COLLECT_DECISION}"}]
    for d in st["devices"]:
        if not d["notice"]:
            continue
        # 값이 없는 것(미수집)과 끊긴 것(수집 중단)은 다른 사실이다 — 배지 종류로 구분한다.
        out.append({"cls": "bad" if d["last_collect_dt"] else "undetermined",
                    "text": f"{d['device_name']} — {d['notice']}"})
    out.append({"cls": "notice",
                "text": f"중단 판정 임계 {st['stale_sec']}초 {st['stale_badge']} · "
                        f"판정 기준시각 {dt(st['checked_at'], '%Y-%m-%d %H:%M:%S')} (실시각)"})
    return out


def live_poll_sec() -> int:
    """실시간 패널 갱신 주기 = PLC 수집 주기(.env, 가설 D-06). 화면은 2초보다 빠르게 두드리지 않는다."""
    return max(2, settings().h("PLC_POLL_SEC").as_int())


def equip_utilisation(since: datetime) -> tuple[float | None, int]:
    """가동률(%) = 가동 신호 ÷ 전체 신호 × 100. 신호가 없으면 `None` 이다."""
    import conn
    from .. import kpi as kpimod
    row = conn.q1(
        "select count(*) as n, count(*) filter (where RUN_STATUS = '가동') as run_n "
        "from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s", (since,),
    ) or {"n": 0, "run_n": 0}
    return kpimod.ratio_pct(row["run_n"], row["n"]), int(row["n"] or 0)


# ── 001 생산현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/001")
async def production_status(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-001")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    names = process_names()

    today = conn.q1(
        "select coalesce(sum(GOOD_QTY),0) as good, count(*) as n from PRC_PERFORMANCES "
        "where START_DT >= %s and START_DT < %s", (day0, day0 + timedelta(days=1)),
    ) or {"good": 0, "n": 0}
    running = conn.q1(
        "select count(*) as n from PRC_WORK_ORDERS where ORDER_STATUS = '진행'") or {"n": 0}
    late = conn.q1(
        "select count(*) as n from EST_PROJECTS "
        "where DUE_DT is not null and DUE_DT < %s and PROJECT_STATUS <> '완료'", (a.date(),),
    ) or {"n": 0}
    util, signal_n = equip_utilisation(day0)

    by_process = conn.q(
        "select PROCESS_CODE, coalesce(sum(GOOD_QTY),0) as good from PRC_PERFORMANCES "
        "group by PROCESS_CODE order by PROCESS_CODE"
    )
    by_project = conn.q(
        "select pj.PROJECT_NO, pj.PROJECT_NAME, "
        "count(h.PRC_HIST_ID) as total, count(h.OUT_DT) as done "
        "from EST_PROJECTS pj "
        "join SHP_LOT_TRACES lt on lt.PROJECT_ID = pj.PROJECT_ID "
        "join PRC_PROCESS_HISTORIES h on h.LOT_TRACE_ID = lt.LOT_TRACE_ID "
        "where pj.PROJECT_STATUS <> '완료' "
        "group by pj.PROJECT_NO, pj.PROJECT_NAME order by pj.PROJECT_NO limit 8"
    )
    # 완료 프로젝트는 '진행률' 목록의 대상이 아니다. 0건이면 **미수집이 아니라 진행 중 0건**이다(§10-14).

    return render(request, "dsh/001.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("금일 실적수량", int(float(today["good"] or 0)), "ea",
                       f"실적 {int(today['n'] or 0)}건 · 기준 {dt(a, '%Y-%m-%d')}",
                       href=f"/prc/021?date={a.strftime('%Y-%m-%d')}"),
            count_card("진행 작업지시", int(running["n"] or 0), href="/prc/021"),
            ratio_card("설비 가동률", util, f"수집 신호 {signal_n:,}건 · 레이저커팅기 1대 (D-06)",
                       href="/dsh/003"),
            count_card("지연 프로젝트", int(late["n"] or 0), "건", "납기일 경과·미완료",
                       href="/dsh/004"),
        ],
        chart_title=mock(td3).get("chart_title", "").replace("(예시)", ""),
        chart=[{"label": names.get(r["process_code"], r["process_code"]),
                "value": float(r["good"] or 0), "text": num(r["good"], 0)} for r in by_process],
        list_title=mock(td3).get("list_title", "").replace("(예시)", ""),
        progress=[{"label": f"{r['project_no']} {r['project_name']}",
                   "href": f"{HISTORY_PATH}?project={r['project_no']}",
                   "percent": int(round(int(r["done"]) / int(r["total"]) * 100)) if r["total"] else 0,
                   "text": f"{r['done']}/{r['total']} 공정"} for r in by_project],
        badges=collection_badges(),
        empty_note=http.not_collected(COLLECT_DECISION),
        list_empty_note=ZERO_ACTIVE_NOTE,
    ))


# ── 002 품질현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/002")
async def quality_status(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-002")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    names = process_names()

    today = conn.q1(
        "select count(*) as n from SHP_INSPECTIONS where INSPECT_DT >= %s and INSPECT_DT < %s",
        (day0, day0 + timedelta(days=1)),
    ) or {"n": 0}
    q = kpimod.quality()
    bad_lots = conn.q1(
        "select count(distinct LOT_TRACE_ID) as n from SHP_INSPECTIONS where JUDGE_RESULT <> '합격'"
    ) or {"n": 0}
    bad_lot_rows = conn.q(
        "select lt.PRODUCT_LOT_NO, count(*) as n from SHP_INSPECTIONS i "
        "join SHP_LOT_TRACES lt on lt.LOT_TRACE_ID = i.LOT_TRACE_ID "
        "where i.JUDGE_RESULT <> '합격' group by lt.PRODUCT_LOT_NO order by lt.PRODUCT_LOT_NO limit 8"
    )
    trend = conn.q(
        "select to_char(START_DT, 'YYYY-MM') as period, coalesce(sum(DEFECT_QTY),0) as defect "
        "from PRC_PERFORMANCES group by 1 order by 1 desc limit 6"
    )
    by_process = conn.q(
        "select PROCESS_CODE, coalesce(sum(DEFECT_QTY),0) as defect from PRC_PERFORMANCES "
        "where coalesce(DEFECT_QTY,0) > 0 group by PROCESS_CODE order by 2 desc limit 6"
    )
    total_defect = sum(float(r["defect"] or 0) for r in by_process) or 1.0

    return render(request, "dsh/002.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("금일 검사 건수", int(today["n"] or 0)),
            # 합격률 단서는 `kpi.QualityKpi.pass_rate_caveat` **한 곳**에서 온다 — 002·044·현황판 공용.
            ratio_card("합격률", q.pass_rate,
                       f"검사 {q.inspect_cnt:,}건 중 합격 {q.pass_cnt:,}건"
                       + (f" · {q.pass_rate_caveat}" if q.pass_rate_caveat else ""),
                       href="/shp/018"),
            count_card("불량 수량", int(q.defect_qty), "ea", f"양품 {q.good_qty:,.0f} ea",
                       href="/prc/025"),
            count_card("이상 LOT", int(bad_lots["n"] or 0), "건", "불합격 판정이 있는 제품 LOT",
                       href="/shp/018?judge=불합격"),
        ],
        # 이상 LOT 목록 — 누르면 그 LOT 의 024 공정이력조회로 간다(TD4-002 fn3).
        bad_lot_list=[{"lot_no": r["product_lot_no"], "n": int(r["n"]),
                       "href": f"{HISTORY_PATH}?lot={r['product_lot_no']}"} for r in bad_lot_rows],
        chart_title="기간별 불량 발생 추이",
        chart=[{"label": r["period"], "value": float(r["defect"] or 0),
                "text": num(r["defect"], 0)} for r in reversed(trend)],
        list_title="공정별 불량 비중",
        progress=[{"label": names.get(r["process_code"], r["process_code"]),
                   "percent": int(round(float(r["defect"] or 0) / total_defect * 100)),
                   "text": f"{num(r['defect'], 0)} ea"} for r in by_process],
        badges=[{"cls": "notice",
                 "text": "판정 기준은 기준정보관리 품질기준(BAS_QUALITY_STANDARDS)을 따른다"}],
        empty_note=http.not_collected(COLLECT_DECISION),
    ))


# ── 003 설비상태 모니터링 ───────────────────────────────────────────────
@router.get("/dsh/003")
async def equipment_status(request: Request):
    import conn
    screen, td3 = guard(request, "MES-TD3-003")
    a = anchor()
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)

    laser = conn.q1(
        "select RUN_STATUS, COLLECT_DT from PRC_EQUIP_SIGNALS where EQUIP_CODE = 'EQ10' "
        "order by COLLECT_DT desc limit 1"
    )
    runtime = conn.q1(
        "select coalesce(sum(RUN_MINUTE),0) as m from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s",
        (day0,),
    ) or {"m": 0}
    alarms = conn.q1(
        "select count(*) as n from PRC_EQUIP_SIGNALS "
        "where ALARM_CODE is not null and COLLECT_DT >= %s", (day0,),
    ) or {"n": 0}
    hourly = conn.q(
        "select to_char(COLLECT_DT, 'HH24') as hh, coalesce(sum(RUN_MINUTE),0) as m "
        "from PRC_EQUIP_SIGNALS where COLLECT_DT >= %s group by 1 order by 1", (day0,),
    )
    # 수집 지점은 **2개소뿐**이다(D-06) — 설비 코드 그룹이 그 2개소의 정본이다.
    points = conn.q(
        "select c.CODE_VALUE, c.CODE_NAME, c.ATTR1, "
        "(select count(*) from PRC_EQUIP_SIGNALS s where s.EQUIP_CODE = c.CODE_VALUE) as n, "
        "(select max(s.COLLECT_DT) from PRC_EQUIP_SIGNALS s where s.EQUIP_CODE = c.CODE_VALUE) as last_dt "
        "from BAS_COMMON_CODES c where c.CODE_GROUP = '설비' order by c.SORT_ORDER"
    )
    devices = conn.q1(
        "select count(*) as n from IF_DEVICE_REGISTRY where USE_YN = 'Y'") or {"n": 0}
    signal_total = sum(int(p["n"] or 0) for p in points) or 1

    has_signal = laser is not None
    from ...ingest import mes
    return render(request, "dsh/003.html", **ctx(
        request, screen, td3,
        # 실시간 패널 (D-223) — API `GET /api/ingest/live` 와 **같은 함수**로 처음 그린다.
        live=mes.live_snapshot(), live_poll_sec=live_poll_sec(),
        cards=[
            {"label": "레이저커팅기 상태",
             "value": laser["run_status"] if has_signal else http.not_collected(COLLECT_DECISION),
             "sub": dt(laser["collect_dt"]) if has_signal else "PLC 수집 신호 없음",
             "off": not has_signal},
            {"label": "금일 가동시간",
             "value": num(runtime["m"], 0, "분") if has_signal else http.not_collected(COLLECT_DECISION),
             "sub": f"기준 {dt(a, '%Y-%m-%d')}", "off": not has_signal},
            count_card("알람 발생", int(alarms["n"] or 0)),
            count_card("수집 지점", 2, "개소", "레이저커팅기 PLC 1 · 현장POP 1 (D-06)"),
        ],
        chart_title="시간대별 가동시간(분)",
        chart=[{"label": f"{r['hh']}시", "value": float(r["m"] or 0),
                "text": num(r["m"], 0)} for r in hourly],
        list_title="수집 지점 상태",
        progress=[{"label": f"{p['code_name']} ({p['code_value']})",
                   "percent": int(round(int(p["n"] or 0) / signal_total * 100)),
                   "text": (f"신호 {int(p['n'] or 0):,}건 · 최종 {dt(p['last_dt'])}"
                            if p["n"] else http.not_collected(COLLECT_DECISION))}
                  for p in points],
        notes=[{"title": "수집 장비",
                "body": f"등록 수집장비 {int(devices['n'] or 0)} 대 (IF_DEVICE_REGISTRY). "
                        f"수집 주기 {settings().h('PLC_POLL_SEC').value}초 "
                        f"{settings().h('PLC_POLL_SEC').badge}"}],
        badges=collection_badges() + [
            {"cls": "notice",
             "text": "설비 예지보전 AI는 본 사업 범위 밖이다 (사업계획서 2.5 현 사업 미적용 · D-01)"}],
        empty_note=http.not_collected(COLLECT_DECISION),
    ))


# ── 004 출하현황 분석 ───────────────────────────────────────────────────
@router.get("/dsh/004")
async def shipment_status(request: Request):
    import conn
    from .. import kpi as kpimod
    screen, td3 = guard(request, "MES-TD3-004")
    a = anchor()

    agg = conn.q1(
        "select count(*) filter (where s.SHIP_DT is null) as planned, "
        "count(*) filter (where s.SHIP_DT is not null) as done, "
        f"count(*) filter (where {LATE_SQL}) as late, "
        "count(*) filter (where s.OTD_YN = 'Y') as otd, "
        "count(*) filter (where s.OTD_YN is not null) as otd_base from SHP_SHIPMENTS s",
        {"today": a.date()},
    ) or {}
    weekly = conn.q(
        "select to_char(SHIP_DT, 'IYYY-IW') as wk, count(*) as n from SHP_SHIPMENTS "
        "where SHIP_DT is not null group by 1 order by 1 desc limit 6"
    )
    due = conn.q(
        "select pj.PROJECT_NO, pj.PROJECT_NAME, pj.DUE_DT, pj.PROJECT_STATUS, "
        "(select count(*) from SHP_LOT_TRACES lt where lt.PROJECT_ID = pj.PROJECT_ID "
        " and lt.TRACE_STATUS = '출하') as shipped "
        "from EST_PROJECTS pj where pj.DUE_DT is not null and pj.PROJECT_STATUS <> '완료' "
        "order by pj.DUE_DT limit 8"
    )

    def days_left(d) -> int:
        return (d - a.date()).days if d else 0

    return render(request, "dsh/004.html", **ctx(
        request, screen, td3,
        cards=[
            count_card("출하 예정", int(agg.get("planned") or 0), href="/shp/016?status=승인대기"),
            count_card("출하 완료", int(agg.get("done") or 0), href="/shp/016?status=완료"),
            count_card("지연", int(agg.get("late") or 0), "건",
                       "파생값 — 납기 미준수 확정(OTD_YN=N) + 미확정·납기 경과", href="/shp/016?status=지연"),
            ratio_card("납기 준수율", kpimod.ratio_pct(agg.get("otd"), agg.get("otd_base")),
                       "출하 확정 건 기준 (OTD_YN)", href="/shp/016?otd=N"),
        ],
        chart_title="주간 출하 물량",
        chart=[{"label": r["wk"], "value": float(r["n"]), "text": num(r["n"], 0)}
               for r in reversed(weekly)],
        list_title="납기 임박 프로젝트",
        progress=[{"label": f"{r['project_no']} {r['project_name']}",
                   "href": f"{HISTORY_PATH}?project={r['project_no']}",
                   "percent": max(0, min(100, 100 - days_left(r["due_dt"]) * 2)),
                   "text": f"납기 {r['due_dt']} · D{days_left(r['due_dt']):+d} · {r['project_status']}"}
                  for r in due],
        list_empty_note=ZERO_ACTIVE_NOTE,
        badges=[{"cls": "notice",
                 "text": "납기는 수주 확정 시점의 납기일 기준이다. 출하 확정 시각이 "
                         "수주출하 리드타임(LEADTIME_O2D)의 종료 시각이다"}],
        empty_note=http.not_collected("D-07"),
    ))
