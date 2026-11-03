import hmac
import logging

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WebhookEvent
from .parsers import sendgrid_event_id
from .services import record_event
from .signatures import valid_twilio_signature
from .tasks import process_inbound_event

logger = logging.getLogger(__name__)


def flat(querydict) -> dict[str, str]:
    """Form payload as plain {key: value}; attachments are not stored."""
    return {k: querydict.get(k) for k in querydict}


class WebhookView(APIView):
    """Verify, record, enqueue, answer 200 fast. Processing happens in Celery.

    Providers retry on non-2xx or timeouts, so the handler does the minimum
    synchronously and lets the idempotency ledger absorb the retries.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, MultiPartParser]
    provider: str

    def verify(self, request, payload) -> bool:
        raise NotImplementedError

    def event_id(self, payload) -> str:
        raise NotImplementedError

    def accepted(self, event: WebhookEvent, created: bool) -> Response:
        return Response({"status": "accepted" if created else "duplicate", "event": event.pk})

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        payload = flat(request.data)
        if not self.verify(request, payload):
            logger.warning("rejected %s webhook: bad signature/token", self.provider)
            return Response({"detail": "invalid signature"}, status=403)
        event_id = self.event_id(payload)
        if not event_id:
            return Response({"detail": "missing message id"}, status=400)
        event, created = record_event(self.provider, event_id, payload)
        if created:
            # Enqueue only after the ledger row is committed, or a fast worker
            # could look for an event that isn't visible yet.
            transaction.on_commit(lambda: process_inbound_event.delay(event.pk))
        return self.accepted(event, created)


class SendGridInboundView(WebhookView):
    """SendGrid Inbound Parse (multipart). Unsigned by SendGrid, so the URL carries a secret."""

    provider = WebhookEvent.Provider.SENDGRID
    parser_classes = [MultiPartParser, FormParser]

    def verify(self, request, payload) -> bool:
        expected = settings.SENDGRID_INBOUND_TOKEN
        given = request.query_params.get("token", "")
        return bool(expected) and hmac.compare_digest(expected, given)

    def event_id(self, payload) -> str:
        return sendgrid_event_id(payload)


class TwilioInboundView(WebhookView):
    provider = WebhookEvent.Provider.TWILIO

    def verify(self, request, payload) -> bool:
        base = settings.WEBHOOK_PUBLIC_BASE_URL
        url = (
            f"{base.rstrip('/')}{request.get_full_path()}" if base else request.build_absolute_uri()
        )
        return valid_twilio_signature(
            settings.TWILIO_AUTH_TOKEN, url, payload, request.headers.get("X-Twilio-Signature", "")
        )

    def event_id(self, payload) -> str:
        return payload.get("MessageSid", "")
