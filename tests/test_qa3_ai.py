"""QA3 — G-14~G-25 AI 게이트 불변식.

판정은 `tools/check_ai.py` 가 한다. 여기서는 **회전이 지나도 흔들리면 안 되는 것**만 못박는다.

규칙
  · **`skip` 금지**(§10-4 · D-62). 데이터가 없으면 `0건 경로`를 그대로 단언하고,
    N건 경로는 이 테스트 안에서 만들어 단언한 뒤 되돌린다.
  · **차단 표지 테스트**: 지금은 `차단`이 정답이다. 나중에 해소되면 이 테스트가 **실패해서**
    리포트를 갱신하게 만든다 — 조용히 통과시키지 않는다(`tests/test_qa1_ui.py` 선례).
  · 성능 수치를 만들지 않는다. 합성 라벨·합성 예측으로 게이트를 넘기지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT / "tools"))

import conn                                                    # noqa: E402
import check_ai                                                # noqa: E402
from conftest import csrf_post                                 # noqa: E402
from kyungdong.agent import llm, retrieval, service            # noqa: E402
from kyungdong.app import rbac                                 # noqa: E402
from kyungdong.app.main import app                             # noqa: E402
from kyungdong.app.settings import settings                    # noqa: E402
from kyungdong.cad import pipeline as cadpipe                   # noqa: E402
from kyungdong.cad import provider as cadprov                   # noqa: E402
from kyungdong.ml import datasets as mldata                     # noqa: E402
from kyungdong.ml import registry as mlreg                      # noqa: E402

GOLDSET = json.loads((ROOT / "work" / "rag_goldset.json").read_text())
LABELSET = json.loads((ROOT / "work" / "cad_labelset.json").read_text())


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def n1(sql: str, params=None) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


# ── G-14 CAD 객체 인식 ───────────────────────────────────────────────────
def test_g14_labelset_is_empty_and_says_why():
    """정답 박스가 0건이라 G-14 는 `차단`이다. **합성 박스를 넣으면 이 테스트가 실패한다.**"""
    assert LABELSET["labels"] == [], (
        "정답 박스가 생겼다 — G-14 를 실제로 잴 수 있다. "
        "outputs/qa3-AI비기능보안.md 의 `차단` 을 실측으로 바꿔라")
    assert LABELSET["predictions"] == []
    assert LABELSET["_meta"]["판정"] == "차단"
    assert LABELSET["evaluator_selftest"]["gate_input"] is False


def test_g14_evaluator_moves_with_threshold():
    """되돌림 시험 — 임계를 바꾸면 혼동행렬이 움직여야 한다(§10-16)."""
    st = LABELSET["evaluator_selftest"]
    seen = set()
    for t in (0.2, 0.5, 0.9):
        r = check_ai.match(st["labels"], st["predictions"], t)
        exp = st["expected"][f"iou_{t}"]
        assert (r["tp"], r["fp"], r["fn"]) == (exp["tp"], exp["fp"], exp["fn"]), \
            f"IoU {t} 혼동행렬이 기대와 다르다: {r}"
        seen.add((r["tp"], r["fp"], r["fn"]))
    assert len(seen) == 3, "임계를 바꿔도 수치가 같다 — 평가기가 임계를 읽지 않는다"


def test_g14_detectors_are_unconfigured_and_raise_501():
    """0건 경로: 공급자 미구성. **빈 리스트를 돌려주면 '0건 인식'과 구분이 안 된다** → 501 이어야 한다."""
    avail = cadprov.availability()
    assert len(avail) == 2
    assert all(not a.configured for a in avail), \
        "CAD 공급자가 구성됐다 — G-14 를 실제로 잴 수 있다. 리포트를 갱신하라"
    for det in (cadprov.parsing_detector(), cadprov.vision_detector()):
        with pytest.raises(Exception) as e:
            det.detect("(없는 파일)")
        assert getattr(e.value, "status_code", None) == 501


# ── G-15~G-18 Label·학습 전제 ────────────────────────────────────────────
def test_g15_g18_denominators_are_zero_with_reasons():
    ready = mlreg.readiness()
    assert ready["models"] == 0 and ready["runs"] == 0, \
        "학습이 실행됐다 — G-15~G-18 을 실측으로 다시 재라"
    assert ready["labeled_items"] == 0, "Label 이 생겼다 (D-04 해소) — 리포트를 갱신하라"
    assert n1("select count(*) as n from EST_ML_PREDICTIONS") == 0
    assert n1("select count(*) as n from EST_SHAP_FACTORS") == 0
    assert len(ready["blockers"]) >= 4


def test_g17_tolerance_comes_from_env_not_code():
    """납기 허용 오차는 `.env` 가설값이다(D-12). 코드 상수로 박히면 결함이다."""
    h = settings().h("DUE_DATE_TOLERANCE_DAYS")
    assert h.decision == "D-12"
    assert h.badge.startswith("가설")
    src = (ROOT / "src").rglob("*.py")
    hard = [p.relative_to(ROOT).as_posix() for p in src
            if "DUE_DATE_TOLERANCE" in p.read_text() and p.name != "settings.py"]
    assert hard == [], f"허용 오차가 settings 밖에 박혀 있다: {hard}"


def test_g18_spearman_needs_two_samples():
    """표본 2 미만이면 ρ 는 **없다**. 0.0 을 돌려주면 없는 것을 있는 것으로 만든다."""
    assert check_ai.spearman([], []) is None
    assert check_ai.spearman([1.0], [1.0]) is None
    rho = check_ai.spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert rho is not None and abs(rho - 1.0) < 1e-9
    rho2 = check_ai.spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert rho2 is not None and abs(rho2 + 1.0) < 1e-9


def test_g15_mape_zero_sample_is_none_not_zero():
    m = check_ai.mape_mae([])
    assert m["n"] == 0 and m["mape"] is None and m["mae"] is None
    m2 = check_ai.mape_mae([(105.0, 100.0), (95.0, 100.0)])
    assert m2["n"] == 2 and abs(m2["mape"] - 5.0) < 1e-9 and abs(m2["mae"] - 5.0) < 1e-9


# ── G-19 5단계 ───────────────────────────────────────────────────────────
def test_g19_stage1_blocks_and_feature_stays_zero():
    """0건 경로(도면 0)와 N건 경로(도면 1건)를 **둘 다** 단언한다. skip 하지 않는다."""
    before = n1("select count(*) as n from EST_CAD_DRAWINGS")
    stages = cadpipe.stage_status()
    assert len(stages) == 5
    assert stages[0]["blocked"] is True, "1단계 인식이 열렸다 — G-19 를 실측으로 다시 재라"

    row = conn.q1(
        "insert into EST_CAD_DRAWINGS (DRAWING_NO, FILE_TYPE, FILE_PATH, FILE_SIZE, "
        " ANALYSIS_STATUS, DUPLICATE_YN, CREATED_DT) "
        "values ('QA3-TEST-G19','dwg','(테스트 probe)',0,'대기','N', now()) returning DRAWING_ID")
    did = int(row["drawing_id"])
    try:
        with pytest.raises(Exception) as e:
            cadpipe.analyze(did)
        assert getattr(e.value, "status_code", None) == 501, \
            "도면이 있어도 인식은 501 이어야 한다 (조용한 합성 Feature 금지 — D-05)"
        feat = cadpipe.build_features(did)
        assert feat["confirmed_objects"] == 0 and feat["created"] == 0
        assert len(feat["blocked"]) == 5, "차단 Feature 5종이 유지돼야 한다"
    finally:
        conn.x("delete from EST_CAD_DRAWINGS where DRAWING_ID = %s", (did,))
    assert n1("select count(*) as n from EST_CAD_DRAWINGS") == before


# ── G-20~G-23 RAG ────────────────────────────────────────────────────────
def test_g20_agent_scope_isolation():
    """입고 Agent 가 클레임 매뉴얼을, 출하 Agent 가 입고 SOP 를 보면 폐쇄형 접근 통제 위반이다."""
    for s in GOLDSET["scope_isolation"]:
        ev, _ = retrieval.search(s["question"], agent_type=s["agent_type"])
        leaked = [e.doc_name for e in ev if e.doc_name == s["forbidden_doc"]]
        assert leaked == [], f"{s['id']}: {s['agent_type']} Agent 가 {s['forbidden_doc']} 를 반환했다"


def test_g20_no_external_network_in_agent_package():
    bad = check_ai._closed_loop_static()
    assert bad == [], f"폐쇄형 위반 — 외부 통신 흔적 {bad}"


def test_g20_every_question_is_logged(monkeypatch):
    """질의 100% 기록. 근거 0건 갈래와 근거 있는 갈래를 **둘 다** 센다."""
    maxid = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    uid = service.resolve_user("SYSADMIN")
    assert uid is not None, "SYSADMIN 계정이 없다 — `make db-seed`"
    asked = 0
    try:
        for q in ("환율 적용 기준은 무엇인가",              # 근거 0건 갈래
                  "입고 자재에 바코드를 발행하는가"):        # 근거 있는 갈래
            try:
                service.ask(q, agent_type="통합", user_id=uid, role_code="SYSADMIN")
            except Exception as e:                          # 501 LLM 미구성도 기록은 남는다
                assert getattr(e, "status_code", None) == 501
            asked += 1
        added = n1("select count(*) as n from AGT_QUERY_LOGS where QUERY_ID > %s", (maxid,))
        assert added == asked, f"질의 {asked} 건 중 {added} 건만 기록됐다 — 100% 기록 위반"
    finally:
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (maxid,))


def test_g22_no_evidence_never_calls_llm(monkeypatch):
    """근거 0건이면 **LLM 을 부르지 않는다**. LLM 이 구성된 것처럼 세워 놓고 감시한다."""
    calls: list[str] = []

    def spy(instructions, question, context):
        calls.append(question)
        return "spy"

    monkeypatch.setattr(llm, "state", lambda: llm.LlmState(True, "spy", "spy", ""))
    monkeypatch.setattr(llm, "complete", spy)
    maxid = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    uid = service.resolve_user("SYSADMIN")
    try:
        none_items = [i for i in GOLDSET["items"] if i["expect"] == "none"]
        assert len(none_items) >= 5, "근거 없음형이 5건 미만이다"
        for it in none_items:
            a = service.ask(it["question"], agent_type=it["agent_type"],
                            user_id=uid, role_code="SYSADMIN")
            assert a.text == "검토 필요 — 근거 부족"
            assert a.grounded is False and a.handover
            assert a.sources == []
        assert calls == [], f"근거 0건인데 LLM 이 호출됐다: {calls}"
        # N건 경로 — 임계를 넘는 질의에서는 실제로 호출돼야 한다
        a = service.ask("설치 후 클레임은 자재 LOT 까지 역추적하는가", agent_type="출하",
                        user_id=uid, role_code="SYSADMIN")
        assert calls, "근거가 충분한데도 LLM 이 호출되지 않았다 — 정상 경로가 죽었다"
        assert a.grounded is True and a.sources
    finally:
        conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (maxid,))


def test_g21_citations_come_only_from_retrieved_docs():
    """지어낸 출처가 없다 — 응답 출처는 실제 검색된 문서명의 부분집합이다."""
    for it in GOLDSET["items"]:
        if it["expect"] != "evidence":
            continue
        ev, _ = retrieval.search(it["question"], agent_type=it["agent_type"])
        assert ev, f"{it['id']}: 근거가 있어야 하는데 0건이다"
        assert ev[0].doc_name == it["expect_doc"], \
            f"{it['id']}: 최상위 근거가 {ev[0].doc_name} (기대 {it['expect_doc']})"
        text = " ".join(e.chunk_text for e in ev)
        missing = [k for k in it["expect_keywords"] if k not in text]
        assert missing == [], f"{it['id']}: 근거 본문에 핵심어 {missing} 가 없다"


def test_g23_threshold_actually_moves_the_verdict(monkeypatch):
    """되돌림 시험 — 임계값을 바꾸면 '근거 부족' 건수가 움직여야 한다(§10-16)."""
    items = GOLDSET["items"]
    counts = check_ai._reversal_rag(items)
    assert len(set(counts.values())) > 1, \
        f"임계를 바꿔도 판정이 같다 — 검사기가 정본 함수를 부르지 않는다: {counts}"
    assert counts["0.0"] < counts["0.99"]


# ── G-24 HITL ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,form,area", [
    ("/est/011/review", {"object_id": "999999", "result": "승인"}, "수주견적AI관리"),
    ("/est/012/confirm", {"quote_id": "999999"}, "수주견적AI관리"),
    ("/est/013/confirm", {"bom_id": "999999"}, "수주견적AI관리"),
    ("/shp/016/approve", {"shipment_id": "999999"}, "출하물류관리"),
])
def test_g24_confirm_requires_approval(client, path, form, area):
    """승인 권한 없는 역할은 **403**. 승인 권한 있는 역할은 403 이 아니다(D-84)."""
    denied = approved = 0
    for role in sorted(rbac.roles()):
        # 실제 브라우저처럼 화면에서 받은 CSRF 토큰을 폼에 싣는다 (D-102).
        # `/est/*/(review|confirm)` 은 화면 버튼이 아직 disabled 라 폼을 찍지 않는다 —
        # 토큰은 경로가 아니라 세션에 매이므로(util/csrf.py `_bind`) `/login` 에서 받는다.
        r = csrf_post(client, path, form, page="/login",
                      headers={"x-kyungdong-role": role}, follow_redirects=False)
        if rbac.can_approve(role, area):
            approved += 1
            assert r.status_code != 403, \
                f"{path}: 승인 권한이 있는 {role} 이 403 을 받았다 (D-84 재발)"
        else:
            denied += 1
            assert r.status_code == 403, f"{path} as {role}: {r.status_code} (기대 403)"
    assert denied > 0 and approved > 0, "0건 경로·N건 경로 중 하나가 비었다"


def test_g24_no_confirmed_row_without_approver():
    assert n1("select count(*) as n from EST_QUOTATIONS "
              "where QUOTE_STATUS = '승인' and APPROVER_ID is null") == 0
    assert n1("select count(*) as n from SHP_SHIPMENTS "
              "where SHIP_DT is not null and APPROVER_ID is null") == 0


def test_g24_confirm_yn_has_exactly_one_write_path():
    """`EST_CAD_OBJECTS.CONFIRM_YN` 을 바꾸는 코드는 `pipeline.review_object` 하나뿐이다."""
    hits = []
    for p in (ROOT / "src").rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if check_ai.WRITE_SQL.search(line):
                hits.append((p.relative_to(ROOT).as_posix(), i))
    objs = [h for h in hits if "pipeline.py" in h[0]]
    assert len(objs) == 1, f"EST_CAD_OBJECTS 쓰기 경로가 {objs} 다 — 하나여야 한다"


def test_g24_inspections_have_no_write_path_yet():
    """**차단 표지** — `SHP_INSPECTIONS` 에 앱 쓰기 경로가 아직 0곳이다.

    '승인 없이 바뀌는 경로 0' 이 통제 때문이 아니라 **구현 부재** 때문임을 못박는다.
    검사 합격 판정 화면(018)이 붙으면 이 테스트가 실패한다 → 그때 G-24 를 다시 재라.
    """
    n = 0
    for p in (ROOT / "src").rglob("*.py"):
        for line in p.read_text().splitlines():
            if __import__("re").search(r"(insert\s+into|update)\s+SHP_INSPECTIONS\b",
                                       line, __import__("re").I):
                n += 1
    assert n == 0, ("SHP_INSPECTIONS 쓰기 경로가 생겼다 — 검사 합격 판정이 "
                    "품질 담당 승인 아래 있는지 G-24 를 다시 재라")


# ── G-25 MLOps ───────────────────────────────────────────────────────────
def test_g25_rollback_returns_to_previous_version():
    """**해소 실측** — 배포 상태를 되돌리는 코드가 0곳이었다. 표지를 뒤집었다.

    **코드가 있다** 로 끝내지 않는다. 두 버전을 넣고 정본 함수를 직접 불러 v1.0 → v0.9 복귀를
    잰다. 학습 미실시로 `EST_ML_MODELS` 가 0행이라 표본은 여기서 만들 수밖에 없고,
    **끝나고 전부 지운다**(G-11 런타임 전용 표 0건).

    이 표본은 **성능 수치가 아니다** — `METRIC_JSON` 을 비워 둔다. 이것으로 G-25 가 PASS 가
    되지는 않는다. 남은 4개(모델 버전·성능·상태 / 학습 이력 / 예측 기록 / Train·Val·Test 분리)는
    학습 미실시로 **분모 0** 이고 그것은 `tools/check_ai.py` 가 `차단` 으로 적는다.
    """
    import re as _re
    dep = _re.compile(r"(update\s+EST_ML_MODELS|set\s+DEPLOY_STATUS|"
                      r"def\s+\w*(rollback|deploy|promote)\w*\s*\()", _re.I)
    hits = [f"{p.relative_to(ROOT).as_posix()}"
            for p in (ROOT / "src").rglob("*.py")
            for line in p.read_text().splitlines() if dep.search(line)]
    assert hits, "롤백·배포 전환 경로가 사라졌다 — G-25 가 회전 6 상태로 되돌아갔다"

    name = "QA3롤백회귀_견적예측"
    mark = int(conn.q1("select coalesce(max(MODEL_ID),0) as n from EST_ML_MODELS")["n"])
    try:
        for ver, status_, ago in (("v0.9", mlreg.VALIDATED, "1 day"),
                                  ("v1.0", mlreg.DEPLOYED, "0 day")):
            conn.x("insert into EST_ML_MODELS (MODEL_NAME, MODEL_TYPE, MODEL_VERSION, "
                   "DEPLOY_STATUS, DEPLOYED_DT, CREATED_DT) "
                   f"values (%s, %s, %s, %s, now() - interval '{ago}', now())",
                   (name, "회귀", ver, status_))
        assert mlreg.deployed_model(name)["model_version"] == "v1.0"
        assert mlreg.previous_version(name)["model_version"] == "v0.9"

        out = mlreg.rollback(name)
        assert out["rolled_back_from"] == "v1.0" and out["rolled_back_to"] == "v0.9"
        assert mlreg.deployed_model(name)["model_version"] == "v0.9", "되돌아가지 않았다"
        # 동시 배포 금지 — 되돌린 뒤 '배포' 는 하나뿐이고 이력은 지워지지 않는다.
        rows = conn.q("select MODEL_VERSION, DEPLOY_STATUS from EST_ML_MODELS "
                      "where MODEL_NAME = %s order by MODEL_ID", (name,))
        assert len(rows) == 2, "롤백이 이력을 지웠다 — 되돌린 사실이 남지 않는다"
        assert [r["deploy_status"] for r in rows] == [mlreg.DEPLOYED, mlreg.VALIDATED]

        # 0건 경로 — 되돌릴 곳이 없으면 **422**. 없는데 성공한 척하지 않는다 (§2.5).
        with pytest.raises(Exception) as e:
            mlreg.rollback("존재하지않는모델_QA3")
        assert getattr(e.value, "status_code", None) == 422
    finally:
        conn.x("delete from EST_ML_MODELS where MODEL_ID > %s", (mark,))
    assert int(conn.q1("select count(*) as n from EST_ML_MODELS")["n"]) == 0, \
        "실측용 모델이 남았다 — G-11(런타임 전용 표 0건)을 오염시킨다"


def test_g25_splits_absent_because_ratio_not_in_canon():
    """Train/Val/Test 분할이 0건인 것은 **비율이 정본에 없어서**다. 임의 비율을 넣으면 실패한다."""
    assert mldata.SPLIT_TYPES == ("Train", "Validation", "Test")
    assert mldata.splits() == [], \
        "분할이 생겼다 — 비율의 근거(정본)를 리포트에 적고 G-25 를 다시 재라"
    assert len(mldata.datasets()) >= 1, "데이터셋 헤더까지 사라지면 G-25 를 잴 분모가 없다"
