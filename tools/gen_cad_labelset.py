#!/usr/bin/env python
"""G-14 정답 라벨셋 생성기 — **가정 답변 ④ (D-150) 에서만** 파생한다.

⚠ **이 라벨은 도입기업이 준 정답이 아니다. 순환이다.**
   우리 DXF 기하 파싱에서 라벨과 예측을 **둘 다** 뽑았다. 그러면 우리 탐지를 우리가 만든
   정답과 비교하는 것이고, 거기서 나온 P/R/F1 은 **측정이 아니라 우리가 고른 값**이다.
   목적은 오직 하나다 — **채점 코드가 실제로 TP/FP/FN 을 세는지** 시험하는 것(④ 가정_방식).

**어긋나게 만드는 방식 (무작위 금지 · 재실행하면 같은 자리)**
  도면을 `DRAWING_ID` 순으로 돌고, 각 도면의 CIRCLE 을 DXF 읽은 순서대로 돌면서
  **전체에 걸친 0부터의 통번호 `i`** 를 붙인다. 그 통번호로만 주입 자리를 정한다.
    · `i % 10 == FP_SLOT` → **라벨에서 뺀다** → 그 예측은 짝이 없어 **FP** 가 된다 (오검출 주입)
    · `i % 10 == FN_SLOT` → **예측에서 뺀다** → 그 라벨은 짝이 없어 **FN** 이 된다 (누락 주입)
  주입 비율은 각각 10% 고정이고, 뺀 자리(통번호·도면·박스)를 `_meta.주입` 에 전부 적는다.

**예측도 실제 탐지기의 출력이 아니다.** `cad.provider` 는 501 미구성(D-05)이라 예측이 0건이다.
여기 `predictions` 는 DXF 기하 파싱(D-110-b·D-123)에서 FN 주입분을 뺀 것이다 — 그 사실을
`_meta` 에 적는다. 점수(`score`)는 기하 파싱이라 확신도가 없어 1.0 자리채움이다.

**어휘는 TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 5종**(홀·슬롯·노즐·플랜지·치수문자)을 썼다.
`docs/cad/라벨링 가이드.docx` 의 3종(title_block·bom_table·rev_table)과 다르다(D-98) —
가이드 어휘를 쓰면 TD5 에 담을 자리가 없다. 그리고 5종 중 실제로 라벨이 생기는 것은
**홀뿐**이다: 우리 파서는 CIRCLE 을 셀 뿐 슬롯·노즐·플랜지·치수문자를 가릴 기준이 없다(D-05).
**빈 4종을 박스로 채우지 않는다.**
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "db"))

import conn                                          # noqa: E402
from kyungdong.app.util import assumed               # noqa: E402
from kyungdong.cad import dwgconv                    # noqa: E402
from kyungdong.cad import dxf                        # noqa: E402
from kyungdong.cad import archive                    # noqa: E402

LABELSET = ROOT / "work" / "cad_labelset.json"

DRAWINGS = 30                # ④ 가정 답변이 말한 라벨 도면 수
FP_SLOT = 3                  # 통번호 % 10 == 3 → 라벨에서 뺀다 (오검출 주입 10%)
FN_SLOT = 7                  # 통번호 % 10 == 7 → 예측에서 뺀다 (누락 주입 10%)
MODULO = 10

# TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 어휘. **이 밖의 이름을 라벨로 쓰지 않는다.**
TD5_VOCAB = ("홀", "슬롯", "노즐", "플랜지", "치수문자")
CLS_HOLE = "홀"
# 라벨링 가이드(D-98)의 클래스 — **쓰지 않았다**. 어느 쪽을 썼는지 남기려고 적어 둔다.
GUIDE_VOCAB = ("title_block", "bom_table", "rev_table")


def measure(file_type: str, file_path: str):
    """도면 하나를 읽는다. `.dwg` 는 dwg2dxf 변환 후 같은 파서로 읽는다(D-123)."""
    p = Path(file_path)
    if not p.is_file():
        p = archive.archive_root() / file_path
    if not p.is_file():
        return None, f"원본 파일이 없다: {file_path}"
    ft = (file_type or "").upper()
    if ft == "DXF":
        return dxf.parse(p), None
    if ft != "DWG":
        return None, f"{ft} 는 dwg2dxf 의 대상이 아니다 (DWG 서명 아님 — D-123)"
    if not dwgconv.available():
        return None, dwgconv.NOT_INSTALLED
    m, conv = dwgconv.measured(p)
    return (m, None) if m is not None else (None, f"변환 실패: {conv.reason}")


def collect(limit: int) -> tuple[list[dict], list[str]]:
    """앞에서부터 CIRCLE 이 있는 도면 `limit` 건. **읽히지 않은 것은 적고 넘어간다.**"""
    rows = conn.q("select DRAWING_ID, DRAWING_NO, FILE_TYPE, FILE_PATH from EST_CAD_DRAWINGS "
                  "where upper(FILE_TYPE) in ('DXF','DWG') order by DRAWING_ID")
    picked: list[dict] = []
    skipped: list[str] = []
    for r in rows:
        if len(picked) >= limit:
            break
        m, why = measure(r["file_type"], r["file_path"])
        if m is None or m.error:
            skipped.append(f"#{r['drawing_id']} {r['drawing_no']} — {why or m.error}")
            continue
        if not m.circles:
            skipped.append(f"#{r['drawing_id']} {r['drawing_no']} — CIRCLE 좌표 0개 "
                           f"(엔티티 {sum(m.entities.values())}개 · 홀 {m.holes})")
            continue
        picked.append({"drawing_id": int(r["drawing_id"]), "drawing_no": r["drawing_no"],
                       "file_type": (r["file_type"] or "").upper(), "uom": m.uom,
                       "circles": m.circles})
    return picked, skipped


def build(picked: list[dict]) -> dict:
    labels: list[dict] = []
    preds: list[dict] = []
    fp_at: list[dict] = []
    fn_at: list[dict] = []
    i = 0
    for d in picked:
        for cx, cy, r in d["circles"]:
            box = [round(cx - r, 4), round(cy - r, 4), round(cx + r, 4), round(cy + r, 4)]
            where = {"n": i, "image": d["drawing_no"], "box": box}
            if i % MODULO != FP_SLOT:
                labels.append({"cls": CLS_HOLE, "box": box, "image": d["drawing_no"]})
            else:
                fp_at.append(where)
            if i % MODULO != FN_SLOT:
                preds.append({"cls": CLS_HOLE, "box": box, "image": d["drawing_no"],
                              "score": 1.0})
            else:
                fn_at.append(where)
            i += 1
    return {"labels": labels, "predictions": preds, "fp_at": fp_at, "fn_at": fn_at, "total": i}


def main() -> int:
    ap = argparse.ArgumentParser(description="G-14 정답 라벨셋 생성 (가정 답변 ④ · D-150)")
    ap.add_argument("--drawings", type=int, default=DRAWINGS)
    ap.add_argument("--dry-run", action="store_true", help="파일에 쓰지 않고 규모만 본다")
    a = ap.parse_args()

    decl = assumed.declaration()
    if decl is None:
        print("가정 선언이 없다 — 라벨을 만들지 않는다.", file=sys.stderr)
        print(f"  {assumed.mismatch()}", file=sys.stderr)
        print("  선언 없이 만든 라벨은 가정이 아니라 조작이다. `make db-seed` 를 먼저 돌린다.",
              file=sys.stderr)
        return 1

    picked, skipped = collect(a.drawings)
    built = build(picked)
    old = json.loads(LABELSET.read_text(encoding="utf-8"))

    answers = (assumed.answers() or {}).get(assumed.K_LABEL) or {}
    meta = {
        "owner": "QA3 / 개발3",
        "purpose": old["_meta"]["purpose"],
        "판정": f"판정 불가 — {assumed.circular_note()}",
        "성격": answers.get("⚠_치명적_한계"),
        "가정_방식": answers.get("가정_방식"),
        "결정번호": decl,
        "출처": assumed.path_text(),
        "선언": f"SYS_CONFIGS('{assumed.CONFIG_TYPE}','{assumed.CONFIG_KEY}') = {decl}",
        "고지": assumed.circular_note(),
        "⚠_정확도_증거_아님": (
            "라벨과 예측을 **같은 DXF 기하 파싱**에서 뽑았다 — 우리 탐지를 우리가 만든 정답과 "
            "비교하는 순환이다. 이 파일에서 나온 P/R/F1 은 채점 파이프라인이 돈다는 증거일 뿐이고 "
            "**AI 정확도의 증거가 아니다.** 숫자만 떼어 인용하면 거짓 증거가 된다"),
        "예측의_정체": (
            "`cad.provider` 는 Parsing·Vision 둘 다 501 미구성(D-05)이라 **실제 탐지기 출력은 "
            "0건**이다. 여기 predictions 는 DXF 기하 파싱(D-110-b · D-123)에서 FN 주입분을 뺀 "
            "것이다. score 1.0 은 확신도가 아니라 자리채움 — 기하 파싱은 점수를 내지 않는다"),
        "어휘": {
            "쓴 것": f"TD5 EST_CAD_OBJECTS.OBJECT_TYPE {list(TD5_VOCAB)}",
            "안 쓴 것": f"docs/cad/라벨링 가이드.docx {list(GUIDE_VOCAB)} — TD5 와 다르다 (D-98)",
            "실제로 라벨이 생긴 것": [CLS_HOLE],
            "0건인 것": [v for v in TD5_VOCAB if v != CLS_HOLE],
            "0건인 이유": ("우리 파서는 CIRCLE 을 셀 뿐 슬롯·노즐·플랜지·치수문자를 가릴 기준이 "
                         "없다(D-05). **빈 4종을 박스로 채우지 않는다** — 채우면 그게 합성이다"),
            "홀의 뜻": ("CIRCLE 전량이다. 지름 필터 기준이 도입기업 자료에 없어 걸지 않았다 — "
                      "계기 버블·중심선도 '홀' 로 세어진다 (D-110-b)"),
        },
        "박스": ("[x1,y1,x2,y2] = CIRCLE 외접 정사각형(중심±반지름). 좌표는 **도면 좌표 그대로**이고 "
                "평행이동·정규화를 하지 않았다. `image` 로 도면을 구분하므로 다른 도면의 박스가 "
                "우연히 매칭되지 않는다 — 채점은 도면별로 하고 합산한다"),
        "표본": {
            "도면": len(picked), "요청": a.drawings,
            "박스(파싱 전량)": built["total"],
            "labels": len(built["labels"]), "predictions": len(built["predictions"]),
            "읽지 못한 도면": len(skipped),
            "단위 분포": {u: sum(1 for d in picked if d["uom"] == u)
                       for u in sorted({d["uom"] for d in picked})},
            "파일형식": {t: sum(1 for d in picked if d["file_type"] == t)
                      for t in sorted({d["file_type"] for d in picked})},
        },
        "주입": {
            "방식": (f"통번호 i (도면 DRAWING_ID 순 · 도면 안은 DXF 읽은 순서) 로만 정한다. "
                   f"**무작위 없음 — 재실행하면 같은 자리다**"),
            "FP(오검출) 비율": f"i % {MODULO} == {FP_SLOT} → 라벨에서 뺀다 = {100 // MODULO}%",
            "FN(누락) 비율": f"i % {MODULO} == {FN_SLOT} → 예측에서 뺀다 = {100 // MODULO}%",
            "FP 자리": built["fp_at"],
            "FN 자리": built["fn_at"],
            "⚠_IoU_임계에_둔감하다": (
                "짝이 남은 라벨·예측은 **같은 박스**라 IoU = 1.0 이다. 그래서 이 라벨셋으로는 "
                "임계값을 0.2↔0.9 로 바꿔도 혼동행렬이 움직이지 않는다 — 임계 민감도는 "
                "`evaluator_selftest`(부분 겹침 박스)만이 증명한다. 박스를 흔들어 IoU 를 "
                "만들어내지 않았다: 그건 좌표를 지어내는 것이다"),
            "기대 혼동행렬(IoU 무관 · 박스가 동일좌표라 IoU=1.0)": {
                "TP": built["total"] - len(built["fp_at"]) - len(built["fn_at"]),
                "FP": len(built["fp_at"]), "FN": len(built["fn_at"]),
            },
        },
        "읽지_못한_도면": skipped,
        "도입기업에_필요한_것": old["_meta"]["도입기업에_필요한_것"],
        "정본_불일치_관찰": old["_meta"]["정본_불일치_관찰"],
        "지어내지_않은_것": ("슬롯·노즐·플랜지·치수문자 박스 · 도입기업 확인 · 실제 탐지기 출력. "
                        "라벨 좌표는 전부 DXF CIRCLE 실측이다"),
    }
    out = {"_meta": meta, "labels": built["labels"], "predictions": built["predictions"],
           "evaluator_selftest": old["evaluator_selftest"]}

    print(f"도면 {len(picked)}/{a.drawings} 건 · 박스 {built['total']} 개 "
          f"→ labels {len(built['labels'])} · predictions {len(built['predictions'])}")
    print(f"FP 주입 {len(built['fp_at'])} 자리 (i%{MODULO}=={FP_SLOT}) · "
          f"FN 주입 {len(built['fn_at'])} 자리 (i%{MODULO}=={FN_SLOT})")
    print(f"기대 TP {meta['주입']['기대 혼동행렬(IoU 무관 · 박스가 동일좌표라 IoU=1.0)']['TP']} "
          f"· 고지 {assumed.circular_note()}")
    for s in skipped[:10]:
        print(f"  건너뜀 {s}")
    if len(skipped) > 10:
        print(f"  … 그리고 {len(skipped) - 10} 건 더")
    if a.dry_run:
        print("dry-run — 파일에 쓰지 않았다")
        return 0
    LABELSET.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{LABELSET.relative_to(ROOT)} 갱신")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
