# progress-dev1.md — 개발1 (입고·기준·시스템·데이터 / 화면 15 · 테이블 23)

경동글로벌텍 제조AI 플랫폼 (SF26179182 · 공급기업 주식회사 재일)
**ETO 주문 설계·제작 고정밀 산업장비** — 반응기·교반기·진공건조기·누체필터·저장탱크.

> 이 문서의 숫자는 전부 **아래 검증 명령의 출력**이다. 명령 없이 적힌 숫자는 없는 것으로 친다.
> 측정 시각의 시간 앵커: `2026-09-10 09:00:00` (`SYS_CONFIGS` · §10-3, `date.today()` 미사용)

---

## 1. 채번 공표 — 개발2·개발3 이 그대로 쓴다

`BAS_COMMON_CODES` 그룹 **`LOT채번`** 이 런타임 정본이다(`ATTR1` = 형식, `ATTR2` = 적용 컬럼).
형식은 SF-TD3 목업이 쓴 **모양**을 따랐다. 목업의 `(예시)` **값**은 시드에 넣지 않았다.

| 코드 | 대상 | 형식 | 예 | 적용 컬럼 (G-08 단계) |
|---|---|---|---|---|
| `PROJECT_NO` | 프로젝트(수주)번호 | `PJ-YYYY-NNN` | `PJ-2026-001` | `EST_PROJECTS.PROJECT_NO` (1) |
| `DRAWING_NO` | 도면번호 | `DWG-{제품군3}-NNNN` | `DWG-RCT-0101` | `EST_CAD_DRAWINGS.DRAWING_NO` (2) |
| `MATERIAL_LOT_NO` | 자재 LOT | `LOT-YYMMDD-NN` | `LOT-260910-01` | `INV_MATERIAL_LOTS.LOT_NO` (4) |
| `RECEIPT_NO` | 입고번호 | `RC-YYYY-NNNN` | `RC-2026-0001` | `INV_RECEIPTS.RECEIPT_NO` |
| `WORK_ORDER_NO` | 작업지시번호 | `WO-YYYY-NNNN` | `WO-2026-0001` | `PRC_WORK_ORDERS.WORK_ORDER_NO` (5) |
| `PRODUCT_LOT_NO` | 제품 LOT | `PLOT-YYYY-NNN` | `PLOT-2026-011` | `SHP_LOT_TRACES.PRODUCT_LOT_NO` (7) |
| `SHIPMENT_NO` | 출하번호 | `SH-YYYY-NNNN` | `SH-2026-0001` | `SHP_SHIPMENTS.SHIPMENT_NO` (9) |

**제품군 3글자**(도면번호용) — 그룹 `제품군` 의 `ATTR2` 에 붙였다. **코드 행은 늘리지 않았다.**

| 코드 | 제품군 | 약어 |
|---|---|---|
| PG10 | 반응기 | `RCT` |
| PG20 | 교반기 | `AGI` |
| PG30 | 진공건조기 | `VDR` |
| PG40 | 누체필터 | `NFL` |
| PG50 | 저장탱크 | `RTK` |

일련번호는 **연도별**(`PJ`·`RC`·`WO`·`PLOT`·`SH`) 또는 **일자별**(`LOT`)로 끊는다.
런타임 채번은 `routers/inv.py` 의 `_next_receipt_no()` · `_next_lot_no()` 가 한 트랜잭션 안에서 한다.

```
검증:  uv run pytest tests/test_dev1_seed.py::test_채번규칙_7건이_LOT채번_그룹에_있다 \
                    tests/test_dev1_seed.py::test_제품군_약어가_5종_전부_붙었다 \
                    tests/test_dev1_flow.py::test_채번이_공표한_형식을_따른다
       → 3 passed
```

---

## 2. 검증 명령과 실측 (전부 직접 돌렸다)

```
uv run python db/seed_dev1.py          # 2회 실행 → 행 수 diff 0
uv run pytest -q
uv run python tools/check_routes.py
uv run python tools/gate.py
```

| 명령 | 실측 |
|---|---|
| `uv run python db/seed_dev1.py` ×2 | `BAS_COMMON_CODES 32 · SYS_CONFIGS 8 · DAT_SOURCES 5 · DAT_INTEGRATION_JOBS 5` — **두 번 다 같다(G-07 diff 0)** |
| `uv run pytest -q` | **407 passed** (전체 — 개발2·3 테스트 포함) / 그중 **개발1 150 passed** (`test_dev1_seed` 14 · `test_dev1_screens` 97 · `test_dev1_flow` 39) |
| `uv run python tools/check_routes.py` | `G-06 PASS` · `G-03-① 전 화면 200 (50개) PASS` · `G-03-② _placeholder 0건 PASS` · `G-03-③ FAIL — 소스 1건` (내 파일 아님 → §6) |
| `uv run python tools/gate.py` | `PASS 5 · FAIL 1 · 차단 0 · 미구현 6 / 12`. `G-01 68` · `G-02 762` · `G-빌드 407 passed` |

