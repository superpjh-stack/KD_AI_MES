"""DXF 실측 파서 · 견적(.xls) 파서 · 원본 아카이브 스캐너 (D-109 ~ D-115).

**원본 아카이브가 없는 장비에서도 돌아야 한다.** 그래서 DXF 는 이 파일이 **직접 만든 최소 도면**으로
재고(손으로 계산한 정답과 대조한다), 아카이브가 있는 장비에서는 실제 파일로 한 번 더 잰다.
아카이브가 없으면 `skip` 이 아니라 **0건 경로를 단언**한다 — `skip` 은 결함이다(D-62).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

from kyungdong.cad import archive, dxf, pipeline, quote   # noqa: E402

# 손으로 계산한 정답이 붙은 최소 DXF.
#   LINE  (0,0)-(3,4) = 5 · LINE (0,0)-(0,10) = 10          → 15
#   ARC   r=10, 0°→90°                                       → 10·π/2 = 15.70796…
#   CIRCLE ×3 (r=2.5 → 지름 5)                               → 홀 3
#   닫힌 LWPOLYLINE 10×10 정사각형                            → 둘레 40 · 면적 100
#   TEXT  'STS316L  t=6'                                     → 재질 STS316L · 두께 6
MINIMAL_DXF = "\n".join([
    "0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
    "0", "SECTION", "2", "ENTITIES",
    "0", "LINE", "10", "0.0", "20", "0.0", "11", "3.0", "21", "4.0",
    "0", "LINE", "10", "0.0", "20", "0.0", "11", "0.0", "21", "10.0",
    "0", "ARC", "10", "0.0", "20", "0.0", "40", "10.0", "50", "0.0", "51", "90.0",
    "0", "CIRCLE", "10", "1.0", "20", "1.0", "40", "2.5",
    "0", "CIRCLE", "10", "2.0", "20", "2.0", "40", "2.5",
    "0", "CIRCLE", "10", "3.0", "20", "3.0", "40", "2.5",
    "0", "LWPOLYLINE", "90", "4", "70", "1",
    "10", "0.0", "20", "0.0", "10", "10.0", "20", "0.0",
    "10", "10.0", "20", "10.0", "10", "0.0", "20", "10.0",
    "0", "TEXT", "10", "0.0", "20", "0.0", "1", "STS316L  t=6",
    "0", "ENDSEC", "0", "EOF", ""])


@pytest.fixture(scope="module")
def minimal(tmp_path_factory) -> dxf.DxfMeasure:
    p = tmp_path_factory.mktemp("dxf") / "minimal.dxf"
    p.write_text(MINIMAL_DXF, encoding="utf-8")
    return dxf.parse(p)


# ══ DXF — 손으로 계산한 정답과 대조한다 ═══════════════════════════════════
def test_DXF_엔티티를_group_code_로_읽는다(minimal):
    assert minimal.error is None
    assert minimal.entities == {"LINE": 2, "ARC": 1, "CIRCLE": 3, "LWPOLYLINE": 1, "TEXT": 1}
    assert minimal.encoding == "utf-8"
    assert minimal.insunits == "mm" and minimal.uom == "mm"


def test_DXF_홀은_CIRCLE_전량이고_지름_필터를_걸지_않는다(minimal):
    assert minimal.holes == 3
    assert minimal.circle_diameters == [5.0, 5.0, 5.0]
    src = next(f for f in minimal.features() if f["type"] == dxf.F_HOLES)["source"]
    assert "지름 필터" in src and "D-110-b" in src, "필터를 안 걸었다는 사실을 적지 않으면 과장이다"


def test_DXF_절단장은_LINE_ARC_POLYLINE_의_합이다(minimal):
    assert minimal.line_len == pytest.approx(15.0)
    assert minimal.arc_len == pytest.approx(10 * math.pi / 2)
    assert minimal.poly_len == pytest.approx(40.0)
    assert minimal.cut_len == pytest.approx(15.0 + 10 * math.pi / 2 + 40.0)


def test_DXF_판재면적은_닫힌_POLYLINE_의_shoelace_다(minimal):
    assert minimal.closed_polys == 1
    assert minimal.closed_area == pytest.approx(100.0)


def test_DXF_표제란에서_재질과_두께를_읽는다(minimal):
    assert minimal.material == "STS316L"
    assert minimal.thickness == pytest.approx(6.0)
    assert minimal.material_hits == {"STS316L": 1}


def test_DXF_재질은_숫자_컬럼에_담을_자리가_없어_value_가_None_이다(minimal):
    mat = next(f for f in minimal.features() if f["type"] == dxf.F_MATERIAL)
    assert mat["value"] is None and mat["text"] == "STS316L"
    assert "NUMERIC" in mat["source"], "적재 못 하는 이유를 적지 않으면 조용한 실패다"
    for f in minimal.features():
        assert str(f["source"]).startswith(dxf.SOURCE_TAG), "합성과 구분되는 표지가 없다"


def test_DXF_가_비면_Feature_도_0건이다(tmp_path):
    p = tmp_path / "empty.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    m = dxf.parse(p)
    assert m.entities == {} and m.features() == [], "빈 도면에서 Feature 를 만들면 합성이다"
    assert dxf.hit_rates([m])["parsed"] == 1


def test_DXF_인코딩은_파일_전체로_판정한다(tmp_path):
    """앞부분만 보고 정하면 145MB 도면에서 뒤쪽 한글이 깨진다 (D-115 재발 방지)."""
    p = tmp_path / "cp949.dxf"
    body = MINIMAL_DXF.replace("STS316L  t=6", "재질 STS316L  t=6 한글표제란")
    p.write_bytes(body.encode("cp949"))
    assert dxf.detect_encoding(p) == "cp949"
    assert dxf.parse(p).material == "STS316L"


# ══ 견적 — 한자 수사 읽기 (원본에 갖은자가 섞여 있다) ═════════════════════
@pytest.mark.parametrize("run, want", [
    ("伍億四阡七百參拾七萬伍阡", 547_375_000),      # 반응기-1차견적080222.xls 실측
    ("壹億四阡貳百四拾六萬伍阡", 142_465_000),      # Reactor-견적.xls 실측
    ("一億六千四十二萬三千", 160_423_000),          # 견적서-REACTOR FULL SET(10,000L).xls 실측
    ("六千七百二萬六千", 67_026_000),               # 견적서-REACTOR 일성.xls 실측
])
def test_한자_수사를_정수로_읽는다(run, want):
    assert quote.han_to_int(run) == want


def test_읽을_수_없는_한자는_None_이다():
    assert quote.han_to_int("院整") is None, "모르는 글자를 만나면 추측하지 않는다"
    assert quote.han_to_int("一二") is None, "1만 미만은 총액이 아니다"


def test_납기_표기를_일수로_읽고_숫자가_없으면_뽑지_않는다():
    assert quote.LEAD_DAYS.search("發注後50日間").group(1) == "50"
    assert quote.LEAD_DAYS.search("발주일로부터70일").group(1) == "70"
    assert quote.LEAD_DAYS.search("발주후45일").group(1) == "45"
    assert quote.LEAD_DAYS.search("납기:신속납기") is None, "0일이라고 적으면 거짓이다"


def test_금액_라벨에_맨_금액은_넣지_않는다():
    """명세표의 `금  액` 열 머리글과 구별이 안 돼 품목 단가를 총액으로 집어 온다."""
    assert quote.TOTAL_LABEL.search("합계금액")
    assert quote.TOTAL_LABEL.search("合計金額")
    assert quote.TOTAL_LABEL.search("공사금액")
    assert quote.TOTAL_LABEL.search("금액") is None


def test_NFC_정규화_없이는_한글을_못_찾는다():
    """macOS 파일명은 NFD 다 — 이 한 줄이 빠져서 `견적` 검색이 0건을 냈다 (D-115)."""
    import unicodedata

    nfd = unicodedata.normalize("NFD", "견적서.xls")
    assert "견적" not in nfd, "전제가 깨졌다 — NFD 에서는 부분 문자열이 안 맞는다"
    assert "견적" in quote.nfc(nfd) and "견적" in archive.nfc(nfd)


# ══ 원본 아카이브 — 프로젝트 번호 파싱 ════════════════════════════════════
@pytest.mark.parametrize("folder, no, group, cust", [
    ("GD160801-진공건조기", "GD160801", "진공건조기", None),
    ("GD160803-누체필터10L", "GD160803", "누체필터", None),
    ("GD2007-00 동광제약", "GD2007-00", None, "동광제약"),
    ("GD1906-저장탱크-대한열기", "GD1906", "저장탱크", "대한열기"),
    ("GD1704-두루텍", "GD1704", None, "두루텍"),
    ("GD2003-02-에니젠-누체필터 100L", "GD2003-02", "누체필터", "에니젠"),
])
def test_GD_폴더명에서_프로젝트번호를_읽는다(folder, no, group, cust):
    p = archive.parse_project(folder)
    assert p is not None
    assert (p.project_no, p.product_group, p.customer) == (no, group, cust)


def test_GD_가_아닌_폴더는_None_이고_지어내지_않는다():
    for bad in ("REACTOR", "16 경동도면함", "기타(개별부품)", "GD-없음"):
        assert archive.parse_project(bad) is None, f"{bad} 를 프로젝트로 만들면 합성이다"


def test_원본_아카이브가_없으면_예외지_빈_결과가_아니다(tmp_path):
    missing = tmp_path / "없는폴더"
    assert archive.available(missing) is False
    with pytest.raises(FileNotFoundError):
        archive.scan(missing)


def test_원본_아카이브_실측_또는_부재를_둘_다_단언한다():
    """있으면 D-109 실측(6,038 파일 · GD 99 · dxf 29)을 재현하고, 없으면 **없다고 단언**한다."""
    if not archive.available():
        assert archive.archive_root().is_dir() is False
        return
    scan = archive.scan()
    st = scan.stats()
    assert st["files"] == 6038, "D-109 실측이 바뀌었다 — 원본이 바뀌었는지 확인한다"
    assert st["cad_by_ext"] == {"dwg": 2240, "cad": 1030, "dxf": 29}
    assert st["project_dirs"] == 99 and st["project_parse_failed"] == 0
    assert st["quote_files"] == 73, "NFC 정규화가 빠지면 여기가 0 이 된다 (D-115)"
    assert st["quote_by_ext"]["xls"] == 31
    # D-113 — REACTOR/반응기 도면 304 · 견적 32
    top = {r["folder"]: r for r in scan.joins()["subtree_top"]}
    assert top["REACTOR/반응기"]["drawings"] == 304
    assert top["REACTOR/반응기"]["quotes"] == 32


def test_표본_수를_숨기지_않는다_DXF_는_전체_도면의_1퍼센트_미만이다():
    """`.dxf` 29 / CAD 3,299 = 0.9%. 이 표본으로 G-14(80%)를 주장하면 거짓이다."""
    doc = (pipeline.__doc__ or "") + (dxf.__doc__ or "")
    assert "3,299" in dxf.__doc__ and "0.9%" in dxf.__doc__
    assert "G-14" in dxf.__doc__, "표본이 작다는 경고가 코드에 없으면 다음 사람이 그 수를 쓴다"
    assert doc  # 0건 경로 방지
