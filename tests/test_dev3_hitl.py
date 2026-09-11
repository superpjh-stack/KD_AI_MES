"""G-24 HITL — 승인 없이 확정되는 경로가 **0** 이다.

`EST_QUOTATIONS`(견적 확정) · `EST_BOM_HEADERS`(BOM 확정) · `EST_CAD_OBJECTS`(객체 확정) ·
`AGT_RECOMMENDATIONS`(추천 반영) 를 바꾸는 코드 경로가 전부 `rbac.can_approve` 를 지난다.
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
from kyungdong.app import rbac                           # noqa: E402
from kyungdong.app.main import app                       # noqa: E402
from kyungdong.app.util import http                      # noqa: E402
from kyungdong.cad import pipeline                       # noqa: E402

EST_AREA = "수주견적AI관리"
AGENT_AREA = "AI Agent 통합관리"
MINE = [ROOT / "src" / "kyungdong" / "app" / "routers" / "est.py",
        ROOT / "src" / "kyungdong" / "app" / "routers" / "agt.py",
        ROOT / "src" / "kyungdong" / "app" / "routers" / "ingest.py"]
PKGS = [ROOT / "src" / "kyungdong" / p for p in ("agent", "cad", "ml", "ingest")]

CONFIRM_TABLES = ("EST_QUOTATIONS", "EST_BOM_HEADERS", "EST_CAD_OBJECTS", "AGT_RECOMMENDATIONS")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _sources() -> dict[Path, str]:
    out = {p: p.read_text() for p in MINE if p.exists()}
    for d in PKGS:
        for f in d.rglob("*.py"):
            out[f] = f.read_text()
    return out


def test_확정_대상_표를_쓰는_함수는_승인_검사를_지난다():
    """쓰기 SQL 이 있는 함수 안에 `can_approve` 또는 `forbidden` 이 함께 있어야 한다."""
    offenders = []
    for path, txt in _sources().items():
        for m in re.finditer(r"(update|insert\s+into)\s+(" + "|".join(CONFIRM_TABLES) + r")", txt, re.I):
            start = txt.rfind("\ndef ", 0, m.start())
            start = txt.rfind("\nasync def ", 0, m.start()) if start < 0 else start
            body = txt[max(0, start): m.end() + 200]
            if "can_approve" not in body and "forbidden" not in body:
                line = txt[:m.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line} {m.group(0)}")
    assert offenders == [], f"승인 검사 없이 확정 표를 쓴다 (G-24): {offenders}"


def test_CONFIRM_YN_을_바꾸는_경로는_하나뿐이다():
    hits = []
    for path, txt in _sources().items():
        for m in re.finditer(r"EST_CAD_OBJECTS\s+set\s+CONFIRM_YN", txt, re.I):
            hits.append(f"{path.name}:{txt[:m.start()].count(chr(10)) + 1}")
    assert len(hits) == 1, f"CONFIRM_YN 을 바꾸는 곳이 {len(hits)}군데다: {hits}"
    assert hits[0].startswith("pipeline.py")


def test_승인_권한이_없으면_객체_확정은_403_이다():
    assert not rbac.can_approve("OPERATOR", EST_AREA)
    with pytest.raises(http.HTTPException) as e:
        pipeline.review_object(1, reviewer_id=1, role_code="OPERATOR", result="승인")
    assert e.value.status_code == 403


def test_검토_결과_어휘_위반은_422_다():
    with pytest.raises(http.HTTPException) as e:
        pipeline.review_object(1, reviewer_id=1, role_code="SYSADMIN", result="대충승인")
    assert e.value.status_code == 422


def test_견적_확정은_승인_권한이_없으면_403_이다(client: TestClient):
    r = client.post("/est/012/confirm?as=OPERATOR", data={"quote_id": 1})
    assert r.status_code == 403


def test_BOM_확정은_승인_권한이_없으면_403_이다(client: TestClient):
    r = client.post("/est/013/confirm?as=QUALITY", data={"bom_id": 1})
    assert r.status_code == 403


def test_추천_반영은_승인_권한이_없으면_403_이다(client: TestClient):
    assert not rbac.can_approve("PRODUCTION", AGENT_AREA)
    r = client.post("/api/agent/recommend/1/adopt?as=PRODUCTION", data={"decision": "승인"})
    assert r.status_code == 403


def test_권한_없는_영역은_403_이다(client: TestClient):
    """현장 작업자는 수주견적AI관리 권한이 없다 (TD3 role_matrix)."""
    assert not rbac.can_read("OPERATOR", EST_AREA)
    for path in ("/est/010", "/est/012", "/est/014", "/est/015"):
        assert client.get(f"{path}?as=OPERATOR").status_code == 403, path
    # /dat/037 은 업무영역이 데이터관리라 현장 작업자도 조회 권한이 있다 (D-38 · role_matrix)
    assert client.get("/dat/037?as=OPERATOR").status_code == 200


def test_승인_경로가_실제로_존재한다():
    """403 만 나는 것이 아니라 권한이 있으면 통과하는 경로가 있어야 한다."""
    assert rbac.can_approve("SYSADMIN", EST_AREA)
    assert rbac.can_approve("EXEC", EST_AREA)


def test_확정_표는_지금_비어_있고_그_사실이_화면에_나온다(client: TestClient):
    for t in ("EST_QUOTATIONS", "EST_BOM_HEADERS"):
        n = int(conn.q1(f"select count(*) as n from {t}")["n"])
        assert n == 0, f"{t} 를 시드하지 않았다 — 단가·코드 그룹 미확보 (D-04·D-47)"
    assert "미수집" in client.get("/est/012").text
    assert "미수집" in client.get("/est/013").text
