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
