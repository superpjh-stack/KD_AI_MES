"""정본 로더 — SF-TD1~TD5(design.json) · SF-AD1~AD3(analysis.json).

goal.md §0.3: **코드 범위의 정본은 이 두 JSON 이다.** 화면의 모든 칸은 여기서 온 문장이다.
지어내지 않는다 — 없으면 비우고 `미확정 (D-nn)` 을 렌더한다.

`contracts/interfaces.md` 공표 시그니처:
    screen(sid) · program(pid) · requirement(rid) · table_def(tid)
    screens() · programs() · requirements() · tables()
"""
from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DESIGN_PATH = ROOT / "docs" / "design" / "design.json"
ANALYSIS_PATH = ROOT / "docs" / "design" / "analysis.json"

# 정본이 정한 규모. 값이 흔들리면 정본이 바뀐 것이므로 즉시 드러나야 한다(goal.md §0.2).
EXPECT = {
    "screens": 45, "areas": 10, "programs": 49, "tables": 68, "columns": 762,
    "common_screens": 4, "roles": 6, "functional": 45, "nonfunctional": 13,
}

_TABLE_REF = re.compile(r"([A-Z][A-Z0-9_]{2,})\s*\(")


@cache
def _design() -> dict[str, Any]:
    return json.loads(DESIGN_PATH.read_text())


@cache
def _analysis() -> dict[str, Any]:
    return json.loads(ANALYSIS_PATH.read_text())


def meta() -> dict[str, Any]:
    return _design()["meta"]


# ── 화면 (SF-TD3) ────────────────────────────────────────────────────────
@cache
def screens() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in _design()["td3"]["screens"]:
        area = group.get("area") or group.get("name") or ""
        for s in group["screens"]:
            out[s["id"]] = {**s, "area": area}
    return out


def screen(sid: str) -> dict[str, Any] | None:
    return screens().get(sid)


@cache
def common_screens() -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in _design()["td3"]["common_screens"]}


@cache
def role_matrix() -> dict[str, Any]:
    return _design()["td3"]["role_matrix"]


def layout_rules() -> Any:
    return _design()["td3"].get("layout_rules")


def standard_note() -> Any:
    return _design()["td3"].get("standard_note")


# ── 프로그램 (SF-TD4) ────────────────────────────────────────────────────
@cache
def programs() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in _design()["td4"]["details"]:
        area = group.get("area") or group.get("name") or ""
        for p in group["programs"]:
            out[p["id"]] = {**p, "area": area}
    return out


def program(pid: str) -> dict[str, Any] | None:
    return programs().get(pid)


def program_tables(pid: str) -> list[str]:
    """TD4 `tables` 문자열에서 테이블 ID 만 뽑는다 — 'PRC_PERFORMANCES(공정실적관리), …'."""
    p = program(pid)
    if not p:
        return []
    known = tables()
    return [t for t in _TABLE_REF.findall(p.get("tables") or "") if t in known]


# ── 테이블 (SF-TD5) ──────────────────────────────────────────────────────
@cache
def tables() -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in _design()["td5"]["details"]}


def table_def(tid: str) -> dict[str, Any] | None:
    return tables().get(tid)


def columns_of(tid: str) -> list[dict[str, str]]:
    """컬럼 행 [한글명, 영문명, 타입, PK, FK, NULL, 비고] 을 dict 로."""
    t = table_def(tid)
    if not t:
        return []
    keys = ("ko", "name", "type", "pk", "fk", "nullable", "note")
    return [dict(zip(keys, (c.strip() for c in row))) for row in t["columns"]]


# ── 요구사항 (SF-AD2) ────────────────────────────────────────────────────
@cache
def requirements() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ad2 = _analysis()["ad2"]
    for kind, key in (("기능", "functional_groups"), ("비기능", "nonfunctional_groups")):
        for group in ad2[key]:
            area = group.get("name") or group.get("area") or ""
            for r in group["requirements"]:
                out[r["id"]] = {**r, "area": area, "kind": kind}
    return out


def requirement(rid: str) -> dict[str, Any] | None:
    return requirements().get(rid)


def functional_ids() -> list[str]:
    return sorted(r["id"] for r in requirements().values() if r["kind"] == "기능")


def nonfunctional_ids() -> list[str]:
    return sorted(r["id"] for r in requirements().values() if r["kind"] == "비기능")


# ── 추적 (요구사항 ↔ 화면 ↔ 프로그램 1:1) ────────────────────────────────
def trace(no: str) -> dict[str, Any]:
    """세 자리 순번으로 세 산출물을 묶는다 — AD2-001 ↔ TD3-001 ↔ TD4-001 (goal.md G-04)."""
    return {
        "no": no,
        "requirement": requirement(f"MES-AD2-{no}"),
        "screen": screen(f"MES-TD3-{no}"),
        "program": program(f"MES-TD4-{no}"),
    }


def selfcheck() -> dict[str, tuple[int, int, bool]]:
    """정본 실측값 ↔ EXPECT 대조. gate.py 와 테스트가 쓴다."""
    d = _design()
    got = {
        "screens": len(screens()),
        "areas": len(d["td3"]["screens"]),
        "programs": len(programs()),
        "tables": len(tables()),
        "columns": sum(len(t["columns"]) for t in tables().values()),
        "common_screens": len(common_screens()),
        "roles": len(role_matrix()["rows"]),
        "functional": len(functional_ids()),
        "nonfunctional": len(nonfunctional_ids()),
    }
    return {k: (got[k], EXPECT[k], got[k] == EXPECT[k]) for k in EXPECT}
