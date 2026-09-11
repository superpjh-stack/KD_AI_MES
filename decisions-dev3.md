# decisions-dev3.md — 개발3(AI) 결정 대장 (D-3nn 대역)

`확정` / `가설` / `차단` 세 상태만 쓴다. 공용 대장은 `decisions.md` 이고 여기는 **개발3 소유 결정**이다.
근거가 없으면 `차단` 으로 남긴다 — 수치를 만들지 않는다.

---

## 회전 6 (2026-09-11) — R1-a 수집 · R1-c RAG · R2 화면 골격

| ID | 상태 | 내용 | 근거·처리 |
|---|---|---|---|
| **D-301** | 확정 | **`EST_SHAP_FACTORS` 는 런타임 전용 표다** — 시드 대상이 아니다 (`contracts/db-schema.md` §7.1 판정) | `EST_SHAP_FACTORS.PREDICT_ID` 가 `EST_ML_PREDICTIONS`(런타임 전용, G-11)를 **NOT NULL FK** 로 본다. 예측이 0건이면 SHAP 행은 존재할 수 없다. → §7 런타임 전용 목록으로 옮긴다. 깨끗한 DB 에서 **0건이 정상**이고 화면 015 는 `미수집` 을 렌더한다 |
| **D-302** | 차단 | **`contracts/api-contract.md` §5 의 `ADOPT_YN`·`ADOPT_BY` 컬럼이 TD5 에 없다.** `AGT_RECOMMENDATIONS` 는 `REVIEW_STATUS`(미검토/승인/수정/반려) · `REVIEWER_ID` 만 가진다 | **컬럼을 추가하지 않는다**(G-02 762 고정). `POST /api/agent/recommend/{id}/adopt` 는 `REVIEW_STATUS`·`REVIEWER_ID`·`UPDATED_DT` 로 기록한다. 계약 문서 문구 수정을 아키텍트에게 요청한다 |
| **D-303** | 차단 | **`AGT_VECTOR_DOCS.DOC_TYPE` 어휘에 '견적·조달 기준' 구분이 없다.** TD5 비고는 입고기준서/검사기준서/SOP/출하기준서/클레임 매뉴얼 5종이다 | 시안 `quote_and_procurement_guide.md` 를 `IF_EXT_DOCUMENTS` 에 **등록만 하고 임베딩 대상에서 뺐다**(`EMBED_TARGET_YN='N'`). 어휘에 없는 구분을 만들어 넣지 않는다. 구분 추가를 도입기업에 제안 |
| **D-304** | 차단 | **도면 중복 제거 키의 '고객사' 축이 없다.** `DAT_DATASET_ITEMS.DEDUP_KEY` 비고는 「도면번호+버전+고객사」인데 실측 인벤토리(`docs/cad/…제품별정리.xlsx`)에 **고객사 열이 없다**(D-03) | 고객사를 지어내지 않고 제품/프로젝트 폴더명을 **대체 축**으로 쓴다(`--scope product`, 키에 `[대체 표기 D-03]` 표기). 고객사 없이 본 결과(`--scope none`)도 함께 측정해 둔다 — **등록 893 / 제외 390** vs 대체 축 **등록 995 / 제외 288**. 고객사 메타데이터 확보를 도입기업에 요청 |
| **D-305** | 차단 | **수집 데이터의 원천(실측/시뮬레이터) 구분 컬럼이 TD5 에 없다.** `IF_PLC_SIGNALS`·`PRC_EQUIP_SIGNALS` 에 출처 열이 없다 | 컬럼을 추가하지 않고 `DAT_TIMESERIES.COLLECT_PATH`(비고 "PLC→Gateway→시계열DB")에 **`시뮬레이터(PLC→Gateway)`** 를 적어 구분한다. `--realtime` 으로 넣은 것만 실수집 경로 문자열을 쓴다. 정규 출처 컬럼 신설을 제안 |
| **D-306** | 확정 | **`app/routers/ingest.py` 는 `main.py` 가 싣지 않는다.** `main.py` 는 `nav.all_screens()` 의 module 집합만 임포트하는데 인터페이스 3종(TD4-047·048·049)은 **화면이 없다** | `main.py` 를 건드리지 않고 `routers/agt.py` 끝에서 `router.include_router(ingest.router)` 로 싣는다. `ingest.SCREENS` 는 빈 튜플이라 placeholder 판정에 영향이 없다 |
| **D-307** | 가설 | **인증 전까지 질의 사용자 해석.** `AGT_QUERY_LOGS.USER_ID` 가 NOT NULL FK 라 사용자를 모르면 "질의 100% 기록" 이 깨진다 | `agent.service.resolve_user(role_code)` 가 `SYS_ROLE_PERMISSIONS.ROLE_CODE` 로 역할 대표 계정을 찾는다. **개발용 보조이며 D-40 의 연장이다** — 개발1 이 인증을 넣으면 세션이 대체하고 이 함수와 `main.py` 역할 전환 미들웨어를 함께 지운다. 남아 있으면 보안 결함 |
| **D-308** | 차단 | **확정 객체로 실제 집계 가능한 Feature 는 `홀 수량` 1종뿐이다.** TD5 `EST_CAD_FEATURES.FEATURE_TYPE` 어휘 6종 중 나머지 5종(총 절단장·판재 면적·용접장·재질·두께)은 `EST_CAD_OBJECTS` 에 원천 컬럼이 없다 | 0 이나 추정값으로 채우지 않는다. `cad.pipeline.BLOCKED_FEATURES` 에 사유를 적고 화면 011 이 그대로 렌더한다. 경로 길이·외곽 좌표·표제란 OCR 확보 후 해제 (D-05) |
| **D-309** | 확정 | **이번 회전에 ML 학습을 하지 않았다**(goal.md §10-2 — 학습이 있는 회전은 단독 기동) | `kyungdong/ml/` 에는 **읽기 경로와 차단 사유만** 둔다. `EST_ML_MODELS`·`_TRAIN_RUNS`·`_PREDICTIONS` 0건. 성능 수치를 만들지 않는다 |
| **D-310** | 확정 | **LLM·임베딩 공급자 호출 구현이 없다.** `.env` 에 값을 넣어도 `501 LLM 미구성` 이다 | "구성됐다고 선언했는데 실제로 없다" 를 조용히 넘기면 §2.5 위반이다. `agent/llm.py` 의 `KNOWN_PROVIDERS`·`_CHAT`·`_EMBED` 에 핸들러가 등록돼야 `configured` 가 참이 된다. 모델명·엔드포인트 확정 대기 (D-08) |
| **D-311** | 확정 | **한국어 키워드 검색은 `to_tsvector('simple', …)` 만으로 부족하다.** 조사가 붙으면 놓친다 | 시안과 같은 **바이그램 보조 검색**을 둔다(`retrieval.search` 2단계). 점수는 매칭 비율(0~1)이고 임계(D-10)와 비교한다. 임베딩이 들어오면 `vector_pgvector` 로 올라간다 |
| **D-312** | 확정 | **정제 규칙이 D-03 의 183건보다 더 많이 제외한다 — 실측 284건**(대체 축 기준) | 파일명 완전일치 중복은 **183건(D-03 재현)** 이고, 여기에 확장자만 다른 같은 도면(`.cad` ↔ `.dwg`)과 버전 토큰 분리로 묶이는 것이 더해져 **284건**이 된다. 두 수치를 모두 보고한다 — 하나만 적으면 오해를 부른다 |
| **D-313** | 확정 | **`app/routers/__init__.py` 는 소유자가 지정되지 않은 파일이다.** 패키지 인식용으로 docstring 만 넣었다 | 다른 개발자가 같은 파일에 내용을 넣으면 **충돌한다**. 여기에는 로직을 두지 않는다 |

