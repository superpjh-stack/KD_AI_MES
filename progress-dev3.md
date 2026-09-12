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

---

## 2026-09-12 회전 — 원본 아카이브 실측 · DXF 파서 · 견적 파서 (D-109 ~ D-115)

**지금까지 우리는 통계 xlsx 4종만 읽고 실제 도면·견적을 한 번도 열지 않았다.** 이번에 원본 폴더를
직접 훑었다. **원본은 읽기만 했다 — 한 바이트도 고치지 않았다.**

원본: `/Users/…/01 경동글로벌텍 제조AI 플랫폼 구축 프로젝트/01 경동Data`
(환경변수 `KYUNGDONG_CAD_ARCHIVE` 로 바꾼다. 없는 장비에서는 `archive.available()` 이 False 다)

### 새로 만든 것

| 파일 | 하는 일 |
|---|---|
| `src/kyungdong/cad/archive.py` | 원본 폴더 스캐너. NFC 정규화 · GD 프로젝트번호 파싱 · 도면/견적 분류 · 조인 집계 |
| `src/kyungdong/cad/dxf.py` | **순수 파이썬 DXF 파서** — 외부 라이브러리 없이 group code 로 읽는다 |
| `src/kyungdong/cad/quote.py` | **과거 견적(.xls) 파서** — 총액·납기·품목명세. `xlrd` 만 쓴다 |
| `tools/cad_ingest.py --source archive` | 위 셋을 묶어 실측 리포트 + `docs/cad/archive_scan.json` |
| `tests/test_dev3_dxf.py` | 손으로 계산한 정답이 붙은 최소 DXF 로 파서를 검증(26건) |

### ① 원본 아카이브 — 실측 (D-109)

| 항목 | 실측 | 비고 |
|---|---|---|
| 파일 | **6,038** 건 | D-109 재현 |
| CAD 파일 | **3,299** 건 (dwg 2,240 · cad 1,030 · **dxf 29**) | **이것이 도면 모집단이다** |
| PDF | 730 건 | 도면·견적·카탈로그가 섞여 있다 — **분류하지 않았다** |
| 견적 파일 | **73** 건 (xls 31 · pdf 29 · docx 8 · pptx 3 · jpg 2) | D-111 재현 |

⚠ **macOS 파일명은 NFD 다** (D-115). `unicodedata.normalize('NFC', …)` 없이 `견적` 을 찾으면
**0건**이 나온다. `archive.nfc()` · `quote.nfc()` 가 전부 거쳐 간다. 회귀 시험을 붙여 뒀다
(`test_NFC_정규화_없이는_한글을_못_찾는다`).

### ② 프로젝트(수주)번호 — 폴더명 파싱 (D-112)

정규식 `^GD[\s_-]?(?P<yymm>\d{4})(?P<seq>\d{2})?(?P<tail>(?:[\s_-]+\d{2})*)[\s_-]*(?P<rest>.*)$`

| 항목 | 실측 |
|---|---|
| GD 폴더 | **99** 개 · 파싱 성공 **99** · **실패 0** |
| 서로 다른 프로젝트번호 | **34** 개 — 99 중 65 는 `20 경동도면함/` 아래 **복사본**이다. **99를 프로젝트 수로 쓰면 부풀린 것이다** |
| 제품군 적중 | **40/99 (40%)** — 진공건조기 8 · 저장탱크 11 · 누체필터 10 · 교반기 6 · 반응기 5 · **미상 59** |
| 고객사 적중 | **40/99 (40%)** — 폴더명 파생 **후보**다 |

### ③ 도면 ↔ 견적 조인 (D-113) — 세는 방식이 둘이고 답이 다르다

| 정의 | 실측 |
|---|---|
| 한 폴더가 도면과 견적을 **직접** 담고 있다 | **21** 폴더 |
| 그 폴더 **아래 어딘가에** 둘 다 있다 (상위 폴더도 세어진다) | **46** 폴더 |
| 최대 | `REACTOR/반응기` 도면 **304** · 견적 **32** (D-113 재현) |

**이 표본으로 ML 을 돌리지 않는다.** 조인되는 프로젝트가 수십 건이면 학습 표본으로 작다.

### ④ DXF 실측 — **D-05 판정 정정** (D-110-b)

