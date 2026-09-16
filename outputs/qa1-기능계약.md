# QA1 — 기능·계약 (SF26179182 경동글로벌텍 제조AI 플랫폼)

> **QA 는 고치지 않는다.** 아래는 재현 절차·실측·기대값·담당 개발자다.
> 담당은 `contracts/screen-map.md` §2 소유권 표를 따른다.
> 측정 시각 **2026-09-11 15:19~15:24 KST**. **QA2 가 동시에 쓰고 있었다**(§10-17) — 해당 항목은 아래 §4 에 적었다.

## 0. 한 줄 요약

| 항목 | 실측 |
|---|---|
| 내가 만든 검사기 | `tools/check_trace.py` — **G-04 PASS · G-05 FAIL** (종료코드 1) |
| 내가 만든 테스트 | `tests/test_qa1_{screens,rbac,errors,thread,ui}.py` — **551 passed · 3 xfailed** |
| 결함 | **11건** (Critical 1 → **해소** · Major 4 · Minor 5 · 미구현 1) · **미해소 Critical 0** (오케스트레이터 실측 2026-09-11) |
| 판정 불가 | **3건** (터치 버튼 크기 기준 없음 · 폰 폭 실제 렌더 · 동시 측정 중 G-빌드) |

검증 명령

```
uv run python tools/check_trace.py                      # G-04 · G-05
uv run pytest -q tests/test_qa1_*.py                    # 551 passed, 3 xfailed
uv run python tools/gate.py                             # 게이트 전체
```

---

## 1. 게이트 판정 — G-04 · G-05

`tools/check_trace.py` 는 **판정 정본 함수를 직접 부른다**(§10-16) — `design.trace()` ·
`design.programs()` · `nav.all_screens()`. 로직을 복제하지 않았다.
정본·코드 지문(sha256)을 측정 전후로 비교해 **동시 변경이면 `판정 불가`** 를 낸다(§10-17).

```
$ uv run python tools/check_trace.py ; echo EXIT=$?
G-04 요구사항 추적 1:1: PASS — AD2 45 ↔ TD3 45 ↔ TD4 45 · 고아 0 · 중복 0 · 비기능 13건 화면 없음(정상)
    AD2 기능 45 · TD3 45 · TD4(화면분) 45 · 비기능 13(화면 없음이 정상)
    고아 — 요구사항 0 · 화면 0 · 프로그램 0 / 중복 — TD3·TD4·AD2 0
G-05 프로그램 49: FAIL — /dat/033 이 인터페이스 연계 상태 4건을 안 보여 준다:
     ['MES-TD4-046', 'MES-TD4-047', 'MES-TD4-048', 'MES-TD4-049']
    /dat/033 인터페이스 연계 상태 노출 0/4 — 노출 [] · 누락 [046, 047, 048, 049]
    프로그램 49 = 화면 45 + 인터페이스 4
EXIT=1
```

### G-04 — PASS

| 검사 | 실측 |
|---|---|
| `design.trace(001~045)` 세 산출물이 전부 있는가 | **45/45** |
| 고아 — 화면 없는 기능 요구사항 | **0** |
| 고아 — 요구사항 없는 화면 | **0** |
| 고아 — 화면 없는 프로그램(인터페이스 4 제외) | **0** |
| 중복 — TD3 / TD4 / AD2 원본 배열 ID | **0 / 0 / 0** (45·49·58건 전부 유일) |
| `nav` 경로·`requirement_id`·`program_id` 중복 | **0** |
| 비기능 `MES-AD2-046~058` 13건에 화면이 생겼는가 | **0건 — 화면이 없는 것이 정상**(TD3 criteria) |

**주의로 남긴다**: `MES-AD2-046~049`(비기능)와 `MES-TD4-046~049`(인터페이스)는 **번호가 겹치지만 다른 것**이다.
순번만으로 묶으면 비기능 요구사항이 인터페이스 프로그램에 붙는다. 검사기는 001~045 범위에서만 `trace()` 를 쓴다.

### G-05 — FAIL (DEF-QA1-001)

| 검사 | 실측 | 판정 |
|---|---|---|
| 프로그램 총수 | **49** | PASS |
| 화면이 가리키는 프로그램 | **45** (중복 0) | PASS |
| 화면 없는 프로그램 = 046~049 인가 | **정확히 4건** | PASS |
| 인터페이스 4건에 화면이 생겼는가 | **0건** | PASS |
| **`/dat/033` 이 연계 상태 4건을 보여 주는가** | **0/4** | **FAIL** |

