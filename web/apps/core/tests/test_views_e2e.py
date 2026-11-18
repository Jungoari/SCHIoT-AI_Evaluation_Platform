"""
HTTP 수준 흐름 테스트 — 실제 화면·API 를 역할별로 호출

관리자2: 대회 개설 → 프로젝트 생성 → 테스트셋 업로드 → 규격 확정 → 마감일 → 공개
참여자 : 프로젝트 화면 → 업로드 티켓 → 업로드 → 상태 확인 → 리더보드
관리자1: 검토 큐 → 판정 제안 / 관리자2: 승인 → 최종 성적 CSV
"""

import json
import re

import pytest
from django.urls import reverse

from apps.competitions.models import JoinCode, Project, ProjectFile
from apps.submissions.models import Submission
from apps.testing import csv_bytes, make_testset, notebook_bytes, predictions_csv, sha, upload, weights_bytes

pytestmark = pytest.mark.django_db


def test_admin2_full_setup_flow(client, admin2):
    client.force_login(admin2)
    res = client.post(reverse("competitions:create"), {"title": "딥러닝 대회", "description": "설명"})
    assert res.status_code == 200
    codes = re.findall(r'data-testid="(?:participant|admin1)-code">([A-Z0-9-]+)<', res.content.decode())
    assert len(codes) == 2 and JoinCode.lookup(codes[0]) is not None

    comp = admin2.created_competitions.get(title="딥러닝 대회")
    res = client.post(reverse("competitions:project_create", args=[comp.pk]),
                      {"title": "붓꽃 분류", "description": "", "metric": "accuracy", "direction": "auto",
                       "decimals": 4, "grace_minutes": 30})
    project = Project.objects.get(title="붓꽃 분류")
    url = reverse("competitions:project_settings", args=[project.pk])

    res = client.post(url, {"action": "testset", "testset": upload("full.csv", csv_bytes(make_testset()))})
    assert "자동 추론 결과" in res.content.decode()
    client.post(url, {"action": "schema", "id_column": "id", "target_column": "label", "task_type": "classification"})
    client.post(url, {"action": "deadline_add", "title": "1차", "due_at": "2099-01-01T18:00", "max_submissions": 3})
    client.post(url, {"action": "publish"})
    project.refresh_from_db()
    assert project.is_published and project.is_ready
    assert project.allowed_labels == ["setosa", "versicolor", "virginica"]

    # 배포된 테스트 특성 파일에는 정답 열이 없다 (RFP p.2)
    features = project.files.get(kind=ProjectFile.Kind.TEST_FEATURES)
    body = b"".join(client.get(reverse("competitions:project_file", args=[project.pk, features.pk])).streaming_content)
    header = body.decode().splitlines()[0]
    assert "label" not in header and header.startswith("id")
    assert project.files.filter(kind=ProjectFile.Kind.TEMPLATE_NOTEBOOK).exists()


def test_participant_submit_via_api(client, project, participant):
    client.force_login(participant)
    page = client.get(reverse("competitions:project_detail", args=[project.pk]))
    assert page.status_code == 200 and "submit-schema" in page.content.decode()

    data, nb, w = predictions_csv(project, wrong_rows=[0]), notebook_bytes(), weights_bytes()
    res = client.post(reverse("submissions:start", args=[project.pk]),
                      data=json.dumps({"hashes": {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)},
                                       "sizes": {"csv": len(data), "notebook": len(nb), "weights": len(w)}}),
                      content_type="application/json")
    start = res.json()
    assert start["ok"]
    res = client.post(start["upload_url"], {"csv": upload("p.csv", data), "notebook": upload("m.ipynb", nb),
                                            "weights": upload("m.joblib", w), "comment": "첫 제출"})
    done = res.json()
    assert done["ok"] and done["status"] == Submission.Status.GRADED
    status = client.get(done["status_url"]).content.decode()
    assert 'data-testid="score"' in status and "0.9833" in status
    assert client.get(reverse("leaderboard:page", args=[project.pk])).status_code == 200


def test_A05_A06_other_users_resources_are_404(client, project, participant, participant2, other_competition, admin1):
    from apps.testing import submit

    sub = submit(participant2, project, predictions_csv(project))
    client.force_login(participant)
    assert client.get(reverse("submissions:detail", args=[sub.pk])).status_code == 404
    assert client.get(reverse("submissions:download", args=[sub.pk, "csv"])).status_code == 404
    assert client.get(reverse("competitions:project_settings", args=[project.pk])).status_code == 404
    assert client.get(reverse("competitions:members", args=[project.competition.pk])).status_code == 404
    client.force_login(admin1)
    assert client.get(reverse("competitions:detail", args=[other_competition.pk])).status_code == 404