**D-05 가 "Feature 5종 전부 차단" 이라 적은 것은 `.dwg` 에는 맞고 `.dxf` 에는 틀렸다.**
`.dxf` 는 순수 텍스트라 group code 파싱만으로 형상이 나온다 — Autodesk API 도 OCR 도 필요 없다.

**표본: dxf 29건 / CAD 모집단 3,299건 = 0.9%.**
**내용 해시로 복사본을 걷어내면 서로 다른 도면 9건.** 읽기 실패 **0**.
**이 9건으로 G-14(CAD 객체 인식 80%)를 주장하지 않는다.**

| Feature | 몇 건에서 뽑았나 | 방법 |
|---|---|---|
| **총 절단장** | **9/9 (100%)** | LINE 길이 + ARC 호길이(r·Δθ) + (LW)POLYLINE 구간합 |
| **홀 수량** | **7/9 (77%)** | `CIRCLE` 엔티티 **전량**. **지름 필터를 걸지 않았다** — 무엇이 홀이고 무엇이 계기 버블인지 가르는 기준이 자료에 없다 |
| **판재 면적** | **5/9 (55%)** | 닫힌 (LW)POLYLINE shoelace |
| **재질** | **5/9 (55%)** | TEXT/MTEXT 표제란 정규식 `MATERIAL_RE` (STS304·STS316L·SUS316·A240 …) |
| **두께** | **5/9 (55%)** | `THICKNESS_RE` — `t=6` · `10T` · `THK 8` · `두께 6`. **단위 없는 맨 숫자는 잡지 않는다** |
| **용접장** | **0/9** | 용접선 레이어·객체 표준이 도면에 없다 — **DXF 를 읽어도 못 가른다 (차단)** |

도면별 실측 (일부): `건조기 20170822.dxf` 엔티티 13,046 · CIRCLE 1,443 · 절단장 1,892,440 ·
`[DOOSAN-PID_ALL-ADDITIVE…dxf` 145.9MB · 엔티티 1,024,451 · 2.2초에 읽는다(스트리밍).

**못 센 것을 센 척하지 않는다**
- `INSERT` 가 참조하는 `BLOCK` 내부 형상은 **전개하지 않았다**. 길이·개수가 그만큼 **적게** 나온다.
  `inserts` 횟수를 Feature 근거 문자열에 같이 적는다.
- 단위는 `$INSUNITS` 가 있는 파일에서만 안다(9건 중 1건). 나머지는 **'도면단위'** 다 — mm 라고 단정하지 않는다.
- **`재질` 은 값이 읽혀도 `EST_CAD_FEATURES.FEATURE_VALUE` 가 `NUMERIC(16,4)` 라 담을 자리가 없다.**
  차단 사유가 D-05(OCR)가 아니라 **스키마**다. `value=None` 으로 돌려주고 그 사실을 적는다.

`cad/pipeline.BLOCKED_FEATURES` 를 **파일 형식별로 갈랐다** — `FORMAT_FEATURE_SUPPORT` ·
`support_for(file_type)` · `blocked_for(file_type)`.

| 형식 | 산출 가능 | 차단 |
|---|---|---|
| **DXF** (29건) | 홀 수량 · 총 절단장 · 판재 면적 · 두께 | 재질(스키마) · 용접장 |
| **DWG** (2,240건) | **없음** | 5종 전부 — 변환기 없음 (D-05) |
| **CAD** (1,030건) | **없음** | 5종 전부 — 변환기 없음 (D-05) |

### ⑤ 견적 실측 (D-111) — **D-04 의 Label 후보**

`.xls` **31 파일** → 내용 해시로 복사본 5건을 걷어내 **서로 다른 26건**. **열기 실패 0.**

| 항목 | 실측 |
|---|---|
| **총액 추출** | **22/26 (84%)** — 파일 경로 기준으로는 **27/31 (87%)** |
| 추출 방식 | 숫자셀 6 · **한자금액 8** · 괄호숫자 5 · 통화기호 3 |
| **총액 못 뽑음** | **4/26** — 갑지 없는 견적요청서·부품 계산시트, 또는 한 행에 금액 후보가 둘이라 **고르지 않았다** |
| 납기(일수) | **8/26 (30%)** · 관측값 **40 · 45 · 50 · 70 일** |
| 품목 명세 | **462 행 / 19 파일** |
| 갑지(시트) 단위 총액 | **90 건** · 한 파일에 견적이 여럿인 것 **8 건** — **파일 1건 ≠ 견적 1건이다** |
| 총액 범위 | 5,200,000 ~ 997,422,000 원 |