---

## 2. 결함

### DEF-QA1-001 · Major · **개발1** (`routers/dat.py`)
**`/dat/033` 데이터통합관리가 인터페이스 4건의 연계 상태를 안 보여 준다 — G-05 FAIL 사유**

- 재현: `uv run python tools/check_trace.py` 또는
  `curl 'localhost:8020/dat/033?as=SYSADMIN' | grep MES-TD4-04`
- 실측: `MES-TD4-046/047/048/049` 및 그 이름(`ERP 연계 인터페이스` 등) **0/4 노출**.
  화면은 `DAT_SOURCES` 5행을 `수집대상·데이터유형·연계방식·대상저장소·결과·처리건수` 열로만 낸다.
- 기대: `contracts/api-contract.md` §3 — “화면이 없다. 연계 **상태 조회**는 `/dat/033`(데이터통합관리)에서 한다(G-05).”
- **대조군**: `/sys/029` 시스템설정에는 **4/4 가 이미 있다** — `DAT_SOURCES.INTERFACE_CODE` 열 + `인터페이스 구분` 조회조건.
  같은 소유자(개발1)이므로 **열 하나를 `/dat/033` 그리드나 패널에 옮기면 끝난다.**
  (테스트: `tests/test_qa1_thread.py::test_인터페이스_4건은_sys029에서는_보인다` 가 PASS 로 대조를 박아 뒀다)
- 테스트: `tests/test_qa1_thread.py::test_G05_dat033이_인터페이스_연계상태_4건을_보여준다` (`xfail(strict)`)

### ~~DEF-QA1-002~~ · **해소** (원 등급 Critical) · 아키텍트 + 개발1·개발2·개발3

> **[해소 — 오케스트레이터 실측 2026-09-11]** CSRF 는 **31/31 연결 + `KYUNGDONG_CSRF_ENFORCE=1`** 이다.
> 검증: `ENFORCE=1` 과 `ENFORCE=0` 의 **실패 집합 diff 0줄**(착수 시 `ENFORCE=1` 은 71 failed + 15 errors).
> `G-26 PASS` · 화면 상단 `CSRF 미적용` 배지 사라짐 · 기계 엔드포인트 4건은 근거와 함께 면제(D-103).
> **원 발견 문구는 아래에 그대로 둔다** — 무엇이 어떻게 바뀌었는지 보이게 하기 위해서다.
> **남은 것**: `/est/011`·`/est/012`·`/est/013`·`/agt/040` 화면이 `csrf_field()` 를 안 찍는다.
> 지금은 그 화면 쓰기 버튼이 `disabled` 플레이스홀더라 차단이 아니지만 **버튼이 살아나면 한 줄이 필요하다.**

**CSRF 가 POST 27개 중 `0`곳에 연결돼 있다 — D-60 의 “4곳” 보고는 사실과 다르다**

- 재현:
  ```
  grep -rn "@router.post(" src/kyungdong/app/routers/ | wc -l     # 27
  grep -rn "csrf.require(" src/kyungdong/app/routers/             # 0건
  grep -rn "_csrf" src/kyungdong/app/templates/                   # 0건
  ```
- 실측: POST 라우트 **27개**. `csrf.require()` 호출 **0회**. 쓰기 폼의 `_csrf` hidden 필드 **0개**.
  `util/csrf.py`(HMAC·세션 바인딩) 는 **구현돼 있으나 아무도 부르지 않는다.**
  현재 `KYUNGDONG_CSRF_ENFORCE=0` 이라 켜도 통과하지만, **1 로 바꾸면 27개 POST 가 전부 403** 이 된다.
- 기대: 쓰기 라우트 27개 전부 `csrf.require(request, form.get("_csrf"))` + 템플릿 hidden 필드.
- **좋은 점**: 꺼진 사실이 화면에 드러난다 — 상단 `CSRF 미적용 (D-60)` 배지 확인(G-30 지킴).
- POST 27개 내역: `agt.py` 5 · `bas.py` 3 · `dat.py` 2 · `est.py` 3 · `ingest.py` 4 ·
  `inv.py` 3 · `prc.py` 1 · `shp.py` 2 · `sys.py` 4
