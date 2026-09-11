#!/usr/bin/env python
"""G-07 ~ G-11 데이터 게이트 + **KPI 독립 재계산** (QA2).

원칙 (goal.md §4.3 · §10)
  · **게이트를 낮추지 않는다.** 못 맞추면 `차단`, 못 재면 `판정 불가` 다. PASS 가 아니다.
  · **없는 데이터를 만들어 통과시키지 않는다.** 시드가 막힌 것은 막혔다고 적는다.
  · **0건 경로와 N건 경로를 둘 다 명시 단언한다**(§10-4). `skip` 은 결함이다(D-62).
  · **정본 함수를 직접 부른다**(§10-16) — `design.columns_of` · `codes.code_columns` ·
    `clock.anchor` · `kpi.measure`. 로직을 복제하지 않는다.
    단 **KPI 만은 예외로 SQL 을 새로 써서 독립 재계산**한다 — `app/kpi.py` 를 믿지 않는 것이
    이 검사기의 목적이다(goal.md §7 QA2).
  · 측정 중 정본·스키마가 바뀌면 FAIL 이 아니라 `판정 불가`(§10-17).
  · **건수 카드의 `0 건` 은 정답이다**(§10-14). '미수집' 문구는 **빈 그리드**에만 요구한다.
    0 에 문구를 강제하면 수집된 사실을 부정하는 거짓 표시가 된다 — 직전 사업의 실제 오판이다.

§10-11: 이 검사기는 `make db-seed` 를 돌린다. 끝나고 **공통 시드로 되돌린다**.
"""
from __future__ import annotations

import ast
import html as htmllib
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                    # noqa: E402
from kyungdong.app import design, kpi as kpimod, nav           # noqa: E402
from kyungdong.app.util import clock, codes                    # noqa: E402

PASS, FAIL, BLOCKED, UNDET = "PASS", "FAIL", "차단", "판정 불가"
THRESHOLD = 85.0          # 사업계획서 2.7.4 · D-23 — 정확성·정합성·연계성·LOT 매핑 전부 85%

VERDICTS: list[tuple[str, str, str]] = []       # (게이트, 판정, 실측 한 줄)
NOTES: list[str] = []


def say(line: str = "") -> None:
    print(line)


def verdict(gate: str, v: str, measured: str) -> None:
    VERDICTS.append((gate, v, measured))


def pct(num: float, den: float) -> float | None:
    """비율(%). **분모 0 이면 `None`** — 0% 라고도 100% 라고도 말하지 않는다."""
    return None if not den else round(num / den * 100.0, 1)


def pct_text(v: float | None) -> str:
    return "판정 불가(분모 0)" if v is None else f"{v} %"


# ── 공통 실측 ────────────────────────────────────────────────────────────
TABLES = sorted(design.tables())            # 정본 함수 (§10-16)


def snapshot() -> dict[str, int]:
    sql = " union all ".join(f"select '{t}' as t, count(*) as n from {t}" for t in TABLES)
    return {r["t"]: int(r["n"]) for r in conn.q(sql)}


