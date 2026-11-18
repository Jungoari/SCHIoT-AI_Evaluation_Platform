"""
제출 모델

상태(status) 흐름
    UPLOADING ─(업로드 완료·해시 일치)→ QUEUED → GRADING → GRADED
        │                                  │         └→ INVALID (형식·규격 오류, 횟수 미차감)
        │                                  └→ FAILED (시스템 오류, 재시도 후 실패, 횟수 미차감)
        ├─(해시 불일치·유예 초과·필수 파일 누락)→ UPLOAD_FAILED (횟수 미차감)
        └─(마감 후 시작)→ LATE (접수만, 채점 제외)

횟수 슬롯(slot) — '좌석 예약' 방식
    시작 시 RESERVED → 채점 성공 시 USED (1회 차감)
                     → 오류 시 RELEASED (차감 없음)
    부적합 판정을 받아도 USED 는 그대로 유지 (RFP: 차감 유지)
"""

import uuid

from django.conf import settings
from django.db import models


class Submission(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "업로드 중"
        QUEUED = "queued", "채점 대기"
        GRADING = "grading", "채점 중"
        GRADED = "graded", "채점 완료"
        INVALID = "invalid", "형식 오류"
        FAILED = "failed", "시스템 오류"
        UPLOAD_FAILED = "upload_failed", "업로드 실패"
        LATE = "late", "마감 후 접수 (채점 제외)"

    class Slot(models.TextChoices):
        NONE = "none", "해당 없음"
        RESERVED = "reserved", "예약"
        USED = "used", "사용"
        RELEASED = "released", "반환"

    # 추측 불가능한 ID (URL 조작으로 남의 제출물을 찾는 공격의 2차 방어선)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("competitions.Project", on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    deadline = models.ForeignKey(
        "competitions.Deadline", on_delete=models.PROTECT, null=True, blank=True, related_name="submissions"
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADING)
    slot = models.CharField(max_length=10, choices=Slot.choices, default=Slot.NONE)

    # 시각은 모두 서버 시계 기준
    started_at = models.DateTimeField("업로드 시작")
    uploaded_at = models.DateTimeField("업로드 완료", null=True, blank=True)
    graded_at = models.DateTimeField("채점 완료", null=True, blank=True)

    # 업로드 시작 시 선언한 파일 지문 {"csv": "...", "notebook": "...", "weights": "..."}
    declared_hashes = models.JSONField(default=dict)

    # 저장 파일 (UPLOAD_ROOT 아래 UUID 이름). 원래 이름은 표시용으로만 사용
    csv_file = models.CharField(max_length=100, blank=True)
    csv_name = models.CharField(max_length=255, blank=True)
    notebook_file = models.CharField(max_length=100, blank=True)
    notebook_name = models.CharField(max_length=255, blank=True)
    weights_file = models.CharField(max_length=100, blank=True)
    weights_name = models.CharField(max_length=255, blank=True)
    weights_format = models.CharField(max_length=30, blank=True)
    total_bytes = models.PositiveBigIntegerField(default=0)

    comment = models.TextField("코멘트", blank=True, max_length=2000)

    score = models.FloatField(null=True, blank=True)
    # 예측값 열의 해시 (완전 중복 제출 탐지용)
    prediction_hash = models.CharField(max_length=64, blank=True)
    errors = models.JSONField(default=list, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["project", "user", "status"]),
            models.Index(fields=["project", "status", "score"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} / {self.project} / {self.started_at:%m-%d %H:%M:%S}"

    @property
    def counts_against_limit(self) -> bool:
        return self.slot in (self.Slot.RESERVED, self.Slot.USED)

    @property
    def is_scored(self) -> bool:
        return self.status == self.Status.GRADED and self.score is not None
