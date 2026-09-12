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

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.util import clock, codes              # noqa: E402
from kyungdong.cad.archive import PRODUCT_ALIASES        # noqa: E402  (제품군 별칭 정본)

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
    ("INV_MATERIAL_LOTS.MATERIAL · EST_BOM_ITEMS.MATERIAL (값)",
     "재질 **코드 그룹**은 개발3 이 가정 답변 ②(D-150)에서 채웠다 — 도면 표제란 실측 14종을 "
     "8종으로 통합한 것이고 `ATTR1` 에 가정 표시가 붙어 있다. 그러나 그것은 **값의 검증표**이고 "
     "합성 사슬의 자재LOT·BOM 항목에 어느 재질이 들어갔는지는 정본에도 가정 답변에도 없다 → "
     "MATERIAL 은 NULL 로 둔다. 그래서 G-09 정합성 'BOM 자재 ↔ 자재LOT 재질' 분모는 여전히 0 이다"),
    ("BAS_COMMON_CODES 그룹 '보관위치'·'불량유형'·'클레임유형'·'원가대상'",
     "창고 레이아웃·불량 분류·클레임 분류·원가대상이 정본에 없다(D-47). 합성 사슬에도 필요하지 않아 "
     "비운 채로 둔다 → INV_STOCKS.LOCATION_CODE·PRC_PERFORMANCES.DEFECT_TYPE 은 NULL 이다"),
    ("EST_QUOTATIONS · EST_QUOTATION_ITEMS",
     "견적 총액 22건은 실측했지만 견적 적재는 G-14~G-19 범위다 — 이번 회전의 범위는 G-08 뿐이라 "
     "넣지 않는다. EST_PROJECTS.ORDER_AMOUNT 도 비운다(견적 문서와 프로젝트의 1:1 근거가 없다)"),
    ("EST_CAD_OBJECTS · EST_CAD_FEATURES",
     "도면 Parsing·표제란 OCR 이 미구성이다(D-05). 확정 객체 0건인데 Feature 가 있으면 그것이 "
     "합성이라고 `tools/check_ingest.py` ⑤ 가 판정한다 — 우회하지 않는다"),
    ("INV_MATERIAL_HISTORY",
     "**판정: 런타임 누적표다** — 입고·투입·반출·반입·출하 시점에 쌓인다. 시드 대상 아님 "
     "(db-schema §7.1 개발1 몫 · D-102)"),
    ("INV_SUPPLIER_QUALITY",
     "**판정: 입고·검사 누적 집계다** — 마스터가 아니다. /inv/008 '평가산출' 이 산출한다 "
     "(db-schema §7.1 개발1 몫 · D-103)"),
    ("BAS_QUALITY_STANDARDS 의 **기준값**(SPEC_MIN·SPEC_MAX·STANDARD_SPEC)",
     "TD3-030 체크: '현행 검사 기준서는 문서로만 존재하므로 초기 기준 데이터는 도입기업이 "
     "제공해야 한다' → **기준 수치는 지어내지 않는다.** 제품군×검사항목 골격만 합성으로 넣고 "
     "(D-131) 수치 칸은 비운다. /bas/030 화면 입력"),
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


# ═════════════════════════════════════════════════════════════════════════
# 5. G-08 디지털 스레드 — **실측 · 가설 · 합성을 갈라서 넣는다** (D-131 · D-139)
#
#   사용자 지시로 디지털 스레드를 채운다. 규칙은 "합성으로 재지 마라" 가 아니라
#   **"합성임을 지울 수 없게 표시하라"** 다 (goal.md §2.3 · §10-1).
#
#   | 층 | 무엇 | 표시 |
#   |---|---|---|
#   | **실측**  | 프로젝트(GD코드·제품군·고객사 폴더) · 도면 파일 341건 | 표시 없음 — 지어내지 않았다 |
#   | **가설**  | 품목 코드 179종 (견적 품목명세 462행/19문서) | `가설 (D-131)` |
#   | **확정**  | 고객사 코드 19종 (사용자 확정 2026-09-12)   | `확정 (D-139)` + 역할 + 확신도 |
#   | **합성**  | BOM · 자재LOT · 입고 · 재고 · 품질기준 골격 · 공급처 | `합성 (D-131)` |
#
#   **고객사가 확정됐다고 G-08 수치가 실측이 되는 것이 아니다.** 사슬의 대부분이 합성이고
#   게이트 판정 줄·화면 배지가 그 사실을 함께 나른다.
#
#   ⚠ **표시를 담을 칸이 없는 표가 있다.** `NO_REMARK_COLUMN` 에 적었고 실행 출력이 그대로 찍는다.
#     컬럼을 추가하지 않는다(G-02 762 고정).
# ═════════════════════════════════════════════════════════════════════════
MARK_SYNTH = "합성 (D-131)"
MARK_HYPO = "가설 (D-131)"
MARK_CONF = "확정 (D-139)"
SYNTH_NOTE = "합성 데이터 기준 (D-131)"

THREAD_JSON = ROOT / "docs" / "cad" / "thread_projects.json"
QUOTE_ITEMS_JSON = ROOT / "docs" / "cad" / "quote_items.json"
CUSTOMER_JSON = ROOT / "docs" / "cad" / "customer_candidates.json"

