"""수집 적재 (MES-TD4-047) — 유실 0 · 순서 보존 · 무손실 재전송.

  수집 API → `IF_PLC_SIGNALS`(수신) → `PRC_EQUIP_SIGNALS` · `DAT_TIMESERIES` → `IF_PLC_SIGNALS`(적재)

**한 배치는 한 트랜잭션이다.** 중간에 터지면 전부 롤백하고 예외를 다시 던진다 —
절반만 들어간 상태를 남기지 않는다. 호출자(게이트웨이)는 실패한 배치를
`IF_GATEWAY_BUFFER` 에 쌓았다가 복구 시 **들어온 순서 그대로** 재전송한다.

재전송이 행을 두 배로 만들지 않도록 `(DEVICE_ID, TAG_NAME, COLLECT_DT)` 로 중복을 건너뛴다 —
TD5 에 유니크 제약이 없으므로(컬럼·제약을 추가하지 않는다) 애플리케이션이 막는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

import conn

from ..app.settings import settings
from ..app.util import http
from ..app.util.codes import require_code
from . import tags

# 수집 경로 라벨 — TD5 `DAT_TIMESERIES.COLLECT_PATH` 비고 그대로
COLLECT_PATH = "PLC→Gateway→시계열DB"
COLLECT_PATH_SIM = "시뮬레이터(PLC→Gateway)"

# TD5 `IF_GATEWAY_BUFFER.BUFFER_REASON` · `BUFFER_STATUS` 비고
BUFFER_REASONS = ("네트워크 단절", "클라우드 오류")
BUFFER_STATUSES = ("대기", "전송완료", "폐기")


@dataclass(frozen=True)
class Sample:
    """PLC 한 태그의 한 시점 값."""
    tag: str
    value: str
    collect_dt: datetime
    protocol: str = "OPC-UA"

    def as_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "value": self.value,
                "collect_dt": self.collect_dt.isoformat(), "protocol": self.protocol}


@dataclass
class IngestResult:
    received: int = 0
    stored: int = 0            # IF_PLC_SIGNALS 신규 행
    duplicated: int = 0        # 재전송으로 이미 있던 행
    signal_rows: int = 0       # PRC_EQUIP_SIGNALS 신규 행
    timeseries_rows: int = 0   # DAT_TIMESERIES 신규 행
    order: list[datetime] = field(default_factory=list)

    @property
    def ordered(self) -> bool:
        """수집 시각이 들어온 순서대로 비내림차순인지 — 순서 보존 단언용."""
        return all(a <= b for a, b in zip(self.order, self.order[1:]))


def _parse_sample(raw: dict[str, Any]) -> Sample:
    try:
        return Sample(
            tag=str(raw["tag"]),
            value="" if raw.get("value") is None else str(raw["value"]),
            collect_dt=raw["collect_dt"] if isinstance(raw.get("collect_dt"), datetime)
            else datetime.fromisoformat(str(raw["collect_dt"])),
            protocol=str(raw.get("protocol") or "OPC-UA"),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise http.fail("validation", f"수집 payload 형식 오류: {e}") from e


def parse_samples(rows: Iterable[dict[str, Any]]) -> list[Sample]:
    return [_parse_sample(r) for r in rows]


def _numeric(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ingest_batch(
    device_id: int,
    equip_code: str,
    samples: Sequence[Sample],
    *,
    collect_path: str = COLLECT_PATH,
) -> IngestResult:
    """한 배치를 한 트랜잭션으로 적재한다. 순서는 **들어온 그대로** 유지한다."""
    if not samples:
        raise http.fail("validation", "수집 payload 가 비어 있다")
    # 코드성 FK 는 DB 가 막지 않는다 (D-32)
    require_code("PRC_EQUIP_SIGNALS", "EQUIP_CODE", equip_code)
    unknown = sorted({s.tag for s in samples if tags.tag(s.tag) is None})
    if unknown:
        raise http.fail(
            "validation",
            f"정본(사업계획서 2.7.1)에 없는 태그 {unknown} — 8종만 받는다",
        )

    res = IngestResult(received=len(samples), order=[s.collect_dt for s in samples])
    # 한 수집 시각에 모인 태그들을 PRC_EQUIP_SIGNALS 한 행으로 접는다. 순서는 유지한다.
    by_dt: dict[datetime, dict[str, str]] = {}
    with conn.tx() as cur:
        for s in samples:
            t = tags.BY_NAME[s.tag]
            cur.execute(
                "select PLC_IF_ID from IF_PLC_SIGNALS "
                "where DEVICE_ID = %s and TAG_NAME = %s and COLLECT_DT = %s",
                (device_id, s.tag, s.collect_dt),
            )
            if cur.fetchone():
                res.duplicated += 1          # 재전송 — 두 번 쌓지 않는다
                continue
            cur.execute(
                "insert into IF_PLC_SIGNALS "
                "(DEVICE_ID, TAG_NAME, RAW_VALUE, CONVERTED_VALUE, PROTOCOL, COLLECT_DT, IF_STATUS, CREATED_DT) "
                "values (%s,%s,%s,%s,%s,%s,%s, now()) returning PLC_IF_ID",
                (device_id, s.tag, s.value, _numeric(s.value) if t.numeric else None,
                 s.protocol, s.collect_dt, "수신"),
            )
            res.stored += 1
            by_dt.setdefault(s.collect_dt, {})[s.tag] = s.value

        for dt in sorted(by_dt):
            values = by_dt[dt]
            cur.execute(
                "select SIGNAL_ID from PRC_EQUIP_SIGNALS where EQUIP_CODE = %s and COLLECT_DT = %s",
                (equip_code, dt),
            )
            row = cur.fetchone()
            cols = {t.column: values.get(t.name) for t in tags.TAGS if t.name in values}
            run_status = cols.pop("RUN_STATUS", None)
            alarm = cols.pop("ALARM_CODE", None)
            if run_status is not None and run_status not in tags.RUN_STATUSES:
                raise http.fail("validation", f"가동 상태 어휘 위반: {run_status!r} (TD5 {tags.RUN_STATUSES})")
            nums = {k: _numeric(v) for k, v in cols.items()}
            if row is None:
                keys = ["EQUIP_CODE", "COLLECT_DT", "RUN_STATUS", "ALARM_CODE", *nums]
                cur.execute(
                    f"insert into PRC_EQUIP_SIGNALS ({', '.join(keys)}, CREATED_DT) "
                    f"values ({', '.join(['%s'] * len(keys))}, now())",
                    (equip_code, dt, run_status, alarm or None, *nums.values()),
                )
                res.signal_rows += 1
            else:
                sets = ["RUN_STATUS = coalesce(%s, RUN_STATUS)", "ALARM_CODE = coalesce(%s, ALARM_CODE)"]
                params: list[Any] = [run_status, alarm or None]
                for k, v in nums.items():
                    sets.append(f"{k} = coalesce(%s, {k})")
                    params.append(v)
                params.append(row["signal_id"])
                cur.execute(
                    f"update PRC_EQUIP_SIGNALS set {', '.join(sets)} where SIGNAL_ID = %s", params
                )

            for t in tags.numeric_tags():
                if t.name not in values:
                    continue
                v = _numeric(values[t.name])
                cur.execute(
                    "select TS_ID from DAT_TIMESERIES "
                    "where TAG_NAME = %s and EQUIP_CODE = %s and MEASURE_DT = %s",
                    (t.name, equip_code, dt),
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    "insert into DAT_TIMESERIES "
                    "(TAG_NAME, EQUIP_CODE, MEASURE_DT, MEASURE_VALUE, UOM, QUALITY_FLAG, COLLECT_PATH, CREATED_DT) "
                    "values (%s,%s,%s,%s,%s,%s,%s, now())",
                    (t.name, equip_code, dt, v, t.uom,
                     "정상" if v is not None else "결측", collect_path),
                )
                res.timeseries_rows += 1

        cur.execute(
            "update IF_PLC_SIGNALS set IF_STATUS = %s "
            "where DEVICE_ID = %s and IF_STATUS = %s and COLLECT_DT between %s and %s",
            ("적재", device_id, "수신", min(res.order), max(res.order)),
        )
    return res


# ── Gateway 로컬 버퍼 (IF_GATEWAY_BUFFER) ─────────────────────────────────
def buffer(device_id: int, equip_code: str, samples: Sequence[Sample],
           reason: str = "네트워크 단절") -> int:
    """단절 구간의 배치를 로컬에 쌓는다. **버린 데이터가 0 이어야 한다.**"""
    if reason not in BUFFER_REASONS:
        raise http.fail("validation", f"버퍼 사유 어휘 위반: {reason!r} (TD5 {BUFFER_REASONS})")
    payload = json.dumps(
        {"equip_code": equip_code, "samples": [s.as_dict() for s in samples]},
        ensure_ascii=False,
    )
    row = conn.q1(
        "insert into IF_GATEWAY_BUFFER "
        "(DEVICE_ID, PAYLOAD, BUFFER_REASON, RETRY_CNT, BUFFERED_DT, BUFFER_STATUS, CREATED_DT) "
        "values (%s,%s,%s,0,%s,%s, now()) returning BUFFER_ID",
        (device_id, payload, reason, min(s.collect_dt for s in samples), "대기"),
    )
    return int(row["buffer_id"])


def pending_buffer(device_id: int | None = None) -> list[dict[str, Any]]:
    sql = ("select BUFFER_ID, DEVICE_ID, PAYLOAD, BUFFER_REASON, RETRY_CNT, BUFFERED_DT "
           "from IF_GATEWAY_BUFFER where BUFFER_STATUS = '대기'")
    params: tuple[Any, ...] = ()
    if device_id is not None:
        sql += " and DEVICE_ID = %s"
        params = (device_id,)
    return conn.q(sql + " order by BUFFERED_DT, BUFFER_ID", params)


def resend(device_id: int | None = None) -> dict[str, Any]:
    """복구 시 **최초 저장 순서대로** 재전송한다. 유실 0 이 목표다."""
    sent, failed, rows = 0, 0, 0
    for buf in pending_buffer(device_id):
        body = json.loads(buf["payload"])
        samples = parse_samples(body["samples"])
        try:
            r = ingest_batch(int(buf["device_id"]), body["equip_code"], samples)
        except Exception:
            conn.x("update IF_GATEWAY_BUFFER set RETRY_CNT = RETRY_CNT + 1 where BUFFER_ID = %s",
                   (buf["buffer_id"],))
            failed += 1
            raise
        rows += r.stored
        conn.x(
            "update IF_GATEWAY_BUFFER set BUFFER_STATUS = %s, RETRY_CNT = RETRY_CNT + 1, RESENT_DT = now() "
            "where BUFFER_ID = %s",
            ("전송완료", buf["buffer_id"]),
        )
        sent += 1
    return {"resent_batches": sent, "failed": failed, "stored_rows": rows}


# ── 수집 상태 (화면 /dsh/003 · /prc/022 배지 — 개발2 가 호출한다) ──────────
def status(now: datetime | None = None) -> dict[str, Any]:
    """수집 지점별 마지막 수집 시각과 중단 여부.

    `now` 는 **실시각**이다(수집이 살아 있는지 묻는 함수이므로). 시드·시뮬레이터가 만드는
    데이터의 기준일은 `clock.anchor()` 이고 이것과 다르다(§10-3).
    """
    s = settings()
    stale_sec = s.h("INGEST_STALE_SEC").as_int()
    ref = now or datetime.now()
    devices = conn.q(
        "select d.DEVICE_ID, d.DEVICE_NAME, d.DEVICE_TYPE, d.PROTOCOL, d.USE_YN, "
        "       d.COLLECT_INTERVAL, d.LOCATION_DESC, "
        "       (select max(COLLECT_DT) from IF_PLC_SIGNALS p where p.DEVICE_ID = d.DEVICE_ID) as last_dt, "
        "       (select count(*) from IF_PLC_SIGNALS p where p.DEVICE_ID = d.DEVICE_ID) as signal_cnt "
        "from IF_DEVICE_REGISTRY d order by d.DEVICE_ID"
    )
    out = []
    for d in devices:
        last = d["last_dt"]
        secs = (ref - last).total_seconds() if last else None
        stale = last is None or secs > stale_sec
        out.append({
            "device_id": int(d["device_id"]),
            "device_name": d["device_name"],
            "device_type": d["device_type"],
            "protocol": d["protocol"],
            "use_yn": d["use_yn"],
            "collect_interval": d["collect_interval"],
            "location_desc": d["location_desc"] or http.undetermined("D-26"),
            "last_collect_dt": last,
            "seconds_since": secs,
            "signal_cnt": int(d["signal_cnt"]),
            "stale": stale,
            "notice": (
                http.not_collected("D-06") if last is None
                else (http.NOTICE_INGEST_STALE.format(ts=last.strftime("%H:%M:%S")) if stale else None)
            ),
        })
    pend = conn.q1("select count(*) as n from IF_GATEWAY_BUFFER where BUFFER_STATUS = '대기'")
    return {
        "checked_at": ref,
        "stale_sec": stale_sec,
        "stale_badge": s.h("INGEST_STALE_SEC").badge,
        "points": len(out),
        "devices": out,
        "buffer_pending": int(pend["n"]) if pend else 0,
        "any_stale": any(d["stale"] for d in out),
    }
