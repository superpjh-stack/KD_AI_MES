# decisions-dev1.md — 개발1 결정·발견한 결함 (`D-1nn` 대역)

경동글로벌텍 제조AI 플랫폼 (SF26179182). 규칙: **산출물을 고치지 않는다** — 결함은 적고 넘어간다.
`decisions.md`(아키텍트, D-01~D-50)와 번호가 겹치지 않도록 **D-101 부터** 쓴다.

---

## D-101 — 입고 업무 데이터는 시드할 수 없다 (차단)

**구분** 차단 · 판정
**대상** `INV_SUPPLIERS` · `INV_MATERIAL_LOTS` · `INV_RECEIPTS` · `INV_STOCKS`

**사실**
- `INV_MATERIAL_LOTS.ITEM_CODE` 는 `NOT NULL` 이고 코드성 FK(그룹 `품목`)다. `MATERIAL` 은 그룹 `재질` 이다.
- 두 그룹은 **비어 있어야 한다** — D-47 "정본에 값이 없어 비운 것이다 · 채우지 마라",
  그리고 `tests/test_arch_seed.py::test_정본에_없는_코드그룹은_비어있다` 가 0건을 단언한다.
- `INV_RECEIPTS.LOT_ID` · `INV_STOCKS.LOT_ID` 도 `NOT NULL` 이라 LOT 없이는 만들 수 없다.
- `INV_SUPPLIERS` 는 목록이 정본에 없고 **45화면에 공급처 마스터 등록 화면이 없다**
  (005 입고관리의 '등록' 은 입고 등록이고, 008 은 조회·평가산출·리포트·엑셀뿐이다).

**판정** 시드 0건이 정답이다. 정본도 같은 말을 한다 — SF-TD3-005 체크:
*"현행 입고 데이터는 Excel 약 1천개와 종이 MTC로 관리되어 **초기 이관 범위를 착수 시 확정해야 한다.**"*
공급처 상호를 지어내면 G-29(개인정보·거래처)와 §0.2(지어내지 않는다)를 동시에 어긴다.

**대신 한 것** 유입 경로를 전부 만들었다 — ① `/bas/032` 코드 등록 → ② `/inv/005` 입고 등록 또는
③ `/inv/007` **Excel 적재**(D-07 정식 입력, 공급처 자동 생성 + 코드 검증 + 실패 행 미적재).
N건 경로는 `tests/test_dev1_flow.py` 가 실제 쓰기로 단언하고 PK 워터마크로 되돌린다.

**도입기업에 필요한 것** 품목·재질·보관위치 코드 목록, 공급처 목록(상호·공급구분).

---

## D-102 — `INV_MATERIAL_HISTORY` 는 런타임 누적표다 (db-schema §7.1 판정)

**판정** 시드 대상 **아님**. `contracts/db-schema.md` §7.1 → **§7 런타임 전용으로 옮긴다.**

**근거** `HIST_TYPE` 이 입고/투입/반출/반입/출하다 — 사건이 일어난 시점에 쌓이는 표다.
입고 저장이 첫 행(`입고` · 공정 `P20 입고검사`)을 쓰고, 이후 공정(개발2)이 투입·반출·반입을 쌓는다.
시드가 이력을 만들면 **실제 흐름 없이 LOT 매핑 성공률(D-23 · 목표 85%)이 조작된다** — G-08·G-09 가 무의미해진다.

**구현** `routers/inv.py::_receive()` 가 LOT·입고·재고·이력을 **한 트랜잭션**으로 쓴다.

---

## D-103 — `INV_SUPPLIER_QUALITY` 는 누적 집계다 (db-schema §7.1 판정)

**판정** 마스터가 아니라 **파생 집계**다. 시드 대상 **아님** → §7 로 옮긴다.

**근거** TD5 `DEFECT_RATE` 비고가 산식을 못 박았다 — *"불합격÷납품×100"*. 산식이 적힌 컬럼은 파생값이다.
`INV_SUPPLIERS.GRADE` 비고도 *"INV_SUPPLIER_QUALITY 산출"* 이라 적혀 있다.

**구현** `/inv/008` '평가산출' 이 `INV_RECEIPTS` 를 분기(`YYYY-Qn`)로 집계해 upsert 한다.
재실행해도 행이 늘지 않는다.