---

## 시그니처 변경 요청 — 아키텍트에게

| 대상 | 요청 |
|---|---|
| `contracts/api-contract.md` §5 | `ADOPT_YN`·`ADOPT_BY` → `REVIEW_STATUS`·`REVIEWER_ID` 로 문구 수정 (D-302) |
| `contracts/db-schema.md` §7 | `EST_SHAP_FACTORS` 를 §7.1(미정)에서 §7(런타임 전용)로 이동 (D-301) |
| `contracts/interfaces.md` §9 | `ingest` 수집 API 행에 `collector.status()` 공표 시그니처 링크 추가 |

## 도입기업 확인 요청

1. **과거 견적금액·실제 제조원가 Label** 보유 여부와 규모 (D-04) — 없으면 G-15·G-17 은 영구 차단이다.
2. **Autodesk API 계정 · YOLOv8 가중치 · OCR 엔진** 확보 계획 (D-05).
3. **도면 고객사 메타데이터** — 중복 제거 키의 세 번째 축 (D-304).
4. **설명가능성 전문가 평가 변수 목록** (D-13) — 없으면 G-18 차단.
5. **LLM·임베딩 모델명과 엔드포인트** (D-08).
6. **품목·재질 코드 마스터** (D-47) — 없으면 BOM Rule 전개가 돌지 않는다.
