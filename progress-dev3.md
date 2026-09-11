# progress-dev3.md — 개발3(AI) 진행률

경동글로벌텍 제조AI 플랫폼 (SF26179182 · 공급기업 주식회사 재일)
담당 화면 **14** · 테이블 **30** · 파일 `routers/{est,agt,ingest}.py` · `kyungdong/{agent,ml,cad,ingest}` ·
`templates/{est,agt}` · `tools/{plc_simulator,cad_ingest}.py` · `db/seed_dev3.py` · `tests/test_dev3_*.py`

---

## 2026-09-11 회전 1 — R1-a 수집 · R1-c RAG · R2 화면 골격

**범위**: 수집(레이저커팅기 1지점) · 폐쇄형 RAG Agent 3종 · 화면 14건 골격.
**ML 학습(R1-b)은 하지 않았다** — 학습이 있는 회전은 단독 기동이다(goal.md §10-2 · D-309).
견적·BOM·SHAP 은 **데이터 구조와 화면만** 세웠고 **성능 수치를 만들지 않았다**.

### 검증 (보고 전에 실행한 것)

```
uv run python db/seed_dev3.py           # 두 번 돌려 행 수 diff 0  → 멱등 OK
uv run python tools/plc_simulator.py --help
uv run python tools/cad_ingest.py       # 1,283 스캔 → 995 등록 · 288 제외
uv run pytest -q                        # 546 passed  (개발3 단독 139)
uv run python tools/check_routes.py     # G-06 PASS · G-03-①②③ 전부 PASS
uv run python tools/gate.py             # PASS 6 · FAIL 0 · 차단 0 · 미구현 6 / 12
```

`check_routes.py`: **전 화면 200(50개) · `_placeholder` 0건 · 타 사업 용어 렌더 0 · 소스 0**.

### 실측값

| 항목 | 실측 | 근거 |
|---|---|---|
| 화면 | 14 / 14 (200) | `/est/010~015` · `/dat/037` · `/inv/009` · `/shp/020` · `/agt/038~042` |
| 개발3 테스트 | **139 passed** | `tests/test_dev3_{screens,ingest,cad,agent,hitl,seed}.py` |
| 도면 인벤토리 | **1,283** 건 / 제품 **77** 종 | `docs/cad/경동글로벌텍_CAD도면_제품별정리.xlsx` |
| 파일명 완전일치 중복 | **183** 건 | D-03 실측을 코드가 그대로 재현 |
| 0KB 손상 | **4** 건 | D-03 재현 |
| 제품당 도면 수 | 최대 **184** · 최소 **1** · 중앙값 **5** · 1건뿐인 제품 **9** 종 | D-03 재현 |
| 확장자 | dwg 918 · cad 355 · dxf 10 | 실측 |
| 정제 결과 (`--scope product`) | 등록 **995** · 제외 **288**(중복 284 · 0KB 4) | D-312 |
| 정제 결과 (`--scope none`) | 등록 **893** · 제외 **390**(중복 386 · 0KB 4) | 고객사 축 부재 영향 (D-304) |
| `IF_CAD_FILES` / `IF_CAD_IMPORT_LOGS` | 1,283 / 4,844 | 4단계(수신·검증·중복제거·등록) 로그 |
| `EST_CAD_DRAWINGS` / `DAT_DATASET_ITEMS` | 995 / 995 | Label **0건** (D-04) |
| 수집 지점 | **2** (레이저커팅기 PLC · 현장POP(터치PC)) | 사업계획서 2.7.1 · D-06 |
| PLC 태그 | **8** 종 | 작업시간·수량·가동상태·알람·속도·압력·전류·온도 |
| 시뮬레이터 무손실 | 6주기 × 8태그 = **48행**, 단절 2배치 → 재전송 후 **48행** (유실 0) | `tools/plc_simulator.py --disconnect 3 --reconnect 5` |
| `AGT_VECTOR_DOCS` | 2 문서 / 2 청크 | 시안 3종 중 2종 (1종은 D-303 차단) |
| 검색 모드 | `tsvector_keyword` | 임베딩 미구성 (D-08). 벡터 차원 상수 **1536** (D-31) |
| 임베딩된 청크 | **0** | 0벡터를 채우지 않았다 (D-08) |
| Agent 도구 | **11** 종 ↔ D-20 재배선 표 1:1 | 입고 5 · 출하 6 · 통합 11 |
| 확정 표 | `EST_QUOTATIONS` 0 · `EST_BOM_HEADERS` 0 · `EST_CAD_OBJECTS` 0 | 승인 없이 바뀌는 경로 **0** (G-24) |
| 학습 | `EST_ML_MODELS` 0 · `_TRAIN_RUNS` 0 · `_PREDICTIONS` 0 · `EST_SHAP_FACTORS` 0 | **학습 미실시** (D-309) |

