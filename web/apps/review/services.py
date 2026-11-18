"""
2단계 검증 서비스 (RFP p.6)

최종 성적 확정 흐름
  1) 참여자마다 '검토 후보' = 부적합 승인되지 않은 기록 중 최고 점수 (동점이면 최신 제출)
  2) 관리자1이 후보를 검토하고 적합/부적합을 '제안' (제안만으로는 순위 변화 없음)
  3) 관리자2가 승인
       - 부적합 승인 → 그 기록 제외, 같은 참여자의 '다음 기록'이 자동으로 새 후보가 됨
       - 통과 승인   → 대표 기록·성적 확정
상태 전환은 반드시 이 모듈의 함수로만 하며, 함수 안에서 권한을 다시 검사한다
(화면에서 버튼을 숨기는 것만으로는 권한을 지킬 수 없기 때문)
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core import permissions
from apps.leaderboard.services import best_per_user, rounded, sort_key
from apps.submissions.models import Submission

from .models import Review


class ReviewError(Exception):
    pass


def candidates(project) -> dict[int, Submission]:
    """참여자별 현재 검토 후보 (리더보드 대표 기록과 동일)"""
    return best_per_user(project, exclude_rejected=True)


def sync_queue(project) -> None:
    """
    후보마다 Review 행을 만들고, 더 이상 후보가 아닌 '결정 전 대기' 행은 정리한다
    (더 높은 점수를 새로 제출하면 새 기록이 후보가 됨)
    """
    cands = candidates(project)
    cand_ids = {s.pk for s in cands.values()}
    with transaction.atomic():
        Review.objects.filter(submission__project=project, state=Review.State.PENDING).exclude(
            submission_id__in=cand_ids
        ).delete()
        existing = set(Review.objects.filter(submission_id__in=cand_ids).values_list("submission_id", flat=True))
        Review.objects.bulk_create(
            [Review(submission=s) for s in cands.values() if s.pk not in existing], ignore_conflicts=True
        )


def queue(project) -> list[Review]:
    """검토 큐: 후보만, 점수 순 (최고 점수 기록부터 검토)"""
    sync_queue(project)
    cand_ids = {s.pk for s in candidates(project).values()}
    reviews = list(
        Review.objects.filter(submission_id__in=cand_ids)
        .select_related("submission", "submission__user", "admin1", "admin2", "submission__integrity")
    )
    reviews.sort(key=lambda r: sort_key(project, r.submission))
    return reviews


def propose(review: Review, actor, verdict: str, note: str, request=None) -> Review:
    project = review.submission.project
    if not permissions.can_propose_verdict(actor, project.competition):
        raise PermissionDenied
    if verdict not in (Review.Verdict.PASS, Review.Verdict.FAIL):
        raise ReviewError("판정은 적합 또는 부적합이어야 합니다")
    if verdict == Review.Verdict.FAIL and not note.strip():
        raise ReviewError("부적합 제안에는 사유를 적어 주세요")
    with transaction.atomic():
        review = Review.objects.select_for_update().get(pk=review.pk)
        if review.state not in (Review.State.PENDING, Review.State.PROPOSED):
            raise ReviewError("이미 최종 결정된 기록입니다")
        review.state = Review.State.PROPOSED
        review.admin1 = actor
        review.admin1_verdict = verdict
        review.admin1_note = note.strip()[:2000]
        review.proposed_at = timezone.now()
        review.save()
        record("review.proposed", actor=actor, request=request, competition=project.competition, target=review,
               summary=f"{review.submission.user.name} 기록에 '{review.get_admin1_verdict_display()}' 제안",
               data={"submission": str(review.submission_id), "verdict": verdict, "note": review.admin1_note})
    return review


def decide(review: Review, actor, approve: bool, note: str = "", request=None) -> Review:
    """
    관리자2 최종 결정. approve=True → 검증 통과(대표 기록 확정), False → 부적합(다음 기록 검토)
    """
    project = review.submission.project
    if not permissions.can_approve(actor, project.competition):
        raise PermissionDenied
    with transaction.atomic():
        review = Review.objects.select_for_update(of=("self",)).select_related("submission__user").get(pk=review.pk)
        if review.state != Review.State.PROPOSED:
            raise ReviewError("관리자1의 판정 제안이 있어야 최종 결정할 수 있습니다")
        if not approve and not (note.strip() or review.admin1_note):
            raise ReviewError("부적합 결정에는 사유가 필요합니다")
        review.state = Review.State.APPROVED if approve else Review.State.REJECTED
        review.admin2 = actor
        review.admin2_note = note.strip()[:2000]
        review.decided_at = timezone.now()
        review.save()
        record(
            "review.approved" if approve else "review.rejected", actor=actor, request=request,
            competition=project.competition, target=review,
            summary=f"{review.submission.user.name} 기록 {'검증 통과 · 성적 확정' if approve else '부적합 확정 → 다음 기록 검토'}",
            data={"submission": str(review.submission_id), "admin1_verdict": review.admin1_verdict,
                  "self_approval": review.admin1_id == actor.pk, "note": review.admin2_note},
        )
    # 부적합이면 같은 참여자의 다음 기록이 새 후보로 큐에 들어간다
    sync_queue(project)
    return review


def bulk_approve(project, actor, review_ids: list[int], request=None) -> int:
    """관리자1이 '적합'으로 제안한 건을 한 번에 승인 (관리자2 승인 피로 감소)"""
    count = 0
    for review in Review.objects.filter(
        pk__in=review_ids, submission__project=project, state=Review.State.PROPOSED,
        admin1_verdict=Review.Verdict.PASS,
    ):
        decide(review, actor, approve=True, request=request)
        count += 1
    return count


def final_results(project) -> list[dict]:
    """
    최종 성적: 참여자별 현재 후보가 '검증 통과'면 확정, 아니면 미확정
    확정된 기록끼리 순위를 다시 매긴다 (동점은 공동 순위)
    """
    sync_queue(project)
    cands = candidates(project)
    rows = []
    for sub in cands.values():
        review = Review.objects.filter(submission=sub).first()
        rows.append({"submission": sub, "user": sub.user, "review": review,
                     "confirmed": bool(review and review.state == Review.State.APPROVED)})
    confirmed = sorted([r for r in rows if r["confirmed"]], key=lambda r: sort_key(project, r["submission"]))
    prev, prev_rank = None, 0
    for i, r in enumerate(confirmed, start=1):
        s = rounded(project, r["submission"].score)
        r["rank"] = prev_rank if s == prev else i
        prev, prev_rank = s, r["rank"]
    pending = sorted([r for r in rows if not r["confirmed"]], key=lambda r: sort_key(project, r["submission"]))
    for r in pending:
        r["rank"] = None
    return confirmed + pending