**"29/31 에서 금액 표기가 읽힌다"(D-111)와 "총액을 정확히 뽑았다"는 다른 사실이다.** 실제로 뽑은 것은
위 숫자다. 한자 수사(`伍億四阡七百參拾七萬伍阡` = 547,375,000)는 갖은자까지 읽되 **모르는 글자를
만나면 `None`** 이다 — 추측하지 않는다. `…六千萬院整` 처럼 **끝에 장식으로 붙은 단위 한 글자**는
떼고 읽는다(이걸 안 떼면 67,026,000 이 127,020,000 으로 두 배가 된다 — 실측으로 잡았다).

**한 행에 금액 후보가 둘 이상이면 고르지 않는다.** 예: `전기견적-석광.xls` 11행에
`1,759,443` 과 `5,200,000` 이 함께 있다 → 그 행은 버리고 사유를 `failures` 에 적는다.

### ⑥ 차단 — 잰 것을 **DB 에 못 넣는 이유** (그대로 남긴다)

| 표 | 왜 못 넣나 |
|---|---|
| **`EST_PROJECTS`** | `CUSTOMER_CODE` 가 NOT NULL 이고 `BAS_COMMON_CODES` **'고객사' 그룹이 0건**이다(D-47·D-56) → `require_code()` 가 422. 폴더명 고객사는 **파일시스템 파생 후보이지 도입기업 마스터가 아니다**(D-114) — 마스터로 승격하면 그게 합성이다. QA2 `test_G07_…` 도 `EST_PROJECTS == 0` 을 단언한다 |
| **`EST_QUOTATIONS`** | `PROJECT_ID` 가 NOT NULL FK → `EST_PROJECTS`. 위가 0건이면 **구조적으로 한 행도 못 넣는다**. 총액 22건·납기 8건은 실측했고 값은 `docs/cad/archive_scan.json` 에 있다 — **적재만** 막혀 있다 |
| **`EST_CAD_DRAWINGS` (원본 3,299건)** | 기본 경로가 통계 xlsx **1,283행**으로 이미 채워져 있다. 원천을 갈아끼우면 `DAT_TRAIN_DATASETS.TOTAL_CNT`·회귀·진행률 실측이 전부 어긋난다 → **정본(D-03) 개정이 먼저다.** 이번 회전은 **재기만** 했다 |
| **`EST_CAD_FEATURES` (DXF 실측)** | `tools/check_ingest.py` ⑤ 가 "확정 객체 0건 + Feature N행 = 합성" 으로 판정한다(G-13). DXF 실측은 합성이 아니지만 **그 검사기는 객체 집계만을 Feature 원천으로 안다.** 검사기는 QA 소유라 고치지 않았다 → `--dxf-features` 로 **명시 요구**할 때만 적재한다 |

`--dxf-features` 를 준 실측: **EST_CAD_DRAWINGS 995건 중 DXF 6건** → `EST_CAD_FEATURES` **18행 신규**
(재질 2건은 NUMERIC 컬럼이라 제외). `SOURCE_DESC` 는 전부 **`DXF 실측 —`** 로 시작해 합성과 구분된다.
**기본 실행에서는 0행이다.**

### 검증 (보고 전에 실행한 것)

```
make db-reset                                     # 테이블 68 · 시드 멱등
uv run python tools/cad_ingest.py                 # 1,283 스캔 → 995 등록 · 288 제외 (변동 없음)
uv run python tools/cad_ingest.py --source archive  # 위 ①~⑥ 실측 + docs/cad/archive_scan.json
uv run pytest -q                                  # **1,237 passed · 2 xfailed · 실패 0** (직전 1,210 → +27)
uv run python tools/gate.py                       # PASS 19 · FAIL 0 · 차단 13 · 미구현 0 / 32
uv run python tools/gate.py                       # **2회 연속 같은 판정** (차이는 지연 ms 뿐)
```

