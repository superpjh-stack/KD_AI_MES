# contracts/screen-map.md — 화면 45 ↔ 담당 ↔ 소유 파일

> **생성 파일이다.** 정본은 `src/kyungdong/app/nav.py` 이고 `tools/gen_screen_map.py` 가 뽑는다.
> 손으로 고치지 않는다. **코드와 다르면 코드가 맞다**(goal.md §4.1) → `nav.py` 를 고치고 다시 생성한다.

화면 **45** · 업무영역 **10** · 프로그램 **49** · 테이블 **68** · 컬럼 **762**

## 1. 화면 45

| # | 화면 ID | 화면명 | 업무영역 | 메뉴 | 경로 | 요구사항 | 프로그램 | 담당 | 구현 파일 | 채널 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | MES-TD3-001 | 생산현황 분석 | AI 대시보드 | 대시보드 | `/dsh/001` | MES-AD2-001 | MES-TD4-001 | **개발2** | `routers/dsh.py` | 관리자 Web, 현황판 2대 / 공정실적·설비 수집 데이터 |
| 2 | MES-TD3-002 | 품질현황 분석 | AI 대시보드 | 대시보드 | `/dsh/002` | MES-AD2-002 | MES-TD4-002 | **개발2** | `routers/dsh.py` | 관리자 Web, 현황판 / 검사·공정실적 데이터 |
| 3 | MES-TD3-003 | 설비상태 모니터링 | AI 대시보드 | 대시보드 | `/dsh/003` | MES-AD2-003 | MES-TD4-003 | **개발2** | `routers/dsh.py` | 관리자 Web, 현황판 / PLC·Gateway 수집 데이터 |
| 4 | MES-TD3-004 | 출하현황 분석 | AI 대시보드 | 대시보드 | `/dsh/004` | MES-AD2-004 | MES-TD4-004 | **개발2** | `routers/dsh.py` | 관리자 Web, 현황판 / 출하·프로젝트 데이터 |
| 5 | MES-TD3-010 | CAD 도면분석 | 수주견적AI관리 | 견적AI | `/est/010` | MES-AD2-010 | MES-TD4-010 | **개발3** | `routers/est.py` | 관리자 Web / CAD 파일 인터페이스·도면 데이터 |
| 6 | MES-TD3-011 | 객체인식 결과관리 | 수주견적AI관리 | 견적AI | `/est/011` | MES-AD2-011 | MES-TD4-011 | **개발3** | `routers/est.py` | 관리자 Web / 객체인식·Feature 데이터 |
| 7 | MES-TD3-012 | 견적자동산출 | 수주견적AI관리 | 견적AI | `/est/012` | MES-AD2-012 | MES-TD4-012 | **개발3** | `routers/est.py` | 관리자 Web / 견적·단가·Feature 데이터 |
| 8 | MES-TD3-013 | BOM자동생성 | 수주견적AI관리 | 견적AI | `/est/013` | MES-AD2-013 | MES-TD4-013 | **개발3** | `routers/est.py` | 관리자 Web / BOM·도면 객체 데이터 |
| 9 | MES-TD3-014 | ML분석 | 수주견적AI관리 | 견적AI | `/est/014` | MES-AD2-014 | MES-TD4-014 | **개발3** | `routers/est.py` | 관리자 Web / 모델·학습이력·데이터셋 |
| 10 | MES-TD3-015 | 영향요인분석 | 수주견적AI관리 | 견적AI | `/est/015` | MES-AD2-015 | MES-TD4-015 | **개발3** | `routers/est.py` | 관리자 Web / SHAP·예측 데이터 |
| 11 | MES-TD3-005 | 입고관리 | 입고재고관리 | 입고 | `/inv/005` | MES-AD2-005 | MES-TD4-005 | **개발1** | `routers/inv.py` | 스마트패드, 관리자 Web / 입고·재고 데이터 |
| 12 | MES-TD3-006 | 원자재 이력조회 | 입고재고관리 | 입고 | `/inv/006` | MES-AD2-006 | MES-TD4-006 | **개발1** | `routers/inv.py` | 관리자 Web, 스마트패드 / 자재 이력 데이터 |
| 13 | MES-TD3-007 | 입고 데이터관리 | 입고재고관리 | 입고 | `/inv/007` | MES-AD2-007 | MES-TD4-007 | **개발1** | `routers/inv.py` | 관리자 Web / 입고·ERP 연계 데이터 |
| 14 | MES-TD3-008 | 공급처 품질분석 | 입고재고관리 | 입고 | `/inv/008` | MES-AD2-008 | MES-TD4-008 | **개발1** | `routers/inv.py` | 관리자 Web / 공급처·입고·검사 데이터 |
| 15 | MES-TD3-009 | 입고 AI Agent | 입고재고관리 | 입고 | `/inv/009` | MES-AD2-009 | MES-TD4-009 | **개발3** ⚠ | `routers/agt.py` | 스마트패드, 관리자 Web / 질의이력·임베딩 문서 |
| 16 | MES-TD3-021 | 공정실적관리 | 공정관리 | 공정 | `/prc/021` | MES-AD2-021 | MES-TD4-021 | **개발2** | `routers/prc.py` | 현장POP, 스마트패드, 관리자 Web / 공정실적 데이터 |
| 17 | MES-TD3-022 | 공정 데이터 모니터링 | 공정관리 | 공정 | `/prc/022` | MES-AD2-022 | MES-TD4-022 | **개발2** | `routers/prc.py` | 관리자 Web, 현황판 / 시계열·PLC 수집 데이터 |
| 18 | MES-TD3-023 | 작업조건관리 | 공정관리 | 공정 | `/prc/023` | MES-AD2-023 | MES-TD4-023 | **개발2** | `routers/prc.py` | 관리자 Web, 현장POP / 표준·실측 조건 데이터 |
| 19 | MES-TD3-024 | 공정이력조회 | 공정관리 | 공정 | `/prc/024` | MES-AD2-024 | MES-TD4-024 | **개발2** | `routers/prc.py` | 관리자 Web, 현장POP / 공정이력 데이터 |
| 20 | MES-TD3-025 | 공정데이터 분석 | 공정관리 | 공정 | `/prc/025` | MES-AD2-025 | MES-TD4-025 | **개발2** | `routers/prc.py` | 관리자 Web / 공정·품질 통합 데이터 |
| 21 | MES-TD3-016 | 출하관리 | 출하물류관리 | 출하 | `/shp/016` | MES-AD2-016 | MES-TD4-016 | **개발2** | `routers/shp.py` | 관리자 Web, 스마트패드 / 출하·ERP 연계 데이터 |
| 22 | MES-TD3-017 | LOT추적관리 | 출하물류관리 | 출하 | `/shp/017` | MES-AD2-017 | MES-TD4-017 | **개발2** | `routers/shp.py` | 관리자 Web, 현장POP / LOT·공정이력 데이터 |
| 23 | MES-TD3-018 | 검사결과관리 | 출하물류관리 | 출하 | `/shp/018` | MES-AD2-018 | MES-TD4-018 | **개발2** | `routers/shp.py` | 관리자 Web, 스마트패드 / 검사·품질기준 데이터 |
| 24 | MES-TD3-019 | 클레임분석 | 출하물류관리 | 출하 | `/shp/019` | MES-AD2-019 | MES-TD4-019 | **개발2** | `routers/shp.py` | 관리자 Web / 클레임·검사·LOT 데이터 |
| 25 | MES-TD3-020 | 출하 AI Agent | 출하물류관리 | 출하 | `/shp/020` | MES-AD2-020 | MES-TD4-020 | **개발3** ⚠ | `routers/agt.py` | 관리자 Web, 스마트패드 / 질의이력·검사·LOT 데이터 |
| 26 | MES-TD3-030 | 품질기준 관리 | 기준정보관리 | 기준 | `/bas/030` | MES-AD2-030 | MES-TD4-030 | **개발1** | `routers/bas.py` | 관리자 Web / 품질기준 데이터 |
| 27 | MES-TD3-031 | 작업표준관리 | 기준정보관리 | 기준 | `/bas/031` | MES-AD2-031 | MES-TD4-031 | **개발1** | `routers/bas.py` | 관리자 Web, 현장POP / 작업표준·SOP 문서 |
| 28 | MES-TD3-032 | 코드관리 | 기준정보관리 | 기준 | `/bas/032` | MES-AD2-032 | MES-TD4-032 | **개발1** | `routers/bas.py` | 관리자 Web / 공통코드 데이터 |
| 29 | MES-TD3-033 | 데이터통합관리 | 데이터관리 | 데이터 | `/dat/033` | MES-AD2-033 | MES-TD4-033 | **개발1** | `routers/dat.py` | 관리자 Web / 수집대상·ETL 작업 데이터 |
| 30 | MES-TD3-034 | 데이터조회 | 데이터관리 | 데이터 | `/dat/034` | MES-AD2-034 | MES-TD4-034 | **개발1** | `routers/dat.py` | 관리자 Web / 통합 데이터 |
| 31 | MES-TD3-035 | 데이터시각화 | 데이터관리 | 데이터 | `/dat/035` | MES-AD2-035 | MES-TD4-035 | **개발1** | `routers/dat.py` | 관리자 Web, 현황판 / 시계열·KPI·실적 데이터 |
| 32 | MES-TD3-036 | 데이터 다운로드 | 데이터관리 | 데이터 | `/dat/036` | MES-AD2-036 | MES-TD4-036 | **개발1** | `routers/dat.py` | 관리자 Web / 다운로드 이력·권한 데이터 |
| 33 | MES-TD3-037 | AI학습 데이터관리 | 데이터관리 | 데이터 | `/dat/037` | MES-AD2-037 | MES-TD4-037 | **개발3** ⚠ | `routers/est.py` | 관리자 Web / 학습 데이터셋·전처리 규칙 |
| 34 | MES-TD3-038 | 통합 AI질의 | AI Agent 통합관리 | Agent | `/agt/038` | MES-AD2-038 | MES-TD4-038 | **개발3** | `routers/agt.py` | 관리자 Web, 스마트패드 / 질의이력·임베딩 문서 |
| 35 | MES-TD3-039 | 생산/품질 분석 | AI Agent 통합관리 | Agent | `/agt/039` | MES-AD2-039 | MES-TD4-039 | **개발3** | `routers/agt.py` | 관리자 Web / 분석·추천 결과 |
| 36 | MES-TD3-040 | 의사결정 지원 | AI Agent 통합관리 | Agent | `/agt/040` | MES-AD2-040 | MES-TD4-040 | **개발3** | `routers/agt.py` | 관리자 Web / 추천·예측 데이터 |
| 37 | MES-TD3-041 | 알림 및 추천 | AI Agent 통합관리 | Agent | `/agt/041` | MES-AD2-041 | MES-TD4-041 | **개발3** | `routers/agt.py` | 관리자 Web, 현황판, 스마트패드 / 알림·추천 데이터 |
| 38 | MES-TD3-042 | 사용자 질문이력 | AI Agent 통합관리 | Agent | `/agt/042` | MES-AD2-042 | MES-TD4-042 | **개발3** | `routers/agt.py` | 관리자 Web / 질의이력 데이터 |
| 39 | MES-TD3-043 | 생산성 KPI 조회 | KPI관리 | KPI | `/kpi/043` | MES-AD2-043 | MES-TD4-043 | **개발2** | `routers/kpi.py` | 관리자 Web, 현황판 / KPI·공정실적 데이터 |
| 40 | MES-TD3-044 | 품질 KPI 조회 | KPI관리 | KPI | `/kpi/044` | MES-AD2-044 | MES-TD4-044 | **개발2** | `routers/kpi.py` | 관리자 Web, 현황판 / 검사·클레임·실적 데이터 |
| 41 | MES-TD3-045 | KPI 관리 | KPI관리 | KPI | `/kpi/045` | MES-AD2-045 | MES-TD4-045 | **개발2** | `routers/kpi.py` | 관리자 Web / KPI 목표·측정 데이터 |
| 42 | MES-TD3-026 | 사용자 관리 | 사용자/시스템관리 | 시스템 | `/sys/026` | MES-AD2-026 | MES-TD4-026 | **개발1** | `routers/sys.py` | 관리자 Web / 사용자·권한 데이터 |
| 43 | MES-TD3-027 | 로그 관리 | 사용자/시스템관리 | 시스템 | `/sys/027` | MES-AD2-027 | MES-TD4-027 | **개발1** | `routers/sys.py` | 관리자 Web / 접속·변경·API·오류 로그 |
| 44 | MES-TD3-028 | 알림 설정 | 사용자/시스템관리 | 시스템 | `/sys/028` | MES-AD2-028 | MES-TD4-028 | **개발1** | `routers/sys.py` | 관리자 Web / 알림 기준·수신 대상 |
| 45 | MES-TD3-029 | 시스템 설정 | 사용자/시스템관리 | 시스템 | `/sys/029` | MES-AD2-029 | MES-TD4-029 | **개발1** | `routers/sys.py` | 관리자 Web / 시스템 설정·수집대상·장비 등록 데이터 |

