"""
무결성 리포트 — "제출한 CSV가 모델의 추론 결과인가?" 1차 자동 선별 (RFP p.8)

빠른 검사(채점 직후, 채점 워커에서 실행)
  I-1 완전 중복          : 다른 참여자와 예측값이 완전히 같은가
  I-2 부분 복사 패턴      : 상대와 대부분 같고, 갈리는 행의 내 답이 아무도 안 내는 부자연스러운 답인가 (변형 복사 탐지)
  I-3 노트북 코드 분석    : 학습·예측·CSV 저장 코드가 있는가, 손으로 적은 긴 예측값 목록이 있는가 (AST 정적 분석, 실행 안 함)
  I-4 실행 기록          : 노트북에 실제 실행 흔적이 있는가, 실행 순서가 정상인가
  I-5 가중치 파일        : 형식·크기 (pickle 은 샌드박스에서만 로드)
  I-7 결과만 바뀐 제출    : 코드·가중치는 이전 제출과 같은데 CSV 결과만 달라졌는가 (CSV 수기 수정 의심)
느린 검사(검토 대상만, 버튼으로 실행)
  I-6 추론 재실행        : sandbox.py

시스템은 '어디를 볼지' 알려줄 뿐, 자동으로 부적합 처리하지 않는다. 판단은 관리자1 → 관리자2.
"""

import ast
import json
import logging

import pandas as pd

from apps.core import storage
from apps.submissions.models import Submission

from .models import IntegrityReport

logger = logging.getLogger(__name__)

LEVEL_ORDER = {"green": 0, "unknown": 0, "yellow": 1, "red": 2}

# I-2 회귀 기준값
REG_IDENTICAL_RED, REG_IDENTICAL_YELLOW = 0.5, 0.2
OTHER_SUBMISSIONS_PER_USER = 5  # 비교 비용 제한


def _check(code, title, level, detail, evidence=None):
    return {"code": code, "title": title, "level": level, "detail": detail, "evidence": evidence or {}}


def overall_level(checks: list[dict]) -> str:
    if not checks:
        return IntegrityReport.Level.UNKNOWN
    worst = max(checks, key=lambda c: LEVEL_ORDER.get(c["level"], 0))
    return worst["level"]


# ---------------------------------------------------------------------------
# 예측값 로드
# ---------------------------------------------------------------------------
def load_predictions(sub: Submission, index: pd.Index) -> pd.Series | None:
    from apps.grading.validation import read_csv

    try:
        df = read_csv(storage.safe_path(storage.upload_root(), sub.csv_file))
        p = sub.project
        return df.set_index(p.id_column)[p.target_column].reindex(index)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# I-1, I-2
# ---------------------------------------------------------------------------
def _peer_submissions(sub: Submission):
    """다른 참여자들의 채점된 제출 (사용자별 최근 N건)"""
    qs = (
        Submission.objects.filter(project=sub.project, status=Submission.Status.GRADED)
        .exclude(user=sub.user)
        .select_related("user")
        .order_by("user_id", "-started_at")
    )
    per_user: dict[int, int] = {}
    for other in qs:
        if per_user.get(other.user_id, 0) >= OTHER_SUBMISSIONS_PER_USER:
            continue
        per_user[other.user_id] = per_user.get(other.user_id, 0) + 1
        yield other


def check_duplicates_and_copy(sub: Submission, labels: pd.Series, predictions: pd.Series) -> list[dict]:
    project = sub.project
    checks = []

    # I-1 완전 중복
    dup = (
        Submission.objects.filter(project=project, prediction_hash=sub.prediction_hash)
        .exclude(user=sub.user)
        .exclude(prediction_hash="")
        .select_related("user")
        .order_by("started_at")
        .first()
    )
    if dup:
        first = "이 제출보다 먼저" if dup.started_at < sub.started_at else "이 제출보다 나중에"
        checks.append(_check(
            "I-1", "완전 중복 제출", "red",
            f"다른 참여자의 제출과 예측값이 100% 같습니다 ({first} 제출됨)",
            {"other_submission": str(dup.pk), "other_user": dup.user_id, "other_started_at": dup.started_at.isoformat()},
        ))
    else:
        checks.append(_check("I-1", "완전 중복 제출", "green", "다른 참여자와 완전히 같은 예측값은 없습니다"))

    # I-2 부분 복사 패턴
    checks.append(check_partial_copy(sub, labels, predictions))
    return checks