def run_seed() -> tuple[int, str]:
    r = subprocess.run(["make", "db-seed"], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    return r.returncode, (r.stdout + r.stderr)


# ══ G-07 시드 멱등 · 시간 앵커 ═══════════════════════════════════════════
# `datetime.now()` 가 허용되는 자리 — 근거를 적는다. 여기 없는 곳에 있으면 위반이다.
NOW_ALLOWED: dict[tuple[str, str], str] = {
    ("db/seed.py", "seed_anchor"):
        "앵커 **발급** 자체다. 발급된 값은 SYS_CONFIGS 에 고정되고 재실행은 그 값을 그대로 쓴다",
    ("tools/plc_simulator.py", "main"):
        "`--realtime` 분기 — 003·022 수집 배지를 실시각으로 시험하는 전용 옵션이다",
    ("src/kyungdong/ingest/collector.py", "status"):
        "수집이 **지금** 살아 있는지 묻는 함수다. 생성 기준일이 아니다",
}
SCAN_ROOTS = ("db", "tools", "src")
BANNED = {("date", "today"), ("datetime", "today"), ("datetime", "utcnow")}
WATCHED = {("datetime", "now")}


def _enclosing_func(tree: ast.AST, lineno: int) -> str:
    best = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                best = node.name
    return best


def scan_clock() -> tuple[list[str], list[str]]:
    """소스에서 `date.today()`·`datetime.now()` 를 **AST 로** 찾는다 (주석·문서열 오탐 없음)."""
    banned: list[str] = []
    watched: list[str] = []
    for root in SCAN_ROOTS:
        for p in sorted((ROOT / root).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if rel.startswith("tools/check_"):
                continue                      # QA 검사기 자신은 데이터 생성 코드가 아니다
            try:
                tree = ast.parse(p.read_text())
            except SyntaxError as e:
                banned.append(f"{rel}: 파싱 실패 {e}")
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                base = node.func.value
                if not isinstance(base, ast.Name):
                    continue
                key = (base.id, node.func.attr)
                where = f"{rel}:{node.lineno} ({_enclosing_func(tree, node.lineno)})"
                if key in BANNED:
                    banned.append(f"{where} — {base.id}.{node.func.attr}()")
                elif key in WATCHED:
                    fn = _enclosing_func(tree, node.lineno)
                    why = NOW_ALLOWED.get((rel, fn))
                    if why:
                        watched.append(f"{where} — 허용: {why}")
                    else:
                        banned.append(
                            f"{where} — datetime.now() 가 허용 목록에 없다."
                            " 생성 기준일이면 clock.anchor() 를 쓴다(§10-3)")
    return banned, watched


def gate_07() -> None:
    say("── G-07 시드 멱등 · 시간 앵커 ─────────────────────────────────")
    a0 = clock.anchor()                                   # 정본 함수 (§10-16)
    s0 = snapshot()

    rc1, out1 = run_seed()
    s1 = snapshot()
    rc2, out2 = run_seed()
    s2 = snapshot()
    a1 = clock.anchor()

    d01 = {t: (s1[t] - s0[t]) for t in TABLES if s1[t] != s0[t]}
    d12 = {t: (s2[t] - s1[t]) for t in TABLES if s2[t] != s1[t]}

    # ── 동시 변경 감지 — FAIL 이 아니라 **판정 불가** 다 (§10-17) ──────────
    # 두 가지 독립 신호로 본다 (회전 6 교훈: 한 신호만 보고 판정하지 않는다).
    #   ① 정지 상태 확인 — 시드를 돌리지 않았는데 행이 움직이면 밖에서 누가 쓰고 있다
    #   ② 되돌아온 변동 — s0→s1 로 늘었다가 s1→s2 로 같은 만큼 줄면 롤백 트랜잭션이 지나갔다
    #      (다른 QA·개발 테스트가 사슬을 만들었다 지우는 패턴이다)
    q0 = snapshot()
    time.sleep(2)
    q1 = snapshot()
    quiet = {t: (q1[t] - q0[t]) for t in TABLES if q0[t] != q1[t]}
    bounced = {t for t in d12 if d01.get(t, 0) == -d12[t]}
    concurrent = bool(quiet) or (bool(d12) and bounced == set(d12))

    # 0건 경로와 N건 경로를 **둘 다** 단언한다 (§10-4)
    zero_tables = [t for t in TABLES if s2[t] == 0]
    n_tables = {t: s2[t] for t in TABLES if s2[t] > 0}
    zero_moved = [t for t in zero_tables if s0[t] != 0]
    n_moved = [t for t in n_tables if d12.get(t)]

    say(f"  시드 1회차 exit {rc1} · 2회차 exit {rc2}")
    say(f"  N건 경로  행이 있는 표 {len(n_tables)}종 — " +
        " · ".join(f"{t} {n}" for t, n in sorted(n_tables.items())[:12]) +
        (" …" if len(n_tables) > 12 else ""))
    say(f"  0건 경로  0건인 표 {len(zero_tables)}종 — 두 번 돌린 뒤에도 0건 유지 "
        f"(변동 {len(zero_moved)}종)")
    say(f"  행 수 diff  1회차→2회차 {len(d12)}종 변동" + (f" {d12}" if d12 else ""))
    if d01:
        say(f"  (참고) 검사 시작 상태→1회차 변동 {len(d01)}종 {d01} — 시작 상태가 시드 직후가 아니었다")
    say(f"  시간 앵커  {a0.isoformat(sep=' ')} → {a1.isoformat(sep=' ')}"
        f"  ({'불변' if a0 == a1 else '**변동**'})")

    banned, watched = scan_clock()
    say(f"  소스 스캔  date.today()/datetime.today()/utcnow() 및 미허용 datetime.now(): {len(banned)}건")
    for w in watched:
        say(f"    허용 {w}")
    for b in banned:
        say(f"    위반 {b}")

    if concurrent:
        say(f"  **동시 변경 감지** — 정지 상태 변동 {quiet or '없음'} · "
            f"되돌아온 변동 {sorted(bounced) or '없음'}")
        say("  다른 프로세스가 같은 DB 에 쓰고 있다. FAIL 이 아니라 **판정 불가** 다(§10-17). "
            "조용한 창에서 다시 잰다")
    ok = rc1 == 0 and rc2 == 0 and not d12 and a0 == a1 and not banned
    verdict("G-07", UNDET if concurrent else (PASS if ok else FAIL),
            (f"동시 변경 중 측정 — 판정 불가(§10-17) · 되돌아온 변동 {len(bounced)}종 · "
             f"정지 상태 변동 {len(quiet)}종" if concurrent else
             f"db-seed ×2 행수 diff {len(d12)}종 · 앵커 {'불변' if a0 == a1 else '변동'}"
             f" · 시간함수 위반 {len(banned)} · N건 표 {len(n_tables)} · 0건 표 {len(zero_tables)}"))
    say()


# ══ G-08 디지털 스레드 (양방향) · LOT 매핑 성공률 ═════════════════════════
# contracts/db-schema.md §5 의 9단계. `INV_MATERIAL_LOTS` 에는 PROJECT_ID 가 없고
# BOM ↔ 자재LOT 는 `SHP_LOT_TRACES(BOM_ID, MATERIAL_LOT_ID)` 가 잇는다 — 실측 구조 그대로 쓴다.
CHAIN = [
    ("1 EST_PROJECTS→2 EST_CAD_DRAWINGS",
     "select count(*) from EST_PROJECTS p where exists "
     "(select 1 from EST_CAD_DRAWINGS d where d.PROJECT_ID = p.PROJECT_ID)",
     "select count(*) from EST_CAD_DRAWINGS d where d.PROJECT_ID is not null and exists "
     "(select 1 from EST_PROJECTS p where p.PROJECT_ID = d.PROJECT_ID)",
     "select count(*) from EST_PROJECTS", "select count(*) from EST_CAD_DRAWINGS"),
    ("2 EST_CAD_DRAWINGS→3 EST_BOM_HEADERS",
     "select count(*) from EST_CAD_DRAWINGS d where exists "
     "(select 1 from EST_BOM_HEADERS b where b.DRAWING_ID = d.DRAWING_ID)",
     "select count(*) from EST_BOM_HEADERS b where b.DRAWING_ID is not null and exists "
     "(select 1 from EST_CAD_DRAWINGS d where d.DRAWING_ID = b.DRAWING_ID)",
     "select count(*) from EST_CAD_DRAWINGS", "select count(*) from EST_BOM_HEADERS"),
    ("3 EST_BOM_HEADERS→4 INV_MATERIAL_LOTS (SHP_LOT_TRACES 경유)",
     "select count(*) from EST_BOM_HEADERS b where exists "
     "(select 1 from SHP_LOT_TRACES t where t.BOM_ID = b.BOM_ID and t.MATERIAL_LOT_ID is not null)",
     "select count(*) from INV_MATERIAL_LOTS m where exists "
     "(select 1 from SHP_LOT_TRACES t where t.MATERIAL_LOT_ID = m.LOT_ID and t.BOM_ID is not null)",
     "select count(*) from EST_BOM_HEADERS", "select count(*) from INV_MATERIAL_LOTS"),
    ("4 INV_MATERIAL_LOTS→5 PRC_WORK_ORDERS (SHP_LOT_TRACES 경유)",
     "select count(*) from INV_MATERIAL_LOTS m where exists "
     "(select 1 from SHP_LOT_TRACES t where t.MATERIAL_LOT_ID = m.LOT_ID and t.WORK_ORDER_ID is not null)",
     "select count(*) from PRC_WORK_ORDERS w where exists "
     "(select 1 from SHP_LOT_TRACES t where t.WORK_ORDER_ID = w.WORK_ORDER_ID "
     " and t.MATERIAL_LOT_ID is not null)",
     "select count(*) from INV_MATERIAL_LOTS", "select count(*) from PRC_WORK_ORDERS"),
    ("5 PRC_WORK_ORDERS→6 PRC_PERFORMANCES",
     "select count(*) from PRC_WORK_ORDERS w where exists "
     "(select 1 from PRC_PERFORMANCES f where f.WORK_ORDER_ID = w.WORK_ORDER_ID)",
     "select count(*) from PRC_PERFORMANCES f where exists "
     "(select 1 from PRC_WORK_ORDERS w where w.WORK_ORDER_ID = f.WORK_ORDER_ID)",
     "select count(*) from PRC_WORK_ORDERS", "select count(*) from PRC_PERFORMANCES"),
    ("6 PRC_PERFORMANCES→7 SHP_LOT_TRACES",
     "select count(*) from PRC_PERFORMANCES f where f.LOT_TRACE_ID is not null and exists "
     "(select 1 from SHP_LOT_TRACES t where t.LOT_TRACE_ID = f.LOT_TRACE_ID)",
     "select count(*) from SHP_LOT_TRACES t where exists "
     "(select 1 from PRC_PERFORMANCES f where f.LOT_TRACE_ID = t.LOT_TRACE_ID)",
     "select count(*) from PRC_PERFORMANCES", "select count(*) from SHP_LOT_TRACES"),
    ("7 SHP_LOT_TRACES→8 SHP_INSPECTIONS",
     "select count(*) from SHP_LOT_TRACES t where exists "
     "(select 1 from SHP_INSPECTIONS i where i.LOT_TRACE_ID = t.LOT_TRACE_ID)",
     "select count(*) from SHP_INSPECTIONS i where exists "
     "(select 1 from SHP_LOT_TRACES t where t.LOT_TRACE_ID = i.LOT_TRACE_ID)",
     "select count(*) from SHP_LOT_TRACES", "select count(*) from SHP_INSPECTIONS"),
    ("8 SHP_INSPECTIONS→9 SHP_SHIPMENTS (SHP_SHIPMENT_ITEMS 경유)",
     "select count(*) from SHP_INSPECTIONS i where exists "
     "(select 1 from SHP_SHIPMENT_ITEMS s where s.INSPECT_ID = i.INSPECT_ID)",
     "select count(*) from SHP_SHIPMENTS h where exists "
     "(select 1 from SHP_SHIPMENT_ITEMS s where s.SHIPMENT_ID = h.SHIPMENT_ID "
     " and s.INSPECT_ID is not null)",
     "select count(*) from SHP_INSPECTIONS", "select count(*) from SHP_SHIPMENTS"),
]

# LOT 한 건이 9단계 전부에 이어졌는지 — **독립 재계산**. TD5 `MAPPING_OK_YN` 을 믿지 않는다.
LOT_FULL_CHAIN = """
select count(*) as total,
       count(*) filter (where
            t.PROJECT_ID is not null
        and t.BOM_ID is not null
        and t.MATERIAL_LOT_ID is not null
        and t.WORK_ORDER_ID is not null
        and exists (select 1 from EST_PROJECTS p       where p.PROJECT_ID = t.PROJECT_ID)
        and exists (select 1 from EST_CAD_DRAWINGS d
                     join EST_BOM_HEADERS b on b.DRAWING_ID = d.DRAWING_ID
                     where b.BOM_ID = t.BOM_ID)
        and exists (select 1 from INV_MATERIAL_LOTS m  where m.LOT_ID = t.MATERIAL_LOT_ID)
        and exists (select 1 from PRC_WORK_ORDERS w    where w.WORK_ORDER_ID = t.WORK_ORDER_ID)
        and exists (select 1 from PRC_PERFORMANCES f   where f.LOT_TRACE_ID = t.LOT_TRACE_ID)
        and exists (select 1 from SHP_INSPECTIONS i    where i.LOT_TRACE_ID = t.LOT_TRACE_ID)
        and exists (select 1 from SHP_SHIPMENT_ITEMS s
                     join SHP_SHIPMENTS h on h.SHIPMENT_ID = s.SHIPMENT_ID
                     where s.LOT_TRACE_ID = t.LOT_TRACE_ID)
       ) as linked,
       count(*) filter (where t.MAPPING_OK_YN = 'Y') as declared
from SHP_LOT_TRACES t
"""


def gate_08() -> None:
    say("── G-08 디지털 스레드 (양방향) · LOT 매핑 성공률 ≥ 85% ──────────")
    broken_fwd = broken_bwd = 0
    measurable = 0
    for label, fwd, bwd, fwd_den, bwd_den in CHAIN:
        f = int(conn.q1(f"select ({fwd}) as n")["n"])
        b = int(conn.q1(f"select ({bwd}) as n")["n"])
        fd = int(conn.q1(f"select ({fwd_den}) as n")["n"])
        bd = int(conn.q1(f"select ({bwd_den}) as n")["n"])
        if fd:
            measurable += 1
            if f == 0:
                broken_fwd += 1
        if bd and b == 0:
            broken_bwd += 1
        say(f"  {label:<52} 정방향 {f}/{fd} ({pct_text(pct(f, fd))})"
            f" · 역방향 {b}/{bd} ({pct_text(pct(b, bd))})")

    row = conn.q1(LOT_FULL_CHAIN)
    total, linked, declared = int(row["total"]), int(row["linked"]), int(row["declared"])
    rate = pct(linked, total)
    decl_rate = pct(declared, total)
    say(f"  LOT 매핑 (독립 재계산)  전체 {total} · 9단계 완주 {linked} → {pct_text(rate)}")
    say(f"  LOT 매핑 (선언값 MAPPING_OK_YN='Y')  {declared} → {pct_text(decl_rate)}")
    if total and linked != declared:
        say(f"  **선언값과 실측이 다르다** — MAPPING_OK_YN 이 실제 연결을 반영하지 않는다")

    if total == 0:
        verdict("G-08", BLOCKED,
                f"SHP_LOT_TRACES 0건 · 측정 가능한 사슬 단계 {measurable}/8 — "
                "EST_PROJECTS 0건(D-47·D-56)이 전제라 매핑률 분모가 없다. 0% 도 100% 도 아니다")
    else:
        ok = rate is not None and rate >= THRESHOLD and broken_fwd == 0 and broken_bwd == 0
        verdict("G-08", PASS if ok else FAIL,
                f"LOT 매핑 {pct_text(rate)} (기준 {THRESHOLD}%) · 사슬 끊김 정방향 {broken_fwd}"
                f" · 역방향 {broken_bwd}")
    say()


# ══ G-09 정확성 · 정합성 · 연계성 (사업계획서 2.7.4 표) ═══════════════════
def accuracy(run=None) -> tuple[int, int, list[str]]:
    """정확성 = 정상 데이터 수 ÷ 전체 × 100.

    **'정상' 의 조작적 정의**: 그 행의 **코드성 FK 29건(§3)** 값이 전부
    `BAS_COMMON_CODES(CODE_GROUP, CODE_VALUE, USE_YN='Y')` 에 있는 행.
    사업계획서 2.7.4 는 '정상' 을 정의하지 않았다 — 여기서 정한 정의를 리포트에 함께 적는다.
    분모는 **코드성 컬럼을 가진 표의 전체 행**이다.

    `run(sql, params) -> dict` 를 주면 그 실행기로 잰다 — 테스트가 **롤백 트랜잭션 안에서**
    N건 경로를 실증할 때 쓴다(§10-4). 기본은 `conn.q1` 이다. 산식은 한 벌뿐이다(§10-16).
    """
    run = run or conn.q1
    by_table: dict[str, list[tuple[str, str]]] = {}
    for (tid, col), group in codes.code_columns().items():      # 정본 함수 (§10-16)
        by_table.setdefault(tid, []).append((col, group))
    total = ok = 0
    bad: list[str] = []
    for tid, cols in sorted(by_table.items()):
        conds, params = [], []
        for col, group in sorted(cols):
            if not group:
                bad.append(f"{tid}.{col}: 코드 그룹 미정의 — util/codes.py COLUMN_GROUP (D-32)")
                conds.append("false")
                continue
            conds.append(
                f"({col} is null or {col} = '' or exists (select 1 from BAS_COMMON_CODES b "
                f"where b.CODE_GROUP = %s and b.CODE_VALUE = {tid}.{col} and b.USE_YN = 'Y'))")
            params.append(group)
        r = run(
            f"select count(*) as total, count(*) filter (where {' and '.join(conds)}) as ok "
            f"from {tid}", params)
        total += int(r["total"])
        ok += int(r["ok"])
        if int(r["total"]) and int(r["ok"]) != int(r["total"]):
            bad.append(f"{tid}: {int(r['total']) - int(r['ok'])}행이 코드성 FK 검증에 걸린다")
    return ok, total, bad


# ── `contracts/missing-policy.md` §4 조건 ②③ — 구조 제약이 강제하지만 **실측한다** ──
def notnull_violations(run=None) -> int:
    """§4-② NOT NULL 컬럼에 값이 있다. DB 가 강제하므로 **위반 불가**지만 0 임을 잰다."""
    run = run or conn.q1
    n = 0
    for tid in sorted(design.tables()):
        cols = [c["name"] for c in design.columns_of(tid)
                if c["pk"] != "Y" and c["nullable"].strip().upper() == "N"]
        if not cols:
            continue
        where = " or ".join(f"{c} is null" for c in cols)
        n += int(run(f"select count(*) as n from {tid} where {where}")["n"])
    return n


def fk_orphans(run=None) -> tuple[int, int]:
    """§4-③ 물리 FK 가 실제 행을 가리키는가. (제약 수, 고아 행 수) — 제약이 강제하므로 0 이어야 한다."""
    run = run or conn.q1
    fks = conn.q(
        "select con.conname, src.relname as src, att.attname as col, "
        "       tgt.relname as tgt, tatt.attname as tcol "
        "from pg_constraint con "
        "join pg_class src on src.oid = con.conrelid "
        "join pg_class tgt on tgt.oid = con.confrelid "
        "join pg_namespace n on n.oid = src.relnamespace "
        "join pg_attribute att on att.attrelid = con.conrelid and att.attnum = con.conkey[1] "
        "join pg_attribute tatt on tatt.attrelid = con.confrelid and tatt.attnum = con.confkey[1] "
        "where con.contype = 'f' and n.nspname = 'public' order by 1")
    orphans = 0
    for f in fks:
        orphans += int(run(
            f"select count(*) as n from {f['src']} s where s.{f['col']} is not null "
            f"and not exists (select 1 from {f['tgt']} t where t.{f['tcol']} = s.{f['col']})")["n"])
    return len(fks), orphans


# §4-④ 수치 범위 — **판정에서 제외한다.** 규약이 그렇게 정했다(범위 표가 정본에 없다).
RANGE_EXCLUDED = ("contracts/missing-policy.md §4-④ — 단위 표준 수치 범위 표가 정본에 없어 "
                  "이 항목은 정확성 판정에서 제외한다(규약이 명시)")


CONSISTENCY = [
    # (이름, 비교 가능 건, 일치 건)
    ("BOM 자재 ↔ 자재LOT 재질",
     "select count(*) from SHP_LOT_TRACES t join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "join EST_BOM_ITEMS i on i.BOM_ID = t.BOM_ID "
     "where m.MATERIAL is not null and i.MATERIAL is not null",
     "select count(*) from SHP_LOT_TRACES t join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "join EST_BOM_ITEMS i on i.BOM_ID = t.BOM_ID "
     "where m.MATERIAL is not null and i.MATERIAL is not null and m.MATERIAL = i.MATERIAL"),
    ("CAD Feature 두께 ↔ 자재LOT 두께",
     "select count(*) from EST_CAD_FEATURES f join EST_BOM_HEADERS b on b.DRAWING_ID = f.DRAWING_ID "
     "join SHP_LOT_TRACES t on t.BOM_ID = b.BOM_ID "
     "join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "where f.FEATURE_TYPE = '두께' and f.FEATURE_VALUE is not null and m.THICKNESS_MM is not null",
     "select count(*) from EST_CAD_FEATURES f join EST_BOM_HEADERS b on b.DRAWING_ID = f.DRAWING_ID "
     "join SHP_LOT_TRACES t on t.BOM_ID = b.BOM_ID "
     "join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "where f.FEATURE_TYPE = '두께' and f.FEATURE_VALUE is not null and m.THICKNESS_MM is not null "
     "and abs(f.FEATURE_VALUE - m.THICKNESS_MM) <= 0.01"),
    ("CAD Feature 총 절단장 ↔ 자재LOT 길이",
     "select count(*) from EST_CAD_FEATURES f join EST_BOM_HEADERS b on b.DRAWING_ID = f.DRAWING_ID "
     "join SHP_LOT_TRACES t on t.BOM_ID = b.BOM_ID "
     "join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "where f.FEATURE_TYPE = '총 절단장' and f.FEATURE_VALUE is not null and m.LENGTH_MM is not null",
     "select count(*) from EST_CAD_FEATURES f join EST_BOM_HEADERS b on b.DRAWING_ID = f.DRAWING_ID "
     "join SHP_LOT_TRACES t on t.BOM_ID = b.BOM_ID "
     "join INV_MATERIAL_LOTS m on m.LOT_ID = t.MATERIAL_LOT_ID "
     "where f.FEATURE_TYPE = '총 절단장' and f.FEATURE_VALUE is not null and m.LENGTH_MM is not null "
     "and f.FEATURE_VALUE <= m.LENGTH_MM"),
    ("BOM 공정 ↔ 견적 공정원가 (Cross Check)",
     "select count(*) from EST_BOM_ROUTINGS r join EST_BOM_HEADERS b on b.BOM_ID = r.BOM_ID "
     "join EST_QUOTATIONS q on q.PROJECT_ID = b.PROJECT_ID "
     "join EST_QUOTATION_ITEMS qi on qi.QUOTE_ID = q.QUOTE_ID",
     "select count(*) from EST_BOM_ROUTINGS r join EST_BOM_HEADERS b on b.BOM_ID = r.BOM_ID "
     "join EST_QUOTATIONS q on q.PROJECT_ID = b.PROJECT_ID "
     "join EST_QUOTATION_ITEMS qi on qi.QUOTE_ID = q.QUOTE_ID "
     "where qi.PROCESS_CODE = r.PROCESS_CODE"),
    ("견적 단가 ↔ 원가단가기준 (EST_COST_RATES)",
     "select count(*) from EST_QUOTATION_ITEMS qi where qi.UNIT_PRICE is not null",
     "select count(*) from EST_QUOTATION_ITEMS qi where qi.UNIT_PRICE is not null and exists "
     "(select 1 from EST_COST_RATES c where c.TARGET_CODE = qi.PROCESS_CODE "
     " and c.USE_YN = 'Y' and c.UNIT_PRICE = qi.UNIT_PRICE)"),
]

LINKAGE = """
select count(*) as total,
       count(*) filter (where
            exists (select 1 from EST_CAD_DRAWINGS d where d.PROJECT_ID = p.PROJECT_ID)
        and exists (select 1 from EST_BOM_HEADERS  b where b.PROJECT_ID = p.PROJECT_ID)
        and exists (select 1 from PRC_WORK_ORDERS  w where w.PROJECT_ID = p.PROJECT_ID)
        and exists (select 1 from SHP_LOT_TRACES t join SHP_INSPECTIONS i
                      on i.LOT_TRACE_ID = t.LOT_TRACE_ID where t.PROJECT_ID = p.PROJECT_ID)
        and exists (select 1 from SHP_SHIPMENTS   h where h.PROJECT_ID = p.PROJECT_ID)
       ) as linked
from EST_PROJECTS p
"""


def gate_09() -> None:
    say("── G-09 정확성 · 정합성 · 연계성 (각 ≥ 85% · 사업계획서 2.7.4) ────")
    ok, total, bad = accuracy()
    acc = pct(ok, total)
    nn = notnull_violations()
    nfk, orphan = fk_orphans()
    say(f"  정확성  정상 {ok} ÷ 전체 {total} × 100 = {pct_text(acc)}")
    say("          '정상' 의 조작적 정의는 `contracts/missing-policy.md` §4 다"
        " (QA2 DEF-QA2-012 를 아키텍트가 규약으로 확정했다)")
    say(f"          ① 코드성 FK 29건 유효 — 분모 {total} · 정상 {ok}")
    say(f"          ② NOT NULL 컬럼에 값이 있다 — 위반 {nn} (DB 제약이 강제한다. 실측으로 0 확인)")
    say(f"          ③ 물리 FK {nfk}건이 실제 행을 가리킨다 — 고아 행 {orphan}")
    say(f"          ④ {RANGE_EXCLUDED}")
    for b in bad:
        say(f"          · {b}")
    if nn or orphan:
        bad.append(f"§4-②③ 위반 — NOT NULL {nn} · FK 고아 {orphan}")

    comp_total = comp_ok = 0
    for name, den_sql, num_sql in CONSISTENCY:
        d = int(conn.q1(f"select ({den_sql}) as n")["n"])
        n = int(conn.q1(f"select ({num_sql}) as n")["n"])
        comp_total += d
        comp_ok += n
        say(f"  정합성  {name:<40} 비교가능 {d} · 일치 {n} ({pct_text(pct(n, d))})")
    con = pct(comp_ok, comp_total)
    say(f"  정합성  합계 {comp_ok} ÷ {comp_total} × 100 = {pct_text(con)}")

    r = conn.q1(LINKAGE)
    lt, ll = int(r["total"]), int(r["linked"])
    lnk = pct(ll, lt)
    say(f"  연계성  수주→도면→BOM→생산→검사→출하 전부 이어진 프로젝트 {ll} ÷ {lt} = {pct_text(lnk)}")

    parts = {"정확성": (acc, total), "정합성": (con, comp_total), "연계성": (lnk, lt)}
    undecidable = [k for k, (v, d) in parts.items() if v is None or d == 0]
    below = [f"{k} {v}%" for k, (v, d) in parts.items() if v is not None and d and v < THRESHOLD]
    struct = f"§4-② NOT NULL 위반 {nn} · §4-③ FK 고아 {orphan}/{nfk}제약 · §4-④ 판정 제외"
    if undecidable:
        verdict("G-09", BLOCKED,
                f"분모 0 → 판정 불가(규약 §5): {' · '.join(undecidable)}"
                f" (측정된 것: " + " · ".join(
                    f"{k} {pct_text(v)}" for k, (v, d) in parts.items()) + f") · {struct}")
    else:
        verdict("G-09", FAIL if (below or nn or orphan) else PASS,
                " · ".join(f"{k} {pct_text(v)}" for k, (v, _d) in parts.items())
                + f" (기준 {THRESHOLD}%)" + (f" · 미달 {', '.join(below)}" if below else "")
                + f" · {struct}")
    say()


# ══ G-10 시계열 신뢰성 — 규약: `contracts/missing-policy.md` ═══════════════
# **동기화율 목표가 사업계획서에 없다(D-09·규약 §0). 실측만 보고한다.**
POLICY = ROOT / "contracts" / "missing-policy.md"


def missing_rate(run=None) -> dict:
    """규약 §2.1 결측률.

    ```
    분모 = (측정 구간 길이 ÷ PLC_POLL_SEC) × 활성 태그 수     — 비가동 구간 제외
    분자 = 실제 적재 건수
    결측률 = 1 − 분자 ÷ 분모
    ```
    · §1 — **수집 지점 2개소 밖은 분모에 넣지 않는다.** 자동 폴링 대상은 `DEVICE_TYPE='PLC'` 뿐이고
      현장POP(터치PC)은 사람이 입력하므로 기대 수집 건수가 없다(미수집이지 결측이 아니다).
    · §2.1 — 비가동(`RUN_STATUS='정지'`) 시각의 기대 건수를 뺀다.
      **상태를 모르는 구간은 결측률에서 제외하고 그 사실을 적는다.**
    · §5 — **분모 0 이면 `None`.** 0% 도 100% 도 아니다.
    """
    run = run or conn.q1
    from kyungdong.ingest import tags as ingest_tags      # 정본 태그표 (§10-16)
    from kyungdong.app.settings import settings

    poll = settings().h("PLC_POLL_SEC").as_int() or 1
    active_tags = len(ingest_tags.TAGS)
    # 규약 문자 그대로 'IF_PLC_SIGNALS 에 정의된 활성 태그' 로도 세어 본다 (§2.1 문구)
    tags_in_ledger = int(run("select count(distinct TAG_NAME) as n from IF_PLC_SIGNALS")["n"])

    out = {"poll_sec": poll, "active_tags": active_tags, "tags_in_ledger": tags_in_ledger,
           "devices": [], "expected": 0, "stored": 0, "excluded_idle": 0, "unknown_state": 0}
    devs = conn.q("select DEVICE_ID, DEVICE_NAME, DEVICE_TYPE from IF_DEVICE_REGISTRY "
                  "where USE_YN = 'Y' order by DEVICE_ID")
    for d in devs:
        if d["device_type"] != "PLC":
            out["devices"].append({"name": d["device_name"], "polled": False,
                                   "why": "자동 폴링 대상이 아니다 — 수동 입력(규약 §1)"})
            continue
        span = run("select min(COLLECT_DT) as a, max(COLLECT_DT) as b, "
                   "count(distinct (TAG_NAME, COLLECT_DT)) as n "
                   "from IF_PLC_SIGNALS where DEVICE_ID = %s", (d["device_id"],))
        if span["a"] is None:
            out["devices"].append({"name": d["device_name"], "polled": True, "span": None,
                                   "why": "적재 0건 — 측정 구간이 없다(분모 0, 규약 §5)"})
            continue
        ticks = int((span["b"] - span["a"]).total_seconds() // poll) + 1
        idle = int(run("select count(*) as n from PRC_EQUIP_SIGNALS "
                       "where RUN_STATUS = '정지' and COLLECT_DT between %s and %s",
                       (span["a"], span["b"]))["n"])
        unknown = int(run("select count(*) as n from PRC_EQUIP_SIGNALS "
                          "where RUN_STATUS is null and COLLECT_DT between %s and %s",
                          (span["a"], span["b"]))["n"])
        expected = (ticks - idle - unknown) * active_tags
        out["expected"] += max(expected, 0)
        out["stored"] += int(span["n"])
        out["excluded_idle"] += idle
        out["unknown_state"] += unknown
        out["devices"].append({
            "name": d["device_name"], "polled": True,
            "span": (span["a"], span["b"]), "ticks": ticks, "idle": idle, "unknown": unknown,
            "expected": max(expected, 0), "stored": int(span["n"])})
    out["rate"] = (None if not out["expected"]
                   else round((1 - out["stored"] / out["expected"]) * 100.0, 1))
    return out


def gate_10() -> None:
    say("── G-10 시계열 (Timestamp 정렬 · 결측/지연 기록) ────────────────")
    ts_n = int(conn.q1("select count(*) as n from DAT_TIMESERIES")["n"])
    sg_n = int(conn.q1("select count(*) as n from PRC_EQUIP_SIGNALS")["n"])

    # 적재 순서(PK) 와 측정 시각의 정렬이 어긋난 건수 — 같은 태그·설비 안에서 본다
    ts_bad = int(conn.q1(
        "select count(*) as n from ("
        " select MEASURE_DT, lag(MEASURE_DT) over (partition by TAG_NAME, EQUIP_CODE order by TS_ID) as prev"
        " from DAT_TIMESERIES) x where prev is not null and MEASURE_DT < prev")["n"])
    sg_bad = int(conn.q1(
        "select count(*) as n from ("
        " select COLLECT_DT, lag(COLLECT_DT) over (partition by EQUIP_CODE order by SIGNAL_ID) as prev"
        " from PRC_EQUIP_SIGNALS) x where prev is not null and COLLECT_DT < prev")["n"])
    dup = int(conn.q1(
        "select count(*) as n from (select TAG_NAME, EQUIP_CODE, MEASURE_DT from DAT_TIMESERIES "
        "group by 1,2,3 having count(*) > 1) x")["n"])
    miss = int(conn.q1("select count(*) as n from DAT_TIMESERIES where QUALITY_FLAG = '결측'")["n"])
    noise = int(conn.q1("select count(*) as n from DAT_TIMESERIES where QUALITY_FLAG = '노이즈'")["n"])
    buf = conn.q("select BUFFER_STATUS, count(*) as n from IF_GATEWAY_BUFFER group by 1 order by 1")
    logs = int(conn.q1("select count(*) as n from DAT_JOB_LOGS")["n"])
    log_fail = int(conn.q1("select coalesce(sum(FAIL_CNT),0) as n from DAT_JOB_LOGS")["n"])

    say(f"  DAT_TIMESERIES {ts_n} 행 · 정렬 위반 {ts_bad} · 중복 (태그,설비,시각) {dup}"
        f" · 결측 {miss} · 노이즈 {noise}")
    say(f"  PRC_EQUIP_SIGNALS {sg_n} 행 · 정렬 위반 {sg_bad}")
    say(f"  IF_GATEWAY_BUFFER  " + (" · ".join(f"{b['buffer_status']} {b['n']}" for b in buf) or "0 건"))
    say(f"  DAT_JOB_LOGS {logs} 건 · 실패 누계 {log_fail}")
    # ── 규약 `contracts/missing-policy.md` 대조 ────────────────────────
    say(f"  규약 문서 `contracts/missing-policy.md` "
        f"{'있음' if POLICY.exists() else '**없음** — goal.md §2.2 G-10 이 가리키는 문서가 부재다'}")
    if not POLICY.exists():
        verdict("G-10", BLOCKED, "결측 분모·분자 규약 문서가 없다 — 분모를 검사기가 임의로 정할 수 없다")
        say()
        return

    m = missing_rate()
    rate_text = "판정 불가 (분모 0 · 규약 §5)" if m["rate"] is None else f"{m['rate']} %"
    say(f"  §2.1 수집 결측률  분모 {m['expected']} = (구간 ÷ {m['poll_sec']}초 − 비가동 − 상태미상)"
        f" × 활성태그 {m['active_tags']} · 분자 {m['stored']} → {rate_text}")
    for d in m["devices"]:
        if not d["polled"]:
            say(f"    §1 분모 제외  {d['name']} — {d['why']}")
        elif d.get("span") is None:
            say(f"    {d['name']} — {d['why']}")
        else:
            say(f"    {d['name']}  구간 {d['span'][0]}~{d['span'][1]} · 틱 {d['ticks']}"
                f" · 비가동 제외 {d['idle']} · 상태미상 제외 {d['unknown']}"
                f" · 기대 {d['expected']} · 적재 {d['stored']}")
    say(f"    **상태를 모르는 구간 {m['unknown_state']}틱은 결측률에서 제외했다**(규약 §2.1 명시 요구)")
    say(f"  부가 실측  적재된 행 중 QUALITY_FLAG='결측' 비율 {pct_text(pct(miss, ts_n))} "
        "— 규약 §2.1 의 수집 결측률과 **다른 지표**다(값 결측 vs 미적재)")
    say(f"  §2.2 지연  Gateway 재전송분은 '지연'이지 '결측'이 아니다 — IF_GATEWAY_BUFFER "
        + (" · ".join(f"{b['buffer_status']} {b['n']}" for b in buf) or "0 건"))
    say(f"  §3 기록 위치  IF_GATEWAY_BUFFER {int(conn.q1('select count(*) as n from IF_GATEWAY_BUFFER')['n'])}"
        f" · DAT_JOB_LOGS {logs} · DAT_PREPROCESS_RULES "
        f"{int(conn.q1('select count(*) as n from DAT_PREPROCESS_RULES')['n'])}"
        f" · DAT_QUALITY_CHECKS {int(conn.q1('select count(*) as n from DAT_QUALITY_CHECKS')['n'])}")
    say("  §0 목표치  **사업계획서에 시계열 동기화율 목표가 없다**(D-09). 실측만 보고한다 — "
        "직전 사업(광성정밀)의 85%·PTP 1s 를 가져오지 않는다")

    if m["rate"] is None:
        verdict("G-10", BLOCKED,
                f"규약 §2.1 분모 0 → 판정 불가(§5). DAT_TIMESERIES {ts_n} · PRC_EQUIP_SIGNALS {sg_n}"
                " — `make db-reset` 직후 0건은 정상이다(수집은 시드가 아니다)."
                " N건 경로는 tools/check_ingest.py 와 tests/test_qa2_ingest.py 가 시뮬레이터로 잰다")
    else:
        verdict("G-10", PASS if ts_bad == 0 and sg_bad == 0 else FAIL,
                f"§2.1 수집 결측률 {rate_text} (목표 없음 — D-09·규약 §0, 실측만 보고)"
                f" · §2.3 정렬 위반 시계열 {ts_bad} · 설비신호 {sg_bad}"
                f" · 상태미상 제외 {m['unknown_state']}틱")
    say()


# ══ G-11 조용한 빈칸 — **그리드 vs 건수 카드 vs 비율 카드** ════════════════
#
# 세 가지를 **명문화해서 구분한다**(§10-14 · 직전 사업에서 실제로 난 오판이다).
#
#   ① 그리드(표) 가 비었다      → `미수집 / 미확정 (D-nn)` **문구가 있어야 한다.**
#   ② 건수 카드의 값이 `0 건`   → **0 이 정답이다.** 여기에 '미수집' 을 요구하면
#                                 수집된 사실(=세어 봤더니 0이다)을 부정하는 **거짓 표시**가 된다.
#   ③ 비율·평균 카드의 분모가 0 → 값이 **없는 것**이다. `미수집` 이 맞고 `0 %` 로 메우면 결함이다.
#
# 그래서 판정은 **카드 값(`span.v`)** 을 보고 한다. 보조설명(`span.s`)에 '0건' 이 들어 있다는
# 이유로 비율 카드를 건수 카드로 오인하면 ②·③ 을 거꾸로 잡는다.
GRID_NOTICE = re.compile(r"(미수집|미확정|미구성|미구현|D-\d+)")
_TD_EMPTY = re.compile(r'<td[^>]*class="[^"]*\bempty\b[^"]*"[^>]*>(.*?)</td>', re.S | re.I)
_TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S | re.I)
_TR = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_CARD = re.compile(r'<div class="d2-card[^"]*">(.*?)</div>\s*</div>|'
                   r'<div class="d2-card[^"]*">(.*?)(?=<div class="d2-card)', re.S)
_SPAN_V = re.compile(r'<span class="v">(.*?)</span>', re.S)
_SPAN_K = re.compile(r'<span class="k">(.*?)</span>', re.S)
_SPAN_S = re.compile(r'<span class="s">(.*?)</span>', re.S)
_CARD_BLOCK = re.compile(r'<div class="d2-card[^"]*">(.*?)</div>', re.S)
_COUNT_VALUE = re.compile(r"^[\d,]+(?:\.\d+)?\s*(건|ea|종|개|명|행)?$")
_ZERO_RATIO = re.compile(r"^0(?:\.0+)?\s*%$")
_TAG = re.compile(r"<[^>]+>")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub(" ", fragment))).strip()