---

## D-104 — `app/util/security.py` 에 근거 없는 타 사업 용어가 남아 있다 (결함 · 아키텍트 소유)

**구분** 발견한 결함 — **고치지 않았다**(내 소유 파일이 아니다).

**사실** `tools/check_routes.py` 의 G-03-③ 이 매 회전 FAIL 을 낸다:

```
G-03-③ 타 사업 용어 0건: FAIL — 렌더 0건 · 소스 1건 ["src/kyungdong/app/util/security.py:3 '타월'"]
```

해당 줄은 `"""보안 헤더 · CSP … 직전 사업(송월타월)에서 **시드 계정이 공통 비밀번호를 공유**한 것이…"""`
— **내용은 가드레일 진술이지 오염이 아니다.** 다만 `QUOTE_OK` 가 요구하는 근거 표지
(`D-01`/`D-02`/`원 산출물명`/`범위 밖`/`미적용`/… )가 용어 앞뒤 160자 안에 없어서 검사기가 잡는다.

**제안 (아키텍트 판단)** 그 문장에 `(D-01 직전 사업 교훈 — 이 사업 범위 밖이다)` 를 덧붙이면 PASS 한다.
게이트를 낮추는 것이 아니라 검사기가 요구하는 표지를 붙이는 것이다.

**영향** G-03 전체가 FAIL 로 남아 `gate.py` 의 `FAIL 1` 이 이것 하나다. 개발1 파일에는 0건이다
(`tests/test_dev1_screens.py::test_개발1_소스와_화면에_타사업_용어가_없다` passed).

---

## D-105 — CSRF 강제 설정은 있는데 검증 코드가 없다 (결함 · 아키텍트 소유)

**사실** `settings().csrf_enforce` 가 기본 `1` 이고 `.env.example` 에 `KYUNGDONG_CSRF_ENFORCE=1` 이 있는데,
토큰을 **발급하거나 검증하는 코드가 저장소 어디에도 없다**. `app/util/` 에 `csrf` 모듈이 없고
`main.py` 미들웨어도 세션·보안헤더만 붙인다.

**영향** 내가 만든 POST 11개(입고 등록 · 코드 등록 · 사용자 등록 · 설정 저장 · Excel 적재 · 반출 등)가
전부 **CSRF 무방비**다. `SameSite` 쿠키 설정도 `session.py` 에 없다.

**고치지 않은 이유** `app/util/*` 과 `main.py` 는 아키텍트 소유다. 공통 미들웨어로 넣으면
내 라우터를 수정하지 않고 붙는다 — 폼에 히든 토큰을 넣는 방식이면 `templates/bas/_list.html`
한 파일만 고치면 되므로, 시그니처가 정해지면 내가 즉시 반영한다.

---

## D-106 — `util/__init__.py` 가 `audit` 를 함수로 재노출해 모듈 import 를 가린다 (사용 주의)

**사실** `contracts/interfaces.md` §5 는 `audit(request, screen_id, action)` 을 공표한다.
`util/__init__.py` 가 `from .audit import audit` 를 하므로 **`from ..util import audit` 는 모듈이 아니라 함수**다.
`audit.audit(...)` 로 쓰면 `AttributeError: 'function' object has no attribute 'audit'` 가 난다.

**결정** 개발1 은 `from ..util.audit import audit` 로 쓴다. `contracts/interfaces.md` 에 한 줄 명기를 요청한다.
같은 패턴이 `mask`(`util/pii.py`)에도 있다 — `from ..util import mask` 는 함수다.

---

## D-107 — 공급처 평가의 4개 지표는 산식·원천이 정본에 없다 (미확정으로 둔다)

**대상** `INV_SUPPLIER_QUALITY` 의 `QUALITY_DEVIATION` · `OTD_RATE` · `TOTAL_SCORE` · `GRADE`

**사실**
- `QUALITY_DEVIATION`(품질 편차) — TD5 비고는 "검사 측정값 표준편차" 인데 `INV_RECEIPTS` 에 **측정값 컬럼이 없다**.
  `INSPECT_RESULT`(합격/불합격/보류)만 있다. 표준편차를 낼 원천이 없다.
