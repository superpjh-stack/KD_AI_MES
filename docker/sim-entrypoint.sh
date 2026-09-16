#!/bin/sh
# PLC 시뮬레이터 사이드카 (D-233) — 앱과 **네트워크를 공유**해 127.0.0.1:8020 으로 진짜 POST /api/ingest/plc 를 보낸다.
# (`--via http` 는 루프백에만 보낸다 — D-180. 그래서 별도 네트워크가 아니라 앱의 네트워크 네임스페이스에 붙는다.)
# 앱이 /health 200 을 낼 때까지 기다린 뒤 → 작업지시를 진행 상태로(시험용 전환, D-226) → 연속 모드.
# 이 값은 시뮬레이션이다 — COLLECT_PATH 에 그렇게 남고 화면에 배지가 뜬다 (D-174).
set -e

BASE="${KYUNGDONG_SIM_BASE_URL:-http://127.0.0.1:8020}"
WO="${KYUNGDONG_SIM_WORK_ORDER:-WO-2017-0002}"
POLL="${KYUNGDONG_SIM_POLL_SEC:-5}"
ANOMALY="${KYUNGDONG_SIM_ANOMALY_RATE:-0.02}"
FAULT_EVERY="${KYUNGDONG_SIM_FAULT_EVERY:-0}"
LOG_EVERY="${KYUNGDONG_SIM_LOG_EVERY:-60}"

echo "[sim] 앱 대기 — ${BASE}/health"
i=0
until python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('${BASE}/health',timeout=3).status==200 else 1)" 2>/dev/null; do
  i=$((i+1))
  if [ "$i" -ge 300 ]; then echo "[sim] 실패: 앱이 300초 안에 뜨지 않았다" >&2; exit 1; fi
  sleep 2
done
echo "[sim] 앱 확인 · 작업지시 ${WO} → 진행 (시험용 전환 D-226)"
python tools/plc_simulator.py --start-work-order "$WO"

echo "[sim] 연속 모드 — ${POLL}초 주기 · 알람률 ${ANOMALY} · 단절 매 ${FAULT_EVERY}주기 · 로그 ${LOG_EVERY}주기마다"
exec python tools/plc_simulator.py --daemon --via http --base-url "$BASE" \
  --poll-sec "$POLL" --anomaly-rate "$ANOMALY" --fault-every "$FAULT_EVERY" \
  --work-order "$WO" --log-every "$LOG_EVERY"
