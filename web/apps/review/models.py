"""
검토·승인 모델 (2단계 검증)

상태 머신
    PENDING ──(관리자1 판정 제안)──→ PROPOSED ──(관리자2 결정)──┬→ APPROVED  : 대표 기록·성적 확정
       ▲                                                        └→ REJECTED  : 해당 기록 제외
       └──────────── REJECTED 이후 같은 참여자의 '다음 후보'가 새 PENDING 으로 생성 ───┘

- 관리자1의 제안(PROPOSED)만으로는 리더보드 순위가 바뀌지 않는다 (RFP p.6)
- 상태 전환 규칙은 review/services.py 에서만 수행한다 (권한 검사 포함)
"""

from django.conf import settings
from django.db import models


class Review(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "검토 전"
        PROPOSED = "proposed", "검토 중"
        APPROVED = "approved", "검토 통과"
        REJECTED = "rejected", "부적합"

    class Verdict(models.TextChoices):
        PASS = "pass", "적합"
        FAIL = "fail", "부적합"

    submission = models.OneToOneField("submissions.Submission", on_delete=models.CASCADE, related_name="review")
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)

    admin1 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    admin1_verdict = models.CharField(max_length=10, choices=Verdict.choices, blank=True)
    admin1_note = models.TextField(blank=True, max_length=2000)
    proposed_at = models.DateTimeField(null=True, blank=True)

    admin2 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    admin2_note = models.TextField(blank=True, max_length=2000)
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.submission} [{self.state}]"
