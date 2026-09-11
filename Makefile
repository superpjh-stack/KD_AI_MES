# 경동글로벌텍 제조AI (SF26179182) — goal.md §9 게이트 실행 명령
.PHONY: setup gen-schema db-schema db-seed db-reset run simulate cad-ingest test \
        check-routes check-trace check-schema check-data check-ingest check-ai check-security \
        gate gate-full contracts

DB   ?= kyungdong_db
PORT ?= 8020
PSQL  = psql -d $(DB) -v ON_ERROR_STOP=1

setup:
	uv python pin 3.12 && uv sync

gen-schema:                     ## SF-TD5 → db/schema.sql 재생성 (손으로 고치지 않는다)
	uv run python tools/gen_schema.py

db-schema: gen-schema           ## DB 초기화 + schema.sql 적용 → 테이블 68
	$(PSQL) -q -c "drop schema public cascade; create schema public;"
	$(PSQL) -q -f db/schema.sql
	@$(PSQL) -Atc "select '테이블 '||count(*) from information_schema.tables where table_schema='public'"
	@$(PSQL) -Atc "select '컬럼 '||count(*) from information_schema.columns where table_schema='public'"

db-seed:                        ## 멱등 시드 (시간 앵커 고정, 비밀번호 난수 1회 출력)
	@test -f db/seed.py || (echo "db/seed.py 미작성 (아키텍트·개발1)"; exit 1)
	uv run python db/seed.py

db-reset: db-schema db-seed     ## 종료 판정은 반드시 이것 뒤에 한다 (§10-4)

run:
	uv run uvicorn kyungdong.app.main:app --app-dir src --port $(PORT) --reload

simulate:                       ## 레이저커팅기 1대 → 수집 API (수집 지점 2개소뿐 — D-06)
	uv run python tools/plc_simulator.py

cad-ingest:                     ## 도면 수집·정제(중복 183·0KB 4 제거) → EST_CAD_DRAWINGS
	uv run python tools/cad_ingest.py

test:
	uv run pytest -q

check-routes:;   uv run python tools/check_routes.py
check-trace:;    uv run python tools/check_trace.py
check-schema:;   uv run python tools/check_schema.py
check-data:;     uv run python tools/check_data.py
check-ingest:;   uv run python tools/check_ingest.py
check-ai:;       uv run python tools/check_ai.py
check-security:; uv run python tools/check_security.py

gate:                           ## 읽기 전용 판정표 — 루프가 매 회전 부르는 것
	uv run python tools/gate.py

gate-full: db-reset gate        ## 회전 마감·종료 판정용 (조용한 창에서만 — §10-17)

contracts:                      ## 계약 3종 재생성 (screen-map · db-schema · api-contract)
	uv run python tools/gen_screen_map.py
	uv run python tools/gen_db_contract.py
	uv run python tools/gen_api_contract.py
