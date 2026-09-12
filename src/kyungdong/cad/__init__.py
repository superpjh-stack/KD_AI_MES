"""CAD 파이프라인 (MES-TD4-010·011·048) — **없는 것을 있는 척하지 않는다 (D-05).**

Autodesk API 계정 · YOLOv8 가중치 · OCR 엔진이 **미확보**다. 그래서 인식 단계는 공급자
인터페이스로만 두고, 미구성이면 **501 `CAD Parsing 미구성 (D-05)`** 또는 화면 명시 배지를 낸다.
**조용히 합성 Feature 를 만들어 정상인 척하면 결함이다.**

**형상 실측은 별개 경로로 풀렸다** — `.dxf` 는 group code 로 그대로 읽고(`dxf.py` · D-110-b),
`.dwg` 는 `dwg2dxf` 로 바꿔 그 파서에 먹인다(`dwgconv.py` · D-123 — 서로 다른 도면 1,136건 중
781건 파싱 성공). **그래도 인식(객체 탐지)은 여전히 미구성이다** — 기하 집계와 정답 라벨 대비
탐지 정확도(G-14)는 다른 일이고, 정답 라벨은 0건이다.

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
