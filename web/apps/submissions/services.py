"""
제출 비즈니스 로직

1) start_submission  : '업로드 티켓' 발급 — 서버 시각 기록, 파일 지문(해시) 선언, 횟수 슬롯 예약
2) complete_upload   : 파일 수신 — 해시 대조, 유예 시간 확인, 내용 검증, 저장, 채점 대기열 등록
3) 채점 결과에 따라 grading.services 가 슬롯을 USED(차감) 또는 RELEASED(반환)로 확정

동시성: 같은 사용자의 제출 시작은 Membership 행 잠금(SELECT ... FOR UPDATE)으로 한 번에 하나씩만 처리한다
→ 남은 횟수 1회에서 동시에 10번 눌러도 1건만 예약된다 (경쟁 조건 방지)
"""

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.competitions.models import Deadline, Membership, Project, Role
from apps.core import storage
from apps.core.jobs import enqueue

from . import filecheck
from .models import Submission

HEX64 = re.compile(r"^[0-9a-f]{64}$")
FILE_KINDS = ("csv", "notebook", "weights")


class SubmissionError(Exception):
    """사용자에게 그대로 보여줘도 안전한 메시지. status 는 HTTP 상태 코드"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# 횟수 집계
# ---------------------------------------------------------------------------
def ticket_ttl(project: Project) -> timedelta:
    return timedelta(minutes=project.grace_minutes or settings.DEFAULT_GRACE_MINUTES)


def expire_stale_uploads(project: Project, user=None, now=None) -> int:
    """
    업로드 티켓만 받고 끝내 파일을 올리지 않은 제출은 유예 시간이 지나면 실패 처리하고 슬롯을 돌려준다
    """
    now = now or timezone.now()
    qs = Submission.objects.filter(
        project=project, status=Submission.Status.UPLOADING, started_at__lt=now - ticket_ttl(project)
    )
    if user is not None:
        qs = qs.filter(user=user)
    count = 0
    for sub in qs:
        _fail_upload(sub, "업로드가 유예 시간 안에 완료되지 않았습니다")
        count += 1
    return count


def used_count(user, deadline: Deadline) -> int:
    return Submission.objects.filter(
        user=user, deadline=deadline, slot__in=[Submission.Slot.RESERVED, Submission.Slot.USED]
    ).count()


def quota_for(user, project: Project, now=None) -> dict:
    """
    화면 표시용: 마감일별 사용·남은 횟수 (RFP p.5 '업로드 횟수 및 남은 횟수 표시')
    """
    now = now or timezone.now()
    current = project.deadline_for(now)
    rows = []
    for d in project.deadlines.all():
        used = used_count(user, d)
        rows.append({
            "deadline": d,
            "used": used,
            "remaining": max(d.max_submissions - used, 0),
            "is_current": current is not None and d.pk == current.pk,
            "is_past": d.due_at < now,
        })
    current_row = next((r for r in rows if r["is_current"]), None)
    return {"rows": rows, "current": current_row, "closed": current is None}


# ---------------------------------------------------------------------------
# 1) 업로드 티켓 발급
# ---------------------------------------------------------------------------
def start_submission(user, project: Project, declared: dict, sizes: dict | None = None, request=None) -> Submission:
    declared = {k: str(declared.get(k, "")).lower() for k in FILE_KINDS}
    for value in declared.values():
        if not HEX64.match(value):
            raise SubmissionError("필수 파일 3종(CSV·노트북·가중치)의 지문 정보가 올바르지 않습니다")
    if not project.is_published or not project.is_ready:
        raise SubmissionError("아직 제출을 받지 않는 프로젝트입니다", 403)

    _check_sizes(sizes or {})

    with transaction.atomic():
        # 사용자별 직렬화 잠금
        membership = (
            Membership.objects.select_for_update()
            .filter(user=user, competition=project.competition, role=Role.PARTICIPANT, is_active=True)
            .first()
        )
        if membership is None:
            raise SubmissionError("이 대회의 참여자만 제출할 수 있습니다", 403)

        now = timezone.now()  # 서버 시각만 신뢰
        expire_stale_uploads(project, user, now)
        deadline = project.deadline_for(now)

        if deadline is None:
            # 모든 마감이 지남 → 접수는 하되 채점 제외 (RFP p.4), 횟수와 무관
            sub = Submission.objects.create(
                project=project, user=user, deadline=None, started_at=now,
                declared_hashes=declared, slot=Submission.Slot.NONE,
            )
        else:
            used = used_count(user, deadline)
            if used >= deadline.max_submissions:
                raise SubmissionError(
                    f"'{deadline.title}' 제출 횟수({deadline.max_submissions}회)를 모두 사용했습니다", 409
                )
            sub = Submission.objects.create(
                project=project, user=user, deadline=deadline, started_at=now,
                declared_hashes=declared, slot=Submission.Slot.RESERVED,
            )
        record(
            "submission.started", actor=user, request=request, competition=project.competition, target=sub,
            summary=f"{project.title} 업로드 시작" + (" (마감 후)" if deadline is None else ""),
            data={"deadline": deadline.pk if deadline else None},
        )
    return sub


def _check_sizes(sizes: dict):
    limits = {
        "csv": settings.MAX_CSV_BYTES, "notebook": settings.MAX_NOTEBOOK_BYTES, "weights": settings.MAX_WEIGHTS_BYTES,
    }
    labels = {"csv": "CSV", "notebook": "노트북", "weights": "가중치"}
    for kind, limit in limits.items():
        try:
            size = int(sizes.get(kind, 0))
        except (TypeError, ValueError):
            size = 0
        if size > limit:
            raise SubmissionError(f"{labels[kind]} 파일이 너무 큽니다 (최대 {limit // (1024 * 1024)}MB)")


# ---------------------------------------------------------------------------
# 2) 파일 수신
# ---------------------------------------------------------------------------
def complete_upload(sub: Submission, files: dict, comment: str = "", request=None) -> Submission:
    """
    files: {"csv": UploadedFile, "notebook": UploadedFile, "weights": UploadedFile}
    실패하면 UPLOAD_FAILED + 슬롯 반환 (횟수 미차감) 상태를 저장한 뒤 SubmissionError
    """
    try:
        return _complete_upload(sub, files, comment, request)
    except _Rejected as exc:
        # 검사 트랜잭션은 롤백되었으므로 실패 상태를 별도 트랜잭션으로 저장
        with transaction.atomic():
            fresh = Submission.objects.select_for_update(of=("self",)).select_related("project__competition").get(pk=sub.pk)
            if fresh.status == Submission.Status.UPLOADING:
                _fail_upload(fresh, str(exc))
        raise SubmissionError(str(exc)) from None


def _complete_upload(sub: Submission, files: dict, comment: str, request) -> Submission:
    with transaction.atomic():
        sub = Submission.objects.select_for_update(of=("self",)).select_related("project", "deadline").get(pk=sub.pk)
        if sub.status != Submission.Status.UPLOADING:
            raise SubmissionError("이미 처리된 업로드입니다", 409)

        now = timezone.now()
        project = sub.project

        missing = [k for k in FILE_KINDS if not files.get(k)]
        if missing:
            names = {"csv": "예측 결과(.csv)", "notebook": "소스코드(.ipynb)", "weights": "모델 파라미터"}
            _fail_and_raise(sub, "필수 파일이 누락되었습니다: " + ", ".join(names[m] for m in missing))

        # 유예 시간: 티켓 발급 후 이 시간 안에 업로드가 끝나야 한다
        if now > sub.started_at + ticket_ttl(project):
            _fail_and_raise(sub, f"업로드 시작 후 {project.grace_minutes}분 안에 완료되지 않아 접수할 수 없습니다")

        stored = {}
        try:
            stored["csv"] = _store(files["csv"], ".csv", settings.MAX_CSV_BYTES)
            stored["notebook"] = _store(files["notebook"], ".ipynb", settings.MAX_NOTEBOOK_BYTES)
            stored["weights"] = _store(
                files["weights"], filecheck.suffix_of(files["weights"].name), settings.MAX_WEIGHTS_BYTES
            )

            # 해시 대조: 시작할 때 선언한 파일과 같은 파일인가 (마감 후 바꿔치기 차단)
            for kind in FILE_KINDS:
                if stored[kind].sha256 != sub.declared_hashes.get(kind):
                    raise filecheck.FileCheckError(
                        "업로드 시작 때 선언한 파일과 내용이 다릅니다 (파일이 변경되었거나 손상됨)"
                    )

            root = storage.upload_root()
            filecheck.check_csv(storage.safe_path(root, stored["csv"].name))
            filecheck.check_notebook(storage.safe_path(root, stored["notebook"].name))
            weights_format = filecheck.detect_weights(storage.safe_path(root, stored["weights"].name), files["weights"].name)
        except (filecheck.FileCheckError, storage.FileTooLarge) as exc:
            for s in stored.values():
                storage.delete(storage.upload_root(), s.name)
            message = "파일 크기 제한을 초과했습니다" if isinstance(exc, storage.FileTooLarge) else str(exc)
            _fail_and_raise(sub, message)

        sub.csv_file, sub.csv_name = stored["csv"].name, _display_name(files["csv"].name)
        sub.notebook_file, sub.notebook_name = stored["notebook"].name, _display_name(files["notebook"].name)
        sub.weights_file, sub.weights_name = stored["weights"].name, _display_name(files["weights"].name)
        sub.weights_format = weights_format
        sub.total_bytes = sum(s.size for s in stored.values())
        sub.comment = (comment or "").strip()[:2000]
        sub.uploaded_at = now

        if sub.deadline_id is None:
            sub.status = Submission.Status.LATE
            sub.save()
            record(
                "submission.late_received", actor=sub.user, request=request, competition=project.competition,
                target=sub, summary=f"{project.title} 마감 후 접수 (채점 제외)",
            )
        else:
            sub.status = Submission.Status.QUEUED
            sub.save()
            record(
                "submission.uploaded", actor=sub.user, request=request, competition=project.competition,
                target=sub, summary=f"{project.title} 업로드 완료, 채점 대기",
                data={"bytes": sub.total_bytes, "after_deadline": now > sub.deadline.due_at},
            )
            from apps.grading.services import grade_submission

            enqueue("grading", grade_submission, str(sub.pk))
    return sub


def _display_name(name: str) -> str:
    # 표시용 원래 이름: 경로 부분 제거, 길이 제한
    return (name or "").replace("\\", "/").split("/")[-1][:200]


def _store(uploaded, suffix: str, max_bytes: int):
    return storage.save_upload(uploaded, storage.upload_root(), suffix, max_bytes)


def _fail_upload(sub: Submission, message: str):
    sub.status = Submission.Status.UPLOAD_FAILED
    if sub.slot == Submission.Slot.RESERVED:
        sub.slot = Submission.Slot.RELEASED
    sub.errors = [{"code": "upload", "message": message}]
    sub.save(update_fields=["status", "slot", "errors"])
    record(
        "submission.upload_failed", actor=sub.user, competition=sub.project.competition, target=sub,
        summary=message[:200],
    )


def _fail_and_raise(sub: Submission, message: str):
    raise _Rejected(message)


class _Rejected(SubmissionError):
    """업로드 거부 (내부용)"""


def visible_submissions_for(user, project: Project):
    return Submission.objects.filter(project=project, user=user).order_by("-started_at")
