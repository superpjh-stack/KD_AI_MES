#!/usr/bin/env python
"""G-14 ~ G-25 — AI 게이트 (QA3).

원칙 (goal.md §2.6 · §10 · 사업계획서 2.6 · D-22)
  · **게이트를 낮추지 않는다.** 못 맞추면 `차단`, 못 재면 `판정 불가`. 수치를 만들지 않는다.
  · **합성 라벨·합성 예측으로 성능을 내지 않는다.** 분모가 0이면 80% 도 0% 도 아니다.
  · **0건 경로와 N건 경로를 둘 다 명시 단언**한다(§10-4). `skip` 은 결함이다(D-62).
  · **판정 정본 함수를 직접 부른다**(§10-16) — `agent.service.ask` · `agent.retrieval` ·
    `cad.pipeline` · `cad.provider` · `ml.registry` · `ml.datasets` · `app.rbac` · `app.settings`.
    로직을 복제하면 개발자가 고쳐도 수치가 안 움직인다. **되돌림 시험**으로 그것을 확인한다.
  · 측정 중 동시 변경을 감지하면 FAIL 이 아니라 **판정 불가**다(§10-17).
  · 이 검사기가 넣은 행은 **전부 지운다**. 남기면 G-11(런타임 전용 표 0건)을 오염시킨다.

출력 규약: 게이트별 판정 줄은 `G-NN <판정> — <실측>` 한 줄이다(`tools/gate.py` 가 파싱한다).
섹션 제목은 반드시 `──` 로 시작한다 — `G-NN` 으로 시작하면 판정 줄로 오인된다.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                      # noqa: E402
from fastapi.testclient import TestClient                        # noqa: E402
from kyungdong.agent import citations, llm, retrieval, service   # noqa: E402
from kyungdong.app import rbac                                   # noqa: E402
from kyungdong.app.main import app                               # noqa: E402
from kyungdong.app.settings import settings                      # noqa: E402
from kyungdong.app.util import assumed, csrf                     # noqa: E402
from kyungdong.cad import pipeline as cadpipe                    # noqa: E402
from kyungdong.cad import provider as cadprov                    # noqa: E402
from kyungdong.ml import datasets as mldata                      # noqa: E402
from kyungdong.ml import registry as mlreg                       # noqa: E402

PASS, FAIL, BLOCKED, UNDET = "PASS", "FAIL", "차단", "판정 불가"
VERDICTS: list[tuple[str, str, str]] = []

GOLDSET = ROOT / "work" / "rag_goldset.json"
LABELSET = ROOT / "work" / "cad_labelset.json"

# 사업계획서 2.6 · D-22 목표치. **여기서 낮추지 않는다.**
TARGETS = {
    "G-14": "CAD 객체 인식 80% 이상 (IoU 0.5 · P/R/F1)",
    "G-15": "견적 산출 정확도 ±5% 이내 (MAPE·MAE)",
    "G-16": "BOM 생성 정확도 85% 이상 (항목 단위 P/R/F1)",
    "G-17": "납기 예측 정확도 85% 이상 (허용 오차 내 정확도 + RMSE)",
    "G-18": "설명가능성 90% (SHAP Top-N vs 전문가 · Spearman ρ)",
}

# G-24 승인 필요 쓰기 (contracts/api-contract.md §6)
APPROVAL_TABLES = ("EST_QUOTATIONS", "EST_BOM_HEADERS", "EST_CAD_OBJECTS",
                   "SHP_INSPECTIONS", "SHP_SHIPMENTS")
WRITE_SQL = re.compile(
    r"(insert\s+into|update)\s+(" + "|".join(APPROVAL_TABLES) + r")\b", re.I)

SRC_DIRS = (ROOT / "src", ROOT / "db", ROOT / "tests", ROOT / "tools")


def say(s: str = "") -> None:
    print(s)


def verdict(gate: str, v: str, m: str) -> None:
    VERDICTS.append((gate, v, m))


def n1(sql: str, params: Any = None) -> int:
    row = conn.q1(sql, params)
    return int(row["n"]) if row else 0


def count(table: str) -> int:
    return n1(f"select count(*) as n from {table}")


def fingerprint() -> str:
    """동시 변경 감지 (§10-17) — 소스 mtime 합."""
    acc = []
    for d in SRC_DIRS:
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            acc.append(f"{p}:{p.stat().st_mtime_ns}")
    return str(hash("\n".join(acc)))


# ══════════════════════════════════════════════════════════════════════════
# IoU 평가기 — G-14 용. **정답 박스가 없으면 부르지 않는다.**
# ══════════════════════════════════════════════════════════════════════════
def iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix, iy = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def match(labels: list[dict], preds: list[dict], thr: float) -> dict[str, Any]:
    """클래스가 같고 IoU ≥ 임계인 것만 TP. 정답 1개는 예측 1개에만 매칭된다."""
    used: set[int] = set()
    tp = 0
    for p in sorted(preds, key=lambda x: -float(x.get("score", 0))):
        best, best_i = 0.0, -1
        for i, g in enumerate(labels):
            if i in used or g["cls"] != p["cls"]:
                continue
            v = iou(g["box"], p["box"])
            if v > best:
                best, best_i = v, i
        if best >= thr and best_i >= 0:
            used.add(best_i)
            tp += 1
    fp, fn = len(preds) - tp, len(labels) - tp
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1}


def spearman(a: list[float], b: list[float]) -> float | None:
    """G-18 용 Spearman ρ. 표본이 2 미만이면 **없다** — 0.0 을 돌려주지 않는다."""
    if len(a) != len(b) or len(a) < 2:
        return None

    def rank(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = rank(a), rank(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return (num / den) if den else None


def mape_mae(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """(예측, 실제) → MAPE·MAE. 표본 0이면 **None** 이다 — 0.0 으로 메우지 않는다."""
    if not pairs:
        return {"n": 0, "mape": None, "mae": None, "within": None}
    ape = [abs(p - a) / abs(a) for p, a in pairs if a]
    ae = [abs(p - a) for p, a in pairs]
    return {"n": len(pairs),
            "mape": (statistics.fmean(ape) * 100) if ape else None,
            "mae": statistics.fmean(ae) if ae else None,
            "within": (sum(1 for x in ape if x <= 0.05) / len(ape)) if ape else None}


# ══════════════════════════════════════════════════════════════════════════
# G-14 CAD 객체 인식
# ══════════════════════════════════════════════════════════════════════════
def gate_14() -> None:
    say("── G-14 CAD 객체 인식 — IoU 0.5 기준 P/R/F1 ──────────────────────")
    ls = json.loads(LABELSET.read_text())
    labels, preds = ls["labels"], ls["predictions"]
    thr = settings().cad_iou_threshold
    objs = count("EST_CAD_OBJECTS")
    drawings = count("EST_CAD_DRAWINGS")
    avail = cadprov.availability()

    say(f"  정답 박스(work/cad_labelset.json labels)  {len(labels)} 건")
    say(f"  예측 박스(predictions)                    {len(preds)} 건")
    say(f"  EST_CAD_OBJECTS {objs} 행 · EST_CAD_DRAWINGS {drawings} 행")
    for a in avail:
        say(f"  공급자 {a.method:<22} 구성 {a.configured} — {a.reason}")
    say(f"  IoU 임계 (KYUNGDONG_CAD_IOU_THRESHOLD, 사업계획서 2.6-1 확정값) = {thr}")
    label_files = [p for d in (ROOT / "docs", ROOT / "work", ROOT / "db")
                   for p in d.rglob("*") if p.suffix.lower() in (".txt",)]
    say(f"  docs·work·db 안의 라벨 후보 파일(*.txt) — {len(label_files)} 건 "
        "(Label Studio YOLO 내보내기는 labels/*.txt + classes.txt 다)")

    # 0건 경로 단언 (§10-4) — 라벨이 0이면 분모가 0이고, 분모 0은 성능값이 아니다.
    if not labels and not preds:
        say("  **0건 경로**: 정답·예측이 모두 0 → TP/FP/FN 분모 0. 합성 박스를 만들지 않는다.")
    # N건 경로: 평가기 자체가 동작하는지 **게이트 입력이 아닌** 자기검증으로 확인한다.
    st = ls["evaluator_selftest"]
    say("  ── 평가기 자기검증 (게이트 입력 아님 — 리포트 실측란에 쓰지 않는다) ──")
    moved = []
    for t in (0.2, 0.5, 0.9):
        r = match(st["labels"], st["predictions"], t)
        exp = st["expected"][f"iou_{t}"]
        ok = (r["tp"], r["fp"], r["fn"]) == (exp["tp"], exp["fp"], exp["fn"])
        moved.append((r["tp"], r["fp"], r["fn"]))
        say(f"     IoU {t}: TP {r['tp']} FP {r['fp']} FN {r['fn']} "
            f"P {r['precision']} R {r['recall']} F1 {r['f1']}  기대일치 {ok}")
    reversal = len(set(moved)) == 3
    say(f"     **되돌림 시험**: 임계를 바꾸면 혼동행렬이 움직이는가 → {reversal} "
        f"(같은 값이 나오면 평가기가 임계를 안 읽는 것이다 — 광성 사업 사고 §10-16)")

    # **어휘 충돌은 더 이상 차단 사유가 아니다.** 도입기업이 3종으로 확정했고(D-160 ④),
    # TD5 비고가 `… 등` 으로 끝나는 열린 목록이라 담을 자리도 있다 — D-98 은 해소됐다.
    # 남은 차단 사유는 하나다: **그 3종의 정답 박스가 0건**이다.
    vocab = assumed.label_vocab()
    why = (f"정답 박스 0건 — 확정 어휘 {list(vocab) or '미확인'} (D-160 ④) 의 사람 라벨이 "
           "docs/cad 에 없다 (Label Studio 내보내기 없음. 라벨링 가이드는 'MVP 100장 → "
           "권장 300장' 계획 단계) · 예측 0건 (Autodesk API·YOLOv8 가중치 미확보 D-05 · "
           "우리 파서는 표제란·BOM표·리비전표의 **경계상자를 만들지 못한다**) · "
           "EST_CAD_OBJECTS 0건")

    # ── 가정 답변 선언 (D-150) ─────────────────────────────────────────
    # **고지 문구를 여기 박지 않는다.** `SYS_CONFIGS('시스템설정','ASSUMED_ANSWERS')` 선언과
    # 그 출처 파일에서 읽는다. 선언이 없으면 문구가 빈 문자열이고, 그러면 **수치를 내지 않는다** —
    # 선언을 지웠는데 수치가 남으면 그 수치가 실측처럼 인용된다.
    note = assumed.circular_note()
    decl = assumed.declaration()
    say(f"  가정 선언 SYS_CONFIGS('{assumed.CONFIG_TYPE}','{assumed.CONFIG_KEY}') = "
        f"{decl or '없음 — ' + (assumed.mismatch() or '')}")
    if not labels or not note:
        if labels and not note:
            say(f"  **라벨이 {len(labels)}건 있는데 가정 선언이 없다** — 출처를 확인할 수 없는 "
                "라벨로 수치를 내지 않는다. 선언을 되살리거나 라벨을 회수해야 한다")
            why = (f"{why} · work/cad_labelset.json 에 라벨 {len(labels)}건이 있으나 "
                   f"가정 선언이 없다 ({assumed.mismatch()})")
        verdict("G-14", BLOCKED, f"{TARGETS['G-14']} / 분모 0 — {why}")
        say()
        return

    # ── N건 경로 (§10-4) — **순환 라벨이다. 정확도 증거가 아니다.** ──────
    # 라벨과 예측을 같은 DXF 기하 파싱에서 뽑았으므로 우리 탐지를 우리가 만든 정답과 비교한다.
    # 그래서 80% 를 넘든 못 넘든 **PASS 도 FAIL 도 아니다** — 판정 불가다. 게이트를 낮추는 것이
    # 아니라, 이 수치로는 게이트를 판정할 수 없다는 사실을 적는 것이다.
    meta = ls.get("_meta", {})
    imgs = sorted({str(b.get("image")) for b in labels + preds})
    say(f"  라벨 도면 {len(imgs)} 건 · 라벨 어휘 {sorted({b['cls'] for b in labels})} "
        f"· 도입기업 확정 어휘 {list(assumed.label_vocab()) or '미확인'} (D-160 ④)")
    say(f"  주입 {meta.get('주입', {}).get('FP(오검출) 비율')} · "
        f"{meta.get('주입', {}).get('FN(누락) 비율')}")
    # 도면별로 재고 합산한다 — 다른 도면의 박스가 우연히 매칭되지 않게. 산식은 `match()` 한 벌이다.
    tp = fp = fn = 0
    for im in imgs:
        r = match([b for b in labels if str(b.get("image")) == im],
                  [b for b in preds if str(b.get("image")) == im], thr)
        tp, fp, fn = tp + r["tp"], fp + r["fp"], fn + r["fn"]
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
    say(f"  IoU {thr} 기준 TP {tp} FP {fp} FN {fn} — "
        f"Precision {prec:.4f} · Recall {rec:.4f} · F1 {f1:.4f}"
        if f1 is not None else f"  IoU {thr} 기준 TP {tp} FP {fp} FN {fn} — P/R/F1 계산 불가")
    # 주입한 만큼 세어졌는가 — **여기서 차이가 나면 그것이 실측이다.** 맞추려고 고치지 않는다.
    exp = (meta.get("주입") or {}).get(
        "기대 혼동행렬(IoU 무관 · 박스가 동일좌표라 IoU=1.0)") or {}
    seen: dict[tuple, int] = {}
    for b in labels:
        k = (str(b.get("image")), b["cls"], tuple(b["box"]))
        seen[k] = seen.get(k, 0) + 1
    coincident = sum(c - 1 for c in seen.values() if c > 1)
    say(f"  주입 기대 TP/FP/FN {exp.get('TP')}/{exp.get('FP')}/{exp.get('FN')} ↔ "
        f"실측 {tp}/{fp}/{fn} — 차이 {abs(int(exp.get('FP', 0)) - fp)}건")
    say(f"     차이의 정체: 같은 도면 안에 **좌표가 겹치는 CIRCLE** 이 있어(라벨 중 중복 좌표 "
        f"{coincident}개) 뺀 자리를 다른 박스가 대신 매칭한다. 탐욕 매칭(정답 1개 ↔ 예측 1개)의 "
        "성질이고 숨기지 않는다 — 주입 자리는 `_meta.주입` 에 전부 적혀 있다")
    say(f"  **{note}** — 라벨과 예측이 같은 DXF 파싱에서 나왔다. 이 수치는 채점 파이프라인이 "
        "돈다는 증거일 뿐이고 AI 정확도의 증거가 **아니다**")
    say(f"  참고: 목표 80% 대비 F1 {'≥' if (f1 or 0) >= 0.8 else '<'} 0.80 — "
        "**순환 라벨이라 이 비교로는 게이트를 판정하지 않는다**")
    verdict("G-14", UNDET,
            f"{TARGETS['G-14']} / {note} · IoU {thr} TP {tp} FP {fp} FN {fn} "
            f"P {prec:.4f} R {rec:.4f} F1 {f1:.4f} · 도면 {len(imgs)}건 · "
            f"라벨·예측을 같은 DXF 파싱에서 파생(순환) — 정확도 증거 아님. "
            f"실제 탐지기는 여전히 501 미구성(D-05)이고 EST_CAD_OBJECTS {objs}행이다"
            if f1 is not None else
            f"{TARGETS['G-14']} / {note} · TP {tp} FP {fp} FN {fn} — P/R/F1 계산 불가")
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-15 견적 · G-16 BOM · G-17 납기 · G-18 설명가능성
# ══════════════════════════════════════════════════════════════════════════
def gate_15_18() -> None:
    say("── G-15~G-18 견적·BOM·납기·설명가능성 — 학습·Label 전제 실측 ───────")
    ready = mlreg.readiness()                       # 정본 함수 (ml.registry)
    for k in ("datasets", "dataset_items", "labeled_items", "splits", "drawings",
              "confirmed_objects", "features", "cost_rates", "models", "runs"):
        say(f"  {k:<18} {ready[k]:>6}")
    preds = mlreg.predictions()                     # 정본 함수
    shaps = mlreg.shap_factors()                    # 정본 함수
    quotes, boms = count("EST_QUOTATIONS"), count("EST_BOM_HEADERS")
    say(f"  EST_ML_PREDICTIONS {len(preds)} · EST_SHAP_FACTORS {len(shaps)} · "
        f"EST_QUOTATIONS {quotes} · EST_BOM_HEADERS {boms}")
    for b in ready["blockers"]:
        say(f"  차단 사유 · {b}")

    # ── G-15 견적 ±5% (MAPE·MAE + 제품군별 오차 분포) ──────────────────
    rows = conn.q(
        "select p.PREDICT_VALUE as pv, p.ACTUAL_VALUE as av, pj.PRODUCT_GROUP as pg "
        "from EST_ML_PREDICTIONS p "
        "left join EST_QUOTATIONS q on q.QUOTE_ID = p.TARGET_ID and p.TARGET_TYPE = '견적원가' "
        "left join EST_PROJECTS pj on pj.PROJECT_ID = q.PROJECT_ID "
        "where p.ACTUAL_VALUE is not null")
    pairs = [(float(r["pv"]), float(r["av"])) for r in rows if r["pv"] is not None]
    m = mape_mae(pairs)
    say(f"  G-15 표본 {m['n']} — MAPE {m['mape']} · MAE {m['mae']} · ±5% 이내 비율 {m['within']}")
    groups = sorted({r["pg"] for r in rows if r["pg"]})
    say(f"       제품군별 오차 분포: {groups or '분모 0 — 제품군별로 나눌 표본이 없다'}")
    if m["n"] == 0:
        verdict("G-15", BLOCKED,
                f"{TARGETS['G-15']} / 표본 0 — EST_ML_PREDICTIONS 0건 · EST_QUOTATIONS 0건 · "
                "과거 견적금액·실제 제조원가 Label 확보 미확인 (D-04). 제품군별 분포도 분모 0")
    else:
        verdict("G-15", FAIL if (m["mape"] or 999) > 5 else PASS,
                f"표본 {m['n']} MAPE {m['mape']:.2f}% MAE {m['mae']:.2f}")

    # ── G-16 BOM 85% (항목 단위 자재·수량·공정 P/R/F1) ─────────────────
    ref_bom = n1("select count(*) as n from EST_BOM_HEADERS where GEN_METHOD = %s", ("수동",))
    items = count("EST_BOM_ITEMS")
    routings = count("EST_BOM_ROUTINGS")
    say(f"  G-16 기준 BOM(수동 생성) {ref_bom} · EST_BOM_ITEMS {items} · EST_BOM_ROUTINGS {routings}")
    if boms == 0:
        verdict("G-16", BLOCKED,
                f"{TARGETS['G-16']} / 분모 0 — EST_BOM_HEADERS 0건 · 기준 BOM 0건 · "
                "자재/수량/공정 항목 0건. 품목·재질 코드 그룹이 비어 있어(D-47) BOM 전개 자체가 불가")
    else:
        verdict("G-16", UNDET, f"BOM {boms}건 — 기준 BOM {ref_bom}건과 대조할 매칭 키가 정본에 없다")

    # ── G-17 납기 85% (허용 오차 내 정확도 + RMSE) ─────────────────────
    tol = settings().h("DUE_DATE_TOLERANCE_DAYS")
    due = conn.q(
        "select PREDICT_VALUE as pv, ACTUAL_VALUE as av from EST_ML_PREDICTIONS "
        "where TARGET_TYPE = %s and ACTUAL_VALUE is not null", ("납기",))
    say(f"  G-17 허용 오차 {tol.value} 일 {tol.badge} (.env KYUNGDONG_DUE_DATE_TOLERANCE_DAYS) "
        f"· 표본 {len(due)}")
    if not due:
        verdict("G-17", BLOCKED,
                f"{TARGETS['G-17']} / 표본 0 — EST_ML_PREDICTIONS TARGET_TYPE='납기' 0건. "
                f"허용 오차 {tol.value}일은 {tol.badge} 이고 정본에 범위가 없다(D-12). "
                "실적 Label 부재(D-04)로 RMSE 도 계산 불가")
    else:
        err = [abs(float(r["pv"]) - float(r["av"])) for r in due]
        rmse = (statistics.fmean([e * e for e in err])) ** 0.5
        acc = sum(1 for e in err if e <= tol.as_float()) / len(err)
        verdict("G-17", PASS if acc >= 0.85 else FAIL,
                f"표본 {len(due)} 정확도 {acc:.1%} RMSE {rmse:.3f} (허용 {tol.value}일 {tol.badge})")

    # ── G-18 설명가능성 90% (SHAP Top-N ↔ 전문가) ──────────────────────
    matched = n1("select count(*) as n from EST_SHAP_FACTORS where EXPERT_MATCH_YN = 'Y'")
    say(f"  G-18 EST_SHAP_FACTORS {len(shaps)} · EXPERT_MATCH_YN='Y' {matched} · "
        f"Spearman ρ 표본 {len(shaps)} (2 미만이면 ρ 는 정의되지 않는다)")
    say("       전문가 평가 변수 목록: **정본에 없다**(D-13) — 일치율의 정답 쪽이 존재하지 않는다")
    if not shaps:
        verdict("G-18", BLOCKED,
                f"{TARGETS['G-18']} / 분모 0 — EST_SHAP_FACTORS 0건(예측 0건이라 FK 상 생길 수 없다) "
                "+ 전문가 평가 변수 목록 부재(D-13). 일치율·Spearman ρ 둘 다 계산 불가")
    else:
        rho = spearman([float(s["shap_value"]) for s in shaps],
                       [float(s["rank_no"]) for s in shaps])
        verdict("G-18", UNDET, f"SHAP {len(shaps)}건 ρ={rho} — 전문가 변수 목록 없음(D-13)")
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-19 CAD 견적 5단계 종단 통과 + Confidence Score·근거
# ══════════════════════════════════════════════════════════════════════════
def gate_19(client: TestClient) -> None:
    say("── G-19 CAD 견적 5단계 종단 통과 · 단계별 Confidence Score·근거 ─────")
    stages = cadpipe.stage_status()                 # 정본 함수
    for s in stages:
        say(f"  {s['no']}단계 {s['name']:<10} {s['table']:<38} {s['count']:>4} 건 "
            f"차단 {s['blocked']} — {s['note'][:70]}")
    passed = [s for s in stages if s["count"] > 0 and not s["blocked"]]
    say(f"  끝까지 통과한 프로젝트: {min((s['count'] for s in stages), default=0)} 건 "
        f"(5단계 전부 > 0 이어야 1건이다)")

    # ── 0건 경로 / N건 경로를 둘 다 단언한다 (§10-4) ───────────────────
    drawings = count("EST_CAD_DRAWINGS")
    say(f"  ① 0건 경로: EST_CAD_DRAWINGS {drawings} 행")
    probe_no = "QA3-PROBE-G19"
    created = None
    try:
        if drawings == 0:
            # N건 경로를 **명시 단언**하려고 도면 1건을 임시로 넣는다. 끝나고 지운다.
            row = conn.q1(
                "insert into EST_CAD_DRAWINGS (DRAWING_NO, FILE_TYPE, FILE_PATH, FILE_SIZE, "
                " ANALYSIS_STATUS, DUPLICATE_YN, CREATED_DT) "
                "values (%s,'dwg','(QA3 probe — 실제 파일 아님)',0,'대기','N', now()) "
                "returning DRAWING_ID", (probe_no,))
            created = int(row["drawing_id"])
        target = created or int(conn.q1("select min(DRAWING_ID) as d from EST_CAD_DRAWINGS")["d"])
        say(f"  ② N건 경로: 도면 #{target} 으로 cad.pipeline.analyze() 실행")
        try:
            r = cadpipe.analyze(target)
            say(f"     인식 결과 {r} — **501 이 아니라 통과했다. 공급자 구성 확인 필요**")
            stage1 = True
        except Exception as e:                       # noqa: BLE001 — 계약 오류를 그대로 본다
            code = getattr(e, "status_code", None)
            detail = getattr(e, "detail", {})
            msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
            say(f"     → HTTP {code} {msg} (기대: 501 CAD Parsing 미구성 — 조용한 합성 금지)")
            stage1 = False
        feat = cadpipe.build_features(target)
        say(f"     Feature 생성: 확정객체 {feat['confirmed_objects']} → 생성 {feat['created']} "
            f"· 차단 Feature {len(feat['blocked'])}/6 종")
    finally:
        if created is not None:
            conn.x("delete from EST_CAD_DRAWINGS where DRAWING_ID = %s", (created,))
            say(f"  (probe 도면 #{created} 삭제 — 분모를 흐리지 않는다)")

    # 단계별 Confidence Score·근거가 화면에 있는가
    say("  ③ 화면 단계별 Confidence Score·근거 표시")
    found: dict[str, bool] = {}
    for path in ("/est/010", "/est/011", "/est/012", "/est/013", "/est/015"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        body = r.text
        has_conf = ("Confidence" in body) or ("신뢰도" in body)
        has_why = ("근거" in body) or ("SOURCE_DESC" in body) or ("산출 근거" in body)
        found[path] = has_conf and has_why
        say(f"     {path} {r.status_code} — Confidence {has_conf} · 근거 {has_why}")

    # ── 가정 답변 고지 (D-150) — **선언에서 읽는다.** 문구를 여기 박지 않는다 ────
    # 3단계(Feature)에 가정 답변 ③ 에서 파생한 행이 섞여 있으면 판정 줄이 그 사실을 나른다.
    note = assumed.circular_note()
    n_feat = count("EST_CAD_FEATURES")
    n_assumed = n1("select count(*) as n from EST_CAD_FEATURES "
                   "where SOURCE_DESC like %s", (assumed.UNIT_TAG_LIKE,))
    say(f"  가정 선언 {assumed.declaration() or '없음 — ' + (assumed.mismatch() or '')}")
    say(f"  3단계 Feature {n_feat} 행 중 **단위 가정 (D-150) 표지가 붙은 것 {n_assumed} 행** "
        "— 표지 없이 단위만 바뀐 행이 있으면 그것이 거짓 실측이다")
    head = f"{note} · 3단계 Feature {n_feat}행(단위 가정 표지 {n_assumed}행) · " if note else ""
    verdict("G-19", BLOCKED,
            head +
            "5단계 종단 통과 0건 — 1단계(인식)가 501 CAD Parsing 미구성(D-05)에서 멈춘다. "
            f"확정객체 0 → 견적 0 → SHAP 0. 가정 답변은 Autodesk API·YOLOv8 가중치를 주지 "
            f"않으므로 1단계는 **가정으로 열리지 않는다**. 화면 Confidence·근거 표기 "
            f"{sum(found.values())}/{len(found)} 화면")
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-20~G-23 RAG — 폐쇄형 · 로그 100% · 인용 · 환각 · 지연
# ══════════════════════════════════════════════════════════════════════════
class _Spy:
    """LLM 호출 감시자. **불리면 기록**한다 — 근거 0건에서 불리면 G-22 결함이다."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, instructions: str, question: str, context: str) -> str:
        self.calls.append(question)
        return "(QA3 spy) 근거 기반 응답 자리\n근거: 확인된 자료 없음"


