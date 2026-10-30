from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.crm.models import Channel, Conversation, Message, Prospect, Tour
from apps.properties.models import Property

from . import outbound
from .ils import MockILSClient
from .models import LeadSourceSync, WebhookEvent
from .parsers import PARSERS, InboundMessage


def record_event(provider: str, event_id: str, payload: dict) -> tuple[WebhookEvent, bool]:
    """Insert the delivery into the idempotency ledger. Returns (event, created).

    Relies on the unique (provider, event_id) constraint rather than a read-then-
    write check, so two concurrent deliveries of the same message can't both win.
    """
    try:
        with transaction.atomic():
            return WebhookEvent.objects.create(
                provider=provider, event_id=event_id, payload=payload
            ), True
    except IntegrityError:
        return WebhookEvent.objects.get(provider=provider, event_id=event_id), False


def route(inbound: InboundMessage) -> Property | None:
    if inbound.channel == Channel.SMS:
        return Property.objects.filter(sms_number=inbound.recipients[0]).first()
    lowered = [r.lower() for r in inbound.recipients]
    return Property.objects.filter(inbound_email__in=lowered).first()


def find_or_create_prospect(prop: Property, inbound: InboundMessage) -> Prospect:
    contact = (
        Q(email=inbound.sender_email) if inbound.sender_email else Q(phone=inbound.sender_phone)
    )
    existing = (
        Prospect.objects.filter(organization_id=prop.organization_id)
        .filter(contact)
        .order_by("-created_at")
        .first()
    )
    if existing:
        return existing
    first, _, last = inbound.sender_name.partition(" ")
    return Prospect.objects.create(
        organization_id=prop.organization_id,
        first_name=first[:100],
        last_name=last[:100],
        email=inbound.sender_email,
        phone=inbound.sender_phone,
        source=Prospect.Source.SMS if inbound.channel == Channel.SMS else Prospect.Source.EMAIL,
        interested_property=prop,
    )


def process_event(event_id: int) -> WebhookEvent:
    """Turn a recorded webhook into prospect/conversation/message rows. Safe to re-run."""
    with transaction.atomic():
        # Row lock serializes concurrent workers handling the same event.
        event = WebhookEvent.objects.select_for_update().get(pk=event_id)
        if event.status in (WebhookEvent.Status.PROCESSED, WebhookEvent.Status.IGNORED):
            return event
        event.attempts += 1
        inbound = PARSERS[event.provider](event.payload)
        prop = route(inbound)
        if prop is None or not (inbound.sender_email or inbound.sender_phone):
            event.status = WebhookEvent.Status.IGNORED
            event.error = "no property matches recipient" if prop is None else "no sender"
            event.save(update_fields=["status", "error", "attempts", "updated_at"])
            return event

        prospect = find_or_create_prospect(prop, inbound)
        conversation, _ = Conversation.objects.get_or_create(
            prospect=prospect,
            channel=inbound.channel,
            defaults={"organization_id": prop.organization_id, "subject": inbound.subject},
        )
        now = timezone.now()
        Message.objects.get_or_create(
            provider=event.provider,
            provider_message_id=event.event_id,
            defaults={
                "organization_id": prop.organization_id,
                "conversation": conversation,
                "direction": Message.Direction.INBOUND,
                "channel": inbound.channel,
                "body": inbound.body or "(empty message)",
                "sent_at": now,
            },
        )
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now, is_unread=True)
        event.status = WebhookEvent.Status.PROCESSED
        event.organization_id = prop.organization_id
        event.processed_at = now
        event.error = ""
        event.save()
        return event


# --- tour reminders ---------------------------------------------------------

REMINDER_FIELDS = {"24h": "reminder_24h_sent_at", "1h": "reminder_1h_sent_at"}


def due_reminder_ids(kind: str, now: datetime | None = None) -> list[int]:
    now = now or timezone.now()
    window = (
        (now + timedelta(hours=1), now + timedelta(hours=24))
        if kind == "24h"
        else (now, now + timedelta(hours=1))
    )
    return list(
        Tour.objects.filter(
            status=Tour.Status.SCHEDULED,
            start__gt=window[0],
            start__lte=window[1],
            **{f"{REMINDER_FIELDS[kind]}__isnull": True},
        ).values_list("id", flat=True)
    )


