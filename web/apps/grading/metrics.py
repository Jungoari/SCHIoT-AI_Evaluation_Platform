"""
평가 지표 레지스트리

새 지표를 추가하려면 METRICS 에 한 줄만 추가하면 된다 (유지보수성).
각 지표는 '높을수록 좋은지' 기본값을 갖고, 프로젝트에서 덮어쓸 수 있다 (RFP p.5).
"""

from dataclasses import dataclass

import numpy as np
from sklearn import metrics as skm


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    task: str  # "classification" | "regression"
    higher_is_better: bool
    description: str

    def compute(self, y_true, y_pred) -> float:
        return float(_FUNCS[self.key](y_true, y_pred))


def _rmse(y_true, y_pred):
    return np.sqrt(skm.mean_squared_error(y_true, y_pred))


_FUNCS = {
    "accuracy": skm.accuracy_score,
    "macro_f1": lambda t, p: skm.f1_score(t, p, average="macro", zero_division=0),
    "weighted_f1": lambda t, p: skm.f1_score(t, p, average="weighted", zero_division=0),
    "balanced_accuracy": skm.balanced_accuracy_score,
    "rmse": _rmse,
    "mae": skm.mean_absolute_error,
    "r2": skm.r2_score,
}

METRICS: dict[str, Metric] = {
    m.key: m
    for m in [
        Metric("accuracy", "정확도 (Accuracy)", "classification", True, "전체 중 맞힌 비율"),
        Metric("macro_f1", "Macro F1", "classification", True, "클래스별 F1의 단순 평균 (불균형 데이터에 적합)"),
        Metric("weighted_f1", "Weighted F1", "classification", True, "클래스 비율로 가중한 F1"),
        Metric("balanced_accuracy", "Balanced Accuracy", "classification", True, "클래스별 재현율의 평균"),
        Metric("rmse", "RMSE", "regression", False, "평균 제곱근 오차 (낮을수록 좋음)"),
        Metric("mae", "MAE", "regression", False, "평균 절대 오차 (낮을수록 좋음)"),
        Metric("r2", "R² (결정계수)", "regression", True, "설명력 (1에 가까울수록 좋음)"),
    ]
}


def metric_choices(task: str | None = None):
    return [(m.key, m.label) for m in METRICS.values() if task is None or m.task == task]


def get_metric(key: str) -> Metric:
    return METRICS[key]