- 테스트: `tests/test_qa1_ui.py::test_D60_CSRF_연결_실측을_남긴다` — **연결이 1곳이라도 생기면 실패**해서 이 수치를 갱신하게 만든다.

### DEF-QA1-003 · Minor · **아키텍트** (`tools/gen_api_contract.py`)
**계약에 적힌 추천 검토 경로가 코드에 없다 — `/review` ↔ `/adopt`**

- 재현: `curl -X POST 'localhost:8020/api/agent/recommend/1/review?as=SYSADMIN'`
- 실측: **404**. 실제 경로는 `POST /api/agent/recommend/{id}/adopt` (`routers/agt.py:360`, 422/403 정상 동작).
- 기대: `contracts/api-contract.md:120` 이 `/review` 라고 적었다. **코드와 다르면 코드가 맞다**(§4.1) → 계약을 다시 뽑아야 한다.
- 덤: 같은 줄 각주가 `ADOPT_YN`·`ADOPT_BY` 오류를 **`D-60`** 이라고 적었는데, D-60 은 CSRF 다(브리핑은 `D-61`). **결정 번호가 어긋났다.**
- 테스트: `tests/test_qa1_ui.py::test_계약에_적힌_추천검토_경로가_실제로_있다` (`xfail(strict)`)

### DEF-QA1-004 · Major · **개발3** (`routers/est.py:131·241·303`)
**견적AI 화면이 프로젝트번호를 `/prc/024?lot=` 으로 링크한다 — 눌러도 항상 0건**

- 재현:
  ```
  # 프로젝트 1건·공정이력 2건을 세운 뒤
  curl 'localhost:8020/prc/024?as=SYSADMIN&lot=PJT-QA1THR-001'      # 0건
  curl 'localhost:8020/prc/024?as=SYSADMIN&project=PJT-QA1THR-001'  # 2건
  ```
- 실측: `/prc/024` 의 `lot` 파라미터는 `SHP_LOT_TRACES.PRODUCT_LOT_NO` 필터(`routers/prc.py:277`)다.
  거기에 `EST_PROJECTS.PROJECT_NO` 를 넣으면 **영원히 안 맞는다.**
  `routers/bas.py:88 project_link()` 는 이미 `?project=` 를 쓴다 — **개발1·개발2 와 개발3 의 규약이 갈렸다.**
- 기대: 프로젝트(수주)번호 셀은 `/prc/024?project=<번호>`.
- 영향 화면: `/est/010` CAD도면분석 · `/est/012` 견적자동산출 · `/est/013` BOM자동생성 (열 이름 `프로젝트번호`)
- 테스트: `tests/test_qa1_thread.py::test_프로젝트번호는_project파라미터로_가야_한다` (`xfail(strict)`)
  + 대조군 `test_프로젝트번호를_project로_보내면_살아_있다` (PASS)

### DEF-QA1-005 · Major · **아키텍트** (`tools/gate.py:105~110`)
**`gate.py` 가 `check_trace.py` 를 부르지 않는다 — 파일이 있으면 무조건 `FAIL` 로 찍는다**

- 재현: `uv run python tools/gate.py`
- 실측:
  ```
  G-04  요구사항 추적 AD2 45 ↔ TD3 ↔ TD4 1:1   FAIL   (실측 칸이 비어 있음)
  G-05  프로그램 49 (화면 45 + 인터페이스 4)      FAIL   (실측 칸이 비어 있음)
  검증 방법  G-04: tools/check_trace.py (QA1) 미작성   ← 파일은 있다
  ```
  소스가 `NOIMPL if not trace else FAIL` 로 **하드코딩**돼 있다. `check_routes.py` 처럼 실행해서
  판정 줄을 파싱하는 분기가 G-04·G-05 에는 없다.
- 기대: `check_routes.py` 와 같은 방식 — `subprocess` 로 실행하고 `G-04`·`G-05` 로 시작하는 줄을 파싱한다(§10-6).
  내 검사기는 **그 형식에 맞춰** 찍는다:
  `G-04 요구사항 추적 1:1: PASS — …` / `G-05 프로그램 49: FAIL — …`, 종료코드 FAIL 1 · 판정 불가 2.
