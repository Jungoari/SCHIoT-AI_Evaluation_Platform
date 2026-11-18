"""
데모 데이터 생성기 — 실제 sklearn 모델을 학습해 '진짜 같은' 제출과 부정 제출 사례를 만든다

프로젝트
  1) 손글씨 숫자 분류 (sklearn digits, 10클래스, Accuracy ↑)
  2) 당뇨 진행도 예측 (sklearn diabetes, 회귀, RMSE ↓)

부정 제출 사례 (무결성 리포트 시연용)
  - 오지우  : 박민준의 CSV를 그대로 제출                 → I-1 완전 중복
  - 한예준  : 최서연의 CSV를 일부 고쳐 제출              → I-2 오답 패턴 일치
  - 임수아  : 예측값을 코드에 직접 적은 노트북            → I-3 노트북 코드 분석
  - 윤지호  : 코드·가중치는 그대로 두고 CSV만 수정         → I-7 결과만 바뀐 제출 (+ I-6 재실행 불일치)
"""

import io
from datetime import timedelta

import joblib
import nbformat
import numpy as np
import pandas as pd
from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from sklearn.datasets import load_diabetes, load_digits
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from apps.competitions import services as comp_services
from apps.competitions.models import Deadline, Project, ProjectFile
from apps.review import services as review_services
from apps.submissions.models import Submission
from apps.submissions.services import complete_upload, start_submission
from apps.testing import sha, upload


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------
def digits_frames():
    data = load_digits()
    X = pd.DataFrame(data.data.astype(int), columns=[f"px{i}" for i in range(64)])
    y = pd.Series(data.target, name="label")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.33, random_state=7, stratify=y)
    train = Xtr.copy()
    train.insert(0, "id", [f"tr{i:04d}" for i in range(len(train))])
    train["label"] = ytr.values
    test = Xte.copy()
    test.insert(0, "id", [f"te{i:04d}" for i in range(len(test))])
    test["label"] = yte.values
    return train.reset_index(drop=True), test.reset_index(drop=True)


def diabetes_frames():
    data = load_diabetes()
    X = pd.DataFrame(data.data, columns=data.feature_names).round(6)
    y = pd.Series(data.target, name="progression")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.32, random_state=3)
    train = Xtr.copy()
    train.insert(0, "id", [f"p{i:04d}" for i in range(len(train))])
    train["progression"] = ytr.values
    test = Xte.copy()
    test.insert(0, "id", [f"q{i:04d}" for i in range(len(test))])
    test["progression"] = yte.values
    return train.reset_index(drop=True), test.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 제출물 생성 (노트북 · 가중치 · CSV)
# ---------------------------------------------------------------------------
def make_notebook(model_code: str, target: str, log_lines: list[str], *, literal_preds=None) -> bytes:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    cells = [nbformat.v4.new_markdown_cell("# 제출 노트북\n모델 학습 → 가중치 저장 → inference 셀로 예측 CSV 생성")]
    setup = nbformat.v4.new_code_cell(
        "import os\nimport pandas as pd\nimport joblib\n" f"ID_COL, TARGET_COL = 'id', {target!r}",
        metadata={"tags": ["setup"]}, execution_count=1,
    )
    cells.append(setup)
    if literal_preds is None:
        train = nbformat.v4.new_code_cell(
            "train = pd.read_csv('train.csv')\nX = train.drop(columns=[ID_COL, TARGET_COL])\ny = train[TARGET_COL]\n"
            f"{model_code}\nmodel.fit(X, y)\nprint('train score', round(model.score(X, y), 4))\n"
            "joblib.dump(model, 'model.joblib', compress=3)",
            execution_count=2,
        )
        train.outputs = [nbformat.v4.new_output("stream", name="stdout", text="\n".join(log_lines) + "\n")]
        cells.append(train)
        infer = nbformat.v4.new_code_cell(
            "TEST_FEATURES_PATH = os.environ.get('TEST_FEATURES_PATH', 'test_features.csv')\n"
            "WEIGHTS_PATH = os.environ.get('WEIGHTS_PATH', 'model.joblib')\n"
            "OUTPUT_PATH = os.environ.get('OUTPUT_PATH', 'submission.csv')\n"
            "test = pd.read_csv(TEST_FEATURES_PATH)\nmodel = joblib.load(WEIGHTS_PATH)\n"
            "pred = model.predict(test.drop(columns=[ID_COL]))\n"
            "pd.DataFrame({ID_COL: test[ID_COL], TARGET_COL: pred}).to_csv(OUTPUT_PATH, index=False)\nprint('saved', OUTPUT_PATH)",
            metadata={"tags": ["inference"]}, execution_count=3,
        )
        infer.outputs = [nbformat.v4.new_output("stream", name="stdout", text="saved submission.csv\n")]
        cells.append(infer)
    else:
        # 예측값을 코드에 직접 적은 노트북 (부정 사례)
        hand = nbformat.v4.new_code_cell(
            "test = pd.read_csv('test_features.csv')\n" f"pred = {literal_preds!r}\n"
            "pd.DataFrame({ID_COL: test[ID_COL], TARGET_COL: pred}).to_csv('submission.csv', index=False)",
            execution_count=2,
        )
        cells.append(hand)
    nb.cells = cells
    return nbformat.writes(nb).encode()


