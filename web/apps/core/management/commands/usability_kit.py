"""
사용성 테스트 준비물 생성 (DEMO_MODE 전용)

    python manage.py usability_kit --out ../var/usability_kit

만드는 것
  - 데모 대회의 참여자 참여 코드 새로 발급 (기존 참여자 코드는 무효화됨 — 발급 화면 규칙과 같음)
  - 테스터에게 나눠 줄 제출 파일
      solution.ipynb / model.joblib      : 정상 노트북·가중치
      submission_wrong.csv               : 과제 2용 — 열 이름 오류 (친절한 오류 안내 확인)
      submission.csv                     : 과제 2에서 고친 뒤 다시 낼 정상 CSV
  - 진행자용 안내 README.txt (코드·과제 요약)
"""

from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler

from apps.competitions import services as comp_services
from apps.competitions.models import Competition, Role
from apps.core import demo

from .seed_demo import DEMO_DOMAIN, DEMO_PASSWORD

COMP_TITLE = "2026-2 머신러닝 기말 프로젝트"


class Command(BaseCommand):
    help = "사용성 테스트용 참여 코드와 제출 파일을 만듭니다"

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(Path(settings.BASE_DIR).parent / "var" / "usability_kit"))

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE=true 일 때만 실행할 수 있습니다")
        try:
            comp = Competition.objects.get(title=COMP_TITLE)
        except Competition.DoesNotExist as exc:
            raise CommandError("데모 대회가 없습니다. 먼저 python manage.py seed_demo 를 실행하세요") from exc

        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)

        # 1) 정상 제출물: 테스터가 만든 것처럼 간단한 로지스틱 회귀 모델 (패션 MNIST, 수업 규칙대로 5-폴드 결과 출력)
        train, test = demo.fashion_frames()
        X, y = train.drop(columns=["id", "label"]), train["label"]
        model = make_pipeline(MinMaxScaler(), LogisticRegression(C=0.1, max_iter=300))
        scores = demo.cv_scores(model, X, y, "accuracy")
        model.fit(X, y)
        pred = model.predict(test.drop(columns=["id", "label"]))
        code = ("from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import MinMaxScaler\n"
                "from sklearn.linear_model import LogisticRegression\n"
                "model = make_pipeline(MinMaxScaler(), LogisticRegression(C=0.1, max_iter=300))")
        acc = float((pred == test["label"].values).mean())

        (out / "solution.ipynb").write_bytes(demo.make_notebook(code, "label", demo.cv_log(scores, "accuracy")))
        (out / "model.joblib").write_bytes(demo.dump_weights(model))
        (out / "submission.csv").write_bytes(demo.csv_of(test["id"], "label", pred))

        # 2) 오류 CSV: 가장 흔한 실수 — 정답 열 이름을 'label' 대신 'digit' 으로 씀
        wrong = pd.DataFrame({"id": test["id"], "digit": pred})
        (out / "submission_wrong.csv").write_text(wrong.to_csv(index=False), encoding="utf-8")

        # 3) 참여 코드 새로 발급 (원문은 이 화면과 README.txt 에만 남음)
        prof = comp.created_by
        raw = comp_services.reissue_code(comp, Role.PARTICIPANT, prof)

        readme = f"""사용성 테스트 준비물 — 진행자용 (테스터에게 이 파일은 보여주지 않기)

참여 코드 (참여자용) : {raw}
  · 이 코드를 발급하면서 이전 참여자 코드는 무효화되었음
  · 테스트가 끝나면 관리자2 화면에서 다시 재발급 권장

관리자 과제용 계정
  · 관리자2 : prof@{DEMO_DOMAIN} / {DEMO_PASSWORD}
  · 관리자1 : ta@{DEMO_DOMAIN} / {DEMO_PASSWORD}

테스터에게 나눠 줄 파일
  · solution.ipynb, model.joblib       — 노트북·가중치
  · submission_wrong.csv               — 과제 2: 처음 제출할 CSV (일부러 틀린 파일)
  · submission.csv                     — 과제 2: 오류 안내를 보고 고쳐 낼 CSV
  (submission.csv 의 예상 정확도 약 {acc:.4f})

과제와 기록 방법은 docs/USABILITY_TEST.md 참고
"""
        (out / "README.txt").write_text(readme, encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"사용성 테스트 준비물 생성: {out.resolve()}"))
        self.stdout.write(f"참여자 참여 코드: {raw}")
        self.stdout.write("오류 CSV: 정답 열 이름 'label' 대신 'digit' 사용")
