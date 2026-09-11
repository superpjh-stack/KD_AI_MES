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
    for t, why in (("EST_COST_RATES", "단가 값 미확보 (D-04)"),
                   ("EST_PROJECTS", "고객사 코드 그룹 비어 있음 (D-47)"),
                   ("DAT_DATASET_SPLITS", "분할 비율이 정본에 없다")):
        n = int(conn.q1(f"select count(*) as n from {t}")["n"])
        assert n == 0, f"{t} 를 시드했다 — {why}"


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
