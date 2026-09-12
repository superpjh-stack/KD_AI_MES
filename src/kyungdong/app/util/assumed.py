"""가정 답변 선언 — `docs/assumed/customer_answers.json` (D-150) 을 읽는 **한 곳**.

**도입기업 답변은 오지 않았다.** 사용자 지시로 "요청서를 받았다고 가정하고" 파이프라인을
예행한다(D-150). 그러면 그 가정에서 파생된 모든 값·수치에 고지가 붙어야 한다 —
`SYS_CONFIGS('시스템설정','SYNTHETIC_THREAD')`(D-131) 가 합성 스레드에 한 것과 같은 방식이다.

**선언은 두 겹이고 둘 다 있어야 한다.**
  ① 파일 — `docs/assumed/customer_answers.json` 이 **가정의 유일한 출처**다. 이 파일 밖의
     값을 만들면 그것은 가정이 아니라 조작이다.
  ② DB — `SYS_CONFIGS('시스템설정','ASSUMED_ANSWERS')` 에 그 파일의 결정번호가 박혀 있다.
     시드(`db/seed_dev3.py`)가 ①을 읽어 넣는다.

**선언이 없으면 파생물은 전부 `차단`이다.** 검사기는 여기서 읽은 값으로 고지를 만들고,
읽히지 않으면 수치를 내지 않는다 — 고지 문구를 검사기에 박아 두면 선언을 지워도 문구가
남아 거짓 증거가 된다.

**고지 문구도 지어내지 않는다.** `_meta.경고` 와 `④.정직한_판정` 이 백틱으로 적어 둔 문구를
그대로 꺼낸다. 파일이 문구를 바꾸면 고지도 바뀐다.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
ANSWERS_PATH = ROOT / "docs" / "assumed" / "customer_answers.json"

CONFIG_TYPE = "시스템설정"
CONFIG_KEY = "ASSUMED_ANSWERS"

# 백틱으로 감싼 첫 문구 — 파일이 스스로 적어 둔 고지다.
_QUOTED = re.compile(r"`([^`]+)`")

# 가정 답변의 질문 키. 파일의 키 이름을 그대로 쓴다 — 여기서 별칭을 만들지 않는다.
K_MATERIAL = "②_재질_두께_확인"
K_UNIT = "③_도면_단위"
K_LABEL = "④_cad_객체_정답_라벨"
K_NOT_GIVEN = "제공되지_않은_것"


def answers() -> dict[str, Any] | None:
    """가정 답변 파일. **없으면 `None`** — 빈 dict 로 뭉개면 파생물이 조용히 생긴다."""
    if not ANSWERS_PATH.is_file():
        return None
    try:
        return json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def file_decision() -> str | None:
    """파일이 적은 결정번호 (`_meta.결정번호`). 없으면 `None`."""
    a = answers()
    if not a:
        return None
    return (a.get("_meta") or {}).get("결정번호") or None


def db_decision() -> str | None:
    """DB 선언값. 없으면 `None` — DB 를 못 읽어도 **선언이 있는 척하지 않는다**."""
    import conn                      # 지연 임포트 — util 이 db 를 끌고 들어오지 않게

    try:
        row = conn.q1(
            "select CONFIG_VALUE from SYS_CONFIGS where CONFIG_TYPE = %s "
            "and CONFIG_KEY = %s and USE_YN = 'Y'", (CONFIG_TYPE, CONFIG_KEY))
    except Exception:                # noqa: BLE001 — DB 장애는 G-30 이 잡는다
        return None
    return (row["config_value"] or None) if row else None


def declaration() -> str | None:
    """**파일과 DB 가 같은 결정번호를 가리킬 때만** 선언이 있다.

    한쪽만 있으면 선언이 아니다 — 파일을 갈아끼우고 시드를 다시 돌리지 않은 상태이거나,
    DB 에만 박혀 출처가 사라진 상태다. 둘 다 `None` 을 돌려주고 파생물은 차단된다.
    """
    f, d = file_decision(), db_decision()
    if f is None or d is None or f != d:
        return None
    return d


def mismatch() -> str | None:
    """선언이 없을 때 **왜 없는지** 한 줄. 검사기가 차단 사유로 그대로 쓴다."""
    f, d = file_decision(), db_decision()
    if f is not None and d is not None and f == d:
        return None
    if f is None and d is None:
        return (f"가정 선언 없음 — 파일 {ANSWERS_PATH.relative_to(ROOT)} 도 "
                f"SYS_CONFIGS('{CONFIG_TYPE}','{CONFIG_KEY}') 도 없다")
    if f is None:
        return (f"DB 선언은 {d} 인데 출처 파일 {ANSWERS_PATH.relative_to(ROOT)} 가 없다 — "
                "가정의 출처가 사라졌다. 파생물을 신뢰할 수 없다")
    if d is None:
        return (f"파일은 {f} 인데 SYS_CONFIGS('{CONFIG_TYPE}','{CONFIG_KEY}') 선언이 없다 — "
                "`make db-seed` 를 돌리지 않았다")
    return f"파일 결정번호 {f} ≠ DB 선언 {d} — 파일을 갈아끼우고 시드를 다시 돌려야 한다"


def _quoted_in(text: str | None) -> str | None:
    if not text:
        return None
    m = _QUOTED.search(text)
    return m.group(1) if m else None


def base_note() -> str:
    """`가정 답변 기준 (D-150)` — `_meta.경고` 가 적어 둔 문구. 선언이 없으면 **빈 문자열**."""
    decl = declaration()
    if decl is None:
        return ""
    a = answers() or {}
    note = _quoted_in((a.get("_meta") or {}).get("경고"))
    return note if note and decl in note else ""


def circular_note() -> str:
    """`가정 답변 기준 (D-150) · 순환 라벨 — 정확도 증거 아님`.

    ④ `정직한_판정` 이 적어 둔 문구다. **정답 라벨을 우리 탐지에서 파생했으므로
    우리 탐지를 우리가 만든 정답과 비교하는 순환**이고, 그 수치는 정확도의 증거가 아니다.
    선언이 없으면 빈 문자열 — 문구를 검사기에 박아 두지 않는다.
    """
    decl = declaration()
    if decl is None:
        return ""
    a = answers() or {}
    note = _quoted_in((a.get(K_LABEL) or {}).get("정직한_판정"))
    return note if note and decl in note else base_note()


def unit_note() -> str:
    """`단위 가정 (D-150) — …` + ③ 이 경고한 25.4배 오차. 도구 출력·리포트용(길다)."""
    decl = declaration()
    if decl is None:
        return ""
    q = (answers() or {}).get(K_UNIT) or {}
    return (f"단위 가정 ({decl}) — {q.get('가정_답변', '')} · {q.get('가정_근거', '')} "
            f"· ⚠ {q.get('위험', '')}")


def unit_target() -> str | None:
    """③ 가정 답변이 말하는 단위. `전량 mm (…)` → `mm`. 없으면 `None` — 바꾸지 않는다."""
    if declaration() is None:
        return None
    q = (answers() or {}).get(K_UNIT) or {}
    m = re.search(r"\b(mm|cm|inch|feet|m)\b", str(q.get("가정_답변") or ""))
    return m.group(1) if m else None


def unit_risk() -> str:
    """③ `위험` 중 **배율 오차를 적은 문장**. 잘려 나가면 경고가 사라지므로 짧게 고른다."""
    if declaration() is None:
        return ""
    q = (answers() or {}).get(K_UNIT) or {}
    risk = str(q.get("위험") or "").replace("**", "")
    for sent in re.split(r"(?<=다)\.\s*", risk):
        if "배" in sent and re.search(r"\d", sent):
            return sent.strip().rstrip(".")
    return risk.strip()[:80]


def unit_tag() -> str:
    """`EST_CAD_FEATURES.SOURCE_DESC` 에 붙는 **짧은** 표지 (varchar(300) 안에서 안 잘리게).

    `단위 가정 (D-150) 도면단위→mm · ⚠ inch 도면을 mm 로 읽으면 25.4배 오차다`
    """
    decl = declaration()
    tgt = unit_target()
    if decl is None or tgt is None:
        return ""
    return f"단위 가정 ({decl}) 도면단위→{tgt} · ⚠ {unit_risk()}"


def material_merge() -> dict[str, list[str]]:
    """② `통합_제안` — `{정규 표기: [통합되는 표기, …]}`. 선언이 없으면 **빈 표**."""
    if declaration() is None:
        return {}
    q = (answers() or {}).get(K_MATERIAL) or {}
    return dict(q.get("통합_제안") or {})


def material_attr1() -> str:
    """`BAS_COMMON_CODES.ATTR1` 표시 — 이 코드가 마스터로 조용히 승격되지 않게."""
    decl = declaration()
    return "" if decl is None else f"가정 답변 기준 ({decl}) — 도입기업 미확인"


def not_given() -> list[str]:
    """`제공되지_않은_것` — **이 목록은 채우지 않는다.** G-15·G-17·G-18 은 차단이 정답이다."""
    a = answers()
    return list((a or {}).get(K_NOT_GIVEN) or [])


@lru_cache(maxsize=1)
def path_text() -> str:
    return ANSWERS_PATH.relative_to(ROOT).as_posix()