def _closed_loop_static() -> list[str]:
    """폐쇄형 정적 검사 — 외부 호출 라이브러리·URL 이 있으면 결함이다."""
    bad: list[str] = []
    # **`urllib.parse` 는 네트워크가 아니다** (D-209) — URL 문자열을 쪼갤 뿐 소켓을
    # 열지 않는다(네트워크는 `urllib.request`·`urllib.error`). 이것까지 막으면 URL
    # 파싱을 손으로 짜게 되고, **열린 리다이렉트 같은 결함이 정확히 그 자리에서** 나온다.
    net = re.compile(r"^\s*(?:import|from)\s+(?:requests|httpx|aiohttp|boto3|openai|socket|urllib\.(?:request|error)|urllib\s*$)",
                     re.M)
    url = re.compile(r"https?://(?!localhost|127\.0\.0\.1)")
    for p in sorted((ROOT / "src" / "kyungdong").rglob("*.py")):
        src = p.read_text()
        rel = p.relative_to(ROOT).as_posix()
        for mod in net.findall(src):
            bad.append(f"{rel}: 외부 통신 모듈 import {mod[1]}")
        if url.search(src):
            bad.append(f"{rel}: 외부 URL 문자열")
    return bad


def gate_20_23(client: TestClient) -> dict[str, Any]:
    say("── G-20~G-23 RAG Agent 3종 (입고 009 · 출하 020 · 통합 038) ────────")
    gs = json.loads(GOLDSET.read_text())
    items = gs["items"]
    corpus = {t: retrieval.corpus_size(t) for t in ("입고", "출하", "통합")}
    for t, c in corpus.items():
        say(f"  말뭉치 {t}: 청크 {c['chunks']} · 문서 {c['docs']} · 임베딩 {c['embedded']} "
            f"· 범위 {c['scope']}")
    say(f"  검색 모드 {settings().search_mode} · LLM {llm.state().badge}")
    say(f"  정답셋 {len(items)} 건 (근거형 {sum(1 for i in items if i['expect']=='evidence')} · "
        f"근거없음형 {sum(1 for i in items if i['expect']=='none')})")

    # 폐쇄형 정적
    closed = _closed_loop_static()
    say(f"  폐쇄형 정적 검사 — 외부 통신 흔적 {len(closed)} 건" +
        ("".join(f"\n     결함 {b}" for b in closed) if closed else " (0건)"))

    log_before = count("AGT_QUERY_LOGS")
    maxid = n1("select coalesce(max(QUERY_ID),0) as n from AGT_QUERY_LOGS")
    say(f"  AGT_QUERY_LOGS 시작 {log_before} 행 (깨끗한 DB 0건이 정상 — G-11)")

    # ── 실행: LLM 을 **구성된 것처럼** 세워 놓고 감시자를 끼운다 ────────
    # 이렇게 해야 "근거 0건이면 LLM 을 부르지 않는다" 가 실제로 검증된다.
    # 미구성 상태에서는 501 이 먼저 나서 호출 여부를 구분할 수 없다.
    spy = _Spy()
    real_state, real_complete = llm.state, llm.complete
    fake = llm.LlmState(True, "(QA3 감시자)", "(QA3 감시자)", "")
    llm.state = lambda: fake                                    # type: ignore[assignment]
    llm.complete = spy                                          # type: ignore[assignment]
    results: list[dict[str, Any]] = []
    try:
        for it in items:
            t0 = time.perf_counter()
            before = len(spy.calls)
            try:
                a = service.ask(it["question"], agent_type=it["agent_type"],
                                user_id=service.resolve_user("SYSADMIN"),
                                role_code="SYSADMIN")
                err = None
            except Exception as e:                              # noqa: BLE001
                a, err = None, e
            results.append({
                "id": it["id"], "expect": it["expect"], "agent": it["agent_type"],
                "q": it["question"], "doc": it.get("expect_doc"),
                "kw": it.get("expect_keywords", []),
                "ans": a, "err": err, "llm_called": len(spy.calls) > before,
                "ms": int((time.perf_counter() - t0) * 1000),
            })
    finally:
        llm.state, llm.complete = real_state, real_complete     # type: ignore[assignment]

    log_after = count("AGT_QUERY_LOGS")
    added = log_after - log_before
    say(f"  질의 {len(items)} 건 실행 → AGT_QUERY_LOGS +{added} 행")

    # ── G-20 폐쇄형 · 로그 100% ───────────────────────────────────────
    say("  ── G-20 폐쇄형 · 질의이력 100% 기록 ──")
    bad20 = list(closed)
    if added != len(items):
        bad20.append(f"질의 {len(items)} 건 중 {added} 건만 기록됐다 — 100% 기록 위반")
    # 기록 내용에 질의·응답·근거·응답시간이 다 있는가
    rows = conn.q("select QUERY_ID, AGENT_TYPE, QUESTION_TEXT, ANSWER_TEXT, REF_DOC_IDS, "
                  "RESPONSE_MS from AGT_QUERY_LOGS where QUERY_ID > %s order by QUERY_ID", (maxid,))
    missing = [r["query_id"] for r in rows
               if not r["question_text"] or not r["answer_text"] or r["response_ms"] is None]
    say(f"     기록 {len(rows)} 행 · 질의/응답/응답시간 누락 {len(missing)} 행")
    if missing:
        bad20.append(f"질의·응답·응답시간이 빈 로그 {len(missing)} 행")
    # Agent 3종이 실제로 다 돌았는가 (009·020·038)
    by_agent = {r["agent_type"] for r in rows}
    say(f"     기록된 Agent 구분 {sorted(by_agent)} (TD5 어휘 입고·출하·통합)")
    if by_agent != {"입고", "출하", "통합"}:
        bad20.append(f"Agent 3종이 다 돌지 않았다: {sorted(by_agent)}")
    # 접근 범위 격리 — 남의 문서가 나오면 폐쇄형 통제 위반
    for s in gs["scope_isolation"]:
        ev, _ = retrieval.search(s["question"], agent_type=s["agent_type"])
        leaked = [e.doc_name for e in ev if e.doc_name == s["forbidden_doc"]]
        say(f"     {s['id']} {s['agent_type']} Agent → 금지문서 {s['forbidden_doc']} 노출 "
            f"{len(leaked)} 건 (기대 0)")
        if leaked:
            bad20.append(f"{s['id']}: {s['agent_type']} Agent 가 {s['forbidden_doc']} 를 반환했다")
    # 화면 3종이 실제로 200 인가
    for path in ("/inv/009", "/shp/020", "/agt/038"):
        r = client.get(path, headers={"x-kyungdong-role": "SYSADMIN"})
        ok = r.status_code == 200 and "폐쇄형" in r.text
        say(f"     {path} {r.status_code} · 폐쇄형 선언 문구 {'있음' if '폐쇄형' in r.text else '**없음**'}")
        if not ok:
            bad20.append(f"{path}: {r.status_code} 또는 폐쇄형 선언 문구 없음")
    verdict("G-20", PASS if not bad20 else FAIL,
            f"외부 검색 0 (외부 통신 import·URL {len(closed)}건) · "
            f"AGT_QUERY_LOGS {added}/{len(items)} = "
            f"{added / len(items):.0%} · Agent 3종 {sorted(by_agent)}" +
            ("" if not bad20 else " · 결함 " + " / ".join(bad20[:3])))

    # ── G-21 인용 정확도 (목표치 없음 D-09 → 실측만) ────────────────────
    say("  ── G-21 인용 정확도 — 목표치가 사업계획서에 없다(D-09). 실측만 적는다 ──")
    ev_items = [r for r in results if r["expect"] == "evidence"]
    top_ok = kw_ok = 0
    for r in ev_items:
        a = r["ans"]
        evs = a.evidence if a is not None else _evidence_of(r["err"])
        top = evs[0].doc_name if evs else None
        hit = top == r["doc"]
        text = " ".join(e.chunk_text for e in evs)
        kws = [k for k in r["kw"] if k in text]
        top_ok += int(hit)
        kw_ok += int(len(kws) == len(r["kw"]))
        if not hit or len(kws) != len(r["kw"]):
            say(f"     {r['id']} top={top} 기대={r['doc']} 핵심어 {len(kws)}/{len(r['kw'])}")
    say(f"     최상위 근거 문서 일치 {top_ok}/{len(ev_items)} · "
        f"핵심어 전량 포함 {kw_ok}/{len(ev_items)}")
    none_items = [r for r in results if r["expect"] == "none"]
    none_zero = sum(1 for r in none_items
                    if not (r["ans"].evidence if r["ans"] is not None else []))
    say(f"     근거없음형 {len(none_items)} 건 중 근거 0건 {none_zero} 건 "
        "(지어낸 출처가 있으면 여기서 0 이 아니다)")
    verdict("G-21", UNDET,
            f"목표치 부재(D-09) — 실측: 최상위 근거 일치 {top_ok}/{len(ev_items)}"
            f" ({top_ok / len(ev_items):.0%}) · 핵심어 전량 포함 {kw_ok}/{len(ev_items)}"
            f" · 근거없음형 {none_zero}/{len(none_items)} 이 근거 0건. 말뭉치 2청크/2문서")

    # ── G-22 환각 방지 ────────────────────────────────────────────────
    say("  ── G-22 환각 방지 — 근거 0건이면 LLM 을 부르지 않는다 ──")
    bad22: list[str] = []
    for r in none_items:
        a = r["ans"]
        refused = a is not None and a.text == "검토 필요 — 근거 부족" and not a.grounded
        handover = bool(a.handover) if a is not None else False
        if r["llm_called"]:
            bad22.append(f"{r['id']}: 근거 0건인데 LLM 이 호출됐다")
        if not refused:
            bad22.append(f"{r['id']}: '검토 필요 — 근거 부족' 이 아니다 "
                         f"({a.text[:30] if a else r['err']})")
        if not handover:
            bad22.append(f"{r['id']}: 담당자 이관 문구가 없다")
    say(f"     근거없음형 {len(none_items)} 건 — LLM 호출 "
        f"{sum(1 for r in none_items if r['llm_called'])} 건 (기대 0) · "
        f"'검토 필요 — 근거 부족' {sum(1 for r in none_items if r['ans'] is not None and r['ans'].text == '검토 필요 — 근거 부족')} 건")
    called = [r["id"] for r in ev_items if r["llm_called"]]
    say(f"     **N건 경로**: 근거형 {len(ev_items)} 건 중 LLM 호출 {len(called)} 건 "
        "(임계 통과분만 호출된다 — 0이면 경로가 죽은 것이다)")
    if not called:
        bad22.append("근거형에서 LLM 호출이 0건이다 — 정상 경로가 검증되지 않았다")
    # 지어낸 출처가 없는가: 응답의 sources 는 실제 검색된 문서명뿐이어야 한다
    invented = 0
    for r in results:
        a = r["ans"]
        if a is None:
            continue
        real = {e.doc_name for e in a.evidence}
        if set(a.sources) - real:
            invented += 1
    say(f"     응답 출처 ⊄ 실제 검색 결과 (지어낸 출처) {invented} 건 (기대 0)")
    if invented:
        bad22.append(f"지어낸 출처 {invented} 건")
    verdict("G-22", PASS if not bad22 else FAIL,
            f"근거 0건 {len(none_items)}건 전부 LLM 미호출·`검토 필요 — 근거 부족`·담당자 이관"
            f" · 근거형 LLM 호출 {len(called)}/{len(ev_items)} · 지어낸 출처 {invented}" +
            ("" if not bad22 else " · 결함 " + " / ".join(bad22[:3])))

    # ── G-23 응답 지연 (목표 없음 D-09 → 실측만) ───────────────────────
    ms = sorted(r["ms"] for r in results)
    p50 = statistics.median(ms)
    p95 = ms[max(0, int(len(ms) * 0.95) - 1)]
    say(f"  ── G-23 응답 지연 실측 — n {len(ms)} · p50 {p50} ms · p95 {p95} ms · "
        f"max {ms[-1]} ms · 설정 타임아웃 {settings().h('RAG_TIMEOUT_SEC').value}초 "
        f"{settings().h('RAG_TIMEOUT_SEC').badge}")
    verdict("G-23", UNDET,
            f"목표 없음(D-09) — 실측 n{len(ms)} p50 {p50}ms p95 {p95}ms max {ms[-1]}ms "
            f"(LLM 미구성 상태의 검색 구간 실측이다 — 생성 지연은 포함되지 않았다)")

    # ── 되돌림 시험 (§10-16) — 임계를 바꾸면 수치가 움직이는가 ─────────
    say("  ── 되돌림 시험: KYUNGDONG_RAG_CONFIDENCE_MIN 을 바꾸면 판정이 움직이는가 ──")
    moved = _reversal_rag(items)
    say(f"     임계별 '근거 부족' 건수: {moved}")
    ok = len(set(moved.values())) > 1
    say(f"     → 움직인다: {ok} (같으면 검사기가 정본 함수를 안 부르는 것이다 — 광성 사업 사고)")
    say()
    return {"results": results, "maxid": maxid, "reversal": moved, "reversal_ok": ok}


