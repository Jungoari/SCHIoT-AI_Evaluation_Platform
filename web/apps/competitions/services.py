"""
대회·프로젝트 설정 서비스 (관리자2)

테스트셋 처리 흐름 (F-13, F-16)
  1) 관리자2가 '정답 포함 테스트셋 CSV'를 올린다 → 정답 저장소(LABEL_ROOT)에 UUID 이름으로 저장
  2) 시스템이 ID 열·정답 열·문제 유형·허용 레이블·행 수를 자동 추론 → 관리자는 확인만
  3) 확정하면 참여자 배포용 파일을 자동 생성
       - 테스트 특성 CSV : 정답 열을 제거한 파일  (RFP p.2 "추론을 위한 특성만 공유")
       - 샘플 제출 CSV   : ID + 예시 예측값
       - 템플릿 노트북   : 재현 검증(I-6)을 위한 inference 셀 포함
  정답 파일은 참여자 배포 경로와 물리적으로 분리되어 있어 실수로 배포될 수 없다.
"""

import io
import json

import nbformat
from django.db import transaction

from apps.audit.services import record
from apps.core import storage
from apps.grading.metrics import get_metric
from apps.grading.validation import CsvReadError, infer_schema, read_csv, schema_for
from apps.submissions import filecheck
from apps.submissions.models import Submission

from .models import Competition, JoinCode, Project, ProjectFile, Role


class SetupError(Exception):
    """사용자에게 보여줘도 안전한 메시지"""


# ---------------------------------------------------------------------------
# 대회·코드
# ---------------------------------------------------------------------------
def create_competition(user, title: str, description: str, request=None):
    with transaction.atomic():
        comp = Competition.objects.create(title=title, description=description, created_by=user)
        _, p_code = JoinCode.issue(comp, Role.PARTICIPANT, user)
        _, a_code = JoinCode.issue(comp, Role.ADMIN1, user)
        record("competition.created", actor=user, request=request, competition=comp, target=comp,
               summary=f"대회 개설: {title}")
    return comp, {"participant": p_code, "admin1": a_code}


def reissue_code(comp: Competition, role: str, user, request=None) -> str:
    with transaction.atomic():
        _, raw = JoinCode.issue(comp, role, user)
        record("joincode.reissued", actor=user, request=request, competition=comp,
               summary=f"{Role(role).label} 참여 코드 재발급 (기존 코드 무효화)", data={"role": role})
    return raw


# ---------------------------------------------------------------------------
# 테스트셋 · 규격
# ---------------------------------------------------------------------------
def upload_testset(project: Project, uploaded, actor, request=None):
    """정답 포함 테스트셋 저장 + 규격 자동 추론 (아직 확정 전)"""
    if filecheck.suffix_of(uploaded.name) != ".csv":
        raise SetupError("CSV 파일만 올릴 수 있습니다")
    stored = storage.save_upload(uploaded, storage.label_root(), ".csv", max_bytes=200 * 1024 * 1024)
    try:
        df = read_csv(storage.safe_path(storage.label_root(), stored.name))
        schema = infer_schema(df)
    except CsvReadError as exc:
        storage.delete(storage.label_root(), stored.name)
        raise SetupError(str(exc)) from None

    with transaction.atomic():
        old = project.label_file
        project.label_file = stored.name
        project.label_sha256 = stored.sha256
        project.id_column = ""  # 확정 전까지 비움 → is_ready=False
        project.target_column = ""
        project.save()
        record("project.testset_uploaded", actor=actor, request=request, competition=project.competition,
               target=project, summary=f"{project.title} 테스트셋 업로드 ({schema.row_count}행)",
               data={"sha256": stored.sha256, "rows": schema.row_count, "replaced": bool(old)})
    if old:
        storage.delete(storage.label_root(), old)
    return schema


def current_testset(project: Project):
    if not project.label_file:
        return None
    return read_csv(storage.safe_path(storage.label_root(), project.label_file))