**측정하지 못한 것 — `차단`으로 남긴다**

| 게이트 | 판정 | 이유 |
|---|---|---|
| G-14 CAD 객체 인식 80% | **차단** | Autodesk API·YOLOv8 가중치·OCR 미확보 (D-05). 인식 실행은 501 |
| G-15 견적 정확도 ±5% | **차단** | 과거 견적금액·실제 제조원가 Label 확보 미확인 (D-04). 단가 기준 0건 |
| G-16 BOM 정확도 85% | **차단** | 기준 BOM 부재 (D-04) · 품목·재질 코드 그룹 0건 (D-47) |
| G-17 납기 예측 85% | **차단** | 실적 Label 부재 (D-04). 허용 오차는 가설 (D-12) |
| G-18 설명가능성 90% | **차단** | 전문가 평가 변수 목록 없음 (D-13) |
| RAG 응답시간·인용 정확도 | **목표 없음** | 사업계획서에 목표치가 없다 (D-09) — 실측만 화면 042 에 적는다 |

### `contracts/db-schema.md` §7.1 판정 — `EST_SHAP_FACTORS`

**런타임 전용 표다 (D-301).** `PREDICT_ID` 가 `EST_ML_PREDICTIONS`(런타임 전용)를 **NOT NULL FK** 로
보므로 예측이 0건이면 SHAP 행은 **존재할 수 없다**. 시드 대상이 아니고, 깨끗한 DB 에서 0건이 정상이며
화면 `/est/015` 는 그때 `미수집` 문구를 렌더한다. §7 목록으로 옮겨 달라고 아키텍트에게 요청했다.

---

## 공표 시그니처 — 다른 개발자가 그대로 쓴다

### 수집 상태 (개발2 — `/dsh/003` 설비상태 · `/prc/022` 공정 데이터 모니터링)

```python
from kyungdong.ingest.collector import status

status(now: datetime | None = None) -> dict
# {
#   "checked_at": datetime,          # 실시각 (수집이 살아 있는지 묻는 함수라 앵커가 아니다)
#   "stale_sec": int,                # .env KYUNGDONG_INGEST_STALE_SEC
#   "stale_badge": str,              # "가설 (D-09)"  — 화면에 그대로 띄운다
#   "points": 2,                     # 수집 지점 (D-06) — 늘리면 결함이다
#   "devices": [{
#       "device_id": int, "device_name": str, "device_type": str, "protocol": str,
#       "use_yn": str, "collect_interval": int | None, "location_desc": str,
#       "last_collect_dt": datetime | None, "seconds_since": float | None,
#       "signal_cnt": int, "stale": bool,
#       "notice": str | None,        # "수집 중단 — 마지막 수집 hh:mm:ss" 또는 "미수집 (D-06)"
#   }],
#   "buffer_pending": int,           # IF_GATEWAY_BUFFER 대기 배치
#   "any_stale": bool,
# }
```

HTTP 로도 같은 값을 준다: **`GET /api/ingest/status`** (데이터관리 조회 권한 필요, 없으면 403).
`notice` 가 `None` 이 아니면 그 문자열을 **배지로 그대로** 띄운다 — 문구를 각자 만들지 않는다.

### 수집 적재 (QA2 — `check_ingest.py`)

```python
from kyungdong.ingest.collector import Sample, ingest_batch, buffer, pending_buffer, resend

ingest_batch(device_id, equip_code, samples, *, collect_path=COLLECT_PATH) -> IngestResult
#   IngestResult(received, stored, duplicated, signal_rows, timeseries_rows, order, .ordered)
buffer(device_id, equip_code, samples, reason="네트워크 단절") -> int   # BUFFER_ID
resend(device_id=None) -> {"resent_batches": int, "failed": int, "stored_rows": int}
```
`POST /api/ingest/plc` · `POST /api/ingest/gateway/resend` 가 같은 함수를 부른다.

