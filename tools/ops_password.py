#!/usr/bin/env python
"""운영 — 계정 비밀번호 재발급 (D-207).

**운영계에 들어갈 길이 없었다.** 비밀번호는 `db/seed.py` 가 계정을 **처음 만들 때 한 번**
난수로 발급해 출력하고 끝이다(저장소에 리터럴 0건 — G-29). 그 출력을 놓치면 그 계정으로는
영영 로그인할 수 없고, 시드를 다시 돌려도 **이미 있는 계정은 비밀번호를 바꾸지 않는다**(§10-11).

그래서 재발급 수단을 둔다. 규칙은 시드와 같다:
  · **난수**다. 고정 문자열을 쓰지 않는다 — 저장소·로그에 비밀번호가 남지 않는다.
  · **화면에 한 번만** 나온다. 파일에 쓰지 않는다.
  · `SYS_ACCESS_LOGS` 에 **누가 언제 어느 계정의 비밀번호를 바꿨는지** 남긴다(G-29).
    비밀번호 자체는 기록하지 않는다.
  · `PWD_CHANGED_DT` 를 지금으로 바꾼다 — 주기 변경 정책이 새로 시작한다.
  · 잠긴 계정은 `--unlock` 을 함께 줘야 풀린다. **조용히 풀지 않는다.**

사용:
    uv run python tools/ops_password.py --login admin
    uv run python tools/ops_password.py --login admin --unlock
    uv run python tools/ops_password.py --list          # 계정·역할·잠금 상태만 본다
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                                    # noqa: E402
from kyungdong.app.auth import hash_password                   # noqa: E402
from kyungdong.app.util import clock                           # noqa: E402

PASSWORD_BYTES = 12          # `secrets.token_urlsafe(12)` — 시드와 같은 길이


def accounts() -> list[dict]:
    return conn.q(
        "select u.USER_ID, u.LOGIN_ID, u.USER_NAME, u.DEPT_NAME, u.LOCK_YN, u.USE_YN, "
        "       u.PWD_CHANGED_DT, p.ROLE_CODE "
        "from SYS_USERS u left join SYS_ROLE_PERMISSIONS p on p.ROLE_PERM_ID = u.ROLE_ID "
        "order by u.USER_ID")


def main() -> int:
    ap = argparse.ArgumentParser(description="운영 계정 비밀번호 재발급 (D-207)")
    ap.add_argument("--login", help="대상 계정 LOGIN_ID")
    ap.add_argument("--unlock", action="store_true", help="잠긴 계정을 함께 푼다")
    ap.add_argument("--list", action="store_true", help="계정 목록만 본다")
    a = ap.parse_args()

    rows = accounts()
    if a.list or not a.login:
        print(f"계정 {len(rows)} 건 — 비밀번호는 여기 나오지 않는다")
        for r in rows:
            print(f"  {r['login_id']:10} {str(r['role_code'] or '역할없음'):10} "
                  f"{r['user_name'] or '':8} 잠금 {r['lock_yn']} 사용 {r['use_yn']} "
                  f"비번변경 {r['pwd_changed_dt']}")
        if not a.login:
            print("\n재발급:  uv run python tools/ops_password.py --login <LOGIN_ID>")
        return 0

    row = next((r for r in rows if r["login_id"] == a.login), None)
    if row is None:
        print(f"그런 계정이 없다: {a.login}", file=sys.stderr)
        return 1
    if row["lock_yn"] == "Y" and not a.unlock:
        print(f"계정 {a.login} 은 잠겨 있다(LOCK_YN=Y). 비밀번호만 바꿔도 로그인하지 못한다.\n"
              f"  함께 풀려면: --unlock", file=sys.stderr)
        return 1

    raw = secrets.token_urlsafe(PASSWORD_BYTES)
    conn.x("update SYS_USERS set PASSWORD_HASH = %s, PWD_CHANGED_DT = now(), "
           "UPDATED_DT = now()" + (", LOCK_YN = 'N'" if a.unlock else "") +
           " where USER_ID = %s", (hash_password(raw), int(row["user_id"])))
    # **비밀번호는 기록하지 않는다** — 누가 언제 무엇을 했는지만 남긴다 (G-29).
    conn.x(
        "insert into SYS_ACCESS_LOGS (USER_ID, ACCESS_TYPE, ACCESS_DT, SCREEN_ID, ACTION_DESC, "
        " RESULT_CODE, CREATED_DT) values (%s, '변경', %s, 'ops', %s, '성공', now())",
        (int(row["user_id"]), clock.anchor(),
         f"운영 비밀번호 재발급 (tools/ops_password.py · D-207)"
         + (" · 계정 잠금 해제" if a.unlock else "")))
    print(f"계정      {row['login_id']} ({row['role_code']})")
    print(f"비밀번호   {raw}")
    print("           ↑ **이 출력에만 나온다.** 저장소·로그 어디에도 남지 않는다.")
    print("           첫 로그인 뒤 화면에서 바꾼다 (로그인 화면의 비밀번호 변경).")
    if a.unlock:
        print("잠금       해제했다 (LOCK_YN='N')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
