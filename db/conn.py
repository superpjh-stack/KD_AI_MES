"""DB 접속 — `contracts/interfaces.md` 공표 시그니처: `q` · `q1` · `x` · `tx`.

**조용한 실패 금지 (goal.md §2.5 · G-30).** DB 가 죽으면 빈 배열을 돌려주지 않고 **503** 을 낸다.
화면이 "데이터 없음" 으로 보이면 결함이다 — 없는 것과 못 읽은 것은 다르다.

행은 `dict` 로 돌려준다(컬럼명 = TD5 영문명 소문자). 파라미터는 **항상 바인딩**한다 — f-string 금지.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kyungdong.app.settings import settings          # noqa: E402
from kyungdong.app.util import http                  # noqa: E402

# psycopg 가 내는 것 중 "DB 를 못 썼다" 에 해당하는 것 — 이때만 503 으로 바꾼다.
_UNAVAILABLE = (
    psycopg.OperationalError,
    psycopg.errors.CannotConnectNow,
    psycopg.errors.AdminShutdown,
    psycopg.errors.CrashShutdown,
)


def _connect() -> psycopg.Connection:
    try:
        return psycopg.connect(settings().pg_dsn, row_factory=dict_row, autocommit=True)
    except _UNAVAILABLE as e:
        raise http.fail("db_down", f"DB 연결 실패: {e.__class__.__name__}") from e


@contextmanager
def cursor() -> Iterator[psycopg.Cursor]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            yield cur
    except _UNAVAILABLE as e:
        raise http.fail("db_down", f"DB 사용 불가: {e.__class__.__name__}") from e
    finally:
        conn.close()


def q(sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """여러 행. **DB 장애는 503 이고 빈 리스트가 아니다.**"""
    with cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def q1(sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    """한 행. 없으면 `None` — 이것은 **정상적인 0건**이고 화면은 '미수집' 문구를 렌더한다(G-11)."""
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def x(sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> int:
    """쓰기. 영향 행 수를 돌려준다."""
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


@contextmanager
def tx() -> Iterator[psycopg.Cursor]:
    """트랜잭션. 예외가 나면 롤백하고 **그 예외를 삼키지 않는다**."""
    conn = _connect()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except _UNAVAILABLE as e:
        conn.rollback()
        raise http.fail("db_down", f"트랜잭션 중 DB 사용 불가: {e.__class__.__name__}") from e
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def alive() -> bool:
    """`/health` 와 게이트가 쓴다. **여기서만** 예외를 삼킨다(살았는지 묻는 함수이므로)."""
    try:
        with cursor() as cur:
            cur.execute("select 1")
            return cur.fetchone() is not None
    except Exception:
        return False


def table_count() -> int:
    row = q1("select count(*) as n from information_schema.tables where table_schema='public'")
    return int(row["n"]) if row else 0


def column_count() -> int:
    row = q1("select count(*) as n from information_schema.columns where table_schema='public'")
    return int(row["n"]) if row else 0