### CAD (QA3 — `check_ai.py` · `work/cad_labelset.json`)

```python
from kyungdong.cad import inventory, pipeline, provider

inventory.read_inventory() -> list[InventoryFile]          # docs/cad/ 실측 1,283건
inventory.clean(files, scope="product") -> list[Cleaned]   # scope: "product" | "none" (D-304)
inventory.stats(files, cleaned=None) -> dict               # 위 실측값 표와 같은 키
pipeline.analyze(drawing_id) -> dict                       # 미구성이면 501 (D-05)
pipeline.review_object(object_id, *, reviewer_id, role_code, result, ...) -> dict  # 유일한 확정 경로
pipeline.build_features(drawing_id) -> {"created", "confirmed_objects", "blocked"}
provider.availability() -> list[Availability]              # 화면 배지
```

### Agent (QA3 — `work/rag_goldset.json`)

```python
from kyungdong.agent import service, retrieval, tools

service.ask(question, *, agent_type="통합", user_id=None, role_code="") -> Answer
#   Answer(text, evidence, mode, confidence, threshold, response_ms, grounded,
#          notice, handover, query_id, sources, evidence_line)
#   · 근거 0건 또는 신뢰도 < 임계 → LLM 미호출, text = "검토 필요 — 근거 부족"
#   · 근거 있음 + LLM 미구성 → 501 (단, AGT_QUERY_LOGS 기록은 **먼저** 남긴다)
service.history(...) / service.history_stats()             # 화면 042
retrieval.search(q, *, agent_type, role_code, limit=5) -> (list[Evidence], mode)
tools.definitions(agent_type) / tools.execute(name, args, *, agent_type, role_code)
```
HTTP: `POST /api/agent/query` · `GET /api/agent/history` · `POST /api/agent/recommend/{id}/adopt`.

---

## 한 일

| 구분 | 파일 | 내용 |
|---|---|---|
| 수집 | `kyungdong/ingest/{tags,collector}.py` | 태그 8종 매핑 · 한 배치 = 한 트랜잭션 · 중복 건너뛰기 · Gateway 버퍼/재전송 · 상태 조회 |
| 수집 | `tools/plc_simulator.py` | **레이저커팅기 1대만.** 앵커 고정 · 이상 주입 · 단절/복구 · `--dry-run` · `--realtime` |
| CAD | `kyungdong/cad/{inventory,provider,pipeline}.py` | 실측 인벤토리 읽기 · 정제 경로 · 공급자 추상화(미구성 501) · HITL · Feature 집계 |
| CAD | `tools/cad_ingest.py` | 1,283 → `IF_CAD_FILES` → 정제 → `EST_CAD_DRAWINGS` → `DAT_DATASET_ITEMS`(Label 0) |
| RAG | `kyungdong/agent/{prompts,retrieval,tools,citations,llm,docs,service}.py` | 시안 이식 + D-20 재배선. 폐쇄형 · 근거 0건 분기 · 로그 100% |
| ML | `kyungdong/ml/{registry,datasets}.py` | **읽기 경로와 차단 사유만.** 학습·성능 수치 없음 |
| 화면 | `routers/{est,agt,ingest}.py` · `templates/{est,agt}/` | 14화면 + 인터페이스 3종. CSS 0줄 추가(공용 `app.css` 만) · 미디어쿼리 0 |
| 시드 | `db/seed_dev3.py` | 장비 2 · 전처리 규칙 5 · 데이터셋 1 · 지식문서 2. 런타임 전용 표 0건 |
| 시험 | `tests/test_dev3_*.py` | 139건 |

### 지키려고 일부러 한 것

- **없는 것을 있는 척하지 않았다.** CAD 인식은 501 이고, 빈 리스트를 돌려주지 않는다 —
  "0건 인식" 과 "못 했다" 는 다르다. `tests/test_dev3_cad.py` 가 501 을 내면서 객체가 늘지 않음을 단언한다.
