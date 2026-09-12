# progress-dev2.md — 개발2 (대시보드·공정·출하·KPI / 16화면 · 15표)

경동글로벌텍 제조AI 플랫폼 (SF26179182 · 공급기업 주식회사 재일)
회전 기준일: **시간 앵커 2026-09-10 09:00:00** (`SYS_CONFIGS.TIME_ANCHOR` · `date.today()` 미사용)

---

## 1. 채번 — 개발1 공표값을 그대로 쓴다

개발1 이 `BAS_COMMON_CODES` 코드 그룹 **`LOT채번`** 에 공표했다. `db/seed_dev2.py` 는
`numbering()` 으로 **DB 에서 읽는다** — 코드에 형식을 박아 두지 않는다(D-200).

| 코드 | 형식 | 개발2 사용 |
|---|---|---|
| `WORK_ORDER_NO` | `WO-YYYY-NNNN` | `PRC_WORK_ORDERS.WORK_ORDER_NO` |
| `PRODUCT_LOT_NO` | `PLOT-YYYY-NNN` | `SHP_LOT_TRACES.PRODUCT_LOT_NO` |
| `SHIPMENT_NO` | `SH-YYYY-NNNN` | `SHP_SHIPMENTS.SHIPMENT_NO` · `/shp/016` 등록 |

착수 시점에 `progress-dev1.md` 가 없어 TD3 목업 `grid_sample` 형식을 임시로 썼는데
공표값과 **완전히 일치**했다. 코드가 없으면 목업 형식으로 되돌린다(fallback).

---

## 2. KPI — `app/kpi.py` 단일 소스 (가장 중요한 일)

`src/kyungdong/app/kpi.py` **한 파일**에 산식이 있고 대시보드 001~004 · 현황판 `/board` ·
KPI 043~045 · `db/seed_dev2.py` 가 **전부 같은 함수**를 부른다.

| 코드 | 지표 | 기존 | 목표 | 감소율 | 가중치 | 구간 |
|---|---|---|---|---|---|---|
| `LEADTIME_MFG` | 제조 리드타임 | **1,320 h** | **1,080 h** | **−18.2 %** | 0.5 | `PRC_WORK_ORDERS.CONFIRM_DT` ~ `SHP_SHIPMENT_ITEMS.PACKING_DT` |
| `LEADTIME_O2D` | 수주출하 리드타임 | **1,440 h** | **1,200 h** | **−16.7 %** | 0.5 | `EST_PROJECTS.ORDER_CONFIRM_DT` ~ `SHP_SHIPMENTS.SHIP_DT` |

- **감소율은 계산값이다.** `improve_rate(base, target) = round((base−target)/base*100, 1)`.
  18.2 / 16.7 을 상수로 박지 않았고 테스트가 독립 재계산으로 단언한다.
- 측정근거 `MEASURE_BASIS` = 2025년 생산 일지(수주출하는 3개월분).
- **표본 0건이면 `None`** 이고 화면은 `—` + `미수집` 을 렌더한다. 0.0 으로 메우지 않는다(G-11).
- 달성률 산식은 정본에 없어 개발2가 정했다 — `(기존−측정)÷(기존−목표)×100`, **가설 D-202**.
  화면에 산식을 함께 띄운다.
- **`/kpi/044` 품질 KPI 는 공식 성과지표가 아니다.** `kpi.QualityKpi.official = False`,
  화면 상단에 `공식 성과지표 아님` 배지 + 사유 문장을 띄운다(TD3 common_screens dashboard checks).

---

## 3. `contracts/db-schema.md` §7.1 "시드 여부 미정" 판정 — 개발2 몫 3건

