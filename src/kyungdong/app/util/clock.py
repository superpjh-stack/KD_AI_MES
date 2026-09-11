"""시간 앵커 (goal.md §10-3) — **`date.today()` 금지.**

직전 사업에서 합성 데이터를 `date.today()` 기준으로 만들었다가 날짜가 바뀔 때마다 ML 수치가
흔들렸다(R² 0.90 ↔ 0.86). 생성 기준일을 `SYS_CONFIGS` 에 못 박고 모든 시드·시뮬레이터·학습이 이것만 쓴다.
`make db-reset` 은 앵커를 새로 발급하므로 수치는 분포 안에서 움직인다 — 앵커 5개 분포를 함께 보고한다.
"""
from __future__ import annotations

from datetime import datetime

CONFIG_TYPE = "시스템설정"
CONFIG_KEY = "TIME_ANCHOR"


def anchor() -> datetime:
    """앵커가 없으면 **터진다.** 조용히 오늘 날짜로 대체하지 않는다."""
    import conn
    row = conn.q1(
        "select CONFIG_VALUE from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
        (CONFIG_TYPE, CONFIG_KEY),
    )
    if not row or not row["config_value"]:
        raise RuntimeError(
            "시간 앵커가 없다 — `make db-seed` 로 발급한다. date.today() 로 대체하지 않는다(§10-3)"
        )
    return datetime.fromisoformat(row["config_value"])


def issue(value: datetime) -> None:
    """시드가 발급한다. 멱등 — 같은 값으로 다시 써도 행이 늘지 않는다(G-07)."""
    import conn
    conn.x(
        "insert into SYS_CONFIGS (CONFIG_TYPE, CONFIG_KEY, CONFIG_VALUE, USE_YN, DESCRIPTION, CREATED_DT) "
        "values (%s, %s, %s, 'Y', %s, now()) "
        "on conflict (CONFIG_TYPE, CONFIG_KEY) do update set CONFIG_VALUE = excluded.CONFIG_VALUE, UPDATED_DT = now()",
        (CONFIG_TYPE, CONFIG_KEY, value.isoformat(timespec="seconds"),
         "시드·시뮬레이터·학습의 생성 기준일 (goal.md §10-3). date.today() 금지"),
    )
