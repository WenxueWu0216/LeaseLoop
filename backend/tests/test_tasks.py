from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import Message, Prospect, Tour
from apps.integrations import tasks
from apps.integrations.ils import MockILSClient
from apps.integrations.models import LeadSourceSync
from apps.integrations.outbound import TransientDeliveryError

from .factories import PropertyFactory, ProspectFactory, TourFactory, UnitFactory

pytestmark = pytest.mark.django_db


class FlakyBackend:
    """Fails the first `failures` sends like a provider timing out."""

    failures = 0
    calls: list = []

    def send(self, request):
        FlakyBackend.calls.append(request)
        if len(FlakyBackend.calls) <= FlakyBackend.failures:
            raise TransientDeliveryError("provider timeout")


@pytest.fixture
def flaky(settings):
    settings.OUTBOUND_BACKEND = "tests.test_tasks.FlakyBackend"
    FlakyBackend.calls = []
    yield FlakyBackend
    FlakyBackend.failures = 0


def tour_in(org, delta, **kwargs):
    prospect = ProspectFactory(organization=org, phone="+12015550100")
    unit = UnitFactory(property__organization=org)
    return TourFactory(prospect=prospect, unit=unit, start=timezone.now() + delta, **kwargs)


# --- reminders ---


def test_24h_reminder_sent_once_even_if_scanner_runs_twice(org, outbox):
    tour = tour_in(org, timedelta(hours=20))
    assert tasks.send_tour_reminders.delay().get() == 1
    tasks.send_tour_reminders.delay().get()
    tasks.send_tour_reminder.delay(tour.pk, "24h").get()  # duplicate delivery of the task
    tour.refresh_from_db()
    assert tour.reminder_24h_sent_at is not None and tour.reminder_1h_sent_at is None
    assert len(outbox) == 1 and outbox[0].idempotency_key == f"tour:{tour.pk}:reminder:24h"
    msg = Message.objects.get(provider="outbox")
    assert msg.direction == "OUT" and "tomorrow" in msg.body and msg.channel == "SMS"


def test_1h_reminder_window(org, outbox):
    soon = tour_in(org, timedelta(minutes=40))
    later = tour_in(org, timedelta(hours=30))
    tasks.send_tour_reminders.delay().get()
    soon.refresh_from_db()
    later.refresh_from_db()
    assert soon.reminder_1h_sent_at and not soon.reminder_24h_sent_at
    assert not later.reminder_24h_sent_at and not later.reminder_1h_sent_at


def test_no_reminder_for_canceled_tours(org, outbox):
    tour_in(org, timedelta(hours=5), status=Tour.Status.CANCELED)
    assert tasks.send_tour_reminders.delay().get() == 0 and outbox == []


def test_transient_failures_are_retried_until_delivered(org, flaky):
    tour = tour_in(org, timedelta(hours=20))
    flaky.failures = 2
    assert tasks.send_tour_reminder.delay(tour.pk, "24h").get() is True
    assert len(flaky.calls) == 3  # 2 failures + 1 success, same idempotency key each time
    assert {c.idempotency_key for c in flaky.calls} == {f"tour:{tour.pk}:reminder:24h"}
    tour.refresh_from_db()
    assert tour.reminder_24h_sent_at is not None
    assert Message.objects.filter(provider="outbox").count() == 1


def test_gives_up_after_max_retries_without_marking_sent(org, flaky):
    tour = tour_in(org, timedelta(hours=20))
    flaky.failures = 100
    with pytest.raises(TransientDeliveryError):
        tasks.send_tour_reminder.delay(tour.pk, "24h").get()
    assert len(flaky.calls) == 1 + tasks.send_tour_reminder.max_retries
    tour.refresh_from_db()
    assert tour.reminder_24h_sent_at is None  # the next scan will try again
    assert not Message.objects.filter(provider="outbox").exists()


def test_task_retry_policy():
    for task in (
        tasks.send_tour_reminder,
        tasks.send_followup,
        tasks.sync_lead_source,
        tasks.process_inbound_event,
    ):
        assert task.retry_backoff is True and task.max_retries == 5 and task.retry_jitter


