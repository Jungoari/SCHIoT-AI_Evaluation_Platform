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
    for _ in range(10):
        client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"))
    # 10회 실패 후에는 올바른 코드여도 차단
    res = client.post(reverse("accounts:signup"), signup_data(participant_code))
    assert "15분간 제한" in res.content.decode()
    assert not User.objects.filter(email="new@test.kr").exists()


@pytest.mark.django_db
def test_A02_nine_failures_still_allowed(client, competition, participant_code):
    """9회 실패까지는 제한 없음 → 올바른 코드로 가입 가능"""
    for _ in range(9):
        res = client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"))
    assert "남은 시도 1회" in res.content.decode()
    res = client.post(reverse("accounts:signup"), signup_data(participant_code))
    assert res.status_code == 302


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


# ---------------------------------------------------------------------------
# 리버스 프록시 뒤 실제 IP 복원 (TrustedProxyMiddleware)
# ---------------------------------------------------------------------------
PROXY = "172.18.0.1"  # 모든 요청이 같은 프록시 IP 로 들어오는 상황


@pytest.mark.django_db
def test_behind_proxy_one_attacker_does_not_block_other_students(client, settings, competition, participant_code):
    """프록시 뒤에서 한 사람이 10번 틀려도 다른 학생의 가입은 막히지 않아야 한다"""
    settings.TRUSTED_PROXY_COUNT = 1
    for _ in range(10):
        client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"),
                    REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="203.0.113.7")
    res = client.post(reverse("accounts:signup"), signup_data(participant_code),
                      REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="198.51.100.20")
    assert res.status_code == 302


@pytest.mark.django_db
def test_behind_proxy_spoofed_forwarded_for_does_not_bypass_limit(client, settings, competition, participant_code):
    """공격자가 X-Forwarded-For 앞쪽을 매번 바꿔도, 프록시가 붙인 마지막 값(실제 IP)으로 제한된다"""
    settings.TRUSTED_PROXY_COUNT = 1
    for i in range(10):
        client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"),
                    REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7")
    res = client.post(reverse("accounts:signup"), signup_data(participant_code),
                      REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR="10.9.9.9, 203.0.113.7")
    assert "15분간 제한" in res.content.decode()


@pytest.mark.django_db
def test_forwarded_for_ignored_without_trusted_proxy(client, settings, competition, participant_code):
    """프록시 설정이 없으면(기본값) 헤더를 바꿔 끼워도 제한을 피할 수 없다"""
    settings.TRUSTED_PROXY_COUNT = 0
    for i in range(10):
        client.post(reverse("accounts:signup"), signup_data("AAAA-BBBB-CCCC"), HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
    res = client.post(reverse("accounts:signup"), signup_data(participant_code), HTTP_X_FORWARDED_FOR="10.9.9.9")
    assert "15분간 제한" in res.content.decode()
