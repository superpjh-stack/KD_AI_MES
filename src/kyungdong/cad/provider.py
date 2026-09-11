"""인식 공급자 추상화 (D-05) — 미구성이면 **501**, 조용한 합성 금지.

TD5 `EST_CAD_OBJECTS.DETECT_METHOD` 가 정한 두 방식이다.

  · `Parsing(Autodesk API)`  — 도면 엔티티 파싱
  · `Vision(YOLOv8+OCR)`     — 이미지 객체 탐지 + 치수문자 인식

두 공급자 모두 **자격정보·가중치가 확인되지 않았다.** 그래서 기본 구현은
`available = False` 이고 호출하면 `501 CAD Parsing 미구성 (D-05)` 을 던진다.
구성이 들어오면 `.env` `KYUNGDONG_CAD_PARSER` · `KYUNGDONG_CAD_VISION_MODEL` 로 켠다.

**대체 구현을 몰래 끼워 넣지 않는다.** 값이 없으면 화면이 그 사실을 보여야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..app.settings import settings
from ..app.util import http

PARSING = "Parsing(Autodesk API)"
VISION = "Vision(YOLOv8+OCR)"

# TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 비고 — 이 어휘만 쓴다
OBJECT_TYPES: tuple[str, ...] = ("홀", "슬롯", "노즐", "플랜지", "치수문자")
CROSS_CHECK = ("일치", "불일치")


@dataclass(frozen=True)
class DetectedObject:
    object_type: str
    pos_x: float | None = None
    pos_y: float | None = None
    dimension_value: float | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class Availability:
    method: str
    configured: bool
    reason: str
    setting_key: str

    @property
    def badge(self) -> str:
        return "구성됨" if self.configured else "CAD Parsing 미구성 (D-05)"


class Detector(Protocol):
    method: str

    def available(self) -> Availability: ...

    def detect(self, file_path: str) -> list[DetectedObject]: ...


class _Unconfigured:
    """미구성 공급자 — 부르면 **501**. 빈 리스트를 돌려주지 않는다(그건 '0건 인식'과 구분이 안 된다)."""

    def __init__(self, method: str, reason: str, key: str) -> None:
        self.method, self._reason, self._key = method, reason, key

    def available(self) -> Availability:
        return Availability(self.method, False, self._reason, self._key)

    def detect(self, file_path: str) -> list[DetectedObject]:
        raise http.fail("cad_unconfigured", f"{self.method}: {self._reason}")


class AutodeskDetector:
    """`KYUNGDONG_CAD_PARSER=autodesk` 일 때 쓰는 자리. **자격정보가 확인되지 않았다.**"""

    method = PARSING

    def available(self) -> Availability:
        return Availability(
            self.method, False,
            "Autodesk API 계정·자격정보 미확보 — 실 연동은 계정 발급 후 (D-05)",
            "KYUNGDONG_CAD_PARSER",
        )

    def detect(self, file_path: str) -> list[DetectedObject]:
        raise http.fail("cad_unconfigured", self.available().reason)


class YoloDetector:
    """`KYUNGDONG_CAD_VISION_MODEL` 가중치 경로가 들어오면 쓰는 자리. **가중치가 없다.**"""

    method = VISION

    def available(self) -> Availability:
        return Availability(
            self.method, False,
            "YOLOv8 가중치·OCR 엔진 미확보 — 학습 후 경로 지정 (D-05)",
            "KYUNGDONG_CAD_VISION_MODEL",
        )

    def detect(self, file_path: str) -> list[DetectedObject]:
        raise http.fail("cad_unconfigured", self.available().reason)


def parsing_detector() -> Detector:
    s = settings()
    if s.cad_parser == "autodesk":
        return AutodeskDetector()
    return _Unconfigured(
        PARSING,
        "KYUNGDONG_CAD_PARSER 미설정 — .dwg 는 바이너리라 파서 없이 읽을 수 없다 (D-05)",
        "KYUNGDONG_CAD_PARSER",
    )


def vision_detector() -> Detector:
    if settings().cad_vision_model:
        return YoloDetector()
    return _Unconfigured(
        VISION,
        "KYUNGDONG_CAD_VISION_MODEL 미설정 — 가중치 없이 객체를 만들지 않는다 (D-05)",
        "KYUNGDONG_CAD_VISION_MODEL",
    )


def availability() -> list[Availability]:
    """화면 010·011 상단 배지용. **미구성 사실을 숨기지 않는다.**"""
    return [parsing_detector().available(), vision_detector().available()]


def configured() -> bool:
    return all(a.configured for a in availability())
