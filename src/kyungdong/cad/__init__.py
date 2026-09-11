"""CAD 파이프라인 (MES-TD4-010·011·048) — **없는 것을 있는 척하지 않는다 (D-05).**

Autodesk API 계정 · YOLOv8 가중치 · OCR 엔진이 **미확보**다. `.dwg` 는 바이너리다.
그래서 인식 단계는 공급자 인터페이스로만 두고, 미구성이면 **501 `CAD Parsing 미구성 (D-05)`**
또는 화면 명시 배지를 낸다. **조용히 합성 Feature 를 만들어 정상인 척하면 결함이다.**

5단계 (화면 010 → 011 → 012·013 → 014 → 015)
  ① `IF_CAD_FILES` 업로드·배치 → Parsing + Vision 병렬 → `EST_CAD_OBJECTS`
  ② **HITL 검증** → `EST_OBJECT_REVIEWS` (사람이 승인하기 전에는 확정이 아니다)
  ③ `EST_CAD_FEATURES` → BOM
  ④ 견적
  ⑤ SHAP
"""
from __future__ import annotations

import sys
from pathlib import Path

_DB = str(Path(__file__).resolve().parents[3] / "db")
if _DB not in sys.path:
    sys.path.insert(0, _DB)