def dump_weights(model) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf, compress=3)
    return buf.getvalue()


def csv_of(ids, target, preds) -> bytes:
    return pd.DataFrame({"id": ids, target: preds}).to_csv(index=False).encode()


def submit_files(user, project, csv: bytes, notebook: bytes, weights: bytes, comment="", weights_name="model.joblib"):
    sub = start_submission(user, project, {"csv": sha(csv), "notebook": sha(notebook), "weights": sha(weights)})
    complete_upload(sub, {"csv": upload("submission.csv", csv), "notebook": upload("solution.ipynb", notebook),
                          "weights": upload(weights_name, weights)}, comment)
    sub.refresh_from_db()
    return sub


def backdate(sub: Submission, when, deadline=None):
    fields = {"started_at": when, "uploaded_at": when + timedelta(seconds=20), "graded_at": when + timedelta(seconds=25)}
    if deadline is not None:
        fields["deadline"] = deadline
    Submission.objects.filter(pk=sub.pk).update(**fields)


# ---------------------------------------------------------------------------
# 전체 시나리오
# ---------------------------------------------------------------------------
@override_settings(RQ_EAGER=True)
def build(prof, ta, students: dict, comp, log=print):
    now = timezone.now()

    # ---------- 프로젝트 1: 손글씨 숫자 분류 ----------
    train, test = digits_frames()
    p1 = Project.objects.create(
        competition=comp, title="손글씨 숫자 분류", task_type="classification", metric="accuracy",
        higher_is_better=True, decimals=4, grace_minutes=30,
        description="8×8 손글씨 숫자 이미지(픽셀 64개)를 0~9로 분류합니다.\n평가 지표: 정확도(Accuracy)",
    )
    comp_services.upload_testset(p1, upload("digits_test_with_labels.csv", test.to_csv(index=False).encode()), prof)
    comp_services.add_project_file(p1, ProjectFile.Kind.TRAIN, upload("digits_train.csv", train.to_csv(index=False).encode()), prof)
    comp_services.confirm_schema(p1, "id", "label", "classification", prof)
    d1 = Deadline.objects.create(project=p1, title="1차 마감", due_at=now + timedelta(days=2, hours=6), max_submissions=3)
    Deadline.objects.create(project=p1, title="최종 마감", due_at=now + timedelta(days=6, hours=6), max_submissions=5)
    p1.is_published = True
    p1.save()

    X, y = train.drop(columns=["id", "label"]), train["label"]
    Xte, ids = test.drop(columns=["id", "label"]), test["id"]
    models = {
        "logreg": ("from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(max_iter=2000)", LogisticRegression(max_iter=2000)),
        "rf": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=200, random_state=0)", RandomForestClassifier(n_estimators=200, random_state=0)),
        "knn": ("from sklearn.neighbors import KNeighborsClassifier\nmodel = KNeighborsClassifier(n_neighbors=3)", KNeighborsClassifier(n_neighbors=3)),
        "svc": ("from sklearn.svm import SVC\nmodel = SVC(C=10, gamma=0.001)", SVC(C=10, gamma=0.001)),
        "tree": ("from sklearn.tree import DecisionTreeClassifier\nmodel = DecisionTreeClassifier(random_state=0)", DecisionTreeClassifier(random_state=0)),
        "nb": ("from sklearn.naive_bayes import GaussianNB\nmodel = GaussianNB()", GaussianNB()),
        "rf_small": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=10, max_depth=6, random_state=1)", RandomForestClassifier(n_estimators=10, max_depth=6, random_state=1)),
        "knn7": ("from sklearn.neighbors import KNeighborsClassifier\nmodel = KNeighborsClassifier(n_neighbors=9, weights='distance')", KNeighborsClassifier(n_neighbors=9, weights="distance")),
        "logreg_c": ("from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(C=0.01, max_iter=2000)", LogisticRegression(C=0.01, max_iter=2000)),
        "rf_mid": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=30, max_depth=8, random_state=3)", RandomForestClassifier(n_estimators=30, max_depth=8, random_state=3)),
        "rf_hand": ("", RandomForestClassifier(n_estimators=120, random_state=11)),
    }
    fitted = {}
    for key, (code, model) in models.items():
        model.fit(X, y)
        pred = model.predict(Xte)
        acc = float((pred == test["label"].values).mean())
        fitted[key] = (code, model, pred, acc)
        log(f"  digits/{key}: {acc:.4f}")

    def legit(user, key, when, deadline=None, comment=""):
        code, model, pred, acc = fitted[key]
        nb = make_notebook(code, "label", [f"train score {model.score(X, y):.4f}", f"validation accuracy {acc:.4f}"])
        sub = submit_files(user, p1, csv_of(ids, "label", pred), nb, dump_weights(model), comment)
        backdate(sub, when, deadline)
        return sub, nb

    s = students
    day = timedelta(days=1)
    # 2~3일 전 제출 — 24시간 전 대비 순위 변화(▲▼)를 보여주기 위해 시점을 나눔
    legit(s["student1"], "tree", now - 3 * day, d1, "베이스라인 의사결정나무")
    legit(s["student2"], "nb", now - 3 * day + timedelta(hours=1), d1)
    legit(s["student3"], "logreg", now - 2 * day, d1, "로지스틱 회귀")
    legit(s["student4"], "rf_small", now - 2 * day, d1)
    legit(s["student5"], "knn7", now - 2 * day, d1)
    # 추가 참여자 6명 — 서로 다른 모델 (반 규모를 현실적으로 + 부분 복사 판정에 필요한 비교 모집단)
    from sklearn.ensemble import ExtraTreesClassifier
    from sklearn.neural_network import MLPClassifier

    extra = [
        ("student9", ExtraTreesClassifier(n_estimators=200, random_state=0), "엑스트라 트리"),
        ("student10", KNeighborsClassifier(n_neighbors=1), "1-NN"),
        ("student11", SVC(C=1), "SVC 기본값"),
        ("student12", MLPClassifier(hidden_layer_sizes=(64,), max_iter=400, random_state=0), "MLP 은닉층 64"),
        ("student13", LogisticRegression(C=0.3, max_iter=3000), "로지스틱 회귀 C=0.3"),
        ("student14", RandomForestClassifier(n_estimators=50, max_depth=10, random_state=1), "랜덤 포레스트 50"),
    ]
    import warnings

    for i, (key, model, comment) in enumerate(extra):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X, y)
        pred = model.predict(Xte)
        acc = float((pred == test["label"].values).mean())
        code = f"from {type(model).__module__.rsplit('.', 1)[0]} import {type(model).__name__}\nmodel = {model!r}"
        nb = make_notebook(code, "label", [f"validation accuracy {acc:.4f}"])
        sub = submit_files(s[key], p1, csv_of(ids, "label", pred), nb, dump_weights(model), comment)
        backdate(sub, now - timedelta(hours=20 - i))
        log(f"  digits/{key}: {acc:.4f}")

    # 형식 오류 예시 (횟수 미차감)
    bad = pd.DataFrame({"id": ids, "digit": fitted["rf"][2]}).to_csv(index=False).encode()
    code, model, _, acc = fitted["rf"]
    bad_sub = submit_files(s["student3"], p1, bad, make_notebook(code, "label", [f"acc {acc:.4f}"]), dump_weights(model), "열 이름 실수")
    backdate(bad_sub, now - day - timedelta(hours=3))

    # 최근 24시간 제출
    legit(s["student1"], "svc", now - timedelta(hours=10), comment="SVC 하이퍼파라미터 튜닝")
    legit(s["student2"], "knn", now - timedelta(hours=9))
    legit(s["student3"], "rf", now - timedelta(hours=8), comment="랜덤 포레스트 200그루")
    legit(s["student4"], "logreg_c", now - timedelta(hours=7), comment="규제 강도 조정")

    # 부정 사례 ①: 오지우 — 박민준의 CSV 그대로 (I-1)
    copy_csv = csv_of(ids, "label", fitted["svc"][2])
    code, model, _, acc = fitted["rf_small"]
    sub = submit_files(s["student8"], p1, copy_csv, make_notebook(code, "label", [f"acc {acc:.4f}"]), dump_weights(model))
    backdate(sub, now - timedelta(hours=5))

    # 부정 사례 ②: 한예준 — 최서연의 CSV를 일부 수정 (I-2)
    rng = np.random.default_rng(42)
    tweaked = fitted["knn"][2].copy()
    idx = rng.choice(len(tweaked), 12, replace=False)
    tweaked[idx] = (tweaked[idx] + rng.integers(1, 9, size=len(idx))) % 10  # 티 나지 않게 12문항을 다른 값으로
    code, model, _, acc = fitted["nb"]
    sub = submit_files(s["student7"], p1, csv_of(ids, "label", tweaked), make_notebook(code, "label", [f"acc {acc:.4f}"]), dump_weights(model))
    backdate(sub, now - timedelta(hours=4))

    # 부정 사례 ③: 임수아 — 예측값을 코드에 직접 기입 (I-3)
    hand = fitted["rf_hand"][2].tolist()
    nb = make_notebook("", "label", [], literal_preds=[int(v) for v in hand])
    sub = submit_files(s["student6"], p1, csv_of(ids, "label", hand), nb, dump_weights(fitted["tree"][1]))
    backdate(sub, now - timedelta(hours=3))

    # 부정 사례 ④: 윤지호 — 같은 노트북·가중치로 CSV만 수정 (I-7, I-6)
    first, nb5 = legit(s["student5"], "rf_mid", now - timedelta(hours=6), comment="랜덤 포레스트 중형")
    edited = fitted["rf_mid"][2].copy()
    wrong = np.flatnonzero(edited != test["label"].values)
    edited[wrong[: int(len(wrong) * 0.7)]] = test["label"].values[wrong[: int(len(wrong) * 0.7)]]  # 오답 70%를 손으로 고침
    w5 = dump_weights(fitted["rf_mid"][1])
    sub = submit_files(s["student5"], p1, csv_of(ids, "label", edited), nb5, w5, "튜닝 결과")
    backdate(sub, now - timedelta(hours=2))

    # 검토 진행 상황: 상위 일부 처리
    queue = review_services.queue(p1)
    by_user = {r.submission.user_id: r for r in queue}
    if s["student1"].pk in by_user:
        r = by_user[s["student1"].pk]
        review_services.propose(r, ta, "pass", "학습·추론 코드와 측정치 로그가 확인되어 적합")
        review_services.decide(r, prof, approve=True)
    if s["student3"].pk in by_user:
        review_services.propose(by_user[s["student3"].pk], ta, "pass", "랜덤 포레스트 학습 로그 확인")
    if s["student8"].pk in by_user:
        review_services.propose(by_user[s["student8"].pk], ta, "fail", "다른 참여자 제출과 예측값이 사실상 동일")

    # ---------- 프로젝트 2: 당뇨 진행도 회귀 ----------
    rtrain, rtest = diabetes_frames()
    p2 = Project.objects.create(
        competition=comp, title="당뇨 진행도 예측", task_type="regression", metric="rmse",
        higher_is_better=False, decimals=3, grace_minutes=30,
        description="환자 정보 10개 특성으로 1년 뒤 당뇨 진행도를 예측합니다.\n평가 지표: RMSE (낮을수록 좋음)",
    )
    comp_services.upload_testset(p2, upload("diabetes_test_with_labels.csv", rtest.to_csv(index=False).encode()), prof)
    comp_services.add_project_file(p2, ProjectFile.Kind.TRAIN, upload("diabetes_train.csv", rtrain.to_csv(index=False).encode()), prof)
    comp_services.confirm_schema(p2, "id", "progression", "regression", prof)
    Deadline.objects.create(project=p2, title="마감", due_at=now + timedelta(days=4), max_submissions=5)
    p2.is_published = True
    p2.save()

    RX, Ry = rtrain.drop(columns=["id", "progression"]), rtrain["progression"]
    RXte, rids = rtest.drop(columns=["id", "progression"]), rtest["id"]
    reg_models = [
        ("student1", "from sklearn.linear_model import Ridge\nmodel = Ridge(alpha=0.5)", Ridge(alpha=0.5)),
        ("student2", "from sklearn.ensemble import RandomForestRegressor\nmodel = RandomForestRegressor(random_state=0)", RandomForestRegressor(random_state=0)),
        ("student3", "from sklearn.ensemble import GradientBoostingRegressor\nmodel = GradientBoostingRegressor(random_state=0)", GradientBoostingRegressor(random_state=0)),
        ("student4", "from sklearn.neighbors import KNeighborsRegressor\nmodel = KNeighborsRegressor(n_neighbors=7)", KNeighborsRegressor(n_neighbors=7)),
    ]
    for i, (key, code, model) in enumerate(reg_models):
        model.fit(RX, Ry)
        pred = np.round(model.predict(RXte), 4)
        nb = make_notebook(code, "progression", [f"train R2 {model.score(RX, Ry):.4f}"])
        sub = submit_files(s[key], p2, csv_of(rids, "progression", pred), nb, dump_weights(model))
        backdate(sub, now - timedelta(hours=30 - i * 5))
    return p1, p2


def sandbox_available() -> bool:
    try:
        import docker

        docker.from_env().images.get(settings.SANDBOX_IMAGE)
        return True
    except Exception:
        return False
