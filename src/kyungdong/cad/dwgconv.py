"""`.dwg` → `.dxf` 변환기 껍데기 (D-123 — **D-05 판정이 바뀌는 지점**).

D-05 는 "`.dwg`·`.cad` 는 바이너리라 변환기 없이 못 읽는다" 였다. 그 문장은 **변환기가 없을 때**만
맞다. 사용자 승인으로 `dwg2dxf`(GNU libredwg 0.14)를 설치했고, 변환된 DXF 에는 우리
`cad/dxf.py` 파서가 **그대로** 돈다(D-123 표본 30건: 변환 21/30 · 파싱 21/21).

그래서 지금의 정직한 문장은 **"DWG 는 구조적 불가가 아니다 — 변환되면 산출되고, 변환
실패분이 차단이다"** 다. 변환율이 100% 가 아니므로 **차단이 사라진 것도 아니다.**

이 모듈은 세 가지만 한다. 값을 만들어 채우지 않는다.
  · `available()` — 변환기가 실제로 있는지. 없으면 호출자가 그 사실을 그대로 적는다.
  · `signature()` — 파일 앞 6바이트 DWG 버전 서명. **실패가 버전별로 갈리는지** 보려고 잰다.
  · `to_dxf()` — 한 건 변환. 실패하면 변환기가 뱉은 말을 경로·숫자만 지워 정규화해 돌려준다
    (분류 바구니를 미리 지어두지 않는다).

`measured()` 는 **변환 → 파싱 → 즉시 삭제**를 한 번에 한다. 중간 DXF 를 남기지 않는 것이
이 모듈의 약속이다 — 전량(3,270건)을 보관하면 팽창률 약 3배로 8.5GB 가 쌓인다.
"""
from __future__ import annotations

import os
import re
import shutil
from functools import lru_cache
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import dxf

BINARY = "dwg2dxf"
DEFAULT_TIMEOUT = 180          # 초. 넘으면 '시간초과' 로 실패에 센다 — 매달리지 않는다

# DWG 파일 앞 6바이트 서명 → 사람이 아는 버전 이름. 모르는 서명은 원문을 그대로 남긴다.
VERSIONS = {
    "AC1.2": "R1.2", "AC1.4": "R1.4", "AC1.50": "R2.0", "AC2.10": "R2.10",
    "AC1001": "R2.22", "AC1002": "R2.5", "AC1003": "R2.6", "AC1004": "R9",
    "AC1006": "R10", "AC1009": "R11/R12", "AC1012": "R13", "AC1014": "R14",
    "AC1015": "R2000", "AC1018": "R2004", "AC1021": "R2007", "AC1024": "R2010",
    "AC1027": "R2013", "AC1032": "R2018",
}

NOT_INSTALLED = (f"`{BINARY}` 가 설치돼 있지 않다 — `brew install libredwg`. "
                 "변환기 없이는 DWG 를 못 읽는다 (D-05 · D-123)")


def which() -> str | None:
    return shutil.which(BINARY)


def available() -> bool:
    return which() is not None


