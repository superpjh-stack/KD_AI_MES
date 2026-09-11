# progress.md — 경동글로벌텍 제조AI (SF26179182)

**검증된 현황의 유일한 진실.** 실측값 + 검증 명령만 적는다. 명령 없이 적힌 숫자는 없는 것으로 친다.
판정 기준은 `goal.md` §2. 결정은 `decisions.md`.

---

## 2026-09-11 회전 1 — Phase 0 (아키텍트 단독 · 오케스트레이터 직접 수행)

`/loop goal.md` 동적 모드 1회전. 착수 시 이 폴더에는 `goal.md` `CLAUDE.md` 뿐이었다.
**§2 게이트를 측정할 수단이 없었으므로 회전 1의 목표를 "측정 가능 상태 만들기" 로 잡았다**(§10-15).
에이전트는 띄우지 않았다 — Phase 0 은 웨이브 A 앞이고 혼자 하는 일이다.

### 한 일

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 디렉터리 골격 | `docs/{design,산출물,cad}` `src/kyungdong/app/{routers,templates,util,static}` `db` `tools` `tests` `contracts` `work` `outputs` 생성 | `ls -R` |
| 정본 반입 | design.json 434KB · analysis.json · 사업계획서.pdf 3.1MB · 산출내역서 v0.97 · 화면설명서 HTML + 화면정의서 PPT 11MB · CAD 자료 6종 1.4MB | `du -sh docs/*` |
| **정본 재실측 (복사본 기준)** | **화면 45 · 영역 10 · 프로그램 49 · 테이블 68 · 컬럼 762 · 공통 4 · 역할 6 / 기능 45 · 비기능 13** — goal.md 표와 일치 | `uv run python -c "…"` (goal.md §9) |
| 테이블 접두 | `BAS`3 `SYS`4 `INV`6 `EST`16 `SHP`6 `PRC`7 `DAT`11 `AGT`3 `KPI`2 `IF`10 = **68** | 같은 명령 |
| DB | `kyungdong_db` 생성 · `vector` **0.8.6** 확장 설치 | `psql -d kyungdong_db -Atc "select extversion from pg_extension where extname='vector'"` |
| uv 프로젝트 | Python 3.12 핀 · `uv sync` 완료 · fastapi·psycopg·xgboost 3.4.1·shap·sklearn·pandas·numpy·jinja2 임포트 확인 | `uv run python -c "import …;print('deps ok')"` |
| `.env.example` | `KYUNGDONG_*` 26키. 가설값에 `(D-nn)` 주석을 달았다 | `wc -l .env.example` = 44 |
| `decisions.md` | goal.md §7 의 **D-01~D-27 전건 이관** + 회전 1 발견 **D-28~D-36** | 파일 |

### 스키마 생성 — `tools/gen_schema.py` → `db/schema.sql`

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| **G-01 테이블** | **68** ✅ **PASS** | `psql -d kyungdong_db -Atc "select count(*) from information_schema.tables where table_schema='public'"` |
| **G-02 컬럼** | **762** ✅ **PASS** | `select count(*) from information_schema.columns where table_schema='public'` |
| FK 제약 | **98** 생성 (TD5 FK 표기 128건 − 코드성 참조 29 − 금액 오표기 1) | `select count(*) … constraint_type='FOREIGN KEY'` |
| UNIQUE 제약 | **16** (단일 14 + 범위 복합 2) = TD5 `Unique` 표기 16건과 일치 | `select count(*) … constraint_type='UNIQUE'` |
| pgvector | `AGT_VECTOR_DOCS.EMBEDDING VECTOR(1536)` 적용됨 | schema.sql · `\d AGT_VECTOR_DOCS` |

**TD5 는 내부 정합했다**(D-36) — FK 128건이 전부 실제 68표로 해석되고, PK 는 표당 정확히 1개이며,
컬럼 행 길이 위반 0건, 타입 어휘 전부 유효. 손 수정 없이 생성기만으로 스키마가 나왔다.

### 생성기가 잡아낸 것 (고치지 않고 등재했다)

