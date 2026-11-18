"""
부하 테스트용 참여자 계정 생성 (DEMO_MODE 전용)

    python manage.py loadtest_users --count 50
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.competitions.models import Competition, Membership, Role, random_alias

from .seed_demo import DEMO_DOMAIN, DEMO_PASSWORD


class Command(BaseCommand):
    help = "부하 테스트용 참여자 계정을 만듭니다"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=50)

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE=true 일 때만 실행할 수 있습니다")
        comp = Competition.objects.get(title="2026-2 머신러닝 기말 프로젝트")
        created = 0
        for i in range(options["count"]):
            email = f"load{i:03d}@{DEMO_DOMAIN}"
            user, new = User.objects.get_or_create(email=email, defaults={"name": f"부하{i:03d}"})
            if new:
                user.set_password(DEMO_PASSWORD)
                user.save()
                created += 1
            Membership.objects.get_or_create(user=user, competition=comp,
                                             defaults={"role": Role.PARTICIPANT, "alias": f"{random_alias()}-{i}"})
        self.stdout.write(f"부하 테스트 계정 {options['count']}개 준비 (새로 만든 계정 {created}개)")
