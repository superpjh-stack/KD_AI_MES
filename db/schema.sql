-- 경동글로벌텍 제조AI 시스템 (SF26179182) — 스키마
-- tools/gen_schema.py 가 SF-TD5(design.json)에서 생성한다. 손으로 고치지 않는다.
-- 테이블 68 · 컬럼 762 · FK 제약 98

CREATE EXTENSION IF NOT EXISTS vector;

-- SYS_ROLE_PERMISSIONS — 역할권한관리
CREATE TABLE SYS_ROLE_PERMISSIONS (
    ROLE_PERM_ID             BIGSERIAL PRIMARY KEY,  -- 역할권한 ID
    ROLE_CODE                VARCHAR(30) NOT NULL,  -- 역할 코드
    ROLE_NAME                VARCHAR(100) NOT NULL,  -- 역할명
    AREA_CODE                VARCHAR(20) NOT NULL,  -- 업무영역 코드
    SCREEN_ID                VARCHAR(20),  -- 화면 ID
    READ_YN                  CHAR(1) NOT NULL,  -- 조회 권한
    WRITE_YN                 CHAR(1) NOT NULL,  -- 등록·수정 권한
    DELETE_YN                CHAR(1) NOT NULL,  -- 삭제 권한
    DOWNLOAD_YN              CHAR(1) NOT NULL,  -- 다운로드 권한
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- SYS_USERS — 사용자관리
CREATE TABLE SYS_USERS (
    USER_ID                  BIGSERIAL PRIMARY KEY,  -- 사용자 ID
    LOGIN_ID                 VARCHAR(50) NOT NULL UNIQUE,  -- 로그인 계정
    PASSWORD_HASH            VARCHAR(255) NOT NULL,  -- 비밀번호
    USER_NAME                VARCHAR(100) NOT NULL,  -- 사용자명
    DEPT_NAME                VARCHAR(100),  -- 소속
    ROLE_ID                  BIGINT NOT NULL,  -- 역할 ID
    PHONE_NO                 VARCHAR(30),  -- 연락처
    EMAIL                    VARCHAR(100),  -- 이메일
    PWD_CHANGED_DT           TIMESTAMP,  -- 비밀번호 변경일
    LOCK_YN                  CHAR(1) NOT NULL,  -- 계정 잠금 여부
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- AGT_QUERY_LOGS — AI질의이력
CREATE TABLE AGT_QUERY_LOGS (
    QUERY_ID                 BIGSERIAL PRIMARY KEY,  -- 질의 ID
    USER_ID                  BIGINT NOT NULL,  -- 사용자 ID
    AGENT_TYPE               VARCHAR(30) NOT NULL,  -- Agent 구분
    QUESTION_TEXT            TEXT NOT NULL,  -- 질의 내용
    ANSWER_TEXT              TEXT,  -- 응답 내용
    REF_DOC_IDS              VARCHAR(300),  -- 참조 문서 ID
    RESPONSE_MS              INT,  -- 응답 시간(ms)
    FEEDBACK_SCORE           INT,  -- 사용자 평가
    QUERIED_DT               TIMESTAMP NOT NULL,  -- 질의 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- AGT_RECOMMENDATIONS — AI분석·추천결과
CREATE TABLE AGT_RECOMMENDATIONS (
    RECO_ID                  BIGSERIAL PRIMARY KEY,  -- 추천 ID
    RECO_TYPE                VARCHAR(30) NOT NULL,  -- 추천 구분
    TARGET_TYPE              VARCHAR(30),  -- 대상 구분
    TARGET_ID                BIGINT,  -- 대상 ID
    SUMMARY_TEXT             TEXT NOT NULL,  -- 분석 요약
    RECOMMEND_VALUE          VARCHAR(300),  -- 추천 값
    EVIDENCE_JSON            JSONB,  -- 근거 데이터
    REVIEW_STATUS            VARCHAR(20) NOT NULL,  -- 검토 상태
    REVIEWER_ID              BIGINT,  -- 검토자 ID
    CREATED_AT_DT            TIMESTAMP NOT NULL,  -- 생성 일시
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- AGT_VECTOR_DOCS — Vector문서임베딩
CREATE TABLE AGT_VECTOR_DOCS (
    DOC_ID                   BIGSERIAL PRIMARY KEY,  -- 문서 ID
    DOC_TYPE                 VARCHAR(50) NOT NULL,  -- 문서 구분
    DOC_NAME                 VARCHAR(200) NOT NULL,  -- 문서명
    SOURCE_PATH              VARCHAR(500),  -- 원본 경로
    CHUNK_SEQ                INT NOT NULL,  -- 청크 순번
    CHUNK_TEXT               TEXT NOT NULL,  -- 본문
    EMBEDDING                VECTOR(1536),  -- 임베딩 벡터
    EMBED_MODEL              VARCHAR(100),  -- 임베딩 모델
    ACCESS_ROLE              VARCHAR(30),  -- 접근 권한 역할
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- BAS_COMMON_CODES — 공통코드관리
CREATE TABLE BAS_COMMON_CODES (
    CODE_ID                  BIGSERIAL PRIMARY KEY,  -- 공통코드 ID
    CODE_GROUP               VARCHAR(50) NOT NULL,  -- 코드 그룹
    CODE_VALUE               VARCHAR(50) NOT NULL,  -- 코드
    CODE_NAME                VARCHAR(200) NOT NULL,  -- 코드명
    PARENT_CODE_ID           BIGINT,  -- 상위 코드 ID
    SORT_ORDER               INT,  -- 정렬 순서
    ATTR1                    VARCHAR(200),  -- 속성값1
    ATTR2                    VARCHAR(200),  -- 속성값2
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- BAS_QUALITY_STANDARDS — 품질기준관리
CREATE TABLE BAS_QUALITY_STANDARDS (
    QSTD_ID                  BIGSERIAL PRIMARY KEY,  -- 품질기준 ID
    QSTD_CODE                VARCHAR(50) NOT NULL UNIQUE,  -- 품질기준 코드
    PRODUCT_GROUP            VARCHAR(50) NOT NULL,  -- 제품군
    INSPECT_TYPE             VARCHAR(30) NOT NULL,  -- 검사구분
    INSPECT_ITEM             VARCHAR(200) NOT NULL,  -- 검사항목
    STANDARD_SPEC            VARCHAR(100),  -- 적용 규격
    SPEC_MIN                 NUMERIC(14,4),  -- 기준값 하한
    SPEC_MAX                 NUMERIC(14,4),  -- 기준값 상한
    UOM                      VARCHAR(20),  -- 단위
    JUDGE_RULE               VARCHAR(200),  -- 판정 기준
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    APPLY_FROM               DATE NOT NULL,  -- 적용 시작일
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- BAS_WORK_STANDARDS — 작업표준관리
CREATE TABLE BAS_WORK_STANDARDS (
    WSTD_ID                  BIGSERIAL PRIMARY KEY,  -- 작업표준 ID
    WSTD_CODE                VARCHAR(50) NOT NULL UNIQUE,  -- 작업표준 코드
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    WSTD_NAME                VARCHAR(200) NOT NULL,  -- 작업표준명
    WORK_PROCEDURE           TEXT,  -- 작업 절차
    STD_MANHOUR              NUMERIC(10,2),  -- 표준 공수
    QUALIFICATION            VARCHAR(200),  -- 자격 요건
    DOC_PATH                 VARCHAR(500),  -- 첨부문서 경로
    STD_VERSION              VARCHAR(20) NOT NULL,  -- 버전
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_TRAIN_DATASETS — AI학습데이터셋
CREATE TABLE DAT_TRAIN_DATASETS (
    DATASET_ID               BIGSERIAL PRIMARY KEY,  -- 데이터셋 ID
    DATASET_NAME             VARCHAR(100) NOT NULL,  -- 데이터셋명
    TARGET_MODEL             VARCHAR(100),  -- 대상 모델
    TOTAL_CNT                BIGINT NOT NULL,  -- 총 건수
    EXCLUDED_CNT             BIGINT,  -- 제외 건수
    DATASET_VERSION          VARCHAR(20) NOT NULL,  -- 버전
    BALANCE_RESULT           VARCHAR(200),  -- 분포 검증 결과
    DATASET_STATUS           VARCHAR(20) NOT NULL,  -- 상태
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_DATASET_ITEMS — 학습데이터항목
CREATE TABLE DAT_DATASET_ITEMS (
    ITEM_ID                  BIGSERIAL PRIMARY KEY,  -- 항목 ID
    DATASET_ID               BIGINT NOT NULL,  -- 데이터셋 ID
    SOURCE_TYPE              VARCHAR(30) NOT NULL,  -- 원천 구분
    SOURCE_ID                BIGINT,  -- 원천 ID
    LABEL_VALUE              VARCHAR(300),  -- Label 값
    IMPUTED_YN               CHAR(1) NOT NULL,  -- 결측 보정 여부
    OUTLIER_REMOVED_YN       CHAR(1) NOT NULL,  -- 이상치 제거 여부
    DEDUP_KEY                VARCHAR(200),  -- 중복 제거 키
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_DATASET_SPLITS — 학습데이터분할
CREATE TABLE DAT_DATASET_SPLITS (
    SPLIT_ID                 BIGSERIAL PRIMARY KEY,  -- 분할 ID
    DATASET_ID               BIGINT NOT NULL,  -- 데이터셋 ID
    SPLIT_TYPE               VARCHAR(20) NOT NULL,  -- 분할 구분
    SPLIT_RATIO              NUMERIC(5,2) NOT NULL,  -- 비율(%)
    SPLIT_CNT                BIGINT NOT NULL,  -- 건수
    SPLIT_RULE               VARCHAR(200),  -- 분할 기준
    SPLIT_DT                 TIMESTAMP NOT NULL,  -- 분할 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- DAT_DOWNLOAD_LOGS — 데이터다운로드이력
CREATE TABLE DAT_DOWNLOAD_LOGS (
    DOWNLOAD_ID              BIGSERIAL PRIMARY KEY,  -- 다운로드 ID
    USER_ID                  BIGINT NOT NULL,  -- 사용자 ID
    SCREEN_ID                VARCHAR(20),  -- 대상 화면 ID
    DATA_CATEGORY            VARCHAR(50) NOT NULL,  -- 데이터 구분
    FILE_FORMAT              VARCHAR(20) NOT NULL,  -- 파일 형식
    ROW_CNT                  BIGINT,  -- 건수
    FILTER_JSON              JSONB,  -- 조회 조건
    APPROVED_YN              CHAR(1) NOT NULL,  -- 승인 여부
    DOWNLOAD_DT              TIMESTAMP NOT NULL,  -- 다운로드 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- DAT_SOURCES — 데이터수집대상관리
CREATE TABLE DAT_SOURCES (
    SOURCE_ID                BIGSERIAL PRIMARY KEY,  -- 수집대상 ID
    SOURCE_NAME              VARCHAR(100) NOT NULL,  -- 수집대상명
    DATA_TYPE                VARCHAR(30) NOT NULL,  -- 데이터 유형
    IF_METHOD                VARCHAR(30) NOT NULL,  -- 연계 방식
    COLLECT_CYCLE            VARCHAR(30),  -- 수집 주기
    CONNECTION_INFO          VARCHAR(300),  -- 접속 정보
    INTERFACE_CODE           VARCHAR(30),  -- 담당 인터페이스
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_INTEGRATION_JOBS — 데이터통합작업
CREATE TABLE DAT_INTEGRATION_JOBS (
    JOB_ID                   BIGSERIAL PRIMARY KEY,  -- 통합작업 ID
    JOB_NAME                 VARCHAR(100) NOT NULL,  -- 작업명
    SOURCE_ID                BIGINT NOT NULL,  -- 수집대상 ID
    JOB_TYPE                 VARCHAR(30) NOT NULL,  -- 처리 유형
    TARGET_STORE             VARCHAR(50) NOT NULL,  -- 적재 대상
    SCHEDULE_EXPR            VARCHAR(50),  -- 스케줄
    TRANSFORM_RULE           TEXT,  -- 변환 규칙
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_JOB_LOGS — 통합작업실행로그
CREATE TABLE DAT_JOB_LOGS (
    JOB_LOG_ID               BIGSERIAL PRIMARY KEY,  -- 실행로그 ID
    JOB_ID                   BIGINT NOT NULL,  -- 통합작업 ID
    START_DT                 TIMESTAMP NOT NULL,  -- 시작 일시
    END_DT                   TIMESTAMP,  -- 종료 일시
    PROCESS_CNT              BIGINT,  -- 처리 건수
    FAIL_CNT                 BIGINT,  -- 실패 건수
    RESULT_CODE              VARCHAR(20) NOT NULL,  -- 실행 결과
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- EST_PROJECTS — 수주프로젝트관리
CREATE TABLE EST_PROJECTS (
    PROJECT_ID               BIGSERIAL PRIMARY KEY,  -- 프로젝트 ID
    PROJECT_NO               VARCHAR(50) NOT NULL UNIQUE,  -- 프로젝트(수주)번호
    CUSTOMER_CODE            VARCHAR(50) NOT NULL,  -- 고객사 코드
    PRODUCT_GROUP            VARCHAR(50) NOT NULL,  -- 제품군
    PROJECT_NAME             VARCHAR(200) NOT NULL,  -- 프로젝트명
    RFQ_DT                   TIMESTAMP,  -- 견적요청일
    ORDER_CONFIRM_DT         TIMESTAMP,  -- 수주 확정일시
    DUE_DT                   DATE,  -- 납기일
    ORDER_AMOUNT             NUMERIC(16,0),  -- 수주 금액
    PROJECT_STATUS           VARCHAR(30) NOT NULL,  -- 진행 상태
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_LAKE_OBJECTS — 비정형데이터저장소
CREATE TABLE DAT_LAKE_OBJECTS (
    LAKE_OBJ_ID              BIGSERIAL PRIMARY KEY,  -- 객체 ID
    OBJ_TYPE                 VARCHAR(30) NOT NULL,  -- 객체 구분
    OBJ_PATH                 VARCHAR(500) NOT NULL,  -- 저장 경로
    ORIGIN_FILE_NAME         VARCHAR(300) NOT NULL,  -- 원본 파일명
    FILE_SIZE                BIGINT,  -- 파일 크기(byte)
    FILE_HASH                VARCHAR(128),  -- 해시값
    PROJECT_ID               BIGINT,  -- 연계 프로젝트 ID
    RETENTION_POLICY         VARCHAR(50),  -- 보존 정책
    INGESTED_DT              TIMESTAMP NOT NULL,  -- 수집 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- DAT_PREPROCESS_RULES — 전처리규칙
CREATE TABLE DAT_PREPROCESS_RULES (
    RULE_ID                  BIGSERIAL PRIMARY KEY,  -- 전처리규칙 ID
    RULE_NAME                VARCHAR(100) NOT NULL,  -- 규칙명
    RULE_STAGE               VARCHAR(30) NOT NULL,  -- 처리 단계
    TARGET_DESC              VARCHAR(200) NOT NULL,  -- 적용 대상
    RULE_EXPR                TEXT,  -- 규칙 내용
    APPLY_ORDER              INT NOT NULL,  -- 적용 순서
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- DAT_QUALITY_CHECKS — 데이터품질검증
CREATE TABLE DAT_QUALITY_CHECKS (
    CHECK_ID                 BIGSERIAL PRIMARY KEY,  -- 검증 ID
    CHECK_AXIS               VARCHAR(30) NOT NULL,  -- 검증 축
    TARGET_DESC              VARCHAR(200) NOT NULL,  -- 대상 데이터
    TOTAL_CNT                BIGINT NOT NULL,  -- 전체 건수
    VALID_CNT                BIGINT NOT NULL,  -- 정상 건수
    ACHIEVE_RATE             NUMERIC(7,3),  -- 달성률(%)
    JUDGE_RESULT             VARCHAR(20),  -- 판정
    CHECKED_DT               TIMESTAMP NOT NULL,  -- 검증 일시
    ACTION_COMMENT           VARCHAR(300),  -- 조치 내용
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- DAT_TIMESERIES — 시계열데이터
CREATE TABLE DAT_TIMESERIES (
    TS_ID                    BIGSERIAL PRIMARY KEY,  -- 시계열 ID
    TAG_NAME                 VARCHAR(100) NOT NULL,  -- 측정 태그
    EQUIP_CODE               VARCHAR(30),  -- 설비 코드
    MEASURE_DT               TIMESTAMP NOT NULL,  -- 측정 일시
    MEASURE_VALUE            NUMERIC(16,4),  -- 측정값
    UOM                      VARCHAR(20),  -- 단위
    QUALITY_FLAG             VARCHAR(20),  -- 품질 플래그
    COLLECT_PATH             VARCHAR(50),  -- 수집 경로
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- EST_CAD_DRAWINGS — CAD도면관리
CREATE TABLE EST_CAD_DRAWINGS (
    DRAWING_ID               BIGSERIAL PRIMARY KEY,  -- 도면 ID
    DRAWING_NO               VARCHAR(100) NOT NULL,  -- 도면번호
    PROJECT_ID               BIGINT,  -- 프로젝트 ID
    FILE_TYPE                VARCHAR(10) NOT NULL,  -- 파일 구분
    FILE_PATH                VARCHAR(500) NOT NULL,  -- 파일 경로
    FILE_SIZE                BIGINT,  -- 파일 크기(byte)
    REVISION                 VARCHAR(20),  -- 리비전
    FILE_MTIME               TIMESTAMP,  -- 최종수정일(mtime)
    ANALYSIS_STATUS          VARCHAR(20) NOT NULL,  -- 분석 상태
    DUPLICATE_YN             CHAR(1) NOT NULL,  -- 중복 여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_BOM_HEADERS — BOM헤더
CREATE TABLE EST_BOM_HEADERS (
    BOM_ID                   BIGSERIAL PRIMARY KEY,  -- BOM ID
    BOM_NO                   VARCHAR(50) NOT NULL UNIQUE,  -- BOM 번호
    PROJECT_ID               BIGINT NOT NULL,  -- 프로젝트 ID
    DRAWING_ID               BIGINT,  -- 도면 ID
    GEN_METHOD               VARCHAR(30) NOT NULL,  -- 생성 방식
    BOM_VERSION              VARCHAR(20) NOT NULL,  -- BOM 버전
    ACCURACY_RATE            NUMERIC(6,2),  -- 정확도(%)
    CONFIRM_YN               CHAR(1) NOT NULL,  -- 확정 여부
    CYCLE_CHECK_RESULT       VARCHAR(20),  -- 순환참조 검증
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_CAD_OBJECTS — 도면객체인식결과
CREATE TABLE EST_CAD_OBJECTS (
    OBJECT_ID                BIGSERIAL PRIMARY KEY,  -- 객체 ID
    DRAWING_ID               BIGINT NOT NULL,  -- 도면 ID
    DETECT_METHOD            VARCHAR(30) NOT NULL,  -- 인식 방식
    OBJECT_TYPE              VARCHAR(50) NOT NULL,  -- 객체 유형
    POS_X                    NUMERIC(14,4),  -- 좌표 X
    POS_Y                    NUMERIC(14,4),  -- 좌표 Y
    DIMENSION_VALUE          NUMERIC(14,4),  -- 치수값
    CONFIDENCE_SCORE         NUMERIC(5,4),  -- 인식 신뢰도
    CROSS_CHECK_RESULT       VARCHAR(20),  -- 정합성 검증 결과
    CONFIRM_YN               CHAR(1) NOT NULL,  -- 확정 여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_BOM_ITEMS — BOM자재구성
CREATE TABLE EST_BOM_ITEMS (
    BOM_ITEM_ID              BIGSERIAL PRIMARY KEY,  -- BOM 항목 ID
    BOM_ID                   BIGINT NOT NULL,  -- BOM ID
    PARENT_ITEM_ID           BIGINT,  -- 상위 항목 ID
    BOM_LEVEL                INT NOT NULL,  -- 레벨
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    MATERIAL                 VARCHAR(50),  -- 재질
    SPEC_TEXT                VARCHAR(200),  -- 규격
    REQUIRE_QTY              NUMERIC(14,3) NOT NULL,  -- 소요 수량
    UOM                      VARCHAR(20) NOT NULL,  -- 단위
    SOURCE_OBJECT_ID         BIGINT,  -- 생성 근거 객체 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_BOM_ROUTINGS — BOM공정구조
CREATE TABLE EST_BOM_ROUTINGS (
    ROUTING_ID               BIGSERIAL PRIMARY KEY,  -- 공정구조 ID
    BOM_ID                   BIGINT NOT NULL,  -- BOM ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    PROCESS_SEQ              INT NOT NULL,  -- 공정 순서
    OUTSOURCE_YN             CHAR(1) NOT NULL,  -- 외주 여부
    STD_MANHOUR              NUMERIC(10,2),  -- 표준 공수(h)
    WSTD_ID                  BIGINT,  -- 작업표준 ID
    REMARK                   VARCHAR(300),  -- 비고
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_CAD_FEATURES — 도면Feature관리
CREATE TABLE EST_CAD_FEATURES (
    FEATURE_ID               BIGSERIAL PRIMARY KEY,  -- Feature ID
    DRAWING_ID               BIGINT NOT NULL,  -- 도면 ID
    FEATURE_TYPE             VARCHAR(50) NOT NULL,  -- Feature 구분
    FEATURE_VALUE            NUMERIC(16,4),  -- Feature 값
    UOM                      VARCHAR(20),  -- 단위
    SOURCE_DESC              VARCHAR(300),  -- 산출 근거
    USED_IN_QUOTE_YN         CHAR(1) NOT NULL,  -- 견적 반영 여부
    TRAIN_USE_YN             CHAR(1) NOT NULL,  -- 학습 활용 여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_COST_RATES — 원가단가기준
CREATE TABLE EST_COST_RATES (
    RATE_ID                  BIGSERIAL PRIMARY KEY,  -- 단가 ID
    RATE_TYPE                VARCHAR(30) NOT NULL,  -- 단가 구분
    TARGET_CODE              VARCHAR(50) NOT NULL,  -- 대상 코드
    UNIT_PRICE               NUMERIC(16,2) NOT NULL,  -- 단가
    UOM                      VARCHAR(20) NOT NULL,  -- 단위
    APPLY_FROM               DATE NOT NULL,  -- 적용 시작일
    APPLY_TO                 DATE,  -- 적용 종료일
    SOURCE_DESC              VARCHAR(200),  -- 출처
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_MATERIAL_REQS — 자재소요량
CREATE TABLE EST_MATERIAL_REQS (
    REQ_ID                   BIGSERIAL PRIMARY KEY,  -- 소요량 ID
    BOM_ID                   BIGINT NOT NULL,  -- BOM ID
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    TOTAL_REQ_QTY            NUMERIC(14,3) NOT NULL,  -- 총 소요 수량
    STOCK_QTY                NUMERIC(14,3),  -- 현재고 수량
    SHORTAGE_QTY             NUMERIC(14,3),  -- 부족 수량
    REQUIRE_DT               DATE,  -- 소요 시점
    PO_NEED_YN               CHAR(1) NOT NULL,  -- 발주 필요 여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_ML_MODELS — ML모델관리
CREATE TABLE EST_ML_MODELS (
    MODEL_ID                 BIGSERIAL PRIMARY KEY,  -- 모델 ID
    MODEL_NAME               VARCHAR(100) NOT NULL,  -- 모델명
    MODEL_TYPE               VARCHAR(50) NOT NULL,  -- 모델 유형
    MODEL_VERSION            VARCHAR(20) NOT NULL,  -- 버전
    DATASET_ID               BIGINT,  -- 학습 데이터셋 ID
    HYPER_PARAMS             JSONB,  -- 하이퍼파라미터
    METRIC_JSON              JSONB,  -- 성능 지표
    DEPLOY_STATUS            VARCHAR(20) NOT NULL,  -- 배포 상태
    DEPLOYED_DT              TIMESTAMP,  -- 배포 일시
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_ML_PREDICTIONS — ML예측결과
CREATE TABLE EST_ML_PREDICTIONS (
    PREDICT_ID               BIGSERIAL PRIMARY KEY,  -- 예측 ID
    MODEL_ID                 BIGINT NOT NULL,  -- 모델 ID
    TARGET_TYPE              VARCHAR(30) NOT NULL,  -- 대상 구분
    TARGET_ID                BIGINT NOT NULL,  -- 대상 ID
    PREDICT_VALUE            NUMERIC(16,4) NOT NULL,  -- 예측값
    ACTUAL_VALUE             NUMERIC(16,4),  -- 실제값
    ERROR_RATE               NUMERIC(8,4),  -- 오차율(%)
    CONFIDENCE_SCORE         NUMERIC(5,4),  -- 신뢰도
    PREDICTED_DT             TIMESTAMP NOT NULL,  -- 예측 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- EST_ML_TRAIN_RUNS — ML학습이력
CREATE TABLE EST_ML_TRAIN_RUNS (
    TRAIN_RUN_ID             BIGSERIAL PRIMARY KEY,  -- 학습 ID
    MODEL_ID                 BIGINT NOT NULL,  -- 모델 ID
    START_DT                 TIMESTAMP NOT NULL,  -- 학습 시작일시
    END_DT                   TIMESTAMP,  -- 학습 종료일시
    TRAIN_CNT                INT,  -- 학습 건수
    VALID_CNT                INT,  -- 검증 건수
    TEST_CNT                 INT,  -- 시험 건수
    VALID_METRIC             NUMERIC(10,4),  -- 검증 성능
    OVERFIT_RESULT           VARCHAR(20),  -- 과적합 판정
    RUN_STATUS               VARCHAR(20) NOT NULL,  -- 실행 결과
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- EST_OBJECT_REVIEWS — 객체인식검증이력
CREATE TABLE EST_OBJECT_REVIEWS (
    REVIEW_ID                BIGSERIAL PRIMARY KEY,  -- 검증 ID
    OBJECT_ID                BIGINT NOT NULL,  -- 객체 ID
    REVIEWER_ID              BIGINT NOT NULL,  -- 검토자 ID
    REVIEW_RESULT            VARCHAR(20) NOT NULL,  -- 검토 결과
    BEFORE_VALUE             VARCHAR(300),  -- 수정 전 값
    AFTER_VALUE              VARCHAR(300),  -- 수정 후 값
    REVIEW_COMMENT           VARCHAR(300),  -- 수정 사유
    RETRAIN_YN               CHAR(1) NOT NULL,  -- 재학습 반영 여부
    REVIEWED_DT              TIMESTAMP NOT NULL,  -- 검토 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- EST_QUOTATIONS — 견적관리
CREATE TABLE EST_QUOTATIONS (
    QUOTE_ID                 BIGSERIAL PRIMARY KEY,  -- 견적 ID
    QUOTE_NO                 VARCHAR(50) NOT NULL UNIQUE,  -- 견적번호
    PROJECT_ID               BIGINT NOT NULL,  -- 프로젝트 ID
    DRAWING_ID               BIGINT,  -- 도면 ID
    BOM_ID                   BIGINT,  -- BOM ID
    CALC_METHOD              VARCHAR(30) NOT NULL,  -- 산출 방식
    TOTAL_AMOUNT             NUMERIC(16,0) NOT NULL,  -- 총 견적금액
    MATERIAL_COST            NUMERIC(16,0),  -- 재료비
    PROCESS_COST             NUMERIC(16,0),  -- 가공·공수비
    OUTSOURCE_COST           NUMERIC(16,0),  -- 외주비
    CONFIDENCE_SCORE         NUMERIC(5,4),  -- 신뢰도 점수
    QUOTE_STATUS             VARCHAR(20) NOT NULL,  -- 견적 상태
    APPROVER_ID              BIGINT,  -- 승인자 ID
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_QUOTATION_ITEMS — 견적공정원가내역
CREATE TABLE EST_QUOTATION_ITEMS (
    QUOTE_ITEM_ID            BIGSERIAL PRIMARY KEY,  -- 견적내역 ID
    QUOTE_ID                 BIGINT NOT NULL,  -- 견적 ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    CALC_QTY                 NUMERIC(14,3),  -- 산출 수량
    UOM                      VARCHAR(20),  -- 단위
    UNIT_PRICE               NUMERIC(16,2),  -- 적용 단가
    PROCESS_AMOUNT           NUMERIC(16,0) NOT NULL,  -- 공정 원가
    PREDICT_MANHOUR          NUMERIC(10,2),  -- 예측 공수(h)
    REMARK                   VARCHAR(300),  -- 비고
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- EST_SHAP_FACTORS — SHAP영향요인
CREATE TABLE EST_SHAP_FACTORS (
    SHAP_ID                  BIGSERIAL PRIMARY KEY,  -- 영향요인 ID
    PREDICT_ID               BIGINT NOT NULL,  -- 예측 ID
    FEATURE_NAME             VARCHAR(100) NOT NULL,  -- 변수명
    SHAP_VALUE               NUMERIC(12,6) NOT NULL,  -- 기여도
    RANK_NO                  INT NOT NULL,  -- 기여 순위
    IMPACT_DIRECTION         VARCHAR(10),  -- 영향 방향
    EXPERT_MATCH_YN          CHAR(1),  -- 전문가 평가 일치
    OPTIMIZE_COMMENT         VARCHAR(300),  -- 최적화 제안
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_CAD_FILES — CAD파일수집
CREATE TABLE IF_CAD_FILES (
    CAD_IF_ID                BIGSERIAL PRIMARY KEY,  -- 수집파일 ID
    ORIGIN_FILE_NAME         VARCHAR(300) NOT NULL,  -- 원본 파일명
    FILE_TYPE                VARCHAR(10) NOT NULL,  -- 파일 형식
    SOURCE_PATH              VARCHAR(500) NOT NULL,  -- 원본 경로
    FILE_SIZE                BIGINT,  -- 파일 크기(byte)
    FILE_MTIME               TIMESTAMP,  -- 최종수정일(mtime)
    COLLECT_METHOD           VARCHAR(30) NOT NULL,  -- 수집 방식
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    DRAWING_ID               BIGINT,  -- 도면 ID
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_CAD_IMPORT_LOGS — CAD수집로그
CREATE TABLE IF_CAD_IMPORT_LOGS (
    CAD_LOG_ID               BIGSERIAL PRIMARY KEY,  -- 수집로그 ID
    CAD_IF_ID                BIGINT NOT NULL,  -- 수집파일 ID
    STEP_NAME                VARCHAR(50) NOT NULL,  -- 처리 단계
    RESULT_CODE              VARCHAR(20) NOT NULL,  -- 처리 결과
    EXCLUDE_REASON           VARCHAR(200),  -- 제외 사유
    PROCESSED_DT             TIMESTAMP NOT NULL,  -- 처리 일시
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_DEVICE_REGISTRY — 수집장비등록
CREATE TABLE IF_DEVICE_REGISTRY (
    DEVICE_ID                BIGSERIAL PRIMARY KEY,  -- 장비 ID
    DEVICE_NAME              VARCHAR(100) NOT NULL,  -- 장비명
    DEVICE_TYPE              VARCHAR(30) NOT NULL,  -- 장비 구분
    MODEL_NAME               VARCHAR(100),  -- 모델명
    IP_ADDRESS               VARCHAR(45),  -- IP 주소
    PROTOCOL                 VARCHAR(30) NOT NULL,  -- 통신 프로토콜
    COLLECT_INTERVAL         INT,  -- 수집 주기(초)
    LOCATION_DESC            VARCHAR(200),  -- 설치 위치
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- IF_EXT_DOCUMENTS — 외부표준문서
CREATE TABLE IF_EXT_DOCUMENTS (
    EXT_DOC_ID               BIGSERIAL PRIMARY KEY,  -- 외부문서 ID
    DOC_NAME                 VARCHAR(200) NOT NULL,  -- 문서명
    DOC_TYPE                 VARCHAR(50) NOT NULL,  -- 문서 구분
    SOURCE_PATH              VARCHAR(500) NOT NULL,  -- 원본 경로
    DOC_VERSION              VARCHAR(20),  -- 버전
    COLLECT_DT               TIMESTAMP NOT NULL,  -- 수집 일시
    EMBED_TARGET_YN          CHAR(1) NOT NULL,  -- 임베딩 대상 여부
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_DOC_EMBED_LOGS — 문서임베딩로그
CREATE TABLE IF_DOC_EMBED_LOGS (
    EMBED_LOG_ID             BIGSERIAL PRIMARY KEY,  -- 임베딩로그 ID
    EXT_DOC_ID               BIGINT NOT NULL,  -- 외부문서 ID
    DOC_ID                   BIGINT,  -- 문서 ID
    CHUNK_CNT                INT,  -- 청크 건수
    EMBED_MODEL              VARCHAR(100),  -- 임베딩 모델
    RESULT_CODE              VARCHAR(20) NOT NULL,  -- 처리 결과
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    PROCESSED_DT             TIMESTAMP NOT NULL,  -- 처리 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_ERP_RECEIPTS — ERP입고연계
CREATE TABLE IF_ERP_RECEIPTS (
    IF_ID                    BIGSERIAL PRIMARY KEY,  -- 연계 ID
    ERP_DOC_NO               VARCHAR(50) NOT NULL,  -- ERP 전표번호
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    SUPPLIER_CODE            VARCHAR(50),  -- 공급처 코드
    RECEIPT_QTY              NUMERIC(14,3) NOT NULL,  -- 입고 수량
    RECEIPT_DT               TIMESTAMP NOT NULL,  -- 입고 일자
    IF_DIRECTION             VARCHAR(10) NOT NULL,  -- 연계 방향
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    IF_DT                    TIMESTAMP NOT NULL,  -- 연계 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_ERP_SHIPMENTS — ERP출하연계
CREATE TABLE IF_ERP_SHIPMENTS (
    IF_ID                    BIGSERIAL PRIMARY KEY,  -- 연계 ID
    ERP_DOC_NO               VARCHAR(50) NOT NULL,  -- ERP 전표번호
    SHIPMENT_NO              VARCHAR(50),  -- 출하번호
    CUSTOMER_CODE            VARCHAR(50) NOT NULL,  -- 고객사 코드
    SHIP_QTY                 NUMERIC(14,3) NOT NULL,  -- 출하 수량
    SHIP_DT                  TIMESTAMP NOT NULL,  -- 출하 일자
    IF_DIRECTION             VARCHAR(10) NOT NULL,  -- 연계 방향
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    IF_DT                    TIMESTAMP NOT NULL,  -- 연계 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_ERP_STOCKS — ERP재고연계
CREATE TABLE IF_ERP_STOCKS (
    IF_ID                    BIGSERIAL PRIMARY KEY,  -- 연계 ID
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    WAREHOUSE_CODE           VARCHAR(50),  -- 창고 코드
    ERP_STOCK_QTY            NUMERIC(14,3) NOT NULL,  -- ERP 재고수량
    SYS_STOCK_QTY            NUMERIC(14,3),  -- 시스템 재고수량
    DIFF_QTY                 NUMERIC(14,3),  -- 차이 수량
    BASE_DT                  DATE NOT NULL,  -- 기준 일자
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    IF_DT                    TIMESTAMP NOT NULL,  -- 연계 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_GATEWAY_BUFFER — Gateway버퍼
CREATE TABLE IF_GATEWAY_BUFFER (
    BUFFER_ID                BIGSERIAL PRIMARY KEY,  -- 버퍼 ID
    DEVICE_ID                BIGINT NOT NULL,  -- 장비 ID
    PAYLOAD                  TEXT NOT NULL,  -- 메시지 본문
    BUFFER_REASON            VARCHAR(50) NOT NULL,  -- 버퍼 사유
    RETRY_CNT                INT NOT NULL,  -- 적재 시도 횟수
    BUFFERED_DT              TIMESTAMP NOT NULL,  -- 최초 저장 일시
    RESENT_DT                TIMESTAMP,  -- 재전송 일시
    BUFFER_STATUS            VARCHAR(20) NOT NULL,  -- 처리 상태
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- IF_PLC_SIGNALS — PLC신호수집
CREATE TABLE IF_PLC_SIGNALS (
    PLC_IF_ID                BIGSERIAL PRIMARY KEY,  -- 수집 ID
    DEVICE_ID                BIGINT NOT NULL,  -- 장비 ID
    TAG_NAME                 VARCHAR(100) NOT NULL,  -- 태그명
    RAW_VALUE                VARCHAR(100),  -- 원시값
    CONVERTED_VALUE          NUMERIC(16,4),  -- 변환값
    PROTOCOL                 VARCHAR(30) NOT NULL,  -- 통신 프로토콜
    COLLECT_DT               TIMESTAMP NOT NULL,  -- 수집 일시
    IF_STATUS                VARCHAR(20) NOT NULL,  -- 처리 상태
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- INV_MATERIAL_LOTS — 자재LOT관리
CREATE TABLE INV_MATERIAL_LOTS (
    LOT_ID                   BIGSERIAL PRIMARY KEY,  -- 자재 LOT ID
    LOT_NO                   VARCHAR(50) NOT NULL UNIQUE,  -- LOT 번호
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    MATERIAL                 VARCHAR(50),  -- 재질
    THICKNESS_MM             NUMERIC(10,2),  -- 두께(mm)
    LENGTH_MM                NUMERIC(12,2),  -- 길이(mm)
    WEIGHT_KG                NUMERIC(14,3),  -- 중량(kg)
    SPEC_TEXT                VARCHAR(200),  -- 규격
    CURRENT_QTY              NUMERIC(14,3) NOT NULL,  -- 보유수량
    LOT_STATUS               VARCHAR(20) NOT NULL,  -- LOT 상태
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- INV_SUPPLIERS — 공급처관리
CREATE TABLE INV_SUPPLIERS (
    SUPPLIER_ID              BIGSERIAL PRIMARY KEY,  -- 공급처 ID
    SUPPLIER_CODE            VARCHAR(50) NOT NULL UNIQUE,  -- 공급처 코드
    SUPPLIER_NAME            VARCHAR(200) NOT NULL,  -- 공급처명
    SUPPLY_TYPE              VARCHAR(30),  -- 공급 구분
    CONTACT_NAME             VARCHAR(100),  -- 담당자명
    CONTACT_PHONE            VARCHAR(30),  -- 연락처
    MAIN_ITEMS               VARCHAR(300),  -- 주요 공급품목
    GRADE                    VARCHAR(10),  -- 평가 등급
    RISK_YN                  CHAR(1) NOT NULL,  -- 리스크 여부
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- PRC_WORK_ORDERS — 작업지시관리
CREATE TABLE PRC_WORK_ORDERS (
    WORK_ORDER_ID            BIGSERIAL PRIMARY KEY,  -- 작업지시 ID
    WORK_ORDER_NO            VARCHAR(50) NOT NULL UNIQUE,  -- 작업지시번호
    PROJECT_ID               BIGINT NOT NULL,  -- 프로젝트 ID
    ROUTING_ID               BIGINT,  -- BOM 공정구조 ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    ORDER_QTY                NUMERIC(14,3) NOT NULL,  -- 지시 수량
    CONFIRM_DT               TIMESTAMP,  -- 지시 확정일시
    PLAN_START_DT            DATE,  -- 착수 예정일
    PLAN_END_DT              DATE,  -- 완료 예정일
    OUTSOURCE_YN             CHAR(1) NOT NULL,  -- 외주 여부
    SUPPLIER_ID              BIGINT,  -- 외주처 ID
    ORDER_STATUS             VARCHAR(20) NOT NULL,  -- 진행 상태
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- INV_MATERIAL_HISTORY — 원자재이력관리
CREATE TABLE INV_MATERIAL_HISTORY (
    HIST_ID                  BIGSERIAL PRIMARY KEY,  -- 이력 ID
    LOT_ID                   BIGINT NOT NULL,  -- 자재 LOT ID
    HIST_TYPE                VARCHAR(20) NOT NULL,  -- 이력 구분
    EVENT_DT                 TIMESTAMP NOT NULL,  -- 발생 일시
    PROCESS_CODE             VARCHAR(30),  -- 관련 공정
    WORK_ORDER_ID            BIGINT,  -- 작업지시 ID
    EVENT_QTY                NUMERIC(14,3) NOT NULL,  -- 수량
    PRODUCT_LOT_NO           VARCHAR(50),  -- 연결 제품 LOT
    USER_ID                  BIGINT,  -- 처리자 ID
    REMARK                   VARCHAR(300),  -- 비고
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- INV_RECEIPTS — 입고관리
CREATE TABLE INV_RECEIPTS (
    RECEIPT_ID               BIGSERIAL PRIMARY KEY,  -- 입고 ID
    RECEIPT_NO               VARCHAR(50) NOT NULL UNIQUE,  -- 입고번호
    PROJECT_ID               BIGINT,  -- 프로젝트 ID
    SUPPLIER_ID              BIGINT NOT NULL,  -- 공급처 ID
    LOT_ID                   BIGINT NOT NULL,  -- 자재 LOT ID
    RECEIPT_DT               TIMESTAMP NOT NULL,  -- 입고일시
    RECEIPT_QTY              NUMERIC(14,3) NOT NULL,  -- 입고수량
    WEIGHT_KG                NUMERIC(14,3),  -- 중량(kg)
    MTC_NO                   VARCHAR(50),  -- MTC 번호
    INSPECT_RESULT           VARCHAR(20),  -- 검사 판정
    INPUT_DEVICE             VARCHAR(30),  -- 입력 단말
    ERP_SYNC_STATUS          VARCHAR(20),  -- ERP 동기화 상태
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- INV_STOCKS — 재고관리
CREATE TABLE INV_STOCKS (
    STOCK_ID                 BIGSERIAL PRIMARY KEY,  -- 재고 ID
    LOT_ID                   BIGINT NOT NULL,  -- 자재 LOT ID
    LOCATION_CODE            VARCHAR(50),  -- 보관 위치
    STOCK_QTY                NUMERIC(14,3) NOT NULL,  -- 현재고 수량
    AVAILABLE_QTY            NUMERIC(14,3) NOT NULL,  -- 가용 수량
    SAFETY_QTY               NUMERIC(14,3),  -- 안전재고
    LAST_IN_DT               TIMESTAMP,  -- 최종 입고일
    LAST_OUT_DT              TIMESTAMP,  -- 최종 출고일
    ERP_DIFF_QTY             NUMERIC(14,3),  -- ERP 재고 차이
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- INV_SUPPLIER_QUALITY — 공급처품질평가
CREATE TABLE INV_SUPPLIER_QUALITY (
    SQ_ID                    BIGSERIAL PRIMARY KEY,  -- 평가 ID
    SUPPLIER_ID              BIGINT NOT NULL,  -- 공급처 ID
    EVAL_PERIOD              VARCHAR(20) NOT NULL,  -- 평가 기간
    DELIVERY_CNT             INT NOT NULL,  -- 납품 건수
    REJECT_CNT               INT NOT NULL,  -- 불합격 건수
    DEFECT_RATE              NUMERIC(7,3),  -- 불량률(%)
    QUALITY_DEVIATION        NUMERIC(10,4),  -- 품질 편차
    OTD_RATE                 NUMERIC(7,3),  -- 납기 준수율(%)
    TOTAL_SCORE              NUMERIC(7,2),  -- 종합 점수
    GRADE                    VARCHAR(10),  -- 평가 등급
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- KPI_TARGETS — KPI목표관리
CREATE TABLE KPI_TARGETS (
    KPI_TARGET_ID            BIGSERIAL PRIMARY KEY,  -- KPI 목표 ID
    KPI_CODE                 VARCHAR(30) NOT NULL UNIQUE,  -- KPI 코드
    KPI_NAME                 VARCHAR(100) NOT NULL,  -- KPI명
    KPI_FIELD                VARCHAR(10) NOT NULL,  -- 분야
    UOM                      VARCHAR(20) NOT NULL,  -- 단위
    BASE_VALUE               NUMERIC(14,4) NOT NULL,  -- 기존값
    TARGET_VALUE             NUMERIC(14,4) NOT NULL,  -- 목표값
    IMPROVE_RATE             NUMERIC(7,3),  -- 개선율(%)
    WEIGHT                   NUMERIC(4,2),  -- 가중치
    OFFICIAL_YN              CHAR(1) NOT NULL,  -- 공식 지표 여부
    MEASURE_BASIS            VARCHAR(300),  -- 측정 근거
    FORMULA_TEXT             VARCHAR(300),  -- 산식
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- KPI_MEASURES — KPI측정실적
CREATE TABLE KPI_MEASURES (
    MEASURE_ID               BIGSERIAL PRIMARY KEY,  -- 측정 ID
    KPI_TARGET_ID            BIGINT NOT NULL,  -- KPI 목표 ID
    PERIOD_CODE              VARCHAR(20) NOT NULL,  -- 집계 기간
    SAMPLE_CNT               INT,  -- 집계 대상 건수
    MEASURE_VALUE            NUMERIC(14,4) NOT NULL,  -- 측정값
    ACHIEVE_RATE             NUMERIC(7,3),  -- 달성률(%)
    SOURCE_TYPE              VARCHAR(30),  -- 산출 근거 구분
    AGGREGATED_DT            TIMESTAMP NOT NULL,  -- 집계 일시
    REMARK                   VARCHAR(300),  -- 비고
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- PRC_STD_CONDITIONS — 표준작업조건
CREATE TABLE PRC_STD_CONDITIONS (
    STD_COND_ID              BIGSERIAL PRIMARY KEY,  -- 표준조건 ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    WSTD_ID                  BIGINT,  -- 작업표준 ID
    COND_ITEM                VARCHAR(100) NOT NULL,  -- 조건 항목
    STD_VALUE                NUMERIC(14,4) NOT NULL,  -- 표준값
    TOL_MIN                  NUMERIC(14,4),  -- 허용 하한
    TOL_MAX                  NUMERIC(14,4),  -- 허용 상한
    UOM                      VARCHAR(20),  -- 단위
    APPLY_CONDITION          VARCHAR(200),  -- 적용 재질·두께
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- PRC_ACTUAL_CONDITIONS — 실측작업조건
CREATE TABLE PRC_ACTUAL_CONDITIONS (
    ACT_COND_ID              BIGSERIAL PRIMARY KEY,  -- 실측조건 ID
    WORK_ORDER_ID            BIGINT NOT NULL,  -- 작업지시 ID
    STD_COND_ID              BIGINT,  -- 표준조건 ID
    COND_ITEM                VARCHAR(100) NOT NULL,  -- 조건 항목
    ACTUAL_VALUE             NUMERIC(14,4) NOT NULL,  -- 실측값
    MEASURED_DT              TIMESTAMP NOT NULL,  -- 측정 일시
    COLLECT_METHOD           VARCHAR(20) NOT NULL,  -- 수집 방식
    USER_ID                  BIGINT,  -- 입력자 ID
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- PRC_CONDITION_DEVIATIONS — 작업조건편차
CREATE TABLE PRC_CONDITION_DEVIATIONS (
    DEVIATION_ID             BIGSERIAL PRIMARY KEY,  -- 편차 ID
    ACT_COND_ID              BIGINT NOT NULL,  -- 실측조건 ID
    STD_COND_ID              BIGINT NOT NULL,  -- 표준조건 ID
    DEVIATION_VALUE          NUMERIC(14,4) NOT NULL,  -- 편차값
    DEVIATION_RATE           NUMERIC(8,4),  -- 편차율(%)
    OUT_OF_TOL_YN            CHAR(1) NOT NULL,  -- 허용범위 초과 여부
    ALERT_SENT_YN            CHAR(1) NOT NULL,  -- 알림 발송 여부
    ACTION_COMMENT           VARCHAR(300),  -- 조치 내용
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- PRC_EQUIP_SIGNALS — 설비·공정수집데이터
CREATE TABLE PRC_EQUIP_SIGNALS (
    SIGNAL_ID                BIGSERIAL PRIMARY KEY,  -- 수집 ID
    EQUIP_CODE               VARCHAR(30) NOT NULL,  -- 설비 코드
    COLLECT_DT               TIMESTAMP NOT NULL,  -- 수집 일시
    RUN_STATUS               VARCHAR(20),  -- 가동 상태
    RUN_MINUTE               NUMERIC(10,2),  -- 가동 시간(분)
    PRODUCE_QTY              NUMERIC(14,3),  -- 생산 수량
    SPEED_VALUE              NUMERIC(12,4),  -- 속도
    PRESSURE_VALUE           NUMERIC(12,4),  -- 압력
    CURRENT_VALUE            NUMERIC(12,4),  -- 전류
    TEMP_VALUE               NUMERIC(12,4),  -- 온도
    ALARM_CODE               VARCHAR(30),  -- 알람 코드
    WORK_ORDER_ID            BIGINT,  -- 작업지시 ID
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- SHP_LOT_TRACES — LOT추적관리
CREATE TABLE SHP_LOT_TRACES (
    LOT_TRACE_ID             BIGSERIAL PRIMARY KEY,  -- LOT추적 ID
    PRODUCT_LOT_NO           VARCHAR(50) NOT NULL UNIQUE,  -- 제품 LOT 번호
    PROJECT_ID               BIGINT NOT NULL,  -- 프로젝트 ID
    BOM_ID                   BIGINT,  -- BOM ID
    MATERIAL_LOT_ID          BIGINT,  -- 투입 자재 LOT ID
    WORK_ORDER_ID            BIGINT,  -- 작업지시 ID
    CURRENT_PROCESS          VARCHAR(30),  -- 현재 공정
    TRACE_STATUS             VARCHAR(20) NOT NULL,  -- 추적 상태
    MAPPING_OK_YN            CHAR(1) NOT NULL,  -- 매핑 성공 여부
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- PRC_PERFORMANCES — 공정실적관리
CREATE TABLE PRC_PERFORMANCES (
    PERF_ID                  BIGSERIAL PRIMARY KEY,  -- 실적 ID
    WORK_ORDER_ID            BIGINT NOT NULL,  -- 작업지시 ID
    LOT_TRACE_ID             BIGINT,  -- 제품 LOT ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    WORKER_ID                BIGINT,  -- 작업자 ID
    START_DT                 TIMESTAMP NOT NULL,  -- 작업 시작일시
    END_DT                   TIMESTAMP,  -- 작업 종료일시
    GOOD_QTY                 NUMERIC(14,3) NOT NULL,  -- 실적 수량
    DEFECT_QTY               NUMERIC(14,3),  -- 불량 수량
    DEFECT_TYPE              VARCHAR(50),  -- 불량 유형
    ACTUAL_MANHOUR           NUMERIC(10,2),  -- 실적 공수(h)
    COLLECT_METHOD           VARCHAR(20) NOT NULL,  -- 수집 방식
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- PRC_PROCESS_HISTORIES — 공정이력관리
CREATE TABLE PRC_PROCESS_HISTORIES (
    PRC_HIST_ID              BIGSERIAL PRIMARY KEY,  -- 공정이력 ID
    LOT_TRACE_ID             BIGINT NOT NULL,  -- 제품 LOT ID
    PROCESS_CODE             VARCHAR(30) NOT NULL,  -- 공정 코드
    PROCESS_SEQ              INT NOT NULL,  -- 공정 순서
    IN_DT                    TIMESTAMP NOT NULL,  -- 진입 일시
    OUT_DT                   TIMESTAMP,  -- 종료 일시
    DWELL_HOUR               NUMERIC(10,2),  -- 체류 시간(h)
    PERF_ID                  BIGINT,  -- 실적 ID
    OUTSOURCE_STEP           VARCHAR(20),  -- 외주 반출·반입
    HIST_STATUS              VARCHAR(20) NOT NULL,  -- 이력 상태
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- SHP_SHIPMENTS — 출하관리
CREATE TABLE SHP_SHIPMENTS (
    SHIPMENT_ID              BIGSERIAL PRIMARY KEY,  -- 출하 ID
    SHIPMENT_NO              VARCHAR(50) NOT NULL UNIQUE,  -- 출하번호
    PROJECT_ID               BIGINT NOT NULL,  -- 프로젝트 ID
    CUSTOMER_CODE            VARCHAR(50) NOT NULL,  -- 고객사 코드
    PLAN_DT                  DATE,  -- 출하 예정일
    SHIP_DT                  TIMESTAMP,  -- 출하 일시
    DUE_DT                   DATE,  -- 납기일
    OTD_YN                   CHAR(1),  -- 납기 준수 여부
    SHIP_STATUS              VARCHAR(20) NOT NULL,  -- 출하 상태
    APPROVER_ID              BIGINT,  -- 승인자 ID
    ERP_SYNC_STATUS          VARCHAR(20),  -- ERP 동기화 상태
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- SHP_CLAIMS — 클레임관리
CREATE TABLE SHP_CLAIMS (
    CLAIM_ID                 BIGSERIAL PRIMARY KEY,  -- 클레임 ID
    CLAIM_NO                 VARCHAR(50) NOT NULL UNIQUE,  -- 클레임 번호
    SHIPMENT_ID              BIGINT,  -- 출하 ID
    LOT_TRACE_ID             BIGINT,  -- 제품 LOT ID
    CUSTOMER_CODE            VARCHAR(50) NOT NULL,  -- 고객사 코드
    RECEIVED_DT              TIMESTAMP NOT NULL,  -- 접수 일시
    CLAIM_TYPE               VARCHAR(50),  -- 클레임 유형
    CLAIM_DESC               TEXT,  -- 클레임 내용
    CLAIM_STATUS             VARCHAR(20) NOT NULL,  -- 처리 상태
    CLOSED_DT                TIMESTAMP,  -- 완료 일시
    CREATED_BY               BIGINT,  -- 등록자 ID
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- SHP_INSPECTIONS — 출하검사결과
CREATE TABLE SHP_INSPECTIONS (
    INSPECT_ID               BIGSERIAL PRIMARY KEY,  -- 검사 ID
    LOT_TRACE_ID             BIGINT NOT NULL,  -- 제품 LOT ID
    QSTD_ID                  BIGINT NOT NULL,  -- 품질기준 ID
    INSPECT_ITEM             VARCHAR(100) NOT NULL,  -- 검사 항목
    MEASURED_VALUE           NUMERIC(14,4),  -- 측정값
    UOM                      VARCHAR(20),  -- 단위
    JUDGE_RESULT             VARCHAR(20) NOT NULL,  -- 판정
    INSPECTOR_ID             BIGINT,  -- 검사자 ID
    INSPECT_DT               TIMESTAMP NOT NULL,  -- 검사 일시
    REPORT_NO                VARCHAR(50),  -- 성적서 번호
    REJECT_REASON            VARCHAR(300),  -- 불합격 사유
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- SHP_CLAIM_CAUSES — 클레임원인분석
CREATE TABLE SHP_CLAIM_CAUSES (
    CAUSE_ID                 BIGSERIAL PRIMARY KEY,  -- 원인분석 ID
    CLAIM_ID                 BIGINT NOT NULL,  -- 클레임 ID
    CAUSE_PROCESS            VARCHAR(30),  -- 원인 공정
    CAUSE_FACTOR             VARCHAR(200),  -- 영향 요인
    INSPECT_ID               BIGINT,  -- 관련 검사 ID
    REPEAT_YN                CHAR(1) NOT NULL,  -- 반복 발생 여부
    ACTION_PLAN              VARCHAR(500),  -- 개선 대책
    PREVENT_RESULT           VARCHAR(300),  -- 예방 조치 결과
    ANALYZED_DT              TIMESTAMP NOT NULL,  -- 분석 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- SHP_SHIPMENT_ITEMS — 출하품목내역
CREATE TABLE SHP_SHIPMENT_ITEMS (
    SHIP_ITEM_ID             BIGSERIAL PRIMARY KEY,  -- 출하내역 ID
    SHIPMENT_ID              BIGINT NOT NULL,  -- 출하 ID
    LOT_TRACE_ID             BIGINT NOT NULL,  -- 제품 LOT ID
    ITEM_CODE                VARCHAR(50) NOT NULL,  -- 품목 코드
    SHIP_QTY                 NUMERIC(14,3) NOT NULL,  -- 출하 수량
    WEIGHT_KG                NUMERIC(14,3),  -- 중량(kg)
    PACKING_DT               TIMESTAMP,  -- 포장 완료일시
    INSPECT_ID               BIGINT,  -- 검사 ID
    REMARK                   VARCHAR(300),  -- 비고
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- SYS_ACCESS_LOGS — 접속·작업로그관리
CREATE TABLE SYS_ACCESS_LOGS (
    LOG_ID                   BIGSERIAL PRIMARY KEY,  -- 로그 ID
    LOG_TYPE                 VARCHAR(30) NOT NULL,  -- 로그 구분
    USER_ID                  BIGINT,  -- 사용자 ID
    ACCESS_IP                VARCHAR(45),  -- 접속 IP
    SCREEN_ID                VARCHAR(20),  -- 대상 화면 ID
    ACTION_NAME              VARCHAR(100) NOT NULL,  -- 수행 작업
    RESULT_CODE              VARCHAR(20) NOT NULL,  -- 처리 결과
    ERROR_MSG                VARCHAR(500),  -- 오류 메시지
    OCCURRED_DT              TIMESTAMP NOT NULL,  -- 발생 일시
    CREATED_DT               TIMESTAMP NOT NULL  -- 등록 일시
);

-- SYS_CONFIGS — 시스템·알림설정관리
CREATE TABLE SYS_CONFIGS (
    CONFIG_ID                BIGSERIAL PRIMARY KEY,  -- 설정 ID
    CONFIG_TYPE              VARCHAR(30) NOT NULL,  -- 설정 구분
    CONFIG_KEY               VARCHAR(100) NOT NULL,  -- 설정 키
    CONFIG_VALUE             VARCHAR(500),  -- 설정 값
    ALERT_CONDITION          VARCHAR(300),  -- 알림 조건
    TARGET_ROLE_CODE         VARCHAR(30),  -- 수신 대상 역할
    TARGET_USER_ID           BIGINT,  -- 수신 대상 사용자
    ALERT_CHANNEL            VARCHAR(30),  -- 알림 채널
    USE_YN                   CHAR(1) NOT NULL,  -- 사용여부
    DESCRIPTION              VARCHAR(300),  -- 설명
    CREATED_DT               TIMESTAMP NOT NULL,  -- 등록 일시
    UPDATED_DT               TIMESTAMP  -- 수정 일시
);

-- ── 범위 유니크 (TD5 비고 '그룹 내/구분 내 Unique') ──
ALTER TABLE BAS_COMMON_CODES ADD CONSTRAINT uq_bas_common_codes_code_value UNIQUE (CODE_GROUP, CODE_VALUE);
ALTER TABLE SYS_CONFIGS ADD CONSTRAINT uq_sys_configs_config_key UNIQUE (CONFIG_TYPE, CONFIG_KEY);

-- ── 외래키 (컬럼 정의 뒤에 붙여 순환 참조를 피한다) ──
ALTER TABLE AGT_QUERY_LOGS ADD CONSTRAINT fk_agt_query_logs_user_id FOREIGN KEY (USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE AGT_RECOMMENDATIONS ADD CONSTRAINT fk_agt_recommendations_reviewer_id FOREIGN KEY (REVIEWER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE BAS_COMMON_CODES ADD CONSTRAINT fk_bas_common_codes_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE BAS_COMMON_CODES ADD CONSTRAINT fk_bas_common_codes_parent_code_id FOREIGN KEY (PARENT_CODE_ID) REFERENCES BAS_COMMON_CODES(CODE_ID);
ALTER TABLE BAS_QUALITY_STANDARDS ADD CONSTRAINT fk_bas_quality_standards_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE BAS_WORK_STANDARDS ADD CONSTRAINT fk_bas_work_standards_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE DAT_DATASET_ITEMS ADD CONSTRAINT fk_dat_dataset_items_dataset_id FOREIGN KEY (DATASET_ID) REFERENCES DAT_TRAIN_DATASETS(DATASET_ID);
ALTER TABLE DAT_DATASET_SPLITS ADD CONSTRAINT fk_dat_dataset_splits_dataset_id FOREIGN KEY (DATASET_ID) REFERENCES DAT_TRAIN_DATASETS(DATASET_ID);
ALTER TABLE DAT_DOWNLOAD_LOGS ADD CONSTRAINT fk_dat_download_logs_user_id FOREIGN KEY (USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE DAT_INTEGRATION_JOBS ADD CONSTRAINT fk_dat_integration_jobs_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE DAT_INTEGRATION_JOBS ADD CONSTRAINT fk_dat_integration_jobs_source_id FOREIGN KEY (SOURCE_ID) REFERENCES DAT_SOURCES(SOURCE_ID);
ALTER TABLE DAT_JOB_LOGS ADD CONSTRAINT fk_dat_job_logs_job_id FOREIGN KEY (JOB_ID) REFERENCES DAT_INTEGRATION_JOBS(JOB_ID);
ALTER TABLE DAT_LAKE_OBJECTS ADD CONSTRAINT fk_dat_lake_objects_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE DAT_PREPROCESS_RULES ADD CONSTRAINT fk_dat_preprocess_rules_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE DAT_SOURCES ADD CONSTRAINT fk_dat_sources_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE DAT_TRAIN_DATASETS ADD CONSTRAINT fk_dat_train_datasets_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_BOM_HEADERS ADD CONSTRAINT fk_est_bom_headers_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_BOM_HEADERS ADD CONSTRAINT fk_est_bom_headers_drawing_id FOREIGN KEY (DRAWING_ID) REFERENCES EST_CAD_DRAWINGS(DRAWING_ID);
ALTER TABLE EST_BOM_HEADERS ADD CONSTRAINT fk_est_bom_headers_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE EST_BOM_ITEMS ADD CONSTRAINT fk_est_bom_items_bom_id FOREIGN KEY (BOM_ID) REFERENCES EST_BOM_HEADERS(BOM_ID);
ALTER TABLE EST_BOM_ITEMS ADD CONSTRAINT fk_est_bom_items_parent_item_id FOREIGN KEY (PARENT_ITEM_ID) REFERENCES EST_BOM_ITEMS(BOM_ITEM_ID);
ALTER TABLE EST_BOM_ITEMS ADD CONSTRAINT fk_est_bom_items_source_object_id FOREIGN KEY (SOURCE_OBJECT_ID) REFERENCES EST_CAD_OBJECTS(OBJECT_ID);
ALTER TABLE EST_BOM_ROUTINGS ADD CONSTRAINT fk_est_bom_routings_bom_id FOREIGN KEY (BOM_ID) REFERENCES EST_BOM_HEADERS(BOM_ID);
ALTER TABLE EST_BOM_ROUTINGS ADD CONSTRAINT fk_est_bom_routings_wstd_id FOREIGN KEY (WSTD_ID) REFERENCES BAS_WORK_STANDARDS(WSTD_ID);
ALTER TABLE EST_CAD_DRAWINGS ADD CONSTRAINT fk_est_cad_drawings_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_CAD_DRAWINGS ADD CONSTRAINT fk_est_cad_drawings_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE EST_CAD_FEATURES ADD CONSTRAINT fk_est_cad_features_drawing_id FOREIGN KEY (DRAWING_ID) REFERENCES EST_CAD_DRAWINGS(DRAWING_ID);
ALTER TABLE EST_CAD_OBJECTS ADD CONSTRAINT fk_est_cad_objects_drawing_id FOREIGN KEY (DRAWING_ID) REFERENCES EST_CAD_DRAWINGS(DRAWING_ID);
ALTER TABLE EST_MATERIAL_REQS ADD CONSTRAINT fk_est_material_reqs_bom_id FOREIGN KEY (BOM_ID) REFERENCES EST_BOM_HEADERS(BOM_ID);
ALTER TABLE EST_ML_MODELS ADD CONSTRAINT fk_est_ml_models_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_ML_MODELS ADD CONSTRAINT fk_est_ml_models_dataset_id FOREIGN KEY (DATASET_ID) REFERENCES DAT_TRAIN_DATASETS(DATASET_ID);
ALTER TABLE EST_ML_PREDICTIONS ADD CONSTRAINT fk_est_ml_predictions_model_id FOREIGN KEY (MODEL_ID) REFERENCES EST_ML_MODELS(MODEL_ID);
ALTER TABLE EST_ML_TRAIN_RUNS ADD CONSTRAINT fk_est_ml_train_runs_model_id FOREIGN KEY (MODEL_ID) REFERENCES EST_ML_MODELS(MODEL_ID);
ALTER TABLE EST_OBJECT_REVIEWS ADD CONSTRAINT fk_est_object_reviews_object_id FOREIGN KEY (OBJECT_ID) REFERENCES EST_CAD_OBJECTS(OBJECT_ID);
ALTER TABLE EST_OBJECT_REVIEWS ADD CONSTRAINT fk_est_object_reviews_reviewer_id FOREIGN KEY (REVIEWER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_PROJECTS ADD CONSTRAINT fk_est_projects_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_QUOTATIONS ADD CONSTRAINT fk_est_quotations_approver_id FOREIGN KEY (APPROVER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_QUOTATIONS ADD CONSTRAINT fk_est_quotations_bom_id FOREIGN KEY (BOM_ID) REFERENCES EST_BOM_HEADERS(BOM_ID);
ALTER TABLE EST_QUOTATIONS ADD CONSTRAINT fk_est_quotations_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE EST_QUOTATIONS ADD CONSTRAINT fk_est_quotations_drawing_id FOREIGN KEY (DRAWING_ID) REFERENCES EST_CAD_DRAWINGS(DRAWING_ID);
ALTER TABLE EST_QUOTATIONS ADD CONSTRAINT fk_est_quotations_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE EST_QUOTATION_ITEMS ADD CONSTRAINT fk_est_quotation_items_quote_id FOREIGN KEY (QUOTE_ID) REFERENCES EST_QUOTATIONS(QUOTE_ID);
ALTER TABLE EST_SHAP_FACTORS ADD CONSTRAINT fk_est_shap_factors_predict_id FOREIGN KEY (PREDICT_ID) REFERENCES EST_ML_PREDICTIONS(PREDICT_ID);
ALTER TABLE IF_CAD_FILES ADD CONSTRAINT fk_if_cad_files_drawing_id FOREIGN KEY (DRAWING_ID) REFERENCES EST_CAD_DRAWINGS(DRAWING_ID);
ALTER TABLE IF_CAD_IMPORT_LOGS ADD CONSTRAINT fk_if_cad_import_logs_cad_if_id FOREIGN KEY (CAD_IF_ID) REFERENCES IF_CAD_FILES(CAD_IF_ID);
ALTER TABLE IF_DOC_EMBED_LOGS ADD CONSTRAINT fk_if_doc_embed_logs_doc_id FOREIGN KEY (DOC_ID) REFERENCES AGT_VECTOR_DOCS(DOC_ID);
ALTER TABLE IF_DOC_EMBED_LOGS ADD CONSTRAINT fk_if_doc_embed_logs_ext_doc_id FOREIGN KEY (EXT_DOC_ID) REFERENCES IF_EXT_DOCUMENTS(EXT_DOC_ID);
ALTER TABLE IF_GATEWAY_BUFFER ADD CONSTRAINT fk_if_gateway_buffer_device_id FOREIGN KEY (DEVICE_ID) REFERENCES IF_DEVICE_REGISTRY(DEVICE_ID);
ALTER TABLE IF_PLC_SIGNALS ADD CONSTRAINT fk_if_plc_signals_device_id FOREIGN KEY (DEVICE_ID) REFERENCES IF_DEVICE_REGISTRY(DEVICE_ID);
ALTER TABLE INV_MATERIAL_HISTORY ADD CONSTRAINT fk_inv_material_history_lot_id FOREIGN KEY (LOT_ID) REFERENCES INV_MATERIAL_LOTS(LOT_ID);
ALTER TABLE INV_MATERIAL_HISTORY ADD CONSTRAINT fk_inv_material_history_user_id FOREIGN KEY (USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE INV_MATERIAL_HISTORY ADD CONSTRAINT fk_inv_material_history_work_order_id FOREIGN KEY (WORK_ORDER_ID) REFERENCES PRC_WORK_ORDERS(WORK_ORDER_ID);
ALTER TABLE INV_RECEIPTS ADD CONSTRAINT fk_inv_receipts_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE INV_RECEIPTS ADD CONSTRAINT fk_inv_receipts_lot_id FOREIGN KEY (LOT_ID) REFERENCES INV_MATERIAL_LOTS(LOT_ID);
ALTER TABLE INV_RECEIPTS ADD CONSTRAINT fk_inv_receipts_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE INV_RECEIPTS ADD CONSTRAINT fk_inv_receipts_supplier_id FOREIGN KEY (SUPPLIER_ID) REFERENCES INV_SUPPLIERS(SUPPLIER_ID);
ALTER TABLE INV_STOCKS ADD CONSTRAINT fk_inv_stocks_lot_id FOREIGN KEY (LOT_ID) REFERENCES INV_MATERIAL_LOTS(LOT_ID);
ALTER TABLE INV_SUPPLIER_QUALITY ADD CONSTRAINT fk_inv_supplier_quality_supplier_id FOREIGN KEY (SUPPLIER_ID) REFERENCES INV_SUPPLIERS(SUPPLIER_ID);
ALTER TABLE KPI_MEASURES ADD CONSTRAINT fk_kpi_measures_kpi_target_id FOREIGN KEY (KPI_TARGET_ID) REFERENCES KPI_TARGETS(KPI_TARGET_ID);
ALTER TABLE KPI_TARGETS ADD CONSTRAINT fk_kpi_targets_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE PRC_ACTUAL_CONDITIONS ADD CONSTRAINT fk_prc_actual_conditions_std_cond_id FOREIGN KEY (STD_COND_ID) REFERENCES PRC_STD_CONDITIONS(STD_COND_ID);
ALTER TABLE PRC_ACTUAL_CONDITIONS ADD CONSTRAINT fk_prc_actual_conditions_user_id FOREIGN KEY (USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE PRC_ACTUAL_CONDITIONS ADD CONSTRAINT fk_prc_actual_conditions_work_order_id FOREIGN KEY (WORK_ORDER_ID) REFERENCES PRC_WORK_ORDERS(WORK_ORDER_ID);
ALTER TABLE PRC_CONDITION_DEVIATIONS ADD CONSTRAINT fk_prc_condition_deviations_act_cond_id FOREIGN KEY (ACT_COND_ID) REFERENCES PRC_ACTUAL_CONDITIONS(ACT_COND_ID);
ALTER TABLE PRC_CONDITION_DEVIATIONS ADD CONSTRAINT fk_prc_condition_deviations_std_cond_id FOREIGN KEY (STD_COND_ID) REFERENCES PRC_STD_CONDITIONS(STD_COND_ID);
ALTER TABLE PRC_EQUIP_SIGNALS ADD CONSTRAINT fk_prc_equip_signals_work_order_id FOREIGN KEY (WORK_ORDER_ID) REFERENCES PRC_WORK_ORDERS(WORK_ORDER_ID);
ALTER TABLE PRC_PERFORMANCES ADD CONSTRAINT fk_prc_performances_lot_trace_id FOREIGN KEY (LOT_TRACE_ID) REFERENCES SHP_LOT_TRACES(LOT_TRACE_ID);
ALTER TABLE PRC_PERFORMANCES ADD CONSTRAINT fk_prc_performances_worker_id FOREIGN KEY (WORKER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE PRC_PERFORMANCES ADD CONSTRAINT fk_prc_performances_work_order_id FOREIGN KEY (WORK_ORDER_ID) REFERENCES PRC_WORK_ORDERS(WORK_ORDER_ID);
ALTER TABLE PRC_PROCESS_HISTORIES ADD CONSTRAINT fk_prc_process_histories_lot_trace_id FOREIGN KEY (LOT_TRACE_ID) REFERENCES SHP_LOT_TRACES(LOT_TRACE_ID);
ALTER TABLE PRC_PROCESS_HISTORIES ADD CONSTRAINT fk_prc_process_histories_perf_id FOREIGN KEY (PERF_ID) REFERENCES PRC_PERFORMANCES(PERF_ID);
ALTER TABLE PRC_STD_CONDITIONS ADD CONSTRAINT fk_prc_std_conditions_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE PRC_STD_CONDITIONS ADD CONSTRAINT fk_prc_std_conditions_wstd_id FOREIGN KEY (WSTD_ID) REFERENCES BAS_WORK_STANDARDS(WSTD_ID);
ALTER TABLE PRC_WORK_ORDERS ADD CONSTRAINT fk_prc_work_orders_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE PRC_WORK_ORDERS ADD CONSTRAINT fk_prc_work_orders_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE PRC_WORK_ORDERS ADD CONSTRAINT fk_prc_work_orders_routing_id FOREIGN KEY (ROUTING_ID) REFERENCES EST_BOM_ROUTINGS(ROUTING_ID);
ALTER TABLE PRC_WORK_ORDERS ADD CONSTRAINT fk_prc_work_orders_supplier_id FOREIGN KEY (SUPPLIER_ID) REFERENCES INV_SUPPLIERS(SUPPLIER_ID);
ALTER TABLE SHP_CLAIMS ADD CONSTRAINT fk_shp_claims_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SHP_CLAIMS ADD CONSTRAINT fk_shp_claims_lot_trace_id FOREIGN KEY (LOT_TRACE_ID) REFERENCES SHP_LOT_TRACES(LOT_TRACE_ID);
ALTER TABLE SHP_CLAIMS ADD CONSTRAINT fk_shp_claims_shipment_id FOREIGN KEY (SHIPMENT_ID) REFERENCES SHP_SHIPMENTS(SHIPMENT_ID);
ALTER TABLE SHP_CLAIM_CAUSES ADD CONSTRAINT fk_shp_claim_causes_claim_id FOREIGN KEY (CLAIM_ID) REFERENCES SHP_CLAIMS(CLAIM_ID);
ALTER TABLE SHP_CLAIM_CAUSES ADD CONSTRAINT fk_shp_claim_causes_inspect_id FOREIGN KEY (INSPECT_ID) REFERENCES SHP_INSPECTIONS(INSPECT_ID);
ALTER TABLE SHP_INSPECTIONS ADD CONSTRAINT fk_shp_inspections_inspector_id FOREIGN KEY (INSPECTOR_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SHP_INSPECTIONS ADD CONSTRAINT fk_shp_inspections_lot_trace_id FOREIGN KEY (LOT_TRACE_ID) REFERENCES SHP_LOT_TRACES(LOT_TRACE_ID);
ALTER TABLE SHP_INSPECTIONS ADD CONSTRAINT fk_shp_inspections_qstd_id FOREIGN KEY (QSTD_ID) REFERENCES BAS_QUALITY_STANDARDS(QSTD_ID);
ALTER TABLE SHP_LOT_TRACES ADD CONSTRAINT fk_shp_lot_traces_bom_id FOREIGN KEY (BOM_ID) REFERENCES EST_BOM_HEADERS(BOM_ID);
ALTER TABLE SHP_LOT_TRACES ADD CONSTRAINT fk_shp_lot_traces_material_lot_id FOREIGN KEY (MATERIAL_LOT_ID) REFERENCES INV_MATERIAL_LOTS(LOT_ID);
ALTER TABLE SHP_LOT_TRACES ADD CONSTRAINT fk_shp_lot_traces_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE SHP_LOT_TRACES ADD CONSTRAINT fk_shp_lot_traces_work_order_id FOREIGN KEY (WORK_ORDER_ID) REFERENCES PRC_WORK_ORDERS(WORK_ORDER_ID);
ALTER TABLE SHP_SHIPMENTS ADD CONSTRAINT fk_shp_shipments_approver_id FOREIGN KEY (APPROVER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SHP_SHIPMENTS ADD CONSTRAINT fk_shp_shipments_created_by FOREIGN KEY (CREATED_BY) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SHP_SHIPMENTS ADD CONSTRAINT fk_shp_shipments_project_id FOREIGN KEY (PROJECT_ID) REFERENCES EST_PROJECTS(PROJECT_ID);
ALTER TABLE SHP_SHIPMENT_ITEMS ADD CONSTRAINT fk_shp_shipment_items_inspect_id FOREIGN KEY (INSPECT_ID) REFERENCES SHP_INSPECTIONS(INSPECT_ID);
ALTER TABLE SHP_SHIPMENT_ITEMS ADD CONSTRAINT fk_shp_shipment_items_lot_trace_id FOREIGN KEY (LOT_TRACE_ID) REFERENCES SHP_LOT_TRACES(LOT_TRACE_ID);
ALTER TABLE SHP_SHIPMENT_ITEMS ADD CONSTRAINT fk_shp_shipment_items_shipment_id FOREIGN KEY (SHIPMENT_ID) REFERENCES SHP_SHIPMENTS(SHIPMENT_ID);
ALTER TABLE SYS_ACCESS_LOGS ADD CONSTRAINT fk_sys_access_logs_user_id FOREIGN KEY (USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SYS_CONFIGS ADD CONSTRAINT fk_sys_configs_target_user_id FOREIGN KEY (TARGET_USER_ID) REFERENCES SYS_USERS(USER_ID);
ALTER TABLE SYS_USERS ADD CONSTRAINT fk_sys_users_role_id FOREIGN KEY (ROLE_ID) REFERENCES SYS_ROLE_PERMISSIONS(ROLE_PERM_ID);
