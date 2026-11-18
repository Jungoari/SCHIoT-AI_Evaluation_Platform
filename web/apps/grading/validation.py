"""
CSV 읽기 · 규격 자동 추론 · 제출 CSV 형식 검사

원칙
- 모든 값을 문자열로 읽는다 (pandas 자동 형 변환 때문에 '007' → 7 처럼 바뀌는 오판 방지)
- 오류는 첫 번째에서 멈추지 않고 모아서 보고한다 (최대 MAX_ERRORS 개)
- 오류 메시지에 정답 값은 절대 포함하지 않는다
"""

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

MAX_ERRORS = 20
MAX_ROWS = 2_000_000

ID_CANDIDATES = ("id", "ID", "Id", "index", "row_id", "sample_id", "PassengerId")
TARGET_CANDIDATES = ("label", "target", "y", "class", "answer", "species", "prediction", "price", "Survived")


class CsvReadError(Exception):
    """사용자에게 보여줘도 안전한 메시지"""


def read_csv(path: Path, max_bytes_check: bool = True) -> pd.DataFrame:
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if b"\x00" in head:
        raise CsvReadError("CSV 파일이 아닙니다 (바이너리 데이터가 포함되어 있음)")
    try:
        df = pd.read_csv(
            path, dtype=str, keep_default_na=False, encoding="utf-8-sig", nrows=MAX_ROWS + 1, skipinitialspace=False
        )
    except UnicodeDecodeError:
        raise CsvReadError("UTF-8 인코딩이 아닙니다. CSV를 UTF-8로 저장해 주세요") from None
    except pd.errors.EmptyDataError:
        raise CsvReadError("빈 파일입니다") from None
    except pd.errors.ParserError as exc:
        raise CsvReadError(f"CSV 형식을 해석할 수 없습니다 ({str(exc).splitlines()[0][:120]})") from None
    if len(df) > MAX_ROWS:
        raise CsvReadError(f"행이 너무 많습니다 (최대 {MAX_ROWS:,}행)")
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# 규격 자동 추론 (관리자2가 정답 포함 테스트셋을 올리면 호출)
# ---------------------------------------------------------------------------
@dataclass
class InferredSchema:
    columns: list[str]
    id_column: str
    target_column: str
    task_type: str
    allowed_labels: list[str] = field(default_factory=list)
    row_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _is_numeric(series: pd.Series) -> bool:
    try:
        pd.to_numeric(series)
        return True
    except (ValueError, TypeError):
        return False


def infer_schema(df: pd.DataFrame) -> InferredSchema:
    cols = list(df.columns)
    warnings = []
    if len(cols) < 2:
        raise CsvReadError("열이 2개 이상이어야 합니다 (ID 열 + 정답 열)")

    id_col = next((c for c in ID_CANDIDATES if c in cols and df[c].is_unique), None)
    if id_col is None:
        id_col = next((c for c in cols if df[c].is_unique), cols[0])
        warnings.append(f"ID 열 이름을 찾지 못해 '{id_col}' 열을 ID로 추정했습니다. 맞는지 확인해 주세요")

    target_col = next((c for c in TARGET_CANDIDATES if c in cols and c != id_col), None)
    if target_col is None:
        target_col = next(c for c in reversed(cols) if c != id_col)
        warnings.append(f"정답 열 이름을 찾지 못해 마지막 열 '{target_col}'을 정답으로 추정했습니다")

    return _finish_schema(df, cols, id_col, target_col, warnings)


def schema_for(df: pd.DataFrame, id_col: str, target_col: str, task_type: str | None = None) -> InferredSchema:
    cols = list(df.columns)
    if id_col not in cols or target_col not in cols or id_col == target_col:
        raise CsvReadError("ID 열과 정답 열을 서로 다른 열로 선택해 주세요")
    if not df[id_col].is_unique:
        raise CsvReadError(f"ID 열 '{id_col}'에 중복 값이 있습니다")
    return _finish_schema(df, cols, id_col, target_col, [], task_type)


