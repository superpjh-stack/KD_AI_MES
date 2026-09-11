#!/usr/bin/env python
"""G-04 · G-05 검사기 (QA1 소유).

G-04  요구사항 추적 1:1 — `MES-AD2-001~045` ↔ `MES-TD3-001~045` ↔ `MES-TD4-001~045`.
      고아 0 · 중복 0. 비기능 13건(`MES-AD2-046~058`)은 **화면이 없는 것이 정상**이다.
G-05  프로그램 **49** = 화면 45 + 인터페이스 4(`MES-TD4-046~049`, 화면 없음).
      인터페이스 **연계 상태는 `/dat/033`(데이터통합관리)에서 조회**된다 — api-contract §3 · G-05.

원칙 (goal.md §10)
  · §10-16 **판정 정본 함수를 직접 부른다.** `design.trace()` · `nav.all_screens()` ·
    `design.programs()` 를 쓴다. 로직을 여기 복제하면 개발자가 고쳐도 수치가 안 움직인다.
  · §10-6 게이트별 **판정 줄**을 찍는다. `gate.py` 가 이 줄을 파싱한다.
  · §10-17 측정 중 **동시 변경을 감지하면 FAIL 이 아니라 `판정 불가`** 다.
  · 게이트를 낮추지 않는다. 못 재면 `판정 불가` 이지 PASS 가 아니다.

종료코드: FAIL 1건 이상 → 1 · 판정 불가만 있으면 → 2 · 전부 PASS → 0
"""
from __future__ import annotations

import hashlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav          # noqa: E402

PASS, FAIL, UNJUDGED = "PASS", "FAIL", "판정 불가"

# 화면이 있는 순번 · 화면이 없는 인터페이스 순번 (정본 TD4 그룹 '인터페이스')
SCREEN_NOS = tuple(f"{i:03d}" for i in range(1, 46))
IFACE_NOS = ("046", "047", "048", "049")
# 비기능 요구사항 — **화면이 없는 것이 정상**이다 (TD3 criteria)
NONFUNC_NOS = tuple(f"{i:03d}" for i in range(46, 59))

# 동시 변경 감시 대상 — 정본과 정본을 읽는 코드 (§10-17)
WATCH = (
    ROOT / "docs" / "design" / "design.json",
    ROOT / "docs" / "design" / "analysis.json",
    ROOT / "src" / "kyungdong" / "app" / "nav.py",
    ROOT / "src" / "kyungdong" / "app" / "design.py",
    ROOT / "src" / "kyungdong" / "app" / "routers" / "dat.py",
)


def _fingerprint() -> dict[str, str]:
    out = {}
    for p in WATCH:
        try:
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except OSError:
            out[p.name] = "없음"
    return out


