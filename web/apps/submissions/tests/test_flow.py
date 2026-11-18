"""
TC-B(마감) · TC-C(횟수) · 업로드 검증 — RFP p.4~5 규칙을 그대로 테스트
"""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.competitions.models import Deadline
from apps.submissions.models import Submission
from apps.submissions.services import SubmissionError, complete_upload, quota_for, start_submission
from apps.testing import (
    csv_bytes,
    make_testset,
    notebook_bytes,
    predictions_csv,
    sha,
    submit,
    upload,
    weights_bytes,
)

pytestmark = pytest.mark.django_db


def test_C01_graded_deducts_one(project, participant):
    sub = submit(participant, project, predictions_csv(project, wrong_rows=[0, 1, 2]))
    assert sub.status == Submission.Status.GRADED and sub.slot == Submission.Slot.USED
    assert sub.score == pytest.approx(57 / 60)
    assert quota_for(participant, project)["current"]["remaining"] == 4


def test_C02_format_error_not_deducted(project, participant):
    bad = csv_bytes(make_testset()[["id", "f1"]])  # 정답 열 없음
    sub = submit(participant, project, bad)
    assert sub.status == Submission.Status.INVALID and sub.slot == Submission.Slot.RELEASED
    assert quota_for(participant, project)["current"]["remaining"] == 5


def test_C03_system_error_not_deducted(project, participant, monkeypatch):
    from apps.grading import services as grading

    def boom(*a, **k):
        raise RuntimeError("채점 서버 장애")

    data = predictions_csv(project)
    monkeypatch.setattr(grading, "load_labels", boom)
    monkeypatch.setattr(grading.time, "sleep", lambda s: None)
    sub = submit(participant, project, data)
    assert sub.status == Submission.Status.FAILED and sub.slot == Submission.Slot.RELEASED
    assert sub.retry_count == 3  # 3회 재시도 후 실패
    assert quota_for(participant, project)["current"]["remaining"] == 5


def test_C05_rejected_keeps_deduction(project, participant, admin1, admin2):
    from apps.review import services as review

    sub = submit(participant, project, predictions_csv(project))
    r = review.queue(project)[0]
    review.propose(r, admin1, "fail", "CSV 생성 과정 없음")
    review.decide(r, admin2, approve=False)
    sub.refresh_from_db()
    assert sub.slot == Submission.Slot.USED
    assert quota_for(participant, project)["current"]["remaining"] == 4


def test_C06_limit_exhausted(project, participant):
    d = project.deadlines.first()
    d.max_submissions = 1
    d.save()
    submit(participant, project, predictions_csv(project))
    with pytest.raises(SubmissionError) as exc:
        submit(participant, project, predictions_csv(project))
    assert exc.value.status == 409


def test_upload_failure_releases_slot_missing_file(project, participant):
    data = predictions_csv(project)
    nb, w = notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)})
    with pytest.raises(SubmissionError, match="필수 파일"):
        complete_upload(sub, {"csv": upload("p.csv", data), "notebook": upload("n.ipynb", nb)})
    sub.refresh_from_db()
    assert sub.status == Submission.Status.UPLOAD_FAILED and sub.slot == Submission.Slot.RELEASED


# ---------------- 마감 경계 ----------------
def test_B01_started_before_deadline_completed_after_is_graded(project, participant):
    d = project.deadlines.first()
    data, nb, w = predictions_csv(project), notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)})
    # 업로드 도중 마감이 지나감
    Deadline.objects.filter(pk=d.pk).update(due_at=timezone.now() - timedelta(seconds=5))
    complete_upload(sub, {"csv": upload("p.csv", data), "notebook": upload("n.ipynb", nb), "weights": upload("m.joblib", w)})
    sub.refresh_from_db()
    assert sub.status == Submission.Status.GRADED and sub.deadline_id == d.pk


def test_B02_started_after_final_deadline_is_late(project, participant):
    Deadline.objects.filter(project=project).update(due_at=timezone.now() - timedelta(minutes=1))
    sub = submit(participant, project, predictions_csv(project))
    assert sub.status == Submission.Status.LATE and sub.score is None
    assert sub.slot == Submission.Slot.NONE