- **근거 0건이면 LLM 을 부르지 않는다.** 테스트가 `monkeypatch` 로 `llm.complete` 를 감시해 **호출 0회**를 단언한다.
- **질의 100% 기록.** 근거 부족 갈래와 501 갈래 **둘 다** `AGT_QUERY_LOGS` 에 남는 것을 단언한다.
- **`CONFIRM_YN` 을 바꾸는 곳은 한 군데뿐**임을 정규식으로 단언한다(`test_dev3_hitl.py`).
  확정 표(`EST_QUOTATIONS` `EST_BOM_HEADERS` `EST_CAD_OBJECTS` `AGT_RECOMMENDATIONS`)에 쓰는 함수는
  전부 `can_approve` 또는 `forbidden` 을 지나는지 소스에서 확인한다.
- **`(예시)` 값을 렌더하지 않는다.** 14화면 전부에 대해 단언한다.
- **외부 리소스 0.** 14화면 렌더에 `http(s)://` 링크가 없음을 단언한다(D-50).

---

## 막힌 것 — 고치지 않고 남긴다

| 무엇 | 상태 | 다음 행동 |
|---|---|---|
| 견적·BOM·납기 정확도 | **차단 (D-04)** | 과거 견적금액·실제 제조원가 Label 확보 여부를 도입기업에 확인 |
| CAD 객체 인식 | **차단 (D-05)** | Autodesk API 계정 · YOLOv8 가중치 · OCR 엔진 |
| 설명가능성 일치율 | **차단 (D-13)** | 전문가 평가 변수 목록 |
| 견적·조달 지식문서 | **차단 (D-303)** | `AGT_VECTOR_DOCS.DOC_TYPE` 어휘 확장 여부 결정 |
| 도면 고객사 축 | **차단 (D-304)** | 고객사 메타데이터 확보. 현재는 제품 폴더명 대체 표기 |
| LLM·임베딩 | **차단 (D-08·D-310)** | 모델명·엔드포인트 확정 후 `agent/llm.py` 에 핸들러 등록 |

## 알아둘 것 (다음 회전·다른 개발자)

1. **`make cad-ingest` 를 돌리지 않으면 `/est/010` 그리드가 0건**이다 — 그때 `미수집` 문구가 정상이다.
   도면 수집은 시드가 아니라 **런타임 동작**이라 `seed_dev3.py` 가 하지 않는다(수집 로그가 런타임 전용 표다).
2. **시뮬레이터 기본값은 앵커 기준**이라 `/dsh/003`·`/prc/022` 배지가 `수집 중단` 으로 보인다.
   초록으로 보려면 `uv run python tools/plc_simulator.py --realtime` 이다. 버그가 아니다(§10-3).
3. **`routers/ingest.py` 는 `agt.py` 가 싣는다**(D-306). `agt.py` 끝의 `include_router` 를 지우면
   `/api/ingest/*` · `/api/cad/*` · `/api/docs/*` 가 통째로 사라진다.
4. **인증이 들어오면 `agent.service.resolve_user()` 를 지운다**(D-307). 개발용 보조다.
5. **다음 회전이 ML 학습(R1-b)이고 단독 기동**이다(§10-2). 그 전에 D-04 답이 없으면
   학습은 **합성 Label 기준**임을 화면·리포트에 명시해야 하고, 그래도 G-15·G-17 은 차단이다.
6. 회전 중 `test_arch_seed.py::test_G07_시드가_멱등이다` 가 **한 번 실패했다가 다시 통과했다.**
   두 시드 실행 사이에 다른 개발자 테스트가 `SYS_USERS` 를 만들어서다 — 개발3 테스트만 돌리면
   재현되지 않는다(아키텍트+개발3 244 passed). **동시 기동 중 관측**이라 §10-17 "판정 불가" 로 적는다.
   마감 시점 실측은 **546 passed** 다.

---

# 웨이브 D 마무리 (회전 7 · 단독) — 개발3 잔여 + CSRF 전 라우트 연결

## 1. 프로젝트번호 링크 (DEF-QA1-004 · G-08 클릭 규약)

`routers/est.py:131·241·303` 이 **프로젝트번호** 열을 `/prc/024?lot=` 로 걸고 있었다 → `?project=`.
`/prc/024` 는 `lot` 과 `project` 를 다른 축으로 읽는다(개발2 `dsh.project_cell` 과 같은 규약).

## 2. 수집 API 파싱 실패 500 → **422** (DEF-QA1-006 · 계약 §4.0)

