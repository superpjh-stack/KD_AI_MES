# contracts/interfaces.md — 공용 함수 시그니처

> **동시 기동 시 이 문서가 계약이다.** 파일이 아직 없어도 여기 적힌 시그니처를 믿고 쓴다(goal.md §3).
> **코드와 다르면 코드가 맞다** — 발견자가 이 문서를 고치고 `progress-*.md` 에 적는다.
> 아키텍트 소유. 개발자가 시그니처를 바꾸고 싶으면 `progress-devN.md` 에 요청을 남긴다.

## 1. 정본 읽기 — `kyungdong.app.design`

코드 범위의 정본은 `docs/design/design.json`(SF-TD1~TD5) · `docs/design/analysis.json`(SF-AD1~AD3) 다.
**JSON 을 직접 열지 말고 이 모듈만 쓴다** — 경로·구조가 바뀌면 한 곳만 고친다.

```python
screen(sid: str) -> dict | None            # "MES-TD3-001" — id·name·path·composition·items·checks·tables·channels·mockup·area
screens() -> dict[str, dict]               # 45건
common_screens() -> dict[str, dict]        # login·common·popup·dashboard (4)
role_matrix() -> dict                      # columns(9) · rows(6)
layout_rules() / standard_note()           # TD3 공통 레이아웃·작성 기준

program(pid: str) -> dict | None            # "MES-TD4-001" — description·flow·functions·tables·area
programs() -> dict[str, dict]               # 49건 (화면 45 + 인터페이스 4)
program_tables(pid: str) -> list[str]       # TD4 tables 문자열에서 실제 존재하는 테이블 ID 만

table_def(tid: str) -> dict | None          # "EST_PROJECTS" — area·id·name·programs·columns
tables() -> dict[str, dict]                 # 68건
columns_of(tid) -> list[dict]               # {ko,name,type,pk,fk,nullable,note}

requirement(rid: str) -> dict | None        # "MES-AD2-001" — description·details·constraints·kind·area
requirements() -> dict[str, dict]           # 58건
functional_ids() / nonfunctional_ids()      # 45 / 13

trace(no: str) -> dict                      # "001" → {requirement, screen, program}  (G-04)
selfcheck() -> dict[str, tuple[int,int,bool]]   # 정본 규모 ↔ goal.md 표 대조
```

**`screen()`·`program()`·`requirement()` 가 `None` 을 주면 지어내지 않는다** — `util.http.undetermined("D-nn")`
문구를 렌더한다(goal.md §0.2).

## 2. DB — `db.conn`

```python
q(sql, params=None)  -> list[dict]     # 여러 행. DB 장애는 503 이고 빈 리스트가 아니다
q1(sql, params=None) -> dict | None    # 한 행. None 은 정상적인 0건 → 화면은 '미수집' 문구 (G-11)
x(sql, params=None)  -> int            # 쓰기. 영향 행 수
tx()                 -> ContextManager[Cursor]   # 트랜잭션. 예외는 롤백 후 **다시 던진다**
alive()              -> bool           # /health·게이트용. **여기서만** 예외를 삼킨다
table_count() / column_count() -> int  # G-01 · G-02
```

- 행은 `dict`, 키는 **TD5 영문명 소문자**(`project_no`, `lot_no`).
- **파라미터는 항상 바인딩**한다. f-string 으로 SQL 을 만들지 않는다.
- **`try/except` 로 빈 배열을 돌려주지 않는다.** DB 가 죽으면 503 이 화면에 보여야 한다(G-30).
- 코드성 FK 29건은 DB 가 막지 않는다 → 저장 전 §5 `validate_code()` 로 확인한다(D-32).

## 3. 렌더 — `kyungdong.app.templating`

```python
render(request, name: str, status_code: int = 200, **ctx) -> HTMLResponse
```

- 공통 컨텍스트는 자동 주입: `menu`(권한 있는 것만) · `role` · `system_name` · `env` · `search_mode` ·
  `llm_configured` · `cad_configured`.
- **autoescape 가 기본**이다. 그리드 셀에 `|safe` 를 쓰지 않는다(§10-8). 링크 셀은 `Markup.format`.
- 반응형은 `app/static/app.css` **단일 파일**에만 둔다. 개발자별 CSS 에 미디어쿼리를 쓰지 않는다(§10-13).

## 4. 권한 — `kyungdong.app.rbac`

```python
roles() -> dict[str, Role]                       # 6역할 (EXEC·QUALITY·PRODUCTION·OPERATOR·SUPPLIER_OPS·SYSADMIN)
perm_for(role_code, area) -> Perm                # Perm(read, write, approve, label)
can_read(role_code, area)    -> bool             # False → 403
can_write(role_code, area)   -> bool             # False → 403
can_approve(role_code, area) -> bool             # 견적 확정·발주·검사 합격·출하 승인 (G-24)
```

`area` 는 **TD3 업무영역 문자열**이다(`"수주견적AI관리"`). 권한영역 8개로의 매핑은 rbac 가 안다.
모르는 역할·영역은 **권한 없음**으로 본다 — 열어주지 않는다.

## 5. 오류·문구 — `kyungdong.app.util.http`

