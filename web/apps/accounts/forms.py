from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.competitions.models import JoinCode
from apps.core.ratelimit import client_ident, join_code_limiter

from .models import User

INPUT = "input"


class JoinCodeField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "참여 코드")
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault(
            "widget",
            forms.TextInput(
                attrs={"class": f"{INPUT} font-mono tracking-widest uppercase", "placeholder": "XXXX-XXXX-XXXX",
                       "autocomplete": "off"}
            ),
        )
        super().__init__(**kwargs)


def validate_join_code(request, raw: str) -> JoinCode:
    """
    참여 코드 검증 + 실패 횟수 제한 (코드 무차별 대입 방지)
    """
    ident = client_ident(request)
    if join_code_limiter.is_blocked(ident):
        raise forms.ValidationError("코드 입력 실패가 많아 15분간 제한됩니다. 잠시 후 다시 시도해 주세요")
    code = JoinCode.lookup(raw)
    if code is None:
        count = join_code_limiter.fail(ident)
        remaining = max(join_code_limiter.limit - count, 0)
        raise forms.ValidationError(f"유효하지 않은 참여 코드입니다 (남은 시도 {remaining}회)")
    join_code_limiter.reset(ident)
    return code


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="이메일", widget=forms.EmailInput(attrs={"class": INPUT, "autofocus": True, "autocomplete": "email"})
    )
    password = forms.CharField(
        label="비밀번호", strip=False,
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "current-password"}),
    )
    error_messages = {
        "invalid_login": "이메일 또는 비밀번호가 올바르지 않습니다",
        "inactive": "비활성화된 계정입니다. 관리자에게 문의하세요",
    }


class SignupForm(forms.Form):
    join_code = JoinCodeField(help_text="관리자에게 받은 대회 참여 코드 (최초 가입 시 필수)")
    email = forms.EmailField(label="이메일", widget=forms.EmailInput(attrs={"class": INPUT, "autocomplete": "email"}))
    name = forms.CharField(label="이름", max_length=50, widget=forms.TextInput(attrs={"class": INPUT}))
    student_no = forms.CharField(
        label="학번", max_length=20, required=False, widget=forms.TextInput(attrs={"class": INPUT})
    )
    password1 = forms.CharField(
        label="비밀번호", strip=False, help_text="10자 이상, 흔한 비밀번호·숫자만으로 된 비밀번호 불가",
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="비밀번호 확인", strip=False,
        widget=forms.PasswordInput(attrs={"class": INPUT, "autocomplete": "new-password"}),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.join_code_obj: JoinCode | None = None
        super().__init__(*args, **kwargs)

    def clean_join_code(self):
        self.join_code_obj = validate_join_code(self.request, self.cleaned_data["join_code"])
        return self.cleaned_data["join_code"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            # 이미 가입된 이메일 → 로그인 후 '대회 추가'로 안내
            raise forms.ValidationError("이미 가입된 이메일입니다. 로그인 후 '대회 추가'에서 코드를 입력하세요")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "비밀번호가 일치하지 않습니다")
        if p1:
            probe = User(email=cleaned.get("email", ""), name=cleaned.get("name", ""))
            try:
                password_validation.validate_password(p1, probe)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class JoinForm(forms.Form):
    join_code = JoinCodeField()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.join_code_obj: JoinCode | None = None
        super().__init__(*args, **kwargs)

    def clean_join_code(self):
        self.join_code_obj = validate_join_code(self.request, self.cleaned_data["join_code"])
        return self.cleaned_data["join_code"]
