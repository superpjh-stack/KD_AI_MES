# QA3 — AI · HITL · 비기능 · 보안 (G-14 ~ G-30)

경동글로벌텍 제조AI 플랫폼 (SF26179182) · 2026-09-11 · **단독 실행**(다른 에이전트 0 — §10-11)

## 0. 한 줄 요약

```
QA3 몫 17 게이트:  PASS 5 · FAIL 4 · 차단 6 · 판정 불가 2
전체 게이트표:      PASS 14 · FAIL 7 · 차단 11 · 미구현 0 / 32     (미구현 17 → 0)
빌드:              1197 passed, 3 skipped, 3 xfailed   (QA3 테스트 52건 추가, 회귀 0)
```

**G-14~G-19 는 `차단`이 정직한 판정이다.** 라벨 0건 · 예측 0건 · 학습 0회 · CAD 파서 미확보이므로
정확도의 **분모가 없다**. 합성 라벨·합성 예측으로 80%·85%·±5% 를 만들지 않았다.
**G-25·G-26·G-27·G-29 는 FAIL** 이다 — 데이터 부재와 무관하게 **코드 경로가 0곳**인 것들이다.

### 판정 요약

| 게이트 | 판정 | 한 줄 근거 |
|---|---|---|
| G-14 CAD 객체 인식 80% | **차단** | 정답 박스 0 · 예측 0 · `EST_CAD_OBJECTS` 0 → 분모 0 |
| G-15 견적 ±5% | **차단** | `EST_ML_PREDICTIONS` 0 · `EST_QUOTATIONS` 0 · Label 0 (D-04) |
| G-16 BOM 85% | **차단** | `EST_BOM_HEADERS` 0 · 기준 BOM 0 · 항목 0 (D-04·D-47) |
| G-17 납기 85% | **차단** | `TARGET_TYPE='납기'` 예측 0 · 허용 오차가 가설 (D-12) |
| G-18 설명가능성 90% | **차단** | `EST_SHAP_FACTORS` 0 + **전문가 변수 목록 부재**(D-13) |
| G-19 CAD 견적 5단계 | **차단** | 1단계 인식이 501 에서 멈춘다 · 종단 통과 0건 |
| G-20 RAG 폐쇄형·로그 100% | **PASS** | 외부 통신 0 · `AGT_QUERY_LOGS` **30/30 = 100%** · Agent 3종 |
| G-21 인용 정확도 | **판정 불가** | 목표치 부재(D-09) — 실측 23/23 만 보고 |
| G-22 환각 방지 | **PASS** | 근거 0건 7건 전부 LLM 미호출 · 지어낸 출처 0 |
| G-23 RAG 지연 | **판정 불가** | 목표 부재(D-09) — 실측 p50 7ms / p95 9ms 만 보고 |
| G-24 HITL | **PASS** | 확정 엔드포인트 6 × 6역할 = 36회 실측, 기대 어긋남 0 |
| G-25 MLOps | **FAIL** | 5/5 미충족 — **롤백 경로 코드 0곳** |
| G-26 전송·저장 보안 | **FAIL** | **CSRF 0/27** (D-60/D-73 독립 재확인) |
| G-27 계정·잠금 | **FAIL** | **POST /login 0곳 · 잠금 연결 0곳 · 복잡도·주기 강제 0곳 · 로그아웃 0곳** |
| G-28 RBAC 6×8 | **PASS** | 270회 실측 불일치 0 · EXEC = 조회/승인(등록·수정 없음) |
| G-29 감사 | **FAIL** | 45화면 중 **16개 접속 미기록** · `오류` 로그 0곳 · URL 평문 비밀번호 |
| G-30 조용한 실패 | **PASS** | DB 503 · LLM 501 · CAD 배지 · 수집 중단 · 그리드 이스케이프 |

> `tools/gate.py` 는 `판정 불가` 를 `차단`으로 집계한다. 그래서 전체표에서 G-21·G-23 은 `차단` 칸에 들어간다.

### 검증 명령 (전부 이 리포트의 숫자를 만든 것)

```bash
make db-reset
uv run python tools/check_ai.py          # G-14~G-25
uv run python tools/check_security.py    # G-26~G-30
uv run pytest -q tests/test_qa3_ai.py tests/test_qa3_security.py   # 52 passed
uv run pytest                            # 1197 passed, 3 skipped, 3 xfailed
uv run python tools/gate.py              # PASS 14 · FAIL 7 · 차단 11 · 미구현 0 / 32
```

**재현성**: `make db-reset` 뒤 두 검사기를 **연속 2회** 돌려 판정 줄을 diff 했다 — `check_security` 는
완전 동일, `check_ai` 는 G-23 의 `max` 만 8ms↔9ms 로 달랐다(시간 측정값이라 당연하다). 나머지 전부 동일.

---

## 1. 결함 (DEF-QA3-nnn)

### DEF-QA3-001 · **Critical** · CSRF 가 POST 27개 중 **0곳**에 연결돼 있다 — 담당 **전원(아키텍트 조율)**

