# 끊겼을 때 — 이 파일만 보면 된다

세션이 끊겨도 **잃은 것은 없다.** 상태는 전부 파일에 있고 대화 기록에 의존하지 않는다(goal.md §4.5).

## 이어서 하려면 이 폴더에서 아래 한 줄을 붙여 넣는다

```
/loop goal.md 를 판정 기준으로 06 Coding Agent 를 돌린다. §4.2 한 회전 절차를 그대로 따른다 —
progress.md·decisions.md 를 읽고, `make gate` 로 §2 게이트 G-01~G-30 을 실측하고, FAIL 중 가장 앞선
웨이브의 항목 하나를 골라 §5 프롬프트로 담당 에이전트(아키텍트 1 · 개발 3 · QA 3, 병렬 가능한 것은 한 번에,
단 ML 학습이 있는 개발3 은 단독)를 기동하고, 보고를 믿지 말고 게이트 명령을 직접 다시 돌려 확인한 뒤
실측값과 검증 명령을 progress.md 에 적는다. 막히면 decisions.md 에 D-번호로 `차단`을 올리고 다음 항목으로
넘어간다 — 사람을 기다리며 멈추지 않는다. 게이트를 낮추거나 테스트를 건너뛰지 않는다.
§4.4 종료 조건 3개를 동시에 만족하면 최종 보고를 쓰고 멈춘다.
```

`/re-begin` 을 써도 된다 — `progress.md` 를 읽고 중단 지점부터 잇는다.

## 먼저 읽는 순서

1. `progress.md` **최신 섹션** — "지금 해야 할 것" · "알아둘 것" 두 절이 끝에 있다
2. `decisions.md` **미결 목록**(`차단` 상태)
3. `goal.md` §2 게이트 표 — 판정 기준

## 지금 어디까지 왔는지 한 줄로 확인

```bash
make gate          # G-01~G-30 판정표. 미구현 = PASS 아님, 잴 수단이 없다는 뜻
```

## 환경 되살리기 (필요하면)

```bash
make setup                                   # uv python pin 3.12 && uv sync
psql -d kyungdong_db -Atc "select count(*) from information_schema.tables where table_schema='public'"
# 68 이 안 나오면:  make db-schema
```

- DB `kyungdong_db` (PostgreSQL 17.10, unix socket `/tmp:5432`, pgvector 0.8.6)
- 개발 서버 포트 **8020** (8000·8010 은 이웃 사업이 점유 — D-28)
- `db/schema.sql` 은 **손으로 고치지 않는다** — `make gen-schema` 로만 바뀐다

## 잠들지 않게 해 둔 것

`work/caffeinate.pid` 에 PID 가 있다(12시간). 해제: `kill $(cat work/caffeinate.pid)`
**뚜껑을 닫으면 caffeinate 로도 못 막는다** — 잠들면 일시정지하고, 깨면 위 한 줄로 이어간다.
