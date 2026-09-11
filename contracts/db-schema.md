# contracts/db-schema.md — 테이블 68 · 컬럼 762

> **생성 파일이다.** 정본은 `docs/design/design.json` 의 SF-TD5 이고 `tools/gen_db_contract.py` 가 뽑는다.
> 스키마 자체는 `tools/gen_schema.py` → `db/schema.sql`. **`schema.sql` 을 손으로 고치지 않는다.**
> **코드와 다르면 코드가 맞다**(goal.md §4.1) → 생성기를 고치고 다시 뽑는다.

테이블 **68** · 컬럼 **762** · 물리 FK 제약 **98** · 코드성 참조(FK 미생성) **29** · 오표기 **1**

## 0. 개발자가 먼저 알아야 할 것

| # | 규약 |
|---|---|
| 1 | **모든 업무 테이블의 최상위 조회 축은 `EST_PROJECTS.PROJECT_NO`(프로젝트=수주번호)** 다. LOT 는 그 하위 식별자다 (TD3 standard_note 2). 반복 생산의 라인·배치 축으로 쿼리를 짜면 이 사업이 아니다 |
| 2 | **코드성 FK 29건은 DB 가 막아주지 않는다**(D-32). 아래 §3 목록은 애플리케이션이 검증해야 한다 |
| 3 | **런타임 전용 표는 깨끗한 DB 에서 0건이 정상**이다(G-11). 화면은 그때 `미수집` 문구를 렌더해야 하고, 테스트는 **0건 경로와 N건 경로를 둘 다 단언**한다(§10-4) |
| 4 | **건수 카드의 `0 건` 은 정답이다** — 빈 그리드에만 문구가 필요하다(§10-14) |
| 5 | 개인정보 컬럼(§6)은 **암호화 저장 + 화면 마스킹**(G-29). 시드에 실명을 넣지 않는다 |
| 6 | 파라미터는 항상 바인딩한다. `db/conn.py` 의 `q`·`q1`·`x`·`tx` 만 쓰고 **DB 장애는 503**(빈 배열 금지) |
| 7 | 시간 기준일은 `SYS_CONFIGS` 시간 앵커에 고정한다 — `date.today()` 금지(§10-3) |

## 1. 업무영역별 테이블