| ID | 내용 |
|---|---|
| **D-32** | 코드성 FK **29건**이 물리 FK 로 성립하지 않는다 — `VARCHAR(30/50)` 컬럼이 `BAS_COMMON_CODES.CODE_ID BIGSERIAL` 을 가리킨다. 실제 의도는 `(CODE_GROUP, CODE_VALUE)` 참조. **FK 제약 미생성 + 애플리케이션 검증** |
| **D-33** | `EST_QUOTATION_ITEMS.UNIT_PRICE NUMERIC(16,2)` 이 FK='Y' 로 표기됨 — **금액 값 컬럼을 외래키로 적은 결함.** 컬럼을 추가하지 않고(G-02 고정) 제안만 |
| **D-34** | 범위 유니크 2건을 복합 제약으로 — `UNIQUE(CODE_GROUP, CODE_VALUE)` · `UNIQUE(CONFIG_TYPE, CONFIG_KEY)` |
| **D-31** | 임베딩 차원 **1536** 확정 (TD5 명시) → D-08 의 "차원 미정" 해소 |
| **D-35** | KPI 코드 확정 — `LEADTIME_MFG` · `LEADTIME_O2D` (TD5 `KPI_TARGETS.KPI_CODE` 비고) |

### 생성기 자체 결함 2건 — 만들면서 잡았다

1. **쉼표가 주석에 먹혔다.** `",\n".join()` 이 `-- 한글명,` 을 만들어 `--` 가 쉼표를 삼켰다 → `psql` 이 두 번째 컬럼에서 구문 오류. 쉼표를 **주석 앞**에 두도록 고쳤다. 이것 때문에 첫 적용이 **테이블 0개**로 끝났다.
2. **범위 유니크를 단일 유니크로 만들 뻔했다.** 비고에 `Unique` 가 있으면 무조건 `UNIQUE` 를 붙이던 로직이 `CODE_VALUE`(그룹 내)·`CONFIG_KEY`(구분 내)에 **틀린 제약**을 걸었다. `SCOPED_UNIQUE` 표에 **명시**하는 방식으로 바꿨다(추측 금지).

### 게이트 판정기 — `tools/gate.py` + `Makefile`

`make gate` 첫 실행 결과:

```
G-01 테이블 68                 PASS   68
G-02 컬럼 762                  PASS   762
정본  design/analysis = goal.md 표  PASS   화면45 영역10 프로그램49 표68 컬럼762 기능45 비기능13
G-03 / G-04 / G-05 / G-06      미구현  (check_routes·check_trace·nav.py 미작성)
G-07~G-11 / G-12~G-13 / G-14~G-25 / G-26~G-30   미구현  (QA 검사기 미작성)
G-빌드 pytest                   미구현  테스트 0파일
──────────────────────────────────────────
PASS 3 · FAIL 0 · 차단 0 · 미구현 9  /  12
```

**`미구현` 은 PASS 가 아니다.** `gate.py` 는 QA 소유 검사기를 있으면 호출하고 없으면 `미구현` 으로 표시하며
**여기서 만들지 않는다**(goal.md §3.4). 빌드 게이트는 "몇 건 실행됐는지" 를 보고 0건이면 `차단` 을 낸다(§10-15).

---

## 지금 해야 할 것 (회전 2 — 웨이브 A 아키텍트)

가장 앞선 FAIL/미구현은 **G-06 → G-03** 이다. 웨이브 A 를 끝내야 개발 3명이 코드를 쓸 수 있다.

1. `app/nav.py` — 10영역 45화면 단일 소스 (`td3.menu_shortcuts` 순서) → **G-06**
2. `app/rbac.py` — TD3 `role_matrix` **6역할 × 8영역**
3. `app/util/` — 오류 규약 10종(§2.5) · 세션 · 속도제한 · 보안헤더 · CSRF
4. `app/templates/{base,login,_placeholder,_popup,_error}.html` — `_placeholder` 가 TD3/TD4/AD2 문장을 200 으로 렌더
5. `tools/check_routes.py` → **G-03**
6. `contracts/` 4종 — `db-schema.md`(D-32·D-33 매핑 포함) · `api-contract.md` · `screen-map.md`(45행 + 담당·소유) · `interfaces.md`
7. D-20 — Agent 시안 도구 11종 ↔ TD5 68표 재배선 매핑표

## 알아둘 것