**기존 판정을 하나도 흔들지 않았다** — 회전 시작 전과 끝이 `PASS 19 · FAIL 0 · 차단 13` 으로 같다.
G-07 시드 멱등 · G-11 · G-20 · G-22 · G-24 · G-26 · G-29 전부 PASS 유지.

### 남은 차단 — **정직하게 차단으로 남긴다**

| 게이트 | 판정 | 이유 |
|---|---|---|
| G-14 CAD 객체 인식 80% | **차단** | 정답 박스 0건. **DXF 9건(전체 도면의 0.9%)으로 80% 를 주장하지 않는다** |
| G-15 견적 정확도 ±5% | **차단** | 총액 Label **후보** 22건을 찾았지만 `EST_QUOTATIONS` 적재가 FK 로 막혀 있고, 22건은 학습 표본으로 작다 |
| G-16 BOM 85% | **차단** | 기준 BOM 부재 · 품목·재질 코드 그룹 0건 (D-47) |
| G-17 납기 예측 85% | **차단** | 납기 Label **후보** 8건(40·45·50·70일). 8건으로는 못 잰다 |
| G-18 설명가능성 90% | **차단** | 전문가 평가 변수 목록 없음 (D-13) |
| G-13 Feature 6종 | **차단** | DWG·CAD 3,270건은 변환기 없음. DXF 29건만 산출 가능 |

### 도입기업 확인 요청 (추가)

7. **고객사 코드 마스터** — 폴더명에서 두루텍·한모루·동광제약·웰이엔씨·대한열기·대호테크·
   엔에프테크·비나텍·그린텍을 읽었다(D-114). **이것이 공식 코드인지 확인이 필요하다.**
   확인되면 `BAS_COMMON_CODES` '고객사' 그룹이 채워지고 `EST_PROJECTS`→`EST_QUOTATIONS` 가
   한 번에 열린다 — G-08·G-15·G-17 의 전제다.
8. **`.dwg` → `.dxf` 변환** — 3,270건을 DXF 로 내보내 주면 위 파서가 **그대로** 돌아간다.
   Autodesk API 계정보다 이쪽이 싸고 확실하다.
9. **홀 지름 기준** — `CIRCLE` 중 무엇이 가공 홀인지 가르는 지름 범위. 없으면 홀 수량은 '원 전량' 이다.

---

# 회전 — DWG 전량 변환 실측 (D-123 후속 · 개발3 단독)

`dwg2dxf`(GNU libredwg 0.14)가 설치돼 **D-05 의 "변환기 없음" 이 풀렸다.** D-123 이 표본 30건으로
잰 것을 **전량**으로 넓혔다. 새 도구 `tools/dwg_convert.py` 는 **한 건씩 흘려보낸다** —
변환 → 파싱 → Feature 적립 → **DXF 즉시 삭제**. 그래서 최대 디스크 사용이 **한 파일 크기**다
(전량 보관하면 팽창률 약 3배로 8.5GB). 산출물은 `docs/cad/dwg_features.json` (2.2MB).
**원본 폴더는 읽기만 했다 — 한 바이트도 쓰지 않았다.**

## ① 대상 파일 수 / 서로 다른 도면 수 — **둘은 다른 수다** (D-115)

| | 원본 파일 | 0바이트 제외 후 | 서로 다른 도면(내용 sha256) |
|---|---|---|---|
| `.dwg` | 2,240 | 2,235 | **802** |
| `.cad` | 1,030 | 1,024 | **325** |
| `.dxf` | 29 | 29 | **9** |
| **합** | **3,299** | **3,288** | **1,136** |

0바이트 손상 **11건**(dwg 5 · cad 6)을 뺐다. 중복 파일 **2,152건** — 한 도면이 최대 **8곳**에
복사돼 있다(`20 경동도면함/` 아래에 16~19 도면함이 통째로 또 있다 — D-320).
**`3,270건을 처리했다` 고 적으면 거짓이다 — 서로 다른 도면은 1,136건이다.**

## ② 변환 성공·실패 (사유별)

변환 대상 = `.dwg`+`.cad` 서로 다른 도면 **1,127건** (`.dxf` 9건은 변환 불필요).

