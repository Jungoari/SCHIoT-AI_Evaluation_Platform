"""TC-I: 부정 제출 탐지 (무결성 리포트)"""

import numpy as np
import pytest

from apps.integrity.models import IntegrityReport
from apps.integrity.services import analyze_notebook
from apps.testing import LABELS, notebook_bytes, notebook_json, predictions_csv, submit

pytestmark = pytest.mark.django_db


def checks(sub):
    report = IntegrityReport.objects.get(submission=sub)
    return {c["code"]: c for c in report.checks}, report.level


def test_I01_exact_copy_is_red(project, participant, participant2):
    data = predictions_csv(project, wrong_rows=[0, 5, 9])
    submit(participant, project, data)
    copy = submit(participant2, project, data)
    c, level = checks(copy)
    assert c["I-1"]["level"] == "red" and level == "red"


def _class_of(n, competition):
    from apps.competitions.models import Role
    from apps.conftest import add_member, make_user

    users = []
    for i in range(n):
        u = make_user(f"pop{i}@test.kr", f"학생{i}")
        add_member(u, competition, Role.PARTICIPANT)
        users.append(u)
    return users


def _honest_wrong_rows(rng, k=12):
    return sorted(rng.choice(60, k, replace=False).tolist())


def test_I02_partial_copy_detected_with_enough_population(project, competition):
    """정직한 참여자 10명(각자 다른 오답) + 원본을 일부 바꾼 복사본 → 🔴, 정직한 제출 → 🟢"""
    import pandas as pd

    from apps.grading.services import load_labels
    from apps.testing import LABELS, csv_bytes

    rng = np.random.default_rng(1)
    users = _class_of(12, competition)
    y = load_labels(project)
    honest_preds = []
    for u in users[:10]:
        preds = y.tolist()
        for i in _honest_wrong_rows(rng):  # 정직한 오답: 그럴듯한(인접) 레이블
            preds[i] = LABELS[(LABELS.index(preds[i]) + 1) % 3]
        honest_preds.append(preds)
        submit(u, project, csv_bytes(pd.DataFrame({"id": y.index, "label": preds})))
    # 변형 복사: 0번의 결과를 가져와 8행을 '아무도 안 낸' 값으로 바꿈 → 허용 레이블 중 드문 쪽
    src = list(honest_preds[0])
    changed = [i for i in range(60) if src[i] == y.iloc[i]][:8]
    for i in changed:
        src[i] = LABELS[(LABELS.index(src[i]) + 2) % 3]
    copy = submit(users[10], project, csv_bytes(pd.DataFrame({"id": y.index, "label": src})))
    honest = submit(users[11], project, predictions_csv(project, wrong_rows=_honest_wrong_rows(rng)))
    assert checks(copy)[0]["I-2"]["level"] == "red"
    assert checks(honest)[0]["I-2"]["level"] == "green"


def test_I02_small_population_never_red(project, participant, participant2):
    """비교 참여자가 적으면 부자연스러움을 판정할 수 없으므로 최대 🟡"""
    data = predictions_csv(project, wrong_rows=list(range(0, 30)))
    submit(participant, project, data)
    tweaked = predictions_csv(project, wrong_rows=list(range(0, 28)))
    assert checks(submit(participant2, project, tweaked))[0]["I-2"]["level"] in ("yellow", "green")


def test_I03_handwritten_predictions_flagged(project, participant):
    sub = submit(participant, project, predictions_csv(project), notebook=notebook_bytes(fit=False, predict=False, literal=True))
    assert checks(sub)[0]["I-3"]["level"] == "red"


def test_I03_normal_notebook_green(project, participant):
    sub = submit(participant, project, predictions_csv(project))
    c, _ = checks(sub)
    assert c["I-3"]["level"] == "green" and c["I-4"]["level"] == "green"


def test_I04_unexecuted_notebook_yellow(project, participant):
    sub = submit(participant, project, predictions_csv(project), notebook=notebook_bytes(executed=False))
    assert checks(sub)[0]["I-4"]["level"] == "yellow"


