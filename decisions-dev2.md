# decisions-dev2.md — 개발2 결정 대장 (대역 `D-2nn`)

`확정` / `가설` / `차단` 세 상태만 쓴다. 공용 결정은 `decisions.md`(D-01~D-51) 에 있고
여기 것은 **개발2 범위에서 새로 정했거나 산출물 결함으로 발견한 것**이다.
산출물은 고치지 않는다 — 여기에 올리고 도입기업에 제안한다.

---

| ID | 상태 | 내용 | 근거·처리 |
|---|---|---|---|
| **D-200** | 확정 | **채번은 개발1 이 `BAS_COMMON_CODES('LOT채번')` 에 공표한 형식을 읽어 쓴다.** `WORK_ORDER_NO=WO-YYYY-NNNN` · `PRODUCT_LOT_NO=PLOT-YYYY-NNN` · `SHIPMENT_NO=SH-YYYY-NNNN` | 착수 시점에 `progress-dev1.md` 가 없어 TD3 목업 `grid_sample`(WO-2026-0031 · PLOT-2026-011 · SH-2026-0011) 형식을 임시로 썼는데, 개발1 이 공표한 값과 **완전히 일치**했다. `db/seed_dev2.py` 는 이제 DB 에서 형식을 읽고(`numbering()`), 코드가 없을 때만 목업 형식으로 되돌린다. **채번 규칙은 한 곳(BAS_COMMON_CODES)에만 둔다** |
| **D-201** | 가설 | **`KPI_TARGETS.KPI_FIELD` 값을 `LEADTIME_MFG='P'` · `LEADTIME_O2D='D'` 로 정했다.** TD5 비고는 "P/Q/C/D 등" 까지만 적고 어느 지표가 어느 분야인지 **적지 않았다** | 제조 리드타임은 043 **생산성** KPI 조회 화면 소속이라 P, 수주출하 리드타임은 납기 축이라 D 로 본다. **화면 로직은 이 값에 의존하지 않는다** — 043·045 는 `OFFICIAL_YN` 과 KPI 코드로 고른다. 분야 코드 체계 확정은 담당자 확인 필요 |
| **D-202** | 가설 | **달성률(%) = (기존값 − 측정값) ÷ (기존값 − 목표값) × 100.** `KPI_MEASURES.ACHIEVE_RATE` 에 TD5 비고가 없고 사업계획서에도 산식이 없다 | 리드타임은 **작을수록 좋은 지표**라 "목표÷측정" 류로 쓰면 100%를 넘는 값이 정상처럼 보인다. 개선 폭 진척률로 정의하고 `app/kpi.py ACHIEVE_FORMULA` 한 곳에 두어 **화면에 산식을 함께 띄운다**. 감소율(IMPROVE_RATE)은 사업계획서 1.5 확정 산식이라 이것과 별개다 |
| **D-203** | 차단 | **표준 작업조건(`PRC_STD_CONDITIONS`) 초기값을 시드하지 않는다.** TD3 023 제약사항: "현행 작업 조건은 작업자 경험으로 전파되고 문서화되어 있지 않아 표준 작업 조건의 초기 정의는 도입기업이 제공해야 한다 — 담당자 확인 필요" | 목업 `grid_sample` 에 절단속도 1200 · 용접전류 180 이 적혀 있으나 **예시 행이지 정본 값이 아니다.** 표준값이 없으면 실측(`PRC_ACTUAL_CONDITIONS`)·편차(`PRC_CONDITION_DEVIATIONS`)도 파생될 수 없다. 023 화면은 `미확정 (D-203)` 을 렌더한다 — '미수집' 이 아니라 **'미확정'** 이다(값이 없는 것이지 못 읽은 것이 아니다). **도입기업에 표준 조건표 요청** |
| **D-204** | 차단 | **클레임(`SHP_CLAIMS`)·클레임원인(`SHP_CLAIM_CAUSES`)을 시드하지 않는다 — 런타임 등록 대상으로 판정했다.** TD3 019 제약사항: "클레임 이력이 문서로만 존재하여 초기 데이터가 부족하다" | 게다가 `CLAIM_TYPE`·`CUSTOMER_CODE` 가 D-47 로 비워 둔 코드 그룹을 참조한다 — 코드가 없으면 `require_code` 가 422 를 낸다. 019 화면은 `미수집 (D-204)` 을 렌더한다. `contracts/db-schema.md` §7 런타임 전용 표로 옮길 대상 |
| **D-205** | 확정 | **현황판 `/board` 는 `routers/kpi.py` 가 맡는다.** `main.py` 의 `/board` 보다 **먼저 등록**되므로(라우터를 먼저 include 한다) 그쪽이 이긴다 | `app/templates/board.html` 은 개발2 소유인데 데이터를 넣으려면 라우트가 필요하고 **`main.py` 는 건드리지 않는다**(소유권 §3.4). FastAPI 가 `_IncludedRouter` 를 `app.routes` 앞쪽(index 2~11)에 두고 `main.py` 의 `/board` 는 index 16 이라 개발2 라우트가 먼저 매치된다 — 실측 확인. 아키텍트가 `main.py` 의 `board_screen` 을 지우면 더 깨끗하다 |
| **D-206** | 차단 | **출하 시드가 `고객사`·`품목` 코드 그룹에 막힌다.** `SHP_SHIPMENTS.CUSTOMER_CODE`(NOT NULL) · `SHP_SHIPMENT_ITEMS.ITEM_CODE`(NOT NULL) 가 D-47 로 비워 둔 그룹을 참조한다 | 두 값 모두 **프로젝트(`EST_PROJECTS.CUSTOMER_CODE` · `PRODUCT_GROUP`)에서 가져오므로** 개발3 이 프로젝트를 넣을 때 이미 코드가 있어야 한다. 시드는 `validate_code` 로 확인하고 없으면 **`차단` 으로 출력**한다 — 코드를 지어내서 넣지 않는다. 화면(016)은 출하 대상 LOT `0 건`을 그대로 보여 준다 |
| **D-207** | 확정 | **`PRC_EQUIP_SIGNALS` 를 개발2 시드에서 만들지 않는다.** 표 접두는 `PRC_` 라 개발2 소유지만 **데이터 출처는 수집 경로(개발3 `ingest` · 레이저커팅기 Master PLC 1지점)** 다 | 자동 수집을 흉내 낸 시드를 넣으면 D-06(수집 지점 2개소 한정)을 화면이 거짓으로 렌더하게 된다. 003·022 는 신호가 없으면 `미수집 (D-06)`, 마지막 수집이 `INGEST_STALE_SEC` 를 넘으면 **수집 중단 배지**를 띄운다(G-12) |
| **D-208** | 확정 | **(결함 → 회전 중 해소)** `tools/check_routes.py` G-03-③ 이 아키텍트 파일에서 타 사업 용어 1건을 잡았다 — `src/kyungdong/app/util/security.py:3` 의 `'타월'`("직전 사업(송월타월)에서 …") | **개발2 파일이 아니라 고치지 않고 보고만 했다**(산출물을 고치지 마라). 근거 D-번호가 주변 160자 안에 없어서 걸렸다(D-37 규칙). **아키텍트가 같은 회전에 고쳐 재실측 `G-03-③ PASS — 렌더 0건 · 소스 0건`.** 개발2 소유 파일(`routers/{dsh,prc,shp,kpi}.py` · `app/kpi.py` · `templates/{dsh,prc,shp,kpi}/*` · `board.html` · `db/seed_dev2.py`)은 처음부터 **0건**이었다 |
| **D-209** | 확정 | **개발2 공용 헬퍼를 `routers/dsh.py` 에 둔다.** `guard` · `ctx` · `cell` · `lot_cell` · `project_cell` · `collection_badges` 를 `prc.py` · `shp.py` · `kpi.py` 가 가져다 쓴다 | 소유 파일이 `routers/{dsh,prc,shp,kpi}.py` 로 고정돼 있어(screen-map §2) `routers/_dev2.py` 같은 새 파일을 만들 수 없다. 같은 이유로 Jinja 공용 매크로는 `templates/dsh/_kit.html` 에 둔다 — 네 디렉터리 전부가 import 한다 |