| | 건수 | 비율 |
|---|---|---|
| **변환 성공** (0바이트 아닌 DXF 산출) | **772** | 68.5% |
| 변환 실패 | **355** | 31.5% |
| (성공분 중 `rc≠0` 이지만 DXF 는 나온 것) | 4 | — |

**실패는 DWG 버전으로 완전히 갈린다** — "30%가 무작위로 실패" 가 아니다.

| 앞 6바이트 서명 | 대상 | 성공 | 실패 | 성공률 |
|---|---|---|---|---|
| `AC1015` (R2000) | 360 | 360 | 0 | **100%** |
| `AC1021` (R2007) | 237 | 237 | 0 | **100%** |
| `AC1018` (R2004) | 77 | 77 | 0 | **100%** |
| `AC1024` (R2010) | 50 | 50 | 0 | **100%** |
| `AC1014` (R14) | 45 | 45 | 0 | **100%** |
| `AC1027` (R2013) | 2 | 2 | 0 | **100%** |
| `AC1032` (R2018) | 1 | 1 | 0 | **100%** |
| **`V10.00` (DWG 아님)** | **324** | 0 | 324 | **0%** |
| **`AC1009` (R11/R12)** | **30** | 0 | 30 | **0%** |
| `V15.00` (DWG 아님) | 1 | 0 | 1 | 0% |

실패 사유 (변환기 stderr 첫 오류줄을 경로·숫자만 지워 정규화 — **분류를 지어내지 않았다**)

| 사유 | 건수 |
|---|---|
| `ERROR: Invalid DWG, magic: V10.N` | 324 |
| `ERROR: DWG_SENTINEL_R11_BLOCK_END not found at N` | 17 |
| `Warning: Unknown flag (<hex>)` | 11 |
| `ERROR: DWG_SENTINEL_R11_LAYER_BEGIN not found at N` | 2 |
| `ERROR: Invalid DWG, magic: V15.N` | 1 |

**`.cad` 확장자는 AutoCAD DWG 가 아니다** (D-325) — 325건 전부 앞 6바이트가 `V10.00`/`V15.00` 로
서명 `AC1xxx` 가 아니다. libredwg 가 읽을 대상 자체가 아니라 **성공률 0%** 다. 어느 CAD 의
포맷인지는 **단정하지 않는다** — 도입기업 확인 요청 ⑪. `.dwg` 만 보면 **802건 중 772건 = 96.3%** 다.

## ③ 파싱 성공

| | 건수 |
|---|---|
| 파싱 대상 (변환 성공 772 + 원본 DXF 9) | **781** |
| **파싱 성공** | **781 (100%)** |
| 파싱 실패 | 0 |

**변환 성공 772 ≠ 파싱 성공 781 ≠ Feature 산출 수** — 네 단계를 각각 센 것이 이 표들이다.

## ④ Feature 별 산출 건수와 비율

| Feature | 건수 | 파싱성공(781) 대비 | 서로 다른 도면(1,136) 대비 |
|---|---|---|---|
| 총 절단장 | **777** | 99.5% | 68.4% |
| 홀 수량 | **708** | 90.7% | 62.3% |
| 두께 | **591** | 75.7% | 52.0% |
| 재질 | **586** | 75.0% | 51.6% |
| 판재 면적 | **564** | 72.2% | 49.6% |
| **용접장** | **0** | **0%** | **0%** |

실측 합계 — 홀 **161,736개** · 절단장 **531,596,852** · 판재면적 **545,975,103,520**.
**단위를 섞어 더한 수다** — `$INSUNITS` 가 있는 것은 781건 중 mm 139 · inch 22 뿐이고
**620건은 `도면단위`**(단위 미상)다(D-323). 그래서 이 합계는 **규모 감각용이지 원가 환산에
바로 못 쓴다.** 재질 분포: STS304 200 · STS316L 199 · SUS304 69 · SS400 52 · SUS316L 28 ….
두께 분포: 3.0mm 92 · 12.0 60 · 6.0 57 · 4.0 50 · 5.0 43 ….

**용접장은 변환해도 0건이다** — 용접선 레이어·객체 표준이 도면에 없다(D-05). 변환으로 풀린
항목과 풀리지 않은 항목을 갈라 적었다.