MIN_POPULATION = 10  # '부자연스러운 답' 을 판정하려면 다른 참여자가 이만큼 필요
RARE = 0.05  # 다른 참여자 중 5% 미만만 낸 답 = 부자연스러운 답
PARTIAL_RED, PARTIAL_YELLOW = 0.8, 0.7
MIN_AGREEMENT, MIN_DISAGREE = 0.8, 5


def _peer_vectors(sub: Submission, index: pd.Index):
    """다른 참여자별 최신 채점 기록의 예측값 (모집단) + 비교 후보 제출들"""
    population: dict[int, pd.Series] = {}
    candidates = []
    for other in _peer_submissions(sub):
        pred = load_predictions(other, index)
        if pred is None:
            continue
        pred = pred.astype(str).str.strip() if sub.project.task_type == "classification" else pred
        population.setdefault(other.user_id, pred)  # 사용자별 최신 1건
        candidates.append((other, pred))
    return population, candidates


def check_partial_copy(sub: Submission, labels: pd.Series, predictions: pd.Series) -> dict:
    """
    I-2 부분 복사 패턴 — 남의 CSV를 가져와 일부만 바꾼 제출 탐지

    분류: 상대 B와 대부분(80% 이상) 같은데, B와 '다른 답을 낸 행'에서 내 답이
          다른 참여자 누구도 거의 내지 않은 부자연스러운 답이라면 → 원본을 무작위로 고친 전형적 패턴
          (정직한 모델은 B와 갈리는 행에서도 다른 모델들이 내는 '그럴듯한' 답을 낸다)
    실험 근거: docs/INTEGRITY_EXPERIMENT.md (다른 참여자 19명 기준 정직 최대 0.66, 변형 복사 최소 0.89)
    다른 참여자가 10명 미만이면 '부자연스러움' 을 믿을 수 없으므로 🟡 까지만 표시한다.
    회귀: 소수점 6자리까지 같은 예측값 비율
    """
    project = sub.project
    population, candidates = _peer_vectors(sub, labels.index)
    candidates = [(o, p) for o, p in candidates if o.prediction_hash != sub.prediction_hash]  # 완전 중복은 I-1
    if not candidates:
        return _check("I-2", "부분 복사 패턴", "green", "비교할 다른 참여자의 제출이 아직 없습니다")

    if project.task_type != "classification":
        a = pd.to_numeric(predictions, errors="coerce").round(6)
        best = max(((float((a == pd.to_numeric(p, errors="coerce").round(6)).mean()), o) for o, p in candidates), key=lambda x: x[0])
        key, other = best
        level = "red" if key >= REG_IDENTICAL_RED else "yellow" if key >= REG_IDENTICAL_YELLOW else "green"
        return _check("I-2", "부분 복사 패턴", level, f"가장 비슷한 다른 참여자와 예측값이 소수점 6자리까지 같은 행이 {key:.0%}입니다",
                      {"other_submission": str(other.pk), "identical": key})

    a = predictions.astype(str).str.strip()
    t = labels.astype(str).str.strip()
    best = None
    for other, b in candidates:
        agree = float((a == b).mean())
        d = a != b
        nd = int(d.sum())
        others = [v for uid, v in population.items() if uid != other.user_id]
        if others:
            mat = pd.concat(others, axis=1)
            pop_rate = mat.eq(a, axis=0).mean(axis=1)  # 내 답과 같은 답을 낸 다른 참여자 비율
            rare_on_d = int(((pop_rate < RARE) & d).sum())
        else:
            rare_on_d = 0
        unnatural = rare_on_d / nd if nd else 0.0
        b_wrong = b != t
        same_wrong = float(((a == b) & b_wrong).sum() / max(int(b_wrong.sum()), 1))
        cand = {"other": other, "agreement": agree, "disagree": nd, "unnatural": unnatural, "rare": rare_on_d,
                "population": len(others), "same_wrong": same_wrong, "b_wrong": int(b_wrong.sum())}
        score = unnatural if agree >= MIN_AGREEMENT and nd >= MIN_DISAGREE else 0.0
        if best is None or (score, agree) > (best["score"], best["agreement"]):
            best = {**cand, "score": score}

    other = best["other"]
    evidence = {k: v for k, v in best.items() if k != "other"} | {"other_submission": str(other.pk), "other_user": other.user_id}
    enough = best["population"] >= MIN_POPULATION - 1
    if best["score"] >= PARTIAL_YELLOW and enough:
        level = "red" if best["score"] >= PARTIAL_RED else "yellow"
        detail = (f"다른 참여자와 {best['agreement']:.0%} 같은 답을 냈고, 서로 다른 {best['disagree']}행 중 "
                  f"{best['rare']}행({best['score']:.0%})은 다른 참여자 누구도 거의 내지 않은 부자연스러운 답입니다 "
                  "— 남의 결과를 일부만 바꾼 전형적 패턴")
    elif not enough and best["agreement"] >= 0.9 and best["b_wrong"] >= 10 and best["same_wrong"] >= 0.9:
        level = "yellow"
        detail = (f"다른 참여자와 {best['agreement']:.0%} 같고, 그 참여자가 틀린 {best['b_wrong']}문항 중 {best['same_wrong']:.0%}에서 "
                  f"똑같은 오답을 냈습니다 (비교 참여자 {best['population'] + 1}명 — 10명 이상이면 더 정확히 판정)")
    else:
        level = "green"
        detail = f"가장 비슷한 다른 참여자와 {best['agreement']:.0%} 일치 — 서로 다른 모델에서 흔한 수준입니다"
    return _check("I-2", "부분 복사 패턴", level, detail, evidence)