# --- follow-ups ---


def make_prospect(org, days_old, **kwargs):
    p = ProspectFactory(organization=org, phone="+12015550101", **kwargs)
    Prospect.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=days_old))
    return p


def test_stale_prospects_get_one_nudge_per_window(org, outbox, settings):
    stale = make_prospect(org, 5)
    fresh = make_prospect(org, 1)
    contacted = make_prospect(org, 5, last_contacted_at=timezone.now() - timedelta(days=1))
    ancient = make_prospect(org, 90)
    lost = make_prospect(org, 5, status=Prospect.Status.LOST)

    assert tasks.follow_up_stale_prospects.delay().get() == 1
    assert tasks.follow_up_stale_prospects.delay().get() == 0  # already nudged in this window
    stale.refresh_from_db()
    assert stale.followup_count == 1 and stale.last_followup_at is not None
    assert [r.idempotency_key for r in outbox] == [f"prospect:{stale.pk}:followup:1"]
    for p in (fresh, contacted, ancient, lost):
        p.refresh_from_db()
        assert p.followup_count == 0


def test_followups_stop_at_max(org, outbox, settings):
    settings.FOLLOWUP_MAX = 2
    p = make_prospect(org, 10)
    for _ in range(3):
        Prospect.objects.filter(pk=p.pk).update(last_followup_at=timezone.now() - timedelta(days=4))
        tasks.follow_up_stale_prospects.delay().get()
    p.refresh_from_db()
    assert p.followup_count == 2 and len(outbox) == 2


def test_followup_skips_prospect_who_replied_after_scan(org, outbox):
    p = make_prospect(org, 5)
    Prospect.objects.filter(pk=p.pk).update(last_contacted_at=timezone.now())
    assert tasks.send_followup.delay(p.pk).get() is False and outbox == []


# --- ILS sync ---


@pytest.fixture
def listings(org, other_org):
    for i in range(1, 6):
        PropertyFactory(organization=org, ils_listing_id=f"LL-1-{i}")
        PropertyFactory(organization=other_org, ils_listing_id=f"LL-2-{i}")


def test_ils_sync_upserts_leads_for_own_listings_only(org, other_org, listings):
    created = tasks.sync_lead_source.delay(org.pk, "ZILLOW").get()
    assert created > 0
    prospects = Prospect.objects.filter(organization=org, source="ZILLOW")
    assert prospects.count() == created
    assert all(p.interested_property.ils_listing_id.startswith("LL-1-") for p in prospects)
    assert Message.objects.filter(provider="ils:zillow", organization=org).count() == created
    assert not Prospect.objects.filter(organization=other_org).exists()
    assert LeadSourceSync.objects.get(organization=org, source="ZILLOW").cursor


def test_ils_sync_is_idempotent_across_runs_and_cursor_resets(org, listings):
    first = tasks.sync_lead_source.delay(org.pk, "ZILLOW").get()
    assert tasks.sync_lead_source.delay(org.pk, "ZILLOW").get() == 0  # cursor: nothing new
    LeadSourceSync.objects.update(cursor="")  # replay the whole feed
    assert tasks.sync_lead_source.delay(org.pk, "ZILLOW").get() == 0  # upsert: no duplicates
    assert Prospect.objects.filter(source="ZILLOW").count() == first


def test_ils_sync_retries_flaky_feed(org, listings):
    MockILSClient.fail_next = 2
    try:
        assert tasks.sync_lead_source.delay(org.pk, "APARTMENTS_COM").get() > 0
    finally:
        MockILSClient.fail_next = 0
    assert LeadSourceSync.objects.get(source="APARTMENTS_COM").last_error == ""


def test_sync_all_fans_out_per_org_and_source(org, other_org, listings):
    assert tasks.sync_all_lead_sources.delay().get() == 4


def test_beat_schedule_points_at_registered_tasks():
    from django.conf import settings

    from config.celery import app

    app.loader.import_default_modules()
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in app.tasks
