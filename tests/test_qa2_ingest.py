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
from kyungdong.ingest import collector, preprocess, tags       # noqa: E402
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


def test_G12_수집중단_판정이_화면과_수집모듈에서_같다(collected):
    """**DEF-QA2-002 · D-70 해소 실측.** 같은 사실에 두 구현이 다른 답을 냈다.

    표지를 뒤집었다 — **판정이 다시 갈리면** 깨진다. 화면 `routers/dsh.collection_badges()` 가
    **앵커** 기준, 수집 모듈 `ingest.collector.status()` 가 **실시각** 기준이라 같은 DB·같은
    시각에 반대 결론을 냈다. 지금은 판정이 `collector.stale_verdict()` **한 벌**이고 화면은
    그것을 부른다.

    `any_stale` 과 견주지 않는다 — 그 값은 한 번도 값이 없는 지점(현장POP)까지 참으로 만드는데
    화면은 그것을 '수집 중단' 이 아니라 **'미수집'** 으로 띄운다. 배지와 1:1 인 것은
    `ci.stale_with_data()` 다.
    """
    st = collector.status()
    screen_stale = any("수집 중단" in i["text"] for i in ci.screen_ingest_state().values())
    assert ci.stale_with_data(st) is True, "앵커 시각 데이터는 실시각 기준으로 중단이 맞다"
    assert screen_stale is True, "모듈이 중단이라는데 화면이 배지를 안 띄운다 (§10-16 판정 복제)"
    assert screen_stale == ci.stale_with_data(st)

    # 판정을 앵커로 **다시 쓰는** 코드가 생기면 그때부터 다시 갈린다 — 그 싹을 막는다.
    dup = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "src").rglob("*.py"))
           if re.search(r"anchor\(\)\s*-\s*last", p.read_text())]
    assert dup == [], f"중단 판정이 앵커 기준으로 복제됐다: {dup} (D-70 · §10-16)"


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


def test_G13_이상치가_실제로_걸러진다(collected):
    """**DEF-QA2-004 해소 실측.** '노이즈' 가 어휘로만 있고 판정·제거 로직이 0곳이었다.

    표지를 뒤집었다 — 판정이 사라지면 깨진다. **코드 유무로 끝내지 않는다**: 값을 주입해
    그 값이 `QUALITY_FLAG='노이즈'` 로 표시되는지 본다. 예전에는 40A 초과가 그대로 적재됐다.

    이상치를 **지우지 않는 것**이 설계다(§2.5) — 값은 남기고 플래그로 드러낸다. 학습에서 빼는
    것은 데이터셋 단계(`DAT_DATASET_ITEMS.OUTLIER_REMOVED_YN`)의 일이다.
    """
    assert "노이즈" in tags.QUALITY_FLAGS
    writers = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "src").rglob("*.py"))
               if "노이즈" in p.read_text()
               and (re.search(r"insert\s+into\s+DAT_TIMESERIES", p.read_text(), re.I)
                    or re.search(r"QUALITY_FLAG\s*=\s*['\"]?노이즈", p.read_text()))]
    assert writers, "이상치 판정·표시 코드가 사라졌다 — 어휘만 남으면 DEF-QA2-004 로 되돌아간다"

    # 판정 기준의 출처를 못박는다 — 없는 상·하한을 지어내지 않는다(D-315).
    assert preprocess.Z_LIMIT > 0 and preprocess.MIN_HISTORY > 0
    tol_rows = _n("PRC_STD_CONDITIONS")

    dev, tag = collected["device"], "CURRENT_VALUE"
    base_dt = clock.anchor() + timedelta(hours=9)
    mark = conn.q1("select coalesce(max(TS_ID),0) as n from DAT_TIMESERIES")["n"]
    try:
        # 표본을 먼저 쌓는다 — `MIN_HISTORY` 미만이면 **판정하지 않는 것**이 옳은 동작이다.
        for i in range(preprocess.MIN_HISTORY + 2):
            collector.ingest_batch(dev, "EQ10", [collector.Sample(
                tag, f"{20 + (i % 2) * 0.1:.4f}", base_dt + timedelta(seconds=i))])
        warm = conn.q("select QUALITY_FLAG, count(*) as n from DAT_TIMESERIES "
                      "where TS_ID > %s group by 1", (mark,))
        assert {r["quality_flag"] for r in warm} == {"정상"}, (
            f"정상 범위 값을 노이즈로 찍는다 (거짓 양성): {warm}")

        # 이상치 주입 — 표본 대비 크게 벗어난 값
        out_dt = base_dt + timedelta(seconds=100)
        collector.ingest_batch(dev, "EQ10", [collector.Sample(tag, "41.5000", out_dt)])
        row = conn.q1("select MEASURE_VALUE, QUALITY_FLAG from DAT_TIMESERIES "
                      "where TAG_NAME = %s and MEASURE_DT = %s", (tag, out_dt))
        assert row is not None, "이상치를 통째로 버렸다 — 값은 남기고 표시만 한다 (§2.5)"
        assert row["quality_flag"] == "노이즈", (
            f"주입한 이상치 {row['measure_value']} 가 '{row['quality_flag']}' 로 적재됐다 — "
            f"판정이 걸러내지 못한다 (표준조건 {tol_rows}건 · z 임계 {preprocess.Z_LIMIT})")
        assert row["measure_value"] is not None, "이상치의 값을 지웠다 — 원천을 잃는다"
    finally:
        conn.x("delete from DAT_TIMESERIES where TS_ID > %s", (mark,))


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


