"""QA2 — G-01 · G-02 엄밀 대조 회귀 (68표 · 762컬럼 · 이름 · 타입).

`tools/gate.py` 는 **개수만** 센다. 여기서는 `tools/check_schema.py` 를 그대로 불러
TD5 정본(`design.columns_of`) ↔ `information_schema` 를 **이름·타입까지** 맞춘다.
검사기와 테스트가 같은 코드를 쓰므로 로직이 갈라지지 않는다(§10-16).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT))

import conn                                              # noqa: E402
from kyungdong.app import design                         # noqa: E402
from tools import check_schema                           # noqa: E402


def test_G01_테이블_68개가_정본과_이름까지_같다():
    want = {t.upper() for t in design.tables()}
    got = {t.upper() for t in check_schema.db_columns()}
    assert len(want) == 68, f"정본 테이블이 68이 아니다: {len(want)}"
    assert want - got == set(), f"DB 에 없는 표: {sorted(want - got)}"
    assert got - want == set(), f"정본에 없는 표: {sorted(got - want)}"


def test_G02_컬럼_762개가_이름과_타입까지_같다():
    got = check_schema.db_columns()
    total = mismatch = 0
    bad: list[str] = []
    for tid in sorted(design.tables()):
        have = got[tid.lower()]
        for col in design.columns_of(tid):          # 정본 함수 직접 호출 (§10-16)
            total += 1
            name = col["name"].strip().lower()
            assert name in have, f"{tid}.{col['name']} 이 DB 에 없다"
            expect = check_schema.pg_type(col["type"])
            assert expect is not None, (
                f"{tid}.{col['name']} 의 TD5 타입 {col['type']!r} 을 대조할 규칙이 없다 — "
                "모르는 타입을 PASS 로 넘기지 않는다")
            if have[name]["type"] != expect:
                mismatch += 1
                bad.append(f"{tid}.{col['name']}: TD5 {col['type']}→{expect} ≠ DB {have[name]['type']}")
    assert total == 762, f"정본 컬럼 합계가 762 가 아니다: {total}"
    assert mismatch == 0, "타입 불일치: " + " / ".join(bad[:10])


def test_DB_에만_있는_컬럼이_없다():
    got = check_schema.db_columns()
    extra: list[str] = []
    for tid in sorted(design.tables()):
        want = {c["name"].strip().lower() for c in design.columns_of(tid)}
        extra += [f"{tid}.{c}" for c in got[tid.lower()] if c not in want]
    assert extra == [], f"정본에 없는 컬럼: {extra}"


def test_information_schema_합계도_68_762_다():
    """게이트가 쓰는 분모(개수)와 엄밀 대조의 분모가 같은지 — 두 경로가 갈리면 안 된다."""
    assert conn.table_count() == 68
    assert conn.column_count() == 762


def test_모든_TD5_타입이_대조_규칙을_가진다():
    """미대조 타입 0건. 새 타입이 들어오면 여기서 먼저 터진다."""
    unknown = {c["type"] for tid in design.tables() for c in design.columns_of(tid)
               if check_schema.pg_type(c["type"]) is None}
    assert unknown == set(), f"대조 규칙이 없는 TD5 타입: {sorted(unknown)}"


def test_컬럼_순서와_NOT_NULL_도_정본과_같다():
    """G-01·G-02 판정 항목은 아니지만(개수·이름·타입) 어긋나면 드러나야 한다."""
    got = check_schema.db_columns()
    ord_bad, null_bad = [], []
    for tid in sorted(design.tables()):
        have = got[tid.lower()]
        for i, col in enumerate(design.columns_of(tid), start=1):
            h = have[col["name"].strip().lower()]
            if h["ord"] != i:
                ord_bad.append(f"{tid}.{col['name']} {h['ord']}≠{i}")
            want_nn = col["pk"].strip() == "Y" or col["nullable"].strip().upper() == "N"
            if h["notnull"] != want_nn:
                null_bad.append(f"{tid}.{col['name']}")
    assert ord_bad == [], f"컬럼 순서 불일치: {ord_bad[:10]}"
    assert null_bad == [], f"NOT NULL 불일치: {null_bad[:10]}"