⚠ = **업무영역과 구현 파일이 갈리는 화면**. URL·메뉴 위치는 산출물(SF-TD3) 그대로 두고 구현 파일만 옮겨 "한 파일은 한 사람만" 을 지킨다.

| 화면 | 메뉴 위치 | 구현 | 이유 |
|---|---|---|---|
| MES-TD3-009 입고 AI Agent | `/inv/009` (입고) | `routers/agt.py` (개발3) | AI 화면이라 개발3 이 소유한다 (goal.md §3.2) |
| MES-TD3-020 출하 AI Agent | `/shp/020` (출하) | `routers/agt.py` (개발3) | AI 화면이라 개발3 이 소유한다 (goal.md §3.2) |
| MES-TD3-037 AI학습 데이터관리 | `/dat/037` (데이터) | `routers/est.py` (개발3) | AI 화면이라 개발3 이 소유한다 (goal.md §3.2) |

## 2. 소유권 — 동시 기동 시 이 표가 곧 계약 (goal.md §3.4)

| 소유자 | 화면 수 | 파일 |
|---|---|---|
| 아키텍트 | — | `contracts/*` · `app/{main,nav,rbac,settings,design,templating,auth}.py` · `app/util/*` · `app/templates/{base,login,_placeholder,_popup,_error,common,board}.html` · `app/static/*` · `db/{schema.sql,conn.py,seed.py}` · `tools/{gen_schema,gen_screen_map,check_routes,gate}.py` · `Makefile` · `pyproject.toml` · `.env.example` |
| 개발1 | **15** | `app/routers/{inv,bas,sys,dat}.py` · `app/templates/{inv,bas,sys,dat}/` · `db/seed_dev1.py` · `tests/test_dev1_*.py` · `progress-dev1.md` · `decisions-dev1.md` |
| 개발2 | **16** | `app/routers/{dsh,prc,shp,kpi}.py` · `app/kpi.py` · `app/templates/{dsh,prc,shp,kpi}/` · `db/seed_dev2.py` · `tests/test_dev2_*.py` · `progress-dev2.md` · `decisions-dev2.md` |
| 개발3 | **14** | `app/routers/{est,agt,ingest}.py` · `src/kyungdong/{agent,ml,cad,ingest}/*` · `app/templates/{est,agt}/` · `tools/{plc_simulator,cad_ingest}.py` · `db/seed_dev3.py` · `tests/test_dev3_*.py` · `progress-dev3.md` · `decisions-dev3.md` |
| QA1 | — | `tools/check_trace.py` · `tests/test_qa1_*.py` · `outputs/qa1-기능계약.md` |
| QA2 | — | `tools/{check_schema,check_data,check_ingest}.py` · `tests/test_qa2_*.py` · `outputs/qa2-데이터정합.md` |
| QA3 | — | `tools/{check_ai,check_security}.py` · `work/rag_goldset.json` · `work/cad_labelset.json` · `tests/test_qa3_*.py` · `outputs/qa3-AI비기능보안.md` |

