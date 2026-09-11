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


def real_now() -> datetime:
    """**실시각** — DB 서버 시계(`select now()`)를 그대로 읽는다.

    `anchor()` 와 섞지 않는다. 앵커는 시드·시뮬레이터·학습의 **생성 기준일**이고(§10-3),
    이 함수는 "지금 몇 시인가" 다. 둘이 답해야 하는 물음이 다르다 —
    수집이 **지금** 끊겼는지(G-12), 비밀번호를 바꾼 지 며칠 됐는지, 작업이 언제 시작·종료했는지.

    파이썬 `datetime.now()` 대신 DB 시계를 쓰는 이유: 저장되는 시각(`CREATED_DT` 등)이 전부
    SQL `now()` 로 찍히므로 **비교 기준도 같은 시계**여야 오차가 생기지 않는다.
    실시각을 읽는 자리는 여기 하나다 — 생성 기준일로 이 함수를 쓰면 §10-3 위반이다.
    """
    import conn
    return conn.q1("select now()::timestamp as t")["t"]


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