**개발1 화면 15건은 placeholder 에서 전부 빠졌다.**
`uv run pytest tests/test_dev1_screens.py::test_내_화면_15건이_placeholder에서_빠졌다` → passed

---

## 3. 화면 15건 — 전부 목업대로 렌더하고 실 데이터에 붙였다

`design.screen(sid)['mockup']` 의 `search_fields` · `grid_columns` · `buttons` · `description` 을
그대로 렌더한다. 공통 레이아웃은 `templates/bas/_list.html` **한 파일**이고(TD3 `layout_rules`:
조회조건 상단 ≤6 · 그리드 중앙 ≤7열 · 버튼 하단 · 설명 패널 우측), 미디어쿼리는 없다(§10-13).

| 경로 | 화면 | 읽는 표 | 쓰기 경로 | 현재 실측 |
|---|---|---|---|---|
| `/inv/005` | 입고관리 | `INV_RECEIPTS`·`INV_MATERIAL_LOTS`·`INV_SUPPLIERS`·`INV_STOCKS` | POST 입고 등록 (채번·D-32 검증·재고 반영·이력 적재, 1 트랜잭션) | 0건 → 미수집 |
| `/inv/006` | 원자재 이력조회 | `INV_MATERIAL_HISTORY`·`INV_MATERIAL_LOTS` | — (입고·투입이 쌓는다) | 0건 → 미수집 |
| `/inv/007` | 입고 데이터관리 | `INV_RECEIPTS`·`IF_ERP_RECEIPTS`·`DAT_QUALITY_CHECKS` | POST **Excel 적재**(D-07 정식 입력) · 정합성 검증 · ERP 재전송 | 0건 → 미수집 |
| `/inv/008` | 공급처 품질분석 | `INV_SUPPLIER_QUALITY`·`INV_SUPPLIERS`·`INV_RECEIPTS` | POST 평가산출(불량률 실측) | 0건 → 미수집 |
| `/sys/026` | 사용자 관리 | `SYS_USERS`·`SYS_ROLE_PERMISSIONS` | POST 사용자 등록(난수 1회 발급) | **6 건** |
| `/sys/027` | 로그 관리 | `SYS_ACCESS_LOGS`·`DAT_DOWNLOAD_LOGS` | POST 반출 이력 기록 | 런타임 누적 |
| `/sys/028` | 알림 설정 | `SYS_CONFIGS`(알림기준) | POST 알림 기준 등록 | **3 건** |
| `/sys/029` | 시스템 설정 | `SYS_CONFIGS`·`DAT_SOURCES`·`IF_DEVICE_REGISTRY` | POST 설정 등록 | **8 건** (장비 0건 → 미수집) |
| `/bas/030` | 품질기준 관리 | `BAS_QUALITY_STANDARDS` | POST 품질기준 등록(상·하한 역전 422) | 0건 → 미수집 |
| `/bas/031` | 작업표준관리 | `BAS_WORK_STANDARDS` | POST 작업표준 등록 | 0건 → 미수집 |
| `/bas/032` | 코드관리 | `BAS_COMMON_CODES` | POST 코드 등록(그룹 내 중복 422) | **32 건 / 7 그룹** |
| `/dat/033` | 데이터통합관리 | `DAT_SOURCES`·`DAT_INTEGRATION_JOBS`·`DAT_JOB_LOGS`·`DAT_QUALITY_CHECKS` | POST 즉시 실행 | **5 / 5 건**, 로그 0건 → 미수집 |
| `/dat/034` | 데이터조회 | `DAT_TIMESERIES`·`DAT_LAKE_OBJECTS`·`INV_MATERIAL_HISTORY` | — | 0건 → **미수집 (D-06)** |
| `/dat/035` | 데이터시각화 | `PRC_PERFORMANCES`·`EST_QUOTATIONS`·`EST_PROJECTS` | — (조회조건 없이 표출) | 카드 4 · 막대 6 · 전부 실측/미확정 |
| `/dat/036` | 데이터 다운로드 | `DAT_DOWNLOAD_LOGS`·`SYS_ROLE_PERMISSIONS` | POST 반출(권한 검증 → 이력) | 0건 → 미수집, 권한표 **24 행** |