합계 화면 **15 + 16 + 14 = 45**

## 3. 모듈별 화면

| 구현 파일 | 화면 수 | 화면 |
|---|---|---|
| `routers/agt.py` | 7 | 009, 020, 038, 039, 040, 041, 042 |
| `routers/bas.py` | 3 | 030, 031, 032 |
| `routers/dat.py` | 4 | 033, 034, 035, 036 |
| `routers/dsh.py` | 4 | 001, 002, 003, 004 |
| `routers/est.py` | 7 | 010, 011, 012, 013, 014, 015, 037 |
| `routers/inv.py` | 4 | 005, 006, 007, 008 |
| `routers/kpi.py` | 3 | 043, 044, 045 |
| `routers/prc.py` | 5 | 021, 022, 023, 024, 025 |
| `routers/shp.py` | 4 | 016, 017, 018, 019 |
| `routers/sys.py` | 4 | 026, 027, 028, 029 |

## 4. 공통 화면

| ID | 이름 | 경로 | 담당 |
|---|---|---|---|
| login | 로그인 화면 | `/login` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |
| common | 메인시안 | `/` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |
| dashboard | 대시보드 화면 | `/board` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |
| popup | 팝업 화면 | `/popup` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |
| error | 공통 오류 화면 | `/error` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |

## 5. RBAC — 6역할 × 8권한영역 (goal.md G-28 · TD3 role_matrix)

R=조회 · W=등록/수정 · A=승인. 권한 없음(`-`) = **403**.

| 역할 | AI 대시보드 | 수주견적AI관리 | 입고재고관리 | 출하물류관리 | 공정관리 | 기준정보·데이터 | AI Agent·KPI | 사용자/시스템관리 |
|---|---|---|---|---|---|---|---|---|
| 총괄PM/경영자 | R | RA | R | RA | R | R | R | R |
| 품질·RCMS 담당 | R | R | RW | RW | R | RW | R | – |
| 공장장·생산관리 | R | R | RW | RW | RW | RW | R | – |
| 현장 작업자 | R | – | RW | RW | RW | R | R | – |
| 공급기업 운영담당 | R | R | R | R | R | RW | R | RW |
| 시스템 관리자 | RWA | RWA | RWA | RWA | RWA | RWA | RWA | RW |

역할 라벨에서 **실명은 제거했다**(G-29 개인정보). 산출물 원문은 `rbac.Role.source_label` 에 있다.
