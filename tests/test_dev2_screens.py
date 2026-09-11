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

from conftest import csrf_post                                   # noqa: E402
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
    r = csrf_post(_client("EXEC"), "/prc/021", {
        "work_order_id": 1, "process_code": "P50", "start_dt": "2026-08-18 08:30",
        "good_qty": 1, "defect_qty": 0})
    assert r.status_code == 403


def test_출하_확정은_승인_권한이_필요하다():
    """현장 작업자는 출하물류관리 RW 지만 **승인(A)은 없다** → 403 (G-24)."""
    from kyungdong.app import rbac
    assert rbac.can_write("OPERATOR", "출하물류관리")
    assert not rbac.can_approve("OPERATOR", "출하물류관리")
    r = csrf_post(_client("OPERATOR"), "/shp/016/approve", {"shipment_id": 1})
    assert r.status_code == 403


def test_자동_수집을_레이저커팅_밖으로_넓히면_422():
    """수집 지점은 2개소뿐이다 — 다른 공정에 자동(PLC)을 붙이면 계약 위반이다 (D-06)."""
    r = csrf_post(_client("PRODUCTION"), "/prc/021", {
        "work_order_id": 1, "process_code": "P50", "start_dt": "2026-08-18 08:30",
        "good_qty": 1, "defect_qty": 0, "collect_method": "자동(PLC)"})
    assert r.status_code == 422
    assert "레이저커팅" in r.text


