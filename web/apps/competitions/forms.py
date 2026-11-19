from django import forms
from django.utils import timezone

from apps.grading.metrics import METRICS

from .models import Deadline, Project, ProjectFile, TaskType

INPUT = "input"


class CompetitionForm(forms.Form):
    title = forms.CharField(label="대회명", max_length=100, widget=forms.TextInput(attrs={"class": INPUT}))
    description = forms.CharField(
        label="설명", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"class": INPUT, "rows": 3}),
    )


DIRECTION_CHOICES = [("auto", "지표 기본값 따르기"), ("higher", "높을수록 좋음"), ("lower", "낮을수록 좋음")]


def metric_choices():
    groups = {"classification": [], "regression": []}
    for m in METRICS.values():
        arrow = "↑" if m.higher_is_better else "↓"
        groups[m.task].append((m.key, f"{m.label} {arrow}"))
    return [("분류", groups["classification"]), ("회귀", groups["regression"])]


class ProjectForm(forms.ModelForm):
    direction = forms.ChoiceField(
        label="점수 방향", choices=DIRECTION_CHOICES, initial="auto",
        widget=forms.Select(attrs={"class": INPUT}),
        help_text="정확도처럼 높을수록 좋은지, 오차처럼 낮을수록 좋은지",
    )

    class Meta:
        model = Project
        fields = ["title", "description", "metric", "decimals", "grace_minutes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT}),
            "description": forms.Textarea(attrs={"class": INPUT, "rows": 4}),
            "decimals": forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": 8}),
            "grace_minutes": forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": 240}),
        }
        help_texts = {
            "decimals": "순위·동점 비교에 쓰는 소수점 자릿수",
            "grace_minutes": "업로드 시작 후 완료까지 허용하는 시간 (마감 직전 대용량 업로드 보호)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["metric"] = forms.ChoiceField(
            label="평가 지표", choices=metric_choices(), widget=forms.Select(attrs={"class": INPUT})
        )
        if self.instance and self.instance.pk:
            default = METRICS[self.instance.metric].higher_is_better if self.instance.metric in METRICS else True
            if self.instance.higher_is_better != default:
                self.initial["direction"] = "higher" if self.instance.higher_is_better else "lower"

    def clean_decimals(self):
        v = self.cleaned_data["decimals"]
        if not 1 <= v <= 8:
            raise forms.ValidationError("1~8 사이로 입력하세요")
        return v

    def clean_grace_minutes(self):
        v = self.cleaned_data["grace_minutes"]
        if not 1 <= v <= 240:
            raise forms.ValidationError("1~240분 사이로 입력하세요")
        return v

    def save(self, commit=True):
        project = super().save(commit=False)
        metric = METRICS[self.cleaned_data["metric"]]
        direction = self.cleaned_data["direction"]
        project.higher_is_better = metric.higher_is_better if direction == "auto" else direction == "higher"
        if not project.task_type or not project.id_column:
            # 규격 확정 전에는 지표로 문제 유형을 정해 둔다
            project.task_type = metric.task if metric.task in TaskType.values else TaskType.CLASSIFICATION
        if commit:
            project.save()
        return project


class TestsetForm(forms.Form):
    testset = forms.FileField(
        label="정답 파일 (.csv)",
        widget=forms.ClearableFileInput(attrs={"class": INPUT, "accept": ".csv"}),
        help_text="ID 열 · 특성 열 · 정답 열이 모두 있는 CSV. 정답 열은 학생에게 절대 공개되지 않습니다",
    )


class SchemaForm(forms.Form):
    id_column = forms.ChoiceField(label="ID 열", widget=forms.Select(attrs={"class": INPUT}))
    target_column = forms.ChoiceField(label="정답(예측) 열", widget=forms.Select(attrs={"class": INPUT}))
    task_type = forms.ChoiceField(label="문제 유형", choices=TaskType.choices, widget=forms.Select(attrs={"class": INPUT}))

    def __init__(self, *args, columns=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(c, c) for c in columns]
        self.fields["id_column"].choices = choices
        self.fields["target_column"].choices = choices


class DeadlineForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        label="마감 시각", input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"class": INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Deadline
        fields = ["title", "due_at", "max_submissions"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT, "placeholder": "예: 1차 마감"}),
            "max_submissions": forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": 1000}),
        }
        labels = {"title": "이름", "max_submissions": "제출 횟수 제한"}

    def clean_max_submissions(self):
        v = self.cleaned_data["max_submissions"]
        if v < 1:
            raise forms.ValidationError("1회 이상이어야 합니다")
        return v

    def clean_due_at(self):
        v = self.cleaned_data["due_at"]
        if timezone.is_naive(v):
            v = timezone.make_aware(v)
        return v


class ProjectFileForm(forms.Form):
    kind = forms.ChoiceField(
        label="종류",
        choices=[(ProjectFile.Kind.TRAIN, "학습 데이터 (.csv)"), (ProjectFile.Kind.TEMPLATE_NOTEBOOK, "예시 노트북 (.ipynb)"),
                 (ProjectFile.Kind.EXTRA, "기타 자료")],
        widget=forms.Select(attrs={"class": INPUT}),
    )
    file = forms.FileField(label="파일", widget=forms.ClearableFileInput(attrs={"class": INPUT}))