@lru_cache(maxsize=1)
def version() -> str | None:
    """변환기 버전 문자열. 없으면 `None` — 있는 척하지 않는다. 화면마다 부르므로 1회만 잰다."""
    if not available():
        return None
    try:
        r = subprocess.run([BINARY, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout or "").strip().splitlines()[0] if r.stdout else None


def signature(path: Path | str) -> str:
    """앞 6바이트. DWG 가 아니면 `아님:` 접두로 그 사실이 보인다."""
    try:
        head = Path(path).open("rb").read(6)
    except OSError as e:
        return f"읽기실패:{type(e).__name__}"
    try:
        sig = head.decode("ascii")
    except UnicodeDecodeError:
        return "아님:비ASCII헤더"
    if sig in VERSIONS:
        return f"{sig} ({VERSIONS[sig]})"
    if sig.startswith("AC"):
        return f"{sig} (미상 버전)"
    return f"아님:{sig!r}"


def normalize_error(stderr: str, rc: int) -> str:
    """stderr 첫 오류줄에서 경로·숫자·주소를 지운다. **변환기가 실제로 뱉은 말**을 묶는다."""
    for line in (stderr or "").splitlines():
        s = line.strip()
        if not s or not re.search(
                r"ERROR|error|Error|Invalid|invalid|not supported|Unknown|Failed|failed", s):
            continue
        s = re.sub(r"/[^\s,:]+", "<path>", s)
        s = re.sub(r"\b0x[0-9a-fA-F]+\b", "<hex>", s)
        s = re.sub(r"\b\d+\b", "N", s)
        return s[:180]
    if rc < 0:
        return f"변환기가 신호 {-rc} 로 죽었다 (libredwg 크래시)"
    return f"stderr 에 오류줄 없이 exit {rc}"


class Converted:
    """변환 결과. **실패를 성공처럼 보이게 하지 않는다** — `ok` 가 False 면 `reason` 이 있다."""

    __slots__ = ("ok", "reason", "rc", "out_size", "secs", "sig", "rc_nonzero")

    def __init__(self, *, ok: bool, reason: str | None = None, rc: int | None = None,
                 out_size: int | None = None, secs: float | None = None,
                 sig: str | None = None, rc_nonzero: bool = False) -> None:
        self.ok, self.reason, self.rc = ok, reason, rc
        self.out_size, self.secs, self.sig, self.rc_nonzero = out_size, secs, sig, rc_nonzero


def to_dxf(src: Path | str, out: Path | str, *, timeout: int = DEFAULT_TIMEOUT) -> Converted:
    """한 건 변환. **변환 성공 = 0바이트가 아닌 DXF 가 나왔다** 로 센다.

    `rc` 가 0이 아니어도 산출물이 있으면 `rc_nonzero=True` 로 따로 남긴다 — 성공/실패를
    종료코드 하나로 뭉개지 않는다(libredwg 는 부분 오류에도 쓸 만한 DXF 를 낸다).
    """
    import time

    src, out = Path(src), Path(out)
    if not available():
        return Converted(ok=False, reason=NOT_INSTALLED)
    if not src.is_file():
        return Converted(ok=False, reason=f"원본 파일이 없다: {src}")
    sig = signature(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    t0 = time.time()
    try:
        p = subprocess.run([BINARY, "-y", "-o", str(out), str(src)],
                           capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        if out.exists():
            out.unlink()
        return Converted(ok=False, reason=f"시간초과 {timeout}s", rc=124, sig=sig,
                         secs=round(time.time() - t0, 1))
    except OSError as e:                                   # 조용히 삼키지 않는다 (§10-9)
        return Converted(ok=False, reason=f"{BINARY} 실행 불가: {e}", sig=sig)
    secs = round(time.time() - t0, 1)
    made = out.is_file() and out.stat().st_size > 0
    if not made:
        if out.exists():
            out.unlink()
        return Converted(ok=False, reason=normalize_error(p.stderr, p.returncode),
                         rc=p.returncode, sig=sig, secs=secs)
    return Converted(ok=True, rc=p.returncode, out_size=out.stat().st_size, secs=secs, sig=sig,
                     rc_nonzero=p.returncode != 0,
                     reason=(normalize_error(p.stderr, p.returncode)
                             if p.returncode != 0 else None))


@contextmanager
def as_dxf(src: Path | str, *, timeout: int = DEFAULT_TIMEOUT,
           work_dir: Path | str | None = None) -> Iterator[tuple[Path | None, Converted]]:
    """`with` 를 벗어나면 **중간 DXF 를 지운다.** 최대 디스크 사용이 한 파일 크기다."""
    src = Path(src)
    base = Path(work_dir) if work_dir else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="dwgconv-", suffix=".dxf", dir=str(base))
    os.close(fd)
    out = Path(tmp)
    out.unlink(missing_ok=True)              # dwg2dxf 가 직접 만들게 둔다
    try:
        got = to_dxf(src, out, timeout=timeout)
        yield (out if got.ok else None), got
    finally:
        out.unlink(missing_ok=True)


def measured(src: Path | str, *, timeout: int = DEFAULT_TIMEOUT,
             work_dir: Path | str | None = None) -> tuple[dxf.DxfMeasure | None, Converted]:
    """변환 → 파싱 → **즉시 삭제**. 변환이 안 되면 `(None, 실패이유)` 다 — 0 을 돌려주지 않는다."""
    with as_dxf(src, timeout=timeout, work_dir=work_dir) as (path, got):
        if path is None:
            return None, got
        return dxf.parse(path), got
