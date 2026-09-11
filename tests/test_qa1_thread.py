"""QA1 ④ 디지털 스레드 — LOT·프로젝트번호 클릭 → `/prc/024` (G-08) · 추적 검사기 (G-04 · G-05).

api-contract §0-5: **LOT·프로젝트번호 열은 클릭 가능**하고 `/prc/024`(공정이력조회)로 간다.

데이터 의존 금지 (§10-4)
  · LOT 열이 있는 화면 **11개 전부**에 대해 **0건 경로**를 단언한다 — 0건이면 링크가 없는 것이
    정답이고, 대신 0건 표지가 보여야 한다.
  · **N건 경로**는 이 파일이 제품 LOT 1건을 세워 실증한다. `skip` 하지 않는다.
  · 발견한 결함은 `xfail(strict=True)` 로 박아 둔다 — **고쳐지면 그때 이 테스트가 실패해서**
    누구도 모르게 지나가지 않는다. (그냥 통과시키면 결함이 테스트에 묻힌다)

**QA 는 고치지 않는다.** 결함 번호는 `outputs/qa1-기능계약.md` 에 있다.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                   # noqa: E402
from kyungdong.app import design, nav                          # noqa: E402
from kyungdong.app.main import app                             # noqa: E402
from kyungdong.app.util import clock                           # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

HISTORY = "/prc/024"
EMPTY_MARKS = ("미수집", "미확정", "0 건", "없다")

PJ_NO = "PJT-QA1THR-001"
LOT_NO = "PLOT-QA1THR-001"
QSTD = "QSTD-QA1THR-1"
CUSTOMER, ITEM = "CUST-QA1THR", "PG10"
MARK = "tests/test_qa1_thread.py 임시 — 끝나면 지운다"


def lot_screens() -> list[nav.Screen]:
    """TD3 목업 `grid_columns` 에 LOT·프로젝트번호 열이 있는 화면 — 정본에서 뽑는다."""
    out = []
    for s in nav.all_screens():
        cols = design.screen(s.id)["mockup"].get("grid_columns") or []
        if any("LOT" in c or "프로젝트" in c for c in cols):
            out.append(s)
    return out


LOT_SCREENS = lot_screens()


def grid_html(path: str, **params) -> str:
    r = client.get(path, params={"as": "SYSADMIN", **params})
    assert r.status_code == 200, f"{path} → {r.status_code}"
    return r.text


def _plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def main_grid(body: str, columns: list[str]) -> str:
    """화면의 **본 그리드** `<table>` 만 집어낸다.

    화면에는 설명 패널·차단 사유 표가 함께 있다(TD3 layout_rules '설명 패널'). 그걸 데이터 행으로
    세면 0건 화면이 N건으로 보인다 — 정본 `grid_columns` 머리글로 본 그리드를 가린다.
    """
    for table in re.findall(r"<table[^>]*>.*?</table>", body, re.S):
        head = _plain(re.search(r"<thead>.*?</thead>", table, re.S).group(0)
                      if re.search(r"<thead>.*?</thead>", table, re.S) else "")
        if all(c in head for c in columns[:3]):
            return table
    return ""


def grid_rows(body: str, columns: list[str]) -> int:
    """본 그리드의 **데이터 행만** 센다. 0건 안내 행(`colspan=`)은 행이 아니다(§10-14)."""
    table = main_grid(body, columns)
    n = 0
    for part in re.findall(r"<tbody>(.*?)</tbody>", table, re.S):
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", part, re.S):
            if 'class="empty"' in tr or "colspan=" in tr:
                continue
            n += 1
    return n


def grid_text(body: str, columns: list[str]) -> str:
    """본 그리드 안쪽 글자만. 조회조건 입력칸에 남은 검색어를 데이터로 착각하지 않기 위해서다."""
    table = main_grid(body, columns)
    return _plain("".join(re.findall(r"<tbody>(.*?)</tbody>", table, re.S)))


def cols_of(screen: nav.Screen) -> list[str]:
    return design.screen(screen.id)["mockup"]["grid_columns"]


# ── 대상 화면 목록 자체가 정본에서 나오는가 ──────────────────────────────
def test_LOT열이_있는_화면이_11개다():
    got = {s.path for s in LOT_SCREENS}
    assert got == {"/est/010", "/est/012", "/est/013", "/inv/005", "/inv/006",
                   "/prc/024", "/shp/016", "/shp/017", "/shp/018", "/shp/019",
                   "/dat/034"}, f"LOT 열 화면이 바뀌었다: {sorted(got)}"


def test_공정이력조회_화면이_G08_목적지다():
    s = nav.by_path()[HISTORY]
    assert s.id == "MES-TD3-024" and s.name == "공정이력조회"


# ── 0건 경로 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("screen", LOT_SCREENS, ids=lambda s: s.no)
def test_0건경로_LOT조건이_안_맞으면_링크없이_0건표지를_낸다(screen):
    """§10-4 — 0건도 **명시로** 단언한다. 없는 LOT 을 지어내지 않는다."""
    nope = "QA1-존재하지않는LOT-zzz"
    cols = cols_of(screen)
    body = grid_html(screen.path, lot=nope, q0=nope, no=nope, project=nope)
    assert main_grid(body, cols), f"{screen.path}: 정본 grid_columns 로 본 그리드를 못 찾았다"
    assert grid_rows(body, cols) == 0, f"{screen.path}: 없는 LOT 조건인데 데이터 행이 나왔다"
    assert nope not in grid_text(body, cols), f"{screen.path}: 없는 LOT 을 그리드에 지어냈다"
    assert any(m in html.unescape(body) for m in EMPTY_MARKS), \
        f"{screen.path}: 0건인데 표지가 없다 — 조용한 빈 화면 (G-30)"
    assert f'href="{HISTORY}?lot={nope}"' not in body, \
        f"{screen.path}: 0건인데 LOT 링크가 만들어졌다"


def test_0건경로_공정이력조회는_없는_LOT에도_200이고_0건이다():
    cols = cols_of(nav.by_path()[HISTORY])
    body = grid_html(HISTORY, lot="QA1-존재하지않는LOT-zzz")
    assert grid_rows(body, cols) == 0
    assert "미수집" in html.unescape(body)
    assert "이력 건수" in html.unescape(body), "0건 카드가 사라졌다 — `0 건` 은 정답이다(§10-14)"


# ── N건 경로 — 제품 LOT 1건을 세워 실증한다 ──────────────────────────────
@pytest.fixture(scope="module")
def one_lot():
    _cleanup()
    a = clock.anchor()
    for group, value, name in (("고객사", CUSTOMER, "QA1 테스트 고객사"), ("품목", ITEM, "반응기")):
        conn.x("insert into BAS_COMMON_CODES (CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, "
               "USE_YN, ATTR1, CREATED_DT) values (%s,%s,%s,91,'Y',%s, now()) "
               "on conflict (CODE_GROUP, CODE_VALUE) do nothing", (group, value, name, MARK))
    conn.x("insert into BAS_QUALITY_STANDARDS (QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, "
           "INSPECT_ITEM, STANDARD_SPEC, UOM, USE_YN, APPLY_FROM, CREATED_DT) "
           "values (%s,%s,%s,%s,%s,%s,'Y',%s, now())",
           (QSTD, ITEM, "수압시험", "압력", "ASME / KS", "bar", a.date()))
    conn.x("insert into EST_PROJECTS (PROJECT_NO, CUSTOMER_CODE, PRODUCT_GROUP, PROJECT_NAME, "
           "ORDER_CONFIRM_DT, DUE_DT, PROJECT_STATUS, CREATED_DT) "
           "values (%s,%s,%s,%s,%s,%s,%s, now())",
           (PJ_NO, CUSTOMER, ITEM, "QA1 디지털스레드 확인용", a - timedelta(hours=100),
            (a + timedelta(days=5)).date(), "생산"))
    pid = int(conn.q1("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = %s",
                      (PJ_NO,))["project_id"])
    conn.x("insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, CURRENT_PROCESS, "
           "TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) values (%s,%s,%s,%s,%s, now())",
           (LOT_NO, pid, "P90", "진행", "Y"))
    lot_id = int(conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                         (LOT_NO,))["lot_trace_id"])
    qstd_id = int(conn.q1("select QSTD_ID from BAS_QUALITY_STANDARDS where QSTD_CODE = %s",
                          (QSTD,))["qstd_id"])
    conn.x("insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, MEASURED_VALUE, "
           "UOM, JUDGE_RESULT, INSPECT_DT, CREATED_DT) values (%s,%s,%s,%s,%s,%s,%s, now())",
           (lot_id, qstd_id, "압력", 12, "bar", "합격", a))
    for seq, code in ((1, "P10"), (9, "P90")):
        conn.x("insert into PRC_PROCESS_HISTORIES (LOT_TRACE_ID, PROCESS_CODE, PROCESS_SEQ, "
               "IN_DT, OUT_DT, DWELL_HOUR, HIST_STATUS, CREATED_DT) "
               "values (%s,%s,%s,%s,%s,%s,%s, now())",
               (lot_id, code, seq, a - timedelta(hours=10 - seq), a, 2, "정상"))

    yield {"lot_id": lot_id, "lot_no": LOT_NO, "project_no": PJ_NO}

    _cleanup()
    assert conn.q1("select 1 as x from EST_PROJECTS where PROJECT_NO = %s", (PJ_NO,)) is None
    assert conn.q1("select 1 as x from BAS_COMMON_CODES where ATTR1 = %s", (MARK,)) is None


def _cleanup() -> None:
    row = conn.q1("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = %s", (PJ_NO,))
    if row:
        pid = row["project_id"]
        conn.x("delete from SHP_SHIPMENT_ITEMS where SHIPMENT_ID in "
               "(select SHIPMENT_ID from SHP_SHIPMENTS where PROJECT_ID = %s)", (pid,))
        conn.x("delete from SHP_SHIPMENTS where PROJECT_ID = %s", (pid,))
        conn.x("delete from SHP_INSPECTIONS where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = %s)", (pid,))
        conn.x("delete from PRC_PROCESS_HISTORIES where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = %s)", (pid,))
        conn.x("delete from SHP_LOT_TRACES where PROJECT_ID = %s", (pid,))
        conn.x("delete from EST_PROJECTS where PROJECT_ID = %s", (pid,))
    conn.x("delete from BAS_QUALITY_STANDARDS where QSTD_CODE = %s", (QSTD,))
    conn.x("delete from BAS_COMMON_CODES where CODE_GROUP = any(%s) and CODE_VALUE = any(%s) "
           "and ATTR1 = %s", (["고객사", "품목"], [CUSTOMER, ITEM], MARK))


def _lit_screens(lot_no: str) -> dict[str, str]:
    """LOT 을 조건으로 줬을 때 **행이 실제로 나온** 화면들."""
    out = {}
    for s in LOT_SCREENS:
        cols = cols_of(s)
        body = grid_html(s.path, lot=lot_no, q0=lot_no, no=lot_no)
        if grid_rows(body, cols) > 0 and lot_no in grid_text(body, cols):
            out[s.path] = body
    return out


def test_N건경로_LOT을_세우면_최소_3개_화면에_행이_뜬다(one_lot):
    lit = _lit_screens(one_lot["lot_no"])
    assert set(lit) >= {"/shp/017", "/shp/018", HISTORY}, (
        f"제품 LOT 1건을 세웠는데 뜬 화면이 {sorted(lit)} 뿐이다 — "
        "전제(LOT추적·검사결과·공정이력)가 안 선다")


def test_N건경로_LOT셀이_전부_공정이력조회로_간다(one_lot):
    """G-08 — 행이 **뜬 화면 전부**에서 LOT 셀이 링크여야 한다."""
    lit = _lit_screens(one_lot["lot_no"])
    assert lit, "N건 경로가 하나도 안 떴다"
    bad = [p for p, body in lit.items() if f'{HISTORY}?lot={one_lot["lot_no"]}' not in body]
    assert not bad, f"LOT 이 보이는데 /prc/024 링크가 없는 화면: {bad}"


def test_N건경로_공정이력조회가_LOT과_프로젝트_두_축으로_찾힌다(one_lot):
    """TD3 standard_note 2 — 최상위 조회 축은 프로젝트(수주)번호다. LOT 은 하위 식별자다."""
    cols = cols_of(nav.by_path()[HISTORY])
    by_lot = grid_html(HISTORY, lot=one_lot["lot_no"])
    by_pj = grid_html(HISTORY, project=one_lot["project_no"])
    assert grid_rows(by_lot, cols) >= 2, "LOT 으로 공정이력이 안 나온다"
    assert grid_rows(by_pj, cols) >= 2, "프로젝트번호로 공정이력이 안 나온다"
    assert one_lot["lot_no"] in grid_text(by_pj, cols)


@pytest.mark.xfail(strict=True, reason=(
    "DEF-QA1-004 — est.py 가 **프로젝트번호**를 `/prc/024?lot=` 로 보낸다. "
    "024 의 `lot` 은 SHP_LOT_TRACES.PRODUCT_LOT_NO 필터라 절대 안 맞는다. "
    "`?project=` 여야 한다 (담당 개발3)"))
def test_프로젝트번호는_project파라미터로_가야_한다(one_lot):
    cols = cols_of(nav.by_path()[HISTORY])
    pj = one_lot["project_no"]
    assert grid_rows(grid_html(HISTORY, lot=pj), cols) > 0, \
        "프로젝트번호를 ?lot= 으로 보내면 공정이력이 0건이다 — est.py 의 링크가 죽어 있다"


def test_프로젝트번호를_project로_보내면_살아_있다(one_lot):
    """위 xfail 의 대조군 — `?project=` 는 정상이다. 링크 파라미터만 틀렸다는 근거."""
    cols = cols_of(nav.by_path()[HISTORY])
    assert grid_rows(grid_html(HISTORY, project=one_lot["project_no"]), cols) > 0


# ── G-04 · G-05 검사기 (tools/check_trace.py) ────────────────────────────
def _run_checker() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / "check_trace.py")],
                          capture_output=True, text=True, timeout=600, cwd=ROOT)


def test_추적검사기가_게이트별_판정줄을_찍는다():
    """§10-6 — `gate.py` 가 파싱한다. 줄이 없으면 게이트가 `미구현` 으로 남는다."""
    r = _run_checker()
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("G-04", "G-05"))]
    assert len(lines) == 2, f"판정 줄 {len(lines)}개: {r.stdout[-500:]}"
    assert any(v in lines[0] for v in ("PASS", "FAIL", "판정 불가"))
    assert r.returncode in (0, 1, 2)


def test_G04_요구사항추적이_1대1이다():
    r = _run_checker()
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("G-04"))
    assert "PASS" in line, line


def test_G04_정본_함수로_45건이_전부_묶인다():
    """검사기와 같은 정본 함수(`design.trace`)로 다시 센다(§10-16)."""
    ok = [no for no in (f"{i:03d}" for i in range(1, 46))
          if all(design.trace(no)[k] for k in ("requirement", "screen", "program"))]
    assert len(ok) == 45, f"묶인 것 {len(ok)}건"
    nonfunc = [n for n in (f"{i:03d}" for i in range(46, 59)) if design.screen(f"MES-TD3-{n}")]
    assert nonfunc == [], f"비기능 요구사항에 화면이 생겼다: {nonfunc}"


def test_G05_프로그램_49건이_화면45_더하기_인터페이스4다():
    progs = set(design.programs())
    screens = {s.program_id for s in nav.all_screens()}
    assert len(progs) == 49 and len(screens) == 45
    assert progs - screens == {f"MES-TD4-{n}" for n in ("046", "047", "048", "049")}


@pytest.mark.xfail(strict=True, reason=(
    "DEF-QA1-001 — api-contract §3 은 인터페이스 4건의 연계 상태를 `/dat/033` 에서 본다고 "
    "적었는데 그 화면에 4건이 없다. `/sys/029` 에는 4/4 가 있다 (담당 개발1)"))
def test_G05_dat033이_인터페이스_연계상태_4건을_보여준다():
    body = client.get("/dat/033", params={"as": "SYSADMIN"}).text
    shown = [p for p in ("MES-TD4-046", "MES-TD4-047", "MES-TD4-048", "MES-TD4-049")
             if p in body or (design.program(p) or {}).get("name", "＃") in body]
    assert len(shown) == 4, f"/dat/033 인터페이스 연계 상태 {len(shown)}/4 — 보이는 것 {shown}"


def test_인터페이스_4건은_sys029에서는_보인다():
    """위 xfail 의 대조군 — 화면 자체는 있고 **위치가 계약과 다르다**는 근거."""
    body = client.get("/sys/029", params={"as": "SYSADMIN"}).text
    shown = [p for p in ("MES-TD4-046", "MES-TD4-047", "MES-TD4-048", "MES-TD4-049") if p in body]
    assert len(shown) == 4, f"/sys/029 에도 {len(shown)}/4 밖에 없다"
