#!/usr/bin/env python
"""개발3 시드 — 수집 장비 2개소 · 전처리 규칙 · 학습 데이터셋 헤더 · 지식문서.

**규칙**
  · 멱등이다(G-07). 두 번 돌려도 행 수 diff 0.
  · **지어내지 않는다.** 값은 사업계획서 2.7.1 · TD5 비고 · `docs/cad/` 실측에서만 온다.
  · **런타임 전용 표는 비워 둔다**(G-11) —
    `AGT_QUERY_LOGS` `AGT_RECOMMENDATIONS` `EST_ML_*` `EST_SHAP_FACTORS` `EST_OBJECT_REVIEWS`
    `IF_CAD_IMPORT_LOGS` `IF_DOC_EMBED_LOGS` `IF_GATEWAY_BUFFER` 는 시드하지 않는다.
  · 도면 수집은 여기가 아니라 `tools/cad_ingest.py` 다(수집 이력을 남기는 것은 런타임 동작이다).

**시드하지 않는 것과 그 이유**
  · `EST_COST_RATES` — 단가 값이 정본에 없다. 과거 견적 Excel·구매 실적 확보 미확인 (D-04)
  · `EST_PROJECTS` — 고객사 코드 그룹이 비어 있다 (D-47). 코드 검증(D-32)을 통과할 수 없다
  · `DAT_DATASET_SPLITS` — Train/Validation/Test 비율이 정본에 없다. 임의 비율을 넣지 않는다
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                   # noqa: E402
from kyungdong.agent import docs as agent_docs                # noqa: E402
from kyungdong.agent import retrieval                         # noqa: E402
from kyungdong.app.settings import settings                   # noqa: E402
from kyungdong.cad import inventory as cad_inventory          # noqa: E402
from kyungdong.ingest import tags                             # noqa: E402

SAMPLE_DIR = ROOT / "src" / "kyungdong" / "agent" / "sample_docs"

# ── 수집 장비 — 사업계획서 2.7.1 데이터 집계 포인트 **2개소뿐** (D-06) ─────
# 모델명은 TD5 `IF_DEVICE_REGISTRY.MODEL_NAME` 비고가 적은 값이다. IP·설치 위치는 **미확인**이라 비운다.
DEVICES = [
    ("레이저커팅기 PLC", "PLC", "XBC-DN32H", "Ethernet/OPC-UA", "EQ10"),
    ("현장POP(터치PC)", "단말", "DUPLE 21인치", "TCP/IP", "EQ20"),
]

# ── 전처리 규칙 — TD5 `DAT_PREPROCESS_RULES.TARGET_DESC` 비고 + D-03 실태 ──
PREPROCESS = [
    (10, "0KB 손상 파일 제외", "필터링", "CAD 도면 파일 크기",
     "FILE_SIZE <= 0 인 파일을 학습 대상에서 제외한다. 실측 4건 (D-03)."),
    (20, "도면 중복 제거", "정제", "도면번호+버전+고객사",
     "DEDUP_KEY = 도면번호+버전+고객사 로 첫 1건만 남긴다. "
     "고객사 메타데이터가 없어 제품/프로젝트 폴더명을 대체 축으로 쓴다 (D-03)."),
    (30, "발행일 대체 기준", "변환", "도면 발행일·개정일",
     "발행일·개정일 메타데이터가 없어 최종수정일(mtime)로 대체한다 (D-03 · TD5 FILE_MTIME 비고)."),
    (40, "센서 노이즈 플래그", "정제", "PLC 시계열 측정값",
     "숫자로 변환되지 않는 값은 QUALITY_FLAG='결측' 으로 표시하고 버리지 않는다."),
    (50, "단위 표준화", "변환", "PLC 태그 단위",
     "태그별 단위를 고정한다: " + " · ".join(f"{t.name}={t.uom or '-'}" for t in tags.TAGS)),
]

# ── 지식문서 — 시안 `sample_docs/` 3종 이식 (D-20) ────────────────────────
# TD5 `AGT_VECTOR_DOCS.DOC_TYPE` 어휘: 입고기준서/검사기준서/SOP/출하기준서/클레임 매뉴얼
# 세 번째 문서(견적·조달)는 **그 어휘에 맞는 구분이 없다** → 등록만 하고 임베딩 대상에서 뺀다(D-303).
#   (파일명, IF_EXT_DOCUMENTS.DOC_TYPE(표준/기준서/매뉴얼), AGT_VECTOR_DOCS.DOC_TYPE 또는 None)
KNOWLEDGE = [
    ("material_receiving_sop.md", "기준서", "SOP"),
    ("fat_safety_claim_manual.md", "매뉴얼", "클레임 매뉴얼"),
    ("quote_and_procurement_guide.md", "기준서", None),
]


def seed_devices() -> int:
    interval = settings().h("PLC_POLL_SEC").as_int()
    for name, dtype, model, protocol, _equip in DEVICES:
        conn.x(
            "insert into IF_DEVICE_REGISTRY "
            "(DEVICE_NAME, DEVICE_TYPE, MODEL_NAME, PROTOCOL, COLLECT_INTERVAL, USE_YN, CREATED_DT) "
            "select %s,%s,%s,%s,%s,'Y', now() "
            "where not exists (select 1 from IF_DEVICE_REGISTRY where DEVICE_NAME = %s)",
            (name, dtype, model, protocol, interval if dtype == "PLC" else None, name),
        )
        conn.x(
            "update IF_DEVICE_REGISTRY set DEVICE_TYPE=%s, MODEL_NAME=%s, PROTOCOL=%s, "
            "COLLECT_INTERVAL=%s, UPDATED_DT=now() where DEVICE_NAME=%s",
            (dtype, model, protocol, interval if dtype == "PLC" else None, name),
        )
    row = conn.q1("select count(*) as n from IF_DEVICE_REGISTRY")
    return int(row["n"])


def seed_preprocess(admin_id: int | None) -> int:
    for order, name, stage, target, expr in PREPROCESS:
        conn.x(
            "insert into DAT_PREPROCESS_RULES "
            "(RULE_NAME, RULE_STAGE, TARGET_DESC, RULE_EXPR, APPLY_ORDER, USE_YN, CREATED_BY, CREATED_DT) "
            "select %s,%s,%s,%s,%s,'Y',%s, now() "
            "where not exists (select 1 from DAT_PREPROCESS_RULES where RULE_NAME = %s)",
            (name, stage, target, expr, order, admin_id, name),
        )
        conn.x(
            "update DAT_PREPROCESS_RULES set RULE_STAGE=%s, TARGET_DESC=%s, RULE_EXPR=%s, "
            "APPLY_ORDER=%s, UPDATED_DT=now() where RULE_NAME=%s",
            (stage, target, expr, order, name),
        )
    row = conn.q1("select count(*) as n from DAT_PREPROCESS_RULES")
    return int(row["n"])


def seed_dataset(admin_id: int | None) -> tuple[int, dict]:
    """학습 데이터셋 헤더 — 건수는 `docs/cad/` **실측**이다(D-03)."""
    files = cad_inventory.read_inventory()
    cleaned = cad_inventory.clean(files)
    st = cad_inventory.stats(files, cleaned)
    name = "CAD도면 원본 인벤토리"
    balance = (f"제품 {st['products']}종 · 제품당 도면 최대 {st['max_per_product']}"
               f"·최소 {st['min_per_product']}·중앙값 {st['median_per_product']} · "
               f"도면 1건뿐인 제품 {st['single_drawing_products']}종 (D-03 불균형)")
    conn.x(
        "insert into DAT_TRAIN_DATASETS "
        "(DATASET_NAME, TARGET_MODEL, TOTAL_CNT, EXCLUDED_CNT, DATASET_VERSION, BALANCE_RESULT, "
        " DATASET_STATUS, CREATED_BY, CREATED_DT) "
        "select %s,%s,%s,%s,%s,%s,%s,%s, now() "
        "where not exists (select 1 from DAT_TRAIN_DATASETS where DATASET_NAME = %s and DATASET_VERSION = %s)",
        (name, "도면객체인식", st["total"], st["excluded"], "v0.1", balance, "작성", admin_id,
         name, "v0.1"),
    )
    conn.x(
        "update DAT_TRAIN_DATASETS set TOTAL_CNT=%s, EXCLUDED_CNT=%s, BALANCE_RESULT=%s, UPDATED_DT=now() "
        "where DATASET_NAME=%s and DATASET_VERSION=%s",
        (st["total"], st["excluded"], balance, name, "v0.1"),
    )
    row = conn.q1("select DATASET_ID from DAT_TRAIN_DATASETS where DATASET_NAME=%s and DATASET_VERSION=%s",
                  (name, "v0.1"))
    return int(row["dataset_id"]), st


def seed_knowledge() -> tuple[int, int, list[str]]:
    """시안 3종을 `IF_EXT_DOCUMENTS` → `AGT_VECTOR_DOCS` 로 옮긴다. 임베딩 미구성이면 본문만."""
    embedded, skipped = 0, []
    for fname, if_type, vec_type in KNOWLEDGE:
        path = SAMPLE_DIR / fname
        if not path.exists():
            skipped.append(f"{fname} — 파일 없음")
            continue
        ext_id = agent_docs.register_document(
            doc_name=fname, doc_type=if_type, source_path=str(path.relative_to(ROOT)),
            embed_target=vec_type is not None)
        if vec_type is None:
            skipped.append(f"{fname} — TD5 AGT_VECTOR_DOCS.DOC_TYPE 어휘에 맞는 구분 없음 (D-303)")
            continue
        if vec_type not in retrieval.DOC_TYPES:
            skipped.append(f"{fname} — 어휘 위반 {vec_type!r}")
            continue
        # 시드는 IF_DOC_EMBED_LOGS 를 만들지 않는다 — 런타임 전용 표다(G-11).
        agent_docs.embed_document(ext_id, path.read_text(), doc_type=vec_type, log=False)
        embedded += 1
    row = conn.q1("select count(*) as n from AGT_VECTOR_DOCS")
    return embedded, int(row["n"]), skipped


RUNTIME_EMPTY = (
    "AGT_QUERY_LOGS", "AGT_RECOMMENDATIONS", "EST_ML_MODELS", "EST_ML_TRAIN_RUNS",
    "EST_ML_PREDICTIONS", "EST_SHAP_FACTORS", "EST_OBJECT_REVIEWS",
    "IF_CAD_IMPORT_LOGS", "IF_DOC_EMBED_LOGS", "IF_GATEWAY_BUFFER",
)


def main() -> int:
    if conn.table_count() != 68:
        print(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-schema`", file=sys.stderr)
        return 1
    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    if admin is None:
        print("공통 시드가 먼저다 — `uv run python db/seed.py`", file=sys.stderr)
        return 1
    admin_id = int(admin["user_id"])

    devices = seed_devices()
    rules = seed_preprocess(admin_id)
    dataset_id, st = seed_dataset(admin_id)
    embedded, chunks, skipped = seed_knowledge()

    print(f"수집 장비        {devices} 건  (사업계획서 2.7.1 데이터 집계 포인트 2개소뿐 — D-06)")
    print(f"전처리 규칙      {rules} 건")
    print(f"학습 데이터셋     #{dataset_id} — 총 {st['total']:,} / 제외 {st['excluded']:,} "
          f"(중복 {st['excluded_by_reason'].get('파일명 중복', 0)} · 0KB {st['excluded_by_reason'].get('0KB 손상', 0)})")
    print(f"지식문서         {embedded} 건 임베딩 → AGT_VECTOR_DOCS {chunks} 청크 "
          f"(검색 모드 {settings().search_mode})")
    for s in skipped:
        print(f"  · 미임베딩 {s}")
    print()
    print("시드하지 않은 것 — 정본에 값이 없다(지어내지 않는다):")
    print("  · EST_COST_RATES   단가 값 미확보 — 과거 견적 Excel·구매 실적 확인 필요 (D-04)")
    print("  · EST_PROJECTS     고객사 코드 그룹이 비어 있다 (D-47) — 코드 검증(D-32) 통과 불가")
    print("  · DAT_DATASET_SPLITS  Train/Validation/Test 비율이 정본에 없다")
    print()
    print("런타임 전용 표 — 0건이 정상이다 (G-11):")
    for t in RUNTIME_EMPTY:
        n = conn.q1(f"select count(*) as n from {t}")["n"]
        print(f"  · {t:<24} {n} 건")
    print()
    print("도면 수집은 `make cad-ingest` 다 — 수집 이력을 남기는 것은 런타임 동작이라 시드가 아니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
