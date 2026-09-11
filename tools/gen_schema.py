#!/usr/bin/env python
"""SF-TD5(design.json) → db/schema.sql 생성기.

goal.md §5 아키텍트: schema.sql 은 손으로 고치지 않는다. 여기서만 바뀐다.
TD5 `details[*].columns` 행 = [한글명, 영문명, 타입, PK, FK, NULL, 비고]
생성 중 발견한 TD5 결함은 stderr 로 보고하고 decisions.md 에 올린다(고치지 않는다).
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design" / "design.json"
OUT = ROOT / "db" / "schema.sql"

FK_PAT = re.compile(r"FK\s*:?\s*([A-Z_]+)")

# TD5 비고가 "그룹 내 Unique" / "구분 내 Unique" 로 적은 것은 단일 컬럼 유니크가 아니다.
# 범위 컬럼을 여기 명시한다(추측하지 않는다). 새로 생기면 여기에 적는다.
SCOPED_UNIQUE: dict[tuple[str, str], str] = {
    ("BAS_COMMON_CODES", "CODE_VALUE"): "CODE_GROUP",   # "그룹 내 Unique(중복 불가)"
    ("SYS_CONFIGS", "CONFIG_KEY"): "CONFIG_TYPE",       # "구분 내 Unique"
}
# TD5 는 논리설계라 BIGSERIAL 로 적혀 있다. FK 가 가리키는 물리 타입은 bigint 다.
PK_PHYSICAL = "BIGINT"


def load_tables() -> list[dict]:
    return json.loads(DESIGN.read_text())["td5"]["details"]


def pk_of(table: dict) -> str | None:
    for c in table["columns"]:
        if c[3].strip() == "Y":
            return c[1].strip()
    return None


def main() -> int:
    tables = load_tables()
    by_id = {t["id"]: t for t in tables}
    defects: list[str] = []

    # ── FK 대상·타입 검사 (TD5 결함 탐지) ──────────────────────────────
    edges: dict[str, set[str]] = defaultdict(set)
    fks: list[tuple[str, str, str, str]] = []  # (표, 컬럼, 대상표, 대상PK)
    for t in tables:
        for c in t["columns"]:
            if c[4].strip() != "Y":
                continue
            m = FK_PAT.search(c[6] or "")
            if not m:
                defects.append(f"{t['id']}.{c[1]}: FK='Y' 인데 비고에 대상 테이블이 없다")
                continue
            target = m.group(1)
            if target not in by_id:
                defects.append(f"{t['id']}.{c[1]}: FK 대상 '{target}' 이 TD5 68표에 없다")
                continue
            tpk = pk_of(by_id[target])
            if tpk is None:
                defects.append(f"{t['id']}.{c[1]}: 대상 '{target}' 에 PK 가 없다")
                continue
            ctype = c[2].strip().upper()
            if ctype != PK_PHYSICAL:
                # 코드성 FK(VARCHAR → BAS_COMMON_CODES) 는 TD5 의 의도적 표기다.
                # 물리 FK 제약을 걸 수 없으므로 결함이 아니라 '제약 미생성' 으로 남긴다.
                defects.append(
                    f"{t['id']}.{c[1]}: FK 타입 {ctype} ≠ 대상 {target}.{tpk} 의 {PK_PHYSICAL}"
                    " → 물리 FK 제약 미생성(코드성 참조)"
                )
                continue
            fks.append((t["id"], c[1].strip(), target, tpk))
            edges[t["id"]].add(target)

    # ── FK 안전 순서 (위상 정렬, 순환은 알파벳순으로 끊는다) ───────────
    order: list[str] = []
    seen: set[str] = set()
    stack: set[str] = set()

    def visit(tid: str) -> None:
        if tid in seen:
            return
        if tid in stack:  # 순환 — ALTER 단계에서 FK 를 붙이므로 문제없다
            return
        stack.add(tid)
        for dep in sorted(edges[tid]):
            visit(dep)
        stack.discard(tid)
        seen.add(tid)
        order.append(tid)

    for tid in sorted(by_id):
        visit(tid)

    # ── SQL ────────────────────────────────────────────────────────────
    lines: list[str] = [
        "-- 경동글로벌텍 제조AI 시스템 (SF26179182) — 스키마",
        "-- tools/gen_schema.py 가 SF-TD5(design.json)에서 생성한다. 손으로 고치지 않는다.",
        f"-- 테이블 {len(tables)} · 컬럼 {sum(len(t['columns']) for t in tables)}"
        f" · FK 제약 {len(fks)}",
        "",
        "CREATE EXTENSION IF NOT EXISTS vector;",
        "",
    ]

    for tid in order:
        t = by_id[tid]
        lines.append(f"-- {t['id']} — {t.get('name', '')}")
        lines.append(f"CREATE TABLE {t['id']} (")
        cols: list[str] = []
        for c in t["columns"]:
            ko, en, typ, pk, _fk, nul, note = (x.strip() for x in c)
            sql_type = "BIGSERIAL" if pk == "Y" else typ
            parts = [f"    {en:<24} {sql_type}"]
            if pk == "Y":
                parts.append("PRIMARY KEY")
            else:
                if nul == "N":
                    parts.append("NOT NULL")
                if "Unique" in note and (t["id"], en) not in SCOPED_UNIQUE:
                    parts.append("UNIQUE")
            cols.append((" ".join(parts), ko))
        for i, (sql, ko) in enumerate(cols):
            comma = "," if i < len(cols) - 1 else ""
            # 쉼표는 반드시 주석 앞에 둔다 — 뒤에 두면 '--' 가 쉼표를 삼킨다.
            lines.append(f"{sql}{comma}  -- {ko}")
        lines.append(");")
        lines.append("")

    lines.append("-- ── 범위 유니크 (TD5 비고 '그룹 내/구분 내 Unique') ──")
    for (tid, col), scope in sorted(SCOPED_UNIQUE.items()):
        if tid not in by_id:
            defects.append(f"SCOPED_UNIQUE 에 적힌 {tid} 이 TD5 68표에 없다")
            continue
        names = {c[1].strip() for c in by_id[tid]["columns"]}
        if col not in names or scope not in names:
            defects.append(f"{tid}: 범위 유니크 컬럼 {col}/{scope} 이 TD5 에 없다")
            continue
        lines.append(
            f"ALTER TABLE {tid} ADD CONSTRAINT uq_{tid.lower()}_{col.lower()}"
            f" UNIQUE ({scope}, {col});"
        )
    lines.append("")

    lines.append("-- ── 외래키 (컬럼 정의 뒤에 붙여 순환 참조를 피한다) ──")
    for src, col, tgt, tpk in sorted(fks):
        lines.append(
            f"ALTER TABLE {src} ADD CONSTRAINT fk_{src.lower()}_{col.lower()}"
            f" FOREIGN KEY ({col}) REFERENCES {tgt}({tpk});"
        )
    lines.append("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines))

    print(
        f"생성: {OUT.relative_to(ROOT)} — 테이블 {len(tables)}"
        f" · 컬럼 {sum(len(t['columns']) for t in tables)} · FK 제약 {len(fks)}"
    )
    if defects:
        print(f"\nTD5 결함·주의 {len(defects)}건 (고치지 않는다 — decisions.md 에 올린다):", file=sys.stderr)
        for d in defects:
            print(f"  · {d}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
