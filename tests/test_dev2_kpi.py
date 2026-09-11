"""개발2 KPI 산식 — `app/kpi.py` 가 **단일 소스**인지 검증한다.

  · 확정값(D-21)이 코드에 그대로 있는가
  · 감소율 18.2 / 16.7 이 **계산 결과**인가 (상수를 박아 두면 여기서 걸린다)
  · 0건 경로가 `None` 인가 — 0.0 으로 메우면 화면이 거짓말을 한다(G-11)
  · 대시보드·현황판·043·045 가 **같은 함수**를 쓰는가
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

from kyungdong.app import kpi                                    # noqa: E402


# ── 확정값 (사업계획서 1.5 · D-21) ───────────────────────────────────────
def test_공식_성과지표는_2종뿐이다():
    assert kpi.OFFICIAL_CODES == ("LEADTIME_MFG", "LEADTIME_O2D")
    assert all(d.official for d in kpi.DEFS.values())
    assert len(kpi.DEFS) == 2


@pytest.mark.parametrize("code,base,target,weight,uom", [
    ("LEADTIME_MFG", 1320.0, 1080.0, 0.5, "h"),
    ("LEADTIME_O2D", 1440.0, 1200.0, 0.5, "h"),
])
def test_확정값이_사업계획서_1_5_와_같다(code, base, target, weight, uom):
    d = kpi.definition(code)
    assert (d.base, d.target, d.weight, d.uom) == (base, target, weight, uom)


def test_감소율은_계산값이다():
    """상수 18.2/16.7 을 박아 두면 이 재계산과 어긋난다."""
    assert kpi.improve_rate(1320, 1080) == pytest.approx(18.2)
    assert kpi.improve_rate(1440, 1200) == pytest.approx(16.7)
    # 독립 재계산 — 산식을 여기서 다시 쓴다
    for d in kpi.DEFS.values():
        assert d.improve_rate == round((d.base - d.target) / d.base * 100.0, 1)


def test_기존값이_0이면_감소율을_내지_않는다():
    with pytest.raises(ValueError):
        kpi.improve_rate(0, 100)


# ── 0건 경로 (G-11) ─────────────────────────────────────────────────────
def test_표본_0건이면_평균은_None_이다():
    assert kpi.mean_hours([]) is None
    assert kpi.mean_hours([None, None]) is None


def test_표본_N건이면_평균을_낸다():
    assert kpi.mean_hours([1200.0, 1100.0, 1000.0]) == pytest.approx(1100.0)
    assert kpi.mean_hours([1190.0, 1160.0]) == pytest.approx(1175.0)


def test_달성률_0건_N건():
    d = kpi.definition("LEADTIME_MFG")
    assert kpi.achieve_rate(d.base, d.target, None) is None          # 0건
    assert kpi.achieve_rate(1320, 1080, 1080) == pytest.approx(100.0)
    assert kpi.achieve_rate(1320, 1080, 1320) == pytest.approx(0.0)
    assert kpi.achieve_rate(1320, 1080, 1200) == pytest.approx(50.0)


def test_비율은_분모가_0이면_None_이다():
    """0% 라고 말하면 '측정했는데 0' 이 되어 버린다 — 없는 것과 다르다."""
    assert kpi.ratio_pct(0, 0) is None
    assert kpi.ratio_pct(None, 10) is None
    assert kpi.ratio_pct(9, 10) == pytest.approx(90.0)


def test_품질_KPI_는_공식_성과지표가_아니다():
    assert kpi.QualityKpi.official is False
    assert "포함되지 않는다" in kpi.NOT_OFFICIAL_NOTE


# ── DB 경로 ─────────────────────────────────────────────────────────────
def test_KPI_TARGETS_에_확정값이_시드돼_있다():
    rows = {r["kpi_code"]: r for r in kpi.targets_in_db()}
    for code, d in kpi.DEFS.items():
        assert code in rows, f"{code} 미시드 — `uv run python db/seed_dev2.py`"
        r = rows[code]
        assert float(r["base_value"]) == pytest.approx(d.base)
        assert float(r["target_value"]) == pytest.approx(d.target)
        assert float(r["improve_rate"]) == pytest.approx(d.improve_rate)
        assert r["official_yn"] == "Y"


def test_measure_는_표본수와_평균을_함께_준다():
    """0건이면 sample_cnt=0 이고 value 는 None 이다 — 둘 다 단언한다."""
    for code in kpi.OFFICIAL_CODES:
        m = kpi.measure(code)
        rows = kpi.samples(code)
        assert m.sample_cnt == len(rows)
        if not rows:
            assert m.value is None and m.achieve is None
            assert m.value_text == "—"
        else:
            # 독립 재계산 — SQL 이 준 구간을 파이썬에서 다시 평균낸다
            manual = sum(float(r["hours"]) for r in rows) / len(rows)
            assert m.value == pytest.approx(round(manual, 2))


def test_summary_는_공식_2종을_순서대로_준다():
    s = kpi.summary()
    assert [m.definition.code for m in s] == list(kpi.OFFICIAL_CODES)


# ── 화면이 같은 값을 쓰는가 ──────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from kyungdong.app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _measured_texts(html: str) -> list[str]:
    """공식 성과지표 표에서 실측 칸 문자열을 뽑는다."""
    return re.findall(r"<td class=\"d2-num\">([^<]*(?:h|—))</td>", html)


def test_043_045_현황판이_같은_실측값을_보여_준다():
    c = _client()
    mfg, o2d = kpi.summary()
    for path in ("/kpi/043", "/kpi/045", "/board"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert mfg.value_text in r.text, f"{path} 에 {mfg.value_text} 가 없다"
        assert o2d.value_text in r.text, f"{path} 에 {o2d.value_text} 가 없다"


def test_043_045_현황판이_같은_확정값을_보여_준다():
    c = _client()
    for path in ("/kpi/043", "/kpi/045", "/board"):
        body = c.get(path).text
        assert "1,320 h" in body and "1,080 h" in body, path
        assert "1,440 h" in body and "1,200 h" in body, path
        assert "−18.2" in body and "−16.7" in body, path


def test_044_는_공식_성과지표가_아님을_구분_표기한다():
    body = _client().get("/kpi/044").text
    assert "공식 성과지표 아님" in body
    assert "포함되지 않는다" in body