| 표 | 판정 | 근거 |
|---|---|---|
| `PRC_PROCESS_HISTORIES` | **시드 대상** — 공정실적 시드와 함께 채운다 | 024 공정이력조회가 LOT 축 중심 화면이고 G-08 사슬 6~7단계 사이를 잇는다. 외주 구간(소재가공·버핑)의 `OUTSOURCE_STEP` 반출/반입과 `HIST_STATUS` 단절도 여기서만 드러난다(D-41). `seed_dev2._seed_histories()` |
| `PRC_CONDITION_DEVIATIONS` | **런타임 파생 — 시드 안 한다** (§7 로 이동 대상) | 표준 조건(`PRC_STD_CONDITIONS`)과 실측(`PRC_ACTUAL_CONDITIONS`)의 비교로만 나온다. 그런데 **표준 조건 초기값이 도입기업 미제공**이다(TD3 023 제약사항 → **D-203**). 표준이 없으면 편차도 없다. 023 화면은 `미확정 (D-203)` |
| `SHP_CLAIM_CAUSES` | **런타임 전용 — 시드 안 한다** (§7 로 이동 대상) | 클레임 접수·원인분석 화면(019)에서 쌓인다. 초기 클레임 이력이 문서로만 존재한다(TD3 019 제약사항). `CLAIM_TYPE`·`CUSTOMER_CODE` 가 D-47 로 비워 둔 코드 그룹을 참조해 시드가 성립하지도 않는다 → **D-204** |

덧붙여 `PRC_STD_CONDITIONS` · `PRC_ACTUAL_CONDITIONS` 도 같은 이유로 **시드하지 않는다**(D-203),
`PRC_EQUIP_SIGNALS` 는 표 접두는 `PRC_` 지만 **수집 경로(개발3 ingest)가 채운다**(D-207).

---

## 4. 산출물 — 실측

### 4.1 화면 16 + 현황판 = **17 경로 전부 200**

| 경로 | 화면 | 특징 |
|---|---|---|
| `/dsh/001` | 생산현황 분석 | 카드 4(금일 실적수량·진행 작업지시·설비 가동률·지연 프로젝트) · 공정별 생산량 인라인 SVG · 프로젝트별 진행률 |
| `/dsh/002` | 품질현황 분석 | 검사·불량 집계 · 기간별 불량 추이 · 공정별 불량 비중 |
| `/dsh/003` | 설비상태 모니터링 | **수집 지점 `2 개소` 고정 카드** · 수집 중단 배지(G-12) · "설비 예지보전 AI는 본 사업 범위 밖" 명시 |
| `/dsh/004` | 출하현황 분석 | 출하 예정/완료/지연 · 납기 준수율(OTD_YN) · 납기 임박 프로젝트 |
| `/prc/021` | 공정실적관리 | 조회 5/6 + **실적 등록 POST** · 자동/수동 구분 |
| `/prc/022` | 공정 데이터 모니터링 | `PRC_EQUIP_SIGNALS` 속도·압력·전류·온도 · 수집 범위 배지 |
| `/prc/023` | 작업조건관리 | 표준조건 0건 → **`미확정 (D-203)`** |
| `/prc/024` | 공정이력조회 | **디지털 스레드 도착지.** `?lot=` `?project=` 로 9단계 사슬 패널 표시 |
| `/prc/025` | 공정데이터 분석 | 공정별 평균 체류시간·불량률·**병목 판정** |
| `/shp/016` | 출하관리 | **출하 등록(422 통제) + 출하 확정(403 통제)** |
| `/shp/017` | LOT추적관리 | **매핑 성공률** 카드 + 목표 85% 대비(D-23) |
| `/shp/018` | 검사결과관리 | 수압·기밀·진공 · 출하 가능 LOT 카드 |
| `/shp/019` | 클레임분석 | 0건 → **`미수집 (D-204)`** |
| `/kpi/043` | 생산성 KPI 조회 | 확정값 4카드 + 실측/달성률 2카드 + 공식 지표 2종 표 |
| `/kpi/044` | 품질 KPI 조회 | **`공식 성과지표 아님` 구분 표기** |
| `/kpi/045` | KPI 관리 | `KPI_TARGETS` 그리드 + `KPI_MEASURES` 실적표 |
| `/board` | 현황판 65" 2대 | 조회조건 없음 · `meta refresh` 자동 갱신 · 품질 지표는 비공식으로 분리 |

