"""
부정 제출 탐지 실험 — 무결성 리포트가 실제로 잘 잡고, 정직한 제출을 오탐하지 않는지 측정

    python manage.py integrity_experiment            # 결과를 docs/INTEGRITY_EXPERIMENT.md 로 저장
    python manage.py integrity_experiment --rerun    # I-6 격리 재실행까지 (Docker 필요, 수 분 소요)

모든 데이터 변경은 하나의 트랜잭션 안에서 하고 마지막에 롤백한다 (DB·감사 로그에 흔적을 남기지 않음).
제출 파일은 실험이 끝나면 디스크에서 지운다.
"""

from collections import Counter
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from apps.accounts.models import User
from apps.competitions import services as cs
from apps.competitions.models import Competition, Deadline, Membership, Project, ProjectFile, Role, random_alias
from apps.core import demo, storage
from apps.grading.services import grade_submission
from apps.integrity.models import IntegrityReport
from apps.submissions.services import complete_upload, start_submission
from apps.testing import sha, upload

HONEST_MODELS = [
    ("LogisticRegression(C=1)", lambda: LogisticRegression(C=1, max_iter=3000)),
    ("LogisticRegression(C=0.05)", lambda: LogisticRegression(C=0.05, max_iter=3000)),
    ("LogisticRegression(C=0.005)", lambda: LogisticRegression(C=0.005, max_iter=3000)),
    ("RandomForest(200)", lambda: RandomForestClassifier(n_estimators=200, random_state=0)),
    ("RandomForest(50, depth 10)", lambda: RandomForestClassifier(n_estimators=50, max_depth=10, random_state=1)),
    ("RandomForest(20, depth 6)", lambda: RandomForestClassifier(n_estimators=20, max_depth=6, random_state=2)),
    ("ExtraTrees(200)", lambda: ExtraTreesClassifier(n_estimators=200, random_state=0)),
    ("ExtraTrees(30, depth 8)", lambda: ExtraTreesClassifier(n_estimators=30, max_depth=8, random_state=3)),
    ("KNN(k=1)", lambda: KNeighborsClassifier(n_neighbors=1)),
    ("KNN(k=5)", lambda: KNeighborsClassifier(n_neighbors=5)),
    ("KNN(k=15, distance)", lambda: KNeighborsClassifier(n_neighbors=15, weights="distance")),
    ("SVC(rbf, C=10)", lambda: SVC(C=10, gamma=0.001)),
    ("SVC(rbf, C=1)", lambda: SVC(C=1)),
    ("SVC(linear)", lambda: SVC(kernel="linear", C=0.01)),
    ("DecisionTree", lambda: DecisionTreeClassifier(random_state=0)),
    ("DecisionTree(depth 8)", lambda: DecisionTreeClassifier(max_depth=8, random_state=1)),
    ("GaussianNB", lambda: GaussianNB()),
    ("RidgeClassifier", lambda: RidgeClassifier(alpha=1.0)),
    ("MLP(64)", lambda: MLPClassifier(hidden_layer_sizes=(64,), max_iter=400, random_state=0)),
    ("MLP(32, alpha)", lambda: MLPClassifier(hidden_layer_sizes=(32,), alpha=0.01, max_iter=400, random_state=1)),
]

GROUPS = [
    ("정직한 제출", "honest"),
    ("완전 복사", "copy"),
    ("변형 복사 (5~20% 수정)", "perturb"),
    ("예측값 직접 기입", "hand"),
    ("코드 그대로 CSV만 수정", "edit"),
]


