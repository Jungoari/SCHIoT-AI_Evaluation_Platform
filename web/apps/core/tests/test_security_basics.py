"""TC-S10 등 기본 보안 동작"""

import pytest
from django.urls import reverse

from apps.core.logging import mask_secrets


def test_mask_secrets_in_logs():
    assert "hunter2" not in mask_secrets("login password=hunter2 ok")
    assert "abc123" not in mask_secrets('{"token": "abc123"}')


@pytest.mark.django_db
def test_security_headers(client):
    res = client.get(reverse("accounts:login"))
    assert "script-src 'self'" in res["Content-Security-Policy"]
    assert res["X-Frame-Options"] == "DENY"
    assert res["X-Content-Type-Options"] == "nosniff"
    assert res["X-Request-ID"]


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    res = client.get(reverse("core:dashboard"))
    assert res.status_code == 302 and "/accounts/login/" in res["Location"]


@pytest.mark.django_db
def test_logout_requires_post(client, participant):
    client.force_login(participant)
    assert client.get(reverse("accounts:logout")).status_code == 405


@pytest.mark.django_db
def test_dashboard_shows_account_and_role(client, admin2, admin1, participant):
    for user, label in [(admin2, "(교수 · 총괄)"), (admin1, "(조교)"), (participant, "(참여자)")]:
        client.force_login(user)
        html = client.get(reverse("core:dashboard")).content.decode()
        assert "현재 로그인 계정" in html and user.name in html and label in html


@pytest.mark.django_db
def test_oversized_upload_rejected_before_reading(client, participant, settings):
    client.force_login(participant)
    res = client.generic("POST", "/s/00000000-0000-0000-0000-000000000000/upload/", data=b"",
                         CONTENT_LENGTH=str(2 * 1024 ** 3), content_type="multipart/form-data; boundary=x")
    assert res.status_code == 413


def test_external_images_removed_from_notebook_html():
    from apps.review.notebook import sanitize_html

    out = sanitize_html('<img src="https://evil.example/track.png"><img src="data:image/png;base64,iVBORw0KGgo=">')
    assert "evil.example" not in out and "data:image/png" in out