**재현**
```bash
grep -rn "csrf\.require(" src/ | grep -v util/csrf.py   # → 0 건
grep -rln "_csrf" src/kyungdong/app/templates/          # → 0 건
grep -rc "@router.post(\|@app.post(" src/ | ...         # → 27 개
uv run python -c "...; print(csrf.enforced())"          # → False
```
**실측** — POST 라우트 **27** · `csrf.require()` 호출 **0** · 템플릿 `_csrf` **0** ·
`KYUNGDONG_CSRF_ENFORCE=0`. 화면 상단에 `CSRF 미적용 (D-60)` 배지는 **실제로 뜬다**(GET `/` 본문 확인).
`util/csrf.py` 구현 자체는 동작한다 — 다른 바인딩 토큰이 거부되는 것까지 실측했다
(`test_qa3_security.py::test_g26_csrf_token_binds_to_session`).

**기대** — 쓰기 27경로 전부 폼 `_csrf` + 핸들러 `csrf.require()` 를 지나고 `CSRF_ENFORCE=1`.
**D-60/D-73 을 내가 독립적으로 다시 셌고, "0곳" 이 맞다.** 지금 `1` 로 올리면 쓰기 27개가 전부 403 이 된다 —
**폼·핸들러를 먼저 고친 뒤에 켜야 한다.**

---

### DEF-QA3-002 · **Critical** · 로그인 처리·로그아웃·실패 잠금이 **어디에도 연결되지 않았다** — 담당 **개발1**

**재현**
```bash
grep -rn "@app.post(\"/login\|@router.post(\"/login" src/     # → 0 건
grep -rn "ratelimit\." src/ | grep -v util/                   # → 0 건
grep -rn "session.destroy\|/logout" src/                      # → 0 건
```
**실측** — `GET /login` 화면은 있고 정책값(최소길이 10 · 주기 90일 · 계정 5회 · IP 20회 · 유휴 30분)을
**표시**한다. 그런데 `POST /login` **0곳**, 로그아웃 **0곳**, `ratelimit` 호출 **0곳**이다.
모듈 자체는 동작한다 — 계정 5회/IP 20회에서 정확히 막히고(`가설 (D-16)` 사유 문자열 포함),
세션 유휴 30분 초과 시 서버측 레지스트리에서도 지워지는 것을 실측했다.

**기대** — 인증 경로가 붙고 실패 시 `ratelimit.record_failure` → `blocked` 를 지난다.
**"장치는 있는데 연결이 없다"** 가 D-52 가 경고한 형태(설정만 있고 구현이 없다)와 같은 계열이다.

---

### DEF-QA3-003 · **High** · 비밀번호 복잡도·주기 변경을 **강제하는 코드가 0곳** — 담당 **개발1**

**재현**
```bash
grep -rn "PASSWORD_MIN_LEN\|PASSWORD_CHANGE_CYCLE_DAYS" src/
# → settings.py(정의) · main.py(로그인 화면 표시) 뿐. 검증·만료 판정 0곳
```
**실측** — `SYS_USERS.PWD_CHANGED_DT` 는 채워지지만 **읽는 코드가 없다**.
`/sys/026` 사용자 등록은 난수 12바이트를 쓰므로 우연히 길이를 만족할 뿐, 검증하지 않는다.
**기대** — 최소 길이·문자종류 검증 함수와 주기 초과 시 강제 변경 유도. 값은 `가설 (D-16)` 이므로
**수치를 바꾸지 말고 강제 경로만 붙인다.**

---

### DEF-QA3-004 · **High** · 45화면 중 **16개가 조회해도 접속 감사 로그를 남기지 않는다** — 담당 **개발2**

**재현** — 45화면을 SYSADMIN 으로 한 번씩 GET 하고 `SYS_ACCESS_LOGS` `LOG_TYPE='접속'` 증분을 센다
(`tools/check_security.py` G-29-①, `test_qa3_security.py::test_g29_sixteen_screens_do_not_log_access`).

**실측** — 기록 남음 **29/45** · 남지 않음 **16/45**:
`/dsh/001·002·003·004` · `/prc/021·022·023·024·025` · `/shp/016·017·018·019` · `/kpi/043·044·045`

URL 접두별 (로그 남음, 안 남음):
`agt (5,0)` · `bas (3,0)` · `dat (5,0)` · `est (6,0)` · `inv (5,0)` · `sys (4,0)` ·
**`dsh (0,4)` · `prc (0,5)` · `shp (1,4)` · `kpi (0,3)`**

**원인은 공용 가드 두 개의 차이다.**
- 개발1 의 `routers/bas.py:37 guard()` 는 **안에서 `audit(...)` 를 부른다**(`log_type="변경" if write else "접속"`).
  `inv.py`·`dat.py`·`sys.py` 가 이 `guard` 를 import 해 쓰므로 자동으로 기록이 남는다.
- 개발2 의 `routers/dsh.py:47 guard()` 는 **`audit` 을 부르지 않는다.**
  `prc.py`·`shp.py`·`kpi.py` 가 이 `guard` 를 쓰므로 16화면이 통째로 빈다.
  (`/shp/020` 만 기록이 남는데, 그 화면은 개발3 의 `agt.py` 소유다 — OWNER_OVERRIDE.)

**기대** — 사업계획서 9.2 ① "접속·변경·API·오류" 전 화면 기록. 조회도 감사 대상이다.
**고치는 자리는 `dsh.guard` 한 곳**이다 — 16화면을 각각 고칠 일이 아니다.

---

