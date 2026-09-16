"""과거 견적서(.xls) 파서 (D-111) — **G-15 견적 Label · G-17 납기 Label 후보를 뽑는다.**

D-04 는 "과거 견적금액·실제 제조원가 Label 확보 미확인" 이라고 적었다. 실측해 보니
원본 아카이브에 **`견적` 파일 73건**(xls 31 · pdf 29 · docx 8 · pptx 3 · jpg 2)이 있고
`.xls` 31건은 **읽기 실패 0** 이다. 다만 **"금액 표기가 있다" 와 "금액을 정확히 뽑았다" 는
다른 사실이다** — 이 모듈은 뽑은 건수와 못 뽑은 사유를 둘 다 돌려준다.

총액 추출 순서 (앞의 것이 이기고, 어느 것으로 뽑았는지 `total_method` 에 남긴다)
  ① `숫자셀`   — `合計金額`·`합계금액`·`Total Amount` 라벨 **오른쪽의 숫자 셀**. 가장 안전하다.
  ② `괄호숫자` — `一金 四千五百三十六萬五千(45,365,000)원 整` 처럼 **괄호 안 아라비아 숫자**.
  ③ `한자금액` — `伍億四阡七百參拾七萬伍阡` 처럼 한자 수사만 있는 경우. 갖은자(壹貳參…)를 읽는다.
                 `…六千萬院整` 처럼 **끝에 장식으로 붙은 단위 한 글자**는 떼고 읽는다.
  ④ 실패      — 라벨은 있는데 값이 없거나, 한 행에 **금액 후보가 둘 이상**이라 고를 수 없을 때.
                 **추측해서 하나를 고르지 않는다.** 사유를 `failures` 에 적는다.

납기는 `發注後 50 日間` · `발주일로부터 70일` · `발주후 45일` 을 **일수**로 읽는다.
`신속납기` 처럼 숫자가 없는 표기는 뽑지 않는다 — 0일이라고 적으면 거짓이다.

**macOS 한글 파일명은 NFD 다**(D-115). 이 모듈이 다루는 모든 문자열은 `NFC` 로 정규화한 뒤
비교한다. 하지 않으면 `견적` 검색이 0건을 낸다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `.xls` 는 BIFF 바이너리라 openpyxl 로 못 읽는다. xlrd 2.x 가 .xls 전용이다.
XLRD_MISSING = ("xlrd 미설치 — `.xls`(BIFF)는 openpyxl 로 읽을 수 없다. "
                "`uv add --dev xlrd` 로 넣는다")


def nfc(s: Any) -> str:
    return unicodedata.normalize("NFC", str(s)) if s is not None else ""


def _sq(s: Any) -> str:
    """공백을 전부 뗀 NFC 문자열 — `合 計 金 額` 같은 자간 벌린 라벨을 잡으려면 필요하다."""
    return re.sub(r"\s+", "", nfc(s))


# **맨 '금액' 은 넣지 않는다** — 명세표의 `금  액` 열 머리글과 구별되지 않아, 품목 단가를
# 총액으로 잘못 집어 온다(실측으로 확인: `견적서-REACTOR 일성.xls` 가 合計 67,026,000 대신
# 품목 67,026,761 을 냈다). 한자 `金額` 은 갑지 표기라 남긴다.
TOTAL_LABEL = re.compile(
    r"(合計金額|合計金|合計|金額|합계금액|합계금|총금액|총액|공사금액|工事金額|工事金|"
    r"一金|壹金|일금|TOTALAMOUNT|GRANDTOTAL)", re.I)
# 라벨 옆에 숫자가 아니라 다른 라벨이 오는 경우를 걸러내려고 쓴다.
_SKIP_CELL = re.compile(r"^[:：\-=\s]*$")
PAREN_AMOUNT = re.compile(r"[（(]\s*[\\￦W₩]?\s*([0-9][0-9,]{5,})\s*[)）]")
# `￦ 58,244,480` — 통화기호가 붙은 아라비아 숫자. **기호 없는 맨 숫자는 잡지 않는다**
# (명세표의 단가와 구별되지 않는다).
CURRENCY_AMOUNT = re.compile(r"[\\￦₩]\s*([0-9][0-9,]{5,})")
# `일금5,200,000원정` — 수사 접두어가 붙은 아라비아 숫자. 접두어를 **요구**한다.
PREFIXED_AMOUNT = re.compile(r"(?:일금|壹金|一金)\s*[\\￦₩W]?\s*([0-9][0-9,]{5,})")
LEAD_DAYS = re.compile(r"(?:발주일로부터|발주후|발주일후|發注後|發注日로부터)\D{0,6}?(\d{1,3})\s*(?:日|일)")
PROJECT_LABEL = re.compile(r"^(工事名|공사명|件名|건명|품명Project|PROJECT[:：])", re.I)
# 명세표 머리글 — `품명 | 규격 | 수량 | 단가 | 금액`. 여기부터 아래가 품목 행이다.
ITEM_HEADER = (re.compile(r"^(품명|품\s*명|DESCRIPTION|內驛|내역|품목)"),
               re.compile(r"^(수량|수\s*량|Q'?TY|數量)"),
               re.compile(r"^(금액|금\s*액|PRICE|AMOUNT|金額)"))

# 명세표 안에 섞여 있는 **집계 행·원가계정 행**. 품목이 아니다 — `BAS_COMMON_CODES('품목')` 에
# 들어가면 005 입고등록 드롭다운이 "LABOUR"·"소모 잡비" 를 자재로 내놓는다(DEF).
# **정확일치가 아니라 정규화 패턴이다** — 원본은 `소 계` · `LAB OUR` · `공 과 잡 비 및 이 윤`
# 처럼 자간을 벌려 적는다. 공백을 전부 떼고 대문자로 올린 뒤 본다.
NOT_AN_ITEM = re.compile(
    r"(소계|합계|총계|잡비|경비|관리비|이윤|재보험료|인건비|노무비|"
    r"LABOU?R|COST|SUBTOTAL|TOTAL|OVERHEAD)", re.I)
# 머리글 되풀이 행 — 품목명 칸에 머리글이 다시 찍힌 경우.
_ITEM_HEADER_ECHO = ("DESCRIPTION", "품명", "내역", "품목", "ITEM")


def is_cost_account(name: str) -> bool:
    """이 이름이 품목이 아니라 **집계/원가계정** 이면 True. 공백 무시 · 대소문자 무시."""
    t = _sq(name).upper()
    return (not t) or t in _ITEM_HEADER_ECHO or bool(NOT_AN_ITEM.search(t))

# 한자 수사 — 갖은자(대사) 포함. 원본에 壹貳參肆伍陸柒捌玖 와 阡(千)·佰(百)이 섞여 나온다.
_HAN_DIGIT = {"零": 0, "〇": 0,
              "一": 1, "壹": 1, "壱": 1, "二": 2, "貳": 2, "弐": 2, "三": 3, "參": 3, "叁": 3,
              "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陸": 6, "七": 7, "柒": 7, "漆": 7,
              "八": 8, "捌": 8, "九": 9, "玖": 9}
_HAN_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "阡": 1000, "仟": 1000}
_HAN_BIG = {"萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8, "兆": 10 ** 12}
_HAN_RUN = re.compile("[" + "".join(list(_HAN_DIGIT) + list(_HAN_UNIT) + list(_HAN_BIG)) + "]{3,}")
# 금액 뒤에 붙는 장식 — `院整` 은 `圓整`(원정)의 오기다. 원본에 그대로 있다.
_HAN_TAIL = re.compile(r"^[院圓원元整정整\s]")

MIN_AMOUNT = 10_000        # 이보다 작은 값은 총액이 아니라 단가·수량이다


def han_to_int(run: str) -> int | None:
    """한자 수사 → 정수. 읽을 수 없는 글자가 하나라도 있으면 **None** 이다(추측하지 않는다)."""
    total = sect = num = 0
    for ch in run:
        if ch in _HAN_DIGIT:
            num = _HAN_DIGIT[ch]
        elif ch in _HAN_UNIT:
            sect += (num or 1) * _HAN_UNIT[ch]
            num = 0
        elif ch in _HAN_BIG:
            sect = (sect + num) * _HAN_BIG[ch]
            total += sect
            sect = num = 0
        else:
            return None
    v = total + sect + num
    return v if v >= MIN_AMOUNT else None


@dataclass
class QuoteItem:
    name: str
    spec: str | None
    qty: float | None
    uom: str | None
    unit_price: float | None
    amount: float | None


@dataclass
class QuoteDoc:
    """견적서 한 건의 실측. **못 뽑은 것은 `None` 이고 사유가 `failures` 에 남는다.**"""

    path: str
    file_name: str
    sheets: int = 0
    total_amount: float | None = None
    total_method: str | None = None      # 숫자셀 · 괄호숫자 · 한자금액
    total_cell: str | None = None        # 어느 시트·행에서 뽑았는지 (근거)
    # **파일 1건 = 견적 1건이 아니다.** `반응기2000-타견적.xls` 처럼 한 통합문서에 갑지가
    # 2장(8000리터·2000리터) 들어 있는 파일이 있다. 시트별 총액을 전부 남긴다 — 첫 장만
    # 쓰고 나머지를 버리면 Label 후보를 조용히 잃는다.
    sheet_totals: list[dict[str, Any]] = field(default_factory=list)
    lead_days: int | None = None
    lead_text: str | None = None
    project_name: str | None = None
    customer: str | None = None
    quote_date: str | None = None
    items: list[QuoteItem] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _cells(sheet, r: int) -> list[Any]:
    return [sheet.cell(r, c) for c in range(sheet.ncols)]


def _row_text(cells: list[Any], xlrd) -> str:
    return nfc(" ".join(str(c.value) for c in cells if c.ctype == xlrd.XL_CELL_TEXT))


def _amount_candidates(cells: list[Any], i: int, xlrd,
                       next_cells: list[Any] | None = None) -> list[tuple[float, str]]:
    """라벨 셀 `i` 기준으로 같은 행에서 총액 후보를 **전부** 모은다.

    후보가 둘 이상이면 호출자가 **고르지 않고 실패로 적는다** — 어느 쪽이 총액인지
    정본이 말해 주지 않는데 하나를 고르면 그게 합성이다.
    """
    out: list[tuple[float, str]] = []
    # ② 괄호·통화기호가 붙은 아라비아 숫자 — 라벨 셀 자신에 붙어 있는 경우가 많다
    for cand in cells[i:]:
        if cand.ctype != xlrd.XL_CELL_TEXT:
            continue
        s = nfc(cand.value)
        for pat, meth in ((PAREN_AMOUNT, "괄호숫자"), (CURRENCY_AMOUNT, "통화기호"),
                          (PREFIXED_AMOUNT, "통화기호")):
            for m in pat.finditer(s):
                v = float(m.group(1).replace(",", ""))
                if v >= MIN_AMOUNT:
                    out.append((v, meth))
    if out:
        return out
    # ① 라벨 오른쪽의 첫 숫자 셀. 중간에 내용 있는 문자 셀을 만나면 거기서 끊는다.
    for cand in cells[i + 1:]:
        if cand.ctype == xlrd.XL_CELL_NUMBER:
            if float(cand.value) >= MIN_AMOUNT:
                out.append((float(cand.value), "숫자셀"))
            break
        if cand.ctype == xlrd.XL_CELL_TEXT and not _SKIP_CELL.match(nfc(cand.value)):
            break
    if out:
        return out
    # ③ 한자 수사 — 같은 행 전체를 본다(병합 때문에 열이 멀리 떨어져 있다)
    for cand in cells[i:]:
        if cand.ctype != xlrd.XL_CELL_TEXT:
            continue
        t = nfc(cand.value)
        for m in _HAN_RUN.finditer(t):
            run = m.group(0)
            # `…六千萬院整` — 뒤가 '원정' 장식이면 끝에 붙은 단위 한 글자는 값이 아니다
            if run[-1] in _HAN_BIG and _HAN_TAIL.match(t[m.end():m.end() + 1] or " "):
                run = run[:-1]
            v = han_to_int(run)
            if v is not None:
                out.append((float(v), "한자금액"))
    if out:
        return out
    # ④ 라벨 **바로 아랫줄**의 통화기호 금액 — `合計金: 일금오천팔백…원정` / `￦ 58,244,480`
    #    처럼 한글 수사로 적고 숫자는 아래 줄에 적은 갑지가 있다. 한글 수사는 읽지 않는다.
    for cand in (next_cells or []):
        if cand.ctype != xlrd.XL_CELL_TEXT:
            continue
        for m in CURRENCY_AMOUNT.finditer(nfc(cand.value)):
            v2 = float(m.group(1).replace(",", ""))
            if v2 >= MIN_AMOUNT:
                out.append((v2, "통화기호"))
    return out


def _label_value(cells: list[Any], i: int, xlrd) -> str | None:
    """라벨 셀 오른쪽 값. 라벨 셀 **자신이** `工事名 : REACTOR` 처럼 값을 품고 있으면 그것을 쓴다."""
    own = nfc(cells[i].value)
    m = re.search(r"[:：]\s*(\S.*)$", own)
    if m and m.group(1).strip():
        return m.group(1).strip()[:200]
    for x in cells[i + 1:]:
        if x.ctype != xlrd.XL_CELL_TEXT:
            continue
        v = nfc(x.value).strip()
        if v and v not in (":", "："):
            return v[:200]
    return None


def _items(sheet, r: int, cells: list[Any], xlrd) -> list[QuoteItem]:
    """명세표 머리글 행을 만나면 그 아래를 품목으로 읽는다. **머리글을 못 찾으면 빈 목록**이다.

    열 위치는 파일마다 다르다(병합·빈 열). 그래서 **머리글이 있는 열 번호**를 잡아 두고
    그 열만 읽는다 — 열 순서를 가정해 옆 칸을 집어 오지 않는다.
    """
    texts = {i: _sq(c.value) for i, c in enumerate(cells) if c.ctype == xlrd.XL_CELL_TEXT}
    col: list[int | None] = [None, None, None]
    for i, t in sorted(texts.items()):
        for k, pat in enumerate(ITEM_HEADER):
            if col[k] is None and pat.match(t):
                col[k] = i
    if any(c is None for c in col):
        return []
    c_name, c_qty, c_amt = col                    # type: ignore[misc]
    out: list[QuoteItem] = []
    for rr in range(r + 1, sheet.nrows):
        row = _cells(sheet, rr)
        name = nfc(row[c_name].value).strip() if row[c_name].ctype == xlrd.XL_CELL_TEXT else ""
        amt = float(row[c_amt].value) if row[c_amt].ctype == xlrd.XL_CELL_NUMBER else None
        qty = float(row[c_qty].value) if row[c_qty].ctype == xlrd.XL_CELL_NUMBER else None
        if not name or amt is None:
            continue
        if is_cost_account(name):      # 머리글 되풀이 · 집계/원가계정 행 — 품목이 아니다
            continue
        out.append(QuoteItem(name=name[:200], spec=None, qty=qty, uom=None,
                             unit_price=None, amount=amt))
    return out


def parse(path: Path | str) -> QuoteDoc:
    """`.xls` 견적서 한 건. **열기 실패는 `error` 로 남긴다 — 빈 결과로 뭉개지 않는다.**"""
    p = Path(path)
    doc = QuoteDoc(path=str(p), file_name=nfc(p.name))
    try:
        import xlrd
    except ImportError:
        doc.error = XLRD_MISSING
        return doc
    try:
        wb = xlrd.open_workbook(str(p), on_demand=False)
    except Exception as e:                      # xlrd 는 예외 종류가 넓다
        doc.error = f"{type(e).__name__}: {e}"
        return doc

    doc.sheets = wb.nsheets
    # **첫 적중을 쓴다 — 최댓값을 고르지 않는다.** 견적서는 갑지(첫 시트 · 앞 행)에 총액을
    # 적고 뒤 시트는 계산 과정이다. 최댓값을 고르면 계산 시트의 중간값이 총액을 덮는다.
    for sh in wb.sheets():
        sheet_done = False
        for r in range(sh.nrows):
            cells = _cells(sh, r)
            line = _row_text(cells, xlrd)
            if doc.lead_days is None:
                m = LEAD_DAYS.search(re.sub(r"\s+", "", line))
                if m:
                    doc.lead_days, doc.lead_text = int(m.group(1)), line[:120]
                elif doc.lead_text is None and re.search(r"納\s*期|납\s*기|Delivery\s*Date", line, re.I):
                    doc.lead_text = line[:120]
            if not doc.items:
                doc.items = _items(sh, r, cells, xlrd)
            for i, c in enumerate(cells):
                if c.ctype != xlrd.XL_CELL_TEXT:
                    continue
                t = _sq(c.value)
                if doc.project_name is None and PROJECT_LABEL.match(t):
                    doc.project_name = _label_value(cells, i, xlrd)
                if sheet_done or not TOTAL_LABEL.search(t):
                    continue
                nxt = _cells(sh, r + 1) if r + 1 < sh.nrows else None
                cands = _amount_candidates(cells, i, xlrd, nxt)
                uniq = sorted({v for v, _ in cands})
                if not cands:
                    continue
                if len(uniq) > 1:
                    doc.failures.append(
                        f"{sh.name}!{r + 1} '{nfc(c.value).strip()[:20]}' 행에 금액 후보가 "
                        f"{len(uniq)}개({', '.join(f'{v:,.0f}' for v in uniq)}) — "
                        "어느 것이 총액인지 정본이 말해 주지 않아 고르지 않는다")
                    continue
                v, meth = cands[0]
                where = f"{sh.name}!{r + 1}"
                doc.sheet_totals.append({"sheet": sh.name, "cell": where,
                                         "amount": v, "method": meth})
                sheet_done = True
                if doc.total_amount is None:
                    doc.total_amount, doc.total_method, doc.total_cell = v, meth, where
    if doc.total_amount is None:
        doc.failures.append("총액 라벨 옆에서 금액을 찾지 못했다 — "
                            "견적요청서·부품 계산시트처럼 갑지가 없는 파일일 수 있다")
    if doc.lead_days is None:
        doc.failures.append("납기 일수를 숫자로 적은 표기가 없다 (예: '신속납기')")
    return doc


def summarize(docs: list[QuoteDoc]) -> dict[str, Any]:
    """**표본 수를 숨기지 않는다** — 몇 건 중 몇 건에서 무엇을 뽑았는지."""
    n = len(docs)
    ok = [d for d in docs if d.ok]
    tot = [d for d in ok if d.total_amount is not None]
    lead = [d for d in ok if d.lead_days is not None]
    by_method: dict[str, int] = {}
    for d in tot:
        by_method[d.total_method or "?"] = by_method.get(d.total_method or "?", 0) + 1
    return {
        "files": n,
        "opened": len(ok),
        "open_failed": n - len(ok),
        "total_extracted": len(tot),
        "total_by_method": by_method,
        # 파일 단위가 아니라 **갑지(시트) 단위** 견적 건수 — Label 후보의 실제 표본 수다
        "sheet_totals": sum(len(d.sheet_totals) for d in ok),
        "multi_quote_files": sum(1 for d in ok if len(d.sheet_totals) > 1),
        "items": sum(len(d.items) for d in ok),
        "files_with_items": sum(1 for d in ok if d.items),
        "lead_extracted": len(lead),
        "project_name_extracted": sum(1 for d in ok if d.project_name),
        "amount_min": min((d.total_amount for d in tot), default=None),
        "amount_max": max((d.total_amount for d in tot), default=None),
        "lead_days": sorted({d.lead_days for d in lead}),
    }
