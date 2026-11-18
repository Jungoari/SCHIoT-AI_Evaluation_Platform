"""
I-6 추론 재실행 — 참여자 노트북을 '격리된 컨테이너'에서 실행해 제출 CSV를 재현할 수 있는지 확인

격리 설정 (참여자 코드가 정답·비밀키·다른 참여자 자료·관리 기능에 접근하지 못하게)
  - 정답 파일은 작업 폴더에 아예 넣지 않는다 (이 모듈은 정답을 읽지 않음)
  - 네트워크 없음, 루트 파일시스템 읽기 전용, 비루트 사용자, 모든 커널 권한 제거, 권한 상승 금지
  - 메모리·CPU·프로세스 수·실행 시간 제한, 환경 변수는 경로 3개만
  - 실행할 때마다 새 컨테이너 → 종료 후 삭제

검증 시간 단축: 노트북에 'inference'(+ 'setup') 태그 셀이 있으면 그 셀만 실행한다 (학습 재실행 불필요)
"""

import logging
import shutil
import time
import uuid
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.utils import timezone

from apps.audit.services import record
from apps.competitions.models import ProjectFile
from apps.core import storage
from apps.core.jobs import enqueue
from apps.grading.validation import read_csv
from apps.submissions.models import Submission

from .models import IntegrityReport
from .services import overall_level

logger = logging.getLogger(__name__)

MATCH_GREEN, MATCH_YELLOW = 0.995, 0.98  # 같은 가중치로 다시 추론하면 결정적 모델은 100% 일치해야 함


def request_rerun(sub: Submission, actor, request=None):
    report, _ = IntegrityReport.objects.get_or_create(submission=sub)
    report.rerun = {"status": "queued", "requested_at": timezone.now().isoformat()}
    report.save(update_fields=["rerun", "updated_at"])
    record("integrity.rerun_requested", actor=actor, request=request, competition=sub.project.competition,
           target=sub, summary=f"{sub.user.name} 제출 재실행 검증 요청")
    enqueue("sandbox", run_rerun, str(sub.pk))


def _prepare_workdir(sub: Submission) -> tuple[Path, str]:
    run_id = uuid.uuid4().hex
    work = Path(settings.SANDBOX_WORK_ROOT) / run_id
    (work / "input").mkdir(parents=True)
    (work / "output").mkdir()
    up = storage.upload_root()
    shutil.copyfile(storage.safe_path(up, sub.notebook_file), work / "input" / "notebook.ipynb")
    weights_name = "weights" + Path(sub.weights_file).suffix
    shutil.copyfile(storage.safe_path(up, sub.weights_file), work / "input" / weights_name)
    project = sub.project
    # 정답이 제거된 테스트 특성 + 학습 데이터만 복사 (정답 파일은 절대 복사하지 않음)
    for kind, name in ((ProjectFile.Kind.TEST_FEATURES, "test_features.csv"), (ProjectFile.Kind.TRAIN, "train.csv")):
        pf = project.files.filter(kind=kind).first()
        if pf:
            shutil.copyfile(storage.safe_path(up, pf.stored_name), work / "input" / name)
    (work / "output").chmod(0o777)  # 비루트 사용자가 결과를 쓸 수 있게
    for p in (work, work / "input"):
        p.chmod(0o755)
    return work, weights_name


def run_container(work: Path, weights_name: str) -> dict:
    """샌드박스 컨테이너 실행. {"exit": int|None, "timeout": bool, "log": str, "duration": float}"""
    import docker
    from docker.errors import DockerException

    host_work = Path(settings.SANDBOX_HOST_WORK_ROOT) / work.name
    try:
        client = docker.from_env()
    except DockerException as exc:
        return {"exit": None, "timeout": False, "log": f"Docker 를 사용할 수 없습니다: {exc}", "duration": 0.0,
                "unavailable": True}
    started = time.monotonic()
    container = None
    try:
        container = client.containers.run(
            settings.SANDBOX_IMAGE,
            command=["python", "/runner/run.py"],
            working_dir="/work/input",
            volumes={str(host_work): {"bind": "/work", "mode": "rw"}},
            environment={
                "TEST_FEATURES_PATH": "/work/input/test_features.csv",
                "WEIGHTS_PATH": f"/work/input/{weights_name}",
                "OUTPUT_PATH": "/work/output/submission.csv",
                "HOME": "/tmp",  # noqa: S108  # nosec B108 — 격리 컨테이너 내부 tmpfs
            },
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": "size=256m,mode=1777"},  # noqa: S108  # nosec B108
            user="65534:65534",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=settings.SANDBOX_MEMORY,
            memswap_limit=settings.SANDBOX_MEMORY,
            nano_cpus=int(settings.SANDBOX_CPUS * 1e9),
            pids_limit=settings.SANDBOX_PIDS_LIMIT,
            detach=True,
        )
        timed_out = False
        try:
            result = container.wait(timeout=settings.SANDBOX_TIMEOUT_SECONDS)
            exit_code = result.get("StatusCode")
        except Exception:  # 시간 초과
            timed_out = True
            exit_code = None
            container.kill()
        log = container.logs(tail=200).decode("utf-8", "replace")
        container.reload()
        oom = bool(container.attrs.get("State", {}).get("OOMKilled", False))
        return {"exit": exit_code, "timeout": timed_out, "oom": oom, "log": log[-6000:],
                "duration": round(time.monotonic() - started, 1)}
    except DockerException as exc:
        return {"exit": None, "timeout": False, "log": f"샌드박스 실행 실패: {exc}", "duration": 0.0, "unavailable": True}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:  # noqa: S110  # nosec B110 — 이미 삭제된 경우
                pass