```python
fail(key: str, detail: str = "") -> HTTPException     # 계약 밖 key 는 KeyError (몰래 새 상태 금지)
undetermined(decision: str) -> str                    # "미확정 (D-13)"
not_collected(decision: str) -> str                   # "미수집 (D-06)"
CASES: tuple[ErrorCase, ...]                          # 401 403 422 500 501×2 503
NOTICE_EMBEDDING / NOTICE_RAG_NO_EVIDENCE / NOTICE_INGEST_STALE
```

`key` 목록: `validation`(422) · `unauthenticated`(401) · `forbidden`(403) · `db_down`(503) ·
`llm_unconfigured`(501) · `cad_unconfigured`(501) · `internal`(500).

**공용 4종 — 구현 완료**

```python
codes.validate_code(group, value) -> bool              # D-32 코드성 FK 검증
codes.require_code(table, column, value) -> None       # 저장 전 호출. 위반 시 422
pii.mask(value, kind) -> str                           # G-29 (name·phone·email·generic)
clock.anchor() -> datetime                             # 시간 앵커 (§10-3, date.today() 금지). 없으면 예외
audit.audit(request, screen_id, action, ...) -> None   # SYS_ACCESS_LOGS (G-29)
```

**CSRF — `kyungdong.app.util.csrf` (D-105, 개발1 이 부재를 발견해 추가)**

```python
csrf.issue(request) -> str                # 렌더 시 발급. 세션(없으면 CSRF 쿠키)에 묶인다
csrf.require(request, token) -> None      # 쓰기 처리 **첫 줄**. 위반 시 403
csrf.valid(request, token) -> bool
csrf.enforced() -> bool                   # KYUNGDONG_CSRF_ENFORCE
FORM_FIELD = "_csrf" · HEADER = "X-CSRF-Token" · COOKIE = "kyungdong_csrf"
```

쓰기 폼이 있는 화면은 **전부** 아래 두 줄을 넣는다.
```html
<input type="hidden" name="_csrf" value="{{ csrf_token }}">
```
```python
csrf.require(request, form.get("_csrf"))   # POST 처리 첫 줄
```
**강제 적용 시점**: 개발 3명이 전부 끝난 **조용한 창**에서 미들웨어로 켠다 —
돌고 있는 동안 켜면 진행 중인 POST 가 403 으로 깨진다.

## 6. 설정 — `kyungdong.app.settings`

```python
settings() -> Settings
  .pg_dsn .env .port .is_prod .session_secret .csrf_enforce
  .llm_configured .embed_configured .cad_configured .search_mode
  .h(key) -> Hypothesis(value, decision, what, badge)      # 가설값 11종
```

**가설값은 `.env` 한 곳에만 둔다. 코드 상수 금지**(§10-1). 화면에는 `h(key).badge` = `가설 (D-nn)` 를 띄운다.

## 7. 메뉴·소유 — `kyungdong.app.nav`

```python
menu() -> list[tuple[str, list[Screen]]]    # (바로가기, 화면들) — td3.menu_shortcuts 순서, 10영역
all_screens() -> list[Screen]               # 45건
by_id() / by_path() -> dict
owned_by(owner: str) -> list[Screen]        # "개발1" | "개발2" | "개발3"
modules() -> dict[str, list[Screen]]        # routers 모듈별
Screen: id no name area shortcut path prefix owner module program_id requirement_id channels
```

## 8. 담당 라우터 등록 규약

`app/main.py` 는 **담당 라우터가 있으면 그것을 싣고, 없는 화면만 `_placeholder`** 로 세운다.
개발자는 `main.py` 를 건드리지 않고 자기 파일에 두 개만 둔다.

```python
# app/routers/inv.py  (개발1)
from fastapi import APIRouter
router = APIRouter()
SCREENS = ("MES-TD3-005", "MES-TD3-006", "MES-TD3-007", "MES-TD3-008")   # 이 화면들을 내가 맡는다

@router.get("/inv/005")
async def receipt(request: Request): ...
```

`SCREENS` 에 적은 화면은 placeholder 에서 빠진다. 경로는 `contracts/screen-map.md` §1 의 값을 그대로 쓴다.

## 9. 아직 계약이 없는 것 — 만들 사람이 여기에 적고 시작한다

| 무엇 | 담당 | 비고 |
|---|---|---|
| `ingest` 수집 API — 태그 매핑 → 수집 → 시계열 적재 → 이력 | 개발3 | TD4-047. `IF_PLC_SIGNALS` → `PRC_EQUIP_SIGNALS`/`DAT_TIMESERIES`. **수집 지점 2개소뿐**(D-06) |
| `cad` 업로드·파싱 API | 개발3 | TD4-048. 미구성이면 **501**(D-05). 조용한 합성 금지 |
| `app/kpi.py` KPI 산식 단일 소스 | 개발2 | `LEADTIME_MFG` · `LEADTIME_O2D`(D-35). 대시보드·현황판·043~045 가 **같은 함수**를 쓴다 |
| 인증 — `app/auth.py` | 개발1 | bcrypt/Argon2. 들어오면 `main.py` 의 역할 전환 미들웨어(D-40)를 **제거**한다 |
| 채번 — 프로젝트번호·도면번호·LOT·출하번호 | 개발1 | 형식을 정하면 `progress-dev1.md` §1 에 공표. 규칙은 `BAS_COMMON_CODES` |
