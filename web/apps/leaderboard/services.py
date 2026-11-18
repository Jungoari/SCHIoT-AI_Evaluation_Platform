"""
리더보드 계산 (RFP p.6)

- 참여자별 최고 CSV 점수 하나 (관리자2가 '부적합'으로 승인한 기록만 제외)
  → 관리자1의 부적합 '제안'만으로는 순위에서 빠지지 않는다
- 미검증 기록도 순위에 포함하고 검증 상태를 함께 표시
- 동점은 공동 순위 (1, 1, 3 방식). 동점 판정은 프로젝트의 표시 자릿수로 반올림한 값 기준
  (0.91230000001 과 0.9123 이 다른 점수로 처리되는 부동소수 오차 방지)
- 24시간 전 순위와 비교해 ▲▼ 변화 표시
"""

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.competitions.models import Membership
from apps.review.models import Review
from apps.submissions.models import Submission


@dataclass
class Row:
    rank: int
    user_id: int
    name: str
    alias: str
    student_no: str
    score: float
    score_text: str
    submission: Submission
    state: str
    state_label: str
    attempts: int
    change: int | None  # +면 상승, -면 하락, None 이면 신규

    @property
    def change_abs(self):
        return abs(self.change) if self.change else 0


def rounded(project, score: float) -> float:
    return round(score, project.decimals)


def sort_key(project, sub: Submission):
    """정렬 키: 점수(방향 반영, 반올림) → 동점이면 최신 제출 우선"""
    s = rounded(project, sub.score)
    return (-s if project.higher_is_better else s, -sub.started_at.timestamp())


def scored_submissions(project, as_of=None):
    qs = Submission.objects.filter(project=project, status=Submission.Status.GRADED, score__isnull=False).exclude(
        deadline=None
    )
    if as_of is not None:
        qs = qs.filter(graded_at__lte=as_of)
    return qs.select_related("user", "review")


def best_per_user(project, as_of=None, exclude_rejected=True) -> dict[int, Submission]:
    best: dict[int, Submission] = {}
    for sub in scored_submissions(project, as_of):
        review = getattr(sub, "review", None) if hasattr(sub, "review") else None
        if exclude_rejected and review is not None and review.state == Review.State.REJECTED:
            continue
        cur = best.get(sub.user_id)
        if cur is None or sort_key(project, sub) < sort_key(project, cur):
            best[sub.user_id] = sub
    return best


def _rank(project, subs: list[Submission]) -> list[tuple[int, Submission]]:
    ordered = sorted(subs, key=lambda s: sort_key(project, s))
    ranked, prev_score, prev_rank = [], None, 0
    for i, sub in enumerate(ordered, start=1):
        s = rounded(project, sub.score)
        rank = prev_rank if s == prev_score else i
        ranked.append((rank, sub))
        prev_score, prev_rank = s, rank
    return ranked


STATE_LABELS = {
    "pending": "검증 대기",
    Review.State.PROPOSED: "검토 중",
    Review.State.APPROVED: "검증 통과",
}


def standings(project) -> list[Row]:
    now = timezone.now()
    best = best_per_user(project)
    previous = {sub.user_id: rank for rank, sub in _rank(project, list(best_per_user(project, now - timedelta(hours=24)).values()))}
    aliases = dict(
        Membership.objects.filter(competition=project.competition).values_list("user_id", "alias")
    )
    attempts: dict[int, int] = {}
    for uid in Submission.objects.filter(project=project, slot=Submission.Slot.USED).values_list("user_id", flat=True):
        attempts[uid] = attempts.get(uid, 0) + 1

    rows = []
    for rank, sub in _rank(project, list(best.values())):
        review = sub.review if hasattr(sub, "review") else None
        state = review.state if review else "pending"
        if state == Review.State.PENDING:
            state = "pending"
        prev = previous.get(sub.user_id)
        rows.append(Row(
            rank=rank, user_id=sub.user_id, name=sub.user.name, alias=aliases.get(sub.user_id, "익명"),
            student_no=sub.user.student_no, score=sub.score, score_text=f"{sub.score:.{project.decimals}f}",
            submission=sub, state=state, state_label=STATE_LABELS.get(state, "검증 대기"),
            attempts=attempts.get(sub.user_id, 0), change=(prev - rank) if prev is not None else None,
        ))
    return rows


def my_row(rows: list[Row], user) -> Row | None:
    return next((r for r in rows if r.user_id == user.pk), None)
