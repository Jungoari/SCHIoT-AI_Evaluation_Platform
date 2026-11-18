"""
대회·프로젝트 화면

권한 원칙: 모든 뷰는 permissions 모듈로 검사하고, 권한이 없으면 404 (존재 여부 숨김)
"""

import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_http_methods, require_POST

from apps.audit.models import AuditLog
from apps.audit.services import record, verify_chain
from apps.core import permissions, storage
from apps.core.context import comp_context
from apps.core.jobs import queue_stats
from apps.grading.metrics import METRICS
from apps.submissions.models import Submission
from apps.submissions.services import quota_for

from . import services
from .forms import CompetitionForm, DeadlineForm, ProjectFileForm, ProjectForm, SchemaForm, TestsetForm
from .models import Membership, Project, ProjectFile, Role


def _project_or_404(user, pk, check=permissions.can_view_competition) -> Project:
    project = Project.objects.select_related("competition").filter(pk=pk).first()
    if project is None or not check(user, project.competition):
        raise Http404
    if not project.is_published and not permissions.can_manage_competition(user, project.competition):
        raise Http404
    return project


# ---------------------------------------------------------------------------
# 대회
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def competition_create(request):
    if not permissions.can_create_competition(request.user):
        raise Http404
    form = CompetitionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        comp, codes = services.create_competition(
            request.user, form.cleaned_data["title"], form.cleaned_data["description"], request
        )
        # 코드 원문은 저장하지 않으므로 지금 한 번만 보여준다
        return render(request, "competitions/codes_issued.html", comp_context(request, comp, codes=codes, created=True))
    return render(request, "competitions/create.html", {"form": form})


@login_required
def competition_detail(request, pk):
    comp = permissions.get_competition_or_404(request.user, pk)
    ctx = comp_context(request, comp)
    now = timezone.now()
    projects = []
    for p in ctx["nav_projects"]:
        item = {"project": p, "next_deadline": p.deadline_for(now), "metric": METRICS.get(p.metric)}
        if ctx["role"] == Role.PARTICIPANT:
            item["quota"] = quota_for(request.user, p, now)
            item["best"] = (
                Submission.objects.filter(project=p, user=request.user, status=Submission.Status.GRADED)
                .order_by("-score" if p.higher_is_better else "score").first()
            )
        else:
            item["submission_count"] = Submission.objects.filter(project=p).exclude(status=Submission.Status.UPLOADING).count()
        projects.append(item)
    if ctx["can_manage"]:
        ctx["member_counts"] = comp.memberships.aggregate(
            participants=Count("id", filter=Q(role=Role.PARTICIPANT, is_active=True)),
            admins=Count("id", filter=Q(role=Role.ADMIN1, is_active=True)),
        )
        ctx["codes"] = comp.join_codes.filter(is_active=True)
        ctx["queue"] = queue_stats()
        ctx["recent_logs"] = AuditLog.objects.filter(competition=comp).select_related("actor")[:6]
    ctx["projects"] = projects
    return render(request, "competitions/detail.html", ctx)


@login_required
@require_POST
def code_reissue(request, pk):
    comp = permissions.get_competition_or_404(request.user, pk, permissions.is_admin2_for)
    role = request.POST.get("role")
    if role not in Role.values:
        raise Http404
    raw = services.reissue_code(comp, role, request.user, request)
    codes = {role: raw}
    return render(request, "competitions/codes_issued.html", comp_context(request, comp, codes=codes, created=False))


# ---------------------------------------------------------------------------
# 회원 관리 (F-17) — 관리자1·관리자2
# ---------------------------------------------------------------------------
@login_required
def members(request, pk):
    comp = permissions.get_competition_or_404(request.user, pk, permissions.can_manage_competition)
    q = request.GET.get("q", "").strip()
    qs = comp.memberships.select_related("user").annotate(
        submissions=Count("user__submissions", filter=Q(user__submissions__project__competition=comp)
                          & ~Q(user__submissions__status=Submission.Status.UPLOADING))
    ).order_by("role", "user__name")
    if q:
        qs = qs.filter(Q(user__name__icontains=q) | Q(user__email__icontains=q) | Q(user__student_no__icontains=q))
    return render(request, "competitions/members.html", comp_context(request, comp, members=qs, q=q))