def _evidence_of(err: Any) -> list[Any]:
    return []


def _reversal_rag(items: list[dict]) -> dict[str, int]:
    """임계값만 바꿔 다시 재 본다. 로그를 더 만들지 않으려고 `retrieval` 만 부른다."""
    out: dict[str, int] = {}
    orig = os.environ.get("KYUNGDONG_RAG_CONFIDENCE_MIN")
    try:
        for t in ("0.0", "0.70", "0.99"):
            os.environ["KYUNGDONG_RAG_CONFIDENCE_MIN"] = t
            settings.cache_clear()
            thr = settings().h("RAG_CONFIDENCE_MIN").as_float()
            n = 0
            for it in items:
                ev, _ = retrieval.search(it["question"], agent_type=it["agent_type"])
                if not ev or retrieval.confidence(ev) < thr:
                    n += 1
            out[t] = n
    finally:
        if orig is None:
            os.environ.pop("KYUNGDONG_RAG_CONFIDENCE_MIN", None)
        else:
            os.environ["KYUNGDONG_RAG_CONFIDENCE_MIN"] = orig
        settings.cache_clear()
    return out


# ══════════════════════════════════════════════════════════════════════════
# G-24 HITL — 승인 없이 바뀌는 경로 0
# ══════════════════════════════════════════════════════════════════════════
# ── CSRF (D-102 · G-26) ─────────────────────────────────────────────────
# `KYUNGDONG_CSRF_ENFORCE=1` 이면 쓰기에 토큰이 필요하다. 검사기도 **실제 브라우저처럼**
# 화면에서 받은 토큰을 실어 보낸다 — 검사를 우회하거나 면제 목록을 늘리지 않는다.
# 토큰은 경로가 아니라 세션·쿠키에 매인다(util/csrf.py `_bind`) — 세션 하나에 토큰 하나다.
_TOKEN_RE = re.compile(r'name="_csrf"\s+value="([^"]+)"')
_TOKENS: dict[int, str] = {}


