"""
사용성 테스트·업무 시간 실측 결과를 README 에 붙일 마크다운 표로 바꾼다

    python scripts/usability_report.py docs/usability/sus_responses.csv docs/usability/task_log.csv [docs/usability/time_log.csv]

입력 파일 형식 (docs/usability/*_template.csv 를 복사해서 채운다)
  sus_responses.csv : tester, q1 ~ q10            (각 1~5점)
  task_log.csv      : tester, task, completed(Y/N), seconds, errors, note
  time_log.csv      : work, items, manual_seconds, system_seconds   (선택, 업무 시간 실측)

SUS 계산 (Brooke, 1996)
  홀수 문항(긍정) : 점수 - 1
  짝수 문항(부정) : 5 - 점수
  합계 × 2.5 → 0~100점 (68점 평균, 80.3점 이상 상위 10%)
"""

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def sus_score(answers: list[int]) -> float:
    if len(answers) != 10 or any(a < 1 or a > 5 for a in answers):
        raise ValueError(f"SUS 응답은 1~5점 10개여야 합니다: {answers}")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5


def grade(score: float) -> str:
    # Bangor et al. (2009) 형용사 척도를 단순화한 등급
    if score >= 80.3:
        return "A (우수)"
    if score >= 68:
        return "B (평균 이상)"
    if score >= 51:
        return "C (개선 필요)"
    return "F (사용 곤란)"


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def sus_section(path: Path) -> list[str]:
    rows = read_rows(path)
    scores = {r["tester"]: sus_score([int(r[f"q{i}"]) for i in range(1, 11)]) for r in rows}
    mean = statistics.mean(scores.values())
    lines = ["### SUS 사용성 점수", "", "| 테스터 | SUS |", "|---|---:|"]
    lines += [f"| {t} | {s:.1f} |" for t, s in scores.items()]
    lines += ["", f"**평균 {mean:.1f}점 — {grade(mean)}** (n={len(scores)}, 업계 평균 68점)", ""]
    return lines


def task_section(path: Path) -> list[str]:
    by_task = defaultdict(list)
    for r in read_rows(path):
        by_task[r["task"]].append(r)
    lines = ["### 과제 수행 결과", "", "| 과제 | 완료율 | 소요 시간 중앙값 | 평균 실수 |", "|---|---:|---:|---:|"]
    for task, rows in by_task.items():
        done = [r for r in rows if r["completed"].strip().upper() == "Y"]
        secs = [float(r["seconds"]) for r in done if r["seconds"].strip()]
        errs = [int(r["errors"] or 0) for r in rows]
        median = f"{statistics.median(secs):.0f}초" if secs else "-"
        lines.append(f"| {task} | {len(done)}/{len(rows)} | {median} | {statistics.mean(errs):.1f} |")
    notes = [f"- {r['tester']} · {r['task']}: {r['note']}" for rows in by_task.values() for r in rows if r.get("note", "").strip()]
    if notes:
        lines += ["", "발견한 문제", *notes]
    return lines + [""]


def time_section(path: Path) -> list[str]:
    lines = ["### 업무 시간 실측", "", "| 업무 | 건수 | 수작업 | 시스템 | 절감 |", "|---|---:|---:|---:|---:|"]
    total_m = total_s = 0.0
    for r in read_rows(path):
        m, s = float(r["manual_seconds"]), float(r["system_seconds"])
        total_m, total_s = total_m + m, total_s + s
        cut = (1 - s / m) * 100 if m else 0
        lines.append(f"| {r['work']} | {r['items']} | {m / 60:.1f}분 | {s / 60:.1f}분 | −{cut:.0f}% |")
    if total_m:
        lines.append(f"| **합계** | | **{total_m / 60:.1f}분** | **{total_s / 60:.1f}분** | **−{(1 - total_s / total_m) * 100:.0f}%** |")
    return lines + [""]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    out = sus_section(Path(argv[1])) + task_section(Path(argv[2]))
    if len(argv) > 3:
        out += time_section(Path(argv[3]))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
