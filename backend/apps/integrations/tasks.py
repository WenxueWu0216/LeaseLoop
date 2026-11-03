"""Celery tasks. Each one is idempotent: re-delivery or retry cannot double-send or
double-insert, because work is claimed under a row lock and every side effect is
keyed (unique constraints, deterministic idempotency keys)."""

import logging

from celery import shared_task
from django.db import OperationalError

from apps.accounts.models import Organization
from apps.crm.models import Prospect

from . import services
from .ils import ILSUnavailable
from .models import LeadSourceSync
from .outbound import TransientDeliveryError

logger = logging.getLogger(__name__)

RETRY = {
    "retry_backoff": True,  # 1s, 2s, 4s, ... with jitter
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 5,
}


@shared_task(autoretry_for=(OperationalError,), **RETRY)
def process_inbound_event(event_id: int) -> str:
    return services.process_event(event_id).status


@shared_task
def send_tour_reminders() -> int:
    queued = 0
    for kind in ("24h", "1h"):
        for tour_id in services.due_reminder_ids(kind):
            send_tour_reminder.delay(tour_id, kind)
            queued += 1
    return queued


@shared_task(autoretry_for=(TransientDeliveryError, OperationalError), **RETRY)
def send_tour_reminder(tour_id: int, kind: str) -> bool:
    return services.send_tour_reminder(tour_id, kind)


@shared_task
def follow_up_stale_prospects() -> int:
    ids = services.stale_prospect_ids()
    for prospect_id in ids:
        send_followup.delay(prospect_id)
    return len(ids)


@shared_task(autoretry_for=(TransientDeliveryError, OperationalError), **RETRY)
def send_followup(prospect_id: int) -> bool:
    return services.send_followup(prospect_id)


ILS_SOURCES = (Prospect.Source.ZILLOW, Prospect.Source.APARTMENTS_COM)


@shared_task
def sync_all_lead_sources() -> int:
    queued = 0
    for org_id in Organization.objects.values_list("id", flat=True):
        for source in ILS_SOURCES:
            sync_lead_source.delay(org_id, source)
            queued += 1
    return queued


@shared_task(bind=True, autoretry_for=(ILSUnavailable, OperationalError), **RETRY)
def sync_lead_source(self, org_id: int, source: str) -> int:
    try:
        return services.sync_lead_source(org_id, source)
    except ILSUnavailable as exc:
        LeadSourceSync.objects.filter(organization_id=org_id, source=source).update(
            last_error=f"attempt {self.request.retries + 1}: {exc}"
        )
        raise