def test_B03_file_swapped_after_ticket_rejected(project, participant):
    original, nb, w = predictions_csv(project, wrong_rows=range(30)), notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(original), "notebook": sha(nb), "weights": sha(w)})
    better = predictions_csv(project)  # 마감 후 더 좋은 파일로 바꿔치기 시도
    with pytest.raises(SubmissionError, match="선언한 파일과 내용이 다릅니다"):
        complete_upload(sub, {"csv": upload("p.csv", better), "notebook": upload("n.ipynb", nb), "weights": upload("m.joblib", w)})
    sub.refresh_from_db()
    assert sub.status == Submission.Status.UPLOAD_FAILED and sub.slot == Submission.Slot.RELEASED


def test_B04_grace_period_exceeded(project, participant):
    data, nb, w = predictions_csv(project), notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)})
    Submission.objects.filter(pk=sub.pk).update(started_at=timezone.now() - timedelta(minutes=31))
    with pytest.raises(SubmissionError, match="30분 안에"):
        complete_upload(sub, {"csv": upload("p.csv", data), "notebook": upload("n.ipynb", nb), "weights": upload("m.joblib", w)})


def test_B05_multiple_deadlines_count_separately(competition, admin2, participant):
    from apps.testing import setup_project

    p = setup_project(competition, admin2, deadlines=[("1차", timedelta(days=1), 1), ("2차", timedelta(days=3), 2)])
    submit(participant, p, predictions_csv(p))
    q = quota_for(participant, p)
    assert q["current"]["deadline"].title == "1차" and q["current"]["remaining"] == 0
    Deadline.objects.filter(project=p, title="1차").update(due_at=timezone.now() - timedelta(minutes=1))
    sub = submit(participant, p, predictions_csv(p))
    assert sub.deadline.title == "2차"
    assert quota_for(participant, p)["current"]["remaining"] == 1


def test_stale_ticket_expires_and_releases(project, participant):
    data, nb, w = predictions_csv(project), notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)})
    Submission.objects.filter(pk=sub.pk).update(started_at=timezone.now() - timedelta(hours=1))
    assert quota_for(participant, project)["current"]["remaining"] == 4  # 아직 예약 중
    submit(participant, project, data)  # 새 제출 시작 시 오래된 티켓 정리
    sub.refresh_from_db()
    assert sub.status == Submission.Status.UPLOAD_FAILED


# ---------------- 파일 내용 검증 ----------------
def test_S06_exe_renamed_as_csv_rejected(project, participant):
    fake = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100
    with pytest.raises(SubmissionError, match="CSV"):
        submit(participant, project, fake)


def test_weights_extension_mismatch_rejected(project, participant):
    with pytest.raises(SubmissionError, match="형식이 아닙니다"):
        submit(participant, project, predictions_csv(project), weights=b"just text pretending to be pickle")


def test_S07_path_traversal_filename_is_ignored(project, participant):
    from apps.core import storage

    data, nb, w = predictions_csv(project), notebook_bytes(), weights_bytes()
    sub = start_submission(participant, project, {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)})
    complete_upload(sub, {"csv": upload("../../etc/passwd.csv", data), "notebook": upload("n.ipynb", nb),
                          "weights": upload("m.joblib", w)})
    sub.refresh_from_db()
    assert sub.csv_name == "passwd.csv"
    assert len(sub.csv_file) == 36 and sub.csv_file.endswith(".csv")  # UUID 저장명
    assert storage.safe_path(storage.upload_root(), sub.csv_file).parent == storage.upload_root().resolve()


def test_not_participant_cannot_submit(project, admin1):
    with pytest.raises(SubmissionError):
        submit(admin1, project, predictions_csv(project))


# ---------------- 동시성 ----------------
@pytest.mark.django_db(transaction=True)
def test_C04_concurrent_submissions_respect_limit(competition, admin2, participant):
    """남은 1회에서 10건 동시 시작 → 정확히 1건만 예약"""
    from apps.testing import setup_project

    p = setup_project(competition, admin2, deadlines=[("마감", timedelta(days=1), 1)])
    data, nb, w = b"x", b"y", b"z"
    hashes = {"csv": sha(data), "notebook": sha(nb), "weights": sha(w)}
    results = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait()
            start_submission(participant, p, hashes)
            results.append("ok")
        except SubmissionError:
            results.append("limit")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("limit") == 9