## ⑤ DB 적재 — **부분 차단. 규칙을 우회하지 않았다** (D-327)

| 표 | 판정 |
|---|---|
| `EST_CAD_DRAWINGS` | **가능하다.** `PROJECT_ID` 가 **NULL 허용**이라 `EST_PROJECTS` 가 0행(D-120)이어도 도면만 적재된다 — `--load-db` 로 **781행 적재 실측 확인**. D-120 은 `EST_PROJECTS`·`EST_QUOTATIONS` 에만 걸린다 |
| `EST_CAD_FEATURES` | **차단.** 3,226행(절단장 777 + 홀 708 + 두께 591 + 재질 586 + 면적 564)을 넣어 **실제로 재 봤다** → `tools/check_ingest.py` ⑤ 가 결함 2건을 내고 **G-13 이 PASS → FAIL** 이 된다 |

검사기가 낸 결함 두 줄(실측 그대로)
```
결함 G-13 확정 객체가 0건인데 EST_CAD_FEATURES 가 3226행이다 — 원천 없이 만들어진 합성 Feature 다
결함 G-13 차단된 Feature 가 적재돼 있다: ['두께','판재 면적','재질','총 절단장']
```

**그 규칙이 맞다고 판단했다.** 확정(`CONFIRM_YN='Y'`)은 `review_object()` 의 **사람 승인**으로만
생기고(G-24), 승인을 지어낼 수는 없다. 검사기는 QA 소유라 고치지 않았다. 그래서 —
적재는 `--load-db --load-features` **명시 옵션**에서만 하고 **기본 실행은 DB 를 건드리지 않는다.**
실측값의 정본은 `docs/cad/dwg_features.json` 이고, 회전 종료 시 DB 는 `make db-reset` 상태(0행)다.
`--load-features` 를 주면 그 결과를 **경고로 먼저 찍는다.**

적재할 때의 `SOURCE_DESC` 는 **`DXF 실측(dwg2dxf 변환) — <원본파일명>`** 으로 시작해 합성과
구분된다(원본 DXF 는 `DXF 실측 — …`). **재질 586행은 `FEATURE_VALUE`= NULL** 이고 관측값을
`SOURCE_DESC` 에 `관측 재질=STS316L` 식으로 증거로 적는다 — **컬럼은 추가하지 않았다**(D-122 ·
G-02 762 고정). 숫자 칸에 코드번호를 만들어 넣지 않았다.

## ⑥ 차단 판정 갱신 — `BLOCKED_FEATURES` (D-324)

`cad/pipeline.py` 의 사유를 **"DWG·CAD 는 바이너리라 못 읽는다"** → **"변환 후 산출 가능 ·
변환 실패분은 차단"** 으로 바꿨다. 사유마다 **D-123** 을 적었다.
**`D-05` 는 지우지 않았다** — 그 결정이 무효가 된 것이 아니라 **차단 모집단이 3,270건에서
서로 다른 도면 355건으로 줄었다**(`.cad` 325 + `.dwg` R11/R12 30). QA 시험(`test_qa2_ingest`)이
사유에서 `D-05` 를 읽으므로 그것도 깨지 않는다.

- `FORMAT_FEATURE_SUPPORT["DWG"]` 에 4종(홀·절단장·면적·두께)을 넣었다. 단
  **`support_for('DWG')` 가 `shutil.which('dwg2dxf')` 로 재서 변환기가 없는 장비에서는 빈 표**
  (= D-05 그대로 전량 차단)를 돌려준다 — 있는 척하지 않는다.
- `FORMAT_FEATURE_SUPPORT["CAD"]` 는 **그대로 `{}`** 다 (변환 성공 0%).
- 새 모듈 `cad/dwgconv.py` — 변환기 껍데기(`available`·`signature`·`to_dxf`·`measured`).
  `measured()` 는 변환 → 파싱 → **즉시 삭제**를 한 번에 하고, 실패하면 `(None, 실패사유)` 다.
- `pipeline.dxf_measure()` 가 **DWG 도 받는다** — 변환해서 재고, 변환 실패는
  `measured=False` + `convert_error` 로 돌려준다. `.cad` 는 "DWG 서명이 아니라 대상이 아니다" 로 적는다.