| 업무영역 | 표 | 컬럼 |
|---|---|---|
| 기준정보관리 | **3** — `BAS_COMMON_CODES`, `BAS_QUALITY_STANDARDS`, `BAS_WORK_STANDARDS` | 40 |
| 사용자/시스템관리 | **4** — `SYS_ACCESS_LOGS`, `SYS_CONFIGS`, `SYS_ROLE_PERMISSIONS`, `SYS_USERS` | 46 |
| 입고재고관리 | **6** — `INV_MATERIAL_HISTORY`, `INV_MATERIAL_LOTS`, `INV_RECEIPTS`, `INV_STOCKS`, `INV_SUPPLIERS`, `INV_SUPPLIER_QUALITY` | 73 |
| 수주견적AI관리 | **16** — `EST_BOM_HEADERS`, `EST_BOM_ITEMS`, `EST_BOM_ROUTINGS`, `EST_CAD_DRAWINGS`, `EST_CAD_FEATURES`, `EST_CAD_OBJECTS`, `EST_COST_RATES`, `EST_MATERIAL_REQS`, `EST_ML_MODELS`, `EST_ML_PREDICTIONS`, `EST_ML_TRAIN_RUNS`, `EST_OBJECT_REVIEWS`, `EST_PROJECTS`, `EST_QUOTATIONS`, `EST_QUOTATION_ITEMS`, `EST_SHAP_FACTORS` | 182 |
| 출하물류관리 | **6** — `SHP_CLAIMS`, `SHP_CLAIM_CAUSES`, `SHP_INSPECTIONS`, `SHP_LOT_TRACES`, `SHP_SHIPMENTS`, `SHP_SHIPMENT_ITEMS` | 72 |
| 공정관리 | **7** — `PRC_ACTUAL_CONDITIONS`, `PRC_CONDITION_DEVIATIONS`, `PRC_EQUIP_SIGNALS`, `PRC_PERFORMANCES`, `PRC_PROCESS_HISTORIES`, `PRC_STD_CONDITIONS`, `PRC_WORK_ORDERS` | 84 |
| 데이터관리 | **11** — `DAT_DATASET_ITEMS`, `DAT_DATASET_SPLITS`, `DAT_DOWNLOAD_LOGS`, `DAT_INTEGRATION_JOBS`, `DAT_JOB_LOGS`, `DAT_LAKE_OBJECTS`, `DAT_PREPROCESS_RULES`, `DAT_QUALITY_CHECKS`, `DAT_SOURCES`, `DAT_TIMESERIES`, `DAT_TRAIN_DATASETS` | 109 |
| AI Agent 통합관리 | **3** — `AGT_QUERY_LOGS`, `AGT_RECOMMENDATIONS`, `AGT_VECTOR_DOCS` | 33 |
| KPI관리 | **2** — `KPI_MEASURES`, `KPI_TARGETS` | 25 |
| 인터페이스 | **10** — `IF_CAD_FILES`, `IF_CAD_IMPORT_LOGS`, `IF_DEVICE_REGISTRY`, `IF_DOC_EMBED_LOGS`, `IF_ERP_RECEIPTS`, `IF_ERP_SHIPMENTS`, `IF_ERP_STOCKS`, `IF_EXT_DOCUMENTS`, `IF_GATEWAY_BUFFER`, `IF_PLC_SIGNALS` | 98 |

접두 합계: `AGT` 3 · `BAS` 3 · `DAT` 11 · `EST` 16 · `IF` 10 · `INV` 6 · `KPI` 2 · `PRC` 7 · `SHP` 6 · `SYS` 4 = **68**

## 2. 테이블 상세

