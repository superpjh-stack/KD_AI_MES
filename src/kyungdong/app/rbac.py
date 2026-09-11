"""RBAC (goal.md G-28) — TD3 `role_matrix` 6역할 × 8권한영역 그대로.

권한 없음 = **403**(§2.5). 좌측 메뉴는 권한 있는 것만 노출한다.
역할·셀 문구는 산출물 정본에서 읽는다 — 손으로 적지 않는다.

**개인정보 주의(G-29)**: TD3 역할명에 실명이 들어 있다(예: "총괄PM/경영자 (제미애 대표)").
UI 라벨과 시드에는 **실명을 쓰지 않고** 직무명만 쓴다. 원문은 `source_label` 에 보관한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from . import design

# TD3 role_matrix 의 8개 권한영역 ↔ 10개 TD3 업무영역
PERM_AREA_TO_AREAS: dict[str, tuple[str, ...]] = {
    "AI 대시보드":        ("AI 대시보드",),
    "수주견적AI관리":      ("수주견적AI관리",),
    "입고재고관리":        ("입고재고관리",),
    "출하물류관리":        ("출하물류관리",),
    "공정관리":           ("공정관리",),
    "기준정보·데이터":      ("기준정보관리", "데이터관리"),
    "AI Agent·KPI":     ("AI Agent 통합관리", "KPI관리"),
    "사용자/시스템관리":    ("사용자/시스템관리",),
}

# 셀 문구 → 권한. TD3 가 쓴 어휘만 해석하고, 모르는 문구는 예외로 터뜨린다(조용히 넘기지 않는다).
_READ = ("조회", "리포트", "검토", "승인", "질의", "입력", "등록", "수정", "전체", "설정", "계정")
_WRITE = ("등록", "수정", "입력", "전체", "계정", "설정")
_APPROVE = ("승인", "전체")

_ROLE_CODE = {
    "총괄PM/경영자": "EXEC",
    "품질·RCMS 담당": "QUALITY",
    "공장장·생산관리": "PRODUCTION",
    "현장 작업자": "OPERATOR",
    "공급기업 운영담당": "SUPPLIER_OPS",
    "시스템 관리자": "SYSADMIN",
}


@dataclass(frozen=True)
class Perm:
    read: bool
    write: bool
    approve: bool
    label: str          # 산출물 원문 셀 ("조회/승인", "POP·패드 입력", "-")

    @property
    def none(self) -> bool:
        return not (self.read or self.write or self.approve)


@dataclass(frozen=True)
class Role:
    code: str
    name: str           # 직무명만 (실명 제거 — G-29)
    source_label: str   # TD3 원문
    perms: dict[str, Perm]   # 권한영역 → Perm


def _parse_cell(cell: str) -> Perm:
    c = (cell or "").strip()
    if c in ("-", "", "없음"):
        return Perm(False, False, False, c or "-")
    if not any(k in c for k in _READ):
        raise RuntimeError(f"role_matrix 셀 문구를 해석할 수 없다: {c!r} — rbac.py 에 어휘를 추가하라")
    return Perm(
        read=True,
        write=any(k in c for k in _WRITE),
        approve=any(k in c for k in _APPROVE),
        label=c,
    )


@cache
def roles() -> dict[str, Role]:
    rm = design.role_matrix()
    cols = rm["columns"][1:]              # 첫 열은 '사용자 유형'
    if list(cols) != list(PERM_AREA_TO_AREAS):
        raise RuntimeError(f"role_matrix 권한영역이 PERM_AREA_TO_AREAS 와 다르다: {cols}")

    out: dict[str, Role] = {}
    for row in rm["rows"]:
        source = row[0].strip()
        name = re.sub(r"\s*\([^)]*\)\s*$", "", source).strip()   # 괄호 안 실명 제거
        code = _ROLE_CODE.get(name)
        if not code:
            raise RuntimeError(f"역할 '{name}' 의 코드가 _ROLE_CODE 에 없다")
        out[code] = Role(
            code=code, name=name, source_label=source,
            perms={area: _parse_cell(cell) for area, cell in zip(cols, row[1:])},
        )
    return out


@cache
def _area_to_perm_area() -> dict[str, str]:
    return {a: pa for pa, areas in PERM_AREA_TO_AREAS.items() for a in areas}


def perm_for(role_code: str, area: str) -> Perm:
    """TD3 업무영역에 대한 권한. 모르는 역할·영역은 권한 없음으로 본다(열어주지 않는다)."""
    role = roles().get(role_code)
    if role is None:
        return Perm(False, False, False, "-")
    pa = _area_to_perm_area().get(area)
    if pa is None:
        return Perm(False, False, False, "-")
    return role.perms[pa]


def can_read(role_code: str, area: str) -> bool:
    return perm_for(role_code, area).read


def can_write(role_code: str, area: str) -> bool:
    return perm_for(role_code, area).write


def can_approve(role_code: str, area: str) -> bool:
    """견적 확정·발주·검사 합격·출하 승인 (G-24). 승인 권한 없으면 403."""
    return perm_for(role_code, area).approve