## ⑦ G-14 — **여전히 차단이다. 표본이 늘어난 것과 라벨이 생긴 것은 다른 일이다** (D-328)

G-14 는 **CAD 객체 인식 80% 이상 (IoU 0.5 기준 Precision·Recall·F1)** 이다.

| 항목 | 실측 |
|---|---|
| `work/cad_labelset.json` `labels` (정답 박스) | **0 건** |
| 같은 파일 `predictions` | **0 건** |
| `EST_CAD_OBJECTS` | **0 행** |
| `docs`·`work`·`db` 안의 YOLO 라벨(`*.txt`) | **0 건** |

**판정: 차단.** 근거 —
1. **우리가 뽑은 것은 기하 집계다.** 홀 수량(CIRCLE 개수) · 절단장(길이합) · 면적(shoelace)은
   **도면에서 재어 합친 값**이다. G-14 가 요구하는 것은 **정답 박스 대비 탐지 정확도**다.
   TP/FP/FN 의 분모는 라벨이고, 라벨이 0이면 **80% 도 0% 도 아니다.**
2. 도면 표본이 9건 → **781건으로 87배 늘었다.** 그래도 **G-14 는 한 걸음도 움직이지 않는다** —
   늘어난 것은 **입력**이고 없는 것은 **정답**이다. 이 둘을 섞어 "표본이 2,000건이니 재 볼 수 있다"
   고 적으면 그게 광성 사업식 수치 조작이다.
3. **차단의 축은 하나로 줄었다** — 예측 박스는 이제 변환된 DXF 에서 뽑을 수 있으므로
   (엔티티 좌표가 있다) **남은 유일한 구속은 정답 라벨**이다. `docs/cad/라벨링 가이드.docx` 는
   여전히 계획 단계('MVP 100장 → 권장 300장')이고, 그 가이드의 클래스 3종
   (`title_block`·`bom_table`·`rev_table`)은 TD5 `OBJECT_TYPE` 5종(홀·슬롯·노즐·플랜지·치수문자)과
   **어휘가 다르다**. 어느 쪽이 G-14 측정 대상인지 정본이 아직 정하지 않았다.
4. **합성 박스를 만들지 않았다.** `cad_labelset.json` 의 `evaluator_selftest` 는 평가기 되돌림
   시험용이고 게이트 입력이 아니다 — 그 값을 실측란에 쓰지 않았다.

G-19 도 같은 이유로 건드리지 않았다.

## 검증 (보고 전에 직접 실행)

```
uv run python tools/dwg_convert.py --limit 20   # 소규모 — 변환 11/20 · 파싱 11/11
uv run python tools/dwg_convert.py              # 전량 — 도면 1,136 · 변환 772 · 파싱 781
make db-reset && uv run pytest                  # **1,239 passed · 2 xfailed · 실패 0** (직전 1,237 → +2)
uv run python tools/gate.py                     # PASS 19 · FAIL 0 · 차단 13 · 미구현 0 / 32
uv run python tools/gate.py                     # **2회 연속 같은 판정**
```

**기존 판정을 하나도 흔들지 않았다** — 회전 시작 전과 끝이 `PASS 19 · FAIL 0 · 차단 13` 으로 같다.
G-07 시드 멱등 · G-11 · G-12 · KPI · G-20 · G-22 · G-24 · G-26 · G-29 전부 PASS 유지.
G-07 은 실제로 한 번 깼다가 고쳤다 — `datetime.now()` 가 금지(§10-3)인데 새 도구에 두 곳 있었다.
`check_data.NOW_ALLOWED`(QA 소유)를 고치지 않고 **DB 시계 `clock.real_now()`** 로 바꿨고,
DB 를 못 읽으면 파이썬 시계로 **조용히 대체하지 않고 그 사실을 적는다.**

중간 DXF 는 실행 끝에 `work/dwg_convert_tmp/` 가 **0B** 인 것으로 확인했다. 재개 원장은
`work/dwg_convert.jsonl`(1,136줄) · 해시 캐시는 `work/dwg_hash_index.json` 이고,
다시 돌리면 **이미 처리한 해시를 건너뛴다**(`이미 처리 1136 · 이번에 처리 0`).