def test_외주_공정_실적_등록은_422():
    """소재가공·버핑은 실적이 아니라 발주·반출·반입 상태다 (D-41)."""
    r = csrf_post(_client("PRODUCTION"), "/prc/021", {
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


# ── G-12 수집 중단 배지 (DEF-QA2-001 · DEF-QA2-002) ─────────────────────
def _ingest_marks() -> dict[str, int]:
    import conn
    return {t: int(conn.q1(f"select coalesce(max({c}),0) as n from {t}")["n"])
            for t, c in (("IF_PLC_SIGNALS", "PLC_IF_ID"),
                         ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                         ("DAT_TIMESERIES", "TS_ID"))}


def _ingest_rollback(marks: dict[str, int]) -> None:
    """이 테스트가 넣은 행만 지운다 — 다른 측정의 0건 경로를 오염시키지 않는다."""
    import conn
    for t, c in (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                 ("IF_PLC_SIGNALS", "PLC_IF_ID")):
        conn.x(f"delete from {t} where {c} > %s", (marks[t],))


def _ingest_at(when):
    """레이저커팅기 PLC 1배치를 `when` 시각으로 적재한다 (정본 수집 함수를 그대로 쓴다)."""
    import conn
    from kyungdong.ingest import collector, tags
    dev = conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                  ("레이저커팅기 PLC",))
    assert dev is not None, "IF_DEVICE_REGISTRY 에 레이저커팅기 PLC 가 없다 — `make db-seed`"
    collector.ingest_batch(
        int(dev["device_id"]), "EQ10",
        [collector.Sample(t.name, "1" if t.numeric else "가동", when) for t in tags.TAGS])


def test_G12_중단_판정은_정본_함수_한_벌이다():
    """화면 배지와 `collector.status()` 가 **같은 함수**를 본다 (DEF-QA2-002 · §10-16).

    판정을 복제하면 개발자가 한 쪽만 고쳐도 수치가 안 움직인다. 정본은
    `kyungdong.ingest.collector.status()` 다 (contracts/interfaces.md §9 TD4-047).
    """
    from kyungdong.app.routers import dsh
    from kyungdong.ingest import collector

    src = (ROOT / "src/kyungdong/app/routers/dsh.py").read_text()
    assert "collector.status()" in src, "화면이 정본 판정 함수를 부르지 않는다"
    # 임계값 비교를 화면이 따로 하면 그것이 복제다
    assert "INGEST_STALE_SEC" not in src, (
        "dsh.py 가 중단 임계를 따로 읽는다 — 판정이 두 곳에 복제됐다 (DEF-QA2-002)")
    assert "anchor() - " not in src.replace(" ", " "), "앵커 기준 중단 판정이 남아 있다"

    st = dsh.collection_status()
    ref = collector.status()
    assert st["points"] == ref["points"] == 2               # 수집 지점 2개소뿐 (D-06)
    assert st["stale_sec"] == ref["stale_sec"]
    assert [d["device_id"] for d in st["devices"]] == [d["device_id"] for d in ref["devices"]]


def test_G12_수집중단_배지가_운영시각에서_뜬다():
    """**0건 · 신선 · 중단** 세 경로를 전부 단언한다. `skip` 하지 않는다 (§10-4).

    DEF-QA2-001: 전에는 `anchor() - last_dt` 라 실시각 수집이면 경과가 항상 음수여서
    배지가 **구조적으로** 못 떴다(QA2 실측 −108,426초). 이제 기준은 실시각이다.
    """
    from datetime import timedelta

    import conn
    from kyungdong.app.routers import dsh
    from kyungdong.app.settings import settings
    from kyungdong.app.util import clock

    stale_sec = settings().h("INGEST_STALE_SEC").as_int()
    marks = _ingest_marks()
    zero_start = conn.q1("select count(*) as n from IF_PLC_SIGNALS")["n"] == 0
    try:
        # ① 0건 경로 — 수집이 한 번도 없으면 '미수집' 이지 '수집 중단' 이 아니다
        if zero_start:
            texts = [b["text"] for b in dsh.collection_badges()]
            assert any("미수집" in t for t in texts), texts
            assert not any("수집 중단" in t for t in texts), texts

        # ② N건 · 중단 — **운영 시각**으로 임계를 넘기면 배지가 뜬다
        #    중단(오래된 것) → 신선(방금) 순서로 잰다. 판정은 `max(COLLECT_DT)` 이라
        #    신선한 배치를 먼저 넣으면 뒤에 넣은 오래된 배치를 덮어 가린다(회전 7 실측).
        old = clock.real_now() - timedelta(seconds=stale_sec * 5)
        _ingest_at(old)
        stopped = [b["text"] for b in dsh.collection_badges()]
        hit = [t for t in stopped if "수집 중단" in t]
        assert hit, f"실시각 {stale_sec * 5}초 전이 마지막 수집인데 배지가 없다: {stopped}"
        assert old.strftime("%H:%M:%S") in " ".join(hit), hit

        # ③ N건 · 신선 — 방금 들어온 수집은 중단이 아니다 (실시각 기준)
        _ingest_at(clock.real_now() - timedelta(seconds=1))
        fresh = [b["text"] for b in dsh.collection_badges()]
        laser = [t for t in fresh if "레이저커팅기" in t]
        assert not any("수집 중단" in t for t in laser), fresh
    finally:
        _ingest_rollback(marks)


def test_G12_003_022_화면이_같은_배지를_쓴다():
    from kyungdong.app.routers import dsh, prc
    assert prc.collection_badges is dsh.collection_badges
    c = _client()
    for path in ("/dsh/003", "/prc/022"):
        assert "자동 수집 2개소" in c.get(path).text, path


# ── G-29 접속 감사 — 공용 가드 한 곳에서 남는다 (D-97) ───────────────────
def test_G29_16화면_조회가_접속_로그를_남긴다():
    import conn
    c = _client()
    for path in DEV2_PATHS:
        before = int(conn.q1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")["n"])
        assert c.get(path).status_code == 200, path
        n = int(conn.q1("select count(*) as n from SYS_ACCESS_LOGS "
                        "where LOG_ID > %s and LOG_TYPE = '접속' and SCREEN_ID = %s",
                        (before, nav.by_path()[path].id))["n"])
        assert n >= 1, f"{path}: 조회했는데 SYS_ACCESS_LOGS 에 '접속' 이 없다 (G-29)"


def test_G29_권한_거부는_오류로_남는다():
    import conn
    before = int(conn.q1("select coalesce(max(LOG_ID),0) as n from SYS_ACCESS_LOGS")["n"])
    assert _client("NOSUCHROLE").get("/prc/021").status_code == 403
    row = conn.q1("select LOG_TYPE, RESULT_CODE from SYS_ACCESS_LOGS "
                  "where LOG_ID > %s and LOG_TYPE = '오류' order by LOG_ID desc limit 1", (before,))
    assert row is not None, "403 거부가 감사에 남지 않는다 (G-29)"
    assert row["result_code"] == "오류"


def test_G29_감사는_가드_한_곳에서만_부른다():
    """16화면에 흩뿌리면 한 곳이 빠질 때 통째로 빠진다 — QA3 가 잡은 결함이다(D-97)."""
    for name in ("dsh", "prc", "shp", "kpi"):
        src = (ROOT / f"src/kyungdong/app/routers/{name}.py").read_text()
        calls = len(re.findall(r"(?<!def )audit\(request", src))
        assert calls == (2 if name == "dsh" else 0), f"{name}.py 의 audit() 호출 {calls}"


# ── G-26 CSRF (DEF-QA3-001) ────────────────────────────────────────────
CSRF_POSTS = ("/prc/021", "/shp/016", "/shp/016/approve")


def test_G26_쓰기_폼에_CSRF_필드가_있다():
    for rel in ("prc/021.html", "shp/016.html"):
        body = (TEMPLATE_DIR / rel).read_text()
        forms = body.count('method="post"')
        assert forms and body.count("{{ csrf_field() }}") == forms, rel
        # `with context` 가 없으면 매크로가 `csrf_token` 을 못 봐 `value=""` 가 렌더된다(회전 7 실측)
        assert '{% from "_macros.html" import csrf_field with context %}' in body, rel


def test_G26_핸들러_첫_줄이_토큰을_검증한다():
    for name in ("prc", "shp"):
        src = (ROOT / f"src/kyungdong/app/routers/{name}.py").read_text()
        posts = len(re.findall(r"@router\.post\(", src))
        assert src.count("csrf.require(request,") == posts, f"{name}.py POST {posts}건"


def test_G26_토큰이_없으면_403_있으면_통과한다():
    """켠 상태와 끈 상태를 **둘 다** 단언한다.

    이 테스트는 두 상태를 직접 만들어 보므로, 끝나면 **원래 설정값으로 되돌린다** —
    `0` 을 박아 넣으면 `KYUNGDONG_CSRF_ENFORCE=1` 로 돌릴 때 뒤따르는 테스트의 설정을 꺼 버린다.
    """
    import os

    from kyungdong.app.settings import settings

    body = {"work_order_id": 1, "process_code": "P50",
            "start_dt": "2026-08-18 08:30", "good_qty": 1, "defect_qty": 0}
    was = os.environ.get("KYUNGDONG_CSRF_ENFORCE")
    try:
        # ── 끈 상태: 토큰이 없어도 CSRF 로는 막지 않는다 ──
        os.environ["KYUNGDONG_CSRF_ENFORCE"] = "0"
        settings.cache_clear()
        assert not settings().csrf_enforce
        assert _client("PRODUCTION").post("/prc/021", data=body).status_code != 403

        # ── 켠 상태: 토큰이 없으면 403, 화면이 발급한 토큰이면 통과 ──
        os.environ["KYUNGDONG_CSRF_ENFORCE"] = "1"
        settings.cache_clear()
        assert settings().csrf_enforce
        c = _client("PRODUCTION")
        for path in CSRF_POSTS:
            assert c.post(path, data=body).status_code == 403, f"{path}: 토큰 없이 통과했다"
        # 유효 토큰은 **화면이 발급한 것**이다 — 토큰을 밖에서 지어내면 바인딩이 달라 어차피 막힌다.
        # (그게 CSRF 의 목적이다. 여기서는 브라우저가 하는 그대로 폼에서 꺼내 쓴다.)
        page = c.get("/prc/021")
        token = re.search(r'name="_csrf" value="([^"]+)"', page.text)
        assert token, "화면 폼에 CSRF 토큰이 렌더되지 않았다"
        r = c.post("/prc/021", data={**body, "_csrf": token.group(1)})
        assert r.status_code != 403, f"유효 토큰인데 403 이다: {r.text[:300]}"
    finally:
        if was is None:
            os.environ.pop("KYUNGDONG_CSRF_ENFORCE", None)
        else:
            os.environ["KYUNGDONG_CSRF_ENFORCE"] = was
        settings.cache_clear()
