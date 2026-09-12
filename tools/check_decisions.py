#!/usr/bin/env python
"""결정 대장 정합성 — **`decisions.md` 가 사실과 어긋나는 것을 잡는다** (D-181).

`CLAUDE.md` 는 "대장에 없는 것을 마음대로 정하지 않는다" 고 못박는다. 그러면 **대장이 맞아야
한다.** 실제로 재 보니 `차단`·`미결` 로 적힌 항목 중 여러 건이 **이미 해소돼 있었다** —
D-120 은 '고객사 코드 0건' 이라 막혔다고 적혀 있는데 코드는 19건 서 있고, D-77 은 '500 이다'
인데 422 로 고쳐져 있었다. 해소된 것이 차단으로 남아 있으면 **읽는 사람이 프로젝트 상태를
잘못 본다.** 다음 할 일을 그 목록에서 고르면 이미 끝난 일을 또 한다.

**손으로 닫으면 또 낡는다.** 그래서 항목마다 **근거를 다시 재는 probe** 를 둔다.
  · probe 가 `열림` 이라고 하면 — 대장이 맞다.
  · probe 가 `해소` 라고 하는데 대장이 `차단` 이면 — **결함이다.** 대장을 닫아야 한다.
  · probe 가 없으면 — **`수동` 이라고 적는다.** 확인한 척하지 않는다(§10-9).

probe 가 없는 것은 대부분 **정본 부재·도입기업 미제공**이다(D-03·D-04·D-05·D-13·D-15 …).
그것들은 코드를 봐서는 알 수 없다 — 문서가 와야 닫힌다.

**대장을 여기서 고치지 않는다.** 검사기는 찍기만 하고 닫는 것은 사람이 한다 —
자동으로 닫으면 어떤 근거로 닫혔는지가 사라진다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                    # noqa: E402

LEDGER = ROOT / "decisions.md"
OPEN_WORDS = ("차단", "미결")

# 판정
OPEN, RESOLVED, MANUAL = "열림", "해소", "수동"


def _src(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _n(sql: str, args=None) -> int:
    try:
        row = conn.q1(sql, args)
        return int(row["n"]) if row else 0
    except Exception as e:                                     # noqa: BLE001
        raise RuntimeError(f"DB 조회 실패 — {e}") from e


# ══ probe — `(열렸는가, 근거)` 를 돌려준다. 근거는 **숫자나 문장**이어야 한다 ══════
def p_d32() -> tuple[bool, str]:
    """코드성 FK 29건이 **물리 FK 로 안 생겼는지**를 DB 에서 잰다 — 규칙 문자열이 아니라 실제 제약."""
    from kyungdong.app.util import codes
    mapped = len(codes.code_columns())
    unmapped = len(codes.unmapped_columns())
    phys = _n("select count(*) as n from information_schema.table_constraints "
              "where constraint_type='FOREIGN KEY' and table_schema='public'")
    # **열려 있는 것이 맞다** — 코드성 FK 는 물리 FK 로 만들 수 없고(TD5 결함) `require_code()`
    # 가 대신 검증한다. 이 판정은 "우리가 우회하지 않고 있는가" 를 잰다.
    return mapped > 0, (f"코드성 FK 컬럼 {mapped}개 → require_code() 검증 "
                        f"(미매핑 {unmapped}) · 물리 FK 제약 {phys}건")


def p_d33() -> tuple[bool, str]:
    d = json.loads(_src("docs/design/design.json"))
    for det in d["td5"]["details"]:
        for c in det.get("columns", []):
            if len(c) >= 5 and c[1] == "UNIT_PRICE" and c[4] == "Y":
                return True, "TD5 UNIT_PRICE 가 여전히 FK='Y' 다 (정본 결함 — 우리가 못 고친다)"
    return False, "TD5 UNIT_PRICE 의 FK 표기가 사라졌다"


def p_d41() -> tuple[bool, str]:
    d = json.loads(_src("docs/design/design.json"))
    cols = {c[1] for det in d["td5"]["details"] for c in det.get("columns", []) if len(c) > 1}
    miss = [c for c in ("OUTSOURCE_ORDER_NO", "OUTSOURCE_VENDOR") if c not in cols]
    return bool(miss), f"TD5 에 없는 컬럼 {miss or '없음'} (762 고정이라 추가하지 않는다)"


def p_d44() -> tuple[bool, str]:
    d = json.loads(_src("docs/design/design.json"))
    for det in d["td5"]["details"]:
        for c in det.get("columns", []):
            if len(c) >= 7 and c[1] == "ROLE_ID" and "SYS_ROLE_PERMISSIONS" in str(c[6]):
                return True, "TD5 SYS_USERS.ROLE_ID 가 여전히 권한행을 가리킨다 (정본 결함)"
    return False, "TD5 ROLE_ID 표기가 바뀌었다"


def p_d54() -> tuple[bool, str]:
    s = _src("src/kyungdong/app/util/__init__.py")
    reexport = bool(re.search(r"^from \.audit import audit", s, re.M))
    return reexport, ("util/__init__ 이 audit 을 함수로 재노출한다 — "
                      "되돌리면 `from ..util.audit import audit` 5곳이 깨진다(대장이 적은 그대로)"
                      if reexport else "재노출이 사라졌다")


def p_d56() -> tuple[bool, str]:
    item = _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP='품목'")
    mat = _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP='재질'")
    lots = _n("select count(*) as n from INV_MATERIAL_LOTS")
    still = not (item and mat and lots)
    return still, f"품목 {item} · 재질 {mat} · 자재LOT {lots} 행"


def p_d57() -> tuple[bool, str]:
    m = len(re.findall(r'@app\.get\("/board"', _src("src/kyungdong/app/main.py")))
    k = len(re.findall(r'@router\.get\("/board"', _src("src/kyungdong/app/routers/kpi.py")))
    return (m + k) > 1, f"/board 선언 — main.py {m} · kpi.py {k}"


def p_d60() -> tuple[bool, str]:
    src = {p.relative_to(ROOT).as_posix(): p.read_text()
           for p in (ROOT / "src").rglob("*.py") if "__pycache__" not in p.parts}
    posts = sum(len(re.findall(r"@(?:router|app)\.post\(", t)) for t in src.values())
    calls = sum(len(re.findall(r"csrf\.require\(", t))
                for f, t in src.items() if not f.endswith("util/csrf.py"))
    return calls < posts, f"POST {posts} · csrf.require {calls}"


def p_d62() -> tuple[bool, str]:
    n = len(re.findall(r"pytest\.skip\(", _src("tests/test_dev3_cad.py")))
    return n > 0, f"test_dev3_cad.py 의 pytest.skip {n} 건 (§10-4 는 0건·N건 둘 다 단언)"


def p_d69_70() -> tuple[bool, str]:
    dsh = _src("src/kyungdong/app/routers/dsh.py")
    col = _src("src/kyungdong/ingest/collector.py")
    one_place = "def stale_verdict(" in col and "collection_status()" in dsh
    dup = bool(re.search(r"anchor\(\)\s*-\s*last", dsh))
    return (dup or not one_place), (
        f"판정 함수 stale_verdict 단일화 {one_place} · dsh 가 자체 뺄셈 {dup}")


def p_d71() -> tuple[bool, str]:
    """전처리 4건(결측 보정·이상치·처리건수·Feature) 중 **Feature 만 남았는지**를 잰다."""
    from kyungdong.cad import pipeline
    blocked = len(getattr(pipeline, "BLOCKED_FEATURES", {}) or {})
    pre = _src("src/kyungdong/ingest/preprocess.py")
    fill = "Forward Fill" in pre
    outlier = "노이즈" in pre
    jobs = "PROCESS_CNT" in pre
    done = fill and outlier and jobs
    return not done, (f"결측 보정 {fill} · 이상치 표시 {outlier} · 처리건수 기록 {jobs} · "
                      f"Feature 차단 {blocked}종은 D-05·D-90 으로 남는다")


def p_d75() -> tuple[bool, str]:
    """`/dat/033` 을 **실제로 렌더해** 인터페이스 4종이 나오는지 본다 — 소스 문자열이 아니라 화면."""
    from fastapi.testclient import TestClient

    from kyungdong.app.main import app

    r = TestClient(app, raise_server_exceptions=False).get(
        "/dat/033", headers={"x-kyungdong-role": "SYSADMIN"})
    hit = sum(1 for k in ("046", "047", "048", "049") if k in r.text)
    return hit < 4, f"/dat/033 렌더 {r.status_code} · 인터페이스 표기 {hit}/4"


def p_d76() -> tuple[bool, str]:
    s = _src("src/kyungdong/app/routers/est.py")
    bad = len(re.findall(r"/prc/024\?lot=\{?r?\[?'?project", s))
    return bad > 0, f"est.py 가 프로젝트번호를 ?lot= 로 거는 곳 {bad}"


def p_d77() -> tuple[bool, str]:
    s = _src("src/kyungdong/app/routers/ingest.py")
    ok = bool(re.search(r"JSONDecodeError.*?\n.*?\n.*?http\.fail\(\"validation\"", s, re.S))
    return not ok, f"본문 파싱 실패 → validation(422) 처리 {ok}"


def p_d81() -> tuple[bool, str]:
    s = _src("tests/test_dev1_flow.py")
    bad = bool(re.search(r"conn\.q\([^)]*\)\[0\]", s))
    return bad, f"ORDER BY 없는 [0] 단언 {bad}"


def p_d94() -> tuple[bool, str]:
    src = {p.relative_to(ROOT).as_posix(): p.read_text()
           for p in (ROOT / "src").rglob("*.py") if "__pycache__" not in p.parts}
    login = sum(len(re.findall(r'@(?:router|app)\.post\("/login"', t)) for t in src.values())
    rl = sum(len(re.findall(r"ratelimit\.\w+\(", t)) for f, t in src.items()
             if not f.endswith("util/ratelimit.py"))
    se = sum(len(re.findall(r"session\.create\(", t)) for f, t in src.items()
             if not f.endswith("util/session.py"))
    return not (login and rl and se), f"POST /login {login} · ratelimit 호출 {rl} · session.create {se}"


def p_d98() -> tuple[bool, str]:
    d = json.loads(_src("docs/design/design.json"))
    remark = ""
    for det in d["td5"]["details"]:
        for c in det.get("columns", []):
            if len(c) >= 7 and c[1] == "OBJECT_TYPE":
                remark = str(c[6])
    from kyungdong.app.util import assumed
    vocab = assumed.label_vocab()
    open_list = remark.rstrip().endswith("등")
    return not (open_list and vocab), (
        f"TD5 비고가 열린 목록 {open_list} · 도입기업 확정 어휘 {list(vocab) or '없음'}")


def p_d102() -> tuple[bool, str]:
    from kyungdong.app.util import csrf
    return not csrf.enforced(), f"CSRF_ENFORCE={csrf.enforced()}"


def p_d120() -> tuple[bool, str]:
    c = _n("select count(*) as n from BAS_COMMON_CODES where CODE_GROUP='고객사'")
    p = _n("select count(*) as n from EST_PROJECTS")
    return not (c and p), f"고객사 코드 {c} · EST_PROJECTS {p} 행"


def p_d127() -> tuple[bool, str]:
    from kyungdong.app.util import assumed
    tgt = assumed.unit_target()
    return tgt is None, f"단위 확정 {tgt or '미확정'} (D-164 회신 mm)"


def p_d129_151() -> tuple[bool, str]:
    ls = json.loads((ROOT / "work" / "cad_labelset.json").read_text())
    return not ls["labels"], f"정답 라벨 {len(ls['labels'])} · 예측 {len(ls['predictions'])}"


def p_d136() -> tuple[bool, str]:
    from kyungdong.cad import archive
    toks = {t for t, _ in archive.known_customers()}
    bad = [x for x in ("최성배", "원명에스티에스", "리트산업", "태양기어") if x in toks]
    return bool(bad), f"고객사 아닌 이름 {bad or '없음'} · 확정 {len({c for _, c in archive.known_customers()})}종"


def p_d146() -> tuple[bool, str]:
    ts = _n("select count(*) as n from DAT_TIMESERIES")
    mat = _n("select count(*) as n from INV_MATERIAL_LOTS where MATERIAL is not null")
    return True, f"G-09 정합성 분모(MATERIAL 채움) {mat} · G-10 시계열 {ts} (시드 직후 0이 정상)"


def p_d168() -> tuple[bool, str]:
    n = _n("select count(*) as n from IF_DEVICE_REGISTRY "
           "where USE_YN='Y' and IP_ADDRESS is not null and length(trim(IP_ADDRESS))>0")
    from kyungdong.app.util import device
    return n == 0, f"IP 등록된 장비 {n} 대 · 시뮬레이터 선언 {device.simulation() or '없음'}"


def p_d169() -> tuple[bool, str]:
    d = json.loads(_src("docs/design/design.json"))
    cols: list[str] = []
    for det in d["td5"]["details"]:
        names = [c[1] for c in det.get("columns", []) if len(c) > 1]
        if "DEVICE_ID" in names and "IP_ADDRESS" in names:
            cols = names
    secret = [c for c in cols if any(k in c for k in ("SECRET", "TOKEN", "CERT", "KEY"))]
    return not secret, f"IF_DEVICE_REGISTRY {len(cols)}컬럼 · 인증 칸 {secret or '없음'}"


PROBES = {
    "D-32": p_d32, "D-33": p_d33, "D-41": p_d41, "D-44": p_d44, "D-54": p_d54,
    "D-56": p_d56, "D-57": p_d57, "D-60": p_d60, "D-62": p_d62, "D-69": p_d69_70,
    "D-70": p_d69_70, "D-71": p_d71, "D-75": p_d75, "D-76": p_d76, "D-77": p_d77,
    "D-81": p_d81, "D-94": p_d94, "D-98": p_d98, "D-102": p_d102, "D-120": p_d120,
    "D-127": p_d127, "D-129": p_d129_151, "D-151": p_d129_151, "D-136": p_d136,
    "D-146": p_d146, "D-168": p_d168, "D-169": p_d169,
}

# probe 를 **의도적으로** 두지 않은 것 — 코드를 봐서는 알 수 없다.
NO_PROBE_WHY = {
    "D-03": "CAD 학습 데이터 실태 — 도입기업 확인",
    "D-04": "견적·실제 제조원가 Label — 도입기업 제공",
    "D-05": "CAD 파서(Autodesk·YOLOv8·OCR) — 미확보",
    "D-07": "ERP 보유 여부 — 정본 상충",
    "D-08": "LLM·임베딩 모델 — 미확정",
    "D-13": "AI 성능목표 산식 5칸 공란 — 정본 부재",
    "D-15": "TLS·저장 암호화 알고리즘 — 정본 부재",
    "D-17": "개인정보·로그 보존기간 — 정본 부재",
    "D-26": "현행 설비 수량·사양 — 정본 부재",
    "D-27": "네트워크 구성 — 범위 밖",
    "D-55": "공급처 평가 4지표 산식 — 정본 부재",
    "D-59": "표준 작업조건·클레임 이력 — 정본 부재",
    "D-68": "'정상 데이터' 정의 — 정본 부재 (missing-policy §4 조작적 정의)",
    "D-90": "Feature 5종 차단 사유가 전부 D-05",
    "D-135": "표제란 좌표 기반 셀 인식 미구현",
    "D-138": "암호 PDF·스캔 PDF·변환 실패 — 원천",
    "D-167": "도입기업 2차 답변 미도착",
    "D-176": "PLC 태그맵 — 도입기업 제공",
}


# 닫힌 표시. 상태 칸이 `~~차단~~ → **해소 …**` 이면 **더는 열린 항목이 아니다** —
# 원문(`차단`)을 지우지 않고 취소선으로 남기기 때문에 글자만 보면 계속 열린 것으로 읽힌다.
CLOSED_MARK = "해소"


def _bare(state: str) -> str:
    """상태 칸에서 강조·취소선·공백을 뗀 **맨 앞 글자**를 본다."""
    return state.replace("*", "").replace("~", "").strip()


def is_open(state: str) -> bool:
    """**열린 항목인가.** 글자 포함 여부로 보면 틀린다 —

    `확정 — G-10 이 차단에서 풀렸다` 는 **확정**인데 '차단' 이 들어 있다. 실제로 이 문장
    하나 때문에 열린 항목이 29 → 30 으로 늘었다(D-187). 그래서 **맨 앞 상태어**로 판정한다.
    """
    bare = _bare(state)
    if CLOSED_MARK in bare:                      # `~~차단~~ → 해소 …`
        return False
    if bare.startswith("확정"):                   # `확정 — … 차단에서 풀렸다`
        return False
    return any(bare.startswith(w) for w in OPEN_WORDS)


def parse_open() -> list[tuple[str, str]]:
    """대장에서 `차단`·`미결` 로 **아직 열려 있는** 항목. 본문이 아니라 상태 칸만 본다."""
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| \*\*(D-\d+)\*\* \| ([^|]+) \|", line)
        if not m:
            continue
        if is_open(m.group(2)):
            out.append((m.group(1), m.group(2).strip()))
    return out


def parse_closed() -> list[str]:
    """`해소` 로 닫힌 항목 — **다시 열리면 알아야 한다.**"""
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| \*\*(D-\d+)\*\* \| ([^|]+) \|", line)
        if m and CLOSED_MARK in _bare(m.group(2)):
            out.append(m.group(1))
    return out


def main() -> int:
    rows = parse_open()
    print(f"decisions.md — `차단`·`미결` {len(rows)} 건")
    print(f"probe 있음 {sum(1 for n, _ in rows if n in PROBES)} · "
          f"probe 없음(사유 적음) {sum(1 for n, _ in rows if n in NO_PROBE_WHY)} · "
          f"미분류 {sum(1 for n, _ in rows if n not in PROBES and n not in NO_PROBE_WHY)}")
    print()
    stale: list[str] = []
    unclassified: list[str] = []
    for no, state in rows:
        if no in PROBES:
            try:
                still, why = PROBES[no]()
            except Exception as e:                              # noqa: BLE001
                print(f"  {no:6} {'probe 실패':8} {type(e).__name__}: {e}")
                continue
            mark = OPEN if still else RESOLVED
            print(f"  {no:6} {mark:6} {why}")
            if not still:
                stale.append(f"{no} — {why}")
        elif no in NO_PROBE_WHY:
            print(f"  {no:6} {MANUAL:6} {NO_PROBE_WHY[no]}")
        else:
            print(f"  {no:6} {'미분류':6} **probe 도 사유도 없다** — 둘 중 하나를 적어야 한다")
            unclassified.append(no)
    # ── 닫힌 항목이 **다시 열리지 않았는지** ─────────────────────────────
    reopened: list[str] = []
    closed_ids = parse_closed()
    if closed_ids:
        print(f"닫힌 항목 {len(closed_ids)} 건 재검 — **되열리면 잡는다**")
        for no in closed_ids:
            if no not in PROBES:
                continue
            try:
                still, why = PROBES[no]()
            except Exception as e:                              # noqa: BLE001
                print(f"  {no:6} {'probe 실패':8} {type(e).__name__}: {e}")
                continue
            if still:
                print(f"  {no:6} {'되열림':6} {why}")
                reopened.append(f"{no} — {why}")
        print(f"  되열린 항목 {len(reopened)} 건")
    print()
    if reopened:
        print(f"**닫았는데 다시 열렸다 — {len(reopened)} 건**")
        for x in reopened:
            print(f"  · {x}")
    if stale:
        print(f"**해소됐는데 대장이 안 닫혔다 — {len(stale)} 건**")
        for x in stale:
            print(f"  · {x}")
    else:
        print("해소됐는데 안 닫힌 항목 0 건")
    if unclassified:
        print(f"**미분류 {len(unclassified)} 건** — {unclassified}")
    print()
    print("대장은 **사람이 닫는다** — 검사기는 찍기만 한다(어떤 근거로 닫혔는지가 남아야 한다)")
    return 1 if (stale or unclassified or reopened) else 0


if __name__ == "__main__":
    raise SystemExit(main())