class Command(BaseCommand):
    help = "무결성 리포트의 탐지율·오탐률을 측정합니다"

    def add_arguments(self, parser):
        parser.add_argument("--rerun", action="store_true", help="I-6 격리 재실행까지 측정")
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--no-save", action="store_true")

    def handle(self, *args, **opts):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE=true 일 때만 실행할 수 있습니다")
        rng = np.random.default_rng(opts["seed"])
        stored = []
        labels = []
        try:
            with transaction.atomic():
                rows = self._run(rng, opts["rerun"], stored, labels)
                transaction.set_rollback(True)  # 실험 데이터는 남기지 않는다
        finally:
            for name in stored:
                storage.delete(storage.upload_root(), name)
            for name in labels:
                storage.delete(storage.label_root(), name)
        md = self._report(rows, opts)
        self.stdout.write(md)
        if not opts["no_save"]:
            out = Path(settings.BASE_DIR).parent / "docs" / "INTEGRITY_EXPERIMENT.md"
            out.write_text(md, encoding="utf-8")
            self.stdout.write(f"\n저장: {out}")

    # ------------------------------------------------------------------
    def _run(self, rng, rerun, stored, labels):
        admin = User.objects.create_user(email="exp-admin@demo.evalhub", password=None, name="실험관리자", is_admin2=True)
        comp = Competition.objects.create(title="무결성 실험 (임시)", created_by=admin)
        project = Project.objects.create(competition=comp, title="실험", task_type="classification", metric="accuracy",
                                         higher_is_better=True, decimals=4, grace_minutes=30)
        train, test = demo.digits_frames()
        cs.upload_testset(project, upload("t.csv", test.to_csv(index=False).encode()), admin)
        cs.add_project_file(project, ProjectFile.Kind.TRAIN, upload("train.csv", train.to_csv(index=False).encode()), admin)
        cs.confirm_schema(project, "id", "label", "classification", admin)
        Deadline.objects.create(project=project, title="마감", due_at=timezone.now() + timezone.timedelta(days=1), max_submissions=5)
        project.is_published = True
        project.save()
        labels.append(project.label_file)
        stored.extend(project.files.values_list("stored_name", flat=True))
        X, y = train.drop(columns=["id", "label"]), train["label"]
        Xte, ids, truth = test.drop(columns=["id", "label"]), test["id"], test["label"].to_numpy()

        counter = iter(range(10_000))

        def user():
            i = next(counter)
            u = User.objects.create_user(email=f"exp{i:03d}@demo.evalhub", password=None, name=f"실험{i:03d}")
            Membership.objects.create(user=u, competition=comp, role=Role.PARTICIPANT, alias=f"{random_alias()}-{i}")
            return u

        def submit(u, preds, nb, w):
            csv = demo.csv_of(ids, "label", preds)
            sub = start_submission(u, project, {"csv": sha(csv), "notebook": sha(nb), "weights": sha(w)})
            complete_upload(sub, {"csv": upload("s.csv", csv), "notebook": upload("n.ipynb", nb), "weights": upload("m.joblib", w)})
            grade_submission(str(sub.pk))  # 트랜잭션 안이라 on_commit 대신 직접 채점
            sub.refresh_from_db()
            stored.extend([sub.csv_file, sub.notebook_file, sub.weights_file])
            return sub

        honest = []
        for label, make in HONEST_MODELS:
            m = make().fit(X, y)
            pred = m.predict(Xte)
            code = f"from {type(m).__module__.rsplit('.', 1)[0]} import {type(m).__name__}\nmodel = {m!r}"
            nb = demo.make_notebook(code, "label", [f"acc {(pred == truth).mean():.4f}"])
            honest.append({"pred": pred, "nb": nb, "w": demo.dump_weights(m), "model": label})

        results = []
        # 1) 정직한 제출
        for h in honest:
            results.append(("honest", submit(user(), h["pred"], h["nb"], h["w"]), h["model"]))
        # 2) 완전 복사: 다른 사람 CSV 그대로, 자기 노트북·가중치
        for _ in range(5):
            src, own = rng.choice(len(honest), 2, replace=False)
            results.append(("copy", submit(user(), honest[src]["pred"], honest[own]["nb"], honest[own]["w"]), f"#{src} 복사"))
        # 3) 변형 복사: 5~20% 행을 다른 값으로
        for _ in range(10):
            src, own = rng.choice(len(honest), 2, replace=False)
            pred = honest[src]["pred"].copy()
            k = int(len(pred) * rng.uniform(0.05, 0.20))
            idx = rng.choice(len(pred), k, replace=False)
            pred[idx] = (pred[idx] + rng.integers(1, 10, size=k)) % 10
            results.append(("perturb", submit(user(), pred, honest[own]["nb"], honest[own]["w"]), f"#{src} {k}행 수정"))
        # 4) 예측값 직접 기입: 노트북에 학습 코드 없이 리스트
        for _ in range(10):
            src = rng.integers(len(honest))
            pred = honest[src]["pred"]
            nb = demo.make_notebook("", "label", [], literal_preds=[int(v) for v in pred])
            results.append(("hand", submit(user(), pred, nb, honest[src]["w"]), "리스트 기입"))
        # 5) CSV만 수정: 같은 노트북·가중치로 두 번 제출, 두 번째는 오답 일부를 정답으로 고침
        for _ in range(5):
            src = rng.integers(len(honest))
            u = user()
            h = honest[src]
            submit(u, h["pred"], h["nb"], h["w"])
            pred = h["pred"].copy()
            wrong = np.flatnonzero(pred != truth)
            fix = wrong[: max(1, int(len(wrong) * 0.6))]
            pred[fix] = truth[fix]
            results.append(("edit", submit(u, pred, h["nb"], h["w"]), "CSV 수정"))

        if rerun:
            from apps.integrity.sandbox import run_rerun

            for _, sub, _ in results:
                run_rerun(str(sub.pk))

        rows = []
        for group, sub, note in results:
            rep = IntegrityReport.objects.get(submission=sub)
            flagged = [c["code"] for c in rep.checks if c["level"] in ("red", "yellow")]
            reds = [c["code"] for c in rep.checks if c["level"] == "red"]
            rows.append({"group": group, "level": rep.level, "flags": flagged, "reds": reds, "note": note, "score": sub.score})
        return rows

    # ------------------------------------------------------------------
    def _report(self, rows, opts):
        lines = [
            "# 부정 제출 탐지 실험 결과",
            "",
            f"> `python manage.py integrity_experiment{' --rerun' if opts['rerun'] else ''}` · 시드 {opts['seed']} · "
            f"{timezone.localtime():%Y-%m-%d %H:%M} · 데이터: sklearn digits (테스트 594행, 10클래스)",
            "> 실험은 하나의 트랜잭션 안에서 실행하고 롤백했다 (운영 데이터·감사 로그에 영향 없음)",
            "",
            "## 1. 그룹별 결과",
            "",
            "| 그룹 | 제출 수 | 🔴 강한 의심 | 🔴+🟡 (확인 필요) | 주로 잡은 검사 |",
            "|---|---:|---:|---:|---|",
        ]
        for label, key in GROUPS:
            g = [r for r in rows if r["group"] == key]
            if not g:
                continue
            red = sum(r["level"] == "red" for r in g)
            any_ = sum(r["level"] in ("red", "yellow") for r in g)
            codes = Counter(c for r in g for c in (r["reds"] or r["flags"]))
            top = ", ".join(f"{c} {n}건" for c, n in codes.most_common(3)) or "-"
            lines.append(f"| {label} | {len(g)} | {red} ({red / len(g):.0%}) | {any_} ({any_ / len(g):.0%}) | {top} |")
        cheat = [r for r in rows if r["group"] != "honest"]
        honest = [r for r in rows if r["group"] == "honest"]
        tp = sum(r["level"] == "red" for r in cheat)
        fp = sum(r["level"] == "red" for r in honest)
        fp_y = sum(r["level"] in ("red", "yellow") for r in honest)
        lines += [
            "",
            "## 2. 요약",
            "",
            f"- **부정 제출 탐지율 (🔴)**: {tp}/{len(cheat)} = **{tp / len(cheat):.0%}**",
            f"- **정직한 제출 오탐 (🔴)**: {fp}/{len(honest)} = **{fp / len(honest):.0%}**",
            f"- 정직한 제출 중 '확인 권장'(🟡 이상): {fp_y}/{len(honest)}",
            "",
            "## 3. 정직한 제출 상세 (서로 다른 모델 20종)",
            "",
            "| 모델 | 정확도 | 리포트 | 표시된 검사 |",
            "|---|---:|---|---|",
        ]
        for r in honest:
            mark = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(r["level"], "-")
            lines.append(f"| {r['note']} | {r['score']:.4f} | {mark} | {', '.join(r['flags']) or '-'} |")
        lines += [
            "",
            "## 4. 해석",
            "",
            "- 시스템은 🔴·🟡로 '어디를 볼지'만 알려주고 자동으로 부적합 처리하지 않는다. 최종 판단은 관리자1 → 관리자2.",
            "- 🟡는 정직한 제출에서도 나올 수 있다 (예: 비슷한 모델끼리 오답이 일부 겹침). 그래서 🟡만으로는 판정하지 않고 근거를 함께 보여준다.",
            "- I-6 격리 재실행은 비용이 커서 검토 대상에만 버튼으로 실행한다 (`--rerun` 으로 전체 측정 가능).",
            "",
        ]
        return "\n".join(lines)
