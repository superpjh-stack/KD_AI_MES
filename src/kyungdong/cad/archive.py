"""원본 도면 아카이브 실측 스캐너 (D-109 ~ D-115) — **읽기 전용이다.**

지금까지 개발3이 읽은 것은 통계 xlsx 4종뿐이었다(`docs/cad/*.xlsx`, 1,283행). 원본 폴더에는
**6,038 파일**이 있고 도면·견적·프로젝트번호 체계가 전부 **파일시스템 안에** 있다(D-109·D-112).
이 모듈은 그 폴더를 **훑어서 읽기만 한다.** 원본은 절대 고치지 않는다.

⚠ **macOS 한글 파일명은 NFD 다** (D-115). `find -iname "*견적*"` 가 0건을 냈지만 실제로는
73건이다. 이 모듈의 모든 이름 비교는 `unicodedata.normalize('NFC', ...)` 를 거친다.
정규화를 빼면 한글 검색이 **조용히 0건**을 내고, 그걸 '데이터 없음' 으로 결론내면 D-115 재발이다.

프로젝트(수주)번호 (D-112) — `GD` + YYMM + 일련번호 + 제품명/고객사
  `GD160801-진공건조기` · `GD160803-누체필터10L` · `GD2007-00 동광제약` ·
  `GD1906-저장탱크-대한열기` · `GD2003-02-에니젠-누체필터 100L`
  **파싱 실패 건수를 함께 돌려준다** — 정규식이 몇 건을 놓쳤는지 숨기지 않는다.

**이것은 도입기업이 준 마스터가 아니다** (D-114). 폴더명에서 파생한 **후보**다.
고객사 공식 코드 여부는 확인되지 않았고, `BAS_COMMON_CODES` 의 '고객사' 그룹은 **0건**이다(D-47).
그래서 `EST_PROJECTS` 적재는 이 모듈이 하지 않는다 — 차단 사유는 `tools/cad_ingest.py` 가 적는다.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ENV_KEY = "KYUNGDONG_CAD_ARCHIVE"
# D-109 가 실측한 원본 위치. 절대경로라 장비가 바뀌면 없다 — 그때는 `available()` 이 False 고
# 호출자가 **통계 xlsx 경로로 되돌아간다**(조용히 0건을 내지 않는다).
DEFAULT_ARCHIVE = Path(
    "/Users/gerardo92/Desktop/26년 제조AI 스마트공장  프로젝트 /"
    "01 경동글로벌텍 제조AI 플랫폼 구축 프로젝트/01 경동Data")

CAD_EXTS = ("dwg", "cad", "dxf")          # EST_CAD_DRAWINGS.FILE_TYPE 어휘 (PDF 는 별도)
QUOTE_MARK = "견적"                        # NFC 로 비교한다 (D-115)

# TD5 `BAS_COMMON_CODES` '제품군' 5종(PG10~PG50)과 폴더명 표기의 대응. 실측 폴더명만 넣는다.
PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "반응기": ("반응기", "REACTOR", "S.S Reactor", "C.S Reactor", "GL REACTOR", "STS REACTOR"),
    "교반기": ("교반기", "AGITATOR", "믹서", "MIXER"),
    "진공건조기": ("진공건조기", "건조기", "DRYER", "VAT"),
    "누체필터": ("누체필터", "누체", "NUTSCHE", "FILTER"),
    "저장탱크": ("저장탱크", "리시버", "RECEIVER", "STORAGE", "TANK", "탱크", "콘덴샤", "CONDENSER"),
}
# D-114 가 폴더명에서 실측한 고객사 실명. **마스터가 아니라 후보다.**
KNOWN_CUSTOMERS = ("두루텍", "한모루", "동광제약", "웰이엔씨", "웰이엔시", "대한열기", "대호테크",
                   "엔에프테크", "비나텍", "그린텍", "신풍제약", "일성신약", "동아제약", "에니젠",
                   "최성배", "원명에스티에스", "리트산업", "태양기어")

# `GD` + YYMM + (일련번호) + 나머지. 구분자는 `-` · `_` · 공백 무엇이든 온다.
PROJECT_RE = re.compile(
    r"^GD[\s_-]?(?P<yymm>\d{4})(?P<seq>\d{2})?(?P<tail>(?:[\s_-]+\d{2})*)[\s_-]*(?P<rest>.*)$",
    re.I)


def nfc(s: Any) -> str:
    return unicodedata.normalize("NFC", str(s)) if s is not None else ""


def archive_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get(ENV_KEY)
    return Path(env) if env else DEFAULT_ARCHIVE


def available(root: Path | str | None = None) -> bool:
    return archive_root(root).is_dir()


@dataclass(frozen=True)
class ArchiveFile:
    name: str            # NFC 정규화된 파일명
    path: str            # NFC 정규화된 전체 경로
    rel: str             # 아카이브 루트 기준 상대경로
    ext: str             # 소문자 확장자 (점 없음)
    size: int
    mtime: datetime | None
    project_dir: str | None      # 이 파일이 속한 가장 가까운 GD 폴더명 (없으면 None)

    @property
    def file_type(self) -> str:
        return self.ext.upper()

    @property
    def is_cad(self) -> bool:
        return self.ext in CAD_EXTS

    @property
    def is_quote(self) -> bool:
        return QUOTE_MARK in self.name


@dataclass(frozen=True)
class Project:
    """폴더명에서 파싱한 프로젝트 **후보**. 마스터가 아니다 (D-114)."""

    folder: str          # 원본 폴더명 (NFC)
    rel: str             # 아카이브 루트 기준 상대경로
    project_no: str      # GD160801 처럼 정규화한 번호
    yymm: str
    seq: str | None
    label: str           # 제품명/고객사 부분 원문
    product_group: str | None    # 정본 5종 중 하나 (못 가리면 None)
    customer: str | None         # D-114 실명 후보 (못 가리면 None)


@dataclass
class ScanResult:
    root: str
    files: list[ArchiveFile] = field(default_factory=list)
    project_dirs: list[tuple[str, str]] = field(default_factory=list)   # (폴더명, 상대경로)
    projects: list[Project] = field(default_factory=list)
    project_parse_failed: list[str] = field(default_factory=list)

    @property
    def cad_files(self) -> list[ArchiveFile]:
        return [f for f in self.files if f.is_cad]

    @property
    def quote_files(self) -> list[ArchiveFile]:
        return [f for f in self.files if f.is_quote]

    def joins(self) -> dict[str, Any]:
        """도면과 견적이 **같이 있는** 폴더 (D-113 — ETO 디지털 스레드의 실제 조인 키).

        세는 방식이 둘이고 **답이 다르다**. 하나로 뭉개지 않고 둘 다 적는다.
          · `same_folder` — 한 폴더가 도면 파일과 견적 파일을 **직접** 담고 있는 경우
          · `subtree`     — 그 폴더 **아래 어딘가에** 둘 다 있는 경우 (상위 폴더도 세어진다)
        """
        direct_cad: Counter[str] = Counter()
        direct_q: Counter[str] = Counter()
        sub_cad: Counter[str] = Counter()
        sub_q: Counter[str] = Counter()
        for f in self.files:
            parts = Path(f.rel).parts[:-1]
            here = "/".join(parts)
            if f.is_cad:
                direct_cad[here] += 1
            if f.is_quote:
                direct_q[here] += 1
            for i in range(len(parts)):
                anc = "/".join(parts[: i + 1])
                if f.is_cad:
                    sub_cad[anc] += 1
                if f.is_quote:
                    sub_q[anc] += 1
        same = sorted(set(direct_cad) & set(direct_q),
                      key=lambda k: -(direct_cad[k] + direct_q[k]))
        sub = sorted(set(sub_cad) & set(sub_q), key=lambda k: -(sub_cad[k] + sub_q[k]))
        return {
            "same_folder": len(same),
            "same_folder_top": [{"folder": k, "drawings": direct_cad[k], "quotes": direct_q[k]}
                                for k in same[:10]],
            "subtree": len(sub),
            "subtree_top": [{"folder": k, "drawings": sub_cad[k], "quotes": sub_q[k]}
                            for k in sub[:10]],
        }

    def stats(self) -> dict[str, Any]:
        """**실측만.** 추정치를 섞지 않는다."""
        ext = Counter(f.ext for f in self.files)
        cad = self.cad_files
        q = self.quote_files
        by_proj_draw = Counter(f.project_dir for f in cad if f.project_dir)
        by_proj_quote = Counter(f.project_dir for f in q if f.project_dir)
        both = sorted(set(by_proj_draw) & set(by_proj_quote),
                      key=lambda k: -(by_proj_draw[k] + by_proj_quote[k]))
        return {
            "root": self.root,
            "files": len(self.files),
            "ext": dict(ext.most_common()),
            "cad_files": len(cad),
            "cad_by_ext": dict(Counter(f.ext for f in cad)),
            "pdf_files": ext.get("pdf", 0),
            "quote_files": len(q),
            "quote_by_ext": dict(Counter(f.ext for f in q)),
            "project_dirs": len(self.project_dirs),
            "projects_parsed": len(self.projects),
            "project_parse_failed": len(self.project_parse_failed),
            "unique_project_no": len({p.project_no for p in self.projects}),
            "product_group_hit": sum(1 for p in self.projects if p.product_group),
            "customer_hit": sum(1 for p in self.projects if p.customer),
            "by_product_group": dict(Counter(p.product_group or "미상" for p in self.projects)),
            "projects_with_drawing_and_quote": len(both),
            "top_joined_projects": [
                {"project_dir": k, "drawings": by_proj_draw[k], "quotes": by_proj_quote[k]}
                for k in both[:8]],
        }


def _is_project_dir(name: str) -> bool:
    m = PROJECT_RE.match(name)
    return bool(m and m.group("yymm"))


def parse_project(folder: str, rel: str = "") -> Project | None:
    """폴더명 → 프로젝트 후보. **못 읽으면 None 이다 — 지어내지 않는다.**"""
    name = nfc(folder).strip()
    m = PROJECT_RE.match(name)
    if not m:
        return None
    yymm, seq = m.group("yymm"), m.group("seq")
    tail = re.findall(r"\d{2}", m.group("tail") or "")
    rest = nfc(m.group("rest")).strip(" -_")
    no = "GD" + yymm + (seq or "")
    if tail:
        no += "-" + "-".join(tail)
    group = None
    up = rest.upper()
    for g, aliases in PRODUCT_ALIASES.items():
        if any(a.upper() in up for a in aliases):
            group = g
            break
    cust = next((c for c in KNOWN_CUSTOMERS if c in rest), None)
    return Project(folder=name, rel=rel, project_no=no, yymm=yymm, seq=seq,
                   label=rest, product_group=group, customer=cust)


def walk(root: Path | str | None = None) -> Iterator[tuple[Path, list[str], list[str]]]:
    yield from os.walk(archive_root(root))


def scan(root: Path | str | None = None) -> ScanResult:
    """아카이브 전체를 한 번 훑는다. 루트가 없으면 **예외** — 빈 결과로 뭉개지 않는다(§10-9)."""
    base = archive_root(root)
    if not base.is_dir():
        raise FileNotFoundError(
            f"원본 도면 아카이브가 없다: {base} — 경로가 다르면 환경변수 {ENV_KEY} 로 준다 (D-109)")
    res = ScanResult(root=nfc(base))
    seen_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        dp = Path(dirpath)
        # 이 경로에서 가장 가까운 GD 폴더 — 견적·도면을 같은 프로젝트로 묶는 조인 키다 (D-113)
        proj_dir = None
        for part in reversed([nfc(x) for x in dp.relative_to(base).parts]):
            if _is_project_dir(part):
                proj_dir = part
                break
        for d in dirnames:
            dn = nfc(d)
            if not _is_project_dir(dn):
                continue
            rel = nfc((dp / d).relative_to(base))
            if rel in seen_dirs:
                continue
            seen_dirs.add(rel)
            res.project_dirs.append((dn, rel))
            p = parse_project(dn, rel)
            if p is None:
                res.project_parse_failed.append(rel)
            else:
                res.projects.append(p)
        for fn in filenames:
            name = nfc(fn)
            if name.startswith("."):
                continue
            full = dp / fn
            try:
                st = full.stat()
            except OSError:
                continue
            res.files.append(ArchiveFile(
                name=name, path=nfc(full), rel=nfc(full.relative_to(base)),
                ext=Path(name).suffix.lower().lstrip("."),
                size=st.st_size,
                mtime=datetime.fromtimestamp(st.st_mtime).replace(microsecond=0),
                project_dir=proj_dir,
            ))
    res.files.sort(key=lambda f: f.rel)
    res.project_dirs.sort(key=lambda x: x[1])
    res.projects.sort(key=lambda p: (p.project_no, p.rel))
    return res
