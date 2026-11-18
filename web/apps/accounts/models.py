"""
사용자 모델

- 로그인 ID는 이메일
- 관리자2(총괄 관리자)는 전역 플래그 is_admin2 로 표현한다
- 참여자 / 관리자1 역할은 '대회 단위'로 부여되므로 competitions.Membership 에 저장한다
  (같은 사람이 A 대회에선 참여자, B 대회에선 관리자1 일 수 있음)
"""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("이메일은 필수입니다")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_admin2", True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("이메일", unique=True)
    name = models.CharField("이름", max_length=50)
    student_no = models.CharField("학번", max_length=20, blank=True)
    is_admin2 = models.BooleanField("관리자2(총괄)", default=False)
    is_active = models.BooleanField("활성", default=True)
    is_staff = models.BooleanField("Django 관리 화면 접근", default=False)
    date_joined = models.DateTimeField("가입일", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        verbose_name = "사용자"
        verbose_name_plural = "사용자"

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"