# ---------------------------------------------------------------------------
# I-3, I-4 노트북 정적 분석 (실행하지 않음)
# ---------------------------------------------------------------------------
FIT_NAMES = {"fit", "fit_transform", "train", "train_on_batch", "fit_generator", "backward", "partial_fit"}
PREDICT_NAMES = {"predict", "predict_proba", "predict_classes", "forward", "decision_function", "argmax"}
SAVE_NAMES = {"dump", "save", "save_model", "save_weights", "save_pretrained", "save_file"}
LONG_LITERAL = 30


def _clean_source(src: str) -> str:
    # IPython 매직·셸 명령 줄 제거 후 파싱
    return "\n".join("" if line.lstrip().startswith(("%", "!")) else line for line in src.splitlines())


def analyze_notebook(nb: dict) -> dict:
    found = {"fit": False, "predict": False, "to_csv": False, "read_test": False, "save": False}
    long_literals = 0
    parse_errors = 0
    exec_counts = []
    executed = 0
    code_cells = 0
    with_output = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        code_cells += 1
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        if cell.get("execution_count") is not None:
            executed += 1
            exec_counts.append(cell["execution_count"])
        if cell.get("outputs"):
            with_output += 1
        try:
            tree = ast.parse(_clean_source(src))
        except SyntaxError:
            parse_errors += 1
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                if name in FIT_NAMES:
                    found["fit"] = True
                if name in PREDICT_NAMES:
                    found["predict"] = True
                if name == "to_csv" or name == "writer":
                    found["to_csv"] = True
                if name in SAVE_NAMES:
                    found["save"] = True
                if name == "read_csv":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "test" in arg.value.lower():
                            found["read_test"] = True
            if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= LONG_LITERAL:
                if all(isinstance(e, ast.Constant) for e in node.elts):
                    long_literals += 1
    ordered = exec_counts == sorted(exec_counts) and len(set(exec_counts)) == len(exec_counts)
    return {
        **found, "long_literals": long_literals, "parse_errors": parse_errors, "code_cells": code_cells,
        "executed": executed, "with_output": with_output, "ordered": ordered,
    }


