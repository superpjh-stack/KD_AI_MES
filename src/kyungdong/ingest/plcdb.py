"""PLC 측 저장소 — **장비의 레지스터 메모리를 대신한다** (D-174).

도입기업이 **장비 IP 를 아직 주지 않았다**(D-169). 그래서 실물 PLC 를 붙일 수 없다.
그렇다고 수집 파이프라인을 못 돌리는 것은 아니다 — **PLC 쪽을 세워서** 돌린다.

**왜 SQLite 파일인가 — 우리 DB 가 아니어야 하기 때문이다.**
실물 구성은 `PLC 레지스터 → Gateway 폴링 → 수집 API → PostgreSQL` 이다. PLC 는 자기
메모리를 들고 있고 Gateway 가 **주기적으로 읽어 간다.** 시뮬레이터가 값을 만들어 곧장
`collector.ingest_batch()` 를 부르면 그 두 다리(**PLC 메모리 · Gateway 폴링**)가 통째로
빠지고, 그러면 **네트워크가 끊겼을 때 PLC 안에 값이 남아 있다가 복구 후 올라가는 것**을
시험할 수 없다. 파일을 `kyungdong_db` 밖에 두는 것이 요점이다 — 같은 DB 에 넣으면
"장비가 들고 있던 값" 과 "우리가 적재한 값" 이 구분되지 않는다.

**이것은 시뮬레이션이다.** 값도, 레지스터 주소도 실물이 아니다.
  · 주소는 `SIM-D0001` 처럼 **`SIM-` 접두**를 단다. 실물 XGB(XBC-DN32H) 주소를 아는 척하지
    않는다 — **PLC 태그맵(태그 ↔ 실주소)은 도입기업에게 받아야 한다**(D-176).
  · 태그 이름은 정본 8종(`ingest.tags.TAGS`)뿐이다. 여기서 태그를 늘리지 않는다.
  · 적재된 값에는 `DAT_TIMESERIES.COLLECT_PATH = '시뮬레이터(PLC→Gateway)'` 가 남는다(D-305).

`sent_yn` 이 이 모듈의 핵심이다. Gateway 가 가져간 것만 `Y` 가 된다 — 단절 구간에서
`N` 으로 쌓였다가 복구 후 올라가고, **끝나면 `N` 이 0 이어야 무손실**이다. 숫자를 맞추려고
`Y` 로 적지 않는다: 실제로 적재에 성공한 뒤에만 표시한다.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from ..app.util import clock
from . import tags

# 기본 위치 — `work/` 는 산출물이 아니라 작업 폴더다. 원본 아카이브에는 **절대** 쓰지 않는다.
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "work" / "plc_device.db"

ADDR_PREFIX = "SIM-D"          # **실물 주소가 아니다** — 태그맵은 도입기업 제공 (D-176)
SENT_NO, SENT_YES = "N", "Y"


@dataclass(frozen=True)
class Scan:
    """PLC 가 한 주기에 읽은 한 태그. Gateway 가 이 단위로 가져간다."""
    scan_id: int
    scan_dt: datetime
    tag_name: str
    value: str


def address_of(tag_name: str) -> str:
    """태그 → **시뮬레이터** 레지스터 주소. 정본 순서로 매긴다 (`SIM-D0001` …).

    실물 주소가 아니다. 실물은 도입기업 PLC 태그맵을 받아야 알 수 있다(D-176).
    """
    names = [t.name for t in tags.TAGS]
    if tag_name not in names:
        raise ValueError(f"정본 8종 밖의 태그다: {tag_name}")
    return f"{ADDR_PREFIX}{names.index(tag_name) + 1:04d}"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DEFAULT_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    return c


def init(c: sqlite3.Connection) -> None:
    """레지스터 표와 스캔 이력. **여러 번 불러도 같다**(시드 멱등과 같은 규칙)."""
    c.executescript(
        """
        create table if not exists plc_registers (
            addr       text primary key,
            tag_name   text not null unique,
            ko         text not null,
            uom        text not null,
            value      text,
            updated_dt text
        );
        create table if not exists plc_scan_log (
            scan_id   integer primary key autoincrement,
            scan_dt   text not null,
            tag_name  text not null,
            value     text not null,
            sent_yn   text not null default 'N',
            sent_dt   text
        );
        create index if not exists ix_scan_unsent on plc_scan_log (sent_yn, scan_id);
        """)
    for t in tags.TAGS:
        c.execute("insert or ignore into plc_registers (addr, tag_name, ko, uom) "
                  "values (?, ?, ?, ?)", (address_of(t.name), t.name, t.ko, t.uom))
    c.commit()


def scan_write(c: sqlite3.Connection, scan_dt: datetime,
               values: dict[str, str]) -> int:
    """PLC 한 주기 — 레지스터를 갱신하고 스캔 이력에 남긴다. **순서는 정본 순서다.**

    정본 8종 밖의 이름은 **예외**다. 조용히 버리면 태그가 늘어난 것을 아무도 모른다.
    """
    unknown = [k for k in values if tags.tag(k) is None]
    if unknown:
        raise ValueError(f"정본(사업계획서 2.7.1) 8종 밖의 태그다: {unknown}")
    stamp = scan_dt.isoformat(sep=" ")
    n = 0
    for t in tags.TAGS:                      # 정본 순서 — 순서 보존 시험의 전제다
        if t.name not in values:
            continue
        v = str(values[t.name])
        c.execute("update plc_registers set value = ?, updated_dt = ? where tag_name = ?",
                  (v, stamp, t.name))
        c.execute("insert into plc_scan_log (scan_dt, tag_name, value) values (?, ?, ?)",
                  (stamp, t.name, v))
        n += 1
    c.commit()
    return n


def poll(c: sqlite3.Connection, limit: int | None = None) -> list[Scan]:
    """Gateway 가 **아직 안 가져간 것**을 순서대로 읽는다. 표시는 하지 않는다.

    읽자마자 `Y` 로 적으면 적재가 실패해도 보낸 것이 되어 **유실이 숨는다.**
    표시는 `mark_sent()` 가 따로 하고, 그것은 적재 성공 뒤에만 부른다.
    """
    sql = ("select scan_id, scan_dt, tag_name, value from plc_scan_log "
           "where sent_yn = ? order by scan_id")
    args: list[object] = [SENT_NO]
    if limit is not None:
        sql += " limit ?"
        args.append(int(limit))
    return [Scan(int(r["scan_id"]), datetime.fromisoformat(r["scan_dt"]),
                 str(r["tag_name"]), str(r["value"]))
            for r in c.execute(sql, args)]


def mark_sent(c: sqlite3.Connection, scan_ids: Iterable[int],
              sent_dt: datetime | None = None) -> int:
    """**적재에 성공한 것만** 표시한다.

    시각을 안 주면 `clock.anchor()` 다 — **`datetime.now()` 를 쓰지 않는다**(§10-3).
    벽시계로 적으면 날짜가 바뀔 때마다 같은 시뮬레이션이 다른 값을 낸다. 실제로 여기에
    `datetime.now()` 를 썼다가 `check_data.py` G-07 이 파일·줄·함수를 찍어 잡아냈다.
    """
    ids = [int(i) for i in scan_ids]
    if not ids:
        return 0
    stamp = (sent_dt or clock.anchor()).isoformat(sep=" ")
    c.executemany("update plc_scan_log set sent_yn = ?, sent_dt = ? where scan_id = ?",
                  [(SENT_YES, stamp, i) for i in ids])
    c.commit()
    return len(ids)


def registers(c: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in c.execute(
        "select addr, tag_name, ko, uom, value, updated_dt from plc_registers order by addr")]


def stats(c: sqlite3.Connection) -> dict[str, int]:
    """**유실을 숨기지 않는다** — 스캔한 것과 보낸 것을 갈라서 센다."""
    row = c.execute(
        "select count(*) as total, "
        "sum(case when sent_yn = 'Y' then 1 else 0 end) as sent, "
        "sum(case when sent_yn = 'N' then 1 else 0 end) as unsent from plc_scan_log").fetchone()
    return {"scanned": int(row["total"] or 0), "sent": int(row["sent"] or 0),
            "unsent": int(row["unsent"] or 0)}


def group_by_cycle(scans: Sequence[Scan]) -> list[tuple[datetime, list[Scan]]]:
    """같은 스캔 시각끼리 묶는다 — Gateway 는 **한 주기를 한 배치로** 보낸다."""
    out: list[tuple[datetime, list[Scan]]] = []
    for s in scans:
        if out and out[-1][0] == s.scan_dt:
            out[-1][1].append(s)
        else:
            out.append((s.scan_dt, [s]))
    return out


def reset(path: Path | str | None = None) -> Path:
    """PLC 파일을 지운다 — 시뮬레이션 흔적을 남기지 않는다."""
    p = Path(path or DEFAULT_PATH)
    if p.exists():
        p.unlink()
    return p
