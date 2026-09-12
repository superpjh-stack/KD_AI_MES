"""CAD 파이프라인 — D-03 실측 재현 · D-05 미구성 501 · HITL 확정 (G-14 전제)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.util import assumed, http             # noqa: E402
from kyungdong.cad import archive                         # noqa: E402
from kyungdong.cad import dwgconv                        # noqa: E402
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
def test_고객사_목록은_박아_두지_않고_확정_정본에서_읽는다():
    """**D-136 해소** — 하드코딩 18종에 고객사가 아닌 것이 4종 섞여 있었다.

    `최성배`(사람 이름) 1 · `원명에스티에스`·`리트산업`·`태양기어`(셋 다 *경동글로벌텍 귀중*
    견적서의 **공급자**) 3. 게다가 `그린텍` 은 미분류였고, 확정 19종 중 **7종이 빠져** 있었다.
    실측으로 `GD1806-최성배` 3폴더가 **사람을 고객사로** 세고 있었고 `GD2003-01-썬바이오`
    2폴더는 진짜 고객사인데 **빠뜨리고** 있었다.

    도입기업이 ⑥ 에서 "협력사·공급사 16종은 고객사가 아니다" 를 확인해 준 뒤로는(D-166)
    이 목록이 정본과 **증명 가능하게** 어긋난 상태였다. 그래서 출처를 하나로 묶었다 —
    D-163 과 같은 결함이다: **진실을 두 곳에 두면 한 곳이 조용히 낡는다.**
    """
    import json as _json

    pairs = archive.known_customers()
    canon = {c for _, c in pairs}
    data = _json.loads(archive.CUSTOMER_JSON.read_text(encoding="utf-8"))
    expected = {str(c["정규화이름"]).split("/")[0].strip() for c in data["후보"]
                if str(c["분류"]).startswith(archive.CUSTOMER_ROLE_PREFIX)}
    assert canon == expected, f"확정 정본과 어긋난다: {sorted(canon ^ expected)}"
    assert len(canon) == 19, f"확정 고객사는 19종이다 (D-139·D-166): {len(canon)}"

    # **돌아오면 안 되는 것** — 사람 이름과 공급사 4종. 하나라도 다시 들어오면 깨진다.
    tokens = {t for t, _ in pairs}
    for wrong in ("최성배", "원명에스티에스", "리트산업", "태양기어"):
        assert wrong not in tokens and wrong not in canon, (
            f"`{wrong}` 은 고객사가 아니다 — 사람 이름이거나 *경동글로벌텍 귀중* 견적서의 공급자다")
    # 빠져 있던 것이 실제로 들어왔는가.
    assert "썬바이오" in canon and "나노신소재" in canon

    # 폴더 표기가 대표 이름으로 접히는가 — `웰이엔시` 폴더도 `웰이엔씨` 로 센다.
    m = dict(pairs)
    assert m.get("웰이엔시") == "웰이엔씨", m.get("웰이엔시")
    assert m.get("애니젠") == "에니젠", m.get("애니젠")
    # 슬래시가 박힌 이름이 그대로 나가지 않는다 — 회사 이름인 줄 안다.
    assert not any("/" in c for c in canon), sorted(c for c in canon if "/" in c)

    # 긴 표기가 먼저 온다 — `엔에프테크 조범주` 가 `엔에프테크` 보다 앞이어야
    # 폴더명 전체를 설명한다.
    order = [t for t, _ in pairs]
    assert order.index("엔에프테크 조범주") < order.index("엔에프테크")


def test_확정_정본이_없으면_고객사는_0건이고_하드코딩으로_돌아가지_않는다(tmp_path, monkeypatch):
    """**출처가 사라지면 0건이다.** 하드코딩 폴백을 두면 D-136 이 조용히 되살아난다(§10-9)."""
    archive.known_customers.cache_clear()
    monkeypatch.setattr(archive, "CUSTOMER_JSON", tmp_path / "없는파일.json")
    try:
        assert archive.known_customers() == ()
    finally:
        monkeypatch.undo()
        archive.known_customers.cache_clear()
    assert len(archive.known_customers()) >= 19, "원상복구되지 않았다"


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
        # D-05(원천 미구성) 는 지우지 않는다. 변환으로 풀린 항목은 D-123 이 함께 적혀 있다.
        assert "D-05" in why, "QA 시험(test_qa2_ingest)이 D-05 를 읽는다 — 빼면 깨진다"
        assert "D-110-b" in why or "D-122" in why or "D-123" in why


def test_변환되면_차단이_아니다_변환_실패분만_차단이다():
    """**D-123 으로 DWG 판정이 바뀌었다.** '구조적 불가' → '변환 후 산출, 실패분은 차단'.

    `.cad` 는 변환기가 있어도 **0%** 다 — 앞 6바이트가 `V10.00` 으로 DWG 서명(AC1xxx)이 아니다.
    **변환이 되는 것과 전량이 되는 것은 다르다** — 사유 문자열이 그 둘을 갈라 적는지 못박는다.
    """
    dxf_ok = [k for k, v in pipeline.support_for("DXF").items() if "없다" not in v]
    assert set(dxf_ok) == {"홀 수량", "총 절단장", "판재 면적", "두께"}
    # `재질` 은 값이 읽혀도 `FEATURE_VALUE` 가 NUMERIC 이라 적재할 자리가 없다 → 여전히 차단
    assert "재질" in pipeline.blocked_for("DXF")
    assert "용접장" in pipeline.blocked_for("DXF")

    # DWG — 변환기가 있으면 DXF 와 같은 4종이 산출 가능이다 (D-123)
    if dwgconv.available():
        dwg_ok = [k for k, v in pipeline.support_for("DWG").items() if "없다" not in v]
        assert set(dwg_ok) == {"홀 수량", "총 절단장", "판재 면적", "두께"}
        assert set(pipeline.blocked_for("DWG")) == {"재질", "용접장"}
        for k in dwg_ok:
            assert "변환" in pipeline.support_for("DWG")[k]
    else:
        # 변환기가 없는 장비에서는 D-05 그대로 전량 차단이다 — 있는 척하지 않는다
        assert pipeline.support_for("DWG") == {}
        assert set(pipeline.blocked_for("DWG")) == set(pipeline.BLOCKED_FEATURES)

    # `.cad` 는 변환기 유무와 무관하게 전량 차단이다
    assert pipeline.support_for("CAD") == {}, "`.cad` 는 변환 성공 0건이다 (D-123)"
    assert set(pipeline.blocked_for("CAD")) == set(pipeline.BLOCKED_FEATURES)
    assert pipeline.support_for(None) == {} and pipeline.support_for("PDF") == {}
    # 용접장은 **변환해도** 못 가른다 — 변환으로 풀렸다고 적으면 거짓이다
    assert "0건" in pipeline.BLOCKED_FEATURES["용접장"]


def test_변환기_껍데기는_실패를_실패로_돌려준다(tmp_path):
    """**없는 성공을 만들지 않는다.** DWG 가 아닌 파일을 넣으면 `ok=False` 와 사유가 나온다."""
    bogus = tmp_path / "not-a-dwg.dwg"
    bogus.write_bytes(b"V10.00" + b"\x00" * 64)      # `.cad` 들의 실제 서명 (D-123)
    assert dwgconv.signature(bogus) == "아님:'V10.00'"
    if not dwgconv.available():
        pytest.skip(f"{dwgconv.BINARY} 미설치 — 이 장비에서는 D-05 그대로다")
    m, got = dwgconv.measured(bogus, work_dir=tmp_path)
    assert m is None and got.ok is False and got.reason
    assert not list(tmp_path.glob("dwgconv-*.dxf")), "중간 DXF 를 남기면 전량에서 8.5GB 가 쌓인다"


def test_변환_실패_사유는_변환기가_뱉은_말을_정규화한다():
    """분류 바구니를 지어내지 않는다 — 경로·숫자만 지운다."""
    got = dwgconv.normalize_error(
        "Warning: something\nERROR: Invalid DWG, magic: V10.00 at /tmp/a/b.dwg 0x1f\n", 1)
    # `V10` 의 10 은 앞이 `V` 라 단어 경계가 없어 남는다 — 실제 동작을 그대로 못박는다
    assert got == "ERROR: Invalid DWG, magic: V10.N at <path> <hex>"
    assert "신호 11" in dwgconv.normalize_error("", -11)


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


# ══ HITL 승인이 확정을 만드는 경로 (G-14·G-19 의 3단계 전제) ═══════════════
# `check_ingest ⑤` 는 "확정 객체 0건 + Feature N행 = 합성" 으로 판정한다. 그 규칙을 **우회하지
# 않고** 규칙이 요구하는 경로 — 객체 → `review_object()` 승인 → 확정 → Feature — 가 실제로
# 도는지 잰다. 넣은 행은 **전부 지운다**(런타임 전용 표 0건 · G-11 을 오염시키지 않는다).
def test_HITL_승인이_확정을_만들고_그_확정으로만_Feature_가_생긴다():
    row = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS order by DRAWING_ID limit 1")
    if row is None:
        pytest.skip("도면 0건 — `make cad-ingest` 먼저")   # noqa: PT018
    did = int(row["drawing_id"])
    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    feat0 = int(conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"])
    obj = conn.q1(
        "insert into EST_CAD_OBJECTS "
        "(DRAWING_ID, DETECT_METHOD, OBJECT_TYPE, CONFIDENCE_SCORE, CONFIRM_YN, CREATED_DT) "
        "values (%s, 'Parsing', '홀', 0.5, 'N', now()) returning OBJECT_ID", (did,))
    oid = int(obj["object_id"])
    try:
        # ① 승인 전에는 확정이 아니다 → Feature 0건
        assert pipeline.build_features(did)["created"] == 0
        assert int(conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"]) == feat0
        # ② 권한 없는 역할은 403 — 확정이 생기지 않는다
        with pytest.raises(http.HTTPException):
            pipeline.review_object(oid, reviewer_id=int(admin["user_id"]),
                                   role_code="OPERATOR", result="승인")
        assert conn.q1("select CONFIRM_YN from EST_CAD_OBJECTS where OBJECT_ID = %s",
                       (oid,))["confirm_yn"] == "N"
        # ③ 승인 권한이 있으면 확정이 생긴다 — **이 경로 하나뿐이다**
        out = pipeline.review_object(oid, reviewer_id=int(admin["user_id"]),
                                     role_code="SYSADMIN", result="승인")
        assert out["confirm_yn"] == "Y"
        assert conn.q1("select CONFIRM_YN from EST_CAD_OBJECTS where OBJECT_ID = %s",
                       (oid,))["confirm_yn"] == "Y"
        # ④ 확정이 있으면 Feature 가 생긴다 — 집계 가능한 것은 '홀 수량' 1종뿐(D-05)
        built = pipeline.build_features(did)
        assert built["confirmed_objects"] == 1
        assert built["created"] == 1, built
        made = conn.q("select FEATURE_TYPE, FEATURE_VALUE, SOURCE_DESC from EST_CAD_FEATURES "
                      "where DRAWING_ID = %s", (did,))
        assert [m["feature_type"] for m in made] == ["홀 수량"]
        assert float(made[0]["feature_value"]) == 1.0
        assert "CONFIRM_YN" in made[0]["source_desc"], made[0]["source_desc"]
    finally:
        conn.x("delete from EST_CAD_FEATURES where DRAWING_ID = %s", (did,))
        conn.x("delete from EST_OBJECT_REVIEWS where OBJECT_ID = %s", (oid,))
        conn.x("delete from EST_CAD_OBJECTS where OBJECT_ID = %s", (oid,))
    assert int(conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"]) == feat0
    assert int(conn.q1("select count(*) as n from EST_OBJECT_REVIEWS")["n"]) == 0
    assert int(conn.q1("select count(*) as n from EST_CAD_OBJECTS")["n"]) == 0


# ══ 단위 가정 (D-150) — 표지 없이 단위만 바뀌면 거짓 실측이다 ══════════════
def test_단위_가정은_표지를_달고_붙고_명시된_단위는_건드리지_않는다():
    """`store_dxf_features` 는 기본으로 쓰지 않는다 — 쓰는 경로를 명시로 열고 되돌린다."""
    rows = conn.q("select DRAWING_ID, FILE_TYPE, FILE_PATH from EST_CAD_DRAWINGS "
                  "where upper(FILE_TYPE) in ('DXF','DWG') order by DRAWING_ID limit 40")
    if not rows:
        pytest.skip("DXF·DWG 도면 0건")
    feat0 = int(conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"])
    unknown = known = 0
    touched: list[int] = []
    try:
        for r in rows:
            got = pipeline.store_dxf_features(int(r["drawing_id"]), allow_unconfirmed=True)
            if not got.get("written"):
                continue
            touched.append(int(r["drawing_id"]))
            if got["unit_assumed"]:
                unknown += 1
            else:
                known += 1
            if unknown and known:
                break
        assert unknown, "단위 미상 도면이 하나도 없다 — 표본을 확인한다"
        marked = conn.q("select UOM, SOURCE_DESC from EST_CAD_FEATURES "
                        "where SOURCE_DESC like %s", (assumed.UNIT_TAG_LIKE,))
        assert marked, "단위 미상 도면인데 표지가 붙은 Feature 가 없다"
        for m in marked:
            assert "25.4" in m["source_desc"], f"배율 오차 경고가 없다: {m['source_desc']}"
            assert assumed.declaration() in m["source_desc"]
            assert m["uom"] != "도면단위", "표지는 붙었는데 단위가 안 바뀌었다"
        # 표지 없는 행에 `도면단위` 가 남아 있어도 되지만, **mm 로 바뀐 채 표지가 없으면** 결함이다.
        silent = conn.q("select DRAWING_ID, FEATURE_TYPE, UOM, SOURCE_DESC "
                        "from EST_CAD_FEATURES where UOM like 'mm%%' "
                        "and SOURCE_DESC not like %s and FEATURE_TYPE <> '두께'",
                        (assumed.UNIT_TAG_LIKE,))
        for s in silent:
            # 두께는 원래 mm 로 읽힌다(표제란 표기). 그 밖에 mm 인데 표지가 없으면
            # `$INSUNITS` 가 실제로 mm 였던 도면이어야 한다.
            assert "DXF 실측" in s["source_desc"], s
    finally:
        for did in touched:
            conn.x("delete from EST_CAD_FEATURES where DRAWING_ID = %s", (did,))
    assert int(conn.q1("select count(*) as n from EST_CAD_FEATURES")["n"]) == feat0
