#!/usr/bin/env python
"""contracts/db-schema.md 생성기 — 정본은 SF-TD5(design.json). 손으로 적으면 어긋난다.

생성만 하는 게 아니라 **개발자가 알아야 할 규약**을 실측으로 뽑는다:
  · D-32 코드성 FK — DB 가 막아주지 않으므로 애플리케이션이 검증해야 하는 컬럼 목록
  · D-33 금액 컬럼 FK 오표기
  · G-08 디지털 스레드 사슬
  · G-11 런타임 전용 표 (깨끗한 DB 에서 0건이 정상)
  · G-29 개인정보 암호화·마스킹 대상 컬럼
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design   # noqa: E402

OUT = ROOT / "contracts" / "db-schema.md"
FK_PAT = re.compile(r"FK\s*:?\s*([A-Z_]+)")

AREA_ORDER = ["기준정보관리", "사용자/시스템관리", "입고재고관리", "수주견적AI관리",
              "출하물류관리", "공정관리", "데이터관리", "AI Agent 통합관리", "KPI관리", "인터페이스"]

# G-08 디지털 스레드 — ETO 최상위 키는 프로젝트(수주)번호다 (TD3 standard_note 2 · TD5 추적성)
THREAD = [
    ("EST_PROJECTS", "PROJECT_NO", "프로젝트(수주)번호 — **ETO 최상위 추적 키**"),
    ("EST_CAD_DRAWINGS", "DRAWING_NO", "도면번호·리비전"),
    ("EST_BOM_HEADERS", "BOM_NO", "BOM"),
    ("INV_MATERIAL_LOTS", "LOT_NO", "자재 LOT"),
    ("PRC_WORK_ORDERS", "WORK_ORDER_NO", "작업지시"),
    ("PRC_PERFORMANCES", "—", "공정실적"),
    ("SHP_LOT_TRACES", "PRODUCT_LOT_NO", "제품 LOT — **제품 축의 중심 테이블**"),
    ("SHP_INSPECTIONS", "—", "출하검사(수압·기밀·진공)"),
    ("SHP_SHIPMENTS", "SHIPMENT_NO", "출하"),
]

# G-29 개인정보 (TD5 criteria: 사용자명·연락처·이메일·공급처 담당자)
PII_HINTS = ("사용자명", "성명", "이름", "연락처", "전화", "휴대", "이메일", "담당자", "주소")

# G-11 런타임 전용 — 깨끗한 DB 에서 0건이 정상. 화면은 반드시 '미수집' 문구를 렌더한다.
# **확실한 것만 여기 적는다.** 이름만 보고 짐작하면 계약이 틀린다 — 애매한 것은 RUNTIME_UNDECIDED 로 넘긴다.
RUNTIME_ONLY = (
    "SYS_ACCESS_LOGS", "DAT_DOWNLOAD_LOGS", "DAT_JOB_LOGS",
    "IF_CAD_IMPORT_LOGS", "IF_DOC_EMBED_LOGS", "IF_GATEWAY_BUFFER",
    "AGT_QUERY_LOGS", "AGT_RECOMMENDATIONS",
    "EST_ML_TRAIN_RUNS", "EST_ML_PREDICTIONS", "EST_OBJECT_REVIEWS",
)
# 이름이 이력·편차라 런타임처럼 보이지만 **시드 대상 업무 데이터일 수 있다.**
# 담당 개발자가 `progress-devN.md` 에 판정을 적을 때까지 계약은 '미정' 으로 둔다.
RUNTIME_UNDECIDED = {
    "INV_MATERIAL_HISTORY": "원자재 이력 — 입고 시드가 채우는지, 사용·출고 시 쌓이는지 (개발1)",
    "PRC_PROCESS_HISTORIES": "공정 이력 — 공정실적 시드와 함께 채우는지 (개발2)",
    "PRC_CONDITION_DEVIATIONS": "작업조건 편차 — 표준·실측 비교로 파생되는지, 시드하는지 (개발2)",
    "EST_SHAP_FACTORS": "SHAP 영향요인 — 모델 실행 산출물인지 시드 예시가 있는지 (개발3)",
    "INV_SUPPLIER_QUALITY": "공급처 품질평가 — 입고 누적 집계인지 마스터인지 (개발1)",
    "SHP_CLAIM_CAUSES": "클레임 원인 — 클레임 등록 시 쌓이는지 (개발2)",
}


def main() -> int:
    tables = design.tables()
    total_cols = sum(len(t["columns"]) for t in tables.values())

    code_fks: list[tuple[str, str, str, str]] = []   # 표, 컬럼, 타입, 대상
    real_fks: list[tuple[str, str, str]] = []
    odd_fks: list[tuple[str, str, str, str]] = []
    for tid, t in tables.items():
        for c in t["columns"]:
            ko, en, typ, pk, fk, nul, note = (x.strip() for x in c)
            if fk != "Y":
                continue
            m = FK_PAT.search(note)
            tgt = m.group(1) if m else "?"
            if typ.upper() == "BIGINT":
                real_fks.append((tid, en, tgt))
            elif tgt == "BAS_COMMON_CODES":
                code_fks.append((tid, en, typ, note))
            else:
                odd_fks.append((tid, en, typ, note))

    pii = [(tid, c[1].strip(), c[0].strip())
           for tid, t in tables.items() for c in t["columns"]
           if any(h in c[0] for h in PII_HINTS)]
    runtime = sorted(t for t in RUNTIME_ONLY if t in tables)
    missing_runtime = [t for t in RUNTIME_ONLY if t not in tables]
    undecided = sorted((t, why) for t, why in RUNTIME_UNDECIDED.items() if t in tables)
    if missing_runtime:
        raise RuntimeError(f"RUNTIME_ONLY 에 TD5 에 없는 표가 있다: {missing_runtime}")

    L: list[str] = [
        "# contracts/db-schema.md — 테이블 68 · 컬럼 762",
        "",
        "> **생성 파일이다.** 정본은 `docs/design/design.json` 의 SF-TD5 이고 `tools/gen_db_contract.py` 가 뽑는다.",
        "> 스키마 자체는 `tools/gen_schema.py` → `db/schema.sql`. **`schema.sql` 을 손으로 고치지 않는다.**",
        "> **코드와 다르면 코드가 맞다**(goal.md §4.1) → 생성기를 고치고 다시 뽑는다.",
        "",
        f"테이블 **{len(tables)}** · 컬럼 **{total_cols}** · 물리 FK 제약 **{len(real_fks)}** · "
        f"코드성 참조(FK 미생성) **{len(code_fks)}** · 오표기 **{len(odd_fks)}**",
        "",
        "## 0. 개발자가 먼저 알아야 할 것",
        "",
        "| # | 규약 |",
        "|---|---|",
        "| 1 | **모든 업무 테이블의 최상위 조회 축은 `EST_PROJECTS.PROJECT_NO`(프로젝트=수주번호)** 다. LOT 는 그 하위 식별자다 (TD3 standard_note 2). 반복 생산의 라인·배치 축으로 쿼리를 짜면 이 사업이 아니다 |",
        "| 2 | **코드성 FK 29건은 DB 가 막아주지 않는다**(D-32). 아래 §3 목록은 애플리케이션이 검증해야 한다 |",
        "| 3 | **런타임 전용 표는 깨끗한 DB 에서 0건이 정상**이다(G-11). 화면은 그때 `미수집` 문구를 렌더해야 하고, 테스트는 **0건 경로와 N건 경로를 둘 다 단언**한다(§10-4) |",
        "| 4 | **건수 카드의 `0 건` 은 정답이다** — 빈 그리드에만 문구가 필요하다(§10-14) |",
        "| 5 | 개인정보 컬럼(§6)은 **암호화 저장 + 화면 마스킹**(G-29). 시드에 실명을 넣지 않는다 |",
        "| 6 | 파라미터는 항상 바인딩한다. `db/conn.py` 의 `q`·`q1`·`x`·`tx` 만 쓰고 **DB 장애는 503**(빈 배열 금지) |",
        "| 7 | 시간 기준일은 `SYS_CONFIGS` 시간 앵커에 고정한다 — `date.today()` 금지(§10-3) |",
        "",
        "## 1. 업무영역별 테이블",
        "",
        "| 업무영역 | 표 | 컬럼 |",
        "|---|---|---|",
    ]
    by_area: dict[str, list[str]] = {}
    for tid, t in tables.items():
        by_area.setdefault(t.get("area", "?"), []).append(tid)
    for area in AREA_ORDER + [a for a in by_area if a not in AREA_ORDER]:
        if area not in by_area:
            continue
        ids = sorted(by_area[area])
        cols = sum(len(tables[i]["columns"]) for i in ids)
        L.append(f"| {area} | **{len(ids)}** — {', '.join(f'`{i}`' for i in ids)} | {cols} |")
    pref = Counter(tid.split("_")[0] for tid in tables)
    L += ["", f"접두 합계: " + " · ".join(f"`{k}` {v}" for k, v in sorted(pref.items()))
          + f" = **{sum(pref.values())}**", ""]

    L += ["## 2. 테이블 상세", "",
          "| 표 | 이름 | 컬럼 | PK | 사용 프로그램 |", "|---|---|---|---|---|"]
    for tid in sorted(tables):
        t = tables[tid]
        pkc = next((c[1].strip() for c in t["columns"] if c[3].strip() == "Y"), "—")
        progs = t.get("programs", "")
        L.append(f"| `{tid}` | {t.get('name','')} | {len(t['columns'])} | `{pkc}` | {progs} |")

    L += ["", "## 3. D-32 — 코드성 참조 (물리 FK 미생성 · 애플리케이션 검증 필수)", "",
          "TD5 비고는 `FK: BAS_COMMON_CODES` 를 가리키지만 컬럼 타입이 `VARCHAR` 다. 그 표의 PK 는",
          "`CODE_ID BIGSERIAL` 이므로 물리 FK 를 걸 수 없다. **실제 의도는",
          "`BAS_COMMON_CODES(CODE_GROUP, CODE_VALUE)` 참조**이고 그 조합에 복합 UNIQUE 가 있다(D-34).",
          "",
          "→ 저장 전에 **코드 그룹 안에 값이 있는지** 확인한다. 공용 검증 함수를 한 곳에 두고 각자 호출한다.",
          "",
          "| 표 | 컬럼 | 타입 | TD5 비고 |", "|---|---|---|---|"]
    for tid, en, typ, note in sorted(code_fks):
        L.append(f"| `{tid}` | `{en}` | {typ} | {note} |")

    L += ["", f"합계 **{len(code_fks)}건**.", ""]

    if odd_fks:
        L += ["## 4. D-33 — FK 오표기", "",
              "| 표 | 컬럼 | 타입 | TD5 비고 | 판정 |", "|---|---|---|---|---|"]
        for tid, en, typ, note in sorted(odd_fks):
            L.append(f"| `{tid}` | `{en}` | {typ} | {note} | **금액 값 컬럼을 FK 로 적었다.** "
                     f"FK 제약 미생성. 참조가 필요하면 `RATE_ID BIGINT` 신설이 맞지만 "
                     f"**컬럼을 추가하지 않는다**(G-02 762 고정) — 도입기업에 제안 |")
        L.append("")

    L += ["## 5. G-08 디지털 스레드 — 이 사슬이 끊기면 FAIL", "",
          "| 단계 | 표 | 키 | 비고 |", "|---|---|---|---|"]
    for i, (tid, key, desc) in enumerate(THREAD, 1):
        L.append(f"| {i} | `{tid}` | `{key}` | {desc} |")
    L += ["",
          "**LOT 기반 데이터 매핑 성공률 ≥ 85%**(사업계획서 2.7.4 · D-23). LOT·프로젝트번호 열이 있는",
          "**모든 화면**에서 클릭하면 **024 공정이력조회**(`/prc/024`)로 간다.",
          ""]

    L += ["## 6. G-29 개인정보 — 암호화 저장 + 화면 마스킹", "",
          "| 표 | 컬럼 | 한글명 |", "|---|---|---|"]
    for tid, en, ko in sorted(pii):
        L.append(f"| `{tid}` | `{en}` | {ko} |")
    L += ["",
          f"합계 **{len(pii)}컬럼**. 시드에 실명을 넣지 않는다 — TD3 `role_matrix` 의 실명도 제거했다(D-39).",
          ""]

    L += ["## 7. G-11 런타임 전용 표 — 깨끗한 DB 에서 0건이 정상", "",
          " · ".join(f"`{t}`" for t in runtime),
          "",
          f"합계 **{len(runtime)}표**. `make db-reset` 직후 비어 있고, 그때 화면은 `미수집 (D-nn)` 문구를",
          "렌더해야 한다. 테스트는 **0건 경로를 명시 단언**한다(§10-4).",
          "",
          "### 7.1 시드 여부 미정 — 담당 개발자가 판정한다 (지금 짐작하지 않는다)", "",
          "이름이 이력·편차라 런타임처럼 보이지만 **시드 대상 업무 데이터일 수 있다.** 담당자가",
          "`progress-devN.md` 에 판정을 적고 그때 이 표를 §7 또는 시드 대상으로 옮긴다.", "",
          "| 표 | 무엇을 정해야 하는가 |", "|---|---|"]
    for t, why in undecided:
        L.append(f"| `{t}` | {why} |")
    L.append("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L))
    print(f"생성: {OUT.relative_to(ROOT)} — 표 {len(tables)} · 컬럼 {total_cols} · "
          f"물리 FK {len(real_fks)} · 코드성 {len(code_fks)} · 오표기 {len(odd_fks)} · "
          f"개인정보 {len(pii)} · 런타임전용 {len(runtime)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