def confirm_schema(project: Project, id_col: str, target_col: str, task_type: str, actor, request=None):
    """규격 확정 → 배포 파일 생성. 이미 제출이 있으면 전체 재채점"""
    df = current_testset(project)
    if df is None:
        raise SetupError("먼저 테스트셋을 올려 주세요")
    try:
        schema = schema_for(df, id_col, target_col, task_type)
    except CsvReadError as exc:
        raise SetupError(str(exc)) from None

    metric = get_metric(project.metric)
    if metric.task != schema.task_type:
        raise SetupError(
            f"평가 지표 '{metric.label}'는 {'분류' if metric.task == 'classification' else '회귀'} 문제용입니다. "
            "프로젝트 설정에서 지표를 먼저 바꿔 주세요"
        )

    with transaction.atomic():
        project.id_column = schema.id_column
        project.target_column = schema.target_column
        project.task_type = schema.task_type
        project.allowed_labels = schema.allowed_labels
        project.row_count = schema.row_count
        project.save()

        features = df.drop(columns=[schema.target_column])
        _replace_generated(project, ProjectFile.Kind.TEST_FEATURES, f"{_slug(project)}_test_features.csv",
                           features.to_csv(index=False).encode())

        sample_value = schema.allowed_labels[0] if schema.allowed_labels else "0.0"
        sample = df[[schema.id_column]].copy()
        sample[schema.target_column] = sample_value
        _replace_generated(project, ProjectFile.Kind.SAMPLE_SUBMISSION, f"{_slug(project)}_sample_submission.csv",
                           sample.to_csv(index=False).encode())

        if not project.files.filter(kind=ProjectFile.Kind.TEMPLATE_NOTEBOOK).exists():
            _replace_generated(project, ProjectFile.Kind.TEMPLATE_NOTEBOOK, f"{_slug(project)}_template.ipynb",
                               template_notebook(project).encode())

        record("project.schema_confirmed", actor=actor, request=request, competition=project.competition,
               target=project, summary=f"{project.title} 규격 확정 및 배포 파일 생성",
               data={"id": schema.id_column, "target": schema.target_column, "task": schema.task_type,
                     "labels": schema.allowed_labels[:50], "rows": schema.row_count})

    if Submission.objects.filter(project=project).exclude(deadline=None).exists():
        from apps.grading.services import regrade_project

        regrade_project(project, actor=actor, request=request)
    return schema


def _slug(project: Project) -> str:
    return f"project{project.pk}"


def _replace_generated(project: Project, kind: str, filename: str, data: bytes):
    for old in project.files.filter(kind=kind):
        storage.delete(storage.upload_root(), old.stored_name)
        old.delete()
    stored = storage.save_bytes(data, storage.upload_root(), filecheck.suffix_of(filename))
    return ProjectFile.objects.create(project=project, kind=kind, original_name=filename,
                                      stored_name=stored.name, size=stored.size, sha256=stored.sha256)


ALLOWED_EXTRA = {".csv", ".ipynb", ".zip", ".txt", ".md", ".pdf", ".json"}


def add_project_file(project: Project, kind: str, uploaded, actor, request=None) -> ProjectFile:
    ext = filecheck.suffix_of(uploaded.name)
    if kind == ProjectFile.Kind.TRAIN and ext != ".csv":
        raise SetupError("학습 데이터는 CSV 파일이어야 합니다")
    if kind == ProjectFile.Kind.TEMPLATE_NOTEBOOK and ext != ".ipynb":
        raise SetupError("템플릿 노트북은 .ipynb 파일이어야 합니다")
    if ext not in ALLOWED_EXTRA:
        raise SetupError("허용되지 않는 파일 형식입니다")
    stored = storage.save_upload(uploaded, storage.upload_root(), ext, max_bytes=500 * 1024 * 1024)
    path = storage.safe_path(storage.upload_root(), stored.name)
    try:
        if ext == ".csv":
            filecheck.check_csv(path)
            # 학습 데이터에 테스트 ID가 섞여 있으면 경고 대신 거부하지는 않음 (교육용 데이터 특성상)
        elif ext == ".ipynb":
            filecheck.check_notebook(path)
    except filecheck.FileCheckError as exc:
        storage.delete(storage.upload_root(), stored.name)
        raise SetupError(str(exc)) from None

    with transaction.atomic():
        if kind in (ProjectFile.Kind.TRAIN, ProjectFile.Kind.TEMPLATE_NOTEBOOK):
            for old in project.files.filter(kind=kind):
                storage.delete(storage.upload_root(), old.stored_name)
                old.delete()
        pf = ProjectFile.objects.create(project=project, kind=kind, original_name=uploaded.name[:200],
                                        stored_name=stored.name, size=stored.size, sha256=stored.sha256)
        record("project.file_added", actor=actor, request=request, competition=project.competition,
               target=project, summary=f"{project.title} 배포 파일 추가: {pf.get_kind_display()}")
    return pf


