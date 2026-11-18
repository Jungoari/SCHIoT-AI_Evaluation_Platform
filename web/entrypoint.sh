#!/bin/sh
# 컨테이너 시작 스크립트
#   web               : 마이그레이션 → 정적 파일 수집 → gunicorn
#   worker <queue>    : RQ 워커 (grading / sandbox)
set -e

mkdir -p /data/uploads /data/labels /data/sandbox 2>/dev/null || true

case "$1" in
  web)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput >/dev/null
    if [ "${DEMO_MODE:-false}" = "true" ]; then
      python manage.py seed_demo --if-empty || true
    fi
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120 --access-logfile -
    ;;
  worker)
    shift
    exec python manage.py rqworker "$@" --with-scheduler
    ;;
  *)
    exec "$@"
    ;;
esac
