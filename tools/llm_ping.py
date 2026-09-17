"""`make check-llm` — LLM 연결 확인 (D-234 · D-236). **실제 API 를 1회 부른다** (과금 · 외부 전송).

구성 상태(`llm.state()`)를 먼저 찍고, 구성됐을 때만 `llm.ping()` 으로 가장 작은 요청을 보낸다.
키가 없으면 501 사유를 그대로 찍고 종료코드 1 이다 — 조용히 통과시키지 않는다.
키 문자열은 어디에도 찍지 않는다(G-29).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

from kyungdong.agent import llm                      # noqa: E402
from kyungdong.app.settings import settings          # noqa: E402
from kyungdong.app.util import http                  # noqa: E402


def main() -> int:
    s = settings()
    st = llm.state()
    print(f"LLM  provider={st.provider or '(비어 있음)'} model={st.model or '(비어 있음)'} "
          f"effort={llm.effort()} 자격={'있음' if llm.has_credential() else '없음'} "
          f"embed={s.embed_provider or '(없음 → tsvector_keyword)'}")
    print(f"     상태: {st.badge}" + (f" — {st.reason}" if st.reason else ""))
    if not st.configured:
        print("     → .env 의 KYUNGDONG_LLM_PROVIDER · KYUNGDONG_LLM_MODEL · ANTHROPIC_API_KEY 를 채운다 (D-234)")
        print("       또는 셸에서 ANTHROPIC_API_KEY 를 export 하거나 `ant auth login` 으로 프로필을 만든다 (D-237)")
        return 1
    print(f"     고지: {llm.EGRESS_NOTE}")
    try:
        r = llm.ping()
    except http.HTTPException as e:
        d = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        print(f"     실패 HTTP {e.status_code}: {d.get('message')} — {d.get('reason', '')}")
        return 1
    print("     연결 성공: " + json.dumps({k: v for k, v in r.items() if k != "egress"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
