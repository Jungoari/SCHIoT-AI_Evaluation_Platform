"""
데모 데이터 생성 — 심사위원이 바로 둘러볼 수 있도록 역할별 계정과 대회를 만든다

    python manage.py seed_demo            # 기존 데모 데이터를 지우고 다시 생성
    python manage.py seed_demo --if-empty # 사용자가 하나도 없을 때만 생성 (컨테이너 시작 시)

데모 계정 비밀번호는 '데모 전용' 값이며 README 에 공개되어 있다.
DEMO_MODE=false 인 운영 환경에서는 실행을 거부한다.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.competitions.models import Competition, JoinCode, Membership, Role, random_alias

DEMO_PASSWORD = "evalhub-demo-2026"  # noqa: S105 — 공개된 데모 전용 비밀번호
DEMO_DOMAIN = "demo.evalhub"

ADMIN2 = ("prof", "김교수")
ADMIN1 = [("ta", "이조교")]
STUDENTS = [
    ("student1", "박민준"), ("student2", "최서연"), ("student3", "정도윤"), ("student4", "강하은"),
    ("student5", "윤지호"), ("student6", "임수아"), ("student7", "한예준"), ("student8", "오지우"),
]


def email(local):
    return f"{local}@{DEMO_DOMAIN}"


class Command(BaseCommand):
    help = "데모용 계정·대회 데이터를 생성합니다"

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="사용자가 없을 때만 생성")

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE=true 일 때만 실행할 수 있습니다")
        if options["if_empty"] and User.objects.exists():
            self.stdout.write("이미 데이터가 있어 건너뜁니다")
            return
        with transaction.atomic():
            self._reset()
            codes = self._create()
        self._print(codes)

    def _reset(self):
        Competition.objects.filter(created_by__email__endswith=f"@{DEMO_DOMAIN}").delete()
        User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").delete()

    def _user(self, local, name, **extra):
        return User.objects.create_user(email=email(local), password=DEMO_PASSWORD, name=name, **extra)

    def _create(self):
        prof = self._user(*ADMIN2, is_admin2=True)
        tas = [self._user(*a) for a in ADMIN1]
        students = [self._user(*s, student_no=f"2022{i:04d}") for i, s in enumerate(STUDENTS, 1)]

        comp = Competition.objects.create(
            title="2026-2 머신러닝 기말 프로젝트",
            description="붓꽃·주택가격 데이터로 분류·회귀 모델을 만들고 성능을 겨룹니다",
            created_by=prof,
        )
        for ta in tas:
            Membership.objects.create(user=ta, competition=comp, role=Role.ADMIN1, alias=random_alias())
        for st in students:
            Membership.objects.create(user=st, competition=comp, role=Role.PARTICIPANT, alias=random_alias())

        _, p_code = JoinCode.issue(comp, Role.PARTICIPANT, prof)
        _, a_code = JoinCode.issue(comp, Role.ADMIN1, prof)
        return {"participant": p_code, "admin1": a_code, "competition": comp.title}

    def _print(self, codes):
        w = self.stdout.write
        w(self.style.SUCCESS("데모 데이터 생성 완료"))
        w(f"  비밀번호(공통) : {DEMO_PASSWORD}")
        w(f"  관리자2        : {email(ADMIN2[0])}")
        w(f"  관리자1        : {email(ADMIN1[0][0])}")
        w(f"  참여자         : {email('student1')} ~ {email('student8')}")
        w(f"  대회           : {codes['competition']}")
        w(f"  참여자 코드    : {codes['participant']}")
        w(f"  관리자1 코드   : {codes['admin1']}")