@login_required
@require_POST
def member_action(request, pk, mid):
    comp = permissions.get_competition_or_404(request.user, pk, permissions.can_manage_competition)
    m = get_object_or_404(Membership.objects.select_related("user"), pk=mid, competition=comp)
    action = request.POST.get("action")
    if m.user_id == request.user.pk:
        messages.error(request, "자기 자신은 변경할 수 없습니다")
        return redirect("competitions:members", pk=comp.pk)
    # 관리자1은 다른 관리자1을 변경할 수 없다 (권한 상승·방해 방지)
    if m.role == Role.ADMIN1 and not permissions.is_admin2(request.user):
        messages.error(request, "관리자1 계정은 관리자2만 변경할 수 있습니다")
        return redirect("competitions:members", pk=comp.pk)

    if action == "toggle":
        m.is_active = not m.is_active
        m.save(update_fields=["is_active"])
        record("membership.toggled", request=request, competition=comp, target=m,
               summary=f"{m.user.name} {'활성화' if m.is_active else '비활성화'}")
        messages.success(request, f"{m.user.name} 님을 {'활성화' if m.is_active else '비활성화'}했습니다")
    elif action == "reset":
        uid = urlsafe_base64_encode(force_bytes(m.user.pk))
        token = default_token_generator.make_token(m.user)
        link = request.build_absolute_uri(reverse("accounts:password_reset_confirm", args=[uid, token]))
        record("user.password_reset_link", request=request, competition=comp, target=m.user,
               summary=f"{m.user.name} 비밀번호 재설정 링크 발급")
        ctx = comp_context(request, comp, members=comp.memberships.select_related("user").order_by("role", "user__name"),
                           reset_link=link, reset_user=m.user)
        return render(request, "competitions/members.html", ctx)
    else:
        raise Http404
    return redirect("competitions:members", pk=comp.pk)


# ---------------------------------------------------------------------------
# 감사 로그
# ---------------------------------------------------------------------------
@login_required
def audit_log(request, pk):
    comp = permissions.get_competition_or_404(request.user, pk, permissions.can_manage_competition)
    logs = AuditLog.objects.filter(competition=comp).select_related("actor")
    action = request.GET.get("action", "")
    if action:
        logs = logs.filter(action__startswith=action)
    ctx = comp_context(request, comp, logs=logs[:300], action=action)
    if request.GET.get("verify") and permissions.is_admin2(request.user):
        ctx["chain"] = verify_chain()
    return render(request, "competitions/audit.html", ctx)


# ---------------------------------------------------------------------------
# 프로젝트
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def project_create(request, pk):
    comp = permissions.get_competition_or_404(request.user, pk, permissions.is_admin2_for)
    form = ProjectForm(request.POST or None, initial={"decimals": 4, "grace_minutes": 30, "metric": "accuracy"})
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.competition = comp
        project.save()
        record("project.created", request=request, competition=comp, target=project, summary=f"프로젝트 생성: {project.title}")
        messages.success(request, "프로젝트를 만들었습니다. 이제 테스트셋과 마감일을 설정하세요")
        return redirect("competitions:project_settings", pk=project.pk)
    return render(request, "competitions/project_form.html", comp_context(request, comp, form=form))


@login_required
def project_detail(request, pk):
    project = _project_or_404(request.user, pk)
    comp = project.competition
    ctx = comp_context(request, comp, project=project, metric=METRICS.get(project.metric))
    now = timezone.now()
    ctx["deadlines"] = list(project.deadlines.all())
    ctx["current_deadline"] = project.deadline_for(now)
    ctx["deadline_soon"] = bool(ctx["current_deadline"] and ctx["current_deadline"].due_at - now < timedelta(hours=24))
    ctx["files"] = project.files.exclude(kind=ProjectFile.Kind.EXTRA).order_by("kind")
    ctx["extra_files"] = project.files.filter(kind=ProjectFile.Kind.EXTRA)
    if ctx["role"] == Role.PARTICIPANT:
        ctx["quota"] = quota_for(request.user, project, now)
        ctx["my_submissions"] = Submission.objects.filter(project=project, user=request.user).select_related(
            "deadline", "review"
        )[:50]
        ctx["schema"] = {
            "id_column": project.id_column, "target_column": project.target_column, "task_type": project.task_type,
            "allowed_labels": project.allowed_labels, "row_count": project.row_count,
            "max_bytes": {"csv": _mb_limit("MAX_CSV_BYTES"), "notebook": _mb_limit("MAX_NOTEBOOK_BYTES"),
                          "weights": _mb_limit("MAX_WEIGHTS_BYTES")},
        }
        from apps.leaderboard.services import my_row, standings

        ctx["my_rank"] = my_row(standings(project), request.user)
        ctx["score_history"] = _score_history(project, request.user)
    else:
        status_counts = dict(
            Submission.objects.filter(project=project).values_list("status").annotate(n=Count("id"))
        )
        ctx["status_counts"] = status_counts
        ctx["recent"] = Submission.objects.filter(project=project).exclude(
            status=Submission.Status.UPLOADING
        ).select_related("user")[:10]
    return render(request, "competitions/project_detail.html", ctx)


