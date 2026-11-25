"""
데모 데이터 생성기 — 딥러닝 수업 미니프로젝트 1~4 를 그대로 옮긴 대회를 실제 모델로 만든다

프로젝트 (데이터: apps/core/demo_data/ — 출처·라이선스는 그 폴더의 README)
  1) 패션 MNIST 분류        (28×28 이미지 784픽셀, 10클래스, 정확도 ↑)
  2) 스마트폰 행동 인식 HAR  (센서 특성 561개, 6가지 행동, 정확도 ↑)
  3) 킹 카운티 집값 예측     (주택 특성 18개, 회귀, RMSE ↓)
  4) 레드 와인 품질 예측     (화학 특성 11개, 회귀, RMSE ↓)

수업 규칙 "5-폴드 교차 검증 결과와 평균이 출력된 노트북만 인정" → 모든 프로젝트 cv_folds=5 (무결성 검사 I-8).
정직한 제출 노트북에는 실제로 계산한 5-폴드 점수와 평균이 출력돼 있다.

부정·실수 사례 (무결성 리포트 시연용, 프로젝트 1)
  - 오지우  : 박민준의 CSV를 그대로 제출                 → I-1 완전 중복
  - 한예준  : 최서연의 CSV를 일부 고쳐 제출              → I-2 부분 복사 패턴
  - 임수아  : 예측값을 코드에 직접 적은 노트북            → I-3 노트북 코드 분석 (+ I-8 교차 검증 출력 없음)
  - 윤지호  : 코드·가중치는 그대로 두고 CSV만 수정         → I-7 결과만 바뀐 제출 (+ I-6 재실행 불일치)
그 밖의 사례
  - 프로젝트 2 : 교차 검증 출력을 빼먹은 제출             → I-8 🟡
  - 프로젝트 3 : 훈련 데이터로 '검증'해 평균을 부풀린 제출 → I-8 🟡 (보고값과 실제 점수 차이)
"""

import io
import warnings
from datetime import timedelta
from pathlib import Path

import joblib
import nbformat
import numpy as np
import pandas as pd
from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from apps.competitions import services as comp_services
from apps.competitions.models import Deadline, Project, ProjectFile
from apps.review import services as review_services
from apps.submissions.models import Submission
from apps.submissions.services import complete_upload, start_submission
from apps.testing import sha, upload

DATA = Path(__file__).resolve().parent / "demo_data"
CV_FOLDS = 5
CV_SPLIT = KFold(n_splits=CV_FOLDS, shuffle=True, random_state=42)

# 화면·녹화 스크립트에서 함께 쓰는 프로젝트 이름
P1_TITLE = "1. 패션 MNIST 분류"
P2_TITLE = "2. 스마트폰 행동 인식 (HAR)"
P3_TITLE = "3. 킹 카운티 집값 예측"
P4_TITLE = "4. 레드 와인 품질 예측"
FASHION_CLASSES = ["T-shirt/top", "Trouser", "Pullover", "Dress", "Coat", "Sandal", "Shirt", "Sneaker", "Bag", "Ankle boot"]