def test_I07_result_changed_without_code_change(project, participant):
    nb = notebook_bytes()  # 같은 노트북 파일을 그대로 다시 제출
    submit(participant, project, predictions_csv(project, wrong_rows=range(10)), notebook=nb)
    edited = submit(participant, project, predictions_csv(project, wrong_rows=[0]), notebook=nb)
    assert checks(edited)[0]["I-7"]["level"] == "red"


def test_analyze_notebook_ignores_magics():
    nb = notebook_json()
    nb["cells"][0]["source"] = "%matplotlib inline\n!pip install x\nimport pandas"
    a = analyze_notebook(nb)
    assert a["parse_errors"] == 0 and a["fit"] and a["to_csv"]


def test_labels_constant():
    assert LABELS == ["setosa", "versicolor", "virginica"]


# ---------------------------------------------------------------------------
# I-8 교차 검증 출력 — 실제 수업 노트북에서 본 출력 형식으로 검증
# ---------------------------------------------------------------------------
from apps.integrity.services import check_cv_output, find_cv_report  # noqa: E402


@pytest.mark.parametrize(
    ("text", "has_k", "mean"),
    [
        # 폴드별 줄 + 평균
        ("Fold 1: accuracy=0.84\nFold 2: accuracy=0.82\nFold 3: accuracy=0.82\nFold 4: accuracy=0.83\nFold 5: accuracy=0.85\n"
         "5-fold CV 평균 정확도: 0.8320", True, 0.832),
        # numpy 배열이 줄바꿈되고 1.0 이 '1.' 로 찍힌 경우 (실제 노트북 형식)
        ("각 fold 정확도: [0.994565 0.995924 0.990476 0.990476 0.991837 0.997279 0.997279 0.991837\n 1.       0.997279]\n"
         "10-fold 평균 정확도: 0.994695", True, 0.994695),
        # '5-fold' 라고 적었지만 점수가 2개뿐인 경우 → 인정 안 함
        ("5-fold CV accuracy results: [0.9556, 0.9508]\n5-fold CV mean accuracy: 0.9568", False, 0.9568),
        # '(10-fold)' 의 10 을 평균으로 읽지 않는다 · 'mean_rmse' 는 평균 보고가 아님
        ("최적 평균 RMSE (10-fold): 111727.8820\n상위 5개 조합 (mean_rmse 기준):", False, 111727.882),
        ("Best Mean RMSE (10-fold x 3 seeds): 0.5619", False, 0.5619),
        # 오차 행렬 행·분류 리포트의 avg 줄은 폴드 점수·평균이 아님
        ("[[1407 0 0 0 0 0]\n [0 1270 16 0 0 0]]\n   macro avg   0.99   1.00   0.99   7352", False, None),
    ],
)
def test_I08_find_cv_report_real_formats(text, has_k, mean):
    r = find_cv_report(text, 5)
    assert r["has_k_folds"] is has_k
    assert r["reported_mean"] == (pytest.approx(mean) if mean is not None else None)


def _nb_with_output(text):
    return {"cells": [{"cell_type": "code", "source": "print(scores)", "execution_count": 1,
                       "outputs": [{"output_type": "stream", "name": "stdout", "text": text}]}]}


def test_I08_only_when_project_requires(project, participant):
    sub = submit(participant, project, predictions_csv(project))
    sub.project.cv_folds = 0
    assert check_cv_output(sub, _nb_with_output("nothing")) is None
    sub.project.cv_folds = 5
    missing = check_cv_output(sub, _nb_with_output("train score 0.99"))
    assert missing["level"] == "yellow" and "5개 폴드 점수" in missing["detail"]


def test_I08_reported_mean_far_from_official_score(project, participant):
    sub = submit(participant, project, predictions_csv(project, wrong_rows=range(30)))  # 공식 점수 0.5
    sub.project.cv_folds = 5
    ok = "CV scores: [0.51 0.49 0.50 0.52 0.48]\nmean 0.50"
    inflated = "CV scores: [0.97 0.98 0.99 0.97 0.98]\nmean 0.978"
    assert check_cv_output(sub, _nb_with_output(ok))["level"] == "green"
    flagged = check_cv_output(sub, _nb_with_output(inflated))
    assert flagged["level"] == "yellow" and "차이가 큽니다" in flagged["detail"]