`/inv/009`(입고 AI Agent)·`/dat/037`(AI학습 데이터관리)는 **건드리지 않았다** — 개발3 몫이다.
`uv run pytest tests/test_dev1_screens.py::test_009와_037은_내_것이_아니다` → passed

---

## 4. `contracts/db-schema.md` §7.1 판정 — 개발1 몫 2건

| 표 | **판정** | 근거 |
|---|---|---|
| `INV_MATERIAL_HISTORY` | **런타임 누적표다. 시드 대상 아님** → §7 로 옮긴다 | `HIST_TYPE` 이 입고/투입/반출/반입/출하다. 입고 저장이 첫 행(`입고`·공정 `P20 입고검사`)을 쓰고 이후 공정이 쌓는다. 시드가 이력을 만들면 실제 흐름 없이 LOT 매핑률(D-23 85%)이 조작된다 (D-102) |
| `INV_SUPPLIER_QUALITY` | **입고·검사 누적 집계다. 마스터가 아님** → §7 로 옮긴다 | TD5 `DEFECT_RATE` 비고가 '불합격÷납품×100' 이라고 산식을 못 박았다 = 파생값이다. `/inv/008` '평가산출' 이 `INV_RECEIPTS` 에서 실측 집계한다. 재실행해도 행이 늘지 않는다(upsert) (D-103) |

```
검증:  uv run pytest tests/test_dev1_seed.py::test_개발1_판정_2건이_적혀있다 \
                    tests/test_dev1_flow.py::test_입고가_원자재_이력을_남긴다 \
                    tests/test_dev1_flow.py::test_평가산출이_불량률만_실측하고_나머지는_비운다 \
                    tests/test_dev1_flow.py::test_평가산출은_두_번_돌려도_행이_늘지_않는다
       → 4 passed
```

---

## 5. 시드 — 넣은 것과 넣지 않은 것

### 5.1 넣은 것 (`db/seed_dev1.py`) — 전부 정본에 문장이 있다

| 대상 | 건수 | 정본 근거 |
|---|---|---|
| `BAS_COMMON_CODES` 그룹 `LOT채번` | **7** | 채번 공표 지시 (goal.md §5 개발1 · interfaces.md §9) |
| `BAS_COMMON_CODES` 그룹 `제품군` `ATTR2` | **5 행 갱신** | 도면번호 채번용 약어. 행은 늘리지 않았다 |
| `SYS_CONFIGS` 인터페이스설정 | **4** | SF-TD3-029 체크 "외부 인터페이스 4종(ERP 연계·IoT/PLC·CAD 파일·외부 표준문서)… EIF 로 별도 산정" + TD4-046~049 |
| `SYS_CONFIGS` 알림기준 | **3** | TD5 `ALERT_CONDITION` 비고 "설비 이상·납기 경고·품질 이상 임계값" |
| `DAT_SOURCES` | **5** | TD5 `SOURCE_NAME` 비고 "ERP/PLC/터치PC/CAD/외부문서" |
| `DAT_INTEGRATION_JOBS` | **5** | 수집대상 1건당 수집 작업 1건. `JOB_TYPE`·`TARGET_STORE` 는 TD5 비고 열거값 |

**비운 칸에도 근거가 있다** — 접속 주소·계정(정본에 없고 암호화 대상) · 알림 임계값(정본에 수치 없음) ·
수집 주기(사업계획서 미기재 D-06) · Cron·변환 규칙(정본에 없음). 전부 화면이 `미확정 (D-nn)` 을 렌더한다.

### 5.2 넣지 **않은** 것 — 17표. 0건이 정답이고 근거를 함께 남겼다

`db/seed_dev1.py` 의 `NOT_SEEDED` 가 정본이고 실행 출력이 그대로 찍는다.

- **런타임 전용 (G-11)** — `SYS_ACCESS_LOGS` · `DAT_JOB_LOGS` · `DAT_DOWNLOAD_LOGS` · `IF_ERP_RECEIPTS/SHIPMENTS/STOCKS`
- **검증 산출물** — `DAT_QUALITY_CHECKS` (달성률을 시드로 지어내면 G-09 가 무의미해진다)
- **수집 산출물 (개발3)** — `DAT_TIMESERIES`(D-06) · `DAT_LAKE_OBJECTS`(D-05)
- **정본이 "도입기업 제공" 이라고 적은 것** — `BAS_QUALITY_STANDARDS`(TD3-030 체크) · `BAS_WORK_STANDARDS`(TD3-031 체크)
- **차단 (D-101)** — `INV_SUPPLIERS` · `INV_MATERIAL_LOTS` · `INV_RECEIPTS` · `INV_STOCKS` → §6
- **판정 (D-102·D-103)** — `INV_MATERIAL_HISTORY` · `INV_SUPPLIER_QUALITY` → §4