- **차트는 전부 인라인 CSS/SVG** 다. 렌더 결과에 `http://`·`https://` **0건**(D-50) — 테스트가 단언.
- 개발2 템플릿(19개)에 **미디어쿼리 0건**(§10-13) · `|safe` **0건**(§10-8) — 테스트가 단언.
- TD3 목업의 `grid_columns` · `search_fields` · `buttons` 를 **전부** 렌더하고, 동작하지 않는
  조회 조건·버튼은 `disabled` 로 두어 **미지원을 숨기지 않는다**.
- 렌더 결과에 `(예시)` **0건** — 목업 예시 값을 화면에도 시드에도 넣지 않았다.

### 4.2 디지털 스레드 (G-08)

LOT·프로젝트번호 셀은 **전 화면에서** `/prc/024?lot=…` · `/prc/024?project=…` 로 간다
(001 · 004 · 017 · 018 · 019 · 021 · 024 · 016 · `/board` 납기 리스크).
024 는 9단계를 표로 보여 주고 **끊긴 단계는 `단절` 로 그대로 드러낸다** — 채워 넣지 않는다.

### 4.3 출하 통제 (G-24) — 실측 확인

| 상황 | 기대 | 실측 |
|---|---|---|
| 검사 **불합격** LOT 출하 등록 | 422 | 422 · "검사 합격 LOT 만 출하할 수 있다" |
| 검사 **자체가 없는** LOT 출하 등록 | 422 | 422 · "출하검사 결과가 없다" |
| 현장 작업자(OPERATOR)가 출하 확정 | 403 | 403 (출하물류관리 RW · A 없음) |
| 시스템 관리자가 출하 확정 | 303 + 기록 | `SHIP_DT` = 시간 앵커 · `APPROVER_ID` 기록 · `SHIP_STATUS='완료'` · `OTD_YN` 산출 |
| 확정된 출하를 다시 확정 | 422 | 422 |
| 총괄PM(EXEC)이 공정실적 등록 | 403 | 403 (공정관리 R) |
| 레이저커팅 외 공정에 `자동(PLC)` | 422 | 422 · "자동 수집은 레이저커팅 1공정(P40)뿐이다" |
| 외주 2공정 실적 등록 | 422 | 422 · "발주·반출·반입 상태 관리다 (D-41)" |

### 4.4 시드 — `db/seed_dev2.py`

```
시간 앵커        2026-09-10 09:00:00
채번(개발1 공표)   WORK_ORDER_NO=WO-YYYY-NNNN · PRODUCT_LOT_NO=PLOT-YYYY-NNN · SHIPMENT_NO=SH-YYYY-NNNN
KPI 목표         2 건   · KPI 실적 0 건
```

| 표 | 행 수(현재) | 비고 |
|---|---|---|
| `KPI_TARGETS` | **2** | 사업계획서 1.5 확정값. 두 번 돌려 **diff 0** |
| `KPI_MEASURES` | 0 | 표본 0건 — 정상(G-11) |
| `PRC_EQUIP_SIGNALS` | 6 | **개발3 수집 경로가 채웠다.** 개발2는 넣지 않는다(D-207) |
| 나머지 12표 | 0 | **차단 — 아래 §5** |

시드 출력 자체가 `차단·미시드` 절에 **사유를 전부 인쇄**한다. 조용히 건너뛰지 않는다.

### 4.5 N건 경로 실측 (`tests/test_dev2_chain.py`)

개발1·개발3 의 전제가 아직 0건이라 **테스트가 전제를 임시로 세우고 끝나면 되돌린다**
(프로젝트 2건 · 품질기준 3건 · 고객사·품목 코드 2건 → 검증 후 전량 삭제, 삭제도 단언).
이 상태에서 `seed_dev2.seed_chain()` 을 **그대로** 돌린 결과:

