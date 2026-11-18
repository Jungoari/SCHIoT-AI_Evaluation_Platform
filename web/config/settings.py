"""
프로젝트 설정

- 모든 비밀값·환경별 값은 환경 변수(.env)에서 읽는다 (하드코딩 금지 — 행안부 가이드 '하드코드된 중요정보')
- 운영 환경 기본값은 '안전한 쪽'으로 둔다 (DEBUG=False, 보안 쿠키 등)
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"환경 변수 {name} 가 설정되지 않았습니다")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    return int(env(name, str(default)))


# ---------------------------------------------------------------------------
# 기본
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# 데모 모드: 시연용 시드 데이터·GIF 녹화용 오버레이 허용 (운영에서는 반드시 False)
DEMO_MODE = env_bool("DEMO_MODE", False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "axes",
    "django_rq",
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.competitions",
    "apps.submissions",
    "apps.grading",
    "apps.leaderboard",
    "apps.review",
    "apps.integrity",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    # axes 는 인증 관련 미들웨어 뒤에 위치해야 함
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# 데이터베이스 (PostgreSQL — 행 잠금으로 제출 횟수 경쟁 조건을 막기 위해 필수)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "evalplatform"),
        "USER": env("POSTGRES_USER", "evalplatform"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

# ---------------------------------------------------------------------------
# 인증 · 비밀번호 (Argon2 해시, 비밀번호 정책)
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # 로그인 실패 횟수 제한
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# 로그인 무차별 대입 방지 (행안부 가이드 '반복된 인증시도 제한 기능 부재')
AXES_FAILURE_LIMIT = env_int("AXES_FAILURE_LIMIT", 10)
AXES_COOLOFF_TIME = 0.25  # 시간 단위 (15분)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked.html"

# ---------------------------------------------------------------------------
# 세션 · 쿠키
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8시간
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_COOKIES = env_bool("SECURE_COOKIES", not DEBUG)
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if env_bool("SECURE_HSTS", False):
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# 국제화
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# 정적 파일
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# 파일 저장소 (웹 루트 밖, UUID 파일명)
#  - UPLOAD_ROOT: 참여자 제출물, 데이터셋 배포본
#  - LABEL_ROOT : 정답 파일. 채점 워커와 웹만 접근, 샌드박스에는 절대 마운트하지 않음
# ---------------------------------------------------------------------------
DATA_ROOT = Path(env("DATA_ROOT", str(BASE_DIR.parent / "var")))
UPLOAD_ROOT = DATA_ROOT / "uploads"
LABEL_ROOT = DATA_ROOT / "labels"
SANDBOX_WORK_ROOT = DATA_ROOT / "sandbox"

# 업로드 크기 상한 (바이트)
MAX_CSV_BYTES = env_int("MAX_CSV_BYTES", 20 * 1024 * 1024)
MAX_NOTEBOOK_BYTES = env_int("MAX_NOTEBOOK_BYTES", 30 * 1024 * 1024)
MAX_WEIGHTS_BYTES = env_int("MAX_WEIGHTS_BYTES", 500 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 이보다 크면 임시 파일로 스트리밍

# 마감 후 업로드 완료까지 허용하는 기본 유예 시간 (분)
DEFAULT_GRACE_MINUTES = env_int("DEFAULT_GRACE_MINUTES", 30)

# ---------------------------------------------------------------------------
# 작업 큐 (Redis + RQ)
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
RQ_QUEUES = {
    "grading": {"URL": REDIS_URL, "DEFAULT_TIMEOUT": 300},
    "sandbox": {"URL": REDIS_URL, "DEFAULT_TIMEOUT": 900},
}
# 테스트 환경 등에서 큐 대신 즉시 실행
RQ_EAGER = env_bool("RQ_EAGER", False)

# 캐시 (실패 횟수 제한 등) — Redis 공유 캐시라 웹 프로세스가 여러 개여도 일관됨
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL", "redis://localhost:6379/1"),
    }
}

# ---------------------------------------------------------------------------
# 샌드박스 (참여자 코드 격리 실행)
# ---------------------------------------------------------------------------
SANDBOX_IMAGE = env("SANDBOX_IMAGE", "evalplatform-sandbox:latest")
SANDBOX_TIMEOUT_SECONDS = env_int("SANDBOX_TIMEOUT_SECONDS", 300)
SANDBOX_MEMORY = env("SANDBOX_MEMORY", "2g")
SANDBOX_CPUS = float(env("SANDBOX_CPUS", "1.0"))
SANDBOX_PIDS_LIMIT = env_int("SANDBOX_PIDS_LIMIT", 128)
# 워커 컨테이너 내부 경로 → 호스트 경로 변환 (Docker-out-of-Docker 볼륨 마운트용)
SANDBOX_HOST_WORK_ROOT = env("SANDBOX_HOST_WORK_ROOT", str(SANDBOX_WORK_ROOT))

# ---------------------------------------------------------------------------
# 로깅 — 비밀번호·토큰 등은 기록하지 않음, 요청 추적 ID 포함
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.core.logging.RequestIdFilter"},
        "mask_secrets": {"()": "apps.core.logging.MaskSecretsFilter"},
    },
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["request_id", "mask_secrets"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
