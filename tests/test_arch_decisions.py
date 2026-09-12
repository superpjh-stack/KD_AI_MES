"""결정 대장 정합성 (D-181) — **대장이 사실과 어긋나면 빌드가 깨진다.**

`CLAUDE.md` 가 "대장에 없는 것을 마음대로 정하지 않는다" 고 못박는다. 그러면 대장이 맞아야
한다. 실제로 재 보니 `차단`·`미결` 45건 중 **16건이 이미 해소**돼 있었다 — D-120 은
'고객사 코드 0건이라 막혔다' 인데 코드는 19건 서 있었고, D-77 은 '500 이다' 인데 422 였다.
해소된 것이 차단으로 남아 있으면 **다음 할 일을 그 목록에서 고를 때 이미 끝난 일을 또 한다.**

게이트를 늘리지 않는다 — `goal.md` 는 **32건 고정**이다(G-01~G-30 + 정본 + G-빌드).
대신 **테스트가 진다**: 이 파일이 깨지면 `G-빌드` 가 FAIL 이므로 대장이 낡은 채로
회전이 끝나지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_decisions as cd                                   # noqa: E402


def _run() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_decisions.py")],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def test_해소된_항목이_차단으로_남아_있지_않다():
    """probe 가 `해소` 라는데 대장이 `차단` 이면 **결함**이다."""
    code, out = _run()
    assert "해소됐는데 안 닫힌 항목 0 건" in out, out[-2500:]
    assert code == 0, out[-2500:]


def test_닫은_항목이_다시_열리지_않았다():
    """닫고 나서 코드가 되돌아갈 수 있다 — **되열리면 잡는다.**"""
    _, out = _run()
    assert "되열린 항목 0 건" in out, out[-2500:]


def test_열린_항목마다_probe_나_사유가_있다():
    """**확인한 척하지 않는다**(§10-9). probe 가 없으면 왜 없는지가 적혀 있어야 한다.

    대부분은 정본 부재·도입기업 미제공이라 **코드를 봐서는 알 수 없다** — 문서가 와야 닫힌다.
    그 사실을 적어 두지 않으면 '아직 안 본 것' 과 '볼 수 없는 것' 이 섞인다.
    """
    missing = [no for no, _ in cd.parse_open()
               if no not in cd.PROBES and no not in cd.NO_PROBE_WHY]
    assert missing == [], f"probe 도 사유도 없는 항목: {missing}"


def test_probe_는_상수를_돌려주지_않는다():
    """probe 가 늘 같은 값을 내면 **아무것도 재지 않는 것**이다(§10-16 되돌림 원칙).

    근거 문장에 **숫자나 판정값이 들어 있는지**로 본다 — `True`/`False`/건수 없이
    설명만 돌려주는 probe 는 대장을 검증하지 못한다.
    """
    import re

    flat: list[str] = []
    for no, fn in cd.PROBES.items():
        try:
            _, why = fn()
        except Exception as e:                                  # noqa: BLE001
            raise AssertionError(f"{no} probe 가 죽었다: {type(e).__name__}: {e}") from e
        if not re.search(r"\d|True|False|없음", why):
            flat.append(f"{no}: {why}")
    assert flat == [], f"측정값 없이 문장만 돌려주는 probe: {flat}"


def test_대장을_검사기가_고치지_않는다():
    """자동으로 닫으면 **어떤 근거로 닫혔는지가 사라진다.** 검사기는 찍기만 한다."""
    src = (ROOT / "tools" / "check_decisions.py").read_text()
    assert "write_text" not in src and "open(LEDGER" not in src, \
        "검사기가 대장을 쓰고 있다 — 닫는 것은 사람이 한다"


def test_상태는_맨앞_상태어로_판정한다():
    """**글자 포함 여부로 보면 틀린다.**

    `확정 — G-10 이 차단에서 풀렸다` 는 확정인데 '차단' 이 들어 있다. 실제로 이 문장 하나
    때문에 열린 항목이 29 → 30 으로 늘었다(D-187). 대장이 커질수록 이런 문장이 늘어난다.
    """
    assert cd.is_open("차단")
    assert cd.is_open("미결")
    assert cd.is_open("**차단(Critical)**")
    assert cd.is_open("차단 유지")
    assert not cd.is_open("확정")
    assert not cd.is_open("**확정 — G-10 이 차단에서 풀렸다**")
    assert not cd.is_open("~~차단~~ → **해소 (D-181 실측)**")
    assert not cd.is_open("가정")
