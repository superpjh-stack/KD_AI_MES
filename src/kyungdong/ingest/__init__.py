"""수집 (MES-TD4-047) — **수집 지점은 2개소뿐이다 (D-06).**

사업계획서 2.7.1 이 적은 데이터 집계 포인트는 두 곳이다.

  ① 신규 레이저커팅기 Master PLC 1지점 (Ethernet/OPC-UA)
  ② 현장POP(터치PC) 1지점

그 밖의 공정 실적은 **수동 입력**이다. 전 공정 실시간 수집을 만들면 결함이다.
화면은 수집 지점 밖 공정에 `미수집 (D-06)` 을 렌더한다.

적재 경로: 수집 API → `IF_PLC_SIGNALS` → `PRC_EQUIP_SIGNALS` / `DAT_TIMESERIES`.
게이트웨이가 끊기면 `IF_GATEWAY_BUFFER` 에 쌓고 복구 시 **순서대로 무손실 재전송**한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# db/conn.py 는 패키지가 아니라 최상위 모듈이다 — util/codes.py 와 같은 방식으로 경로를 붙인다.
_DB = str(Path(__file__).resolve().parents[3] / "db")
if _DB not in sys.path:
    sys.path.insert(0, _DB)
