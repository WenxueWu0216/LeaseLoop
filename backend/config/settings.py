import os
from pathlib import Path

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.properties",
    "apps.crm",
    "apps.integrations",
    "apps.assistant",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestMetricsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "leaseloop"),
        "USER": env("POSTGRES_USER", "leaseloop"),
        "PASSWORD": env("POSTGRES_PASSWORD", "leaseloop"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"assistant_chat": env("ASSISTANT_CHAT_RATE", "30/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LeaseLoop API",
    "DESCRIPTION": "Multi-tenant apartment leasing CRM",
    "VERSION": "0.1.0",
    "ENUM_NAME_OVERRIDES": {
        "ProspectStatusEnum": "apps.crm.models.Prospect.Status",
        "TourStatusEnum": "apps.crm.models.Tour.Status",
        "ApplicationStatusEnum": "apps.crm.models.Application.Status",
        "LeaseStatusEnum": "apps.crm.models.Lease.Status",
        "RenewalStatusEnum": "apps.crm.models.Renewal.Status",
        "HandoffStatusEnum": "apps.crm.models.HandoffTask.Status",
        "UnitStatusEnum": "apps.properties.models.Unit.Status",
    },
}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_ACKS_LATE = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BEAT_SCHEDULE = {
    "tour-reminders": {
        "task": "apps.integrations.tasks.send_tour_reminders",
        "schedule": 300.0,
    },
    "stale-prospect-followups": {
        "task": "apps.integrations.tasks.follow_up_stale_prospects",
        "schedule": crontab(minute=7),
    },
    "ils-lead-sync": {
        "task": "apps.integrations.tasks.sync_all_lead_sources",
        "schedule": 900.0,
    },
}

# Webhooks and outbound messaging
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
SENDGRID_INBOUND_TOKEN = env("SENDGRID_INBOUND_TOKEN")
# Public URL Twilio calls (signatures cover the exact URL); defaults to the request's own.
WEBHOOK_PUBLIC_BASE_URL = env("WEBHOOK_PUBLIC_BASE_URL")
OUTBOUND_BACKEND = env("OUTBOUND_BACKEND", "apps.integrations.outbound.LogBackend")
ILS_FEED_DIR = env("ILS_FEED_DIR", str(BASE_DIR / "apps" / "integrations" / "sample_payloads"))
FOLLOWUP_AFTER_DAYS = int(env("FOLLOWUP_AFTER_DAYS", "3"))
FOLLOWUP_MAX_AGE_DAYS = int(env("FOLLOWUP_MAX_AGE_DAYS", "30"))
FOLLOWUP_MAX = int(env("FOLLOWUP_MAX", "2"))
FOLLOWUP_BATCH = int(env("FOLLOWUP_BATCH", "500"))

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
LLM_PROVIDER = env("LLM_PROVIDER", "mock")  # mock | anthropic
LLM_MODEL = env("LLM_MODEL", "claude-opus-5-5")
LLM_EFFORT = env("LLM_EFFORT", "medium")
# Below this cosine similarity, retrieval alone doesn't count as grounding (the answer
# then needs a tool result or it is handed off). 0.20 sits above every unanswerable
# question in evals/dev_questions.jsonl for the hashing embedder; see docs/assistant.md.
ASSISTANT_MIN_RETRIEVAL_SCORE = float(env("ASSISTANT_MIN_RETRIEVAL_SCORE", "0.20"))

# Requests slower than this, or with more queries than this, are logged at WARNING.
SLOW_REQUEST_MS = int(env("SLOW_REQUEST_MS", "500"))
MAX_QUERIES_PER_REQUEST = int(env("MAX_QUERIES_PER_REQUEST", "30"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "leaseloop.request": {
            "handlers": ["console"],
            "level": env("REQUEST_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
