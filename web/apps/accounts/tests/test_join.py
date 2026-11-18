"""TC-A01~A04: 참여 코드 가입·대회 추가·무차별 대입 방지"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.competitions.models import JoinCode, Membership, Role
from apps.conftest import PASSWORD


def signup_data(code, email="new@test.kr"):
    return {
        "join_code": code, "email": email, "name": "새학생", "student_no": "20261234",
        "password1": PASSWORD, "password2": PASSWORD,
    }


@pytest.mark.django_db
def test_A01_signup_requires_code(client):
    res = client.post(reverse("accounts:signup"), signup_data(""))
    assert res.status_code == 200
    assert not User.objects.filter(email="new@test.kr").exists()


@pytest.mark.django_db
def test_A01_signup_with_valid_code_joins_competition(client, competition, participant_code):
    res = client.post(reverse("accounts:signup"), signup_data(participant_code.lower()))  # 소문자도 허용
    assert res.status_code == 302
    user = User.objects.get(email="new@test.kr")
    m = Membership.objects.get(user=user)
    assert m.competition == competition and m.role == Role.PARTICIPANT
    assert m.alias  # 익명 별칭 자동 부여


@pytest.mark.django_db
def test_A02_code_bruteforce_is_limited(client, competition, participant_code):
    for _ in range(5):
        client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"))
    # 6번째에는 올바른 코드여도 차단
    res = client.post(reverse("accounts:signup"), signup_data(participant_code))
    assert "15분간 제한" in res.content.decode()
    assert not User.objects.filter(email="new@test.kr").exists()


@pytest.mark.django_db
def test_A03_existing_member_adds_competition(client, other_competition, participant, admin2):
    _, raw = JoinCode.issue(other_competition, Role.PARTICIPANT, admin2)
    client.force_login(participant)
    res = client.post(reverse("accounts:join"), {"join_code": raw})
    assert res.status_code == 302
    assert participant.memberships.count() == 2
    assert User.objects.filter(email=participant.email).count() == 1


@pytest.mark.django_db
def test_A03_cannot_join_same_competition_twice(client, participant, participant_code):
    client.force_login(participant)
    res = client.post(reverse("accounts:join"), {"join_code": participant_code})
    assert "이미 참여 중인 대회" in res.content.decode()


@pytest.mark.django_db
def test_A04_admin1_code_grants_admin1_role(client, competition, admin2):
    _, raw = JoinCode.issue(competition, Role.ADMIN1, admin2)
    client.post(reverse("accounts:signup"), signup_data(raw, "ta@test.kr"))
    assert Membership.objects.get(user__email="ta@test.kr").role == Role.ADMIN1


@pytest.mark.django_db
def test_reissue_invalidates_old_code(competition, admin2, participant_code):
    JoinCode.issue(competition, Role.PARTICIPANT, admin2)
    assert JoinCode.lookup(participant_code) is None


@pytest.mark.django_db
def test_code_is_stored_hashed(competition, participant_code):
    code = JoinCode.objects.get(is_active=True, role=Role.PARTICIPANT)
    assert participant_code.replace("-", "") not in code.code_hash
    assert len(code.code_hash) == 64


@pytest.mark.django_db
def test_weak_password_rejected(client, participant_code):
    data = signup_data(participant_code)
    data["password1"] = data["password2"] = "12345678"
    client.post(reverse("accounts:signup"), data)
    assert not User.objects.filter(email="new@test.kr").exists()
