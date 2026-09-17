"""인식 공급자 추상화 (D-05 · D-235) — 미구성이면 **501**, 조용한 합성 금지.

TD5 `EST_CAD_OBJECTS.DETECT_METHOD` 가 정한 두 방식이다.

  · `Parsing(Autodesk API)`  — 도면 엔티티 파싱
  · `Vision(YOLOv8+OCR)`     — 이미지 객체 탐지 + 치수문자 인식

**Parsing 은 Autodesk API 없이도 된다 (D-235).** `dwg2dxf`(GNU libredwg, D-123)로 변환한 DXF 를
`cad/dxf.py` 가 group code 로 읽는다 — 그 실측 파서를 `KYUNGDONG_CAD_PARSER=dxf` 로 인식 공급자에
붙인 것이 `DxfDetector` 다. 방식 라벨은 **실제 엔진 이름**을 쓴다(`Parsing(dwg2dxf+DXF)`).
Autodesk API 를 쓰지 않는데 `Parsing(Autodesk API)` 라고 적으면 그것이 지어낸 값이다.

Vision(YOLOv8+OCR) 은 **여전히 미구성**이다 — 가중치·OCR 엔진이 없다(D-05). 그래서
Parsing↔Vision 정합성 검증(`CROSS_CHECK_RESULT`)은 만들 수 없고 NULL 로 남는다.

값이 없으면 화면이 그 사실을 보여야 한다. **대체 구현을 몰래 끼워 넣지 않는다.**
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..app.settings import settings
from ..app.util import http
from . import archive, dwgconv, dxf

PARSING = "Parsing(Autodesk API)"
PARSING_DXF = "Parsing(dwg2dxf+DXF)"       # 실제 엔진 (D-235). VARCHAR(30) 안이다
VISION = "Vision(YOLOv8+OCR)"

# TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 비고 — 이 어휘만 쓴다
OBJECT_TYPES: tuple[str, ...] = ("홀", "슬롯", "노즐", "플랜지", "치수문자")
CROSS_CHECK = ("일치", "불일치")

# `.env` KYUNGDONG_CAD_PARSER 가 인정하는 값. 이 밖의 값은 미구성이고 그 사실을 사유에 적는다.
PARSER_VALUES: tuple[str, ...] = ("dxf", "autodesk")


@dataclass(frozen=True)
class DetectedObject:
    object_type: str
    pos_x: float | None = None
    pos_y: float | None = None
    dimension_value: float | None = None
    confidence: float | None = None       # Parsing 은 결정적이라 IoU 신뢰도가 없다 → None (D-235)


@dataclass(frozen=True)
class Availability:
    method: str
    configured: bool
    reason: str
    setting_key: str

    @property
    def badge(self) -> str:
        return (f"{self.method} 구성됨" if self.configured
                else "CAD Parsing 미구성 (D-05)")


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


class DxfDetector:
    """`KYUNGDONG_CAD_PARSER=dxf` — dwg2dxf 변환 + `cad/dxf.py` group code 파싱 (D-123 · D-235).

    내는 객체는 **엔티티에서 바로 나오는 두 종류**뿐이다.
      · `홀`      ← CIRCLE 전량. 중심(10·20)과 지름(2r). 무엇이 홀이고 무엇이 계기 버블·중심선인지
                    가르는 기준이 도입기업 자료에 없어 **지름 필터를 걸지 않는다**(D-110-b) —
                    그 판정이 HITL(011)의 몫이다.
      · `치수문자` ← DIMENSION 전량. 위치는 문자 중점(11·21), 치수값은 group 42 가 양수일 때만.
    `슬롯`·`노즐`·`플랜지` 는 **형상 의미 판정**이라 파싱만으로 만들 수 없다 — 내지 않는다.
    신뢰도는 **None** 이다: 결정적 파싱에는 IoU 기반 신뢰도가 없고, 지어내지 않는다.

    변환·파싱 실패는 **422** 다(입력 문제) — 501(미구성)과 섞지 않는다.
    `.cad` 는 DWG 서명(AC1xxx)이 아니어서 dwg2dxf 의 대상이 아니다 → 422 로 그 사실을 적는다.
    """

    method = PARSING_DXF

    def available(self) -> Availability:
        if not dwgconv.available():
            return Availability(self.method, False,
                                "KYUNGDONG_CAD_PARSER=dxf 인데 `dwg2dxf` 가 없다 — "
                                "`brew install libredwg` (D-123). 변환기 없이는 DWG 를 못 읽는다",
                                "KYUNGDONG_CAD_PARSER")
        return Availability(
            self.method, True,
            f"dwg2dxf({dwgconv.version() or '버전 미상'}) 변환 + cad/dxf.py group code 파싱 (D-123 · D-235). "
            "객체 유형은 홀(CIRCLE)·치수문자(DIMENSION) 2종 · 신뢰도 없음 · Vision 미구성이라 정합성 검증 없음",
            "KYUNGDONG_CAD_PARSER",
        )

    @staticmethod
    def resolve(file_path: str) -> Path:
        """`EST_CAD_DRAWINGS.FILE_PATH` 는 아카이브 루트 기준 상대경로일 수 있다(D-03·D-109)."""
        p = Path(file_path)
        if p.is_file():
            return p
        alt = archive.archive_root() / file_path
        if alt.is_file():
            return alt
        raise http.fail("validation",
                        f"원본 파일이 없다: {file_path} (아카이브 루트 {archive.archive_root()} "
                        "기준으로도 못 찾았다 — D-109)")

    def measure(self, file_path: str) -> tuple[dxf.DxfMeasure, dwgconv.Converted | None]:
        av = self.available()
        if not av.configured:
            raise http.fail("cad_unconfigured", f"{self.method}: {av.reason}")
        path = self.resolve(file_path)
        ext = path.suffix.lower().lstrip(".")
        if ext == "dxf":
            m, conv = dxf.parse(path), None
        elif ext == "dwg":
            m, conv = dwgconv.measured(path)
            if m is None:
                raise http.fail("validation",
                                f"dwg2dxf 변환 실패 — 실패는 실패로 센다 (D-123): {conv.reason} "
                                f"[서명 {conv.sig}]")
        else:
            raise http.fail("validation",
                            f"'.{ext}' 는 dwg2dxf 의 대상이 아니다 — DWG 서명(AC1xxx)이 아닌 독자 포맷 "
                            "(D-05 · D-123). `.cad` 325건은 앞 6바이트가 V10.00/V15.00 이다")
        if m.error:
            raise http.fail("validation", f"DXF 읽기 실패: {m.error}")
        return m, conv

    def detect(self, file_path: str) -> list[DetectedObject]:
        m, _conv = self.measure(file_path)
        out: list[DetectedObject] = []
        for cx, cy, r in m.circles:
            out.append(DetectedObject("홀", cx, cy, round(r * 2.0, 4), None))
        # 반지름·중심이 없어 `circles` 에 못 들어간 CIRCLE 도 홀 개수에는 있다 — 위치 없이 낸다
        for _ in range(m.holes - len(m.circles)):
            out.append(DetectedObject("홀", None, None, None, None))
        for x, y, v in m.dimensions:
            out.append(DetectedObject("치수문자", x, y, v, None))
        return out


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
    v = (s.cad_parser or "").strip().lower()
    if v == "dxf":
        return DxfDetector()
    if v == "autodesk":
        return AutodeskDetector()
    if v:
        return _Unconfigured(
            PARSING,
            f"KYUNGDONG_CAD_PARSER={s.cad_parser!r} 는 모르는 값이다 — {PARSER_VALUES} 중 하나 (D-05 · D-235)",
            "KYUNGDONG_CAD_PARSER",
        )
    return _Unconfigured(
        PARSING,
        "KYUNGDONG_CAD_PARSER 미설정 — .dwg 는 바이너리라 파서 없이 읽을 수 없다 (D-05). "
        "`dxf` 로 두면 dwg2dxf 변환 파서가 붙는다 (D-235)",
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


def parsing_configured() -> bool:
    return parsing_detector().available().configured


def configured() -> bool:
    """Parsing·Vision **둘 다** 구성됐는가 — 정합성 검증까지 가능한 상태."""
    return all(a.configured for a in availability())