- `OTD_RATE`(납기 준수율) — `INV_RECEIPTS` 에 **납기일 컬럼이 없다**. 입고일시만 있다.
- `TOTAL_SCORE` · `GRADE` — **가중치·등급 컷이 정본에 없다**. 008 목업의 `A`·`C` 는 `(예시)` 행이다.

**결정** 산출하지 않고 `NULL` 로 둔다. 화면은 `미확정 (D-107)` 을 렌더한다.
**불량률만** 실측한다 — TD5 가 산식을 적어 둔 유일한 지표이기 때문이다(`불합격÷납품×100`).

**정본 결함 성격** SF-TD3-008 목업 그리드에는 '납기 준수율(%)' 열이 있는데 TD5 에 그 원천이 없다.
도입기업 발주서(납기일)나 ERP 연계가 들어와야 성립한다. **컬럼을 추가하지 않았다**(G-02 762 고정).

---

## D-108 — 공통 시드의 `SYS_USERS.USER_NAME` 이 역할명과 같아 마스킹 검증이 헷갈린다 (관찰)

**사실** `db/seed.py` 의 `ACCOUNTS` 는 실명 대신 직무명을 쓴다(G-29·D-39 준수 — 옳다).
그 결과 `USER_NAME` 이 `총괄PM/경영자` 이고, 이는 `SYS_ROLE_PERMISSIONS.ROLE_NAME` 과 **같은 문자열**이다.

**영향** 026 화면에서 사용자명은 `총********` 으로 마스킹되지만 같은 행의 **역할 열**에는 원문이 그대로 있다.
"화면에 원문이 없다" 로 단언하면 오탐이 난다 — 내 테스트는 **사용자명 열만** 골라 본다.

**결정** 결함이 아니라 시드 설계의 결과다. QA3 가 G-29 를 검사할 때 같은 함정을 밟지 않도록 적어 둔다.
실명 계정이 들어오면 자연히 갈라진다.

---

## D-109 — 알림 임계값이 정본에 수치로 없다 (조건 문장만 시드한다)

**사실** TD5 `SYS_CONFIGS.ALERT_CONDITION` 비고는 "설비 이상·납기 경고·품질 이상 임계값" 이라고
**범주만** 적었다. SF-TD3-028 목업의 `ALERT_EQUIP_ALARM` · `납기 3일 이내 미출하` 는 `(예시)` 다.

**결정** 3개 범주의 **조건 문장과 수신 역할·채널만** 시드하고 `CONFIG_VALUE`(임계값)는 비운다.
화면은 `미확정 (D-109)` 을 렌더하고 `/sys/028` 등록 폼으로 입력받는다.
`.env` 의 `INGEST_STALE_SEC`(D-09) 같은 가설값을 `SYS_CONFIGS` 에 **복제하지 않았다** — §10-1 위반이 된다.

---

## D-110 — 인터페이스 접속 정보는 저장도 표시도 하지 않는다

**사실** TD5 `SYS_CONFIGS.CONNECTION_INFO`·`DAT_SOURCES.CONNECTION_INFO` 비고가
"접속 계정·엔드포인트는 **암호화 저장**" 이라고 적었다. 실제 값은 정본에 없다(D-07 ERP 상충 포함).

**결정** ① 시드에 값을 넣지 않는다. ② `/sys/029` 그리드는 `인터페이스설정` 구분의 값을
**`(암호화 저장)`** 으로만 표시하고 원문을 내보내지 않는다(값이 없으면 `미확정 (D-07)`).
③ '연계 테스트' 버튼은 **미구현이라고 렌더한다** — 실 연동이 범위 밖인데 성공한 척하면 G-30 위반이다.

`tests/test_dev1_flow.py::test_인터페이스_설정값은_화면에_다시_나오지_않는다` 가 단언한다.

---

## D-111 — `DAT_QUALITY_CHECKS` 는 시드하지 않고 실측으로만 기록한다

**결정** `contracts/db-schema.md` §7·§7.1 어디에도 없지만 **검증 실행 산출물**로 판정했다.