### DEF-QA3-005 · **High** · `LOG_TYPE='오류'` 를 남기는 코드가 **0곳** — 담당 **아키텍트 + 개발1**

**재현**
```bash
grep -rno 'log_type="오류"' src/       # → 0 건
# 호출 분포: 접속 0(기본값) · 변경 5 · API 7 · 오류 0
```
**실측** — `util/audit.py` 는 `LOG_TYPES = ("접속","변경","API","오류")` 를 선언하지만 `오류` 는 한 번도
쓰이지 않는다. `main.py` 의 전역 500 핸들러(`on_unhandled`)·HTTPException 핸들러 둘 다
`SYS_ACCESS_LOGS` 에 쓰지 않는다(주석에 "기록은 SYS_ACCESS_LOGS(개발1)" 이라고만 적혀 있다).
**403·422·500·503 이 하나도 감사에 남지 않는다.**

**기대** — 오류 계약(§2.5) 경로가 `audit(..., log_type="오류", result="오류", error=...)` 를 지난다.

---

### DEF-QA3-006 · **High** · 발급 비밀번호가 **URL 쿼리스트링**으로 전달된다 — 담당 **개발1**

**재현** — `src/kyungdong/app/routers/sys.py:151`
```python
return redirect(f"/sys/026?issued={raw}&issued_for={v['login_id']}")
```
**실측** — 난수 발급 자체는 옳다(저장소 리터럴 0건 실측). 그러나 **평문 비밀번호가 URL 에 실린다** —
브라우저 이력 · `Referer` 헤더 · 리버스 프록시/웹서버 액세스 로그에 그대로 남는다.
**기대** — POST-리다이렉트 후 서버측 1회성 저장(플래시)이나 같은 응답 본문에 렌더. URL 에 넣지 않는다.

---

### DEF-QA3-007 · **High** · MLOps — **롤백 경로 0곳 · 모델 등록 쓰기 경로 0곳** — 담당 **개발3**

**재현**
```bash
grep -rniE "update\s+EST_ML_MODELS|set\s+DEPLOY_STATUS|def \w*(rollback|deploy|promote)\w*\(" src/
# → 0 건
grep -rniE "insert\s+into\s+EST_ML_MODELS" src/     # → 0 건
```
**실측** — `ml/registry.py` 는 **읽기 전용**이다. `EST_ML_MODELS`·`EST_ML_TRAIN_RUNS`·`EST_ML_PREDICTIONS`
0행, `DAT_DATASET_SPLITS` 0행. G-25 의 5항목이 **5/5 미충족**이다.
**성능·버전·상태 3항목은 학습 미실시라 분모 0(차단 성격)이지만, 롤백 경로는 데이터와 무관한 코드 부재**이므로
게이트 전체를 `FAIL` 로 적었다. `차단`으로 낮추지 않았다.

`DAT_DATASET_SPLITS` 0행은 **개발3 의 판단이 옳다** — Train/Val/Test 비율이 정본에 없어 넣지 않았다.
다만 `docs/cad/라벨링 가이드.docx` 는 "프로젝트 단위 70:15:15" 를 권고한다 — **정본 승격 여부는 아키텍트 몫**이다.
여기서 비율을 정하지 않았다.

---

### DEF-QA3-008 · **Medium** · RAG 임계 0.70(가설 D-10)이 실측 점수 분포와 맞지 않아 **정확히 검색된 근거를 거절한다** — 담당 **개발3 + 아키텍트**

**재현** — `work/rag_goldset.json` 30건을 `agent.service.ask` 로 돌린다(`tools/check_ai.py` G-20~G-23).

**실측** — 근거형 23건은 **최상위 근거 문서가 23/23 정확**하고 핵심어도 23/23 포함된다.
그런데 정규화 점수 분포가 **최소 0.4167 · 중앙값 ≈ 0.60 · 최대 0.8125** 라서,
임계 0.70 을 넘는 것은 **6/23** 뿐이다. 나머지 **17건은 근거가 맞는데도 `검토 필요 — 근거 부족`** 으로 떨어진다.

되돌림 시험(임계별 '근거 부족' 건수): `{0.0: 7, 0.70: 24, 0.99: 30}`
→ **0.0 에서도 7건이 남는다** = 근거 0건 분기는 임계와 무관하게 항상 적용된다(D-10 처리란 그대로다. 옳다).

**기대** — 임계값은 정본에 없다(D-10). **그러므로 값을 여기서 바꾸지 않았다.**
점수 정규화 방식(`ts_rank_cd/(rank+1)` 과 바이그램 `hit/len(grams)` 가 **같은 축이 아니다**)을 먼저 정리하고,
임계를 실측 분포 위에서 다시 정하라. **지금 임계를 낮춰 게이트를 넘기는 것은 금지다.**

---

### DEF-QA3-009 · **Medium** · API 감사 기록이 두 갈래에서 빠진다 — 담당 **개발3**

**실측**

| 갈래 | 응답 | `SYS_ACCESS_LOGS` |
|---|---|---|
| `POST /api/agent/query` (JSON) | 200 | **0 행** |
| `POST /inv/009` 정상 갈래 | 200 | 1 행 (`API`) — 정상 |
| `POST /inv/009` LLM 미구성 갈래 | 501 | **0 행** |