def csrf_token_of(client: TestClient) -> str:
    got = _TOKENS.get(id(client))
    if got is None:
        m = _TOKEN_RE.search(client.get("/login").text)
        got = _TOKENS[id(client)] = m.group(1) if m else ""
    return got


def cform(client: TestClient, path: str, form: dict) -> dict:
    """폼에 토큰을 붙인다. 면제 경로(util/csrf.EXEMPT_PATHS)는 그대로 둔다."""
    out = dict(form)
    if csrf.exempt(path) is None:
        tok = csrf_token_of(client)
        if tok:
            out.setdefault(csrf.FORM_FIELD, tok)
    return out


def gate_24(client: TestClient) -> None:
    say("── G-24 HITL — 승인 없이 확정되는 경로 0 ──────────────────────────")
    # ① 정적: 승인 필요 표를 바꾸는 코드 위치를 전부 센다
    hits: list[tuple[str, int, str]] = []
    for d in (ROOT / "src",):
        for p in sorted(d.rglob("*.py")):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                m = WRITE_SQL.search(line)
                if m:
                    hits.append((p.relative_to(ROOT).as_posix(), i, m.group(2).upper()))
    say(f"  ① 승인 필요 표를 바꾸는 코드 위치 {len(hits)} 곳")
    for f, i, t in hits:
        say(f"     {f}:{i}  {t}")
    per_table = {t: sum(1 for _f, _i, x in hits if x == t) for t in APPROVAL_TABLES}
    say(f"     표별: {per_table}")
    no_path = [t for t, n in per_table.items() if n == 0]
    if no_path:
        say(f"     **쓰기 경로가 아예 없는 표**: {no_path} — "
            "'승인 없이 바뀌는 경로 0' 이 구현 부재로 성립한다. 둘을 구분해 적는다")

    # ② 동적: 승인 권한 없는 역할이 확정 엔드포인트를 부르면 403 인가
    say("  ② 동적 — 승인 권한 없는 역할이 확정을 시도하면 403 이어야 한다")
    # kind='approve' → 승인 권한이 필요한 확정 · kind='write' → 등록(승인대기 상태 생성)
    probes = [
        ("POST", "/est/011/review", {"object_id": "999999", "result": "승인"},
         "수주견적AI관리", "approve"),
        ("POST", "/est/012/confirm", {"quote_id": "999999"}, "수주견적AI관리", "approve"),
        ("POST", "/est/013/confirm", {"bom_id": "999999"}, "수주견적AI관리", "approve"),
        ("POST", "/shp/016/approve", {"shipment_id": "999999"}, "출하물류관리", "approve"),
        ("POST", "/api/agent/recommend/999999/adopt", {"decision": "승인"},
         "AI Agent 통합관리", "approve"),
        # SHP_SHIPMENTS 에 행을 만드는 경로 — 확정(SHIP_DT·APPROVER_ID)이 아니라 '승인대기' 생성이다.
        ("POST", "/shp/016", {"lot_trace_id": "999999", "plan_dt": ""},
         "출하물류관리", "write"),
        # SHP_INSPECTIONS 의 유일한 쓰기 경로 — 018 검사결과 등록. 판정은 품질기준이 정하고
        # 검사자는 로그인 계정이다(G-24). 등록 권한 없는 역할은 403 이어야 한다.
        ("POST", "/shp/018", {"lot_trace_id": "999999", "inspect_type": "수압시험",
                              "qstd_id": "999999", "measured_value": "1"},
         "출하물류관리", "write"),
    ]
    bad: list[str] = []
    for method, path, form, area, kind in probes:
        for role in sorted(rbac.roles()):
            approver = rbac.can_approve(role, area)
            writer = rbac.can_write(role, area)
            reader = rbac.can_read(role, area)
            allowed = approver if kind == "approve" else writer
            r = client.request(method, path, data=cform(client, path, form),
                               headers={"x-kyungdong-role": role}, follow_redirects=False)
            got = r.status_code
            if allowed:
                ok = got != 403                     # 권한 있는 역할을 막으면 D-84 재발이다
                want = "403 아님"
            else:
                ok = got == 403
                want = "403" + ("" if reader else " (조회 권한도 없음)")
            mark = "" if ok else "  ** 기대 어긋남"
            say(f"     {path:<34}{kind:<8} {role:<13} 권한 {str(allowed):<5} → {got} "
                f"(기대 {want}){mark}")
            if not ok:
                bad.append(f"{path} as {role}({kind}): {got} (기대 {want})")

    # ③ 확정 상태로 실제 바뀐 행이 있는가 (0건이어야 한다)
    changed = {
        "EST_QUOTATIONS 승인": n1("select count(*) as n from EST_QUOTATIONS "
                                "where QUOTE_STATUS = '승인' and APPROVER_ID is null"),
        "EST_BOM_HEADERS 확정": n1("select count(*) as n from EST_BOM_HEADERS "
                                 "where CONFIRM_YN = 'Y'"),
        "EST_CAD_OBJECTS 확정": n1("select count(*) as n from EST_CAD_OBJECTS "
                                 "where CONFIRM_YN = 'Y'"),
        "EST_OBJECT_REVIEWS": count("EST_OBJECT_REVIEWS"),
        "SHP_SHIPMENTS 승인자없는 확정": n1("select count(*) as n from SHP_SHIPMENTS "
                                     "where SHIP_DT is not null and APPROVER_ID is null"),
        "SHP_INSPECTIONS": count("SHP_INSPECTIONS"),
    }
    say(f"  ③ 승인 흔적 없는 확정 행: {changed}")
    for k, v in changed.items():
        if "승인자없는" in k or "승인" == k.split()[-1]:
            if v:
                bad.append(f"{k} {v} 행 — 승인 기록 없이 확정 상태다")

    verdict("G-24", PASS if not bad else FAIL,
            f"확정 엔드포인트 {len(probes)}개 × 6역할 = {len(probes) * 6} 회 실측, "
            f"기대 어긋남 {len(bad)} 건 · 승인 흔적 없는 확정 행 0 · "
            f"쓰기 경로 없는 표 {no_path or '없음'}" +
            ("" if not bad else " · " + " / ".join(bad[:3])))
    say()


