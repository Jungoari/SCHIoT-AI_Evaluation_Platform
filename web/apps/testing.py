"""
테스트·데모 공용 도우미 — 테스트셋·노트북·가중치·제출 파일을 코드로 만든다
"""

import hashlib
import io
import json

import joblib
import nbformat
import numpy as np
import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

LABELS = ["setosa", "versicolor", "virginica"]


def make_testset(n=60, seed=0, task="classification") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "id": [f"t{i:04d}" for i in range(n)],
        "f1": rng.normal(size=n).round(4),
        "f2": rng.normal(size=n).round(4),
    })
    if task == "classification":
        df["label"] = [LABELS[i % 3] for i in range(n)]
    else:
        df["target"] = (df["f1"] * 3 + rng.normal(size=n)).round(4)
    return df


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def upload(name: str, data: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def notebook_bytes(fit=True, predict=True, to_csv=True, literal=False, executed=True) -> bytes:
    nb = nbformat.v4.new_notebook()
    cells = ["import pandas as pd\nimport joblib"]
    if fit:
        cells.append("model.fit(X, y)\nprint('acc', 0.9)")
    if predict:
        cells.append("pred = model.predict(test)")
    if literal:
        cells.append("pred = " + repr(["setosa"] * 40))
    if to_csv:
        cells.append("pd.DataFrame({'id': ids, 'label': pred}).to_csv('submission.csv', index=False)")
    nb.cells = [nbformat.v4.new_code_cell(c, execution_count=(i + 1) if executed else None) for i, c in enumerate(cells)]
    return nbformat.writes(nb).encode()


def weights_bytes(obj=None) -> bytes:
    buf = io.BytesIO()
    joblib.dump(obj if obj is not None else {"w": [1, 2, 3]}, buf)
    return buf.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def predictions_csv(project, labels: pd.Series | None = None, wrong_rows=(), value=None, df=None) -> bytes:
    """정답을 기준으로 일부 행만 틀린 제출 CSV"""
    if df is not None:
        return csv_bytes(df)
    from apps.grading.services import load_labels

    y = (labels if labels is not None else load_labels(project)).copy()
    preds = y.tolist()
    for i in wrong_rows:
        if project.task_type == "classification":
            preds[i] = LABELS[(LABELS.index(preds[i]) + 1) % 3] if value is None else value
        else:
            preds[i] = str(float(preds[i]) + 5)
    return csv_bytes(pd.DataFrame({project.id_column: y.index, project.target_column: preds}))


def setup_project(competition, admin2, *, task="classification", n=60, deadlines=None, metric=None, published=True):
    """정답 업로드 → 규격 확정 → 마감일 → 공개까지 완료된 프로젝트"""
    from apps.competitions import services
    from apps.competitions.models import Deadline, Project

    metric = metric or ("accuracy" if task == "classification" else "rmse")
    project = Project.objects.create(
        competition=competition, title=f"{task} 프로젝트", task_type=task, metric=metric,
        higher_is_better=metric != "rmse", decimals=4, grace_minutes=30,
    )
    df = make_testset(n=n, task=task)
    services.upload_testset(project, upload("test_full.csv", csv_bytes(df)), admin2)
    target = "label" if task == "classification" else "target"
    services.confirm_schema(project, "id", target, task, admin2)
    now = timezone.now()
    for title, delta, limit in deadlines or [("1차 마감", timezone.timedelta(days=7), 5)]:
        Deadline.objects.create(project=project, title=title, due_at=now + delta, max_submissions=limit)
    project.is_published = published
    project.save()
    project.refresh_from_db()
    return project


def submit(user, project, csv: bytes, notebook: bytes | None = None, weights: bytes | None = None, comment=""):
    """티켓 발급 + 업로드 (테스트에서는 채점까지 즉시 실행)"""
    from apps.submissions.services import complete_upload, start_submission

    notebook = notebook if notebook is not None else notebook_bytes()
    weights = weights if weights is not None else weights_bytes()
    sub = start_submission(user, project, {"csv": sha(csv), "notebook": sha(notebook), "weights": sha(weights)})
    complete_upload(sub, {"csv": upload("pred.csv", csv), "notebook": upload("model.ipynb", notebook),
                          "weights": upload("model.joblib", weights)}, comment)
    sub.refresh_from_db()
    return sub


def notebook_json(**kw) -> dict:
    return json.loads(notebook_bytes(**kw))