# 합성 행에 표시를 남길 **비고/REMARK/SOURCE_DESC 계열 컬럼이 없는 표**.
# 대신 ① 게이트 판정 줄 ② 화면 배지 ③ `SYS_CONFIGS('시스템설정','SYNTHETIC_THREAD')` 선언이 나른다.
NO_REMARK_COLUMN: dict[str, str] = {
    "EST_BOM_HEADERS": "GEN_METHOD·BOM_VERSION·CYCLE_CHECK_RESULT 는 어휘 칸이다 — "
                       "표시를 넣으면 어휘가 깨진다. 하위 EST_BOM_ROUTINGS.REMARK 가 대신 진다",
    "INV_RECEIPTS": "MTC_NO(재질성적서)·INSPECT_RESULT 는 값 칸이다",
    "INV_STOCKS": "전 컬럼이 수량·위치·일시다",
    "PRC_WORK_ORDERS": "전 컬럼이 수량·일시·어휘다",
    "PRC_PERFORMANCES": "DEFECT_TYPE 은 '불량유형' 코드성 FK 라 문장을 넣을 수 없다",
    "PRC_PROCESS_HISTORIES": "OUTSOURCE_STEP·HIST_STATUS 는 어휘 칸이다",
    "SHP_LOT_TRACES": "MAPPING_OK_YN 은 Y/N 한 글자다",
    "SHP_INSPECTIONS": "REJECT_REASON 은 **불합격 사유** 칸이라 합격 행에 쓰면 거짓이 된다",
    "SHP_SHIPMENTS": "전 컬럼이 일시·어휘·FK 다",
}

# 의도적 단절 — **전부 완벽하게 이으면 100% 가 나오고 그건 검사기를 시험하지 못한다.**
# 제품LOT 전역 순번(프로젝트번호·BOM번호 오름차순, 0부터)에 고정으로 박는다. 무작위가 아니다.
BREAKS: dict[int, str] = {
    3:  "BOM 미연결 — SHP_LOT_TRACES.BOM_ID 를 비운다 (사슬 3단계 끊김)",
    9:  "도면 미연결 BOM — EST_BOM_HEADERS.DRAWING_ID 를 비운다 (사슬 2단계 끊김)",
    16: "자재LOT 미투입 — SHP_LOT_TRACES.MATERIAL_LOT_ID 를 비운다 (사슬 4단계 끊김)",
    24: "공정실적 누락 — PRC_PERFORMANCES 를 만들지 않는다 (사슬 6단계 끊김)",
    33: "검사·출하 누락 — SHP_INSPECTIONS·SHP_SHIPMENTS 를 만들지 않는다 (사슬 8·9단계 끊김)",
}

# 제품군 코드 ↔ 폴더명 표기. 공통 시드의 '제품군' 5종이 정본이고 여기서 늘리지 않는다.
PRODUCT_GROUP_CODE: dict[str, str] = {
    "반응기": "PG10", "교반기": "PG20", "진공건조기": "PG30",
    "누체필터": "PG40", "저장탱크": "PG50",
}

# BOM 공정구조가 펴는 제조 공정 — 사업계획서 1.3 의 10공정 중 제조 7공정.
# `db/seed_dev2.py` 의 `MFG_PROCESSES`·`OUTSOURCED` 와 **같은 정본**이다(개발2 가 실행 시 대조한다).
ROUTING_PROCESSES = ("P30", "P40", "P50", "P60", "P70", "P80", "P90")
ROUTING_OUTSOURCED = ("P30", "P60")
PROCESS_SEQ = {code: i for i, code in enumerate(
    ("P10", "P20", "P30", "P40", "P50", "P60", "P70", "P80", "P90", "P95"), start=1)}

# 출하검사 3종 — 사업계획서 1.3. 코드는 공통 시드의 '검사구분' 3종이다.
INSPECT_STANDARDS = (("IT10", "수압시험", "bar"), ("IT20", "기밀시험", "bar"),
                     ("IT30", "진공시험", "mmHg"))

# 공급처 — **실존 상호를 지어내지 않는다**(D-101). 합성임을 상호 자체에 박는다.
SUPPLIERS = (("SUP-001", "합성 공급처 01 (D-131)", "ST10"),
             ("SUP-002", "합성 공급처 02 (D-131)", "ST20"),
             ("SUP-003", "합성 공급처 03 (D-131)", "ST30"))

BOMS_PER_PROJECT = 4      # 견적 실측 근거: 한 견적 파일에 갑지가 2~5장이다(multi_quote_files 8건)
BOM_SUB_ITEMS = 5         # BOM 레벨2 자재 수 — 합성이다
_BOM_IN_SPEC = re.compile(r"투입 BOM (\S+)")
CUSTOMER_ROLES = {"발주처 후보": "발주처", "수요처(엔드유저) 후보": "수요처"}
CONFIDENCE_ORDER = {"높음": 1, "중간": 2, "낮음": 3}


def _read_json(path: Path) -> dict:
    """실측 산출물을 읽는다. **없으면 터진다** — 조용히 빈 목록으로 넘어가지 않는다."""
    if not path.exists():
        raise RuntimeError(
            f"실측 산출물이 없다: {path.relative_to(ROOT)} — "
            "원본 아카이브에서 다시 뽑아야 한다(지어내지 않는다)")
    return json.loads(path.read_text(encoding="utf-8"))


