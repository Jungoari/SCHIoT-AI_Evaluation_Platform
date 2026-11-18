"""TC-S11: 감사 로그 해시 체인 — 변조 감지"""

import pytest

from apps.audit.models import AuditLog
from apps.audit.services import record, verify_chain


@pytest.mark.django_db
def test_chain_valid_and_detects_tampering(admin2):
    for i in range(5):
        record("test.event", actor=admin2, summary=f"이벤트 {i}", data={"i": i})
    assert verify_chain() == (True, None)

    # DB를 직접 수정 (관리자가 몰래 기록을 고친 상황)
    victim = AuditLog.objects.order_by("id")[2]
    AuditLog.objects.filter(pk=victim.pk).update(summary="조작된 기록")
    ok, broken_id = verify_chain()
    assert not ok and broken_id == victim.pk


@pytest.mark.django_db
def test_chain_detects_deletion(admin2):
    for i in range(4):
        record("test.event", actor=admin2, summary=f"이벤트 {i}")
    AuditLog.objects.order_by("id")[1].delete()
    assert verify_chain()[0] is False
