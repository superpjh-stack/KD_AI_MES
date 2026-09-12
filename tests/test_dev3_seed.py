"""개발3 시드 — 멱등(G-07) · 실측값만 · 지어내지 않은 것은 비어 있다(§0.2)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from kyungdong.app.settings import settings              # noqa: E402
from kyungdong.app.util import assumed                   # noqa: E402
from kyungdong.cad import inventory as inv               # noqa: E402
from kyungdong.ml import datasets as ml_datasets         # noqa: E402
from kyungdong.ml import registry as ml_registry         # noqa: E402

SEED = ROOT / "db" / "seed_dev3.py"
COUNTS = ("IF_DEVICE_REGISTRY", "DAT_PREPROCESS_RULES", "DAT_TRAIN_DATASETS",
          "AGT_VECTOR_DOCS", "IF_EXT_DOCUMENTS")


def _counts() -> dict[str, int]:
    return {t: int(conn.q1(f"select count(*) as n from {t}")["n"]) for t in COUNTS}


def test_시드를_두_번_돌려도_행_수가_같다():
    subprocess.run([sys.executable, str(SEED)], check=True, capture_output=True, cwd=ROOT)
    before = _counts()
    subprocess.run([sys.executable, str(SEED)], check=True, capture_output=True, cwd=ROOT)
    assert _counts() == before, "시드가 멱등이 아니다 (G-07)"


def test_수집_주기는_env_가설값에서_온다():
    row = conn.q1("select COLLECT_INTERVAL from IF_DEVICE_REGISTRY where DEVICE_TYPE = 'PLC'")
    assert int(row["collect_interval"]) == settings().h("PLC_POLL_SEC").as_int()
    assert settings().h("PLC_POLL_SEC").badge == "가설 (D-06)"


def test_설치_위치와_IP_는_미확인이라_비어_있다():
    rows = conn.q("select IP_ADDRESS, LOCATION_DESC from IF_DEVICE_REGISTRY")
    for r in rows:
        assert r["ip_address"] is None, "현장 실사 전 IP 를 지어내지 않는다 (D-26·D-27)"
        assert r["location_desc"] is None, "설치 위치 미확인 (D-26)"


def test_학습_데이터셋_건수는_실측값이다():
    ds = conn.q1("select TOTAL_CNT, EXCLUDED_CNT, BALANCE_RESULT, DATASET_STATUS "
                 "from DAT_TRAIN_DATASETS order by DATASET_ID limit 1")
    assert ds is not None
    st = inv.stats(inv.read_inventory())
    assert int(ds["total_cnt"]) == st["total"] == 1283
    assert int(ds["excluded_cnt"]) == st["excluded"]
    assert "184" in ds["balance_result"] and "중앙값 5" in ds["balance_result"]
    assert ds["dataset_status"] == "작성", "검증·확정은 사람이 한다"


def test_Label_은_0_건이고_차단으로_표기된다():
    ds = conn.q1("select DATASET_ID from DAT_TRAIN_DATASETS order by DATASET_ID limit 1")
    cov = ml_datasets.label_coverage(int(ds["dataset_id"]))
    assert cov["labeled"] == 0
    assert cov["verdict"] == "차단 (D-04)"


def test_지어내지_않은_것은_비어_있다():
    """**개발3 시드가** 넣지 않는 표. `EST_PROJECTS` 는 여기서 빠졌다 —

    사용자 지시로 고객사 코드가 확정(D-139)되어 D-47 차단이 풀렸고, `db/seed_dev1.py` 가
    **실측 GD 프로젝트**를 넣는다(D-131). 0건 단언을 지우지 않고 아래로 **뒤집어** 옮겼다.
    """
    for t, why in (("EST_COST_RATES", "단가 값 미확보 (D-04)"),
                   ("DAT_DATASET_SPLITS", "분할 비율이 정본에 없다")):
        n = int(conn.q1(f"select count(*) as n from {t}")["n"])
        assert n == 0, f"{t} 를 시드했다 — {why}"
    src = SEED.read_text()
    assert "insert into EST_PROJECTS" not in src, \
        "EST_PROJECTS 는 개발3 시드가 넣지 않는다 — 개발1 이 실측 GD 코드로 넣는다 (D-131)"


def test_EST_PROJECTS_는_실측_GD_코드만_들어간다():
    """채워졌으면 **지어낸 번호가 아님**을 단언한다 — `GD`+YYMM 형식과 고객사 확정 표시."""
    rows = conn.q("select PROJECT_NO, CUSTOMER_CODE, PRODUCT_GROUP from EST_PROJECTS "
                  "where PROJECT_NO like 'GD%'")
    if not rows:                    # 개발1 시드 전이면 0건이 정답이다 — 그 사실을 그대로 단언한다
        assert int(conn.q1("select count(*) as n from EST_PROJECTS")["n"]) == 0
        return
    import re
    for r in rows:
        assert re.match(r"^GD\s?\d{4}", r["project_no"]), \
            f"GD+YYMM 형식이 아니다 — 지어낸 번호다: {r['project_no']}"
        mark = conn.q1("select ATTR1 from BAS_COMMON_CODES where CODE_GROUP = '고객사' "
                       "and CODE_VALUE = %s", (r["customer_code"],))
        assert mark is not None, f"고객사 코드 {r['customer_code']} 가 공통코드에 없다 (D-32)"
        assert "확정 (D-139)" in (mark["attr1"] or ""), \
            f"{r['customer_code']} 에 확정 표시가 없다 — 마스터로 조용히 승격됐다"


RUNTIME_ONLY = ("AGT_QUERY_LOGS", "AGT_RECOMMENDATIONS", "EST_ML_MODELS", "EST_ML_TRAIN_RUNS",
                "EST_ML_PREDICTIONS", "EST_SHAP_FACTORS", "EST_OBJECT_REVIEWS",
                "IF_CAD_IMPORT_LOGS", "IF_DOC_EMBED_LOGS", "IF_GATEWAY_BUFFER")


def test_시드는_런타임_전용_표에_쓰지_않는다():
    """수집·질의를 돌리면 쌓이지만 **시드**가 만들면 안 되는 표다(G-11 · §10-4)."""
    import re
    src = SEED.read_text()
    writes = re.findall(r"insert\s+into\s+([A-Z_]+)", src, re.I)
    assert not (set(w.upper() for w in writes) & set(RUNTIME_ONLY)), \
        f"시드가 런타임 전용 표에 쓴다: {writes}"
    assert all(t in src for t in RUNTIME_ONLY), "시드 출력이 런타임 전용 표 0건을 보여 줘야 한다"


def test_학습_회전은_아직_돌지_않았다():
    r = ml_registry.readiness()
    assert r["models"] == 0 and r["runs"] == 0
    assert "학습 미실시" in r["status"]
    assert all("D-0" in b or "D-1" in b or "D-4" in b for b in r["blockers"])


def test_성능목표는_목표치로만_적혀_있다():
    for t in ml_registry.TARGETS:
        assert t["blocked"], "달성값을 만들지 않고 차단 사유를 남긴다"


def test_지식문서는_실제_파일에서_왔다():
    rows = conn.q("select DOC_NAME, SOURCE_PATH, EMBED_TARGET_YN from IF_EXT_DOCUMENTS")
    assert rows, "지식문서가 0건이면 RAG 는 항상 근거 부족이다"
    for r in rows:
        assert (ROOT / r["source_path"]).exists(), f"원본이 없다: {r['source_path']}"


def test_임베딩_미구성이면_벡터가_비어_있다():
    n = int(conn.q1("select count(*) as n from AGT_VECTOR_DOCS where EMBEDDING is not null")["n"])
    if not settings().embed_configured:
        assert n == 0, "임베딩 공급자가 없는데 벡터가 있다 — 0벡터를 채웠는지 확인한다 (D-08)"


# ══ 가정 답변 선언 (D-150) 과 그 파생물 ═══════════════════════════════════
# **0건 단언을 지우지 않고 방향을 뒤집었다** — '재질' 그룹이 0건이던 동안은
# `tests/test_dev1_seed.py` 가 비었는지를 단언했다. 가정 답변에서 채운 뒤에는 여기가
# **표지가 붙었는지·목록 밖 이름이 없는지**를 단언한다.
def test_가정_선언이_DB_에_박혀_있고_파일과_같은_결정번호다():
    decl = conn.q1("select CONFIG_VALUE, DESCRIPTION from SYS_CONFIGS "
                   "where CONFIG_TYPE = %s and CONFIG_KEY = %s and USE_YN = 'Y'",
                   (assumed.CONFIG_TYPE, assumed.CONFIG_KEY))
    assert decl is not None, (
        "가정 선언이 없다 — 이 선언이 없으면 재질 코드·단위 가정·G-14 라벨이 전부 차단이다")
    assert decl["config_value"] == assumed.file_decision() == "D-150"
    assert assumed.path_text() in (decl["description"] or ""), "선언에 출처 파일이 없다"
    assert assumed.declaration() == "D-150"


def test_고지_문구는_선언_파일에서_읽는다():
    """검사기·화면이 문구를 박아 두면 선언을 지워도 문구가 남아 거짓 증거가 된다."""
    assert assumed.base_note() == "가정 답변 기준 (D-150)"
    assert assumed.circular_note() == "가정 답변 기준 (D-150) · 순환 라벨 — 정확도 증거 아님"
    assert "25.4" in assumed.unit_tag() and "단위 가정 (D-150)" in assumed.unit_tag()
    assert assumed.material_attr1() == "가정 답변 기준 (D-150) — 도입기업 미확인"


def test_재질_코드는_실측_목록_밖의_이름을_만들지_않는다():
    """**목록 밖 이름이 하나라도 있으면 FAIL** — 가정 답변 ② 는 실측 표기만 확인했다."""
    import seed_dev3

    measured = {k for k, _ in seed_dev3.measured_materials()}
    assert len(measured) == 14, f"실측 표기가 14종이 아니다: {sorted(measured)}"
    merge = assumed.material_merge()
    allowed = measured | set(merge)          # 실측 표기 + 통합 정규 표기
    rows = conn.q("select CODE_VALUE, CODE_NAME, ATTR1, ATTR2 from BAS_COMMON_CODES "
                  "where CODE_GROUP = '재질' order by SORT_ORDER")
    assert rows, "재질 코드가 비었다 — `make db-seed`"
    seeded = {r["code_value"] for r in rows if (r["attr1"] or "").startswith("가정 답변 기준")}
    assert seeded <= allowed, f"실측·통합 목록 밖의 재질을 만들었다: {sorted(seeded - allowed)}"
    assert len(seeded) == 8, f"통합 후 8종이어야 한다: {sorted(seeded)}"
    for r in rows:
        if r["code_value"] not in seeded:
            continue
        assert r["attr1"] == assumed.material_attr1(), r["attr1"]
        assert "실측 도면" in (r["attr2"] or ""), f"{r['code_value']} 에 실측 건수가 없다"


def test_두께는_코드_그룹이_아니다():
    """두께는 수치다 — `EST_CAD_FEATURES` 에 있다. 코드 그룹으로 만들면 값이 코드로 굳는다."""
    n = int(conn.q1("select count(*) as n from BAS_COMMON_CODES "
                    "where CODE_GROUP in ('두께','THICKNESS')")["n"])
    assert n == 0, "두께를 코드 그룹으로 만들었다 — 수치를 코드로 굳히면 새 두께가 422 가 된다"


def test_선언을_지우면_재질_코드가_회수된다():
    """**선언이 없으면 파생물도 없다.** 되돌림 시험 — 끝나고 원상복구한다."""
    import seed_dev3

    admin = conn.q1("select USER_ID from SYS_USERS where LOGIN_ID = 'admin'")
    admin_id = int(admin["user_id"])
    before = int(conn.q1("select count(*) as n from BAS_COMMON_CODES "
                         "where CODE_GROUP = '재질'")["n"])
    conn.x("delete from SYS_CONFIGS where CONFIG_TYPE = %s and CONFIG_KEY = %s",
           (assumed.CONFIG_TYPE, assumed.CONFIG_KEY))
    try:
        assert assumed.declaration() is None
        assert assumed.material_attr1() == "", "선언이 없는데 표시 문구가 나온다"
        seed_dev3.seed_material_codes(admin_id)
        after = int(conn.q1("select count(*) as n from BAS_COMMON_CODES "
                            "where CODE_GROUP = '재질'")["n"])
        assert after == 0, f"선언을 지웠는데 재질 코드가 {after}건 남았다"
    finally:
        seed_dev3.seed_assumed_flag()
        seed_dev3.seed_material_codes(admin_id)
    assert int(conn.q1("select count(*) as n from BAS_COMMON_CODES "
                       "where CODE_GROUP = '재질'")["n"]) == before
