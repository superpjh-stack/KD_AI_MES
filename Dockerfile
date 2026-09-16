# 경동글로벌텍 제조AI 스마트공장 (SF26179182)
# AP 서버 — FastAPI + uvicorn. 사업계획서 2.4 클라우드 SW 명세의 AP 서버에 해당한다 (docs/DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src:/app/db

# psql — 엔트리포인트가 DB 대기·스키마 적용에 쓴다 (db/schema.sql 은 psql 로 적용한다, Makefile db-schema 와 같다)
# libgomp1 — xgboost·shap 런타임 의존. 빠지면 import 에서 터진다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 먼저 — 소스가 바뀌어도 이 계층은 캐시된다
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 코드가 저장소 루트 기준으로 읽는 것들 (경로는 코드에 적혀 있다):
#   docs/design/*.json (정본 로더) · docs/assumed/customer_answers.json (D-160) · docs/cad/*.json·xlsx (시드·CAD)
#   decisions.md (app/followup.py — 화면의 미비 항목) · src/kyungdong/agent/sample_docs (시드)
COPY src/ ./src/
COPY db/ ./db/
COPY tools/ ./tools/
COPY docs/design/ ./docs/design/
COPY docs/assumed/ ./docs/assumed/
COPY docs/cad/ ./docs/cad/
COPY decisions.md goal.md ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/sim-entrypoint.sh /usr/local/bin/sim-entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/sim-entrypoint.sh

# 빠지면 기동이 아니라 화면에서 터진다 — 빌드 때 잡는다.
RUN test -f docs/design/design.json \
 && test -f docs/design/analysis.json \
 && test -f docs/assumed/customer_answers.json \
 && test -f docs/cad/customer_candidates.json \
 && test -f db/schema.sql \
 && test -f decisions.md

# PLC 시뮬레이터의 장비 측 저장소 자리 (work/plc_device.db, D-174)
RUN mkdir -p /app/work /app/outputs

RUN useradd -m -u 10001 kyungdong && chown -R kyungdong:kyungdong /app
USER kyungdong

EXPOSE 8020
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "kyungdong.app.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8020", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
