"""
쿼리 수 회귀 테스트 — 참여자가 늘어나도 화면당 DB 쿼리 수가 늘지 않아야 한다 (N+1 방지)

학과 단위(50명 이상)에서 참여자 수만큼 쿼리가 반복되면 화면이 눈에 띄게 느려진다.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.competitions.models import Role
from apps.conftest import add_member, make_user
from apps.testing import predictions_csv, submit

pytestmark = pytest.mark.django_db


def _add_participants(competition, project, start, count):
    for i in range(start, start + count):
        u = make_user(f"s{i}@test.kr", f"학생{i}")
        add_member(u, competition, Role.PARTICIPANT)
        submit(u, project, predictions_csv(project, wrong_rows=range(i % 7)))


def _queries(client, url) -> int:
    client.get(url)  # 첫 요청에서 검토 행 생성 등 1회성 작업을 끝낸다
    with CaptureQueriesContext(connection) as q:
        res = client.get(url)
    assert res.status_code == 200
    return len(q.captured_queries)


@pytest.mark.parametrize("url_name", ["review:results", "review:queue", "leaderboard:page"])
def test_query_count_does_not_grow_with_participants(client, admin2, competition, project, url_name):
    client.force_login(admin2)
    url = reverse(url_name, args=[project.pk])
    _add_participants(competition, project, 0, 3)
    few = _queries(client, url)
    _add_participants(competition, project, 3, 6)
    many = _queries(client, url)
    assert many == few, f"{url_name}: 참여자 3명 {few}개 → 9명 {many}개"