def send_tour_reminder(tour_id: int, kind: str) -> bool:
    """Send one reminder at most once. Returns True if this call sent it."""
    field = REMINDER_FIELDS[kind]
    with transaction.atomic():
        tour = (
            Tour.objects.select_for_update(of=("self",))
            .select_related("prospect", "unit__property")
            .get(pk=tour_id)
        )
        if getattr(tour, field) is not None or tour.status != Tour.Status.SCHEDULED:
            return False
        local = tour.start.astimezone(ZoneInfo(tour.unit.property.timezone))
        when = "tomorrow" if kind == "24h" else "in about an hour"
        body = (
            f"Reminder: your tour of {tour.unit.property.name}, unit {tour.unit.number}, is {when} "
            f"at {local:%-I:%M %p} ({local:%a %b %-d}). Reply C to cancel."
        )
        outbound.send_to_prospect(tour.prospect, body, f"tour:{tour.pk}:reminder:{kind}")
        setattr(tour, field, timezone.now())
        tour.save(update_fields=[field, "updated_at"])
        return True


# --- stale prospect follow-ups ----------------------------------------------


def stale_prospects_q(now: datetime) -> Q:
    quiet_since = now - timedelta(days=settings.FOLLOWUP_AFTER_DAYS)
    return (
        Q(status__in=[Prospect.Status.NEW, Prospect.Status.CONTACTED])
        & Q(created_at__gte=now - timedelta(days=settings.FOLLOWUP_MAX_AGE_DAYS))
        & Q(created_at__lte=quiet_since)
        & (Q(last_contacted_at__isnull=True) | Q(last_contacted_at__lte=quiet_since))
        & (Q(last_followup_at__isnull=True) | Q(last_followup_at__lte=quiet_since))
        & Q(followup_count__lt=settings.FOLLOWUP_MAX)
    )


def stale_prospect_ids(now: datetime | None = None) -> list[int]:
    now = now or timezone.now()
    qs = Prospect.objects.filter(stale_prospects_q(now)).order_by("created_at")
    return list(qs.values_list("id", flat=True)[: settings.FOLLOWUP_BATCH])


def send_followup(prospect_id: int) -> bool:
    now = timezone.now()
    with transaction.atomic():
        prospect = Prospect.objects.select_for_update().filter(pk=prospect_id).first()
        # Re-check under the lock: the prospect may have replied, been followed up by a
        # duplicate task, or changed status since the scan enqueued it.
        if (
            prospect is None
            or not Prospect.objects.filter(pk=prospect_id).filter(stale_prospects_q(now)).exists()
        ):
            return False
        n = prospect.followup_count + 1
        name = prospect.first_name or "there"
        body = (
            f"Hi {name}, just checking in: are you still looking for an apartment? "
            "Reply with a day that works and we'll set up a tour."
        )
        outbound.send_to_prospect(prospect, body, f"prospect:{prospect.pk}:followup:{n}")
        prospect.followup_count = n
        prospect.last_followup_at = now
        prospect.save(update_fields=["followup_count", "last_followup_at", "updated_at"])
        return True


# --- ILS lead sync -----------------------------------------------------------


def sync_lead_source(org_id: int, source: str, client: MockILSClient | None = None) -> int:
    """Pull new leads since the stored cursor and upsert them. Returns leads created."""
    client = client or MockILSClient(source)
    listings = {
        p.ils_listing_id: p
        for p in Property.objects.filter(organization_id=org_id).exclude(ils_listing_id="")
    }
    if not listings:
        return 0
    created = 0
    with transaction.atomic():
        state, _ = LeadSourceSync.objects.select_for_update().get_or_create(
            organization_id=org_id, source=source
        )
        leads, cursor = client.fetch(set(listings), state.cursor)
        for lead in leads:
            prop = listings[lead.listing_id]
            prospect, was_created = Prospect.objects.get_or_create(
                organization_id=org_id,
                source=source,
                external_id=lead.external_id,
                defaults={
                    "first_name": lead.first_name,
                    "last_name": lead.last_name,
                    "email": lead.email,
                    "phone": lead.phone,
                    "interested_property": prop,
                    "desired_move_in": parse_date(lead.move_in) if lead.move_in else None,
                },
            )
            if was_created and lead.message:
                created += 1
                sent = parse_datetime(lead.created_at) or timezone.now()
                conversation, _ = Conversation.objects.get_or_create(
                    prospect=prospect,
                    channel=Channel.EMAIL,
                    defaults={"organization_id": org_id, "subject": f"{source} inquiry"},
                )
                Message.objects.get_or_create(
                    provider=f"ils:{source.lower()}",
                    provider_message_id=lead.external_id,
                    defaults={
                        "organization_id": org_id,
                        "conversation": conversation,
                        "direction": Message.Direction.INBOUND,
                        "channel": Channel.EMAIL,
                        "body": lead.message,
                        "sent_at": sent,
                    },
                )
                Conversation.objects.filter(pk=conversation.pk).update(last_message_at=sent)
            elif was_created:
                created += 1
        state.cursor = cursor
        state.last_synced_at = timezone.now()
        state.last_error = ""
        state.save()
    return created