| 표 | 행 수 |
|---|---|
| `PRC_WORK_ORDERS` | 14 (프로젝트 2 × 제조공정 7) |
| `PRC_PERFORMANCES` | 10 (외주 2공정 제외 — 5공정 × 2) |
| `PRC_PROCESS_HISTORIES` | 14 |
| `SHP_LOT_TRACES` | 2 |
| `SHP_INSPECTIONS` | 6 (LOT 당 수압·기밀·진공) |
| `SHP_SHIPMENTS` / `SHP_SHIPMENT_ITEMS` | 2 / 2 |

KPI 실측 (독립 재계산과 일치 — SQL 이 준 구간을 파이썬에서 다시 평균냈다):

| 코드 | 표본 | 측정값 | 달성률 | 목표 대비 |
|---|---|---|---|---|
| `LEADTIME_MFG` | 2 | **1,175.0 h** | 60.4 % | 기존 1,320 → 목표 1,080 사이 |
| `LEADTIME_O2D` | 2 | **1,285.0 h** | 64.6 % | 기존 1,440 → 목표 1,200 사이 |

품질(비공식): 검사 6건 · 합격 6건 · 합격률 **100.0 %** · 공정 불량률 **0.0 %** · 클레임 발생률 **0.0 %**.
**`/kpi/043` · `/kpi/045` · `/board` 가 같은 문자열(`1,175.0 h` · `1,285.0 h`)을 렌더**하는 것을
테스트가 단언한다 — 산식이 한 곳에 있다는 증거다.

`seed_chain()` 을 두 번 돌려 7개 표 행 수 **diff 0**(멱등 G-07).

### 4.6 테스트

| 파일 | 건수 | 무엇 |
|---|---|---|
| `tests/test_dev2_kpi.py` | 16 | 확정값 · 감소율 독립 재계산 · **0건 경로 `None`** · 화면 3곳 값 일치 |
| `tests/test_dev2_screens.py` | 112 | 16화면+현황판 200 · RBAC 403 · 422 · **빈 그리드 문구 / 건수 카드 `0 건`** · CDN 0 · 미디어쿼리 0 · TD3 목업 항목 일치 |
| `tests/test_dev2_chain.py` | 24 | **N건 경로** · 멱등 · 디지털 스레드 · KPI 독립 재계산 · 출하 통제 |
| **합계** | **152** | 전건 통과 |

0건 경로와 N건 경로를 **둘 다** 단언한다. `skip` 0건.

---

## 5. 차단 — 못 한 것은 못 했다고 적는다

| # | 차단 | 누구 | 풀리면 |
|---|---|---|---|
| 1 | **`EST_PROJECTS` 0건** — 프로젝트(수주)번호가 G-08 최상위 키라 공정·LOT·검사·출하 시드 전부가 여기 걸린다 | 개발3 `db/seed_dev3.py` | `uv run python db/seed_dev2.py` 재실행만 하면 사슬 전체가 채워진다(§4.5 가 그 경로를 실증했다) |
| 2 | **`BAS_QUALITY_STANDARDS` 0건** — `SHP_INSPECTIONS.QSTD_ID` 가 NOT NULL 이라 검사 결과를 만들 수 없고, 검사가 없으면 출하도 없다 | 개발1 | 위와 같다. 검사 항목명·단위는 **기준 데이터에서 읽는다**(지어내지 않는다) |
| 3 | **`고객사`·`품목` 코드 그룹 0건**(D-47) — `SHP_SHIPMENTS.CUSTOMER_CODE` · `SHP_SHIPMENT_ITEMS.ITEM_CODE` 가 NOT NULL 코드성 FK다 (**D-206**) | 개발1/도입기업 | 프로젝트가 이미 그 코드를 쓰므로 개발3 시드 시점에 함께 풀린다 |
| 4 | **표준 작업조건 미제공**(D-203) — 023·025 편차 분석이 성립하지 않는다 | 도입기업 | 표준 조건표 수령 후 023 에서 등록 |
| 5 | **클레임 초기 이력 없음**(D-204) — 019 분석 신뢰도는 누적 후에 확보된다 | 도입기업 | 019 등록 화면은 다음 회전 |
| 6 | ~~`tools/check_routes.py` G-03-③ FAIL 1건 (`app/util/security.py:3`)~~ → **해소됨.** 아키텍트가 고쳤고 재실측 `G-03-③ PASS — 렌더 0건 · 소스 0건` (D-208) | — | — |

