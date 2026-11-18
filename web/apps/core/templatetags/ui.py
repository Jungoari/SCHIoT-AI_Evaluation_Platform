"""화면 공통 표시 규칙 — 상태 색은 모든 화면에서 동일하게"""

import zlib

from django import template
from django.utils.html import format_html

register = template.Library()

SUBMISSION_BADGES = {
    "uploading": ("badge-slate", "업로드 중"),
    "queued": ("badge-slate", "채점 대기"),
    "grading": ("badge-blue", "채점 중"),
    "graded": ("badge-green", "채점 완료"),
    "invalid": ("badge-red", "형식 오류 · 미차감"),
    "failed": ("badge-amber", "시스템 오류 · 미차감"),
    "upload_failed": ("badge-red", "업로드 실패 · 미차감"),
    "late": ("badge-amber", "마감 후 접수 · 채점 제외"),
}

REVIEW_BADGES = {
    "pending": ("badge-slate", "검증 대기"),
    "proposed": ("badge-blue", "검토 중"),
    "approved": ("badge-green", "검증 통과"),
    "rejected": ("badge-red", "부적합"),
}

LEVEL_BADGES = {
    "green": ("badge-green", "이상 없음"),
    "yellow": ("badge-amber", "확인 권장"),
    "red": ("badge-red", "강한 의심"),
    "unknown": ("badge-slate", "분석 전"),
}

LEVEL_DOTS = {"green": "bg-up", "yellow": "bg-amber-400", "red": "bg-down", "unknown": "bg-faint"}


@register.simple_tag
def submission_badge(status):
    cls, label = SUBMISSION_BADGES.get(status, ("badge-slate", status))
    return format_html('<span class="{}">{}</span>', cls, label)


@register.simple_tag
def review_badge(state):
    cls, label = REVIEW_BADGES.get(state or "pending", ("badge-slate", state))
    return format_html('<span class="{}">{}</span>', cls, label)


@register.simple_tag
def level_badge(level):
    cls, label = LEVEL_BADGES.get(level or "unknown", LEVEL_BADGES["unknown"])
    return format_html('<span class="{}">{}</span>', cls, label)


@register.filter
def level_dot(level):
    return LEVEL_DOTS.get(level or "unknown", "bg-faint")


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def score(value, decimals=4):
    if value is None:
        return "-"
    return f"{value:.{int(decimals)}f}"


@register.filter
def initials(name):
    """실명은 이름 끝 두 글자, 익명 별칭('용감한 수달 42')은 동물 이름"""
    parts = (name or "?").split()
    if len(parts) == 3:
        return parts[1][:2]
    return (name or "?")[-2:]


AVATAR_COLORS = [
    "from-brand-400 to-brand-600", "from-emerald-300 to-emerald-500", "from-amber-300 to-orange-500",
    "from-rose-300 to-rose-500", "from-violet-300 to-violet-500", "from-sky-300 to-sky-500",
]


@register.filter
def avatar_color(seed):
    return AVATAR_COLORS[zlib.crc32(str(seed).encode()) % len(AVATAR_COLORS)]