# ---------------------------------------------------------------------------
# 템플릿 노트북 — 재현 검증(I-6)을 쉽게 만드는 약속
# ---------------------------------------------------------------------------
def template_notebook(project: Project) -> str:
    """
    참여자용 시작 노트북. 핵심 약속:
      - inference 태그가 붙은 셀은 '가중치 파일만으로' 예측 CSV를 만들 수 있어야 한다
      - 경로는 환경 변수(TEST_FEATURES_PATH, WEIGHTS_PATH, OUTPUT_PATH)로 받는다
    이 약속 덕분에 검증 시 학습을 다시 하지 않고 추론만 재실행해 시간을 크게 줄인다 (RFP p.8)
    """
    is_clf = project.task_type == "classification"
    model = "RandomForestClassifier" if is_clf else "RandomForestRegressor"
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.cells = [
        nbformat.v4.new_markdown_cell(
            f"# {project.title} — 제출 템플릿\n\n"
            "1. 학습 셀에서 모델을 학습하고 **가중치 파일**을 저장합니다\n"
            "2. `inference` 태그가 붙은 마지막 셀은 **가중치 파일만으로** 예측 CSV를 만들어야 합니다\n"
            "   (관리자 검증 시 이 셀만 격리 환경에서 다시 실행해 제출 CSV와 비교합니다)\n"
            "3. 제출물: 예측 CSV + 이 노트북(.ipynb) + 가중치 파일"
        ),
        nbformat.v4.new_code_cell(
            "import os\nimport pandas as pd\nimport joblib\n"
            f"from sklearn.ensemble import {model}\n\n"
            f"ID_COL = {project.id_column!r}\nTARGET_COL = {project.target_column!r}",
            metadata={"tags": ["setup"]},
        ),
        nbformat.v4.new_code_cell(
            "# 학습 (자유롭게 수정)\n"
            "train = pd.read_csv('train.csv')\n"
            "X = train.drop(columns=[ID_COL, TARGET_COL], errors='ignore')\n"
            "y = train[TARGET_COL]\n"
            f"model = {model}(random_state=42)\n"
            "model.fit(X, y)\n"
            "print('train score:', model.score(X, y))\n"
            "joblib.dump(model, 'model.joblib')"
        ),
        nbformat.v4.new_code_cell(
            "# 추론 — 가중치 파일만으로 예측 CSV 생성 (경로는 환경 변수로 바뀔 수 있음)\n"
            "TEST_FEATURES_PATH = os.environ.get('TEST_FEATURES_PATH', 'test_features.csv')\n"
            "WEIGHTS_PATH = os.environ.get('WEIGHTS_PATH', 'model.joblib')\n"
            "OUTPUT_PATH = os.environ.get('OUTPUT_PATH', 'submission.csv')\n\n"
            "test = pd.read_csv(TEST_FEATURES_PATH)\n"
            "model = joblib.load(WEIGHTS_PATH)\n"
            "pred = model.predict(test.drop(columns=[ID_COL]))\n"
            "pd.DataFrame({ID_COL: test[ID_COL], TARGET_COL: pred}).to_csv(OUTPUT_PATH, index=False)\n"
            "print('saved', OUTPUT_PATH)",
            metadata={"tags": ["inference"]},
        ),
    ]
    buf = io.StringIO()
    nbformat.write(nb, buf)
    return buf.getvalue()


def project_summary(project: Project) -> dict:
    """설정 화면 체크리스트"""
    return {
        "testset": bool(project.label_file),
        "schema": bool(project.id_column and project.target_column),
        "deadlines": project.deadlines.exists(),
        "train": project.files.filter(kind=ProjectFile.Kind.TRAIN).exists(),
        "published": project.is_published,
    }


def labels_preview(project: Project) -> str:
    return json.dumps(project.allowed_labels[:20], ensure_ascii=False)