def customers() -> list[tuple[str, str, str, str]]:
    """확정 고객사 19종 (code, name, 역할, 확신도) — 사용자 확정 2026-09-12 (D-139).

    `분류` 가 **발주처 후보 · 수요처(엔드유저) 후보** 인 것만 쓴다.
    협력사·공급사(VEN) · 관계사(REL) · 도입기업 본인(SELF) · 사람이름 · 제품명 · 미분류는 **고객사가 아니다.**
    """
    out: list[tuple[str, str, str, str]] = []
    for c in _read_json(CUSTOMER_JSON)["후보"]:
        role = CUSTOMER_ROLES.get(c["분류"])
        if role is None:
            continue
        out.append((c["제안코드"], c["정규화이름"], role, c["확신도"]))
    out.sort(key=lambda r: (CONFIDENCE_ORDER.get(r[3], 9), r[0]))
    return out


def quote_items() -> tuple[list[dict], dict]:
    """견적서 품목명세에서 뽑은 품목명 (가설 D-131). **이 목록 밖의 품목명을 만들지 않는다.**"""
    data = _read_json(QUOTE_ITEMS_JSON)
    return data["items"], data["실측"]


def thread_projects() -> dict:
    """G-08 이 쓰는 실측 프로젝트·도면. 선정 규칙은 JSON `_meta.선정규칙` 에 적혀 있다."""
    return _read_json(THREAD_JSON)


def _base_dt(yymm: str) -> datetime:
    """수주 확정 시각 — **프로젝트(수주)번호의 YYMM 이 곧 기준일이다**(실측).

    `date.today()` 도 `datetime.now()` 도 쓰지 않는다(§10-3). 앵커가 바뀌어도 이 값은 안 움직인다.
    """
    return datetime(2000 + int(yymm[:2]), int(yymm[2:]), 10, 9, 0)


# ── 코드 마스터 (가설·확정) ───────────────────────────────────────────────
def seed_customers(admin_id: int | None) -> int:
    """고객사 19종 → `BAS_COMMON_CODES('고객사')`. ATTR1 에 역할 + 확정 표시, ATTR2 에 확신도."""
    rows = customers()
    for i, (code, name, role, conf) in enumerate(rows, 1):
        conn.x(
            "insert into BAS_COMMON_CODES "
            "(CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, ATTR1, ATTR2, USE_YN, CREATED_BY, CREATED_DT) "
            "values ('고객사', %s, %s, %s, %s, %s, 'Y', %s, now()) "
            "on conflict (CODE_GROUP, CODE_VALUE) do update set "
            "CODE_NAME = excluded.CODE_NAME, SORT_ORDER = excluded.SORT_ORDER, "
            "ATTR1 = excluded.ATTR1, ATTR2 = excluded.ATTR2, UPDATED_DT = now()",
            (code, name, i * 10,
             f"{role} · {MARK_CONF} — 사용자 확정 2026-09-12 · 관측 기반(견적·발주 수신처·폴더명)",
             conf, admin_id),
        )
    return len(rows)


def seed_items(admin_id: int | None) -> tuple[int, dict]:
    """품목 179종 → `BAS_COMMON_CODES('품목')`. **견적서에 있는 이름만** 쓴다(가설 D-131)."""
    items, measured = quote_items()
    for i, it in enumerate(items, 1):
        conn.x(
            "insert into BAS_COMMON_CODES "
            "(CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, ATTR1, ATTR2, USE_YN, CREATED_BY, CREATED_DT) "
            "values ('품목', %s, %s, %s, %s, %s, 'Y', %s, now()) "
            "on conflict (CODE_GROUP, CODE_VALUE) do update set "
            "CODE_NAME = excluded.CODE_NAME, SORT_ORDER = excluded.SORT_ORDER, "
            "ATTR1 = excluded.ATTR1, ATTR2 = excluded.ATTR2, UPDATED_DT = now()",
            (f"ITEM-{i:03d}", it["name"][:200], i * 10,
             f"{MARK_HYPO} — 과거 견적서 품목명세 실측(D-118-b). 도입기업 코드체계 미확정",
             f"견적 {it['rows']}행 · 문서 {len(it['files'])}건", admin_id),
        )
    return len(items), measured


def seed_synthetic_flag() -> str:
    """합성 선언 1행 — 화면 배지와 게이트 판정 줄이 **이 한 곳**을 읽는다."""
    desc = (f"{SYNTH_NOTE} — BOM·자재LOT·입고·재고·작업지시·공정실적·LOT추적·검사·출하는 "
            "원천이 없는 합성이다. 프로젝트·도면은 실측, 고객사는 확정(D-139), 품목은 가설(D-131)")
    conn.x(
        "insert into SYS_CONFIGS "
        "(CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, USE_YN, DESCRIPTION, CREATED_DT) "
        "values ('시스템설정', 'SYNTHETIC_THREAD', 'D-131', 'Y', %s, now()) "
        "on conflict (CONFIG_TYPE, CONFIG_KEY) do update set "
        "CONFIG_VALUE = excluded.CONFIG_VALUE, DESCRIPTION = excluded.DESCRIPTION, "
        "UPDATED_DT = now()",
        (desc,),
    )
    return desc


