#!/usr/bin/env python
"""DWG·CAD 전량 변환 + Feature 실측 (D-123 — D-05 판정 정정).

**D-05 는 "변환기가 없다" 였다. 이제 있다.** `dwg2dxf`(GNU libredwg 0.14, 사용자 승인 설치)로
`.dwg` 를 DXF 로 바꾸면 우리 `cad/dxf.py` 파서가 **그대로** 돈다(D-123 표본 30건 실측).
이 도구는 그 표본을 **전량**으로 넓힌다.

**한 건씩 흘려보낸다 — 변환 → 파싱 → 적립 → 즉시 삭제.**
전량을 보관하면 DXF 팽창률이 약 3배라 8.5GB 가 쌓인다. 여기서는 **최대 디스크 사용이
한 파일 크기**다. 중간 DXF 는 `work/dwg_convert_tmp/` 에만 잠깐 있다가 지워진다.

**네 단계를 각각 센다 — 하나로 뭉개지 않는다** (D-115 교훈).
  ① 대상 파일 수  ≠  ② 서로 다른 도면 수(내용 sha256)  ≠  ③ 변환 성공 수
  ≠  ④ 파싱 성공 수  ≠  ⑤ Feature 별 산출 수
파일 수를 표본 수로 쓰지 않는다. 복사본은 같은 도면이다.

**실패는 실패로 센다.** 변환이 안 된 것을 합성으로 채우지 않는다. 실패 사유는
  · `dwg2dxf` 의 stderr 첫 오류줄을 경로·숫자만 지워 **정규화**한 것 (지어낸 분류가 아니다)
  · 파일 앞 6바이트의 **DWG 버전 서명**(AC1015=R2000 …) — 실패가 버전별로 갈리는지 보려고
둘 다 남긴다.

**중단돼도 이어서 돈다.** 처리한 도면은 해시 단위로 `work/dwg_convert.jsonl` 에 한 줄씩
append 되고, 다시 돌리면 그 해시를 건너뛴다. `--restart` 로만 처음부터 다시 한다.

산출: `docs/cad/dwg_features.json` (집계 + 도면별 실측). **DB 적재는 하지 않는다** —
`--load-db` 를 명시로 줘야 하고, 그때도 `tools/check_ingest.py` ⑤ 판정과 충돌하는지
먼저 재서 보고한다(아래 `load_db()` 주석).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

from kyungdong.cad import archive                    # noqa: E402
from kyungdong.cad import dwgconv                    # noqa: E402
from kyungdong.cad import dxf                        # noqa: E402

CONVERTER = dwgconv.BINARY
TMP_DIR = ROOT / "work" / "dwg_convert_tmp"
LEDGER = ROOT / "work" / "dwg_convert.jsonl"          # 해시 1개 = 한 줄 (재개용)
HASH_CACHE = ROOT / "work" / "dwg_hash_index.json"    # (rel, size, mtime) → sha256
OUT_JSON = ROOT / "docs" / "cad" / "dwg_features.json"

CONVERT_EXTS = ("dwg", "cad")      # 변환이 필요한 것
DIRECT_EXTS = ("dxf",)             # 이미 텍스트라 그대로 읽는다
DEFAULT_TIMEOUT = dwgconv.DEFAULT_TIMEOUT


def measured_at() -> str:
    """측정 시각. **DB 시계(`clock.real_now()`)를 쓴다.**

    파이썬 `datetime.now()` 는 이 저장소에서 금지다 — 생성 기준일 오용으로 직전 사업에서 ML
    수치가 흔들렸다(§10-3 · G-07 `check_data.scan_clock`). 이 값은 생성 기준일이 아니라
    "이 측정을 언제 돌렸나" 지만, 실시각을 읽는 자리는 정본이 하나로 정해 뒀으니 그것을 쓴다.
    DB 를 못 읽으면 **파이썬 시계로 조용히 대체하지 않고** 그 사실을 적는다.
    """
    try:
        from kyungdong.app.util import clock          # noqa: E402  (DB 가 있을 때만)
        return clock.real_now().isoformat(timespec="seconds")
    except Exception as e:                            # DB 없이도 도구는 돌아야 한다
        return (f"미기록 — DB 시계를 못 읽었다({type(e).__name__}). "
                "파이썬 시계로 대체하지 않는다 (§10-3)")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# ── 대상 수집 · 중복 제거 ────────────────────────────────────────────────────
def collect(root: Path | None, exts: tuple[str, ...]) -> list[archive.ArchiveFile]:
    res = archive.scan(root)
    return [f for f in res.files if f.ext in exts and f.size > 0]


def load_hash_cache() -> dict[str, str]:
    if HASH_CACHE.is_file():
        try:
            return json.loads(HASH_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def dedupe(files: list[archive.ArchiveFile], *, say=print) -> tuple[list[dict], int]:
    """내용 sha256 으로 묶는다. **파일 수와 서로 다른 도면 수를 둘 다 돌려준다** (D-115)."""
    cache = load_hash_cache()
    groups: dict[str, dict] = {}
    t0 = time.time()
    for i, f in enumerate(files, 1):
        key = f"{f.rel}|{f.size}|{f.mtime.isoformat()}"
        digest = cache.get(key)
        if digest is None:
            try:
                digest = sha256(Path(f.path))
            except OSError as e:                       # 조용히 건너뛰지 않는다
                digest = f"읽기실패:{type(e).__name__}"
            cache[key] = digest
        g = groups.setdefault(digest, {"sha256": digest, "rel": f.rel, "path": f.path,
                                       "name": f.name, "ext": f.ext, "size": f.size,
                                       "copies": 0, "copy_rels": []})
        g["copies"] += 1
        if len(g["copy_rels"]) < 5:
            g["copy_rels"].append(f.rel)
        if i % 500 == 0 or i == len(files):
            say(f"    해시 {i}/{len(files)} · 서로 다른 내용 {len(groups)} "
                f"({time.time() - t0:.0f}s)")
    HASH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    HASH_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    out = sorted(groups.values(), key=lambda g: g["rel"])
    return out, len(files)


# ── 한 건 처리: 변환 → 파싱 → 적립 → 삭제 ────────────────────────────────────
def measure_to_record(m: dxf.DxfMeasure) -> dict:
    """`DxfMeasure` 를 저장 가능한 작은 dict 로. **못 잰 값은 넣지 않는다**(0 으로 안 채운다)."""
    feats = {}
    for f in m.features():
        feats[f["type"]] = {"value": f["value"], "uom": f["uom"],
                            "text": f["text"], "source": f["source"]}
    return {
        "entities": dict(sorted(m.entities.items(), key=lambda kv: -kv[1])[:12]),
        "entity_total": sum(m.entities.values()),
        "holes": m.holes if "CIRCLE" in m.entities else None,
        "cut_len": round(m.cut_len, 3) if m.cut_len > 0 else None,
        "area": round(m.closed_area, 3) if m.closed_polys else None,
        "thickness": m.thickness,
        "material": m.material,
        "uom": m.uom,
        "inserts": m.inserts,
        "blocks": m.blocks,
        "features": feats,
    }


def process_one(g: dict, *, timeout: int, keep: bool = False) -> dict:
    src = Path(g["path"])
    rec = {"sha256": g["sha256"], "rel": g["rel"], "name": g["name"], "ext": g["ext"],
           "size": g["size"], "copies": g["copies"], "copy_rels": g["copy_rels"]}
    if not src.is_file():
        return {**rec, "stage": "원본없음", "converted": False, "parsed": False,
                "reason": "원본 파일이 사라졌다"}

    if g["ext"] in DIRECT_EXTS:
        # 이미 DXF 다 — 변환하지 않는다. '변환 성공' 으로 세지도 않는다.
        rec["signature"] = None
        rec["converted"] = None            # None = 변환 불필요
        m = dxf.parse(src)
        rec["parsed"] = m.error is None
        if m.error:
            return {**rec, "stage": "파싱실패", "reason": m.error}
        return {**rec, "stage": "완료", **measure_to_record(m)}

    rec["signature"] = dwgconv.signature(src)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"{g['sha256'][:16]}.dxf"
    # **변환 성공 = 0바이트가 아닌 DXF 가 나왔다** (`dwgconv.to_dxf` 의 정의). rc 가 0이 아니어도
    # 산출물이 있으면 `rc_nonzero` 로 따로 남긴다 — 성공/실패를 종료코드 하나로 뭉개지 않는다.
    got = dwgconv.to_dxf(src, out, timeout=timeout)
    rec["secs"], rec["rc"] = got.secs, got.rc
    if not got.ok:
        return {**rec, "stage": "변환실패", "converted": False, "parsed": False,
                "reason": got.reason}
    rec["converted"] = True
    rec["dxf_size"] = got.out_size
    rec["rc_nonzero"] = got.rc_nonzero
    if got.rc_nonzero:
        rec["convert_warn"] = got.reason

    try:
        m = dxf.parse(out)
        rec["parsed"] = m.error is None
        if m.error:
            rec.update({"stage": "파싱실패", "reason": m.error})
        else:
            rec.update({"stage": "완료", **measure_to_record(m)})
    finally:
        if not keep and out.exists():
            out.unlink()               # **여기서 지운다** — 전량 보관하면 8.5GB 다
    return rec


# ── 집계 ────────────────────────────────────────────────────────────────────
FEATURE_KEYS = (dxf.F_CUTLEN, dxf.F_HOLES, dxf.F_THICK, dxf.F_MATERIAL, dxf.F_AREA)


def summarize(records: list[dict], *, files_total: int, distinct_total: int) -> dict:
    conv_target = [r for r in records if r["ext"] in CONVERT_EXTS]
    direct = [r for r in records if r["ext"] in DIRECT_EXTS]
    converted = [r for r in conv_target if r.get("converted")]
    conv_failed = [r for r in conv_target if not r.get("converted")]
    parsed = [r for r in records if r.get("parsed")]
    parse_target = converted + direct
    feat_counts = {k: sum(1 for r in parsed if k in (r.get("features") or {}))
                   for k in FEATURE_KEYS}

    reasons = Counter(r.get("reason", "?") for r in conv_failed)
    by_sig_all = Counter(r.get("signature") or "(DXF — 변환 불필요)" for r in conv_target)
    by_sig_fail = Counter(r.get("signature") or "?" for r in conv_failed)
    sig_rate = {}
    for sig, n in by_sig_all.most_common():
        f = by_sig_fail.get(sig, 0)
        sig_rate[sig] = {"대상": n, "변환성공": n - f, "변환실패": f,
                         "성공률": round((n - f) / n * 100, 1) if n else None}

    def pct(a: int, b: int) -> float | None:
        return round(a / b * 100, 1) if b else None

    return {
        "① 대상": {
            "파일 수": files_total,
            "서로 다른 도면 수(sha256)": distinct_total,
            "처리한 도면 수": len(records),
            "중복 파일 수": files_total - distinct_total,
            "주석": "**파일 수 ≠ 도면 수다** — 복사본은 같은 도면이다 (D-115)",
        },
        "② 변환": {
            "변환 대상(dwg·cad 서로 다른 도면)": len(conv_target),
            "변환 성공": len(converted),
            "변환 실패": len(conv_failed),
            "성공률(%)": pct(len(converted), len(conv_target)),
            "rc≠0 이지만 DXF 는 나온 건": sum(1 for r in converted if r.get("rc_nonzero")),
            "변환 불필요(이미 DXF)": len(direct),
            "실패 사유 상위": reasons.most_common(12),
            "DWG 버전 서명별 성공률": sig_rate,
        },
        "③ 파싱": {
            "파싱 대상(변환 성공 + 원본 DXF)": len(parse_target),
            "파싱 성공": len(parsed),
            "파싱 실패": len(parse_target) - len(parsed),
            "성공률(%)": pct(len(parsed), len(parse_target)),
            "파싱 실패 사유": Counter(r.get("reason", "?") for r in parse_target
                                 if not r.get("parsed")).most_common(8),
        },
        "④ Feature": {
            k: {"건수": v,
                "파싱성공 대비(%)": pct(v, len(parsed)),
                "서로 다른 도면 대비(%)": pct(v, distinct_total)}
            for k, v in feat_counts.items()
        },
        "④-주": ("재질은 값이 읽혀도 `EST_CAD_FEATURES.FEATURE_VALUE` 가 NUMERIC(16,4) 이라 "
                "적재할 자리가 없다 — `SOURCE_DESC` 에 증거로만 남긴다 (D-122). "
                "용접장은 0건이다 — 용접 레이어 표준이 도면에 없다 (D-05)"),
        "실측 합계": {
            "홀 수량 합": sum(r.get("holes") or 0 for r in parsed),
            "총 절단장 합": round(sum(r.get("cut_len") or 0 for r in parsed), 1),
            "판재 면적 합": round(sum(r.get("area") or 0 for r in parsed), 1),
            "재질 분포": Counter(r["material"] for r in parsed if r.get("material")).most_common(15),
            "두께 분포": Counter(str(r["thickness"]) for r in parsed
                              if r.get("thickness") is not None).most_common(15),
            "단위 분포": Counter(r.get("uom") for r in parsed).most_common(),
        },
        "DB 적재 판정": {
            "EST_CAD_DRAWINGS": ("**스키마상 가능하다** — `PROJECT_ID` 는 NULL 허용이라 "
                                 "`EST_PROJECTS` 가 0행(D-120)이어도 도면만 적재할 수 있다. "
                                 "실측: `--load-db` 로 781행 적재됨"),
            "EST_CAD_FEATURES": "차단",
            "차단 사유": ("**실측했다.** Feature 3,226행을 넣으면 `tools/check_ingest.py` ⑤ 가 "
                       "결함 2건을 내고 **G-13 이 PASS→FAIL** 이 된다 — ① 확정(CONFIRM_YN='Y') "
                       "객체 0건인데 Feature N행이면 합성 ② `BLOCKED_FEATURES` 키가 적재돼 있으면 "
                       "지어낸 값. **그 규칙이 맞다** — 확정은 `review_object()` 의 사람 승인으로만 "
                       "생기고(G-24) 승인을 지어낼 수 없다. 우회하지 않는다"),
            "그래서": ("실측값은 이 JSON 이 정본이다. 적재는 ① HITL 승인 경로로 확정 객체가 생기거나 "
                     "② QA 가 검사기에 'DXF 실측' 원천을 인정하도록 규칙을 넓힐 때 풀린다"),
            "재질": ("`FEATURE_VALUE NUMERIC(16,4)` 에 담을 칸이 없어 적재 시에도 값은 NULL 이고 "
                    "관측값은 `SOURCE_DESC` 에 증거로 남긴다. 컬럼은 추가하지 않았다 "
                    "(D-122 · G-02 762 고정)"),
        },
        "G-14": {
            "판정": "차단",
            "근거": ("표본이 늘어난 것과 정답 라벨이 생긴 것은 **다른 일**이다. "
                    "G-14 는 IoU 0.5 기준 Precision·Recall·F1 이고 그 분모는 **정답 박스**다. "
                    "`work/cad_labelset.json` 의 labels·predictions 가 여전히 0건이라 "
                    "도면이 2,000건이어도 TP/FP/FN 을 못 만든다. "
                    "여기서 뽑은 것은 **기하 집계**(홀 수량·절단장)이지 탐지 정확도가 아니다"),
        },
    }


# ── DB 적재 ─────────────────────────────────────────────────────────────────
def load_db(records: list[dict], *, limit: int | None = None, say=print) -> dict:
    """`EST_CAD_DRAWINGS` + `EST_CAD_FEATURES` 적재. **기본으로는 부르지 않는다.**

    두 가지를 먼저 재고 그대로 적는다 —
      ① `EST_PROJECTS` 는 0행이다(D-120). 그런데 `EST_CAD_DRAWINGS.PROJECT_ID` 는 **NULL 허용**이라
         프로젝트 없이 도면만 적재하는 것은 **스키마상 가능하다**.
      ② `tools/check_ingest.py` ⑤ 는 "확정(CONFIRM_YN='Y') 객체 0건 + `EST_CAD_FEATURES` N행
         = 합성 Feature" 로 판정하고, 나아가 **`BLOCKED_FEATURES` 키가 적재돼 있으면 결함**으로 센다.
         그 규칙은 **맞다** — 객체 집계를 유일한 원천으로 보는 한 맞고, 우회하지 않는다.
         확정 객체는 `review_object()` 의 사람 승인으로만 생긴다(G-24). 승인을 지어낼 수 없다.
      → 그래서 이 함수는 **부딪히는 지점을 먼저 계산해 돌려주고**, `--load-db` 를 준 경우에만
        도면을 적재한다. Feature 적재는 `--load-features` 를 **추가로** 줘야 한다.
    """
    import conn                                       # noqa: E402  (DB 가 있을 때만)

    parsed = [r for r in records if r.get("parsed")]
    if limit is not None:
        parsed = parsed[:limit]
    drawings = features = mat_rows = 0
    for r in parsed:
        hit = conn.q1("select DRAWING_ID from EST_CAD_DRAWINGS where FILE_PATH = %s", (r["rel"],))
        if hit:
            did = int(hit["drawing_id"])
        else:
            row = conn.q1(
                "insert into EST_CAD_DRAWINGS "
                "(DRAWING_NO, FILE_TYPE, FILE_PATH, FILE_SIZE, ANALYSIS_STATUS, "
                " DUPLICATE_YN, CREATED_DT) values (%s,%s,%s,%s,'완료',%s, now()) "
                "returning DRAWING_ID",
                (Path(r["name"]).stem[:100], r["ext"].upper(), r["rel"], r["size"],
                 "Y" if r["copies"] > 1 else "N"),
            )
            did = int(row["drawing_id"])
            drawings += 1
        r["drawing_id"] = did
    say(f"    EST_CAD_DRAWINGS 신규 {drawings}행 (PROJECT_ID 는 NULL — EST_PROJECTS 0행, D-120)")
    return {"drawings_inserted": drawings, "features_inserted": features,
            "material_rows": mat_rows, "parsed_used": len(parsed)}


def load_features(records: list[dict], *, say=print) -> dict:
    """실측 Feature 를 `EST_CAD_FEATURES` 에 적재한다. **`SOURCE_DESC` 로 합성과 구분한다.**

    `재질` 은 `FEATURE_VALUE` 를 NULL 로 두고 관측값을 `SOURCE_DESC` 에 증거로 적는다(D-122).
    컬럼은 추가하지 않는다(G-02 762 고정).
    """
    import conn                                       # noqa: E402

    say("    ⚠ **실측으로 확인했다 — 이 적재는 `G-13` 을 PASS→FAIL 로 만든다.** "
        "`check_ingest` ⑤ 가 결함 2건을 낸다: ① 확정 객체 0건인데 Feature 3,226행 = 합성 판정 "
        "② 차단 Feature(두께·판재 면적·재질·총 절단장)가 적재돼 있다. "
        "**그 규칙은 맞다** — 확정(CONFIRM_YN='Y')은 `review_object()` 의 사람 승인으로만 생기고"
        "(G-24), 승인을 지어낼 수는 없다. 기본 산출물은 `docs/cad/dwg_features.json` 이다")
    created = updated = mat = 0
    for r in records:
        did = r.get("drawing_id")
        if did is None or not r.get("parsed"):
            continue
        for ftype, f in (r.get("features") or {}).items():
            src = f"DXF 실측(dwg2dxf 변환) — {r['name']}"[:300] if r["ext"] != "dxf" \
                else f"DXF 실측 — {r['name']}"[:300]
            if f["value"] is None:                     # 재질
                src = (f"DXF 실측(dwg2dxf 변환) — {r['name']} · 관측 재질={f['text']} "
                       "· FEATURE_VALUE 는 NUMERIC 이라 NULL (D-122)")[:300]
                mat += 1
            hit = conn.q1("select FEATURE_ID from EST_CAD_FEATURES "
                          "where DRAWING_ID = %s and FEATURE_TYPE = %s", (did, ftype))
            if hit:
                conn.x("update EST_CAD_FEATURES set FEATURE_VALUE = %s, UOM = %s, "
                       "SOURCE_DESC = %s, UPDATED_DT = now() where FEATURE_ID = %s",
                       (f["value"], (f["uom"] or "")[:20] or None, src, hit["feature_id"]))
                updated += 1
                continue
            conn.x("insert into EST_CAD_FEATURES "
                   "(DRAWING_ID, FEATURE_TYPE, FEATURE_VALUE, UOM, SOURCE_DESC, "
                   " USED_IN_QUOTE_YN, TRAIN_USE_YN, CREATED_DT) "
                   "values (%s,%s,%s,%s,%s,'N','N', now())",
                   (did, ftype, f["value"], (f["uom"] or "")[:20] or None, src))
            created += 1
    say(f"    EST_CAD_FEATURES 신규 {created} · 갱신 {updated} (재질 {mat}행은 VALUE NULL)")
    return {"created": created, "updated": updated, "material_null_rows": mat}


# ── 실행 ────────────────────────────────────────────────────────────────────
def read_ledger() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if not LEDGER.is_file():
        return done
    for line in LEDGER.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                                   # 중단으로 잘린 마지막 줄
        done[r["sha256"]] = r
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="서로 다른 도면 N건만 (소규모 확인용)")
    ap.add_argument("--root", help=f"아카이브 루트 (기본 {archive.ENV_KEY} 또는 D-109 실측 경로)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="변환 1건 제한 시간(초)")
    ap.add_argument("--restart", action="store_true", help="재개 원장을 버리고 처음부터")
    ap.add_argument("--keep-dxf", action="store_true",
                    help="중간 DXF 를 지우지 않는다 (디버깅용 — 전량에는 쓰지 마라, 8.5GB)")
    ap.add_argument("--load-db", action="store_true", help="EST_CAD_DRAWINGS 적재")
    ap.add_argument("--load-features", action="store_true",
                    help="EST_CAD_FEATURES 적재 (--load-db 와 함께. check_ingest ⑤ 와 충돌한다)")
    ap.add_argument("--every", type=int, default=25, help="진행률 출력 간격")
    a = ap.parse_args(argv)

    say = print
    if not dwgconv.available():
        say(f"✗ {dwgconv.NOT_INSTALLED}")
        return 2
    ver = dwgconv.version() or CONVERTER
    root = Path(a.root) if a.root else None
    if not archive.available(root):
        say(f"✗ 원본 아카이브가 없다: {archive.archive_root(root)} (D-109)")
        return 2

    say(f"■ DWG·CAD 전량 변환 + Feature 실측 (D-123)  변환기: {ver or CONVERTER}")
    say(f"  원본(읽기 전용): {archive.archive_root(root)}")
    say("  ① 대상 수집 — 원본 아카이브 전체 스캔")
    files = collect(root, CONVERT_EXTS + DIRECT_EXTS)
    by_ext = Counter(f.ext for f in files)
    say(f"    CAD 파일 {len(files)}건 {dict(by_ext)} (0바이트 제외)")
    say("  ② 내용 sha256 으로 중복 제거 — **파일 수를 표본 수로 쓰지 않는다** (D-115)")
    groups, files_total = dedupe(files, say=say)
    distinct_total = len(groups)
    say(f"    파일 {files_total} → **서로 다른 도면 {distinct_total}** "
        f"(중복 {files_total - distinct_total}) {dict(Counter(g['ext'] for g in groups))}")

    if a.restart and LEDGER.exists():
        LEDGER.unlink()
        say("    재개 원장을 버렸다 (--restart)")
    done = read_ledger()
    todo = [g for g in groups if g["sha256"] not in done]
    if a.limit is not None:
        todo = todo[:a.limit]
    say(f"  ③ 변환 → 파싱 → 적립 → **즉시 삭제** (최대 디스크 사용 = 한 파일)")
    say(f"    이미 처리 {len(done)} · 이번에 처리 {len(todo)}")

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with LEDGER.open("a", encoding="utf-8") as fh:
        for i, g in enumerate(todo, 1):
            rec = process_one(g, timeout=a.timeout, keep=a.keep_dxf)
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            done[rec["sha256"]] = rec
            if i % a.every == 0 or i == len(todo):
                el = time.time() - t0
                rate = i / el if el else 0
                eta = (len(todo) - i) / rate if rate else 0
                ok = sum(1 for r in done.values() if r.get("parsed"))
                say(f"    {i}/{len(todo)} · 파싱성공 누적 {ok} · {rate:.2f}건/s · "
                    f"경과 {el/60:.1f}분 · 남은 예상 {eta/60:.1f}분")

    # 전량 집계는 **처리한 도면 전체**(이번 회차 + 이전 회차) 기준이다.
    records = [done[g["sha256"]] for g in groups if g["sha256"] in done]
    summary = summarize(records, files_total=files_total, distinct_total=distinct_total)

    if a.load_db:
        say("  ④ DB 적재")
        summary["DB 적재"] = load_db(records, say=say)
        if a.load_features:
            summary["DB 적재"].update(load_features(records, say=say))
        else:
            summary["DB 적재"]["features"] = (
                "적재하지 않았다 — `--load-features` 를 명시로 줘야 한다. "
                "`check_ingest` ⑤ 가 '확정 객체 0 + Feature N행 = 합성' 으로 판정하고 "
                "`BLOCKED_FEATURES` 키가 적재돼 있으면 결함으로 센다. 그 규칙은 맞다 — 우회하지 않는다")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"_meta": {"측정시각": measured_at(),
                   "변환기": ver or CONVERTER,
                   "원본": str(archive.archive_root(root)),
                   "근거": "D-123 (D-05 정정) · 파서 cad/dxf.py (D-110-b · D-121)",
                   "원본을 고치지 않았다": True},
         "요약": summary,
         "도면별": records}, ensure_ascii=False, indent=2, default=str))
    say("")
    say(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    say(f"\n  → {OUT_JSON.relative_to(ROOT)} ({OUT_JSON.stat().st_size/1e6:.1f}MB) · "
        f"재개 원장 {LEDGER.relative_to(ROOT)}")
    # 중간 DXF 가 남아 있으면 지운다 — 여기서 디스크를 비워두는 것이 이 도구의 약속이다
    if not a.keep_dxf and TMP_DIR.is_dir():
        left = list(TMP_DIR.glob("*.dxf"))
        for p in left:
            p.unlink()
        if left:
            say(f"  중간 DXF {len(left)}건 삭제")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