`audit()` 가 `service.ask()` **뒤에** 있어 예외 갈래를 지나친다. `AGT_QUERY_LOGS` 에는 501 도 남는다
(100% 기록은 지켜진다 — G-20 PASS). 감사 쪽만 빈다.
**기대** — JSON API 엔드포인트에도 `audit(log_type="API")`, 예외 갈래는 `try/finally` 또는 `log_type="오류"`.

---

### DEF-QA3-010 · **Medium** · CAD 견적 5단계 화면 중 **Confidence Score 와 근거를 함께 보여주는 화면이 1/5** — 담당 **개발3**

**실측** (SYSADMIN GET, 본문 문자열 검사)

| 화면 | 응답 | Confidence/신뢰도 | 근거 |
|---|---|---|---|
| `/est/010` | 200 | 있음 | **없음** |
| `/est/011` | 200 | 있음 | 있음 |
| `/est/012` | 200 | 있음 | **없음** |
| `/est/013` | 200 | **없음** | 있음 |
| `/est/015` | 200 | 있음 | **없음** |

**기대** — G-19 는 "각 단계에 Confidence Score **와 근거**" 를 함께 요구한다.
데이터가 0건이어도 **자리와 라벨은 있어야** 값이 들어왔을 때 검증 가능하다.

---

### DEF-QA3-011 · **Medium** · 라벨링 계획의 클래스·모집단이 TD5·D-03 과 어긋난다 — 담당 **아키텍트 → 도입기업**

**실측** — `docs/cad/라벨링 가이드.docx`

