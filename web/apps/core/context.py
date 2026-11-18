"""대회 화면 공통 컨텍스트 (사이드바의 대회 메뉴·역할 표시)"""

from apps.competitions.models import Project

from . import permissions

ROLE_LABELS = {"admin2": "관리자2", "admin1": "관리자1", "participant": "참여자"}


def visible_projects(user, competition):
    qs = Project.objects.filter(competition=competition).order_by("created_at")
    if not permissions.can_manage_competition(user, competition):
        qs = qs.filter(is_published=True)
    return qs


def comp_context(request, competition, **extra) -> dict:
    user = request.user
    role = permissions.role_in(user, competition)
    ctx = {
        "competition": competition,
        "role": role,
        "role_label": ROLE_LABELS.get(role, ""),
        "can_manage": permissions.can_manage_competition(user, competition),
        "is_admin2": permissions.is_admin2(user),
        "nav_projects": list(visible_projects(user, competition)),
    }
    ctx.update(extra)
    return ctx