**근거** `ACHIEVE_RATE` 비고가 "정상÷전체×100, **목표 85% 이상**" 이다 — G-09 의 판정 대상 그 자체다.
시드가 달성률을 채우면 QA2 의 `check_data.py` 가 측정할 것이 없어지고 게이트가 껍데기가 된다.

**구현** `/inv/007` '정합성 검증'(및 Excel 적재 직후)이 두 축을 실측 기록한다.
- **정확성** — 검사 판정이 있고 MTC(재질성적서)가 첨부된 입고 비율
- **연계성** — 자재 LOT → 제품 LOT 이력 연결 비율 (G-08 · D-23)

전체 0건이면 `ACHIEVE_RATE`·`JUDGE_RESULT` 를 `NULL` 로 두고 `ACTION_COMMENT` 에
"전체 0건 — 달성률 판정 불가" 를 남긴다. **0건을 0% 로 적지 않는다.**

---

## D-112 — `/dat/033` '즉시 실행' 은 못 하는 수집을 실패로 기록한다

**결정** 수집대상 5종 중 실제로 실행할 수 있는 것은 **ERP 경로(Excel 적재 실적 집계)뿐**이다.
나머지 4종은 `DAT_JOB_LOGS` 에 `RESULT_CODE='실패'` + **사유**를 남긴다.

| 수집대상 | 결과 | 사유 |
|---|---|---|
| ERP(이카운트) | 성공/부분성공/실패 (실측) | `IF_ERP_RECEIPTS` 성공·실패 건수를 센다 (D-07) |
| 레이저커팅기 PLC | 실패 | 수집 API 는 개발3 `ingest`(TD4-047) 소관 (D-06) |
| 현장POP(터치PC) | 실패 | 현장POP 입력은 공정실적 화면(개발2)이 받는다 (D-06) |
| CAD 도면함 | 실패 | CAD Parsing 미구성 — Autodesk API·YOLOv8 미확보 (D-05) |
| 외부 표준문서 | 실패 | 문서 임베딩은 개발3 TD4-049 소관 (D-08) |

**근거** G-30. 버튼을 눌렀는데 '성공' 이 찍히면서 아무 데이터도 안 들어오면 그게 조용한 실패다.

---

## D-113 — `/inv/007` ERP '재전송' 은 보내지 않고 '대기' 로만 기록한다

**사실** D-07 로 ERP 실 연동은 범위 밖이다. 그런데 SF-TD3-007 목업에는 '재전송' 버튼과
'동기화 상태(전송/오류)' 열이 있다.

**결정** 재전송은 `IF_ERP_RECEIPTS` 에 `IF_STATUS='대기'` · `IF_DIRECTION='송신'` 으로 남기고
`ERROR_MSG` 에 *"ERP 실 연동은 범위 밖이다 (D-07) — 연계 대기로만 기록한다"* 를 적는다.
`INV_RECEIPTS.ERP_SYNC_STATUS` 를 '전송' 으로 **바꾸지 않는다** — 보내지 않았기 때문이다.

---

## D-114 — 개발1 4모듈의 공통 헬퍼를 `routers/bas.py` 에 두었다

**결정** `inv.py`·`sys.py`·`dat.py` 가 `from .bas import guard, screen_page, search_spec, …` 로 쓴다.
공통 목록 템플릿도 `templates/bas/_list.html` 한 파일이다(15화면 전부 이것을 쓴다).

**이유** 소유권 규약은 `app/routers/{inv,bas,sys,dat}.py` 와 `app/templates/{inv,bas,sys,dat}/` 를
**전부 개발1** 에게 준다. 공용 코드를 둘 곳이 그 4개 파일 말고 없다 — `app/` 최상위에 새 모듈을 만들면
아키텍트 소유 영역을 침범한다. `bas`(기준정보)가 의미상 가장 가깝다.

**부작용** `templates/inv/` `templates/sys/` `templates/dat/` 디렉터리는 **비어 있다**(생성하지 않았다).
필요해지면 그때 만든다.

**요청** 개발자 공용 헬퍼를 둘 자리(예: `app/routers/_common.py`)를 아키텍트가 정해 주면 옮긴다.

---

## D-115 — `routers/__init__.py` 를 내가 만들었다 (소유자 미지정)