def all_paths() -> list[str]:
    return ["/", "/login", "/popup", "/error", "/board"] + [s.path for s in nav.all_screens()]


def cards_of(body: str) -> list[tuple[str, str, str]]:
    """(라벨, 값, 보조설명) — 값은 `span.v` 다."""
    out = []
    for blk in _CARD_BLOCK.findall(body):
        v = _SPAN_V.search(blk)
        if not v:
            continue
        k = _SPAN_K.search(blk)
        s = _SPAN_S.search(blk)
        out.append((text_of(k.group(1)) if k else "",
                    text_of(v.group(1)),
                    text_of(s.group(1)) if s else ""))
    return out


def gate_11() -> None:
    say("── G-11 빈 그리드 문구 · 건수 카드 0건 · 비율 카드 분모 0 ──────────")
    say("  규약: ① 빈 그리드 → 문구 필요  ② 건수 카드 `0 건` → 0 이 정답(문구 요구 금지)")
    say("        ③ 비율·평균 카드 분모 0 → `미수집` 이 정답, `0 %` 로 메우면 결함 (§10-14)")
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    empty_cells = silent = 0
    filled_grids = 0
    screens_empty: list[str] = []
    screens_filled: list[str] = []
    count_zero = count_zero_bad = 0
    ratio_none = 0
    ratio_faked: list[str] = []
    notes_seen: set[str] = set()
    errors: list[str] = []

    for path in all_paths():
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        if r.status_code != 200:
            errors.append(f"{path} → HTTP {r.status_code}")
            continue
        body = r.text
        for tb in _TBODY.findall(body):
            rows = _TR.findall(tb)
            empties = [text_of(c) for c in _TD_EMPTY.findall(tb)]
            if empties:
                empty_cells += len(empties)
                if path not in screens_empty:
                    screens_empty.append(path)
                for c in empties:
                    notes_seen.add(c)
                    if not c or not GRID_NOTICE.search(c):
                        silent += 1
                        errors.append(f"{path} 빈 그리드에 문구가 없다/부적합: {c[:70]!r}")
            elif rows:
                filled_grids += 1
                if path not in screens_filled:
                    screens_filled.append(path)

        for label, value, sub in cards_of(body):
            if _COUNT_VALUE.match(value):
                if re.match(r"^0(?:\.0+)?\s*(건|ea|종|개|명|행)?$", value):
                    count_zero += 1
                    if "미수집" in value or "미확정" in value:
                        count_zero_bad += 1
                        errors.append(f"{path} 건수 카드 `{label}` 의 0 에 문구를 붙였다 — 거짓 표시")
            elif GRID_NOTICE.search(value):
                ratio_none += 1
            elif _ZERO_RATIO.match(value) and re.search(r"(?<![0-9,.])0\s*건", sub):
                ratio_faked.append(f"{path} `{label}` = {value} (보조설명: {sub[:50]})")

    say(f"  ① 0건 경로  빈 그리드 {empty_cells}개 (화면 {len(screens_empty)}종) · "
        f"문구 없음 {silent}개 · 서로 다른 문구 {len(notes_seen)}종")
    for n in sorted(notes_seen)[:8]:
        say(f"       \"{n[:90]}\"")
    say(f"  ① N건 경로  행이 그려진 그리드 {filled_grids}개 (화면 {len(screens_filled)}종) — "
        f"예: {', '.join(screens_filled[:8])}")
    say(f"  ② 건수 카드  값이 `0 건` 류인 카드 {count_zero}개 — **0 이 정답이다**. "
        f"문구를 붙인 거짓 표시 {count_zero_bad}개")
    say(f"  ③ 비율·평균 카드  값이 '미수집/미확정' 인 카드 {ratio_none}개 (분모 0 → 값이 없는 것). "
        f"0%로 메운 거짓 {len(ratio_faked)}개")
    for f in ratio_faked:
        say(f"       {f}")
    for e in errors[:30]:
        say(f"    {e}")

    if empty_cells == 0 or filled_grids == 0:
        verdict("G-11", UNDET,
                f"빈 그리드 {empty_cells} · 채워진 그리드 {filled_grids} — "
                "0건·N건 두 경로 중 하나를 이 상태에서 못 쟀다")
    else:
        bad = silent + count_zero_bad + len(ratio_faked) + len(errors)
        verdict("G-11", PASS if bad == 0 else FAIL,
                f"빈 그리드 {empty_cells}개 문구 위반 {silent} · N건 그리드 {filled_grids}개 · "
                f"`0 건` 카드 {count_zero}개(거짓 문구 {count_zero_bad}) · "
                f"미수집 비율카드 {ratio_none}개(0%로 메움 {len(ratio_faked)})")
    say()


