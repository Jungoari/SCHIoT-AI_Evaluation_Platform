"""사용성 테스트 준비 명령·결과 정리 스크립트 테스트"""

import importlib.util
import io
import re
from pathlib import Path

import pandas as pd
import pytest
from django.core.management import CommandError, call_command

from apps.competitions.models import Competition, JoinCode, Role

pytestmark = pytest.mark.django_db

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "usability_report.py"


def _load_report():
    spec = importlib.util.spec_from_file_location("usability_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_usability_kit_creates_files_and_working_code(settings, tmp_path, admin2):
    settings.DEMO_MODE = True
    comp = Competition.objects.create(title="2026-2 머신러닝 기말 프로젝트", created_by=admin2)
    old = JoinCode.objects.filter(competition=comp).count()

    out = io.StringIO()
    call_command("usability_kit", "--out", str(tmp_path / "kit"), stdout=out)

    kit = tmp_path / "kit"
    for name in ["README.txt", "solution.ipynb", "model.joblib", "submission.csv", "submission_wrong.csv"]:
        assert (kit / name).stat().st_size > 0, name

    # 출력된 참여 코드로 실제 참여자 역할을 찾을 수 있어야 한다
    raw = re.search(r"참여자 참여 코드: (\S+)", out.getvalue()).group(1)
    code = JoinCode.lookup(raw)
    assert code is not None and code.role == Role.PARTICIPANT and code.competition == comp
    assert JoinCode.objects.filter(competition=comp).count() == old + 1

    # 오류 CSV 는 정답 열 이름만 틀리고, 정상 CSV 와 행 수는 같다
    good, bad = pd.read_csv(kit / "submission.csv"), pd.read_csv(kit / "submission_wrong.csv")
    assert list(good.columns) == ["id", "label"] and list(bad.columns) == ["id", "digit"]
    assert len(good) == len(bad)


def test_usability_kit_refused_outside_demo_mode(settings, tmp_path):
    settings.DEMO_MODE = False
    with pytest.raises(CommandError):
        call_command("usability_kit", "--out", str(tmp_path))


@pytest.mark.parametrize(
    ("answers", "expected"),
    [([3] * 10, 50.0), ([5, 1] * 5, 100.0), ([1, 5] * 5, 0.0), ([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], 75.0)],
)
def test_sus_score(answers, expected):
    assert _load_report().sus_score(answers) == expected


def test_sus_score_rejects_bad_input():
    with pytest.raises(ValueError):
        _load_report().sus_score([6] * 10)
