#!/usr/bin/env python
"""contracts/screen-map.md 생성기 — 정본은 `app/nav.py` 다. 손으로 적으면 어긋난다."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav, rbac   # noqa: E402

OUT = ROOT / "contracts" / "screen-map.md"

OWNER_FILES = {
    "아키텍트": "`contracts/*` · `app/{main,nav,rbac,settings,design,templating,auth}.py` · `app/util/*` · "
                "`app/templates/{base,login,_placeholder,_popup,_error,common,board}.html` · `app/static/*` · "
                "`db/{schema.sql,conn.py,seed.py}` · `tools/{gen_schema,gen_screen_map,check_routes,gate}.py` · "
                "`Makefile` · `pyproject.toml` · `.env.example`",
    "개발1": "`app/routers/{inv,bas,sys,dat}.py` · `app/templates/{inv,bas,sys,dat}/` · `db/seed_dev1.py` · "
             "`tests/test_dev1_*.py` · `progress-dev1.md` · `decisions-dev1.md`",
    "개발2": "`app/routers/{dsh,prc,shp,kpi}.py` · `app/kpi.py` · `app/templates/{dsh,prc,shp,kpi}/` · "
             "`db/seed_dev2.py` · `tests/test_dev2_*.py` · `progress-dev2.md` · `decisions-dev2.md`",
    "개발3": "`app/routers/{est,agt,ingest}.py` · `src/kyungdong/{agent,ml,cad,ingest}/*` · "
             "`app/templates/{est,agt}/` · `tools/{plc_simulator,cad_ingest}.py` · `db/seed_dev3.py` · "
             "`tests/test_dev3_*.py` · `progress-dev3.md` · `decisions-dev3.md`",
    "QA1": "`tools/check_trace.py` · `tests/test_qa1_*.py` · `outputs/qa1-기능계약.md`",
    "QA2": "`tools/{check_schema,check_data,check_ingest}.py` · `tests/test_qa2_*.py` · `outputs/qa2-데이터정합.md`",
    "QA3": "`tools/{check_ai,check_security}.py` · `work/rag_goldset.json` · `work/cad_labelset.json` · "
           "`tests/test_qa3_*.py` · `outputs/qa3-AI비기능보안.md`",
}


def main() -> int:
    screens = nav.all_screens()
    L: list[str] = [
        "# contracts/screen-map.md — 화면 45 ↔ 담당 ↔ 소유 파일",
        "",
        "> **생성 파일이다.** 정본은 `src/kyungdong/app/nav.py` 이고 `tools/gen_screen_map.py` 가 뽑는다.",
        "> 손으로 고치지 않는다. **코드와 다르면 코드가 맞다**(goal.md §4.1) → `nav.py` 를 고치고 다시 생성한다.",
        "",
        f"화면 **{len(screens)}** · 업무영역 **{len(nav.menu())}** · 프로그램 **{len(design.programs())}**"
        f" · 테이블 **{len(design.tables())}** · 컬럼 **{sum(len(t['columns']) for t in design.tables().values())}**",
        "",
        "## 1. 화면 45",
        "",
        "| # | 화면 ID | 화면명 | 업무영역 | 메뉴 | 경로 | 요구사항 | 프로그램 | 담당 | 구현 파일 | 채널 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(screens, 1):
        mark = " ⚠" if s.module != s.prefix else ""
        L.append(
            f"| {i} | {s.id} | {s.name} | {s.area} | {s.shortcut} | `{s.path}` | "
            f"{s.requirement_id} | {s.program_id} | **{s.owner}**{mark} | `routers/{s.module}.py` | {s.channels} |"
        )

    odd = [s for s in screens if s.module != s.prefix]
    L += [
        "",
        "⚠ = **업무영역과 구현 파일이 갈리는 화면**. URL·메뉴 위치는 산출물(SF-TD3) 그대로 두고 "
        "구현 파일만 옮겨 \"한 파일은 한 사람만\" 을 지킨다.",
        "",
        "| 화면 | 메뉴 위치 | 구현 | 이유 |",
        "|---|---|---|---|",
    ]
    for s in odd:
        L.append(f"| {s.id} {s.name} | `{s.path}` ({s.shortcut}) | `routers/{s.module}.py` ({s.owner}) "
                 f"| AI 화면이라 개발3 이 소유한다 (goal.md §3.2) |")

    cnt = Counter(s.owner for s in screens)
    L += [
        "",
        "## 2. 소유권 — 동시 기동 시 이 표가 곧 계약 (goal.md §3.4)",
        "",
        "| 소유자 | 화면 수 | 파일 |",
        "|---|---|---|",
        f"| 아키텍트 | — | {OWNER_FILES['아키텍트']} |",
    ]
    for who in ("개발1", "개발2", "개발3"):
        L.append(f"| {who} | **{cnt[who]}** | {OWNER_FILES[who]} |")
    for who in ("QA1", "QA2", "QA3"):
        L.append(f"| {who} | — | {OWNER_FILES[who]} |")

    L += [
        "",
        f"합계 화면 **{cnt['개발1']} + {cnt['개발2']} + {cnt['개발3']} = {sum(cnt.values())}**",
        "",
        "## 3. 모듈별 화면",
        "",
        "| 구현 파일 | 화면 수 | 화면 |",
        "|---|---|---|",
    ]
    for module, group in sorted(nav.modules().items()):
        L.append(f"| `routers/{module}.py` | {len(group)} | {', '.join(s.no for s in group)} |")

    L += [
        "",
        "## 4. 공통 화면",
        "",
        "| ID | 이름 | 경로 | 담당 |",
        "|---|---|---|---|",
    ]
    for cid, path in nav.COMMON_ROUTES.items():
        name = design.common_screens().get(cid, {}).get("name", "공통 오류 화면")
        L.append(f"| {cid} | {name} | `{path}` | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |")

    rm = rbac.roles()
    L += [
        "",
        "## 5. RBAC — 6역할 × 8권한영역 (goal.md G-28 · TD3 role_matrix)",
        "",
        "R=조회 · W=등록/수정 · A=승인. 권한 없음(`-`) = **403**.",
        "",
        "| 역할 | " + " | ".join(rbac.PERM_AREA_TO_AREAS) + " |",
        "|---" * (len(rbac.PERM_AREA_TO_AREAS) + 1) + "|",
    ]
    for r in rm.values():
        cells = []
        for area in rbac.PERM_AREA_TO_AREAS:
            p = r.perms[area]
            flag = ("R" if p.read else "") + ("W" if p.write else "") + ("A" if p.approve else "")
            cells.append(flag or "–")
        L.append(f"| {r.name} | " + " | ".join(cells) + " |")
    L += [
        "",
        "역할 라벨에서 **실명은 제거했다**(G-29 개인정보). 산출물 원문은 `rbac.Role.source_label` 에 있다.",
        "",
    ]

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L))
    print(f"생성: {OUT.relative_to(ROOT)} — 화면 {len(screens)} · 영역 {len(nav.menu())}"
          f" · 소유 개발1 {cnt['개발1']} / 개발2 {cnt['개발2']} / 개발3 {cnt['개발3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