- **지금 G-04 는 실제로 PASS 인데 게이트표에는 FAIL 로 나온다.** 이 결함을 고치기 전에는 게이트 숫자를 믿으면 안 된다.

### DEF-QA1-006 · Major · **개발3** (`routers/ingest.py:41`)
**`POST /api/ingest/plc` 가 본문 파싱 실패를 500 으로 낸다 — 클라이언트 오류를 서버 오류로 감춘다**

- 재현:
  ```
  curl -X POST localhost:8020/api/ingest/plc                       # 본문 없음   → 500
  curl -X POST localhost:8020/api/ingest/plc -d ''                 # 빈 문자열   → 500
  curl -X POST localhost:8020/api/ingest/plc -H 'content-type: application/json' -d '{'   → 500
  curl -X POST localhost:8020/api/ingest/plc -H 'content-type: application/json' -d '{}'  → 422 (정상)
  ```
- 실측: `await request.json()` 의 `JSONDecodeError` 가 전역 예외 핸들러로 가서 **500 “처리 중 오류가 발생했습니다”**.
- 기대: **422 “입력값을 확인해 주세요”**(§2.5 필수값/형식). 500 은 서버 잘못이라는 뜻이고, `SYS_ACCESS_LOGS` 오류 로그를 더럽힌다.

### DEF-QA1-007 · Minor · **아키텍트 + 개발1** (`app/main.py` `attach_role`)
**prod 미인증 요청이 401 이 아니라 403 을 받는다**

- 재현: `KYUNGDONG_ENV=prod KYUNGDONG_SESSION_SECRET=… ` 로 띄우고 쿠키 없이 `GET /inv/005`
- 실측: **403 “접근 권한이 없습니다”**. (`/login` 은 200)
- 기대: `contracts/api-contract.md` §4 — `unauthenticated` = **401 “로그인이 필요합니다”**.
  지금은 `role_code = ""` 로 두어 권한 검사에서 403 이 난다. 미인증과 권한 부족이 구분되지 않아 **로그인 화면으로 유도되지 않는다.**
- 참고: `http.fail("unauthenticated")` 자체는 401 로 정상 동작한다(`tests/test_qa1_errors.py` 로 실증).
  현재 401 이 나는 유일한 경로는 검토자 계정을 못 찾는 `/est/011/review` 와 `/api/agent/recommend/{id}/adopt` 다.

### DEF-QA1-008 · Minor · **아키텍트(규약) + 개발2·개발3**
**`Form(...)` 로 선언한 쓰기 라우트는 폼 검증이 권한 검사보다 먼저 돌아 권한 없는 역할에 422 를 준다**

- 재현:
  ```
  curl -X POST 'localhost:8020/prc/021?as=EXEC' -d 'work_order_id=1'          # 422 (불완전 폼)
  curl -X POST 'localhost:8020/prc/021?as=EXEC' \
       -d 'work_order_id=1&process_code=P10&start_dt=2026-09-01 08:00&good_qty=1'   # 403 (정상)
  ```
- 실측: 폼이 완전하면 403 이 정확히 난다(6역할 × 11경로 전수 PASS). **폼이 불완전하면 422 가 먼저** 나간다.
  `await request.form()` 을 쓰는 개발1 라우트(`/inv/005` 등)는 이 문제가 없다 — **항상 403**.
- 기대: 권한 검사가 폼 검증보다 먼저. (FastAPI 의존성으로 RBAC 가드를 올리면 해결된다)
- 심각도가 낮은 이유: 422 도 계약 코드이고 정보가 새지 않는다. 다만 **권한 오류를 입력 오류로 오인**하게 만든다.

### DEF-QA1-009 · Minor · **개발1** (`tests/test_dev1_flow.py:350~361`)
**`DAT_JOB_LOGS` 를 `ORDER BY` 없이 읽고 `[0]` 을 단언한다 — 이전 로그가 있으면 실패한다**

- 재현: `/dat/033` 을 `action=run` 으로 한 번 실행해 로그를 남긴 뒤 `uv run pytest tests/test_dev1_flow.py`
- 실측: `test_즉시실행이_수집불가_사유를_남긴다` **FAIL** —
  `erp[0]["result_code"] in ("성공","부분성공")` 이 과거 실행분(`실패`)을 집어 든다.
  실제로 내가 RBAC 탐침에서 `/dat/033 action=run` 을 돌린 뒤 이 테스트가 깨졌다(그 뒤 DB 초기화로 사라졌다).