- **8020 포트를 쓴다.** 8000·8010 은 이웃 사업 서버가 점유 중이다(실측, D-28).
- **`db/schema.sql` 은 손으로 고치지 않는다.** `make gen-schema` 로만 바뀐다.
- **코드성 FK 29건은 DB 가 막아주지 않는다**(D-32). 개발 3명은 코드 값 검증을 애플리케이션에서 해야 한다 — `contracts/interfaces.md` 에 공용 검증 함수를 두는 것이 맞다.
- **`pdftotext` 가 없다**(D-30). 사업계획서는 `uv run --with pypdf` 로 읽는다.
- 이 사업의 AI 는 **CAD 견적 자동화 + RAG Agent** 다. **예지보전·품질예측을 만들면 결함**이다(D-01). 직전 사업(광성정밀)이 예지보전이라 코드를 가져올 때 가장 위험하다.

---

## 2026-09-11 회전 2 — 웨이브 A (아키텍트 · 오케스트레이터 직접 수행)

사용자가 "컴퓨터가 잠들어도 계속" 을 요청했다. 절전은 `caffeinate` 로 막았고(`work/caffeinate.pid`, 12시간),
**뚜껑 닫힘·세션 종료는 막을 수 없다**는 것을 명시하고 `RESUME.md` 로 복귀 비용을 0에 가깝게 만들었다.

### 게이트 실측 — `make gate`

```
G-01 테이블 68                          PASS   68
G-02 컬럼 762                           PASS   762
G-06 메뉴 10영역 단일 소스                 PASS
G-03 화면 45+공통4+오류1 · ph 0 · 용어 0    FAIL   ①200 PASS / ②placeholder 45건 FAIL / ③용어 PASS
정본  design/analysis = goal.md 표        PASS   화면45 영역10 프로그램49 표68 컬럼762 기능45 비기능13
G-04·G-05                              미구현  check_trace.py (QA1)
G-07~G-30                              미구현  check_data·check_ingest·check_ai·check_security (QA2·QA3)
G-빌드 pytest                            PASS   59 passed
──────────────────────────────────────────────────────
PASS 5 · FAIL 1 · 차단 0 · 미구현 6  /  12
```

**G-03 의 FAIL 은 placeholder 45건 하나뿐이다** — 개발 3명이 화면을 채우면 사라진다. 정상적인 진행 상태다.

### 만든 것

| 파일 | 역할 | 실측 검증 |
|---|---|---|
| `app/design.py` | **정본 로더** — `screen/program/requirement/table_def/trace/columns_of`. `selfcheck()` 가 정본 9항목을 goal.md 표와 대조 | 9/9 일치 (`selfcheck()`) |
| `app/nav.py` | **메뉴 단일 소스 (G-06)** — `td3.menu_shortcuts` 순서 10영역, 45화면을 design.json 에서 읽는다(45행 손으로 안 적음) | 영역 10 · 화면 45 · 소유 **개발1 15 / 개발2 16 / 개발3 14** = goal.md §3.2 와 일치 |
| `app/rbac.py` | **6역할 × 8권한영역** — TD3 `role_matrix` 셀 문구를 R/W/A 로 해석. 모르는 문구는 **예외로 터뜨린다** | 현장 작업자 → 수주견적AI관리 = `-` → **403** 확인 |
| `app/settings.py` | `KYUNGDONG_*` 로더. **가설값 11종을 값+D번호+설명 묶음**으로 들고 다녀 화면에 `가설 (D-nn)` 배지를 띄운다 | 11종 출력 확인 · prod 에서 `SESSION_SECRET` 없으면 기동 거부 |
| `app/util/http.py` | **오류 계약 7종** 한 곳 (401·403·422·500·501×2·503) + 200 으로 드러내는 알림 문구 5종 | 계약 밖 key 는 `KeyError` |
| `app/templating.py` | Jinja2 · **autoescape 기본**(§10-8) · 권한 있는 메뉴만 노출 | — |
| `app/main.py` | 45화면 + 공통 4 + 오류. **담당 라우터가 있으면 그것이 이기고**, 없는 화면만 `_placeholder` | 라우트 53 · placeholder 45 · 담당 라우터 0 |
| `app/templates/` 7종 + `static/app.css` | `_placeholder` 가 AD2·TD3·TD4·TD5 **정본 문장과 컬럼표**를 200 으로 렌더. CSS 는 **단일 파일**(§10-13) | 전 화면 200 |
| `tools/check_routes.py` | **G-03·G-06 검사기** | 아래 참조 |
| `tools/gen_screen_map.py` → `contracts/screen-map.md` | 화면 45행 + 소유권 + 모듈별 + 공통 + RBAC 표. **정본은 `nav.py`** | G-06 PASS |
| `tests/test_arch_smoke.py` | 정본 규모·메뉴·소유 3분할·추적 1:1·공통 200·45화면 200·403·메뉴 은닉·오류 계약·미구성 노출 | **59 passed** |

