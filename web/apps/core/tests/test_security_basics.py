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
