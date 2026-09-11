#!/usr/bin/env python
"""G-03 · G-06 검사기 (아키텍트 소유).

G-03: 45화면 + 공통 4 + 오류 1 전부 **HTTP 200** · `_placeholder` **0건** · **타 사업 용어 0건**
G-06: 메뉴 10영역 단일 소스 — `nav.py` ↔ `contracts/screen-map.md` ↔ `design.json` 대조

판정 줄을 게이트별로 찍는다(§10-6). 게이트를 낮추지 않는다 — placeholder 가 남아 있으면 FAIL 이다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient          # noqa: E402

from kyungdong.app import design, nav              # noqa: E402
from kyungdong.app.main import PLACEHOLDERS, app   # noqa: E402

# ── 타 사업·타 업종 용어 (goal.md §6) ────────────────────────────────────
# ① 직전 사업 코드에서 넘어오는 것   ② 사업계획서 자체의 잔재(D-02)
FOREIGN_TERMS: tuple[str, ...] = (
    # 광성정밀 (프레스 · 예지보전)
    "kwangsung", "프레스", "금형", "샷카운트", "전착", "프론트쉘", "스프링백",
    "예지보전", "불량예측",
    # 평창꽃순이김치
    "kkotsuni", "절임", "발효", "염도", "레시피",
    # 송월타월
    "songwol", "와인딩", "에이징", "타월",
    # 사업계획서 잔재 (D-02)
    "포밍", "롤포밍", "로봇용접", "레토르트", "판금", "금속 구조",
)
# 정본 문장을 그대로 렌더하는 화면은 잔재 용어를 **인용**할 수 있다. 그때는 그 용어 **바로 옆**에
# 근거 D-번호가 있어야 한다. 본문 어딘가에 D-번호가 있다고 봐주면 검사가 통째로 무력해진다(§10-16).
# ① 근거 D-번호  ② 원 산출물명 병기  ③ **배제를 명시하는 문장**
#   — "예지보전 AI는 본 사업 범위 밖이다" 는 오염이 아니라 가드레일 진술이다(goal.md §6 "내용으로 판단").
QUOTE_OK = re.compile(
    r"(D-0[12]|원 산출물명|범위 밖|미적용|제외한다|제외하며|제외됨|포함하지 않|대상이 아니|수집원이 없|만들지 않는다)"
)
CONTEXT = 160   # 용어 주변 몇 글자까지 근거로 인정할지


def _quoted_with_basis(body: str, term: str) -> list[int]:
    """용어가 나온 위치 중 **근거 없이** 나온 것만 돌려준다."""
    bare = []
    for m in re.finditer(re.escape(term), body):
        near = body[max(0, m.start() - CONTEXT): m.end() + CONTEXT]
        if not QUOTE_OK.search(near):
            bare.append(m.start())
    return bare

# 'pH' 는 영문 두 글자라 오탐이 많다 — 단어 경계로만 본다.
PH_RE = re.compile(r"\bpH\b")


def main() -> int:
    client = TestClient(app, raise_server_exceptions=False)
    fails: list[str] = []

    # ── G-06 메뉴 단일 소스 ──────────────────────────────────────────
    menu = nav.menu()
    areas_json = {g.get("area") or g.get("name") for g in design._design()["td3"]["screens"]}
    areas_nav = {s.area for s in nav.all_screens()}
    g06 = []
    if len(menu) != 10:
        g06.append(f"메뉴 영역 {len(menu)} ≠ 10")
    if areas_nav != areas_json:
        g06.append(f"nav 영역 ≠ design.json 영역: {areas_nav ^ areas_json}")
    if len(nav.all_screens()) != len(design.screens()):
        g06.append(f"nav 화면 {len(nav.all_screens())} ≠ TD3 {len(design.screens())}")
    dup = {s.path for s in nav.all_screens()}
    if len(dup) != len(nav.all_screens()):
        g06.append("경로 중복")
    smap = ROOT / "contracts" / "screen-map.md"
    if not smap.exists():
        g06.append("contracts/screen-map.md 미작성")
    else:
        txt = smap.read_text()
        missing = [s.id for s in nav.all_screens() if s.id not in txt]
        if missing:
            g06.append(f"screen-map.md 에 없는 화면 {len(missing)}건: {missing[:3]}…")
    print(f"G-06 메뉴 10영역 단일 소스: {'PASS' if not g06 else 'FAIL'}"
          f"{'' if not g06 else ' — ' + ' / '.join(g06)}")
    fails += g06

    # ── G-03 응답 코드 ───────────────────────────────────────────────
    targets = [("공통", p) for p in ("/", "/login", "/popup", "/board", "/error")]
    targets += [(s.id, s.path) for s in nav.all_screens()]
    bad_status: list[str] = []
    bodies: dict[str, str] = {}
    for label, path in targets:
        r = client.get(path)
        # /error 는 공통 오류 화면 자체이므로 200 으로 렌더한다
        if r.status_code != 200:
            bad_status.append(f"{label} {path} → {r.status_code}")
        bodies[path] = r.text

    h = client.get("/health")
    if h.status_code != 200:
        bad_status.append(f"/health → {h.status_code} ({h.text[:120]})")

    print(f"G-03-① 전 화면 200 ({len(targets)}개): "
          f"{'PASS' if not bad_status else 'FAIL'}"
          f"{'' if not bad_status else ' — ' + '; '.join(bad_status[:5])}")
    fails += bad_status

    # ── G-03 placeholder 0건 ─────────────────────────────────────────
    n = len(PLACEHOLDERS)
    print(f"G-03-② _placeholder 0건: {'PASS' if n == 0 else 'FAIL'} — 현재 {n}건"
          f"{'' if n == 0 else ' (' + ', '.join(PLACEHOLDERS[:3]) + ' …)'}")
    if n:
        fails.append(f"placeholder {n}건")

    # ── G-03 타 사업 용어 0건 (렌더 결과 + 소스) ──────────────────────
    hits: list[str] = []
    for path, body in bodies.items():
        for term in FOREIGN_TERMS:
            bare = _quoted_with_basis(body, term)
            if bare:
                hits.append(f"{path}: '{term}' × {len(bare)} (근거 없음)")
        for m in PH_RE.finditer(body):
            near = body[max(0, m.start() - CONTEXT): m.end() + CONTEXT]
            if not QUOTE_OK.search(near):
                hits.append(f"{path}: 'pH' (근거 없음)")
                break
    src_hits: list[str] = []
    for py in sorted((ROOT / "src").rglob("*.py")):
        txt = py.read_text()
        for term in FOREIGN_TERMS:
            for m in re.finditer(re.escape(term), txt):
                near = txt[max(0, m.start() - CONTEXT): m.end() + CONTEXT]
                if not QUOTE_OK.search(near):
                    src_hits.append(f"{py.relative_to(ROOT)}:{txt[:m.start()].count(chr(10)) + 1} '{term}'")
    print(f"G-03-③ 타 사업 용어 0건: {'PASS' if not (hits or src_hits) else 'FAIL'}"
          f" — 렌더 {len(hits)}건 · 소스 {len(src_hits)}건"
          f"{'' if not (hits or src_hits) else ' ' + str((hits + src_hits)[:5])}")
    fails += hits + src_hits

    print(f"\n판정: {'PASS' if not fails else f'FAIL ({len(fails)}건)'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