### 검사기·게이트 자체 결함 4건 — 만들면서 잡았다 (전부 §10 이 경고한 유형)

1. **오염 검사가 통째로 무력했다.** `QUOTE_OK` 를 **본문 전체**에서 찾아서, placeholder 의 "산출물 정본 문장이다" 에 걸려 항상 면제됐다. → 용어 **주변 160자**만 보도록 고쳤다(D-37). 고치자마자 숨어 있던 4건이 드러났다.
2. **고친 검사기가 잡은 4건은 오염이 아니었다.** `/dsh/003`·`/prc/022` 가 렌더한 "설비 예지보전 AI는 본 사업 범위 밖이다" · "포밍·용접 설비는 제외한다" 는 **배제 진술**이다. 배제 문맥을 인정하도록 규칙을 정했다(D-37).
3. **빌드 게이트가 `차단` 을 오판했다.** `gate.py` 가 stdout **마지막 줄**을 요약으로 믿었는데 경고 문서 URL 이 뒤에 붙는다 → 요약 줄을 정규식으로 찾도록 고쳤다.
4. **`-qq` 때문에 요약 줄이 아예 없었다.** `pyproject` `addopts = "-q"` 에 명령줄 `-q` 가 더해졌다 → `gate.py` 는 `uv run pytest` 로 부른다.

**둘 다 검사기가 "항상 통과" 하거나 "판정을 못 하는" 결함이었다.** 주입 시험으로 양방향을 확인했다 —
일부러 `프레스 금형 샷카운트` 를 넣으면 3건 FAIL, 빼면 0건 PASS.

### 지금 해야 할 것 (회전 3)

가장 앞선 미구현은 **G-04·G-05**(요구사항 추적)다. 웨이브 A 잔여분을 끝낸 뒤 웨이브 B 로 넘어간다.

1. `contracts/db-schema.md` — 68표·762컬럼 + **D-32 코드성 FK 29건 검증 규약** + D-33 매핑
2. `contracts/api-contract.md` — 45화면 라우트 + 공통 + Agent API + 수집 API + CAD 업로드 API
3. `contracts/interfaces.md` — `db.conn.q/x/tx` · `design.*` · `templating.render` · `util.http` · `ingest`·`cad` 시그니처
4. `db/conn.py` — psycopg 연결·`q/x/tx` (DB 죽으면 **503**, 조용히 빈 배열 금지)
5. D-20 — Agent 시안 도구 11종 ↔ TD5 68표 재배선 매핑표
6. `tools/check_trace.py`(QA1 소유지만 **게이트가 안 서면 아무 판정도 못 한다** — 아키텍트가 최소판을 만들고 QA1 이 인수할지 결정)

### 알아둘 것

- **`?as=OPERATOR` 로 역할을 바꿔 화면을 볼 수 있다**(D-40 가설). 인증이 들어오면 이 미들웨어를 **제거**해야 한다 — 남으면 보안 결함이다.
- **담당 라우터가 placeholder 를 이긴다.** 개발자는 `app/routers/<module>.py` 에 `router` 와 `SCREENS = ("MES-TD3-0nn", …)` 를 두면 된다. main.py 는 건드리지 않는다.
- `contracts/screen-map.md` 는 **생성 파일**이다. `nav.py` 를 고치고 `uv run python tools/gen_screen_map.py` 를 다시 돌린다.
- 게이트 판정을 볼 때 **`미구현` 6건이 PASS 가 아니다.** 현재 진짜 측정된 것은 G-01·G-02·G-03·G-06·빌드뿐이다.

---

## 2026-09-11 회전 3 — 웨이브 A 완료 (아키텍트)

### 게이트 실측 — `make gate`

```
G-01 68 PASS · G-02 762 PASS · G-06 PASS · 정본 PASS · G-빌드 PASS (70 passed)
G-03 FAIL — ①200 PASS / ②placeholder 45 FAIL / ③용어 PASS
G-04·G-05 · G-07~G-30  미구현 (QA 검사기 미작성)
──────────────────────────────────────────
PASS 5 · FAIL 1 · 차단 0 · 미구현 6  /  12   (회전 2와 동일 — 웨이브 A 는 게이트를 올리는 일이 아니라 개발 3명이 코드를 쓸 수 있게 하는 일이다)
```