| 표 | 이름 | 컬럼 | PK | 사용 프로그램 |
|---|---|---|---|---|
| `AGT_QUERY_LOGS` | AI질의이력 | 10 | `QUERY_ID` | MES-TD4-009, MES-TD4-020, MES-TD4-038, MES-TD4-042 |
| `AGT_RECOMMENDATIONS` | AI분석·추천결과 | 12 | `RECO_ID` | MES-TD4-028, MES-TD4-038, MES-TD4-039, MES-TD4-040, MES-TD4-041 |
| `AGT_VECTOR_DOCS` | Vector문서임베딩 | 11 | `DOC_ID` | MES-TD4-009, MES-TD4-020, MES-TD4-031, MES-TD4-038, MES-TD4-042, MES-TD4-049 |
| `BAS_COMMON_CODES` | 공통코드관리 | 12 | `CODE_ID` | MES-TD4-021, MES-TD4-030, MES-TD4-031, MES-TD4-032 |
| `BAS_QUALITY_STANDARDS` | 품질기준관리 | 15 | `QSTD_ID` | MES-TD4-002, MES-TD4-018, MES-TD4-030 |
| `BAS_WORK_STANDARDS` | 작업표준관리 | 13 | `WSTD_ID` | MES-TD4-023, MES-TD4-031, MES-TD4-049 |
| `DAT_DATASET_ITEMS` | 학습데이터항목 | 10 | `ITEM_ID` | MES-TD4-037 |
| `DAT_DATASET_SPLITS` | 학습데이터분할 | 8 | `SPLIT_ID` | MES-TD4-037 |
| `DAT_DOWNLOAD_LOGS` | 데이터다운로드이력 | 10 | `DOWNLOAD_ID` | MES-TD4-027, MES-TD4-036 |
| `DAT_INTEGRATION_JOBS` | 데이터통합작업 | 11 | `JOB_ID` | MES-TD4-033 |
| `DAT_JOB_LOGS` | 통합작업실행로그 | 9 | `JOB_LOG_ID` | MES-TD4-033 |
| `DAT_LAKE_OBJECTS` | 비정형데이터저장소 | 10 | `LAKE_OBJ_ID` | MES-TD4-034, MES-TD4-048 |
| `DAT_PREPROCESS_RULES` | 전처리규칙 | 10 | `RULE_ID` | MES-TD4-037 |
| `DAT_QUALITY_CHECKS` | 데이터품질검증 | 10 | `CHECK_ID` | MES-TD4-007, MES-TD4-033, MES-TD4-034 |
| `DAT_SOURCES` | 데이터수집대상관리 | 11 | `SOURCE_ID` | MES-TD4-029, MES-TD4-033 |
| `DAT_TIMESERIES` | 시계열데이터 | 9 | `TS_ID` | MES-TD4-022, MES-TD4-034, MES-TD4-035, MES-TD4-047 |
| `DAT_TRAIN_DATASETS` | AI학습데이터셋 | 11 | `DATASET_ID` | MES-TD4-014, MES-TD4-037 |
| `EST_BOM_HEADERS` | BOM헤더 | 12 | `BOM_ID` | MES-TD4-013, MES-TD4-017 |
| `EST_BOM_ITEMS` | BOM자재구성 | 12 | `BOM_ITEM_ID` | MES-TD4-013 |
| `EST_BOM_ROUTINGS` | BOM공정구조 | 10 | `ROUTING_ID` | MES-TD4-013 |
| `EST_CAD_DRAWINGS` | CAD도면관리 | 13 | `DRAWING_ID` | MES-TD4-010, MES-TD4-011, MES-TD4-048 |
| `EST_CAD_FEATURES` | 도면Feature관리 | 10 | `FEATURE_ID` | MES-TD4-011, MES-TD4-012, MES-TD4-015 |
| `EST_CAD_OBJECTS` | 도면객체인식결과 | 12 | `OBJECT_ID` | MES-TD4-010, MES-TD4-011 |
| `EST_COST_RATES` | 원가단가기준 | 11 | `RATE_ID` | MES-TD4-012 |
| `EST_MATERIAL_REQS` | 자재소요량 | 10 | `REQ_ID` | MES-TD4-013 |
| `EST_ML_MODELS` | ML모델관리 | 12 | `MODEL_ID` | MES-TD4-014 |
| `EST_ML_PREDICTIONS` | ML예측결과 | 10 | `PREDICT_ID` | MES-TD4-014, MES-TD4-015, MES-TD4-040 |
| `EST_ML_TRAIN_RUNS` | ML학습이력 | 11 | `TRAIN_RUN_ID` | MES-TD4-014 |
| `EST_OBJECT_REVIEWS` | 객체인식검증이력 | 10 | `REVIEW_ID` | MES-TD4-011 |
| `EST_PROJECTS` | 수주프로젝트관리 | 13 | `PROJECT_ID` | MES-TD4-001, MES-TD4-004, MES-TD4-010, MES-TD4-016, MES-TD4-040, MES-TD4-045 |
| `EST_QUOTATIONS` | 견적관리 | 16 | `QUOTE_ID` | MES-TD4-012, MES-TD4-015, MES-TD4-035 |
| `EST_QUOTATION_ITEMS` | 견적공정원가내역 | 11 | `QUOTE_ITEM_ID` | MES-TD4-012 |
| `EST_SHAP_FACTORS` | SHAP영향요인 | 9 | `SHAP_ID` | MES-TD4-015 |
| `IF_CAD_FILES` | CAD파일수집 | 10 | `CAD_IF_ID` | MES-TD4-010, MES-TD4-048 |
| `IF_CAD_IMPORT_LOGS` | CAD수집로그 | 8 | `CAD_LOG_ID` | MES-TD4-048 |
| `IF_DEVICE_REGISTRY` | 수집장비등록 | 11 | `DEVICE_ID` | MES-TD4-003, MES-TD4-029, MES-TD4-047 |
| `IF_DOC_EMBED_LOGS` | 문서임베딩로그 | 9 | `EMBED_LOG_ID` | MES-TD4-049 |
| `IF_ERP_RECEIPTS` | ERP입고연계 | 11 | `IF_ID` | MES-TD4-007, MES-TD4-046 |
| `IF_ERP_SHIPMENTS` | ERP출하연계 | 11 | `IF_ID` | MES-TD4-016, MES-TD4-046 |
| `IF_ERP_STOCKS` | ERP재고연계 | 10 | `IF_ID` | MES-TD4-046 |
| `IF_EXT_DOCUMENTS` | 외부표준문서 | 9 | `EXT_DOC_ID` | MES-TD4-049 |
| `IF_GATEWAY_BUFFER` | Gateway버퍼 | 9 | `BUFFER_ID` | MES-TD4-047 |
| `IF_PLC_SIGNALS` | PLC신호수집 | 10 | `PLC_IF_ID` | MES-TD4-003, MES-TD4-022, MES-TD4-047 |
| `INV_MATERIAL_HISTORY` | 원자재이력관리 | 11 | `HIST_ID` | MES-TD4-006 |
| `INV_MATERIAL_LOTS` | 자재LOT관리 | 12 | `LOT_ID` | MES-TD4-005, MES-TD4-006, MES-TD4-009, MES-TD4-017 |
| `INV_RECEIPTS` | 입고관리 | 15 | `RECEIPT_ID` | MES-TD4-005, MES-TD4-007, MES-TD4-008, MES-TD4-009, MES-TD4-046 |
| `INV_STOCKS` | 재고관리 | 11 | `STOCK_ID` | MES-TD4-005, MES-TD4-007, MES-TD4-046 |
| `INV_SUPPLIERS` | 공급처관리 | 12 | `SUPPLIER_ID` | MES-TD4-005, MES-TD4-008 |
| `INV_SUPPLIER_QUALITY` | 공급처품질평가 | 12 | `SQ_ID` | MES-TD4-008 |
| `KPI_MEASURES` | KPI측정실적 | 10 | `MEASURE_ID` | MES-TD4-035, MES-TD4-043, MES-TD4-044, MES-TD4-045 |
| `KPI_TARGETS` | KPI목표관리 | 15 | `KPI_TARGET_ID` | MES-TD4-043, MES-TD4-045 |
| `PRC_ACTUAL_CONDITIONS` | 실측작업조건 | 9 | `ACT_COND_ID` | MES-TD4-023 |
| `PRC_CONDITION_DEVIATIONS` | 작업조건편차 | 9 | `DEVIATION_ID` | MES-TD4-023, MES-TD4-025, MES-TD4-039 |
| `PRC_EQUIP_SIGNALS` | 설비·공정수집데이터 | 13 | `SIGNAL_ID` | MES-TD4-001, MES-TD4-003, MES-TD4-022, MES-TD4-041, MES-TD4-047 |
| `PRC_PERFORMANCES` | 공정실적관리 | 14 | `PERF_ID` | MES-TD4-001, MES-TD4-002, MES-TD4-021, MES-TD4-024, MES-TD4-025, MES-TD4-035, MES-TD4-039, MES-TD4-043, MES-TD4-044 |
| `PRC_PROCESS_HISTORIES` | 공정이력관리 | 11 | `PRC_HIST_ID` | MES-TD4-017, MES-TD4-024, MES-TD4-025, MES-TD4-043 |
| `PRC_STD_CONDITIONS` | 표준작업조건 | 13 | `STD_COND_ID` | MES-TD4-023, MES-TD4-031, MES-TD4-040 |
| `PRC_WORK_ORDERS` | 작업지시관리 | 15 | `WORK_ORDER_ID` | MES-TD4-001, MES-TD4-006, MES-TD4-021, MES-TD4-024 |
| `SHP_CLAIMS` | 클레임관리 | 13 | `CLAIM_ID` | MES-TD4-019, MES-TD4-044 |
| `SHP_CLAIM_CAUSES` | 클레임원인분석 | 10 | `CAUSE_ID` | MES-TD4-008, MES-TD4-019 |
| `SHP_INSPECTIONS` | 출하검사결과 | 13 | `INSPECT_ID` | MES-TD4-002, MES-TD4-018, MES-TD4-019, MES-TD4-020, MES-TD4-025, MES-TD4-030, MES-TD4-039, MES-TD4-044 |
| `SHP_LOT_TRACES` | LOT추적관리 | 11 | `LOT_TRACE_ID` | MES-TD4-002, MES-TD4-004, MES-TD4-006, MES-TD4-017, MES-TD4-018, MES-TD4-019, MES-TD4-020, MES-TD4-021, MES-TD4-024, MES-TD4-034 |
| `SHP_SHIPMENTS` | 출하관리 | 14 | `SHIPMENT_ID` | MES-TD4-004, MES-TD4-016, MES-TD4-041, MES-TD4-045, MES-TD4-046 |
| `SHP_SHIPMENT_ITEMS` | 출하품목내역 | 11 | `SHIP_ITEM_ID` | MES-TD4-004, MES-TD4-016, MES-TD4-018 |
| `SYS_ACCESS_LOGS` | 접속·작업로그관리 | 10 | `LOG_ID` | MES-TD4-026, MES-TD4-027 |
| `SYS_CONFIGS` | 시스템·알림설정관리 | 12 | `CONFIG_ID` | MES-TD4-003, MES-TD4-022, MES-TD4-028, MES-TD4-029, MES-TD4-032, MES-TD4-041 |
| `SYS_ROLE_PERMISSIONS` | 역할권한관리 | 11 | `ROLE_PERM_ID` | MES-TD4-026, MES-TD4-036 |
| `SYS_USERS` | 사용자관리 | 13 | `USER_ID` | MES-TD4-026, MES-TD4-027, MES-TD4-028, MES-TD4-036, MES-TD4-042 |