# ══════════════════════════════════════════════════════════════════════════
# G-25 MLOps
# ══════════════════════════════════════════════════════════════════════════
def gate_25() -> None:
    say("── G-25 MLOps — 버전·성능·상태 · 롤백 경로 · Train/Val/Test 분리 ────")
    models = mlreg.models()                          # 정본 함수
    runs = mlreg.train_runs()
    preds = mlreg.predictions()
    splits = mldata.splits()                         # 정본 함수
    dsets = mldata.datasets()
    say(f"  EST_ML_MODELS {len(models)} · EST_ML_TRAIN_RUNS {len(runs)} · "
        f"EST_ML_PREDICTIONS {len(preds)}")
    say(f"  DAT_TRAIN_DATASETS {len(dsets)} · DAT_DATASET_SPLITS {len(splits)} "
        f"(어휘 {mldata.SPLIT_TYPES})")
    for d in dsets:
        cov = mldata.label_coverage(int(d["dataset_id"]))
        say(f"     #{d['dataset_id']} {d['dataset_name']} v{d['dataset_version']} "
            f"총 {d['total_cnt']} 제외 {d['excluded_cnt']} 항목 {d['items']} 분할 {d['splits']} "
            f"· Label {cov['verdict']}")

    # 롤백 경로 — 배포 상태를 되돌리는 **코드**가 있는가.
    # 주석·docstring 의 '롤백' 이라는 낱말은 경로가 아니다 — SQL·함수 정의만 센다.
    dep = re.compile(r"(update\s+EST_ML_MODELS|set\s+DEPLOY_STATUS|"
                     r"def\s+\w*(rollback|deploy|promote)\w*\s*\()", re.I)
    rb: list[str] = []
    for p in sorted((ROOT / "src").rglob("*.py")):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if dep.search(line):
                rb.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    say(f"  롤백·배포상태 전환 코드 위치 {len(rb)} 곳: {rb or '**0곳 — 롤백 경로가 없다**'}")
    write_paths = [p.relative_to(ROOT).as_posix()
                   for p in (ROOT / "src").rglob("*.py")
                   if re.search(r"insert\s+into\s+EST_ML_MODELS", p.read_text(), re.I)]
    say(f"  EST_ML_MODELS 쓰기 경로 {len(write_paths)} 곳: {write_paths or '**0곳**'}")

    # **코드가 있다** 와 **되돌아간다** 는 다른 사실이다. 두 버전을 넣고 정본 함수를 직접 불러
    # v1.0 → v0.9 복귀를 실측한다(§10-16). 학습이 없어 `EST_ML_MODELS` 가 0행이므로 경로를
    # 재려면 검사기가 표본을 만들 수밖에 없다 — **넣은 행은 전부 지운다**(G-11 오염 금지).
    # 이 표본은 **성능 수치가 아니다.** METRIC_JSON 을 비워 두는 이유이고, 이것으로 G-25 를
    # PASS 로 만들지 않는다. 여기서 재는 것은 오직 "되돌아가는가" 하나다.
    rb_ok, rb_note = False, ""
    mark = int(conn.q1("select coalesce(max(MODEL_ID), 0) as n from EST_ML_MODELS")["n"])
    name = "QA3롤백경로실측"
    try:
        for ver, status_, ago in (("v0.9", mlreg.VALIDATED, "1 day"), ("v1.0", mlreg.DEPLOYED, "0 day")):
            conn.x("insert into EST_ML_MODELS "
                   "(MODEL_NAME, MODEL_TYPE, MODEL_VERSION, DEPLOY_STATUS, DEPLOYED_DT, CREATED_DT) "
                   f"values (%s, %s, %s, %s, now() - interval '{ago}', now())",
                   (name, "회귀", ver, status_))
        cur0 = mlreg.deployed_model(name)
        prev0 = mlreg.previous_version(name)
        say(f"  롤백 실측  배포중 {cur0['model_version']} · 직전 {prev0['model_version']} "
            f"(`ml.registry.previous_version()`)")
        out = mlreg.rollback(name)
        after = mlreg.deployed_model(name)
        hist = conn.q("select MODEL_VERSION, DEPLOY_STATUS from EST_ML_MODELS "
                      "where MODEL_NAME = %s order by MODEL_ID", (name,))
        say(f"             `ml.registry.rollback()` → {out['rolled_back_from']} → "
            f"{out['rolled_back_to']} · 되돌린 뒤 배포중 {after['model_version']} "
            f"· 직전 배포본 강등 {out['demoted']}건")
        say(f"             이력 보존: {[(h['model_version'], h['deploy_status']) for h in hist]} "
            "(지우지 않고 상태만 바꾼다)")
        # 되돌릴 곳이 없으면 **성공한 척하지 않는가** (0건 경로 — §10-4)
        try:
            mlreg.rollback("존재하지않는모델_QA3")
            zero_path = "**422 가 아니라 성공했다**"
        except Exception as e:                                    # noqa: BLE001
            zero_path = f"{getattr(e, 'status_code', type(e).__name__)} (되돌릴 것이 없다고 말한다)"
        say(f"             0건 경로: 배포본 없는 모델 롤백 → {zero_path}")
        rb_ok = (after["model_version"] == "v0.9" and out["rolled_back_from"] == "v1.0"
                 and str(zero_path).startswith("422"))
        rb_note = (f"v1.0→v0.9 복귀 실측 {'성공' if rb_ok else '실패'} · "
                   f"없는 모델 롤백 {zero_path}")
    finally:
        n = conn.x("delete from EST_ML_MODELS where MODEL_ID > %s", (mark,))
        say(f"             (실측용 모델 {n} 행 삭제 → EST_ML_MODELS "
            f"{count('EST_ML_MODELS')} 행 · G-11 0건 유지)")

    items = [
        ("모델 버전·성능·상태", len(models) > 0, f"EST_ML_MODELS {len(models)} 행", "분모 0"),
        ("학습 이력", len(runs) > 0, f"EST_ML_TRAIN_RUNS {len(runs)} 행", "분모 0"),
        ("예측 기록", len(preds) > 0, f"EST_ML_PREDICTIONS {len(preds)} 행", "분모 0"),
        ("롤백 경로", rb_ok, f"배포상태 전환 코드 {len(rb)} 곳 · {rb_note}", "코드"),
        ("Train/Val/Test 분리", len(splits) > 0, f"DAT_DATASET_SPLITS {len(splits)} 행", "분모 0"),
    ]
    for nm, ok, m, _kind in items:
        say(f"  {'PASS ' if ok else '미충족'} {nm:<20} {m}")
    unmet = [(nm, kind) for nm, ok, _m, kind in items if not ok]
    data_blocked = [nm for nm, kind in unmet if kind == "분모 0"]
    code_gaps = [nm for nm, kind in unmet if kind != "분모 0"]

    # 판정 (D-91) — 남은 미충족이 **학습 미실시로 분모 0** 인 것뿐이면 `차단` 이다.
    # 롤백처럼 데이터와 무관한 항목이 비면 그것은 구현 결함이라 FAIL 이다.
    # **충족 1/5 을 PASS 로 올리지 않는다** — 차단은 "아직 못 잰다" 지 "통과했다" 가 아니다.
    common = (f"미충족 {len(unmet)}/5 — {', '.join(nm for nm, _ in unmet)}. "
              f"롤백 경로: {rb_note}. "
              "모델·학습·예측·분할은 **학습 미실시로 분모 0** 이다 — 견적 Label 원천(D-04)과 "
              "Train/Val/Test 비율이 정본에 없어 시드하지 않았다(개발3 판단). "
              "합성 라벨로 채우지 않는다(§10-18)")
    if code_gaps:
        verdict("G-25", FAIL, f"{common}. **{', '.join(code_gaps)} 는 데이터 부재와 무관한 "
                              "구현 결함이다**")
    elif data_blocked:
        verdict("G-25", BLOCKED, common)
    else:
        verdict("G-25", PASS, f"5/5 충족 · 롤백 {rb_note}")
    say()


