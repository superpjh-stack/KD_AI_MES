#!/usr/bin/env python
"""도면 수집·정제 (MES-TD4-048).

**두 가지 원천이 있고 둘은 다른 것이다 — 섞어 쓰지 않는다.**

  ① 기본(`--source inventory`) — `docs/cad/경동글로벌텍_CAD도면_제품별정리.xlsx` **1,283행**.
     인벤토리 → `IF_CAD_FILES`(수신) → 정제 → `EST_CAD_DRAWINGS` → `DAT_DATASET_ITEMS`.
     단계마다 `IF_CAD_IMPORT_LOGS` 에 수신/검증/중복제거/등록을 남긴다. **DB 를 채우는 경로다.**

  ② `--source archive` — **원본 폴더 6,038 파일을 직접 훑는다**(D-109 ~ D-115).
     프로젝트(GD 폴더 99) · 도면(CAD 3,299) · 견적(73) · DXF 실측을 **재서 보고만** 한다.
     **DB 에는 쓰지 않는다.** 왜 못 쓰는지는 아래 '차단' 에 그대로 적는다.

정제 규칙 (D-03)
  · 0KB 손상 제외 — 실측 4건
  · 도면번호+버전+고객사 중복 제거 — **고객사 메타데이터가 없어** 제품/프로젝트 폴더명을
    대체 축으로 쓴다(`--scope none` 으로 고객사 없이도 돌려 볼 수 있다)
  · 발행일·개정일이 없어 최종수정일(mtime)로 대체

**Label 은 만들지 않는다**(D-04). `DAT_DATASET_ITEMS.LABEL_VALUE` 는 NULL 로 둔다 —
합성 Label 로 채우면 결함이다. 다만 `--source archive` 가 **과거 견적 총액을 파일 27/31건(내용이 서로 다른 22/26건)** 에서 실측했고
그것이 D-04 의 **Label 후보**다. 후보와 Label 은 다르다 — 적재는 아래 차단 때문에 막혀 있다.

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
from kyungdong.cad import archive                    # noqa: E402
from kyungdong.cad import dxf                        # noqa: E402
from kyungdong.cad import inventory as inv           # noqa: E402
from kyungdong.cad import pipeline                   # noqa: E402
from kyungdong.cad import quote as quotelib          # noqa: E402

DATASET_NAME = "CAD도면 원본 인벤토리"
DATASET_VERSION = "v0.1"

REPORT_JSON = ROOT / "docs" / "cad" / "archive_scan.json"

# `--source archive` 가 잰 것을 **DB 에 못 넣는 이유**. 사유 없이 비워 두면 그건 차단이 아니라 누락이다.
ARCHIVE_BLOCKS: dict[str, str] = {
    "EST_PROJECTS": (
        "`CUSTOMER_CODE` 가 NOT NULL 이고 `BAS_COMMON_CODES` '고객사' 그룹이 **0건**이다(D-47·D-56). "
        "`util/codes.require_code()` 가 422 를 던진다. 폴더명에서 읽은 고객사는 "
        "**파일시스템 파생 후보이지 도입기업 마스터가 아니다**(D-114) — 마스터로 승격하면 그게 합성이다"),
    "EST_QUOTATIONS": (
        "`PROJECT_ID` 가 NOT NULL FK → `EST_PROJECTS` 다. 위가 0건이면 **구조적으로 한 행도 못 넣는다**. "
        "견적 총액·납기는 실측했고 값은 이 리포트에 있다 — 적재만 막혀 있다"),
    "EST_CAD_DRAWINGS(원본 3,299건)": (
        "기본 경로가 통계 xlsx 1,283행으로 이미 채워져 있다. 원본 3,299건으로 갈아끼우면 "
        "`DAT_TRAIN_DATASETS.TOTAL_CNT` · 기존 회귀·진행률 실측이 전부 어긋난다 — "
        "원천 교체는 정본(D-03) 개정이 먼저다. 여기서는 **재기만** 한다"),
    "EST_CAD_FEATURES(DXF 실측)": (
        "`tools/check_ingest.py` ⑤ 가 '확정 객체 0건 + Feature N행 = 합성' 으로 판정한다(G-13). "
        "DXF 실측은 합성이 아니지만 그 검사기는 객체 집계만을 Feature 원천으로 안다 — "
        "`--dxf-features` 로 **명시 요구**할 때만 쓴다"),
}


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


def _uniq_files(files: list[archive.ArchiveFile]) -> list[archive.ArchiveFile]:
    """같은 파일의 복사본을 걷어낸다 — **내용 해시**로 가른다.

    `20 경동도면함/` 아래에 16~19 도면함이 통째로 또 들어 있고(D-109),
    `CAD도면_제품별정리(신규)/` 는 같은 파일에 `113_2020-11-14_` 같은 접두어를 붙여 놨다.
    파일명으로 가르면 같은 도면이 둘로 세어진다 — 29건을 29개 도면이라고 하면 **표본을 부풀린 것**이다.
    """
    import hashlib

    def digest(f: archive.ArchiveFile) -> tuple[int, str]:
        h = hashlib.sha1()
        with open(f.path, "rb") as fp:
            h.update(fp.read(1 << 20))
            if f.size > (2 << 20):
                fp.seek(-(1 << 20), 2)
                h.update(fp.read(1 << 20))
        return f.size, h.hexdigest()

    seen: dict[tuple[int, str], archive.ArchiveFile] = {}
    for f in files:
        seen.setdefault(digest(f), f)
    return sorted(seen.values(), key=lambda f: f.rel)


def archive_report(*, dxf_limit: int | None, write_json: bool) -> dict:
    """원본 아카이브 실측. **표본 수·모집단·적중률을 항상 함께 적는다.**"""
    if not archive.available():
        print(f"원본 아카이브가 없다: {archive.archive_root()}", file=sys.stderr)
        print(f"경로가 다르면 환경변수 {archive.ENV_KEY} 로 준다 (D-109)", file=sys.stderr)
        return {}
    scan = archive.scan()
    st, jn = scan.stats(), scan.joins()

    print("═══ ① 원본 아카이브 실측 (D-109) ═══════════════════════════════")
    print(f"  루트            {st['root']}")
    print(f"  파일            {st['files']:,} 건")
    print(f"  확장자 상위      {dict(list(st['ext'].items())[:10])}")
    print(f"  CAD 파일        {st['cad_files']:,} 건 {st['cad_by_ext']}  ← 이것이 도면 모집단이다")
    print(f"  PDF             {st['pdf_files']:,} 건 (도면·견적·카탈로그가 섞여 있다 — 분류 안 했다)")
    print("  ⚠ 파일명은 macOS NFD 다 — NFC 정규화 없이 '견적' 을 찾으면 **0건**이 나온다 (D-115)")

    print()
    print("═══ ② 프로젝트(수주)번호 — 폴더명 파싱 (D-112) ═══════════════════")
    print(f"  정규식          {archive.PROJECT_RE.pattern}")
    print(f"  GD 폴더         {st['project_dirs']} 개 · 파싱 성공 {st['projects_parsed']} "
          f"· **실패 {st['project_parse_failed']}**")
    print(f"  서로 다른 번호   {st['unique_project_no']} 개 "
          f"(99 - 34 = 65 는 `20 경동도면함/` 아래 복사본이다 — 99를 프로젝트 수로 쓰면 부풀린 것이다)")
    print(f"  제품군 적중      {st['product_group_hit']}/{st['projects_parsed']} "
          f"({st['product_group_hit'] * 100 // max(st['projects_parsed'], 1)}%) {st['by_product_group']}")
    print(f"  고객사 적중      {st['customer_hit']}/{st['projects_parsed']} "
          f"({st['customer_hit'] * 100 // max(st['projects_parsed'], 1)}%) — "
          "**폴더명 파생 후보다. 도입기업 마스터가 아니다** (D-114)")
    for p in scan.projects[:6]:
        print(f"     {p.project_no:14} 제품군 {p.product_group or '-':7} "
              f"고객사 {p.customer or '-':7} 폴더 {p.folder[:40]}")

    print()
    print("═══ ③ 도면 ↔ 견적 조인 (D-113) ════════════════════════════════")
    print(f"  견적 파일        {st['quote_files']} 건 {st['quote_by_ext']}")
    print(f"  같은 폴더에 둘 다  **{jn['same_folder']}** 폴더 (직접 포함 기준)")
    print(f"  하위까지 치면      **{jn['subtree']}** 폴더 (상위 폴더도 세어진다 — 두 수는 다른 것이다)")
    for r in jn["subtree_top"][:4]:
        print(f"     {r['folder'][:52]:54} 도면 {r['drawings']:>4} · 견적 {r['quotes']:>3}")

    print()
    print("═══ ④ DXF 실측 (D-110-b — D-05 판정 정정) ══════════════════════")
    dxf_files = [f for f in scan.cad_files if f.ext == "dxf"]
    uniq = _uniq_files(dxf_files)
    if dxf_limit is not None:
        uniq = uniq[:dxf_limit]
    print(f"  **표본 {len(dxf_files)}건 / 모집단 CAD {st['cad_files']:,}건 = "
          f"{len(dxf_files) * 100 / max(st['cad_files'], 1):.1f}%** — "
          "이 표본으로 G-14(CAD 객체 인식 80%)를 주장하지 않는다")
    print(f"  복사본 제거 후 서로 다른 도면 **{len(uniq)}건**")
    measures = [dxf.parse(f.path) for f in uniq]
    for f, m in zip(uniq, measures):
        print(f"     {f.name[:38]:40} {f.size / 1e6:7.1f}MB {m.encoding:8} "
              f"엔티티 {sum(m.entities.values()):>7,} · 홀(CIRCLE) {m.holes:>5,} · "
              f"절단장 {m.cut_len:>12,.0f} · 닫힌폴리 {m.closed_polys:>4} · "
              f"재질 {m.material or '-':9} 두께 {m.thickness if m.thickness is not None else '-'}")
    hits = dxf.hit_rates(measures)
    print(f"  적중률 (분모 = 서로 다른 도면 {hits['parsed']}건 · 읽기 실패 {hits['failed']})")
    for k in (dxf.F_HOLES, dxf.F_CUTLEN, dxf.F_AREA, dxf.F_MATERIAL, dxf.F_THICK):
        print(f"     {k:8} {hits[k]:>2}/{hits['parsed']} "
              f"({hits[k] * 100 // max(hits['parsed'], 1)}%)")
    print(f"  재질 정규식      {dxf.MATERIAL_RE.pattern[:88]}…")
    print(f"  두께 정규식      {dxf.THICKNESS_RE.pattern[:88]}…")
    print("  형식별 산출 가능 (`cad/pipeline.FORMAT_FEATURE_SUPPORT`)")
    for ft in ("DXF", "DWG", "CAD"):
        ok = [k for k, v in pipeline.support_for(ft).items() if "없다" not in v]
        print(f"     {ft:4} 산출 {ok or '없음'} · 차단 {sorted(pipeline.blocked_for(ft))}")

    print()
    print("═══ ⑤ 견적 실측 (D-111) — D-04 의 Label 후보 ═════════════════════")
    xls_all = [f for f in scan.quote_files if f.ext == "xls"]
    xls = _uniq_files(xls_all)          # 내용이 같은 복사본은 하나로 — 표본을 부풀리지 않는다
    docs = [quotelib.parse(f.path) for f in xls]
    qs = quotelib.summarize(docs)
    print(f"  `.xls` 견적      파일 {len(xls_all)} 건 → **내용이 서로 다른 {qs['files']} 건** "
          f"(상위 폴더 복사본 {len(xls_all) - qs['files']} 건 제거) · 열기 성공 {qs['opened']} "
          f"· **열기 실패 {qs['open_failed']}**")
    print(f"  **총액 추출 {qs['total_extracted']}/{qs['files']}** "
          f"({qs['total_extracted'] * 100 // max(qs['files'], 1)}%) 방식별 {qs['total_by_method']}")
    print(f"  **못 뽑은 {qs['files'] - qs['total_extracted']}건** — 갑지 없는 견적요청서·부품 "
          "계산시트거나, 한 행에 금액 후보가 둘 이상이라 고르지 않은 것이다")
    print(f"  납기(일수) 추출  {qs['lead_extracted']}/{qs['files']} "
          f"({qs['lead_extracted'] * 100 // max(qs['files'], 1)}%) · 관측값 {qs['lead_days']} 일")
    print(f"  품목 명세        {qs['items']:,} 행 / {qs['files_with_items']} 파일")
    print(f"  갑지(시트) 단위 총액 {qs['sheet_totals']} 건 · 한 파일에 견적이 여럿인 것 "
          f"{qs['multi_quote_files']} 건 — **파일 1건 ≠ 견적 1건이다**")
    print(f"  총액 범위        {qs['amount_min']:,.0f} ~ {qs['amount_max']:,.0f} 원")
    for d in docs:
        mark = "T" if d.total_amount is not None else "-"
        print(f"     {mark} {d.file_name[:38]:40} "
              f"{(f'{d.total_amount:,.0f}' if d.total_amount is not None else '—'):>16} "
              f"{d.total_method or '':6} 납기 {str(d.lead_days or '—'):>4} 품목 {len(d.items):>3}")
        for fail in d.failures:
            print(f"       × {fail[:130]}")

    print()
    print("═══ ⑥ 차단 — 잰 것을 DB 에 못 넣는 이유 ═════════════════════════")
    for table, why in ARCHIVE_BLOCKS.items():
        print(f"  차단 {table}")
        print(f"       {why}")

    payload = {
        "archive": st, "joins": jn,
        "projects": [vars(p) for p in scan.projects],
        "dxf": {"population_cad_files": st["cad_files"], "dxf_files": len(dxf_files),
                "distinct_drawings": len(uniq), "hit_rates": hits,
                "measures": [{"file": f.name, "rel": f.rel, "size": f.size,
                              "encoding": m.encoding, "entities": m.entities,
                              "holes": m.holes, "cut_len": m.cut_len,
                              "closed_area": m.closed_area, "closed_polys": m.closed_polys,
                              "material": m.material, "material_hits": m.material_hits,
                              "thickness": m.thickness, "thickness_hits": m.thickness_hits,
                              "uom": m.uom, "inserts": m.inserts, "error": m.error,
                              "features": m.features()}
                             for f, m in zip(uniq, measures)]},
        "quotes": {"summary": qs,
                   "docs": [{"file": d.file_name, "rel": d.path, "total": d.total_amount,
                             "method": d.total_method, "cell": d.total_cell,
                             "lead_days": d.lead_days, "project_name": d.project_name,
                             "sheet_totals": d.sheet_totals, "items": len(d.items),
                             "failures": d.failures, "error": d.error}
                            for d in docs]},
        "blocked": ARCHIVE_BLOCKS,
    }
    if write_json:
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                               encoding="utf-8")
        print()
        print(f"  실측 JSON       {REPORT_JSON.relative_to(ROOT)} "
              "(원본 폴더는 건드리지 않았다 — 읽기 전용)")
    return payload


def store_dxf(limit: int | None) -> None:
    """DXF 실측 Feature 를 `EST_CAD_FEATURES` 에 적재한다 — **`--dxf-features` 를 준 때만.**"""
    rows = conn.q("select DRAWING_ID, DRAWING_NO, FILE_PATH from EST_CAD_DRAWINGS "
                  "where upper(FILE_TYPE) = 'DXF' order by DRAWING_ID")
    if limit is not None:
        rows = rows[:limit]
    print(f"  DXF 도면 {len(rows)} 건 (EST_CAD_DRAWINGS 기준)")
    created = updated = skipped = missing = 0
    for r in rows:
        got = pipeline.store_dxf_features(int(r["drawing_id"]), allow_unconfirmed=True)
        if not got.get("measured"):
            missing += 1
            print(f"     - {r['drawing_no'][:44]:46} {got.get('note', got.get('error'))}"[:150])
            continue
        created += got["created"]
        updated += got["updated"]
        skipped += got["skipped_text"]
        print(f"     + {r['drawing_no'][:44]:46} 신규 {got['created']} · 갱신 {got['updated']} "
              f"· 문자형 제외 {got['skipped_text']}")
    print(f"  EST_CAD_FEATURES 신규 {created} · 갱신 {updated} · "
          f"문자형(재질) 제외 {skipped} · 원본 없음 {missing}")
    print("  `SOURCE_DESC` 는 전부 'DXF 실측 —' 로 시작한다 — 합성 Feature 와 구분된다")
    print("  ⚠ 이 적재는 `tools/check_ingest.py` ⑤(확정 객체 0건 + Feature N행 = 합성)를 "
          "건드린다. G-13 판정을 다시 재라")


def main() -> int:
    p = argparse.ArgumentParser(description="CAD 도면 수집·정제 (D-03 실측 인벤토리 / D-109 원본)")
    p.add_argument("--limit", type=int, default=None, help="처음 N건만 수집 (시험용)")
    p.add_argument("--scope", choices=inv.SCOPES, default="product",
                   help="중복 제거 키의 고객사 자리. product = 제품/프로젝트 폴더명 대체 표기 (D-03)")
    p.add_argument("--report", action="store_true", help="DB 에 쓰지 않고 실측 통계만 출력")
    p.add_argument("--json", action="store_true", help="통계를 JSON 으로 출력")
    p.add_argument("--source", choices=("inventory", "archive"), default="inventory",
                   help="inventory = 통계 xlsx 1,283행(기본·DB 적재) / "
                        "archive = 원본 폴더 6,038 파일 실측(보고만)")
    p.add_argument("--dxf-features", action="store_true",
                   help="DXF 실측 Feature 를 EST_CAD_FEATURES 에 적재한다 "
                        "(기본은 적재하지 않는다 — check_ingest ⑤ 가 합성으로 판정한다)")
    p.add_argument("--dxf-limit", type=int, default=None, help="DXF 실측을 앞 N건만 (시험용)")
    a = p.parse_args()

    if a.source == "archive":
        payload = archive_report(dxf_limit=a.dxf_limit, write_json=not a.report)
        if a.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
        return 0 if payload else 1

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
    print("단 `.dxf` 는 예외다 — 순수 텍스트라 group code 로 읽힌다(D-110-b). "
          f"이 인벤토리의 dxf 는 {st['ext'].get('dxf', 0)} 건 / 전체 {st['total']:,} 건이다. "
          "`--source archive` 로 원본 실측을 본다.")
    if a.dxf_features:
        print()
        print("═══ DXF 실측 Feature 적재 (`--dxf-features`) ═══════════════════")
        store_dxf(a.dxf_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
