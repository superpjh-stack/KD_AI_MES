"""도입기업 답변 선언 — `docs/assumed/customer_answers.json` (D-160) 을 읽는 **한 곳**.

**답변이 왔다.** 요청서 7개 항목 중 **②재질 ③단위 ④어휘 ⑥고객사** 는 회신을 받았고(확정),
**①.cad 제품 ⑤원가·납기 실적** 과 **④의 정답 라벨 자체** 는 오지 않았다(미확정).
그 전까지(D-150)는 답변을 **가정**해 예행했고, 이 모듈 이름 `assumed` 는 그때 붙었다 —
**이름을 바꾸지 않는다.** 13개 파일이 이 이름으로 부르고 있고, 이름을 고치려다 호출부를
깨뜨린 적이 있다(§10 · util/audit.py 사건). 성격은 파일의 `성격` 칸이 말한다.

**항목마다 성격이 다르다.** `확정` 인 항목은 파생값에 **출처 표기**(언제 누구에게 받았는지)가
붙고, `미확정` 인 항목은 **차단 고지**가 붙는다. 둘을 섞지 않는다 — 확정된 값에 가정 딱지를
붙이면 쓸 수 있는 값을 못 쓰게 되고, 미확정 값에서 딱지를 떼면 그것이 거짓 증거가 된다.

**선언은 두 겹이고 둘 다 있어야 한다.**
  ① 파일 — `docs/assumed/customer_answers.json` 이 **답변의 유일한 출처**다. 이 파일 밖의
     값을 만들면 그것은 답변이 아니라 조작이다.
  ② DB — `SYS_CONFIGS('시스템설정','ASSUMED_ANSWERS')` 에 그 파일의 결정번호가 박혀 있다.
     시드(`db/seed_dev3.py`)가 ①을 읽어 넣는다.

**선언이 없으면 파생물은 전부 `차단`이다.** 검사기는 여기서 읽은 값으로 표기를 만들고,
읽히지 않으면 수치를 내지 않는다 — 표기 문구를 검사기에 박아 두면 선언을 지워도 문구가
남아 거짓 증거가 된다.

**문구도 지어내지 않는다.** `_meta.경고` 와 `④.정직한_판정` 이 백틱으로 적어 둔 문구를
그대로 꺼낸다. 파일이 문구를 바꾸면 표기도 바뀐다.
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
K_LABEL = "④_cad_객체_라벨_어휘"
K_CUSTOMER = "⑥_고객사_목록"
K_NOT_GIVEN = "제공되지_않은_것"

# `성격` 칸이 이 글자로 시작하면 답을 받은 것이다. 그 밖은 전부 미확정으로 본다.
CONFIRMED = "확정"


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


def status(key: str) -> str:
    """그 항목의 `성격` 칸 그대로. 선언이 없거나 항목이 없으면 **빈 문자열**."""
    if declaration() is None:
        return ""
    return str(((answers() or {}).get(key) or {}).get("성격") or "")


def answered(key: str) -> bool:
    """그 항목의 답을 **받았는가**. `성격` 이 `확정` 으로 시작할 때만 참이다.

    ④ 는 `어휘는 확정 · 정답 라벨 자체는 미확정` 이라 **거짓**이다 — 어휘만 받고
    라벨은 못 받았으므로, 라벨이 필요한 곳에서 받은 척하면 안 된다.
    """
    return status(key).startswith(CONFIRMED)


def source_tag(key: str) -> str:
    """확정 항목에 붙는 **출처 표기** — `도입기업 확정 (D-160) 2026-09-12`.

    고지가 아니라 출처다. 확정된 값에 `가정` 딱지를 붙이면 쓸 수 있는 값을 못 쓰게 된다.
    미확정 항목에는 빈 문자열을 돌려준다 — 부르는 쪽이 `base_note()` 로 차단 고지를 쓴다.
    """
    decl = declaration()
    if decl is None or not answered(key):
        return ""
    when = str(((answers() or {}).get(key) or {}).get("회신") or "").strip()
    return f"도입기업 확정 ({decl})" + (f" {when.replace('도입기업 ', '')}" if when else "")


def _quoted_in(text: str | None) -> str | None:
    if not text:
        return None
    m = _QUOTED.search(text)
    return m.group(1) if m else None


def base_note() -> str:
    """`미확정 (D-160)` — `_meta.경고` 가 적어 둔 문구. 선언이 없으면 **빈 문자열**.

    **받지 못한 항목**에서 파생된 값에 붙는 차단 고지다. 받은 항목에는 이것이 아니라
    `source_tag()` 의 출처 표기가 붙는다 — 둘을 섞으면 확정된 값이 못 쓰게 된다.
    """
    decl = declaration()
    if decl is None:
        return ""
    a = answers() or {}
    note = _quoted_in((a.get("_meta") or {}).get("경고"))
    return note if note and decl in note else ""


def circular_note() -> str:
    """G-14 판정 줄에 붙는 문구 — ④ `정직한_판정` 이 백틱으로 적어 둔 것 그대로.

    **이름은 그대로 둔다.** 가정 라벨을 쓰던 동안은 `순환 라벨 — 정확도 증거 아님` 이었고
    그래서 `circular` 다. 어휘가 3종으로 확정된 뒤(D-160) 그 라벨은 회수됐고 문구는
    `차단 (D-160) — 3종 어휘의 정답 라벨 0건 …` 으로 바뀌었다. 부르는 곳이 5군데라
    이름을 고치려다 호출부를 깨뜨리는 것보다, **문구가 파일에서 온다**는 사실이 중요하다.

    선언이 없으면 빈 문자열 — 문구를 검사기에 박아 두지 않는다.
    """
    decl = declaration()
    if decl is None:
        return ""
    a = answers() or {}
    note = _quoted_in((a.get(K_LABEL) or {}).get("정직한_판정"))
    return note if note and decl in note else base_note()


def unit_note() -> str:
    """`단위 확정 (D-160) — 도면단위 → mm …` + ③ 이 남긴 주의. 도구 출력·리포트용(길다)."""
    decl = declaration()
    if decl is None:
        return ""
    q = (answers() or {}).get(K_UNIT) or {}
    return (f"단위 {status(K_UNIT) or '미확정'} ({decl}) — 도면단위 → {q.get('답변', '')} "
            f"· {q.get('적용', '')} · ⚠ {q.get('남은_주의', '')}")


def unit_target() -> str | None:
    """③ 가정 답변이 말하는 단위. `전량 mm (…)` → `mm`. 없으면 `None` — 바꾸지 않는다."""
    if declaration() is None:
        return None
    q = (answers() or {}).get(K_UNIT) or {}
    m = re.search(r"\b(mm|cm|inch|feet|m)\b", str(q.get("답변") or ""))
    return m.group(1) if m else None


def unit_risk() -> str:
    """③ `위험` 중 **배율 오차를 적은 문장**. 잘려 나가면 경고가 사라지므로 짧게 고른다."""
    if declaration() is None:
        return ""
    q = (answers() or {}).get(K_UNIT) or {}
    risk = str(q.get("남은_주의") or "").replace("**", "")
    for sent in re.split(r"(?<=다)\.\s*", risk):
        if "배" in sent and re.search(r"\d", sent):
            return sent.strip().rstrip(".")
    return risk.strip()[:80]


def unit_tag() -> str:
    """`EST_CAD_FEATURES.SOURCE_DESC` 에 붙는 **짧은** 표지 (varchar(300) 안에서 안 잘리게).

    `도입기업 확정 (D-160) 2026-09-12 도면단위→mm · ⚠ … 25.4 배 환산이 필요하다`
    """
    decl = declaration()
    tgt = unit_target()
    if decl is None or tgt is None:
        return ""
    # 확정이면 `가정` 이 아니라 **출처**를 적는다. 표지 자체는 없애지 않는다 —
    # 표지가 사라지면 `단위 변환도 일어나지 않는다`(pipeline.dxf_features 가 둘을 묶어 뒀다).
    head = source_tag(K_UNIT) or f"단위 {status(K_UNIT) or '미확정'} ({decl})"
    return f"{head} {UNIT_MARK}{tgt} · ⚠ {unit_risk()}"


def material_merge() -> dict[str, list[str]]:
    """② `통합_제안` — `{정규 표기: [통합되는 표기, …]}`. 선언이 없으면 **빈 표**."""
    if declaration() is None:
        return {}
    q = (answers() or {}).get(K_MATERIAL) or {}
    return dict(q.get("통합") or {})


# 선언에서 파생된 행을 **회수할 때** 쓰는 SQL LIKE 패턴.
# `material_attr1()` 문구는 성격(확정/미확정)에 따라 바뀌지만 **결정번호 괄호는 항상 있다.**
# 문구를 그대로 패턴에 박으면 성격이 바뀐 순간 회수가 조용히 실패한다 — 실제로 그럴 뻔했다.
# 화면(032 코드관리)에서 사람이 손으로 넣은 행에는 `(D-nnn)` 이 없으므로 걸리지 않는다.
ATTR1_LIKE = "%(D-%)%"

# 단위 표지의 **불변 부분**. 앞머리(`단위 가정 (D-150)` → `도입기업 확정 (D-160)`)는 성격이
# 바뀌면 같이 바뀌지만 **화살표는 변환 그 자체라 늘 있다.** 검사기·테스트·회수는 전부 이
# 패턴으로 건다 — 문구를 다섯 군데에 복사해 두면 문구를 고치는 순간 다섯 군데가 조용히
# 어긋난다(실제로 `%단위 가정 (%` 가 5곳에 복사돼 있었다).
UNIT_MARK = "도면단위→"
UNIT_TAG_LIKE = f"%{UNIT_MARK}%"


def material_attr1() -> str:
    """`BAS_COMMON_CODES.ATTR1` 표시 — 이 코드가 마스터로 조용히 승격되지 않게."""
    decl = declaration()
    if decl is None:
        return ""
    tag = source_tag(K_MATERIAL)
    return tag or f"미확정 ({decl}) — 도입기업 회신 없음"


def label_vocab() -> tuple[str, ...]:
    """④ 답변이 정한 **라벨 어휘**. 답을 못 받았으면 빈 튜플 — 어휘를 우리가 고르지 않는다.

    답은 **3종**(`title_block`·`bom_table`·`rev_table`)이다. 홀·슬롯·노즐·플랜지·치수문자는
    `범위_밖` 이 적은 대로 **이번 사업이 아니다**. `답변` 칸의 백틱 이름만 꺼낸다 —
    목록을 코드에 박아 두면 파일이 바뀌어도 코드가 옛 어휘를 계속 쓴다.
    """
    if declaration() is None:
        return ()
    q = (answers() or {}).get(K_LABEL) or {}
    return tuple(_QUOTED.findall(str(q.get("답변") or "")))


def label_out_of_scope() -> str:
    """④ `범위_밖` 한 줄. 회수 사유를 검사기가 그대로 인용한다."""
    if declaration() is None:
        return ""
    return str(((answers() or {}).get(K_LABEL) or {}).get("범위_밖") or "").replace("**", "")


def not_given() -> list[str]:
    """`제공되지_않은_것` — **이 목록은 채우지 않는다.** G-15·G-17·G-18 은 차단이 정답이다."""
    a = answers()
    return list((a or {}).get(K_NOT_GIVEN) or [])


@lru_cache(maxsize=1)
def path_text() -> str:
    return ANSWERS_PATH.relative_to(ROOT).as_posix()