def compare_predictions(sub: Submission, regenerated: Path) -> dict:
    project = sub.project
    original = read_csv(storage.safe_path(storage.upload_root(), sub.csv_file)).set_index(project.id_column)[project.target_column]
    try:
        new = read_csv(regenerated).set_index(project.id_column)[project.target_column]
    except Exception as exc:  # 형식이 다른 CSV
        return {"match_rate": 0.0, "error": f"재생성된 CSV를 읽을 수 없습니다: {str(exc)[:120]}"}
    new = new.reindex(original.index)
    if project.task_type == "regression":
        a = pd.to_numeric(original, errors="coerce")
        b = pd.to_numeric(new, errors="coerce")
        match = ((a - b).abs() <= 1e-6 * a.abs().clip(lower=1)).mean()
    else:
        match = (original.str.strip() == new.fillna("").str.strip()).mean()
    return {"match_rate": float(match), "rows": int(len(original))}


def run_rerun(submission_id: str) -> None:
    sub = Submission.objects.select_related("project__competition", "user").get(pk=submission_id)
    report, _ = IntegrityReport.objects.get_or_create(submission=sub)
    report.rerun = {"status": "running", "started_at": timezone.now().isoformat()}
    report.save(update_fields=["rerun", "updated_at"])

    work, weights_name = _prepare_workdir(sub)
    try:
        run = run_container(work, weights_name)
        out = work / "output" / "submission.csv"
        rerun = {"status": "done", **run, "finished_at": timezone.now().isoformat()}
        if run.get("unavailable"):
            rerun["status"] = "unavailable"
            check = _check("yellow", "샌드박스를 사용할 수 없어 재실행하지 못했습니다 (관리자 확인 필요)")
        elif run["timeout"]:
            check = _check("yellow", f"제한 시간({settings.SANDBOX_TIMEOUT_SECONDS}초)을 넘겨 강제 종료되었습니다")
        elif run.get("oom"):
            check = _check("yellow", f"메모리 제한({settings.SANDBOX_MEMORY})을 넘겨 강제 종료되었습니다")
        elif not out.exists():
            check = _check("yellow", "노트북 실행 후 예측 CSV가 만들어지지 않았습니다 (OUTPUT_PATH 사용 여부 확인)")
        else:
            cmp = compare_predictions(sub, out)
            rerun.update(cmp)
            rate = cmp["match_rate"]
            level = "green" if rate >= MATCH_GREEN else "yellow" if rate >= MATCH_YELLOW else "red"
            detail = f"가중치로 다시 추론한 결과가 제출 CSV와 {rate:.1%} 일치합니다 ({run['duration']}초 소요)"
            if level == "red":
                detail += " — 제출 CSV가 이 모델로 만들어지지 않았을 가능성이 큽니다"
            check = _check(level, detail, {"match_rate": rate})
    finally:
        shutil.rmtree(work, ignore_errors=True)

    report.refresh_from_db()
    report.checks = [c for c in report.checks if c.get("code") != "I-6"] + [check]
    report.level = overall_level(report.checks)
    report.rerun = rerun
    report.save()
    record("integrity.rerun_finished", actor=None, competition=sub.project.competition, target=sub,
           summary=f"{sub.user.name} 재실행 검증: {check['detail'][:120]}", data={"level": check["level"]})


def _check(level, detail, evidence=None):
    return {"code": "I-6", "title": "추론 재실행", "level": level, "detail": detail, "evidence": evidence or {}}
