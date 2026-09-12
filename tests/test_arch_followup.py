"""미비 항목을 화면에 남긴다 (D-188) — **화면과 대장이 같은 말을 하는지**.

사용자 요청: "미비하거나 부족한 건 개발된 화면에 남겨줘. 팔로우업할테니."
그러면 화면이 말하는 건수와 대장이 말하는 건수가 **같아야** 한다. 화면이 자기 목록을
따로 들면 어긋나고, 그 사고를 이미 두 번 겪었다(D-163 표시 문구 7곳 복사 · D-181 대장 낡음).
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
sys.path.insert(0, str(ROOT / "tools"))

from kyungdong.app import followup, nav                        # noqa: E402
from kyungdong.app.main import app                             # noqa: E402

COUNT_RE = re.compile(r"미비 항목 (\d+)건")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _count(client: TestClient, path: str) -> int:
    r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 200, (path, r.status_code)
    m = COUNT_RE.search(re.sub(r"<[^>]+>", " ", r.text))
    return int(m.group(1)) if m else 0


def test_화면과_검사기가_같은_건수를_말한다(client):
    """검사기가 28 이라는데 화면이 다른 수를 말하면 **둘 중 하나가 거짓**이다."""
    import check_decisions as cd

    assert len(cd.parse_open()) == len(followup.open_items()), "검사기와 화면 모듈이 어긋난다"
    assert _count(client, "/sys/029") == len(followup.open_items())


def test_어디에도_안_뜨는_항목이_없다(client):
    """배정이 빠진 항목이 **조용히 사라지지** 않아야 한다.

    `SCREEN_MAP` 에 없는 D-번호는 `029` 로 모인다. 그래서 029 의 건수가 곧 전체다.
    """
    all_no = {i.no for i in followup.open_items()}
    shown = {i.no for i in followup.for_screen(followup.CATCH_ALL)}
    assert shown == all_no, f"029 에서 빠진 항목: {sorted(all_no - shown)}"


def test_대장이_정본이고_화면은_읽기만_한다():
    """화면 모듈이 자기 목록을 들면 대장과 어긋난다 — **하드코딩 금지.**

    `SCREEN_MAP`·`OWNER` 는 *배정*이지 *목록*이 아니다. 항목의 존재·상태·문장은
    전부 `decisions.md` 에서 온다.
    """
    src = (ROOT / "src" / "kyungdong" / "app" / "followup.py").read_text()
    assert "LEDGER.read_text" in src, "대장을 읽지 않는다"
    # 배정표에만 있고 대장에 없는 D-번호는 **죽은 배정**이다 — 화면에 영영 안 뜬다.
    known = {i.no for i in followup.open_items()}
    # **허용목록을 두지 않는다.** 닫힌 항목의 배정은 화면에 영영 안 뜨므로 남겨 두면 착시다 —
    # "배정은 해 뒀다" 는 느낌만 주고 실제로는 아무 데도 안 보인다. 실제로 D-56·D-151·
    # D-06·D-09 4건이 그 상태였고 이 단언이 잡았다.
    dead = [no for no in followup.SCREEN_MAP if no not in known]
    assert dead == [], f"닫힌 항목의 죽은 배정: {dead} — 배정표에서 뺀다"
    orphan = [i.no for i in followup.open_items() if i.no not in followup.SCREEN_MAP]
    assert orphan == [] or all(i in {x.no for x in followup.for_screen(followup.CATCH_ALL)}
                               for i in orphan), "배정 없는 항목이 029 에도 안 뜬다"


def test_항목마다_무엇이_있어야_닫히는지_적혀_있다():
    """D-번호만 띄우면 **화면에서는 아무 뜻이 없다.** 누가 주어야 하는지가 있어야 한다."""
    unknown = [i.no for i in followup.open_items() if i.need == "담당 미확정"]
    assert unknown == [], f"닫는 주체가 안 적힌 항목: {unknown}"
    for it in followup.open_items():
        assert it.summary and len(it.summary) > 5, (it.no, it.summary)
        assert "**" not in it.summary and "`" not in it.summary, "마크업이 화면에 샌다"


def test_미비가_없는_화면에는_패널이_안_뜬다(client):
    """없는 것을 있다고 하지 않는다 — 배정이 없으면 **아무것도 안 뜬다.**"""
    empty = [s.no for s in nav.all_screens() if not followup.for_screen(s.no)]
    assert empty, "모든 화면에 미비가 있다 — 배정을 확인한다"
    sc = next(s for s in nav.all_screens() if s.no == empty[0])
    assert _count(client, sc.path) == 0


def test_Critical_이_맨_위에_온다():
    """급한 것이 아래에 묻히면 화면에 남긴 뜻이 없다."""
    items = followup.for_screen(followup.CATCH_ALL)
    crit = [i for i in items if i.critical]
    if crit:
        assert items[0].critical, "Critical 이 맨 위가 아니다"


def test_대장을_못_읽어도_화면은_뜬다(client, monkeypatch):
    """대장 파일이 없다고 화면이 죽으면 안 된다 — **미비 목록은 부가 정보**다."""
    monkeypatch.setattr(followup, "LEDGER", ROOT / "없는파일.md")
    followup.open_items.cache_clear()
    try:
        assert followup.open_items() == ()
        r = client.get("/sys/029", headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200
    finally:
        monkeypatch.undo()
        followup.open_items.cache_clear()
    assert len(followup.open_items()) > 0, "원상복구되지 않았다"
