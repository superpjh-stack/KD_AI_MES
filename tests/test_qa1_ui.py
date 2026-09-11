"""QA1 ⑤ 단말·반응형·계약 대조 — 터치 단말(TD3 standard_note 3) · 폰 폭 메뉴(§10-13) ·
계약 ↔ 코드 대조(D-57 경로 중복 · D-60 CSRF · D-61 계약에만 있는 컬럼).

**브라우저가 없다.** 그래서 폰 폭 판정은 **CSS 를 읽어서** 한다(§10-13). 읽어서 알 수 있는 것만
단언하고, 픽셀로만 알 수 있는 것은 `outputs/qa1-기능계약.md` 에 **판정 불가**로 적는다.
직전 사업 사고: 메뉴가 가로 **5,604px** 스트립이 되어 링크 51개 중 4개만 보였다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav                        # noqa: E402
from kyungdong.app.main import app                           # noqa: E402
from kyungdong.app.settings import settings                  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

APP_DIR = ROOT / "src" / "kyungdong" / "app"
CSS = (APP_DIR / "static" / "app.css").read_text()
TEMPLATES = sorted((APP_DIR / "templates").rglob("*.html"))
ROUTERS = sorted((APP_DIR / "routers").glob("*.py"))

PHONE = 400          # 현장 스마트패드·폰 폭
TOUCH_CHANNELS = ("현장POP", "스마트패드", "현황판")


def rule(selector: str) -> str:
    """`app.css` 에서 선택자 한 줄의 선언부를 꺼낸다. 없으면 빈 문자열."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


