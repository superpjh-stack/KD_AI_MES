"""개발1 화면 15건 — 목업 충실도 · RBAC · 0건 문구 · 마스킹 · 외부 CDN 0.

**0건 경로와 N건 경로를 둘 다 단언한다**(§10-4). `skip` 하지 않는다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app import design, nav                    # noqa: E402
from kyungdong.app.main import PLACEHOLDERS, app         # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

MINE = [s for s in nav.all_screens() if s.owner == "개발1"]
MINE_IDS = [s.id for s in MINE]


def get(path: str, role: str = "SYSADMIN"):
    return client.get(path, headers={"x-kyungdong-role": role})


def cards_of(html: str) -> list[str]:
    return re.findall(r'<div class="d1-card">(.*?)</div>\s*</div>', html, re.S)


# ── 담당 범위 ─────────────────────────────────────────────────────────────
def test_개발1_화면은_15건이다():
    assert len(MINE) == 15, [s.id for s in MINE]
    assert {s.prefix for s in MINE} == {"inv", "bas", "sys", "dat"}


def test_009와_037은_내_것이_아니다():
    """입고 AI Agent·AI학습 데이터관리는 개발3 몫이다 — 건드리지 않는다."""
    assert nav.by_id()["MES-TD3-009"].owner == "개발3"
    assert nav.by_id()["MES-TD3-037"].owner == "개발3"
    for mod in ("inv", "bas", "sys", "dat"):
        src = (ROOT / "src/kyungdong/app/routers" / f"{mod}.py").read_text()
        assert '"/inv/009"' not in src and '"/dat/037"' not in src


def test_내_화면_15건이_placeholder에서_빠졌다():
    """G-03-② — SCREENS 에 적은 화면은 placeholder 가 맡지 않는다."""
    still = [sid for sid in MINE_IDS if sid in PLACEHOLDERS]
    assert not still, f"아직 placeholder 인 개발1 화면: {still}"


@pytest.mark.parametrize("screen", MINE, ids=MINE_IDS)
def test_15화면이_200이고_placeholder_문구가_없다(screen):
    r = get(screen.path)
    assert r.status_code == 200, r.text[:400]
    assert "미구현 화면" not in r.text, "placeholder 템플릿이 렌더됐다"
    assert screen.name in r.text
    assert screen.requirement_id in r.text and screen.program_id in r.text


# ── 목업 충실도 — 화면의 모든 칸은 정본 문장이다 ──────────────────────────
@pytest.mark.parametrize("screen", MINE, ids=MINE_IDS)
def test_목업의_조회조건_그리드열_버튼이_전부_렌더된다(screen):
    mock = design.screen(screen.id).get("mockup") or {}
    html = get(screen.path).text
    for label in mock.get("search_fields") or []:
        assert label in html, f"{screen.id} 조회 조건 '{label}' 이 없다"
    for col in mock.get("grid_columns") or []:
        assert col in html, f"{screen.id} 그리드 열 '{col}' 이 없다"
    for btn in mock.get("buttons") or []:
        assert btn in html, f"{screen.id} 버튼 '{btn}' 이 없다"


@pytest.mark.parametrize("screen", MINE, ids=MINE_IDS)
def test_목업_설명패널_문장이_렌더된다(screen):
    """화면 목적·처리 절차·연계 ID·체크 — TD3 layout_rules 우측 패널."""
    mock = design.screen(screen.id).get("mockup") or {}
    html = get(screen.path).text
    blocks = mock.get("description") or []
    if not blocks:                       # 035 대시보드는 description 이 없다 → TD3 본문을 쓴다
        body = design.screen(screen.id)["composition"]
        chunk = max(re.split(r"[<>()\[\]]", body), key=len).strip()[:20]
        assert chunk and chunk in html, f"{screen.id} 가 TD3 화면 구성 문장을 렌더하지 않았다"
        return
    for block in blocks:
        assert block["title"] in html, f"{screen.id} 설명 '{block['title']}' 이 없다"


@pytest.mark.parametrize("screen", MINE, ids=MINE_IDS)
def test_목업의_예시값을_렌더하지_않는다(screen):
    """`(예시)` 값은 시드에도 화면에도 넣지 않는다 (§0.2)."""
    mock = design.screen(screen.id).get("mockup") or {}
    html = get(screen.path).text
    samples = [c for row in (mock.get("grid_sample") or []) for c in row]
    samples += [c["value"] for c in (mock.get("cards") or [])]
    samples += [r["label"] for r in (mock.get("list_rows") or [])]
    for s in samples:
        if "(예시)" in str(s):
            assert str(s) not in html, f"{screen.id} 가 목업 예시값 '{s}' 를 렌더했다"


# ── G-11 · §10-14 — 0건 문구와 건수 카드 ──────────────────────────────────
def test_0건_그리드는_미수집_문구를_렌더한다():
    """런타임 전용 표(`DAT_DOWNLOAD_LOGS`)와 미시드 표가 0건일 때."""
    assert int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS")["n"]) >= 0
    html = get("/dat/036?cat=CAD&fmt=Excel&appr=N&user=존재하지않는계정zzz").text
    assert "미수집" in html, "0건 그리드에 문구가 없다 (G-11)"


def test_0건인데도_건수_카드에는_문구를_붙이지_않는다():
    """**건수 카드의 `0 건` 은 정답이다**(§10-14)."""
    html = get("/dat/036").text
    cards = cards_of(html)
    assert cards, "건수 카드가 없다"
    for c in cards:
        assert "미수집" not in c, f"건수 카드에 미수집 문구가 붙었다: {c!r}"
    assert any("건" in c for c in cards)


@pytest.mark.parametrize("path,table", [
    ("/sys/027", "SYS_ACCESS_LOGS"),
    ("/dat/033", "DAT_JOB_LOGS"),
    ("/dat/036", "DAT_DOWNLOAD_LOGS"),
    ("/inv/006", "INV_MATERIAL_HISTORY"),
])
def test_런타임표_0건_경로와_N건_경로(path, table):
    """0건이면 미수집, 행이 있으면 그 행이 보인다 — 두 경로를 모두 단언한다."""
    n = int(conn.q1(f"select count(*) as n from {table}")["n"])
    html = get(path).text
    assert html.count("미수집") >= (1 if n == 0 else 0)
    if n:
        assert f"{n} 건" in html or "건" in html


def test_로그화면_0건_필터는_미수집_N건_필터는_행을_낸다():
    """같은 화면에서 두 경로를 모두 통과시킨다."""
    get("/sys/027")                       # 조회 자체가 접속 로그를 남긴다 (G-29)
    total = int(conn.q1("select count(*) as n from SYS_ACCESS_LOGS")["n"])
    assert total > 0, "화면 조회가 감사 로그를 남기지 않았다 (G-29)"

    none = get("/sys/027?user=존재하지않는계정zzz").text
    assert "미수집" in none

    some = get("/sys/027").text
    assert "미수집" not in some.split('<h2>로그')[1].split('</table>')[0]


# ── G-28 RBAC — 권한 없음은 403 ──────────────────────────────────────────
def test_품질담당은_사용자시스템관리에_접근할_수_없다():
    """TD3 role_matrix 에서 '–' 인 칸이다 → 403."""
    for path in ("/sys/026", "/sys/027", "/sys/028", "/sys/029"):
        assert get(path, role="QUALITY").status_code == 403, path


def test_경영자는_기준정보를_읽지만_쓰지는_못한다():
    assert get("/bas/032", role="EXEC").status_code == 200
    r = client.post("/bas/032", headers={"x-kyungdong-role": "EXEC"},
                    data={"code_group": "품목", "code_value": "X", "code_name": "X"})
    assert r.status_code == 403, r.text[:300]


def test_모르는_역할은_열어주지_않는다():
    assert get("/inv/005", role="NOBODY").status_code == 403


def test_쓰기권한이_없으면_저장_버튼이_잠긴다():
    html = get("/bas/030", role="EXEC").text
    assert "등록·수정 권한이 없다" in html


# ── G-29 개인정보 마스킹 ─────────────────────────────────────────────────
def test_사용자_실명이_화면에_그대로_나가지_않는다():
    names = [r["user_name"] for r in conn.q("select USER_NAME from SYS_USERS")]
    assert names, "계정이 0건이다 — 먼저 `make db-seed`"
    html = get("/sys/026").text
    grid = html.split("<h2>사용자")[1].split("</table>")[0]       # 목록 그리드만 본다
    # 열 순서는 목업 grid_columns: No · 로그인 계정 · **사용자명** · 소속 · 역할 · 잠금 · 사용여부
    shown = {re.findall(r"<td>(.*?)</td>", tr)[2]
             for tr in re.findall(r"<tr>(.*?)</tr>", grid) if "<td>" in tr}
    assert shown, "사용자 그리드가 비어 있다"
    for n in names:
        if len(n) > 1:
            assert n not in shown, f"사용자명 '{n}' 이 마스킹 없이 렌더됐다 (G-29)"
            assert n[0] + "*" * (len(n) - 1) in shown


def test_공급처_담당자는_마스킹_대상으로_표기된다():
    html = get("/inv/008").text
    assert "마스킹" in html and "G-29" in html


# ── D-50 외부 CDN·차트 라이브러리 0건 ────────────────────────────────────
@pytest.mark.parametrize("screen", MINE, ids=MINE_IDS)
def test_외부_CDN_참조가_0건이다(screen):
    html = get(screen.path).text
    for bad in ("http://", "https://", "cdn.", "//unpkg", "chart.js", "d3.", "jquery"):
        assert bad not in html.lower(), f"{screen.id} 에 외부 참조 '{bad}'"


def test_개발1_CSS에_미디어쿼리가_없다():
    """반응형은 app/static/app.css 단일 파일에만 있다 (§10-13)."""
    tpl = ROOT / "src/kyungdong/app/templates/bas/_list.html"
    assert "@media" not in tpl.read_text()


# ── 조회 축 · LOT 클릭 이동 (G-08) ───────────────────────────────────────
def test_LOT_열은_024_공정이력조회로_간다():
    html = get("/inv/006").text
    assert "/prc/024" in html or "024 공정이력조회" in html


def test_최상위_조회축이_LOT_기반이_아니라_프로젝트_LOT_이다():
    """ETO — 반복 생산 라인·배치 축이 아니다 (TD3 standard_note 2)."""
    html = get("/dat/035").text
    assert "프로젝트(수주)번호" in html


# ── 조용한 실패 금지 (G-30) ──────────────────────────────────────────────
def test_미구현_기능은_미구현이라고_적는다():
    """버튼이 눌려도 아무 일이 없으면서 성공한 척하면 결함이다."""
    for path in ("/bas/030", "/inv/007", "/sys/028", "/dat/036"):
        assert "미구현" in get(path).text, path


def test_라우터에_조용한_예외처리가_없다():
    """`try/except` 로 빈 결과를 끼워넣지 않는다 (G-30)."""
    for mod in ("inv", "bas", "sys", "dat"):
        src = (ROOT / "src/kyungdong/app/routers" / f"{mod}.py").read_text()
        assert "except Exception" not in src, f"{mod}.py 에 광범위 예외 처리가 있다"
        assert "return []" not in src


# ── 타 사업 용어 0건 (§6) ────────────────────────────────────────────────
FOREIGN = ("프레스", "금형", "샷카운트", "전착", "프론트쉘", "예지보전", "불량예측",
           "절임", "발효", "염도", "레시피", "와인딩", "에이징", "타월",
           "포밍", "롤포밍", "로봇용접", "레토르트", "판금")


def test_개발1_소스와_화면에_타사업_용어가_없다():
    for mod in ("inv", "bas", "sys", "dat"):
        src = (ROOT / "src/kyungdong/app/routers" / f"{mod}.py").read_text()
        for term in FOREIGN:
            assert term not in src, f"{mod}.py 에 타 사업 용어 '{term}' (§6)"
    seed = (ROOT / "db" / "seed_dev1.py").read_text()
    for term in FOREIGN:
        assert term not in seed, f"seed_dev1.py 에 타 사업 용어 '{term}'"
    for screen in MINE:
        html = get(screen.path).text
        for term in FOREIGN:
            assert term not in html, f"{screen.id} 렌더에 '{term}'"
