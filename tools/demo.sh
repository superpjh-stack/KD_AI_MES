#!/usr/bin/env bash
# 서버 + PLC 시뮬레이터를 **함께** 띄운다 (D-230). Ctrl-C 한 번에 둘 다 내려가고 작업지시도 되돌린다.
#
#   make demo                       # 기본: 포트 8020 · 2초 주기 · 작업지시 WO-2017-0002
#   make demo WO=WO-2017-0009 POLL=1 ANOMALY=0.1 FAULT_EVERY=30
#
# 하는 일 (순서대로)
#   ① uvicorn 을 백그라운드로 띄우고 /health 가 200 이 될 때까지 기다린다
#   ② 레이저커팅 작업지시를 진행 상태로 둔다 (시험용 전환 + SYS_CONFIGS 선언, D-226)
#   ③ 시뮬레이터 --daemon 을 전경에서 돌린다 (진짜 POST /api/ingest/plc)
#   ④ Ctrl-C → 시뮬레이터·서버 종료 → 작업지시 완료 복귀 + 선언 거둠
#
# 남는 것: 시뮬레이터가 적재한 신호·시계열·알림·자동 실적 — 런타임 행이라 G-11 과 섞인다.
# 게이트를 재기 전에는 `make db-reset` 을 한다. 여기서 자동으로 지우지 않는다 — 방금 본 데이터를
# 사용자가 화면에서 더 들여다볼 수 있어야 하기 때문이다.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8020}"
WO="${WO:-WO-2017-0002}"
POLL="${POLL:-2}"
ANOMALY="${ANOMALY:-0.02}"
FAULT_EVERY="${FAULT_EVERY:-0}"
LOG="${LOG:-work/demo_server.log}"
mkdir -p work

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "포트 $PORT 가 이미 열려 있다 — 다른 서버가 떠 있으면 PORT= 로 바꾼다" >&2
  exit 1
fi

echo "① 서버        uvicorn :$PORT (로그 $LOG)"
uv run uvicorn kyungdong.app.main:app --app-dir src --port "$PORT" >"$LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  echo
  echo "④ 종료        시뮬레이터·서버를 내리고 작업지시를 되돌린다"
  kill "$SERVER_PID" 2>/dev/null || true
  uv run python tools/plc_simulator.py --finish-work-order "$WO" 2>/dev/null || true
  echo "   남은 런타임 행(신호·알림·자동 실적)은 화면에서 더 볼 수 있다. 게이트 전에는 \`make db-reset\`."
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/health" | grep -q 200; then break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "서버가 죽었다 — $LOG 를 본다" >&2; tail -20 "$LOG" >&2; exit 1
  fi
  sleep 1
done

echo "② 작업지시    $WO → 진행 (시험용, D-226)"
uv run python tools/plc_simulator.py --start-work-order "$WO"

echo "③ 시뮬레이터  ${POLL}초 주기 · 알람률 $ANOMALY · 단절 매 ${FAULT_EVERY}주기 — Ctrl-C 로 전부 멈춘다"
echo "   화면: http://127.0.0.1:$PORT/dsh/003  ·  http://127.0.0.1:$PORT/prc/022  ·  http://127.0.0.1:$PORT/agt/041"
uv run python tools/plc_simulator.py --daemon --via http --base-url "http://127.0.0.1:$PORT" \
  --plc-reset --poll-sec "$POLL" --anomaly-rate "$ANOMALY" --fault-every "$FAULT_EVERY"