### 만든 것

| 파일 | 역할 | 실측 검증 |
|---|---|---|
| `db/conn.py` | `q`·`q1`·`x`·`tx`·`alive`. **DB 장애 → 503**(빈 배열 금지) · dict 행 · 파라미터 바인딩 강제 | DSN 을 죽였을 때 **HTTP 503 `db_down`** 확인. 0건은 `None`(정상) |
| `contracts/screen-map.md` | 화면 45행 + 소유권 + 모듈별 + 공통 + RBAC 표 | 생성. G-06 PASS |
| `contracts/db-schema.md` | 68표·762컬럼 · 물리 FK 98 · **코드성 29(D-32)** · 오표기 1(D-33) · 디지털 스레드 · 개인정보 6 · 런타임전용 11 + **미정 6** | 생성 |
| `contracts/api-contract.md` | 45화면 라우트 + 공통 5 + EIF 4 + 오류 7종 + Agent API + **승인 필요 쓰기 6종** | 생성 |
| `contracts/interfaces.md` | 공용 시그니처 9절. **아직 없는 것 4종**(`validate_code`·`mask`·`anchor`·`audit`)도 시그니처를 먼저 공표 | 손으로 작성 |
| `tools/gen_{screen_map,db_contract,api_contract}.py` · `make contracts` | 계약 3종 생성기 | 재생성 무변화 테스트로 잠금 |
| `tests/test_arch_contracts.py` | 계약 드리프트 · DB 503 · 0건 None · 바인딩 · D-32 전건 등재 · 런타임전용 미정 구분 | **70 passed** (회전 2 59 → +11) |

### 실측으로 확인한 것

| 항목 | 실측 |
|---|---|
| 물리 FK | **98** (TD5 FK 표기 128 − 코드성 29 − 오표기 1) |
| **코드성 FK (D-32)** | **29건** — `VARCHAR` 컬럼이 `BAS_COMMON_CODES.CODE_ID BIGSERIAL` 을 가리킨다. **DB 가 막지 않으므로 애플리케이션 검증 필수.** 계약 §3 에 전건 등재(테스트로 잠금) |
| 개인정보 (G-29) | **6컬럼** — 암호화 저장 + 화면 마스킹 |
| 런타임 전용 (G-11) | **확실한 것 11표**만 계약에 넣었다 |
| 시드 여부 **미정 6표** | `INV_MATERIAL_HISTORY` · `PRC_PROCESS_HISTORIES` · `PRC_CONDITION_DEVIATIONS` · `EST_SHAP_FACTORS` · `INV_SUPPLIER_QUALITY` · `SHP_CLAIM_CAUSES` — **담당 개발자가 판정한다** |

### 이번에도 짐작을 계약에 넣을 뻔했다

런타임 전용 표를 **이름 휴리스틱**(`_HISTORY`·`_DEVIATIONS`)으로 뽑았더니 `INV_MATERIAL_HISTORY`(원자재 이력)·
`PRC_CONDITION_DEVIATIONS`(작업조건 편차)까지 "0건이 정상" 으로 분류됐다. **시드 대상 업무 데이터일 수 있다.**
G-11 판정이 여기에 걸려 있으므로 **확실한 것(로그·버퍼)만 계약에 넣고 나머지 6표는 §7.1 '미정' 으로 넘겼다.**
담당 개발자가 판정해 옮긴다.

### 새 산출물 결함 — D-41

**외주 발주 관리 항목이 없다.** TD1 `process_steps` 는 소재가공(외주)·버핑(외주)의 데이터로
"외주 발주번호, 자재 LOT, 반출·반입일, 외주처, 수량" 을 적었는데 TD5 에 **외주 발주번호·외주처 컬럼이 없다.**
구매 발주(PO) 테이블도 없고 `EST_MATERIAL_REQS.PO_NEED_YN` 뿐이다.
→ **컬럼을 추가하지 않고**(G-02 762 고정) 있는 것으로 소화한다: 반출·반입은 `PRC_PROCESS_HISTORIES.OUTSOURCE_STEP` ·
`INV_MATERIAL_HISTORY.HIST_TYPE`, 외주처는 `INV_SUPPLIERS(SUPPLY_TYPE='외주')`, 발주번호는 `PRC_WORK_ORDERS.WORK_ORDER_NO`.
화면에 `대체 표기 (D-41)` 을 붙이고 정규 컬럼 신설을 제안한다.