# ── 실측: 프로젝트 · 도면 ────────────────────────────────────────────────
def seed_projects(admin_id: int | None) -> dict[str, int]:
    """수주 프로젝트 — **GD 실측 코드만.** 고객사·제품군을 못 이으면 JSON 이 이미 뺐다."""
    out: dict[str, int] = {}
    for p in thread_projects()["projects"]:
        pg = PRODUCT_GROUP_CODE[p["product_group"]]
        if not codes.validate_code("제품군", pg):
            raise RuntimeError(f"제품군 코드 {pg} 가 BAS_COMMON_CODES 에 없다 (D-32)")
        if not codes.validate_code("고객사", p["customer_code"]):
            raise RuntimeError(f"고객사 코드 {p['customer_code']} 가 없다 — 먼저 seed_customers (D-32)")
        base = _base_dt(p["yymm"])
        conn.x(
            "insert into EST_PROJECTS "
            "(PROJECT_NO, CUSTOMER_CODE, PRODUCT_GROUP, PROJECT_NAME, RFQ_DT, ORDER_CONFIRM_DT, "
            " DUE_DT, ORDER_AMOUNT, PROJECT_STATUS, CREATED_BY, CREATED_DT) "
            "values (%s,%s,%s,%s,%s,%s,%s, null, '완료', %s, now()) "
            "on conflict (PROJECT_NO) do update set "
            "CUSTOMER_CODE = excluded.CUSTOMER_CODE, PRODUCT_GROUP = excluded.PRODUCT_GROUP, "
            "PROJECT_NAME = excluded.PROJECT_NAME, RFQ_DT = excluded.RFQ_DT, "
            "ORDER_CONFIRM_DT = excluded.ORDER_CONFIRM_DT, DUE_DT = excluded.DUE_DT, "
            "PROJECT_STATUS = excluded.PROJECT_STATUS, UPDATED_DT = now()",
            (p["project_no"], p["customer_code"], pg,
             (p["label"] or p["product_group"])[:200],
             base - timedelta(days=20), base,
             (base + timedelta(hours=1200)).date(), admin_id),
        )
        row = conn.q1("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = %s", (p["project_no"],))
        out[p["project_no"]] = int(row["project_id"])
    return out


def seed_drawings(admin_id: int | None, pids: dict[str, int]) -> dict[str, list[int]]:
    """도면 341건 — **파일·경로·크기·최종수정일은 실측**이다. 도면번호만 개발1 채번 형식으로 붙인다.

    (표제란 도면번호는 434/1,136건에만 있다 — 없는 것을 지어내지 않고 채번 규칙을 쓴다.)
    `EST_CAD_DRAWINGS.DRAWING_NO` 에 물리 UNIQUE 가 없으므로 **FILE_PATH 로 존재 확인**한다(G-07).
    """
    seq: dict[str, int] = {}
    out: dict[str, list[int]] = {}
    for p in thread_projects()["projects"]:
        pg = PRODUCT_GROUP_CODE[p["product_group"]]
        abbr = PRODUCT_ABBR[pg]
        ids: list[int] = []
        for d in p["drawings"]:
            seq[abbr] = seq.get(abbr, 0) + 1
            no = f"DWG-{abbr}-{seq[abbr]:04d}"
            mtime = datetime.fromisoformat(d["mtime"]) if d["mtime"] else None
            row = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS where FILE_PATH = %s", (d["rel"],))
            if row:
                conn.x(
                    "update EST_CAD_DRAWINGS set DRAWING_NO = %s, PROJECT_ID = %s, FILE_TYPE = %s, "
                    "FILE_SIZE = %s, FILE_MTIME = %s, ANALYSIS_STATUS = '대기', DUPLICATE_YN = 'N', "
                    "UPDATED_DT = now() where DRAWING_ID = %s",
                    (no, pids[p["project_no"]], d["ext"].upper(), d["size"], mtime,
                     int(row["drawing_id"])),
                )
                ids.append(int(row["drawing_id"]))
                continue
            conn.x(
                "insert into EST_CAD_DRAWINGS "
                "(DRAWING_NO, PROJECT_ID, FILE_TYPE, FILE_PATH, FILE_SIZE, REVISION, FILE_MTIME, "
                " ANALYSIS_STATUS, DUPLICATE_YN, CREATED_BY, CREATED_DT) "
                "values (%s,%s,%s,%s,%s, null, %s, '대기', 'N', %s, now())",
                (no, pids[p["project_no"]], d["ext"].upper(), d["rel"], d["size"], mtime, admin_id),
            )
            row = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS where FILE_PATH = %s", (d["rel"],))
            ids.append(int(row["drawing_id"]))
        out[p["project_no"]] = ids
    return out


# ── 합성: 품질기준 골격 · 공급처 ─────────────────────────────────────────
def seed_quality_standards(admin_id: int | None, apply_from: date) -> int:
    """제품군 5 × 검사 3 = 15행. **기준 수치(SPEC_MIN·MAX·적용규격)는 비운다**(TD3-030)."""
    rule = (f"{MARK_SYNTH} — 제품군×검사항목 골격만 넣었다. 기준 수치는 도입기업 제공 대기"
            "(TD3-030)라 비어 있고, 기준값 없이 판정만 기록한다")
    n = 0
    for pg in sorted(PRODUCT_GROUP_CODE.values()):
        for itype, item, uom in INSPECT_STANDARDS:
            conn.x(
                "insert into BAS_QUALITY_STANDARDS "
                "(QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, INSPECT_ITEM, STANDARD_SPEC, "
                " SPEC_MIN, SPEC_MAX, UOM, JUDGE_RULE, USE_YN, APPLY_FROM, CREATED_BY, CREATED_DT) "
                "values (%s,%s,%s,%s, null, null, null, %s, %s, 'Y', %s, %s, now()) "
                "on conflict (QSTD_CODE) do update set "
                "PRODUCT_GROUP = excluded.PRODUCT_GROUP, INSPECT_TYPE = excluded.INSPECT_TYPE, "
                "INSPECT_ITEM = excluded.INSPECT_ITEM, UOM = excluded.UOM, "
                "JUDGE_RULE = excluded.JUDGE_RULE, APPLY_FROM = excluded.APPLY_FROM, "
                "UPDATED_DT = now()",
                (f"QS-{pg}-{itype}", pg, itype, item, uom, rule, apply_from, admin_id),
            )
            n += 1
    return n


