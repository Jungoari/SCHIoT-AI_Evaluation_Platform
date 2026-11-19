import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import escape
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.competitions.models import Project
from apps.core import permissions, storage
from apps.core.context import comp_context
from apps.integrity.models import IntegrityReport

from . import services
from .models import Review
from .notebook import NOTEBOOK_CSP, NOTEBOOK_STYLE, render_notebook

REASON_TEMPLATES = [
    "학습·추론 코드와 측정치 로그가 확인되어 적합",
    "노트북에 CSV 생성 과정이 없음",
    "다른 참여자 제출과 예측값이 사실상 동일",
    "제출한 모델로 다시 실행한 결과가 제출 CSV와 다름",
    "예측값을 코드에 직접 기입한 흔적",
]


def _project(request, pk, check=permissions.can_propose_verdict) -> Project:
    project = Project.objects.select_related("competition").filter(pk=pk).first()
    if project is None or not check(request.user, project.competition):
        raise Http404
    return project


def _review(request, pk) -> Review:
    review = Review.objects.select_related("submission__project__competition", "submission__user").filter(pk=pk).first()
    if review is None or not permissions.can_propose_verdict(request.user, review.submission.project.competition):
        raise Http404
    return review


@login_required
def review_queue(request, pk):
    project = _project(request, pk)
    reviews = services.queue(project)
    state = request.GET.get("state", "")
    if state:
        reviews = [r for r in reviews if r.state == state]
    counts = {s: 0 for s in Review.State.values}
    for r in services.queue(project) if state else reviews:
        counts[r.state] += 1
    ctx = comp_context(request, project.competition, project=project, reviews=reviews, counts=counts, state=state,
                       can_approve=permissions.can_approve(request.user, project.competition))
    return render(request, "review/queue.html", ctx)


@login_required
def review_detail(request, pk):
    review = _review(request, pk)
    sub = review.submission
    project = sub.project
    report = IntegrityReport.objects.filter(submission=sub).first()
    queue = services.queue(project)
    ids = [r.pk for r in queue]
    idx = ids.index(review.pk) if review.pk in ids else -1
    ctx = comp_context(
        request, project.competition, project=project, review=review, sub=sub, report=report,
        reasons=REASON_TEMPLATES, can_approve=permissions.can_approve(request.user, project.competition),
        prev_id=ids[idx - 1] if idx > 0 else None, next_id=ids[idx + 1] if 0 <= idx < len(ids) - 1 else None,
        position=idx + 1, total=len(ids), is_candidate=idx >= 0,
        history=sub.user.submissions.filter(project=project).select_related("review").order_by("-started_at")[:20],
    )
    return render(request, "review/detail.html", ctx)


@login_required
@require_POST
def review_propose(request, pk):
    review = _review(request, pk)
    try:
        services.propose(review, request.user, request.POST.get("verdict", ""), request.POST.get("note", ""), request)
        messages.success(request, "검토 의견을 냈습니다. 교수의 승인을 기다립니다")
    except services.ReviewError as exc:
        messages.error(request, str(exc))
        return redirect("review:detail", pk=review.pk)
    nxt = request.POST.get("next")
    return redirect("review:detail", pk=int(nxt)) if nxt and nxt.isdigit() else redirect("review:detail", pk=review.pk)


@login_required
@require_POST
def review_decide(request, pk):
    review = _review(request, pk)
    try:
        services.decide(review, request.user, request.POST.get("decision") == "approve", request.POST.get("note", ""), request)
    except PermissionDenied:
        raise Http404 from None
    except services.ReviewError as exc:
        messages.error(request, str(exc))
        return redirect("review:detail", pk=review.pk)
    review.refresh_from_db()
    if review.state == Review.State.REJECTED:
        messages.success(request, "부적합으로 확정했습니다. 이 참여자의 다음 기록이 검토 목록에 추가되었습니다")
    else:
        messages.success(request, "검토 통과 — 대표 기록과 성적이 확정되었습니다")
    return redirect("review:queue", pk=review.submission.project_id)


@login_required
@require_POST
def bulk_approve(request, pk):
    project = _project(request, pk, permissions.can_approve)
    ids = [int(i) for i in request.POST.getlist("review") if i.isdigit()]
    n = services.bulk_approve(project, request.user, ids, request)
    messages.success(request, f"{n}건을 일괄 승인했습니다")
    return redirect("review:queue", pk=project.pk)


@login_required
@xframe_options_sameorigin
def notebook_view(request, pk):
    """iframe(sandbox) 안에서만 표시되는 정제된 노트북"""
    review = _review(request, pk)
    sub = review.submission
    try:
        with open(storage.safe_path(storage.upload_root(), sub.notebook_file), encoding="utf-8") as fh:
            nb = json.load(fh)
        body, _ = render_notebook(nb)
    except Exception:
        body = "<p>노트북을 표시할 수 없습니다</p>"
    html = (
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{escape(sub.notebook_name)}</title>"
        f"<style>{NOTEBOOK_STYLE}</style></head><body>{body}</body></html>"
    )
    response = HttpResponse(html)
    response["Content-Security-Policy"] = NOTEBOOK_CSP + "; frame-ancestors 'self'"
    return response


@login_required
@require_POST
def rerun(request, pk):
    """I-6 추론 재실행 (검토 대상만, 버튼으로)"""
    review = _review(request, pk)
    from apps.integrity.sandbox import request_rerun

    request_rerun(review.submission, request.user, request)
    messages.success(request, "안전한 환경에서 다시 실행을 시작했습니다. 잠시 후 새로고침하세요")
    return redirect("review:detail", pk=review.pk)


@login_required
def results(request, pk):
    project = _project(request, pk, permissions.can_manage_competition)
    rows = services.final_results(project)
    confirmed = sum(1 for r in rows if r["confirmed"])
    ctx = comp_context(request, project.competition, project=project, rows=rows,
                       confirmed=confirmed, pending=len(rows) - confirmed)
    return render(request, "review/results.html", ctx)