# ═══════════════════════════════════════════════════════════════════════
# G-04 — 요구사항 추적 1:1
# ═══════════════════════════════════════════════════════════════════════
def g04() -> tuple[str, str, list[str]]:
    """(판정, 실측 요약, 상세) — `design.trace()` 정본 함수를 그대로 쓴다(§10-16)."""
    detail: list[str] = []
    bad: list[str] = []

    # ① 세 산출물이 순번으로 묶이는가 (정본 함수 trace)
    missing_req, missing_scr, missing_prg = [], [], []
    for no in SCREEN_NOS:
        t = design.trace(no)
        if t["requirement"] is None:
            missing_req.append(f"MES-AD2-{no}")
        if t["screen"] is None:
            missing_scr.append(f"MES-TD3-{no}")
        if t["program"] is None:
            missing_prg.append(f"MES-TD4-{no}")
    if missing_req:
        bad.append(f"AD2 누락 {len(missing_req)}: {missing_req[:5]}")
    if missing_scr:
        bad.append(f"TD3 누락 {len(missing_scr)}: {missing_scr[:5]}")
    if missing_prg:
        bad.append(f"TD4 누락 {len(missing_prg)}: {missing_prg[:5]}")

    # ② 고아 — 세 방향 전부 본다 (한 방향만 보면 고아가 숨는다)
    func = set(design.functional_ids())
    scr_ids = set(design.screens())
    prg_ids = set(design.programs())
    want_func = {f"MES-AD2-{n}" for n in SCREEN_NOS}
    want_scr = {f"MES-TD3-{n}" for n in SCREEN_NOS}
    want_prg = {f"MES-TD4-{n}" for n in SCREEN_NOS}

    orphan_req = sorted(func - want_func)                 # 화면 없는 기능 요구사항
    orphan_scr = sorted(scr_ids - want_scr)               # 요구사항 없는 화면
    orphan_prg = sorted(prg_ids - want_prg - {f"MES-TD4-{n}" for n in IFACE_NOS})
    if orphan_req:
        bad.append(f"고아 기능요구사항 {len(orphan_req)}: {orphan_req}")
    if orphan_scr:
        bad.append(f"고아 화면 {len(orphan_scr)}: {orphan_scr}")
    if orphan_prg:
        bad.append(f"고아 프로그램 {len(orphan_prg)}: {orphan_prg}")

    # ③ 중복 — 원본 JSON 배열에서 센다. dict 로 접으면 중복이 사라져 안 보인다.
    raw = design._design()
    raw_scr = [s["id"] for g in raw["td3"]["screens"] for s in g["screens"]]
    raw_prg = [p["id"] for g in raw["td4"]["details"] for p in g["programs"]]
    raw_ad2 = [r["id"] for k in ("functional_groups", "nonfunctional_groups")
               for g in design._analysis()["ad2"][k] for r in g["requirements"]]
    for label, ids in (("TD3", raw_scr), ("TD4", raw_prg), ("AD2", raw_ad2)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            bad.append(f"{label} 중복 {len(dup)}: {dup}")

    # ④ 화면 정본(nav) 이 추적 ID 를 1:1 로 들고 있는가
    screens = nav.all_screens()
    if len(screens) != 45:
        bad.append(f"nav 화면 {len(screens)} ≠ 45")
    if len({s.requirement_id for s in screens}) != len(screens):
        bad.append("nav requirement_id 중복")
    if len({s.program_id for s in screens}) != len(screens):
        bad.append("nav program_id 중복")
    if len({s.path for s in screens}) != len(screens):
        bad.append("nav 경로 중복")
    mismatch = [f"{s.id}→{s.requirement_id}/{s.program_id}" for s in screens
                if (s.requirement_id, s.program_id) != (f"MES-AD2-{s.no}", f"MES-TD4-{s.no}")]
    if mismatch:
        bad.append(f"순번 어긋남 {len(mismatch)}: {mismatch[:5]}")

    # ⑤ 비기능 13건 — **화면이 없는 것이 정상**. 화면이 생겼으면 그게 결함이다.
    nonfunc = set(design.nonfunctional_ids())
    want_nonfunc = {f"MES-AD2-{n}" for n in NONFUNC_NOS}
    if nonfunc != want_nonfunc:
        bad.append(f"비기능 요구사항 {sorted(nonfunc)} ≠ 046~058")
    leaked = sorted(f"MES-TD3-{n}" for n in NONFUNC_NOS if design.screen(f"MES-TD3-{n}"))
    if leaked:
        bad.append(f"비기능에 화면이 생겼다: {leaked}")

    detail.append(f"AD2 기능 {len(func)} · TD3 {len(scr_ids)} · TD4(화면분) "
                  f"{len(want_prg & prg_ids)} · 비기능 {len(nonfunc)}(화면 없음이 정상)")
    detail.append(f"고아 — 요구사항 {len(orphan_req)} · 화면 {len(orphan_scr)} · "
                  f"프로그램 {len(orphan_prg)} / 중복 — TD3·TD4·AD2 0")

    if bad:
        return FAIL, " · ".join(bad), detail
    return PASS, (f"AD2 45 ↔ TD3 45 ↔ TD4 45 · 고아 0 · 중복 0 · "
                  f"비기능 13건 화면 없음(정상)"), detail


# ═══════════════════════════════════════════════════════════════════════
# G-05 — 프로그램 49 (화면 45 + 인터페이스 4)
# ═══════════════════════════════════════════════════════════════════════
def _dat033_body() -> tuple[str | None, str]:
    """`/dat/033` 렌더 결과. DB·앱이 안 서면 (None, 사유) — FAIL 이 아니라 판정 불가다."""
    try:
        from fastapi.testclient import TestClient

        from kyungdong.app.main import app
        r = TestClient(app, raise_server_exceptions=False).get("/dat/033")
    except Exception as e:                                    # noqa: BLE001
        return None, f"/dat/033 렌더 실패: {e.__class__.__name__}: {e}"
    if r.status_code != 200:
        return None, f"/dat/033 가 {r.status_code} 다 (200 이 아니면 연계 상태를 잴 수 없다)"
    return r.text, ""


def g05() -> tuple[str, str, list[str]]:
    detail: list[str] = []
    bad: list[str] = []
    unjudged: list[str] = []

    programs = design.programs()
    ifaces = {f"MES-TD4-{n}": programs.get(f"MES-TD4-{n}") for n in IFACE_NOS}

    # ① 규모 — 49 = 45 + 4
    if len(programs) != 49:
        bad.append(f"프로그램 {len(programs)} ≠ 49")
    screen_progs = {s.program_id for s in nav.all_screens()}
    if len(screen_progs) != 45:
        bad.append(f"화면이 가리키는 프로그램 {len(screen_progs)} ≠ 45")
    rest = set(programs) - screen_progs
    if rest != set(ifaces):
        bad.append(f"화면 없는 프로그램이 {sorted(rest)} 다 — 046~049 여야 한다")

    # ② 인터페이스 4건은 **화면이 없어야** 한다
    with_screen = [pid for pid in ifaces if design.screen(f"MES-TD3-{pid.rsplit('-', 1)[-1]}")]
    if with_screen:
        bad.append(f"인터페이스에 화면이 생겼다: {with_screen}")
    empty = [pid for pid, p in ifaces.items() if not p]
    if empty:
        bad.append(f"인터페이스 프로그램이 정본에 없다: {empty}")

    # ③ 연계 상태가 `/dat/033` 에서 조회되는가 (api-contract §3 — "연계 상태 조회는 /dat/033")
    body, why = _dat033_body()
    if body is None:
        unjudged.append(why)
    else:
        shown, absent = [], []
        for pid, p in ifaces.items():
            name = (p or {}).get("name", "")
            (shown if (pid in body or (name and name in body)) else absent).append(pid)
        detail.append(f"/dat/033 인터페이스 연계 상태 노출 {len(shown)}/4 — 노출 {shown} · 누락 {absent}")
        if absent:
            bad.append(f"/dat/033 이 인터페이스 연계 상태 {len(absent)}건을 안 보여 준다: {absent}")

    detail.append(f"프로그램 {len(programs)} = 화면 {len(screen_progs)} + 인터페이스 {len(rest)}")
    for pid, p in ifaces.items():
        detail.append(f"  {pid} {(p or {}).get('name', '(정본 없음)')} — 화면 없음")

    if bad:
        return FAIL, " · ".join(bad), detail
    if unjudged:
        return UNJUDGED, " · ".join(unjudged), detail
    return PASS, f"프로그램 49 = 화면 45 + 인터페이스 4 · /dat/033 연계 상태 4/4", detail


def main() -> int:
    before = _fingerprint()
    try:
        v04, m04, d04 = g04()
    except Exception:                                          # noqa: BLE001
        v04, m04, d04 = UNJUDGED, "검사기 예외", traceback.format_exc().splitlines()[-3:]
    try:
        v05, m05, d05 = g05()
    except Exception:                                          # noqa: BLE001
        v05, m05, d05 = UNJUDGED, "검사기 예외", traceback.format_exc().splitlines()[-3:]
    after = _fingerprint()

    if before != after:
        # §10-17 — 재면서 바뀐 것을 FAIL 로 적으면 남의 결함이 된다. 다시 재라고 적는다.
        changed = sorted(k for k in before if before[k] != after[k])
        v04 = v05 = UNJUDGED
        m04 = m05 = f"측정 중 정본·코드가 바뀌었다: {changed} — 조용한 창에서 다시 재라 (§10-17)"
        d04, d05 = [], []

    print(f"G-04 요구사항 추적 1:1: {v04}" + (f" — {m04}" if m04 else ""))
    for line in d04:
        print(f"    {line}")
    print(f"G-05 프로그램 49: {v05}" + (f" — {m05}" if m05 else ""))
    for line in d05:
        print(f"    {line}")

    verdicts = (v04, v05)
    print(f"\n판정: {'FAIL' if FAIL in verdicts else (UNJUDGED if UNJUDGED in verdicts else 'PASS')}")
    if FAIL in verdicts:
        return 1
    if UNJUDGED in verdicts:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
