#!/usr/bin/env python
"""공통 시드 (아키텍트) — 시간 앵커 · 역할 6 · 계정 · 공통코드.

**규칙 (goal.md)**
  · 멱등이다(G-07). 두 번 돌려도 행 수 diff 0.
  · 생성 기준일은 **시간 앵커**에 고정한다. `date.today()` 금지(§10-3).
  · **지어내지 않는다.** 정본(사업계획서·TD1·TD5 비고)에 값이 있는 코드 그룹만 채우고,
    없는 그룹은 **비워 둔다** — 화면이 `미확정 (D-nn)` 을 렌더한다(§0.2).
  · 계정 비밀번호는 **계정별 난수를 1회 출력**한다. 저장소에 리터럴 0건(G-29).
  · 이미 있는 계정의 비밀번호는 **건드리지 않는다** — 재실행이 남의 로그인을 깨면 안 된다(§10-11).

업무 데이터는 `db/seed_dev1.py` · `seed_dev2.py` · `seed_dev3.py` 가 각자 넣는다.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app import nav, rbac                      # noqa: E402
from kyungdong.app.settings import settings              # noqa: E402
from kyungdong.app.util import clock                     # noqa: E402

# TD5 `SYS_ROLE_PERMISSIONS.AREA_CODE` 비고가 정한 10코드 — nav 의 라우트 접두와 같다(실측 확인)
AREA_CODE = {s.area: s.prefix.upper() for s in nav.all_screens()}

# ── 정본에 값이 있는 코드 그룹만 채운다 ──────────────────────────────────
# 공정 10단계 — 사업계획서 1.3 (외주 2공정 포함)
PROCESSES = [
    ("P10", "수주견적관리", "AI 대상 — CAD 견적 자동화"),
    ("P20", "입고검사", "AI 대상 — 입고 RAG Agent"),
    ("P30", "소재가공(외주)", "외주. 발주·반출·반입 상태 관리 (D-41)"),
    ("P40", "가공(레이저커팅)", "**자동 수집 공정** — Master PLC 1지점 (사업계획서 2.7.1)"),
    ("P50", "제관 및 용접", "현장POP 수동 입력. WPS·용접사 자격 참조"),
    ("P60", "버핑(외주)", "외주. 발주·반출·반입 상태 관리 (D-41)"),
    ("P70", "조립", "현장POP·스마트패드 수동 입력"),
    ("P80", "출하검사", "수압·기밀·진공 시험"),
    ("P90", "포장", "스마트패드 입력. 제조 리드타임 종료 시각 (LEADTIME_MFG)"),
    ("P95", "출하", "AI 대상 — 출하 RAG Agent. 수주출하 리드타임 종료 시각 (LEADTIME_O2D)"),
]
# 제품군 5 — 사업계획서 1.1 · design.json meta.products
PRODUCT_GROUPS = [
    ("PG10", "반응기", "Reactor — CAD 아카이브 최대 비중(48프로젝트·470도면)"),
    ("PG20", "교반기", "Agitator"),
    ("PG30", "진공건조기", "Vacuum Dryer"),
    ("PG40", "누체필터", "Nutsche Filter"),
    ("PG50", "저장탱크", "Receiver Tank"),
]
# 검사구분 — 사업계획서 1.3 출하검사(수압·기밀·진공)
INSPECT_TYPES = [("IT10", "수압", ""), ("IT20", "기밀", ""), ("IT30", "진공", "")]
# 공급구분 — TD1 입고검사(원자재·부자재) + INV_SUPPLIERS.SUPPLY_TYPE 비고(외주)
SUPPLY_TYPES = [("ST10", "원자재", ""), ("ST20", "부자재", ""), ("ST30", "외주", "소재가공·버핑")]
# 외주구간 — PRC_PROCESS_HISTORIES.OUTSOURCE_STEP 비고
OUTSOURCE_STEPS = [("OS10", "반출", ""), ("OS20", "반입", "")]
# 설비 — 사업계획서 2.7.1 데이터 집계 포인트 **2개소뿐**
EQUIPMENTS = [
    ("EQ10", "레이저커팅기", "FC3015S_6000/6kW · Master PLC XBC-DN32H + XBL-EMTA · Ethernet/OPC-UA"),
    ("EQ20", "현장POP(터치PC)", "DUPLE 21\" 안드로이드 · 작업·검사 입력 (D-25 명칭 병기)"),
]

CODE_GROUPS: dict[str, tuple[list[tuple[str, str, str]], str]] = {
    "공정": (PROCESSES, "사업계획서 1.3 공정 흐름 10단계"),
    "제품군": (PRODUCT_GROUPS, "사업계획서 1.1 · meta.products"),
    "검사구분": (INSPECT_TYPES, "사업계획서 1.3 출하검사"),
    "공급구분": (SUPPLY_TYPES, "TD1 입고검사 · INV_SUPPLIERS.SUPPLY_TYPE 비고"),
    "외주구간": (OUTSOURCE_STEPS, "PRC_PROCESS_HISTORIES.OUTSOURCE_STEP 비고"),
    "설비": (EQUIPMENTS, "사업계획서 2.7.1 데이터 집계 포인트 2개소"),
}
# 정본에 구체 값이 **없는** 그룹 — 비워 둔다. 화면 입력 마스터이고 시드에 지어내지 않는다.
EMPTY_GROUPS: dict[str, str] = {
    "품목": "품목 마스터가 정본에 없다 — 화면 입력 (D-26)",
    "재질": "재질 코드 목록이 정본에 없다 — 입고·도면에서 수집",
    "고객사": "고객사 목록이 정본에 없다 — 개인정보·거래처 (D-26)",
    "보관위치": "창고 레이아웃이 정본에 없다 — 현장 실사 (D-26)",
    "불량유형": "불량 유형 분류가 정본에 없다 — 화면 입력",
    "클레임유형": "클레임 유형 분류가 정본에 없다 — 화면 입력",
    "원가대상": "EST_COST_RATES.TARGET_CODE 는 재질·공정·외주처의 합집합이라 단일 그룹이 아니다 (D-32)",
}

# 역할별 대표 계정 — **실명을 넣지 않는다**(G-29 · D-39). 직무 계정이다.
ACCOUNTS = [
    ("exec",     "EXEC",         "총괄PM/경영자", "경영"),
    ("quality",  "QUALITY",      "품질·RCMS 담당", "품질"),
    ("prod",     "PRODUCTION",   "공장장·생산관리", "생산"),
    ("operator", "OPERATOR",     "현장 작업자", "생산"),
    ("supplier", "SUPPLIER_OPS", "공급기업 운영담당", "공급기업"),
    ("admin",    "SYSADMIN",     "시스템 관리자", "전산"),
]


def hash_password(raw: str) -> str:
    from passlib.hash import argon2
    return argon2.hash(raw)


def seed_anchor() -> datetime:
    """앵커를 발급한다. 이미 있으면 **그대로 쓴다** — 재실행이 수치를 흔들지 않는다."""
    import conn as c
    row = c.q1("select CONFIG_VALUE from SYS_CONFIGS where CONFIG_TYPE=%s and CONFIG_KEY=%s",
               (clock.CONFIG_TYPE, clock.CONFIG_KEY))
    if row and row["config_value"]:
        return datetime.fromisoformat(row["config_value"])
    # 새 앵커: 오늘이 아니라 **고정 가능한 기준**으로 잡는다 — 정시로 끊어 재현 가능하게.
    value = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    clock.issue(value)
    return value


def seed_roles() -> dict[str, int]:
    """6역할 × 10업무영역. **upsert 다** — delete 는 `SYS_USERS.ROLE_ID` FK 가 막는다(D-44).
    물리 유니크 `UNIQUE NULLS NOT DISTINCT (ROLE_CODE, AREA_CODE, SCREEN_ID)` 에 기댄다(D-45)."""
    for role in rbac.roles().values():
        for area, code in sorted(AREA_CODE.items(), key=lambda kv: kv[1]):
            p = rbac.perm_for(role.code, area)
            conn.x(
                "insert into SYS_ROLE_PERMISSIONS "
                "(ROLE_CODE, ROLE_NAME, AREA_CODE, READ_YN, WRITE_YN, DELETE_YN, DOWNLOAD_YN, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s, now()) "
                "on conflict (ROLE_CODE, AREA_CODE, SCREEN_ID) do update set "
                "ROLE_NAME = excluded.ROLE_NAME, READ_YN = excluded.READ_YN, "
                "WRITE_YN = excluded.WRITE_YN, DELETE_YN = excluded.DELETE_YN, "
                "DOWNLOAD_YN = excluded.DOWNLOAD_YN, UPDATED_DT = now()",
                (role.code, role.name, code,
                 "Y" if p.read else "N",
                 "Y" if p.write else "N",
                 "Y" if p.write else "N",          # 삭제는 등록·수정 권한에 준한다 (TD3 는 구분하지 않는다)
                 "Y" if p.read else "N"),          # 반출 통제는 9.2 ① — 조회 권한 있는 역할만
            )
    rows = conn.q("select ROLE_CODE, min(ROLE_PERM_ID) as rid from SYS_ROLE_PERMISSIONS group by ROLE_CODE")
    return {r["role_code"]: int(r["rid"]) for r in rows}


def seed_accounts(role_rep: dict[str, int]) -> list[tuple[str, str]]:
    """계정별 난수 비밀번호를 **1회 출력**. 이미 있는 계정은 비밀번호를 바꾸지 않는다(§10-11)."""
    issued: list[tuple[str, str]] = []
    fixed = settings().seed_password        # 자동화 전용. 비어 있으면 난수
    for login, role_code, name, dept in ACCOUNTS:
        exists = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = %s", (login,))
        if exists:
            continue
        raw = fixed or secrets.token_urlsafe(12)
        conn.x(
            "insert into SYS_USERS (LOGIN_ID, PASSWORD_HASH, USER_NAME, DEPT_NAME, ROLE_ID, "
            "PWD_CHANGED_DT, LOCK_YN, USE_YN, CREATED_DT) "
            "values (%s,%s,%s,%s,%s, now(), 'N','Y', now())",
            (login, hash_password(raw), name, dept, role_rep[role_code]),
        )
        if not fixed:
            issued.append((login, raw))
    return issued


def seed_codes(admin_id: int | None) -> tuple[int, int]:
    filled = 0
    for group, (items, source) in CODE_GROUPS.items():
        for i, (value, label, note) in enumerate(items, 1):
            conn.x(
                "insert into BAS_COMMON_CODES "
                "(CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, ATTR1, USE_YN, CREATED_BY, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,'Y',%s, now()) "
                "on conflict (CODE_GROUP, CODE_VALUE) do update set "
                "CODE_NAME = excluded.CODE_NAME, SORT_ORDER = excluded.SORT_ORDER, "
                "ATTR1 = excluded.ATTR1, UPDATED_DT = now()",
                (group, value, label, i * 10, note or source, admin_id),
            )
            filled += 1
    return filled, len(EMPTY_GROUPS)


def main() -> int:
    if conn.table_count() != 68:
        print(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-schema`", file=sys.stderr)
        return 1

    a = seed_anchor()
    role_rep = seed_roles()
    issued = seed_accounts(role_rep)
    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    filled, empty = seed_codes(int(admin["user_id"]) if admin else None)

    print(f"시간 앵커       {a.isoformat(sep=' ')}   (date.today() 금지 — §10-3)")
    print(f"역할·권한       {conn.q1('select count(*) n from SYS_ROLE_PERMISSIONS')['n']} 행"
          f"  ({len(rbac.roles())}역할 × {len(set(AREA_CODE.values()))}영역)")
    print(f"계정           {conn.q1('select count(*) n from SYS_USERS')['n']} 건")
    print(f"공통코드        {conn.q1('select count(*) n from BAS_COMMON_CODES')['n']} 건"
          f"  (채운 그룹 {len(CODE_GROUPS)} / 비운 그룹 {empty})")
    print()
    print("비운 코드 그룹 — 정본에 값이 없다. 지어내지 않는다(화면 입력 마스터):")
    for g, why in EMPTY_GROUPS.items():
        print(f"  · {g:<8} {why}")
    if issued:
        print()
        print("발급된 비밀번호 (이 출력에만 나온다 — 저장소에 남기지 않는다):")
        for login, raw in issued:
            print(f"  {login:<10} {raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