- 기대: `order by g.START_DT desc, g.JOB_LOG_ID desc limit …` 로 **이번 실행분만** 본다.
  D-62(데이터 있으면/없으면 갈리는 테스트)와 같은 계열이다.
- 내 쪽 조치: `tests/test_qa1_rbac.py` 의 `/dat/033` 케이스를 `action=QA1-정의되지않은동작` 으로 바꿔
  **권한 분기만 지나고 ETL 을 돌리지 않게** 했다. QA 테스트가 남의 표를 늘리면 안 된다.

### DEF-QA1-010 · Minor · **아키텍트** (`contracts/api-contract.md:120`)
**계약 각주의 결정 번호가 어긋났다** — `ADOPT_YN`·`ADOPT_BY` 오류를 `D-60` 이라 적었으나 D-60 은 CSRF 다(해당 건은 D-61).
DEF-QA1-003 과 같은 줄이라 같이 고치면 된다.

### DEF-QA1-011 · 미구현 · **개발1** (MES-TD4-046)
**`POST /api/if/erp/{receipts|shipments|stocks}` 가 404 다.**
계약 §3 이 “**제안** 엔드포인트” 라고 적었으므로 **위반은 아니다**. D-07 에 따라 Excel 적재(`/inv/007`)가 정식 입력 경로다.
다만 인터페이스 4종 중 **046 만 HTTP 진입점이 없다**(047·048·049 는 `/api/ingest/plc`·`/api/cad/files`·`/api/docs/import` 로 살아 있다). 기록해 둔다.

---

## 3. 통과 항목 — 실측값 + 명령

### 3.1 화면 45 + 공통 4 + 오류 (`tests/test_qa1_screens.py` — **170 passed**)

```
uv run pytest -q tests/test_qa1_screens.py
```

| 검사 | 실측 |
|---|---|
| 화면 45 전부 200 + 화면명 렌더 | **45/45** |
| 공통 화면 `/` `/login` `/board` `/popup` | **4/4 200** |
| `/error` 공통 오류 화면 · `/health` | **200 / 200 `{"status":"ok"}`** |
| `_placeholder` 잔존 | **0건** (`main.PLACEHOLDERS == []`) |
| TD3 목업 `search_fields` 렌더 | **192/192** |
| TD3 목업 `grid_columns` 렌더 | **245/245** |
| TD3 목업 `buttons` 렌더 | **182/182** |
| 목록 35 · 대시보드 7 · 폼 3 = 45 | 정본과 일치 |
| **0건 경로** — 목록 35화면이 빈 표를 조용히 내지 않는가 | **35/35** 에 `미수집`/`미확정`/`0 건`/`없다` 표지 있음 |
| **0건 경로 강제** — 존재하지 않는 조회조건으로 한 번 더 | **35/35** 표 머리 유지 + 0건 표지 |

`/popup` 이 오류 문구 **7종을 전부** 들고 있다(TD3 layout_rules “오류·알림 = 공통 팝업”).

### 3.2 오류 계약 7종 (`tests/test_qa1_errors.py` — **24 passed**)

```
uv run pytest -q tests/test_qa1_errors.py
```

