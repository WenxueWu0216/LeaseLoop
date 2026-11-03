"""Outbound email/SMS delivery behind a swappable backend.

Every send carries a deterministic idempotency key. Real providers accept such a
key (SendGrid custom args / Twilio idempotency token), so a task retried after a
successful send but a failed commit does not message the renter twice.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.crm.models import Channel, Conversation, Message, Prospect

logger = logging.getLogger(__name__)


class TransientDeliveryError(Exception):
    """Provider timeout/5xx: safe to retry."""


@dataclass
class OutboundRequest:
    to: str
    channel: str
    body: str
    idempotency_key: str


class LogBackend:
    """Dev/test backend: records what would be sent."""

    sent: list[OutboundRequest] = []

    def send(self, request: OutboundRequest) -> None:
        self.sent.append(request)
        logger.info(
            "outbound %s to %s key=%s", request.channel, request.to, request.idempotency_key
        )


def get_backend():
    return import_string(settings.OUTBOUND_BACKEND)()


def preferred_channel(prospect: Prospect) -> str | None:
    if prospect.phone:
        return Channel.SMS
    if prospect.email:
        return Channel.EMAIL
    return None


def send_to_prospect(prospect: Prospect, body: str, idempotency_key: str) -> Message | None:
    """Deliver and record one outbound message. Call inside the caller's transaction."""
    channel = preferred_channel(prospect)
    if channel is None:
        return None
    to = prospect.phone if channel == Channel.SMS else prospect.email
    get_backend().send(
        OutboundRequest(to=to, channel=channel, body=body, idempotency_key=idempotency_key)
    )
    conversation, _ = Conversation.objects.get_or_create(
        prospect=prospect, channel=channel, defaults={"organization_id": prospect.organization_id}
    )
    now = timezone.now()
    try:
        with transaction.atomic():
            message = Message.objects.create(
                organization_id=prospect.organization_id,
                conversation=conversation,
                direction=Message.Direction.OUTBOUND,
                channel=channel,
                body=body,
                provider="outbox",
                provider_message_id=idempotency_key,
                sent_at=now,
            )
    except IntegrityError:
        return Message.objects.get(provider="outbox", provider_message_id=idempotency_key)
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now)
    return message
