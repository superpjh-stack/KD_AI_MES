"""QA2 — G-12 수집 · G-13 전처리 회귀.

**수집 지점은 2개소뿐이다**(D-06). 전 공정 실시간 수집을 전제한 코드가 있으면 결함이다.
**0건 경로와 N건 경로를 둘 다 단언한다**(§10-4) — 데이터가 없다고 `skip` 하지 않는다(D-62).
이 파일이 넣은 행은 모듈 픽스처가 **전부 지운다**. 다른 테스트의 0건 경로를 오염시키지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT))

import conn                                                    # noqa: E402
from kyungdong.app.util import clock                           # noqa: E402
from kyungdong.cad import inventory as cadinv                  # noqa: E402
from kyungdong.cad import pipeline as cadpipe                  # noqa: E402
from kyungdong.ingest import collector, tags                   # noqa: E402
from tools import check_ingest as ci                           # noqa: E402

CYCLES = 5
COLLECT_TABLES = (("DAT_TIMESERIES", "TS_ID"), ("PRC_EQUIP_SIGNALS", "SIGNAL_ID"),
                  ("IF_GATEWAY_BUFFER", "BUFFER_ID"), ("IF_PLC_SIGNALS", "PLC_IF_ID"))


def _n(t: str) -> int:
    return int(conn.q1(f"select count(*) as n from {t}")["n"])


@pytest.fixture(scope="module")
def collected():
    """0건 상태에서 시작해 5주기를 수집하고(중간 1주기는 단절·복구), 끝나면 전부 지운다."""
    base = {t: (ci.maxid(t, c), _n(t)) for t, c in COLLECT_TABLES}
    assert all(v[1] == 0 for v in base.values()), (
        f"수집 표가 비어 있지 않다 {base} — `make db-reset` 뒤에 돌린다")
    dev = int(conn.q1("select DEVICE_ID from IF_DEVICE_REGISTRY where DEVICE_NAME = %s",
                      ("레이저커팅기 PLC",))["device_id"])
    a = clock.anchor()
    made = {"device": dev, "anchor": a, "batches": [], "buffered": []}
    try:
        for i in range(CYCLES):
            dt = a + timedelta(seconds=i)
            samples = [collector.Sample(t.name, "1" if t.numeric else "가동", dt)
                       for t in tags.TAGS]
            if i == 2:                                  # 단절 구간 — 로컬 버퍼에 쌓는다
                collector.buffer(dev, "EQ10", samples, "네트워크 단절")
                made["buffered"].append(dt)
            else:
                made["batches"].append(collector.ingest_batch(dev, "EQ10", samples))
        made["resend"] = collector.resend(dev)          # 복구 — 무손실 재전송
        yield made
    finally:
        for t, c in COLLECT_TABLES:
            conn.x(f"delete from {t} where {c} > %s", (base[t][0],))
        for t, _c in COLLECT_TABLES:
            assert _n(t) == base[t][1], f"{t} 가 검사 전 상태로 돌아가지 않았다"


# ══ G-12-① 수집 지점 2개소뿐 (D-06) ══════════════════════════════════════
def test_G12_수집_장비는_2대뿐이다():
    dev = conn.q("select DEVICE_NAME, DEVICE_TYPE from IF_DEVICE_REGISTRY order by DEVICE_ID")
    assert len(dev) == 2, f"사업계획서 2.7.1 데이터 집계 포인트는 2개소다: {dev}"
    assert {d["device_name"] for d in dev} == {"레이저커팅기 PLC", "현장POP(터치PC)"}
    eq = conn.q("select CODE_VALUE from BAS_COMMON_CODES where CODE_GROUP = '설비'")
    assert {e["code_value"] for e in eq} == {"EQ10", "EQ20"}


def test_G12_PLC_태그는_정본_8종뿐이고_모르는_태그는_422다():
    assert len(tags.TAGS) == 8
    assert tags.tag("없는태그") is None
    with pytest.raises(Exception) as e:
        collector.ingest_batch(1, "EQ10",
                               [collector.Sample("없는태그", "1", clock.anchor())])
    assert getattr(e.value, "status_code", None) == 422


def test_G12_시드가_수집_데이터를_흉내내지_않는다():
    src = "\n".join((ROOT / f).read_text() for f in ci.SEED_FILES)
    for t in ci.AUTO_TABLES:
        assert not re.search(rf"insert\s+into\s+{t}\b", src, re.I), (
            f"시드가 {t} 를 채우면 자동 수집을 위조하는 것이다 (D-06)")


def test_G12_자동수집_실적은_레이저커팅_P40_밖에_없다():
    rows = conn.q("select distinct PROCESS_CODE from PRC_PERFORMANCES "
                  "where COLLECT_METHOD like '자동%'")
    assert {r["process_code"] for r in rows} <= {"P40"}, (
        "자동(PLC) 수집은 가공(레이저커팅) 1지점뿐이다 — 전 공정 실시간 수집은 D-06 위반")


# ══ G-12-② 0건 경로 ══════════════════════════════════════════════════════
def test_G12_0건_경로_화면이_미수집을_렌더한다():
    assert _n("IF_PLC_SIGNALS") == 0 and _n("PRC_EQUIP_SIGNALS") == 0
    st = collector.status()
    assert st["points"] == 2
    assert all(d["last_collect_dt"] is None and d["stale"] for d in st["devices"])
    assert all("미수집" in (d["notice"] or "") for d in st["devices"])
    for path, info in ci.screen_ingest_state().items():
        assert info["status"] == 200
        assert "미수집" in info["text"], f"{path}: 수집 0건인데 '미수집' 문구가 없다"


# ══ G-12-③ N건 경로 — 유실 0 · 순서 보존 · 재전송 무손실 ═══════════════════
def test_G12_적재_유실이_0이다(collected):
    assert _n("IF_PLC_SIGNALS") == CYCLES * len(tags.TAGS)
    assert _n("PRC_EQUIP_SIGNALS") == CYCLES
    assert _n("DAT_TIMESERIES") == CYCLES * len(tags.numeric_tags())


def test_G10_규약_2_1_결측률_N건_경로가_0퍼센트다(collected):
    """`contracts/missing-policy.md` §2.1 산식의 **N건 경로**. 유실이 0이면 결측률도 0이다.

    0건 경로(분모 0 → 판정 불가)는 `tests/test_qa2_data.py` 가 단언한다(§10-4 둘 다).
    """
    from tools import check_data as cd
    m = cd.missing_rate()
    assert m["poll_sec"] == 1 and m["active_tags"] == 8
    assert m["expected"] == CYCLES * len(tags.TAGS), (
        f"기대 수집 건수 = (구간 {CYCLES}틱 − 비가동 {m['excluded_idle']} − 상태미상 "
        f"{m['unknown_state']}) × 태그 8 이어야 한다: {m['expected']}")
    assert m["stored"] == m["expected"]
    assert m["rate"] == 0.0, f"유실 0 인데 결측률이 {m['rate']}% 다"
    assert m["excluded_idle"] == 0 and m["unknown_state"] == 0, (
        "이 표본은 전부 '가동' 상태다 — 제외 구간이 생기면 산식 전제가 달라진다")
    # §1 — 현장POP 은 자동 폴링 대상이 아니라 분모에 들어가지 않는다
    assert [d["name"] for d in m["devices"] if not d["polled"]] == ["현장POP(터치PC)"]


def test_G12_순서가_구간별로_보존된다(collected):
    """store-and-forward 다 — 재전송분이 라이브 뒤에 붙는 전역 역전은 설계상 정상이다."""
    buffered = set(collected["buffered"])
    rows = conn.q("select TAG_NAME, COLLECT_DT from IF_PLC_SIGNALS order by PLC_IF_ID")
    live, resent = {}, {}
    for r in rows:
        box = resent if r["collect_dt"] in buffered else live
        prev = box.get(r["tag_name"])
        assert prev is None or prev <= r["collect_dt"], (
            f"{r['tag_name']} 구간 안에서 순서가 뒤집혔다")
        box[r["tag_name"]] = r["collect_dt"]
    assert live and resent, "라이브 구간과 재전송 구간이 둘 다 있어야 시험이 성립한다"


def test_G12_Gateway_버퍼가_무손실로_재전송된다(collected):
    bufs = conn.q("select BUFFER_STATUS, RESENT_DT, PAYLOAD from IF_GATEWAY_BUFFER")
    assert len(bufs) == len(collected["buffered"]) == 1
    assert all(b["buffer_status"] == "전송완료" and b["resent_dt"] is not None for b in bufs)
    for b in bufs:
        for s in json.loads(b["payload"])["samples"]:
            assert int(conn.q1(
                "select count(*) as n from IF_PLC_SIGNALS where TAG_NAME = %s and COLLECT_DT = %s",
                (s["tag"], s["collect_dt"]))["n"]) == 1, "버퍼 샘플이 유실되거나 두 번 들어갔다"
    assert collected["resend"]["failed"] == 0


def test_G12_같은_배치를_다시_보내도_행이_늘지_않는다(collected):
    before = _n("IF_PLC_SIGNALS")
    dt = collected["anchor"]
    r = collector.ingest_batch(
        collected["device"], "EQ10",
        [collector.Sample(t.name, "1" if t.numeric else "가동", dt) for t in tags.TAGS])
    assert r.stored == 0 and r.duplicated == len(tags.TAGS)
    assert _n("IF_PLC_SIGNALS") == before


def test_G12_N건_경로_화면에_마지막_수집시각이_뜬다(collected):
    last = conn.q1("select max(COLLECT_DT) as d from PRC_EQUIP_SIGNALS")["d"]
    for path, info in ci.screen_ingest_state().items():
        assert info["status"] == 200
        assert last.strftime("%Y-%m-%d %H:%M") in info["text"], (
            f"{path}: 수집 {CYCLES}건인데 마지막 수집시각이 화면에 없다 (G-12)")


def test_G12_수집중단_판정이_화면과_수집모듈에서_갈린다(collected):
    """DEF-QA2-002 — 같은 사실에 두 구현이 다른 답을 낸다.

    화면 `routers/dsh.collection_badges()` 는 **앵커** 기준, 수집 모듈
    `ingest.collector.status()` 는 **실시각** 기준이다. 이 단언이 깨지면 결함이 해소된
    것이므로 리포트를 갱신한다.
    """
    module_stale = collector.status()["any_stale"]
    screen_stale = any("수집 중단" in i["text"] for i in ci.screen_ingest_state().values())
    assert module_stale is True, "앵커 시각 데이터는 실시각 기준으로는 중단이다"
    assert screen_stale is False, "화면은 앵커 기준이라 중단으로 보지 않는다"


def test_G12_앵커보다_오래된_수집이면_화면도_중단을_표시한다(collected):
    """화면의 중단 배지 경로 자체는 살아 있다 — 다만 **앵커보다 과거**여야만 뜬다."""
    before = conn.q1("select max(COLLECT_DT) as d from PRC_EQUIP_SIGNALS")["d"]
    # **정확히 되돌린다** — 상수로 덮어쓰면 서로 다른 수집 시각이 한 값으로 뭉개진다
    conn.x("update PRC_EQUIP_SIGNALS set COLLECT_DT = COLLECT_DT - interval '2 hours'")
    try:
        shifted = before - timedelta(hours=2)
        screens = ci.screen_ingest_state()
        assert any("수집 중단" in i["text"] for i in screens.values())
        assert all(shifted.strftime("%Y-%m-%d %H:%M") in i["text"] for i in screens.values())
    finally:
        conn.x("update PRC_EQUIP_SIGNALS set COLLECT_DT = COLLECT_DT + interval '2 hours'")
    assert conn.q1("select max(COLLECT_DT) as d from PRC_EQUIP_SIGNALS")["d"] == before


# ══ G-13 전처리 ══════════════════════════════════════════════════════════
def test_G13_단위_표준화가_태그_정본을_따른다(collected):
    for t in tags.numeric_tags():
        rows = conn.q("select distinct UOM from DAT_TIMESERIES where TAG_NAME = %s", (t.name,))
        assert [r["uom"] for r in rows] == [t.uom], f"{t.name} 단위가 정본과 다르다"


def test_G13_비숫자값은_결측으로_남기고_버리지_않는다(collected):
    dt = clock.anchor() + timedelta(seconds=900)
    t = tags.numeric_tags()[0]
    collector.ingest_batch(collected["device"], "EQ10",
                           [collector.Sample(t.name, "N/A", dt)])
    row = conn.q1("select MEASURE_VALUE, QUALITY_FLAG from DAT_TIMESERIES "
                  "where TAG_NAME = %s and MEASURE_DT = %s", (t.name, dt))
    assert row is not None, "결측을 버리면 안 된다 — 행은 남기고 플래그로 표시한다"
    assert row["measure_value"] is None and row["quality_flag"] == "결측"


def test_G13_중복_제거는_도면번호_버전_고객사_기준이다():
    """0건 경로와 N건 경로 · 주입 전후 비교."""
    assert cadinv.clean([]) == [], "빈 입력의 정제 결과는 빈 리스트다 (0건 경로)"
    files = cadinv.read_inventory()
    base = cadinv.clean(files)
    base_kept = sum(1 for c in base if c.keep)
    assert base_kept > 0, "N건 경로가 없다"
    import dataclasses
    inject = [files[0], files[0], files[1],
              dataclasses.replace(files[2], size_kb=0.0)]
    after = cadinv.clean(list(files) + inject)
    assert sum(1 for c in after if c.keep) == base_kept, (
        "중복 3건·0KB 1건을 주입했는데 등록 건수가 늘었다")
    reasons = {}
    for c in after:
        if not c.keep:
            reasons[c.reason] = reasons.get(c.reason, 0) + 1
    assert reasons[cadinv.EXCLUDE_DUP] >= 3 and reasons[cadinv.EXCLUDE_ZERO] >= 1
    # 고객사 메타데이터 부재 — 지어내지 않고 그렇게 적는다 (D-03)
    assert cadinv.CUSTOMER_UNKNOWN in cadinv.dedup_key("A", "1", None)


def test_G13_이상치_처리가_없다는_사실을_기록한다():
    """DEF-QA2-004 — '노이즈' 는 어휘로만 있고 판정·제거 로직이 없다.

    이 단언이 깨지면 이상치 처리가 생긴 것이므로 리포트를 갱신한다.
    """
    assert "노이즈" in tags.QUALITY_FLAGS
    writers = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "src").rglob("*.py"))
               if "노이즈" in p.read_text()
               and (re.search(r"insert\s+into\s+DAT_TIMESERIES", p.read_text(), re.I)
                    or re.search(r"QUALITY_FLAG\s*=\s*['\"]?노이즈", p.read_text()))]
    assert writers == [], f"이상치 판정 코드가 생겼다: {writers}"


def test_G13_Feature_6종_중_1종만_산출_가능하다():
    """DEF-QA2-005 — 게이트 요구 6종 대비 코드로 산출 가능한 것은 '홀 수량' 뿐이다.

    **이 결함은 해소되지 않았다.** (조율자가 DEF-QA2-005 해소로 전달받은 것은
    `contracts/missing-policy.md` 부재 = DEF-QA2-007 이다. 검사기 메시지의 번호가 틀렸던 것을
    바로잡았다 — 리포트 §1 참조.)
    """
    assert set(cadpipe.DERIVABLE) == {"홀 수량"}
    alias = {"절단 길이": "총 절단장", "용접 길이": "용접장"}
    derivable = [f for f in ci.REQUIRED_FEATURES if alias.get(f, f) in cadpipe.DERIVABLE]
    assert derivable == ["홀 수량"], f"산출 가능 Feature 가 늘었다: {derivable}"
    assert "형상 복잡도" not in cadpipe.FEATURE_TYPES, (
        "게이트가 요구하는 '형상 복잡도' 는 TD5 FEATURE_TYPE 어휘에도 없다")
    for why in cadpipe.BLOCKED_FEATURES.values():
        assert "D-05" in why, "차단 사유에 근거 결정번호가 없다"


def test_G13_전처리_규칙은_정의뿐이고_처리건수_컬럼이_없다():
    """DEF-QA2-006 — 처리 건수가 `DAT_JOB_LOGS` 에 남지 않는다."""
    cols = {c["name"] for c in __import__("kyungdong.app.design", fromlist=["design"])
            .columns_of("DAT_PREPROCESS_RULES")}
    assert "PROCESS_CNT" not in cols and "APPLY_CNT" not in cols
    assert _n("DAT_PREPROCESS_RULES") == 5, "전처리 규칙 5건 (seed_dev3)"
    writers = [p.relative_to(ROOT).as_posix()
               for p in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tools").rglob("*.py"))
               if not p.name.startswith("check_")
               and re.search(r"insert\s+into\s+DAT_JOB_LOGS", p.read_text(), re.I)]
    assert writers == ["src/kyungdong/app/routers/dat.py"], (
        f"DAT_JOB_LOGS 에 쓰는 곳이 바뀌었다: {writers}")