```
검증:  uv run pytest tests/test_dev1_seed.py -q     → 14 passed
       uv run python db/seed_dev1.py                # 17종의 미시드 근거를 그대로 출력
```

---

## 6. 차단 — 입고 업무 데이터 시드 (D-101)

**막혔다. 지어내지 않고 차단으로 남긴다.**

`INV_MATERIAL_LOTS.ITEM_CODE` 는 **NOT NULL** 이면서 코드성 FK(그룹 `품목`)이고,
`MATERIAL` 은 그룹 `재질` 이다. 그런데 두 그룹은 **D-47 로 비어 있어야 한다**
("정본에 값이 없어 비운 것이다 · 채우지 마라 · 테스트가 비어 있음을 단언한다" —
`tests/test_arch_seed.py::test_정본에_없는_코드그룹은_비어있다`).

→ 유효한 자재 LOT 을 만들 수 없다 → `INV_RECEIPTS.LOT_ID`(NOT NULL)·`INV_STOCKS.LOT_ID`(NOT NULL)도
만들 수 없다 → `INV_SUPPLIER_QUALITY` 도 집계할 원천이 없다.
공급처는 목록이 정본에 없고 **45화면에 공급처 마스터 등록 화면 자체가 없다.**

정본도 같은 말을 한다 — SF-TD3-005 체크: *"현행 입고 데이터는 Excel 약 1천개와 종이 MTC로 관리되어
**초기 이관 범위를 착수 시 확정해야 한다.**"*

**그래서 시드 0건이 정답이라고 판정했고, 대신 실제 유입 경로를 전부 만들었다:**

1. `/bas/032` 코드관리에서 품목·재질 코드를 등록한다 (화면 입력 마스터 — D-47 의 원래 의도).
2. `/inv/005` 입고 등록 또는 `/inv/007` **Excel 적재**(D-07 정식 입력)로 업무 데이터가 들어온다.
3. Excel 적재는 공급처가 없으면 만들고, 품목·재질을 `require_code` 로 검증해 **실패 행을 적재하지 않고**
   `IF_ERP_RECEIPTS` 에 사유를 남긴다.

**N건 경로는 `tests/test_dev1_flow.py` 가 실제 쓰기로 통과시킨다**(39 passed) — 코드 등록 → 입고 등록 →
채번·재고·이력 확인 → Excel 적재(성공·실패 각 1행) → 정합성 검증 → 평가산출 → 반출 이력.
테스트가 만든 행은 PK 워터마크로 전부 되돌리므로 D-47 단언이 깨지지 않는다.

> **도입기업에 필요한 것**: 품목·재질·보관위치 코드 목록과 공급처 목록(상호·공급구분).
> 이것이 들어오면 시드 없이 화면·Excel 로 즉시 적재된다.

---

## 7. 게이트별 자기 판정

| 게이트 | 내 범위 판정 | 근거 |
|---|---|---|
| G-03 화면 200 · placeholder 0 | **PASS** | `check_routes.py` — 내 15화면 전부 200, placeholder 0건 |
| G-03 타 사업 용어 0 | **PASS (내 파일)** | `test_개발1_소스와_화면에_타사업_용어가_없다` — 라우터 4 · 시드 · 렌더 15화면 모두 0건. 남은 1건은 `app/util/security.py`(아키텍트) → `decisions-dev1.md` D-104 |
| G-07 시드 멱등 | **PASS** | `seed_dev1.py` ×2 행 수 diff 0 |
| G-11 빈 표·조용한 빈칸 | **PASS** | 0건 그리드 미수집 · **건수 카드 `0 건` 에는 문구 없음**(§10-14) 단언 |
| G-28 RBAC | **PASS** | 품질담당 → `/sys/*` 403 · 경영자 쓰기 403 · 모르는 역할 403 |
| G-29 개인정보·감사 | **PASS** | 사용자명/연락처/이메일/담당자/IP 마스킹 · 화면조회 `SYS_ACCESS_LOGS` · 반출 `DAT_DOWNLOAD_LOGS` 분리 · 난수 1회 발급 · 저장소 리터럴 0 |
| G-30 조용한 실패 | **PASS** | 라우터에 `except Exception`·`return []` 0건 · 미구현은 "미구현" 이라고 렌더 · 저장형 XSS 이스케이프 |
| G-08 디지털 스레드 | **부분** | 내 구간(자재 LOT → 이력 → 제품 LOT)은 붙었고 LOT 열은 `/prc/024` 로 간다. 전 구간 판정은 QA2 `check_data.py` 몫 |
| D-32 코드성 FK | **PASS** | 저장 전 `require_code` — 품목·재질·제품군·검사구분·공정 위반 시 422 |

