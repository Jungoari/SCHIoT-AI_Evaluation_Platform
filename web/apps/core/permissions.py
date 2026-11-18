"""
권한 정책 — 모든 권한 판단은 이 모듈의 함수로만 한다

뷰마다 권한 검사를 제각각 구현하면 하나쯤 빠뜨리기 쉽다 (가장 흔한 보안 사고).
그래서 "누가 무엇을 할 수 있나"를 한 곳에 모아 두고, 권한 매트릭스 테스트로 전부 검증한다.

역할 요약
- 관리자2 (User.is_admin2)      : 전체 대회. 대회 개설, 최종 승인, 관리자1 권한 전부
- 관리자1 (Membership admin1)   : 담당 대회만. 회원·대회 운영, 채점 운영, 코드 확인, 판정 제안
- 참여자  (Membership participant): 소속 대회만. 제출, 내 결과, 익명 리더보드
"""

from django.http import Http404

from apps.competitions.models import Competition, Membership, Role


def is_admin2(user) -> bool:
    return bool(user.is_authenticated and user.is_active and user.is_admin2)


def membership(user, competition) -> Membership | None:
    if not user.is_authenticated:
        return None
    return Membership.objects.filter(user=user, competition=competition, is_active=True).first()


def role_in(user, competition) -> str | None:
    """대회 안에서의 역할: 'admin2' / 'admin1' / 'participant' / None"""
    if is_admin2(user):
        return "admin2"
    m = membership(user, competition)
    return m.role if m else None


def can_view_competition(user, competition) -> bool:
    return role_in(user, competition) is not None


def can_manage_competition(user, competition) -> bool:
    """회원·대회 운영, 채점 운영, 제출 코드 확인, 실명 열람"""
    return role_in(user, competition) in ("admin2", Role.ADMIN1)


def can_view_real_names(user, competition) -> bool:
    return can_manage_competition(user, competition)


def can_propose_verdict(user, competition) -> bool:
    return can_manage_competition(user, competition)


def can_approve(user, competition) -> bool:
    """최종 승인은 관리자2만"""
    return is_admin2(user)


def can_create_competition(user) -> bool:
    return is_admin2(user)


def can_configure_project(user, competition) -> bool:
    """정답·지표·규격·마감일·횟수 설정은 관리자2 (RFP p.5)"""
    return is_admin2(user)


def can_submit(user, competition) -> bool:
    return role_in(user, competition) == Role.PARTICIPANT


def competitions_for(user):
    """사용자가 볼 수 있는 대회 목록"""
    if is_admin2(user):
        return Competition.objects.all()
    return Competition.objects.filter(memberships__user=user, memberships__is_active=True).distinct()


def get_competition_or_404(user, pk, check=can_view_competition) -> Competition:
    """
    권한이 없으면 403 대신 404 — 대회의 존재 여부 자체를 숨긴다
    """
    competition = Competition.objects.filter(pk=pk).first()
    if competition is None or not check(user, competition):
        raise Http404
    return competition
