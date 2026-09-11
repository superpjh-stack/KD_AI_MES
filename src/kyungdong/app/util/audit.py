"""G-29 감사추적 — 로그인·화면조회·변경을 `SYS_ACCESS_LOGS` 에 남긴다.

보존기간은 미확정(D-17)이므로 **삭제 배치를 만들지 않는다.**
데이터 반출은 `DAT_DOWNLOAD_LOGS` 에 따로 기록한다(9.2 ①).
"""
from __future__ import annotations

from typing import Any

LOG_TYPES = ("접속", "변경", "API", "오류")
RESULT_OK, RESULT_ERR = "정상", "오류"


def audit(request: Any, screen_id: str | None, action: str, *,
          log_type: str = "접속", result: str = RESULT_OK,
          error: str | None = None, user_id: int | None = None) -> None:
    """감사 기록. **여기서 예외를 삼키지 않는다** — 기록 실패는 드러나야 한다(G-30).

    단 `SYS_ACCESS_LOGS` 는 런타임 전용 표라 깨끗한 DB 에서 0건이 정상이다(G-11).
    """
    import conn
    if log_type not in LOG_TYPES:
        raise ValueError(f"LOG_TYPE 은 {LOG_TYPES} 중 하나다 (TD5): {log_type!r}")
    client = getattr(request, "client", None)
    conn.x(
        "insert into SYS_ACCESS_LOGS "
        "(LOG_TYPE, USER_ID, ACCESS_IP, SCREEN_ID, ACTION_NAME, RESULT_CODE, ERROR_MSG, OCCURRED_DT, CREATED_DT) "
        "values (%s, %s, %s, %s, %s, %s, %s, now(), now())",
        (log_type, user_id, getattr(client, "host", None), screen_id, action, result,
         (error or "")[:500] or None),
    )
