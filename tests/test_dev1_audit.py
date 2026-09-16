"""개발1 감사 지적 회귀 — 잘못된 입력은 422 · 쪽 넘김은 안정 · 품목은 자재만.

이 파일이 지키는 것 (감사 항목 번호는 지적서 순서다)
  ① 타입 있는 조회·입력값이 SQL 캐스트 오류로 500 이 되지 않는다 — **422 다**(계약 §2.5).
  ② `order by` 동률이 풀려 쪽을 넘겨도 같은 행이 되풀이되지 않는다.
  ③ `BAS_COMMON_CODES('품목')` 드롭다운에 **집계/원가계정 행**이 없다.
  ④ 007 '검증 결과' 조회칸이 실제로 거른다 (렌더만 하고 무시하지 않는다).
  ⑨ 쪽 번호를 전부 그리지 않는다 (739쪽 화면에서 앵커 739개가 쏟아지던 결함).
  ⑪ 역할 매트릭스 셀 문구를 넓게 읽어 집계·재전송·계정 생성까지 열어 주지 않는다 (G-28).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                              # noqa: E402
from conftest import csrf_post                           # noqa: E402
from kyungdong.app.main import app                       # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

# 이 파일의 검사는 화면을 통해 행을 만든다(설정 1건 · 반출 이력 2건 · 사용자 1건).
# **시드 행은 건드리지 않고 테스트가 만든 것만 되돌린다** — 남기면 뒤따르는
# `test_dev1_seed.py` 의 "정본에 있는 것만 넣었는가" 단언이 내 쓰레기에 걸려 넘어진다.
TRACKED: tuple[tuple[str, str], ...] = (
    ("INV_MATERIAL_HISTORY", "HIST_ID"),
    ("INV_STOCKS", "STOCK_ID"),
    ("INV_RECEIPTS", "RECEIPT_ID"),
    ("INV_MATERIAL_LOTS", "LOT_ID"),
    ("INV_SUPPLIER_QUALITY", "SQ_ID"),      # 008 평가산출을 실제로 돌린다 — §7.1 판정은 0건이다
    ("DAT_DOWNLOAD_LOGS", "DOWNLOAD_ID"),
    ("SYS_ACCESS_LOGS", "LOG_ID"),
    ("BAS_COMMON_CODES", "CODE_ID"),
    ("BAS_QUALITY_STANDARDS", "QSTD_ID"),
    ("SYS_CONFIGS", "CONFIG_ID"),
    ("SYS_USERS", "USER_ID"),
)


@pytest.fixture(scope="module", autouse=True)
def rollback_after():
    marks = {t: int(conn.q1(f"select coalesce(max({pk}), 0) as m from {t}")["m"])
             for t, pk in TRACKED}
    yield marks
    for table, pk in TRACKED:
        conn.x(f"delete from {table} where {pk} > %s", (marks[table],))
    assert conn.q1("select 1 as x from SYS_CONFIGS where CONFIG_KEY = 'ZZ_AUDIT_ENDPOINT'") is None
    # 시드가 넣은 인터페이스설정 4종은 그대로여야 한다 — 되돌림이 너무 많이 지웠는지 본다
    assert int(conn.q1("select count(*) as n from SYS_CONFIGS "
                       "where CONFIG_TYPE = '인터페이스설정'")["n"]) == 4


def get(path: str, role: str = "SYSADMIN"):
    return client.get(path, headers={"x-kyungdong-role": role})


def total_of(html: str, title: str) -> int:
    m = re.search(rf"{re.escape(title)} — (\d+) 건", html)
    assert m, f"'{title} — N 건' 머리글을 못 찾았다"
    return int(m.group(1))


# ═════════════════════════════════════════════════════════════════════════
# ① 형식이 틀린 조회값·입력값은 422 다 — 500 이 아니다
# ═════════════════════════════════════════════════════════════════════════
BAD_QUERIES = [
    # 정수 칸에 문자열
    "/inv/005?sup=abc", "/inv/008?sup=abc", "/inv/007?loaded=abc",
    # 날짜 칸에 문자열 · 달력에 없는 날
    "/inv/005?day=abc", "/inv/005?day=2020-99-99", "/inv/005?day=2021-02-30",
    "/inv/006?from=abc", "/inv/006?to=abc", "/inv/007?from=abc", "/inv/007?to=abc",
    "/sys/027?from=notadate", "/sys/027?to=zzz",
    "/dat/033?from=abc", "/dat/034?from=abc", "/dat/036?from=abc",
    # 어휘 칸에 없는 값
    "/inv/007?verify=아무거나", "/sys/028?type=없는구분", "/sys/028?channel=없는채널",
    "/sys/029?type=없는구분", "/dat/034?kind=없는구분", "/dat/034?flag=없는플래그",
]


@pytest.mark.parametrize("url", BAD_QUERIES)
def test_형식이_틀린_조회값은_422다(url):
    r = get(url)
    assert r.status_code == 422, f"{url} → {r.status_code} (500 이면 SQL 캐스트가 새어 나온 것이다)"


def test_같은_칸에_올바른_값을_주면_200이다():
    """422 가 '무조건 막는다' 가 되지 않았는지 반대편도 단언한다 (§10-4)."""
    for url in ("/inv/005?sup=1", "/inv/005?day=2025-01-02", "/inv/006?from=2025-01-01",
                "/sys/027?from=2025-01-01", "/dat/034?from=2025-01-01",
                "/inv/007?verify=정합", "/sys/028?type=알림기준", "/dat/034?kind=시계열"):
        assert get(url).status_code == 200, url


def test_입고등록_입고일시_형식이_틀리면_422다():
    sup = conn.q1("select SUPPLIER_ID from INV_SUPPLIERS where USE_YN='Y' limit 1")["supplier_id"]
    item = conn.q1("select CODE_VALUE from BAS_COMMON_CODES "
                   "where CODE_GROUP='품목' and USE_YN='Y' limit 1")["code_value"]
    r = csrf_post(client, "/inv/005",
                  {"supplier_id": str(sup), "item_code": item, "receipt_qty": "1",
                   "inspect_result": "합격", "input_device": "Web", "receipt_dt": "어제"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 422, r.status_code


def test_입고등록_공급처가_숫자가_아니면_422다():
    r = csrf_post(client, "/inv/005",
                  {"supplier_id": "abc", "item_code": "ITEM-001", "receipt_qty": "1",
                   "inspect_result": "합격", "input_device": "Web"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 422, r.status_code


def test_코드관리_정렬순서가_숫자가_아니면_422다():
    r = csrf_post(client, "/bas/032",
                  {"code_group": "품목", "code_value": "ZZ-TEST-1", "code_name": "x",
                   "sort_order": "첫번째"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 422, r.status_code


def test_코드관리_모르는_코드그룹은_422다():
    r = csrf_post(client, "/bas/032",
                  {"code_group": "있지도않은그룹", "code_value": "ZZ-TEST-2", "code_name": "x"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 422, r.status_code


def test_품질기준_적용일자_형식이_틀리면_422다():
    r = csrf_post(client, "/bas/030",
                  {"qstd_code": "ZZ-TEST", "product_group": "반응기", "inspect_type": "입고검사",
                   "inspect_item": "x", "apply_from": "2025-13-45"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 422, r.status_code


# ═════════════════════════════════════════════════════════════════════════
# ② 쪽을 넘겨도 같은 행이 되풀이되지 않는다 (order by 동률 해소)
# ═════════════════════════════════════════════════════════════════════════
def test_007은_쪽을_넘겨도_입고번호가_겹치지_않는다():
    total = int(conn.q1("select count(*) as n from INV_RECEIPTS")["n"])
    assert total > 20, "표본이 한 쪽에 다 들어가면 이 검사가 무의미하다 — 먼저 seed_dev1"
    seen: list[str] = []
    pages = -(-total // 20)
    for p in range(1, pages + 1):
        seen += re.findall(r"RC-\d{4}-\d{4}", get(f"/inv/007?page={p}").text)
    assert len(seen) == total, f"{len(seen)} ≠ {total}"
    assert len(set(seen)) == total, "쪽 넘김에서 같은 입고번호가 두 번 나왔다 (동률 정렬)"


def test_034는_두_원천을_합쳐_세고_200건에서_잘리지_않는다():
    """`limit 100` 두 번 + `total=len(rows)` 이던 결함 — 이제 SQL 이 센다."""
    ts = int(conn.q1("select count(*) as n from DAT_TIMESERIES")["n"])
    lake = int(conn.q1("select count(*) as n from DAT_LAKE_OBJECTS")["n"])
    assert total_of(get("/dat/034").text, "통합 데이터") == ts + lake
    assert total_of(get("/dat/034?kind=시계열").text, "통합 데이터") == ts
    assert total_of(get("/dat/034?kind=비정형").text, "통합 데이터") == lake


def test_036과_027은_2차_정렬키를_들고_있다():
    src = (ROOT / "src/kyungdong/app/routers/dat.py").read_text()
    assert "d.DOWNLOAD_DT desc, d.DOWNLOAD_ID desc" in src
    src = (ROOT / "src/kyungdong/app/routers/inv.py").read_text()
    assert "r.RECEIPT_DT desc, r.RECEIPT_NO desc" in src


# ═════════════════════════════════════════════════════════════════════════
# ③ 품목 드롭다운에 집계/원가계정 행이 없다
# ═════════════════════════════════════════════════════════════════════════
COST_ACCOUNT_LABELS = (
    "LAB OUR", "LABOR COST", "LABOUR", "PROCESSING COST",
    "경비 및 기타 재 보험료", "공 과 잡 비 및 이 윤", "공과 잡비",
    "볼트 및 소모 잡비", "소모 잡비", "일반 관리비 및 기타 경비", "재료비 소계",
)


def test_품목코드_드롭다운에_원가계정이_없다():
    html = get("/inv/005").text
    opts = re.findall(r"<option value=\"ITEM-\d+\">([^<]*)</option>", html)
    assert opts, "품목 선택지가 비었다 — 먼저 `uv run python db/seed_dev1.py`"
    for bad in COST_ACCOUNT_LABELS:
        assert bad not in opts, f"품목 드롭다운에 원가계정 '{bad}' 이 남아 있다"


def test_원가계정_품목은_지우지_않고_사용중지한다():
    """`ITEM-nnn` 은 일련번호다 — 빼면 뒤가 밀려 기존 참조가 다른 품목을 가리킨다."""
    off = conn.q("select CODE_VALUE, CODE_NAME from BAS_COMMON_CODES "
                 "where CODE_GROUP='품목' and USE_YN='N' order by CODE_VALUE")
    names = {r["code_name"] for r in off}
    for bad in COST_ACCOUNT_LABELS:
        assert bad in names, f"'{bad}' 이 사용중지 목록에 없다"
    # **코드 자체는 살아 있다** — 시드가 넣은 `ITEM-nnn` 은 179개가 끊김 없이 그대로다.
    # (다른 검사가 만든 임시 코드는 셈에서 뺀다 — 이 단언이 보는 것은 시드 일련번호다.)
    seeded = conn.q("select CODE_VALUE from BAS_COMMON_CODES "
                    "where CODE_GROUP='품목' and CODE_VALUE like 'ITEM-%' order by CODE_VALUE")
    assert len(seeded) == 179, f"{len(seeded)}종 — 원가계정을 지워서 일련번호가 밀렸다"
    assert seeded[0]["code_value"] == "ITEM-001"
    assert seeded[-1]["code_value"] == "ITEM-179"


def test_합성_사슬은_원가계정_품목을_쓰지_않는다():
    n = int(conn.q1("select count(*) as n from EST_BOM_ITEMS b "
                    "join BAS_COMMON_CODES c on c.CODE_GROUP='품목' and c.CODE_VALUE=b.ITEM_CODE "
                    "where c.USE_YN='N'")["n"])
    assert n == 0, f"BOM 자재 {n}행이 집계/원가계정 코드를 가리킨다"


def test_원가계정_판정은_공백과_대소문자를_무시한다():
    from kyungdong.cad.quote import is_cost_account
    for s in ("소 계", "SUB TOTAL", "LAB OUR", "labour", "공 과 잡 비", "일 반 관 리 비"):
        assert is_cost_account(s), s
    for s in ("REACTOR", "ACID CLEANING", "MAIN BODY", "AGITATOR"):
        assert not is_cost_account(s), s


# ═════════════════════════════════════════════════════════════════════════
# ④ 007 '검증 결과' 조회칸이 실제로 거른다
# ═════════════════════════════════════════════════════════════════════════
VERIFY_RESULTS = ("정합", "오류", "검사 판정 없음", "MTC 미첨부")


def test_007_검증결과_조회칸이_실제로_거른다():
    whole = total_of(get("/inv/007").text, "입고 연계")
    parts = {v: total_of(get(f"/inv/007?verify={v}").text, "입고 연계") for v in VERIFY_RESULTS}
    assert sum(parts.values()) == whole, f"부분합 {parts} ≠ 전체 {whole}"
    # 적어도 한 갈래는 전체와 달라야 '걸렀다' 고 말할 수 있다
    assert any(n != whole for n in parts.values()), f"어떤 값으로도 줄지 않는다 — 거르지 않는다 {parts}"


def test_007_검증결과_SQL판정과_화면판정이_어긋나지_않는다():
    """SQL `case when`(거름) 과 파이썬 `verdict()`(표시) 가 어긋나면 필터가 거짓말한다.

    걸러 낸 쪽의 **모든 행**이 그 판정으로 보여야 한다.
    """
    for v in VERIFY_RESULTS:
        html = get(f"/inv/007?verify={v}").text
        n = total_of(html, "입고 연계")
        if n == 0:
            continue
        body = html.split('<h2>입고 연계')[1].split("</table>")[0]
        cells = re.findall(r"<td>(?:<span[^>]*>)?([^<]*)", body)
        shown = [x for x in cells if x.strip() in VERIFY_RESULTS]
        assert shown, f"verify={v} 인데 판정 칸이 비었다"
        assert set(shown) == {v}, f"verify={v} 로 걸렀는데 화면 판정은 {set(shown)}"


# ═════════════════════════════════════════════════════════════════════════
# ⑤ Excel 적재 결과가 화면에 남는다
# ═════════════════════════════════════════════════════════════════════════
def test_엑셀_적재결과가_화면에_보인다():
    html = get("/inv/007?loaded=7&failed=2").text
    assert "적재 7건 · 실패 2건" in html


# ═════════════════════════════════════════════════════════════════════════
# ⑨ 쪽 번호를 전부 그리지 않는다
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", ["/sys/027", "/inv/007", "/dat/034", "/bas/032"])
def test_쪽번호_앵커는_20개_미만이다(path):
    for page in (1, 2, 300):
        html = get(f"{path}?page={page}").text
        n = len(re.findall(r"\?[^\"']*page=\d+", html))
        assert n < 20, f"{path}?page={page} 에 쪽 앵커가 {n}개다 (전부 그리고 있다)"


def test_쪽_넘김_링크는_첫쪽과_끝쪽을_남긴다():
    # 가운데 쪽에서 본다 — 마지막 쪽에 서 있으면 마지막 쪽은 링크가 아니라 **현재 쪽(굵게)** 이다.
    # 전에는 `?page=300` 을 청해 표가 6,000행을 넘던 DB 에서만 통과했다(db-reset 뒤 172쪽 → 실패).
    html = get("/sys/027?page=300").text
    m = re.search(r"(\d+)/(\d+) 쪽", html)
    assert m, "쪽 표시가 없다"
    cur, last = m.group(1), m.group(2)
    assert int(last) > 2, f"쪽이 {last}개뿐이라 첫·끝 링크를 잴 수 없다 — 시드가 줄었는가"
    assert cur == last, "page=300 은 마지막 쪽으로 붙여야 한다(범위 밖 쪽 번호는 끝으로 붙인다)"
    assert f"<b>{last}</b>" in html, "마지막 쪽에 서 있으면 마지막 쪽이 현재 쪽으로 굵게 표시돼야 한다"
    assert "page=1\"" in html, "첫 쪽으로 가는 링크가 없다"
    html = get("/sys/027?page=2").text
    m = re.search(r"(\d+)/(\d+) 쪽", html)
    assert m and m.group(1) == "2"
    assert f"page={last}\"" in html, "가운데 쪽에서 마지막 쪽으로 가는 링크가 없다"
    assert "page=1\"" in html, "가운데 쪽에서 첫 쪽으로 가는 링크가 없다"


def test_쪽_넘김_링크는_조회조건을_URL인코딩한다():
    """`?kind=접속&page=2` 의 한글·공백이 날것으로 나가면 링크가 깨진다."""
    html = get("/sys/027?kind=접속").text
    assert "page=" in html
    assert "kind=%EC%A0%91%EC%86%8D" in html, "조회조건이 URL 인코딩되지 않았다"


# ═════════════════════════════════════════════════════════════════════════
# ⑪ 역할 매트릭스를 넓게 읽어 권한을 더 주지 않는다 (G-28)
# ═════════════════════════════════════════════════════════════════════════
DATA_OPS_ALLOWED = ("PRODUCTION", "QUALITY", "SYSADMIN")
DATA_OPS_DENIED = ("OPERATOR", "SUPPLIER_OPS", "EXEC")


@pytest.mark.parametrize("role", DATA_OPS_DENIED)
def test_집계와_재전송은_현장입력_역할에게_403이다(role):
    """OPERATOR 셀 'POP·패드 입력' 은 데이터 입력이지 ERP 재전송·평가산출이 아니다."""
    h = {"x-kyungdong-role": role}
    assert csrf_post(client, "/inv/007", {"action": "verify"}, headers=h).status_code == 403
    assert csrf_post(client, "/inv/007", {"action": "resend"}, headers=h).status_code == 403
    assert csrf_post(client, "/inv/008", {"action": "evaluate"}, headers=h).status_code == 403


@pytest.mark.parametrize("role", DATA_OPS_ALLOWED)
def test_집계와_재전송은_생산품질시스템관리자에게_열려있다(role):
    h = {"x-kyungdong-role": role}
    assert csrf_post(client, "/inv/007", {"action": "verify"}, headers=h).status_code != 403
    assert csrf_post(client, "/inv/008", {"action": "evaluate"}, headers=h).status_code != 403


@pytest.mark.parametrize("role", ["SUPPLIER_OPS", "OPERATOR", "QUALITY", "EXEC", "PRODUCTION"])
def test_계정등록은_시스템관리자만_한다(role):
    """SUPPLIER_OPS 셀 '설정 지원' 은 설정을 돕는 것이지 계정 생성이 아니다."""
    r = csrf_post(client, "/sys/026",
                  {"login_id": f"zz-{role.lower()}", "user_name": "테스트",
                   "role_code": "OPERATOR"},
                  headers={"x-kyungdong-role": role})
    assert r.status_code in (403,), f"{role} 이 계정을 만들 수 있었다 → {r.status_code}"


def test_권한없는_역할에게는_버튼도_잠겨있다():
    """서버만 막고 버튼을 열어 두면 사용자가 403 을 받고서야 안다 (G-28 고지)."""
    html = get("/inv/007", role="OPERATOR").text
    assert "정합성 검증" in html
    assert "disabled" in html
    assert "권한이 없다" in html


def test_사용자등록_폼은_공급기업담당에게_잠겨있다():
    html = get("/sys/026", role="SUPPLIER_OPS").text
    assert "사용자 등록" in html
    assert "계정 생성은 시스템 관리자만 한다" in html


# ═════════════════════════════════════════════════════════════════════════
# ⑦ 반출 거절도 흔적을 남긴다 (9.2 ①)
# ═════════════════════════════════════════════════════════════════════════
def test_반출_거절은_미승인으로_기록되고_403이다():
    """현재 시드에는 '화면은 쓸 수 있는데 반출은 못 하는' 역할이 없다 —
    그 조합을 만들어 거절 경로를 실제로 밟는다. 끝나면 되돌린다."""
    before = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS "
                         "where APPROVED_YN='N'")["n"])
    conn.x("update SYS_ROLE_PERMISSIONS set DOWNLOAD_YN='N' "
           "where ROLE_CODE='QUALITY' and AREA_CODE='DAT'")
    try:
        r = csrf_post(client, "/dat/036", {"category": "CAD", "fmt": "CSV"},
                      headers={"x-kyungdong-role": "QUALITY"})
        assert r.status_code == 403, r.status_code
        after = int(conn.q1("select count(*) as n from DAT_DOWNLOAD_LOGS "
                            "where APPROVED_YN='N'")["n"])
        assert after == before + 1, "거절이 통제 기록에 남지 않았다 (9.2 ①)"
    finally:
        conn.x("update SYS_ROLE_PERMISSIONS set DOWNLOAD_YN='Y' "
               "where ROLE_CODE='QUALITY' and AREA_CODE='DAT'")


def test_반출_건수는_0으로_적지_않는다():
    r = csrf_post(client, "/dat/036", {"category": "CAD", "fmt": "CSV"},
                  headers={"x-kyungdong-role": "SYSADMIN"})
    assert r.status_code == 200, r.status_code
    row = conn.q1("select ROW_CNT from DAT_DOWNLOAD_LOGS where APPROVED_YN='Y' "
                  "and DATA_CATEGORY='CAD' order by DOWNLOAD_ID desc limit 1")
    assert row is not None
    expect = int(conn.q1("select count(*) as n from EST_CAD_DRAWINGS")["n"])
    assert int(row["row_cnt"]) == expect, f"{row['row_cnt']} ≠ 실측 {expect}"


# ═════════════════════════════════════════════════════════════════════════
# ⑥ ⑧ ⑩ ⑬ — 화면이 거짓말하지 않는다
# ═════════════════════════════════════════════════════════════════════════
def test_034_제품LOT칸은_입력을_받지_않는다고_적혀있다():
    html = get("/dat/034").text
    assert "미확정 (D-06)" in html
    assert "disabled" in html
    # 정본 칸 수는 그대로 5개다
    assert html.count('<div class="d1-cond">') == 1


def test_034_공정칸은_설비를_고른다고_밝힌다():
    assert "공정 (설비 코드)" in get("/dat/034").text


def test_029는_암호화했다고_말하지_않는다():
    """값이 있는 인터페이스설정 행이 있어야 값 칸을 볼 수 있다 — 하나 넣고 본다."""
    csrf_post(client, "/sys/029",
              {"config_type": "인터페이스설정", "config_key": "ZZ_AUDIT_ENDPOINT",
               "config_value": "plain-value-zzz"},
              headers={"x-kyungdong-role": "SYSADMIN"})
    html = get("/sys/029?type=인터페이스설정").text
    assert "plain-value-zzz" not in html, "비표시 대상 값이 화면에 나갔다"
    assert "(암호화 저장)" not in html, "암호화하지 않으면서 암호화했다고 적었다"
    assert "값 비표시 (암호화 미구현 — D-15)" in html


def test_028은_구분을_바꿔도_알림기준을_벗어나지_않는다():
    """`?type=시스템설정` 이 기본 술어를 대체해 028 이 029 로 둔갑하던 결함."""
    base = total_of(get("/sys/028").text, "알림 기준")
    other = total_of(get("/sys/028?type=시스템설정").text, "알림 기준")
    assert other == 0, f"알림기준 밖의 설정 {other}건이 028 에 나왔다"
    assert total_of(get("/sys/028?type=알림기준").text, "알림 기준") == base


def test_029_인터페이스_선택지는_프로그램명을_보여준다():
    html = get("/sys/029").text
    if "MES-TD4-046" in html:
        assert "ERP 연계 인터페이스" in html, "인터페이스 ID 만 보이고 이름이 없다"


@pytest.mark.parametrize("path", ["/inv/006", "/inv/007", "/sys/027",
                                  "/dat/033", "/dat/034", "/dat/036"])
def test_기간칸은_시작일임을_밝힌다(path):
    assert "기간 (시작일)" in get(path).text, path
