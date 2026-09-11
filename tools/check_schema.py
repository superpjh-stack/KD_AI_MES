#!/usr/bin/env python
"""G-01 · G-02 **엄밀 대조** — TD5 `details[*].columns` ↔ `information_schema` (QA2).

`tools/gate.py` 는 **개수만** 센다. 68/762 가 맞아도 컬럼 **이름·타입**이 어긋날 수 있다.
여기서는 정본 함수 `design.columns_of(tid)` 를 **직접 부르고**(§10-16 로직 복제 금지)
DB 의 실제 컬럼과 이름·타입까지 한 건씩 맞춘다.

판정 규칙 (goal.md §4.3 · §10)
  · 게이트를 낮추지 않는다. 못 재면 `판정 불가` 이지 PASS 가 아니다.
  · 측정 중 정본(design.json)·스키마가 바뀌면 FAIL 이 아니라 `판정 불가`(§10-17).
  · 게이트별 판정 줄을 찍는다(§10-6) — 그룹 종료코드 하나로 뭉개지 않는다.

타입 대조는 `format_type(atttypid, atttypmod)` 의 정규 표기와 맞춘다.
  BIGSERIAL → bigint (PK 물리 타입 — `tools/gen_schema.py` PK_PHYSICAL 과 같은 규약)
  INT → integer · CHAR(n) → character(n) · VARCHAR(n) → character varying(n)
  TIMESTAMP → timestamp without time zone · VECTOR(n) → vector(n)
**모르는 타입은 조용히 통과시키지 않는다** — `미대조` 로 세고 FAIL 사유에 넣는다.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                        # noqa: E402
from kyungdong.app import design                   # noqa: E402

PASS, FAIL, BLOCKED = "PASS", "FAIL", "판정 불가"

# TD5 논리 타입 → PostgreSQL `format_type` 정규 표기
_SIMPLE = {
    "BIGSERIAL": "bigint",          # PK 는 BIGSERIAL 로 만들지만 물리 타입은 bigint 다
    "BIGINT": "bigint",
    "INT": "integer",
    "INTEGER": "integer",
    "TEXT": "text",
    "DATE": "date",
    "JSONB": "jsonb",
    "TIMESTAMP": "timestamp without time zone",
}
_PARAM = re.compile(r"^([A-Z]+)\s*\(\s*([0-9]+)\s*(?:,\s*([0-9]+)\s*)?\)$")
_PARAM_MAP = {
    "VARCHAR": "character varying",
    "CHAR": "character",
    "NUMERIC": "numeric",
    "VECTOR": "vector",
}


def pg_type(td5_type: str) -> str | None:
    """TD5 타입 문자열 → format_type 표기. 모르면 `None` (조용히 통과시키지 않는다)."""
    t = (td5_type or "").strip().upper()
    if t in _SIMPLE:
        return _SIMPLE[t]
    m = _PARAM.match(t)
    if not m:
        return None
    base, a, b = m.group(1), m.group(2), m.group(3)
    if base not in _PARAM_MAP:
        return None
    name = _PARAM_MAP[base]
    return f"{name}({a},{b})" if b else f"{name}({a})"


def canon_fingerprint() -> str:
    """정본(design.json) 지문 — 측정 전후가 다르면 `판정 불가`(§10-17)."""
    return hashlib.sha256((ROOT / "docs" / "design" / "design.json").read_bytes()).hexdigest()[:12]


def db_fingerprint() -> str:
    """DB 스키마 지문 — 측정 중 스키마가 바뀌었는지 본다(§10-17)."""
    rows = conn.q(
        "select c.relname as t, a.attname as c, format_type(a.atttypid, a.atttypmod) as ty "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "join pg_attribute a on a.attrelid = c.oid "
        "where n.nspname = 'public' and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped "
        "order by 1, 2"
    )
    blob = "\n".join(f"{r['t']}.{r['c']}:{r['ty']}" for r in rows)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def db_columns() -> dict[str, dict[str, dict]]:
    """실제 컬럼 — {표(소문자): {컬럼(소문자): {type, notnull, ord}}}."""
    rows = conn.q(
        "select c.relname as table_name, a.attname as column_name, a.attnum as ord, "
        "       format_type(a.atttypid, a.atttypmod) as data_type, a.attnotnull as notnull "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "join pg_attribute a on a.attrelid = c.oid "
        "where n.nspname = 'public' and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped "
        "order by c.relname, a.attnum"
    )
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        out.setdefault(r["table_name"], {})[r["column_name"]] = {
            "type": r["data_type"], "notnull": bool(r["notnull"]), "ord": int(r["ord"]),
        }
    return out


def main() -> int:
    canon_before, db_before = canon_fingerprint(), db_fingerprint()

    want_tables = design.tables()                      # 정본 함수를 직접 부른다 (§10-16)
    want_cols_total = sum(len(design.columns_of(t)) for t in want_tables)
    got = db_columns()

    # information_schema 로도 한 번 더 센다 — gate.py 와 같은 분모를 쓰는지 확인한다
    isc_tables = conn.q1("select count(*) as n from information_schema.tables "
                         "where table_schema = 'public'")["n"]
    isc_cols = conn.q1("select count(*) as n from information_schema.columns "
                       "where table_schema = 'public'")["n"]

    detail: list[str] = []

    # ── G-01 테이블 집합 ──────────────────────────────────────────────
    want_ids = {t.upper() for t in want_tables}
    got_ids = {t.upper() for t in got}
    missing = sorted(want_ids - got_ids)
    extra = sorted(got_ids - want_ids)
    g01_ok = not missing and not extra and len(got) == len(want_tables) == int(isc_tables)
    for t in missing:
        detail.append(f"  [G-01] 정본에 있고 DB 에 없다: {t}")
    for t in extra:
        detail.append(f"  [G-01] DB 에 있고 정본에 없다: {t}")

    # ── G-02 컬럼 이름·타입 ──────────────────────────────────────────
    name_miss = name_extra = type_bad = order_bad = unknown_type = null_bad = 0
    measured_cols = 0
    for tid in sorted(want_ids & got_ids):
        want = design.columns_of(tid)                  # 정본 함수 (§10-16)
        have = got[tid.lower()]
        measured_cols += len(want)
        want_names = [c["name"].strip().lower() for c in want]
        for i, (col, lname) in enumerate(zip(want, want_names), start=1):
            if lname not in have:
                name_miss += 1
                detail.append(f"  [G-02] {tid}.{col['name']} — DB 에 없다")
                continue
            h = have[lname]
            expect = pg_type(col["type"])
            if expect is None:
                unknown_type += 1
                detail.append(
                    f"  [G-02] {tid}.{col['name']} — TD5 타입 {col['type']!r} 을 대조할 규칙이 없다"
                    " (검사기가 모르는 타입은 PASS 로 넘기지 않는다)")
            elif h["type"] != expect:
                type_bad += 1
                detail.append(
                    f"  [G-02] {tid}.{col['name']} — 타입 불일치: TD5 {col['type']}"
                    f"(→{expect}) ≠ DB {h['type']}")
            if h["ord"] != i:
                order_bad += 1
                detail.append(
                    f"  [G-02] {tid}.{col['name']} — 컬럼 순서 {h['ord']} ≠ TD5 {i}")
            # 부가 실측: NULL 허용. G-02 판정에는 넣지 않는다(게이트 정의는 이름·타입이다)
            want_notnull = col["pk"].strip() == "Y" or col["nullable"].strip().upper() == "N"
            if h["notnull"] != want_notnull:
                null_bad += 1
                detail.append(
                    f"  [부가] {tid}.{col['name']} — NOT NULL 실측 {h['notnull']}"
                    f" ≠ TD5 nullable={col['nullable']!r}")
        for lname in have:
            if lname not in want_names:
                name_extra += 1
                detail.append(f"  [G-02] {tid}.{lname} — DB 에만 있다(정본에 없는 컬럼)")

    g02_ok = (
        want_cols_total == int(isc_cols) == sum(len(c) for c in got.values())
        and name_miss == name_extra == type_bad == unknown_type == 0
    )

    canon_after, db_after = canon_fingerprint(), db_fingerprint()
    changed = (canon_before, db_before) != (canon_after, db_after)

    # ── 판정 줄 (§10-6) ──────────────────────────────────────────────
    if changed:
        v01 = v02 = BLOCKED
        m01 = m02 = "측정 중 정본 또는 스키마가 변경됐다 — FAIL 이 아니라 판정 불가다(§10-17)"
    else:
        v01 = PASS if g01_ok else FAIL
        m01 = (f"테이블 DB {len(got)} / information_schema {isc_tables} / TD5 {len(want_tables)}"
               f" · 누락 {len(missing)} · 초과 {len(extra)}")
        v02 = PASS if g02_ok else FAIL
        m02 = (f"컬럼 DB {sum(len(c) for c in got.values())} / information_schema {isc_cols}"
               f" / TD5 {want_cols_total} · 대조 {measured_cols} · 이름누락 {name_miss}"
               f" · 이름초과 {name_extra} · 타입불일치 {type_bad} · 미대조타입 {unknown_type}")

    print(f"정본 지문 design.json {canon_before} · DB 스키마 지문 {db_before}")
    print(f"G-01  {v01}  {m01}")
    print(f"G-02  {v02}  {m02}")
    print(f"부가  실측  컬럼 순서 불일치 {order_bad} · NOT NULL 불일치 {null_bad}"
          f"  (G-01·G-02 판정에는 넣지 않는다 — 게이트 정의는 개수·이름·타입이다)")
    if detail:
        print("\n불일치 상세")
        for line in detail[:200]:
            print(line)
        if len(detail) > 200:
            print(f"  … 외 {len(detail) - 200} 건")
    print(f"\nG-01 {v01} · G-02 {v02}")
    return 0 if v01 == PASS and v02 == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
