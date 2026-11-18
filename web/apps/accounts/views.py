from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
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