`/api/ingest/plc` 가 `await request.json()` 을 맨몸으로 불러 깨진 본문에 **500** 을 냈다.
`json.JSONDecodeError`·`UnicodeDecodeError` 를 잡아 `http.fail("validation", ...)` = **422** 로 바꿨다.
`try/except` 로 결과를 지어내지 않는다 — 사유를 응답에 그대로 적는다.

## 3. CAD 수집 처리 건수 → `DAT_JOB_LOGS` (DEF-QA2-006) — **실측 확인**

WIP 커밋이 이미 `cad/pipeline.import_inventory()` 끝에 `preprocess.log_job(JOB_CAD, ...)` 를 넣어 뒀다.
동작을 실측했다:

```
pipeline.import_inventory(limit=30)
  scanned 30 · registered 28 · excluded 2 · job_log_id 1
  DAT_JOB_LOGS → {'job_name':'CAD 도면함 수집','process_cnt':28,'fail_cnt':2,'result_code':'부분성공'}
preprocess.run() → job_log_id 2
```

`FAIL_CNT` 는 **정제 제외 건수**다(TD5 에 '제외 건수' 컬럼이 없다). 오류가 아니라는 사실을 `ERROR_MSG` 에 적는다.

## 4. CAD 테스트 `skip` 제거 (DEF-QA2-010 · D-62 · §10-4) — **skip 0건**

`tests/test_dev3_cad.py` 의 `pytest.skip` 3곳을 **0건 경로 명시 단언**으로 바꿨다.

| 테스트 | 0건 경로에서 단언하는 것 |
|---|---|
| 분석 실행 501 | 도면 0건이면 `analyze(1)` 이 **422**, `EST_CAD_OBJECTS` 증가 0 |
| 확정 객체 0 → Feature 0 | `build_features()` 가 0 을 돌려주고 `EST_CAD_FEATURES` 증가 0 |
| 수집 로그 단계별 | 파일 0건이면 **로그도 0건** (있으면 시드가 런타임 표를 채운 것 — G-11) |

```
uv run pytest -q tests/test_dev3_cad.py    → 13 passed · skip 0
grep -c "pytest.skip" tests/test_dev3_cad.py → 0
```

## 5. MLOps 롤백 경로 (G-25 FAIL 사유) — **코드 0곳 → 있음**

`ml/registry.py` 에 `deployed_model()` · `previous_version()` · `deploy()` · `rollback()`,
화면 경로로 `POST /est/014/deploy`(배포·롤백) + `est/014.html` 배포 카드.
어휘는 TD5 `DEPLOY_STATUS` (학습중/검증/배포/폐기) 그대로다. 롤백은 지금 배포본을 `검증` 으로 내리고
직전 버전을 `배포` 로 올린다 — **이력을 지우지 않는다.** 되돌릴 버전이 없으면 **422**(없는데 성공한 척 안 한다),
승인 권한 없으면 **403**.

임시 2버전으로 실측(넣고 되돌리고 지웠다):
```
deploy v1.0   → demoted 1
현재 v1.0 · 직전 v0.9
rollback      → rolled_back_from v1.0 → rolled_back_to v0.9
결과 [('v0.9','배포'), ('v1.0','검증')]
```

**G-25 는 여전히 FAIL 이다.** 미충족이 5/5 → **4/5** 로 줄었고 남은 4(모델·학습·예측·Train/Val/Test 분할)는
전부 **학습 미실시로 분모 0** = 차단 성격이다. `tools/check_ai.py` 가 G-25 를 `FAIL` 로 **하드코딩**하고 있어
검사기가 갱신돼야 판정이 움직인다. **학습을 돌려 수치를 만들지 않았다**(§10-2 · 이번 회전 범위 밖).

## 6. URL 평문 비밀번호 (`routers/sys.py`) — 0건. 자세한 건 `progress-dev1.md`.

## 7. CSRF — **POST 31개 전부 연결 (31/31)**

스톨 시점 15/27. 남아 있던 12개(`agt` 5 · `est` 3 · `ingest` 4)를 연결했고, 이번에 추가한
`POST /est/014/deploy` 까지 31개다. 패턴은 §2 그대로 — **핸들러 첫 줄**.