**사실** `contracts/screen-map.md` §2 는 `app/routers/{inv,bas,sys,dat}.py` 를 개발1 에게 주지만
`app/routers/__init__.py` 는 **누구 몫인지 적혀 있지 않다.** `main.py` 가
`importlib.import_module(f".routers.{module}", __package__)` 로 부르므로 패키지 선언이 필요하다.

**결정** 최소 docstring 만 담은 파일을 만들었다. 다른 개발자가 이미 만들었다면 충돌하지 않는다(내용이 없다).
**아키텍트 소유로 옮기는 것이 맞다** — 세 개발자가 공유하는 파일이기 때문이다.

---

## D-131 — 사용자 지시로 G-08 디지털 스레드를 **합성 데이터로 채웠다** (표시를 지울 수 없게 붙였다)

**사실** 사용자가 "가설데이터 만들어서 G-08에 숫자띄워줘" 라고 지시했고, 오케스트레이터가 위험을 먼저
알린 뒤 재확인받았다. 방법론에 선례가 있다 — 광성정밀 사업은 G-14~G-18 을 합성으로 재면서
goal.md §2.3 대로 `합성 데이터 기준 (D-08)` 고지를 **화면 전부에** 붙였다.
규칙은 "합성으로 재지 마라" 가 아니라 **"합성임을 지울 수 없게 표시하라"** 다.

**결정** 네 층으로 갈라서 넣고 층마다 다른 표시를 붙였다.

| 층 | 무엇 | 표시 | 어디에 남는가 |
|---|---|---|---|
| **실측** | GD 프로젝트 12건 · CAD 도면 341건(파일·경로·크기·mtime) | 표시 없음 — 지어내지 않았다 | `docs/cad/thread_projects.json` |
| **확정** | 고객사 코드 19종 | `확정 (D-139)` | `BAS_COMMON_CODES.ATTR1` |
| **가설** | 품목 코드 179종 | `가설 (D-131)` | `BAS_COMMON_CODES.ATTR1` |
| **합성** | BOM·공정구조·자재LOT·입고·재고·품질기준 골격·공급처 | `합성 (D-131)` | `EST_BOM_ROUTINGS.REMARK` · `EST_BOM_ITEMS.SPEC_TEXT` · `INV_MATERIAL_LOTS.SPEC_TEXT` · `BAS_QUALITY_STANDARDS.JUDGE_RULE` · `INV_SUPPLIERS.SUPPLIER_NAME` |

표시를 나르는 **세 번째 축**이 DB 선언 한 행이다 —
`SYS_CONFIGS('시스템설정','SYNTHETIC_THREAD') = 'D-131'`.
`templating.render()` 가 이것을 읽어 **모든 화면의 머리·바닥에 배지**를 띄우고,
`tools/check_data.py` 의 `synthetic_note()` 가 같은 행을 읽어 **G-08 판정 줄 안에** 고지를 싣는다.
선언을 지우면 배지와 고지가 같이 사라지므로, 데이터만 남기고 표시만 떼는 일이 불가능하다.

**임계값은 건드리지 않았다** — 85% 그대로다. 판정 로직도 그대로고 고지만 붙였다.

## D-131-보고 — **합성 표시를 담을 칸이 없는 표가 9종이다** (컬럼을 추가하지 않았다)

`비고`/`REMARK`/`SOURCE_DESC` 계열 컬럼은 TD5 68표 중 **7표**에만 있다
(`EST_BOM_ROUTINGS` · `EST_QUOTATION_ITEMS` · `EST_CAD_FEATURES` · `EST_COST_RATES` ·
`INV_MATERIAL_HISTORY` · `KPI_MEASURES` · `SHP_SHIPMENT_ITEMS`).
G-08 사슬 9단계 중 **`EST_PROJECTS` · `EST_CAD_DRAWINGS` 를 뺀 나머지에는 비고 칸이 없다.**

