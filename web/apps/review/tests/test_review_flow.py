"""TC-E(리더보드) · TC-F(검증 흐름) · TC-S05(노트북 XSS)"""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from apps.leaderboard.services import standings
from apps.review import services as review
from apps.review.models import Review
from apps.review.notebook import render_notebook
from apps.submissions.models import Submission
from apps.testing import predictions_csv, submit

pytestmark = pytest.mark.django_db


def test_E02_ties_share_rank(project, participant, participant2, participant3):
    submit(participant, project, predictions_csv(project, wrong_rows=[0]))
    submit(participant2, project, predictions_csv(project, wrong_rows=[1]))  # 동점
    submit(participant3, project, predictions_csv(project, wrong_rows=[0, 1, 2]))
    ranks = [(r.name, r.rank) for r in standings(project)]
    assert [rank for _, rank in ranks] == [1, 1, 3]


def test_E03_best_score_per_participant(project, participant):
    submit(participant, project, predictions_csv(project, wrong_rows=range(10)))
    best = submit(participant, project, predictions_csv(project, wrong_rows=[0]))
    submit(participant, project, predictions_csv(project, wrong_rows=range(20)))
    rows = standings(project)
    assert len(rows) == 1 and rows[0].submission.pk == best.pk and rows[0].attempts == 3


def test_lower_is_better_ordering(competition, admin2, participant, participant2):
    from apps.testing import setup_project

    p = setup_project(competition, admin2, task="regression")
    submit(participant, p, predictions_csv(p, wrong_rows=range(20)))
    submit(participant2, p, predictions_csv(p, wrong_rows=[0]))
    rows = standings(p)
    assert rows[0].user_id == participant2.pk and rows[0].score < rows[1].score  # RMSE 는 낮을수록 1위


def test_E01_E05_participant_sees_aliases_only(client, project, participant, participant2, admin1):
    submit(participant2, project, predictions_csv(project, wrong_rows=[0]))
    client.force_login(participant)
    html = client.get(reverse("leaderboard:page", args=[project.pk])).content.decode()
    assert participant2.name not in html and participant2.email not in html  # 실명이 응답에 아예 없음
    client.force_login(admin1)
    html = client.get(reverse("leaderboard:page", args=[project.pk])).content.decode()
    assert participant2.name in html


def test_E04_unverified_included_with_state(project, participant):
    submit(participant, project, predictions_csv(project))
    rows = standings(project)
    assert rows[0].state_label == "검토 전"


def test_F01_same_score_latest_first(project, participant):
    older = submit(participant, project, predictions_csv(project, wrong_rows=[0]))
    newer = submit(participant, project, predictions_csv(project, wrong_rows=[1]))
    Submission.objects.filter(pk=older.pk).update(started_at=timezone.now() - timedelta(hours=1))
    assert review.queue(project)[0].submission_id == newer.pk


def test_F02_admin1_proposal_does_not_remove_rank(project, participant, admin1):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    review.propose(r, admin1, Review.Verdict.FAIL, "의심")
    row = standings(project)[0]
    assert row.user_id == participant.pk and row.state_label == "검토 중"


def test_F03_rejection_moves_to_next_record(project, participant, admin1, admin2):
    second = submit(participant, project, predictions_csv(project, wrong_rows=range(5)))
    best = submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    assert r.submission_id == best.pk
    review.propose(r, admin1, "fail", "CSV 직접 작성 흔적")
    review.decide(r, admin2, approve=False)
    q = review.queue(project)
    assert q[0].submission_id == second.pk and q[0].state == Review.State.PENDING
    assert standings(project)[0].submission.pk == second.pk  # 리더보드도 다음 기록으로


def test_F04_approval_confirms_result(project, participant, admin1, admin2):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    review.propose(r, admin1, "pass", "")
    review.decide(r, admin2, approve=True)
    results = review.final_results(project)
    assert results[0]["confirmed"] and results[0]["rank"] == 1


def test_F05_admin1_cannot_approve(project, participant, admin1):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    review.propose(r, admin1, "pass", "")
    with pytest.raises(PermissionDenied):
        review.decide(r, admin1, approve=True)


def test_F05_admin1_decide_url_is_404(client, project, participant, admin1):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    review.propose(r, admin1, "pass", "")
    client.force_login(admin1)
    res = client.post(reverse("review:decide", args=[r.pk]), {"decision": "approve"})
    assert res.status_code == 404
    r.refresh_from_db()
    assert r.state == Review.State.PROPOSED


def test_decide_requires_proposal(project, participant, admin2):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    with pytest.raises(review.ReviewError):
        review.decide(r, admin2, approve=True)


def test_bulk_approve_only_pass_proposals(project, participant, participant2, admin1, admin2):
    submit(participant, project, predictions_csv(project))
    submit(participant2, project, predictions_csv(project, wrong_rows=[0]))
    a, b = review.queue(project)
    review.propose(a, admin1, "pass", "")
    review.propose(b, admin1, "fail", "의심")
    assert review.bulk_approve(project, admin2, [a.pk, b.pk]) == 1


def test_participant_cannot_open_review(client, project, participant):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    client.force_login(participant)
    assert client.get(reverse("review:detail", args=[r.pk])).status_code == 404
    assert client.get(reverse("review:notebook", args=[r.pk])).status_code == 404


# ---------------- 노트북 XSS (S05) ----------------
def test_S05_notebook_scripts_are_removed():
    nb = {"cells": [
        {"cell_type": "markdown", "source": "# 제목\n<script>alert(1)</script><img src=x onerror=alert(2)>"},
        {"cell_type": "code", "source": "x", "execution_count": 1, "metadata": {}, "outputs": [
            {"output_type": "display_data", "data": {"text/html": "<b>ok</b><script>steal()</script><a href='javascript:x()'>l</a>"}},
            {"output_type": "display_data", "data": {"application/javascript": "fetch('/x')"}},
            {"output_type": "display_data", "data": {"image/png": "PHN2Zz48L3N2Zz4="}},  # PNG 아님
        ]},
    ]}
    html, stats = render_notebook(nb)
    lowered = html.lower()
    assert "<script" not in lowered and "onerror" not in lowered and "javascript:" not in lowered
    assert "<b>ok</b>" in html and stats["blocked"] == 1


def test_notebook_view_has_strict_csp(client, project, participant, admin1):
    submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    client.force_login(admin1)
    res = client.get(reverse("review:notebook", args=[r.pk]))
    assert res.status_code == 200
    assert "default-src 'none'" in res["Content-Security-Policy"]
    assert res["X-Frame-Options"] == "SAMEORIGIN"