# ══ KPI 독립 재계산 — `app/kpi.py` 를 믿지 않는다 ═════════════════════════
SQL_MFG_QA = """
with wo as (
  select t.LOT_TRACE_ID as lot, min(w.CONFIRM_DT) as confirm_dt
  from SHP_LOT_TRACES t
  join PRC_WORK_ORDERS w
    on w.WORK_ORDER_ID = t.WORK_ORDER_ID
    or w.WORK_ORDER_ID in (select f.WORK_ORDER_ID from PRC_PERFORMANCES f
                            where f.LOT_TRACE_ID = t.LOT_TRACE_ID)
  where w.CONFIRM_DT is not null
  group by 1
),
pack as (
  select LOT_TRACE_ID as lot, max(PACKING_DT) as packing_dt
  from SHP_SHIPMENT_ITEMS where PACKING_DT is not null group by 1
)
select count(*) as n,
       avg(extract(epoch from (p.packing_dt - w.confirm_dt)) / 3600.0) as h
from wo w join pack p on p.lot = w.lot
where p.packing_dt >= w.confirm_dt
"""
SQL_O2D_QA = """
select count(*) as n,
       avg(extract(epoch from (s.SHIP_DT - j.ORDER_CONFIRM_DT)) / 3600.0) as h
from SHP_SHIPMENTS s
join EST_PROJECTS j on j.PROJECT_ID = s.PROJECT_ID
where s.SHIP_DT is not null and j.ORDER_CONFIRM_DT is not null
  and s.SHIP_DT >= j.ORDER_CONFIRM_DT
"""
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)


