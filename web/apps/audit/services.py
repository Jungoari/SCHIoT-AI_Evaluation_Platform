"""
감사 로그 기록·검증

record() 는 반드시 이 함수를 통해서만 기록한다.
여러 요청이 동시에 기록해도 체인이 꼬이지 않도록 PostgreSQL 트랜잭션 잠금(advisory lock)을 건다.
"""

from django.db import connection, transaction
from django.utils import timezone

from .models import GENESIS_HASH, AuditLog

_AUDIT_LOCK_KEY = 7_204_311  # 임의의 고정 정수 (감사 로그 전용 잠금 키)


def _client_ip(request) -> str | None:
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


def record(action: str, *, actor=None, request=None, competition=None, target=None, summary="", data=None):
    """
    감사 로그 1건 기록

    action      : "submission.graded", "review.approved" 같은 점(.) 구분 이름
    target      : 대상 모델 객체 (선택)
    data        : 변경 전후 값 등 (비밀 정보는 넣지 않는다)
    """
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_AUDIT_LOCK_KEY])
        last = AuditLog.objects.order_by("-id").only("hash").first()
        log = AuditLog(
            actor=actor,
            action=action,
            competition=competition,
            target_type=target.__class__.__name__ if target is not None else "",
            target_id=str(target.pk) if target is not None else "",
            summary=summary[:255],
            data=data or {},
            ip=_client_ip(request),
            created_at=timezone.now(),
            prev_hash=last.hash if last else GENESIS_HASH,
        )
        log.hash = log.compute_hash()
        log.save()
        return log


def verify_chain() -> tuple[bool, int | None]:
    """
    전체 체인 검증. (정상 여부, 처음으로 깨진 기록 ID) 반환
    """
    prev = GENESIS_HASH
    for log in AuditLog.objects.order_by("id").iterator():
        if log.prev_hash != prev or log.compute_hash() != log.hash:
            return False, log.id
        prev = log.hash
    return True, None