## 3. D-32 — 코드성 참조 (물리 FK 미생성 · 애플리케이션 검증 필수)

TD5 비고는 `FK: BAS_COMMON_CODES` 를 가리키지만 컬럼 타입이 `VARCHAR` 다. 그 표의 PK 는
`CODE_ID BIGSERIAL` 이므로 물리 FK 를 걸 수 없다. **실제 의도는
`BAS_COMMON_CODES(CODE_GROUP, CODE_VALUE)` 참조**이고 그 조합에 복합 UNIQUE 가 있다(D-34).

→ 저장 전에 **코드 그룹 안에 값이 있는지** 확인한다. 공용 검증 함수를 한 곳에 두고 각자 호출한다.

| 표 | 컬럼 | 타입 | TD5 비고 |
|---|---|---|---|
| `BAS_QUALITY_STANDARDS` | `INSPECT_TYPE` | VARCHAR(30) | FK: BAS_COMMON_CODES (입고검사/출하검사) |
| `BAS_QUALITY_STANDARDS` | `PRODUCT_GROUP` | VARCHAR(50) | FK: BAS_COMMON_CODES (반응기·교반기·진공건조기·누체필터·저장탱크) |
| `BAS_WORK_STANDARDS` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES (10개 공정) |
| `DAT_TIMESERIES` | `EQUIP_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `EST_BOM_ITEMS` | `ITEM_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `EST_BOM_ITEMS` | `MATERIAL` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `EST_BOM_ROUTINGS` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `EST_COST_RATES` | `TARGET_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES (재질·공정·외주처) |
| `EST_MATERIAL_REQS` | `ITEM_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `EST_PROJECTS` | `CUSTOMER_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `EST_PROJECTS` | `PRODUCT_GROUP` | VARCHAR(50) | FK: BAS_COMMON_CODES (반응기·교반기·진공건조기·누체필터·저장탱크) |
| `EST_QUOTATION_ITEMS` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES (10개 공정) |
| `INV_MATERIAL_HISTORY` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `INV_MATERIAL_LOTS` | `ITEM_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `INV_MATERIAL_LOTS` | `MATERIAL` | VARCHAR(50) | FK: BAS_COMMON_CODES (STS304·STS316L 등) |
| `INV_STOCKS` | `LOCATION_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `INV_SUPPLIERS` | `SUPPLY_TYPE` | VARCHAR(30) | FK: BAS_COMMON_CODES (자재/외주 — 소재가공·버핑) |
| `PRC_EQUIP_SIGNALS` | `EQUIP_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES (레이저커팅기·터치PC) |
| `PRC_PERFORMANCES` | `DEFECT_TYPE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `PRC_PERFORMANCES` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `PRC_PROCESS_HISTORIES` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `PRC_STD_CONDITIONS` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `PRC_WORK_ORDERS` | `PROCESS_CODE` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `SHP_CLAIMS` | `CLAIM_TYPE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `SHP_CLAIMS` | `CUSTOMER_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `SHP_CLAIM_CAUSES` | `CAUSE_PROCESS` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `SHP_LOT_TRACES` | `CURRENT_PROCESS` | VARCHAR(30) | FK: BAS_COMMON_CODES |
| `SHP_SHIPMENTS` | `CUSTOMER_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |
| `SHP_SHIPMENT_ITEMS` | `ITEM_CODE` | VARCHAR(50) | FK: BAS_COMMON_CODES |

