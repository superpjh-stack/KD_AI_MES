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
            # `AGT_RECOMMENDATIONS` 에 **미검토** 행을 넣는 것은 제안(추천·알림)이지 확정이 아니다 —
            # G-24 가 막는 것은 REVIEW_STATUS 를 승인으로 바꾸는 경로다. 단 REVIEWER_ID 를 함께
            # 적으면 검토한 것처럼 보이므로 그것은 여전히 위반이다 (D-228 검사기 정밀화).
            after = txt[m.end(): m.end() + 900]
            proposal = (m.group(2).upper() == "AGT_RECOMMENDATIONS" and m.group(1).lower() != "update"
                        and ("REVIEW_INITIAL" in after or "'미검토'" in after)
                        and "REVIEWER_ID" not in after.split("values")[0])
            if proposal:
                continue
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
    """`EST_QUOTATIONS` 는 여전히 0건이다 — 단가 값이 없다(D-04).

    **`EST_BOM_HEADERS` 는 0건 단언에서 빠졌다.** 사용자 지시로 G-08 디지털 스레드를 합성으로
    채웠고(D-131) BOM 은 그 사슬의 3단계다. 대신 **채워졌으면 합성 표시가 붙어 있어야 한다** —
    BOM 헤더에는 비고 칸이 없으므로 하위 `EST_BOM_ROUTINGS.REMARK` 와 화면 배지가 진다.
    """
    n = int(conn.q1("select count(*) as n from EST_QUOTATIONS")["n"])
    assert n == 0, "EST_QUOTATIONS 를 시드하지 않았다 — 단가 값 미확보 (D-04)"
    boms = int(conn.q1("select count(*) as n from EST_BOM_HEADERS")["n"])
    if boms:
        marked = int(conn.q1(
            "select count(*) as n from EST_BOM_HEADERS b where exists "
            "(select 1 from EST_BOM_ROUTINGS r where r.BOM_ID = b.BOM_ID "
            " and r.REMARK like '%합성 (D-131)%')")["n"])
        assert marked == boms, \
            f"BOM {boms}건 중 합성 표시가 붙은 것이 {marked}건뿐이다 — 표시 없는 합성은 거짓 증거다"
        assert "합성 데이터 기준 (D-131)" in client.get("/est/013").text, \
            "013 화면에 합성 데이터 배지가 없다"
    assert "미수집" in client.get("/est/012").text     # 견적 0건은 그대로다