def test_G13_처리건수가_DAT_JOB_LOGS_에_남는다(collected):
    """**DEF-QA2-006 해소 실측.** 전처리 처리 건수가 `DAT_JOB_LOGS` 에 한 줄도 안 남았다.

    표지를 뒤집었다 — 기록이 사라지거나 건수가 실제와 어긋나면 깨진다.
    `DAT_PREPROCESS_RULES` 는 **규칙 정의**뿐이고(TD5 10컬럼에 건수 컬럼이 없다) 실행 건수는
    `DAT_JOB_LOGS.PROCESS_CNT` 에 남는 것이 정본 구조다 — 그 구조도 함께 못박는다.

    **0건을 처리하고 0을 적는 것으로는 증명되지 않는다.** 처리 대상을 일부러 남겨 두고
    실행해 기록된 건수가 실제 건수와 같은지 본다.
    """
    cols = {c["name"] for c in __import__("kyungdong.app.design", fromlist=["design"])
            .columns_of("DAT_PREPROCESS_RULES")}
    assert "PROCESS_CNT" not in cols and "APPLY_CNT" not in cols, \
        "규칙 표에 건수 컬럼이 생겼다 — 정의와 실행 기록을 섞지 않는다 (TD5)"
    assert _n("DAT_PREPROCESS_RULES") >= 5, "전처리 규칙이 시드되지 않았다 (seed_dev3)"
    writers = [p.relative_to(ROOT).as_posix()
               for p in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tools").rglob("*.py"))
               if not p.name.startswith("check_")
               and re.search(r"insert\s+into\s+DAT_JOB_LOGS", p.read_text(), re.I)]
    assert "src/kyungdong/ingest/preprocess.py" in writers, (
        f"전처리가 `DAT_JOB_LOGS` 에 쓰지 않는다: {writers} — DEF-QA2-006 으로 되돌아갔다")

    dev, tag = collected["device"], tags.numeric_tags()[0].name
    t0 = clock.anchor() + timedelta(hours=11)
    mark_ts = conn.q1("select coalesce(max(TS_ID),0) as n from DAT_TIMESERIES")["n"]
    mark_jl = conn.q1("select coalesce(max(JOB_LOG_ID),0) as n from DAT_JOB_LOGS")["n"]
    try:
        for i in range(6):
            collector.ingest_batch(dev, "EQ10", [collector.Sample(
                tag, "비숫자값" if i in (2, 4) else f"{70 + i}.0", t0 + timedelta(seconds=i))])
        mine = conn.q1("select count(*) as n from DAT_TIMESERIES where TS_ID > %s "
                       "and QUALITY_FLAG = '결측' and MEASURE_VALUE is null", (mark_ts,))["n"]
        assert mine == 2, f"보정 대상을 만들지 못했다 (내가 넣은 결측 {mine}건)"
        # 분모는 **이 설비의 보정 대기 전체**다 — `run()` 은 내가 넣은 것만 보지 않는다.
        # 앞선 테스트가 남긴 결측까지 세야 기록된 건수와 견줄 수 있다.
        want = conn.q1("select count(*) as n from DAT_TIMESERIES where EQUIP_CODE = 'EQ10' "
                       "and QUALITY_FLAG = '결측' and MEASURE_VALUE is null")["n"]
        assert want >= mine

        res = preprocess.run(equip_code="EQ10")
        assert res.job_log_id is not None, "전처리를 실행했는데 실행 로그 ID 가 없다"
        log = conn.q1("select PROCESS_CNT, FAIL_CNT, RESULT_CODE from DAT_JOB_LOGS "
                      "where JOB_LOG_ID = %s", (res.job_log_id,))
        assert log is not None, "`DAT_JOB_LOGS` 에 행이 남지 않았다 (G-13)"
        assert int(log["process_cnt"]) + int(log["fail_cnt"]) == want, (
            f"보정 대상 {want}건인데 기록은 처리 {log['process_cnt']} · 실패 {log['fail_cnt']} — "
            "처리 건수가 실제와 다르다")
        assert log["result_code"] in preprocess.RESULT_CODES, \
            f"실행 결과 어휘 위반: {log['result_code']}"
    finally:
        conn.x("delete from DAT_JOB_LOGS where JOB_LOG_ID > %s", (mark_jl,))
        conn.x("delete from DAT_TIMESERIES where TS_ID > %s", (mark_ts,))


