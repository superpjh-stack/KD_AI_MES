"""CAD 파이프라인 — D-03 실측 재현 · D-05 미구성 501 · HITL 확정 (G-14 전제)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.util import http                      # noqa: E402
from kyungdong.cad import inventory as inv               # noqa: E402
from kyungdong.cad import pipeline, provider             # noqa: E402


@pytest.fixture(scope="module")
def files():
    return inv.read_inventory()


# ── D-03 실태를 코드가 재현한다 (수치를 지어내지 않았다는 증거) ─────────────
def test_인벤토리_실측이_D_03_과_같다(files):
    st = inv.stats(files)
    assert st["total"] == 1283
    assert st["products"] == 77
    assert st["file_name_dup"] == 183
    assert st["zero_byte"] == 4
    assert st["max_per_product"] == 184
    assert st["min_per_product"] == 1
    assert st["median_per_product"] == 5
    assert st["single_drawing_products"] == 9


def test_발행일_메타데이터가_없어_mtime_으로_대체한다(files):
    assert inv.stats(files)["no_mtime"] == 0, "mtime 조차 없으면 대체 기준이 무너진다 (D-03)"


def test_0KB_는_정제에서_제외된다(files):
    excluded = [c for c in inv.clean(files) if c.reason == inv.EXCLUDE_ZERO]
    assert len(excluded) == 4


def test_중복_제거_키는_도면번호_버전_고객사다():
    a = inv.dedup_key("TVD18", "C", None)
    b = inv.dedup_key("tvd18", "c", None)
    assert a == b, "대소문자·공백은 같은 도면으로 본다"
    assert inv.CUSTOMER_UNKNOWN in a, "고객사 메타데이터가 없다는 사실을 키에 남긴다 (D-03)"
    assert inv.dedup_key("TVD18", "C", None) != inv.dedup_key("TVD18", "E", None)


def test_버전_토큰을_파일명에서_뗀다():
    assert inv.split_revision("진공건조기 2.0 G.dwg") == ("진공건조기 2.0", "G")
    assert inv.split_revision("TVD18-C.cad") == ("TVD18", "C")
    assert inv.split_revision("GD1606-01-00.cad")[1] == ""


def test_정제는_순서를_유지하고_처음_1건만_남긴다(files):
    cleaned = inv.clean(files)
    assert [c.src.no for c in cleaned] == [f.no for f in files]
    keys = [c.dedup_key for c in cleaned if c.keep]
    assert len(keys) == len(set(keys))


# ── D-05 미구성이면 501. 조용한 합성 금지 ─────────────────────────────────
def test_인식_공급자가_미구성이다():
    avail = provider.availability()
    assert len(avail) == 2
    assert not any(a.configured for a in avail), "자격정보가 없는데 구성됐다고 말하면 안 된다"
    assert not provider.configured()


def test_미구성_공급자를_부르면_501_이다():
    for det in (provider.parsing_detector(), provider.vision_detector()):
        with pytest.raises(http.HTTPException) as e:
            det.detect("x.dwg")
        assert e.value.status_code == 501
        assert e.value.detail["message"] == "CAD Parsing 미구성 (D-05)"


def test_미구성_공급자는_빈_리스트를_돌려주지_않는다():
    """빈 리스트는 '0건 인식' 과 구분되지 않는다 — 그래서 예외여야 한다."""
    det = provider.parsing_detector()
    with pytest.raises(http.HTTPException):
        det.detect("x.dwg")


def test_분석_실행은_501_이고_객체를_만들지_않는다():
    """0건 경로도 **명시적으로 단언한다** — `skip` 하면 게이트에서 영원히 검증되지 않는다
    (§10-4 · DEF-QA2-010 · D-62)."""
    row = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS order by DRAWING_ID limit 1")
    before = conn.q1("select count(*) as n from EST_CAD_OBJECTS")["n"]
    if row is None:
        # 도면 0건 경로 — 없는 도면 분석은 **422** 이고, 그래도 객체는 안 생긴다.
        assert conn.q1("select count(*) as n from EST_CAD_DRAWINGS")["n"] == 0
        with pytest.raises(http.HTTPException) as e:
            pipeline.analyze(1)
        assert e.value.status_code == 422, "없는 도면인데 422 가 아니다"
        assert conn.q1("select count(*) as n from EST_CAD_OBJECTS")["n"] == before
        return
    with pytest.raises(http.HTTPException) as e:
        pipeline.analyze(int(row["drawing_id"]))
    assert e.value.status_code == 501
    after = conn.q1("select count(*) as n from EST_CAD_OBJECTS")["n"]
    assert before == after, "501 을 내면서 객체를 만들면 D-05 위반이다"


def test_집계_불가_Feature_는_차단으로_남는다():
    assert set(pipeline.DERIVABLE) == {"홀 수량"}
    assert set(pipeline.BLOCKED_FEATURES) == set(pipeline.FEATURE_TYPES) - {"홀 수량"}
    for why in pipeline.BLOCKED_FEATURES.values():
        # 차단 사유에는 **결정번호**가 있어야 한다 — 없으면 차단이 아니라 누락이다.
        # `.dwg`·`.cad` 는 D-05, `.dxf` 로는 되는 항목은 D-110-b 가 함께 적혀 있다.
        assert "D-05" in why or "D-110-b" in why


def test_차단은_파일_형식별로_갈린다_DXF_는_예외다():
    """D-05 를 '5종 전부 차단' 이라 적은 것은 `.dwg` 에는 맞고 `.dxf` 에는 틀리다 (D-110-b).

    **표본을 숨기지 않는다** — 원본 CAD 3,299건 중 dxf 는 29건(0.9%)이고 서로 다른 도면은 9건이다.
    """
    dxf_ok = [k for k, v in pipeline.support_for("DXF").items() if "없다" not in v]
    assert set(dxf_ok) == {"홀 수량", "총 절단장", "판재 면적", "두께"}
    # `재질` 은 값이 읽혀도 `FEATURE_VALUE` 가 NUMERIC 이라 적재할 자리가 없다 → 여전히 차단
    assert "재질" in pipeline.blocked_for("DXF")
    assert "용접장" in pipeline.blocked_for("DXF")
    for ft in ("DWG", "CAD"):
        assert pipeline.support_for(ft) == {}, f"{ft} 는 변환기가 없다 — 산출 가능이라고 적으면 거짓이다"
        assert set(pipeline.blocked_for(ft)) == set(pipeline.BLOCKED_FEATURES)
    assert pipeline.support_for(None) == {} and pipeline.support_for("PDF") == {}


def test_확정_객체가_없으면_Feature_도_0건이다():
    """도면이 0건이어도 **0건 경로를 단언한다** (§10-4 · DEF-QA2-010)."""
    row = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS order by DRAWING_ID limit 1")
    before = conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"]
    drawing_id = int(row["drawing_id"]) if row else 1
    out = pipeline.build_features(drawing_id)
    assert out["confirmed_objects"] == 0
    assert out["created"] == 0, "확정 전에 Feature 를 만들면 HITL 이 무의미하다"
    assert conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"] == before
    if row is None:
        # 없는 도면을 넣어도 Feature 를 지어내지 않는다 — 0건이 0건으로 남는다.
        assert conn.q1("select count(*) as n from EST_CAD_DRAWINGS")["n"] == 0
        assert before == 0


def test_수집_로그가_단계별로_남는다():
    """수집 전(0건) 경로도 단언한다 — 파일이 0건인데 로그가 있으면 시드가 런타임 표를 채운 것이다
    (§10-4 · G-11 · DEF-QA2-010)."""
    files_n = conn.q1("select count(*) as n from IF_CAD_FILES")["n"]
    logs_n = conn.q1("select count(*) as n from IF_CAD_IMPORT_LOGS")["n"]
    if files_n == 0:
        assert logs_n == 0, "수집 0건인데 수집 로그가 있다 — 런타임 전용 표를 시드가 채웠다 (G-11)"
        return
    steps = {r["step_name"] for r in conn.q("select distinct STEP_NAME from IF_CAD_IMPORT_LOGS")}
    assert steps <= set(pipeline.STEPS) and "수신" in steps and "중복제거" in steps
    reasons = {r["exclude_reason"] for r in conn.q(
        "select distinct EXCLUDE_REASON from IF_CAD_IMPORT_LOGS where EXCLUDE_REASON is not null")}
    assert reasons <= {inv.EXCLUDE_ZERO, inv.EXCLUDE_DUP}