합계 **29건**.

## 4. D-33 — FK 오표기

| 표 | 컬럼 | 타입 | TD5 비고 | 판정 |
|---|---|---|---|---|
| `EST_QUOTATION_ITEMS` | `UNIT_PRICE` | NUMERIC(16,2) | FK: EST_COST_RATES | **금액 값 컬럼을 FK 로 적었다.** FK 제약 미생성. 참조가 필요하면 `RATE_ID BIGINT` 신설이 맞지만 **컬럼을 추가하지 않는다**(G-02 762 고정) — 도입기업에 제안 |

## 5. G-08 디지털 스레드 — 이 사슬이 끊기면 FAIL

| 단계 | 표 | 키 | 비고 |
|---|---|---|---|
| 1 | `EST_PROJECTS` | `PROJECT_NO` | 프로젝트(수주)번호 — **ETO 최상위 추적 키** |
| 2 | `EST_CAD_DRAWINGS` | `DRAWING_NO` | 도면번호·리비전 |
| 3 | `EST_BOM_HEADERS` | `BOM_NO` | BOM |
| 4 | `INV_MATERIAL_LOTS` | `LOT_NO` | 자재 LOT |
| 5 | `PRC_WORK_ORDERS` | `WORK_ORDER_NO` | 작업지시 |
| 6 | `PRC_PERFORMANCES` | `—` | 공정실적 |
| 7 | `SHP_LOT_TRACES` | `PRODUCT_LOT_NO` | 제품 LOT — **제품 축의 중심 테이블** |
| 8 | `SHP_INSPECTIONS` | `—` | 출하검사(수압·기밀·진공) |
| 9 | `SHP_SHIPMENTS` | `SHIPMENT_NO` | 출하 |

