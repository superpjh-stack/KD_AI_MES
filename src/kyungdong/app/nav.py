"""메뉴 단일 소스 (goal.md G-06) — 10영역 45화면.

**여기 말고 다른 곳에 메뉴를 두지 않는다.** 화면 목록·순서·경로·소유자는 전부 이 파일이 정본이고
`contracts/screen-map.md` 는 여기서 생성한다. 화면 자체는 `design.json`(SF-TD3)에서 읽는다 — 45행을
손으로 적지 않는다.

메뉴 순서는 `td3.menu_shortcuts` 를 따른다(goal.md §5 아키텍트).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from . import design

# ── 메뉴 바로가기(td3.menu_shortcuts) ↔ TD3 업무영역 ──────────────────────
# JSON 이 둘을 잇지 않으므로 여기서 명시한다(추측 금지). 10 ↔ 10 이 아니면 기동 시 터진다.
SHORTCUT_TO_AREA: dict[str, str] = {
    "대시보드": "AI 대시보드",
    "견적AI": "수주견적AI관리",
    "입고": "입고재고관리",
    "공정": "공정관리",
    "출하": "출하물류관리",
    "기준": "기준정보관리",
    "데이터": "데이터관리",
    "Agent": "AI Agent 통합관리",
    "KPI": "KPI관리",
    "시스템": "사용자/시스템관리",
}

# 업무영역 ↔ URL 접두 · 기본 소유자 (goal.md §3.2 · §3.4)
AREA_PREFIX: dict[str, tuple[str, str]] = {
    "AI 대시보드":        ("dsh", "개발2"),
    "수주견적AI관리":      ("est", "개발3"),
    "입고재고관리":        ("inv", "개발1"),
    "공정관리":           ("prc", "개발2"),
    "출하물류관리":        ("shp", "개발2"),
    "기준정보관리":        ("bas", "개발1"),
    "데이터관리":          ("dat", "개발1"),
    "AI Agent 통합관리":  ("agt", "개발3"),
    "KPI관리":           ("kpi", "개발2"),
    "사용자/시스템관리":    ("sys", "개발1"),
}

# 영역과 소유자가 갈리는 화면 (goal.md §3.2). URL 은 업무영역을 따르고 **구현 파일만** 옮긴다 —
# 사용자가 보는 메뉴 위치는 산출물 그대로 두면서 "한 파일은 한 사람만" 을 지키기 위해서다.
OWNER_OVERRIDE: dict[str, tuple[str, str]] = {
    "MES-TD3-009": ("개발3", "agt"),   # 입고 AI Agent  — 메뉴는 입고, 구현은 agt.py
    "MES-TD3-020": ("개발3", "agt"),   # 출하 AI Agent  — 메뉴는 출하, 구현은 agt.py
    "MES-TD3-037": ("개발3", "est"),   # AI학습 데이터관리 — 메뉴는 데이터, 구현은 est.py
}

# 공통 화면 (td3.common_screens 4종 + 오류)
COMMON_ROUTES: dict[str, str] = {
    "login": "/login",
    "common": "/",              # 메인시안
    "dashboard": "/board",      # 현황판 65" 2대
    "popup": "/popup",
    "error": "/error",
}


@dataclass(frozen=True)
class Screen:
    id: str            # MES-TD3-001
    no: str            # 001
    name: str
    area: str
    shortcut: str      # 좌측 메뉴 바로가기
    path: str          # /dsh/001
    prefix: str        # dsh
    owner: str         # 개발1|2|3
    module: str        # app/routers/<module>.py
    program_id: str    # MES-TD4-001
    requirement_id: str  # MES-AD2-001
    channels: str


@cache
def menu() -> list[tuple[str, list[Screen]]]:
    """좌측 메뉴 — (바로가기, 화면들). 순서는 td3.menu_shortcuts."""
    shortcuts = design._design()["td3"]["menu_shortcuts"]
    if set(shortcuts) != set(SHORTCUT_TO_AREA):
        raise RuntimeError(
            f"menu_shortcuts 와 SHORTCUT_TO_AREA 가 다르다: "
            f"{set(shortcuts) ^ set(SHORTCUT_TO_AREA)}"
        )

    by_area: dict[str, list[Screen]] = {a: [] for a in SHORTCUT_TO_AREA.values()}
    for sid, s in sorted(design.screens().items()):
        area = s["area"]
        if area not in AREA_PREFIX:
            raise RuntimeError(f"{sid}: TD3 업무영역 '{area}' 이 AREA_PREFIX 에 없다")
        prefix, owner = AREA_PREFIX[area]
        owner, module = OWNER_OVERRIDE.get(sid, (owner, prefix))
        no = sid.rsplit("-", 1)[-1]
        by_area[area].append(Screen(
            id=sid, no=no, name=s["name"], area=area,
            shortcut=next(k for k, v in SHORTCUT_TO_AREA.items() if v == area),
            path=f"/{prefix}/{no}", prefix=prefix, owner=owner, module=module,
            program_id=f"MES-TD4-{no}", requirement_id=f"MES-AD2-{no}",
            channels=s.get("channels") or "",
        ))
    return [(sc, by_area[SHORTCUT_TO_AREA[sc]]) for sc in shortcuts]


@cache
def all_screens() -> list[Screen]:
    return [s for _, group in menu() for s in group]


@cache
def by_id() -> dict[str, Screen]:
    return {s.id: s for s in all_screens()}


@cache
def by_path() -> dict[str, Screen]:
    return {s.path: s for s in all_screens()}


def owned_by(owner: str) -> list[Screen]:
    return [s for s in all_screens() if s.owner == owner]


def modules() -> dict[str, list[Screen]]:
    out: dict[str, list[Screen]] = {}
    for s in all_screens():
        out.setdefault(s.module, []).append(s)
    return out
