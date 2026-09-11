"""QA1 ① 화면 — 45화면 + 공통 4 + 오류 전부 200 · TD3 목업 항목 일치 (§2.3 · G-03).

**QA 는 고치지 않는다.** 여기서는 개발자가 이미 PASS 라고 보고한 것을 **독립적으로 다시 잰다**.

데이터 의존 금지 (§10-4)
  · **0건 경로를 명시로 단언**한다 — 그리드가 비면 `미수집 (D-nn)` 같은 문구가 **반드시 보여야** 한다.
    아무것도 없이 빈 표만 나오면 "없는 것" 과 "못 읽은 것" 이 구분되지 않는다(G-11 · G-30).
  · `skip` 하지 않는다. 데이터가 없으면 없는 대로 **단언**한다.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav                     # noqa: E402
from kyungdong.app.main import PLACEHOLDERS, app          # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

COMMON_PATHS = ("/", "/login", "/board", "/popup")        # td3.common_screens 4종
ERROR_PATH = "/error"

# 0건일 때 화면이 내야 하는 표지 (§2.5 '200 으로 렌더하되 숨기지 않는 것')
EMPTY_MARKS = ("미수집", "미확정", "0 건", "없다", "검토 필요")


def body(path: str, **params) -> str:
    r = client.get(path, params=params or None)
    assert r.status_code == 200, f"{path} → {r.status_code}"
    return html.unescape(r.text)


# ── 200 (§2.3 · G-03-①) ─────────────────────────────────────────────────
@pytest.mark.parametrize("screen", nav.all_screens(), ids=lambda s: s.no)
def test_화면45가_200이고_화면명을_렌더한다(screen):
    r = client.get(screen.path)
    assert r.status_code == 200, f"{screen.path} → {r.status_code}"
    assert screen.name in html.unescape(r.text), f"{screen.path} 에 화면명이 없다"


@pytest.mark.parametrize("path", COMMON_PATHS)
def test_공통화면_4종이_200이다(path):
    assert client.get(path).status_code == 200


def test_공통_오류화면과_헬스체크가_계약대로다():
    r = client.get(ERROR_PATH)
    assert r.status_code == 200
    # `/error` 는 **공통 오류 화면 견본**이다. 실제 문구 7종은 `/popup` 이 계약대로 들고 있다.
    assert "500" in r.text and "조용한 실패 금지" in r.text
    h = client.get("/health")
    assert h.status_code == 200, f"/health {h.status_code} — 정본 규모가 흔들렸다"
    assert h.json()["status"] == "ok"


def test_placeholder가_0건이다():
    """G-03-② — 담당 라우터가 안 만든 화면이 하나라도 있으면 이름을 찍는다."""
    assert PLACEHOLDERS == [], f"placeholder 로 서 있는 화면 {len(PLACEHOLDERS)}: {PLACEHOLDERS}"


def test_경로_수가_45_더하기_공통5다():
    paths = {s.path for s in nav.all_screens()}
    assert len(paths) == 45
    assert not (paths & set(COMMON_PATHS)), "화면 경로와 공통 경로가 겹친다"


# ── TD3 목업 항목 일치 (§2.3 — 화면의 모든 칸은 정본 문장이다) ───────────
@pytest.mark.parametrize("screen", nav.all_screens(), ids=lambda s: s.no)
def test_목업_조회조건_그리드열_버튼이_렌더된다(screen):
    mock = design.screen(screen.id)["mockup"]
    page = body(screen.path)
    missing: dict[str, list[str]] = {}
    for key in ("search_fields", "grid_columns", "buttons"):
        gone = [item for item in (mock.get(key) or []) if item not in page]
        if gone:
            missing[key] = gone
    assert not missing, f"{screen.path} 에 TD3 목업 항목이 없다: {missing}"


def test_목업_항목_총량을_실측으로_남긴다():
    """건수까지 적어 둔다 — 나중에 항목이 슬며시 줄면 여기서 드러난다."""
    want = {"search_fields": 0, "grid_columns": 0, "buttons": 0}
    got = dict(want)
    for screen in nav.all_screens():
        page = body(screen.path)
        for key in want:
            items = design.screen(screen.id)["mockup"].get(key) or []
            want[key] += len(items)
            got[key] += sum(1 for i in items if i in page)
    assert want == {"search_fields": 192, "grid_columns": 245, "buttons": 182}, \
        f"TD3 목업 항목 수가 바뀌었다: {want} — 정본이 바뀌었는지 확인하라"
    assert got == want, f"렌더 누락: {got} ≠ {want}"


# ── 0건 경로 (§10-4 · §10-14 · G-11) ────────────────────────────────────
LIST_SCREENS = [s for s in nav.all_screens()
                if (design.screen(s.id)["mockup"].get("kind")) == "list"]
DASH_SCREENS = [s for s in nav.all_screens()
                if (design.screen(s.id)["mockup"].get("kind")) == "dashboard"]


def test_목록화면과_대시보드_수가_정본과_같다():
    assert (len(LIST_SCREENS), len(DASH_SCREENS)) == (35, 7)
    assert len(LIST_SCREENS) + len(DASH_SCREENS) + 3 == 45      # form 3건


@pytest.mark.parametrize("screen", LIST_SCREENS, ids=lambda s: s.no)
def test_목록화면은_0건일때_빈표를_조용히_내지_않는다(screen):
    """§10-14 — `0 건` 은 정답이다. 다만 **아무 말도 없는 빈 표**는 결함이다."""
    page = body(screen.path)
    marks = [m for m in EMPTY_MARKS if m in page]
    assert marks, f"{screen.path}: 0건/미확정 표지가 하나도 없다 — 조용한 빈 화면 (G-30)"


@pytest.mark.parametrize("screen", LIST_SCREENS, ids=lambda s: s.no)
def test_존재하지_않는_조회조건에도_200이고_0건_표지를_낸다(screen):
    """N건 화면이든 0건 화면이든 **반드시 0건이 되는 조건**으로 한 번 더 때린다."""
    mock = design.screen(screen.id)["mockup"]
    page = html.unescape(
        client.get(screen.path, params={"q0": "QA1-존재하지않는값-zzz",
                                        "no": "QA1-존재하지않는값-zzz",
                                        "src": "QA1-존재하지않는값-zzz",
                                        "key": "QA1-존재하지않는값-zzz",
                                        "lot": "QA1-존재하지않는값-zzz"}).text)
    assert mock["grid_columns"][0] in page, f"{screen.path}: 0건이면 표 머리까지 사라진다"
    assert any(m in page for m in EMPTY_MARKS), f"{screen.path}: 0건 표지 없음"


def test_페이지네이션_계약이_지켜진다():
    """api-contract §0-7 — `?page=&size=` 기본 20. 잘못된 값은 조용히 무시하지 않는다."""
    s = next(x for x in LIST_SCREENS if x.owner == "개발1")
    assert client.get(s.path, params={"page": "1", "size": "5"}).status_code == 200
    bad = client.get(s.path, params={"page": "abc"})
    assert bad.status_code in (200, 422), f"{s.path}?page=abc → {bad.status_code}"
