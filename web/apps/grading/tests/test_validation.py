"""TC-D01~D06: CSV 형식 검사 · 지표 · 규격 추론"""

import pandas as pd
import pytest

from apps.grading.metrics import METRICS
from apps.grading.validation import infer_schema, validate_submission
from apps.testing import make_testset


class P:  # 프로젝트 대역
    id_column, target_column, task_type = "id", "label", "classification"
    allowed_labels = ["a", "b"]


IDS = pd.Index(["1", "2", "3"])


def df(rows, cols=("id", "label")):
    return pd.DataFrame(rows, columns=list(cols)).astype(str)


def codes(result):
    return [e["code"] for e in result.errors]


def test_valid_submission_reordered_ids():
    r = validate_submission(df([["3", "a"], ["1", "b"], ["2", "a"]]), P, IDS)
    assert r.ok and r.predictions.tolist() == ["b", "a", "a"]  # 정답 순서로 정렬


def test_D01_missing_row():
    r = validate_submission(df([["1", "a"], ["2", "b"]]), P, IDS)
    assert "row_count" in codes(r) and "id_missing" in codes(r)
    assert "3" in " ".join(e["message"] for e in r.errors)


def test_D02_label_not_allowed_reports_row_number():
    r = validate_submission(df([["1", "a"], ["2", "cat"], ["3", "b"]]), P, IDS)
    assert codes(r) == ["value_label"]
    assert "3행" in r.errors[0]["message"] and "'cat'" in r.errors[0]["message"]


def test_D03_header_wrong():
    r = validate_submission(df([["1", "a"], ["2", "b"], ["3", "a"]], cols=("id", "pred")), P, IDS)
    assert codes(r) == ["header_missing", "header_extra"]


def test_D04_duplicate_id():
    r = validate_submission(df([["1", "a"], ["1", "b"], ["3", "a"]]), P, IDS)
    assert "id_duplicate" in codes(r)


def test_D05_multiple_errors_collected():
    r = validate_submission(df([["1", "x"], ["1", "y"], ["9", ""]]), P, IDS)
    assert len(r.errors) >= 4


def test_errors_never_contain_answers():
    r = validate_submission(df([["1", "zzz"], ["2", "b"], ["3", "a"]]), P, IDS)
    text = " ".join(e["message"] for e in r.errors)
    assert "허용" in text  # 허용 레이블 목록은 공개 정보, 정답 값(행별 정답)은 포함되지 않음


def test_regression_requires_numbers():
    class R(P):
        target_column, task_type, allowed_labels = "y", "regression", []

    r = validate_submission(df([["1", "1.5"], ["2", "abc"], ["3", "inf"]], cols=("id", "y")), R, IDS)
    assert set(codes(r)) == {"value_number", "value_inf"}


def test_D06_metric_directions():
    assert METRICS["accuracy"].higher_is_better and not METRICS["rmse"].higher_is_better
    assert METRICS["rmse"].compute([1.0, 2.0], [1.0, 4.0]) == pytest.approx(1.41421356)


def test_infer_schema_classification_and_regression():
    s = infer_schema(make_testset().astype(str))
    assert (s.id_column, s.target_column, s.task_type) == ("id", "label", "classification")
    assert s.allowed_labels == ["setosa", "versicolor", "virginica"]
    r = infer_schema(make_testset(task="regression").astype(str))
    assert (r.target_column, r.task_type) == ("target", "regression")
