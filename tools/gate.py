#!/usr/bin/env python
"""goal.md §2 수용 게이트 G-01~G-30 판정표.

원칙 (goal.md §4.3 · §10):
  · 여기서 게이트를 낮추지 않는다. 못 재면 `미구현`(측정기 없음) 이지 PASS 가 아니다.
  · QA 소유 검사기(check_*.py)는 **있으면 호출하고 없으면 `미구현`** — 여기서 만들지 않는다.
  · 그룹 종료코드 하나로 여러 게이트를 뭉개지 않는다. 게이트별 판정 줄을 파싱한다(§10-6).
  · 측정 중 동시 변경을 감지하면 FAIL 이 아니라 `판정 불가` 다(§10-17).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design" / "design.json"
ANALYSIS = ROOT / "docs" / "design" / "analysis.json"
DSN = os.environ.get("KYUNGDONG_PG_DSN", "postgresql:///kyungdong_db")

PASS, FAIL, BLOCKED, NOIMPL = "PASS", "FAIL", "차단", "미구현"


@dataclass
class Row:
    gate: str
    name: str
    verdict: str
    measured: str = ""
    how: str = ""


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)

    def add(self, *a, **k) -> None:
        self.rows.append(Row(*a, **k))


def psql(sql: str) -> str | None:
    try:
        r = subprocess.run(
            ["psql", "-d", DSN, "-Atc", sql],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def qa_checker(name: str) -> Path | None:
    p = ROOT / "tools" / name
    return p if p.exists() else None


def structural(rep: Report) -> None:
    d = json.loads(DESIGN.read_text())
    a = json.loads(ANALYSIS.read_text())
    td3, td4, td5 = d["td3"], d["td4"], d["td5"]

    want_tables = len(td5["details"])
    want_cols = sum(len(t["columns"]) for t in td5["details"])
    want_screens = sum(len(g["screens"]) for g in td3["screens"])
    want_progs = sum(len(x["programs"]) for x in td4["details"])
    want_areas = len(td3["screens"])

    got = psql("select count(*) from information_schema.tables where table_schema='public'")
    rep.add("G-01", f"테이블 {want_tables}", 
            PASS if got == str(want_tables) else (FAIL if got is not None else NOIMPL),
            f"{got or 'DB 연결 실패'}", "information_schema.tables")

    got = psql("select count(*) from information_schema.columns where table_schema='public'")
    rep.add("G-02", f"컬럼 {want_cols}",
            PASS if got == str(want_cols) else (FAIL if got is not None else NOIMPL),
            f"{got or 'DB 연결 실패'}",
            "information_schema.columns (엄밀 대조는 tools/check_schema.py — QA2)")

    routes = qa_checker("check_routes.py")
    if not routes:
        rep.add("G-03", f"화면 {want_screens}+공통 4+오류 1 · placeholder 0 · 타 사업 용어 0",
                NOIMPL, "", "tools/check_routes.py (아키텍트) 미작성")
        rep.add("G-06", f"메뉴 {want_areas}영역 단일 소스", NOIMPL, "", "같은 검사기")
    else:
        # 그룹 종료코드 하나로 뭉개지 않는다 — 게이트별 판정 줄을 파싱한다(§10-6).
        r = subprocess.run([sys.executable, str(routes)], capture_output=True, text=True, timeout=600)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("G-03", "G-06"))]
        for prefix, label in (("G-06", f"메뉴 {want_areas}영역 단일 소스"),
                              ("G-03", f"화면 {want_screens}+공통 4+오류 1 · placeholder 0 · 용어 0")):
            mine = [ln for ln in lines if ln.startswith(prefix)]
            if not mine:
                rep.add(prefix, label, NOIMPL, "판정 줄 없음", f"tools/check_routes.py 출력 형식 확인")
                continue
            verdict = PASS if all("PASS" in ln for ln in mine) else FAIL
            rep.add(prefix, label, verdict,
                    " / ".join(ln.split(":", 1)[1].strip() for ln in mine),
                    "tools/check_routes.py")

    trace = qa_checker("check_trace.py")
    rep.add("G-04", f"요구사항 추적 AD2 45 ↔ TD3 ↔ TD4 1:1",
            NOIMPL if not trace else FAIL, "", "tools/check_trace.py (QA1) 미작성")
    rep.add("G-05", f"프로그램 {want_progs} (화면 45 + 인터페이스 4)",
            NOIMPL if not trace else FAIL, "", "tools/check_trace.py (QA1) 미작성")

    # 정본 자체가 흔들리지 않았는지 (이 문서의 숫자가 곧 게이트다)
    f = sum(len(g["requirements"]) for g in a["ad2"]["functional_groups"])
    n = sum(len(g["requirements"]) for g in a["ad2"]["nonfunctional_groups"])
    ok = (want_screens, want_areas, want_progs, want_tables, want_cols, f, n) == (
        45, 10, 49, 68, 762, 45, 13)
    rep.add("정본", "design/analysis 실측 = goal.md 표",
            PASS if ok else FAIL,
            f"화면{want_screens} 영역{want_areas} 프로그램{want_progs} 표{want_tables}"
            f" 컬럼{want_cols} 기능{f} 비기능{n}", "§9 재확인 명령")


CHECKERS = [
    ("G-07~G-11", "데이터 게이트 (시드 멱등·디지털 스레드·정확성/정합성/연계성·시계열·빈 칸)", "check_data.py", "QA2"),
    ("G-12~G-13", "수집·전처리 (유실 0·Gateway 재전송·Feature 생성)", "check_ingest.py", "QA2"),
    ("G-14~G-25", "AI 게이트 (CAD 인식·견적·BOM·납기·설명가능성·RAG·HITL·MLOps)", "check_ai.py", "QA3"),
    ("G-26~G-30", "보안·운영 (암호화·계정·RBAC·감사·조용한 실패)", "check_security.py", "QA3"),
]


def checkers(rep: Report) -> None:
    for gate, name, script, owner in CHECKERS:
        p = qa_checker(script)
        if not p:
            rep.add(gate, name, NOIMPL, "", f"tools/{script} ({owner}) 미작성 — gate.py 가 만들지 않는다")
            continue
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, timeout=900)
        rep.add(gate, name, PASS if r.returncode == 0 else FAIL,
                r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "",
                f"tools/{script}")


def build(rep: Report) -> None:
    """§2.6 빌드 게이트. §10-15 — '몇 건 실행됐는지' 를 반드시 본다. 0건이면 판정 무효다."""
    if not list((ROOT / "tests").glob("test_*.py")):
        rep.add("G-빌드", "pytest 전건 통과", NOIMPL, "테스트 0파일", "tests/ 비어 있음")
        return
    # -q 는 pyproject addopts 에 이미 있다. 여기서 또 주면 -qq 가 되어 **요약 줄이 사라진다**.
    r = subprocess.run(["uv", "run", "pytest"], capture_output=True, text=True,
                       cwd=ROOT, timeout=1800)
    # 마지막 줄을 요약으로 믿지 않는다 — 경고 문서 URL 이 뒤에 붙는다. 요약 줄을 찾아서 센다(§10-15).
    summary = next(
        (ln.strip() for ln in reversed(r.stdout.splitlines())
         if re.search(r"\b\d+\s+(passed|failed|error)", ln)),
        "",
    )
    m = re.search(r"(\d+)\s+passed", summary)
    ran = int(m.group(1)) if m else 0
    if not summary or ran == 0:
        verdict, measured = BLOCKED, f"실행 0건 — 판정 불가 (출력: {summary or '요약 줄 없음'})"
    elif r.returncode == 0:
        verdict, measured = PASS, summary
    else:
        verdict, measured = FAIL, summary
    rep.add("G-빌드", "pytest 전건 통과", verdict, measured,
            "uv run pytest  ※ 실행 0건이면 그 회전 판정은 전부 무효(§10-15)")


def main() -> int:
    rep = Report()
    structural(rep)
    checkers(rep)
    build(rep)

    w = max(len(r.name) for r in rep.rows)
    print(f"{'게이트':<10} {'항목':<{w}}  {'판정':<6} 실측")
    print("─" * (10 + w + 30))
    for r in rep.rows:
        print(f"{r.gate:<10} {r.name:<{w}}  {r.verdict:<6} {r.measured}")
    tally = {v: sum(1 for r in rep.rows if r.verdict == v) for v in (PASS, FAIL, BLOCKED, NOIMPL)}
    print("─" * (10 + w + 30))
    print(f"PASS {tally[PASS]} · FAIL {tally[FAIL]} · 차단 {tally[BLOCKED]} · 미구현 {tally[NOIMPL]}"
          f"  /  {len(rep.rows)}")
    print("\n검증 방법")
    for r in rep.rows:
        if r.how:
            print(f"  {r.gate}: {r.how}")
    return 0 if tally[FAIL] == 0 and tally[NOIMPL] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
