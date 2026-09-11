"""PLC 태그 매핑 — 사업계획서 2.7.1 이 적은 8종만 받는다.

「작업시간·수량·가동상태·알람·속도·압력·전류·온도」가 정본이 적은 전부다.
**여기 없는 태그는 받지 않는다**(422). 태그를 늘리려면 정본 근거를 먼저 찾는다.

`IF_PLC_SIGNALS.TAG_NAME` → `PRC_EQUIP_SIGNALS` 컬럼 → `DAT_TIMESERIES` 한 행.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tag:
    name: str        # IF_PLC_SIGNALS.TAG_NAME
    ko: str          # 사업계획서 2.7.1 표기
    column: str      # PRC_EQUIP_SIGNALS 컬럼명
    uom: str         # DAT_TIMESERIES.UOM
    numeric: bool    # 숫자값이면 CONVERTED_VALUE·시계열 적재 대상


TAGS: tuple[Tag, ...] = (
    Tag("RUN_MINUTE",     "작업시간",  "RUN_MINUTE",     "min",    True),
    Tag("PRODUCE_QTY",    "수량",     "PRODUCE_QTY",    "ea",     True),
    Tag("RUN_STATUS",     "가동상태",  "RUN_STATUS",     "",       False),
    Tag("ALARM_CODE",     "알람",     "ALARM_CODE",     "",       False),
    Tag("SPEED_VALUE",    "속도",     "SPEED_VALUE",    "mm/min", True),
    Tag("PRESSURE_VALUE", "압력",     "PRESSURE_VALUE", "bar",    True),
    Tag("CURRENT_VALUE",  "전류",     "CURRENT_VALUE",  "A",      True),
    Tag("TEMP_VALUE",     "온도",     "TEMP_VALUE",     "℃",      True),
)

BY_NAME: dict[str, Tag] = {t.name: t for t in TAGS}

# TD5 `PRC_EQUIP_SIGNALS.RUN_STATUS` 비고가 정한 어휘. 다른 값을 쓰지 않는다.
RUN_STATUSES: tuple[str, ...] = ("가동", "정지", "대기", "알람")

# TD5 `DAT_TIMESERIES.QUALITY_FLAG` 비고
QUALITY_FLAGS: tuple[str, ...] = ("정상", "노이즈", "결측")

# TD5 `IF_PLC_SIGNALS.IF_STATUS` 비고
IF_STATUSES: tuple[str, ...] = ("수신", "적재", "오류")


def tag(name: str) -> Tag | None:
    """모르는 태그는 `None` — 호출자가 422 로 막는다. 조용히 넘기지 않는다."""
    return BY_NAME.get(name)


def numeric_tags() -> tuple[Tag, ...]:
    return tuple(t for t in TAGS if t.numeric)