def check_notebook(sub: Submission) -> list[dict]:
    try:
        with open(storage.safe_path(storage.upload_root(), sub.notebook_file), encoding="utf-8") as fh:
            nb = json.load(fh)
    except Exception:
        return [_check("I-3", "노트북 코드 분석", "yellow", "노트북을 분석할 수 없습니다")]
    a = analyze_notebook(nb)
    checks = []

    missing = [label for key, label in (("fit", "학습(fit)"), ("predict", "예측(predict)"), ("to_csv", "CSV 저장")) if not a[key]]
    if a["long_literals"]:
        level, detail = "red", f"코드에 상수 {LONG_LITERAL}개 이상으로 된 목록이 {a['long_literals']}개 있습니다 (예측값을 손으로 적었을 가능성)"
    elif not a["fit"] and not a["predict"]:
        level, detail = "red", "학습·예측 코드가 모두 없습니다 (CSV가 모델로 만들어졌다는 근거가 없음)"
    elif missing:
        level, detail = "yellow", "다음 코드를 찾지 못했습니다: " + ", ".join(missing)
    else:
        level, detail = "green", "학습 → 예측 → CSV 저장 코드가 모두 있습니다"
    checks.append(_check("I-3", "노트북 코드 분석", level, detail, a))

    if a["executed"] == 0:
        level, detail = "yellow", "실행 기록이 없는 노트북입니다 (측정치 로그 확인 불가)"
    elif not a["ordered"]:
        level, detail = "yellow", "셀 실행 순서가 뒤섞여 있습니다 (위에서부터 다시 실행하면 결과가 다를 수 있음)"
    else:
        level, detail = "green", f"코드 셀 {a['code_cells']}개 중 {a['executed']}개 실행, {a['with_output']}개 출력 기록 있음"
    checks.append(_check("I-4", "실행 기록", level, detail))
    return checks


# ---------------------------------------------------------------------------
# I-5, I-7
# ---------------------------------------------------------------------------
def check_weights(sub: Submission) -> dict:
    size_mb = 0.0
    try:
        size_mb = storage.safe_path(storage.upload_root(), sub.weights_file).stat().st_size / (1024 * 1024)
    except Exception:  # noqa: S110  # nosec B110 — 크기 확인 실패는 0으로 표시
        pass
    note = " · pickle 계열이므로 샌드박스 안에서만 로드합니다" if sub.weights_format in ("pickle", "joblib", "pytorch") else ""
    level = "yellow" if size_mb * 1024 * 1024 < 100 else "green"  # 100바이트 미만은 사실상 빈 파일
    return _check("I-5", "가중치 파일", level, f"형식 {sub.weights_format}, {size_mb:.2f}MB{note}")


def check_result_only_changed(sub: Submission) -> dict:
    prev = (
        Submission.objects.filter(
            project=sub.project, user=sub.user, status=Submission.Status.GRADED, started_at__lt=sub.started_at
        )
        .order_by("-started_at")
        .first()
    )
    if prev is None:
        return _check("I-7", "결과만 바뀐 제출", "green", "이전 제출이 없습니다")
    same_code = prev.declared_hashes.get("notebook") == sub.declared_hashes.get("notebook")
    same_weights = prev.declared_hashes.get("weights") == sub.declared_hashes.get("weights")
    changed_csv = prev.prediction_hash != sub.prediction_hash
    if same_code and same_weights and changed_csv:
        return _check(
            "I-7", "결과만 바뀐 제출", "red",
            "노트북과 가중치는 직전 제출과 똑같은데 예측 결과만 달라졌습니다 (CSV 직접 수정 의심)",
            {"previous_submission": str(prev.pk)},
        )
    return _check("I-7", "결과만 바뀐 제출", "green", "직전 제출과 비교해 이상한 점이 없습니다")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run_quick_checks(sub: Submission, labels: pd.Series | None = None, predictions: pd.Series | None = None):
    if labels is None:
        from apps.grading.services import load_labels

        labels = load_labels(sub.project)
    if predictions is None:
        predictions = load_predictions(sub, labels.index)
    checks = []
    if predictions is not None and sub.prediction_hash:
        checks += check_duplicates_and_copy(sub, labels, predictions)
    checks += check_notebook(sub)
    checks.append(check_weights(sub))
    checks.append(check_result_only_changed(sub))

    report, _ = IntegrityReport.objects.get_or_create(submission=sub)
    # 재실행(I-6) 결과는 유지
    rerun_checks = [c for c in report.checks if c.get("code") == "I-6"]
    report.checks = checks + rerun_checks
    report.level = overall_level(report.checks)
    report.save()
    return report

