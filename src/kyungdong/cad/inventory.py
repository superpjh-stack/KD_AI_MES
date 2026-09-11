"""도면 아카이브 정제 경로 (D-03) — **실측 인벤토리만 읽는다.**

정본 자료: `docs/cad/경동글로벌텍_CAD도면_제품별정리.xlsx` 시트 `CAD도면_제품별정리`
(대분류·제품명·파일명·확장자·수정일자·크기(KB)·파일경로 — **1,283행**).

D-03 이 적은 실태를 그대로 재현한다.
  · 파일명 중복 183건 · 0KB 손상 4건
  · 제품당 편차 최대 184 / 최소 1 / 중앙값 5 · 도면 1건뿐인 제품 9개
  · **발행일·개정일 메타데이터가 없다** → `mtime` 으로 대체한다(TD5 `FILE_MTIME` 비고)

정제 규칙(TD5 `DAT_DATASET_ITEMS.DEDUP_KEY` 비고 = 「도면번호+버전+고객사」)
  · 0KB 는 제외한다.
  · 같은 (도면번호, 버전, 고객사) 는 처음 1건만 등록하고 나머지는 제외한다.
  · **고객사 메타데이터가 인벤토리에 없다**(D-03) — 지어내지 않고 `고객사미확보(D-03)` 로 둔다.
    그래서 실제 키는 (도면번호, 버전) 로 축약된다. 이 한계를 화면·리포트에 그대로 적는다.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
INVENTORY_XLSX = ROOT / "docs" / "cad" / "경동글로벌텍_CAD도면_제품별정리.xlsx"
INVENTORY_SHEET = "CAD도면_제품별정리"

CUSTOMER_UNKNOWN = "고객사미확보(D-03)"

# TD5 `EST_CAD_DRAWINGS.FILE_TYPE` 비고 — DWG/CAD/DXF/PDF
FILE_TYPES = ("DWG", "CAD", "DXF", "PDF")

EXCLUDE_ZERO = "0KB 손상"
EXCLUDE_DUP = "파일명 중복"

# 파일명 끝의 리비전 토큰 — 'A'~'Z' 한 글자 · 'Rev.2' · 'R3' · 'v1.2'
_REV = re.compile(r"[ _\-(]*(?:(?:rev\.?|ver\.?|v|r)\s*([0-9]+(?:\.[0-9]+)?)|([A-Z]))\)?$", re.I)
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class InventoryFile:
    no: int
    category: str          # 대분류
    product: str           # 제품명
    file_name: str
    ext: str
    mtime: datetime | None
    size_kb: float
    path: str

    @property
    def file_type(self) -> str:
        e = (self.ext or "").upper()
        return e if e in FILE_TYPES else (e or "")

    @property
    def size_bytes(self) -> int:
        return int(round(self.size_kb * 1024))


@dataclass(frozen=True)
class Cleaned:
    src: InventoryFile
    drawing_no: str
    revision: str
    customer: str
    dedup_key: str
    keep: bool
    reason: str          # 제외 사유 ('' 이면 등록)


def split_revision(file_name: str) -> tuple[str, str]:
    """파일명에서 도면번호와 버전을 뗀다. 버전 토큰이 없으면 버전은 빈 문자열이다."""
    stem = Path(file_name).stem
    stem = _WS.sub(" ", stem).strip()
    m = _REV.search(stem)
    if not m:
        return stem, ""
    rev = (m.group(1) or m.group(2) or "").upper()
    return stem[: m.start()].strip(" _-") or stem, rev


def dedup_key(drawing_no: str, revision: str, customer: str | None) -> str:
    """TD5 `DEDUP_KEY` = 도면번호+버전+고객사. 고객사가 없으면 **없다고 적는다.**"""
    return f"{_WS.sub(' ', drawing_no).strip().casefold()}|{revision.upper()}|{customer or CUSTOMER_UNKNOWN}"


# 고객사 자리를 무엇으로 채울지. 정본에 고객사 열이 없으므로 **지어내지 않고** 둘 중 하나를 고른다.
#   "product" — 제품/프로젝트 폴더명을 고객사 축의 **대체 표기**로 쓴다 (D-03 · D-41 과 같은 방식)
#   "none"    — 고객사 없이 (도면번호+버전) 으로만 본다. 다른 고객사의 동명 도면이 합쳐진다
SCOPES = ("product", "none")


def read_inventory(path: Path | None = None) -> list[InventoryFile]:
    """실측 인벤토리를 읽는다. 파일이 없으면 **빈 리스트가 아니라 예외**다(§10-9)."""
    import openpyxl

    src = path or INVENTORY_XLSX
    if not src.exists():
        raise FileNotFoundError(f"도면 인벤토리가 없다: {src} — docs/cad/ 자료를 확인한다 (D-03)")
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    try:
        ws = wb[INVENTORY_SHEET]
        out: list[InventoryFile] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None or row[3] in (None, ""):
                continue
            mtime = row[5] if isinstance(row[5], datetime) else None
            try:
                size = float(row[6]) if row[6] not in (None, "") else 0.0
            except (TypeError, ValueError):
                size = 0.0
            out.append(InventoryFile(
                no=int(row[0]) if row[0] else len(out) + 1,
                category=str(row[1] or ""), product=str(row[2] or ""),
                file_name=str(row[3]), ext=str(row[4] or "").lower(),
                mtime=mtime, size_kb=size, path=str(row[7] or ""),
            ))
        return out
    finally:
        wb.close()


def clean(files: Iterable[InventoryFile], scope: str = "product") -> list[Cleaned]:
    """정제 경로. 순서를 유지하고 **처음 1건만** 등록한다."""
    if scope not in SCOPES:
        raise ValueError(f"scope 는 {SCOPES} 중 하나다: {scope!r}")
    seen: set[str] = set()
    out: list[Cleaned] = []
    for f in files:
        no, rev = split_revision(f.file_name)
        customer = f"{f.product}[대체 표기 D-03]" if scope == "product" else CUSTOMER_UNKNOWN
        key = dedup_key(no, rev, customer if scope == "product" else None)
        if f.size_bytes <= 0:
            out.append(Cleaned(f, no, rev, customer, key, False, EXCLUDE_ZERO))
            continue
        if key in seen:
            out.append(Cleaned(f, no, rev, customer, key, False, EXCLUDE_DUP))
            continue
        seen.add(key)
        out.append(Cleaned(f, no, rev, customer, key, True, ""))
    return out


def stats(files: list[InventoryFile], cleaned: list[Cleaned] | None = None) -> dict[str, Any]:
    """실측값만 돌려준다. 목표치·추정치를 섞지 않는다(D-03)."""
    cleaned = cleaned if cleaned is not None else clean(files)
    by_product = Counter(f.product for f in files)
    name_counts = Counter(f.file_name for f in files)
    counts = sorted(by_product.values())
    excluded = [c for c in cleaned if not c.keep]
    return {
        "total": len(files),
        "products": len(by_product),
        "file_name_dup": sum(v - 1 for v in name_counts.values() if v > 1),
        "zero_byte": sum(1 for f in files if f.size_bytes <= 0),
        "max_per_product": max(counts) if counts else 0,
        "min_per_product": min(counts) if counts else 0,
        "median_per_product": statistics.median(counts) if counts else 0,
        "single_drawing_products": sum(1 for v in by_product.values() if v == 1),
        "ext": dict(Counter(f.ext for f in files)),
        "category": dict(Counter(f.category for f in files)),
        "kept": sum(1 for c in cleaned if c.keep),
        "excluded": len(excluded),
        "excluded_by_reason": dict(Counter(c.reason for c in excluded)),
        "no_mtime": sum(1 for f in files if f.mtime is None),
        "customer_meta": CUSTOMER_UNKNOWN,
    }
