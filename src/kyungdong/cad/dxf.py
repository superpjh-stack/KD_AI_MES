"""DXF 실측 파서 (D-110-b) — **외부 라이브러리 없이 group code 로 읽는다.**

`.dwg` · `.cad` 는 바이너리라 변환기 없이 못 읽는다(D-05). 그러나 **`.dxf` 는 순수 텍스트**다.
group code(짝수 줄) / 값(홀수 줄) 짝을 그대로 읽으면 엔티티가 나온다 — Autodesk API 도
OCR 도 필요 없다. D-05 가 "5종 전부 차단" 이라고 적은 것은 **.dwg 에는 맞고 .dxf 에는 틀리다.**

**표본을 숨기지 않는다.** 원본 아카이브 CAD 파일 **3,299건**(dwg 2,240 · cad 1,030 · dxf 29)
중 이 파서가 읽는 것은 **dxf 29건(0.9%)** 이고, 그 29건도 내용 해시로 복사본을 걷어내면
**서로 다른 도면 9건**뿐이다. 이 숫자로 G-14(CAD 객체 인식 80%)를 주장하지 않는다.

산출 규칙 (전부 실측 · 추정 없음)
  · **홀 수량**  = `CIRCLE` 엔티티 개수. **지름 필터를 걸지 않는다** — 무엇이 홀이고 무엇이
    계기 버블·중심선인지 가르는 기준이 도입기업 자료에 없다(D-05). 그래서 `holes` 는
    "원 전량" 이라는 뜻이고, 지름 분포(`circle_diameters`)를 함께 돌려준다.
  · **총 절단장** = LINE 길이합 + ARC 호길이(r·Δθ) + (LW)POLYLINE 구간합.
  · **판재 면적** = **닫힌** (LW)POLYLINE 의 shoelace 면적 합.
  · **재질·두께** = TEXT/MTEXT 문자열의 표제란 패턴. 정규식과 적중률을 `MATERIAL_RE`·
    `THICKNESS_RE` 와 `parse()` 결과에 그대로 남긴다.

**세지 못하는 것을 센 척하지 않는다**
  · `INSERT` 가 참조하는 `BLOCK` 내부 형상은 **전개하지 않는다.** 블록이 여러 번 삽입되면
    그만큼 길이·개수가 **적게** 나온다. `blocks`·`inserts` 를 함께 돌려주니 그 사실이 보인다.
  · 단위는 DXF `$INSUNITS` 를 읽지만 없는 파일이 많다 — 없으면 `None` 이고 길이는 **도면 단위**다.
    mm 라고 단정하지 않는다.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ── TD5 `EST_CAD_FEATURES.FEATURE_TYPE` 어휘와 같은 이름을 쓴다 ──────────────
F_HOLES = "홀 수량"
F_CUTLEN = "총 절단장"
F_AREA = "판재 면적"
F_THICK = "두께"
F_MATERIAL = "재질"

SOURCE_TAG = "DXF 실측"          # `EST_CAD_FEATURES.SOURCE_DESC` 접두 — 합성과 구분한다
UNKNOWN_UOM = "도면단위"          # `$INSUNITS` 가 없을 때의 단위 이름. mm 라고 단정하지 않는다

# 표제란 재질 표기. 실제 원본에서 관측된 것만 넣는다(STS304·STS316·SUS316·A240 …).
# 새 표기를 만나면 여기 추가하고 **적중률을 다시 잰다** — 정규식을 넓혀 적중률을 만들지 않는다.
MATERIAL_RE = re.compile(
    r"\b("
    r"S(?:US|TS)\s?-?\s?\d{3}\s?[A-Z]?L?"      # SUS304 · STS316L · STS 304
    r"|SS\d{3}|SM\d{2}[A-C]|SPCC|SGCC|SS400"
    r"|A\s?240(?:\s?-?\s?\d{3}[A-Z]?L?)?"      # ASTM A240 / A240-304
    r"|A\s?516(?:\s?GR\s?\d{2})?"
    r"|AL\d{4}|ALUMINI?U?M"
    r"|CARBON\s*STEEL|MILD\s*STEEL"
    r")\b",
    re.I,
)
# 두께. `t=6` · `T6` · `10T` · `THK 8` · `두께 6`. **단위 없는 맨 숫자는 잡지 않는다.**
THICKNESS_RE = re.compile(
    r"(?:"
    r"\b(?:t|T|THK|THICK(?:NESS)?|두께)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*(?:mm|MM|㎜)?\b"
    r"|\b(\d+(?:\.\d+)?)\s*[tT]\b"             # 10T · 3t
    r")"
)

# `$INSUNITS` → 이름. 없으면 판정하지 않는다.
INSUNITS = {0: None, 1: "inch", 2: "feet", 4: "mm", 5: "cm", 6: "m"}

# $DWGCODEPAGE → 파이썬 인코딩. 못 읽으면 순서대로 시도한다.
_CODEPAGE = {"ANSI_949": "cp949", "ANSI_1252": "cp1252", "ANSI_932": "cp932",
             "ANSI_936": "gbk", "UTF8": "utf-8"}
_TRY_ENCODINGS = ("utf-8", "cp949", "cp1252", "latin-1")


@dataclass
class DxfMeasure:
    """한 DXF 파일의 **실측**. 못 잰 값은 `None` 이고 0 으로 채우지 않는다."""

    path: str
    encoding: str
    entities: dict[str, int] = field(default_factory=dict)   # ENTITIES 섹션 엔티티별 개수
    block_entities: dict[str, int] = field(default_factory=dict)  # BLOCKS 섹션 (전개하지 않음)
    holes: int = 0                       # CIRCLE 전량 — 지름 필터 없음
    circle_diameters: list[float] = field(default_factory=list)
    # CIRCLE 의 (중심x, 중심y, 반지름) — group code 10·20·40 을 **읽던 그대로** 담는다.
    # 박스를 만들지 않는다: 박스가 필요한 쪽(G-14 라벨셋)이 [x-r, y-r, x+r, y+r] 로 만든다.
    circles: list[tuple[float, float, float]] = field(default_factory=list)
    line_len: float = 0.0
    arc_len: float = 0.0
    poly_len: float = 0.0
    closed_area: float = 0.0
    closed_polys: int = 0
    texts: list[str] = field(default_factory=list)
    material: str | None = None
    material_hits: dict[str, int] = field(default_factory=dict)
    thickness: float | None = None
    thickness_hits: dict[str, int] = field(default_factory=dict)
    insunits: str | None = None
    inserts: int = 0
    blocks: int = 0
    error: str | None = None

    @property
    def cut_len(self) -> float:
        return self.line_len + self.arc_len + self.poly_len

    @property
    def uom(self) -> str:
        """길이 단위. `$INSUNITS` 가 없으면 '도면단위' 다 — mm 라고 단정하지 않는다."""
        return self.insunits or UNKNOWN_UOM

    def features(self) -> list[dict[str, object]]:
        """`EST_CAD_FEATURES` 행 후보. **뽑지 못한 것은 넣지 않는다**(0 으로 채우지 않는다).

        `재질` 은 문자열이라 `FEATURE_VALUE NUMERIC(16,4)` 에 담을 자리가 없다 —
        값이 있어도 `value=None` 으로 돌려주고 `text` 에 담는다. 호출자가 그 사실을 적는다.
        """
        out: list[dict[str, object]] = []
        n = sum(self.entities.values())
        if n == 0:
            return out
        if "CIRCLE" in self.entities:
            out.append({
                "type": F_HOLES, "value": float(self.holes), "uom": "ea", "text": None,
                "source": (f"{SOURCE_TAG} — CIRCLE 엔티티 {self.holes}개 전량. "
                           "지름 필터 기준이 도입기업 자료에 없어 걸지 않았다 (D-110-b)"),
            })
        if self.cut_len > 0:
            out.append({
                "type": F_CUTLEN, "value": round(self.cut_len, 4), "uom": self.uom, "text": None,
                "source": (f"{SOURCE_TAG} — LINE {round(self.line_len, 1)} + "
                           f"ARC {round(self.arc_len, 1)} + POLYLINE {round(self.poly_len, 1)}. "
                           f"BLOCK 내부 형상 미전개(INSERT {self.inserts}회) — 과소 계상 (D-110-b)"),
            })
        if self.closed_polys:
            out.append({
                "type": F_AREA, "value": round(self.closed_area, 4), "uom": f"{self.uom}²",
                "text": None,
                "source": (f"{SOURCE_TAG} — 닫힌 POLYLINE {self.closed_polys}개 shoelace 면적합 "
                           "(D-110-b)"),
            })
        if self.thickness is not None:
            out.append({
                "type": F_THICK, "value": float(self.thickness), "uom": "mm", "text": None,
                "source": (f"{SOURCE_TAG} — TEXT/MTEXT 표제란 정규식 적중 {self.thickness_hits} "
                           "중 최빈값 (D-110-b)"),
            })
        if self.material is not None:
            out.append({
                "type": F_MATERIAL, "value": None, "uom": None, "text": self.material,
                "source": (f"{SOURCE_TAG} — TEXT/MTEXT 표제란 정규식 적중 {self.material_hits} "
                           "중 최빈값. `FEATURE_VALUE` 가 NUMERIC 이라 적재할 자리가 없다 (D-110-b)"),
            })
        return out


def _decodes(path: Path, enc: str) -> bool:
    """**파일 전체**가 그 인코딩으로 깨지지 않고 읽히는가. 앞부분만 보고 판정하지 않는다 —
    145MB DXF 는 앞 64KB 가 ASCII 라 무엇으로든 읽히는 것처럼 보인다(D-115 의 재발 방지)."""
    import codecs

    dec = codecs.getincrementaldecoder(enc)()
    try:
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                dec.decode(chunk)
            dec.decode(b"", final=True)
    except (UnicodeDecodeError, LookupError):
        return False
    return True


def detect_encoding(path: Path | str) -> str:
    """인코딩 판정. **UTF-8 검증을 먼저 한다** — UTF-8 로 전부 읽히면 그건 UTF-8 이다
    (엄격한 검증이라 우연히 통과할 확률이 낮다). 아니면 `$DWGCODEPAGE` 선언을 따르고,
    그것도 안 되면 후보를 차례로 시도한다. 마지막 `latin-1` 은 절대 실패하지 않는 바닥이다."""
    p = Path(path)
    if _decodes(p, "utf-8"):
        return "utf-8"
    head = p.open("rb").read(65536)
    m = re.search(rb"\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*([A-Za-z0-9_]+)", head)
    if m:
        enc = _CODEPAGE.get(m.group(1).decode("ascii", "replace").upper())
        if enc and enc != "utf-8" and _decodes(p, enc):
            return enc
    for enc in _TRY_ENCODINGS:
        if enc != "utf-8" and _decodes(p, enc):
            return enc
    return "latin-1"


def _pairs(path: Path, encoding: str) -> Iterator[tuple[str, str]]:
    """(group code, 값) 짝을 **스트리밍**으로 읽는다 — 145MB 파일도 메모리에 올리지 않는다."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        while True:
            code = f.readline()
            if not code:
                return
            val = f.readline()
            if not val:
                return
            yield code.strip(), val.rstrip("\r\n")


