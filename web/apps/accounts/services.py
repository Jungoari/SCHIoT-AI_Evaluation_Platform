"""
가입·대회 참여 비즈니스 로직 (뷰와 분리해 테스트하기 쉽게)
"""

from django.db import IntegrityError, transaction

from apps.audit.services import record
from apps.competitions.models import JoinCode, Membership, random_alias


class JoinError(Exception):
    """사용자에게 그대로 보여줘도 안전한 메시지만 담는다"""


def join_competition(user, join_code: JoinCode, request=None) -> Membership:
    """
    참여 코드로 대회에 합류한다.
    - 이미 같은 대회의 멤버면 오류
    - 익명 별칭이 대회 안에서 겹치면 다시 뽑는다
    """
    competition = join_code.competition
    if Membership.objects.filter(user=user, competition=competition).exists():
        raise JoinError("이미 참여 중인 대회입니다")

    for _ in range(20):
        try:
            with transaction.atomic():
                membership = Membership.objects.create(
                    user=user, competition=competition, role=join_code.role, alias=random_alias()
                )
            break
        except IntegrityError:
            if Membership.objects.filter(user=user, competition=competition).exists():
                raise JoinError("이미 참여 중인 대회입니다") from None
            continue  # 별칭 충돌 → 다시 뽑기
    else:
        raise JoinError("잠시 후 다시 시도해 주세요")

    record(
        "membership.joined",
        actor=user,
        request=request,
        competition=competition,
        target=membership,
        summary=f"{user.name} 님이 {membership.get_role_display()}(으)로 참여",
        data={"role": membership.role, "code_hint": join_code.code_hint},
    )
    return membership