def test_unpublished_project_hidden_from_participant(client, competition, admin2, participant):
    from apps.testing import setup_project

    p = setup_project(competition, admin2, published=False)
    client.force_login(participant)
    assert client.get(reverse("competitions:project_detail", args=[p.pk])).status_code == 404


def test_review_and_export_flow(client, project, participant, admin1, admin2):
    from apps.review.models import Review
    from apps.testing import submit

    submit(participant, project, predictions_csv(project))
    client.force_login(admin1)
    q = client.get(reverse("review:queue", args=[project.pk]))
    assert q.status_code == 200
    r = Review.objects.get()
    assert client.get(reverse("review:detail", args=[r.pk])).status_code == 200
    client.post(reverse("review:propose", args=[r.pk]), {"verdict": "pass", "note": "확인"})
    client.force_login(admin2)
    client.post(reverse("review:decide", args=[r.pk]), {"decision": "approve"})
    r.refresh_from_db()
    assert r.state == Review.State.APPROVED
    csv_text = client.get(reverse("competitions:results_export", args=[project.pk])).content.decode("utf-8-sig")
    assert participant.name in csv_text and "검증 통과" in csv_text


def test_csv_export_escapes_formula(client, project, participant, admin2):
    from apps.testing import submit

    participant.name = "=HYPERLINK(\"http://evil\")"
    participant.save()
    submit(participant, project, predictions_csv(project))
    client.force_login(admin2)
    text = client.get(reverse("competitions:results_export", args=[project.pk])).content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text


def test_member_reset_link_and_toggle(client, competition, admin1, participant):
    client.force_login(admin1)
    m = participant.memberships.get()
    res = client.post(reverse("competitions:member_action", args=[competition.pk, m.pk]), {"action": "reset"})
    link = re.search(r"http://testserver(/accounts/reset/[^\s\"<]+)", res.content.decode()).group(1)
    client.logout()
    page = client.get(link, follow=True)
    assert "새 비밀번호 설정" in page.content.decode()
    client.force_login(admin1)
    client.post(reverse("competitions:member_action", args=[competition.pk, m.pk]), {"action": "toggle"})
    m.refresh_from_db()
    assert not m.is_active


def test_admin1_cannot_toggle_other_admin1(client, competition, admin1, admin2):
    from apps.competitions.models import Role
    from apps.conftest import add_member, make_user

    other = make_user("ta2@test.kr", "조교2")
    m = add_member(other, competition, Role.ADMIN1)
    client.force_login(admin1)
    client.post(reverse("competitions:member_action", args=[competition.pk, m.pk]), {"action": "toggle"})
    m.refresh_from_db()
    assert m.is_active


def test_all_main_pages_render(client, project, participant, admin1, admin2):
    from apps.testing import submit

    sub = submit(participant, project, predictions_csv(project))
    comp = project.competition
    pages_by_user = {
        participant: [reverse("core:dashboard"), reverse("competitions:detail", args=[comp.pk]),
                      reverse("competitions:project_detail", args=[project.pk]), reverse("submissions:detail", args=[sub.pk]),
                      reverse("leaderboard:page", args=[project.pk])],
        admin1: [reverse("competitions:detail", args=[comp.pk]), reverse("competitions:members", args=[comp.pk]),
                 reverse("competitions:audit", args=[comp.pk]), reverse("review:queue", args=[project.pk]),
                 reverse("review:results", args=[project.pk]), reverse("competitions:project_detail", args=[project.pk])],
        admin2: [reverse("competitions:create"), reverse("competitions:project_settings", args=[project.pk]),
                 reverse("competitions:audit", args=[comp.pk]) + "?verify=1"],
    }
    for user, urls in pages_by_user.items():
        client.force_login(user)
        for url in urls:
            assert client.get(url).status_code == 200, (user.email, url)


def test_dashboard_todos_for_admins(client, project, participant, admin1, admin2):
    from apps.review import services as review
    from apps.testing import submit

    submit(participant, project, predictions_csv(project))
    client.force_login(admin1)
    html = client.get(reverse("core:dashboard")).content.decode()
    assert 'data-testid="todos"' in html and "관리자1 검토 대기" in html
    r = review.queue(project)[0]
    review.propose(r, admin1, "pass", "")
    client.force_login(admin2)
    assert "관리자2 승인 대기" in client.get(reverse("core:dashboard")).content.decode()
    client.force_login(participant)
    assert 'data-testid="todos"' not in client.get(reverse("core:dashboard")).content.decode()


def test_deadline_soon_banner(client, project, participant):
    from datetime import timedelta

    from django.utils import timezone

    project.deadlines.update(due_at=timezone.now() + timedelta(hours=3))
    client.force_login(participant)
    html = client.get(reverse("competitions:project_detail", args=[project.pk])).content.decode()
    assert 'data-testid="banner"' in html and "마감까지" in html