# ══════════════════════════════════════════════════════════════════════════
def cleanup(maxid: int) -> None:
    """이 검사기가 만든 질의 로그를 지운다 — G-11(런타임 전용 표 0건)을 오염시키지 않는다."""
    n = conn.x("delete from AGT_QUERY_LOGS where QUERY_ID > %s", (maxid,))
    say(f"── 정리: AGT_QUERY_LOGS {n} 행 삭제 (검사기가 넣은 것만) → "
        f"현재 {count('AGT_QUERY_LOGS')} 행")


def main() -> int:
    fp0 = fingerprint()
    say("tools/check_ai.py — G-14~G-25 (QA3)")
    say(f"DSN {settings().pg_dsn} · ENV {settings().env}")
    say()
    client = TestClient(app, raise_server_exceptions=False)

    gate_14()
    gate_15_18()
    gate_19(client)
    rag = gate_20_23(client)
    gate_24(client)
    gate_25()
    cleanup(rag["maxid"])

    fp1 = fingerprint()
    if fp0 != fp1:
        say()
        say("**측정 중 소스가 바뀌었다 — 이 회차 판정은 전부 `판정 불가` 다 (§10-17)**")
        for i, (g, _v, m) in enumerate(VERDICTS):
            VERDICTS[i] = (g, UNDET, f"동시 변경 감지 — {m}")

    say()
    say("═══ 판정 ═══")
    for g, v, m in VERDICTS:
        say(f"{g} {v} — {m}")
    say()
    say(f"PASS {sum(1 for _g, v, _m in VERDICTS if v == PASS)} · "
        f"FAIL {sum(1 for _g, v, _m in VERDICTS if v == FAIL)} · "
        f"차단 {sum(1 for _g, v, _m in VERDICTS if v == BLOCKED)} · "
        f"판정 불가 {sum(1 for _g, v, _m in VERDICTS if v == UNDET)} / {len(VERDICTS)}")
    return 0 if all(v == PASS for _g, v, _m in VERDICTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