### D-20 Agent 도구 재배선 확정

시안 11종을 TD5 68표에 전부 매핑했다(decisions.md D-20 표). 시안 `purchase_orders` 만 대응표가 없어 D-41 로 갔다.
**프롬프트 7~10번(검색하지 않은 문서를 지어내지 않는다)·5줄 형식·`근거:` 줄·승인 명시**를 이식하고,
SQLite 스키마·`demo_data`·데모 예측 상수·Streamlit·`voice.py` 는 버린다.

### 지금 해야 할 것 (회전 4)

**웨이브 A 는 끝났다. 다음은 웨이브 B(개발 3명 병렬)이고 여기서 토큰이 크게 는다 — 사용자 확인을 받는다.**

확인을 기다리는 동안 아키텍트가 혼자 할 수 있는 잔여분을 한다(에이전트 0):

1. `app/util/` 공용 4종 — `validate_code()`(D-32 코드성 FK 검증) · `mask()`(G-29) · `anchor()`(§10-3 시간 앵커) · `audit()`(G-29 `SYS_ACCESS_LOGS`)
2. `db/seed.py` 뼈대 — 시간 앵커 발급 · 역할 6 · 계정 난수 1회 출력 · `BAS_COMMON_CODES` 10공정 + 제품군 5종
3. `app/util/` 세션·속도제한·보안헤더·CSRF (§10-12)

### 알아둘 것

- **계약 3종은 생성 파일이다**(D-43). 손으로 고치면 `test_계약을_다시_뽑아도_같다` 가 잡는다. `make contracts` 로 갱신한다.
- **`tools/check_trace.py` 는 QA1 몫이다**(D-42). 아키텍트가 대신 만들지 않는다 — G-04·G-05 는 QA1 이 올 때까지 `미구현` 이고 **`미구현`은 PASS 가 아니다**. 추적 1:1 자체는 스모크 테스트가 이미 단언한다.
- 개발자는 `main.py` 를 건드리지 않는다. 자기 `app/routers/<module>.py` 에 `router` 와 `SCREENS = (...)` 만 두면 placeholder 에서 빠진다.

---

## 2026-09-11 회전 4 — 공용 모듈·공통 시드 (아키텍트 · 에이전트 0)

웨이브 B 는 사용자 확인 대기 중이라 아키텍트 잔여분만 했다.

### 게이트 — `make gate`

```
PASS 5 · FAIL 1 · 차단 0 · 미구현 6  /  12      G-빌드 88 passed (70 → +18)
```

### 만든 것

| 파일 | 역할 | 실측 검증 |
|---|---|---|
| `app/util/codes.py` | **D-32 코드성 FK 검증** — `validate_code` · `require_code`(위반 시 **422**) · `code_group_for`. 29컬럼 → 코드 그룹 매핑을 **명시**(추측 아님) | 매핑 **29/29**, 미지정 **0**. `require_code` 위반 시 422 확인 |
| `app/util/pii.py` | **G-29 마스킹** — name·phone·email·generic | `홍길동`→`홍**` · `010-1234-5678`→`010-****-5678` · `so*****@example.com` |
| `app/util/clock.py` | **시간 앵커**(§10-3). 앵커가 없으면 **터진다** — 조용히 오늘 날짜로 대체하지 않는다 | 재실행해도 앵커 불변 확인 |
| `app/util/audit.py` | **G-29 감사추적** `SYS_ACCESS_LOGS`. 기록 실패를 삼키지 않는다 | LOG_TYPE 은 TD5 4종만 허용(위반 시 예외) |
| `db/seed.py` | 시간 앵커 · 역할 **6×10=60행** · 계정 6 · 공통코드 25 | **3회 연속 exit 0 · 행 수 diff 0 · 비밀번호 불변** |
| `tests/test_arch_seed.py` | G-07 멱등 · §10-11 비밀번호 · 앵커 고정 · RBAC DB 반영 · 실명 없음 · 빈 그룹 · D-32 검증 · 마스킹 | **88 passed** (70 → +18) |

### 실측으로 확인한 것

