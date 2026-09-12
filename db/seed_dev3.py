#!/usr/bin/env python
"""개발3 시드 — 수집 장비 2개소 · 전처리 규칙 · 학습 데이터셋 헤더 · 지식문서
· **가정 답변 선언(D-150)과 그 파생물**.

**규칙**
  · 멱등이다(G-07). 두 번 돌려도 행 수 diff 0.
  · **지어내지 않는다.** 값은 사업계획서 2.7.1 · TD5 비고 · `docs/cad/` 실측에서만 온다.
  · **가정 답변에서 파생한 것은 `docs/assumed/customer_answers.json` (D-150) 안의 값만이다.**
    그 파일이 없으면 선언을 지우고 파생물도 **되돌린다** — 선언 없이 남은 파생물은 조작이다.
  · **런타임 전용 표는 비워 둔다**(G-11) —
    `AGT_QUERY_LOGS` `AGT_RECOMMENDATIONS` `EST_ML_*` `EST_SHAP_FACTORS` `EST_OBJECT_REVIEWS`
    `IF_CAD_IMPORT_LOGS` `IF_DOC_EMBED_LOGS` `IF_GATEWAY_BUFFER` 는 시드하지 않는다.
  · 도면 수집은 여기가 아니라 `tools/cad_ingest.py` 다(수집 이력을 남기는 것은 런타임 동작이다).

**시드하지 않는 것과 그 이유**
  · `EST_COST_RATES` — 단가 값이 정본에 없다. 과거 견적 Excel·구매 실적 확보 미확인 (D-04)
  · `EST_PROJECTS` — **개발1 이 넣는다.** 고객사 코드가 사용자 확정(D-139)되어 D-47 차단이
    풀렸고, 실측 GD 프로젝트를 `db/seed_dev1.py` 가 적재한다 (D-131). 여기서는 건드리지 않는다
  · `DAT_DATASET_SPLITS` — Train/Validation/Test 비율이 정본에 없다. 임의 비율을 넣지 않는다
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import json                                                   # noqa: E402

import conn                                                   # noqa: E402
from kyungdong.agent import docs as agent_docs                # noqa: E402
from kyungdong.agent import retrieval                         # noqa: E402
from kyungdong.app.settings import settings                   # noqa: E402
from kyungdong.app.util import assumed                        # noqa: E402
from kyungdong.cad import inventory as cad_inventory          # noqa: E402
from kyungdong.ingest import preprocess, tags                 # noqa: E402

SAMPLE_DIR = ROOT / "src" / "kyungdong" / "agent" / "sample_docs"

# `tools/dwg_convert.py` 가 남긴 **실측** — 재질·두께·단위 분포의 유일한 출처다 (D-123).
DWG_FEATURES = ROOT / "docs" / "cad" / "dwg_features.json"

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
    # ↓ 회전 7 추가 — 규칙만 있고 코드가 없던 두 항목을 코드로 넣었다 (DEF-QA2-003 · 004).
    #   규칙 표가 정본이고 `USE_YN='N'` 이면 코드가 적용하지 않는다(`preprocess.rule_on`).
    (60, preprocess.RULE_OUTLIER, "정제", "PLC 시계열 측정값(숫자 태그)",
     "① 정본 허용 상·하한(PRC_STD_CONDITIONS.TOL_MIN/TOL_MAX)이 있으면 그것으로 판정한다 — "
     "현재 0건이다(D-203). "
     f"② 없으면 조작적 정의: 같은 태그·설비의 직전 정상값 {preprocess.MIN_HISTORY}건 이상으로 "
     f"중앙값·MAD 로버스트 z-score 를 구해 |z| > {preprocess.Z_LIMIT} 를 이상치로 본다 "
     "(임계는 정본 수치가 아니다 — D-315). "
     "③ 표본 부족·산포 0 이면 **판정하지 않는다**. "
     "판정된 행은 QUALITY_FLAG='노이즈' 로 **표시만** 하고 값을 지우지 않는다."),
    (70, preprocess.RULE_IMPUTE, "변환", "DAT_TIMESERIES 결측 행(MEASURE_VALUE IS NULL)",
     "앞뒤 정상값이 있으면 시간 비례 선형 보간, 뒤가 없으면 Forward Fill, "
     "앞이 없으면 미보정으로 남긴다(미래를 끌어오지 않는다). "
     "보정 뒤에도 QUALITY_FLAG='결측' 은 지우지 않는다 — 원천이 결측이었다는 사실이다(D-314). "
     "처리·미보정 건수는 DAT_JOB_LOGS.PROCESS_CNT/FAIL_CNT 에 남는다. "
     "도면 치수·재질 결측 보정은 Parsing·OCR 미구성으로 **차단**이다(D-05)."),
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


# ═════════════════════════════════════════════════════════════════════════
# 가정 답변 선언 (D-150) — `SYNTHETIC_THREAD`(D-131) 와 같은 방식
# ═════════════════════════════════════════════════════════════════════════
def seed_assumed_flag() -> str | None:
    """가정 선언 1행. **파일이 없으면 선언을 지운다** — 선언은 파일의 그림자다.

    화면 배지·게이트 판정 줄·`SOURCE_DESC` 고지가 **이 한 곳**을 읽는다. 선언을 지우면
    파생물의 고지가 함께 사라지므로, 파생물 자체도 같은 실행에서 되돌려야 한다
    (`seed_material_codes`·`unmark_assumed_features`).
    """
    decl = assumed.file_decision()
    if decl is None:
        conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
               (assumed.CONFIG_TYPE, assumed.CONFIG_KEY))
        return None
    a = assumed.answers() or {}
    meta = a.get("_meta") or {}
    desc = (f"{meta.get('성격', '')} {meta.get('목적', '')} "
            f"출처 {assumed.path_text()} · 갈아끼우는 법: {meta.get('갈아끼우는 법', '')}")
    conn.x(
        "insert into SYS_CONFIGS "
        "(CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, USE_YN, DESCRIPTION, CREATED_DT) "
        "values (%s, %s, %s, 'Y', %s, now()) "
        "on conflict (CONFIG_TYPE, CONFIG_KEY) do update set "
        "CONFIG_VALUE = excluded.CONFIG_VALUE, DESCRIPTION = excluded.DESCRIPTION, "
        "UPDATED_DT = now()",
        (assumed.CONFIG_TYPE, assumed.CONFIG_KEY, decl, desc[:500]),
    )
    return decl


def measured_materials() -> list[tuple[str, int]]:
    """`docs/cad/dwg_features.json` 의 **재질 분포 실측**. 없으면 빈 목록이다."""
    if not DWG_FEATURES.is_file():
        return []
    try:
        d = json.loads(DWG_FEATURES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    dist = ((d.get("요약") or {}).get("실측 합계") or {}).get("재질 분포") or []
    return [(str(k), int(v)) for k, v in dist]


def merged_materials() -> tuple[dict[str, dict], list[str]]:
    """실측 표기를 ② `통합_제안` 으로 묶는다. **목록 밖의 재질은 만들지 않는다.**

    돌려주는 것: `{정규표기: {"count": 실측건수, "from": [원표기 …]}}` 와
    **통합 제안에 적혔지만 실측에 없는 표기** 목록(지어낸 것이 아니라 제안이 남는 것이다).
    """
    measured = dict(measured_materials())
    merge = assumed.material_merge()
    alias: dict[str, str] = {}
    for canon, olds in merge.items():
        for o in olds:
            alias[o] = canon
    out: dict[str, dict] = {}
    for name, n in measured.items():
        canon = alias.get(name, name)
        slot = out.setdefault(canon, {"count": 0, "from": []})
        slot["count"] += n
        slot["from"].append(name)
    unseen = sorted({c for c in merge} - set(measured)
                    | {o for olds in merge.values() for o in olds} - set(measured))
    return out, unseen


def seed_material_codes(admin_id: int | None) -> dict[str, object]:
    """`BAS_COMMON_CODES` 그룹 '재질' — **가정 답변 ②(D-150) 에서만** 파생한다.

    · 값은 `docs/cad/dwg_features.json` 실측 표기뿐이다. **목록 밖의 이름을 만들지 않는다.**
    · `ATTR1` 에 `가정 답변 기준 (D-150) — 도입기업 미확인`, `ATTR2` 에 실측 도면 건수.
    · **두께는 코드가 아니다** — 수치이고 `EST_CAD_FEATURES` 에 있다. 코드 그룹을 만들지 않는다.
    · 선언이 없으면 **표시가 붙은 행을 지운다** → 그룹이 다시 0건이 되고 D-47 차단으로 돌아간다.
      화면(032 코드관리)이 손으로 넣은 행은 표시가 없으므로 건드리지 않는다.
    """
    mark = assumed.material_attr1()
    if not mark:                                   # 선언 없음 → 파생물 회수
        removed = conn.x("delete from BAS_COMMON_CODES where CODE_GROUP = '재질' "
                         "and ATTR1 like '가정 답변 기준 %%'")
        return {"declared": None, "before": len(measured_materials()), "after": 0,
                "removed": removed, "codes": {}, "unseen": []}
    measured = dict(measured_materials())
    codes, unseen = merged_materials()
    order = sorted(codes.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    for i, (canon, info) in enumerate(order, start=1):
        froms = sorted(info["from"], key=lambda s: (-measured[s], s))
        name = canon if froms == [canon] else f"{canon} (통합: {' · '.join(froms)})"
        attr2 = (f"실측 도면 {info['count']}건 — "
                 + " · ".join(f"{s} {measured[s]}" for s in froms))
        conn.x(
            "insert into BAS_COMMON_CODES "
            "(CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, ATTR1, ATTR2, USE_YN, "
            " CREATED_BY, CREATED_DT) values ('재질', %s, %s, %s, %s, %s, 'Y', %s, now()) "
            "on conflict (CODE_GROUP, CODE_VALUE) do update set "
            "CODE_NAME = excluded.CODE_NAME, SORT_ORDER = excluded.SORT_ORDER, "
            "ATTR1 = excluded.ATTR1, ATTR2 = excluded.ATTR2, UPDATED_DT = now()",
            (canon[:50], name[:200], i * 10, mark[:200], attr2[:200], admin_id),
        )
    keep = [c for c, _ in order]
    removed = conn.x(
        "delete from BAS_COMMON_CODES where CODE_GROUP = '재질' "
        "and ATTR1 like '가정 답변 기준 %%' and not (CODE_VALUE = any(%s))", (keep,))
    return {"declared": assumed.declaration(), "before": len(measured_materials()),
            "after": len(order), "removed": removed, "codes": dict(order), "unseen": unseen}


def unmark_assumed_features() -> int:
    """선언이 없으면 `EST_CAD_FEATURES` 의 단위 가정 행도 되돌린다.

    가정 표시를 달고 적재된 Feature 는 **가정이 선언된 동안만** 존재해야 한다. 선언을 지우면
    표시만 사라져 값이 실측처럼 남는 일이 없도록 **행을 지운다**(적재는 옵션이었다 —
    `tools/cad_ingest.py --dxf-features`).
    """
    if assumed.declaration() is not None:
        return 0
    return conn.x("delete from EST_CAD_FEATURES where SOURCE_DESC like '%%단위 가정 (%%'")


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

    decl = seed_assumed_flag()
    mats = seed_material_codes(admin_id)
    unmarked = unmark_assumed_features()
    devices = seed_devices()
    rules = seed_preprocess(admin_id)
    dataset_id, st = seed_dataset(admin_id)
    embedded, chunks, skipped = seed_knowledge()

    print(f"가정 선언        SYS_CONFIGS('{assumed.CONFIG_TYPE}','{assumed.CONFIG_KEY}') = "
          f"{decl or '없음 — ' + (assumed.mismatch() or '')}")
    if decl:
        print(f"  · 출처         {assumed.path_text()} — **도입기업 답변이 아니다.** "
              "이 파일을 지우고 시드를 다시 돌리면 파생물이 회수되고 게이트는 차단으로 돌아간다")
        print(f"  · 고지 문구     {assumed.base_note()} / {assumed.circular_note()}")
        print(f"  · 채우지 않은 것 {len(assumed.not_given())} 건 (G-15·G-17·G-18 은 차단이 정답이다): "
              + " · ".join(assumed.not_given()))
    print(f"재질 코드        실측 표기 {mats['before']} 종 → 통합 후 {mats['after']} 종 "
          f"(회수 {mats['removed']} 행) · 표시 {assumed.material_attr1() or '없음'}")
    for canon, info in sorted(mats["codes"].items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        print(f"  · {canon:<10} 실측 {info['count']:>3} 건  ← {' · '.join(sorted(info['from']))}")
    if mats["unseen"]:
        print(f"  · 통합 제안에는 있으나 실측에 없는 표기 {mats['unseen']} — 만들지 않았다")
    print("  · **두께는 코드 그룹을 만들지 않았다** — 수치이고 `EST_CAD_FEATURES` 에 있다. "
          "실측 distinct 43종이고 요약 JSON 의 '두께 15종' 은 상위 15종 절단이다")
    if unmarked:
        print(f"  · 선언이 없어 단위 가정 Feature {unmarked} 행을 회수했다")
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
    n_pj = conn.q1("select count(*) as n from EST_PROJECTS")["n"]
    print(f"  · EST_PROJECTS     개발1 이 실측 GD 프로젝트를 넣는다 (D-131 · 고객사 확정 D-139) "
          f"— 현재 {n_pj} 건. 개발3 시드는 건드리지 않는다")
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
