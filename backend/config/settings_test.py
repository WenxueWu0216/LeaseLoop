from .settings import *  # noqa: F403

# Run Celery tasks inline so tests exercise retries/idempotency without a broker.
# Propagation stays off: with it on, an eager autoretry raises celery's Retry instead
# of re-applying the task. Tests call .get(), which re-raises the final failure.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
