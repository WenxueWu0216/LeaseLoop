import os

# Set before importing settings, which refuse to load with DEBUG off and no real key.
# A full-length key also keeps JWT HMAC signing at a realistic key size.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-" + "k" * 54)

from .settings import *  # noqa: E402, F403

# Tests talk plain HTTP; the HTTPS redirect is tested explicitly with override_settings.
SECURE_SSL_REDIRECT = False

# Run Celery tasks inline so tests exercise retries/idempotency without a broker.
# Propagation stays off: with it on, an eager autoretry raises celery's Retry instead
# of re-applying the task. Tests call .get(), which re-raises the final failure.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