def seed_suppliers() -> int:
    """공급처 3종. **실존 상호를 지어내지 않는다**(D-101) — 상호 자체에 합성임을 박는다."""
    for code, name, stype in SUPPLIERS:
        conn.x(
            "insert into INV_SUPPLIERS "
            "(SUPPLIER_CODE, SUPPLIER_NAME, SUPPLY_TYPE, CONTACT_NAME, CONTACT_PHONE, MAIN_ITEMS, "
            " GRADE, RISK_YN, USE_YN, CREATED_DT) "
            "values (%s,%s,%s, null, null, %s, null, 'N', 'Y', now()) "
            "on conflict (SUPPLIER_CODE) do update set "
            "SUPPLIER_NAME = excluded.SUPPLIER_NAME, SUPPLY_TYPE = excluded.SUPPLY_TYPE, "
            "MAIN_ITEMS = excluded.MAIN_ITEMS, UPDATED_DT = now()",
            (code, name, stype,
             f"{MARK_SYNTH} — 실제 공급품목 목록이 정본에 없다. 담당자·연락처는 개인정보라 비운다(G-29)"),
        )
    return len(SUPPLIERS)


# ── 합성: BOM · 공정구조 · 자재LOT · 입고 · 재고 ─────────────────────────
def _representative_item(product_group: str, items: list[dict], fallback: int) -> int:
    """BOM 레벨1 대표 품목 — 제품군 별칭이 이름에 들어간 **견적 품목**을 고른다.

    **품목명을 지어내지 않는다.** 별칭에 걸리는 것이 없으면(진공건조기·누체필터가 그렇다)
    순환 배분으로 떨어뜨리고 그 사실을 보고한다.
    """
    for alias in PRODUCT_ALIASES.get(product_group, ()):  # 정본 별칭표 (cad/archive.py)
        up = alias.upper()
        for i, it in enumerate(items):
            if up in it["name"].upper():
                return i
    return fallback % len(items)


