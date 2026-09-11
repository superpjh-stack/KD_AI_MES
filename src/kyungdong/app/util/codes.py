"""D-32 코드성 참조 검증 — **DB 가 막아주지 않는 29건은 여기서 막는다.**

TD5 비고는 `FK: BAS_COMMON_CODES` 를 가리키지만 컬럼이 `VARCHAR` 라 물리 FK 를 걸 수 없다.
실제 의도는 `BAS_COMMON_CODES(CODE_GROUP, CODE_VALUE)` 참조이고 그 조합에 복합 UNIQUE 가 있다(D-34).
대상 29컬럼 목록은 `contracts/db-schema.md` §3.
"""
from __future__ import annotations

import re
import sys
from functools import cache
from pathlib import Path

from .. import design
from . import http

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "db"))

_FK_CODE = re.compile(r"FK\s*:?\s*BAS_COMMON_CODES")

# 컬럼 → 코드 그룹. TD5 가 그룹명을 적어 두지 않았으므로 **컬럼 의미로 정한다**(추측이 아니라 명시).
# 새 컬럼이 생기면 여기 적는다 — 빠지면 `code_group_for()` 가 None 을 돌려주고 검증이 차단된다.
COLUMN_GROUP: dict[str, str] = {
    "PRODUCT_GROUP": "제품군",       # 반응기·교반기·진공건조기·누체필터·저장탱크
    "PROCESS_CODE": "공정",          # 10공정
    "CURRENT_PROCESS": "공정",
    "CAUSE_PROCESS": "공정",
    "OUTSOURCE_STEP": "외주구간",
    "ITEM_CODE": "품목",
    "MATERIAL": "재질",
    "LOCATION_CODE": "보관위치",
    "CUSTOMER_CODE": "고객사",
    "SUPPLY_TYPE": "공급구분",       # 원자재·부자재·외주
    "EQUIP_CODE": "설비",
    "INSPECT_TYPE": "검사구분",
    "DEFECT_TYPE": "불량유형",
    "CLAIM_TYPE": "클레임유형",
    "TARGET_CODE": "원가대상",
}


@cache
def code_columns() -> dict[tuple[str, str], str]:
    """(표, 컬럼) → 코드 그룹. TD5 에서 실측한다."""
    out: dict[tuple[str, str], str] = {}
    for tid in design.tables():
        for c in design.columns_of(tid):
            if c["fk"] == "Y" and c["type"].upper() != "BIGINT" and _FK_CODE.search(c["note"]):
                out[(tid, c["name"])] = COLUMN_GROUP.get(c["name"], "")
    return out


def code_group_for(table: str, column: str) -> str | None:
    """모르는 컬럼은 `None` — 열어주지 않고 호출자가 차단한다."""
    return code_columns().get((table, column)) or None


def unmapped_columns() -> list[tuple[str, str]]:
    """COLUMN_GROUP 에 아직 안 적힌 코드성 컬럼. 테스트가 0건을 단언한다."""
    return sorted(k for k, v in code_columns().items() if not v)


def validate_code(group: str, value: str | None, *, allow_empty: bool = False) -> bool:
    """`BAS_COMMON_CODES` 에 (그룹, 값) 이 있고 사용중인지. 없으면 False → 호출자가 422."""
    if value is None or value == "":
        return allow_empty
    import conn  # 지연 임포트 — util 이 db 를 끌고 들어오지 않게
    row = conn.q1(
        "select 1 as ok from BAS_COMMON_CODES "
        "where CODE_GROUP = %s and CODE_VALUE = %s and USE_YN = 'Y'",
        (group, value),
    )
    return row is not None


def require_code(table: str, column: str, value: str | None, *, allow_empty: bool = False) -> None:
    """저장 전에 부른다. 어기면 **422**(§2.5 '코드 중복/필수값' 계열)."""
    group = code_group_for(table, column)
    if group is None:
        raise http.fail(
            "validation",
            f"{table}.{column} 의 코드 그룹이 정의되지 않았다 — util/codes.py COLUMN_GROUP 에 추가하라 (D-32)",
        )
    if not validate_code(group, value, allow_empty=allow_empty):
        raise http.fail("validation", f"{table}.{column}: 코드 '{value}' 가 '{group}' 그룹에 없다 (D-32)")
