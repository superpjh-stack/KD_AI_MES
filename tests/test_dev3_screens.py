"""개발3 화면 14건 — 200 · 정본 렌더 · 0건 문구 · 외부 리소스 0 (G-03 · G-11 · D-50)."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from kyungdong.app import design, nav
from kyungdong.app.main import PLACEHOLDERS, app
from kyungdong.app.routers import agt as agt_router
from kyungdong.app.routers import est as est_router

MY_SCREENS = est_router.SCREENS + agt_router.SCREENS


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_개발3_화면은_14건이다():
    assert len(MY_SCREENS) == 14
    assert sorted(MY_SCREENS) == sorted(s.id for s in nav.owned_by("개발3"))


def test_내_화면은_placeholder_에_없다():
    assert [s for s in MY_SCREENS if s in PLACEHOLDERS] == []


@pytest.mark.parametrize("sid", MY_SCREENS)
def test_전_화면이_200_이고_정본_화면명을_렌더한다(client: TestClient, sid: str):
    screen = nav.by_id()[sid]
    r = client.get(screen.path)
    assert r.status_code == 200, r.text[:300]
    assert screen.name in r.text
    assert screen.requirement_id in r.text and screen.program_id in r.text


@pytest.mark.parametrize("sid", MY_SCREENS)
def test_조회조건과_버튼은_TD3_mockup_그대로다(client: TestClient, sid: str):
    m = design.screen(sid)["mockup"]
    body = client.get(nav.by_id()[sid].path).text
    for f in m["search_fields"]:
        assert f in body, f"{sid}: 조회조건 '{f}' 누락"
    for b in m["buttons"]:
        assert b in body, f"{sid}: 버튼 '{b}' 누락"


@pytest.mark.parametrize("sid", [s for s in MY_SCREENS
                                 if design.screen(s)["mockup"].get("kind") == "list"])
def test_그리드_열은_TD3_mockup_그대로다(client: TestClient, sid: str):
    m = design.screen(sid)["mockup"]
    body = client.get(nav.by_id()[sid].path).text
    for c in m["grid_columns"]:
        assert c in body, f"{sid}: 그리드 열 '{c}' 누락"
    assert len(m["grid_columns"]) <= 7, "TD3 layout_rules — 열 최대 7"
    assert len(m["search_fields"]) <= 6, "TD3 layout_rules — 조회조건 최대 6"


@pytest.mark.parametrize("sid", MY_SCREENS)
def test_예시값을_렌더하지_않는다(client: TestClient, sid: str):
    """TD3 `grid_sample` 의 `(예시)` 값은 시안 표기다 — 시드·렌더 금지(§0.2)."""
    body = client.get(nav.by_id()[sid].path).text
    assert "(예시)" not in body, f"{sid}: 시안 예시값이 렌더됐다"


@pytest.mark.parametrize("sid", MY_SCREENS)
def test_외부_리소스를_참조하지_않는다(client: TestClient, sid: str):
    """CSP `default-src 'self'` — 외부 CDN 0 (D-50)."""
    body = client.get(nav.by_id()[sid].path).text
    assert re.search(r'(src|href)\s*=\s*["\']https?://', body) is None


def test_비어_있는_런타임_표는_미수집_문구를_낸다(client: TestClient):
    """0건 경로를 **명시 단언**한다(§10-4 · G-11). 학습이력·SHAP·추천은 아직 0건이다."""
    for path in ("/est/014", "/est/015", "/agt/039", "/agt/040", "/agt/042"):
        body = client.get(path).text
        assert "미수집" in body, f"{path}: 0건인데 '미수집' 문구가 없다"


def test_수집_지점_2개소_밖_공정을_실시간으로_보여주지_않는다(client: TestClient):
    body = client.get("/agt/041").text
    assert "레이저커팅기 PLC" in body and "현장POP(터치PC)" in body
    assert "수동 입력" in body, "수집 지점 밖 공정이 수동 입력임을 화면이 밝혀야 한다 (D-06)"


def test_AI_화면은_신뢰도와_근거_표기를_약속한다(client: TestClient):
    """TD3 layout_rules 'AI 결과 표기' — 신뢰도 + 근거 + 검토 상태."""
    for path in ("/inv/009", "/shp/020", "/agt/038"):
        body = client.get(path).text
        assert "폐쇄형" in body and "근거" in body
        assert "tsvector_keyword" in body or "vector_pgvector" in body
