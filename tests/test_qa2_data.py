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
    assert b["EST_PROJECTS"] == 0, "EST_PROJECTS 는 D-47·D-56 으로 0건이 정답이다"


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
    row = conn.q1(cd.LOT_FULL_CHAIN)
    total = int(row["total"])
    assert total == 0, "전제가 바뀌었다 — SHP_LOT_TRACES 가 채워졌으면 N건 경로로 판정한다"
    assert cd.pct(int(row["linked"]), total) is None, "분모 0 을 0% 라고 말하면 거짓이다"


def test_G08_N건_경로는_사슬이_양방향으로_이어진다():
    def body(cur):
        _chain(cur)
        run = _q1(cur)
        chain = run(cd.LOT_FULL_CHAIN)
        steps = []
        for label, fwd, bwd, fden, bden in cd.CHAIN:
            steps.append((label,
                          int(run(f"select ({fwd}) as n")["n"]),
                          int(run(f"select ({bwd}) as n")["n"])))
        return chain, steps
    chain, steps = _in_rollback(body)
    assert int(chain["total"]) == 1
    assert int(chain["linked"]) == 1, "9단계를 다 이었는데 완주로 세지 않는다"
    assert cd.pct(int(chain["linked"]), int(chain["total"])) == 100.0 >= cd.THRESHOLD
    for label, f, b in steps:
        assert f >= 1, f"정방향 끊김: {label}"
        assert b >= 1, f"역방향 끊김: {label}"


def test_G08_선언값_MAPPING_OK_YN_을_믿지_않고_독립_재계산한다():
    """`MAPPING_OK_YN='Y'` 라고 적어 두기만 하면 매핑률이 올라가서는 안 된다."""
    def body(cur):
        _insert(cur, "EST_PROJECTS", PROJECT_NO="QA2-P9", CUSTOMER_CODE="QA2CUST",
                PRODUCT_GROUP="PG10", PROJECT_NAME="끊긴 체인", PROJECT_STATUS="생산")
        cur.execute("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = 'QA2-P9'")
        pj = int(cur.fetchone()["project_id"])
        _insert(cur, "SHP_LOT_TRACES", PRODUCT_LOT_NO="QA2-T9", PROJECT_ID=pj,
                TRACE_STATUS="생산중", MAPPING_OK_YN="Y")      # 선언만 Y, 실제로는 끊겼다
        return _q1(cur)(cd.LOT_FULL_CHAIN)
    row = _in_rollback(body)
    assert int(row["declared"]) == 1, "선언값은 Y 로 세어야 한다"
    assert int(row["linked"]) == 0, "끊긴 LOT 을 완주로 세면 매핑률이 조작된다"


# ══ G-09 정확성 · 정합성 · 연계성 ═════════════════════════════════════════
def test_G09_0건_경로_세_지표_모두_판정불가다():
    ok, total, bad = cd.accuracy()
    assert total == 0 and cd.pct(ok, total) is None
    r = conn.q1(cd.LINKAGE)
    assert int(r["total"]) == 0 and cd.pct(int(r["linked"]), int(r["total"])) is None
    assert bad == [] or all("코드 그룹 미정의" in b for b in bad)


def test_G09_N건_경로_연계성_100퍼센트와_정확성_산식():
    def body(cur):
        _chain(cur)
        run = _q1(cur)
        link = run(cd.LINKAGE)
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
    def body(cur):
        _insert(cur, "INV_MATERIAL_LOTS", LOT_NO="QA2-LX", ITEM_CODE="없는코드",
                CURRENT_QTY=0, LOT_STATUS="입고")
        return cd.accuracy(run=_q1(cur))
    ok, total, _bad = _in_rollback(body)
    assert total == 1 and ok == 0, "코드성 FK 위반 행을 '정상' 으로 세면 안 된다 (D-32)"
    assert cd.pct(ok, total) == 0.0


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
    assert (ok, total) == (0, 0), "전제가 바뀌었다 — N건 경로 테스트로 판정한다"
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


def test_KPI_0건_경로는_None_이고_0_0_이_아니다():
    for code, sql in ((kpimod.CODE_MFG, cd.SQL_MFG_QA), (kpimod.CODE_O2D, cd.SQL_O2D_QA)):
        r = conn.q1(sql)
        m = kpimod.measure(code)
        assert int(r["n"]) == 0 == m.sample_cnt
        assert r["h"] is None and m.value is None, "표본 0건을 0.0 으로 메우면 결함이다"
        assert m.achieve is None and m.value_text == "—"


def test_KPI_N건_경로_독립SQL이_앱_산식과_같은_값을_낸다():
    """`app/kpi.py` 를 믿지 않고 QA 가 새로 쓴 SQL 로 잰다."""
    def body(cur):
        c = _chain(cur, hours_mfg=1000.0, hours_o2d=1100.0)
        run = _q1(cur)
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
            # PRC_PROCESS_HISTORIES — 개발2 는 '시드 대상' 이라 판정했는데 전제가 막혀 0건이다
            assert n == 0, (
                f"{tid} 가 채워졌다 — §7.1 판정(시드 대상)이 실현된 것이므로 리포트를 갱신한다")
        else:
            assert n == expect, f"{tid} 판정({expect}건)과 실제({n}건)가 다르다"
