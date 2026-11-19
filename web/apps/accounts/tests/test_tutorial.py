"""처음 로그인 사용 안내(튜토리얼): 역할별 내용 · 한 번만 표시 · 다시 보기 · 안전한 이동"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

DASH = "/dashboard/"


def _html(client, url=DASH):
    res = client.get(url)
    assert res.status_code == 200
    return res.content.decode()


@pytest.mark.parametrize(
    ("who", "badge", "step"),
    [("participant", "사용 안내 · 학생", "제출하기"),
     ("admin1", "사용 안내 · 조교", "검토 목록"),
     ("admin2", "사용 안내 · 교수", "대회 개설")],
)
def test_first_login_shows_role_specific_tutorial(client, request, who, badge, step):
    user = request.getfixturevalue(who)
    client.force_login(user)
    html = _html(client)
    assert 'data-testid="tutorial"' in html and 'role="dialog"' in html
    assert badge in html and step in html


def test_tutorial_not_shown_after_done(client, participant):
    client.force_login(participant)
    res = client.post(reverse("accounts:tutorial_done"), HTTP_X_REQUESTED_WITH="fetch")
    assert res.status_code == 204
    participant.refresh_from_db()
    assert participant.tutorial_done_at is not None
    assert 'data-testid="tutorial"' not in _html(client)


def test_tutorial_can_be_replayed(client, participant):
    client.force_login(participant)
    client.post(reverse("accounts:tutorial_done"), HTTP_X_REQUESTED_WITH="fetch")
    html = _html(client)
    assert 'data-testid="tutorial-replay"' in html  # 사이드바 '사용 안내 다시 보기'
    assert 'data-testid="tutorial"' in _html(client, DASH + "?tutorial=1")


def test_tutorial_done_without_script_redirects_back_safely(client, participant):
    client.force_login(participant)
    res = client.post(reverse("accounts:tutorial_done"), {"next": "/accounts/join/"})
    assert res.status_code == 302 and res["Location"] == "/accounts/join/"
    # 외부 주소로 보내려는 시도는 대시보드로 (열린 리디렉트 방지)
    res = client.post(reverse("accounts:tutorial_done"), {"next": "https://evil.example.com/"})
    assert res["Location"] == DASH


def test_tutorial_done_requires_login_and_post(client, participant):
    res = client.post(reverse("accounts:tutorial_done"))
    assert res.status_code == 302 and "/accounts/login/" in res["Location"]
    client.force_login(participant)
    assert client.get(reverse("accounts:tutorial_done")).status_code == 405


def test_login_page_has_no_tutorial(client):
    assert 'data-testid="tutorial"' not in _html(client, reverse("accounts:login"))
