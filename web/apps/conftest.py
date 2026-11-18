"""공통 테스트 픽스처"""

import pytest
from django.core.cache import cache

from apps.accounts.models import User
from apps.competitions.models import Competition, JoinCode, Membership, Role, random_alias

PASSWORD = "Test-pass-2026!"


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    # 테스트에서는 정적 파일 manifest 없이 동작, 파일 저장은 임시 폴더
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.UPLOAD_ROOT = tmp_path / "uploads"
    settings.LABEL_ROOT = tmp_path / "labels"
    settings.SANDBOX_WORK_ROOT = tmp_path / "sandbox"
    settings.RQ_EAGER = True


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_user(email, name="테스트", admin2=False):
    return User.objects.create_user(email=email, password=PASSWORD, name=name, is_admin2=admin2)


@pytest.fixture
def admin2(db):
    return make_user("admin2@test.kr", "총괄관리자", admin2=True)


@pytest.fixture
def competition(admin2):
    return Competition.objects.create(title="머신러닝 기말 대회", created_by=admin2)


@pytest.fixture
def other_competition(admin2):
    return Competition.objects.create(title="다른 대회", created_by=admin2)


def add_member(user, competition, role):
    return Membership.objects.create(user=user, competition=competition, role=role, alias=random_alias())


@pytest.fixture
def admin1(competition):
    u = make_user("admin1@test.kr", "조교")
    add_member(u, competition, Role.ADMIN1)
    return u


@pytest.fixture
def participant(competition):
    u = make_user("student@test.kr", "학생")
    add_member(u, competition, Role.PARTICIPANT)
    return u


@pytest.fixture
def outsider(db):
    return make_user("outsider@test.kr", "외부인")


@pytest.fixture
def participant_code(competition, admin2):
    obj, raw = JoinCode.issue(competition, Role.PARTICIPANT, admin2)
    return raw