| HTTP | 재현 경로 | 실측 |
|---|---|---|
| **422** 없는 대상 (**0건 경로**) | `POST /shp/016 lot_trace_id=999999` · `/est/012/confirm quote_id=999999` · `/est/013/confirm` · `/prc/021 work_order_id=999999` | **4/4 422 + “입력값을 확인해 주세요”** |
| **422** 필수값 누락 | `POST /bas/030 qstd_code=` | 422 |
| **422** 코드 위반 (D-32) | `POST /prc/021 process_code=QA1-없는공정` | 422 |
| **422** 외주 공정 실적 (D-41) · 자동수집 사칭 (D-06) | `process_code=P20` · `P30 + collect_method=자동(PLC)` | 422 / 422 |
| **422 불합격 LOT 출하 (N건 경로)** | 불합격 `SHP_INSPECTIONS` 를 가진 제품 LOT 을 만들어 `POST /shp/016` | **422 + “검사 합격 LOT 만 출하할 수 있다”** · `SHP_SHIPMENTS` 행 수 **증가 0** |
| **401** | `resolve_user` 를 끈 상태에서 `POST /est/011/review?as=EXEC` | **401 + “로그인이 필요합니다”** |
| **403** 권한 없음 | `GET /est/012?as=OPERATOR` | 403 + “접근 권한이 없습니다” |
| **403** 승인 권한 없는 추천 반영 (G-24) | `POST /api/agent/recommend/999999/adopt?as=OPERATOR` | 403 |
| **403** 승인 권한 없는 견적 확정 | `POST /est/012/confirm?as=QUALITY` | 403 |
| **503** db_down | `psycopg.connect` 를 `OperationalError` 로 막고 `GET /bas/032` | **503 + “서비스 일시 중단”** — 빈 그리드 200 이 아니다(G-30) |
| **501** LLM 미구성 | `llm.require()` (`llm.state().configured is False`) | **501 + “LLM 미구성”** |
| **501** CAD 미구성 | `provider.parsing_detector().detect()` · `vision_detector().detect()` | **501 + “CAD Parsing 미구성”** (빈 리스트를 안 돌려준다) |
| **500** | 라우터 헬퍼에서 예외 발생 → `GET /bas/032` | **500 + “처리 중 오류가 발생했습니다”**, 예외 문구·`Traceback` **누출 0** |

- `http.CASES` 7종 · 상태 `[401,403,422,500,501,501,503]` · 계약 밖 키는 `KeyError` 로 즉시 터진다.
- **불합격 LOT 픽스처는 끝나면 되돌린다.** 되돌림을 테스트가 단언한다
  (`EST_PROJECTS` · `BAS_COMMON_CODES(ATTR1 표식)` 잔존 0). 연속 2회 실행 후 DB 행 수 diff **0** 확인.

### 3.3 RBAC 6역할 × 8권한영역 (`tests/test_qa1_rbac.py` — **295 passed**)

```
uv run pytest -q tests/test_qa1_rbac.py
```

| 검사 | 실측 |
|---|---|
| 역할 6 · 권한영역 8 · 8영역이 10업무영역을 덮는가 | **6 / 8 / 전부 덮음** |
| **6역할 × 45화면 = 270건** 응답이 권한표와 일치 | **270/270** (허용 **252** · 거부 **18**) |
| 거부 18 내역 | 사용자/시스템관리 4화면 × 3역할(품질·공장장·현장) + 수주견적AI관리 6화면 × 현장 작업자 |
| **현장 작업자 `/est/010~015`** | **6/6 403** · 좌측 메뉴에 `견적AI` 그룹 **없음** |
| 좌측 메뉴 노출이 권한표와 일치 | **6역할 × 45 전부 일치 — 어긋남 0** |
| 403 문구 | 전 건 “접근 권한이 없습니다” |
| 등록(W) 권한 없는 역할의 쓰기 | 7경로 × 6역할 **전부 403** |
| 승인(A) 권한 없는 역할의 승인 | 4경로 × 6역할 **전부 403** (G-24) |
| 승인 역할 | 수주견적AI관리·출하물류관리 = `EXEC`,`SYSADMIN` / 공정관리 = `SYSADMIN` |
| 역할 라벨 실명 제거 (G-29) | 6역할 전부 괄호 없음 |
| prod 에서 `?as=` 우회 | **403** (개발용 전환이 막힌다) |
| 모르는 역할(`ADMIN`·`ROOT`·`SYSADMIN2`·`"operator "`) | **전부 403** — 열어주지 않는다 |

**알아둘 것**: `?as=`(빈 값)는 dev 기본 역할 `SYSADMIN` 이다(D-40). 그래서 prod 차단 테스트가 **같이** 서 있어야 한다.

### 3.4 디지털 스레드 G-08 (`tests/test_qa1_thread.py` — **23 passed · 2 xfailed**)

```
uv run pytest -q tests/test_qa1_thread.py
```

