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
def test_g14_라벨셋은_회수됐고_이유가_둘_다_적혀_있다():
    """**0건 단언을 지우지 않고 방향을 두 번 뒤집었다** (선례: CSRF 표지 · G-08 시드 표지 · 품목 코드).

    ① 라벨이 0건이던 동안은 `비었는지` 를 단언했다.
    ② 사용자 지시(D-150)로 가정 답변에서 라벨을 만든 뒤에는 `표지가 붙었는지` 를 단언했다.
    ③ 도입기업이 어휘를 3종으로 확정하자(D-160) 그 라벨은 **범위 밖**이 됐다. 이제
       `회수됐는지 · 왜 회수했는지` 를 단언한다.

    지우지 않는 이유는 매번 같다 — 단언이 사라지면 다음 사람이 라벨을 다시 만들어 넣어도
    아무도 막지 못한다.
    """
    meta = LABELSET["_meta"]
    assert LABELSET["labels"] == [], f"회수했는데 라벨이 남아 있다: {len(LABELSET['labels'])}건"
    assert LABELSET["predictions"] == []
    assert meta["결정번호"] == "D-160", meta.get("결정번호")
    assert "회수" in meta["성격"], meta["성격"]
    w = meta["회수한_것"]
    # **두 사유가 각각 남아 있어야 한다.** 하나만 적으면 다른 하나가 풀렸을 때 되살아난다.
    assert "범위" in w["사유_①_범위밖"], w["사유_①_범위밖"]
    assert "우리가 만든 정답과 비교" in w["사유_②_순환"], w["사유_②_순환"]
    assert "단독" in w["둘의_관계"], w["둘의_관계"]
    # 회수 전 수치를 남긴다 — 어딘가에 인용돼 있을 때 추적할 수 있어야 한다.
    assert "0.9009" in w["이전_수치"], w["이전_수치"]
    assert LABELSET["evaluator_selftest"]["gate_input"] is False


def test_g14_확정어휘는_3종이고_박스를_한_개도_만들지_않았다():
    """도입기업 확정 어휘는 `title_block`·`bom_table`·`rev_table` 3종이다 (D-160 ④).

    **우리가 3종 박스를 만들면 그게 합성이다.** 우리 파서는 영역을 가리지 못한다 —
    `_title_block` 은 이름과 달리 TEXT 에서 재질·두께 문자열을 찾을 뿐이다.
    """
    meta = LABELSET["_meta"]
    assert meta["확정_어휘"] == ["title_block", "bom_table", "rev_table"], meta["확정_어휘"]
    used = {b["cls"] for b in LABELSET["labels"]} | {b["cls"] for b in LABELSET["predictions"]}
    assert used == set(), f"확정 어휘로 박스를 만들었다 — 그건 정답이 아니라 합성이다: {sorted(used)}"
    why = meta["우리가_만들_수_없는_이유"]
    assert "경계상자가 나오지 않는다" in why, f"왜 못 만드는지가 적혀 있지 않다: {why}"
    assert "_title_block" in why, "어느 코드가 영역을 못 가리는지 적혀 있지 않다"


def test_g14_D98_은_해소됐고_TD5_비고가_열린_목록임을_적었다():
    """`가이드 3종을 쓰면 TD5 에 담을 자리가 없다`(D-98) 던 판단이 **틀렸다**.

    TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 비고는 `홀/슬롯/노즐/플랜지/치수문자 **등**` 이다.
    `등` 으로 끝나므로 닫힌 목록이 아니고, VARCHAR(50) 이라 3종이 들어간다.
    **내 판단이 틀렸다는 사실을 파일에 남긴다** — 남기지 않으면 다음 사람이 같은 충돌을
    다시 '발견'한다.
    """
    import json as _json
    design = _json.loads((ROOT / "docs" / "design" / "design.json").read_text())
    remark = None
    for det in design["td5"]["details"]:
        for c in det.get("columns", []):
            if len(c) >= 7 and c[1] == "OBJECT_TYPE":
                remark = c[6]
    assert remark is not None, "TD5 에서 OBJECT_TYPE 을 찾지 못했다"
    assert remark.rstrip().endswith("등"), f"비고가 열린 목록이 아니다: {remark}"
    obs = LABELSET["_meta"]["정본_불일치_관찰"]
    assert "해소" in obs and "틀렸다" in obs, obs