def _mb_limit(name):
    from django.conf import settings

    return getattr(settings, name)


def _score_history(project, user) -> list[dict]:
    """내 점수 추이 (막대 차트용, 최근 12건)"""
    subs = list(
        Submission.objects.filter(project=project, user=user, status=Submission.Status.GRADED)
        .order_by("-started_at")[:12]
    )[::-1]
    if not subs:
        return []
    scores = [s.score for s in subs]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    out = []
    for s in subs:
        # 막대 높이: 최저 25% ~ 최고 100% (좋을수록 높게)
        norm = (s.score - lo) / span
        if not project.higher_is_better:
            norm = 1 - norm
        out.append({"sub": s, "height": int(25 + norm * 75), "label": s.started_at.strftime("%m/%d")})
    return out


@login_required
@require_http_methods(["GET", "POST"])
def project_settings(request, pk):
    project = _project_or_404(request.user, pk, permissions.is_admin2_for)
    comp = project.competition
    action = request.POST.get("action") if request.method == "POST" else None

    form = ProjectForm(instance=project)
    testset_form = TestsetForm()
    deadline_form = DeadlineForm(initial={"title": f"{project.deadlines.count() + 1}차 마감", "max_submissions": 5})
    file_form = ProjectFileForm()
    schema_form = None
    inferred = None

    try:
        if action == "update":
            form = ProjectForm(request.POST, instance=project)
            if form.is_valid():
                with transaction.atomic():
                    form.save()
                    record("project.updated", request=request, competition=comp, target=project,
                           summary=f"{project.title} 설정 변경", data=form.cleaned_data | {"description": "…"})
                messages.success(request, "프로젝트 설정을 저장했습니다")
                return redirect("competitions:project_settings", pk=project.pk)
        elif action == "testset":
            testset_form = TestsetForm(request.POST, request.FILES)
            if testset_form.is_valid():
                inferred = services.upload_testset(project, testset_form.cleaned_data["testset"], request.user, request)
                project.refresh_from_db()
                messages.success(request, "테스트셋을 올렸습니다. 자동 추론된 규격을 확인하고 확정해 주세요")
        elif action == "schema":
            df = services.current_testset(project)
            schema_form = SchemaForm(request.POST, columns=list(df.columns) if df is not None else [])
            if schema_form.is_valid():
                services.confirm_schema(project, schema_form.cleaned_data["id_column"],
                                        schema_form.cleaned_data["target_column"], schema_form.cleaned_data["task_type"],
                                        request.user, request)
                messages.success(request, "규격을 확정하고 참여자 배포 파일(테스트 특성·샘플 제출·템플릿)을 만들었습니다")
                return redirect("competitions:project_settings", pk=project.pk)
        elif action == "deadline_add":
            deadline_form = DeadlineForm(request.POST)
            if deadline_form.is_valid():
                d = deadline_form.save(commit=False)
                d.project = project
                d.save()
                record("deadline.created", request=request, competition=comp, target=project,
                       summary=f"{project.title} 마감일 추가: {d.title} {d.due_at:%m-%d %H:%M} ({d.max_submissions}회)")
                messages.success(request, "마감일을 추가했습니다")
                return redirect("competitions:project_settings", pk=project.pk)
        elif action == "deadline_update":
            d = get_object_or_404(project.deadlines, pk=request.POST.get("deadline"))
            before = {"due_at": d.due_at.isoformat(), "max": d.max_submissions}
            f = DeadlineForm(request.POST, instance=d)
            if f.is_valid():
                f.save()
                record("deadline.updated", request=request, competition=comp, target=project,
                       summary=f"{project.title} 마감일 변경: {d.title}",
                       data={"before": before, "after": {"due_at": d.due_at.isoformat(), "max": d.max_submissions}})
                messages.success(request, "마감일을 변경했습니다")
            else:
                messages.error(request, "마감일 값을 확인해 주세요")
            return redirect("competitions:project_settings", pk=project.pk)
        elif action == "deadline_delete":
            d = get_object_or_404(project.deadlines, pk=request.POST.get("deadline"))
            if d.submissions.exists():
                messages.error(request, "이미 제출이 있는 마감일은 삭제할 수 없습니다 (기록 보존)")
            else:
                record("deadline.deleted", request=request, competition=comp, target=project, summary=f"마감일 삭제: {d.title}")
                d.delete()
                messages.success(request, "마감일을 삭제했습니다")
            return redirect("competitions:project_settings", pk=project.pk)
        elif action == "file_add":
            file_form = ProjectFileForm(request.POST, request.FILES)
            if file_form.is_valid():
                services.add_project_file(project, file_form.cleaned_data["kind"], file_form.cleaned_data["file"],
                                          request.user, request)
                messages.success(request, "배포 파일을 추가했습니다")
                return redirect("competitions:project_settings", pk=project.pk)
        elif action == "file_delete":
            pf = get_object_or_404(project.files, pk=request.POST.get("file"))
            if pf.kind in (ProjectFile.Kind.TEST_FEATURES, ProjectFile.Kind.SAMPLE_SUBMISSION):
                messages.error(request, "자동 생성 파일은 규격을 다시 확정하면 갱신됩니다")
            else:
                storage.delete(storage.upload_root(), pf.stored_name)
                record("project.file_deleted", request=request, competition=comp, target=project,
                       summary=f"배포 파일 삭제: {pf.original_name}")
                pf.delete()
                messages.success(request, "파일을 삭제했습니다")
            return redirect("competitions:project_settings", pk=project.pk)
        elif action == "publish":
            if not project.is_ready and not project.is_published:
                messages.error(request, "테스트셋 규격 확정과 마감일 설정을 먼저 완료해 주세요")
            else:
                project.is_published = not project.is_published
                project.save(update_fields=["is_published"])
                record("project.published" if project.is_published else "project.unpublished", request=request,
                       competition=comp, target=project,
                       summary=f"{project.title} {'공개' if project.is_published else '비공개 전환'}")
                messages.success(request, "참여자에게 공개했습니다" if project.is_published else "비공개로 전환했습니다")
            return redirect("competitions:project_settings", pk=project.pk)
        elif action == "regrade":
            from apps.grading.services import regrade_project

            n = regrade_project(project, actor=request.user, request=request)
            messages.success(request, f"{n}건을 다시 채점 대기열에 넣었습니다")
            return redirect("competitions:project_settings", pk=project.pk)
    except services.SetupError as exc:
        messages.error(request, str(exc))
        project.refresh_from_db()

    # 테스트셋은 있는데 규격 미확정 → 추론 결과로 확정 폼 채우기
    df = services.current_testset(project) if project.label_file else None
    if df is not None and schema_form is None:
        from apps.grading.validation import infer_schema

        guess = inferred or infer_schema(df)
        initial = {
            "id_column": project.id_column or guess.id_column,
            "target_column": project.target_column or guess.target_column,
            "task_type": project.task_type if project.id_column else guess.task_type,
        }
        schema_form = SchemaForm(columns=list(df.columns), initial=initial)
        inferred = guess
    ctx = comp_context(
        request, comp, project=project, form=form, testset_form=testset_form, schema_form=schema_form,
        inferred=inferred, testset_preview=df.head(5).to_dict("split") if df is not None else None,
        deadline_form=deadline_form, file_form=file_form, checklist=services.project_summary(project),
        deadlines=[(d, DeadlineForm(instance=d, prefix=f"d{d.pk}")) for d in project.deadlines.all()],
        files=project.files.all(), submission_count=Submission.objects.filter(project=project).count(),
    )
    return render(request, "competitions/project_settings.html", ctx)