| 항목 | 라벨링 가이드 | 이 사업의 정본 |
|---|---|---|
| 클래스 | `title_block` · `bom_table` · `rev_table` **3종** | TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` = 홀·슬롯·노즐·플랜지·치수문자 **5종** |
| 심볼 검출 | "노즐·플랜지·용접기호는 **2차 고도화 단계에서 별도 프로젝트**" | 이번 사업의 G-14 측정 대상 |
| 모집단 | "DWG·PDF **835건**" | D-03 / `cad_inventory` 실측 **1,283건** |
| 라벨 수량 | "목표 물량 MVP 100장 → 권장 300장" (계획) | 현재 **0건** |

**기대** — G-14 를 무엇으로 잴지가 정해지지 않았다. **어느 쪽이 맞는지 여기서 정하지 않았다.**
도입기업에 ① 클래스 매핑 확정 ② G-14 모집단 확정 ③ 라벨 산출물 인도를 요청한다.

---

### DEF-QA3-012 · **Medium** · `SHP_INSPECTIONS` 에 앱 쓰기 경로가 **0곳** — 담당 **개발2**

**재현** — `grep -rniE "(insert into|update)\s+SHP_INSPECTIONS" src/` → **0 건**
(`db/seed_dev2.py` 와 테스트에만 있다).

**실측** — 화면 018 검사결과관리는 **조회 전용**이고 POST 가 없다.
즉 G-24 의 "승인 없이 `SHP_INSPECTIONS` 가 바뀌는 경로 0" 이 **통제 때문이 아니라 구현 부재로 성립한다.**
계약 §6 은 "검사 합격 판정 = 품질 담당 승인" 을 요구한다.

**기대** — 018 에 판정 쓰기 경로가 붙을 때 `rbac.can_approve(role, "출하물류관리")` 를 반드시 지난다.
`test_qa3_ai.py::test_g24_inspections_have_no_write_path_yet` 가 **경로가 생기는 순간 실패**해서
G-24 재측정을 강제한다.

---

### 관찰 (결함으로 올리지 않음 — 정본 판단이 필요한 것)

- **`SUPPLIER_OPS`(공급기업 운영담당)가 `사용자/시스템관리` 에 등록·수정 권한을 갖는다.**
  TD3 `role_matrix` 셀이 `설정 지원` 이고 `rbac._parse_cell` 이 `설정` 을 write 로 해석한다.
  DB 권한행과 TD3 정본은 **완전히 일치**하므로(불일치 0건) 이것은 구현 결함이 아니라 **정본 해석 문제**다.
  최소 권한 관점에서 외부 운영담당이 계정 등록(`POST /sys/026`)을 할 수 있는 것이 의도인지 확인이 필요하다.
- **저장 암호화**: 개인정보 6컬럼은 마스킹만 있고 저장 암호문이 아니다(`SYS_USERS.USER_NAME` 표본 `총괄PM/경영자`).
  `contracts/db-schema.md` §6 은 "암호화 저장 + 화면 마스킹" 이라고 적었지만
  **알고리즘이 사업계획서에 없다(D-15).** 다른 사업의 AES-256 같은 값을 여기에 적지 않았다 —
  **사양 확정 전까지 이 항목은 판정 대상이 아니다.**
- **HTTPS 강제 미들웨어 0곳**: `HTTPSRedirectMiddleware`·`TrustedHostMiddleware` 가 없다.
  배포 형상(리버스 프록시 종단 vs 앱 종단)이 정본에 없어 **결함으로 올리지 않았다.** 사실만 적는다.

---

## 2. 통과 — 실측값과 명령

### G-20 · RAG Agent 3종 폐쇄형 + 질의이력 100% — **PASS**

```bash
uv run python tools/check_ai.py      # "── G-20 폐쇄형 · 질의이력 100% 기록 ──"
```
- **외부 검색 0**: `src/kyungdong/**` 전체에서 `requests·httpx·urllib·aiohttp·socket·boto3·openai`
  import **0건**, 외부 URL 문자열 **0건**. CSP 는 전 지시자가 `'self'`.
- **질의이력 100%**: 정답셋 30건 실행 → `AGT_QUERY_LOGS` **+30행 (30/30)**.
  질의·응답·응답시간이 빈 행 **0**. **501 로 끝난 갈래도 로그가 먼저 남는다**(실측).
- **Agent 3종**: 기록된 `AGENT_TYPE` = `['입고','출하','통합']` (TD5 어휘).
  화면 `/inv/009`·`/shp/020`·`/agt/038` 전부 200 이고 **폐쇄형 선언 문구**가 렌더된다.
- **접근범위 격리**: 입고 Agent → 클레임 매뉴얼 노출 **0건**, 출하 Agent → 입고 SOP 노출 **0건**.

### G-22 · 환각 방지 — **PASS**

```bash
uv run pytest -q tests/test_qa3_ai.py::test_g22_no_evidence_never_calls_llm
```
- **LLM 을 "구성된 것처럼" 세워 놓고 감시자를 끼워** 측정했다. 미구성 상태에서는 501 이 먼저 나서
  호출 여부를 구분할 수 없기 때문이다.
- 근거 0건 **7건 전부**: LLM 호출 **0** · 응답 정확히 `검토 필요 — 근거 부족` · 담당자 이관 문구 있음 ·
  `sources == []`.
- **N건 경로도 단언**: 임계를 넘는 근거형에서는 LLM 이 **6/23** 실제로 호출된다(0이면 경로가 죽은 것이다).
- **지어낸 출처 0건**: 모든 응답의 `sources` ⊆ 실제 검색된 문서명. `citations.py` 가 모델 응답이 아니라
  **실제 조회한 `AGT_VECTOR_DOCS` 행**에서만 출처를 만든다.

### G-24 · HITL — **PASS**

```bash
uv run python tools/check_ai.py      # "── G-24 HITL ──"
uv run pytest -q tests/test_qa3_ai.py -k g24
```
- **정적**: 승인 필요 5표를 바꾸는 코드 위치 **5곳** — `est.py:274`(QUOTATIONS) · `est.py:337`(BOM) ·
  `shp.py:182·230`(SHIPMENTS) · `cad/pipeline.py:168`(CAD_OBJECTS). `SHP_INSPECTIONS` **0곳**(DEF-QA3-012).
- **동적**: 확정 엔드포인트 6개 × 6역할 = **36회 실측, 기대 어긋남 0**.
  승인 권한 없는 역할은 전부 **403**, 승인 권한 있는 역할(EXEC·SYSADMIN)은 **403 이 아니다**(422 = 대상 없음).
- **D-84 재발 없음**: EXEC 는 `/est/011/review`·`/est/012/confirm`·`/est/013/confirm`·`/shp/016/approve` 를
  통과하고, **등록**인 `/shp/016` 에서는 **403** 을 받는다. 승인만 가능하고 등록은 못 한다 — 계약대로다.
- **승인 흔적 없는 확정 행 0**: `EST_QUOTATIONS` 승인+승인자 없음 0 · `SHP_SHIPMENTS` 확정+승인자 없음 0 ·
  `EST_CAD_OBJECTS.CONFIRM_YN='Y'` 0 · `EST_OBJECT_REVIEWS` 0.
- `CONFIRM_YN` 을 바꾸는 코드는 `pipeline.review_object` **하나뿐**이고 그 안에서 `rbac.can_approve` 를 지난다.

### G-28 · RBAC 6역할 × 8권한영역 — **PASS**

```bash
uv run python tools/check_security.py    # "── G-28 ──"
```
- 6역할 × 8권한영역 = **48셀**. DB `SYS_ROLE_PERMISSIONS` ↔ TD3 `role_matrix` **불일치 0건**(6×10=60행 대조).
- 45화면 × 6역할 = **270회 GET**: 권한 있음 252회(403 아님) · **권한 없음 18회 전부 403** · 불일치 **0**.
  → **0건 경로가 아니다** — 403 을 18회 실제로 쟀다.
- 좌측 메뉴 노출 위반 **0건**(권한 없는 경로가 메뉴에 보이지 않는다).
- **EXEC = 조회/승인**: `수주견적AI관리`·`출하물류관리` 둘 다 셀 `조회/승인` → read True · write **False** · approve True.
  **D-84 에서 한 번 틀렸던 지점이고, 이번엔 맞다.**

### G-30 · 조용한 실패 사냥 — **PASS**

```bash
uv run python tools/check_security.py    # "── G-30 ──"
```

| 죽인 것 | 결과 | 판정 |
|---|---|---|
| **DB** (`KYUNGDONG_PG_DSN` → 죽은 포트) | `/dsh/001` **503** + `서비스 일시 중단` · `/inv/006` **503** | 빈 그리드로 위장하지 않는다 |
| **LLM** (미구성) | 임계 초과 질의(신뢰도 0.7692) → **501** + `LLM 미구성` | 폴백 문장을 만들지 않는다 |
| 〃 근거 0건 갈래 | **200** + `검토 필요 — 근거 부족` | 계약대로 |
| **CAD 파서** (미구성) | `/est/010` 200 + **미구성 배지** · `analyze()` **501** | 합성 Feature 0 |
| **시뮬레이터** (수집 중단) | 0건 → `미수집` · 앵커 −2h → **`수집 중단` + 마지막 수집시각** 둘 다 `/dsh/003`·`/prc/022` 에 표시 | — |
| **그리드 이스케이프** | `<script>alert('qa3')</script>` 질의 → `/agt/042` 에 원문 **없음**, `&lt;script&gt;` **있음** | 저장형 XSS 없음 |

- 템플릿 `|safe` **실제 사용 0곳**(주석 언급 1곳은 "쓰지 않는다" 는 규칙 문장이다).
- **백엔드 죽임은 직접 재지 못했다** — 이 검사기는 서버를 띄우지 않는다. 대신 폴백 표면을 셌다:
  JS 파일 **0** · 인라인 `<script>` **0** · `fetch`/`XHR` **0**. 전 화면 서버 렌더라
  백엔드가 죽으면 브라우저가 연결 실패를 그대로 보여 준다. **브라우저 실측은 하지 않았다** — 그 사실을 적어 둔다.

---

## 3. 차단 — 왜 못 쟀는지

> 여기 수치가 없는 것은 **없어서**다. 없는 것을 만들지 않았다.

### G-14 CAD 객체 인식 80% (IoU 0.5 · P/R/F1)

| 필요한 것 | 실측 |
|---|---|
| 정답 박스(ground truth) | **0건** — `docs/cad/` 는 xlsx·pptx·docx 뿐. YOLO 라벨(`labels/*.txt`)·`classes.txt`·Label Studio JSON **0개** |
| 예측 박스 | **0건** — `KYUNGDONG_CAD_PARSER`·`KYUNGDONG_CAD_VISION_MODEL` 미설정 (D-05) |
| `EST_CAD_OBJECTS` | **0행** |
| 라벨 클래스 | 가이드 3종(`title_block`·`bom_table`·`rev_table`) ≠ TD5 5종 (DEF-QA3-011) |

→ TP/FP/FN 의 **분모가 0**이다. `work/cad_labelset.json` 의 `labels`·`predictions` 는 **빈 배열**이고,
왜 비었는지를 파일 안에 적었다.

**평가기는 만들어 두었고 동작을 확인했다** — 다만 그 확인용 합성 입력은 `evaluator_selftest`
(`gate_input: false`)에 격리했고 **G-14 실측란에 쓰지 않았다**. 되돌림 시험 결과:

| IoU 임계 | TP | FP | FN |
|---|---|---|---|
| 0.2 | 2 | 1 | 1 |
| 0.5 | 1 | 2 | 2 |
| 0.9 | 0 | 3 | 3 |

임계를 바꾸면 혼동행렬이 **실제로 움직인다**(3회 전부 다른 값). 광성 사업에서 `check_ai` 가 판정 함수를
안 불러 "설정을 바꿔도 소수점까지 동일" 했던 사고의 재발 여부를 이렇게 확인했다.

### G-15 견적 ±5% · G-16 BOM 85% · G-17 납기 85% · G-18 설명가능성 90%

`ml.registry.readiness()` (정본 함수) 실측:

```
datasets 1 · dataset_items 0 · labeled_items 0 · splits 0
drawings 0 · confirmed_objects 0 · features 0 · cost_rates 0
models 0 · runs 0
EST_ML_PREDICTIONS 0 · EST_SHAP_FACTORS 0 · EST_QUOTATIONS 0 · EST_BOM_HEADERS 0
```

| 게이트 | 분모가 0인 이유 |
|---|---|
| G-15 | 예측·실제 쌍 0 → MAPE·MAE·±5% 비율 전부 없음. **제품군별 오차 분포도 나눌 표본이 없다**. Label 미확보(D-04) |
| G-16 | 기준 BOM(수동) 0 · `EST_BOM_ITEMS` 0 · `EST_BOM_ROUTINGS` 0 → 자재·수량·공정 항목 단위 대조 불가. 품목·재질 코드 그룹이 비어 있어(D-47) BOM 전개 자체가 막혀 있다 |
| G-17 | `TARGET_TYPE='납기'` 예측 0 → 허용 오차 내 정확도·RMSE 불가. 허용 오차 3일은 **가설 (D-12)** 이고 정본에 범위가 없다 |
| G-18 | `EST_SHAP_FACTORS` 0 (`EST_ML_PREDICTIONS` FK 라 예측 없이 생길 수 없다) + **전문가 평가 변수 목록 부재(D-13)** — 일치율의 **정답 쪽이 존재하지 않는다**. Spearman ρ 는 표본 2 미만이면 `None` 을 돌려준다(0.0 으로 메우지 않는다) |

**개발3 이 `EST_ML_*` 를 의도적으로 만들지 않은 것은 옳다** — `ml/registry.py` 는 읽기 전용이고
`TARGETS` 를 "목표치이고 달성값이 아니다" 라고 명시한다. **성능 수치를 만들지 않았다.**

### G-19 CAD 견적 5단계 종단 통과

`cad.pipeline.stage_status()` (정본 함수) 실측 — 5단계 전부 0건:

| 단계 | 표 | 건수 | 차단 |
|---|---|---|---|
| ① 수집·인식 | `IF_CAD_FILES → EST_CAD_OBJECTS` | 0 | **예** — 공급자 2종 모두 미구성 |
| ② HITL 검증 | `EST_OBJECT_REVIEWS` | 0 | 아니오 (승인 대상이 없다) |
| ③ Feature·BOM | `EST_CAD_FEATURES` | 0 | **예** — 집계 가능 Feature 1/6종 |
| ④ 견적 | `EST_QUOTATIONS` | 0 | **예** — 단가 기준 없음 (D-04) |
| ⑤ SHAP | `EST_SHAP_FACTORS` | 0 | **예** — 예측 0건 |

**0건 경로와 N건 경로를 둘 다 단언했다**(`skip` 하지 않았다): `EST_CAD_DRAWINGS` 가 0행이므로
검사기가 도면 1건을 임시로 넣고 `analyze()` 를 불러 **501 `CAD Parsing 미구성 (D-05)`** 를 확인한 뒤
그 행을 지웠다. `build_features()` 는 확정객체 0 → 생성 0 · 차단 Feature **5/6종**.
**조용히 합성 Feature 를 내지 않는 것까지 확인했다.**

`make cad-ingest`(도면 995건)는 **돌리지 않았다** — 이번 판정에 필요한 건 "도면 1건이 있어도 1단계가
501 에서 멈춘다" 이고, 그건 임시 1행으로 충분했다. 995건을 넣으면 다른 게이트의 0건 경로가 오염된다.

### G-21 인용 정확도 · G-23 RAG 응답 지연 — **판정 불가 (목표치 부재 D-09)**

**사업계획서에 목표 수치가 없다. 그래서 PASS/FAIL 을 붙이지 않고 실측만 적는다.**

**G-21 실측** (정답셋 근거형 23건)
- 최상위 근거 문서 일치 **23/23 (100%)**
- 기대 핵심어 전량 포함 **23/23**
- 근거없음형 **7/7 이 근거 0건** — 지어낸 출처 0
- **한계**: `AGT_VECTOR_DOCS` 가 **2청크 / 2문서**뿐이다(`quote_and_procurement_guide.md` 는 TD5
  `DOC_TYPE` 어휘에 맞는 구분이 없어 미임베딩 — D-303). **이 100% 는 검색 정확도의 상한을 증명하지 않는다.**
  문서가 늘면 정답셋을 다시 만들어야 한다.

**G-23 실측** (30질의)
- p50 **7 ms** · p95 **9 ms** · max **9 ms** · n 30
- 검색 모드 `tsvector_keyword`(임베딩 미구성 — D-08), `KYUNGDONG_RAG_TIMEOUT_SEC=10` `가설 (D-09)`
- **이것은 검색 구간만의 실측이다.** LLM 이 미구성이라 **생성 지연이 포함되지 않았다.**
  LLM 이 붙으면 다시 재야 한다 — 이 숫자를 "RAG 응답시간" 으로 쓰면 안 된다.

---

## 4. 검사기가 정본 함수를 부르는지 — 되돌림 시험 (§10-16)

광성 사업에서 `check_ai` 가 판정 함수를 안 불러 **설정을 바꿔도 혼동행렬까지 소수점 동일**했던 사고가 있었다.
같은 일이 없는지 **설정을 바꿔 수치가 실제로 움직이는지** 확인했다.

| 바꾼 설정 | 부르는 정본 함수 | 결과 | 움직였나 |
|---|---|---|---|
| `KYUNGDONG_RAG_CONFIDENCE_MIN` 0.0 / 0.70 / 0.99 | `retrieval.search` · `retrieval.confidence` · `settings()` | '근거 부족' 건수 **7 / 24 / 30** | **예** |
| `KYUNGDONG_CAD_IOU_THRESHOLD` 0.2 / 0.5 / 0.9 | `check_ai.match` (`settings().cad_iou_threshold` 를 읽는다) | TP/FP/FN **(2,1,1) / (1,2,2) / (0,3,3)** | **예** |
| `KYUNGDONG_ENV=prod` + `SESSION_SECRET` | `settings()` · `security.headers()` | 기동 거부 → HSTS 부착 | **예** |
| `KYUNGDONG_PG_DSN` → 죽은 포트 | `conn._connect` · `http.fail("db_down")` | 200 → **503** | **예** |

검사기가 직접 부르는 정본 함수: `agent.service.ask` · `agent.retrieval.{search,confidence,corpus_size}` ·
`agent.citations` · `agent.llm.state` · `cad.pipeline.{stage_status,analyze,build_features}` ·
`cad.provider.availability` · `ml.registry.{readiness,models,train_runs,predictions,shap_factors}` ·
`ml.datasets.{datasets,splits,label_coverage}` · `app.rbac.{roles,perm_for,can_*}` · `app.settings.settings` ·
`util.{security.headers,csrf.*,session.*,ratelimit.*,pii.mask}` · `ingest.collector.{status,ingest_batch}`.

**로직 복제 0** — 임계·허용 오차·잠금 한도·IoU 값을 검사기 안에 박지 않았다. 전부 `settings()` 에서 읽는다.

---

## 5. 내가 하지 않은 것 (하면 안 되는 것이라서)

- **합성 라벨·합성 예측을 만들지 않았다.** G-14~G-18 의 분모를 채우면 80%·85%·±5% 를 만들 수 있었다.
  `차단`으로 남겼다.
- **RAG 임계값을 내리지 않았다.** 0.70 → 0.55 로만 내려도 G-21·G-22 의 "근거 부족" 건수가 확 줄어
  보기 좋아진다. D-10 은 가설이고 정본에 수치가 없다 — **QA 가 정할 값이 아니다**(DEF-QA3-008 로 넘겼다).
- **TLS 버전·저장 암호화 알고리즘을 적지 않았다.** 사업계획서에 없다(D-15). 다른 사업의 사양을
  정본인 척 옮겨 적지 않았다.
- **터치 버튼 크기·응답시간 같은 목표 없는 항목에 남의 기준을 끌어오지 않았다**(QA1 D-82 와 같은 판단).
- **`make cad-ingest` 를 돌리지 않았다.** 995건이 들어오면 다른 게이트의 0건 경로가 오염된다.
  필요한 N건 경로는 도면 **1행**을 임시로 넣고 지우는 것으로 충분했다.
- **`G-25` 를 `차단`으로 낮추지 않았다.** 롤백 경로는 데이터 부재와 무관한 코드 부재라 `FAIL` 이다.
- **`skip` 을 한 번도 쓰지 않았다.** QA3 테스트 52건 중 skip **0건**(D-62 가 실례다).
  데이터가 없으면 0건 경로를 단언하고, N건 경로는 테스트 안에서 만들었다가 되돌렸다.

---

## 6. 상태 되돌림 (§10-11)

- 검사기 2종은 **자기가 넣은 행만** 삭제한다(시작 시점 max id 기준):
  `AGT_QUERY_LOGS` · `SYS_ACCESS_LOGS` · `DAT_DOWNLOAD_LOGS` · `IF_PLC_SIGNALS` ·
  `PRC_EQUIP_SIGNALS` · `DAT_TIMESERIES` · `EST_CAD_DRAWINGS`(probe 1행).
- 테스트 52건도 넣은 행을 `finally` 에서 전부 지운다.
- **마감 시 `make db-reset` 으로 공통 시드로 되돌렸다.** 비밀번호는 계정별 난수이고
  `seed_accounts()` 는 **이미 있는 계정의 비밀번호를 건드리지 않는다** — 재실행이 남의 로그인을 깨지 않는다.
  (§10-11 의 사고: `check_ai` 가 끝나며 시드를 되돌려 다른 에이전트 테스트를 401 로 죽였다.
  이번엔 **단독 실행**이었고 되돌림도 마지막에 한 번만 했다.)

---

## 7. 담당자별 넘길 것

| 담당 | 결함 |
|---|---|
| **전원 (아키텍트 조율)** | DEF-QA3-001 **CSRF 0/27 (Critical)** — 폼·핸들러 먼저, 그다음 `CSRF_ENFORCE=1` |
| **개발1** | DEF-QA3-002 **로그인·로그아웃·잠금 미연결 (Critical)** · DEF-QA3-003 비밀번호 정책 미강제 · DEF-QA3-006 URL 평문 비밀번호 |
| **개발2** | DEF-QA3-004 16화면 접속 감사 미기록 · DEF-QA3-012 `SHP_INSPECTIONS` 쓰기 경로 부재 |
| **개발3** | DEF-QA3-007 MLOps 롤백 경로 0곳 · DEF-QA3-009 API 감사 2갈래 누락 · DEF-QA3-010 5단계 Confidence·근거 1/5 |
| **아키텍트** | DEF-QA3-005 `오류` 감사 로그 0곳(전역 핸들러) · DEF-QA3-008 D-10 임계 재검토 · DEF-QA3-011 라벨 클래스·모집단 정본 충돌 |
| **도입기업 요청** | CAD 정답 박스(YOLO/Label Studio 내보내기) · 클래스 매핑 확정 · 과거 견적금액·실제 제조원가 Label(D-04) · 전문가 평가 변수 목록(D-13) · Train/Val/Test 비율 · TLS/저장 암호화 사양(D-15) |

---

## 8. 내가 만든 파일

| 파일 | 내용 |
|---|---|
| `tools/check_ai.py` | G-14~G-25. IoU/P/R/F1 · MAPE/MAE · Spearman ρ · RAG 정답셋 실행 · HITL 36회 실측 · MLOps |
| `tools/check_security.py` | G-26~G-30. prod 프로파일 · CSRF 계수 · RBAC 270회 · 감사 4종 · 조용한 실패 6종 |
| `work/rag_goldset.json` | 30건 (근거형 23 · **근거없음형 7**) + 접근범위 격리 2건 + 이스케이프 probe 1건. **`AGT_VECTOR_DOCS` 본문에서만** 만들었고 `D-nn` 같은 문서 식별자를 핵심어로 요구하지 않았다(§10-7) |
| `work/cad_labelset.json` | 정답·예측 **빈 배열** + 왜 비었는지 · 평가기 자기검증(격리, `gate_input: false`) |
| `tests/test_qa3_ai.py` | 23건 — 차단 표지 포함. 해소되면 **실패해서** 리포트 갱신을 강제한다 |
| `tests/test_qa3_security.py` | 29건 — 〃 |
| `outputs/qa3-AI비기능보안.md` | 이 문서 |