```python
form = await request.form()
csrf.require(request, csrf.token_of(request, form))   # 위반 시 403
```

`Form(...)` 시그니처는 **전부 걷어냈다.** FastAPI 가 본문을 핸들러보다 먼저 파싱해서
토큰 없는 요청이 403 이 아니라 422 를 받기 때문이다(실측 재현). 검사 순서는 **CSRF → 권한 → 입력값**(계약 §4.0).

### JSON·기계 API 는 헤더로 받는다
`csrf.token_of(request, form)` 이 **폼 필드 `_csrf` → 헤더 `X-CSRF-Token`** 순으로 본다.
`/api/ingest/plc` 는 폼이 아니라 JSON 본문이라 **헤더만** 쓴다.

```
POST 라우트 31 · csrf.require 31 · 누락 []
uv run python tools/check_security.py  →  **CSRF 31/31**
```

## 못 한 것 — **`KYUNGDONG_CSRF_ENFORCE` 를 1 로 올리지 못했다**

올리기 전에 쓰기 경로를 먼저 쟀다. **켜면 85건이 깨진다**(실측, 끈 상태 14건 — 전부 QA 표지):

```
make db-reset && KYUNGDONG_CSRF_ENFORCE=1 uv run pytest -q
  FAILED/ERROR 85 건
    test_dev1_flow 37 · test_qa1_rbac 11 · test_qa3_security 10 · test_qa1_errors 9
    test_qa3_ai 5 · test_qa1_ui 4 · test_qa2_ingest 3 · test_dev2_screens 3 · test_dev2_chain 3
```

사유 둘 — **구현 결함이 아니다.**

1. **테스트 하네스가 토큰을 싣지 않는다.** 브라우저 경로는 통과한다 —
   화면이 발급한 토큰으로 `ENFORCE=1` 왕복을 실측했다(`test_G26_토큰이_없으면_403_있으면_통과한다`).
   85건 중 **42건이 QA 소유 파일**(`tests/test_qa*.py`)이라 개발이 고칠 수 없다.
   켜면 QA 가 CSRF 와 **무관한** 것(RBAC·오류계약·AI)을 못 재게 된다.
2. **기계 클라이언트에 토큰 발급 경로가 없다.** `/api/ingest/plc` · `/api/cad/files` ·
   `/api/docs/import` · `/api/ingest/gateway/resend` 는 Gateway·배치가 부른다.
   세션이 없는 기계는 `X-CSRF-Token` 을 **받을 방법이 없다** — 지금 켜면 **PLC 수집이 죽는다.**
   기계 자격증명(API 키·mTLS) 경로는 정본에 없다 → **새 결정이 필요하다.**

그래서 `.env.example` 은 **0 으로 두고** 화면 상단 `CSRF 미적용 (D-60)` 배지도 그대로 뒀다 —
조용히 꺼진 보안 장치를 만들지 않는다(G-30). 배지는 `ENFORCE` 를 1 로 올리면 자동으로 사라진다
(`templating.render()` → `csrf_enforced` → `base.html:16`). 실측 근거는 `.env.example` 주석에 적었다.
**G-26 은 이 이유로 FAIL 로 남는다.**

## 건드리지 않은 것 (그대로가 정직하다)

- **ML 학습** — G-14~G-19 `차단` 유지. 합성 라벨·합성 예측 **0건**.
- **Feature 6종** — `cad/pipeline.py:38 BLOCKED_FEATURES` 5종 D-05 그대로. **G-13 은 `차단`이 정직한 끝**이고
  `tools/check_ingest.py` 는 아직 `FAIL` 로 낸다(남은 결함이 이 1건뿐이다 — QA 갱신 대기).
- **RAG 임계값 0.70** (DEF-QA3-008) · **G-08·09·10 분모 0** (D-56).

## 검증 명령

```
make db-reset && uv run pytest -q                 # QA 표지 외 실패 0 (14 failed 전부 tests/test_qa*.py)
uv run pytest -q tests/test_dev3_cad.py           # 13 passed · skip 0
uv run python tools/check_ai.py                   # G-25 미충족 4/5 (롤백 경로 있음)
uv run python tools/check_security.py             # CSRF 31/31 · G-29 PASS
uv run python tools/gate.py                       # PASS 16 · FAIL 5 · 차단 11 · 미구현 0
```