### 이번 회전에 만들지 않은 것 (의도적)

- **019 클레임 등록·원인분석 POST** — 코드 그룹이 비어 있어 저장이 422 로만 끝난다(D-204). 조회만 만들었다.
- **023 표준조건 등록 POST** — 표준값 정본이 없다(D-203). 조회만 만들었다.
- **엑셀 다운로드·삭제·목표대비 비교 버튼** — 버튼은 TD3 목업대로 그리되 `disabled` + 사유 툴팁이다.
  `DAT_DOWNLOAD_LOGS` 반출 통제(9.2 ①)는 개발1 `/dat/036` 소관이라 중복 구현하지 않았다.
- **CSRF 토큰** — `settings().csrf_enforce` 는 있으나 `contracts/interfaces.md` 에 토큰 발급·검증
  시그니처가 공표되지 않았다. 아키텍트가 공표하면 POST 3개(`/prc/021` · `/shp/016` · `/shp/016/approve`)에 붙인다.

---

## 6. 검증 — 보고 전에 직접 돌린 명령과 실측

```
$ uv run python db/seed_dev2.py          # 두 번 돌려 행 수 diff 0 · 출력 diff 0
KPI_TARGETS 2 → 2 · KPI_MEASURES 0 → 0

$ uv run pytest
525 passed, 4 warnings in 13.9s          # 전체 (개발2 몫 152건)

$ uv run pytest tests/test_dev2_kpi.py tests/test_dev2_screens.py tests/test_dev2_chain.py
152 passed

$ uv run python tools/check_routes.py
G-06 메뉴 10영역 단일 소스: PASS
G-03-① 전 화면 200 (50개): PASS
G-03-② _placeholder 0건: PASS — 현재 0건
G-03-③ 타 사업 용어 0건: PASS — 렌더 0건 · 소스 0건
판정: PASS

$ uv run python tools/gate.py
G-01 테이블 68 PASS · G-02 컬럼 762 PASS · G-03 PASS · G-06 PASS · 정본 PASS · G-빌드 PASS(525)
G-04·G-05·G-07~G-30 미구현 (QA1·QA2·QA3 검사기 미작성 — 개발2가 만들지 않는다)
PASS 6 · FAIL 0 · 차단 0 · 미구현 6 / 12
```

---

## 7. 소유 파일

```
src/kyungdong/app/kpi.py                        KPI 산식 단일 소스
src/kyungdong/app/routers/dsh.py                001~004 + 개발2 공용 헬퍼 (D-209)
src/kyungdong/app/routers/prc.py                021~025
src/kyungdong/app/routers/shp.py                016~019  (020 은 개발3 — 건드리지 않았다)
src/kyungdong/app/routers/kpi.py                043~045 + /board (D-205)
src/kyungdong/app/templates/dsh/_kit.html       공용 매크로 · 인라인 SVG 차트
src/kyungdong/app/templates/dsh/001~004.html
src/kyungdong/app/templates/prc/021~025.html
src/kyungdong/app/templates/shp/016~019.html
src/kyungdong/app/templates/kpi/_official.html  공식 성과지표 2종 표 (043·044·045·board 공용)
src/kyungdong/app/templates/kpi/043~045.html
src/kyungdong/app/templates/board.html          현황판 65" 2대
db/seed_dev2.py
tests/test_dev2_{kpi,screens,chain}.py
progress-dev2.md · decisions-dev2.md
```

**`app/main.py` 를 건드리지 않았다.** 라우터 4개에 `router` 와 `SCREENS` 만 두었다.
`EST_*` · `AGT_*` · `BAS_*` · `INV_*` · `IF_*` 표는 **읽기만** 했다
(예외: `tests/test_dev2_chain.py` 픽스처가 전제를 임시로 넣고 **되돌린다**).

---

# 웨이브 D 마무리 (회전 7 · 단독) — 개발2 미완성 테스트 4건