def _f(v: str) -> float | None:
    try:
        return float(v.strip())
    except (TypeError, ValueError):
        return None


def _shoelace(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def parse(path: Path | str, *, encoding: str | None = None) -> DxfMeasure:
    """DXF 한 파일을 읽어 실측한다. **읽다 실패하면 `error` 에 적고 조용히 0 을 돌려주지 않는다.**"""
    p = Path(path)
    enc = encoding or detect_encoding(p)
    m = DxfMeasure(path=str(p), encoding=enc)
    section: str | None = None
    kind: str | None = None            # 지금 읽고 있는 엔티티 이름
    hvar: str | None = None            # HEADER 섹션에서 읽고 있는 변수 이름 ($INSUNITS 등)
    g: dict[int, list[float]] = {}     # 수치 group code → 값들 (10,20,11,21,40,50,51,70,90)
    texts: list[str] = []
    poly_pts: list[tuple[float, float]] = []
    poly_closed = False
    in_polyline = False

    def flush() -> None:
        """현재 엔티티 하나를 집계에 반영한다."""
        nonlocal poly_pts, poly_closed, in_polyline
        if kind is None:
            return
        bucket = m.entities if section == "ENTITIES" else m.block_entities
        bucket[kind] = bucket.get(kind, 0) + 1
        if section != "ENTITIES":
            # BLOCKS 섹션은 **템플릿**이다. 삽입 횟수를 모르므로 길이·개수에 더하지 않는다.
            return
        if kind == "LINE":
            x1, y1 = (g.get(10) or [None])[0], (g.get(20) or [None])[0]
            x2, y2 = (g.get(11) or [None])[0], (g.get(21) or [None])[0]
            if None not in (x1, y1, x2, y2):
                m.line_len += math.hypot(x2 - x1, y2 - y1)
        elif kind == "ARC":
            r = (g.get(40) or [None])[0]
            a1, a2 = (g.get(50) or [None])[0], (g.get(51) or [None])[0]
            if r is not None and a1 is not None and a2 is not None:
                sweep = (a2 - a1) % 360.0
                m.arc_len += abs(r) * math.radians(sweep)
        elif kind == "CIRCLE":
            r = (g.get(40) or [None])[0]
            cx, cy = (g.get(10) or [None])[0], (g.get(20) or [None])[0]
            m.holes += 1
            if r is not None:
                m.circle_diameters.append(abs(r) * 2.0)
                if cx is not None and cy is not None:
                    m.circles.append((cx, cy, abs(r)))
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            flags = int((g.get(70) or [0.0])[0])
            closed = bool(flags & 1)
            if kind == "LWPOLYLINE":
                xs, ys = g.get(10) or [], g.get(20) or []
                pts = list(zip(xs, ys))
                _add_poly(m, pts, closed)
            else:
                in_polyline, poly_closed, poly_pts = True, closed, []
        elif kind == "VERTEX" and in_polyline:
            x, y = (g.get(10) or [None])[0], (g.get(20) or [None])[0]
            if x is not None and y is not None:
                poly_pts.append((x, y))
        elif kind == "SEQEND" and in_polyline:
            _add_poly(m, poly_pts, poly_closed)
            in_polyline, poly_pts, poly_closed = False, [], False
        elif kind == "INSERT":
            m.inserts += 1
        elif kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            m.texts.extend(texts)

    try:
        for code, val in _pairs(p, enc):
            if code == "0":
                flush()
                g, texts, hvar = {}, [], None
                if val == "SECTION":
                    section, kind = "?", None
                    continue
                if val == "ENDSEC":
                    section, kind = None, None
                    continue
                if val == "BLOCK":
                    m.blocks += 1
                kind = val
                continue
            if code == "2" and section == "?":
                section, kind = val.strip(), None
                continue
            if section == "HEADER":
                # HEADER 변수 — 다음 값 줄이 변수값이다. `$INSUNITS` 만 본다.
                # **엔티티 이름(`kind`)과 섞지 않는다** — 섞으면 HEADER 변수가 엔티티로 세어진다.
                # **HEADER 밖에서는 이 가지에 들어오지 않는다** — 안 그러면 LWPOLYLINE 의
                # group code 70(닫힘 플래그)이 `$INSUNITS` 로 읽혀 도면이 열린 것으로 뒤집힌다.
                if code == "9":
                    hvar = val.strip()
                    continue
                if hvar == "$INSUNITS" and code == "70":
                    v = _f(val)
                    if v is not None:
                        m.insunits = INSUNITS.get(int(v))
                continue
            if code in ("1", "3") and kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                texts.append(val)
                continue
            c = int(code) if code.lstrip("-").isdigit() else None
            if c in (10, 20, 11, 21, 40, 50, 51, 70, 90):
                v = _f(val)
                if v is not None:
                    g.setdefault(c, []).append(v)
        flush()
    except OSError as e:                       # 조용히 삼키지 않는다 (§10-9)
        m.error = f"{type(e).__name__}: {e}"
        return m

    _title_block(m)
    return m


def _add_poly(m: DxfMeasure, pts: list[tuple[float, float]], closed: bool) -> None:
    if len(pts) < 2:
        return
    seq = pts + [pts[0]] if closed else pts
    m.poly_len += sum(math.hypot(seq[i + 1][0] - seq[i][0], seq[i + 1][1] - seq[i][1])
                      for i in range(len(seq) - 1))
    if closed and len(pts) >= 3:
        m.closed_polys += 1
        m.closed_area += _shoelace(pts)


def _title_block(m: DxfMeasure) -> None:
    """TEXT/MTEXT 에서 재질·두께를 찾는다. **최빈값**을 고르고 적중 분포를 남긴다."""
    mats: dict[str, int] = {}
    thks: dict[str, int] = {}
    for raw in m.texts:
        t = unicodedata.normalize("NFC", raw)
        for hit in MATERIAL_RE.finditer(t):
            key = re.sub(r"[\s\-]", "", hit.group(1)).upper()
            mats[key] = mats.get(key, 0) + 1
        for hit in THICKNESS_RE.finditer(t):
            v = hit.group(1) or hit.group(2)
            if v is None:
                continue
            f = _f(v)
            if f is None or not (0.1 <= f <= 500.0):   # 도면 두께로 있을 수 없는 값은 버린다
                continue
            k = f"{f:g}"
            thks[k] = thks.get(k, 0) + 1
    m.material_hits, m.thickness_hits = mats, thks
    if mats:
        m.material = max(mats.items(), key=lambda kv: (kv[1], kv[0]))[0]
    if thks:
        m.thickness = float(max(thks.items(), key=lambda kv: (kv[1], -float(kv[0])))[0])


def parse_many(paths: list[Path | str]) -> list[DxfMeasure]:
    return [parse(p) for p in paths]


def hit_rates(measures: list[DxfMeasure]) -> dict[str, object]:
    """**적중률을 숨기지 않는다** — 몇 건 중 몇 건에서 무엇을 뽑았는지."""
    n = len(measures)
    ok = [x for x in measures if x.error is None]
    def cnt(pred) -> int:
        return sum(1 for x in ok if pred(x))
    return {
        "files": n,
        "parsed": len(ok),
        "failed": n - len(ok),
        F_HOLES: cnt(lambda x: "CIRCLE" in x.entities),
        F_CUTLEN: cnt(lambda x: x.cut_len > 0),
        F_AREA: cnt(lambda x: x.closed_polys > 0),
        F_MATERIAL: cnt(lambda x: x.material is not None),
        F_THICK: cnt(lambda x: x.thickness is not None),
    }
