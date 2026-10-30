import json
from pathlib import Path

import pytest

from apps.crm.models import Conversation, Message, Prospect
from apps.integrations.models import WebhookEvent
from apps.integrations.services import process_event, record_event
from apps.integrations.signatures import twilio_signature

from .factories import PropertyFactory, ProspectFactory

pytestmark = pytest.mark.django_db

SAMPLES = Path(__file__).resolve().parents[1] / "apps/integrations/sample_payloads"
SG_URL = "/api/webhooks/sendgrid/inbound/?token=sg-secret"
TW_URL = "/api/webhooks/twilio/sms/"


def sample(name):
    data = json.loads((SAMPLES / name).read_text())
    data.pop("_comment")
    return data


@pytest.fixture(autouse=True)
def webhook_settings(settings):
    settings.SENDGRID_INBOUND_TOKEN = "sg-secret"
    settings.TWILIO_AUTH_TOKEN = "tw-secret"


@pytest.fixture
def prop(org):
    return PropertyFactory(
        organization=org,
        inbound_email="leasing-1-1@inbound.leaseloop.dev",
        sms_number="+15550010001",
    )


def post_sendgrid(client, payload, capture):
    with capture(execute=True):
        return client.post(SG_URL, payload)  # multipart, like SendGrid


def post_twilio(client, payload, capture, signature=None):
    url = f"http://testserver{TW_URL}"
    sig = signature or twilio_signature("tw-secret", url, payload)
    with capture(execute=True):
        return client.post(TW_URL, payload, HTTP_X_TWILIO_SIGNATURE=sig)


def test_sendgrid_creates_prospect_conversation_and_message(
    client, prop, django_capture_on_commit_callbacks
):
    resp = post_sendgrid(
        client, sample("sendgrid_inbound.json"), django_capture_on_commit_callbacks
    )
    assert resp.status_code == 200 and resp.json()["status"] == "accepted"

    prospect = Prospect.objects.get()
    assert prospect.organization_id == prop.organization_id
    assert (prospect.first_name, prospect.last_name) == ("Jane", "Rivera")
    assert prospect.email == "jane.rivera@example.com" and prospect.source == "EMAIL"
    assert prospect.interested_property == prop
    message = Message.objects.get()
    assert message.direction == "IN" and "small dog" in message.body
    assert message.provider_message_id == "<CAF8x9-renter-0001@mail.gmail.com>"
    conv = message.conversation
    assert conv.is_unread and conv.last_message_at is not None
    event = WebhookEvent.objects.get()
    assert event.status == "PROCESSED" and event.organization_id == prop.organization_id


def test_duplicate_sendgrid_delivery_is_a_no_op(client, prop, django_capture_on_commit_callbacks):
    payload = sample("sendgrid_inbound.json")
    first = post_sendgrid(client, payload, django_capture_on_commit_callbacks)
    second = post_sendgrid(client, payload, django_capture_on_commit_callbacks)
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert (
        Prospect.objects.count(),
        Conversation.objects.count(),
        Message.objects.count(),
        WebhookEvent.objects.count(),
    ) == (1, 1, 1, 1)


def test_duplicate_twilio_delivery_is_a_no_op(client, prop, django_capture_on_commit_callbacks):
    payload = sample("twilio_sms.json")
    for expected in ("accepted", "duplicate", "duplicate"):
        resp = post_twilio(client, payload, django_capture_on_commit_callbacks)
        assert resp.status_code == 200 and resp.json()["status"] == expected
    prospect = Prospect.objects.get()
    assert prospect.phone == "+12015550123" and prospect.source == "SMS"
    assert Message.objects.get().channel == "SMS"


def test_bad_credentials_are_rejected_and_not_recorded(
    client, prop, django_capture_on_commit_callbacks
):
    resp = client.post(
        "/api/webhooks/sendgrid/inbound/?token=wrong", sample("sendgrid_inbound.json")
    )
    assert resp.status_code == 403
    resp = post_twilio(
        client, sample("twilio_sms.json"), django_capture_on_commit_callbacks, signature="forged"
    )
    assert resp.status_code == 403
    tampered = {**sample("twilio_sms.json")}
    sig = twilio_signature("tw-secret", f"http://testserver{TW_URL}", tampered)
    tampered["Body"] = "changed after signing"
    assert (
        post_twilio(client, tampered, django_capture_on_commit_callbacks, signature=sig).status_code
        == 403
    )
    assert WebhookEvent.objects.count() == 0 and Prospect.objects.count() == 0


def test_sendgrid_rejected_when_token_not_configured(client, prop, settings):
    settings.SENDGRID_INBOUND_TOKEN = ""
    resp = client.post("/api/webhooks/sendgrid/inbound/?token=", sample("sendgrid_inbound.json"))
    assert resp.status_code == 403


def test_inbound_matches_existing_prospect(client, prop, django_capture_on_commit_callbacks):
    existing = ProspectFactory(organization=prop.organization, email="jane.rivera@example.com")
    post_sendgrid(client, sample("sendgrid_inbound.json"), django_capture_on_commit_callbacks)
    assert Prospect.objects.get() == existing
    assert Message.objects.get().conversation.prospect == existing


def test_same_email_in_other_org_is_not_matched(
    client, prop, other_org, django_capture_on_commit_callbacks
):
    ProspectFactory(organization=other_org, email="jane.rivera@example.com")
    post_sendgrid(client, sample("sendgrid_inbound.json"), django_capture_on_commit_callbacks)
    assert Prospect.objects.filter(organization=prop.organization).count() == 1


def test_unknown_recipient_is_ignored_not_retried(client, org, django_capture_on_commit_callbacks):
    resp = post_sendgrid(
        client, sample("sendgrid_inbound.json"), django_capture_on_commit_callbacks
    )
    assert resp.status_code == 200  # 2xx so the provider stops retrying
    event = WebhookEvent.objects.get()
    assert event.status == "IGNORED" and "no property" in event.error
    assert Prospect.objects.count() == 0


def test_missing_message_id_falls_back_to_content_hash(
    client, prop, django_capture_on_commit_callbacks
):
    payload = sample("sendgrid_inbound.json")
    payload["headers"] = "From: Jane Rivera <jane.rivera@example.com>"
    post_sendgrid(client, payload, django_capture_on_commit_callbacks)
    resp = post_sendgrid(client, payload, django_capture_on_commit_callbacks)
    assert resp.json()["status"] == "duplicate"
    assert WebhookEvent.objects.get().event_id.startswith("sha256:")


def test_reprocessing_a_processed_event_changes_nothing(prop):
    """Celery may deliver the same task twice (acks_late, worker crash)."""
    event, created = record_event("twilio", "SM-redelivered", sample("twilio_sms.json"))
    assert created
    process_event(event.pk)
    process_event(event.pk)
    assert Message.objects.count() == 1
    event.refresh_from_db()
    assert event.attempts == 1


def test_ledger_insert_is_idempotent(prop):
    first, created1 = record_event("twilio", "SM-1", {"Body": "a"})
    again, created2 = record_event("twilio", "SM-1", {"Body": "a"})
    assert created1 and not created2 and first.pk == again.pk