**LOT 기반 데이터 매핑 성공률 ≥ 85%**(사업계획서 2.7.4 · D-23). LOT·프로젝트번호 열이 있는
**모든 화면**에서 클릭하면 **024 공정이력조회**(`/prc/024`)로 간다.

## 6. G-29 개인정보 — 암호화 저장 + 화면 마스킹

| 표 | 컬럼 | 한글명 |
|---|---|---|
| `IF_DEVICE_REGISTRY` | `IP_ADDRESS` | IP 주소 |
| `INV_SUPPLIERS` | `CONTACT_NAME` | 담당자명 |
| `INV_SUPPLIERS` | `CONTACT_PHONE` | 연락처 |
| `SYS_USERS` | `EMAIL` | 이메일 |
| `SYS_USERS` | `PHONE_NO` | 연락처 |
| `SYS_USERS` | `USER_NAME` | 사용자명 |

합계 **6컬럼**. 시드에 실명을 넣지 않는다 — TD3 `role_matrix` 의 실명도 제거했다(D-39).

## 7. G-11 런타임 전용 표 — 깨끗한 DB 에서 0건이 정상

`AGT_QUERY_LOGS` · `AGT_RECOMMENDATIONS` · `DAT_DOWNLOAD_LOGS` · `DAT_JOB_LOGS` · `EST_ML_PREDICTIONS` · `EST_ML_TRAIN_RUNS` · `EST_OBJECT_REVIEWS` · `IF_CAD_IMPORT_LOGS` · `IF_DOC_EMBED_LOGS` · `IF_GATEWAY_BUFFER` · `SYS_ACCESS_LOGS`

