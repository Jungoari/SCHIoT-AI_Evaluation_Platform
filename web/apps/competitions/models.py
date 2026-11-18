"""
대회 구조 모델

Competition(대회) ─┬─ JoinCode(참여 코드, 역할별)
                   ├─ Membership(대회 단위 역할: 참여자 / 관리자1, 익명 별칭)
                   └─ Project(프로젝트) ─┬─ Deadline(마감일 n개, 마감일별 제출 횟수)
                                         └─ ProjectFile(배포용 데이터셋 파일)
"""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class Competition(models.Model):
    title = models.CharField("대회명", max_length=100)
    description = models.TextField("설명", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_competitions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField("진행 중", default=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "대회"
        verbose_name_plural = "대회"

    def __str__(self) -> str:
        return self.title


class Role(models.TextChoices):
    PARTICIPANT = "participant", "참여자"
    ADMIN1 = "admin1", "관리자1"


# 혼동되는 문자(0/O, 1/I/L)를 뺀 32자 → 12자리 코드 = 60비트 엔트로피
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def hash_code(raw: str) -> str:
    return hashlib.sha256(normalize_code(raw).encode()).hexdigest()


class JoinCode(models.Model):
    """
    참여 코드. 원문은 저장하지 않고 해시만 저장한다 (비밀번호처럼 취급).
    원문은 발급 직후 한 번만 화면에 보여주고, 분실 시 재발급한다.
    """

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="join_codes")
    role = models.CharField(max_length=20, choices=Role.choices)
    code_hash = models.CharField(max_length=64, unique=True)
    code_hint = models.CharField("끝 4자리", max_length=4)
    expires_at = models.DateTimeField("만료", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def generate_raw() -> str:
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"

    @classmethod
    def issue(cls, competition, role, created_by, expires_at=None) -> tuple["JoinCode", str]:
        """같은 역할의 기존 코드를 비활성화하고 새 코드를 발급한다. (객체, 원문) 반환"""
        cls.objects.filter(competition=competition, role=role, is_active=True).update(is_active=False)
        raw = cls.generate_raw()
        obj = cls.objects.create(
            competition=competition,
            role=role,
            code_hash=hash_code(raw),
            code_hint=normalize_code(raw)[-4:],
            expires_at=expires_at,
            created_by=created_by,
        )
        return obj, raw

    @classmethod
    def lookup(cls, raw: str) -> "JoinCode | None":
        code = (
            cls.objects.select_related("competition")
            .filter(code_hash=hash_code(raw), is_active=True, competition__is_active=True)
            .first()
        )
        if code and code.expires_at and code.expires_at < timezone.now():
            return None
        return code


# 익명 별칭 단어 (참여자 화면 리더보드에 표시)
_ALIAS_ADJ = [
    "용감한", "재빠른", "침착한", "영리한", "끈기있는", "명랑한", "신중한", "대담한",
    "성실한", "느긋한", "날렵한", "꼼꼼한", "씩씩한", "조용한", "다정한", "호기심많은",
]
_ALIAS_NOUN = [
    "수달", "부엉이", "고래", "여우", "판다", "펭귄", "다람쥐", "돌고래",
    "치타", "거북이", "고슴도치", "참새", "알파카", "해달", "너구리", "코알라",
]


def random_alias() -> str:
    return f"{secrets.choice(_ALIAS_ADJ)} {secrets.choice(_ALIAS_NOUN)} {secrets.randbelow(90) + 10}"


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    # 무작위 생성 → 사용자 ID로 역추적 불가
    alias = models.CharField("익명 별칭", max_length=40)
    is_active = models.BooleanField("활성", default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "competition"], name="uniq_membership"),
            models.UniqueConstraint(fields=["competition", "alias"], name="uniq_alias_per_competition"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.competition} ({self.role})"


class TaskType(models.TextChoices):
    CLASSIFICATION = "classification", "분류"
    REGRESSION = "regression", "회귀"


class Project(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField("프로젝트명", max_length=100)
    description = models.TextField("설명", blank=True)
    task_type = models.CharField("문제 유형", max_length=20, choices=TaskType.choices)
    metric = models.CharField("평가 지표", max_length=30)
    higher_is_better = models.BooleanField("높을수록 좋음", default=True)
    decimals = models.PositiveSmallIntegerField("순위 비교 소수점 자릿수", default=4)

    # CSV 규격 (정답 CSV에서 자동 추론 → 관리자 확인)
    id_column = models.CharField("ID 열", max_length=100, blank=True)
    target_column = models.CharField("예측 열", max_length=100, blank=True)
    allowed_labels = models.JSONField("허용 레이블", default=list, blank=True)
    row_count = models.PositiveIntegerField("행 수", default=0)

    # 정답 파일: LABEL_ROOT 아래 UUID 이름으로 저장
    label_file = models.CharField(max_length=100, blank=True)
    label_sha256 = models.CharField(max_length=64, blank=True)

    grace_minutes = models.PositiveIntegerField("업로드 유예 시간(분)", default=30)
    is_published = models.BooleanField("공개", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.competition} / {self.title}"

    @property
    def metric_label(self) -> str:
        from apps.grading.metrics import METRICS

        m = METRICS.get(self.metric)
        return m.label if m else self.metric

    @property
    def is_ready(self) -> bool:
        """정답·규격·마감일이 모두 준비됐는지"""
        return bool(self.label_file and self.id_column and self.target_column and self.deadlines.exists())

    def deadline_for(self, when):
        """
        시각 when 에 시작된 제출이 속하는 마감 구간.
        when 이후 가장 가까운 마감일. 모든 마감이 지났으면 None (=마감 후 제출)
        """
        return self.deadlines.filter(due_at__gte=when).order_by("due_at").first()

    def final_deadline(self):
        return self.deadlines.order_by("-due_at").first()


class Deadline(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="deadlines")
    title = models.CharField("이름", max_length=50, default="마감")
    due_at = models.DateTimeField("마감 시각")
    max_submissions = models.PositiveIntegerField("제출 횟수 제한", default=5)

    class Meta:
        ordering = ["due_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.due_at:%Y-%m-%d %H:%M})"


class ProjectFile(models.Model):
    """참여자에게 배포하는 파일 (학습 데이터, 정답이 제거된 테스트 특성, 샘플 제출)"""

    class Kind(models.TextChoices):
        TRAIN = "train", "학습 데이터"
        TEST_FEATURES = "test_features", "테스트 특성 (정답 제외)"
        SAMPLE_SUBMISSION = "sample_submission", "샘플 제출 파일"
        TEMPLATE_NOTEBOOK = "template_notebook", "템플릿 노트북"
        EXTRA = "extra", "기타"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    original_name = models.CharField(max_length=255)
    stored_name = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "created_at"]
