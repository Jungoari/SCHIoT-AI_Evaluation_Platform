from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.audit.services import record

from .forms import JoinForm, LoginForm, SignupForm
from .models import User
from .services import JoinError, join_competition


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
    post_reset_login = False


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@require_http_methods(["GET", "POST"])
def signup(request):
    """최초 회원가입 — 참여 코드 필수 (대회에 속하지 않은 계정이 생기지 않도록)"""
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = SignupForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(
                email=data["email"], password=data["password1"], name=data["name"], student_no=data["student_no"]
            )
            record("user.signed_up", actor=user, request=request, target=user, summary=f"{user.name} 가입")
            try:
                membership = join_competition(user, form.join_code_obj, request=request)
            except JoinError as exc:
                transaction.set_rollback(True)
                form.add_error("join_code", str(exc))
                return render(request, "accounts/signup.html", {"form": form})
        # 세션 고정 공격 방지: login() 이 세션 ID를 새로 발급한다
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"'{membership.competition.title}' 대회에 참여했습니다")
        return redirect("core:dashboard")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def join(request):
    """기존 회원이 참여 코드로 대회 추가"""
    form = JoinForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            membership = join_competition(request.user, form.join_code_obj, request=request)
        except JoinError as exc:
            form.add_error("join_code", str(exc))
        else:
            messages.success(
                request, f"'{membership.competition.title}' 대회에 {membership.get_role_display()}(으)로 참여했습니다"
            )
            return redirect("core:dashboard")
    return render(request, "accounts/join.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def tutorial_done(request):
    """사용 안내를 끝냈거나 건너뜀 → 다음 로그인부터 자동으로 띄우지 않음"""
    if request.user.tutorial_done_at is None:
        request.user.tutorial_done_at = timezone.now()
        request.user.save(update_fields=["tutorial_done_at"])
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    # 스크립트 없이 폼으로 보낸 경우: 보던 화면으로 (같은 사이트 주소만 허용 — 열린 리디렉트 방지)
    nxt = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = "/dashboard/"
    return redirect(nxt)
