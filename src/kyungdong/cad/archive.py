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

import json
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
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
# 확정 고객사 (D-139 · 도입기업 회신 ⑥ 로 재확인 D-166). **여기 목록을 박아 두지 않는다** —
# `docs/cad/customer_candidates.json` 이 정본이고 이 함수가 거기서 꺼낸다.
#
# 박아 뒀을 때 실제로 틀렸다(D-136): 하드코딩 18종에 **사람 이름 `최성배` 1 + 공급사 3**
# (`원명에스티에스`·`리트산업`·`태양기어` — 셋 다 *경동글로벌텍 귀중* 견적서의 **공급자**)이
# 섞여 있었고, `그린텍` 은 미분류였다. 반대로 확정 19종 중 **7종이 빠져** 있었다.
# 도입기업이 ⑥ 에서 "협력사·공급사 16종은 고객사가 아니다" 를 확인해 준 뒤로는 이 목록이
# 정본과 **증명 가능하게** 어긋난 상태였다. 출처를 하나로 묶어 그 어긋남을 없앤다(D-163 과 같은 결함).
CUSTOMER_JSON = Path(__file__).resolve().parents[3] / "docs" / "cad" / "customer_candidates.json"

# `분류` 가 이 둘로 시작하는 후보만 고객사다. 협력사·공급사 · 관계사 · 도입기업 본인 ·
# 미분류 · 사람이름 · 제품명은 **고객사가 아니다.**
CUSTOMER_ROLE_PREFIX = ("발주처", "수요처")


@lru_cache(maxsize=1)
def known_customers() -> tuple[tuple[str, str], ...]:
    """`((폴더에서 찾을 표기, 정규화이름), …)` — **긴 표기가 먼저** 온다.

    긴 것부터 보는 이유: `엔에프테크 조범주` 가 `엔에프테크` 보다 먼저 걸려야 폴더명 전체를
    설명한다. 둘 다 같은 고객으로 접히므로 결과는 같지만 **무엇을 보고 붙였는지**가 달라진다.

    표기는 두 곳에서 모은다 — ① `정규화이름`(`에니젠/애니젠` 처럼 `/` 로 두 표기를 적은 것은
    갈라서 둘 다) ② `표기변형` 중 **폴더·파일명에서 관측된 것**(`웰이엔시` · `서한` 처럼
    폴더에만 나오는 표기가 여기 있다). 견적서 수신처 표기(`㈜ 한 모 루`)는 **넣지 않는다** —
    공백이 박힌 문서 표기라 폴더명에 없고, 넣으면 영영 걸리지 않는 항목만 늘어난다.

    파일을 못 읽으면 **빈 튜플**이다. 하드코딩으로 되돌아가지 않는다 — 되돌아가면 D-136 이
    조용히 되살아난다. 부르는 쪽은 고객사 0건을 그대로 보고한다(§10-9).
    """
    try:
        data = json.loads(CUSTOMER_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    pairs: dict[str, str] = {}
    for c in data.get("후보") or []:
        if not str(c.get("분류", "")).startswith(CUSTOMER_ROLE_PREFIX):
            continue
        raw = nfc(str(c.get("정규화이름") or "")).strip()
        if not raw:
            continue
        # `에니젠/애니젠` 처럼 한 칸에 두 표기를 적은 것이 있다. **앞의 것을 대표로 쓰고**
        # 뒤의 것은 찾을 표기로만 둔다 — 슬래시가 박힌 이름이 화면·통계에 그대로 나가면
        # 그게 회사 이름인 줄 안다.
        parts = [x.strip() for x in raw.split("/") if x.strip()]
        canon = parts[0]
        for part in parts:
            pairs.setdefault(part, canon)
        for v in c.get("표기변형") or []:
            v = nfc(str(v))
            if "폴더" not in v and "파일명" not in v:
                continue
            head = v.split(" (")[0].strip()
            if head:
                pairs.setdefault(head, canon)
    return tuple(sorted(pairs.items(), key=lambda kv: (-len(kv[0]), kv[0])))

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
    # 붙는 이름은 **정규화이름**이다 — `엔에프테크 조범주` 폴더도 `엔에프테크` 로 센다.
    cust = next((canon for tok, canon in known_customers() if tok in rest), None)
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