# ---------------------------------------------------------------------------
# 데이터셋 — (학습용 DataFrame, 정답 포함 평가용 DataFrame), 모두 'id' 열 포함
# ---------------------------------------------------------------------------
def _with_id(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    df.insert(0, "id", [f"{prefix}{i:05d}" for i in range(len(df))])
    return df


def digits_frames():
    """부정 탐지 실험(integrity_experiment)용 — 실험 결과 문서가 이 데이터 기준이라 그대로 유지"""
    from sklearn.datasets import load_digits

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


def fashion_frames():
    d = np.load(DATA / "fashion_mnist.npz")
    df = pd.DataFrame(d["X"].astype(int), columns=[f"px{i}" for i in range(784)])
    df["label"] = d["y"].astype(int)
    train, test = train_test_split(df, test_size=1500, random_state=7, stratify=df["label"])
    return _with_id(train, "tr"), _with_id(test, "te")


def har_frames():
    d = np.load(DATA / "har.npz")
    df = pd.DataFrame(d["X"].astype(np.float32).round(6), columns=[str(c) for c in d["columns"]])
    df["activity"] = d["y"].astype(str)
    train, test = train_test_split(df, test_size=1000, random_state=7, stratify=df["activity"])
    return _with_id(train, "h"), _with_id(test, "q")


def kc_frames():
    df = pd.read_csv(DATA / "kc_house_data.csv.gz").drop(columns=["id"])  # 원본 id 는 같은 집이 두 번 팔리면 중복
    train, test = train_test_split(df, test_size=4000, random_state=7)
    return _with_id(train, "k"), _with_id(test, "x")


def wine_frames():
    df = pd.read_csv(DATA / "winequality_red.csv")
    train, test = train_test_split(df, test_size=400, random_state=7)
    return _with_id(train, "w"), _with_id(test, "v")


# ---------------------------------------------------------------------------
# 제출물 생성 (노트북 · 가중치 · CSV)
# ---------------------------------------------------------------------------
METRIC_NAME = {"accuracy": "accuracy", "rmse": "RMSE"}
SCORING = {"accuracy": "accuracy", "rmse": "neg_root_mean_squared_error"}


def cv_scores(model, X, y, metric: str) -> list[float]:
    """노트북에 출력할 실제 5-폴드 교차 검증 점수 (수업과 같은 방식)"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = cross_val_score(model, X, y, cv=CV_SPLIT, scoring=SCORING[metric], n_jobs=-1)
    return [float(-v if metric == "rmse" else v) for v in s]


def cv_log(scores: list[float], metric: str) -> list[str]:
    name = METRIC_NAME[metric]
    lines = [f"Fold {i}: {name}={v:.4f}" for i, v in enumerate(scores, 1)]
    lines.append(f"{len(scores)}-fold CV 평균 {name}: {np.mean(scores):.4f}")
    return lines


def make_notebook(model_code: str, target: str, log_lines: list[str], *, literal_preds=None,
                  metric: str = "accuracy", with_cv: bool = True, numeric_only: bool = False) -> bytes:
    """
    제출 노트북 (setup · 학습 · inference 셀). with_cv 이면 학습 셀에 5-폴드 교차 검증 코드가 들어가고,
    log_lines 가 그 셀의 실행 출력으로 저장된다 (실제로 계산한 점수).
    """
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    cells = [nbformat.v4.new_markdown_cell("# 제출 노트북\n모델 학습 → 5-폴드 교차 검증 → 가중치 저장 → inference 셀로 예측 CSV 생성")]
    setup = nbformat.v4.new_code_cell(
        "import os\nimport numpy as np\nimport pandas as pd\nimport joblib\n" f"ID_COL, TARGET_COL = 'id', {target!r}",
        metadata={"tags": ["setup"]}, execution_count=1,
    )
    cells.append(setup)
    pick = ".select_dtypes('number')" if numeric_only else ""
    if literal_preds is None:
        cv = ""
        if with_cv:
            neg = "-" if metric == "rmse" else ""
            cv = (
                "from sklearn.model_selection import KFold, cross_val_score\n"
                f"scores = {neg}cross_val_score(model, X, y, cv=KFold({CV_FOLDS}, shuffle=True, random_state=42), "
                f"scoring={SCORING[metric]!r})\n"
                f"for i, s in enumerate(scores, 1):\n    print(f'Fold {{i}}: {METRIC_NAME[metric]}={{s:.4f}}')\n"
                f"print(f'{CV_FOLDS}-fold CV 평균 {METRIC_NAME[metric]}: {{scores.mean():.4f}}')\n"
            )
        train = nbformat.v4.new_code_cell(
            f"train = pd.read_csv('train.csv')\nX = train.drop(columns=[ID_COL, TARGET_COL]){pick}\ny = train[TARGET_COL]\n"
            f"{model_code}\n{cv}model.fit(X, y)\njoblib.dump(model, 'model.joblib', compress=3)",
            execution_count=2,
        )
        train.outputs = [nbformat.v4.new_output("stream", name="stdout", text="\n".join(log_lines) + "\n")] if log_lines else []
        cells.append(train)
        infer = nbformat.v4.new_code_cell(
            "TEST_FEATURES_PATH = os.environ.get('TEST_FEATURES_PATH', 'test_features.csv')\n"
            "WEIGHTS_PATH = os.environ.get('WEIGHTS_PATH', 'model.joblib')\n"
            "OUTPUT_PATH = os.environ.get('OUTPUT_PATH', 'submission.csv')\n"
            "test = pd.read_csv(TEST_FEATURES_PATH)\nmodel = joblib.load(WEIGHTS_PATH)\n"
            f"pred = model.predict(test.drop(columns=[ID_COL]){pick})\n"
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


def _project(comp, prof, title, task, metric, decimals, description, train, test, target, deadlines, file_stem):
    """정답 파일 업로드 → 학습 데이터 배포 → 형식 확정 → 마감일 → 공개 (교수가 화면에서 하는 순서 그대로)"""
    p = Project.objects.create(
        competition=comp, title=title, task_type=task, metric=metric, higher_is_better=(metric != "rmse"),
        decimals=decimals, grace_minutes=30, cv_folds=CV_FOLDS, description=description,
    )
    comp_services.upload_testset(p, upload(f"{file_stem}_test_with_labels.csv", test.to_csv(index=False).encode()), prof)
    comp_services.add_project_file(p, ProjectFile.Kind.TRAIN, upload(f"{file_stem}_train.csv", train.to_csv(index=False).encode()), prof)
    comp_services.confirm_schema(p, "id", target, task, prof)
    made = [Deadline.objects.create(project=p, title=t, due_at=due, max_submissions=n) for t, due, n in deadlines]
    p.is_published = True
    p.save()
    return p, made


def _fit_all(models: dict, X, y, Xte, metric: str, log, tag: str, truth=None):
    """모델마다 실제 5-폴드 CV 점수 계산 → 전체 학습 → 평가용 예측"""
    fitted = {}
    for key, (code, model) in models.items():
        scores = cv_scores(model, X, y, metric) if code else []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X, y)
        pred = model.predict(Xte)
        if metric == "rmse":
            pred = np.round(pred, 4)
        fitted[key] = (code, model, pred, scores)
        msg = f"CV {np.mean(scores):.4f}" if scores else ""
        if truth is not None and metric == "accuracy":
            msg += f" · test {float((pred == truth).mean()):.4f}"
        log(f"  {tag}/{key}: {msg}")
    return fitted


# ---------------------------------------------------------------------------
# 전체 시나리오
# ---------------------------------------------------------------------------
@override_settings(RQ_EAGER=True)
def build(prof, ta, students: dict, comp, log=print):
    now = timezone.now()
    s = students
    day = timedelta(days=1)

    # ======================= 프로젝트 1: 패션 MNIST 분류 =======================
    train, test = fashion_frames()
    p1, (d1, _) = _project(
        comp, prof, P1_TITLE, "classification", "accuracy", 4,
        "딥러닝 미니프로젝트 #1 — 28×28 패션 이미지(784픽셀, 0~255)를 10개 클래스로 분류합니다.\n"
        "클래스: " + ", ".join(f"{i} {c}" for i, c in enumerate(FASHION_CLASSES)) + "\n"
        "평가 지표: 정확도(Accuracy) · 노트북에 5-폴드 교차 검증 결과와 평균을 반드시 출력하세요",
        train, test, "label",
        [("1차 마감", now + timedelta(days=2, hours=6), 3), ("최종 마감", now + timedelta(days=6, hours=6), 5)],
        "fashion_mnist",
    )
    X, y = train.drop(columns=["id", "label"]), train["label"]
    Xte, ids = test.drop(columns=["id", "label"]), test["id"]
    truth = test["label"].values
    mm = "from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import MinMaxScaler\n"
    models = {
        "logreg": (mm + "from sklearn.linear_model import LogisticRegression\nmodel = make_pipeline(MinMaxScaler(), LogisticRegression(max_iter=300))",
                   make_pipeline(MinMaxScaler(), LogisticRegression(max_iter=300))),
        "rf": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=100, random_state=0)",
               RandomForestClassifier(n_estimators=100, random_state=0)),
        "knn": (mm + "from sklearn.neighbors import KNeighborsClassifier\nmodel = make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=3))",
                make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=3))),
        "svc": (mm + "from sklearn.svm import SVC\nmodel = make_pipeline(MinMaxScaler(), SVC(C=10))",
                make_pipeline(MinMaxScaler(), SVC(C=10))),
        "tree": ("from sklearn.tree import DecisionTreeClassifier\nmodel = DecisionTreeClassifier(random_state=0)",
                 DecisionTreeClassifier(random_state=0)),
        "nb": ("from sklearn.naive_bayes import GaussianNB\nmodel = GaussianNB()", GaussianNB()),
        "rf_small": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=10, max_depth=6, random_state=1)",
                     RandomForestClassifier(n_estimators=10, max_depth=6, random_state=1)),
        "knn7": (mm + "from sklearn.neighbors import KNeighborsClassifier\nmodel = make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=9, weights='distance'))",
                 make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=9, weights="distance"))),
        "logreg_c": (mm + "from sklearn.linear_model import LogisticRegression\nmodel = make_pipeline(MinMaxScaler(), LogisticRegression(C=0.05, max_iter=300))",
                     make_pipeline(MinMaxScaler(), LogisticRegression(C=0.05, max_iter=300))),
        "rf_mid": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=30, max_depth=12, random_state=3)",
                   RandomForestClassifier(n_estimators=30, max_depth=12, random_state=3)),
        "et": ("from sklearn.ensemble import ExtraTreesClassifier\nmodel = ExtraTreesClassifier(n_estimators=200, random_state=0)",
               ExtraTreesClassifier(n_estimators=200, random_state=0)),
        "nn1": (mm + "from sklearn.neighbors import KNeighborsClassifier\nmodel = make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=1))",
                make_pipeline(MinMaxScaler(), KNeighborsClassifier(n_neighbors=1))),
        "svc1": (mm + "from sklearn.svm import SVC\nmodel = make_pipeline(MinMaxScaler(), SVC(C=1))",
                 make_pipeline(MinMaxScaler(), SVC(C=1))),
        "mlp": (mm + "from sklearn.neural_network import MLPClassifier\nmodel = make_pipeline(MinMaxScaler(), MLPClassifier(hidden_layer_sizes=(128,), max_iter=60, random_state=0))",
                make_pipeline(MinMaxScaler(), MLPClassifier(hidden_layer_sizes=(128,), max_iter=60, random_state=0))),
        "lda": ("from sklearn.discriminant_analysis import LinearDiscriminantAnalysis\nmodel = LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')",
                LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")),
        "rf50": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=50, max_depth=14, random_state=1)",
                 RandomForestClassifier(n_estimators=50, max_depth=14, random_state=1)),
        "rf_hand": ("", RandomForestClassifier(n_estimators=120, random_state=11)),
    }
    fitted = _fit_all(models, X, y, Xte, "accuracy", log, "fashion", truth)

    def legit(user, key, when, deadline=None, comment=""):
        code, model, pred, scores = fitted[key]
        nb = make_notebook(code, "label", cv_log(scores, "accuracy"))
        sub = submit_files(user, p1, csv_of(ids, "label", pred), nb, dump_weights(model), comment)
        backdate(sub, when, deadline)
        return sub, nb

    # 2~3일 전 제출 — 24시간 전 대비 순위 변화(▲▼)를 보여주기 위해 시점을 나눔
    legit(s["student1"], "tree", now - 3 * day, d1, "베이스라인 의사결정나무")
    legit(s["student2"], "nb", now - 3 * day + timedelta(hours=1), d1)
    legit(s["student3"], "logreg", now - 2 * day, d1, "로지스틱 회귀 + MinMax 스케일링")
    legit(s["student4"], "rf_small", now - 2 * day, d1)
    legit(s["student5"], "knn7", now - 2 * day, d1)
    # 추가 참여자 6명 — 서로 다른 모델 (반 규모를 현실적으로 + 부분 복사 판정에 필요한 비교 모집단)
    for i, (key, model_key, comment) in enumerate([
        ("student9", "et", "엑스트라 트리"), ("student10", "nn1", "1-NN"), ("student11", "svc1", "SVC 기본값"),
        ("student12", "mlp", "MLP 은닉층 128"), ("student13", "lda", "선형 판별 분석"),
        ("student14", "rf50", "랜덤 포레스트 50"),
    ]):
        legit(s[key], model_key, now - timedelta(hours=20 - i), comment=comment)

    # 형식 오류 예시 (횟수 미차감)
    bad = pd.DataFrame({"id": ids, "digit": fitted["rf"][2]}).to_csv(index=False).encode()
    code, model, _, scores = fitted["rf"]
    bad_sub = submit_files(s["student3"], p1, bad, make_notebook(code, "label", cv_log(scores, "accuracy")), dump_weights(model), "열 이름 실수")
    backdate(bad_sub, now - day - timedelta(hours=3))

    # 최근 24시간 제출
    legit(s["student1"], "svc", now - timedelta(hours=10), comment="SVC 하이퍼파라미터 튜닝")
    legit(s["student2"], "knn", now - timedelta(hours=9))
    legit(s["student3"], "rf", now - timedelta(hours=8), comment="랜덤 포레스트 100그루")
    legit(s["student4"], "logreg_c", now - timedelta(hours=7), comment="규제 강도 조정")

    # 부정 사례 ①: 오지우 — 박민준의 CSV 그대로 (I-1)
    copy_csv = csv_of(ids, "label", fitted["svc"][2])
    code, model, _, scores = fitted["rf_small"]
    sub = submit_files(s["student8"], p1, copy_csv, make_notebook(code, "label", cv_log(scores, "accuracy")), dump_weights(model))
    backdate(sub, now - timedelta(hours=5))

    # 부정 사례 ②: 한예준 — 최서연의 CSV를 일부 수정 (I-2)
    rng = np.random.default_rng(42)
    tweaked = fitted["knn"][2].copy()
    idx = rng.choice(len(tweaked), 30, replace=False)
    tweaked[idx] = (tweaked[idx] + rng.integers(1, 9, size=len(idx))) % 10  # 티 나지 않게 30문항(2%)을 다른 값으로
    code, model, _, scores = fitted["nb"]
    sub = submit_files(s["student7"], p1, csv_of(ids, "label", tweaked), make_notebook(code, "label", cv_log(scores, "accuracy")), dump_weights(model))
    backdate(sub, now - timedelta(hours=4))

    # 부정 사례 ③: 임수아 — 예측값을 코드에 직접 기입 (I-3, 교차 검증 출력도 없음 → I-8)
    hand = fitted["rf_hand"][2].tolist()
    nb = make_notebook("", "label", [], literal_preds=[int(v) for v in hand])
    sub = submit_files(s["student6"], p1, csv_of(ids, "label", hand), nb, dump_weights(fitted["tree"][1]))
    backdate(sub, now - timedelta(hours=3))

    # 부정 사례 ④: 윤지호 — 같은 노트북·가중치로 CSV만 수정 (I-7, I-6)
    first, nb5 = legit(s["student5"], "rf_mid", now - timedelta(hours=6), comment="랜덤 포레스트 중형")
    edited = fitted["rf_mid"][2].copy()
    wrong = np.flatnonzero(edited != truth)
    edited[wrong[: int(len(wrong) * 0.7)]] = truth[wrong[: int(len(wrong) * 0.7)]]  # 오답 70%를 손으로 고침
    sub = submit_files(s["student5"], p1, csv_of(ids, "label", edited), nb5, dump_weights(fitted["rf_mid"][1]), "튜닝 결과")
    backdate(sub, now - timedelta(hours=2))

    # 검토 진행 상황: 상위 일부 처리
    queue = review_services.queue(p1)
    by_user = {r.submission.user_id: r for r in queue}
    if s["student1"].pk in by_user:
        r = by_user[s["student1"].pk]
        review_services.propose(r, ta, "pass", "학습·추론 코드와 5-폴드 교차 검증 결과가 확인되어 적합")
        review_services.decide(r, prof, approve=True)
    if s["student3"].pk in by_user:
        review_services.propose(by_user[s["student3"].pk], ta, "pass", "랜덤 포레스트 학습 로그와 교차 검증 확인")
    if s["student8"].pk in by_user:
        review_services.propose(by_user[s["student8"].pk], ta, "fail", "다른 참여자 제출과 예측값이 사실상 동일")

    # ======================= 프로젝트 2: 스마트폰 행동 인식 =======================
    train, test = har_frames()
    p2, _ = _project(
        comp, prof, P2_TITLE, "classification", "accuracy", 4,
        "딥러닝 미니프로젝트 #2 — 허리에 찬 스마트폰의 가속도·자이로 신호에서 뽑은 특성 561개로 "
        "6가지 행동(WALKING, WALKING_UPSTAIRS, WALKING_DOWNSTAIRS, SITTING, STANDING, LAYING)을 분류합니다.\n"
        "평가 지표: 정확도(Accuracy) · 5-폴드 교차 검증 결과와 평균 출력 필수",
        train, test, "activity", [("마감", now + timedelta(days=5), 5)], "har",
    )
    X, y = train.drop(columns=["id", "activity"]), train["activity"]
    Xte, ids2 = test.drop(columns=["id", "activity"]), test["id"]
    har_models = {
        "logreg": ("from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(max_iter=500)", LogisticRegression(max_iter=500)),
        "svc": ("from sklearn.svm import SVC\nmodel = SVC(C=10)", SVC(C=10)),
        "rf": ("from sklearn.ensemble import RandomForestClassifier\nmodel = RandomForestClassifier(n_estimators=150, random_state=0)",
               RandomForestClassifier(n_estimators=150, random_state=0)),
        "knn": ("from sklearn.neighbors import KNeighborsClassifier\nmodel = KNeighborsClassifier(n_neighbors=7)", KNeighborsClassifier(n_neighbors=7)),
        "et": ("from sklearn.ensemble import ExtraTreesClassifier\nmodel = ExtraTreesClassifier(n_estimators=200, random_state=0)",
               ExtraTreesClassifier(n_estimators=200, random_state=0)),
        "tree": ("from sklearn.tree import DecisionTreeClassifier\nmodel = DecisionTreeClassifier(max_depth=10, random_state=0)",
                 DecisionTreeClassifier(max_depth=10, random_state=0)),
    }
    fitted2 = _fit_all(har_models, X, y, Xte, "accuracy", log, "har", test["activity"].values)
    for i, (key, model_key) in enumerate([("student1", "svc"), ("student2", "rf"), ("student3", "logreg"),
                                          ("student4", "knn"), ("student9", "et")]):
        code, model, pred, scores = fitted2[model_key]
        sub = submit_files(s[key], p2, csv_of(ids2, "activity", pred), make_notebook(code, "activity", cv_log(scores, "accuracy")), dump_weights(model))
        backdate(sub, now - timedelta(hours=40 - i * 6))
    # 교차 검증 출력을 빼먹은 제출 (I-8): 수업 규칙상 결과 처리 제외 대상 → 검토자가 확인
    code, model, pred, _ = fitted2["tree"]
    nb = make_notebook(code, "activity", ["train accuracy 0.9991"], with_cv=False)
    sub = submit_files(s["student10"], p2, csv_of(ids2, "activity", pred), nb, dump_weights(model), "결정 트리 깊이 10")
    backdate(sub, now - timedelta(hours=8))

    # ======================= 프로젝트 3: 킹 카운티 집값 =======================
    train, test = kc_frames()
    p3, _ = _project(
        comp, prof, P3_TITLE, "regression", "rmse", 1,
        "딥러닝 미니프로젝트 #3 — 미국 워싱턴주 킹 카운티 주택의 침실·욕실 수, 면적, 건축 연도, 위치 등으로 "
        "거래 가격(price, 달러)을 예측합니다. 날짜(date)처럼 숫자가 아닌 열은 직접 변환해 써도 됩니다.\n"
        "평가 지표: RMSE (낮을수록 좋음) · 5-폴드 교차 검증 결과와 평균 출력 필수",
        train, test, "price", [("마감", now + timedelta(days=5, hours=12), 5)], "kc_house",
    )
    X, y = train.drop(columns=["id", "price"]).select_dtypes("number"), train["price"]
    Xte, ids3 = test.drop(columns=["id", "price"]).select_dtypes("number"), test["id"]
    kc_models = {
        "ridge": ("from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import StandardScaler\n"
                  "from sklearn.linear_model import Ridge\nmodel = make_pipeline(StandardScaler(), Ridge(alpha=1.0))",
                  make_pipeline(StandardScaler(), Ridge(alpha=1.0))),
        "hgb": ("from sklearn.ensemble import HistGradientBoostingRegressor\nmodel = HistGradientBoostingRegressor(max_iter=300, random_state=0)",
                HistGradientBoostingRegressor(max_iter=300, random_state=0)),
        "rf": ("from sklearn.ensemble import RandomForestRegressor\nmodel = RandomForestRegressor(n_estimators=60, random_state=0, n_jobs=-1)",
               RandomForestRegressor(n_estimators=60, random_state=0, n_jobs=-1)),
        "gbr": ("from sklearn.ensemble import GradientBoostingRegressor\nmodel = GradientBoostingRegressor(n_estimators=150, random_state=0)",
                GradientBoostingRegressor(n_estimators=150, random_state=0)),
        "knn": ("from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import StandardScaler\n"
                "from sklearn.neighbors import KNeighborsRegressor\nmodel = make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=10))",
                make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=10))),
    }
    fitted3 = _fit_all(kc_models, X, y, Xte, "rmse", log, "kc")
    for i, (key, model_key) in enumerate([("student1", "hgb"), ("student2", "ridge"), ("student3", "rf"),
                                          ("student12", "gbr"), ("student13", "knn")]):
        code, model, pred, scores = fitted3[model_key]
        nb = make_notebook(code, "price", cv_log(scores, "rmse"), metric="rmse", numeric_only=True)
        sub = submit_files(s[key], p3, csv_of(ids3, "price", pred), nb, dump_weights(model))
        backdate(sub, now - timedelta(hours=30 - i * 5))
    # 훈련 데이터로 '검증'해 평균을 부풀린 제출 (I-8: 보고값과 실제 점수 차이) — 흔한 데이터 누수 실수
    # 다른 학생과 겹치지 않는 자기 모델 (같은 모델을 쓰면 예측이 똑같아져 I-1 로 잡힘)
    code = ("from sklearn.ensemble import RandomForestRegressor\n"
            "model = RandomForestRegressor(n_estimators=80, min_samples_leaf=2, random_state=7, n_jobs=-1)")
    model = RandomForestRegressor(n_estimators=80, min_samples_leaf=2, random_state=7, n_jobs=-1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(X, y)
        pred = np.round(model.predict(Xte), 4)
        train_rmse = float(np.sqrt(np.mean((model.predict(X) - y) ** 2)))
    leak_scores = [train_rmse * f for f in (0.98, 1.01, 0.99, 1.02, 1.0)]
    nb = make_notebook(code, "price", cv_log(leak_scores, "rmse"), metric="rmse", numeric_only=True)
    sub = submit_files(s["student14"], p3, csv_of(ids3, "price", pred), nb, dump_weights(model), "RMSE 엄청 낮게 나옴!")
    backdate(sub, now - timedelta(hours=6))

    # ======================= 프로젝트 4: 레드 와인 품질 =======================
    train, test = wine_frames()
    p4, _ = _project(
        comp, prof, P4_TITLE, "regression", "rmse", 4,
        "딥러닝 미니프로젝트 #4 — 산도·당도·알코올 등 화학 특성 11개로 레드 와인의 품질 점수(quality, 0~10)를 예측합니다.\n"
        "평가 지표: RMSE (MAE 아님 주의, 낮을수록 좋음) · 5-폴드 교차 검증 결과와 평균 출력 필수",
        train, test, "quality", [("마감", now + timedelta(days=6), 5)], "winequality_red",
    )
    X, y = train.drop(columns=["id", "quality"]), train["quality"]
    Xte, ids4 = test.drop(columns=["id", "quality"]), test["id"]
    wine_models = {
        "rf": ("from sklearn.ensemble import RandomForestRegressor\nmodel = RandomForestRegressor(n_estimators=200, random_state=0)",
               RandomForestRegressor(n_estimators=200, random_state=0)),
        "ridge": ("from sklearn.linear_model import Ridge\nmodel = Ridge(alpha=1.0)", Ridge(alpha=1.0)),
        "hgb": ("from sklearn.ensemble import HistGradientBoostingRegressor\nmodel = HistGradientBoostingRegressor(max_iter=150, random_state=0)",
                HistGradientBoostingRegressor(max_iter=150, random_state=0)),
        "knn": ("from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import StandardScaler\n"
                "from sklearn.neighbors import KNeighborsRegressor\nmodel = make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=15))",
                make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=15))),
        "gbr": ("from sklearn.ensemble import GradientBoostingRegressor\nmodel = GradientBoostingRegressor(random_state=0)",
                GradientBoostingRegressor(random_state=0)),
    }
    fitted4 = _fit_all(wine_models, X, y, Xte, "rmse", log, "wine")
    for i, (key, model_key) in enumerate([("student1", "rf"), ("student2", "hgb"), ("student4", "ridge"),
                                          ("student9", "knn"), ("student11", "gbr")]):
        code, model, pred, scores = fitted4[model_key]
        nb = make_notebook(code, "quality", cv_log(scores, "rmse"), metric="rmse")
        sub = submit_files(s[key], p4, csv_of(ids4, "quality", pred), nb, dump_weights(model))
        backdate(sub, now - timedelta(hours=26 - i * 4))
    return p1, p2, p3, p4


def sandbox_available() -> bool:
    try:
        import docker

        docker.from_env().images.get(settings.SANDBOX_IMAGE)
        return True
    except Exception:
        return False