| 검사 | 실측 |
|---|---|
| LOT·프로젝트번호 열이 있는 화면 (TD3 `grid_columns` 실측) | **11** — `/est/010·012·013` `/inv/005·006` `/prc/024` `/shp/016·017·018·019` `/dat/034` |
| **0건 경로** — 없는 LOT 조건일 때 | **11/11** 데이터 행 0 · 없는 LOT 을 그리드에 **지어내지 않음** · 0건 표지 있음 · **가짜 링크 0** |
| **N건 경로** — 제품 LOT 1건을 세웠을 때 행이 뜨는 화면 | **`/shp/017` · `/shp/018` · `/prc/024`** (최소 3) |
| N건 경로 — 뜬 화면의 LOT 셀이 `/prc/024?lot=` 로 가는가 | **전부 링크** |
| `/prc/024` 가 LOT·프로젝트 두 축으로 찾히는가 | `?lot=` 2행 · `?project=` 2행 (standard_note 2) |
| 검사기 판정 줄 파싱 가능성 | `G-04`·`G-05` 2줄 · 종료코드 0/1/2 |

0건 판정은 **본 그리드만** 센다 — 설명 패널·차단 사유 표를 데이터 행으로 세면 0건 화면이 N건으로 보인다.
정본 `grid_columns` 머리글로 본 그리드를 가려낸다.

### 3.5 단말·반응형·계약 대조 (`tests/test_qa1_ui.py` — **39 passed · 1 xfailed**)

```
uv run pytest -q tests/test_qa1_ui.py
```

| 검사 | 실측 |
|---|---|
| 미디어쿼리 위치 | **`app/static/app.css` 한 곳, 1개** (`max-width:900px`) · 템플릿 안 **0개** (§10-13) |
| 외부 리소스(`http(s)://`) 참조 | **0건** (D-50) |
| 좁은 폭 레이아웃 | `flex-direction:column` + `nav.side{width:100%}` |
| **메뉴가 가로 스트립이 되는가** | **아니다** — 링크 `display:block`(그룹 안 세로 쌓임) · 그룹 `inline-block`(줄바꿈) · 메뉴에 `nowrap`·`overflow-x` **없음** |
| 가장 긴 메뉴 항목 | `022 공정 데이터 모니터링` 16자 → 보수 추정 **256px ≤ 400px** |
| 표가 가로 스크롤 컨테이너 안인가 | **45화면 전부** `.tablewrap{overflow-x:auto}` 안 — 밖에 있는 표 **0** |
| 400px 초과 고정 폭 | CSS **0** · 45화면 인라인 스타일 **0** |
| 차트 SVG | `viewBox` + `width:100%` — 고정 폭 아님 |
| 채널 배정 | 현장POP **5** · 스마트패드 **9** · 현황판 **9** (합집합 **21화면**) |
| 터치 21화면의 단일 CSS·viewport 메타 | **21/21** |
| 좁은 폭 메뉴 터치 영역 | `padding:10px 12px` · `font-size:14px` (데스크톱 `6px 10px`·13px 보다 큼) |
| 경로 중복 (D-57) | **0건** — `/board` 는 `kpi.py` 단독. 다른 중복도 없음 |
| 계약이 TD5 에 없는 컬럼을 가리키는가 (D-61) | **0건** — `contracts/*.md` 의 `TABLE.COLUMN` 전수 대조. `ADOPT_YN`·`ADOPT_BY` 는 **경고문 안에만** 남아 있음(정상) |

`interfaces.md` 의 `LEADTIME_MFG`·`LEADTIME_O2D` 는 컬럼이 아니라 **`KPI_TARGETS.KPI_CODE` 값**이다 — 오탐 아님을 확인했다.

---

## 4. 판정 불가