def test_g14_회수하면_주입자리도_남지_않는다():
    """가정 라벨의 **고정비율 주입**(i%10==3 FP · i%10==7 FN)은 회수와 함께 사라져야 한다.

    주입 자리만 남으면 라벨이 0건인데도 `기대 혼동행렬` 이 파일에 남아, 누가 그 숫자를
    실측처럼 읽는다. 회수는 **수치까지 회수하는 것**이다.
    """
    meta = LABELSET["_meta"]
    assert "주입" not in meta, "회수했는데 주입 자리가 남아 있다"
    assert "표본" not in meta, "회수했는데 표본 수치가 남아 있다"
    # `evaluator_selftest` 만은 남아야 한다 — 라벨과 무관한 채점기 자기검증이다(§10-16).
    assert LABELSET["evaluator_selftest"]["labels"], "자기검증까지 지우면 채점기를 못 잰다"


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
    """0건 경로: 공급자 미구성. **빈 리스트를 돌려주면 '0건 인식'과 구분이 안 된다** → 501 이어야 한다.

    **Parsing 이 구성된 장비(D-235, `KYUNGDONG_CAD_PARSER=dxf`)에서는** Parsing 은 없는 파일에
    422 를, Vision 은 그대로 501 을 낸다 — 둘을 섞지 않는다. G-14 는 그래도 열리지 않는다:
    파서는 홀·치수문자 좌표를 낼 뿐 IoU 를 잴 경계상자·정답 라벨이 없다.
    """
    avail = cadprov.availability()
    assert len(avail) == 2
    assert not avail[1].configured, "Vision 이 구성됐다 — G-14 를 실제로 잴 수 있다. 리포트를 갱신하라"
    with pytest.raises(Exception) as e:
        cadprov.vision_detector().detect("(없는 파일)")
    assert getattr(e.value, "status_code", None) == 501
    with pytest.raises(Exception) as e:
        cadprov.parsing_detector().detect("(없는 파일)")
    assert getattr(e.value, "status_code", None) == (422 if avail[0].configured else 501)


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
    parsing_on = cadprov.parsing_configured()
    # Parsing 이 구성되면(D-235) 1단계는 **열린다** — 그때 비고에 Vision 미구성·정합성 없음이 적혀야 한다.
    assert stages[0]["blocked"] is (not parsing_on), "1단계 판정이 공급자 구성 상태와 어긋난다"
    if parsing_on:
        assert "D-235" in stages[0]["note"] and "Vision" in stages[0]["note"]

    row = conn.q1(
        "insert into EST_CAD_DRAWINGS (DRAWING_NO, FILE_TYPE, FILE_PATH, FILE_SIZE, "
        " ANALYSIS_STATUS, DUPLICATE_YN, CREATED_DT) "
        "values ('QA3-TEST-G19','dwg','(테스트 probe)',0,'대기','N', now()) returning DRAWING_ID")
    did = int(row["drawing_id"])
    try:
        with pytest.raises(Exception) as e:
            cadpipe.analyze(did)
        # 미구성 → 501. Parsing 구성(D-235) → probe 는 파일이 없어 422 — 어느 쪽도 객체를 만들지 않는다.
        assert getattr(e.value, "status_code", None) == (422 if parsing_on else 501), \
            "도면이 있어도 인식은 501(미구성) 또는 422(파일 없음)이어야 한다 (조용한 합성 금지 — D-05)"
        assert n1("select count(*) as n from EST_CAD_OBJECTS where DRAWING_ID = %s", (did,)) == 0
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
    # `analyze()` 의 insert 는 **CONFIRM_YN='N'** 고정이다(D-235) — 인식 결과 제안이지 확정이 아니다.
    # CONFIRM_YN 을 **바꾸는**(update) 경로는 여전히 `review_object()` 하나여야 한다.
    src = (ROOT / "src/kyungdong/cad/pipeline.py").read_text().splitlines()
    updates = [h for h in objs if src[h[1] - 1].lower().lstrip('" ').startswith("update")]
    inserts = [h for h in objs if h not in updates]
    assert len(updates) == 1, f"EST_CAD_OBJECTS 의 CONFIRM_YN 을 바꾸는 경로가 {updates} 다 — 하나여야 한다"
    for _f, i in inserts:
        tail = " ".join(src[i - 1: i + 3])
        assert "'N'" in tail and "'Y'" not in tail, f"pipeline.py:{i} insert 가 확정('Y') 을 만든다"


def test_g24_inspections_write_path_is_one_and_guarded(client):
    """**표지를 뒤집었다** — `SHP_INSPECTIONS` 쓰기 경로가 0곳이던 시절의 차단 표지였다.

    018 검사결과 등록(`POST /shp/018`)이 붙었다. '승인 없이 바뀌는 경로 0' 이 이제
    **구현 부재가 아니라 통제** 로 성립하는지 잰다 — 쓰기 경로는 **정확히 1곳**이고,
    출하물류관리 등록 권한이 없는 역할은 403, 있는 역할은 권한 문 뒤의 입력값 검증(422)까지 간다.
    """
    hits = []
    for p in (ROOT / "src").rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if __import__("re").search(r"(insert\s+into|update)\s+SHP_INSPECTIONS\b",
                                       line, __import__("re").I):
                hits.append((p.relative_to(ROOT).as_posix(), i))
    assert len(hits) == 1 and hits[0][0].endswith("routers/shp.py"), (
        f"SHP_INSPECTIONS 쓰기 경로는 018 하나여야 한다: {hits}")

    form = {"lot_trace_id": "999999", "inspect_type": "수압시험", "qstd_id": "999999",
            "measured_value": "1"}
    for role in sorted(rbac.roles()):
        r = csrf_post(client, "/shp/018", form, headers={"x-kyungdong-role": role},
                      follow_redirects=False)
        if rbac.can_write(role, "출하물류관리"):
            assert r.status_code == 422, f"{role}: 권한 문을 지나 입력값 검증(422)이어야 한다: {r.status_code}"
        else:
            assert r.status_code == 403, f"{role}(출하물류관리 W 없음): {r.status_code} — 403 이어야 한다"


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
