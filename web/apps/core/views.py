from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.competitions.models import Deadline, Project
from apps.submissions.models import Submission

from . import permissions


def home(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("accounts:login")


@login_required
def dashboard(request):
    """역할별 '지금 할 일' 중심 첫 화면"""
    user = request.user
    now = timezone.now()
    competitions = list(permissions.competitions_for(user).prefetch_related("projects"))
    memberships = {m.competition_id: m for m in user.memberships.filter(is_active=True)}
    is_admin2 = permissions.is_admin2(user)

    cards = []
    for comp in competitions:
        m = memberships.get(comp.id)
        role = "admin2" if is_admin2 else (m.role if m else None)
        cards.append({"competition": comp, "role": role, "membership": m})

    projects = Project.objects.filter(competition__in=competitions)
    if not is_admin2:
        # 참여자·관리자1에게는 공개된 프로젝트만
        projects = projects.filter(is_published=True)
    upcoming = list(
        Deadline.objects.filter(project__in=projects, due_at__gte=now)
        .select_related("project", "project__competition")
        .order_by("due_at")[:5]
    )
    stats = {
        "competitions": len(competitions),
        "projects": projects.count(),
        "upcoming": Deadline.objects.filter(project__in=projects, due_at__gte=now).count(),
        "my_submissions": Submission.objects.filter(user=user).count(),
    }
    return render(
        request,
        "core/dashboard.html",
        {"cards": cards, "upcoming": upcoming, "stats": stats, "now": now, "role_label": role_label(user),
         "todos": admin_todos(user, competitions)},
    )


def admin_todos(user, competitions) -> list[dict]:
    """관리자 첫 화면의 '지금 할 일': 프로젝트별 검토 대기(관리자1)·승인 대기(관리자2)·미공개 설정"""
    from apps.review.services import queue

    todos = []
    for comp in competitions:
        if not permissions.can_manage_competition(user, comp):
            continue
        for project in comp.projects.all():
            if not project.is_published:
                if permissions.is_admin2(user):
                    todos.append({"kind": "setup", "project": project, "count": None})
                continue
            reviews = queue(project)
            pending = sum(1 for r in reviews if r.state == "pending")
            proposed = sum(1 for r in reviews if r.state == "proposed")
            if pending:
                todos.append({"kind": "review", "project": project, "count": pending})
            if proposed and permissions.can_approve(user, comp):
                todos.append({"kind": "approve", "project": project, "count": proposed})
    return todos


def role_label(user) -> str:
    """현재 계정의 권한 표시 (대회마다 역할이 다를 수 있어 모두 나열)"""
    if permissions.is_admin2(user):
        return "관리자2 · 총괄"
    roles = {m.get_role_display() for m in user.memberships.filter(is_active=True)}
    order = ["관리자1", "참여자"]
    return " · ".join(r for r in order if r in roles) or "소속 대회 없음"


def healthz(request):
    """헬스 체크: DB 연결 확인 (내부 정보는 노출하지 않음)"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:
        return JsonResponse({"status": "error"}, status=503)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_403(request, exception=None):
    # 권한 없음도 404처럼 보이게 해 존재 여부를 숨긴다
    return render(request, "errors/404.html", status=404)


def error_500(request):
    # 내부 정보 없이 추적 ID만 보여준다
    return render(request, "errors/500.html", {"request_id": getattr(request, "request_id", "-")}, status=500)