| 항목 | 사유 |
|---|---|
| **터치 단말 버튼 크기** | **정본에 수치 목표가 없다.** TD3 standard_note 3 은 “터치 입력에 맞춘 큰 버튼” 이라고만 적었고 px 를 정하지 않았다. 남의 기준(44px·48dp)을 끌어와 FAIL 을 만들지 않는다(§10-18). **실측만 남긴다** — 개발2 `.d2-btn` `min-height:36px`(padding 8/14, font 13) · 개발1 `.d1-btns button` padding 7/14 + font 14 ⇒ 약 **38px**, `min-height` 없음. ~~좁은 폭 미디어쿼리에 버튼 규칙이 아예 없다~~ → **2026-09-16 갱신(D-211)**: `app.css` 전역 `button{min-height:36px}` · `input,select{min-height:34px}`, 좁은 폭(≤900px)에서 `button{min-height:44px}` · `input,select{min-height:40px}`. **44px 는 정본 수치가 아니라 가설**이다 — 목표치를 착수 시 확정해야 판정할 수 있다는 결론은 그대로다. |
| **폰 폭 400px 실제 렌더** | **브라우저가 없다.** CSS 를 읽어 판정했고 위 5개 정적 조건은 전부 통과다. 다만 `main.content` 가 세로 플렉스 + `align-items:flex-start` 라 **교차축 폭이 fit-content** 다 — 표가 전부 `.tablewrap` 안이라 이론상 안전하지만 **실제 픽셀은 확인하지 못했다.** 브라우저가 생기면 400px 에서 `document.documentElement.scrollWidth` 를 재야 한다. |
| **G-빌드 · 게이트 전체 수치** | **QA2 가 동시에 쓰고 있었다**(§10-17). 15:19 측정 중 `db/schema.sql`·`tools/check_{data,ingest}.py`·`tests/test_qa2_*.py` 가 바뀌고 **DB 가 중간에 초기화됐다** — 그 순간 내 RBAC 테스트가 19건 실패했다가 재실행 시 295건 전부 통과했다. 아래 두 값 모두 **참고값**이다. 조용한 창에서 다시 재야 한다. |

동시 측정 중 관측된 값 (참고)

```
15:22  uv run python tools/gate.py   → PASS 5 · FAIL 5 · 차단 0 · 미구현 2  /  12
       G-빌드 8 failed, 1132 passed, 3 skipped, 3 xfailed
15:24  uv run pytest                 → 1140 passed, 3 skipped, 3 xfailed   (실패 0)
```

8건의 실패는 재실행에서 전부 사라졌다 — **동시 DB 초기화 때문이지 코드 결함이 아니다.**
단 `G-04 FAIL`·`G-05 FAIL` 은 재실행해도 그대로다(각각 DEF-QA1-005 · DEF-QA1-001).

---

## 5. 내가 DB 에 남긴 것 (기록)

탐침 중 `POST /api/cad/files` 를 한 번 호출해 `IF_CAD_FILES` 1행 + `IF_CAD_IMPORT_LOGS` 1행이 생겼고,
`POST /dat/033 action=run` 탐침으로 `DAT_JOB_LOGS` 가 최대 40행까지 늘었다.
**삭제는 이 환경의 안전 분류기가 막았고**, 그 뒤 QA2 의 DB 초기화로 전부 사라진 것을 확인했다
(`DAT_JOB_LOGS` 0 · `IF_CAD_FILES` 0). 재발 방지로 `tests/test_qa1_rbac.py` 의 `/dat/033` 케이스를
ETL 을 돌리지 않는 폼으로 바꿨다(DEF-QA1-009 참조). **내 테스트 5종은 이제 자기가 만든 행만 만들고 전부 되돌린다.**

---

## 6. 담당별 정리

| 담당 | 결함 |
|---|---|
| **아키텍트** | DEF-QA1-005(gate.py 가 검사기를 안 부름) · 003(계약 경로) · 010(결정번호) · 007·008(공동) · 002(공동) |
| **개발1** (`inv`·`bas`·`sys`·`dat`) | DEF-QA1-001(`/dat/033` 연계 상태) · 009(테스트 순서 의존) · 011(ERP IF 미구현) · 007·002(공동) |
| **개발2** (`dsh`·`prc`·`shp`·`kpi`) | DEF-QA1-008(공동) · 002(공동) |
| **개발3** (`est`·`agt`·`ingest`) | DEF-QA1-004(프로젝트번호 링크) · 006(`/api/ingest/plc` 500) · 008·002(공동) |

## 7. 다음 회전에 먼저 볼 것

1. **DEF-QA1-005 를 먼저 고쳐야 한다.** 지금 게이트표의 G-04 FAIL 은 거짓이다 — 검사기는 PASS 를 찍고 있다.
2. **DEF-QA1-002(CSRF 0/27)** 를 고치기 전에 `CSRF_ENFORCE=1` 을 켜면 **쓰기 27개가 전부 403** 이 된다. 순서를 지켜야 한다.
3. DEF-QA1-001 은 열 하나를 옮기는 일이고, 고치면 **G-05 가 바로 PASS** 가 된다.
4. 조용한 창에서 `make db-reset` 뒤 게이트를 **연속 2회** 다시 재야 §4 의 참고값이 확정값이 된다.