합계 **11표**. `make db-reset` 직후 비어 있고, 그때 화면은 `미수집 (D-nn)` 문구를
렌더해야 한다. 테스트는 **0건 경로를 명시 단언**한다(§10-4).

### 7.1 시드 여부 미정 — 담당 개발자가 판정한다 (지금 짐작하지 않는다)

이름이 이력·편차라 런타임처럼 보이지만 **시드 대상 업무 데이터일 수 있다.** 담당자가
`progress-devN.md` 에 판정을 적고 그때 이 표를 §7 또는 시드 대상으로 옮긴다.

| 표 | 무엇을 정해야 하는가 |
|---|---|
| `EST_SHAP_FACTORS` | SHAP 영향요인 — 모델 실행 산출물인지 시드 예시가 있는지 (개발3) |
| `INV_MATERIAL_HISTORY` | 원자재 이력 — 입고 시드가 채우는지, 사용·출고 시 쌓이는지 (개발1) |
| `INV_SUPPLIER_QUALITY` | 공급처 품질평가 — 입고 누적 집계인지 마스터인지 (개발1) |
| `PRC_CONDITION_DEVIATIONS` | 작업조건 편차 — 표준·실측 비교로 파생되는지, 시드하는지 (개발2) |
| `PRC_PROCESS_HISTORIES` | 공정 이력 — 공정실적 시드와 함께 채우는지 (개발2) |
| `SHP_CLAIM_CAUSES` | 클레임 원인 — 클레임 등록 시 쌓이는지 (개발2) |

## 8. 물리 설계 결정 (TD5 criteria: 물리 인덱스·파티션·제약명은 구현 단계 확정)

**컬럼을 추가하지 않았다** — G-02(762)에 영향 없음.

| 표 | 제약 | 근거 |
|---|---|---|
| `BAS_COMMON_CODES` | `UNIQUE(CODE_GROUP, CODE_VALUE)` | TD5 비고 '그룹 내/구분 내 Unique' (D-34) |
| `SYS_CONFIGS` | `UNIQUE(CONFIG_TYPE, CONFIG_KEY)` | TD5 비고 '그룹 내/구분 내 Unique' (D-34) |
| `SYS_ROLE_PERMISSIONS` | `UNIQUE NULLS NOT DISTINCT (ROLE_CODE, AREA_CODE, SCREEN_ID)` | 시드 upsert 필수 — delete 는 `SYS_USERS.ROLE_ID` FK 가 막는다 (D-45) |

`NULLS NOT DISTINCT` 는 PostgreSQL 15+ 기능이다. `SCREEN_ID` 가 NULL 인 영역 단위 행도
중복을 막아야 하므로 쓴다.
