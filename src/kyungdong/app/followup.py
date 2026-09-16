"""미비 항목을 **화면에 남긴다** (D-188).

지금까지 "무엇이 부족한가" 는 `decisions.md`·`progress.md`·게이트 판정줄에만 있었다.
그것들은 **개발자가 보는 자리**다. 화면을 쓰는 사람은 어떤 칸이 왜 비어 있는지,
무엇을 주면 채워지는지 알 수 없었다 — 빈 그리드에 `미확정 (D-nn)` 이 떠도 그 D-번호가
무슨 뜻인지 화면 어디에도 없었다.

**출처는 `decisions.md` 하나다.** 화면이 자기 목록을 따로 들면 대장과 어긋난다 —
그 사고를 이미 두 번 겪었다(D-163 표시 문구 7곳 복사 · D-181 대장 16건 낡음).
그래서 이 모듈이 대장을 읽고, `tools/check_decisions.py` 도 **여기의 파서를 쓴다.**

**화면 배정은 지어내지 않는다.** `SCREEN_MAP` 에 적힌 것만 그 화면에 뜨고, 적히지 않은
항목은 **`029 시스템 설정`(전사 공통)** 으로 모인다. 배정이 빠진 항목이 **조용히 사라지지
않게** 테스트가 "열린 항목 = 화면별 합계" 를 단언한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[3] / "decisions.md"

OPEN_WORDS = ("차단", "미결")
CLOSED_MARK = "해소"

# 배정되지 않은 항목이 모이는 곳 — **버리지 않는다.**
CATCH_ALL = "029"


@dataclass(frozen=True)
class Item:
    no: str              # D-번호
    state: str           # 차단 / 미결 / 차단(Critical) …
    summary: str         # 왜 비어 있는가 (대장 본문의 관찰부)
    action: str          # 지금은 어떻게 하고 있는가 (대장 본문의 대응부)
    need: str            # 누가 주어야 하는가
    critical: bool


# 무엇이 있어야 닫히는가 — **화면을 보는 사람이 알아야 할 말**로 적는다.
# D-번호만 띄우면 화면에서는 아무 뜻이 없다.
NEED = {
    "도입기업": "도입기업 제공",
    "정본": "산출물(정본) 보완",
    "우리": "개발 잔여",
}

# D-번호 → 화면 번호. **여기 없는 것은 029 로 모인다**(버리지 않는다).
SCREEN_MAP: dict[str, tuple[str, ...]] = {
    # 견적AI — CAD·견적·BOM
    "D-03": ("010", "037"), "D-05": ("010", "011"), "D-129": ("011",),
    "D-135": ("010", "011"), "D-138": ("010",), "D-90": ("010",),
    "D-04": ("012", "014"), "D-13": ("014", "015"), "D-33": ("012",),
    # 입고 · 공급처
    "D-55": ("008",), "D-32": ("032",),
    # 공정 · 외주
    "D-41": ("021", "024"), "D-59": ("023", "019"), "D-26": ("003",),
    # 데이터 · 수집
    "D-68": ("034", "007"), "D-146": ("033", "035"),
    "D-197": ("022", "007", "034", "035"), "D-225": ("022", "023", "003"),
    "D-176": ("029", "033"), "D-169": ("029",), "D-168": ("029", "033"),
    # Agent · RAG
    "D-08": ("038", "039", "040"),
    # 시스템 · 보안
    "D-15": ("029",), "D-17": ("027", "029"), "D-44": ("026",), "D-27": ("029",),
    "D-54": ("029",), "D-62": ("029",), "D-07": ("033", "029"),
    # 도입기업 2차 답변 — 여러 화면이 걸린다
    "D-167": ("010", "011", "012", "029"),
}

# 누가 주어야 닫히는가. **적히지 않은 것은 `우리` 로 치지 않는다** — 모르면 모른다고 적는다.
OWNER: dict[str, str] = {
    "D-03": "도입기업", "D-04": "도입기업", "D-05": "도입기업", "D-07": "정본",
    "D-08": "도입기업", "D-09": "정본", "D-13": "정본", "D-15": "정본", "D-17": "정본",
    "D-26": "도입기업", "D-27": "정본", "D-32": "정본", "D-33": "정본", "D-41": "정본",
    "D-44": "정본", "D-54": "우리", "D-55": "도입기업",
    "D-59": "도입기업", "D-62": "우리", "D-68": "정본", "D-90": "도입기업",
    "D-129": "도입기업", "D-135": "우리", "D-138": "도입기업", "D-146": "도입기업",
    "D-167": "도입기업", "D-168": "도입기업", "D-169": "정본",
    "D-176": "도입기업", "D-197": "정본", "D-225": "도입기업",
}


def _bare(state: str) -> str:
    return state.replace("*", "").replace("~", "").strip()


def is_open(state: str) -> bool:
    """**맨 앞 상태어**로 판정한다 — 글자 포함으로 보면 틀린다.

    `확정 — G-10 이 차단에서 풀렸다` 는 확정인데 '차단' 이 들어 있다(D-187).
    """
    bare = _bare(state)
    if CLOSED_MARK in bare or bare.startswith("확정"):
        return False
    return any(bare.startswith(w) for w in OPEN_WORDS)


_LIMIT = 190


def _clip(t: str) -> str:
    """문장 경계에서 자른다. **제목만 남기지 않는다** — `CAD 학습 데이터 실태.` 로 끝나면
    팔로우업에 쓸 수가 없다. 최소 45자는 넘긴 뒤의 문장 끝을 찾는다."""
    t = t.strip()
    if len(t) <= _LIMIT:
        return t
    m = re.search(r"[.다]\s", t[45:_LIMIT])
    return (t[:45 + m.end()].strip() if m else t[:_LIMIT].rstrip() + "…")


def _split(body: str) -> tuple[str, str]:
    """대장 본문을 **관찰부 | 대응부** 로 가른다.

    대장은 `| 결함 설명 | 우리가 한 대응 |` 꼴이다. 화면에는 **둘 다** 있어야 한다 —
    왜 비어 있는지만 보이고 지금 뭘 하고 있는지가 없으면 "고장 났나" 로 읽힌다.
    """
    t = re.sub(r"\*\*|`|~~", "", body).strip().strip("|").strip()
    parts = [x.strip() for x in t.split(" | ") if x.strip()]
    if not parts:
        return "", ""
    return _clip(parts[0]), (_clip(parts[1]) if len(parts) > 1 else "")


@lru_cache(maxsize=1)
def open_items() -> tuple[Item, ...]:
    """대장에서 **아직 열린** 항목. 파일을 못 읽으면 빈 튜플 — 조용히 채우지 않는다."""
    try:
        text = LEDGER.read_text(encoding="utf-8")
    except OSError:
        return ()
    out: list[Item] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\| \*\*(D-\d+)\*\* \| ([^|]+) \|(.*)$", line)
        if not m or not is_open(m.group(2)):
            continue
        no = m.group(1)
        if no in seen:                       # 같은 번호가 두 번 적힌 대장이 있다 — 앞의 것만
            continue
        seen.add(no)
        state = _bare(m.group(2))
        why, act = _split(m.group(3))
        out.append(Item(no=no, state=state, summary=why, action=act,
                        need=NEED.get(OWNER.get(no, ""), "담당 미확정"),
                        critical="Critical" in m.group(2)))
    return tuple(out)


def for_screen(screen_no: str | None) -> list[Item]:
    """그 화면에 걸린 미비 항목.

    **`029` 는 전체를 본다.** 화면마다 자기 것만 보이면 "전부 몇 건인지" 를 볼 자리가
    없어진다 — 배정이 빠진 항목도 여기로 모이므로 **어디에도 안 뜨는 항목이 생기지 않는다.**
    (화면을 새로 만들 수 없다 — `goal.md` 는 화면 45 고정이다.)
    """
    if not screen_no:
        return []
    if screen_no == CATCH_ALL:
        out = list(open_items())
    else:
        out = [it for it in open_items() if screen_no in (SCREEN_MAP.get(it.no) or ())]
    # Critical 을 먼저, 그 다음 번호순 — 화면에서 위에 있어야 눈에 띈다.
    return sorted(out, key=lambda i: (not i.critical, int(i.no.split("-")[1])))


def unassigned() -> list[Item]:
    """`SCREEN_MAP` 에 배정되지 않아 `029` 로 모인 항목."""
    return [it for it in open_items() if it.no not in SCREEN_MAP]