| 항목 | 실측 |
|---|---|
| `SYS_ROLE_PERMISSIONS.AREA_CODE` | TD5 비고가 정한 `DSH/INV/EST/SHP/PRC/BAS/DAT/AGT/KPI/SYS` **10코드가 `nav.py` 라우트 접두와 정확히 같다** — 정본이 접두 선택을 확인해 줬다 |
| 역할·권한 | **60행** (6역할 × 10영역). 현장 작업자 `EST` 는 `READ_YN='N'` — TD3 셀 `-` 가 DB 까지 내려왔다(G-28) |
| 채운 코드 그룹 | **6** — 공정 10(레이저커팅만 자동 수집) · 제품군 5 · 검사구분 3(수압·기밀·진공) · 공급구분 3 · 외주구간 2 · 설비 2(수집 지점 2개소) |
| **비운 코드 그룹** | **7** — 품목 · 재질 · 고객사 · 보관위치 · 불량유형 · 클레임유형 · 원가대상. **정본에 값이 없어 지어내지 않았다**(D-47). 테스트가 "비어 있음" 을 단언한다 |

### 실물로 터진 산출물 결함 — D-44

시드 재실행이 **`ForeignKeyViolation` 으로 죽었다**:

```
update or delete on table "sys_role_permissions" violates foreign key constraint "fk_sys_users_role_id"
DETAIL:  Key (role_perm_id)=(1) is still referenced from table "sys_users".
```

원인은 TD5 설계다 — `SYS_USERS.ROLE_ID` 가 `SYS_ROLE_PERMISSIONS.ROLE_PERM_ID` 를 가리키는데
그 표는 **역할 × 영역(× 화면) 조합마다 한 행**이다. 사용자가 "역할" 이 아니라 **권한 행 하나**를 가리킨다.

→ **컬럼을 추가하지 않고**(G-02 762 고정) 두 가지로 풀었다.
1. 시드는 `ROLE_ID` 에 **그 역할의 대표 행(최소 `ROLE_PERM_ID`)** 을 넣고, 권한 판정은 `ROLE_CODE` 조인으로 한다.
2. **물리 유니크**(D-45)를 걸어 시드를 `delete+insert` 에서 **upsert** 로 바꿨다 —
   `UNIQUE NULLS NOT DISTINCT (ROLE_CODE, AREA_CODE, SCREEN_ID)`. 근거는 TD5 criteria
   "물리 인덱스·파티션·실제 제약명은 **구현 단계에서 확정**한다" 다. 컬럼은 그대로 762 다.

역할 마스터 분리를 도입기업에 제안한다.

### 또 하나 — D-46 모듈명 함정

`util/anchor.py` 의 모듈명과 `anchor()` 함수명이 겹쳐 `from util import anchor` 가 **함수로 해석**돼
`anchor.CONFIG_TYPE` 이 `AttributeError` 로 터졌다. 개발 3명이 똑같이 걸릴 함정이라
모듈을 **`util/clock.py`** 로 바꿨다. 함수명은 `anchor()` 그대로다.

### 지금 해야 할 것 (회전 5)

**웨이브 A 는 완전히 끝났다. 남은 것은 전부 웨이브 B·C 다 — 사용자 확인이 필요하다.**

확인이 오면: 개발1(입고·기준·시스템·데이터 15화면) · 개발2(대시보드·공정·출하·KPI 16화면) ·
개발3(AI 14화면) 을 §5 프롬프트로 기동한다. **ML 학습이 있는 개발3 회전은 단독**(§10-2).

확인이 없으면 아키텍트가 할 수 있는 것이 거의 없다. 남은 것:
1. `app/util/` 세션·속도제한(계정 5회/IP 20회)·보안헤더·CSP(외부 CDN 0)·CSRF (§10-12)
2. `app/auth.py` 골격 — 단 인증 본체는 개발1 몫이라 **시그니처만** 두고 넘긴다

### 알아둘 것

- **시드 계정 6개는 직무 계정**이다(`exec` `quality` `prod` `operator` `supplier` `admin`). 실명 없음(D-39).
  비밀번호는 **최초 1회만 출력**되고 재실행해도 바뀌지 않는다 — 잃어버리면 계정을 지우고 다시 시드한다.
