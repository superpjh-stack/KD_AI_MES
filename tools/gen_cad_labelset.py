#!/usr/bin/env python
"""G-14 정답 라벨셋 — **도입기업이 어휘를 3종으로 확정한 뒤(D-160) 이 생성기는 라벨을 만들지 않는다.**

전에는 가정 답변 ④(D-150)에서 **홀** 라벨 3,391건을 파생해 만들었다. 답이 오면서 그 라벨은
**두 가지 이유로 각각 단독으로** 못 쓰게 됐다.

  ① **어휘가 범위 밖이다.** 답은 `title_block`·`bom_table`·`rev_table` **3종**이다.
     홀·슬롯·노즐·플랜지·치수문자는 이번 사업이 아니다(라벨링 가이드 '2차 고도화 별도 프로젝트').
  ② **순환이었다.** 라벨과 예측을 같은 DXF 기하 파싱에서 뽑았으니 우리 탐지를 우리가 만든
     정답과 비교한 것이고, 거기서 나온 P/R/F1 0.9009 는 측정이 아니라 우리가 고른 값이다.

그래서 이 도구는 이제 **회수기**다. 어휘에 홀이 없으면 `labels`·`predictions` 를 **0건으로
비우고** 회수 사유를 `_meta` 에 적는다. `evaluator_selftest` 는 남긴다 — 그것은 게이트 입력이
아니라 **채점기가 임계값을 읽는지** 보는 자기검증이고, 라벨과 무관하게 계속 돌아야 한다.

**3종 라벨을 우리가 만들지 않는다.** 우리 파서는 재질·두께 **문자열을 찾을 뿐 표제란·BOM표·
리비전표의 경계상자를 가리지 못한다**(`cad/dxf.py _title_block` 은 영역이 아니라 텍스트를 본다).
없는 탐지 결과로 정답을 만들면 그게 다시 순환이다. **G-14 는 도면 30~50건의 사람 라벨이
올 때까지 차단이 정답이다.**
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

# TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 비고가 예로 든 어휘. 비고는 `… 등` 으로 끝나는
# **열린 목록**이고 컬럼은 VARCHAR(50) 이라 3종도 담긴다 — `TD5 에 담을 자리가 없다` 던
# D-98 의 내 판단이 틀렸다(D-160).
TD5_VOCAB = ("홀", "슬롯", "노즐", "플랜지", "치수문자")
CLS_HOLE = "홀"
# 도입기업이 확정한 어휘(D-160 ④). **코드에 박아 두지 않는다** — `assumed.label_vocab()` 이
# 선언 파일에서 꺼낸다. 여기 이름은 선언을 못 읽었을 때 무엇이 빠졌는지 적기 위한 것뿐이다.
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


def withdraw(old: dict, decl: str, vocab: tuple[str, ...], dry: bool) -> int:
    """**회수한다** — 라벨·예측을 0건으로 비우고 왜 비웠는지 남긴다.

    지우고 끝내지 않는 이유: 다음 사람이 `labels: []` 만 보면 **아직 안 만든 것**으로 읽고
    다시 만들려 한다. 회수 사유를 파일 안에 적어 두면 그러지 않는다.

    `evaluator_selftest` 는 **건드리지 않는다.** 채점기가 임계값을 실제로 읽는지 보는
    자기검증이고 게이트 입력이 아니다 — 라벨이 0건이어도 계속 돌아야 한다(§10-16).
    """
    meta = {
        "owner": "QA3 / 개발3",
        "purpose": old["_meta"]["purpose"],
        "판정": "차단 — 3종 어휘의 정답 라벨 0건",
        "성격": f"**회수됨 ({decl}).** 도입기업이 라벨 어휘를 {list(vocab)} 3종으로 확정했다",
        "결정번호": decl,
        "출처": assumed.path_text(),
        "선언": f"SYS_CONFIGS('{assumed.CONFIG_TYPE}','{assumed.CONFIG_KEY}') = {decl}",
        "회수한_것": {
            "무엇": f"가정 답변 ④(D-150)에서 파생한 `{CLS_HOLE}` 라벨과 예측 전량",
            "이전_수치": "IoU 0.5 · TP 3055 · FP 336 · FN 336 · P/R/F1 0.9009 (D-151)",
            "사유_①_범위밖": assumed.label_out_of_scope(),
            "사유_②_순환": ("라벨과 예측을 같은 DXF 기하 파싱에서 뽑아 우리 탐지를 우리가 만든 "
                        "정답과 비교했다 — 측정이 아니라 우리가 고른 값이다 (D-151)"),
            "둘의_관계": "**각각 단독으로 회수 사유다.** 하나가 풀려도 다른 하나가 남는다",
        },
        "확정_어휘": list(vocab),
        "우리가_만들_수_없는_이유": (
            "3종은 도면 위의 **영역**(표제란·BOM표·리비전표)이다. `cad/dxf.py` 의 `_title_block` 은 "
            "이름과 달리 영역을 가리지 않고 TEXT/MTEXT 에서 재질·두께 **문자열**을 찾을 뿐이라 "
            "경계상자가 나오지 않는다. 없는 탐지 결과로 정답을 만들면 그게 다시 순환이다"),
        "도입기업에_필요한_것": [
            f"{list(vocab)} 3종의 **정답 박스** — 도면 30~50건. 이것이 G-14·G-19 의 유일한 분모다",
            "Label Studio 내보내기(YOLO 포맷 images/·labels/·classes.txt) 또는 동등한 형식",
            "학습/검증/테스트 분할 기준 — 가이드는 프로젝트 단위 70:15:15 을 권고하나 "
            "사업계획서에는 없다",
        ],
        "답을_받아_지운_것": ("`TD5 5종 어휘와 라벨 클래스의 매핑 확정(또는 어휘 자체의 정정)` 은 "
                        f"더 묻지 않는다 — {decl} 에서 3종으로 확정됐다"),
        "정본_불일치_관찰": (
            f"D-98 은 해소됐다 — TD5 `EST_CAD_OBJECTS.OBJECT_TYPE` 비고 "
            f"`홀/슬롯/노즐/플랜지/치수문자 등` 은 `등` 으로 끝나는 **열린 목록**이고 "
            f"VARCHAR(50) 이라 {list(vocab)} 를 담을 자리가 있다. "
            f"`가이드 어휘를 쓰면 TD5 에 담을 자리가 없다` 던 내 판단이 틀렸다"),
        "지어내지_않은_것": f"{list(vocab)} 박스 — 한 개도 만들지 않았다",
    }
    out = {"_meta": meta, "labels": [], "predictions": [],
           "evaluator_selftest": old["evaluator_selftest"]}
    print(f"**회수** — 도입기업 확정 어휘 {list(vocab)} 에 `{CLS_HOLE}` 이 없다.")
    print(f"  이전 라벨 {len(old.get('labels', []))} · 예측 {len(old.get('predictions', []))} "
          f"→ 0 · 0")
    print(f"  사유 ① {assumed.label_out_of_scope()[:70]}")
    print("  사유 ② 순환 (D-151) — 각각 단독으로 회수 사유다")
    print("  G-14 는 차단이 정답이다 — 3종 정답 라벨은 도입기업이 주어야 한다")
    if dry:
        print("  (--dry-run · 파일을 쓰지 않았다)")
        return 0
    LABELSET.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  → {LABELSET.relative_to(ROOT)}")
    return 0


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

    old = json.loads(LABELSET.read_text(encoding="utf-8"))

    # ── 어휘 확인 (D-160 ④) ─────────────────────────────────────────────
    # 도입기업이 3종을 확정했다. 우리가 만들 줄 아는 라벨은 **홀**뿐인데 홀은 범위 밖이다.
    # 그러면 만들 것이 없다 — **비우는 것이 답이다.** 어휘를 코드에서 고르지 않고
    # 선언 파일에서 꺼내므로, 답이 바뀌면 이 분기도 따라 바뀐다.
    vocab = assumed.label_vocab()
    if vocab and CLS_HOLE not in vocab:
        return withdraw(old, decl, vocab, a.dry_run)
    if not vocab:
        print(f"선언은 {decl} 인데 라벨 어휘를 읽지 못했다 — 라벨을 만들지 않는다.",
              file=sys.stderr)
        print(f"  {assumed.path_text()} 의 `{assumed.K_LABEL}.답변` 에 백틱으로 감싼 "
              "클래스 이름이 있어야 한다.", file=sys.stderr)
        return 1

    picked, skipped = collect(a.drawings)
    built = build(picked)

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
