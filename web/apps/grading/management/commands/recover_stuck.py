"""
장애 복구: 워커가 죽어 '채점 대기/채점 중'에 멈춘 제출을 다시 대기열에 넣는다
워커 컨테이너가 시작될 때 자동 실행된다 (entrypoint.sh)
"""

from django.core.management.base import BaseCommand

from apps.grading.services import recover_stuck


class Command(BaseCommand):
    help = "멈춘 채점 작업을 다시 대기열에 넣습니다"

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=5)

    def handle(self, *args, **options):
        n = recover_stuck(options["minutes"])
        self.stdout.write(f"다시 대기열에 넣은 제출: {n}건")
