"""개발2 화면 16 + 현황판 — 렌더·권한·빈 칸 문구·디지털 스레드 링크.

  · 16화면 + `/board` 전부 200 (G-03)
  · 권한 없으면 403, 등록 권한 없으면 403 (G-28)
  · 빈 **그리드**에는 문구가 있고, 건수 카드의 `0 건` 에는 **붙이지 않는다** (G-11 · §10-14)
  · LOT·프로젝트번호 열은 `/prc/024` 로 간다 (G-08)
  · 외부 CDN 0건 (D-50) · 개발2 CSS 에 미디어쿼리 0건 (§10-13)
  · 자동 수집을 전 공정으로 넓히지 않는다 (D-06)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

from kyungdong.app import design, nav                            # noqa: E402

DEV2_PATHS = [s.path for s in nav.owned_by("개발2")]
BOARD = "/board"
TEMPLATE_DIR = ROOT / "src" / "kyungdong" / "app" / "templates"
MY_TEMPLATES = sorted(
    [p for d in ("dsh", "prc", "shp", "kpi") for p in (TEMPLATE_DIR / d).glob("*.html")]
    + [TEMPLATE_DIR / "board.html"]
)


def _client(role: str = "SYSADMIN"):
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    return TestClient(app, raise_server_exceptions=False,
                      headers={"x-kyungdong-role": role})


def test_담당_화면은_16건이다():
    assert len(DEV2_PATHS) == 16
    assert sorted(DEV2_PATHS) == sorted([
        "/dsh/001", "/dsh/002", "/dsh/003", "/dsh/004",
        "/prc/021", "/prc/022", "/prc/023", "/prc/024", "/prc/025",
        "/shp/016", "/shp/017", "/shp/018", "/shp/019",
        "/kpi/043", "/kpi/044", "/kpi/045",
    ])


def test_출하_AI_Agent_는_개발2_것이_아니다():
    """`/shp/020` 은 개발3(routers/agt.py) 몫이다 — 여기서 만들면 소유권 위반이다."""
    assert nav.by_path()["/shp/020"].owner == "개발3"
    from kyungdong.app.routers import shp
    assert "MES-TD3-020" not in shp.SCREENS


@pytest.mark.parametrize("path", DEV2_PATHS + [BOARD])
def test_전부_200_이다(path):
    r = _client().get(path)
    assert r.status_code == 200, f"{path} → {r.status_code}\n{r.text[:600]}"


@pytest.mark.parametrize("path", DEV2_PATHS + [BOARD])
def test_외부_CDN_0건(path):
    """CSP `default-src 'self'` — 차트도 인라인 SVG 다 (D-50)."""
    body = _client().get(path).text
    assert "http://" not in body and "https://" not in body, path
    assert "<svg" in body or "d2-prog" in body or "tablewrap" in body


def test_개발2_템플릿에_미디어쿼리가_없다():
    """반응형은 app/static/app.css 단일 파일이다 (§10-13)."""
    hits = [p.name for p in MY_TEMPLATES if "@media" in p.read_text()]
    assert hits == [], f"미디어쿼리가 있는 템플릿: {hits}"


JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)


def test_그리드_셀에_safe_필터를_쓰지_않는다():
    """autoescape 가 기본이다 (§10-8). 주석 안의 언급은 제외하고 실제 사용만 본다."""
    hits = [p.name for p in MY_TEMPLATES
            if re.search(r"\|\s*safe", JINJA_COMMENT.sub("", p.read_text()))]
    assert hits == []


# ── 권한 (G-28) ─────────────────────────────────────────────────────────
def test_권한_없는_역할은_403_이다():
    """'품질·RCMS 담당' 은 사용자/시스템관리 권한이 없다 — 개발2 화면은 전부 조회 가능하다."""
    c = _client("QUALITY")
    for path in DEV2_PATHS:
        assert c.get(path).status_code == 200, path
    # 모르는 역할은 열어주지 않는다
    bad = _client("NOSUCHROLE")
    assert bad.get("/prc/021").status_code == 403


def test_등록_권한이_없으면_403():
    """총괄PM/경영자는 공정관리가 R 이다 — 실적 등록은 403."""
    r = _client("EXEC").post("/prc/021", data={
        "work_order_id": 1, "process_code": "P50", "start_dt": "2026-08-18 08:30",
        "good_qty": 1, "defect_qty": 0})
    assert r.status_code == 403


def test_출하_확정은_승인_권한이_필요하다():
    """현장 작업자는 출하물류관리 RW 지만 **승인(A)은 없다** → 403 (G-24)."""
    from kyungdong.app import rbac
    assert rbac.can_write("OPERATOR", "출하물류관리")
    assert not rbac.can_approve("OPERATOR", "출하물류관리")
    r = _client("OPERATOR").post("/shp/016/approve", data={"shipment_id": 1})
    assert r.status_code == 403


def test_자동_수집을_레이저커팅_밖으로_넓히면_422():
    """수집 지점은 2개소뿐이다 — 다른 공정에 자동(PLC)을 붙이면 계약 위반이다 (D-06)."""
    r = _client("PRODUCTION").post("/prc/021", data={
        "work_order_id": 1, "process_code": "P50", "start_dt": "2026-08-18 08:30",
        "good_qty": 1, "defect_qty": 0, "collect_method": "자동(PLC)"})
    assert r.status_code == 422
    assert "레이저커팅" in r.text


def test_외주_공정_실적_등록은_422():
    """소재가공·버핑은 실적이 아니라 발주·반출·반입 상태다 (D-41)."""
    r = _client("PRODUCTION").post("/prc/021", data={
        "work_order_id": 1, "process_code": "P60", "start_dt": "2026-08-18 08:30",
        "good_qty": 1, "defect_qty": 0})
    assert r.status_code == 422
    assert "외주" in r.text


# ── 빈 칸 문구 (G-11 · §10-14) ──────────────────────────────────────────
GRID_EMPTY = re.compile(r'<td class="empty" colspan="\d+">([^<]+)</td>')
CARD = re.compile(r'<span class="k">([^<]*)</span>\s*<span class="v">([^<]*)</span>')


@pytest.mark.parametrize("path", DEV2_PATHS)
def test_빈_그리드에는_문구가_있다(path):
    body = _client().get(path).text
    for note in GRID_EMPTY.findall(body):
        assert ("미수집" in note or "미확정" in note), f"{path}: 빈 그리드 문구가 비었다 — {note!r}"


@pytest.mark.parametrize("path", DEV2_PATHS + [BOARD])
def test_건수_카드의_0건에는_미수집을_붙이지_않는다(path):
    """`0 건` 은 정답이다 — 거기에 '미수집' 을 붙이면 수집된 사실을 부정하는 거짓 표시다."""
    for label, value in CARD.findall(_client().get(path).text):
        if value.strip().endswith("건") or value.strip().endswith("ea") or value.strip().endswith("개소"):
            assert "미수집" not in value and "미확정" not in value, f"{path} · {label} = {value}"


def test_023_은_표준조건이_없으면_미확정을_낸다():
    """표준 작업조건은 도입기업 제공이다 — '미수집' 이 아니라 '미확정' 이 맞다 (D-203)."""
    import conn
    n = conn.q1("select count(*) as n from PRC_STD_CONDITIONS")["n"]
    body = _client().get("/prc/023").text
    if n == 0:
        assert "미확정 (D-203)" in body
    else:
        assert "<td class=\"empty\"" not in body


def test_022_는_수집_범위를_밝힌다():
    body = _client().get("/prc/022").text
    assert "D-06" in body
    assert "2개소" in body or "레이저커팅기 PLC" in body


# ── 디지털 스레드 (G-08) ────────────────────────────────────────────────
def test_LOT_프로젝트번호_열은_024_로_간다():
    from kyungdong.app.routers import dsh
    assert dsh.lot_cell("PLOT-2026-001")["href"] == "/prc/024?lot=PLOT-2026-001"
    assert dsh.project_cell("PJ-2026-001")["href"] == "/prc/024?project=PJ-2026-001"
    assert dsh.lot_cell(None)["href"] is None          # 값이 없으면 링크도 없다


def test_024_는_조건_없이도_200_이고_스레드_패널은_조건이_있을_때만_뜬다():
    c = _client()
    assert c.get("/prc/024").status_code == 200
    assert "디지털 스레드 —" not in c.get("/prc/024").text
    r = c.get("/prc/024?project=NO-SUCH-PROJECT")
    assert r.status_code == 200
    assert "디지털 스레드 —" not in r.text       # 없는 프로젝트를 지어내지 않는다


# ── TD3 정본과 맞는가 ───────────────────────────────────────────────────
@pytest.mark.parametrize("sid", [s.id for s in nav.owned_by("개발2")])
def test_TD3_목업_항목이_화면에_있다(sid):
    td3 = design.screen(sid)
    mock = td3.get("mockup") or {}
    body = _client().get(nav.by_id()[sid].path).text
    for col in mock.get("grid_columns", []):
        assert col in body, f"{sid}: 그리드 열 '{col}' 이 화면에 없다"
    for field in mock.get("search_fields", []):
        assert field in body, f"{sid}: 조회 조건 '{field}' 이 화면에 없다"
    for btn in mock.get("buttons", []):
        assert btn in body, f"{sid}: 버튼 '{btn}' 이 화면에 없다"


@pytest.mark.parametrize("sid", [s.id for s in nav.owned_by("개발2")])
def test_예시_값을_렌더하지_않는다(sid):
    """TD3 목업의 `(예시)` 값은 화면에도 시드에도 넣지 않는다 (§0.2)."""
    body = _client().get(nav.by_id()[sid].path).text
    assert "(예시)" not in body, f"{sid}: 목업의 (예시) 값이 그대로 나왔다"
