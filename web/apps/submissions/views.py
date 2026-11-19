"""
제출 화면·API

업로드는 2단계 (브라우저 JS 가 처리)
  1) POST /p/<id>/submit/start/  : 파일 지문(SHA-256)·크기 선언 → 업로드 티켓(제출 ID) 발급, 시작 시각 서버 기록
  2) POST /s/<id>/upload/        : 실제 파일 전송 → 해시 대조·내용 검증 → 채점 대기열
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.competitions.models import Project
from apps.core import permissions, storage
from apps.core.context import comp_context

from .models import Submission
from .services import SubmissionError, complete_upload, quota_for, start_submission


def _json_error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@login_required
@require_POST
def submit_start(request, pk):
    project = Project.objects.select_related("competition").filter(pk=pk).first()
    if project is None or not permissions.can_submit(request.user, project.competition):
        return _json_error("제출 권한이 없습니다", 404)
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _json_error("잘못된 요청입니다")
    try:
        sub = start_submission(request.user, project, payload.get("hashes", {}), payload.get("sizes", {}), request)
    except SubmissionError as exc:
        return _json_error(str(exc), exc.status)
    return JsonResponse({
        "ok": True,
        "id": str(sub.pk),
        "late": sub.deadline_id is None,
        "upload_url": reverse("submissions:upload", args=[sub.pk]),
        "started_at": sub.started_at.isoformat(),
    })


def _own_submission(request, pk) -> Submission:
    sub = Submission.objects.select_related("project__competition", "deadline").filter(pk=pk).first()
    if sub is None:
        raise Http404
    if sub.user_id != request.user.pk and not permissions.can_manage_competition(request.user, sub.project.competition):
        raise Http404
    return sub


@login_required
@require_POST
def submit_upload(request, pk):
    sub = Submission.objects.select_related("project__competition").filter(pk=pk, user=request.user).first()
    if sub is None:
        return _json_error("업로드 정보를 찾을 수 없습니다", 404)
    files = {k: request.FILES.get(k) for k in ("csv", "notebook", "weights")}
    try:
        sub = complete_upload(sub, files, request.POST.get("comment", ""), request)
    except SubmissionError as exc:
        return _json_error(str(exc), exc.status)
    sub.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "status": sub.status,
        "status_url": reverse("submissions:status", args=[sub.pk]),
        "detail_url": reverse("submissions:detail", args=[sub.pk]),
    })


@login_required
def submission_status(request, pk):
    """HTMX 폴링용 상태 조각"""
    sub = _own_submission(request, pk)
    quota = quota_for(sub.user, sub.project)
    rank = None
    if sub.status == Submission.Status.GRADED:
        from apps.leaderboard.services import my_row, standings

        rank = my_row(standings(sub.project), sub.user)
    final = sub.status not in (Submission.Status.UPLOADING, Submission.Status.QUEUED, Submission.Status.GRADING)
    return render(request, "submissions/_status.html",
                  {"sub": sub, "project": sub.project, "quota": quota, "rank": rank, "final": final})


@login_required
def submission_detail(request, pk):
    sub = _own_submission(request, pk)
    comp = sub.project.competition
    ctx = comp_context(request, comp, sub=sub, project=sub.project)
    review = getattr(sub, "review", None) if hasattr(sub, "review") else None
    # 참여자에게는 판정 '결과'만, 관리자 메모는 관리자에게만
    ctx["review"] = review
    ctx["is_owner"] = sub.user_id == request.user.pk
    return render(request, "submissions/detail.html", ctx)


@login_required
def submission_download(request, pk, kind):
    sub = _own_submission(request, pk)
    mapping = {
        "csv": (sub.csv_file, sub.csv_name),
        "notebook": (sub.notebook_file, sub.notebook_name),
        "weights": (sub.weights_file, sub.weights_name),
    }
    if kind not in mapping or not mapping[kind][0]:
        raise Http404
    stored, name = mapping[kind]
    path = storage.safe_path(storage.upload_root(), stored)
    from apps.audit.services import record

    if sub.user_id != request.user.pk:
        record("submission.file_viewed", request=request, competition=sub.project.competition, target=sub,
               summary=f"{sub.user.name} 제출물 다운로드 ({kind})")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name or f"{kind}.bin",  # noqa: SIM115
                        content_type="application/octet-stream")
