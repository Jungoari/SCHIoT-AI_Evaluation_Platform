"""
작업 큐 등록

- grading : CSV 검증·채점·빠른 무결성 검사 (정답 접근 O)
- sandbox : 참여자 노트북 격리 재실행 (정답 접근 X)

테스트·로컬 개발(RQ_EAGER=true)에서는 큐를 거치지 않고 즉시 실행한다.
"""

import logging

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def enqueue(queue: str, func, *args, retries: int = 0, **kwargs):
    """
    DB 트랜잭션이 커밋된 뒤에 작업을 등록한다
    (커밋 전에 워커가 먼저 실행되어 아직 없는 행을 찾는 문제 방지)
    """

    def _submit():
        if settings.RQ_EAGER:
            func(*args, **kwargs)
            return
        import django_rq
        from rq import Retry

        q = django_rq.get_queue(queue)
        options = {}
        if retries:
            options["retry"] = Retry(max=retries, interval=[5, 15, 30][:retries])
        q.enqueue(func, *args, **kwargs, **options)

    transaction.on_commit(_submit)


def queue_stats() -> dict:
    """운영 대시보드용 큐 상태 (실패 시 빈 값)"""
    if settings.RQ_EAGER:
        return {"mode": "eager"}
    try:
        import django_rq

        stats = {}
        for name in ("grading", "sandbox"):
            q = django_rq.get_queue(name)
            stats[name] = {"queued": q.count, "failed": q.failed_job_registry.count}
        return stats
    except Exception:  # Redis 장애 등
        logger.exception("큐 상태 조회 실패")
        return {"error": True}