def media_block() -> str:
    m = re.search(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{(.*?)\n\}", CSS, re.S)
    return m.group(2) if m else ""


# ── 단일 CSS (§10-13) ───────────────────────────────────────────────────
def test_미디어쿼리는_app_css_한곳에만_있다():
    """개발자별 CSS 에 미디어쿼리를 쓰면 폰 폭에서 규칙이 서로 덮어쓴다."""
    others = [p.relative_to(ROOT) for p in TEMPLATES if "@media" in p.read_text()]
    assert not others, f"템플릿 안에 미디어쿼리가 있다: {others}"
    assert CSS.count("@media") == 1, f"app.css 미디어쿼리 {CSS.count('@media')}개 — 한 개여야 한다"


def test_외부_리소스를_하나도_안_쓴다():
    """D-50 — 폰트·아이콘·차트를 CDN 에서 끌면 현장 단말에서 깨진다."""
    bad = []
    for s in nav.all_screens()[:10] + [nav.by_path()["/prc/024"]]:
        body = client.get(s.path, params={"as": "SYSADMIN"}).text
        bad += [f"{s.path}: {u}" for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', body)]
    assert not bad, f"외부 리소스 참조: {bad}"


# ── 폰 폭 메뉴 (§10-13 — 직전 사업 5,604px 스트립 사고) ──────────────────
def test_좁은폭_미디어쿼리가_있고_레이아웃을_세로로_바꾼다():
    block = media_block()
    assert block, "app.css 에 좁은 폭 미디어쿼리가 없다 — 현장 단말이 데스크톱 레이아웃을 받는다"
    assert "flex-direction:column" in block.replace(" ", ""), "좁은 폭에서 2단 레이아웃이 그대로다"
    assert re.search(r"nav\.side\{[^}]*width:\s*100%", block), \
        "좁은 폭에서 좌측 메뉴가 고정 폭(210px)으로 남는다"


def test_메뉴_링크가_가로_스트립이_되지_않는다():
    """직전 사업 사고 재발 방지 — 링크가 한 줄로 늘어서면 폭이 터진다.

    ① 링크는 `display:block` 이라 그룹 안에서 **세로로** 쌓인다.
    ② 그룹은 `inline-block` 이라 컨테이너 폭에서 **줄바꿈**된다.
    ③ 메뉴에 `white-space:nowrap` · `overflow-x` 가 없다 — 있으면 줄바꿈이 막힌다.
    """
    assert "display:block" in rule("nav.side a"), "메뉴 링크가 block 이 아니다"
    block = media_block()
    grp = re.search(r"nav\.side \.grp\{([^}]*)\}", block)
    assert grp and "inline-block" in grp.group(1), "좁은 폭 그룹 배치 규칙이 없다"
    nav_css = "\n".join(ln for ln in CSS.splitlines() if "nav.side" in ln)
    assert "nowrap" not in nav_css, f"메뉴에 nowrap 이 있다 — 줄바꿈이 막힌다: {nav_css}"
    assert "overflow-x" not in nav_css, "메뉴가 가로 스크롤 스트립이다 (직전 사업 사고 §10-13)"


def test_메뉴_최장_항목이_폰_폭_안에_들어간다():
    """`inline-block` 그룹의 폭 = 가장 긴 링크의 max-content. 그것이 400px 를 넘으면 터진다.

    한글 14px 기준 글자당 최대 14px 로 **보수적으로** 잡는다(폰트는 인라인 시스템 폰트다).
    """
    pad = 12 * 2 + 8            # 좁은 폭 링크 좌우 패딩 + 그룹 오른쪽 여백
    worst = max(nav.all_screens(), key=lambda s: len(f"{s.no} {s.name}"))
    label = f"{worst.no} {worst.name}"
    est_px = len(label) * 14 + pad
    assert est_px <= PHONE, (
        f"가장 긴 메뉴 항목 {label!r}({len(label)}자) 추정 폭 {est_px}px > {PHONE}px — "
        "그룹이 줄바꿈돼도 한 항목이 화면을 넘는다")


def test_표는_전부_가로스크롤_컨테이너_안에_있다():
    """표는 폰 폭보다 넓어도 된다 — **자기 컨테이너 안에서** 스크롤되면 된다.

    컨테이너 밖으로 나가면 페이지 전체가 가로로 밀린다(직전 사업과 같은 증상).
    """
    assert "overflow-x:auto" in rule(".tablewrap"), ".tablewrap 에 가로 스크롤이 없다"
    bad = {}
    for s in nav.all_screens():
        body = client.get(s.path, params={"as": "SYSADMIN"}).text
        tables = len(re.findall(r"<table", body))
        wraps = len(re.findall(r'class="[^"]*tablewrap', body))
        if tables > wraps:
            bad[s.path] = (tables, wraps)
    assert not bad, f"스크롤 컨테이너 밖의 표: {bad}"


def test_고정_픽셀_폭이_폰_폭을_넘지_않는다():
    """CSS·인라인 어디에도 400px 를 넘는 고정 폭·최소 폭이 없어야 한다."""
    # `@media (max-width:900px)` 의 900 은 중단점이지 요소 폭이 아니다 — 빼고 센다.
    decls = re.sub(r"@media[^{]*\{", "{", CSS)
    css_wide = [int(v) for v in re.findall(r"(?:min-)?width:\s*(\d{3,})px", decls)
                if int(v) > PHONE]
    assert not css_wide, f"app.css 에 {PHONE}px 초과 고정 폭: {css_wide}"
    inline_wide = {}
    for s in nav.all_screens():
        body = client.get(s.path, params={"as": "SYSADMIN"}).text
        hits = sorted({int(v) for v in re.findall(r"(?:min-)?width:\s*(\d{3,})px", body)
                       if int(v) > PHONE})
        if hits:
            inline_wide[s.path] = hits
    assert not inline_wide, f"인라인 스타일에 {PHONE}px 초과 폭: {inline_wide}"


def test_차트는_고정폭_SVG_가_아니다():
    kit = (APP_DIR / "templates" / "dsh" / "_kit.html").read_text()
    assert "viewBox" in kit and "width:100%" in kit.replace(" ", ""), \
        "차트 SVG 가 고정 폭이다 — 폰 폭에서 잘린다"


# ── 터치 단말 (TD3 standard_note 3) ─────────────────────────────────────
def touch_screens() -> list[nav.Screen]:
    return [s for s in nav.all_screens() if any(k in s.channels for k in TOUCH_CHANNELS)]


def test_터치_현황판_채널_화면_수를_실측으로_남긴다():
    got = {k: sum(1 for s in nav.all_screens() if k in s.channels) for k in TOUCH_CHANNELS}
    assert got == {"현장POP": 5, "스마트패드": 9, "현황판": 9}, f"채널 배정이 바뀌었다: {got}"
    assert len(touch_screens()) == 21


@pytest.mark.parametrize("screen", touch_screens(), ids=lambda s: s.no)
def test_터치_화면도_좁은폭에서_같은_단일_CSS_를_쓴다(screen):
    body = client.get(screen.path, params={"as": "SYSADMIN"}).text
    assert 'href="/static/app.css"' in body, f"{screen.path}: 단일 CSS 를 안 쓴다"
    assert 'name="viewport"' in body and "width=device-width" in body, \
        f"{screen.path}: viewport 메타가 없다 — 현장 단말이 데스크톱 폭으로 렌더한다"


def test_좁은폭에서_메뉴_터치영역이_커진다():
    """standard_note 3 '터치 입력에 맞춘 큰 버튼'. **메뉴는** 좁은 폭에서 커진다."""
    block = media_block()
    link = re.search(r"nav\.side a\{([^}]*)\}", block)
    assert link, "좁은 폭에서 메뉴 링크 크기 규칙이 없다"
    assert "padding:10px 12px" in link.group(1) and "font-size:14px" in link.group(1), \
        f"메뉴 터치 영역이 데스크톱과 같다: {link.group(1)}"


def test_버튼_높이_실측을_남긴다():
    """**목표 수치가 정본에 없다.** 지어내지 않고 실측만 남긴다 — 판정은 `outputs` 에 적는다.

    정본(TD3 standard_note 3)은 '큰 버튼' 이라고만 적었고 px 를 정하지 않았다. 여기서 44px 같은
    남의 기준을 끌어와 FAIL 을 만들지 않는다(§10-18). 대신 **지금 값이 얼마인지**를 박아 둔다.
    """
    kit = (APP_DIR / "templates" / "dsh" / "_kit.html").read_text()
    lst = (APP_DIR / "templates" / "bas" / "_list.html").read_text()
    assert "min-height:36px" in kit.replace(" ", ""), "개발2 버튼 min-height 가 바뀌었다"
    assert re.search(r"\.d1-btns button\{[^}]*padding:7px 14px", lst), "개발1 버튼 패딩이 바뀌었다"
    # 좁은 폭 미디어쿼리에 **버튼** 규칙은 없다 — 이 사실을 실측으로 박는다.
    assert "button" not in media_block(), \
        "좁은 폭 버튼 규칙이 생겼다 — outputs/qa1-기능계약.md 의 실측을 갱신하라"


# ── 계약 ↔ 코드 대조 ────────────────────────────────────────────────────
def route_decls() -> list[tuple[str, str, str]]:
    """(메서드, 경로, 파일) — 라우터 소스에서 뽑는다."""
    out = []
    for p in ROUTERS + [APP_DIR / "main.py"]:
        for m in re.finditer(r"@(?:router|app)\.(get|post|put|delete)\(\"([^\"]+)\"", p.read_text()):
            out.append((m.group(1), m.group(2), p.name))
    return out


def test_D57_한_경로에_핸들러가_둘인_곳이_없다():
    """D-57 — `/board` 가 `main.py` 와 `kpi.py` 양쪽에 있었다. 다른 중복이 또 있는지 본다."""
    seen: dict[tuple[str, str], list[str]] = {}
    for method, path, where in route_decls():
        seen.setdefault((method, path), []).append(where)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, f"같은 경로에 핸들러가 둘 이상이다: {dup}"
    assert ("get", "/board") in seen and seen[("get", "/board")] == ["kpi.py"], \
        f"/board 소유가 바뀌었다: {seen.get(('get', '/board'))}"


def test_D61_계약이_TD5에_없는_컬럼을_말하지_않는다():
    """D-61 — `ADOPT_YN`·`ADOPT_BY` 는 TD5 에 없는 컬럼이었다. 같은 유형이 더 있는지 전수로 본다."""
    cols_by_table = {tid: {c["name"] for c in design.columns_of(tid)} for tid in design.tables()}
    bad = []
    for md in sorted((ROOT / "contracts").glob("*.md")):
        text = md.read_text()
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\.([A-Z][A-Z0-9_]{2,})\b", text):
            table, col = m.group(1), m.group(2)
            if table in cols_by_table and col not in cols_by_table[table]:
                bad.append(f"{md.name}: {table}.{col}")
    assert not bad, f"계약이 TD5 에 없는 컬럼을 가리킨다: {sorted(set(bad))}"


def test_D61_ADOPT_컬럼은_경고문_안에만_남아_있다():
    text = (ROOT / "contracts" / "api-contract.md").read_text()
    for token in ("ADOPT_YN", "ADOPT_BY"):
        for m in re.finditer(token, text):
            near = text[max(0, m.start() - 120): m.end() + 120]
            assert "TD5 에 없다" in near, f"{token} 이 경고 없이 계약에 남아 있다"


CSRF_POSTS = [(m, p, w) for m, p, w in route_decls() if m == "post"]


def test_D60_CSRF_연결_실측을_남긴다():
    """D-60 — 보고서에는 '27개 중 4곳' 이라고 적혀 있다. **직접 센다.**"""
    wired = []
    for p in ROUTERS:
        src = p.read_text()
        if re.search(r"csrf\.require\(", src):
            wired.append(p.name)
    posts = len(CSRF_POSTS)
    assert posts == 27, f"POST 라우트가 {posts}개다 — 실측을 갱신하라"
    assert wired == [], (
        f"csrf.require 가 연결된 라우터가 생겼다: {wired} — "
        "outputs/qa1-기능계약.md 의 DEF-QA1-002 실측(0/27)을 갱신하라")


def test_D60_꺼진_보안장치가_화면에_드러난다():
    """G-30 — 조용히 꺼진 보안 장치를 만들지 않는다. 꺼졌으면 화면이 그 사실을 말해야 한다."""
    assert settings().csrf_enforce is False, "CSRF_ENFORCE 가 켜졌다 — 실측을 다시 하라"
    body = client.get("/", params={"as": "SYSADMIN"}).text
    assert "CSRF 미적용 (D-60)" in body, "CSRF 가 꺼져 있는데 화면이 조용하다"


def test_쓰기_폼에_CSRF_토큰_필드가_없다는_사실을_박아둔다():
    """토큰 필드가 하나라도 생기면 이 테스트가 깨진다 — 그때 실측을 갱신한다."""
    has_token = [p.relative_to(ROOT).as_posix() for p in TEMPLATES if "_csrf" in p.read_text()]
    assert has_token == [], f"CSRF 토큰 필드가 생겼다: {has_token}"


@pytest.mark.xfail(strict=True, reason=(
    "DEF-QA1-003 — api-contract §5 는 `/api/agent/recommend/{id}/review` 인데 "
    "코드는 `/adopt` 다. 계약을 코드에 맞춰 다시 뽑아야 한다 (담당 아키텍트 gen_api_contract.py)"))
def test_계약에_적힌_추천검토_경로가_실제로_있다():
    r = client.post("/api/agent/recommend/999999/review", params={"as": "SYSADMIN"},
                    data={"decision": "승인"})
    assert r.status_code != 404, "계약에 적힌 경로가 404 다"


def test_실제_추천검토_경로는_adopt다():
    """위 xfail 의 대조군 — 기능은 있고 **계약 문서의 경로만** 다르다."""
    r = client.post("/api/agent/recommend/999999/adopt", params={"as": "SYSADMIN"},
                    data={"decision": "승인"})
    assert r.status_code == 422, f"/adopt 도 사라졌다 → {r.status_code}"
