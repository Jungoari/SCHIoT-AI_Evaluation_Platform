"""
감사 로그 — 해시 체인으로 위변조를 감지한다

각 기록의 hash = SHA256(이전 기록의 hash + 이 기록의 내용)
중간 기록 하나를 수정·삭제하면 그 뒤의 모든 hash 가 맞지 않게 되어 검증에서 드러난다.
애플리케이션에는 감사 로그를 수정·삭제하는 기능을 두지 않는다.
"""

import hashlib
import json

from django.conf import settings
from django.db import models

GENESIS_HASH = "0" * 64


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=60, db_index=True)
    competition = models.ForeignKey(
        "competitions.Competition", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    summary = models.CharField(max_length=255, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(db_index=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-id"]

    def canonical_payload(self) -> str:
        """해시 계산에 쓰는 정규화된 내용 (키 순서 고정)"""
        return json.dumps(
            {
                "actor": self.actor_id,
                "action": self.action,
                "competition": self.competition_id,
                "target_type": self.target_type,
                "target_id": self.target_id,
                "summary": self.summary,
                "data": self.data,
                "ip": self.ip,
                "created_at": self.created_at.isoformat(),
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    def compute_hash(self) -> str:
        return hashlib.sha256((self.prev_hash + self.canonical_payload()).encode()).hexdigest()