> 스톨 시점에 개발2 가 쓴 테스트 4건이 실패하고 있었다. 전부 통과시켰다.
> `uv run pytest -q tests/test_dev2_screens.py` → **121 passed**(실측).

## 1. 수집 중단 판정 정본 한 벌 (DEF-QA2-002 · §10-16)

`routers/dsh.py` 에 남아 있던 것은 **코드가 아니라 문서열**이었다 —
docstring 이 `anchor() - max(COLLECT_DT)` 와 `INGEST_STALE_SEC` 를 그대로 적고 있어
`test_G12_중단_판정은_정본_함수_한_벌이다` 의 소스 스캔에 걸렸다. 문구를 고쳤다.
판정 코드는 이미 `collector.status()` 한 벌이다(실측 grep 0건):

```
grep -n "INGEST_STALE_SEC\|anchor() - " src/kyungdong/app/routers/dsh.py   → 0 건
```

## 2. 수집 중단 배지가 운영 시각에서 뜬다 (DEF-QA2-001)

`collector.stale_reference()` 는 이미 실시각 기준이었다. 남은 문제는 **테스트 자체**였다:
② 신선(now−1s) → ③ 중단(now−300s) 순서로 넣는데, 판정은 `max(COLLECT_DT)` 라
**뒤에 넣은 오래된 배치를 앞의 신선한 배치가 덮어 가렸다**(실측: ③에서 배지 0건).
`max(COLLECT_DT)` 가 맞는 의미다 — Gateway 재전송이 오래된 타임스탬프를 몰고 올 때
"방금 재전송받았는데 중단" 이라고 말하면 거짓이다. **판정을 바꾸지 않고 테스트 순서를 뒤집었다**
(중단 → 신선). 0건·중단·신선 **세 경로를 전부 단언**한다는 원래 의도는 그대로다.

```
uv run pytest -q tests/test_dev2_screens.py -k G12     → 3 passed
  ① 0건   → '미수집 (D-06)'   (수집 중단 아님)
  ② 중단  → '수집 중단 — 마지막 수집 HH:MM:SS' (실시각 300초 전, 임계 60초)
  ③ 신선  → 배지 없음 (실시각 1초 전)
```

## 3. 권한 거부를 `오류` 로 기록 (G-29)

**16화면을 각각 고치지 않았다.** 원인은 `app/main.py` 의 공용 권한 가드(D-78)가
라우터 `guard()` **보다 먼저** 돌아서 `dsh.guard` 안의 거부 감사에 도달하지 못한 것이었다.
기록을 그 한 곳에 넣었다. `routers/{dsh,prc,shp,kpi}.py` 의 `audit(request` 호출 수는
**dsh 2 · 나머지 0** 그대로다(`test_G29_감사는_가드_한_곳에서만_부른다` 통과).

## 4. CSRF 토큰 왕복 (G-26)

두 가지가 걸려 있었다.
- `shp.py` 의 `Form(...)` 시그니처가 **핸들러 본문보다 먼저** 파싱돼 토큰 없는 요청이 403 이 아니라
  **422** 를 받았다. `request.form()` 수동 파싱으로 바꿔 검사 순서를 **CSRF → 권한 → 입력값** 으로 맞췄다.
- 토큰이 **빈 문자열로 렌더되고 있었다**(Jinja `with context` 누락 — 자세한 건 `progress-dev1.md` §4).
  또 세션 없는 요청의 CSRF 쿠키를 **응답에서** 처음 심어서, 화면이 발급한 토큰이 다음 POST 에서
  항상 무효였다. `app/main.py` 가 **요청 시점**에 쿠키 값을 정하도록 고쳤다.

테스트의 유효 토큰 획득도 고쳤다 — 밖에서 지어낸 토큰은 바인딩이 달라 막히는 게 **정상**이다.
브라우저가 하는 그대로 `GET /prc/021` 응답의 폼에서 꺼내 쓴다.

```
uv run pytest -q tests/test_dev2_screens.py -k G26     → 3 passed
  ENFORCE=1 · 토큰 없음 → /prc/021 · /shp/016 · /shp/016/approve 전부 403
  ENFORCE=1 · 화면이 발급한 토큰 → 403 아님
```