# ══ G-10 N건 경로 (D-182) ═════════════════════════════════════════════════
def test_g10_은_시뮬레이터로_N건_경로를_재고_되돌린다():
    """**분모 0 은 판정 불가이지 PASS 도 FAIL 도 아니다**(규약 §5).

    그런데 `make db-reset` 직후 런타임 표는 늘 0이라 G-10 은 **영원히 차단**이었다 —
    측정은 시뮬레이터로 이미 하고 있었는데 그 결과가 G-10 에 귀속되지 않았을 뿐이다.
    결함 수정이 아니라 **판정이 사실을 말하게 만드는 일**이다(D-182).

    끝나고 런타임 표가 **0으로 돌아와야** 한다 — 남으면 G-11 이 오염된다.
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import check_data as cd

    tbls = ("IF_PLC_SIGNALS", "DAT_TIMESERIES", "PRC_EQUIP_SIGNALS")
    before = {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in tbls}
    if any(before.values()):
        # 실데이터가 있으면 시뮬레이터는 **손대지 않는다** — 그 사실을 단언하고 끝낸다.
        assert cd.simulate_for_g10() is None, "실데이터가 있는데 시뮬레이터가 덮어썼다"
        return

    sim = cd.simulate_for_g10()
    assert sim is not None, "시뮬레이터를 못 돌렸다"
    try:
        m = cd.missing_rate()
        # **주입한 만큼 세어지는가** — 완벽한 시계열을 만들면 결측률이 늘 0% 라 지표가
        # 결측을 잡는지 알 수 없다(§10-16 되돌림 원칙).
        assert m["rate"] == sim["expected_rate"], (
            f"주입 {sim['expected_rate']}% ↔ 실측 {m['rate']}%")
        assert m["expected"] > 0 and m["stored"] > 0, m
        ts_bad, sg_bad = cd.order_violations()
        assert ts_bad == 0 and sg_bad == 0, (ts_bad, sg_bad)
    finally:
        cd.cleanup_g10(sim)
    after = {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in tbls}
    assert after == before == {t: 0 for t in tbls}, f"런타임 표가 0으로 안 돌아왔다: {after}"


def test_g10_판정줄은_고지를_수치_앞에_둔다():
    """`gate.py` 가 판정 줄을 **120자에서 자른다.** 고지가 뒤에 있으면 잘려 나가고
    `PASS · 결측률 10.0%` 만 남아 **실물 설비 실측처럼** 인용된다 — G-14 에서 같은 이유로
    고지를 앞에 뒀다(D-151).
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import check_data as cd

    src = _Path(cd.__file__).read_text()
    i = src.index('verdict("G-10", PASS if ok else FAIL,')
    line = src[i:i + 400]
    notice = line.index("시뮬레이터 기준")
    number = line.index("결측률")
    assert notice < number, "고지가 수치 뒤에 있다 — 잘리면 거짓 증거가 된다"
    assert "실물 설비 실측이 아니다" in line
