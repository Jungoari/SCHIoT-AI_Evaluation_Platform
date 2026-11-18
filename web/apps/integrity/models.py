"""
무결성 리포트 — 제출 CSV가 모델의 추론 결과인지 1차 자동 선별 (RFP p.8)

자동으로 부적합 처리하지 않는다. 사람(관리자1 → 관리자2)이 판단할 '근거'만 제공한다.
"""

from django.db import models


class IntegrityReport(models.Model):
    class Level(models.TextChoices):
        GREEN = "green", "이상 없음"
        YELLOW = "yellow", "확인 권장"
        RED = "red", "강한 의심"
        UNKNOWN = "unknown", "분석 전"

    submission = models.OneToOneField(
        "submissions.Submission", on_delete=models.CASCADE, related_name="integrity"
    )
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.UNKNOWN)
    # [{"code": "I-1", "title": "...", "level": "red", "detail": "...", "evidence": {...}}, ...]
    checks = models.JSONField(default=list)
    # 샌드박스 재실행 결과 {"status": "...", "match_rate": 0.98, "duration": 12.3, "log": "..."}
    rerun = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.submission_id} [{self.level}]"