## 내가 바꾼 개발2 테스트 (숨기지 않는다)

`tests/test_dev2_screens.py` 3곳:
① `test_G12_수집중단_배지가_운영시각에서_뜬다` — ②③ 순서 교환(위 §2).
② `test_G26_쓰기_폼에_CSRF_필드가_있다` — import 단언에 `with context` 추가(매크로가 동작하려면 필수).
③ `test_G26_토큰이_없으면_403_있으면_통과한다` — 유효 토큰을 화면에서 꺼내도록.
**구현을 테스트에 맞춰 비틀지 않았다.** 셋 다 테스트 쪽 전제가 틀렸던 경우다.

## 검증 명령

```
make db-reset && uv run pytest -q tests/test_dev2_screens.py   # 121 passed
uv run python tools/check_ingest.py                            # G-12-③a 화면↔모듈 판정 일치 True
```

## 남은 것 (개발2 몫 아님 · QA 갱신 대기)

- **G-12 는 아직 FAIL 이다.** 남은 결함 1건은 `tools/check_ingest.py` 의 `③b` 다:
  "실시각 수집 직후에 `수집 중단` 배지가 없으면 결함" 이라고 본다. 그런데 **방금 들어온 수집은
  중단이 아니다** — 그게 DEF-QA2-001 을 고친 결과다. 검사기 문구가 아직
  "`routers/dsh.collection_badges()` 의 `anchor() - last_dt`" 를 지목하는데 그 코드는 없다(grep 0건).
  실제 중단 시나리오(③a)는 화면·모듈 **둘 다 True** 로 일치한다(실측). **QA 가 ③b 를 갱신해야 한다.**
- DEF-QA2-011(`PRC_PROCESS_HISTORIES` 판정 ↔ 실제 0건)은 **손대지 않았다.**

---

# 회전 22 — 사슬 후반(작업지시~출하)을 합성으로 채웠다 (D-131 · 상세는 `progress-dev1.md` 회전 22)

> **자재LOT 이후는 전부 합성이다.** 이 수치를 성과 실적으로 인용할 수 없다 — `합성 데이터 기준 (D-131)`.

## 무엇이 바뀌었나

- **제품LOT 은 BOM 1건당 1건이다**(D-212). `seed_chain` 이 `seed_dev1.thread_rows()`
  (프로젝트 → BOM → 투입 자재LOT + **의도적 단절 위치**)를 읽어 돈다. 프로젝트당 1건이 아니다 —
  LOT 매핑률의 분모를 12에서 **40** 으로 키워 85% 임계를 의미 있게 재려는 목적도 있다.
- **작업지시는 제품LOT × 제조 7공정**이다 → 280건. `ROUTING_ID` 가 개발1 이 만든
  `EST_BOM_ROUTINGS` 를 가리킨다(전에는 NULL 이었다).
- **품질기준을 제품군별로 고른다** — `standards_for(qstd, PRODUCT_GROUP)`. 15행(제품군 5 × 검사 3)
  중 그 제품군의 수압·기밀·진공 3종을 다 못 찾으면 검사를 만들지 않고 `차단` 으로 적는다.
- **`SHP_SHIPMENTS.APPROVER_ID` 를 반드시 채운다** — `SHIP_DT` 가 있는데 승인자가 비면
  **G-24 가 FAIL** 이다(`check_ai.py` · `tests/test_qa3_ai.py`). 실명을 넣지 않고 직무 계정 `exec` 를 쓴다.
- **출하 품목 코드 = BOM 레벨1 품목**(D-206-정정). 제품군 코드(PG10…)를 품목 칸에 넣던 것이 틀렸다.
- **`MAPPING_OK_YN` 을 선언하지 않고 실제 연결로 다시 쓴다**(D-213) — `_restate_mapping_flag()`.
  Y 35 / 전체 40 이고 QA2 독립 재계산 35/40(87.5%)과 **정확히 일치**한다.
