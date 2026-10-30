from celery import shared_task
from django.db import OperationalError

from apps.properties.models import PropertyPolicy

from .retrieval import index_policy


@shared_task(
    autoretry_for=(OperationalError,), retry_backoff=True, retry_jitter=True, max_retries=5
)
def reindex_policy(policy_id: int) -> int:
    policy = PropertyPolicy.objects.filter(pk=policy_id).first()
    return index_policy(policy) if policy else 0
