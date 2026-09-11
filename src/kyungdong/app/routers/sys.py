"""사용자/시스템관리 026~029 (개발1).

G-29 개인정보: `SYS_USERS.USER_NAME` · `PHONE_NO` · `EMAIL` 과 `IF_DEVICE_REGISTRY.IP_ADDRESS` 는
**화면에서 마스킹**한다(`util.mask`). 시드·화면에 실명을 넣지 않는다.
G-11 런타임 전용: `SYS_ACCESS_LOGS` 는 깨끗한 DB 에서 0건이 정상이고 그때 그리드는 `미수집` 을 렌더한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from .bas import (anchor_label, code_options, dt, guard, paginate, redirect,  # noqa: F401
                  require_fields, screen_page, search_spec, undetermined, val)
from .. import auth, rbac
from ..util import clock, csrf, http, mask
from ..util.audit import LOG_TYPES

import conn                                              # noqa: E402

router = APIRouter()
SCREENS = ("MES-TD3-026", "MES-TD3-027", "MES-TD3-028", "MES-TD3-029")

# 인증(`app/auth.py`)은 화면이 아니라 공통화면 `login` 이라 `SCREENS` 에 들어가지 않는다.
# `main.py` 는 **화면 모듈만** 싣는다(§8 등록 규약) — 그래서 개발1 담당 라우터에 얹는다(D-117).
router.include_router(auth.router)

# TD5 `SYS_CONFIGS.CONFIG_TYPE` 비고가 정한 3구분
CONFIG_TYPES = ("시스템설정", "인터페이스설정", "알림기준")
ALERT_CHANNELS = ("화면", "현황판", "스마트패드", "화면·현황판", "화면·스마트패드")


def _opts(values) -> list[dict[str, str]]:
    return [{"value": v, "label": v} for v in values]


def _role_options() -> list[dict[str, str]]:
    return [{"value": r.code, "label": r.name} for r in rbac.roles().values()]


def _role_rep() -> dict[str, int]:
    """역할 대표 권한행 — `SYS_USERS.ROLE_ID` 가 가리키는 행(공통 시드와 같은 규칙)."""
    return {r["role_code"]: int(r["rid"]) for r in conn.q(
        "select ROLE_CODE, min(ROLE_PERM_ID) as rid from SYS_ROLE_PERMISSIONS group by ROLE_CODE")}


# ═════════════════════════════════════════════════════════════════════════
# 026 사용자 관리
# ═════════════════════════════════════════════════════════════════════════
@router.get("/sys/026")
async def users(request: Request):
    return _users_page(request)


def _users_page(request: Request, issued: str = "", issued_for: str = ""):
    """발급 비밀번호는 **POST 응답 본문**으로만 흐른다 — URL 쿼리스트링에 싣지 않는다(D-118).
    쿼리스트링은 접속로그·프록시·브라우저 이력에 남는다(9.2 ① · G-29)."""
    sid = "MES-TD3-026"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("login"):
        where.append("u.LOGIN_ID ilike %s"); params.append(f"%{q['login']}%")
    if q.get("name"):
        where.append("u.USER_NAME ilike %s"); params.append(f"%{q['name']}%")
    if q.get("role"):
        where.append("p.ROLE_CODE = %s"); params.append(q["role"])
    if q.get("dept"):
        where.append("u.DEPT_NAME ilike %s"); params.append(f"%{q['dept']}%")
    if q.get("use"):
        where.append("u.USE_YN = %s"); params.append(q["use"])
    cond = " and ".join(where)
    join = ("from SYS_USERS u "
            "left join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID")

    total = int(conn.q1(f"select count(*) as n {join} where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select u.LOGIN_ID, u.USER_NAME, u.DEPT_NAME, p.ROLE_NAME, u.LOCK_YN, u.USE_YN, "
        f"u.PHONE_NO, u.EMAIL {join} where {cond} order by u.LOGIN_ID limit %s offset %s",
        [*params, size, off])
    # G-29 — 사용자명은 마스킹해서 내보낸다. 원문을 렌더하지 않는다.
    grid = [[str(off + i), r["login_id"], mask(r["user_name"], "name"),
             val(r["dept_name"], "D-108"), val(r["role_name"], "D-108"),
             r["lock_yn"], r["use_yn"]]
            for i, r in enumerate(rows, 1)]

    contact_rows = [[str(off + i), r["login_id"],
                     mask(r["phone_no"], "phone") or undetermined("D-108"),
                     mask(r["email"], "email") or undetermined("D-108")]
                    for i, r in enumerate(rows, 1)]

    locked = int(conn.q1("select count(*) as n from SYS_USERS where LOCK_YN='Y'")["n"])
    notices = [{"kind": "notice",
                "text": "사용자명·연락처·이메일은 마스킹해서 표시한다 (G-29 · TD5 개인정보)"}]
    if issued:
        notices.insert(0, {"kind": "bad",
                           "text": f"'{issued_for}' 발급 비밀번호 {issued} — "
                                   "이 화면에만 1회 표시된다. 다시 볼 수 없다 (G-29)"})

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("login", "text"), ("name", "text"), ("role", "text", _role_options()),
            ("dept", "text"), ("use", "text", _opts(("Y", "N")))]),
        rows=grid, total=total, pager=pager, grid_title="사용자",
        empty_notice=http.not_collected("D-108") + " — 이 조건에 맞는 계정이 없다.",
        cards=[{"label": "계정", "value": f"{total} 건"},
               {"label": "잠금", "value": f"{locked} 건"},
               {"label": "역할", "value": f"{len(rbac.roles())} 종"}],
        notices=notices,
        panels=[{
            "title": "연락처 (마스킹 — G-29)",
            "columns": ["No", "로그인 계정", "연락처", "이메일"],
            "rows": contact_rows,
            "empty_notice": http.not_collected("D-108"),
            "note": "원문은 화면에 내보내지 않는다. 값이 없으면 미확정으로 표시한다.",
        }],
        form={
            "title": "사용자 등록", "action": "/sys/026", "submit": "저장",
            "note": "비밀번호는 저장하지 않고 **난수를 1회 발급**해 화면에 한 번만 보여준다(G-29). "
                    "역할은 TD3 role_matrix 6역할만 선택된다 — 권한 없는 영역은 403 이다(G-28).",
            "fields": [
                {"label": "로그인 계정", "name": "login_id", "required": True},
                {"label": "사용자명", "name": "user_name", "required": True},
                {"label": "소속", "name": "dept_name"},
                {"label": "역할", "name": "role_code", "required": True, "options": _role_options()},
                {"label": "연락처", "name": "phone_no"},
                {"label": "이메일", "name": "email", "type": "email"},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·비밀번호 초기화는 미구현이다 — "
                      "인증 모듈(app/auth.py)이 들어온 뒤에 붙인다(G-30).",
    )


@router.post("/sys/026")
async def users_save(request: Request):
    sid = "MES-TD3-026"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("login_id", "user_name", "role_code"))
    if v["role_code"] not in rbac.roles():
        raise http.fail("validation", f"알 수 없는 역할: {v['role_code']}")
    if conn.q1("select 1 as x from SYS_USERS where LOGIN_ID = %s", (v["login_id"],)):
        raise http.fail("validation", f"로그인 계정 중복: {v['login_id']}")
    rep = _role_rep().get(v["role_code"])
    if rep is None:
        raise http.fail("internal",
                        f"역할 '{v['role_code']}' 의 권한행이 없다 — 먼저 `make db-seed`")

    # 저장소에 리터럴 0건 (G-29) · 발급값도 **계정 정책을 만족해야 한다** (9.2-2 · auth.policy_errors)
    raw = auth.generate_password()
    conn.x(
        "insert into SYS_USERS (LOGIN_ID, PASSWORD_HASH, USER_NAME, DEPT_NAME, ROLE_ID, "
        " PHONE_NO, EMAIL, PWD_CHANGED_DT, LOCK_YN, USE_YN, CREATED_DT) "
        "values (%s,%s,%s,%s,%s,%s,%s, now(), 'N','Y', now())",
        (v["login_id"], auth.hash_password(raw), v["user_name"],
         (f.get("dept_name") or "").strip() or None, rep,
         (f.get("phone_no") or "").strip() or None, (f.get("email") or "").strip() or None))
    # 리다이렉트하지 않는다 — 리다이렉트하면 원문이 URL 로 흐른다(D-118).
    return _users_page(request, issued=raw, issued_for=v["login_id"])


# ═════════════════════════════════════════════════════════════════════════
# 027 로그 관리 — `SYS_ACCESS_LOGS` 는 런타임 전용이다 (G-11)
# ═════════════════════════════════════════════════════════════════════════
@router.get("/sys/027")
async def logs(request: Request):
    sid = "MES-TD3-027"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("from"):
        where.append("g.OCCURRED_DT >= %s"); params.append(q["from"])
    if q.get("to"):
        where.append("g.OCCURRED_DT < (%s::date + 1)"); params.append(q["to"])
    if q.get("kind"):
        where.append("g.LOG_TYPE = %s"); params.append(q["kind"])
    if q.get("user"):
        where.append("u.LOGIN_ID ilike %s"); params.append(f"%{q['user']}%")
    if q.get("screen"):
        where.append("g.SCREEN_ID = %s"); params.append(q["screen"])
    if q.get("result"):
        where.append("g.RESULT_CODE = %s"); params.append(q["result"])
    cond = " and ".join(where)
    join = "from SYS_ACCESS_LOGS g left join SYS_USERS u on u.USER_ID = g.USER_ID"

    total = int(conn.q1(f"select count(*) as n {join} where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select g.OCCURRED_DT, g.LOG_TYPE, u.LOGIN_ID, g.SCREEN_ID, g.ACTION_NAME, "
        f"g.RESULT_CODE, g.ERROR_MSG {join} where {cond} "
        f"order by g.OCCURRED_DT desc, g.LOG_ID desc limit %s offset %s", [*params, size, off])
    grid = [[str(off + i), dt(r["occurred_dt"], "D-17"), r["log_type"],
             r["login_id"] or undetermined("D-108"),
             r["screen_id"] or "-", r["action_name"], r["result_code"]]
            for i, r in enumerate(rows, 1)]

    by_type = {r["log_type"]: int(r["n"]) for r in conn.q(
        "select LOG_TYPE, count(*) as n from SYS_ACCESS_LOGS group by LOG_TYPE")}
    downloads = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"])
    screens = [{"value": r["screen_id"], "label": r["screen_id"]} for r in conn.q(
        "select distinct SCREEN_ID from SYS_ACCESS_LOGS where SCREEN_ID is not null "
        "order by SCREEN_ID")]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("from", "date"), ("kind", "text", _opts(LOG_TYPES)), ("user", "text"),
            ("screen", "text", screens), ("result", "text", _opts(("정상", "오류")))]),
        rows=grid, total=total, pager=pager, grid_title="로그",
        empty_notice=http.not_collected("D-17") +
        " — 접속·작업 로그는 런타임 전용이다(G-11). 깨끗한 DB 에서 0건이 정상이고 "
        "화면 조회·변경이 일어나면 쌓인다.",
        cards=[{"label": "로그", "value": f"{total} 건"}] +
              [{"label": t, "value": f"{by_type.get(t, 0)} 건"} for t in LOG_TYPES] +
              [{"label": "반출 이력", "value": f"{downloads} 건"}],
        notices=[{"kind": "notice",
                  "text": "데이터 반출은 SYS_ACCESS_LOGS 가 아니라 DAT_DOWNLOAD_LOGS 에 따로 "
                          "기록한다 (9.2 ① · G-29)"},
                 {"kind": "undetermined",
                  "text": "로그 보존기간이 정본에 없다 (D-17) — 삭제 배치를 만들지 않는다"}],
        disabled_note="'다운로드' 는 아래 버튼으로 실행하고 DAT_DOWNLOAD_LOGS 에 이력을 남긴다. "
                      "엑셀 파일 생성은 미구현이다(G-30).",
        extra_actions=[{"label": "다운로드 이력 기록", "action": "/sys/027",
                        "name": "action", "value": "download"}],
    )


@router.post("/sys/027")
async def logs_download(request: Request):
    """로그 반출 — **이력을 먼저 남긴다**(9.2 ① · G-29). 파일 생성은 미구현이다."""
    sid = "MES-TD3-027"
    form = await request.form()
    csrf.require(request, form.get("_csrf"))
    guard(request, sid, write=True)
    if (form.get("action") or "").strip() != "download":
        raise http.fail("validation", "알 수 없는 동작")
    _record_download(request, sid, "로그", "CSV",
                     int(conn.q1("select count(*) as n from SYS_ACCESS_LOGS")["n"]))
    return redirect("/sys/027")


def _record_download(request: Request, screen_id: str, category: str,
                     fmt: str, row_cnt: int) -> None:
    """`DAT_DOWNLOAD_LOGS` — 반출 통제(9.2 ①). 권한 없으면 403 이고 기록도 남지 않는다."""
    role = getattr(request.state, "role_code", "") or ""
    perm = conn.q1("select DOWNLOAD_YN from SYS_ROLE_PERMISSIONS "
                   "where ROLE_CODE = %s and AREA_CODE = %s limit 1",
                   (role, screen_id_area(screen_id)))
    if not perm or perm["download_yn"] != "Y":
        raise http.fail("forbidden", f"역할 {role} 에 반출 권한이 없다 (9.2 ①)")
    user_id = getattr(getattr(request.state, "session", None), "user_id", None)
    if user_id is None:                    # DAT_DOWNLOAD_LOGS.USER_ID 는 NOT NULL 이다
        row = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
        if not row:
            raise http.fail("internal", "반출 기록에 쓸 사용자가 없다 — 먼저 `make db-seed`")
        user_id = int(row["user_id"])
    conn.x(
        "insert into DAT_DOWNLOAD_LOGS "
        "(USER_ID, SCREEN_ID, DATA_CATEGORY, FILE_FORMAT, ROW_CNT, APPROVED_YN, "
        " DOWNLOAD_DT, CREATED_DT) values (%s,%s,%s,%s,%s,'Y',%s, now())",
        (user_id, screen_id, category, fmt, row_cnt, clock.anchor()))


def screen_id_area(screen_id: str) -> str:
    from .. import nav
    return nav.by_id()[screen_id].prefix.upper()


# ═════════════════════════════════════════════════════════════════════════
# 028 알림 설정
# ═════════════════════════════════════════════════════════════════════════
@router.get("/sys/028")
async def alerts(request: Request):
    sid = "MES-TD3-028"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["CONFIG_TYPE = '알림기준'"], []
    if q.get("type"):
        where[0] = "CONFIG_TYPE = %s"; params.append(q["type"])
    if q.get("key"):
        where.append("CONFIG_KEY ilike %s"); params.append(f"%{q['key']}%")
    if q.get("role"):
        where.append("TARGET_ROLE_CODE = %s"); params.append(q["role"])
    if q.get("channel"):
        where.append("ALERT_CHANNEL = %s"); params.append(q["channel"])
    if q.get("use"):
        where.append("USE_YN = %s"); params.append(q["use"])
    cond = " and ".join(where)

    total = int(conn.q1(f"select count(*) as n from SYS_CONFIGS where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select CONFIG_KEY, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL, USE_YN, "
        f"UPDATED_DT, CREATED_DT from SYS_CONFIGS where {cond} order by CONFIG_KEY "
        f"limit %s offset %s", [*params, size, off])
    role_name = {r.code: r.name for r in rbac.roles().values()}
    grid = [[str(off + i), r["config_key"], val(r["alert_condition"], "D-109"),
             role_name.get(r["target_role_code"], r["target_role_code"] or "")
             or undetermined("D-109"),
             val(r["alert_channel"], "D-109"), r["use_yn"],
             dt(r["updated_dt"] or r["created_dt"])]
            for i, r in enumerate(rows, 1)]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("type", "text", _opts(CONFIG_TYPES)), ("key", "text"),
            ("role", "text", _role_options()), ("channel", "text", _opts(ALERT_CHANNELS)),
            ("use", "text", _opts(("Y", "N")))]),
        rows=grid, total=total, pager=pager, grid_title="알림 기준",
        empty_notice=http.not_collected("D-109") + " — 이 조건에 맞는 알림 기준이 없다.",
        cards=[{"label": "알림 기준", "value": f"{total} 건"},
               {"label": "수신 역할", "value": f"{len(role_name)} 종"}],
        notices=[{"kind": "undetermined",
                  "text": "알림 임계값(설비 이상·납기 경고·품질 이상)이 정본에 수치로 없다 — "
                          "조건 문장만 두고 값은 화면 입력이다 (D-109)"},
                 {"kind": "bad",
                  "text": "'테스트 발송' 은 발송 채널이 구성되지 않아 미구현이다 — "
                          "보낸 척하지 않는다 (G-30)"}],
        form={
            "title": "알림 기준 등록", "action": "/sys/028", "submit": "저장",
            "note": "설정 키는 구분 안에서 중복될 수 없다 — 중복이면 422 "
                    "(UNIQUE(CONFIG_TYPE, CONFIG_KEY) · D-34).",
            "fields": [
                {"label": "설정 키", "name": "config_key", "required": True},
                {"label": "알림 조건", "name": "alert_condition", "required": True},
                {"label": "임계값", "name": "config_value"},
                {"label": "수신 대상 역할", "name": "target_role_code", "options": _role_options()},
                {"label": "알림 채널", "name": "alert_channel", "options": _opts(ALERT_CHANNELS)},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·테스트 발송은 미구현이다(G-30).",
    )


@router.post("/sys/028")
async def alerts_save(request: Request):
    sid = "MES-TD3-028"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("config_key", "alert_condition"))
    role = (f.get("target_role_code") or "").strip() or None
    if role and role not in rbac.roles():
        raise http.fail("validation", f"알 수 없는 역할: {role}")
    if conn.q1("select 1 as x from SYS_CONFIGS where CONFIG_TYPE='알림기준' and CONFIG_KEY=%s",
               (v["config_key"],)):
        raise http.fail("validation", f"설정 키 중복: 알림기준 '{v['config_key']}'")
    conn.x(
        "insert into SYS_CONFIGS (CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, ALERT_CONDITION, "
        " TARGET_ROLE_CODE, ALERT_CHANNEL, USE_YN, CREATED_DT) "
        "values ('알림기준',%s,%s,%s,%s,%s,'Y', now())",
        (v["config_key"], (f.get("config_value") or "").strip() or None, v["alert_condition"],
         role, (f.get("alert_channel") or "").strip() or None))
    return redirect("/sys/028")


# ═════════════════════════════════════════════════════════════════════════
# 029 시스템 설정
# ═════════════════════════════════════════════════════════════════════════
SECRET_TYPES = ("인터페이스설정",)      # 접속 주소·계정은 암호화 저장 대상이다 (TD5 criteria)


@router.get("/sys/029")
async def configs(request: Request):
    sid = "MES-TD3-029"
    scr, td3 = guard(request, sid)
    q = request.query_params
    where, params = ["1=1"], []
    if q.get("type"):
        where.append("CONFIG_TYPE = %s"); params.append(q["type"])
    if q.get("key"):
        where.append("CONFIG_KEY ilike %s"); params.append(f"%{q['key']}%")
    if q.get("use"):
        where.append("USE_YN = %s"); params.append(q["use"])
    if q.get("iface"):
        where.append("ALERT_CONDITION = %s"); params.append(q["iface"])
    cond = " and ".join(where)

    total = int(conn.q1(f"select count(*) as n from SYS_CONFIGS where {cond}", params)["n"])
    pager, size, off = paginate(request, total)
    rows = conn.q(
        f"select CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, DESCRIPTION, USE_YN, UPDATED_DT, "
        f"CREATED_DT from SYS_CONFIGS where {cond} order by CONFIG_TYPE, CONFIG_KEY "
        f"limit %s offset %s", [*params, size, off])

    def shown(r) -> object:
        """인터페이스 접속 정보는 값을 내보내지 않는다 (암호화 저장 대상)."""
        if r["config_type"] in SECRET_TYPES:
            return "(암호화 저장)" if r["config_value"] else undetermined("D-07")
        return val(r["config_value"], "D-110")

    grid = [[str(off + i), r["config_type"], r["config_key"], shown(r),
             val(r["description"], "D-110"), r["use_yn"],
             dt(r["updated_dt"] or r["created_dt"])]
            for i, r in enumerate(rows, 1)]

    src_rows = [[str(i), s["source_name"], s["data_type"], s["if_method"],
                 val(s["collect_cycle"], "D-06"), val(s["interface_code"], "D-110"), s["use_yn"]]
                for i, s in enumerate(conn.q(
                    "select SOURCE_NAME, DATA_TYPE, IF_METHOD, COLLECT_CYCLE, INTERFACE_CODE, "
                    "USE_YN from DAT_SOURCES order by SOURCE_ID"), 1)]
    dev_rows = [[str(i), d["device_name"], d["device_type"], val(d["model_name"], "D-06"),
                 mask(d["ip_address"], "generic") or undetermined("D-06"),
                 d["protocol"], val(d["collect_interval"], "D-06")]
                for i, d in enumerate(conn.q(
                    "select DEVICE_NAME, DEVICE_TYPE, MODEL_NAME, IP_ADDRESS, PROTOCOL, "
                    "COLLECT_INTERVAL from IF_DEVICE_REGISTRY order by DEVICE_ID"), 1)]

    ifaces = [{"value": r["alert_condition"], "label": r["alert_condition"]} for r in conn.q(
        "select distinct ALERT_CONDITION from SYS_CONFIGS "
        "where CONFIG_TYPE = '인터페이스설정' and ALERT_CONDITION is not null "
        "order by ALERT_CONDITION")]

    return screen_page(
        request, sid, _loaded=(scr, td3),
        search=search_spec(td3, request, [
            ("type", "text", _opts(CONFIG_TYPES)), ("key", "text"),
            ("use", "text", _opts(("Y", "N"))), ("iface", "text", ifaces)]),
        rows=grid, total=total, pager=pager, grid_title="시스템 설정",
        empty_notice=http.not_collected("D-110") + " — 이 조건에 맞는 설정이 없다.",
        cards=[{"label": "설정", "value": f"{total} 건"},
               {"label": "수집대상", "value": f"{len(src_rows)} 건"},
               {"label": "등록 장비", "value": f"{len(dev_rows)} 건"}],
        notices=[{"kind": "notice",
                  "text": "외부 인터페이스 4종(ERP 연계·IoT/PLC·CAD 파일·외부 표준문서)은 "
                          "FP산정리스트에서 EIF 로 별도 산정된다 (SF-TD3-029 체크)"},
                 {"kind": "undetermined",
                  "text": "접속 주소·계정은 정본에 값이 없고 암호화 저장 대상이다 — "
                          "값을 내보내지 않는다 (D-07)"},
                 {"kind": "bad",
                  "text": "'연계 테스트' 는 실 연동이 범위 밖이라 미구현이다 — "
                          "성공한 척하지 않는다 (D-07 · G-30)"}],
        panels=[
            {"title": "데이터 수집대상 (DAT_SOURCES)",
             "columns": ["No", "수집대상명", "데이터 유형", "연계 방식", "수집 주기",
                         "담당 인터페이스", "사용여부"],
             "rows": src_rows,
             "empty_notice": http.not_collected("D-06"),
             "note": "수집 지점은 레이저커팅기 PLC·현장POP 2개소뿐이다 (D-06). "
                     "수집 주기는 사업계획서에 없어 비워 둔다."},
            {"title": "수집 장비 등록 (IF_DEVICE_REGISTRY · IP 마스킹 — G-29)",
             "columns": ["No", "장비명", "장비 구분", "모델명", "IP 주소", "프로토콜", "수집 주기(초)"],
             "rows": dev_rows,
             "empty_notice": http.not_collected("D-06") +
             " — 장비 등록은 개발3 의 수집 API(TD4-047)가 채운다."},
        ],
        form={
            "title": "시스템 설정 등록", "action": "/sys/029", "submit": "저장",
            "note": "설정 키는 구분 안에서 중복될 수 없다 — 중복이면 422 (D-34). "
                    "인터페이스설정의 값은 화면에 다시 내보내지 않는다.",
            "fields": [
                {"label": "설정 구분", "name": "config_type", "required": True,
                 "options": _opts(CONFIG_TYPES)},
                {"label": "설정 키", "name": "config_key", "required": True},
                {"label": "설정 값", "name": "config_value"},
                {"label": "설명", "name": "description"},
            ],
        },
        disabled_note="등록·저장은 아래 폼이 담당한다. 삭제·연계 테스트는 미구현이다(G-30).",
    )


@router.post("/sys/029")
async def configs_save(request: Request):
    sid = "MES-TD3-029"
    f = await request.form()
    csrf.require(request, f.get("_csrf"))
    guard(request, sid, write=True)
    v = require_fields(f, ("config_type", "config_key"))
    if v["config_type"] not in CONFIG_TYPES:
        raise http.fail("validation", f"설정 구분은 {CONFIG_TYPES} 중 하나다")
    if v["config_key"] == clock.CONFIG_KEY and v["config_type"] == clock.CONFIG_TYPE:
        raise http.fail("validation",
                        "시간 앵커는 화면에서 바꾸지 않는다 — 시드가 발급한다 (§10-3)")
    if conn.q1("select 1 as x from SYS_CONFIGS where CONFIG_TYPE=%s and CONFIG_KEY=%s",
               (v["config_type"], v["config_key"])):
        raise http.fail("validation", f"설정 키 중복: {v['config_type']} '{v['config_key']}'")
    conn.x(
        "insert into SYS_CONFIGS (CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, USE_YN, DESCRIPTION, "
        " CREATED_DT) values (%s,%s,%s,'Y',%s, now())",
        (v["config_type"], v["config_key"], (f.get("config_value") or "").strip() or None,
         (f.get("description") or "").strip() or None))
    return redirect(f"/sys/029?type={v['config_type']}")
