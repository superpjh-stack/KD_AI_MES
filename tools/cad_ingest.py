#!/usr/bin/env python
"""도면 수집·정제 (MES-TD4-048) — `docs/cad/` **실측 인벤토리**만 읽는다.

  인벤토리 → `IF_CAD_FILES`(수신) → 정제 → `EST_CAD_DRAWINGS` → `DAT_DATASET_ITEMS`
  단계마다 `IF_CAD_IMPORT_LOGS` 에 수신/검증/중복제거/등록을 남긴다.

정제 규칙 (D-03)
  · 0KB 손상 제외 — 실측 4건
  · 도면번호+버전+고객사 중복 제거 — **고객사 메타데이터가 없어** 제품/프로젝트 폴더명을
    대체 축으로 쓴다(`--scope none` 으로 고객사 없이도 돌려 볼 수 있다)
  · 발행일·개정일이 없어 최종수정일(mtime)로 대체

**Label 은 만들지 않는다**(D-04). `DAT_DATASET_ITEMS.LABEL_VALUE` 는 NULL 로 둔다 —
과거 견적금액·실제 제조원가 확보 여부가 확인되지 않았고, 합성 Label 로 채우면 결함이다.

멱등이다 — 같은 (원본 파일명, 원본 경로) 는 다시 수집하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                          # noqa: E402
from kyungdong.cad import inventory as inv           # noqa: E402
from kyungdong.cad import pipeline                   # noqa: E402

DATASET_NAME = "CAD도면 원본 인벤토리"
DATASET_VERSION = "v0.1"


def link_dataset(scope: str, limit: int | None) -> dict[str, int]:
    """등록된 도면을 학습 데이터셋 항목으로 잇는다. **Label 은 비운다**(D-04)."""
    ds = conn.q1("select DATASET_ID from DAT_TRAIN_DATASETS where DATASET_NAME=%s and DATASET_VERSION=%s",
                 (DATASET_NAME, DATASET_VERSION))
    if ds is None:
        return {"dataset": 0, "created": 0, "existing": 0}
    dataset_id = int(ds["dataset_id"])
    files = inv.read_inventory()
    cleaned = [c for c in inv.clean(files, scope) if c.keep]
    if limit is not None:
        cleaned = cleaned[:limit]
    by_key = {c.dedup_key: c for c in cleaned}
    rows = conn.q("select DRAWING_ID, DRAWING_NO, REVISION from EST_CAD_DRAWINGS")
    created = existing = 0
    for r in rows:
        key = inv.dedup_key(r["drawing_no"], r["revision"] or "", None)
        match = by_key.get(key)
        if match is None:
            # 제품 대체 축으로 만든 키도 확인한다
            match = next((c for c in cleaned
                          if c.drawing_no == r["drawing_no"] and (c.revision or "") == (r["revision"] or "")),
                         None)
        dedup = match.dedup_key if match else inv.dedup_key(r["drawing_no"], r["revision"] or "", None)
        hit = conn.q1(
            "select ITEM_ID from DAT_DATASET_ITEMS "
            "where DATASET_ID = %s and SOURCE_TYPE = 'CAD도면' and SOURCE_ID = %s",
            (dataset_id, r["drawing_id"]))
        if hit:
            existing += 1
            continue
        conn.x(
            "insert into DAT_DATASET_ITEMS "
            "(DATASET_ID, SOURCE_TYPE, SOURCE_ID, LABEL_VALUE, IMPUTED_YN, OUTLIER_REMOVED_YN, "
            " DEDUP_KEY, CREATED_DT) values (%s,'CAD도면',%s, null, 'N','N', %s, now())",
            (dataset_id, r["drawing_id"], dedup[:200]))
        created += 1
    return {"dataset": dataset_id, "created": created, "existing": existing}


def main() -> int:
    p = argparse.ArgumentParser(description="CAD 도면 수집·정제 (D-03 실측 인벤토리)")
    p.add_argument("--limit", type=int, default=None, help="처음 N건만 수집 (시험용)")
    p.add_argument("--scope", choices=inv.SCOPES, default="product",
                   help="중복 제거 키의 고객사 자리. product = 제품/프로젝트 폴더명 대체 표기 (D-03)")
    p.add_argument("--report", action="store_true", help="DB 에 쓰지 않고 실측 통계만 출력")
    p.add_argument("--json", action="store_true", help="통계를 JSON 으로 출력")
    a = p.parse_args()

    files = inv.read_inventory()
    cleaned = inv.clean(files, a.scope)
    st = inv.stats(files, cleaned)

    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=1, default=str))
    else:
        print(f"인벤토리        {st['total']:,} 건 / 제품 {st['products']} 종  ({inv.INVENTORY_XLSX.name})")
        print(f"파일명 중복      {st['file_name_dup']} 건 (완전일치 — D-03 실측 재현)")
        print(f"0KB 손상        {st['zero_byte']} 건")
        print(f"제품당 도면      최대 {st['max_per_product']} · 최소 {st['min_per_product']} "
              f"· 중앙값 {st['median_per_product']} · 1건뿐인 제품 {st['single_drawing_products']} 종")
        print(f"확장자          {st['ext']}")
        print(f"정제(scope={a.scope})  등록 {st['kept']:,} · 제외 {st['excluded']:,} {st['excluded_by_reason']}")
        print(f"고객사 메타     {st['customer_meta']} — 발행일 메타 없음, mtime 대체 (D-03)")

    if a.report:
        return 0

    if conn.table_count() != 68:
        print(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-schema`", file=sys.stderr)
        return 1
    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    res = pipeline.import_inventory(limit=a.limit, scope=a.scope,
                                    created_by=int(admin["user_id"]) if admin else None)
    link = link_dataset(a.scope, a.limit)
    print()
    print(f"수집            스캔 {res.scanned:,} · 신규 등록 {res.registered:,} · 제외 {res.excluded:,} "
          f"· 이미 수집됨 {res.skipped:,}")
    print(f"제외 사유        {res.by_reason}")
    print(f"학습 항목        DAT_DATASET_ITEMS 신규 {link['created']:,} · 기존 {link['existing']:,} "
          f"(데이터셋 #{link['dataset']})")
    print(f"Label           0 건 — 과거 견적금액·실제 제조원가 확보 미확인 (D-04). 합성 Label 을 넣지 않는다")
    for t in ("IF_CAD_FILES", "IF_CAD_IMPORT_LOGS", "EST_CAD_DRAWINGS", "DAT_DATASET_ITEMS"):
        print(f"  {t:<22} {conn.q1(f'select count(*) as n from {t}')['n']:,}")
    print()
    print("분석 실행(Parsing·Vision)은 **501 CAD Parsing 미구성 (D-05)** 이다 — "
          "객체·Feature 를 만들어 채우지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
