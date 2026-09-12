"""QA2 — G-07 ~ G-11 데이터 게이트 + KPI 독립 재계산 회귀.

**0건 경로와 N건 경로를 둘 다 명시 단언한다**(§10-4). 데이터가 없다고 `skip` 하지 않는다 —
`tests/test_dev3_cad.py:93·112·120` 이 그 결함(D-62)이다. 전제가 막혀 있는 게이트는
**롤백 트랜잭션 안에서** N건 경로를 실증하고, 커밋하지 않는다. 없는 데이터를 만들어
게이트를 통과시키지 않는다.

산식은 `tools/check_data.py` 한 벌뿐이다 — 테스트가 그 모듈을 불러 쓴다(§10-16).
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT))

import conn                                                   # noqa: E402
from kyungdong.app import design, kpi as kpimod               # noqa: E402
from kyungdong.app.util import clock, codes                   # noqa: E402
from tools import check_data as cd                            # noqa: E402

SEED = ROOT / "db" / "seed.py"


# ── 롤백 트랜잭션으로 만드는 N건 경로 ─────────────────────────────────────
def _required(tid: str) -> list[dict]:
    return [c for c in design.columns_of(tid)
            if c["pk"] != "Y" and c["nullable"].strip().upper() == "N"]


def _filler(col: dict):
    t = col["type"].upper()
    if t.startswith(("BIGINT", "INT", "NUMERIC")):
        return 0
    if t.startswith("TIMESTAMP") or t.startswith("DATE"):
        return None                      # now()/current_date 로 넣는다
    if t.startswith("CHAR("):
        return "N"
    return "QA2"


def _insert(cur, tid: str, **values):
    """필수 컬럼을 채워 한 행 넣고 PK 를 돌려준다. 값은 전부 바인딩한다."""
    pk = next(c["name"] for c in design.columns_of(tid) if c["pk"] == "Y")
    cols, params, exprs = [], [], []
    for c in _required(tid):
        name = c["name"]
        if name in values:
            continue
        v = _filler(c)
        cols.append(name)
        if v is None:
            exprs.append("current_date" if c["type"].upper().startswith("DATE") else "now()")
        else:
            exprs.append("%s")
            params.append(v)
    for name, v in values.items():
        cols.append(name)
        exprs.append("%s")
        params.append(v)
    cur.execute(f"insert into {tid} ({', '.join(cols)}) values ({', '.join(exprs)}) "
                f"returning {pk}", params)
    return int(cur.fetchone()[pk.lower()])


def _chain(cur, *, hours_mfg: float = 1000.0, hours_o2d: float = 1100.0) -> dict:
    """수주 → 도면 → BOM → 자재LOT → 작업지시 → 실적 → 제품LOT → 검사 → 출하 **한 벌**."""
    a = clock.anchor()
    order_dt = a - timedelta(hours=hours_o2d)
    confirm_dt = a - timedelta(hours=hours_mfg)
    pj = _insert(cur, "EST_PROJECTS", PROJECT_NO="QA2-P1", CUSTOMER_CODE="QA2CUST",
                 PRODUCT_GROUP="PG10", PROJECT_NAME="QA2 체인", PROJECT_STATUS="생산",
                 ORDER_CONFIRM_DT=order_dt)
    dr = _insert(cur, "EST_CAD_DRAWINGS", DRAWING_NO="QA2-D1", PROJECT_ID=pj,
                 FILE_TYPE="DWG", FILE_PATH="/qa2/d1.dwg", ANALYSIS_STATUS="완료",
                 DUPLICATE_YN="N", REVISION="A")
    bom = _insert(cur, "EST_BOM_HEADERS", BOM_NO="QA2-B1", PROJECT_ID=pj, DRAWING_ID=dr,
                  GEN_METHOD="수동", BOM_VERSION="v1", CONFIRM_YN="Y")
    _insert(cur, "EST_BOM_ITEMS", BOM_ID=bom, BOM_LEVEL=1, ITEM_CODE="QA2ITEM",
            MATERIAL="QA2MAT", REQUIRE_QTY=1, UOM="ea")
    lot = _insert(cur, "INV_MATERIAL_LOTS", LOT_NO="QA2-L1", ITEM_CODE="QA2ITEM",
                  MATERIAL="QA2MAT", CURRENT_QTY=1, LOT_STATUS="사용중",
                  THICKNESS_MM=6.0, LENGTH_MM=2400.0)
    wo = _insert(cur, "PRC_WORK_ORDERS", WORK_ORDER_NO="QA2-W1", PROJECT_ID=pj,
                 PROCESS_CODE="P40", ORDER_QTY=1, OUTSOURCE_YN="N", ORDER_STATUS="완료",
                 CONFIRM_DT=confirm_dt)
    tr = _insert(cur, "SHP_LOT_TRACES", PRODUCT_LOT_NO="QA2-T1", PROJECT_ID=pj, BOM_ID=bom,
                 MATERIAL_LOT_ID=lot, WORK_ORDER_ID=wo, CURRENT_PROCESS="P40",
                 TRACE_STATUS="출하", MAPPING_OK_YN="Y")
    _insert(cur, "PRC_PERFORMANCES", WORK_ORDER_ID=wo, LOT_TRACE_ID=tr, PROCESS_CODE="P40",
            START_DT=confirm_dt, END_DT=a, GOOD_QTY=1, DEFECT_QTY=0,
            COLLECT_METHOD="자동(PLC)")
    qstd = _insert(cur, "BAS_QUALITY_STANDARDS", INSPECT_TYPE="IT10", PRODUCT_GROUP="PG10")
    ins = _insert(cur, "SHP_INSPECTIONS", LOT_TRACE_ID=tr, QSTD_ID=qstd,
                  INSPECT_ITEM="수압시험", JUDGE_RESULT="합격", INSPECT_DT=a)
    sh = _insert(cur, "SHP_SHIPMENTS", SHIPMENT_NO="QA2-S1", PROJECT_ID=pj,
                 CUSTOMER_CODE="QA2CUST", SHIP_STATUS="완료", SHIP_DT=a)
    _insert(cur, "SHP_SHIPMENT_ITEMS", SHIPMENT_ID=sh, LOT_TRACE_ID=tr, ITEM_CODE="QA2ITEM",
            SHIP_QTY=1, PACKING_DT=a, INSPECT_ID=ins)
    return {"project": pj, "lot_trace": tr, "shipment": sh,
            "order_dt": order_dt, "confirm_dt": confirm_dt, "anchor": a}


class _Rollback(Exception):
    """N건 경로를 실증한 뒤 **반드시** 롤백시키는 신호."""


def _in_rollback(fn):
    """`fn(cur)` 를 트랜잭션 안에서 돌리고 결과를 돌려준 뒤 **롤백**한다."""
    box: dict = {}
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            box["out"] = fn(cur)
            raise _Rollback
    return box["out"]


def _q1(cur):
    def run(sql, params=None):
        cur.execute(sql, params)
        return cur.fetchone()
    return run


# ══ G-07 시드 멱등 · 시간 앵커 ═══════════════════════════════════════════
def test_G07_공통시드가_멱등이다_0건표와_N건표를_모두_단언():
    def snap():
        return cd.snapshot()
    subprocess.run([sys.executable, str(SEED)], cwd=ROOT, capture_output=True, text=True, check=True)
    a = snap()
    subprocess.run([sys.executable, str(SEED)], cwd=ROOT, capture_output=True, text=True, check=True)
    b = snap()
    diff = {t: (b[t] - a[t]) for t in a if a[t] != b[t]}
    assert diff == {}, f"재실행이 행을 바꿨다: {diff}"

    n_tables = {t: b[t] for t in b if b[t] > 0}
    zero_tables = [t for t in b if b[t] == 0]
    assert n_tables, "N건 경로가 없다 — 시드가 아무것도 넣지 못했다"
    assert zero_tables, "0건 경로가 없다 — 이 사업은 시드가 막힌 표가 있는 상태다"
    assert b["BAS_COMMON_CODES"] > 0 and b["SYS_ROLE_PERMISSIONS"] > 0
    # `EST_PROJECTS` 는 더 이상 **0건 단언 대상이 아니다** — 사용자 지시로 실측 GD 프로젝트가
    # 들어갔다(D-131 · 고객사 확정 D-139). 0건 단언을 지우지 않고 **출처 단언으로 뒤집는다**:
    # 채워졌으면 합성 선언이 함께 있어야 하고, 선언이 없으면 0건이 정답이다.
    decl = conn.q1(cd.SYNTH_DECL)
    if decl and decl["config_value"]:
        assert b["EST_PROJECTS"] > 0, "합성 선언은 있는데 사슬 최상위(EST_PROJECTS)가 0건이다"
        assert b["EST_CAD_DRAWINGS"] > 0 and b["SHP_LOT_TRACES"] > 0
        assert cd.synthetic_note() == f"합성 데이터 기준 {decl['config_value']}"
    else:
        assert b["EST_PROJECTS"] == 0, \
            "합성 선언 없이 채워진 프로젝트는 출처를 댈 수 없다 (D-47·D-56)"


def test_G07_시간앵커가_고정이고_date_today_가_없다():
    banned, watched = cd.scan_clock()
    assert banned == [], "시간 기준일 위반: " + " / ".join(banned)
    assert watched, "허용된 datetime.now() 목록이 비었다 — 스캐너가 동작하지 않았다"
    a1 = clock.anchor()
    a2 = clock.anchor()
    assert a1 == a2 and a1.tzinfo is None


def test_G07_런타임_전용표는_시드가_채우지_않는다():
    """§7 11표 — 시드만 돌린 상태에서 0건이어야 한다(화면·API 가 채운다)."""
    runtime = ("AGT_QUERY_LOGS", "AGT_RECOMMENDATIONS", "DAT_DOWNLOAD_LOGS",
               "EST_ML_PREDICTIONS", "EST_ML_TRAIN_RUNS", "EST_OBJECT_REVIEWS",
               "IF_DOC_EMBED_LOGS", "IF_GATEWAY_BUFFER")
    src = "\n".join((ROOT / f).read_text()
                    for f in ("db/seed.py", "db/seed_dev1.py", "db/seed_dev2.py", "db/seed_dev3.py"))
    for t in runtime:
        assert not re.search(rf"insert\s+into\s+{t}\b", src, re.I), f"시드가 {t} 를 채운다"


# ══ G-08 디지털 스레드 · LOT 매핑 ═════════════════════════════════════════
def test_G08_0건_경로는_0퍼센트가_아니라_판정불가다():
    """사슬 표를 **롤백 트랜잭션 안에서 비우고** 재서 0건 경로를 실증한다.

    시드가 채운 합성 사슬(D-131)을 지워서 0건을 만들지 않는다 — 커밋하지 않는다.
    """
    def body(cur):
        for sql in ("delete from SHP_SHIPMENT_ITEMS", "delete from SHP_INSPECTIONS",
                    "delete from PRC_PROCESS_HISTORIES", "delete from PRC_PERFORMANCES",
                    "delete from SHP_LOT_TRACES"):
            cur.execute(sql)
        return _q1(cur)(cd.LOT_FULL_CHAIN)
    row = _in_rollback(body)
    assert int(row["total"]) == 0
    assert cd.pct(int(row["linked"]), int(row["total"])) is None, "분모 0 을 0% 라고 말하면 거짓이다"
    assert cd.pct_text(None) == "판정 불가(분모 0)"
    # 롤백 뒤 라이브 사슬이 그대로 남아 있는지 — 테스트가 시드를 지우면 그게 더 큰 사고다
    assert int(conn.q1(cd.LOT_FULL_CHAIN)["total"]) > 0


def test_G08_N건_경로는_사슬이_양방향으로_이어진다():
    """라이브에 합성 사슬이 이미 있으므로 **증분**으로 잰다 — 한 벌을 더 넣어 +1 을 확인한다."""
    def body(cur):
        run = _q1(cur)
        before = run(cd.LOT_FULL_CHAIN)
        _chain(cur)
        after = run(cd.LOT_FULL_CHAIN)
        steps = []
        for label, fwd, bwd, fden, bden in cd.CHAIN:
            steps.append((label,
                          int(run(f"select ({fwd}) as n")["n"]),
                          int(run(f"select ({bwd}) as n")["n"])))
        return before, after, steps
    before, after, steps = _in_rollback(body)
    assert int(after["total"]) - int(before["total"]) == 1
    assert int(after["linked"]) - int(before["linked"]) == 1, "9단계를 다 이었는데 완주로 세지 않는다"
    for label, f, b in steps:
        assert f >= 1, f"정방향 끊김: {label}"
        assert b >= 1, f"역방향 끊김: {label}"


def test_G08_합성_데이터로_잰_값이면_판정_줄에_그_사실이_붙는다():
    """**숫자만 떼어 인용될 수 없게** 한다 (goal.md §2.3 · §10-1).

    임계값(85%)·판정 조건은 그대로다 — 고지를 붙이는 것뿐이다.
    """
    note = cd.synthetic_note()
    total = int(conn.q1(cd.LOT_FULL_CHAIN)["total"])
    if total == 0:
        assert note == "", "사슬이 0건인데 합성 선언이 있다 — 선언이 실제와 어긋난다"
        return
    assert note.startswith("합성 데이터 기준 D-"), f"합성 고지가 없다: {note!r}"
    cd.VERDICTS.clear()
    cd.gate_08()
    gate, verdict, measured = next(v for v in cd.VERDICTS if v[0] == "G-08")
    cd.VERDICTS.clear()
    assert note in measured, f"G-08 판정 줄에 합성 고지가 없다: {measured!r}"
    assert f"표본 {total}" in measured, f"판정 줄에 표본 수가 없다: {measured!r}"
    assert "LOT 매핑" in measured and "%" in measured, "수치가 같은 줄에 없다"
    assert f"기준 {cd.THRESHOLD}%" in measured, "임계값 표기가 사라졌다 — 85% 는 그대로다"


def test_G08_의도적_단절_표본이_있어서_100퍼센트가_아니다():
    """전부 이으면 100% 가 나오고 그건 검사기를 시험하지 못한다 — 단절 표본이 있어야 한다."""
    import seed_dev1
    row = conn.q1(cd.LOT_FULL_CHAIN)
    total, linked = int(row["total"]), int(row["linked"])
    if total == 0:
        return
    assert linked < total, "합성인데 전부 이어져 100% 다 — 단절 표본을 빼면 검사기를 못 시험한다"
    assert seed_dev1.BREAKS, "의도적 단절 위치가 선언돼 있지 않다"
    rate = cd.pct(linked, total)
    assert rate is not None and rate >= cd.THRESHOLD, (
        f"LOT 매핑 {rate}% — 기준 {cd.THRESHOLD}% 미달이면 **미달로 보고**하고 단절을 빼지 않는다")


def test_G08_선언값_MAPPING_OK_YN_을_믿지_않고_독립_재계산한다():
    """`MAPPING_OK_YN='Y'` 라고 적어 두기만 하면 매핑률이 올라가서는 안 된다."""
    def body(cur):
        run = _q1(cur)
        before = run(cd.LOT_FULL_CHAIN)
        _insert(cur, "EST_PROJECTS", PROJECT_NO="QA2-P9", CUSTOMER_CODE="QA2CUST",
                PRODUCT_GROUP="PG10", PROJECT_NAME="끊긴 체인", PROJECT_STATUS="생산")
        cur.execute("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = 'QA2-P9'")
        pj = int(cur.fetchone()["project_id"])
        _insert(cur, "SHP_LOT_TRACES", PRODUCT_LOT_NO="QA2-T9", PROJECT_ID=pj,
                TRACE_STATUS="생산중", MAPPING_OK_YN="Y")      # 선언만 Y, 실제로는 끊겼다
        return before, run(cd.LOT_FULL_CHAIN)
    before, after = _in_rollback(body)
    assert int(after["declared"]) - int(before["declared"]) == 1, "선언값은 Y 로 세어야 한다"
    assert int(after["linked"]) - int(before["linked"]) == 0, \
        "끊긴 LOT 을 완주로 세면 매핑률이 조작된다"


# ══ G-09 정확성 · 정합성 · 연계성 ═════════════════════════════════════════
def test_G09_분모_0_지표는_0퍼센트가_아니라_판정불가다():
    """0건 경로는 **산식**으로 단언한다 — 합성 사슬(D-131)이 들어온 뒤 정확성·연계성 분모는 N이다.

    **정합성은 여전히 분모 0 이다** — 그래서 G-09 는 `차단` 으로 남는다. 그 이유를 여기 못박는다:
    `EST_CAD_FEATURES`(D-05) · `EST_QUOTATIONS`·`EST_COST_RATES`(D-04) · `재질` 코드(D-47)가 없다.
    """
    assert cd.pct(0, 0) is None and cd.pct(1, 0) is None
    ok, total, bad = cd.accuracy()
    assert bad == [] or all("코드 그룹 미정의" in b for b in bad)
    if total:
        assert cd.pct(ok, total) == 100.0, f"정확성 {ok}/{total} — 코드성 FK 위반이 있다 (D-32)"
    comp_total = sum(int(conn.q1(f"select ({den}) as n")["n"]) for _n, den, _num in cd.CONSISTENCY)
    assert comp_total == 0, (
        "정합성 분모가 생겼다 — G-09 가 차단에서 벗어났으므로 판정을 다시 적어야 한다")
    r = conn.q1(cd.LINKAGE)
    if int(r["total"]) == 0:
        assert cd.pct(int(r["linked"]), int(r["total"])) is None
    else:
        assert cd.pct(int(r["linked"]), int(r["total"])) is not None


def test_G09_N건_경로_연계성_100퍼센트와_정확성_산식():
    def body(cur):
        run = _q1(cur)
        link_before = run(cd.LINKAGE)
        _chain(cur)
        link = run(cd.LINKAGE)
        link = {"total": int(link["total"]) - int(link_before["total"]),
                "linked": int(link["linked"]) - int(link_before["linked"])}
        # 코드성 FK 를 만족시키는 코드를 같은 트랜잭션에 넣고 정확성이 올라가는지 본다
        for group, value in (("품목", "QA2ITEM"), ("재질", "QA2MAT"), ("고객사", "QA2CUST")):
            cur.execute(
                "insert into BAS_COMMON_CODES (CODE_GROUP, CODE_VALUE, CODE_NAME, USE_YN, CREATED_DT) "
                "values (%s,%s,%s,'Y', now())", (group, value, value))
        after = cd.accuracy(run=run)
        return link, after
    link, (ok, total, _bad) = _in_rollback(body)
    assert int(link["total"]) == 1 and int(link["linked"]) == 1
    assert cd.pct(int(link["linked"]), int(link["total"])) == 100.0 >= cd.THRESHOLD
    assert total > 0, "코드성 컬럼을 가진 표에 행이 있어야 정확성 분모가 생긴다"
    assert cd.pct(ok, total) == 100.0, f"정확성 {ok}/{total} — 코드가 전부 있는데 위반으로 센다"


def test_G09_없는_코드를_쓰면_정확성이_떨어진다():
    """**증분**으로 본다 — 한 행을 더 넣으면 분모는 +1 인데 정상 건수는 그대로여야 한다."""
    def body(cur):
        run = _q1(cur)
        before = cd.accuracy(run=run)
        _insert(cur, "INV_MATERIAL_LOTS", LOT_NO="QA2-LX", ITEM_CODE="없는코드",
                CURRENT_QTY=0, LOT_STATUS="입고")
        return before, cd.accuracy(run=run)
    (ok0, total0, _b0), (ok1, total1, _b1) = _in_rollback(body)
    assert total1 - total0 == 1, "행을 넣었는데 정확성 분모가 늘지 않았다"
    assert ok1 - ok0 == 0, "코드성 FK 위반 행을 '정상' 으로 세면 안 된다 (D-32)"


def test_코드성_FK_29건이_전부_그룹에_매핑돼_있다():
    assert len(codes.code_columns()) == 29, "contracts/db-schema.md §3 은 29건이다"
    assert codes.unmapped_columns() == [], f"그룹 미정의: {codes.unmapped_columns()}"


# ══ G-10 시계열 — 규약 `contracts/missing-policy.md` 준수 ═════════════════
# DEF-QA2-007 해소(아키텍트가 규약 문서를 작성). 표지 단언을 **문서 부재 → 문서 준수**로 바꿨다.
def test_G10_규약_문서가_있다():
    assert cd.POLICY.exists(), (
        "goal.md §2.2 G-10 이 가리키는 `contracts/missing-policy.md` 가 사라졌다 — "
        "DEF-QA2-007 이 재발한 것이다")
    body = cd.POLICY.read_text()
    for anchor in ("## 1.", "### 2.1", "### 2.3", "## 4.", "## 5."):
        assert anchor in body, f"규약에서 {anchor} 절이 사라졌다 — 검사기가 그 절을 구현하고 있다"


def test_G10_규약_1_수집지점_2개소_밖은_분모에_넣지_않는다():
    """§1 — 수집 대상 밖은 결측이 아니라 `미수집 (D-06)` 이다."""
    m = cd.missing_rate()
    polled = [d for d in m["devices"] if d["polled"]]
    excluded = [d for d in m["devices"] if not d["polled"]]
    assert len(m["devices"]) == 2, "수집 지점은 2개소뿐이다 (D-06)"
    assert [d["name"] for d in polled] == ["레이저커팅기 PLC"]
    assert [d["name"] for d in excluded] == ["현장POP(터치PC)"]
    assert "수동 입력" in excluded[0]["why"]


def test_G10_규약_2_1_분모가_정본_주기와_활성태그로_선다():
    """§2.1 — 분모 = (구간 ÷ PLC_POLL_SEC) × 활성 태그 수. 정본 태그표를 쓴다."""
    from kyungdong.app.settings import settings
    from kyungdong.ingest import tags as ingest_tags
    m = cd.missing_rate()
    assert m["poll_sec"] == settings().h("PLC_POLL_SEC").as_int()
    assert m["active_tags"] == len(ingest_tags.TAGS) == 8
    assert "unknown_state" in m and "excluded_idle" in m, (
        "비가동·상태미상 제외 건수를 세지 않으면 §2.1 을 지킨 것이 아니다")


def test_G10_규약_5_분모_0은_0퍼센트가_아니라_판정불가다():
    """§5 — 0% 도 100% 도 아니다."""
    n = int(conn.q1("select count(*) as n from DAT_TIMESERIES")["n"])
    assert n == 0, "수집 표에 행이 있다 — check_ingest 뒤 정리가 안 됐는지 확인한다"
    m = cd.missing_rate()
    assert m["expected"] == 0 and m["rate"] is None
    assert cd.pct(0, n) is None, "0건에서 결측률을 0% 라고 말하지 않는다"


def test_G10_규약_4_정확성_조작적_정의를_검사기가_그대로_구현한다():
    """§4 — ① 코드성 FK ② NOT NULL ③ 물리 FK ④ 수치 범위(판정 제외)."""
    ok, total, _bad = cd.accuracy()                      # ①
    assert total > 0, "정확성 분모가 0이다 — 코드성 컬럼을 가진 표가 전부 비었는지 확인한다"
    assert ok == total, f"코드성 FK 위반 {total - ok}행 (D-32)"
    assert cd.notnull_violations() == 0                  # ② DB 제약이 강제한다
    nfk, orphan = cd.fk_orphans()                        # ③
    assert nfk == 98, f"물리 FK 제약이 98건이 아니다: {nfk} (contracts/db-schema.md 머리말)"
    assert orphan == 0, "물리 FK 가 가리키는 행이 없다 — 제약이 깨졌다"
    assert "판정에서 제외" in cd.RANGE_EXCLUDED           # ④ 명시적 제외
    assert "§4-④" in cd.RANGE_EXCLUDED


# ══ G-11 그리드 vs 건수 카드 vs 비율 카드 ═════════════════════════════════
@pytest.fixture(scope="module")
def rendered():
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    out = {}
    for p in cd.all_paths():
        r = client.get(p, headers={"x-kyungdong-role": "SYSADMIN"})
        assert r.status_code == 200, f"{p} → {r.status_code}"
        out[p] = r.text
    return out


def test_G11_빈_그리드는_전부_문구를_렌더한다_0건경로(rendered):
    silent = []
    empties = 0
    for path, body in rendered.items():
        for cell in cd._TD_EMPTY.findall(body):
            empties += 1
            t = cd.text_of(cell)
            if not t or not cd.GRID_NOTICE.search(t):
                silent.append(f"{path}: {t[:60]!r}")
    assert empties > 0, "빈 그리드가 하나도 없다 — 0건 경로를 재현하지 못했다"
    assert silent == [], f"조용한 빈칸: {silent}"


def test_G11_N건_그리드가_실제로_행을_그린다(rendered):
    filled = 0
    for body in rendered.values():
        for tb in cd._TBODY.findall(body):
            if cd._TR.findall(tb) and not cd._TD_EMPTY.findall(tb):
                filled += 1
    assert filled > 0, "행이 그려진 그리드가 없다 — N건 경로를 재현하지 못했다"


def test_G11_건수카드의_0건에_미수집을_붙이지_않는다(rendered):
    """§10-14 — 0 은 정답이다. 여기에 문구를 요구하면 거짓 표시가 된다."""
    zero_cards, lying = 0, []
    for path, body in rendered.items():
        for label, value, _sub in cd.cards_of(body):
            if re.match(r"^0(?:\.0+)?\s*(건|ea|종|개|명|행)?$", value):
                zero_cards += 1
                if cd.GRID_NOTICE.search(value):
                    lying.append(f"{path} {label}={value}")
    assert zero_cards > 0, "`0 건` 카드가 없다 — 이 상태에서는 있어야 한다"
    assert lying == [], f"0 에 문구를 붙인 거짓 표시: {lying}"


def test_G11_비율카드는_분모가_0이면_0퍼센트로_메우지_않는다(rendered):
    faked, none_cards = [], 0
    for path, body in rendered.items():
        for label, value, sub in cd.cards_of(body):
            if cd.GRID_NOTICE.search(value):
                none_cards += 1
            elif cd._ZERO_RATIO.match(value) and re.search(r"(?<![0-9,.])0\s*건", sub):
                faked.append(f"{path} {label}={value} ({sub[:40]})")
    assert none_cards > 0, "분모 0 인 비율 카드가 하나도 없다 — 이 상태에서는 있어야 한다"
    assert faked == [], f"표본 0건인데 0% 로 메웠다: {faked}"


# ══ KPI 독립 재계산 ══════════════════════════════════════════════════════
def test_KPI_감소율을_상수가_아니라_계산으로_낸다():
    assert kpimod.improve_rate(1320, 1080) == 18.2
    assert kpimod.improve_rate(1440, 1200) == 16.7
    assert kpimod.definition(kpimod.CODE_MFG).improve_rate == 18.2
    assert kpimod.definition(kpimod.CODE_O2D).improve_rate == 16.7


def test_KPI_표본_0건_경로는_None_이고_0_0_이_아니다():
    """0건 경로는 **순수 함수**로 단언한다 — 합성 사슬(D-131)이 들어와 라이브 표본은 N건이다.

    라이브에서는 **QA 독립 SQL 과 앱 산식이 같은 값**을 내는지를 본다(이것이 이 검사의 목적).
    """
    assert kpimod.mean_hours([]) is None, "표본 0건을 0.0 으로 메우면 결함이다"
    assert kpimod.achieve_rate(1320, 1080, None) is None
    assert kpimod.ratio_pct(0, 0) is None
    for code, sql in ((kpimod.CODE_MFG, cd.SQL_MFG_QA), (kpimod.CODE_O2D, cd.SQL_O2D_QA)):
        r = conn.q1(sql)
        m = kpimod.measure(code)
        assert int(r["n"]) == m.sample_cnt, f"{code} 표본 QA {r['n']} ≠ 앱 {m.sample_cnt}"
        if int(r["n"]) == 0:
            assert r["h"] is None and m.value is None
            assert m.achieve is None and m.value_text == "—"
        else:
            assert round(float(r["h"]), 2) == m.value, f"{code} 평균 QA {r['h']} ≠ 앱 {m.value}"
            assert m.achieve is not None and m.value_text != "—"


def test_KPI_N건_경로_독립SQL이_앱_산식과_같은_값을_낸다():
    """`app/kpi.py` 를 믿지 않고 QA 가 새로 쓴 SQL 로 잰다."""
    def body(cur):
        run = _q1(cur)
        # 라이브 합성 표본을 걷어낸 자리에서 **한 벌만** 넣어 산식을 정확히 잰다 (롤백한다).
        for sql in ("delete from SHP_SHIPMENT_ITEMS", "delete from SHP_INSPECTIONS",
                    "delete from PRC_PROCESS_HISTORIES", "delete from PRC_PERFORMANCES",
                    "delete from SHP_LOT_TRACES", "delete from SHP_SHIPMENTS"):
            cur.execute(sql)
        c = _chain(cur, hours_mfg=1000.0, hours_o2d=1100.0)
        return run(cd.SQL_MFG_QA), run(cd.SQL_O2D_QA), c
    mfg, o2d, c = _in_rollback(body)
    assert int(mfg["n"]) == 1 and abs(float(mfg["h"]) - 1000.0) < 0.01
    assert int(o2d["n"]) == 1 and abs(float(o2d["h"]) - 1100.0) < 0.01
    # 같은 표본을 앱의 순수 함수에 넣어도 같은 값이어야 한다
    assert kpimod.mean_hours([float(mfg["h"])]) == round(float(mfg["h"]), 2)
    d = kpimod.definition(kpimod.CODE_MFG)
    assert kpimod.achieve_rate(d.base, d.target, 1000.0) == round((1320 - 1000) / 240 * 100, 1)


def test_KPI_대시보드_현황판_043_045_가_같은_문자열을_낸다(rendered):
    seen = {p: cd.official_rows(b) for p, b in rendered.items() if cd.official_rows(b)}
    assert len(seen) >= 4, f"공식 지표표를 렌더하는 화면이 {len(seen)}종뿐이다: {sorted(seen)}"
    assert "/board" in seen and "/kpi/043" in seen and "/kpi/045" in seen
    for code in (kpimod.CODE_MFG, kpimod.CODE_O2D):
        rows = {p: v[code] for p, v in seen.items() if code in v}
        assert len(set(rows.values())) == 1, f"{code} 가 화면마다 다르다: {rows}"
        cells = next(iter(rows.values()))
        d = kpimod.definition(code)
        assert cells[2].startswith(f"{d.base:,.0f}") and cells[3].startswith(f"{d.target:,.0f}")
        assert cells[4] == f"−{d.improve_rate}"


def test_KPI_044_는_공식_성과지표가_아니라고_화면이_구분_표기한다(rendered):
    body = cd.text_of(rendered["/kpi/044"])
    assert kpimod.NOT_OFFICIAL_NOTE[:30] in body
    assert "공식 성과지표 2종" in body, "044 도 공식 2종 표를 같이 보여 구분이 드러나야 한다"
    assert kpimod.OFFICIAL_NOTE[:10] in cd.text_of(rendered["/kpi/043"])


def test_KPI_TARGETS_적재값이_정본과_같다():
    rows = kpimod.targets_in_db()
    assert len(rows) == 2, f"KPI_TARGETS 는 공식 2건이다: {len(rows)}"
    for t in rows:
        d = kpimod.DEFS[t["kpi_code"]]
        assert float(t["base_value"]) == d.base and float(t["target_value"]) == d.target
        assert round(float(t["improve_rate"]), 1) == d.improve_rate
        assert (t["official_yn"] == "Y") is d.official


# ══ §7.1 '시드 여부 미정' 판정 ↔ 실제 ═════════════════════════════════════
def test_71_시드여부_미정_6건의_판정이_실제_데이터와_맞는다():
    for tid, (_owner, _why, expect) in cd.UNDECIDED_71.items():
        n = int(conn.q1(f"select count(*) as n from {tid}")["n"])
        if expect is None:
            # PRC_PROCESS_HISTORIES — 개발2 판정은 '시드 대상' 이다. 전제(EST_PROJECTS·BOM)가
            # 서면서 **판정이 실현됐다**(D-131). 0건이면 전제가 아직 막힌 것이고 그때도 0이 정답이다.
            if n == 0:
                assert int(conn.q1("select count(*) as n from SHP_LOT_TRACES")["n"]) == 0, \
                    f"{tid} 가 0건인데 제품LOT 은 있다 — 시드 대상 판정이 실행되지 않았다"
            else:
                assert n >= int(conn.q1("select count(*) as n from SHP_LOT_TRACES")["n"]), \
                    f"{tid} {n}건이 제품LOT 수보다 적다 — 공정이력이 LOT 당 1건 이상이어야 한다"
        else:
            assert n == expect, f"{tid} 판정({expect}건)과 실제({n}건)가 다르다"


# ══ 표본 크기 (D-199~D-203) ═══════════════════════════════════════════════
def test_단절_비율은_표본_크기와_무관하다():
    """**표본만 늘리면 게이트가 좋아 보인다** (D-200).

    단절 5건을 고정해 두고 표본을 40 → 100 으로 늘리면 단절이 12.5% → 5% 로 묽어져
    **LOT 매핑률이 87.5% → 95%** 가 된다. 나아진 것은 하나도 없는데 수치만 오른다 —
    표본을 키워 게이트를 통과시키는 짓이다.
    """
    import seed_dev1 as sd

    for n in (40, 60, 100, 200):
        b = sd.breaks_for(n)
        ratio = len(b) / n
        assert abs(ratio - sd.BREAK_RATIO) < 0.02, f"표본 {n}: 단절 {len(b)}건 = {ratio:.1%}"
        assert len(set(b)) == len(b), "단절 자리가 겹쳤다"
        assert all(0 <= i < n for i in b), "단절 자리가 표본 밖이다"
    # 기본 표본에서는 **원래 쓰던 자리를 그대로** 재현해야 한다 — 바뀌면 기존 실측과 못 잇는다.
    assert sorted(sd.breaks_for(40)) == list(sd.BREAK_SEATS_40)


def test_표본_크기를_섞으면_시드가_막는다():
    """**조용히 깨지던 것을 막는다** (D-201).

    자재LOT 번호가 계획 순서로 매겨져서, 표본 100 DB 에 40 으로 재시드하면 같은 날짜의
    앞 번호가 **다른 BOM 을 가리키도록 덮어써진다.** 실측으로 BOM 키 100 → 89,
    LOT 매핑 88.0% → 82.0% 로 떨어졌고 **깨졌다는 신호는 어디에도 없었다.**
    """
    import pytest as _pytest

    import seed_dev1 as sd

    now = sd.recorded_sample()
    assert now, "이 DB 의 표본 크기가 기록돼 있지 않다"
    with _pytest.raises(SystemExit, match="표본 크기를 섞을 수 없다"):
        sd.guard_sample_size(now + 7)
    sd.guard_sample_size(now)            # 같은 크기는 통과해야 한다(멱등)


def test_환경변수가_없으면_DB_에_기록된_표본을_따른다():
    """재시드 경로가 많다(멱등 시험·테스트·검사기). 무조건 기본 40 으로 돌아가면
    **표본 100 인 DB 를 40 으로 덮어쓴다** — 그래서 기록된 크기를 따른다 (D-201).
    """
    import os

    import seed_dev1 as sd

    assert not os.environ.get("KYUNGDONG_SAMPLE_LOTS"), "이 시험은 환경변수 없이 돈다"
    assert sd.sample_lots() == sd.recorded_sample()


def test_만들지_않는_단절은_남은_행까지_지운다():
    """**"만들지 않는다" 는 단절은 멱등이 아니었다** (D-203).

    그 자리가 한 번이라도 단절이 아닌 적이 있으면 그때 만든 행이 남아 **단절을 치유한다** —
    실측으로 4자리가 살아나 LOT 매핑이 88.0% → **92.0%** 로 올랐다. 나아진 것이 없는데
    숫자만 오르는 것이라, 단절 자리에는 행이 **하나도 없어야** 한다.
    """
    import subprocess
    import sys as _sys

    import seed_dev1 as sd

    # **시드 직후 상태를 잰다.** 다른 테스트가 사슬에 행을 더하므로(픽스처가 PLOT-2026-* 를
    # 만든다) 그대로 재면 그 잔여를 단절 실패로 오인한다. 시드를 다시 돌려 기준을 맞춘다 —
    # 시드는 멱등이므로(G-07) 이 호출이 다른 값을 만들지 않는다.
    for script in ("seed.py", "seed_dev1.py", "seed_dev2.py", "seed_dev3.py"):
        r = subprocess.run([_sys.executable, str(ROOT / "db" / script)],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, f"{script}: " + (r.stdout[-600:] + r.stderr[-600:])

    rows = sd.thread_rows()
    lots = sorted(r["product_lot_no"] for r in conn.q(
        "select PRODUCT_LOT_NO from SHP_LOT_TRACES"))
    checked = 0
    for r in rows:
        broke, idx = r["break"], r["index"]
        if not broke or idx >= len(lots):
            continue
        tid = conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                      (lots[idx],))
        if tid is None:
            continue
        tid = int(tid["lot_trace_id"])
        if "공정실적 누락" in broke:
            n = int(conn.q1("select count(*) as n from PRC_PERFORMANCES "
                            "where LOT_TRACE_ID = %s", (tid,))["n"])
            assert n == 0, f"#{idx} 공정실적 단절인데 {n} 행이 남아 있다"
            checked += 1
        if "검사·출하 누락" in broke:
            n = int(conn.q1("select count(*) as n from SHP_INSPECTIONS "
                            "where LOT_TRACE_ID = %s", (tid,))["n"])
            assert n == 0, f"#{idx} 검사 단절인데 {n} 행이 남아 있다"
            checked += 1
    assert checked >= 2, f"검사한 단절 자리가 {checked} 개뿐이다"
