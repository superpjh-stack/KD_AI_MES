#!/usr/bin/env python
"""개발1 업무 시드 — 채번 규칙 · 시스템/알림 설정 · 데이터 수집대상 · 통합작업.

**규칙 (goal.md)**
  · 멱등이다(G-07). 두 번 돌려도 행 수 diff 0.
  · 생성 기준일은 **시간 앵커**(`util.clock.anchor()`)에 고정한다. `date.today()` 금지(§10-3).
  · **지어내지 않는다**(§0.2). 정본(사업계획서·SF-TD3/TD4/TD5 비고)에 값이 있는 것만 넣고,
    없으면 **넣지 않는다** — 화면이 `미확정 (D-nn)` / `미수집 (D-nn)` 을 렌더한다.
  · 목업의 `(예시)` 값은 시드에 넣지 않는다.
  · 공통 시드(`db/seed.py`)가 이미 넣은 것(시간앵커·역할권한·계정·공통코드 6그룹)은 다시 넣지 않는다.
  · 런타임 전용 표는 비워 둔다(G-11): `SYS_ACCESS_LOGS` `DAT_JOB_LOGS` `DAT_DOWNLOAD_LOGS` `IF_ERP_*`.

**시드하지 않는 표와 그 근거는 `NOT_SEEDED` 에 적혀 있고 실행 출력이 그대로 찍는다.**
숫자만 적고 근거를 빼지 않는다 — 근거 없는 0건은 결함과 구분되지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.util import clock                     # noqa: E402

# ─────────────────────────────────────────────────────────────────────────
# 1. 채번 규칙 — 개발1 이 정하고 공표한다 (goal.md §5 개발1 · interfaces.md §9)
#
#    형식은 SF-TD3 목업이 쓴 **모양**을 따른다. 목업의 `(예시)` **값**은 시드에 넣지 않고
#    자리표기(YYYY·NN)만 규칙으로 삼는다. 개발2·개발3 이 이 규칙을 그대로 쓴다.
#    `BAS_COMMON_CODES` 그룹 `LOT채번` 이 런타임 정본이다 (TD5 CODE_GROUP 비고 'LOT채번').
# ─────────────────────────────────────────────────────────────────────────
NUMBERING: list[tuple[str, str, str, str]] = [
    # (CODE_VALUE, CODE_NAME, ATTR1=형식, ATTR2=적용 컬럼)
    ("PROJECT_NO", "프로젝트(수주)번호", "PJ-YYYY-NNN",
     "EST_PROJECTS.PROJECT_NO — ETO 최상위 추적 키 (G-08 1단계)"),
    ("DRAWING_NO", "도면번호", "DWG-{제품군3}-NNNN",
     "EST_CAD_DRAWINGS.DRAWING_NO — 제품군3 은 그룹 '제품군' 의 ATTR2 (G-08 2단계)"),
    ("MATERIAL_LOT_NO", "자재 LOT 번호", "LOT-YYMMDD-NN",
     "INV_MATERIAL_LOTS.LOT_NO — 일자 + 당일 일련 (G-08 4단계)"),
    ("RECEIPT_NO", "입고번호", "RC-YYYY-NNNN", "INV_RECEIPTS.RECEIPT_NO"),
    ("WORK_ORDER_NO", "작업지시번호", "WO-YYYY-NNNN",
     "PRC_WORK_ORDERS.WORK_ORDER_NO (G-08 5단계)"),
    ("PRODUCT_LOT_NO", "제품 LOT 번호", "PLOT-YYYY-NNN",
     "SHP_LOT_TRACES.PRODUCT_LOT_NO — 제품 축의 중심 (G-08 7단계)"),
    ("SHIPMENT_NO", "출하번호", "SH-YYYY-NNNN", "SHP_SHIPMENTS.SHIPMENT_NO (G-08 9단계)"),
]

# 도면번호의 제품군 3글자 — 그룹 '제품군'(공통 시드) 의 ATTR2 로 붙인다. 코드 값은 늘리지 않는다.
PRODUCT_ABBR: dict[str, str] = {
    "PG10": "RCT",   # 반응기 Reactor
    "PG20": "AGI",   # 교반기 Agitator
    "PG30": "VDR",   # 진공건조기 Vacuum Dryer
    "PG40": "NFL",   # 누체필터 Nutsche Filter
    "PG50": "RTK",   # 저장탱크 Receiver Tank
}

# ─────────────────────────────────────────────────────────────────────────
# 2. SYS_CONFIGS — 인터페이스설정 4종 · 알림기준 3종
#
#    인터페이스 4종: SF-TD3-029 체크 문장 "외부 인터페이스 4종(ERP 연계·IoT/PLC·CAD 파일·
#    외부 표준문서)은 FP산정리스트에서 EIF 로 별도 산정" + SF-TD4-046~049.
#    **접속 주소·계정은 정본에 없다 → CONFIG_VALUE 를 넣지 않는다**(화면이 미확정을 렌더).
#    알림 3종: TD5 `SYS_CONFIGS.ALERT_CONDITION` 비고 "설비 이상·납기 경고·품질 이상 임계값".
#    **임계값 수치는 정본에 없다 → 넣지 않는다.**
# ─────────────────────────────────────────────────────────────────────────
INTERFACE_CONFIGS: list[tuple[str, str, str]] = [
    # (CONFIG_KEY, DESCRIPTION, 담당 인터페이스 프로그램)
    ("IF_ERP", "ERP(이카운트) 연계 — 입고·출하·재고. 보유·연계 범위가 사업계획서 안에서 "
               "상충한다(D-07) → Excel 적재를 정식 입력으로 두고 IF_ERP_* 에 이력을 남긴다",
     "MES-TD4-046"),
    ("IF_IOT_PLC", "IoT/PLC 수집 — 레이저커팅기 Master PLC 1지점. 수집 지점은 2개소뿐이다(D-06)",
     "MES-TD4-047"),
    ("IF_CAD_FILE", "CAD 파일 수집 — Autodesk API·YOLOv8 미확보 시 501 로 드러낸다(D-05)",
     "MES-TD4-048"),
    ("IF_EXT_DOC", "외부 표준문서 수집 — 작업표준·품질기준 임베딩 대상", "MES-TD4-049"),
]

ALERT_CONFIGS: list[tuple[str, str, str, str]] = [
    # (CONFIG_KEY, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL)
    #   TARGET_ROLE_CODE 는 rbac 6역할 코드. ALERT_CHANNEL 은 TD5 비고 "화면 / 현황판 / 스마트패드".
    ("ALERT_EQUIP", "설비 이상 — 레이저커팅기 알람·임계 초과 (임계값 미확정)",
     "PRODUCTION", "화면·현황판"),
    ("ALERT_DUE", "납기 경고 — 납기 대비 지연 위험 (임계값 미확정)",
     "EXEC", "화면·현황판"),
    ("ALERT_QUALITY", "품질 이상 — 검사 불합격·기준 이탈 (임계값 미확정)",
     "QUALITY", "화면·스마트패드"),
]

# ─────────────────────────────────────────────────────────────────────────
# 3. DAT_SOURCES — 수집대상 5종
#    TD5 `DAT_SOURCES.SOURCE_NAME` 비고 "ERP/PLC/터치PC/CAD/외부문서" 가 정본 열거다.
#    **수집 주기는 사업계획서에 없다**(D-06) → COLLECT_CYCLE 을 넣지 않는다.
#    **접속 정보는 암호화 저장 대상이고 값이 없다** → CONNECTION_INFO 를 넣지 않는다.
# ─────────────────────────────────────────────────────────────────────────
SOURCES: list[tuple[str, str, str, str]] = [
    # (SOURCE_NAME, DATA_TYPE, IF_METHOD, INTERFACE_CODE)
    ("ERP(이카운트)", "정형", "API", "MES-TD4-046"),
    ("레이저커팅기 PLC", "시계열", "OPC-UA", "MES-TD4-047"),
    ("현장POP(터치PC)", "정형", "API", "MES-TD4-047"),
    ("CAD 도면함", "비정형", "파일", "MES-TD4-048"),
    ("외부 표준문서", "비정형", "파일", "MES-TD4-049"),
]

# 통합작업 — 수집대상 1건당 수집 작업 1건. 처리 유형·적재 대상은 TD5 비고의 열거값이다.
# **스케줄(Cron)·변환 규칙은 정본에 없다** → 넣지 않는다.
JOB_TARGET: dict[str, str] = {
    "정형": "PostgreSQL",
    "시계열": "시계열DB",
    "비정형": "Data Lake",
}

# ─────────────────────────────────────────────────────────────────────────
# 4. 시드하지 않는 표 — 근거를 함께 남긴다. 화면은 `미수집`/`미확정` 을 렌더해야 한다.
# ─────────────────────────────────────────────────────────────────────────
NOT_SEEDED: list[tuple[str, str]] = [
    ("INV_SUPPLIERS",
     "공급처 목록이 정본에 없다. 45화면에 공급처 마스터 등록 화면도 없다 → Excel 적재(/inv/007)로 "
     "들어온다. 상호를 지어내지 않는다 (D-101)"),
    ("INV_MATERIAL_LOTS",
     "ITEM_CODE(NOT NULL)·MATERIAL 이 코드성 FK 인데 그룹 '품목'·'재질' 이 비어 있다(D-47) → "
     "유효한 LOT 을 만들 수 없다. 코드를 /bas/032 에 등록한 뒤 입고가 생성한다 (D-101)"),
    ("INV_RECEIPTS",
     "LOT_ID(NOT NULL) 가 INV_MATERIAL_LOTS 를 요구한다. TD3-005 체크도 '초기 이관 범위를 "
     "착수 시 확정' 이라고 적었다 → 시드 0건이 정본 판정이다 (D-101)"),
    ("INV_STOCKS",
     "LOT_ID(NOT NULL) 가 INV_MATERIAL_LOTS 를 요구한다. 입고 저장이 반영한다 (D-101)"),
    ("INV_MATERIAL_HISTORY",
     "**판정: 런타임 누적표다** — 입고·투입·반출·반입·출하 시점에 쌓인다. 시드 대상 아님 "
     "(db-schema §7.1 개발1 몫 · D-102)"),
    ("INV_SUPPLIER_QUALITY",
     "**판정: 입고·검사 누적 집계다** — 마스터가 아니다. /inv/008 '평가산출' 이 산출한다 "
     "(db-schema §7.1 개발1 몫 · D-103)"),
    ("BAS_QUALITY_STANDARDS",
     "TD3-030 체크: '현행 검사 기준서는 문서로만 존재하므로 초기 기준 데이터는 도입기업이 "
     "제공해야 한다' → 기준값을 지어내지 않는다. /bas/030 화면 입력"),
    ("BAS_WORK_STANDARDS",
     "TD3-031 체크: '현행 작업표준은 작업자 경험으로 전파되고 있어 초기 표준 정의가 선행되어야 "
     "한다' → /bas/031 화면 입력"),
    ("SYS_ACCESS_LOGS", "런타임 전용 (G-11). 화면 조회·변경이 쌓는다"),
    ("DAT_JOB_LOGS", "런타임 전용 (G-11). /dat/033 '즉시 실행' 이 쌓는다"),
    ("DAT_DOWNLOAD_LOGS", "런타임 전용 (G-11). /dat/036 다운로드가 쌓는다"),
    ("DAT_QUALITY_CHECKS",
     "검증 실행 산출물이다 — /inv/007 '표준화·검증' 과 /dat/033 이 실측으로 기록한다. "
     "달성률을 시드로 지어내면 G-09 가 무의미해진다"),
    ("DAT_TIMESERIES", "수집 산출물 (개발3 ingest). 수집 지점은 2개소뿐이다 (D-06)"),
    ("DAT_LAKE_OBJECTS", "CAD·문서 수집 산출물 (개발3). 미구성 시 501 (D-05)"),
    ("IF_ERP_RECEIPTS", "런타임 연계 이력. Excel 적재(/inv/007)가 남긴다 (D-07)"),
    ("IF_ERP_SHIPMENTS", "런타임 연계 이력 (출하 — 개발2 화면이 남긴다) (D-07)"),
    ("IF_ERP_STOCKS", "런타임 대사 이력. /inv/007 재고 대사가 남긴다 (D-07)"),
]


# ── 시드 ──────────────────────────────────────────────────────────────────
def _admin_id() -> int | None:
    row = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    return int(row["user_id"]) if row else None


def seed_numbering(admin_id: int | None) -> int:
    """채번 규칙 7건 → `BAS_COMMON_CODES` 그룹 `LOT채번`. 복합 UNIQUE 로 멱등(D-34)."""
    for i, (value, name, fmt, applies) in enumerate(NUMBERING, 1):
        conn.x(
            "insert into BAS_COMMON_CODES "
            "(CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, ATTR1, ATTR2, USE_YN, CREATED_BY, CREATED_DT) "
            "values ('LOT채번', %s, %s, %s, %s, %s, 'Y', %s, now()) "
            "on conflict (CODE_GROUP, CODE_VALUE) do update set "
            "CODE_NAME = excluded.CODE_NAME, SORT_ORDER = excluded.SORT_ORDER, "
            "ATTR1 = excluded.ATTR1, ATTR2 = excluded.ATTR2, UPDATED_DT = now()",
            (value, name, i * 10, fmt, applies, admin_id),
        )
    return len(NUMBERING)


def seed_product_abbr() -> int:
    """도면번호 채번이 쓰는 제품군 3글자를 그룹 '제품군' 의 ATTR2 에 붙인다.

    **코드 행을 늘리지 않는다** — 공통 시드가 넣은 5행의 빈 칸을 채울 뿐이다.
    """
    n = 0
    for code, abbr in PRODUCT_ABBR.items():
        n += conn.x(
            "update BAS_COMMON_CODES set ATTR2 = %s, UPDATED_DT = now() "
            "where CODE_GROUP = '제품군' and CODE_VALUE = %s and ATTR2 is distinct from %s",
            (abbr, code, abbr),
        )
    return n


def seed_configs() -> tuple[int, int]:
    """인터페이스설정 4 · 알림기준 3. `UNIQUE(CONFIG_TYPE, CONFIG_KEY)` 로 멱등(D-34)."""
    for key, desc, program in INTERFACE_CONFIGS:
        conn.x(
            "insert into SYS_CONFIGS "
            "(CONFIG_TYPE, CONFIG_KEY, DESCRIPTION, ALERT_CONDITION, USE_YN, CREATED_DT) "
            "values ('인터페이스설정', %s, %s, %s, 'Y', now()) "
            "on conflict (CONFIG_TYPE, CONFIG_KEY) do update set "
            "DESCRIPTION = excluded.DESCRIPTION, UPDATED_DT = now()",
            (key, desc, program),
        )
    for key, cond, role, channel in ALERT_CONFIGS:
        conn.x(
            "insert into SYS_CONFIGS "
            "(CONFIG_TYPE, CONFIG_KEY, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL, "
            " USE_YN, DESCRIPTION, CREATED_DT) "
            "values ('알림기준', %s, %s, %s, %s, 'Y', %s, now()) "
            "on conflict (CONFIG_TYPE, CONFIG_KEY) do update set "
            "ALERT_CONDITION = excluded.ALERT_CONDITION, "
            "TARGET_ROLE_CODE = excluded.TARGET_ROLE_CODE, "
            "ALERT_CHANNEL = excluded.ALERT_CHANNEL, UPDATED_DT = now()",
            (key, cond, role, channel,
             "TD5 SYS_CONFIGS.ALERT_CONDITION 비고 — 임계값 수치는 정본에 없다"),
        )
    return len(INTERFACE_CONFIGS), len(ALERT_CONFIGS)


def seed_sources(admin_id: int | None) -> int:
    """수집대상 5종. `SOURCE_NAME` 에 물리 UNIQUE 가 없으므로 존재 확인 후 넣는다(G-07)."""
    for name, dtype, method, program in SOURCES:
        row = conn.q1("select SOURCE_ID from DAT_SOURCES where SOURCE_NAME = %s", (name,))
        if row:
            conn.x(
                "update DAT_SOURCES set DATA_TYPE = %s, IF_METHOD = %s, INTERFACE_CODE = %s, "
                "UPDATED_DT = now() where SOURCE_ID = %s",
                (dtype, method, program, row["source_id"]),
            )
            continue
        conn.x(
            "insert into DAT_SOURCES "
            "(SOURCE_NAME, DATA_TYPE, IF_METHOD, INTERFACE_CODE, USE_YN, CREATED_BY, CREATED_DT) "
            "values (%s, %s, %s, %s, 'Y', %s, now())",
            (name, dtype, method, program, admin_id),
        )
    return len(SOURCES)


def seed_jobs(admin_id: int | None) -> int:
    """수집대상 1건당 수집 작업 1건. `JOB_NAME` 에 UNIQUE 가 없으므로 존재 확인 후 넣는다."""
    n = 0
    for name, dtype, _method, _program in SOURCES:
        src = conn.q1("select SOURCE_ID from DAT_SOURCES where SOURCE_NAME = %s", (name,))
        if not src:
            continue
        job_name = f"{name} 수집"
        target = JOB_TARGET[dtype]
        row = conn.q1("select JOB_ID from DAT_INTEGRATION_JOBS where JOB_NAME = %s", (job_name,))
        if row:
            conn.x(
                "update DAT_INTEGRATION_JOBS set SOURCE_ID = %s, JOB_TYPE = '수집', "
                "TARGET_STORE = %s, UPDATED_DT = now() where JOB_ID = %s",
                (src["source_id"], target, row["job_id"]),
            )
        else:
            conn.x(
                "insert into DAT_INTEGRATION_JOBS "
                "(JOB_NAME, SOURCE_ID, JOB_TYPE, TARGET_STORE, USE_YN, CREATED_BY, CREATED_DT) "
                "values (%s, %s, '수집', %s, 'Y', %s, now())",
                (job_name, src["source_id"], target, admin_id),
            )
        n += 1
    return n


def counts() -> dict[str, int]:
    """검증용 실측 — 두 번 돌려 diff 0 을 확인할 때 쓴다(G-07)."""
    tables = ("BAS_COMMON_CODES", "SYS_CONFIGS", "DAT_SOURCES", "DAT_INTEGRATION_JOBS")
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in tables}


def main() -> int:
    if conn.table_count() != 68:
        print(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-schema`", file=sys.stderr)
        return 1
    a = clock.anchor()          # 없으면 여기서 터진다. date.today() 로 대체하지 않는다(§10-3).
    admin = _admin_id()
    if admin is None:
        print("공통 시드가 아직이다 — 먼저 `make db-seed`(db/seed.py)", file=sys.stderr)
        return 1

    num = seed_numbering(admin)
    abbr = seed_product_abbr()
    ifc, alert = seed_configs()
    src = seed_sources(admin)
    job = seed_jobs(admin)
    c = counts()

    print(f"시간 앵커          {a.isoformat(sep=' ')}   (date.today() 금지 — §10-3)")
    print(f"채번 규칙          {num} 건  (BAS_COMMON_CODES 그룹 'LOT채번' — progress-dev1.md §1 공표)")
    print(f"제품군 약어        {abbr} 행 갱신  (도면번호 채번용 ATTR2. 코드 행은 늘리지 않는다)")
    print(f"인터페이스설정      {ifc} 건  (EIF 4종 — TD4-046~049. 접속 주소는 정본에 없어 비움)")
    print(f"알림기준           {alert} 건  (설비 이상·납기 경고·품질 이상. 임계값은 정본에 없어 비움)")
    print(f"수집대상           {src} 건  (ERP·PLC·현장POP·CAD·외부문서. 수집 주기 미기재 — D-06)")
    print(f"통합작업           {job} 건  (수집대상당 1건. Cron·변환규칙은 정본에 없어 비움)")
    print()
    print("표 실측:  " + "  ".join(f"{k} {v}" for k, v in c.items()))
    print()
    print(f"시드하지 않은 표 {len(NOT_SEEDED)}종 — 0건이 정답이고 화면은 미수집/미확정을 렌더한다:")
    for table, why in NOT_SEEDED:
        print(f"  · {table:<22} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
