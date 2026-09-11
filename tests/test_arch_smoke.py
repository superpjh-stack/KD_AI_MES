"""아키텍트 웨이브 A 스모크 — 정본·메뉴·RBAC·라우트가 서 있는지.

goal.md §10-4: 데이터 의존적으로 쓰지 않는다. 여기서는 DB 를 쓰지 않는다(정본·라우트만).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav, rbac      # noqa: E402
from kyungdong.app.main import app               # noqa: E402
from kyungdong.app.util import http              # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def test_정본_규모가_goal_표와_같다():
    bad = {k: (got, want) for k, (got, want, ok) in design.selfcheck().items() if not ok}
    assert not bad, f"정본이 흔들렸다: {bad}"


def test_메뉴는_10영역_45화면이다():
    assert len(nav.menu()) == 10
    assert len(nav.all_screens()) == 45


def test_화면_소유가_3분할이다():
    from collections import Counter
    c = Counter(s.owner for s in nav.all_screens())
    assert (c["개발1"], c["개발2"], c["개발3"]) == (15, 16, 14)


def test_경로와_추적ID가_중복없이_1대1이다():
    ss = nav.all_screens()
    assert len({s.path for s in ss}) == 45
    assert len({s.requirement_id for s in ss}) == 45
    assert len({s.program_id for s in ss}) == 45
    for s in ss:
        assert design.requirement(s.requirement_id), s.requirement_id
        assert design.program(s.program_id), s.program_id


@pytest.mark.parametrize("path", ["/", "/login", "/popup", "/board", "/error", "/health"])
def test_공통화면이_200이다(path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("screen", nav.all_screens(), ids=lambda s: s.no)
def test_45화면이_200이다(screen):
    r = client.get(screen.path)
    assert r.status_code == 200
    assert screen.name in r.text


def test_권한없으면_403이다():
    """현장 작업자는 수주견적AI관리 접근 불가 — TD3 role_matrix 셀이 '-' 다 (G-28)."""
    est = next(s for s in nav.all_screens() if s.area == "수주견적AI관리")
    assert not rbac.can_read("OPERATOR", "수주견적AI관리")
    assert client.get(est.path, headers={"x-kyungdong-role": "OPERATOR"}).status_code == 403


def test_권한없는_역할에게는_메뉴가_안보인다():
    est = next(s for s in nav.all_screens() if s.area == "수주견적AI관리")
    body = client.get("/", headers={"x-kyungdong-role": "OPERATOR"}).text
    assert est.path not in body


def test_오류계약_문구가_한곳에만_있다():
    assert {c.status for c in http.CASES} == {401, 403, 422, 500, 501, 503}
    with pytest.raises(KeyError):
        http.fail("없는키")          # 계약 밖 상태를 몰래 만들 수 없다


def test_LLM_CAD_미구성이_숨지_않는다():
    """API 키·CAD 파서가 없으면 화면이 그 사실을 말해야 한다 (§2.5 · D-05 · D-08)."""
    body = client.get("/").text
    assert "LLM 미구성" in body
    assert "CAD Parsing 미구성" in body
    assert "tsvector_keyword" in body
