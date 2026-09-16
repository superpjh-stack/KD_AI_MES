#!/bin/sh
# DB 기동 대기 → 스키마 적용(최초 1회) → 시드(멱등) → 앱 실행.
# 조용한 실패 금지: 어느 단계든 실패하면 로그에 사유를 남기고 종료한다 (CLAUDE.md · G-30).
set -e

: "${KYUNGDONG_PG_DSN:?KYUNGDONG_PG_DSN 이 없다. docker-compose 의 environment 를 확인하라}"

WAIT="${KYUNGDONG_DB_WAIT_SEC:-60}"
echo "[entrypoint] DB 접속 대기 — ${WAIT}초"
i=0
until psql "$KYUNGDONG_PG_DSN" -c 'select 1' >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -ge "$WAIT" ]; then
    echo "[entrypoint] 실패: DB 에 접속하지 못했다 (${WAIT}초 초과). DSN·네트워크를 확인하라" >&2
    exit 1
  fi
  sleep 1
done
echo "[entrypoint] DB 접속 확인"

# 스키마 — SF-TD5 68테이블 · 762컬럼. 이미 있으면 건너뛴다. **기존 데이터를 지우지 않는다.**
# (Makefile db-schema 는 `drop schema public cascade` 를 한다 — 운영 컨테이너에서는 쓰지 않는다.)
TABLES=$(psql "$KYUNGDONG_PG_DSN" -Atc "select count(*) from information_schema.tables where table_schema='public'")
if [ "$TABLES" -lt 68 ]; then
  echo "[entrypoint] 스키마 적용 — 현재 테이블 ${TABLES}개 (SF-TD5 68테이블 · 762컬럼)"
  psql "$KYUNGDONG_PG_DSN" -v ON_ERROR_STOP=1 -q -f db/schema.sql
  TABLES=$(psql "$KYUNGDONG_PG_DSN" -Atc "select count(*) from information_schema.tables where table_schema='public'")
  COLS=$(psql "$KYUNGDONG_PG_DSN" -Atc "select count(*) from information_schema.columns where table_schema='public'")
  echo "[entrypoint] 스키마 적용 완료 — 테이블 ${TABLES}개 · 컬럼 ${COLS}개"
  if [ "$TABLES" -ne 68 ]; then
    echo "[entrypoint] 실패: 테이블이 68개가 아니다 (${TABLES}) — db/schema.sql 을 확인하라 (G-01)" >&2
    exit 1
  fi
else
  echo "[entrypoint] 스키마 존재 — 테이블 ${TABLES}개, 적용 건너뜀"
fi

# 시드 — 멱등이다 (G-07). 기존 계정의 비밀번호는 바꾸지 않는다 (D-207 · §10-11).
# 신규 계정은 계정별 난수를 이 로그에 **딱 한 번** 출력한다 — 받아 적어라 (G-29: 저장소에 적지 않는다).
# 놓쳤으면: docker compose exec app python tools/ops_password.py --login admin
# 순서: 공통(코드 마스터·계정·앵커) → 개발1·2·3 업무 데이터 (Makefile db-seed 와 같다).
if [ "${KYUNGDONG_SKIP_SEED:-0}" != "1" ]; then
  echo "[entrypoint] 시드 — 공통 (db/seed.py)"
  python db/seed.py
  for s in seed_dev1 seed_dev2 seed_dev3; do
    echo "[entrypoint] 시드 — ${s}"
    python "db/${s}.py"
  done
fi

echo "[entrypoint] 앱 기동 — env=${KYUNGDONG_ENV:-dev} · llm=${KYUNGDONG_LLM_PROVIDER:-미구성(D-08)} · 검색=${KYUNGDONG_EMBED_PROVIDER:-tsvector_keyword(D-08)} · CAD=${KYUNGDONG_CAD_PARSER:-미구성(D-05)}"
if [ "${KYUNGDONG_ENV:-dev}" != "prod" ]; then
  echo "[entrypoint] ※ dev 프로파일 — 로그인 없이 시스템 관리자로 열린다 (D-206). 공개망에 두려면 HTTPS 종단 뒤에서 prod 로 올린다 (D-208 · docs/DEPLOY.md)"
fi
exec "$@"
