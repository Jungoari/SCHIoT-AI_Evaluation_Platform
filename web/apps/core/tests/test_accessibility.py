"""
접근성 회귀 테스트 — 주요 화면을 역할별로 렌더링해 기본 규칙을 검사한다 (WCAG 2.1 AA 일부)

  - 모든 입력 요소에 연결된 라벨(label[for] · 감싸는 label · aria-label)
  - 모든 이미지에 alt
  - 페이지마다 h1 정확히 1개, html lang 지정
  - 같은 id 중복 없음

색 대비는 실제 렌더링이 필요해 브라우저로 점검했다 (docs/ACCESSIBILITY.md)
"""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.testing import predictions_csv, submit

pytestmark = pytest.mark.django_db


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs, self.label_for, self.images, self.ids = [], set(), [], []
        self.h1 = 0
        self.lang = None
        self._label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "h1":
            self.h1 += 1
        elif tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag == "img":
            self.images.append(a)
        elif tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            self.inputs.append((a, self._label_depth > 0))

    def handle_endtag(self, tag):
        if tag == "label":
            self._label_depth = max(0, self._label_depth - 1)


def check_page(html: str) -> list[str]:
    c = _Collector()
    c.feed(html)
    problems = []
    for attrs, wrapped in c.inputs:
        if not (wrapped or attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("id") in c.label_for):
            problems.append(f"라벨 없는 입력: {attrs.get('name')}")
    problems += [f"alt 없는 이미지: {i.get('src')}" for i in c.images if "alt" not in i]
    if c.h1 != 1:
        problems.append(f"h1 {c.h1}개")
    if not c.lang:
        problems.append("html lang 없음")
    problems += [f"중복 id: {i}" for i in {i for i in c.ids if c.ids.count(i) > 1}]
    return problems


def _assert_pages(client, urls):
    failures = {}
    for url in urls:
        res = client.get(url)
        assert res.status_code == 200, url
        problems = check_page(res.content.decode())
        if problems:
            failures[url] = problems
    assert not failures, failures


def test_public_pages_accessible(client):
    _assert_pages(client, [reverse("accounts:login"), reverse("accounts:signup")])


def test_participant_pages_accessible(client, project, participant):
    sub = submit(participant, project, predictions_csv(project))
    client.force_login(participant)
    _assert_pages(client, [
        reverse("core:dashboard"),
        reverse("accounts:join"),
        reverse("competitions:project_detail", args=[project.pk]),
        reverse("leaderboard:page", args=[project.pk]),
        reverse("submissions:detail", args=[sub.pk]),
    ])


def test_admin_pages_accessible(client, project, admin2, participant):
    submit(participant, project, predictions_csv(project))
    client.force_login(admin2)
    comp = project.competition
    _assert_pages(client, [
        reverse("core:dashboard"),
        reverse("competitions:create"),
        reverse("competitions:detail", args=[comp.pk]),
        reverse("competitions:members", args=[comp.pk]),
        reverse("competitions:audit", args=[comp.pk]),
        reverse("competitions:project_settings", args=[project.pk]),
        reverse("review:queue", args=[project.pk]),
        reverse("review:queue", args=[project.pk]) + "?state=proposed",
        reverse("review:results", args=[project.pk]),
    ])


def test_review_detail_accessible(client, project, admin1, participant):
    from apps.review.models import Review

    submit(participant, project, predictions_csv(project))
    client.force_login(admin1)
    client.get(reverse("review:queue", args=[project.pk]))  # 큐를 열면 검토 후보가 만들어진다
    review = Review.objects.filter(submission__project=project).first()
    assert review is not None
    _assert_pages(client, [reverse("review:detail", args=[review.pk])])


def test_checker_detects_missing_label():
    """검사기 자체가 동작하는지 (라벨 없는 입력·h1 없음)"""
    problems = check_page('<html lang="ko"><body><input name="q"></body></html>')
    assert "라벨 없는 입력: q" in problems and "h1 0개" in problems