def seed_boms(admin_id: int | None, pids: dict[str, int],
              drawings: dict[str, list[int]]) -> list[dict[str, Any]]:
    """BOM 헤더·자재구성·공정구조 — **전부 합성이다.** 도면 객체인식이 미구성이라 원천이 없다(D-05).

    제품LOT 전역 순번은 **(프로젝트번호, BOM번호) 오름차순**이고 `BREAKS` 가 그 순번에 박힌다.
    """
    items, _ = quote_items()
    spec = (f"{MARK_SYNTH} — BOM 구성은 견적 품목명을 배분한 것이다. "
            "실제 소요 관계·규격의 원천이 없다(D-05)")
    routing_remark = (f"{MARK_SYNTH} — 사업계획서 1.3 의 10공정 중 제조 7공정을 폈다. "
                      "표준 공수는 정본에 없어 비운다(D-203)")
    plan: list[dict[str, Any]] = []
    for p in thread_projects()["projects"]:
        n_bom = min(BOMS_PER_PROJECT, len(drawings[p["project_no"]]))
        for k in range(1, n_bom + 1):
            plan.append({"project_no": p["project_no"], "bom_no": f"BOM-{p['project_no']}-{k:02d}",
                         "project_id": pids[p["project_no"]], "product_group": p["product_group"],
                         "yymm": p["yymm"], "drawing_id": drawings[p["project_no"]][k - 1]})
    plan.sort(key=lambda r: (r["project_no"], r["bom_no"]))

    for idx, b in enumerate(plan):
        b["index"] = idx
        b["break"] = BREAKS.get(idx)
        drawing_id = None if idx in BREAKS and "도면 미연결" in BREAKS[idx] else b["drawing_id"]
        conn.x(
            "insert into EST_BOM_HEADERS "
            "(BOM_NO, PROJECT_ID, DRAWING_ID, GEN_METHOD, BOM_VERSION, ACCURACY_RATE, "
            " CONFIRM_YN, CYCLE_CHECK_RESULT, CREATED_BY, CREATED_DT) "
            "values (%s,%s,%s,'수동','v1.0', null, 'N', '정상', %s, now()) "
            "on conflict (BOM_NO) do update set PROJECT_ID = excluded.PROJECT_ID, "
            "DRAWING_ID = excluded.DRAWING_ID, GEN_METHOD = excluded.GEN_METHOD, "
            "BOM_VERSION = excluded.BOM_VERSION, CONFIRM_YN = excluded.CONFIRM_YN, "
            "CYCLE_CHECK_RESULT = excluded.CYCLE_CHECK_RESULT, UPDATED_DT = now()",
            (b["bom_no"], b["project_id"], drawing_id, admin_id),
        )
        bom_id = int(conn.q1("select BOM_ID from EST_BOM_HEADERS where BOM_NO = %s",
                             (b["bom_no"],))["bom_id"])
        b["bom_id"] = bom_id

        # 레벨1 대표 품목 + 레벨2 자재 — **품목 코드는 견적 실측 목록에서만 고른다**
        top = _representative_item(b["product_group"], items, idx)
        chosen = [top]
        for i in range(BOM_SUB_ITEMS):
            j = (idx * 7 + i * 13 + 1) % len(items)
            while j in chosen:
                j = (j + 1) % len(items)
            chosen.append(j)
        parent_id = None
        for level, j in enumerate(chosen):
            item_code = f"ITEM-{j + 1:03d}"
            if not codes.validate_code("품목", item_code):
                raise RuntimeError(f"품목 코드 {item_code} 가 없다 — 먼저 seed_items (D-32)")
            row = conn.q1(
                "select BOM_ITEM_ID from EST_BOM_ITEMS where BOM_ID = %s and ITEM_CODE = %s",
                (bom_id, item_code))
            if row:
                item_id = int(row["bom_item_id"])
                conn.x("update EST_BOM_ITEMS set PARENT_ITEM_ID = %s, BOM_LEVEL = %s, "
                       "SPEC_TEXT = %s, UPDATED_DT = now() where BOM_ITEM_ID = %s",
                       (parent_id if level else None, 1 if level == 0 else 2, spec, item_id))
            else:
                conn.x(
                    "insert into EST_BOM_ITEMS "
                    "(BOM_ID, PARENT_ITEM_ID, BOM_LEVEL, ITEM_CODE, MATERIAL, SPEC_TEXT, "
                    " REQUIRE_QTY, UOM, CREATED_DT) "
                    "values (%s,%s,%s,%s, null, %s, 1, 'EA', now())",
                    (bom_id, parent_id if level else None, 1 if level == 0 else 2, item_code, spec))
                item_id = int(conn.q1(
                    "select BOM_ITEM_ID from EST_BOM_ITEMS where BOM_ID = %s and ITEM_CODE = %s",
                    (bom_id, item_code))["bom_item_id"])
            if level == 0:
                parent_id = item_id
                b["top_item"] = item_code
            elif level == 1:
                b["material_item"] = item_code

        for code in ROUTING_PROCESSES:
            row = conn.q1("select ROUTING_ID from EST_BOM_ROUTINGS where BOM_ID = %s "
                          "and PROCESS_SEQ = %s", (bom_id, PROCESS_SEQ[code]))
            params = (code, "Y" if code in ROUTING_OUTSOURCED else "N", routing_remark)
            if row:
                conn.x("update EST_BOM_ROUTINGS set PROCESS_CODE = %s, OUTSOURCE_YN = %s, "
                       "REMARK = %s, UPDATED_DT = now() where ROUTING_ID = %s",
                       (*params, int(row["routing_id"])))
            else:
                conn.x(
                    "insert into EST_BOM_ROUTINGS "
                    "(BOM_ID, PROCESS_CODE, PROCESS_SEQ, OUTSOURCE_YN, STD_MANHOUR, WSTD_ID, "
                    " REMARK, CREATED_DT) values (%s,%s,%s,%s, null, null, %s, now())",
                    (bom_id, code, PROCESS_SEQ[code], "Y" if code in ROUTING_OUTSOURCED else "N",
                     routing_remark))
    return plan


def seed_material_flow(admin_id: int | None, plan: list[dict[str, Any]]) -> dict[str, int]:
    """자재LOT · 입고 · 재고 — **합성이다.** BOM 1건당 투입 자재 LOT 1건.

    `INV_MATERIAL_LOTS` 에는 BOM_ID 컬럼이 없다(컬럼을 추가하지 않는다 — G-02 762 고정).
    그래서 **규격 칸(SPEC_TEXT)에 합성 표시와 함께 투입 BOM 번호를 남기고** 개발2가 그것으로 잇는다.
    """
    made = {"lots": 0, "receipts": 0, "stocks": 0}
    supplier = conn.q1("select SUPPLIER_ID from INV_SUPPLIERS where SUPPLIER_CODE = 'SUP-001'")
    if supplier is None:
        return made
    by_date: dict[str, int] = {}
    by_year: dict[int, int] = {}
    for b in plan:
        base = _base_dt(b["yymm"])
        receipt_dt = base + timedelta(hours=24)
        day = receipt_dt.strftime("%y%m%d")
        by_date[day] = by_date.get(day, 0) + 1
        lot_no = f"LOT-{day}-{by_date[day]:02d}"
        by_year[receipt_dt.year] = by_year.get(receipt_dt.year, 0) + 1
        receipt_no = f"RC-{receipt_dt.year}-{by_year[receipt_dt.year]:04d}"
        spec = (f"{MARK_SYNTH} · 투입 BOM {b['bom_no']} — 두께·길이·중량·재질은 "
                "도면 Parsing 원천이 없어 비운다(D-05)")
        conn.x(
            "insert into INV_MATERIAL_LOTS "
            "(LOT_NO, ITEM_CODE, MATERIAL, THICKNESS_MM, LENGTH_MM, WEIGHT_KG, SPEC_TEXT, "
            " CURRENT_QTY, LOT_STATUS, CREATED_DT) "
            "values (%s,%s, null, null, null, null, %s, 1, '사용중', now()) "
            "on conflict (LOT_NO) do update set ITEM_CODE = excluded.ITEM_CODE, "
            "SPEC_TEXT = excluded.SPEC_TEXT, LOT_STATUS = excluded.LOT_STATUS, UPDATED_DT = now()",
            (lot_no, b["material_item"], spec),
        )
        lot_id = int(conn.q1("select LOT_ID from INV_MATERIAL_LOTS where LOT_NO = %s",
                             (lot_no,))["lot_id"])
        b["material_lot_id"] = lot_id
        b["lot_no"] = lot_no
        made["lots"] += 1

        conn.x(
            "insert into INV_RECEIPTS "
            "(RECEIPT_NO, PROJECT_ID, SUPPLIER_ID, LOT_ID, RECEIPT_DT, RECEIPT_QTY, WEIGHT_KG, "
            " MTC_NO, INSPECT_RESULT, INPUT_DEVICE, ERP_SYNC_STATUS, CREATED_BY, CREATED_DT) "
            "values (%s,%s,%s,%s,%s, 1, null, null, '합격', '스마트패드', '미전송', %s, now()) "
            "on conflict (RECEIPT_NO) do update set PROJECT_ID = excluded.PROJECT_ID, "
            "SUPPLIER_ID = excluded.SUPPLIER_ID, LOT_ID = excluded.LOT_ID, "
            "RECEIPT_DT = excluded.RECEIPT_DT, UPDATED_DT = now()",
            (receipt_no, b["project_id"], int(supplier["supplier_id"]), lot_id, receipt_dt,
             admin_id),
        )
        made["receipts"] += 1

        row = conn.q1("select STOCK_ID from INV_STOCKS where LOT_ID = %s", (lot_id,))
        if row:
            conn.x("update INV_STOCKS set STOCK_QTY = 1, AVAILABLE_QTY = 1, LAST_IN_DT = %s, "
                   "UPDATED_DT = now() where STOCK_ID = %s", (receipt_dt, int(row["stock_id"])))
        else:
            conn.x(
                "insert into INV_STOCKS "
                "(LOT_ID, LOCATION_CODE, STOCK_QTY, AVAILABLE_QTY, SAFETY_QTY, LAST_IN_DT, "
                " LAST_OUT_DT, ERP_DIFF_QTY, CREATED_DT) "
                "values (%s, null, 1, 1, null, %s, null, null, now())", (lot_id, receipt_dt))
        made["stocks"] += 1
    return made