- **`require_code()` 를 저장 전에 부른다**(D-32). DB 가 막아주지 않는 29컬럼이다.
- **`clock.anchor()` 를 쓴다.** `date.today()` 를 쓰면 §10-3 사고가 재현된다.
- 비운 코드 그룹 7종(D-47)에 값을 넣고 싶으면 **정본 근거를 먼저 찾는다.** 없으면 화면 입력으로 둔다.

---

## 2026-09-11 회전 5 — 보안 기반 (아키텍트 · 에이전트 0)

웨이브 B 확인 대기 중. §3.1 아키텍트 범위의 마지막 항목(세션·속도제한·보안헤더·CSRF 기반)을 했다.

### 게이트

```
PASS 5 · FAIL 1 · 차단 0 · 미구현 6  /  12      G-빌드 105 passed (88 → +17)
```

### 만든 것 — 직전 사업 사고를 처음부터 막는다(§10-12)

| 파일 | 역할 | 실측 검증 |
|---|---|---|
| `app/util/security.py` | 보안 헤더 6종 + **CSP `default-src 'self'`**. HSTS 는 **prod 에서만** | 렌더 결과에 `http://`·`https://` **0건** 단언 |
| `app/util/session.py` | 서명 쿠키 + **서버측 무효화** · 유휴 만료 · `destroy_user()`(계정 잠금 시 전 세션 차단) | 지운 세션의 쿠키가 **더 이상 안 먹힘** 확인 · 위조 쿠키 거부 |
| `app/util/ratelimit.py` | 계정 5회 / IP 20회 (10분 창). 성공 시 해제 | 계정·IP 한도가 **서로 독립**임 확인 |
| `main.py` 미들웨어 | 세션 → 역할. **prod 에서는 개발용 전환을 받지 않는다** | `prod` + `?as=SYSADMIN` → **403** 확인 |

| 헤더 | 값 |
|---|---|
| Content-Security-Policy | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` |
| X-Content-Type-Options / X-Frame-Options / Referrer-Policy / Cache-Control | `nosniff` / `DENY` / `same-origin` / `no-store` |

### 판단한 것

- **세션 테이블을 만들지 않았다**(D-48). TD5 68표에 없다 → G-01 은 68 고정이다. 저장소는 프로세스 메모리이고, **재기동하면 세션이 끊긴다**는 한계를 적어 두었다. 다중 워커로 가면 공유 저장소가 필요하다(사업계획서 4.7 에 ElastiCache 가 있다).
- **속도 제한 수치는 사업계획서에 없다**(D-49). 9.2 는 "비밀번호 복잡도·주기적 변경" 까지만 적었다. 직전 사업 교훈에서 온 값이므로 `가설 (D-16)` 배지를 화면 문구에 넣었다 — 목표가 없는 것을 있는 척하지 않는다.
- 잠금 문구가 `(가설 D-16)` 으로 나가 앱 전체 배지 형식 `가설 (D-16)` 과 어긋났다. 테스트가 잡아서 **`settings.Hypothesis.badge` 한 곳을 쓰도록** 통일했다.

### 지금 해야 할 것 (회전 6)

**아키텍트 범위(§3.1)가 끝났다.** `contracts/` 4종 · 스키마 생성기 · 공용 모듈 · RBAC · 오류 규약 ·
감사로그 훅 · `check_routes.py` · `gate.py` 가 전부 있다. **남은 것은 전부 웨이브 B·C 다.**

- 웨이브 B — 개발1(입고·기준·시스템·데이터 15화면) · 개발2(대시보드·공정·출하·KPI 16화면) · 개발3(AI 14화면)
- 웨이브 C — QA1(기능·계약) · QA2(데이터·수집) · QA3(AI·보안)

**사용자 확인 없이는 더 진행할 수 없다.** 다음 회전에도 확인이 없으면 루프를 멈추고 대기 상태로 보고한다 —
빈 회전을 반복하는 것은 토큰 낭비다.

### 알아둘 것

- **인증을 넣을 때(개발1) `main.py` 의 개발용 역할 전환 분기를 지운다**(D-40·D-51). prod 는 이미 막혀 있지만 dev 분기가 남아 있다.
- **외부 리소스를 하나라도 참조하면 테스트가 깨진다**(D-50). 폰트·아이콘·차트 라이브러리 전부 인라인이다.
- 세션은 **재기동하면 끊긴다**(D-48). 개발 중 로그인이 풀리면 버그가 아니다.
