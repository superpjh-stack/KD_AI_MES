"""계약·DB 접속 계층 검증 (아키텍트 웨이브 A).

goal.md §4.1: **코드와 다르면 코드가 맞다.** 계약 3종은 생성 파일이므로 재생성해도 내용이
그대로여야 한다 — 달라지면 누군가 손으로 고쳤거나 정본이 바뀐 것이다(D-43).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                        # noqa: E402
from kyungdong.app import design                   # noqa: E402
from kyungdong.app.settings import settings        # noqa: E402

GENERATORS = ("gen_screen_map.py", "gen_db_contract.py", "gen_api_contract.py")
CONTRACTS = ("screen-map.md", "db-schema.md", "api-contract.md")


@pytest.mark.parametrize("name", CONTRACTS)
def test_계약이_존재한다(name):
    assert (ROOT / "contracts" / name).exists()


def test_계약을_다시_뽑아도_같다():
    """손으로 고쳤거나 정본이 바뀌면 여기서 잡힌다 (D-43)."""
    before = {n: (ROOT / "contracts" / n).read_text() for n in CONTRACTS}
    for g in GENERATORS:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / g)],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, f"{g}: {r.stderr[-400:]}"
    after = {n: (ROOT / "contracts" / n).read_text() for n in CONTRACTS}
    drifted = [n for n in CONTRACTS if before[n] != after[n]]
    assert not drifted, f"계약이 코드와 어긋났다 — `make contracts` 로 갱신하라: {drifted}"


def test_interfaces_는_손으로_쓰는_문서다():
    txt = (ROOT / "contracts" / "interfaces.md").read_text()
    for sig in ("q(sql", "q1(sql", "tx()", "render(request", "can_approve",
                "fail(key", "validate_code", "anchor()", "SCREENS"):
        assert sig in txt, f"interfaces.md 에 {sig} 시그니처가 없다"


def test_db_가_살아_있고_규모가_맞다():
    assert conn.alive()
    assert conn.table_count() == 68
    assert conn.column_count() == 762


def test_q1_은_0건일때_None_이다():
    """0건은 정상이고 화면은 '미수집' 문구를 렌더한다 (G-11). 예외가 아니다."""
    assert conn.q1("select 1 as n where false") is None


def test_파라미터가_바인딩된다():
    row = conn.q1("select %s::int as n", (7,))
    assert row and row["n"] == 7


def test_DB가_죽으면_503이다_빈배열이_아니다():
    """조용한 실패 금지 (G-30 · §2.5). 화면이 '데이터 없음' 으로 보이면 결함이다."""
    old = os.environ.get("KYUNGDONG_PG_DSN")
    os.environ["KYUNGDONG_PG_DSN"] = "postgresql://127.0.0.1:1/nope"
    settings.cache_clear()
    try:
        with pytest.raises(Exception) as e:
            conn.q("select 1")
        assert getattr(e.value, "status_code", None) == 503
        assert e.value.detail["key"] == "db_down"
    finally:
        if old is None:
            os.environ.pop("KYUNGDONG_PG_DSN", None)
        else:
            os.environ["KYUNGDONG_PG_DSN"] = old
        settings.cache_clear()
    assert conn.alive(), "정리 후 DB 가 다시 살아야 한다"


def test_D32_코드성FK가_계약에_전건_적혀_있다():
    """DB 가 막아주지 않는 29건이 누락되면 개발자가 검증을 빠뜨린다."""
    import re
    txt = (ROOT / "contracts" / "db-schema.md").read_text()
    code_fk = [
        (tid, c["name"]) for tid in design.tables() for c in design.columns_of(tid)
        if c["fk"] == "Y" and c["type"].upper() != "BIGINT"
        and re.search(r"FK\s*:?\s*BAS_COMMON_CODES", c["note"])
    ]
    assert len(code_fk) == 29
    missing = [f"{t}.{c}" for t, c in code_fk if f"`{t}` | `{c}`" not in txt]
    assert not missing, f"db-schema.md 에 빠진 코드성 FK: {missing}"


def test_런타임전용표는_짐작하지_않는다():
    """이름만 보고 런타임 전용이라 단정하면 G-11 판정이 틀린다."""
    txt = (ROOT / "contracts" / "db-schema.md").read_text()
    assert "### 7.1 시드 여부 미정" in txt
    for t in ("INV_MATERIAL_HISTORY", "PRC_PROCESS_HISTORIES", "PRC_CONDITION_DEVIATIONS"):
        assert f"`{t}` |" in txt, f"{t} 이 '미정' 목록에 없다"
