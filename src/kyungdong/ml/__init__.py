"""ML (MES-TD4-014·015·037) — **이번 회전에 학습하지 않는다.**

학습이 있는 회전은 단독으로 돈다(goal.md §10-2). 이번 회전은 **수집 · RAG · 화면 골격**까지다.
그래서 여기에는 **읽기 경로와 차단 사유만** 둔다 — 성능 수치를 만들지 않는다.

차단 사유(지어내지 않고 그대로 적는다)
  · **D-04** 과거 견적금액·실제 제조원가 Label 확보 여부가 확인되지 않았다 →
    견적 정확도(±5%)·BOM 정확도(85%)·납기 예측(85%)은 **측정 불가**다.
  · **D-05** Autodesk API·YOLOv8 가중치 미확보 → 도면 객체 인식 학습·평가 불가.
  · **D-13** 설명가능성 전문가 평가 변수 목록이 없다 → SHAP 일치율 **차단**.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DB = str(Path(__file__).resolve().parents[3] / "db")
if _DB not in sys.path:
    sys.path.insert(0, _DB)

TRAINING_DEFERRED = "학습 미실시 — 다음 단독 회전 (goal.md §10-2)"
