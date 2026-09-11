#!/usr/bin/env python
"""contracts/api-contract.md 생성기 — 정본은 `app/nav.py` + SF-TD4 처리 흐름."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kyungdong.app import design, nav      # noqa: E402
from kyungdong.app.util import http        # noqa: E402

OUT = ROOT / "contracts" / "api-contract.md"

# 화면 없는 인터페이스 프로그램 4건 (EIF) — TD4-046~049
EIF = ["MES-TD4-046", "MES-TD4-047", "MES-TD4-048", "MES-TD4-049"]


def first_line(s: str | None, n: int = 150) -> str:
    if not s:
        return ""
    t = " ".join(s.split())
    return t[:n] + ("…" if len(t) > n else "")


def main() -> int:
    screens = nav.all_screens()
    L: list[str] = [
        "# contracts/api-contract.md — 라우트 계약",
        "",
        "> **생성 파일이다.** 정본은 `src/kyungdong/app/nav.py`(경로·소유) + SF-TD4(처리 흐름).",
        "> `tools/gen_api_contract.py` 가 뽑는다. **코드와 다르면 코드가 맞다** → `nav.py` 를 고치고 다시 뽑는다.",
        "",
        "## 0. 규약",
        "",
        "| # | 규약 |",
        "|---|---|",
        "| 1 | 화면은 **GET = 조회 렌더**. 등록·수정은 같은 경로에 **POST**, 삭제는 **POST + `_method=delete`**(폼 전송). |",
        "| 2 | 조회 조건은 **쿼리스트링**, 저장 payload 는 **폼**. JSON API 는 Agent·수집·CAD 만 쓴다. |",
        "| 3 | **모든 업무 화면의 최상위 조회 조건은 프로젝트(수주)번호·도면번호**다(TD3 standard_note 2). |",
        "| 4 | 권한 없음 = **403**(G-28). 좌측 메뉴는 권한 있는 것만 노출한다. |",
        "| 5 | **LOT·프로젝트번호 열은 클릭 가능**하고 `/prc/024`(공정이력조회)로 간다(G-08). |",
        "| 6 | 오류는 §4 계약 코드로만 낸다. **조용한 200 금지**(G-30). |",
        "| 7 | 페이지네이션은 `?page=&size=` (기본 size 20). 정렬은 `?sort=<컬럼>&dir=asc|desc`. |",
        "",
        "## 1. 공통 화면",
        "",
        "| 경로 | 메서드 | 화면 | 담당 |",
        "|---|---|---|---|",
    ]
    for cid, path in nav.COMMON_ROUTES.items():
        name = design.common_screens().get(cid, {}).get("name", "공통 오류 화면")
        L.append(f"| `{path}` | GET | {name} | 아키텍트 → 개발1(인증·레이아웃) / 개발2(현황판) |")
    L += ["| `/health` | GET | 헬스체크 — 정본 규모 대조. 불일치면 **500** | 아키텍트 |",
          "| `/static/app.css` | GET | 단일 CSS(§10-13) | 아키텍트 |", ""]

    L += ["## 2. 화면 45", "",
          "| 경로 | 화면 | 요구사항 | 프로그램 | 담당 | 처리 흐름 (SF-TD4) |",
          "|---|---|---|---|---|---|"]
    for s in screens:
        p = design.program(s.program_id) or {}
        L.append(f"| `GET {s.path}` | {s.no} {s.name} | {s.requirement_id} | {s.program_id} | "
                 f"{s.owner} | {first_line(p.get('flow'))} |")
    L.append("")

    L += ["## 3. 화면 없는 인터페이스 (EIF 4건 — TD4-046~049)", "",
          "화면이 없다. 연계 **상태 조회**는 `/dat/033`(데이터통합관리)에서 한다(G-05).", "",
          "| 프로그램 | 이름 | 제안 엔드포인트 | 담당 | 처리 흐름 |",
          "|---|---|---|---|---|"]
    endpoints = {
        "MES-TD4-046": "`POST /api/if/erp/{receipts|shipments|stocks}` · Excel 적재도 같은 경로(D-07)",
        "MES-TD4-047": "`POST /api/ingest/plc` (태그 배열) · `GET /api/ingest/status`",
        "MES-TD4-048": "`POST /api/cad/files` (multipart) · `GET /api/cad/import-logs`",
        "MES-TD4-049": "`POST /api/docs/import` · `GET /api/docs/embed-logs`",
    }
    owners = {"MES-TD4-046": "개발1", "MES-TD4-047": "개발3",
              "MES-TD4-048": "개발3", "MES-TD4-049": "개발3"}
    for pid in EIF:
        p = design.program(pid) or {}
        L.append(f"| {pid} | {p.get('name','')} | {endpoints[pid]} | {owners[pid]} | {first_line(p.get('flow'))} |")
    L.append("")

    L += ["## 4. 오류 계약 (goal.md §2.5 — QA1 테스트 케이스 원본)", "",
          "### 4.0 검사 순서 — 이 순서를 어기면 코드가 틀린 것이다 (D-78)", "",
          "```",
          "① 인증      미인증 → 401   (인증 도입 전에는 구조적으로 403 — D-79)",
          "② 권한      권한 없음 → 403",
          "③ CSRF      토큰 없음·위조 → 403",
          "④ 폼 검증   필수값·형식 → 422",
          "⑤ 업무 규칙 불합격 LOT 출하·승인 전 확정·코드 위반 → 422",
          "```",
          "",
          "**FastAPI 의 `Form(...)` 은 핸들러 본문보다 먼저 파싱된다.** 핸들러 안에서 권한을 보면 "
          "**권한 없는 역할이 403 이 아니라 422 를 받는다** — 실측으로 재현했다"
          "(`POST /est/012/confirm` as `OPERATOR` → **422**, 기대 403).",
          "",
          "→ 권한 검사는 **폼 파싱보다 앞**에 있어야 한다. 라우트가 `Form(...)` 을 쓴다면 "
          "핸들러 안 검사만으로는 부족하다. 아키텍트가 공용 가드를 제공한다.",
          "",
          "| 상황 | HTTP | 화면 문구 |", "|---|---|---|"]
    for c in http.CASES:
        L.append(f"| {c.note or c.key} | **{c.status}** | {c.message} |")
    L += ["",
          "**200 으로 렌더하되 숨기지 않는 것**", "",
          "| 상황 | 표시 |", "|---|---|",
          f"| 임베딩 미구성 | `{http.NOTICE_EMBEDDING}` — 검색 모드 라벨 |",
          f"| RAG 근거 0건·신뢰도 미달 | `{http.NOTICE_RAG_NO_EVIDENCE}` + 담당자 이관 (G-22) |",
          f"| 수집 중단 | `{http.NOTICE_INGEST_STALE.format(ts='hh:mm:ss')}` 배지 |",
          "| 값 미확정 | `미확정 (D-nn)` 배지 |",
          "| 수집 대상 아님 | `미수집 (D-nn)` — 수집 지점 2개소 밖 공정 (D-06) |",
          "| 가설값 | `가설 (D-nn)` 배지 |",
          ""]

    L += ["## 5. Agent API (개발3)", "",
          "| 경로 | 메서드 | 설명 |", "|---|---|---|",
          "| `/api/agent/query` | POST | 통합 질의. **폐쇄형** — 외부 검색 0. 근거 0건이면 LLM 을 부르지 않고 `검토 필요` |",
          "| `/api/agent/history` | GET | `AGT_QUERY_LOGS` 조회 (화면 042) |",
          "| `/api/agent/recommend/{reco_id}/adopt` | POST | 추천 검토·채택. **승인 권한 없으면 403**, "
          "`AGT_RECOMMENDATIONS.REVIEW_STATUS`·`REVIEWER_ID` 기록 (G-24). "
          "※ 경로는 **코드가 정본**이다(§4.1 · D-80). `ADOPT_YN`·`ADOPT_BY` 는 **TD5 에 없다** — "
          "직전 사업 컬럼명을 옮겨 적은 계약 오류였다(D-61) |",
          "",
          "질의·응답·근거·응답시간을 **100% `AGT_QUERY_LOGS` 에 기록**한다(G-20). "
          "LLM 미구성이면 **501**, 임베딩 미구성이면 200 + `tsvector_keyword` 라벨.",
          "",
          "## 6. 승인이 필요한 쓰기 (G-24 — 승인 없이 바뀌면 결함)", "",
          "| 대상 테이블 | 무엇 | 승인 역할 |", "|---|---|---|",
          "| `EST_QUOTATIONS` | 견적 확정 | 승인 권한(A) 보유 역할 |",
          "| `EST_BOM_HEADERS` | BOM 확정 | 〃 |",
          "| `SHP_INSPECTIONS` | 검사 합격 판정 | 품질 담당 |",
          "| `SHP_SHIPMENTS` | 출하 확정 — **검사 합격 LOT 만**(아니면 422) | 〃 |",
          "| `PRC_STD_CONDITIONS` | 표준 작업조건 변경 | 생산관리 |",
          "| `EST_CAD_OBJECTS` | 객체인식 결과 확정 | HITL 검증자 — `EST_OBJECT_REVIEWS`"
          "(`REVIEW_RESULT`·`REVIEWER_ID`·`BEFORE_VALUE`·`AFTER_VALUE`) 기록 |",
          "",
          "AI 는 **추천까지**다. 승인 전에는 **확정 상태로 표기하지 않는다**(TD3 standard_note 4).",
          ""]

    OUT.write_text("\n".join(L))
    print(f"생성: {OUT.relative_to(ROOT)} — 화면 {len(screens)} · 공통 {len(nav.COMMON_ROUTES)} · "
          f"EIF {len(EIF)} · 오류 {len(http.CASES)}종")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
