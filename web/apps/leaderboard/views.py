from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from apps.competitions.models import Project
from apps.core import permissions
from apps.core.context import comp_context

from .services import my_row, standings


def _project(request, pk) -> Project:
    project = Project.objects.select_related("competition").filter(pk=pk).first()
    if project is None or not permissions.can_view_competition(request.user, project.competition):
        raise Http404
    if not project.is_published and not permissions.can_manage_competition(request.user, project.competition):
        raise Http404
    return project


def _table_context(request, project):
    rows = standings(project)
    # 실명 여부는 서버에서 결정 — 참여자 화면에는 실명이 응답에 아예 포함되지 않는다
    show_names = permissions.can_view_real_names(request.user, project.competition)
    return {"project": project, "rows": rows, "show_names": show_names, "me": my_row(rows, request.user)}


@login_required
def leaderboard(request, pk):
    project = _project(request, pk)
    ctx = comp_context(request, project.competition, **_table_context(request, project))
    rows = ctx["rows"]
    ctx["stats"] = {
        "participants": len(rows),
        "verified": sum(1 for r in rows if r.state == "approved"),
        "top": rows[0].score_text if rows else "-",
    }
    return render(request, "leaderboard/page.html", ctx)


@login_required
def leaderboard_table(request, pk):
    """HTMX 30초 자동 갱신용 표 조각"""
    project = _project(request, pk)
    return render(request, "leaderboard/_table.html", _table_context(request, project))