def official_rows(body: str) -> dict[str, tuple[str, ...]]:
    """렌더 결과에서 공식 성과지표 2종 행을 문자열 그대로 뽑는다."""
    out: dict[str, tuple[str, ...]] = {}
    for row in _ROW.findall(body):
        cells = tuple(text_of(c) for c in _CELL.findall(row))
        if cells and cells[0] in (kpimod.CODE_MFG, kpimod.CODE_O2D) and len(cells) >= 9:
            out[cells[0]] = cells
    return out


def kpi_recalc() -> None:
    say("── KPI 독립 재계산 (app/kpi.py 를 믿지 않는다) ────────────────")
    bad = 0
    for code, sql in ((kpimod.CODE_MFG, SQL_MFG_QA), (kpimod.CODE_O2D, SQL_O2D_QA)):
        d = kpimod.definition(code)
        r = conn.q1(sql)
        qa_n = int(r["n"])
        qa_h = None if r["h"] is None else round(float(r["h"]), 2)
        m = kpimod.measure(code)                     # 앱 산식
        qa_rate = round((d.base - d.target) / d.base * 100.0, 1)
        agree_n = qa_n == m.sample_cnt
        agree_v = qa_h == m.value
        agree_r = qa_rate == d.improve_rate
        if not (agree_n and agree_v and agree_r):
            bad += 1
        say(f"  {code}  기존 {d.base:,.0f}{d.uom} → 목표 {d.target:,.0f}{d.uom}"
            f" · 감소율 QA {qa_rate}% / 앱 {d.improve_rate}% {'일치' if agree_r else '**불일치**'}")
        say(f"    표본 QA {qa_n} / 앱 {m.sample_cnt} {'일치' if agree_n else '**불일치**'}"
            f" · 평균(h) QA {qa_h} / 앱 {m.value} {'일치' if agree_v else '**불일치**'}")
        if qa_n == 0:
            say(f"    표본 0건 — 값은 `None` 이 정답이다. 0.0 으로 메우면 결함이다(G-11)")

    # DB 에 적재된 목표값도 같은지
    for t in kpimod.targets_in_db():
        d = kpimod.DEFS.get(t["kpi_code"])
        if d is None:
            say(f"  KPI_TARGETS 에 정본에 없는 코드 {t['kpi_code']} — 몰래 새 KPI 를 만들면 안 된다")
            bad += 1
            continue
        same = (float(t["base_value"]) == d.base and float(t["target_value"]) == d.target
                and round(float(t["improve_rate"]), 1) == d.improve_rate
                and (t["official_yn"] == "Y") == d.official)
        say(f"  KPI_TARGETS {t['kpi_code']}  기존 {t['base_value']} · 목표 {t['target_value']}"
            f" · 개선율 {t['improve_rate']} · 공식 {t['official_yn']}  {'일치' if same else '**불일치**'}")
        if not same:
            bad += 1

    # ── 화면 렌더 결과 문자열 대조 ────────────────────────────────────
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    client = TestClient(app, raise_server_exceptions=False)

    seen: dict[str, dict[str, tuple[str, ...]]] = {}
    for path in ("/board", "/kpi/043", "/kpi/044", "/kpi/045",
                 "/dsh/001", "/dsh/002", "/dsh/003", "/dsh/004"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        if r.status_code != 200:
            say(f"  {path} → HTTP {r.status_code} (대조 불가)")
            bad += 1
            continue
        rows = official_rows(r.text)
        if rows:
            seen[path] = rows

    say(f"  공식 성과지표 2종 표를 렌더하는 화면 {len(seen)}종: {', '.join(sorted(seen))}")
    for code in (kpimod.CODE_MFG, kpimod.CODE_O2D):
        variants = {p: v[code] for p, v in seen.items() if code in v}
        distinct = {v for v in variants.values()}
        say(f"  {code}  화면 {len(variants)}종 · 서로 다른 문자열 {len(distinct)}종")
        for v in distinct:
            say(f"    {' | '.join(v)}")
        if len(distinct) > 1:
            bad += 1
            say(f"    **화면마다 값이 다르다** — 단일 산식(app/kpi.py) 규약 위반")

    # 044 는 공식 성과지표가 아니다 — 화면이 그렇게 구분 표기하는가
    r44 = client.get("/kpi/044", headers={"x-kyungdong-role": "SYSADMIN"})
    body44 = text_of(r44.text)
    marked = kpimod.NOT_OFFICIAL_NOTE[:30] in body44
    say(f"  044 품질 KPI 비공식 구분 표기 {'있음' if marked else '**없음**'}"
        f"  (문구: {kpimod.NOT_OFFICIAL_NOTE[:40]}…)")
    if not marked:
        bad += 1

    verdict("KPI", PASS if bad == 0 else FAIL,
            f"독립 재계산·화면 문자열 대조 불일치 {bad}건 "
            f"(LEADTIME_MFG 1,320→1,080 −18.2% · LEADTIME_O2D 1,440→1,200 −16.7%)")
    say()


# ══ §7.1 '시드 여부 미정' 판정 ↔ 실제 데이터 ══════════════════════════════
UNDECIDED_71 = {
    "EST_SHAP_FACTORS": ("개발3", "런타임 — 학습 미실시(D-309)", 0),
    "INV_MATERIAL_HISTORY": ("개발1", "런타임 누적표 — 시드 대상 아님(D-102)", 0),
    "INV_SUPPLIER_QUALITY": ("개발1", "입고·검사 누적 집계 — 마스터 아님(D-103)", 0),
    "PRC_CONDITION_DEVIATIONS": ("개발2", "런타임 파생 — 시드 안 함(D-203)", 0),
    "PRC_PROCESS_HISTORIES": ("개발2", "**시드 대상** — 공정실적 시드와 함께 채운다", None),
    "SHP_CLAIM_CAUSES": ("개발2", "런타임 전용 — 시드 안 함(D-204)", 0),
}


def check_71() -> None:
    say("── contracts/db-schema.md §7.1 '시드 여부 미정' 판정 ↔ 실제 데이터 ──")
    mismatch = 0
    for tid, (owner, decision, expect) in sorted(UNDECIDED_71.items()):
        n = int(conn.q1(f"select count(*) as n from {tid}")["n"])
        if expect is None:
            state = "시드 대상이라 판정했으나 실제 0건 — 전제(EST_PROJECTS 0건)가 막았다" if n == 0 \
                else f"시드 대상 판정과 일치 ({n}건)"
            if n == 0:
                mismatch += 1
        else:
            state = "판정과 일치" if n == expect else f"**판정과 불일치** (기대 {expect})"
            if n != expect:
                mismatch += 1
        say(f"  {tid:<26} {n:>5} 건  [{owner}] {decision} → {state}")
    NOTES.append(f"§7.1 6건 중 판정과 실제가 어긋난 것 {mismatch}건")
    say()


def main() -> int:
    if conn.table_count() != 68:
        say(f"테이블이 68이 아니다({conn.table_count()}) — 먼저 `make db-reset`")
        return 1

    say("경동글로벌텍 제조AI — G-07~G-11 데이터 게이트 (QA2)")
    say("기준: 사업계획서 2.7.4 (정확성·정합성·연계성·LOT 매핑 각 85%) · goal.md §2.2")
    say()
    gate_07()
    gate_08()
    gate_09()
    gate_10()
    gate_11()
    kpi_recalc()
    check_71()

    # §10-11 — 시드를 돌렸으면 **끝나고 공통 시드로 되돌린다**
    r = subprocess.run([sys.executable, str(ROOT / "db" / "seed.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    say(f"공통 시드 복원 (§10-11) exit {r.returncode}")
    say()

    say("═══ 판정표 (게이트별 — §10-6) ═══")
    for gate, v, m in VERDICTS:
        say(f"{gate:<6} {v:<8} {m}")
    for n in NOTES:
        say(f"참고   {n}")
    say()
    say(" · ".join(f"{g} {v}" for g, v, _m in VERDICTS))
    return 0 if all(v == PASS for _g, v, _m in VERDICTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