**미구현이라고 적은 것** (조용히 성공한 척하지 않았다): 삭제 · 엑셀 파일 생성 · 비밀번호 초기화 ·
임베딩 등록(개발3 TD4-049) · 테스트 발송 · 연계 테스트(D-07 실 연동 범위 밖).

---

## 8. 아키텍트에게 — 계약 확인·요청

1. `contracts/interfaces.md` §5 의 `validate_code` · `mask` · `anchor` · `audit` 는 **코드에 이미 있고 그대로 썼다.**
   다만 `util/__init__.py` 가 `audit` 를 *함수*로 재노출해서 `from ..util import audit` 는 모듈이 아니라 함수다 —
   `from ..util.audit import audit` 로 써야 한다. 문서에 한 줄 있으면 좋겠다.
2. `require_code(표, 컬럼, 값)` 시그니처는 `contracts/interfaces.md` §5 에 없다(`validate_code` 만 있다).
   실제 코드에 있고 내가 쓰는 것은 `require_code` 다 — 문서에 추가를 요청한다.
3. **CSRF 토큰 발급·검증 경로가 없다**(`settings.csrf_enforce=1` 인데 검증하는 코드가 없다).
   내 POST 11개는 전부 폼 전송이다. 아키텍트가 공통 미들웨어로 넣어 주면 라우터 수정 없이 붙는다 → D-105.
4. `app/auth.py`(인증)는 interfaces.md §9 에서 내 몫으로 적혀 있으나 **이번 회전에 못 했다** → §9.

---

## 9. 못 한 것 (완료라고 적지 않는다)

| 항목 | 상태 | 이유 |
|---|---|---|
| `app/auth.py` 인증 (bcrypt/Argon2 로그인·로그아웃) | **미착수** | 15화면 + 쓰기 경로 + 시드 + 테스트를 먼저 끝냈다. `main.py` 의 역할 전환 미들웨어(D-40) 제거는 인증이 들어온 뒤다. `util/session.py`·`ratelimit.py`·`security.py` 는 이미 있어 붙이기만 하면 된다 |
| 엑셀 **다운로드** 파일 생성 (005·006·007·008·030·031·032·033·034·036) | **미구현** | 화면에 "미구현" 이라고 적었다. 반출 **이력**(`DAT_DOWNLOAD_LOGS`)과 권한 검증은 동작한다 |
| 삭제(030·031·032·026·028·029) · 비밀번호 초기화(026) | **미구현** | 삭제는 FK 영향 범위를 QA2 정합성 판정과 맞춘 뒤에 붙이는 것이 맞다 |
| 032 코드 **수정**(저장) | **미구현** | 등록·중복 검증까지만 했다 |
| `/inv/007` 표준화 규칙 (2.7.3 재질·두께·길이·중량 단위 변환) | **미구현** | 변환 규칙 표가 정본에 없다 → `DAT_INTEGRATION_JOBS.TRANSFORM_RULE` 을 비워 뒀다. 규칙이 오면 붙인다 |
| 현장POP·스마트패드 전용 터치 레이아웃 | **부분** | `app.css` 의 900px 미디어쿼리(아키텍트 소유)에 기대고 있다. 내 CSS 에는 미디어쿼리를 넣지 않았다(§10-13) |

---

## 10. 소유 파일

```
src/kyungdong/app/routers/{inv,bas,sys,dat}.py      # bas.py 에 4모듈 공통 헬퍼
src/kyungdong/app/routers/__init__.py               # 패키지 선언 (소유자 미지정이라 내가 만들었다)
src/kyungdong/app/templates/bas/_list.html          # 15화면 공통 레이아웃 (미디어쿼리 없음)
db/seed_dev1.py
tests/test_dev1_{seed,screens,flow}.py
progress-dev1.md · decisions-dev1.md
```

`app/main.py` 는 건드리지 않았다. 라우터 등록은 `SCREENS` 규약만 썼다.
`app/static/app.css` · `db/{schema.sql,seed.py,conn.py}` · `app/util/*` 도 건드리지 않았다.
