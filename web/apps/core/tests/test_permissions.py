"""
권한 매트릭스 테스트 — (관리자2 / 관리자1 / 참여자 / 외부인) × 권한 함수
권한 누락은 가장 흔한 보안 사고라서, 표 전체를 한 번에 검증한다
"""

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.core import permissions as P

# (권한 함수, 관리자2, 관리자1, 참여자, 외부인)
MATRIX = [
    (P.can_view_competition, True, True, True, False),
    (P.can_manage_competition, True, True, False, False),
    (P.can_view_real_names, True, True, False, False),
    (P.can_propose_verdict, True, True, False, False),
    (P.can_approve, True, False, False, False),
    (P.can_configure_project, True, False, False, False),
    (P.can_submit, False, False, True, False),
]


@pytest.mark.parametrize("func,a2,a1,pt,out", MATRIX, ids=[m[0].__name__ for m in MATRIX])
def test_permission_matrix(func, a2, a1, pt, out, competition, admin2, admin1, participant, outsider):
    assert func(admin2, competition) is a2
    assert func(admin1, competition) is a1
    assert func(participant, competition) is pt
    assert func(outsider, competition) is out
    assert func(AnonymousUser(), competition) is False


def test_admin1_only_sees_assigned_competition(competition, other_competition, admin1):
    """'담당' 관리자1 — 다른 대회는 관리 불가 (RFP p.6)"""
    assert P.can_manage_competition(admin1, competition)
    assert not P.can_view_competition(admin1, other_competition)
    assert list(P.competitions_for(admin1)) == [competition]


def test_inactive_membership_loses_access(competition, participant):
    participant.memberships.update(is_active=False)
    assert not P.can_view_competition(participant, competition)


def test_only_admin2_creates_competition(admin2, admin1, participant):
    assert P.can_create_competition(admin2)
    assert not P.can_create_competition(admin1)
    assert not P.can_create_competition(participant)