| 표 | 왜 담을 수 없는가 |
|---|---|
| `EST_BOM_HEADERS` | `GEN_METHOD`·`BOM_VERSION`·`CYCLE_CHECK_RESULT` 는 어휘 칸이다 |
| `INV_RECEIPTS` | `MTC_NO`(재질성적서)·`INSPECT_RESULT` 는 값 칸이다 |
| `INV_STOCKS` | 전 컬럼이 수량·위치·일시다 |
| `PRC_WORK_ORDERS` | 전 컬럼이 수량·일시·어휘다 |
| `PRC_PERFORMANCES` | `DEFECT_TYPE` 은 '불량유형' 코드성 FK 라 문장을 넣을 수 없다 |
| `PRC_PROCESS_HISTORIES` | `OUTSOURCE_STEP`·`HIST_STATUS` 는 어휘 칸이다 |
| `SHP_LOT_TRACES` | `MAPPING_OK_YN` 은 Y/N 한 글자다 |
| `SHP_INSPECTIONS` | `REJECT_REASON` 은 **불합격 사유** 칸이다 — 합격 행에 쓰면 거짓이 된다 |
| `SHP_SHIPMENTS` | 전 컬럼이 일시·어휘·FK 다 |

**컬럼을 추가하지 않았다**(G-02 762 고정). 그래서 이 9표의 합성 표시는 **행 안이 아니라**
① 게이트 판정 줄 ② 화면 배지 ③ `SYS_CONFIGS` 선언 ④ 상위·하위 표의 비고(`EST_BOM_ROUTINGS.REMARK`,
`SHP_SHIPMENT_ITEMS.REMARK`)가 나른다. 실행 출력(`db/seed_dev1.py`)이 이 목록을 그대로 찍는다.

**요청** 사슬 표에 `REMARK VARCHAR(300)` 을 두는 것이 맞다 — 도입기업·아키텍트 판단이 필요하다.
지금은 컬럼 수 고정이 우선이라 붙이지 않았다.

## D-139 — 고객사 코드 19종은 **사용자 확정**이다 (가설이 아니다)

**사실** 사용자가 2026-09-12 "후보목록을 그대로 확정해줘. 빠진건 그냥 없는 대로 해줘" 로 지시했다.

**결정** `docs/cad/customer_candidates.json` 의 `후보` 중 `분류` 가 **발주처 후보(12) · 수요처(7)**
인 19종만 `BAS_COMMON_CODES('고객사')` 에 넣었다.
`ATTR1` = `<역할> · 확정 (D-139) — 사용자 확정 2026-09-12 · 관측 기반(견적·발주 수신처·폴더명)`,
`ATTR2` = 확신도(`높음` 8 · `중간` 6 · `낮음` 5), `SORT_ORDER` 는 확신도 높음→중간→낮음.

**넣지 않은 것** 협력사·공급사 16(VEN — 공급자다) · 관계사 1(REL-001 케이테크, D-137 로 경동의
전신 후보) · 타사 도면 소유사 1(REL-002) · 도입기업 본인 1(SELF-001) · 역할 미정 8(UNK) ·
사람이름 17 · 제품명 26 · 출처 의심 36.

**역할을 버리지 않았다** — D-134 가 실측한 2단 구조(`GD2003-00 웰이엔씨` → `-02 에니젠`·`-03 비나텍`)
는 실재한다. `EST_PROJECTS` 에는 고객사 칸이 하나뿐이라 **발주처를 넣고**, 관측된 수요처는
`docs/cad/thread_projects.json` 의 `enduser_codes` 에만 남겼다(프로젝트 2건 — CUST-014·CUST-013).
**수요처 칸 신설은 컬럼 추가라 하지 않았다** — 도입기업에 제안할 항목이다.

**고객사가 확정됐다고 G-08 수치가 실측이 되는 것은 아니다.** 사슬의 대부분(자재LOT 이후)은
여전히 합성이고 게이트 판정 줄에 `합성 데이터 기준 (D-131)` 이 그대로 붙는다.

**아키텍트 확인 요청** `decisions.md` 에 이미 **`D-131-a`** 가 있다(고객사 후보 1차 실측 오류 정정).
내가 쓴 **`D-131`**(합성 데이터 기준)은 오케스트레이터가 지정한 번호이고 `D-131-a` 와 뜻이 다르다.
**같은 자리에 두 뜻이 붙어 있으니 아키텍트가 `decisions.md` 에 `D-131` 행을 명시해 주기 바란다.**
코드·테스트·화면 배지에 이미 51곳 이상 박혀 있어 내가 임의로 갈아치우지 않았다.