def thread_rows() -> list[dict[str, Any]]:
    """**개발2가 읽는 상류 골격.** 프로젝트 → BOM → 투입 자재LOT + 의도적 단절 위치.

    개발2가 같은 조회를 복제하지 않게 여기 한 벌만 둔다(§10-16).
    전역 순번은 (프로젝트번호, BOM번호) 오름차순이고 `BREAKS` 가 그 순번에 박힌다.
    """
    rows = conn.q(
        "select b.BOM_ID, b.BOM_NO, b.PROJECT_ID, b.DRAWING_ID, p.PROJECT_NO, p.PRODUCT_GROUP "
        "from EST_BOM_HEADERS b join EST_PROJECTS p on p.PROJECT_ID = b.PROJECT_ID "
        "where b.BOM_NO like 'BOM-%'")
    lots: dict[str, int] = {}
    for m in conn.q("select LOT_ID, SPEC_TEXT from INV_MATERIAL_LOTS where SPEC_TEXT is not null"):
        hit = _BOM_IN_SPEC.search(m["spec_text"])
        if hit:
            lots[hit.group(1)] = int(m["lot_id"])
    top: dict[int, str] = {}
    for r in conn.q("select BOM_ID, ITEM_CODE from EST_BOM_ITEMS where BOM_LEVEL = 1"):
        top[int(r["bom_id"])] = r["item_code"]
    out = []
    for r in sorted(rows, key=lambda r: (r["project_no"], r["bom_no"])):
        out.append({
            "bom_id": int(r["bom_id"]), "bom_no": r["bom_no"],
            "project_id": int(r["project_id"]), "project_no": r["project_no"],
            "drawing_id": None if r["drawing_id"] is None else int(r["drawing_id"]),
            "material_lot_id": lots.get(r["bom_no"]),
            "item_code": top.get(int(r["bom_id"])),
        })
    for i, r in enumerate(out):
        r["index"] = i
        r["break"] = BREAKS.get(i)
    return out


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
    tables = ("BAS_COMMON_CODES", "SYS_CONFIGS", "DAT_SOURCES", "DAT_INTEGRATION_JOBS",
              "BAS_QUALITY_STANDARDS", "INV_SUPPLIERS", "EST_PROJECTS", "EST_CAD_DRAWINGS",
              "EST_BOM_HEADERS", "EST_BOM_ITEMS", "EST_BOM_ROUTINGS",
              "INV_MATERIAL_LOTS", "INV_RECEIPTS", "INV_STOCKS")
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

    # ── G-08 디지털 스레드 (D-131 · D-139) ──────────────────────────────
    synth_desc = seed_synthetic_flag()
    n_cust = seed_customers(admin)
    n_item, item_measured = seed_items(admin)
    n_qstd = seed_quality_standards(admin, a.date())
    n_sup = seed_suppliers()
    pids = seed_projects(admin)
    draw = seed_drawings(admin, pids)
    plan = seed_boms(admin, pids, draw)
    flow = seed_material_flow(admin, plan)
    pj = thread_projects()

    c = counts()

    print(f"시간 앵커          {a.isoformat(sep=' ')}   (date.today() 금지 — §10-3)")
    print(f"채번 규칙          {num} 건  (BAS_COMMON_CODES 그룹 'LOT채번' — progress-dev1.md §1 공표)")
    print(f"제품군 약어        {abbr} 행 갱신  (도면번호 채번용 ATTR2. 코드 행은 늘리지 않는다)")
    print(f"인터페이스설정      {ifc} 건  (EIF 4종 — TD4-046~049. 접속 주소는 정본에 없어 비움)")
    print(f"알림기준           {alert} 건  (설비 이상·납기 경고·품질 이상. 임계값은 정본에 없어 비움)")
    print(f"수집대상           {src} 건  (ERP·PLC·현장POP·CAD·외부문서. 수집 주기 미기재 — D-06)")
    print(f"통합작업           {job} 건  (수집대상당 1건. Cron·변환규칙은 정본에 없어 비움)")
    print()
    print("═══ G-08 디지털 스레드 — 실측 · 확정 · 가설 · 합성을 갈라서 적는다 (D-131 · D-139) ═══")
    print(f"합성 선언          SYS_CONFIGS('시스템설정','SYNTHETIC_THREAD') = D-131")
    print(f"                  {synth_desc}")
    print()
    print("【확정】사용자 확정 2026-09-12 (D-139)")
    print(f"  고객사 코드      {n_cust} 종  (발주처 {sum(1 for c2 in customers() if c2[2] == '발주처')}"
          f" · 수요처 {sum(1 for c2 in customers() if c2[2] == '수요처')})"
          f"  ATTR1=역할+확정표시 · ATTR2=확신도")
    print(f"                  확신도 높음 {sum(1 for c2 in customers() if c2[3] == '높음')}"
          f" · 중간 {sum(1 for c2 in customers() if c2[3] == '중간')}"
          f" · 낮음 {sum(1 for c2 in customers() if c2[3] == '낮음')}"
          f"  — 협력사·관계사·사람이름·제품명은 고객사가 아니라 넣지 않았다")
    print()
    print("【가설】관측 기반 · 도입기업 미확정 (D-131)")
    print(f"  품목 코드        {n_item} 종  (견적 품목명세 {item_measured['품목명세 행']}행 /"
          f" {item_measured['품목명세를 가진 문서']}문서 실측 · 고유 견적문서"
          f" {item_measured['내용 해시 중복 제거 뒤 고유 문서']}건)")
    print(f"                  집계·원가계정 {item_measured['집계·원가계정으로 제외한 행']}행"
          f"({item_measured['제외한 서로 다른 표기']}표기)은 품목이 아니라 제외했다"
          f" — 근거 docs/cad/quote_items.json")
    print()
    print("【실측】원본 아카이브 폴더 구조 — 지어내지 않았다")
    print(f"  수주 프로젝트     {len(pids)} 건  (파싱된 GD 프로젝트 {pj['실측']['파싱된 프로젝트']}건 중"
          f" 고객사·제품군·도면을 **셋 다** 이을 수 있는 것만)")
    print(f"                  제품군별 {pj['실측']['제품군별']} · 발주처별 {pj['실측']['발주처별']}")
    print(f"  CAD 도면         {sum(len(v) for v in draw.values())} 건  (내용 해시로 사본 제거)."
          f" 파일·경로·크기·최종수정일은 실측 · 도면번호는 개발1 채번 `DWG-{{제품군3}}-NNNN`")
    print()
    print("【합성】원천이 없다 (D-131)")
    print(f"  품질기준 골격     {n_qstd} 행  (제품군 5 × 검사 3). **기준 수치는 비웠다** — TD3-030")
    print(f"  공급처           {n_sup} 종  (상호 자체에 합성 표시. 실존 상호를 지어내지 않는다 — D-101)")
    print(f"  BOM 헤더         {len(plan)} 건  · 자재구성 {c['EST_BOM_ITEMS']} 행"
          f" · 공정구조 {c['EST_BOM_ROUTINGS']} 행 (REMARK 에 합성 표시)")
    print(f"  자재 LOT         {flow['lots']} 건  · 입고 {flow['receipts']} · 재고 {flow['stocks']}"
          f"  (SPEC_TEXT 에 합성 표시 + 투입 BOM 번호)")
    print()
    print(f"  의도적 단절       {len(BREAKS)} / {len(plan)} 건"
          f" = {round(len(BREAKS) / len(plan) * 100, 1)}%  — 전역 순번(프로젝트번호·BOM번호 오름차순)에 고정")
    for i, why in sorted(BREAKS.items()):
        hit = plan[i] if i < len(plan) else None
        where = f"{hit['project_no']} / {hit['bom_no']}" if hit else "**범위 밖 — 표본이 줄었다**"
        print(f"    #{i:<3} {where:<28} {why}")
    print()
    print(f"  ⚠ **합성 표시를 담을 비고/REMARK 계열 컬럼이 없는 표 {len(NO_REMARK_COLUMN)}종** — "
          "컬럼을 추가하지 않았다(G-02 762 고정):")
    for t, why in NO_REMARK_COLUMN.items():
        print(f"    · {t:<24} {why}")
    print(f"    → 표시는 ① 게이트 판정 줄 ② 화면 배지 `{SYNTH_NOTE}` "
          f"③ SYS_CONFIGS 선언이 나른다")
    print()
    print("표 실측:  " + "  ".join(f"{k} {v}" for k, v in c.items()))
    print()
    print(f"시드하지 않은 표 {len(NOT_SEEDED)}종 — 0건이 정답이고 화면은 미수집/미확정을 렌더한다:")
    for table, why in NOT_SEEDED:
        print(f"  · {table:<22} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
