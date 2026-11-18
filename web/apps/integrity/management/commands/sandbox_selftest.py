"""
샌드박스 보안 자가 진단 (TC-S01~S04)

악성 노트북을 실제로 샌드박스에서 실행해, 각 공격이 막히는지 확인한다.
    python manage.py sandbox_selftest
"""

import shutil
import uuid
from pathlib import Path

import nbformat
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.integrity.sandbox import run_container

ATTACKS = [
    ("S01", "정답 파일 읽기", """
import os, glob
found = [p for p in glob.glob('/data/**', recursive=True)] + glob.glob('/work/**/*label*', recursive=True)
print('RESULT S01', 'ALLOWED' if found else 'BLOCKED', found[:3])
"""),
    ("S02", "비밀키·환경 변수 탈취", """
import os
leaked = [k for k in os.environ if any(s in k.upper() for s in ('SECRET', 'PASSWORD', 'TOKEN', 'POSTGRES', 'REDIS', 'DJANGO'))]
print('RESULT S02', 'ALLOWED' if leaked else 'BLOCKED', leaked)
"""),
    ("S03", "외부·내부 네트워크 접속", """
import socket
ok = []
for host, port in [('8.8.8.8', 53), ('db', 5432), ('redis', 6379), ('host.docker.internal', 8000)]:
    try:
        s = socket.create_connection((host, port), timeout=2); s.close(); ok.append(host)
    except Exception:
        pass
print('RESULT S03', 'ALLOWED' if ok else 'BLOCKED', ok)
"""),
    ("S03b", "시스템 파일 변조", """
try:
    open('/usr/local/lib/pwned.txt', 'w').write('x')
    print('RESULT S03b ALLOWED')
except OSError as e:
    print('RESULT S03b BLOCKED', type(e).__name__)
"""),
    ("S04", "프로세스 폭탄", """
import subprocess
procs = []
try:
    for _ in range(1000):
        procs.append(subprocess.Popen(['sleep', '30']))
    print('RESULT S04 ALLOWED', len(procs))
except Exception as e:
    print('RESULT S04 BLOCKED', type(e).__name__, len(procs))
finally:
    for p in procs: p.kill()
"""),
    ("S04b", "메모리 폭탄", """
try:
    blob = bytearray(6 * 1024 ** 3)
    print('RESULT S04b ALLOWED')
except MemoryError:
    print('RESULT S04b BLOCKED MemoryError')
"""),
]


class Command(BaseCommand):
    help = "악성 노트북으로 샌드박스 격리를 자가 진단합니다"

    def handle(self, *args, **options):
        nb = nbformat.v4.new_notebook()
        nb.cells = [nbformat.v4.new_code_cell(code.strip(), metadata={"tags": ["inference"]}) for _, _, code in ATTACKS]
        work = Path(settings.SANDBOX_WORK_ROOT) / uuid.uuid4().hex
        (work / "input").mkdir(parents=True)
        (work / "output").mkdir()
        (work / "output").chmod(0o777)
        nbformat.write(nb, work / "input" / "notebook.ipynb")
        try:
            self.stdout.write("악성 노트북을 샌드박스에서 실행합니다 …")
            run = run_container(work, "weights.bin")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if run.get("unavailable"):
            self.stdout.write(self.style.ERROR(run["log"]))
            return
        log = run["log"]
        results = {}
        for line in log.splitlines():
            if "RESULT " in line:
                parts = line.split("RESULT ", 1)[1].split()
                results[parts[0]] = parts[1]
        oom = run.get("oom")
        passed = 0
        for code, title, _ in ATTACKS:
            verdict = results.get(code)
            if verdict is None and code == "S04b" and (oom or "커널" in log or "Dead" in log or "실행 실패" in log):
                verdict = "BLOCKED"  # 메모리 제한으로 커널이 강제 종료됨
            ok = verdict == "BLOCKED"
            passed += ok
            mark = self.style.SUCCESS("BLOCKED ✓") if ok else self.style.ERROR(f"{verdict or '결과 없음'} ✕")
            self.stdout.write(f"  {code:5} {title:<20} {mark}")
        self.stdout.write(f"\n{passed}/{len(ATTACKS)} 공격 차단 · {run['duration']}초")