@login_required
def project_file_download(request, pk, fid):
    project = _project_or_404(request.user, pk)
    pf = get_object_or_404(ProjectFile, pk=fid, project=project)
    path = storage.safe_path(storage.upload_root(), pf.stored_name)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=pf.original_name,  # noqa: SIM115
                        content_type="application/octet-stream")


# ---------------------------------------------------------------------------
# 최종 성적 내보내기
# ---------------------------------------------------------------------------
def _csv_safe(value) -> str:
    """CSV 수식 주입 방지: 엑셀에서 수식으로 해석될 수 있는 값 앞에 ' 를 붙인다"""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@login_required
def results_export(request, pk):
    project = _project_or_404(request.user, pk, permissions.can_manage_competition)
    from apps.review.services import final_results

    rows = final_results(project)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="results_project{project.pk}.csv"'
    response.write("﻿")  # 엑셀 한글 깨짐 방지
    writer = csv.writer(response)
    writer.writerow(["순위", "이름", "학번", "이메일", "점수", "검증 상태", "대표 제출 ID", "제출 시각"])
    for r in rows:
        sub = r["submission"]
        state = r["review"].get_state_display() if r["review"] else "검증 대기"
        writer.writerow([_csv_safe(v) for v in (
            r["rank"] or "-", sub.user.name, sub.user.student_no, sub.user.email,
            f"{sub.score:.{project.decimals}f}", state, sub.pk, timezone.localtime(sub.started_at).strftime("%Y-%m-%d %H:%M:%S"),
        )])
    record("results.exported", request=request, competition=project.competition, target=project,
           summary=f"{project.title} 최종 성적 내보내기 ({len(rows)}명)")
    return response
