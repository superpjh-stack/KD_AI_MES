"""QA1 ③ 오류 계약 7종 — contracts/api-contract.md §4 (goal.md §2.5 · G-30).

| 상황 | HTTP | 문구 |
|---|---|---|
| 필수값 누락 / 코드 중복 / 상·하한 역전 / **검사 합격 아닌 LOT 출하** / **승인 전 견적 확정** | 422 | 입력값을 확인해 주세요 |
| unauthenticated | 401 | 로그인이 필요합니다 |
| 권한 없음 / 승인 권한 없는 추천값 반영 | 403 | 접근 권한이 없습니다 |
| db_down | 503 | 서비스 일시 중단 |
| API 키 없음 | 501 | LLM 미구성 |
| Autodesk·YOLOv8 미확보 | 501 | CAD Parsing 미구성 (D-05) |
| 처리 중 오류 | 500 | 처리 중 오류가 발생했습니다 |

데이터 의존 금지 (§10-4)
  · **0건 경로**(없는 LOT·없는 견적)와 **N건 경로**(실제로 불합격인 LOT)를 **둘 다** 단언한다.
  · `skip` 하지 않는다. N건 경로가 필요하면 **이 파일이 전제를 만들고 끝나면 지운다**.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                   # noqa: E402
from conftest import csrf_post                                 # noqa: E402
from kyungdong.agent import llm, service as agent_service      # noqa: E402
from kyungdong.app.main import app                             # noqa: E402
from kyungdong.app.routers import bas as bas_router            # noqa: E402
from kyungdong.app.util import clock, http                     # noqa: E402
from kyungdong.cad import pipeline as cad_pipeline, provider as cad_provider  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

# ── CSRF (D-102) ────────────────────────────────────────────────────────
# 실제 브라우저는 화면에서 받은 토큰을 폼에 실어 보낸다. 테스트도 같아야 한다.
# 아래 라우트는 **화면에 쓰기 폼이 아직 없다**(버튼이 disabled 다) — 토큰을 찍는 템플릿이
# 없으므로 세션 토큰을 `/login` 에서 받는다. 토큰은 경로가 아니라 세션에 매인다(util/csrf.py `_bind`).
FORMLESS = ("/est/011/review", "/est/012/confirm", "/est/013/confirm", "/api/agent/")


def post(path: str, data: dict | None = None, **kw):
    page = "/login" if path.startswith(FORMLESS) else None
    return csrf_post(client, path, data, page=page, **kw)


MSG = {c.status: c.message for c in http.CASES if c.status != 501}
MSG_LLM = http.BY_KEY["llm_unconfigured"].message
MSG_CAD = http.BY_KEY["cad_unconfigured"].message

# 이 파일이 만드는 전제 — 접두어로 격리하고 끝나면 지운다.
PJ_NO = "PJT-QA1ERR-001"
LOT_NO = "PLOT-QA1ERR-001"
QSTD = "QSTD-QA1ERR-1"
CUSTOMER, ITEM = "CUST-QA1ERR", "PG10"
MARK = "tests/test_qa1_errors.py 임시 — 끝나면 지운다"


# ── 계약 자체 ────────────────────────────────────────────────────────────
def test_오류_계약이_7종이고_문구가_한곳에만_있다():
    assert len(http.CASES) == 7, f"오류 계약 {len(http.CASES)}종 ≠ 7"
    assert sorted(c.status for c in http.CASES) == [401, 403, 422, 500, 501, 501, 503]
    with pytest.raises(KeyError):
        http.fail("몰래만든키")                     # 계약 밖 상태를 새로 만들 수 없다


def test_공통_팝업이_7종_문구를_전부_들고_있다():
    """TD3 layout_rules '오류·알림 = 공통 팝업'. 문구가 화면에 실제로 있는지 본다."""
    page = client.get("/popup").text
    missing = [c.message for c in http.CASES if c.message not in page]
    assert not missing, f"/popup 에 없는 오류 문구: {missing}"


# ── 422 ① 0건 경로 — 없는 대상 ──────────────────────────────────────────
@pytest.mark.parametrize("path,form", [
    ("/shp/016", {"lot_trace_id": "999999"}),                 # 없는 제품 LOT
    ("/est/012/confirm", {"quote_id": "999999"}),             # 없는 견적
    ("/est/013/confirm", {"bom_id": "999999"}),               # 없는 BOM
    ("/prc/021", {"work_order_id": "999999", "process_code": "P10",
                  "start_dt": "2026-09-01 08:00", "good_qty": "1"}),
])
def test_422_0건경로_없는_대상은_422다(path, form):
    r = post(path, form, params={"as": "SYSADMIN"})
    assert r.status_code == 422, f"{path} → {r.status_code}"
    assert MSG[422] in r.text


def test_422_필수값_누락은_422다():
    r = post("/bas/030", {"qstd_code": ""}, params={"as": "SYSADMIN"})
    assert r.status_code == 422 and MSG[422] in r.text


def test_422_코드_위반은_422다():
    """D-32 — DB 가 막지 않는 코드성 FK 29건은 `util.codes` 가 막는다."""
    r = post("/prc/021", {"work_order_id": "999999", "process_code": "QA1-없는공정",
                          "start_dt": "2026-09-01 08:00", "good_qty": "1"},
             params={"as": "PRODUCTION"})
    assert r.status_code == 422, f"없는 공정 코드로 실적이 들어갔다 → {r.status_code}"
    assert MSG[422] in r.text


def test_422_외주공정_실적과_자동수집_사칭은_422다():
    """D-41 · D-06 — 없는 수집을 한 척하면 422."""
    base = {"work_order_id": "999999", "start_dt": "2026-09-01 08:00", "good_qty": "1"}
    out = post("/prc/021", {**base, "process_code": "P20"}, params={"as": "PRODUCTION"})
    auto = post("/prc/021", {**base, "process_code": "P30", "collect_method": "자동(PLC)"},
                params={"as": "PRODUCTION"})
    assert (out.status_code, auto.status_code) == (422, 422)


# ── 422 ② N건 경로 — **실제로 불합격인 LOT** 을 만들어 출하해 본다 ───────
@pytest.fixture(scope="module")
def failed_lot():
    """검사 **불합격** 제품 LOT 1건을 세우고, 끝나면 되돌린다.

    개발2 의 `tests/test_dev2_chain.py` 와 같은 방식이다 — 남의 표를 영구히 건드리지 않는다.
    """
    _cleanup()
    a = clock.anchor()
    for group, value, name in (("고객사", CUSTOMER, "QA1 테스트 고객사"), ("품목", ITEM, "반응기")):
        conn.x("insert into BAS_COMMON_CODES (CODE_GROUP, CODE_VALUE, CODE_NAME, SORT_ORDER, "
               "USE_YN, ATTR1, CREATED_DT) values (%s,%s,%s,90,'Y',%s, now()) "
               "on conflict (CODE_GROUP, CODE_VALUE) do nothing",
               (group, value, name, MARK))
    conn.x("insert into BAS_QUALITY_STANDARDS (QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, "
           "INSPECT_ITEM, STANDARD_SPEC, UOM, USE_YN, APPLY_FROM, CREATED_DT) "
           "values (%s,%s,%s,%s,%s,%s,'Y',%s, now())",
           (QSTD, ITEM, "수압시험", "압력", "ASME / KS", "bar", a.date()))
    conn.x("insert into EST_PROJECTS (PROJECT_NO, CUSTOMER_CODE, PRODUCT_GROUP, PROJECT_NAME, "
           "ORDER_CONFIRM_DT, DUE_DT, PROJECT_STATUS, CREATED_DT) "
           "values (%s,%s,%s,%s,%s,%s,%s, now())",
           (PJ_NO, CUSTOMER, ITEM, "QA1 오류계약 확인용", a - timedelta(hours=100),
            (a + timedelta(days=5)).date(), "생산"))
    pid = conn.q1("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = %s", (PJ_NO,))["project_id"]
    conn.x("insert into SHP_LOT_TRACES (PRODUCT_LOT_NO, PROJECT_ID, CURRENT_PROCESS, "
           "TRACE_STATUS, MAPPING_OK_YN, CREATED_DT) values (%s,%s,%s,%s,%s, now())",
           (LOT_NO, pid, "P90", "진행", "Y"))
    lot_id = int(conn.q1("select LOT_TRACE_ID from SHP_LOT_TRACES where PRODUCT_LOT_NO = %s",
                         (LOT_NO,))["lot_trace_id"])
    qstd_id = int(conn.q1("select QSTD_ID from BAS_QUALITY_STANDARDS where QSTD_CODE = %s",
                          (QSTD,))["qstd_id"])
    conn.x("insert into SHP_INSPECTIONS (LOT_TRACE_ID, QSTD_ID, INSPECT_ITEM, MEASURED_VALUE, "
           "UOM, JUDGE_RESULT, INSPECT_DT, REJECT_REASON, CREATED_DT) "
           "values (%s,%s,%s,%s,%s,%s,%s,%s, now())",
           (lot_id, qstd_id, "압력", 3, "bar", "불합격", a, "QA1 오류계약 확인용 불합격"))
    conn.x("insert into PRC_PROCESS_HISTORIES (LOT_TRACE_ID, PROCESS_CODE, PROCESS_SEQ, IN_DT, "
           "OUT_DT, DWELL_HOUR, HIST_STATUS, CREATED_DT) values (%s,%s,%s,%s,%s,%s,%s, now())",
           (lot_id, "P90", 9, a - timedelta(hours=4), a, 4, "정상"))

    yield {"lot_id": lot_id, "lot_no": LOT_NO, "project_no": PJ_NO, "project_id": int(pid)}

    _cleanup()
    assert conn.q1("select 1 as x from EST_PROJECTS where PROJECT_NO = %s", (PJ_NO,)) is None, \
        "픽스처가 남긴 행이 있다"
    assert conn.q1("select 1 as x from BAS_COMMON_CODES where ATTR1 = %s", (MARK,)) is None, \
        "픽스처가 넣은 공통코드가 남아 있다"


def _cleanup() -> None:
    row = conn.q1("select PROJECT_ID from EST_PROJECTS where PROJECT_NO = %s", (PJ_NO,))
    if row:
        pid = row["project_id"]
        conn.x("delete from SHP_SHIPMENT_ITEMS where SHIPMENT_ID in "
               "(select SHIPMENT_ID from SHP_SHIPMENTS where PROJECT_ID = %s)", (pid,))
        conn.x("delete from SHP_SHIPMENTS where PROJECT_ID = %s", (pid,))
        conn.x("delete from SHP_INSPECTIONS where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = %s)", (pid,))
        conn.x("delete from PRC_PROCESS_HISTORIES where LOT_TRACE_ID in "
               "(select LOT_TRACE_ID from SHP_LOT_TRACES where PROJECT_ID = %s)", (pid,))
        conn.x("delete from SHP_LOT_TRACES where PROJECT_ID = %s", (pid,))
        conn.x("delete from EST_PROJECTS where PROJECT_ID = %s", (pid,))
    conn.x("delete from BAS_QUALITY_STANDARDS where QSTD_CODE = %s", (QSTD,))
    # **내가 넣은 행만** 지운다 — `ATTR1` 표식으로 가린다. 남이 넣어 둔 코드를 지우면 안 된다.
    conn.x("delete from BAS_COMMON_CODES where CODE_GROUP = any(%s) and CODE_VALUE = any(%s) "
           "and ATTR1 = %s", (["고객사", "품목"], [CUSTOMER, ITEM], MARK))


def test_422_N건경로_불합격_LOT_은_출하할_수_없다(failed_lot):
    """api-contract §6 — `SHP_SHIPMENTS` 는 **검사 합격 LOT 만**. 아니면 422."""
    before = int(conn.q1("select count(*) as n from SHP_SHIPMENTS")["n"])
    r = post("/shp/016", {"lot_trace_id": str(failed_lot["lot_id"])},
             params={"as": "PRODUCTION"})
    assert r.status_code == 422, f"불합격 LOT 이 출하됐다 → {r.status_code}"
    assert MSG[422] in r.text
    assert "검사 합격 LOT 만" in r.text, "422 는 났는데 사유가 검사 판정이 아니다"
    after = int(conn.q1("select count(*) as n from SHP_SHIPMENTS")["n"])
    assert after == before, "422 를 내면서 출하 행을 만들었다"


def test_불합격_LOT_이_출하화면에_출하가능으로_보이지_않는다(failed_lot):
    """TD3 standard_note 4 — 승인·판정 전에는 확정 상태로 표기하지 않는다."""
    page = client.get("/shp/018", params={"as": "SYSADMIN", "lot": failed_lot["lot_no"]}).text
    assert failed_lot["lot_no"] in page, "만든 불합격 LOT 이 018 검사결과관리에 안 보인다"
    assert "불합격" in page


# ── 401 ─────────────────────────────────────────────────────────────────
def test_401_검토자를_확인할_수_없으면_401이다(monkeypatch):
    """`EST_OBJECT_REVIEWS.REVIEWER_ID` 는 필수다 — 미인증이면 401 이고 200 이 아니다.

    지금은 개발용 보조(D-40)가 역할로 사용자를 찾아 준다. 그 보조를 끄면 미인증 상태가 된다.
    """
    monkeypatch.setattr(agent_service, "resolve_user", lambda *_a, **_k: None)
    r = post("/est/011/review", {"object_id": "999999", "result": "승인"},
             params={"as": "EXEC"})
    assert r.status_code == 401, f"미인증 검토 요청이 {r.status_code} 다"
    assert MSG[401] in r.text


def test_401_계약_문구가_한곳에서_온다():
    assert http.fail("unauthenticated").status_code == 401
    assert http.BY_KEY["unauthenticated"].message == "로그인이 필요합니다"


# ── 403 ─────────────────────────────────────────────────────────────────
def test_403_권한없는_화면은_403이다():
    r = client.get("/est/012", params={"as": "OPERATOR"})
    assert r.status_code == 403 and MSG[403] in r.text


def test_403_승인권한_없는_추천값_반영은_403이다():
    """G-24 — 승인 권한 없는 역할이 추천을 반영하려 하면 403."""
    r = post("/api/agent/recommend/999999/adopt", {"decision": "승인"},
             params={"as": "OPERATOR"})
    assert r.status_code == 403


def test_403_승인권한_없는_역할은_견적을_확정할_수_없다():
    r = post("/est/012/confirm", {"quote_id": "999999"}, params={"as": "QUALITY"})
    assert r.status_code == 403 and MSG[403] in r.text


# ── 503 ─────────────────────────────────────────────────────────────────
def test_503_DB가_죽으면_빈_화면이_아니라_503이다(monkeypatch):
    """G-30 — '없는 것' 과 '못 읽은 것' 은 다르다. 빈 그리드 200 은 결함이다."""
    def boom(*_a, **_k):
        raise psycopg.OperationalError("QA1 강제 차단")

    monkeypatch.setattr(psycopg, "connect", boom)
    r = client.get("/bas/032", params={"as": "SYSADMIN"})
    assert r.status_code == 503, f"DB 가 죽었는데 {r.status_code} 가 나왔다"
    assert MSG[503] in r.text


def test_503_이_아닌_정상경로는_200이다():
    """위 테스트가 monkeypatch 를 되돌렸는지까지 확인한다."""
    assert client.get("/bas/032", params={"as": "SYSADMIN"}).status_code == 200


# ── 501 × 2 ─────────────────────────────────────────────────────────────
def test_501_LLM_미구성은_조용히_폴백하지_않는다():
    """D-08 — 키가 없으면 문장을 지어내지 않고 501."""
    assert llm.state().configured is False, "LLM 이 구성되어 있다 — 이 회전의 전제가 아니다"
    with pytest.raises(Exception) as e:
        llm.require()
    assert e.value.status_code == 501 and e.value.detail["message"] == MSG_LLM


def test_501_CAD_미구성은_합성_Feature_를_내지_않는다():
    """D-05 — Autodesk·YOLOv8 미확보. 빈 리스트도 0건 인식과 구분이 안 되므로 501 이다."""
    avail = cad_provider.availability()
    assert len(avail) == 2 and not avail[1].configured, "Vision 이 구성되어 있다 — D-05 판정을 다시 잰다"
    # Parsing 은 dwg2dxf 파서로 구성될 수 있다(D-235) — 그때 없는 파일은 **422** 다. 501(미구성)과 섞지 않는다.
    for det, av in zip((cad_provider.parsing_detector(), cad_provider.vision_detector()), avail):
        with pytest.raises(Exception) as e:
            det.detect("QA1-없는파일.dwg")
        if av.configured:
            assert e.value.status_code == 422, "구성된 파서가 없는 파일에 501 을 내면 원인을 못 찾는다"
            continue
        assert e.value.status_code == 501
        assert MSG_CAD.split(" (")[0] in e.value.detail["message"]


def test_없는_도면은_422고_501이_아니다():
    """501(미구성)과 422(없는 대상)를 구분해서 단언한다 — 뭉개면 원인을 못 찾는다."""
    with pytest.raises(Exception) as e:
        cad_pipeline.analyze(999999)
    assert e.value.status_code == 422, "없는 도면은 422 여야 한다"


def test_501_두_종류가_서로_다른_문구를_쓴다():
    assert MSG_LLM != MSG_CAD
    assert {c.status for c in http.CASES if c.status == 501} == {501}
    assert len([c for c in http.CASES if c.status == 501]) == 2


# ── 500 ─────────────────────────────────────────────────────────────────
def test_500_예외는_공통_오류화면으로_나가고_내용을_흘리지_않는다(monkeypatch):
    """§10-12 — 스택트레이스·예외 문구를 사용자에게 노출하지 않는다."""
    def boom(*_a, **_k):
        raise ValueError("QA1-비밀문자열-절대노출금지")

    monkeypatch.setattr(bas_router, "tables_panel", boom)
    r = client.get("/bas/032", params={"as": "SYSADMIN"})
    assert r.status_code == 500, f"예외가 났는데 {r.status_code} 다"
    assert MSG[500] in r.text
    assert "QA1-비밀문자열-절대노출금지" not in r.text, "예외 문구가 화면에 샜다"
    assert "Traceback" not in r.text


def test_500_계약된_internal_은_500이다():
    assert http.fail("internal").status_code == 500
