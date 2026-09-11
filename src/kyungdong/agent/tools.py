"""Agent 도구 11종 — 시안 `factory_tools.py` 를 **TD5 68표로 재배선**한다 (D-20).

이식한 규칙
  · strict JSON schema (`additionalProperties: false` · `strict: true`)
  · **허용목록 밖 도구 이름은 거부**한다 — 몰래 새 도구를 만들지 않는다
  · **쓰기 동사 금지** — 모든 SQL 은 `select` 로 시작하고, 검사를 통과하지 못하면 터진다
버린 것: SQLite 스키마 · `demo_data: true` · 데모 예측 상수 · Streamlit

Agent 3종이 보는 도구 범위는 `TOOLSETS` 가 정한다(입고 009 · 출하 020 · 통합 038).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import conn

from ..app import design
from ..app.util import http, pii
from . import retrieval

# ── 쓰기 동사 차단 (조회 전용) ────────────────────────────────────────────
_WRITE_VERB = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|merge|call|do)\b",
    re.I,
)


def _readonly(sql: str) -> str:
    """조회 전용 단언. 쓰기 동사가 보이면 **즉시 터진다** — 조용히 실행하지 않는다."""
    head = sql.lstrip().lower()
    if not head.startswith(("select", "with")):
        raise RuntimeError(f"Agent 도구는 조회만 한다: {sql[:60]!r}")
    if _WRITE_VERB.search(sql):
        raise RuntimeError(f"Agent 도구 SQL 에 쓰기 동사가 있다: {sql[:80]!r}")
    return sql


def _q(sql: str, params: Any = ()) -> list[dict[str, Any]]:
    return conn.q(_readonly(sql), params)


# ── 개인정보 마스킹 (G-29) ────────────────────────────────────────────────
MASKED: dict[str, str] = {
    "contact_name": "name", "contact_phone": "phone", "user_name": "name",
    "email": "email", "phone_no": "phone", "ip_address": "generic",
}


def _mask_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append({k: (pii.mask(v, MASKED[k]) if k in MASKED and isinstance(v, str) else v)
                    for k, v in r.items()})
    return out


# ── 도구 구현 (D-20 재배선 표) ────────────────────────────────────────────
def search_knowledge(query: str, agent_type: str = "통합", role_code: str = "") -> dict[str, Any]:
    ev, mode = retrieval.search(query, agent_type=agent_type, role_code=role_code)
    return {
        "mode": mode,
        "count": len(ev),
        "documents": [{"filename": e.doc_name, "doc_type": e.doc_type, "chunk_seq": e.chunk_seq,
                       "text": e.snippet, "score": round(e.score, 4)} for e in ev],
        "note": "폐쇄형 — 내부 AGT_VECTOR_DOCS 만 검색했다. 외부 검색 0건.",
    }


def get_rules() -> dict[str, Any]:
    """`SYS_CONFIGS`(알림 조건) + `BAS_QUALITY_STANDARDS`. **자동 실행 엔진이 아니다.**"""
    alerts = _q(
        "select CONFIG_KEY, CONFIG_VALUE, ALERT_CONDITION, TARGET_ROLE_CODE, ALERT_CHANNEL, DESCRIPTION "
        "from SYS_CONFIGS where CONFIG_TYPE = '알림기준' and USE_YN = 'Y' order by CONFIG_KEY"
    )
    stds = _q(
        "select QSTD_CODE, PRODUCT_GROUP, INSPECT_TYPE, INSPECT_ITEM, STANDARD_SPEC, "
        "       SPEC_MIN, SPEC_MAX, UOM, JUDGE_RULE "
        "from BAS_QUALITY_STANDARDS where USE_YN = 'Y' order by QSTD_CODE"
    )
    return {"alert_rules": alerts, "quality_standards": stds,
            "note": "조건·담당자·조치·근거만 조회한다. 설비를 직접 제어하지 않는다 (D-01)."}


def get_db_records(table: str, limit: int = 20) -> dict[str, Any]:
    """허용목록(TD5 68표) 안에서만 읽는다. 목록 밖 이름은 거부다."""
    known = design.tables()
    if table not in known:
        return {"error": f"허용되지 않은 테이블입니다: {table}", "allowed": len(known)}
    cols = [c["name"] for c in design.columns_of(table)]
    rows = _q(f"select {', '.join(cols)} from {table} limit %s", (max(1, min(int(limit), 200)),))
    return {"table": table, "name": known[table]["name"], "count": len(rows),
            "records": _mask_rows(rows)}


def get_project_summary(project_no: str | None = None) -> dict[str, Any]:
    where, params = ("", [])
    if project_no:
        where, params = "where p.PROJECT_NO = %s", [project_no]
    projects = _q(
        "select p.PROJECT_NO, p.PRODUCT_GROUP, p.PROJECT_NAME, p.PROJECT_STATUS, "
        "       p.ORDER_CONFIRM_DT, p.DUE_DT, "
        "       (select count(*) from EST_CAD_DRAWINGS d where d.PROJECT_ID = p.PROJECT_ID) as drawings, "
        "       (select count(*) from PRC_WORK_ORDERS w where w.PROJECT_ID = p.PROJECT_ID) as work_orders "
        f"from EST_PROJECTS p {where} order by p.PROJECT_NO limit 20", params)
    perf = _q(
        "select w.WORK_ORDER_NO, f.PROCESS_CODE, f.GOOD_QTY, f.DEFECT_QTY, f.ACTUAL_MANHOUR, "
        "       f.START_DT, f.END_DT "
        "from PRC_PERFORMANCES f join PRC_WORK_ORDERS w on w.WORK_ORDER_ID = f.WORK_ORDER_ID "
        "join EST_PROJECTS p on p.PROJECT_ID = w.PROJECT_ID "
        + ("where p.PROJECT_NO = %s " if project_no else "")
        + "order by f.START_DT desc limit 20", params)
    return {"projects": projects, "performances": perf}


def get_material_status(project_no: str | None = None, issues_only: bool = False) -> dict[str, Any]:
    sql = (
        "select l.LOT_NO, l.ITEM_CODE, l.MATERIAL, l.THICKNESS_MM, l.CURRENT_QTY, l.LOT_STATUS, "
        "       s.LOCATION_CODE, s.STOCK_QTY, s.AVAILABLE_QTY, s.SAFETY_QTY, "
        "       r.RECEIPT_NO, r.MTC_NO, r.INSPECT_RESULT "
        "from INV_MATERIAL_LOTS l "
        "left join INV_STOCKS s on s.LOT_ID = l.LOT_ID "
        "left join INV_RECEIPTS r on r.LOT_ID = l.LOT_ID "
        "left join EST_PROJECTS p on p.PROJECT_ID = r.PROJECT_ID "
    )
    conds, params = [], []
    if project_no:
        conds.append("p.PROJECT_NO = %s")
        params.append(project_no)
    if issues_only:
        conds.append("(r.INSPECT_RESULT <> '합격' or r.MTC_NO is null or s.AVAILABLE_QTY < s.SAFETY_QTY)")
    if conds:
        sql += "where " + " and ".join(conds) + " "
    return {"materials": _q(sql + "order by l.LOT_NO limit 50", params)}


def get_incoming_inspection_issues(project_no: str | None = None) -> dict[str, Any]:
    sql = (
        "select r.RECEIPT_NO, r.RECEIPT_DT, r.MTC_NO, r.INSPECT_RESULT, r.ERP_SYNC_STATUS, "
        "       v.SUPPLIER_CODE, v.SUPPLIER_NAME, q.DEFECT_RATE, q.OTD_RATE, q.GRADE "
        "from INV_RECEIPTS r "
        "left join INV_SUPPLIERS v on v.SUPPLIER_ID = r.SUPPLIER_ID "
        "left join INV_SUPPLIER_QUALITY q on q.SUPPLIER_ID = r.SUPPLIER_ID "
        "left join EST_PROJECTS p on p.PROJECT_ID = r.PROJECT_ID "
        "where (r.INSPECT_RESULT is distinct from '합격' or r.MTC_NO is null) "
    )
    params: list[Any] = []
    if project_no:
        sql += "and p.PROJECT_NO = %s "
        params.append(project_no)
    return {"issues": _q(sql + "order by r.RECEIPT_DT desc limit 50", params)}


def get_quote_analysis(project_no: str | None = None,
                       product_group: str | None = None) -> dict[str, Any]:
    conds, params = [], []
    if project_no:
        conds.append("p.PROJECT_NO = %s")
        params.append(project_no)
    if product_group:
        conds.append("p.PRODUCT_GROUP = %s")
        params.append(product_group)
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    quotes = _q(
        "select q.QUOTE_NO, p.PROJECT_NO, q.CALC_METHOD, q.TOTAL_AMOUNT, q.MATERIAL_COST, "
        "       q.PROCESS_COST, q.OUTSOURCE_COST, q.CONFIDENCE_SCORE, q.QUOTE_STATUS "
        "from EST_QUOTATIONS q join EST_PROJECTS p on p.PROJECT_ID = q.PROJECT_ID "
        f"{where}order by q.QUOTE_NO limit 20", params)
    preds = _q(
        "select m.MODEL_NAME, r.TARGET_TYPE, r.PREDICT_VALUE, r.ACTUAL_VALUE, r.ERROR_RATE, "
        "       r.CONFIDENCE_SCORE, r.PREDICTED_DT "
        "from EST_ML_PREDICTIONS r join EST_ML_MODELS m on m.MODEL_ID = r.MODEL_ID "
        "order by r.PREDICTED_DT desc limit 20")
    shap = _q(
        "select s.FEATURE_NAME, s.SHAP_VALUE, s.RANK_NO, s.IMPACT_DIRECTION, s.EXPERT_MATCH_YN "
        "from EST_SHAP_FACTORS s order by s.PREDICT_ID desc, s.RANK_NO limit 20")
    return {
        "quotations": quotes, "predictions": preds, "shap_top": shap,
        "note": "견적 확정은 담당자 승인 대상이다 (G-24). 예측값을 실제 달성값으로 말하지 않는다.",
    }


def get_procurement_risks(project_no: str | None = None,
                          supplier: str | None = None) -> dict[str, Any]:
    conds, params = [], []
    if supplier:
        conds.append("(v.SUPPLIER_CODE = %s or v.SUPPLIER_NAME = %s)")
        params += [supplier, supplier]
    where = ("where " + " and ".join(conds) + " ") if conds else ""
    suppliers = _q(
        "select v.SUPPLIER_CODE, v.SUPPLIER_NAME, v.SUPPLY_TYPE, v.GRADE, v.RISK_YN, "
        "       q.OTD_RATE, q.DEFECT_RATE, q.TOTAL_SCORE "
        "from INV_SUPPLIERS v left join INV_SUPPLIER_QUALITY q on q.SUPPLIER_ID = v.SUPPLIER_ID "
        f"{where}order by v.SUPPLIER_CODE limit 50", params)
    reqs_sql = (
        "select r.ITEM_CODE, r.TOTAL_REQ_QTY, r.STOCK_QTY, r.SHORTAGE_QTY, r.REQUIRE_DT, r.PO_NEED_YN "
        "from EST_MATERIAL_REQS r join EST_BOM_HEADERS b on b.BOM_ID = r.BOM_ID "
        "join EST_PROJECTS p on p.PROJECT_ID = b.PROJECT_ID where r.PO_NEED_YN = 'Y' ")
    rparams: list[Any] = []
    if project_no:
        reqs_sql += "and p.PROJECT_NO = %s "
        rparams.append(project_no)
    return {
        "suppliers": suppliers,
        "shortages": _q(reqs_sql + "order by r.REQUIRE_DT limit 50", rparams),
        "note": "발주 테이블이 TD5 에 없다 — 외주 발주번호는 작업지시번호로 대체 표기한다 (D-41).",
    }


def get_fat_quality(project_no: str | None = None) -> dict[str, Any]:
    """출하 전 성능검사(수압·기밀·진공) 결과 + 품질기준."""
    sql = (
        "select t.PRODUCT_LOT_NO, i.INSPECT_ITEM, i.MEASURED_VALUE, i.UOM, i.JUDGE_RESULT, "
        "       i.INSPECT_DT, i.REPORT_NO, i.REJECT_REASON, "
        "       s.QSTD_CODE, s.STANDARD_SPEC, s.SPEC_MIN, s.SPEC_MAX, s.JUDGE_RULE "
        "from SHP_INSPECTIONS i "
        "left join SHP_LOT_TRACES t on t.LOT_TRACE_ID = i.LOT_TRACE_ID "
        "left join BAS_QUALITY_STANDARDS s on s.QSTD_ID = i.QSTD_ID "
        "left join EST_PROJECTS p on p.PROJECT_ID = t.PROJECT_ID "
    )
    params: list[Any] = []
    if project_no:
        sql += "where p.PROJECT_NO = %s "
        params.append(project_no)
    return {"inspections": _q(sql + "order by i.INSPECT_DT desc limit 50", params),
            "note": "검사 합격·출하 승인은 담당자 승인 대상이다 (G-24)."}


def get_lead_time_status(project_no: str | None = None) -> dict[str, Any]:
    """`LEADTIME_MFG` · `LEADTIME_O2D`(D-35). **산식은 `app/kpi.py` 한 곳**(개발2)."""
    kpis = _q(
        "select t.KPI_CODE, t.KPI_NAME, t.UOM, t.BASE_VALUE, t.TARGET_VALUE, t.IMPROVE_RATE, "
        "       t.WEIGHT, t.MEASURE_BASIS, m.PERIOD_CODE, m.MEASURE_VALUE, m.ACHIEVE_RATE, m.SAMPLE_CNT "
        "from KPI_TARGETS t left join KPI_MEASURES m on m.KPI_TARGET_ID = t.KPI_TARGET_ID "
        "where t.KPI_CODE in ('LEADTIME_MFG','LEADTIME_O2D') "
        "order by t.KPI_CODE, m.PERIOD_CODE limit 50")
    sql = (
        "select p.PROJECT_NO, p.ORDER_CONFIRM_DT, p.DUE_DT, s.SHIPMENT_NO, s.PLAN_DT, s.SHIP_DT, "
        "       s.OTD_YN, s.SHIP_STATUS "
        "from EST_PROJECTS p left join SHP_SHIPMENTS s on s.PROJECT_ID = p.PROJECT_ID ")
    params: list[Any] = []
    if project_no:
        sql += "where p.PROJECT_NO = %s "
        params.append(project_no)
    return {"kpi": kpis, "shipments": _q(sql + "order by p.PROJECT_NO limit 50", params)}


def get_claim_trace(claim_no: str) -> dict[str, Any]:
    claims = _q(
        "select c.CLAIM_NO, c.CLAIM_TYPE, c.CLAIM_DESC, c.CLAIM_STATUS, c.RECEIVED_DT, c.CLOSED_DT, "
        "       t.PRODUCT_LOT_NO, t.CURRENT_PROCESS "
        "from SHP_CLAIMS c left join SHP_LOT_TRACES t on t.LOT_TRACE_ID = c.LOT_TRACE_ID "
        "where c.CLAIM_NO = %s", (claim_no,))
    causes = _q(
        "select u.CAUSE_PROCESS, u.CAUSE_FACTOR, u.REPEAT_YN, u.ACTION_PLAN, u.PREVENT_RESULT "
        "from SHP_CLAIM_CAUSES u join SHP_CLAIMS c on c.CLAIM_ID = u.CLAIM_ID "
        "where c.CLAIM_NO = %s order by u.CAUSE_ID", (claim_no,))
    insp = _q(
        "select i.INSPECT_ITEM, i.MEASURED_VALUE, i.UOM, i.JUDGE_RESULT, i.INSPECT_DT "
        "from SHP_INSPECTIONS i join SHP_LOT_TRACES t on t.LOT_TRACE_ID = i.LOT_TRACE_ID "
        "join SHP_CLAIMS c on c.LOT_TRACE_ID = t.LOT_TRACE_ID where c.CLAIM_NO = %s "
        "order by i.INSPECT_DT desc limit 20", (claim_no,))
    return {"claims": claims, "causes": causes, "inspections": insp}


# ── 스키마 (strict) ───────────────────────────────────────────────────────
def _nullable(desc: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": desc}


def _tool(name: str, description: str, properties: dict[str, Any],
          required: list[str]) -> dict[str, Any]:
    return {
        "type": "function", "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
        "strict": True,
    }


HANDLERS: dict[str, Callable[..., Any]] = {
    "search_knowledge": search_knowledge,
    "get_rules": get_rules,
    "get_db_records": get_db_records,
    "get_project_summary": get_project_summary,
    "get_material_status": get_material_status,
    "get_incoming_inspection_issues": get_incoming_inspection_issues,
    "get_quote_analysis": get_quote_analysis,
    "get_procurement_risks": get_procurement_risks,
    "get_fat_quality": get_fat_quality,
    "get_lead_time_status": get_lead_time_status,
    "get_claim_trace": get_claim_trace,
}

# D-20 재배선 표 — 도구 ↔ TD5 테이블. 화면 038 이 그대로 렌더한다.
REWIRING: dict[str, str] = {
    "search_knowledge": "AGT_VECTOR_DOCS",
    "get_rules": "SYS_CONFIGS(알림기준) + BAS_QUALITY_STANDARDS",
    "get_db_records": "허용목록 내 68표 (읽기 전용)",
    "get_project_summary": "EST_PROJECTS + EST_CAD_DRAWINGS + PRC_WORK_ORDERS + PRC_PERFORMANCES",
    "get_material_status": "INV_MATERIAL_LOTS + INV_STOCKS + INV_RECEIPTS(MTC_NO)",
    "get_incoming_inspection_issues": "INV_RECEIPTS + INV_SUPPLIER_QUALITY",
    "get_quote_analysis": "EST_QUOTATIONS + EST_QUOTATION_ITEMS + EST_ML_PREDICTIONS + EST_SHAP_FACTORS",
    "get_procurement_risks": "INV_SUPPLIERS + INV_SUPPLIER_QUALITY + EST_MATERIAL_REQS(PO_NEED_YN)",
    "get_fat_quality": "SHP_INSPECTIONS(수압·기밀·진공) + BAS_QUALITY_STANDARDS",
    "get_lead_time_status": "KPI_MEASURES + KPI_TARGETS + PRC_PERFORMANCES + EST_PROJECTS + SHP_SHIPMENTS",
    "get_claim_trace": "SHP_CLAIMS + SHP_CLAIM_CAUSES + SHP_LOT_TRACES + SHP_INSPECTIONS",
}

# Agent 3종 ↔ 도구 (TD3 009 입고 · 020 출하 · 038 통합)
TOOLSETS: dict[str, tuple[str, ...]] = {
    "입고": ("search_knowledge", "get_rules", "get_material_status",
             "get_incoming_inspection_issues", "get_db_records"),
    "출하": ("search_knowledge", "get_rules", "get_fat_quality", "get_claim_trace",
             "get_lead_time_status", "get_db_records"),
    "통합": tuple(HANDLERS),
}


def definitions(agent_type: str = "통합") -> list[dict[str, Any]]:
    allowed = TOOLSETS.get(agent_type, TOOLSETS["통합"])
    all_defs = {
        "get_db_records": _tool(
            "get_db_records",
            "업무 DB 테이블의 실제 저장 레코드를 조회한다. 설비 수집값·전체 목록 등 원본 데이터 조회에 쓴다.",
            {"table": {"type": "string", "enum": sorted(design.tables()),
                       "description": "조회할 TD5 테이블 이름"},
             "limit": {"type": "integer", "description": "최대 행 수(1~200)"}},
            ["table", "limit"]),
        "search_knowledge": _tool(
            "search_knowledge",
            "사내 지식문서(작업표준·품질기준·검사기준·클레임 매뉴얼)를 폐쇄형으로 검색한다. "
            "승인 절차·검사기준·작업표준 질문에 반드시 먼저 쓴다.",
            {"query": {"type": "string", "description": "문서 검색어 또는 질문"}}, ["query"]),
        "get_rules": _tool(
            "get_rules",
            "등록된 알림 조건과 품질기준의 조건·담당자·조치·근거를 조회한다. 자동 실행 엔진이 아니다.",
            {}, []),
        "get_project_summary": _tool(
            "get_project_summary", "프로젝트(수주)·도면 버전·작업지시·공정실적 현황을 조회한다.",
            {"project_no": _nullable("프로젝트(수주)번호. 전체이면 null")}, ["project_no"]),
        "get_material_status": _tool(
            "get_material_status", "자재 LOT, MTC, 보관위치, 부족·보류 상태를 조회한다.",
            {"project_no": _nullable("프로젝트(수주)번호. 전체이면 null"),
             "issues_only": {"type": "boolean", "description": "이슈만 조회할지 여부"}},
            ["project_no", "issues_only"]),
        "get_incoming_inspection_issues": _tool(
            "get_incoming_inspection_issues", "입고검사 보류·불합격과 MTC 누락을 조회한다.",
            {"project_no": _nullable("프로젝트(수주)번호. 전체이면 null")}, ["project_no"]),
        "get_quote_analysis": _tool(
            "get_quote_analysis",
            "견적 원가·신뢰도와 저장된 예측·영향요인을 조회한다. 예측값을 달성값처럼 말하지 않는다.",
            {"project_no": _nullable("프로젝트(수주)번호"),
             "product_group": _nullable("반응기·교반기·진공건조기·누체필터·저장탱크")},
            ["project_no", "product_group"]),
        "get_procurement_risks": _tool(
            "get_procurement_risks", "공급처 납기·품질 위험과 자재 부족을 조회한다. 발주·대체는 승인 대상이다.",
            {"project_no": _nullable("프로젝트(수주)번호"), "supplier": _nullable("공급처 코드 또는 명")},
            ["project_no", "supplier"]),
        "get_fat_quality": _tool(
            "get_fat_quality", "출하 전 성능검사(수압·기밀·진공) 결과와 적용 품질기준을 조회한다.",
            {"project_no": _nullable("프로젝트(수주)번호. 전체이면 null")}, ["project_no"]),
        "get_lead_time_status": _tool(
            "get_lead_time_status", "제조 리드타임·수주출하 리드타임 목표와 측정값, 출하 예정을 조회한다.",
            {"project_no": _nullable("프로젝트(수주)번호. 전체이면 null")}, ["project_no"]),
        "get_claim_trace": _tool(
            "get_claim_trace", "클레임을 제품 LOT·검사 이력과 연결해 조회한다.",
            {"claim_no": {"type": "string", "description": "클레임 번호"}}, ["claim_no"]),
    }
    return [all_defs[n] for n in allowed]


def execute(name: str, arguments: str | dict[str, Any], *,
            agent_type: str = "통합", role_code: str = "") -> str:
    """허용목록 밖 도구는 **거부**한다. 결과는 JSON 문자열이다(`demo_data` 플래그는 버렸다)."""
    allowed = TOOLSETS.get(agent_type, TOOLSETS["통합"])
    if name not in HANDLERS or name not in allowed:
        return json.dumps({"error": "허용되지 않은 도구입니다.", "tool": name,
                           "allowed": list(allowed)}, ensure_ascii=False)
    try:
        payload = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        if name == "search_knowledge":
            payload.setdefault("agent_type", agent_type)
            payload.setdefault("role_code", role_code)
        return json.dumps({"status": "ok", "result": HANDLERS[name](**payload)},
                          ensure_ascii=False, default=str)
    except http.HTTPException:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        return json.dumps({"error": str(e), "tool": name}, ensure_ascii=False)
