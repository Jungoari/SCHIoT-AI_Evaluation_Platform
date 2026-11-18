"""
채점 서비스 (채점 워커에서 실행 — 정답 접근 O, 참여자 코드 실행 X)

grade_submission 흐름
    QUEUED → GRADING → (형식 검사) → GRADED (슬롯 USED = 1회 차감)
                                  └→ INVALID (슬롯 RELEASED = 차감 없음)
    예외 발생 시 최대 3회까지 재시도 → 그래도 실패하면 FAILED (차감 없음)

제출 CSV 는 '데이터'로만 파싱한다. 어떤 코드도 실행하지 않는다.
"""

import logging
import time
from datetime import timedelta

import pandas as pd
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core import storage
from apps.submissions.models import Submission

from .metrics import get_metric
from .validation import CsvReadError, prediction_hash, read_csv, validate_submission

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def load_labels(project) -> pd.Series:
    """정답: ID → 정답값 (정답 파일의 행 순서 유지)"""
    df = read_csv(storage.safe_path(storage.label_root(), project.label_file))
    return df.set_index(project.id_column)[project.target_column]


def compute_score(project, y_true: pd.Series, y_pred: pd.Series) -> float:
    metric = get_metric(project.metric)
    if project.task_type == "regression":
        return metric.compute(pd.to_numeric(y_true).to_numpy(), pd.to_numeric(y_pred).to_numpy())
    return metric.compute(y_true.str.strip().to_numpy(), y_pred.str.strip().to_numpy())


def grade_submission(submission_id: str, sleep=time.sleep) -> None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _grade_once(submission_id)
            return
        except Exception:
            logger.exception("채점 실패 (시도 %s/%s) submission=%s", attempt, MAX_ATTEMPTS, submission_id)
            Submission.objects.filter(pk=submission_id).update(retry_count=attempt)
            if attempt < MAX_ATTEMPTS:
                sleep(2 * attempt)
    _mark_system_failure(submission_id)


def _grade_once(submission_id: str) -> None:
    with transaction.atomic():
        sub = (
            Submission.objects.select_for_update(of=("self",))
            .select_related("project", "project__competition", "user")
            .filter(pk=submission_id)
            .first()
        )
        if sub is None or sub.status not in (Submission.Status.QUEUED, Submission.Status.GRADING):
            return  # 이미 처리됨 (중복 실행 방지)
        sub.status = Submission.Status.GRADING
        sub.save(update_fields=["status"])

        project = sub.project
        labels = load_labels(project)
        try:
            df = read_csv(storage.safe_path(storage.upload_root(), sub.csv_file))
        except CsvReadError as exc:
            _mark_invalid(sub, [{"code": "read", "message": str(exc)}])
            return

        result = validate_submission(df, project, labels.index)
        if not result.ok:
            _mark_invalid(sub, result.errors)
            return

        score = compute_score(project, labels, result.predictions)
        sub.score = score
        sub.prediction_hash = prediction_hash(result.predictions)
        sub.status = Submission.Status.GRADED
        sub.slot = Submission.Slot.USED  # 정상 채점 성공 → 1회 차감 (RFP p.5)
        sub.graded_at = timezone.now()
        sub.errors = []
        sub.save()
        record(
            "submission.graded", actor=None, competition=project.competition, target=sub,
            summary=f"{sub.user.name} / {project.title} 채점 완료: {score:.{project.decimals}f}",
            data={"score": score, "metric": project.metric},
        )

    # 채점 결과와 별개로 빠른 무결성 검사 (실패해도 점수에는 영향 없음)
    try:
        from apps.integrity.services import run_quick_checks

        run_quick_checks(sub, labels=labels, predictions=result.predictions)
    except Exception:
        logger.exception("무결성 검사 실패 submission=%s", submission_id)


def _mark_invalid(sub: Submission, errors: list[dict]) -> None:
    sub.status = Submission.Status.INVALID
    sub.slot = Submission.Slot.RELEASED  # 형식·규격 오류 → 미차감 (RFP p.5)
    sub.errors = errors
    sub.graded_at = timezone.now()
    sub.save()
    record(
        "submission.invalid", actor=None, competition=sub.project.competition, target=sub,
        summary=f"{sub.user.name} / {sub.project.title} 형식 오류 {len(errors)}건 (횟수 미차감)",
    )


def _mark_system_failure(submission_id: str) -> None:
    with transaction.atomic():
        sub = Submission.objects.select_for_update(of=("self",)).select_related("project__competition", "user").get(
            pk=submission_id
        )
        if sub.status not in (Submission.Status.QUEUED, Submission.Status.GRADING):
            return
        sub.status = Submission.Status.FAILED
        if sub.slot == Submission.Slot.RESERVED:
            sub.slot = Submission.Slot.RELEASED  # 서버·채점 시스템 오류 → 미차감 (RFP p.5)
        sub.errors = [{"code": "system", "message": "채점 시스템 오류가 발생했습니다. 제출 횟수는 차감되지 않았습니다"}]
        sub.save()
        record(
            "submission.system_error", actor=None, competition=sub.project.competition, target=sub,
            summary=f"{sub.user.name} / {sub.project.title} 시스템 오류 (횟수 미차감)",
        )


def recover_stuck(older_than_minutes: int = 10) -> int:
    """
    워커가 죽어 QUEUED/GRADING 에 멈춘 제출을 다시 대기열에 넣는다 (장애 복구)
    """
    from apps.core.jobs import enqueue

    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    stuck = Submission.objects.filter(
        status__in=[Submission.Status.QUEUED, Submission.Status.GRADING], uploaded_at__lt=cutoff
    )
    count = 0
    for sub in stuck:
        Submission.objects.filter(pk=sub.pk).update(status=Submission.Status.QUEUED)
        enqueue("grading", grade_submission, str(sub.pk))
        count += 1
    return count


def regrade_project(project, actor=None, request=None) -> int:
    """
    정답 교체 등으로 전체 재채점 (F-34). 형식 오류였던 제출도 다시 검사한다.
    재채점 중에는 슬롯을 RESERVED 로 되돌려 결과에 따라 다시 확정한다.
    """
    from apps.core.jobs import enqueue

    targets = Submission.objects.filter(
        project=project,
        status__in=[Submission.Status.GRADED, Submission.Status.INVALID, Submission.Status.FAILED],
    ).exclude(deadline=None)
    ids = list(targets.values_list("pk", flat=True))
    with transaction.atomic():
        for sub in Submission.objects.select_for_update().filter(pk__in=ids):
            sub.status = Submission.Status.QUEUED
            # 부적합 판정으로 '차감 유지' 중인 기록은 계속 USED
            if sub.slot == Submission.Slot.RELEASED:
                sub.slot = Submission.Slot.RESERVED
            sub.save(update_fields=["status", "slot"])
        record(
            "project.regraded", actor=actor, request=request, competition=project.competition, target=project,
            summary=f"{project.title} 전체 재채점 {len(ids)}건", data={"count": len(ids)},
        )
        for pk in ids:
            enqueue("grading", grade_submission, str(pk))
    return len(ids)