def _finish_schema(df, cols, id_col, target_col, warnings, task_type=None) -> InferredSchema:
    target = df[target_col]
    if (target == "").any():
        raise CsvReadError(f"정답 열 '{target_col}'에 빈 값이 있습니다")
    if task_type is None:
        numeric = _is_numeric(target)
        task_type = "regression" if numeric and target.nunique() > 20 else "classification"
    labels = []
    if task_type == "classification":
        labels = sorted(target.unique().tolist())
        if len(labels) > 200:
            warnings.append("레이블 종류가 200개를 넘습니다. 회귀 문제가 아닌지 확인해 주세요")
    elif not _is_numeric(target):
        raise CsvReadError(f"회귀 문제인데 정답 열 '{target_col}'에 숫자가 아닌 값이 있습니다")
    return InferredSchema(
        columns=cols, id_column=id_col, target_column=target_col, task_type=task_type,
        allowed_labels=labels, row_count=len(df), warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 제출 CSV 검사
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    errors: list[dict]
    predictions: pd.Series | None = None  # ID 순서로 정렬된 예측값 (정답과 같은 순서)

    @property
    def ok(self) -> bool:
        return not self.errors


class _Collector:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, code: str, message: str):
        if len(self.items) < MAX_ERRORS:
            self.items.append({"code": code, "message": message})

    @property
    def full(self):
        return len(self.items) >= MAX_ERRORS


def _sample(values, n=5) -> str:
    values = list(values)
    shown = ", ".join(str(v)[:30] for v in values[:n])
    return shown + (f" 외 {len(values) - n}개" if len(values) > n else "")


def validate_submission(df: pd.DataFrame, project, expected_ids: pd.Index) -> ValidationResult:
    """
    df            : 제출 CSV (문자열로 읽은 것)
    project       : id_column / target_column / task_type / allowed_labels / row_count
    expected_ids  : 정답 파일의 ID 순서
    """
    err = _Collector()
    id_col, target_col = project.id_column, project.target_column

    # 1) 헤더
    cols = list(df.columns)
    missing_cols = [c for c in (id_col, target_col) if c not in cols]
    extra_cols = [c for c in cols if c not in (id_col, target_col)]
    if missing_cols:
        err.add("header_missing", f"필수 열이 없습니다: {', '.join(missing_cols)} (필요한 열: {id_col}, {target_col})")
    if extra_cols:
        err.add("header_extra", f"허용되지 않은 열이 있습니다: {_sample(extra_cols)} (필요한 열: {id_col}, {target_col})")
    if missing_cols:
        return ValidationResult(err.items)

    # 2) 행 수
    if len(df) != len(expected_ids):
        err.add("row_count", f"행 수가 맞지 않습니다: 제출 {len(df):,}행 / 필요 {len(expected_ids):,}행")

    # 3) ID 중복·누락·여분
    ids = df[id_col]
    dup = ids[ids.duplicated()].unique()
    if len(dup):
        err.add("id_duplicate", f"중복된 ID가 있습니다: {_sample(dup)}")
    expected_set = set(expected_ids)
    got_set = set(ids)
    missing = [i for i in expected_ids if i not in got_set]
    extra = sorted(got_set - expected_set)
    if missing:
        err.add("id_missing", f"누락된 ID가 있습니다: {_sample(missing)}")
    if extra:
        err.add("id_extra", f"정답에 없는 ID가 있습니다: {_sample(extra)}")

    # 4) 값 검사 (행 번호는 헤더를 1행으로 볼 때의 엑셀 기준 번호)
    values = df[target_col]
    empty_rows = [i + 2 for i in values.index[values.str.strip() == ""]]
    if empty_rows:
        err.add("value_empty", f"예측값이 비어 있는 행: {_sample(empty_rows)}행")

    if project.task_type == "classification":
        allowed = set(project.allowed_labels)
        bad = values[(values.str.strip() != "") & ~values.isin(allowed)]
        for idx, val in bad.head(MAX_ERRORS).items():
            if err.full:
                break
            err.add("value_label", f"{idx + 2}행: '{str(val)[:30]}'은(는) 허용된 레이블이 아닙니다 (허용: {_sample(sorted(allowed), 8)})")
    else:
        numeric = pd.to_numeric(values, errors="coerce")
        bad_idx = numeric.index[numeric.isna() & (values.str.strip() != "")]
        for idx in bad_idx[:MAX_ERRORS]:
            if err.full:
                break
            err.add("value_number", f"{idx + 2}행: '{str(values[idx])[:30]}'은(는) 숫자가 아닙니다")
        inf_idx = numeric.index[numeric.apply(lambda v: isinstance(v, float) and math.isinf(v))]
        if len(inf_idx):
            err.add("value_inf", f"무한대 값이 있는 행: {_sample([i + 2 for i in inf_idx])}행")

    if err.items:
        return ValidationResult(err.items)

    preds = df.set_index(id_col)[target_col].reindex(expected_ids)
    return ValidationResult([], preds)


def prediction_hash(predictions: pd.Series) -> str:
    """ID 순서로 정렬된 예측값의 지문 — 완전 중복 제출 탐지(I-1)에 사용"""
    text = "\n".join(str(v).strip() for v in predictions.tolist())
    return hashlib.sha256(text.encode()).hexdigest()