- **`SHP_SHIPMENT_ITEMS.REMARK` · `KPI_MEASURES.REMARK` 에 합성 표시**를 남겼다.
  나머지 개발2 표(`PRC_WORK_ORDERS`·`PRC_PERFORMANCES`·`PRC_PROCESS_HISTORIES`·`SHP_LOT_TRACES`·
  `SHP_INSPECTIONS`·`SHP_SHIPMENTS`)에는 **비고 칸이 없다** — 컬럼을 추가하지 않았고(G-02 762 고정)
  표시는 화면 배지·게이트 판정 줄·`SYS_CONFIGS` 선언이 진다. 근거는 `decisions-dev1.md` D-131-보고.

## 행 수 (합성)

`PRC_WORK_ORDERS` **280** · `PRC_PERFORMANCES` **195** · `PRC_PROCESS_HISTORIES` **280** ·
`SHP_LOT_TRACES` **40** · `SHP_INSPECTIONS` **117** · `SHP_SHIPMENTS` **39** ·
`SHP_SHIPMENT_ITEMS` **39** · `KPI_TARGETS` 2 · `KPI_MEASURES` **22**.
여전히 **0건**: `PRC_STD_CONDITIONS`·`PRC_ACTUAL_CONDITIONS`·`PRC_CONDITION_DEVIATIONS`(D-203) ·
`PRC_EQUIP_SIGNALS`(D-06 수집 산출물) · `SHP_CLAIMS`·`SHP_CLAIM_CAUSES`(D-204).

**의도적 단절 5 / 40 = 12.5%** — 위치는 `seed_dev1.BREAKS` 가 정본이고 표는
`progress-dev1.md` 회전 22 ④ 에 있다. **단절을 빼서 100% 를 만들지 않았다.**

## KPI — 합성 표본이라 성과가 아니다

| 코드 | 기존 → 목표 | 감소율 | **합성 표본** | 실측 평균 | 달성률 |
|---|---|---|---|---|---|
| `LEADTIME_MFG` | 1,320h → 1,080h | −18.2% | 39건 | 1,099.1 h | 92.0 % |
| `LEADTIME_O2D` | 1,440h → 1,200h | −16.7% | 39건 | 1,206.5 h | 97.3 % |

QA2 독립 SQL 과 앱 산식이 **표본·평균 모두 일치**하고 4화면(`/board`·043·044·045)의 문자열이
**1종**이다 → `KPI PASS`. 다만 `KPI_MEASURES.REMARK` 에
`합성 데이터 기준 (D-131) — … 자재LOT 이후가 합성이라 이 값은 성과 실적이 아니다` 가 박혀 있다.

## 결함 2건 (합성 데이터가 드러냈다)

- **D-210** `POST /shp/016` 채번 `count(*) + 1` → 연도별 시드 번호와 충돌해 UNIQUE 위반 **500**.
  그 해 마지막 일련번호 + 1 로 고쳤다.
- **D-211** `/kpi/044` 클레임 발생률 카드 보조설명이 "분모 0 인데 0%로 메웠다" 로 **오탐**됐다.
  분모는 출하 39건이고 분자가 0이라 0.0% 는 참값이다. **검사기(QA2 소유)를 고치지 않고**
  보조설명을 `분모 출하 39건 · 분자 클레임 0 (D-204 미등록)` 로 갈랐다.
  **QA2 에 보고**: 보조설명 문자열 판정은 **분자 0 을 분모 0 으로 오탐**할 수 있다.

## 테스트

`tests/test_dev2_chain.py` 픽스처가 상류(도면 → BOM → BOM자재 → 공정구조 → 자재LOT)까지 세운다 —
`seed_chain` 이 BOM 단위로 돌기 때문이다. 끝나면 전부 되돌리고 그것도 단언한다.
`/dsh/001` 은 `PROJECT_NO` 오름차순 상위 8건만 그리므로 테스트 프로젝트가 밀린다 —
**밀린 것이 결함이 아니라서** 화면과 같은 순서로 뽑은 첫 프로젝트를 확인하도록 뒤집었다.
